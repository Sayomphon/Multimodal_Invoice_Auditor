"""Image safety boundary used before any model sees an upload."""

from __future__ import annotations

import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
DEFAULT_LONGEST_SIDE = 1600


class UnsafeImageError(ValueError):
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
