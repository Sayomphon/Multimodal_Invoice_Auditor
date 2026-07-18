from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from invoice_auditor.datasets import prepare_sroie_local


class SroieDatasetTests(unittest.TestCase):
    def test_local_subset_is_deterministic_hashed_and_field_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "images").mkdir(parents=True)
            (source / "entities").mkdir()
            for index in range(3):
                Image.new("RGB", (20, 20), (index, index, index)).save(
                    source / "images" / f"receipt-{index}.png"
                )
                annotation = {
                    "company": f"Vendor {index}",
                    "date": "2026-01-01",
                    "total": str(100 + index),
                    "address": "not evaluated",
                }
                (source / "entities" / f"receipt-{index}.txt").write_text(
                    json.dumps(annotation), encoding="utf-8"
                )
            output = root / "subset"
            manifest_path = prepare_sroie_local(
                source,
                output,
                dataset_revision="licensed-local-copy-v1",
                license_reference="https://example.invalid/license-review",
                count=2,
                seed=7,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["count"], 2)
            for record in manifest["records"]:
                self.assertEqual(record["dataset_segment"], "sroie_vlm")
                self.assertEqual(len(record["sha256"]), 64)
                self.assertEqual(
                    set(record["evaluable_fields"]), {"vendor_name", "invoice_date", "total"}
                )
                self.assertFalse(Path(record["image_path"]).is_absolute())


if __name__ == "__main__":
    unittest.main()
