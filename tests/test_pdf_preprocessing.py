from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from invoice_auditor.preprocessing import UnsafeDocumentError, load_safe_pdf


class _Bitmap:
    def __init__(self) -> None:
        self.closed = False

    def to_pil(self) -> Image.Image:
        return Image.new("RGB", (100, 200), "white")

    def close(self) -> None:
        self.closed = True


class _Page:
    def __init__(self, size: tuple[int, int] = (612, 792)) -> None:
        self.size = size
        self.closed = False

    def get_size(self) -> tuple[int, int]:
        return self.size

    def render(self, *, scale: float) -> _Bitmap:
        self.scale = scale
        return _Bitmap()

    def close(self) -> None:
        self.closed = True


def _pdfium(page_count: int = 1, size: tuple[int, int] = (612, 792)) -> object:
    class Document:
        def __init__(self, path: str) -> None:
            self.pages = [_Page(size) for _ in range(page_count)]
            self.closed = False

        def __len__(self) -> int:
            return len(self.pages)

        def __getitem__(self, index: int) -> _Page:
            return self.pages[index]

        def close(self) -> None:
            self.closed = True

    return SimpleNamespace(PdfDocument=Document)


class PdfPreprocessingTests(unittest.TestCase):
    def _pdf_path(self, root: Path, content: bytes = b"%PDF-1.7\n") -> Path:
        path = root / "invoice.pdf"
        path.write_bytes(content)
        return path

    def test_one_page_pdf_renders_to_bounded_rgb_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image = load_safe_pdf(
                self._pdf_path(Path(temporary)),
                longest_side=1000,
                pdfium_module=_pdfium(),
            )
            self.assertEqual(image.mode, "RGB")
            self.assertLessEqual(max(image.size), 1000)

    def test_pdfium_integration_when_optional_dependency_is_installed(self) -> None:
        try:
            import pypdfium2  # noqa: F401
        except ImportError:
            self.skipTest("pypdfium2 optional dependency is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "pillow-generated.pdf"
            Image.new("RGB", (300, 200), "white").save(path, format="PDF")
            image = load_safe_pdf(path, longest_side=500)
            self.assertEqual(image.mode, "RGB")
            self.assertLessEqual(max(image.size), 500)

    def test_rejects_multi_page_and_oversized_page(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._pdf_path(Path(temporary))
            with self.assertRaises(UnsafeDocumentError):
                load_safe_pdf(path, pdfium_module=_pdfium(page_count=2))
            with self.assertRaises(UnsafeDocumentError):
                load_safe_pdf(path, max_pixels=100, pdfium_module=_pdfium(size=(1000, 1000)))

    def test_rejects_misleading_pdf_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._pdf_path(Path(temporary), b"not a pdf")
            with self.assertRaises(UnsafeDocumentError):
                load_safe_pdf(path, pdfium_module=_pdfium())


if __name__ == "__main__":
    unittest.main()
