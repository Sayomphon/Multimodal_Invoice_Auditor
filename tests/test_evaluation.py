from __future__ import annotations

import unittest

from invoice_auditor.evaluation import evaluate


def _truth(image_id: str, segment: str) -> dict[str, object]:
    return {
        "image_id": image_id,
        "dataset_segment": segment,
        "expected_fields": {"vendor_name": "Vendor", "total": "107.00"},
        "evaluable_fields": ["vendor_name", "total"],
        "expected_decision": "PASS",
    }


def _success(image_id: str, latency: int) -> dict[str, object]:
    return {
        "image_id": image_id,
        "source_path": f"images/{image_id}.png",
        "status": "success",
        "error_stage": None,
        "error_type": None,
        "error_message": None,
        "audit_report": {
            "source_id": image_id,
            "normalized": {"vendor_name": "Vendor", "total": "107.00"},
            "decision": "PASS",
        },
        "runtime": {
            "model_id": "fake",
            "runtime_profile": "standard",
            "latency_ms": latency,
            "peak_vram_mb": 1000,
        },
    }


class EvaluationTests(unittest.TestCase):
    def test_failures_and_missing_records_remain_in_denominators(self) -> None:
        truth = [
            _truth("clean", "synthetic_vlm_clean"),
            _truth("failed", "synthetic_vlm_transformed"),
            _truth("missing", "synthetic_vlm_transformed"),
        ]
        predictions = [
            _success("clean", 10),
            {
                "image_id": "failed",
                "source_path": "images/failed.png",
                "status": "failed",
                "error_stage": "parse",
                "error_type": "ModelOutputError",
                "error_message": "invalid JSON",
                "audit_report": {},
                "runtime": {},
            },
        ]
        metrics = evaluate(truth, predictions)
        self.assertEqual(metrics["counts"]["attempted"], 3)
        self.assertEqual(metrics["counts"]["failed_predictions"], 1)
        self.assertEqual(metrics["counts"]["missing_predictions"], 1)
        self.assertEqual(metrics["field_denominators"]["vendor_name"], 3)
        self.assertAlmostEqual(metrics["field_accuracy"]["vendor_name"], 1 / 3)
        self.assertAlmostEqual(metrics["json_validity_rate"], 1 / 3)
        self.assertEqual(metrics["p50_latency_ms"], 10.0)
        self.assertEqual(metrics["error_attribution_by_stage"], {"parse": 1})
        self.assertIn("synthetic_vlm_clean", metrics["segments"])
        self.assertIsNotNone(metrics["robustness_delta"])


if __name__ == "__main__":
    unittest.main()
