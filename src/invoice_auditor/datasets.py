"""Reproducible SROIE subset preparation without committing raw benchmark data."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from invoice_auditor.io_utils import append_jsonl, atomic_write_json

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SROIE_FIELD_MAP = {
    "company": "vendor_name",
    "vendor": "vendor_name",
    "date": "invoice_date",
    "total": "total",
}


def _selection_key(seed: int, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_expected(annotation: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    expected: dict[str, Any] = {}
    evaluable: list[str] = []
    for source_field, target_field in SROIE_FIELD_MAP.items():
        value = annotation.get(source_field)
        if value is None or target_field in expected:
            continue
        expected[target_field] = value
        evaluable.append(target_field)
    if not evaluable:
        raise ValueError("SROIE annotation has no supported company/date/total fields")
    return expected, evaluable


def _annotation_for_image(input_root: Path, image_path: Path) -> tuple[dict[str, Any], Path]:
    candidates = (
        input_root / "entities" / f"{image_path.stem}.txt",
        input_root / "entities" / f"{image_path.stem}.json",
        image_path.with_suffix(".json"),
        image_path.with_suffix(".txt"),
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid SROIE entity annotation for {image_path.name}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"SROIE entity annotation must be an object: {candidate.name}")
        return payload, candidate
    raise ValueError(f"missing SROIE entity annotation for {image_path.name}")


def _write_dataset(
    output_root: Path,
    *,
    entries: list[dict[str, Any]],
    dataset_revision: str,
    split: str,
    subset_seed: int,
    license_reference: str,
    source_mode: str,
) -> Path:
    manifest = {
        "schema_version": "1.0.0",
        "dataset_name": "SROIE",
        "dataset_revision": dataset_revision,
        "split": split,
        "subset_seed": subset_seed,
        "license_reference": license_reference,
        "source_mode": source_mode,
        "count": len(entries),
        "records": entries,
    }
    manifest_path = atomic_write_json(output_root / "manifest.json", manifest)
    append_jsonl(output_root / "ground_truth.jsonl", entries)
    return manifest_path


def prepare_sroie_local(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    dataset_revision: str,
    license_reference: str,
    count: int = 50,
    seed: int = 42,
    split: str = "test",
    overwrite: bool = False,
) -> Path:
    if not dataset_revision.strip() or not license_reference.strip():
        raise ValueError("dataset_revision and license_reference are required")
    input_root = Path(input_dir).expanduser().resolve(strict=True)
    output_root = Path(output_dir).expanduser().resolve()
    manifest_path = output_root / "manifest.json"
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {manifest_path}; pass overwrite=True")
    images = sorted(
        path
        for path in input_root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise ValueError("no SROIE image files found")
    if not 1 <= count <= len(images):
        raise ValueError(f"count must be between 1 and {len(images)}")
    selected = sorted(
        sorted(
            images,
            key=lambda path: _selection_key(seed, str(path.relative_to(input_root))),
        )[:count]
    )
    image_output = output_root / "images"
    image_output.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for index, source_image in enumerate(selected, 1):
        annotation, annotation_path = _annotation_for_image(input_root, source_image)
        expected, evaluable = _normalized_expected(annotation)
        image_id = f"SROIE-{split}-{index:04d}-{source_image.stem}"
        destination = image_output / f"{image_id}{source_image.suffix.lower()}"
        shutil.copyfile(source_image, destination)
        entries.append(
            {
                "dataset_name": "SROIE",
                "dataset_revision": dataset_revision,
                "dataset_segment": "sroie_vlm",
                "split": split,
                "subset_seed": seed,
                "image_id": image_id,
                "image_path": str(destination.relative_to(output_root)),
                "sha256": sha256_file(destination),
                "source_annotation": str(annotation_path.relative_to(input_root)),
                "expected_fields": expected,
                "evaluable_fields": evaluable,
                "license_reference": license_reference,
            }
        )
    return _write_dataset(
        output_root,
        entries=entries,
        dataset_revision=dataset_revision,
        split=split,
        subset_seed=seed,
        license_reference=license_reference,
        source_mode="local",
    )


def prepare_sroie_huggingface(
    output_dir: str | Path,
    *,
    dataset_id: str,
    revision: str,
    license_reference: str,
    count: int = 50,
    seed: int = 42,
    split: str = "test",
    overwrite: bool = False,
) -> Path:
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise ValueError("Hugging Face dataset revision must be a full 40-character SHA")
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError("Hugging Face mode requires the optional datasets package") from exc
    output_root = Path(output_dir).expanduser().resolve()
    if (output_root / "manifest.json").exists() and not overwrite:
        raise FileExistsError("dataset output already exists; pass overwrite=True")
    dataset = load_dataset(dataset_id, revision=revision, split=split)
    if not 1 <= count <= len(dataset):
        raise ValueError(f"count must be between 1 and {len(dataset)}")
    indices = sorted(
        sorted(range(len(dataset)), key=lambda index: _selection_key(seed, str(index)))[:count]
    )
    image_output = output_root / "images"
    image_output.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    for sequence, index in enumerate(indices, 1):
        row = dict(dataset[index])
        annotation = row.get("entities") if isinstance(row.get("entities"), dict) else row
        expected, evaluable = _normalized_expected(annotation)
        image = row.get("image")
        if not isinstance(image, Image.Image):
            raise ValueError("Hugging Face SROIE row does not expose a PIL image")
        image_id = f"SROIE-{split}-{sequence:04d}"
        destination = image_output / f"{image_id}.png"
        image.convert("RGB").save(destination, format="PNG")
        entries.append(
            {
                "dataset_name": "SROIE",
                "dataset_revision": revision,
                "dataset_segment": "sroie_vlm",
                "split": split,
                "subset_seed": seed,
                "image_id": image_id,
                "image_path": str(destination.relative_to(output_root)),
                "sha256": sha256_file(destination),
                "source_annotation": f"{dataset_id}:{split}:{index}",
                "expected_fields": expected,
                "evaluable_fields": evaluable,
                "license_reference": license_reference,
            }
        )
    return _write_dataset(
        output_root,
        entries=entries,
        dataset_revision=revision,
        split=split,
        subset_seed=seed,
        license_reference=license_reference,
        source_mode="huggingface",
    )
