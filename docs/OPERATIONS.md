# Operations

## Runtime profiles

- `core`: CPU-only สำหรับ JSON audit, rules, synthetic generation และ metrics
- `vlm-local`: GPU runtime สำหรับ Qwen inference; batch size เริ่มต้น 1
- `model-server`: production extension ที่แยก GPU serving ออกจาก audit workers
- `colab-candidate`: interactive POC/portfolio flow; require CUDA, batch=1 และ public/redacted artifacts

Synthetic Thai rendering ต้องใช้ฟอนต์ที่รองรับภาษาไทย และควรใช้ Pillow build ที่มี libraqm/HarfBuzz เมื่อฟอนต์ต้องพึ่ง complex text shaping ตรวจภาพตัวอย่างก่อนใช้ dataset ทุกครั้ง

## Recommended production topology

1. Upload service ตรวจ file type/size และเก็บ encrypted object
2. Queue ส่ง document ID ไป preprocessing/extraction worker
3. Model server คืน raw JSON + model metadata
4. Audit worker normalize, evaluate rules และบันทึก immutable report
5. REVIEW/REJECT ถูก route ไป human-review queue
6. Metrics/trace ส่งไป observability platform โดยไม่ log PII

## Observability

ติดตาม JSON validity, missing-field rate, field accuracy จาก sampled labels, rule failure distribution, decision distribution, latency, peak memory, model/parser error และ drift แยกตาม vendor/template

สำหรับ Colab/batch ให้ติดตาม `model_load_ms`, `preprocess_ms`, `inference_ms`, total `latency_ms`, `peak_vram_mb`, `fallback_from/reason` และ error stage. CPU mode ต้องใช้ `peak_vram_mb=null`; ห้ามใช้ `0` แทน unavailable telemetry

## Configuration changes

การเปลี่ยน VAT/tolerance/severity ต้องเพิ่ม test case, review config diff, update version และเก็บ fingerprint ใน output ไม่ควรแก้ค่าโดยตรงใน running container

## Clean-room verification

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
invoice-auditor generate-synthetic --output-dir /tmp/invoice-demo --count 3 --seed 42
invoice-auditor audit-json /tmp/invoice-demo/records/INV-2026-0001.json
```

Colab release ใช้ two-pass clean-runtime protocol และ artifact validator ตาม `docs/COLAB_RUNBOOK.md`; local CPU CI ไม่สามารถทดแทน GPU integration gate ได้
