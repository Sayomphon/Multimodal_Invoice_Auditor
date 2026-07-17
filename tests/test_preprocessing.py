from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from invoice_auditor.preprocessing import UnsafeImageError, load_safe_image


class ImagePreprocessingTests(unittest.TestCase):
    def test_loads_rgb_and_resizes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invoice.png"
            Image.new("RGBA", (2400, 1200), (255, 255, 255, 128)).save(path)
            image = load_safe_image(path, longest_side=1000)
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(max(image.size), 1000)

    def test_rejects_extension_and_corrupt_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text_path = root / "invoice.txt"
            text_path.write_text("not an image", encoding="utf-8")
            with self.assertRaises(UnsafeImageError):
                load_safe_image(text_path)
            corrupt = root / "invoice.png"
            corrupt.write_bytes(b"not a png")
            with self.assertRaises(UnsafeImageError):
                load_safe_image(corrupt)


if __name__ == "__main__":
    unittest.main()

