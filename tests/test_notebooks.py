from __future__ import annotations

import json
import unittest
from pathlib import Path


class NotebookContractTests(unittest.TestCase):
    def test_notebooks_are_valid_json_and_code_cells_compile(self) -> None:
        root = Path(__file__).resolve().parents[1]
        notebooks = sorted((root / "notebooks").glob("*.ipynb"))
        self.assertEqual(len(notebooks), 4)
        for path in notebooks:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["nbformat"], 4)
            for index, cell in enumerate(payload["cells"]):
                if cell["cell_type"] == "code":
                    compile("".join(cell["source"]), f"{path.name}:cell-{index}", "exec")

    def test_colab_pipeline_uses_real_runtime_and_artifact_validator(self) -> None:
        root = Path(__file__).resolve().parents[1]
        bootstrap = (root / "notebooks/00_colab_bootstrap.ipynb").read_text(encoding="utf-8")
        pipeline = (root / "notebooks/02_vlm_extraction_pipeline.ipynb").read_text(
            encoding="utf-8"
        )
        self.assertIn("requirements-colab.lock", bootstrap)
        self.assertIn("VLMRuntime", pipeline)
        self.assertIn("run_batch_inference", pipeline)
        self.assertIn("validate_run_artifacts", pipeline)
        self.assertNotIn("share=True", pipeline)


if __name__ == "__main__":
    unittest.main()
