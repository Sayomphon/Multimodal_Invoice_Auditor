"""Conservative normalization that never guesses an unparseable value."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Callable

from invoice_auditor.models import (
    NormalizationIssue,
    NormalizationResult,
    NormalizedInvoice,
    RawInvoiceData,
    RawValue,
)

_CURRENCY_MAP = {
    "฿": "THB",
    "บาท": "THB",
    "THB": "THB",
    "USD": "USD",
    "$": "USD",
    "EUR": "EUR",
    "€": "EUR",
}

_MONEY_ALLOWED = re.compile(r"^-?[0-9][0-9,.]*$")


def _text(value: RawValue, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value)).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"value exceeds maximum length of {max_length}")
    return " ".join(normalized.split())


def normalize_money(value: RawValue) -> Decimal | None:
    text = _text(value, max_length=64)
    if text is None:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = f"-{text[1:-1]}"
    for token in ("THB", "บาท", "฿", "USD", "$", "EUR", "€"):
        text = text.replace(token, "")
    text = text.replace(" ", "")
    if not _MONEY_ALLOWED.fullmatch(text):
        raise ValueError("money contains unsupported characters")

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts) == 2 and len(parts[1]) in {1, 2}:
            text = ".".join(parts)
        else:
            text = "".join(parts)
    elif text.count(".") > 1:
        parts = text.split(".")
        if len(parts[-1]) in {1, 2}:
            text = "".join(parts[:-1]) + "." + parts[-1]
        else:
            text = "".join(parts)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("money is not a valid decimal") from exc


def normalize_date(value: RawValue) -> date | None:
    text = _text(value, max_length=64)
    if text is None:
        return None
    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d/%m/%y",
        "%d-%m-%y",
    )
    parsed: date | None = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError("date format is unsupported")
    if 2400 <= parsed.year <= 2699:
        parsed = parsed.replace(year=parsed.year - 543)
    return parsed


def normalize_currency(value: RawValue) -> str | None:
    text = _text(value, max_length=16)
    if text is None:
        return None
    canonical = _CURRENCY_MAP.get(text.upper(), _CURRENCY_MAP.get(text))
    if canonical is None:
        if re.fullmatch(r"[A-Za-z]{3}", text):
            return text.upper()
        raise ValueError("currency must be an ISO-like three-letter code or known symbol")
    return canonical


def normalize_tax_id(value: RawValue) -> str | None:
    text = _text(value, max_length=64)
    if text is None:
        return None
    digits = re.sub(r"[\s-]", "", text)
    if not digits.isdigit():
        raise ValueError("tax ID contains non-digit characters")
    return digits


def normalize_invoice(raw: RawInvoiceData) -> NormalizationResult:
    issues: list[NormalizationIssue] = []

    def capture(
        field: str,
        value: RawValue,
        parser: Callable[[RawValue], object | None],
    ) -> object | None:
        try:
            return parser(value)
        except ValueError as exc:
            raw_text = None if value is None else str(value)[:256]
            issues.append(
                NormalizationIssue(
                    field=field,
                    code="parse_error",
                    message=str(exc),
                    raw_value=raw_text,
                )
            )
            return None

    normalized = NormalizedInvoice(
        invoice_number=capture(
            "invoice_number", raw.invoice_number, lambda value: _text(value, max_length=128)
        ),
        vendor_name=capture(
            "vendor_name", raw.vendor_name, lambda value: _text(value, max_length=512)
        ),
        tax_id=capture("tax_id", raw.tax_id, normalize_tax_id),
        invoice_date=capture("invoice_date", raw.invoice_date, normalize_date),
        subtotal=capture("subtotal", raw.subtotal, normalize_money),
        vat=capture("vat", raw.vat, normalize_money),
        total=capture("total", raw.total, normalize_money),
        currency=capture("currency", raw.currency, normalize_currency),
    )
    return NormalizationResult(invoice=normalized, issues=issues)

