# Multimodal Invoice Auditor

A reference implementation for ingesting invoice or receipt images, extracting structured data, normalizing values, and applying deterministic business rules to produce a `PASS`, `REVIEW`, or `REJECT` decision with an auditable trail.

The central design principle is a clear trust boundary: the Vision-Language Model (VLM) reads the document, while Python code performs type conversion, VAT and total calculations, duplicate checks, and decision policy evaluation. This keeps financial decisions versioned, testable, and reproducible.

> **Release status:** the local implementation gates are complete. Clean Google Colab GPU acceptance is still pending, so no actual VLM quality metric is presented as verified.

## Architecture

```text
Image or single-page PDF
        |
        v
Safe preprocessing --> VLM extraction --> RawInvoiceData
                                              |
                                              v
Audit JSON <-- Decision policy <-- Rule engine <-- Normalization <-- NormalizedInvoice
```

The core pipeline does not load a model or call an external API automatically. VLM support is an optional dependency, which allows business logic and tests to run on CPU-based CI environments without a GPU.

Version 0.2.0 adds Google Colab orchestration, GPU/VRAM telemetry, a strict primary/fallback model registry, per-attempt batch records, segmented VLM evaluation, SROIE manifest tooling, and safe single-page PDF rendering.

For design, security, and operating details, see the [architecture](docs/ARCHITECTURE.md), [security](docs/SECURITY.md), and [operations](docs/OPERATIONS.md) documentation.

## Capabilities

- Extract eight core fields: invoice number, vendor, Tax ID, invoice date, subtotal, VAT, total, and currency.
- Normalize dates, amounts, currencies, and Tax IDs deterministically.
- Evaluate required fields, total consistency, VAT rate, Tax ID format, duplicate invoices, and future dates.
- Preserve raw extractor output, normalization issues, per-rule evidence, decision policy versioning, and a configuration fingerprint for audit and replay.
- Process images or bounded, single-page PDFs without invoking shell tools from a document path.
- Run model inference in batches with one success or failure record for every attempted input.
- Mask vendor and Tax ID values when writing outputs intended for publication.

## Requirements

- Python 3.11 or later
- A CUDA-capable GPU for local VLM inference (optional)
- Google Colab with a GPU runtime for the Colab acceptance workflow (pending verification)

## Quick start

Create a virtual environment, install the development dependencies, generate reproducible synthetic invoices, and run an audit:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

invoice-auditor generate-synthetic --output-dir data/synthetic --count 6 --seed 42
invoice-auditor audit-json data/synthetic/records/SYN-42-0001.json
python -m pytest
```

`generate-synthetic` creates source JSON, rendered invoice images, and a manifest without using real customer documents.

## Optional VLM inference

Install the VLM extra, then audit an invoice image. Model weights are downloaded only when `--allow-download` is supplied.

```bash
python -m pip install -e ".[vlm]"
invoice-auditor audit-image path/to/invoice.png \
  --allow-download \
  --output reports/audit.json
```

When `--model` is omitted, the CLI uses [`config/models.colab.json`](config/models.colab.json). It checks GPU/VRAM eligibility and uses the configured fallback only for allowlisted out-of-memory or compatibility failures. JSON, schema, and preprocessing errors never trigger model fallback.

Run batch inference from a manifest:

```bash
invoice-auditor batch-inference data/synthetic/manifest.json \
  --output reports/predictions.jsonl \
  --allow-download \
  --public-output
```

The model instance is reused across the batch, and every attempted image or PDF produces exactly one `success` or `failed` record.

## Google Colab workflow

- Start with [`notebooks/00_colab_bootstrap.ipynb`](notebooks/00_colab_bootstrap.ipynb) for an environment smoke test.
- Run [`notebooks/02_vlm_extraction_pipeline.ipynb`](notebooks/02_vlm_extraction_pipeline.ipynb) independently for one-image and golden-set inference.
- Use [`notebooks/03_evaluation_and_demo.ipynb`](notebooks/03_evaluation_and_demo.ipynb) for segmented metrics and a redacted audit view.
- Follow the two-pass freeze and acceptance procedure in the [Google Colab runbook](docs/COLAB_RUNBOOK.md).

`requirements-colab.lock` and the current model SHAs are candidates. Change their status to verified only after the clean Colab GPU acceptance run succeeds.

## Single-page PDF input

Install the PDF extra and use the existing `audit-image` or batch-manifest commands:

```bash
python -m pip install -e ".[vlm,pdf]"
invoice-auditor audit-image synthetic-invoice.pdf --allow-download
```

PDF input must contain one page and pass file-size, header, page-count, DPI, dimension, and total-pixel limits. The document is rendered in memory through PDFium; no shell or Poppler command is constructed from an input path.

## SROIE evaluation subset

Raw SROIE images are not committed to this repository. After confirming the dataset licence, prepare a deterministic local subset with:

```bash
python scripts/prepare_sroie.py \
  --source local \
  --input-dir /path/to/licensed/SROIE \
  --output-dir data/sroie_subset \
  --revision licensed-local-copy-v1 \
  --license-reference /path/to/license-review.md \
  --count 50 --seed 42
```

The generated manifest records SHA-256 checksums and `evaluable_fields`. A field not available in SROIE is excluded from scoring instead of being treated as an incorrect prediction.

## Local demo UI

```bash
python -m pip install -e ".[vlm,demo]"
invoice-auditor demo --model Qwen/Qwen3-VL-4B-Instruct
```

The UI binds only to `127.0.0.1` and does not enable a Gradio share link, preventing accidental publication of sensitive documents to a public endpoint.

## Audit report contents

Each audit report contains:

- `raw`: values returned by the extractor; absent evidence remains `null` rather than being guessed.
- `normalized`: dates, amounts, currency, and Tax ID after deterministic normalization.
- `normalization_issues`: detected conversion problems without hiding the original error.
- `rules`: each rule result with observed value, expected value, severity, and explanation.
- `decision`: the aggregated result produced by the versioned decision policy.
- `config_fingerprint`: a SHA-256 fingerprint of the rule configuration for auditability and replay.

## Scope and limitations

This MVP supports single-page image documents and the eight core fields above. It does not cover line-item extraction, multi-page workflows, ERP/PO/GRN reconciliation, fraud forensics, or accounting and tax opinions.

## Privacy and publication safety

Do not commit real invoices containing PII or commercially sensitive data to a public repository. Use synthetic or licensed public data for demonstrations. Add `--public-output` when generating output that may be shared externally so vendor and Tax ID values are masked.

## Development checks

```bash
python -m pytest
ruff check src tests
```

## Project documentation

- [Implementation log](docs/IMPLEMENTATION_LOG.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Security and governance](docs/SECURITY.md)
- [Operations](docs/OPERATIONS.md)
- [Evaluation](docs/EVALUATION.md)
- [Google Colab runbook](docs/COLAB_RUNBOOK.md)
