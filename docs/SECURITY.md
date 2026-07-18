# Security and Governance

## Security defaults

- ไม่รับ image URL จาก CLI เพื่อลด SSRF และ uncontrolled network access
- จำกัด input file size, image dimensions และ total pixels ก่อน inference
- ใช้ Pillow verify/load ภายใต้ decompression-bomb guard
- VLM dependency เป็น optional และไม่มี model download ระหว่าง core tests
- JSON parser จำกัดขนาด output และรับ object เดียวเท่านั้น
- เขียน output แบบ atomic replacement เพื่อลดไฟล์ครึ่งสมบูรณ์
- มี public serialization สำหรับ mask vendor name และ Tax ID
- PDF รับหนึ่งหน้า, render เข้า memory ผ่าน PDFium และจำกัด bytes/page/DPI/dimensions/pixels
- Batch public artifact เก็บเฉพาะ relative/logical source path และลบ raw model response
- Model fallback ใช้ allowlist; parser/schema/unsafe input ไม่ทำให้เปลี่ยน model โดยเงียบ

## Data classification

Invoice จริงอาจมี PII, Tax ID, bank/payment information และข้อมูลการค้า จึงไม่ควร commit เข้า source control ใช้ synthetic หรือ public benchmark สำหรับ repository และกำหนด encryption, access control, retention และ audit logging ก่อนใช้ข้อมูล production

Colab เป็น third-party managed runtime และไม่ใช่ production-controlled environment. Notebook จึงไม่ mount Drive, ไม่เปิด public tunnel และเตือนให้ใช้ synthetic/public data. Private Git token ต้องมาจาก Colab Secret/read-only scope และไม่ถูกเขียนลง environment/run artifacts

## Model governance

- Pin model revision และ Transformers version ที่ผ่าน validation
- Registry status `candidate_unverified` ต้องไม่ถูกตีความว่าเป็น tested model/dependency set
- บันทึก model ID/revision, prompt version และ generation parameters ทุกครั้ง
- ห้ามใช้ VLM decision เป็นคำรับรองทางภาษีหรือบัญชี
- กรณี missing evidence, parser failure หรือ low confidence ต้องเข้าสู่ human review

## Rule governance

VAT rate, monetary tolerance, required fields และ severity เป็น configuration ที่ต้องผ่าน test/approval การตรวจ Tax ID ใน MVP ตรวจเพียงรูปแบบและ checksum ไม่ยืนยันตัวตนหรือสถานะนิติบุคคล

## Production gaps

ก่อน production ต้องเพิ่ม authentication/authorization, secrets management, encrypted storage, malware scanning, centralized duplicate index, vendor/PO/GRN integration, retention/deletion workflow, monitoring, incident response และ PDPA impact assessment
