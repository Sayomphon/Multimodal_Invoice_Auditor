"""Validated, versioned business-rule configuration."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from invoice_auditor.models import Severity, StrictModel

RULE_IDS = (
    "required_fields",
    "total_consistency",
    "vat_rate",
    "tax_id_format",
    "duplicate_invoice",
    "future_date",
)

INVOICE_FIELDS = {
    "invoice_number",
    "vendor_name",
    "tax_id",
    "invoice_date",
    "subtotal",
    "vat",
    "total",
    "currency",
}


class RuleConfig(StrictModel):
    config_version: str = Field(min_length=1, max_length=64)
    required_fields: list[str]
    expected_vat_rate: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    money_tolerance: Decimal = Field(gt=Decimal("0"), le=Decimal("100"))
    vat_rate_tolerance: Decimal = Field(gt=Decimal("0"), le=Decimal("0.1"))
    future_date_grace_days: int = Field(ge=0, le=365)
    severity: dict[str, Severity]

    @field_validator("required_fields")
    @classmethod
    def validate_required_fields(cls, value: list[str]) -> list[str]:
        unknown = set(value) - INVOICE_FIELDS
        if unknown:
            raise ValueError(f"unknown required fields: {sorted(unknown)}")
        if len(value) != len(set(value)):
            raise ValueError("required_fields must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_severity_map(self) -> RuleConfig:
        missing = set(RULE_IDS) - set(self.severity)
        extra = set(self.severity) - set(RULE_IDS)
        if missing or extra:
            raise ValueError(
                f"severity keys must match rules; missing={sorted(missing)}, extra={sorted(extra)}"
            )
        return self

    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def default_rule_config() -> RuleConfig:
    return RuleConfig.model_validate(
        {
            "config_version": "1.0.0",
            "required_fields": ["invoice_number", "invoice_date", "total"],
            "expected_vat_rate": "0.07",
            "money_tolerance": "0.02",
            "vat_rate_tolerance": "0.001",
            "future_date_grace_days": 0,
            "severity": {
                "required_fields": "review",
                "total_consistency": "reject",
                "vat_rate": "review",
                "tax_id_format": "review",
                "duplicate_invoice": "reject",
                "future_date": "review",
            },
        }
    )


def load_rule_config(path: str | Path | None = None) -> RuleConfig:
    if path is None:
        return default_rule_config()
    config_path = Path(path).expanduser().resolve(strict=True)
    if not config_path.is_file():
        raise ValueError(f"config path is not a file: {config_path}")
    if config_path.stat().st_size > 64 * 1024:
        raise ValueError("config file exceeds 64 KiB safety limit")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid config JSON: {exc}") from exc
    return RuleConfig.model_validate(payload)

