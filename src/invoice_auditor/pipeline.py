"""End-to-end orchestration independent from model runtime and user interface."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from invoice_auditor.config import RuleConfig, default_rule_config
from invoice_auditor.decision_policy import decide
from invoice_auditor.models import AuditReport, ModelTrace, RawInvoiceData
from invoice_auditor.normalizer import normalize_invoice
from invoice_auditor.rules import DuplicateStore, RuleEngine


class InvoiceAuditPipeline:
    def __init__(
        self,
        config: RuleConfig | None = None,
        duplicate_store: DuplicateStore | None = None,
    ) -> None:
        self.config = config or default_rule_config()
        self.rule_engine = RuleEngine(self.config, duplicate_store=duplicate_store)

    def audit(
        self,
        raw: RawInvoiceData | dict[str, object],
        *,
        source_id: str | None = None,
        model_trace: ModelTrace | None = None,
        register_duplicate: bool = True,
        now: datetime | None = None,
    ) -> AuditReport:
        raw_model = raw if isinstance(raw, RawInvoiceData) else RawInvoiceData.model_validate(raw)
        timestamp = now or datetime.now(UTC)
        if timestamp.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        normalized = normalize_invoice(raw_model)
        rules = self.rule_engine.evaluate(
            normalized.invoice,
            today=timestamp.date(),
            register_duplicate=register_duplicate,
        )
        return AuditReport(
            audit_id=secrets.token_hex(16),
            source_id=source_id,
            created_at=timestamp,
            config_version=self.config.config_version,
            config_fingerprint=self.config.fingerprint(),
            raw=raw_model,
            normalized=normalized.invoice,
            normalization_issues=normalized.issues,
            rules=rules,
            decision=decide(rules),
            model_trace=model_trace,
        )

