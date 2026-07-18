"""Command-line interface for generation, auditing, and evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from invoice_auditor.artifacts import validate_run_artifacts
from invoice_auditor.batch_inference import run_batch_inference
from invoice_auditor.config import load_rule_config
from invoice_auditor.evaluation import evaluate_jsonl
from invoice_auditor.io_utils import append_jsonl, atomic_write_json, load_json_object
from invoice_auditor.pipeline import InvoiceAuditPipeline
from invoice_auditor.runtime import detect_runtime
from invoice_auditor.synthetic_generator import AnomalyType, generate_dataset
from invoice_auditor.vlm_extractor import ExtractorSettings, QwenVLMExtractor
from invoice_auditor.vlm_runtime import (
    VLMRuntime,
    default_registry_path,
    load_model_registry,
)


def _common_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="Path to validated rule JSON configuration")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="invoice-auditor",
        description="Privacy-aware invoice extraction and deterministic audit pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_json = subparsers.add_parser("audit-json", help="Audit one raw invoice JSON object")
    audit_json.add_argument("input", type=Path)
    audit_json.add_argument("--output", type=Path)
    audit_json.add_argument("--public-output", action="store_true")
    audit_json.add_argument("--no-register-duplicate", action="store_true")
    _common_config(audit_json)

    audit_image = subparsers.add_parser("audit-image", help="Extract and audit one local image")
    audit_image.add_argument("input", type=Path)
    audit_image.add_argument("--output", type=Path)
    audit_image.add_argument("--model", help="Direct model override; bypasses registry fallback")
    audit_image.add_argument("--revision")
    audit_image.add_argument("--registry", type=Path, default=default_registry_path())
    audit_image.add_argument("--max-new-tokens", type=int, default=512)
    audit_image.add_argument("--longest-side", type=int, default=1600)
    audit_image.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow Transformers to access the model registry if files are not cached",
    )
    audit_image.add_argument("--public-output", action="store_true")
    audit_image.add_argument("--allow-cpu", action="store_true")
    _common_config(audit_image)

    generate = subparsers.add_parser("generate-synthetic", help="Create synthetic Thai invoices")
    generate.add_argument("--output-dir", type=Path, required=True)
    generate.add_argument("--count", type=int, default=6)
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--font-path", type=Path)
    generate.add_argument(
        "--anomalies",
        nargs="+",
        choices=[item.value for item in AnomalyType],
        default=[item.value for item in AnomalyType],
    )
    generate.add_argument("--overwrite", action="store_true")

    batch = subparsers.add_parser(
        "batch-audit",
        help="Audit synthetic record sidecars in manifest order",
    )
    batch.add_argument("manifest", type=Path)
    batch.add_argument("--output", type=Path, required=True)
    batch.add_argument("--public-output", action="store_true")
    _common_config(batch)

    batch_inference = subparsers.add_parser(
        "batch-inference",
        help="Run real VLM inference for every image/PDF in a manifest",
    )
    batch_inference.add_argument("manifest", type=Path)
    batch_inference.add_argument("--output", type=Path, required=True)
    batch_inference.add_argument("--registry", type=Path, default=default_registry_path())
    batch_inference.add_argument("--max-new-tokens", type=int, default=512)
    batch_inference.add_argument("--longest-side", type=int, default=1600)
    batch_inference.add_argument("--allow-download", action="store_true")
    batch_inference.add_argument("--allow-cpu", action="store_true")
    batch_inference.add_argument("--public-output", action="store_true")
    _common_config(batch_inference)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate prediction JSONL")
    evaluate.add_argument("ground_truth", type=Path)
    evaluate.add_argument("predictions", type=Path)
    evaluate.add_argument("--output", type=Path)

    show = subparsers.add_parser("show-config", help="Validate and print effective rule config")
    _common_config(show)

    runtime_info = subparsers.add_parser("runtime-info", help="Print CPU/GPU environment telemetry")
    runtime_info.add_argument("--output", type=Path)
    runtime_info.add_argument("--disk-path", type=Path, default=Path.cwd())

    validate = subparsers.add_parser(
        "validate-artifacts",
        help="Validate a Colab run directory before publishing metrics",
    )
    validate.add_argument("run_dir", type=Path)
    validate.add_argument("--allow-local", action="store_true")
    validate.add_argument("--minimum-attempts", type=int, default=5)

    demo = subparsers.add_parser("demo", help="Launch a loopback-only Gradio audit UI")
    demo.add_argument("--model", default="Qwen/Qwen3-VL-4B-Instruct")
    demo.add_argument("--revision")
    demo.add_argument("--port", type=int, default=7860)
    demo.add_argument("--allow-download", action="store_true")
    _common_config(demo)
    return parser


def _emit(payload: dict[str, Any], output: Path | None) -> None:
    if output is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        written = atomic_write_json(output, payload)
        print(written)


def _audit_json(args: argparse.Namespace) -> None:
    config = load_rule_config(args.config)
    raw = load_json_object(args.input)
    report = InvoiceAuditPipeline(config).audit(
        raw,
        source_id=args.input.name,
        register_duplicate=not args.no_register_duplicate,
    )
    payload = report.public_dict() if args.public_output else report.model_dump(mode="json")
    _emit(payload, args.output)


def _audit_image(args: argparse.Namespace) -> None:
    config = load_rule_config(args.config)
    if args.model:
        extractor: Any = QwenVLMExtractor(
            ExtractorSettings(
                model_id=args.model,
                model_revision=args.revision,
                max_new_tokens=args.max_new_tokens,
                longest_side=args.longest_side,
                local_files_only=not args.allow_download,
            )
        )
    else:
        if args.revision:
            raise ValueError("--revision requires --model; registry revisions are immutable")
        extractor = VLMRuntime(
            load_model_registry(args.registry),
            allow_download=args.allow_download,
            max_new_tokens=args.max_new_tokens,
            longest_side=args.longest_side,
            require_cuda=not args.allow_cpu,
        )
    try:
        raw, trace = extractor.extract(args.input)
    finally:
        extractor.release()
    report = InvoiceAuditPipeline(config).audit(
        raw,
        source_id=args.input.name,
        model_trace=trace,
    )
    payload = report.public_dict() if args.public_output else report.model_dump(mode="json")
    _emit(payload, args.output)


def _generate(args: argparse.Namespace) -> None:
    anomaly_cycle = tuple(AnomalyType(value) for value in args.anomalies)
    manifest = generate_dataset(
        args.output_dir,
        count=args.count,
        seed=args.seed,
        font_path=args.font_path,
        anomaly_cycle=anomaly_cycle,
        overwrite=args.overwrite,
    )
    print(manifest)


def _batch_audit(args: argparse.Namespace) -> None:
    manifest_path = args.manifest.expanduser().resolve(strict=True)
    manifest = load_json_object(manifest_path, max_bytes=100 * 1024 * 1024)
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("manifest.records must be a list")
    pipeline = InvoiceAuditPipeline(load_rule_config(args.config))
    predictions: list[dict[str, Any]] = []
    for entry in records:
        if not isinstance(entry, dict) or not isinstance(entry.get("record_path"), str):
            raise ValueError("each manifest record must contain record_path")
        record_path = (manifest_path.parent / entry["record_path"]).resolve(strict=True)
        if manifest_path.parent not in record_path.parents:
            raise ValueError("manifest record_path escapes the dataset directory")
        raw = load_json_object(record_path)
        report = pipeline.audit(raw, source_id=str(entry["image_id"]))
        payload = report.public_dict() if args.public_output else report.model_dump(mode="json")
        predictions.append(payload)
    written = append_jsonl(args.output, predictions)
    print(written)


def _batch_inference(args: argparse.Namespace) -> None:
    runtime = VLMRuntime(
        load_model_registry(args.registry),
        allow_download=args.allow_download,
        max_new_tokens=args.max_new_tokens,
        longest_side=args.longest_side,
        require_cuda=not args.allow_cpu,
    )
    try:
        result = run_batch_inference(
            args.manifest,
            args.output,
            runtime,
            pipeline=InvoiceAuditPipeline(load_rule_config(args.config)),
            public_output=args.public_output,
        )
    finally:
        runtime.release()
    _emit(result.model_dump(mode="json"), None)


def _evaluate(args: argparse.Namespace) -> None:
    result = evaluate_jsonl(args.ground_truth, args.predictions)
    _emit(result, args.output)


def _show_config(args: argparse.Namespace) -> None:
    config = load_rule_config(args.config)
    payload = config.model_dump(mode="json")
    payload["fingerprint"] = config.fingerprint()
    _emit(payload, None)


def _runtime_info(args: argparse.Namespace) -> None:
    payload = detect_runtime(disk_path=args.disk_path).model_dump(mode="json")
    _emit(payload, args.output)


def _validate_artifacts(args: argparse.Namespace) -> None:
    result = validate_run_artifacts(
        args.run_dir,
        require_colab=not args.allow_local,
        minimum_attempts=args.minimum_attempts,
    )
    _emit(result.model_dump(mode="json"), None)
    if not result.ok:
        raise ValueError("artifact validation failed")


def _demo(args: argparse.Namespace) -> None:
    from invoice_auditor.demo_app import launch_demo

    launch_demo(
        model_id=args.model,
        model_revision=args.revision,
        allow_download=args.allow_download,
        port=args.port,
        config=load_rule_config(args.config),
    )


def run(args: argparse.Namespace) -> None:
    handlers = {
        "audit-json": _audit_json,
        "audit-image": _audit_image,
        "generate-synthetic": _generate,
        "batch-audit": _batch_audit,
        "batch-inference": _batch_inference,
        "evaluate": _evaluate,
        "show-config": _show_config,
        "runtime-info": _runtime_info,
        "validate-artifacts": _validate_artifacts,
        "demo": _demo,
    }
    handlers[args.command](args)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        run(args)
    except (ValidationError, ValueError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
