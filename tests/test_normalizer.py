from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from invoice_auditor.models import RawInvoiceData
from invoice_auditor.normalizer import (
    normalize_currency,
    normalize_date,
    normalize_invoice,
    normalize_money,
)


class MoneyNormalizerTests(unittest.TestCase):
    def test_common_number_formats(self) -> None:
        cases = {
            "10,700.00": Decimal("10700.00"),
            "10.700,50": Decimal("10700.50"),
            "฿ 1,234": Decimal("1234"),
            "(500.25)": Decimal("-500.25"),
            700: Decimal("700"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_money(raw), expected)

    def test_rejects_exponent_and_arbitrary_text(self) -> None:
        for raw in ("1e6", "one hundred", "10,000 THB<script>"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_money(raw)


class DateAndCurrencyNormalizerTests(unittest.TestCase):
    def test_supported_date_formats_and_buddhist_year(self) -> None:
        self.assertEqual(normalize_date("15/07/2026"), date(2026, 7, 15))
        self.assertEqual(normalize_date("15/07/2569"), date(2026, 7, 15))

    def test_currency_mapping(self) -> None:
        self.assertEqual(normalize_currency("บาท"), "THB")
        self.assertEqual(normalize_currency("usd"), "USD")
        with self.assertRaises(ValueError):
            normalize_currency("BITCOIN")

    def test_invoice_preserves_parse_failures(self) -> None:
        result = normalize_invoice(
            RawInvoiceData(
                invoice_number="A-1",
                invoice_date="not-a-date",
                total="10x",
            )
        )
        self.assertIsNone(result.invoice.invoice_date)
        self.assertIsNone(result.invoice.total)
        self.assertEqual({issue.field for issue in result.issues}, {"invoice_date", "total"})


if __name__ == "__main__":
    unittest.main()

