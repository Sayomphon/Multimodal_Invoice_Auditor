from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from invoice_auditor.artifacts import validate_run_artifacts


class ArtifactValidationTests(unittest.TestCase):
    def test_valid_local_public_run_passes_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = {
                "colab": False,
                "cuda_available": False,
                "packages": {
                    "torch": "2.8.0",
                    "transformers": "4.57.1",
                    "accelerate": "1.10.1",
                    "safetensors": "0.6.2",
                },
            }
            (root / "environment.json").write_text(json.dumps(environment), encoding="utf-8")
            (root / "run_manifest.json").write_text(
                json.dumps({"application_commit": "a" * 40}), encoding="utf-8"
            )
            runtime = {
                "model_id": "fake",
                "model_revision": "b" * 40,
                "prompt_version": "v1",
                "runtime_profile": "standard",
                "device": "cuda:0",
                "dtype": "bfloat16",
                "torch_version": "2.8.0",
                "transformers_version": "4.57.1",
                "model_load_ms": 1,
                "preprocess_ms": 1,
                "inference_ms": 1,
                "latency_ms": 3,
                "raw_response": None,
            }
            prediction = {
                "run_id": "test",
                "image_id": "one",
                "source_path": "images/one.png",
                "status": "success",
                "error_stage": None,
                "error_type": None,
                "error_message": None,
                "audit_report": {
                    "raw": {},
                    "normalized": {},
                    "rules": [],
                    "decision": "PASS",
                },
                "runtime": runtime,
            }
            (root / "predictions.jsonl").write_text(
                json.dumps(prediction) + "\n", encoding="utf-8"
            )
            (root / "metrics.json").write_text(
                json.dumps({"counts": {"attempted": 1}}), encoding="utf-8"
            )
            result = validate_run_artifacts(root, require_colab=False, minimum_attempts=1)
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.counts["successful"], 1)


if __name__ == "__main__":
    unittest.main()
