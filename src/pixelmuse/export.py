"""Export helpers: save a batch, or bundle it as a zip / PDF contact sheet."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Iterable, List, Sequence

from . import imgio
from .effects import core as C
from .generator import RenderedImage

Image = None  # populated lazily to keep the import cost off the hot path


def save_batch(
    images: Iterable[RenderedImage],
    output_dir: str | Path,
    format_ext: str = ".png",
    quality: int = 95,
) -> List[Path]:
    """Save every image into *output_dir*, avoiding name collisions."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    used: set[str] = set()
    for item in images:
        stem = f"{item.style_key}_v{item.variant + 1:02d}"
        candidate = directory / f"{stem}{format_ext}"
        counter = 2
        while candidate.name in used or candidate.exists():
            candidate = directory / f"{stem}_{counter}{format_ext}"
            counter += 1
        used.add(candidate.name)
        written.append(imgio.save_image(item.image, candidate, quality=quality))
    return written


def batch_to_zip_bytes(
    images: Sequence[RenderedImage], format_ext: str = ".png", quality: int = 95
) -> bytes:
    """Serialise a batch to an in-memory zip, ready to stream to a browser."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, item in enumerate(images):
            payload = io.BytesIO()
            image = item.image
            if format_ext.lower() in (".jpg", ".jpeg"):
                image.convert("RGB").save(payload, format="JPEG", quality=quality)
            else:
                image.save(payload, format="PNG", compress_level=6)
            name = f"{item.style_key}_v{item.variant + 1:02d}{format_ext}"
            archive.writestr(name, payload.getvalue())
    return buffer.getvalue()


def batch_to_pdf_bytes(images: Sequence[RenderedImage]) -> bytes:
    """One image per page, A4-ish, no external PDF library needed."""
    buffer = io.BytesIO()
    pages = [item.image.convert("RGB") for item in images]
    if not pages:
        raise ValueError("no images to export")
    first, *rest = pages
    first.save(buffer, format="PDF", save_all=True, append_images=rest, resolution=150.0)
    return buffer.getvalue()


def contact_sheet_bytes(images: Sequence[RenderedImage], columns: int = 3) -> bytes:
    """PNG bytes of a grid preview of the whole batch."""
    from .generator import build_contact_sheet

    sheet = build_contact_sheet(images, columns=columns)
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


def metadata_lines(images: Sequence[RenderedImage]) -> List[str]:
    """Human readable summary of what was generated."""
    lines: List[str] = []
    for item in images:
        lines.append(
            f"{item.style_key}/v{item.variant + 1:02d}  "
            f"{item.width}x{item.height}  seed={item.seed}  {item.seconds:.2f}s"
        )
    return lines


__all__ = [
    "save_batch",
    "batch_to_zip_bytes",
    "batch_to_pdf_bytes",
    "contact_sheet_bytes",
    "metadata_lines",
    "C",
]
