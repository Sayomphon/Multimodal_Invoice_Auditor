"""Prepare a deterministic, license-explicit SROIE evaluation subset."""

from __future__ import annotations

import argparse
from pathlib import Path

from invoice_auditor.datasets import prepare_sroie_huggingface, prepare_sroie_local


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("local", "huggingface"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--dataset-id", default="darentang/sroie")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--license-reference", required=True)
    parser.add_argument("--split", default="test")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    common = {
        "license_reference": args.license_reference,
        "count": args.count,
        "seed": args.seed,
        "split": args.split,
        "overwrite": args.overwrite,
    }
    if args.source == "local":
        if args.input_dir is None:
            raise SystemExit("--input-dir is required for --source local")
        path = prepare_sroie_local(
            args.input_dir,
            args.output_dir,
            dataset_revision=args.revision,
            **common,
        )
    else:
        path = prepare_sroie_huggingface(
            args.output_dir,
            dataset_id=args.dataset_id,
            revision=args.revision,
            **common,
        )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
