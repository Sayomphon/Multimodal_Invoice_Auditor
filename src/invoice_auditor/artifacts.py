"""Acceptance artifact validator for clean Colab runs."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from pydantic import Field

from invoice_auditor.evaluation import read_jsonl
from invoice_auditor.io_utils import load_json_object
from invoice_auditor.models import StrictModel


class ArtifactValidationResult(StrictModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


def _full_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def validate_run_artifacts(
    run_dir: str | Path,
    *,
    require_colab: bool = True,
    minimum_attempts: int = 5,
) -> ArtifactValidationResult:
    root = Path(run_dir).expanduser().resolve(strict=True)
    errors: list[str] = []
    warnings: list[str] = []
    required = ("environment.json", "run_manifest.json", "predictions.jsonl", "metrics.json")
    for name in required:
        if not (root / name).is_file():
            errors.append(f"missing required artifact: {name}")
    if errors:
        return ArtifactValidationResult(ok=False, errors=errors)

    environment = load_json_object(root / "environment.json")
    manifest = load_json_object(root / "run_manifest.json")
    metrics = load_json_object(root / "metrics.json", max_bytes=10 * 1024 * 1024)
    predictions, parse_errors = read_jsonl(root / "predictions.jsonl")
    errors.extend(f"predictions JSONL {error}" for error in parse_errors)
    if require_colab and not environment.get("colab"):
        errors.append("environment does not identify a Colab runtime")
    if require_colab and not environment.get("cuda_available"):
        errors.append("environment does not identify an available CUDA GPU")
    packages = environment.get("packages") or {}
    for package in ("torch", "transformers", "accelerate", "safetensors"):
        if not packages.get(package):
            errors.append(f"environment package version is missing: {package}")
    if not _full_sha(manifest.get("application_commit")):
        errors.append("run_manifest.application_commit must be a full commit SHA")
    if len(predictions) < minimum_attempts:
        errors.append(f"attempted records {len(predictions)} < required {minimum_attempts}")

    decisions: set[str] = set()
    successful = failed = 0
    for index, record in enumerate(predictions, 1):
        source = record.get("source_path")
        source_path = PurePosixPath(str(source or ""))
        if source_path.is_absolute() or ".." in source_path.parts:
            errors.append(f"prediction {index} exposes an unsafe source_path")
        if record.get("status") == "failed":
            failed += 1
            for field in ("error_stage", "error_type", "error_message"):
                if not record.get(field):
                    errors.append(f"prediction {index} failed without {field}")
            continue
        if record.get("status") != "success":
            errors.append(f"prediction {index} has invalid status")
            continue
        successful += 1
        report = record.get("audit_report") or {}
        runtime = record.get("runtime") or {}
        decisions.add(str(report.get("decision")))
        for field in ("raw", "normalized", "rules", "decision"):
            if field not in report:
                errors.append(f"prediction {index} audit_report missing {field}")
        for field in (
            "model_id",
            "model_revision",
            "prompt_version",
            "runtime_profile",
            "device",
            "dtype",
            "torch_version",
            "transformers_version",
            "model_load_ms",
            "preprocess_ms",
            "inference_ms",
            "latency_ms",
        ):
            if runtime.get(field) is None:
                errors.append(f"prediction {index} runtime missing {field}")
        if not _full_sha(runtime.get("model_revision")):
            errors.append(f"prediction {index} model_revision is not a full SHA")
        if runtime.get("raw_response") is not None:
            errors.append(f"prediction {index} public runtime exposes raw_response")
    missing_decisions = {"PASS", "REVIEW", "REJECT"} - decisions
    if missing_decisions:
        warnings.append(f"decision coverage missing: {sorted(missing_decisions)}")
    if metrics.get("counts", {}).get("attempted") != len(predictions):
        errors.append("metrics attempted denominator does not match predictions")
    return ArtifactValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        counts={"attempted": len(predictions), "successful": successful, "failed": failed},
    )
