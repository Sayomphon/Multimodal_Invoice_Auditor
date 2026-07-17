from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from invoice_auditor.evaluation import evaluate_jsonl
from invoice_auditor.io_utils import append_jsonl
from invoice_auditor.pipeline import InvoiceAuditPipeline
from invoice_auditor.synthetic_generator import generate_dataset, resolve_thai_font
from tests.helpers import NOW


class SyntheticEvaluationTests(unittest.TestCase):
    def test_end_to_end_sidecar_evaluation(self) -> None:
        try:
            font = resolve_thai_font()
        except FileNotFoundError:
            self.skipTest("Thai font not available in this runtime")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "dataset"
            manifest_path = generate_dataset(root, count=6, seed=42, font_path=font)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            pipeline = InvoiceAuditPipeline()
            predictions = []
            for entry in manifest["records"]:
                raw = json.loads((root / entry["record_path"]).read_text(encoding="utf-8"))
                report = pipeline.audit(raw, source_id=entry["image_id"], now=NOW)
                predictions.append(report.model_dump(mode="json"))
            predictions_path = append_jsonl(root / "predictions.jsonl", predictions)
            metrics = evaluate_jsonl(root / "ground_truth.jsonl", predictions_path)
            self.assertEqual(metrics["counts"]["ground_truth"], 6)
            self.assertEqual(metrics["decision_accuracy"], 1.0)
            self.assertEqual(metrics["numeric_accuracy"], 1.0)
            self.assertEqual(metrics["json_validity_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()

