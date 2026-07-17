"""Deterministic business rules and duplicate-store abstraction."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from threading import Lock
from typing import Protocol

from invoice_auditor.config import RuleConfig
from invoice_auditor.models import NormalizedInvoice, RuleResult


class DuplicateStore(Protocol):
    def seen_or_register(self, key: str, *, register: bool) -> bool:
        """Return whether key was already present; optionally register atomically."""


class InMemoryDuplicateStore:
    """Thread-safe process-local store for demos and tests only."""

    def __init__(self) -> None:
        self._keys: set[str] = set()
        self._lock = Lock()

    def seen_or_register(self, key: str, *, register: bool) -> bool:
        with self._lock:
            seen = key in self._keys
            if register and not seen:
                self._keys.add(key)
            return seen

    def clear(self) -> None:
        with self._lock:
            self._keys.clear()


def thai_tax_id_checksum_is_valid(tax_id: str) -> bool:
    """Validate the 13-digit checksum only; this does not verify an entity."""

    if len(tax_id) != 13 or not tax_id.isdigit():
        return False
    weighted_sum = sum(int(digit) * weight for digit, weight in zip(tax_id[:12], range(13, 1, -1)))
    expected = (11 - (weighted_sum % 11)) % 10
    return expected == int(tax_id[-1])


class RuleEngine:
    def __init__(
        self,
        config: RuleConfig,
        duplicate_store: DuplicateStore | None = None,
    ) -> None:
        self.config = config
        self.duplicate_store = duplicate_store or InMemoryDuplicateStore()

    def evaluate(
        self,
        invoice: NormalizedInvoice,
        *,
        today: date,
        register_duplicate: bool = True,
    ) -> list[RuleResult]:
        return [
            self._required_fields(invoice),
            self._total_consistency(invoice),
            self._vat_rate(invoice),
            self._tax_id_format(invoice),
            self._duplicate_invoice(invoice, register=register_duplicate),
            self._future_date(invoice, today=today),
        ]

    def _required_fields(self, invoice: NormalizedInvoice) -> RuleResult:
        missing = [name for name in self.config.required_fields if getattr(invoice, name) is None]
        return RuleResult(
            rule_id="required_fields",
            passed=not missing,
            severity=self.config.severity["required_fields"],
            observed=", ".join(missing) if missing else "all configured fields present",
            expected=", ".join(self.config.required_fields),
            message="required fields missing" if missing else "required fields are present",
        )

    def _total_consistency(self, invoice: NormalizedInvoice) -> RuleResult:
        values = (invoice.subtotal, invoice.vat, invoice.total)
        if any(value is None for value in values):
            return RuleResult(
                rule_id="total_consistency",
                passed=None,
                severity=self.config.severity["total_consistency"],
                message="cannot evaluate without subtotal, VAT, and total",
            )
        assert invoice.subtotal is not None
        assert invoice.vat is not None
        assert invoice.total is not None
        expected = invoice.subtotal + invoice.vat
        difference = abs(invoice.total - expected)
        passed = difference <= self.config.money_tolerance
        return RuleResult(
            rule_id="total_consistency",
            passed=passed,
            severity=self.config.severity["total_consistency"],
            observed=f"total={invoice.total}; difference={difference}",
            expected=f"subtotal+vat={expected}; tolerance<={self.config.money_tolerance}",
            message="total is consistent" if passed else "total does not equal subtotal plus VAT",
        )

    def _vat_rate(self, invoice: NormalizedInvoice) -> RuleResult:
        if invoice.subtotal is None or invoice.vat is None or invoice.subtotal <= Decimal("0"):
            return RuleResult(
                rule_id="vat_rate",
                passed=None,
                severity=self.config.severity["vat_rate"],
                message="cannot evaluate without positive subtotal and VAT",
            )
        observed_rate = invoice.vat / invoice.subtotal
        difference = abs(observed_rate - self.config.expected_vat_rate)
        passed = difference <= self.config.vat_rate_tolerance
        return RuleResult(
            rule_id="vat_rate",
            passed=passed,
            severity=self.config.severity["vat_rate"],
            observed=f"{observed_rate:.6f}",
            expected=(
                f"{self.config.expected_vat_rate} +/- {self.config.vat_rate_tolerance}"
            ),
            message="VAT rate is within tolerance" if passed else "VAT rate is outside tolerance",
        )

    def _tax_id_format(self, invoice: NormalizedInvoice) -> RuleResult:
        if invoice.tax_id is None:
            return RuleResult(
                rule_id="tax_id_format",
                passed=False,
                severity=self.config.severity["tax_id_format"],
                observed="missing",
                expected="13-digit Thai Tax ID with valid checksum",
                message="Tax ID is missing",
            )
        passed = thai_tax_id_checksum_is_valid(invoice.tax_id)
        return RuleResult(
            rule_id="tax_id_format",
            passed=passed,
            severity=self.config.severity["tax_id_format"],
            observed=f"length={len(invoice.tax_id)}",
            expected="13-digit Thai Tax ID with valid checksum",
            message="Tax ID format is valid" if passed else "Tax ID format/checksum is invalid",
        )

    def _duplicate_invoice(self, invoice: NormalizedInvoice, *, register: bool) -> RuleResult:
        if invoice.vendor_name is None or invoice.invoice_number is None:
            return RuleResult(
                rule_id="duplicate_invoice",
                passed=None,
                severity=self.config.severity["duplicate_invoice"],
                message="cannot evaluate without vendor and invoice number",
            )
        key = f"{invoice.vendor_name.casefold()}::{invoice.invoice_number.casefold()}"
        seen = self.duplicate_store.seen_or_register(key, register=register)
        return RuleResult(
            rule_id="duplicate_invoice",
            passed=not seen,
            severity=self.config.severity["duplicate_invoice"],
            observed="already seen" if seen else "not previously seen",
            expected="unique vendor + invoice number",
            message="duplicate invoice detected" if seen else "invoice key is unique",
        )

    def _future_date(self, invoice: NormalizedInvoice, *, today: date) -> RuleResult:
        if invoice.invoice_date is None:
            return RuleResult(
                rule_id="future_date",
                passed=None,
                severity=self.config.severity["future_date"],
                message="cannot evaluate without invoice date",
            )
        latest_allowed = today + timedelta(days=self.config.future_date_grace_days)
        passed = invoice.invoice_date <= latest_allowed
        return RuleResult(
            rule_id="future_date",
            passed=passed,
            severity=self.config.severity["future_date"],
            observed=invoice.invoice_date.isoformat(),
            expected=f"date <= {latest_allowed.isoformat()}",
            message="invoice date is allowed" if passed else "invoice date is in the future",
        )
