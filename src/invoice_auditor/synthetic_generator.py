"""Reproducible, privacy-safe Thai invoice image and label generation."""

from __future__ import annotations

import os
import random
import tempfile
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from invoice_auditor.io_utils import append_jsonl, atomic_write_json


class AnomalyType(StrEnum):
    NORMAL = "normal"
    VAT_WRONG = "vat_wrong"
    TOTAL_MISMATCH = "total_mismatch"
    MISSING_TAX_ID = "missing_tax_id"
    DUPLICATE_INVOICE = "duplicate_invoice"
    FUTURE_DATE = "future_date"


DEFAULT_ANOMALY_CYCLE = tuple(AnomalyType)

_VENDORS = (
    "บริษัท สยามดิจิทัล จำกัด",
    "บริษัท ไทยสมาร์ทโลจิสติกส์ จำกัด",
    "บริษัท นวัตกรรมอุตสาหกรรม จำกัด",
    "ห้างหุ้นส่วนจำกัด เมืองไทยซัพพลาย",
)

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/SukhumvitSet.ttc",
    "/System/Library/Fonts/Supplemental/Tahoma.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/usr/share/fonts/truetype/tlwg/Garuda.ttf",
    "/System/Library/Fonts/Supplemental/Thonburi.ttc",
    "/System/Library/Fonts/ThonburiUI.ttc",
)


def _valid_tax_id(rng: random.Random) -> str:
    first_twelve = "".join(str(rng.randrange(10)) for _ in range(12))
    weighted_sum = sum(
        int(digit) * weight
        for digit, weight in zip(first_twelve, range(13, 1, -1), strict=True)
    )
    checksum = (11 - (weighted_sum % 11)) % 10
    return f"{first_twelve}{checksum}"


def resolve_thai_font(font_path: str | Path | None = None) -> Path:
    configured = font_path or os.environ.get("INVOICE_AUDITOR_FONT_PATH")
    candidates = (str(configured),) if configured else _FONT_CANDIDATES
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file() and path.stat().st_size <= 100 * 1024 * 1024:
            return path.resolve()
    raise FileNotFoundError(
        "Thai font not found. Pass --font-path or set INVOICE_AUDITOR_FONT_PATH "
        "to a trusted Noto Sans Thai/TH Sarabun/Thonburi font file."
    )


