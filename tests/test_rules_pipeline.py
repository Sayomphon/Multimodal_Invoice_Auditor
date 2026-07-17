from __future__ import annotations

import unittest

from invoice_auditor.models import AuditDecision
from invoice_auditor.pipeline import InvoiceAuditPipeline
from invoice_auditor.rules import InMemoryDuplicateStore, thai_tax_id_checksum_is_valid
from tests.helpers import NOW, valid_raw, valid_tax_id


class RulePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryDuplicateStore()
        self.pipeline = InvoiceAuditPipeline(duplicate_store=self.store)

    def test_valid_invoice_passes(self) -> None:
        report = self.pipeline.audit(valid_raw(), now=NOW)
        self.assertEqual(report.decision, AuditDecision.PASS)
        self.assertTrue(all(rule.passed is not False for rule in report.rules))

    def test_vat_wrong_is_review(self) -> None:
        raw = valid_raw()
        raw["vat"] = "790.00"
        raw["total"] = "10,790.00"
        report = self.pipeline.audit(raw, now=NOW)
        self.assertEqual(report.decision, AuditDecision.REVIEW)
        vat_rule = next(rule for rule in report.rules if rule.rule_id == "vat_rate")
        self.assertFalse(vat_rule.passed)

    def test_total_mismatch_is_reject(self) -> None:
        raw = valid_raw()
        raw["total"] = "10,800.00"
        report = self.pipeline.audit(raw, now=NOW)
        self.assertEqual(report.decision, AuditDecision.REJECT)

    def test_missing_tax_id_is_review(self) -> None:
        raw = valid_raw()
        raw["tax_id"] = None
        report = self.pipeline.audit(raw, now=NOW)
        self.assertEqual(report.decision, AuditDecision.REVIEW)

    def test_future_date_is_review(self) -> None:
        raw = valid_raw()
        raw["invoice_date"] = "2099-12-31"
        report = self.pipeline.audit(raw, now=NOW)
        self.assertEqual(report.decision, AuditDecision.REVIEW)

    def test_duplicate_is_atomic_and_rejected(self) -> None:
        first = self.pipeline.audit(valid_raw(), now=NOW)
        second = self.pipeline.audit(valid_raw(), now=NOW)
        self.assertEqual(first.decision, AuditDecision.PASS)
        self.assertEqual(second.decision, AuditDecision.REJECT)

    def test_duplicate_registration_can_be_disabled(self) -> None:
        first = self.pipeline.audit(valid_raw(), now=NOW, register_duplicate=False)
        second = self.pipeline.audit(valid_raw(), now=NOW, register_duplicate=False)
        self.assertEqual(first.decision, AuditDecision.PASS)
        self.assertEqual(second.decision, AuditDecision.PASS)

    def test_tax_id_checksum(self) -> None:
        valid = valid_tax_id()
        self.assertTrue(thai_tax_id_checksum_is_valid(valid))
        replacement = "0" if valid[-1] != "0" else "1"
        self.assertFalse(thai_tax_id_checksum_is_valid(valid[:-1] + replacement))

    def test_public_output_masks_sensitive_fields(self) -> None:
        report = self.pipeline.audit(valid_raw(), now=NOW)
        public = report.public_dict()
        self.assertEqual(public["raw"]["vendor_name"], "[REDACTED]")
        self.assertTrue(public["raw"]["tax_id"].endswith(valid_tax_id()[-4:]))
        self.assertNotEqual(public["raw"]["tax_id"], valid_tax_id())


if __name__ == "__main__":
    unittest.main()

