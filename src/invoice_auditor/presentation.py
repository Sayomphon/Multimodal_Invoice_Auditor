"""Redacted, notebook-friendly presentation contract."""

from __future__ import annotations

from typing import Any

from invoice_auditor.models import AuditReport


def build_public_audit_view(report: AuditReport) -> dict[str, Any]:
    public = report.public_dict()
    trace = public.get("model_trace") or {}
    return {
        "source": {
            "source_id": public.get("source_id"),
            "audit_id": public["audit_id"],
            "created_at": public["created_at"],
        },
        "extraction": {
            "raw": public["raw"],
            "model_id": trace.get("model_id"),
            "model_revision": trace.get("model_revision"),
            "prompt_version": trace.get("prompt_version"),
            "raw_response": None,
        },
        "normalization": {
            "fields": public["normalized"],
            "issues": public["normalization_issues"],
        },
        "rules": public["rules"],
        "decision": {
            "value": public["decision"],
            "fallback_from": trace.get("fallback_from"),
            "fallback_reason": trace.get("fallback_reason"),
            "uncertainty_note": (
                "Fallback model was used; compare metrics by model/profile."
                if trace.get("fallback_from")
                else "Missing/unreadable evidence is routed by deterministic rules."
            ),
        },
        "runtime": {
            key: value
            for key, value in trace.items()
            if key not in {"raw_response", "generation_parameters"}
        },
        "download": public,
    }
