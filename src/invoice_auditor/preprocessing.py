"""Image/PDF safety boundary used before any model sees an upload."""

from __future__ import annotations

import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
DEFAULT_LONGEST_SIDE = 1600
MAX_PDF_DPI = 200


class UnsafeDocumentError(ValueError):
    """Raised when an input violates the document safety contract."""


class UnsafeImageError(UnsafeDocumentError):
    """Raised when an input violates the image safety contract."""


def load_safe_image(
    path: str | Path,
    *,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_pixels: int = MAX_IMAGE_PIXELS,
    longest_side: int = DEFAULT_LONGEST_SIDE,
) -> Image.Image:
    image_path = Path(path).expanduser().resolve(strict=True)
    if not image_path.is_file():
        raise UnsafeImageError(f"image path is not a file: {image_path}")
    if image_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UnsafeImageError(
            f"unsupported image extension {image_path.suffix!r}; "
            f"allowed={sorted(ALLOWED_EXTENSIONS)}"
        )
    if image_path.stat().st_size > max_file_bytes:
        raise UnsafeImageError(f"image exceeds {max_file_bytes} byte safety limit")
    if longest_side < 256 or longest_side > 4096:
        raise UnsafeImageError("longest_side must be between 256 and 4096")

    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(image_path) as probe:
                probe.verify()
            with Image.open(image_path) as opened:
                width, height = opened.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise UnsafeImageError(f"image dimensions exceed {max_pixels} total pixels")
                clean = ImageOps.exif_transpose(opened).convert("RGB")
                clean.thumbnail((longest_side, longest_side), Image.Resampling.LANCZOS)
                clean.load()
                return clean.copy()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise UnsafeImageError("image exceeds decompression-bomb limits") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise UnsafeImageError(
            "image is corrupt or its content does not match the extension"
        ) from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def _close_if_supported(value: object | None) -> None:
    close = getattr(value, "close", None)
    if callable(close):
        close()


def load_safe_pdf(
    path: str | Path,
    *,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_pixels: int = MAX_IMAGE_PIXELS,
    longest_side: int = DEFAULT_LONGEST_SIDE,
    render_dpi: int = 150,
    pdfium_module: object | None = None,
) -> Image.Image:
    """Render exactly one PDF page in memory with bounded dimensions and pixels."""

    pdf_path = Path(path).expanduser().resolve(strict=True)
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        raise UnsafeDocumentError("PDF input must be a regular .pdf file")
    if pdf_path.stat().st_size > max_file_bytes:
        raise UnsafeDocumentError(f"PDF exceeds {max_file_bytes} byte safety limit")
    if not pdf_path.read_bytes()[:5] == b"%PDF-":
        raise UnsafeDocumentError("PDF content does not match its extension")
    if not 72 <= render_dpi <= MAX_PDF_DPI:
        raise UnsafeDocumentError(f"render_dpi must be between 72 and {MAX_PDF_DPI}")
    if longest_side < 256 or longest_side > 4096:
        raise UnsafeDocumentError("longest_side must be between 256 and 4096")

    pdfium = pdfium_module
    if pdfium is None:
        try:
            import pypdfium2 as imported_pdfium
        except ImportError as exc:
            raise RuntimeError(
                "PDF support is missing; install requirements-pdf.txt or .[pdf]"
            ) from exc
        pdfium = imported_pdfium

    document = page = bitmap = None
    try:
        document = pdfium.PdfDocument(str(pdf_path))
        page_count = len(document)
        if page_count != 1:
            raise UnsafeDocumentError(
                f"PDF must contain exactly one page; received {page_count}. Split pages first."
            )
        page = document[0]
        width_points, height_points = page.get_size()
        scale = render_dpi / 72
        width = round(width_points * scale)
        height = round(height_points * scale)
        if width <= 0 or height <= 0 or width * height > max_pixels:
            raise UnsafeDocumentError(f"rendered PDF exceeds {max_pixels} total pixels")
        bitmap = page.render(scale=scale)
        rendered = bitmap.to_pil().convert("RGB")
        rendered.thumbnail((longest_side, longest_side), Image.Resampling.LANCZOS)
        rendered.load()
        return rendered.copy()
    except UnsafeDocumentError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise UnsafeDocumentError("PDF is corrupt, encrypted, or unsupported") from exc
    finally:
        _close_if_supported(bitmap)
        _close_if_supported(page)
        _close_if_supported(document)


def load_safe_document(
    path: str | Path,
    *,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_pixels: int = MAX_IMAGE_PIXELS,
    longest_side: int = DEFAULT_LONGEST_SIDE,
    render_dpi: int = 150,
) -> Image.Image:
    document_path = Path(path).expanduser().resolve(strict=True)
    if document_path.suffix.lower() == ".pdf":
        return load_safe_pdf(
            document_path,
            max_file_bytes=max_file_bytes,
            max_pixels=max_pixels,
            longest_side=longest_side,
            render_dpi=render_dpi,
        )
    return load_safe_image(
        document_path,
        max_file_bytes=max_file_bytes,
        max_pixels=max_pixels,
        longest_side=longest_side,
    )
