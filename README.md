# Multimodal Invoice Auditor

ระบบตัวอย่างสำหรับรับภาพ Invoice/Receipt, สกัดข้อมูลแบบ structured, normalize ค่า และตรวจด้วยกฎธุรกิจที่ deterministic ก่อนตัดสิน `PASS`, `REVIEW` หรือ `REJECT` พร้อม audit trail

จุดออกแบบหลักคือการแยก trust boundary: Vision-Language Model (VLM) ทำหน้าที่อ่านเอกสารเท่านั้น ส่วนการแปลงชนิดข้อมูล การคำนวณ VAT/ยอดรวม การตรวจ duplicate และ decision policy อยู่ใน Python ที่ version, test และ audit ได้

## Architecture

```text
Image -> Safe preprocessing -> VLM extraction -> RawInvoiceData
                                                |
                                                v
Audit JSON -> Normalization -> NormalizedInvoice -> Rule Engine -> Decision Policy
                                                        |               |
                                                        +---- AuditReport
```

Core pipeline ไม่โหลดโมเดลและไม่เรียก external API โดยอัตโนมัติ การติดตั้ง VLM เป็น optional extra เพื่อให้ business logic รันใน CI/CPU ได้โดยไม่ต้องใช้ GPU

รายละเอียดเพิ่มเติมอยู่ที่ [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/SECURITY.md](docs/SECURITY.md) และ [docs/OPERATIONS.md](docs/OPERATIONS.md)

## Quick start

ต้องใช้ Python 3.11 ขึ้นไป

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

invoice-auditor generate-synthetic --output-dir data/synthetic --count 6 --seed 42
invoice-auditor audit-json data/synthetic/records/SYN-42-0001.json
python -m pytest
```

คำสั่ง `generate-synthetic` สร้าง source JSON, rendered invoice และ manifest แบบ reproducible โดยไม่ใช้เอกสารลูกค้าจริง

## VLM inference (optional)

```bash
python -m pip install -e ".[vlm]"
invoice-auditor audit-image path/to/invoice.png \
  --model Qwen/Qwen3-VL-4B-Instruct \
  --output reports/audit.json
```

โมเดลจะถูกดาวน์โหลดเมื่อเรียก `audit-image` พร้อม `--allow-download` เท่านั้น ค่าเริ่มต้นใช้เฉพาะ model cache ในเครื่อง ควร pin model revision ที่ผ่านการทดสอบใน production และตรวจ model/data license ตามนโยบายองค์กร

## Local demo UI (optional)

```bash
python -m pip install -e ".[vlm,demo]"
invoice-auditor demo --model Qwen/Qwen3-VL-4B-Instruct
```

UI bind เฉพาะ `127.0.0.1` และไม่เปิด Gradio share link เพื่อลดความเสี่ยงส่งเอกสารออกสู่ public endpoint โดยไม่ตั้งใจ

## Core outputs

- `raw`: ค่าที่ extractor ส่งกลับ โดยอนุญาต `null` และไม่เดาค่าที่ไม่มี evidence
- `normalized`: วันที่ จำนวนเงิน สกุลเงิน และ Tax ID หลัง deterministic normalization
- `normalization_issues`: ปัญหาที่พบโดยไม่กลบ error
- `rules`: ผลแต่ละกฎพร้อม observed, expected, severity และเหตุผล
- `decision`: ผลรวมตาม policy ที่ versioned
- `config_fingerprint`: SHA-256 ของ rule configuration เพื่อรองรับ audit/replay

## Scope

MVP รองรับเอกสารภาพหน้าเดียวและ 8 fields ได้แก่ invoice number, vendor, Tax ID, invoice date, subtotal, VAT, total และ currency รวมถึงกฎ required fields, total consistency, VAT rate, Tax ID format, duplicate invoice และ future date

ไม่ครอบคลุม line-item extraction, multi-page workflow, ERP/PO/GRN reconciliation, fraud forensics หรือคำวินิจฉัยทางบัญชีและภาษี

## Privacy

ห้าม commit invoice จริงที่มี PII หรือข้อมูลการค้าเข้า repository สาธารณะ ใช้ synthetic/public data สำหรับ demo และใช้ `--public-output` เมื่อต้องการ mask vendor/Tax ID ในผลลัพธ์ที่จะเผยแพร่

## Project documentation

- [Implementation log](docs/IMPLEMENTATION_LOG.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security and governance](docs/SECURITY.md)
- [Operations](docs/OPERATIONS.md)
- [Evaluation](docs/EVALUATION.md)
