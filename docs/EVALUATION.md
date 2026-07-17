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

