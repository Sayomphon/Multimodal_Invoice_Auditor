"""Manifest-driven VLM inference with one structured record per attempted document."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import Field

from invoice_auditor.io_utils import append_jsonl, load_json_object
from invoice_auditor.models import StrictModel
from invoice_auditor.pipeline import InvoiceAuditPipeline
from invoice_auditor.vlm_runtime import ErrorStage, Extractor, classify_error


class BatchInferenceRecord(StrictModel):
    run_id: str
    image_id: str
    source_path: str
    status: str
    error_stage: ErrorStage | None = None
    error_type: str | None = None
    error_message: str | None = None
    audit_report: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)


class BatchRunResult(StrictModel):
    run_id: str
    output_path: str
    attempted: int
    successful: int
    failed: int
    started_at: datetime
    completed_at: datetime


def _logical_source_path(value: object, image_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return image_id
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return image_id
    return candidate.as_posix()


def _resolve_manifest_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("manifest entry must contain image_path")
    candidate = (root / value).resolve(strict=True)
    if root != candidate and root not in candidate.parents:
        raise ValueError("manifest image_path escapes the dataset directory")
    if not candidate.is_file():
        raise ValueError("manifest image_path is not a file")
    return candidate


def run_batch_inference(
    manifest_path: str | Path,
    output_path: str | Path,
    extractor: Extractor,
    *,
    pipeline: InvoiceAuditPipeline | None = None,
    run_id: str | None = None,
    public_output: bool = False,
) -> BatchRunResult:
    """Reuse one extractor and atomically replace the JSONL with all attempt records."""

    started_at = datetime.now(UTC)
    resolved_manifest = Path(manifest_path).expanduser().resolve(strict=True)
    manifest = load_json_object(resolved_manifest, max_bytes=100 * 1024 * 1024)
    entries = manifest.get("records")
    if not isinstance(entries, list):
        raise ValueError("manifest.records must be a list")
    active_run_id = run_id or f"run-{started_at:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
    audit_pipeline = pipeline or InvoiceAuditPipeline()
    records: list[dict[str, Any]] = []

    for index, entry in enumerate(entries, 1):
        mapping = entry if isinstance(entry, dict) else {}
        image_id = str(mapping.get("image_id") or f"manifest-index-{index:04d}")
        source_path = _logical_source_path(mapping.get("image_path"), image_id)
        current_stage = ErrorStage.PREPROCESS
        try:
            image_path = _resolve_manifest_path(resolved_manifest.parent, mapping.get("image_path"))
            current_stage = ErrorStage.INFERENCE
            raw, trace = extractor.extract(image_path)
            current_stage = ErrorStage.AUDIT
            report = audit_pipeline.audit(raw, source_id=image_id, model_trace=trace)
            audit_report = report.public_dict() if public_output else report.model_dump(mode="json")
            runtime = trace.model_dump(mode="json")
            if public_output:
                runtime["raw_response"] = None
            record = BatchInferenceRecord(
                run_id=active_run_id,
                image_id=image_id,
                source_path=source_path,
                status="success",
                audit_report=audit_report,
                runtime=runtime,
            )
        except Exception as exc:
            classification = classify_error(exc, current_stage)
            record = BatchInferenceRecord(
                run_id=active_run_id,
                image_id=image_id,
                source_path=source_path,
                status="failed",
                error_stage=classification.stage,
                error_type=classification.error_type,
                error_message=classification.message,
            )
        records.append(record.model_dump(mode="json"))

    written = append_jsonl(output_path, records)
    successful = sum(record["status"] == "success" for record in records)
    completed_at = datetime.now(UTC)
    return BatchRunResult(
        run_id=active_run_id,
        output_path=str(written),
        attempted=len(records),
        successful=successful,
        failed=len(records) - successful,
        started_at=started_at,
        completed_at=completed_at,
    )
