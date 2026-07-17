from __future__ import annotations

from datetime import UTC, datetime

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def valid_tax_id(prefix: str = "010556912345") -> str:
    if len(prefix) != 12 or not prefix.isdigit():
        raise ValueError("prefix must contain 12 digits")
    weighted_sum = sum(
        int(digit) * weight for digit, weight in zip(prefix, range(13, 1, -1), strict=True)
    )
    return f"{prefix}{(11 - weighted_sum % 11) % 10}"


def valid_raw() -> dict[str, object]:
    return {
        "invoice_number": "INV-2026-001",
        "vendor_name": "บริษัท ตัวอย่าง จำกัด",
        "tax_id": valid_tax_id(),
        "invoice_date": "2026-07-15",
        "subtotal": "10,000.00",
        "vat": "700.00",
        "total": "10,700.00",
        "currency": "THB",
    }
