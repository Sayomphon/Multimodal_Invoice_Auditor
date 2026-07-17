"""Strict-enough parser for bounded JSON objects emitted by a model."""

from __future__ import annotations

import json
from typing import Any


class ModelOutputError(ValueError):
    """Raised when a model response cannot be safely treated as one JSON object."""


def parse_model_json(text: str, *, max_chars: int = 65_536) -> dict[str, Any]:
    if len(text) > max_chars:
        raise ModelOutputError(f"model response exceeds {max_chars} characters")
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1]).strip()
            if candidate.lower().startswith("json\n"):
                candidate = candidate[5:].lstrip()

    object_start = candidate.find("{")
    if object_start < 0:
        raise ModelOutputError("model response does not contain a JSON object")
    decoder = json.JSONDecoder()
    try:
        payload, end = decoder.raw_decode(candidate[object_start:])
    except json.JSONDecodeError as exc:
        raise ModelOutputError(f"invalid model JSON: {exc}") from exc
    trailing = candidate[object_start + end :].strip()
    if trailing:
        raise ModelOutputError("model response contains trailing non-JSON content")
    if not isinstance(payload, dict):
        raise ModelOutputError("model response must contain one JSON object")
    return payload

