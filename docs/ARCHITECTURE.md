# Architecture

## Design intent

ระบบนี้ออกแบบให้ probabilistic component มีขอบเขตแคบที่สุด VLM มีหน้าที่แปลงภาพเป็น raw fields ขณะที่ logic ที่กระทบผล audit เป็น deterministic Python และรับ configuration ที่ versioned

## Processing flow

1. `preprocessing` ตรวจชนิด ขนาด และจำนวน pixel ของภาพ ปรับ EXIF orientation, resize และลบ metadata ออกจาก object ที่ส่งให้โมเดล
2. `vlm_extractor` ส่ง prompt ที่บังคับ JSON และอนุญาต `null` เมื่อไม่พบ evidence
3. `normalizer` แปลง raw string เป็น `date` และ `Decimal` โดยไม่เดาค่าที่ parse ไม่ได้
4. `rule_engine` ประเมินกฎทางธุรกิจแบบ pure/deterministic เท่าที่ทำได้ และคืน `passed=None` เมื่อข้อมูลไม่พอ
5. `decision_policy` เลือก severity สูงสุดจากกฎที่ fail เป็น `PASS`, `REVIEW` หรือ `REJECT`
6. `pipeline` สร้าง audit report พร้อม timestamp, config version และ fingerprint สำหรับ replay

## Package boundaries

- `models.py`: domain contracts และ output schema
- `config.py`: validated rules configuration และ fingerprint
- `normalizer.py`: deterministic parsing/normalization
- `rules.py`: business rules และ duplicate store abstraction
- `decision_policy.py`: aggregate rule result เป็น decision
- `pipeline.py`: orchestration โดยไม่ผูกกับ UI หรือ model runtime
- `preprocessing.py`: image safety boundary
- `vlm_extractor.py`: optional local model adapter
- `synthetic_generator.py`: privacy-safe reproducible dataset
- `evaluation.py`: metrics และ error attribution
- `cli.py`: operator interface และ atomic output writing

## Extension points

- เปลี่ยน `DuplicateStore` เป็น Redis/SQL implementation สำหรับหลาย worker
- เพิ่ม extractor adapter สำหรับ model server โดยไม่เปลี่ยน rule engine
- เพิ่ม vendor master, PO และ GRN rules ผ่าน rule registry
- ส่ง `AuditReport` เข้า human-review queue หรือ event stream
- ย้าย configuration ไป config service ที่มี approval workflow