def _fonts(font_path: Path) -> dict[str, ImageFont.FreeTypeFont]:
    return {
        "title": ImageFont.truetype(str(font_path), 54),
        "heading": ImageFont.truetype(str(font_path), 34),
        "body": ImageFont.truetype(str(font_path), 28),
        "small": ImageFont.truetype(str(font_path), 23),
    }


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _build_raw_record(
    *,
    index: int,
    anomaly: AnomalyType,
    rng: random.Random,
    duplicate_source: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    subtotal = Decimal(rng.randrange(2_000, 50_001)).quantize(Decimal("0.01"))
    expected_vat = (subtotal * Decimal("0.07")).quantize(Decimal("0.01"))
    expected_total = subtotal + expected_vat
    raw: dict[str, Any] = {
        "invoice_number": f"INV-2026-{index:04d}",
        "vendor_name": rng.choice(_VENDORS),
        "tax_id": _valid_tax_id(rng),
        "invoice_date": "2026-07-15",
        "subtotal": _money(subtotal),
        "vat": _money(expected_vat),
        "total": _money(expected_total),
        "currency": "THB",
    }
    expected_decision = "PASS"

    if anomaly is AnomalyType.VAT_WRONG:
        wrong_vat = expected_vat + Decimal("90.00")
        raw["vat"] = _money(wrong_vat)
        raw["total"] = _money(subtotal + wrong_vat)
        expected_decision = "REVIEW"
    elif anomaly is AnomalyType.TOTAL_MISMATCH:
        raw["total"] = _money(expected_total + Decimal("100.00"))
        expected_decision = "REJECT"
    elif anomaly is AnomalyType.MISSING_TAX_ID:
        raw["tax_id"] = None
        expected_decision = "REVIEW"
    elif anomaly is AnomalyType.DUPLICATE_INVOICE:
        if duplicate_source is None:
            raise ValueError("duplicate anomaly requires a previously generated source record")
        raw["invoice_number"] = duplicate_source["invoice_number"]
        raw["vendor_name"] = duplicate_source["vendor_name"]
        expected_decision = "REJECT"
    elif anomaly is AnomalyType.FUTURE_DATE:
        raw["invoice_date"] = "2099-12-31"
        expected_decision = "REVIEW"

    truth = {
        "anomaly_type": anomaly.value,
        "expected_decision": expected_decision,
        "business_expected": {
            "vat_rate": "0.07",
            "vat": _money(expected_vat),
            "total": _money(expected_total),
        },
    }
    return raw, truth


def _draw_template_a(
    raw: dict[str, Any],
    *,
    fonts: dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    navy, teal, grey = "#12324A", "#128C8C", "#EAF2F4"
    draw.rectangle((0, 0, 1200, 190), fill=navy)
    draw.text((70, 45), "ใบกำกับภาษี / INVOICE", font=fonts["title"], fill="white")
    draw.text(
        (70, 230),
        str(raw["vendor_name"]),
        font=fonts["heading"],
        fill=navy,
    )
    draw.text(
        (70, 285),
        f"เลขประจำตัวผู้เสียภาษี: {raw['tax_id'] or '-'}",
        font=fonts["body"],
        fill=navy,
    )
    draw.rounded_rectangle(
        (710, 225, 1120, 390),
        radius=18,
        fill=grey,
        outline=teal,
        width=3,
    )
    draw.text(
        (745, 255),
        f"เลขที่: {raw['invoice_number']}",
        font=fonts["body"],
        fill=navy,
    )
    draw.text(
        (745, 315),
        f"วันที่: {raw['invoice_date']}",
        font=fonts["body"],
        fill=navy,
    )

    top = 500
    draw.rectangle((70, top, 1130, top + 70), fill=teal)
    headers = ((100, "รายการ"), (720, "จำนวน"), (930, "ราคา"))
    for x, text in headers:
        draw.text((x, top + 17), text, font=fonts["body"], fill="white")
    rows = (("ค่าบริการระบบวิเคราะห์เอกสาร", "1", raw["subtotal"]),)
    for row_index, row in enumerate(rows):
        y = top + 95 + row_index * 80
        draw.text((100, y), row[0], font=fonts["body"], fill=navy)
        draw.text((760, y), row[1], font=fonts["body"], fill=navy)
        draw.text((930, y), str(row[2]), font=fonts["body"], fill=navy)
        draw.line((70, y + 55, 1130, y + 55), fill="#C9D8DC", width=2)

    summary_y = 900
    summary = (
        ("ยอดก่อนภาษี", raw["subtotal"]),
        ("ภาษีมูลค่าเพิ่ม 7%", raw["vat"]),
        ("ยอดรวมสุทธิ", raw["total"]),
    )
    for offset, (label, value) in enumerate(summary):
        y = summary_y + offset * 90
        if offset == 2:
            draw.rounded_rectangle((610, y - 15, 1130, y + 65), radius=12, fill=navy)
            color = "white"
        else:
            color = navy
        draw.text((650, y), label, font=fonts["body"], fill=color)
        draw.text((970, y), str(value), font=fonts["body"], fill=color, anchor="ra")
    draw.text(
        (70, 1450),
        "เอกสารสังเคราะห์สำหรับการทดสอบเท่านั้น",
        font=fonts["small"],
        fill="#687B86",
    )
    return image


def _draw_template_b(
    raw: dict[str, Any],
    *,
    fonts: dict[str, ImageFont.FreeTypeFont],
) -> Image.Image:
    image = Image.new("RGB", (1200, 1600), "#F8F6F0")
    draw = ImageDraw.Draw(image)
    brown, orange, paper = "#3B2F2F", "#C86B32", "#FFFDFC"
    draw.rounded_rectangle(
        (55, 55, 1145, 1545),
        radius=24,
        fill=paper,
        outline=brown,
        width=3,
    )
    draw.text((95, 100), "INVOICE", font=fonts["title"], fill=orange)
    draw.text((95, 195), str(raw["vendor_name"]), font=fonts["heading"], fill=brown)
    draw.text((95, 255), f"Tax ID: {raw['tax_id'] or '-'}", font=fonts["body"], fill=brown)
    draw.text(
        (790, 120),
        f"เลขที่ {raw['invoice_number']}",
        font=fonts["body"],
        fill=brown,
    )
    draw.text(
        (790, 180),
        f"วันที่ {raw['invoice_date']}",
        font=fonts["body"],
        fill=brown,
    )
    draw.line((95, 340, 1105, 340), fill=orange, width=5)
    draw.text((95, 410), "รายละเอียด", font=fonts["heading"], fill=brown)
    draw.text(
        (95, 500),
        "บริการตรวจสอบเอกสารด้วยระบบ AI",
        font=fonts["body"],
        fill=brown,
    )
    draw.text(
        (920, 500),
        str(raw["subtotal"]),
        font=fonts["body"],
        fill=brown,
        anchor="ra",
    )
    draw.line((95, 570, 1105, 570), fill="#D6CCC2", width=2)
    summary = (
        ("Subtotal", raw["subtotal"]),
        ("VAT 7%", raw["vat"]),
        ("TOTAL", raw["total"]),
    )
    for offset, (label, value) in enumerate(summary):
        y = 740 + offset * 120
        size_font = fonts["heading"] if offset == 2 else fonts["body"]
        color = orange if offset == 2 else brown
        draw.text((620, y), label, font=size_font, fill=color)
        draw.text((1040, y), str(value), font=size_font, fill=color, anchor="ra")
    draw.text((95, 1435), "สกุลเงิน / Currency: THB", font=fonts["small"], fill=brown)
    draw.text(
        (670, 1435),
        "SYNTHETIC TEST DOCUMENT",
        font=fonts["small"],
        fill=orange,
    )
    return image


def _transform(
    image: Image.Image,
    rng: random.Random,
    variant: str,
) -> tuple[Image.Image, dict[str, Any]]:
    metadata: dict[str, Any] = {
        "rotation_deg": 0.0,
        "blur_radius": 0.0,
        "brightness_factor": 1.0,
        "jpeg_quality": 92,
    }
    if variant == "clean":
        return image, metadata
    if variant == "rotate":
        angle = rng.choice((-2.0, -1.0, 1.0, 2.0))
        metadata["rotation_deg"] = angle
        transformed = image.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor="white",
        )
        return transformed, metadata
    if variant == "blur":
        radius = rng.choice((0.7, 1.0, 1.3))
        metadata["blur_radius"] = radius
        return image.filter(ImageFilter.GaussianBlur(radius)), metadata
    if variant == "dark":
        factor = rng.choice((0.75, 0.82, 0.88))
        metadata["brightness_factor"] = factor
        return ImageEnhance.Brightness(image).enhance(factor), metadata
    raise ValueError(f"unsupported variant: {variant}")


def _atomic_save_image(image: Image.Image, path: Path, *, jpeg_quality: int = 92) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.stem}.",
        suffix=path.suffix,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        image.save(temporary_path, format="JPEG", quality=jpeg_quality, optimize=True)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def generate_dataset(
    output_dir: str | Path,
    *,
    count: int = 6,
    seed: int = 42,
    font_path: str | Path | None = None,
    anomaly_cycle: tuple[AnomalyType, ...] = DEFAULT_ANOMALY_CYCLE,
    overwrite: bool = False,
) -> Path:
    if not 1 <= count <= 10_000:
        raise ValueError("count must be between 1 and 10,000")
    if not anomaly_cycle:
        raise ValueError("anomaly_cycle must not be empty")
    root = Path(output_dir).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(f"dataset already exists: {manifest_path}; pass overwrite=True")
    resolved_font = resolve_thai_font(font_path)
    fonts = _fonts(resolved_font)
    rng = random.Random(seed)  # noqa: S311 - reproducibility is the security requirement.
    image_dir = root / "images"
    record_dir = root / "records"
    image_dir.mkdir(parents=True, exist_ok=True)
    record_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    first_raw: dict[str, Any] | None = None
    variants = ("clean", "rotate", "blur", "dark")
    for offset in range(count):
        index = offset + 1
        anomaly = anomaly_cycle[offset % len(anomaly_cycle)]
        if anomaly is AnomalyType.DUPLICATE_INVOICE and first_raw is None:
            anomaly = AnomalyType.NORMAL
        raw, truth = _build_raw_record(
            index=index,
            anomaly=anomaly,
            rng=rng,
            duplicate_source=first_raw,
        )
        if first_raw is None:
            first_raw = dict(raw)
        image_id = f"SYN-{seed}-{index:04d}"
        template = "A" if index % 2 else "B"
        base_image = (
            _draw_template_a(raw, fonts=fonts)
            if template == "A"
            else _draw_template_b(raw, fonts=fonts)
        )
        variant = variants[offset % len(variants)]
        final_image, transform = _transform(base_image, rng, variant)
        image_path = image_dir / f"{image_id}.jpg"
        record_path = record_dir / f"{image_id}.json"
        _atomic_save_image(final_image, image_path, jpeg_quality=transform["jpeg_quality"])
        atomic_write_json(record_path, raw)
        entries.append(
            {
                "dataset_name": "synthetic_thai_invoice",
                "dataset_revision": f"generator-v1-seed-{seed}",
                "split": "evaluation",
                "dataset_partition": "clean" if variant == "clean" else "transformed",
                "image_id": image_id,
                "image_path": str(image_path.relative_to(root)),
                "record_path": str(record_path.relative_to(root)),
                "template": template,
                "variant": variant,
                "transformation": transform,
                "expected_fields": raw,
                "evaluable_fields": [
                    "invoice_number",
                    "vendor_name",
                    "tax_id",
                    "invoice_date",
                    "subtotal",
                    "vat",
                    "total",
                    "currency",
                ],
                **truth,
            }
        )

    manifest = {
        "schema_version": "1.0.0",
        "seed": seed,
        "count": count,
        "font_file": resolved_font.name,
        "records": entries,
    }
    atomic_write_json(manifest_path, manifest)
    append_jsonl(root / "ground_truth.jsonl", entries)
    return manifest_path
