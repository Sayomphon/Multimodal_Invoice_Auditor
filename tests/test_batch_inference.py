from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from invoice_auditor.batch_inference import run_batch_inference
from invoice_auditor.evaluation import read_jsonl
from invoice_auditor.models import ModelTrace, RawInvoiceData
from invoice_auditor.preprocessing import UnsafeImageError
from tests.helpers import valid_raw


class _BatchExtractor:
    def load(self) -> None:
        return None

    def extract(self, image_path: str | Path) -> tuple[RawInvoiceData, ModelTrace]:
        if Path(image_path).name.startswith("bad"):
            raise UnsafeImageError("unsafe test image")
        trace = ModelTrace(
            model_id="fake",
            model_revision="a" * 40,
            prompt_version="test",
            generation_parameters={},
            latency_ms=10,
            raw_response="sensitive",
        )
        return RawInvoiceData.model_validate(valid_raw()), trace

    def release(self) -> None:
        return None


class BatchInferenceTests(unittest.TestCase):
    def test_every_attempt_produces_success_or_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "images").mkdir()
            (root / "images/good.png").write_bytes(b"placeholder")
            (root / "images/bad.png").write_bytes(b"placeholder")
            manifest = {
                "records": [
                    {"image_id": "good", "image_path": "images/good.png"},
                    {"image_id": "bad", "image_path": "images/bad.png"},
                ]
            }
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = run_batch_inference(
                root / "manifest.json",
                root / "predictions.jsonl",
                _BatchExtractor(),
                public_output=True,
            )
            records, errors = read_jsonl(root / "predictions.jsonl")
            self.assertFalse(errors)
            self.assertEqual(result.attempted, 2)
            self.assertEqual(result.successful, 1)
            self.assertEqual(result.failed, 1)
            self.assertEqual([record["status"] for record in records], ["success", "failed"])
            self.assertIsNone(records[0]["runtime"]["raw_response"])
            self.assertEqual(records[1]["error_stage"], "preprocess")


if __name__ == "__main__":
    unittest.main()
