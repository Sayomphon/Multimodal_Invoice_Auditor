# Evaluation Framework

Evaluation แยกเป็น 4 ระดับเพื่อไม่ให้ metric เดียวกลบ failure ที่ต้นเหตุแตกต่างกัน

1. Extraction: JSON validity และ field match เทียบ ground truth
2. Normalization: normalized match และ numeric accuracy ภายใน tolerance
3. Audit: anomaly precision/recall และผลของแต่ละ rule
4. Workflow: confusion matrix ของ PASS/REVIEW/REJECT, latency และ resource usage

## Error attribution

- `extractor_error`: raw field ไม่ตรงภาพ
- `normalization_error`: raw ถูกแต่แปลง date/number/currency ผิด
- `rule_error`: normalized fields ถูกแต่ rule logic ผิด
- `policy_error`: rule result ถูกแต่ severity/decision mapping ผิด
- `dataset_error`: ground truth หรือ rendered image ไม่ตรง source record

SROIE และ synthetic Thai ต้องรายงานแยกกัน รวมถึง breakdown ของ clean, rotation, blur และ JPEG compression เพื่อไม่ให้ synthetic score ถูกตีความเป็น production estimate

## Prediction denominator contract

Evaluation รับทั้ง legacy `AuditReport` JSONL และ batch record จาก `batch-inference`. หนึ่ง attempted document ต้องมีหนึ่ง record และถูกนับดังนี้:

- `success` นับเป็น valid JSON/extraction และเข้าสู่ field/rule/decision metrics
- `failed` อยู่ใน denominator และแยก `error_stage`
- invalid JSONL line อยู่ใน attempted/parse-failure denominator
- ground-truth ID ที่ไม่มี prediction อยู่ใน missing denominator
- `evaluable_fields` กำหนด denominator ต่อ field; field ที่ benchmark ไม่มี annotation ไม่ถูกนับผิด

Metrics ที่คืนประกอบด้วย attempted/success/failed/invalid/missing, field accuracy + denominator, numeric accuracy, rule/anomaly precision-recall, decision confusion, p50/p95 latency, peak VRAM max, model/profile breakdown และ error attribution by stage

## Required segments

1. `sidecar_rule_baseline` — ตรวจ deterministic pipeline เท่านั้น ห้ามอ้างเป็น VLM accuracy
2. `synthetic_vlm_clean`
3. `synthetic_vlm_transformed` — ใช้ `robustness_delta` เทียบ clean
4. `sroie_vlm`

ผลจาก model fallback ต้องรายงานแยก model/profile เพื่อไม่ให้ accuracy/latency ของ Qwen3 และ Qwen2.5 ถูกเฉลี่ยกลบกัน

## Current evidence boundary

Local tests ยืนยัน denominator/failure/segment/resource aggregation ด้วย fakes แต่ยังไม่มี actual Colab GPU predictions. ห้ามเติมค่า target ≥90% หรือ performance number ใน README/portfolio จนกว่าจะมี `reports/colab/<run_id>` ที่ผ่าน artifact validator
