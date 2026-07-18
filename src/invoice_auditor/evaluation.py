"""Evaluation with explicit denominators, segments, failures, latency, and VRAM."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from invoice_auditor.models import RawInvoiceData
from invoice_auditor.normalizer import normalize_invoice

FIELDS = (
    "invoice_number",
    "vendor_name",
    "tax_id",
    "invoice_date",
    "subtotal",
    "vat",
    "total",
    "currency",
)
NUMERIC_FIELDS = ("subtotal", "vat", "total")


def read_jsonl(
    path: str | Path,
    *,
    max_bytes: int = 100 * 1024 * 1024,
    max_line_bytes: int = 1024 * 1024,
) -> tuple[list[dict[str, Any]], list[str]]:
    input_path = Path(path).expanduser().resolve(strict=True)
    if not input_path.is_file():
        raise ValueError(f"JSONL path is not a file: {input_path}")
    if input_path.stat().st_size > max_bytes:
        raise ValueError(f"JSONL input exceeds {max_bytes} byte safety limit")
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    with input_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if len(line.encode("utf-8")) > max_line_bytes:
                errors.append(f"line {line_number}: exceeds safety limit")
                continue
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: {exc.msg}")
                continue
            if not isinstance(payload, dict):
                errors.append(f"line {line_number}: expected object")
                continue
            records.append(payload)
    return records, errors


def _canonical(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().casefold()


def _numeric_match(expected: Any, observed: Any, tolerance: Decimal) -> bool:
    if expected is None or observed is None:
        return expected is observed
    try:
        return abs(Decimal(str(expected)) - Decimal(str(observed))) <= tolerance
    except InvalidOperation:
        return False


def _prediction_id(record: dict[str, Any]) -> str | None:
    direct = record.get("source_id") or record.get("image_id")
    if direct:
        return str(direct)
    report = record.get("audit_report")
    if isinstance(report, dict) and report.get("source_id"):
        return str(report["source_id"])
    return None


def _unwrap_prediction(record: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    status = str(record.get("status") or "success")
    report = record.get("audit_report") if "audit_report" in record else record
    runtime = record.get("runtime") or (
        report.get("model_trace") if isinstance(report, dict) else {}
    )
    return (
        status,
        report if isinstance(report, dict) else {},
        runtime if isinstance(runtime, dict) else {},
    )


def _segment_name(
    record: dict[str, Any],
    prediction: dict[str, Any] | None = None,
    *,
    vlm_run: bool = False,
) -> str:
    explicit = record.get("dataset_segment")
    if explicit:
        return str(explicit)
    dataset_name = str(record.get("dataset_name") or "").casefold()
    if "sroie" in dataset_name:
        return "sroie_vlm"
    _, _, runtime = _unwrap_prediction(prediction or {})
    is_vlm_prediction = vlm_run or bool(runtime.get("model_id"))
    if not is_vlm_prediction:
        return "sidecar_rule_baseline"
    variant = record.get("variant")
    if variant == "clean":
        return "synthetic_vlm_clean"
    if variant:
        return "synthetic_vlm_transformed"
    return "sidecar_rule_baseline"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 2)


def _resource_summary(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    latencies: list[float] = []
    peaks: list[float] = []
    breakdown: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"attempted": 0, "successful": 0, "failed": 0, "latency_ms": [], "peak": []}
    )
    errors: Counter[str] = Counter()
    for prediction in predictions:
        status, _, runtime = _unwrap_prediction(prediction)
        model = str(runtime.get("model_id") or "unknown")
        profile = str(runtime.get("runtime_profile") or "unknown")
        key = f"{model}|{profile}"
        bucket = breakdown[key]
        bucket["attempted"] += 1
        if status == "success":
            bucket["successful"] += 1
        else:
            bucket["failed"] += 1
            errors[str(prediction.get("error_stage") or "unknown")] += 1
        latency = runtime.get("latency_ms")
        if isinstance(latency, int | float) and latency >= 0:
            latencies.append(float(latency))
            bucket["latency_ms"].append(float(latency))
        peak = runtime.get("peak_vram_mb")
        if isinstance(peak, int | float) and peak >= 0:
            peaks.append(float(peak))
            bucket["peak"].append(float(peak))

    serialized_breakdown: dict[str, Any] = {}
    for key, bucket in sorted(breakdown.items()):
        serialized_breakdown[key] = {
            "attempted": bucket["attempted"],
            "successful": bucket["successful"],
            "failed": bucket["failed"],
            "p50_latency_ms": _percentile(bucket["latency_ms"], 0.50),
            "p95_latency_ms": _percentile(bucket["latency_ms"], 0.95),
            "peak_vram_mb_max": max(bucket["peak"], default=None),
        }
    return {
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "peak_vram_mb_max": max(peaks, default=None),
        "model_profile_breakdown": serialized_breakdown,
        "error_attribution_by_stage": dict(sorted(errors.items())),
    }


def _evaluate_core(
    ground_truth_records: list[dict[str, Any]],
    prediction_records: list[dict[str, Any]],
    *,
    invalid_prediction_lines: int,
    numeric_tolerance: Decimal,
) -> dict[str, Any]:
    truth_by_id = {str(record["image_id"]): record for record in ground_truth_records}
    prediction_by_id: dict[str, dict[str, Any]] = {}
    duplicate_predictions = 0
    for record in prediction_records:
        image_id = _prediction_id(record)
        if image_id is None:
            continue
        duplicate_predictions += int(image_id in prediction_by_id)
        prediction_by_id[image_id] = record

    field_correct = Counter({field: 0 for field in FIELDS})
    field_total = Counter({field: 0 for field in FIELDS})
    numeric_correct = numeric_total = 0
    decision_correct = decision_total = 0
    confusion: Counter[str] = Counter()
    anomaly_tp = anomaly_fp = anomaly_fn = 0
    missing_predictions: list[str] = []
    failed_predictions = 0
    matched_success = 0

    for image_id, truth in truth_by_id.items():
        prediction = prediction_by_id.get(image_id)
        expected_fields = truth.get("expected_fields") or {}
        expected_raw = RawInvoiceData.model_validate(expected_fields)
        expected = normalize_invoice(expected_raw).invoice.model_dump(mode="json")
        evaluable = truth.get("evaluable_fields") or list(FIELDS)
        evaluable_fields = [field for field in evaluable if field in FIELDS]
        status, report, _ = _unwrap_prediction(prediction or {})
        successful = prediction is not None and status == "success"
        observed = report.get("normalized") if successful else {}
        observed = observed if isinstance(observed, dict) else {}
        if prediction is None:
            missing_predictions.append(image_id)
        elif not successful:
            failed_predictions += 1
        else:
            matched_success += 1

        for field in evaluable_fields:
            field_total[field] += 1
            if field in NUMERIC_FIELDS:
                matched = successful and _numeric_match(
                    expected.get(field), observed.get(field), numeric_tolerance
                )
                numeric_total += 1
                numeric_correct += int(matched)
            else:
                matched = successful and (
                    _canonical(expected.get(field)) == _canonical(observed.get(field))
                )
            field_correct[field] += int(matched)

        if truth.get("expected_decision") is None:
            continue
        expected_decision = str(truth["expected_decision"])
        observed_decision = str(report.get("decision")) if successful else (
            "MISSING" if prediction is None else "FAILED"
        )
        decision_total += 1
        decision_correct += int(expected_decision == observed_decision)
        confusion[f"{expected_decision}->{observed_decision}"] += 1
        expected_anomaly = expected_decision != "PASS"
        if successful:
            observed_anomaly = observed_decision != "PASS"
            anomaly_tp += int(expected_anomaly and observed_anomaly)
            anomaly_fp += int(not expected_anomaly and observed_anomaly)
            anomaly_fn += int(expected_anomaly and not observed_anomaly)
        else:
            anomaly_fn += int(expected_anomaly)

    successful_records = sum(
        _unwrap_prediction(record)[0] == "success" for record in prediction_records
    )
    attempts = max(len(ground_truth_records), len(prediction_records) + invalid_prediction_lines)
    precision_denominator = anomaly_tp + anomaly_fp
    recall_denominator = anomaly_tp + anomaly_fn
    resources = _resource_summary(prediction_records)
    if invalid_prediction_lines:
        resources["error_attribution_by_stage"]["parse"] = (
            resources["error_attribution_by_stage"].get("parse", 0)
            + invalid_prediction_lines
        )
    return {
        "counts": {
            "ground_truth": len(ground_truth_records),
            "attempted": attempts,
            "valid_predictions": successful_records,
            "failed_predictions": failed_predictions,
            "invalid_prediction_lines": invalid_prediction_lines,
            "matched_predictions": matched_success,
            "missing_predictions": len(missing_predictions),
            "duplicate_predictions": duplicate_predictions,
        },
        "json_validity_rate": successful_records / attempts if attempts else 0.0,
        "field_accuracy": {
            field: (field_correct[field] / field_total[field] if field_total[field] else 0.0)
            for field in FIELDS
        },
        "field_denominators": dict(field_total),
        "numeric_accuracy": numeric_correct / numeric_total if numeric_total else 0.0,
        "numeric_denominator": numeric_total,
        "decision_accuracy": decision_correct / decision_total if decision_total else 0.0,
        "decision_denominator": decision_total,
        "decision_confusion": dict(sorted(confusion.items())),
        "anomaly_precision": anomaly_tp / precision_denominator if precision_denominator else 0.0,
        "anomaly_recall": anomaly_tp / recall_denominator if recall_denominator else 0.0,
        "rule_precision": anomaly_tp / precision_denominator if precision_denominator else 0.0,
        "rule_recall": anomaly_tp / recall_denominator if recall_denominator else 0.0,
        "missing_prediction_ids": missing_predictions[:100],
        **resources,
    }


def evaluate(
    ground_truth_records: list[dict[str, Any]],
    prediction_records: list[dict[str, Any]],
    *,
    invalid_prediction_lines: int = 0,
    numeric_tolerance: Decimal = Decimal("0.02"),
) -> dict[str, Any]:
    result = _evaluate_core(
        ground_truth_records,
        prediction_records,
        invalid_prediction_lines=invalid_prediction_lines,
        numeric_tolerance=numeric_tolerance,
    )
    predictions_by_id = {
        image_id: record
        for record in prediction_records
        if (image_id := _prediction_id(record)) is not None
    }
    grouped_truth: dict[str, list[dict[str, Any]]] = defaultdict(list)
    vlm_run = any("status" in prediction for prediction in prediction_records)
    for truth in ground_truth_records:
        image_id = str(truth["image_id"])
        grouped_truth[
            _segment_name(
                truth,
                predictions_by_id.get(image_id),
                vlm_run=vlm_run,
            )
        ].append(truth)
    segments: dict[str, Any] = {}
    for name, truth_records in sorted(grouped_truth.items()):
        ids = {str(record["image_id"]) for record in truth_records}
        segment_predictions = [
            prediction for image_id, prediction in predictions_by_id.items() if image_id in ids
        ]
        segments[name] = _evaluate_core(
            truth_records,
            segment_predictions,
            invalid_prediction_lines=0,
            numeric_tolerance=numeric_tolerance,
        )
    result["segments"] = segments
    clean = segments.get("synthetic_vlm_clean")
    transformed = segments.get("synthetic_vlm_transformed")
    result["robustness_delta"] = (
        {
            "json_validity_rate": transformed["json_validity_rate"] - clean["json_validity_rate"],
            "decision_accuracy": transformed["decision_accuracy"] - clean["decision_accuracy"],
            "numeric_accuracy": transformed["numeric_accuracy"] - clean["numeric_accuracy"],
        }
        if clean and transformed
        else None
    )
    result["notes"] = [
        "Failed, missing, and invalid predictions remain in their applicable denominators.",
        "Sidecar, synthetic VLM, robustness, and public benchmark segments "
        "are not interchangeable.",
        "Portfolio-sized metrics are not production estimates.",
    ]
    return result


def evaluate_jsonl(
    ground_truth_path: str | Path,
    predictions_path: str | Path,
    *,
    numeric_tolerance: Decimal = Decimal("0.02"),
) -> dict[str, Any]:
    truth, truth_errors = read_jsonl(ground_truth_path)
    if truth_errors:
        raise ValueError(f"ground truth contains invalid records: {truth_errors[:3]}")
    predictions, prediction_errors = read_jsonl(predictions_path)
    result = evaluate(
        truth,
        predictions,
        invalid_prediction_lines=len(prediction_errors),
        numeric_tolerance=numeric_tolerance,
    )
    result["prediction_parse_errors"] = prediction_errors[:100]
    return result
