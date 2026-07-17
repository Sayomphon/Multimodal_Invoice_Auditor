"""Small-dataset evaluation with explicit denominators and error accounting."""

from __future__ import annotations

import json
from collections import Counter
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


def evaluate(
    ground_truth_records: list[dict[str, Any]],
    prediction_records: list[dict[str, Any]],
    *,
    invalid_prediction_lines: int = 0,
    numeric_tolerance: Decimal = Decimal("0.02"),
) -> dict[str, Any]:
    truth_by_id = {str(record["image_id"]): record for record in ground_truth_records}
    prediction_by_id = {
        str(record.get("source_id") or record.get("image_id")): record
        for record in prediction_records
        if record.get("source_id") or record.get("image_id")
    }
    field_correct = Counter({field: 0 for field in FIELDS})
    field_total = Counter({field: 0 for field in FIELDS})
    numeric_correct = 0
    numeric_total = 0
    decision_correct = 0
    decision_total = 0
    confusion: Counter[str] = Counter()
    anomaly_tp = anomaly_fp = anomaly_fn = 0
    missing_predictions: list[str] = []

    for image_id, truth in truth_by_id.items():
        prediction = prediction_by_id.get(image_id)
        if prediction is None:
            missing_predictions.append(image_id)
            continue
        expected_raw = RawInvoiceData.model_validate(truth["expected_fields"])
        expected = normalize_invoice(expected_raw).invoice.model_dump(mode="json")
        observed = prediction.get("normalized") or {}
        for field in FIELDS:
            field_total[field] += 1
            if field in NUMERIC_FIELDS:
                matched = _numeric_match(
                    expected.get(field),
                    observed.get(field),
                    numeric_tolerance,
                )
                numeric_total += 1
                numeric_correct += int(matched)
            else:
                matched = _canonical(expected.get(field)) == _canonical(observed.get(field))
            field_correct[field] += int(matched)

        expected_decision = str(truth["expected_decision"])
        observed_decision = str(prediction.get("decision"))
        decision_total += 1
        decision_correct += int(expected_decision == observed_decision)
        confusion[f"{expected_decision}->{observed_decision}"] += 1
        expected_anomaly = expected_decision != "PASS"
        observed_anomaly = observed_decision != "PASS"
        anomaly_tp += int(expected_anomaly and observed_anomaly)
        anomaly_fp += int(not expected_anomaly and observed_anomaly)
        anomaly_fn += int(expected_anomaly and not observed_anomaly)

    valid_predictions = len(prediction_records)
    prediction_attempts = valid_predictions + invalid_prediction_lines
    precision_denominator = anomaly_tp + anomaly_fp
    recall_denominator = anomaly_tp + anomaly_fn
    return {
        "counts": {
            "ground_truth": len(ground_truth_records),
            "valid_predictions": valid_predictions,
            "invalid_prediction_lines": invalid_prediction_lines,
            "matched_predictions": decision_total,
            "missing_predictions": len(missing_predictions),
        },
        "json_validity_rate": (
            valid_predictions / prediction_attempts if prediction_attempts else 0.0
        ),
        "field_accuracy": {
            field: (field_correct[field] / field_total[field] if field_total[field] else 0.0)
            for field in FIELDS
        },
        "numeric_accuracy": numeric_correct / numeric_total if numeric_total else 0.0,
        "decision_accuracy": decision_correct / decision_total if decision_total else 0.0,
        "decision_confusion": dict(sorted(confusion.items())),
        "anomaly_precision": anomaly_tp / precision_denominator if precision_denominator else 0.0,
        "anomaly_recall": anomaly_tp / recall_denominator if recall_denominator else 0.0,
        "missing_prediction_ids": missing_predictions[:100],
        "notes": [
            "Metrics are portfolio-sized and must not be interpreted as production estimates.",
            "Synthetic and public benchmark results should be reported separately.",
        ],
    }


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
