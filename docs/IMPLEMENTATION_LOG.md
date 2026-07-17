# Implementation Log

เอกสารนี้บันทึกสิ่งที่ดำเนินการกับ repository และผลการตรวจสอบ เพื่อให้สามารถ audit และส่งต่องานได้

## 2026-07-17 — Repository bootstrap

- อ่านและสรุป Project Blueprint จาก `03_Multimodal_Invoice_Auditor_5Day_Plan_TH.docx`
- ยืนยันว่าโฟลเดอร์เริ่มต้นยังไม่มี source code และยังไม่เป็น Git repository
- ตรวจ model card ทางการของ Qwen3-VL-4B-Instruct และ Qwen2.5-VL-3B-Instruct เพื่อกำหนด integration contract ผ่าน Transformers
- เลือก Python 3.11+ และจัดโครงสร้างแบบ `src/` layout
- แยก core dependencies ออกจาก optional VLM dependencies เพื่อให้ test business logic ได้โดยไม่ใช้ GPU
- เพิ่ม configuration, package metadata, ignore rules และเอกสาร architecture/security/operations/evaluation
- พัฒนา Pydantic domain models ที่ปฏิเสธ unknown fields และสร้าง public serialization สำหรับ mask vendor/Tax ID
- พัฒนา conservative normalization สำหรับ Decimal, วันที่ ค.ศ./พ.ศ., currency และ Tax ID โดยเก็บ parse failure แยกไว้ใน audit report
- พัฒนา deterministic rules 6 รายการ, Thai Tax ID checksum, thread-safe in-memory duplicate store และ decision policy
- พัฒนา end-to-end audit pipeline พร้อม UTC timestamp, config version และ SHA-256 config fingerprint
- เพิ่ม bounded JSON/model-output parser, atomic owner-only output writing และ image safety boundary
- เพิ่ม optional Qwen VLM adapter แบบ lazy load โดยปิด model download เป็นค่าเริ่มต้น
- เพิ่ม synthetic Thai invoice generator 2 templates พร้อม normal/anomaly labels และ rotation/blur/brightness variants
- เพิ่ม batch audit, evaluation metrics, CLI commands และ loopback-only Gradio demo adapter
- เพิ่ม thin notebooks 3 ไฟล์สำหรับ data generation, extraction/audit และ evaluation
- เพิ่ม test fixtures สำหรับ PASS/REVIEW/REJECT, GitHub Actions CI, Dockerfile แบบ non-root และ Makefile
- Initialize Git repository ด้วย default branch `main`; ยังไม่ได้สร้าง commit

## Security and quality decisions

- Core runtime ไม่มี API key และไม่เรียก network โดยอัตโนมัติ
- CLI ไม่รับ image URL และจำกัด file size, extension, pixel count และ model-output size
- VLM output ต้องเป็น JSON object เดียวและ schema ไม่อนุญาต extra keys
- จำนวนเงินใช้ `Decimal`; ไม่ใช้ `float` ใน financial rules
- Output file ใช้ atomic replacement และ permission `0600`
- Demo UI bind เฉพาะ `127.0.0.1`, ปิด public share และจำกัด upload 20 MB
- ตรวจภาพ synthetic จริงและพบว่า Thonburi แสดง Thai combining marks ไม่สมบูรณ์เมื่อ Pillow ไม่มี libraqm จึงปรับ fallback ให้เลือก Sukhumvit/Tahoma/Arial Unicode ก่อน และตรวจภาพซ้ำแล้ว

## Verification record

- `compileall` สำหรับ `src/` และ `tests/`: ผ่าน
- ตรวจ notebook ทั้ง 3 ไฟล์ว่าเป็น JSON ที่ถูกต้อง: ผ่าน
- Unit/integration tests: ผ่าน 23/23 tests
- Synthetic smoke dataset: 6 เอกสาร, 2 templates และ 4 image variants
- Batch audit smoke test: PASS 1, REVIEW 3, REJECT 2 ตรง expected labels
- Sidecar baseline evaluation: field accuracy 1.0 ทุก field, numeric accuracy 1.0, decision accuracy 1.0, anomaly precision/recall 1.0
- Public-output smoke test: vendor ถูก redact และ Tax ID เหลือเฉพาะ 4 ตัวท้าย
- Python wheel build แบบ no-dependency/no-isolation: ผ่าน (`multimodal_invoice_auditor-0.1.0-py3-none-any.whl`)
- Docker `build --check`: ผ่านและไม่พบ warning
- ตรวจหา risky code patterns เช่น dynamic `eval/exec`, shell execution, pickle, unsafe YAML และ HTTP client ใน core: ไม่พบ (คำว่า `.eval()` ที่พบเป็น PyTorch model evaluation mode)

## Verification boundary

- ยังไม่ได้ดาวน์โหลดหรือรัน Qwen model จริง เนื่องจากต้องใช้ optional VLM dependencies, model weights และ GPU runtime การตรวจรอบนี้ครอบคลุม adapter contract, safe failure เมื่อ dependency ไม่มี, deterministic pipeline และ synthetic sidecar baseline
- ยังไม่ได้รัน GitHub Actions บน remote; workflow ถูกเตรียมให้รัน Python 3.11/3.12, Ruff และ pytest เมื่อ push repository
- Synthetic baseline score 1.0 เป็นการตรวจความถูกต้องของ pipeline/rules ไม่ใช่การวัด VLM extraction accuracy หรือ production performance

## 2026-07-17 — Initial GitHub release preparation

- เชื่อม local repository กับ private remote `Sayomphon/Multimodal_Invoice_Auditor`
- ตรวจพบ remote initial commit ที่มี Apache-2.0 `LICENSE` และ placeholder `README.md`
- กำหนดให้คง `LICENSE` จาก remote และใช้ README ฉบับ implementation แทน placeholder
- ไม่รวมไฟล์ Word blueprint ต้นฉบับใน code release และเพิ่ม `*.docx` ใน `.gitignore`
- เตรียม publish โดยรักษา remote history และไม่ใช้ force push
- Push initial implementation commit `d07011a` ไปยัง `origin/main` สำเร็จ
- GitHub Actions รอบแรกพบ Ruff lint findings 9 รายการ ซึ่งเป็น import modernization, explicit `zip(strict=True)`, simplification, unused import และ false positives ของ Bandit rules สำหรับ `PASS` decision/random synthetic seed
- แก้ lint findings โดยไม่เปลี่ยน business behavior และเตรียม follow-up CI fix commit
- ตรวจซ้ำหลังแก้ด้วย `ruff check src tests`: ผ่าน
- ตรวจซ้ำด้วย unit/integration tests: ผ่าน 23/23 tests
- Push follow-up commit `5617593` (`Fix CI lint checks`) ไปยัง `origin/main` สำเร็จ โดยไม่ใช้ force push
- GitHub Actions run `29592184295`: ผ่านทั้ง Python 3.11 และ 3.12 (install, lint และ test)
