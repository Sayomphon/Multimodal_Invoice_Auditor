# Google Colab Runbook

## Current release status

โค้ดและ local CPU gates สำหรับ Colab flow ถูก implement แล้ว แต่ release ยังอยู่สถานะ **candidate / external acceptance pending** เพราะ repository นี้ยังไม่ได้รัน model weights บน clean Google Colab GPU. ดังนั้นห้ามเปลี่ยน `config/models.colab.json.acceptance_status` เป็น `colab_verified` หรืออ้าง actual VLM metrics จนกว่าจะทำ two-pass protocol ด้านล่างครบ

ไฟล์ `requirements-colab.lock` เป็น candidate direct pin set สำหรับ smoke test แรก ไม่ใช่หลักฐานว่าเข้ากันได้กับ Colab image ปัจจุบัน เนื่องจาก Google เปลี่ยน GPU type, CUDA image และ usage limits ได้โดยไม่รับประกัน

## Security prerequisites

- ใช้เฉพาะ synthetic/public data; ห้ามใช้ invoice จริง, PII, Tax ID หรือข้อมูลการค้าของลูกค้า
- Notebook ไม่ mount Google Drive และไม่เปิด Gradio/public tunnel โดยอัตโนมัติ
- ถ้า repository ยังเป็น private ให้สร้าง Colab Secret ชื่อ `GITHUB_TOKEN` แบบ read-only repository scope. Notebook ส่ง secret ผ่าน temporary Git config environment และไม่เขียนลง artifact
- Model download ต้องเปิดอย่างชัดเจนด้วย `allow_download=True`; core tests และ import ไม่เรียก network
- Output ที่เผยแพร่ต้องมาจาก `public_output=True` และผ่าน `validate-artifacts`

## Entry points

1. `notebooks/00_colab_bootstrap.ipynb` — clone/checkout, install, import และ environment smoke โดยยังไม่โหลด weights
2. `notebooks/02_vlm_extraction_pipeline.ipynb` — standalone bootstrap, preflight, synthetic generation, one-image smoke, batch inference และ artifacts
3. `notebooks/03_evaluation_and_demo.ipynb` — segmented metrics, failure accounting และ redacted presentation

ตั้ง runtime เป็น GPU ก่อนเริ่ม notebook 02. สามารถ pin application revision โดยกำหนด environment variable `INVOICE_AUDITOR_REF` เป็น full Git SHA; หากไม่กำหนด notebook จะ resolve `main` เป็น full SHA และบันทึก SHA จริงใน run manifest

## What the bootstrap records

`environment.json` บันทึก Python/platform, package versions, CUDA availability/version, GPU name, compute capability, total/free VRAM และ disk free. CPU/missing package ถูกบันทึกเป็น `false`/`null` โดยไม่ปลอมค่าเป็นศูนย์

`run_manifest.json` บันทึก application commit, SHA-256 ของ dependency lock, model registry, timestamps และ public/redacted flag. ทุก prediction มี model/revision/profile, device/dtype, load/preprocess/inference/total latency, peak VRAM และ fallback provenance

## Primary/fallback policy

1. Preflight ตรวจ CUDA และ free VRAM ก่อนโหลด model
2. พยายาม primary `Qwen/Qwen3-VL-4B-Instruct` เมื่อผ่าน threshold
3. ใช้ fallback `Qwen/Qwen2.5-VL-3B-Instruct` เฉพาะ preflight VRAM, allowlisted CUDA OOM หรือ known model/dependency compatibility error
4. Parser error, schema error, unsafe image/PDF และ audit errorไม่เปลี่ยน model
5. ก่อน fallback หลัง OOM จะ release model/processor references, run garbage collection และ empty CUDA cache
6. 4-bit profile รองรับแบบ explicit ใน code แต่ไม่อยู่ใน candidate registry เพราะยังไม่มี accuracy/compatibility comparison

