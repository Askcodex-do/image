"""Image loading, normalising and saving helpers (Pillow only)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageOps

# Pillow refuses to open images above this pixel count unless we raise the cap.
# 32 MP is plenty for a photo/artwork reference and still safe on 2 GB RAM.
MAX_SOURCE_PIXELS = 32_000_000


class ImageLoadError(RuntimeError):
    """Raised when a file cannot be read as an image."""


def allow_large_images() -> None:
    """Raise Pillow's decompression-bomb cap for legitimate large photos."""
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS


def load_image(path: str | os.PathLike[str]) -> Image.Image:
    """Open *path*, apply EXIF rotation and return an independent RGB image."""
    allow_large_images()
    file_path = Path(path)
    if not file_path.is_file():
        raise ImageLoadError(f"File not found: {file_path}")

    try:
        with Image.open(file_path) as handle:
            handle.load()
            image = ImageOps.exif_transpose(handle)
            return image.convert("RGB")
    except Exception as exc:  # Pillow raises many different exception types
        raise ImageLoadError(f"Could not read image: {file_path} ({exc})") from exc


def load_thumbnail(
    path: str | os.PathLike[str], max_size: Tuple[int, int] = (480, 480)
) -> Image.Image:
    """Load a small preview copy, used by the GUI to stay memory friendly."""
    image = load_image(path)
    image.thumbnail(max_size, Image.Resampling.LANCZOS)
    return image


def fit_within(
    image: Image.Image, max_size: Tuple[int, int], resample: int = Image.Resampling.LANCZOS
) -> Tuple[Image.Image, float]:
    """Return a copy that fits inside *max_size* plus the scale factor applied."""
    width, height = image.size
    max_w, max_h = max_size
    scale = min(max_w / float(width), max_h / float(height), 1.0)
    if scale >= 1.0:
        return image.copy(), 1.0
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return image.resize(new_size, resample), scale


def square(image: Image.Image, size: int, resample: int = Image.Resampling.LANCZOS) -> Image.Image:
    """Centre-crop to a square and resize to ``size`` x ``size``."""
    return ImageOps.fit(image, (size, size), method=resample, centering=(0.5, 0.5))


def save_image(
    image: Image.Image,
    path: str | os.PathLike[str],
    quality: int = 95,
    dpi: int = 300,
) -> Path:
    """Save *image*, choosing format/options from the file extension."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = out_path.suffix.lower()

    if suffix in (".jpg", ".jpeg"):
        image.convert("RGB").save(
            out_path, format="JPEG", quality=quality, subsampling=0, optimize=True, dpi=(dpi, dpi)
        )
    elif suffix == ".png":
        image.save(out_path, format="PNG", compress_level=6, dpi=(dpi, dpi))
    elif suffix == ".bmp":
        image.convert("RGB").save(out_path, format="BMP")
    elif suffix == ".webp":
        image.save(out_path, format="WEBP", quality=quality, method=4)
    else:
        # Unknown extension: fall back to PNG bytes.
        out_path = out_path.with_suffix(".png")
        image.save(out_path, format="PNG", compress_level=6, dpi=(dpi, dpi))
    return out_path


def supported_extensions() -> tuple[str, ...]:
    """File extensions the loader is expected to handle."""
    return (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif", ".ppm")
