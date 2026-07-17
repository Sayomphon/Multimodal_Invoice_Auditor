"""Bounded JSON input and atomic, owner-only output helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_json_object(path: str | Path, *, max_bytes: int = 1_048_576) -> dict[str, Any]:
    input_path = Path(path).expanduser().resolve(strict=True)
    if not input_path.is_file():
        raise ValueError(f"input path is not a file: {input_path}")
    size = input_path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"JSON input exceeds {max_bytes} byte safety limit")
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("JSON input must be UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON input must contain one object")
    return payload


def atomic_write_json(
    path: str | Path,
    payload: dict[str, Any] | list[Any],
    *,
    mode: int = 0o600,
) -> Path:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path


def append_jsonl(path: str | Path, records: list[dict[str, Any]]) -> Path:
    """Write a complete JSONL file atomically; despite the name this never appends in place."""

    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return output_path