Model revisions ใน registry เป็น immutable upstream SHAs ที่ resolve ณ วันที่ implement แต่ยังไม่ถือว่า “tested SHA” จนกว่าจะผ่าน acceptance run

## Two-pass clean-runtime acceptance

### Pass 1 — Candidate smoke and freeze

1. เริ่ม Colab GPU runtime ใหม่
2. รัน notebook 00 และยืนยัน Python/package/CUDA/GPU/VRAM
3. รัน notebook 02 ถึง one-image smoke
4. ถ้า dependency/model load ไม่ผ่าน ให้แก้ candidate versions ใน source repository ไม่ทำ ad-hoc pip patch ใน `/content`
5. เมื่อ one-image ผ่าน ให้ freeze dependency graph ที่ใช้งานจริงและบันทึก model revisions ที่โหลดจริง
6. Sync root registry กับ packaged copy ใน `src/invoice_auditor/resources/`, commit candidate lock/registry ที่ freeze แล้ว; ยังไม่เปลี่ยน acceptance status

### Pass 2 — Release acceptance from zero

1. Factory reset/delete runtime แล้วเปิด GPU runtime ใหม่
2. Checkout exact application commit จาก Pass 1
3. รัน notebooks ตามลำดับโดยไม่แก้ cell, source หรือ pip command
4. รัน synthetic golden setอย่างน้อย 5 attempts; ทุก attempt ต้องมี success/failed record
5. ยืนยัน raw extraction, normalized fields, rule math, decision และ complete trace ใน successful records
6. รัน evaluation และ artifact validator
7. เก็บ failure samples และตรวจว่า public artifacts ไม่มี raw response, absolute temp/Drive path หรือ PII
8. เมื่อทุก gate ผ่าน จึงเปลี่ยน registry status เป็น `colab_verified`, อัปเดต implementation log ด้วย run ID/hardware/metrics และ commit actual redacted evidence

คำสั่ง validator ที่เทียบเท่า notebook:

```bash
invoice-auditor validate-artifacts reports/colab/<run_id> --minimum-attempts 5
```

## Expected artifacts

```text
reports/colab/<run_id>/
├── environment.json
├── predictions.jsonl
├── metrics.json
└── run_manifest.json
```

หนึ่งบรรทัดใน `predictions.jsonl` เท่ากับหนึ่ง attempted document. Failure ต้องมี `error_stage`, `error_type`, `error_message`; success ต้องมี `audit_report` และ `runtime`. `source_path` ต้องเป็น relative/logical path เท่านั้น

## Troubleshooting

- `cuda_unavailable`: เปลี่ยน runtime type เป็น GPU; อย่าปล่อยให้ acceptance ใช้ CPU โดยเงียบ
- `insufficient_vram`: runtime ที่ได้รับไม่พอทั้ง primary/fallback; เริ่ม runtime ใหม่หรือใช้ dedicated GPU. อย่าลด threshold โดยไม่มี smoke evidence
- `cuda_oom`: runtime จะ fallback ได้หนึ่งครั้งตาม allowlist; ตรวจ `fallback_from`/`fallback_reason`
- `compatibility_error`: เปลี่ยน candidate dependency ใน repository แล้วเริ่ม clean smoke ใหม่
- `parse`/`schema`: ปรับ prompt/parser/evaluation; ห้ามใช้ fallback เพื่อซ่อน invalid output
- PDF หลายหน้า: แยกหน้าอย่างปลอดภัยก่อน upload; MVP รับหนึ่งหน้าเท่านั้น

## Cost and operational notes

Model weightsประมาณ 7.5–8.9 GB ก่อน runtime overhead และ Colab resource ไม่รับประกัน. Cache ลด download time แต่ acceptance รอบสุดท้ายต้องพิสูจน์ fresh runtime. สำหรับ production ในไทยควรย้าย inference ไป controlled GPU service พร้อม IAM, encryption, PDPA controls, retention policy, centralized audit logging และ human-review workflow; Colab เหมาะกับ POC/portfolio evidence ไม่ใช่ production document processing
