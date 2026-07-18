"""Typed domain contracts shared by extractors, rules, and interfaces."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base model that rejects silent schema drift."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Severity(StrEnum):
    INFO = "info"
    REVIEW = "review"
    REJECT = "reject"


class AuditDecision(StrEnum):
    PASS = "PASS"  # noqa: S105 - workflow decision, not a credential.
    REVIEW = "REVIEW"
    REJECT = "REJECT"


RawValue = str | int | float | Decimal | None


class RawInvoiceData(StrictModel):
    """Untrusted values returned by an extractor or supplied as input."""

    invoice_number: RawValue = None
    vendor_name: RawValue = None
    tax_id: RawValue = None
    invoice_date: RawValue = None
    subtotal: RawValue = None
    vat: RawValue = None
    total: RawValue = None
    currency: RawValue = None


class NormalizedInvoice(StrictModel):
    """Deterministically normalized invoice used by business rules."""

    invoice_number: str | None = Field(default=None, max_length=128)
    vendor_name: str | None = Field(default=None, max_length=512)
    tax_id: str | None = Field(default=None, max_length=32)
    invoice_date: date | None = None
    subtotal: Decimal | None = None
    vat: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = Field(default=None, max_length=8)


class NormalizationIssue(StrictModel):
    field: str
    code: str
    message: str
    raw_value: str | None = None


class NormalizationResult(StrictModel):
    invoice: NormalizedInvoice
    issues: list[NormalizationIssue] = Field(default_factory=list)


class RuleResult(StrictModel):
    rule_id: str
    passed: bool | None
    severity: Severity
    observed: str | None = None
    expected: str | None = None
    message: str


class ModelTrace(StrictModel):
    model_id: str
    model_revision: str | None = None
    prompt_version: str
    runtime_profile: str | None = None
    device: str | None = None
    dtype: str | None = None
    quantization: str | None = None
    torch_version: str | None = None
    transformers_version: str | None = None
    cuda_version: str | None = None
    gpu_name: str | None = None
    model_load_ms: int | None = Field(default=None, ge=0)
    preprocess_ms: int | None = Field(default=None, ge=0)
    inference_ms: int | None = Field(default=None, ge=0)
    generation_parameters: dict[str, Any]
    latency_ms: int = Field(ge=0)
    peak_vram_mb: float | None = Field(default=None, ge=0)
    fallback_from: str | None = None
    fallback_reason: str | None = None
    raw_response: str | None = None


def _mask_tax_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return f"{'*' * (len(text) - 4)}{text[-4:]}"


class AuditReport(StrictModel):
    audit_id: str = Field(min_length=16, max_length=128)
    source_id: str | None = Field(default=None, max_length=512)
    created_at: datetime
    config_version: str
    config_fingerprint: str
    raw: RawInvoiceData
    normalized: NormalizedInvoice
    normalization_issues: list[NormalizationIssue]
    rules: list[RuleResult]
    decision: AuditDecision
    model_trace: ModelTrace | None = None

    def public_dict(self) -> dict[str, Any]:
        """Return JSON-ready output with common invoice identifiers masked."""

        payload = self.model_dump(mode="json")
        payload["raw"]["vendor_name"] = "[REDACTED]" if self.raw.vendor_name else None
        payload["raw"]["tax_id"] = _mask_tax_id(self.raw.tax_id)
        payload["normalized"]["vendor_name"] = (
            "[REDACTED]" if self.normalized.vendor_name else None
        )
        payload["normalized"]["tax_id"] = _mask_tax_id(self.normalized.tax_id)
        for issue in payload["normalization_issues"]:
            if issue["field"] in {"vendor_name", "tax_id"}:
                issue["raw_value"] = "[REDACTED]"
        if payload.get("model_trace"):
            payload["model_trace"]["raw_response"] = None
        return payload
