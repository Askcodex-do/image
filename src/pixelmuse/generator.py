"""Rendering engine: turn one source image into many styled images.

Memory strategy for a 2 GB Windows machine:
  * the source is downscaled to a working canvas (long edge <= ``max_side``)
  * variants are rendered one at a time and handed back as PIL images
  * the caller (CLI/GUI/web) decides when to keep or drop them
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Sequence

import numpy as np
from PIL import Image

from . import catalog_draw as _catalog_draw  # noqa: F401  (registers styles)
from . import catalog_paint as _catalog_paint  # noqa: F401  (registers styles)
from . import imgio
from .effects import core as C
from .styles import RenderOptions, Style, all_styles, get_style

Array = np.ndarray

# Conservative defaults: 1400 px long edge keeps peak RAM around 350 MB for a
# single RGB float32 buffer (1400*1400*3*4 bytes ~= 23 MB per buffer).
DEFAULT_MAX_SIDE = 1400
DEFAULT_VARIANTS = 4

# 0 = auto (single-threaded). Pillow/NumPy releases the GIL for most of the
# heavy lifting, so the GUI can put a render on a worker thread safely.
ProgressFn = Callable[[str, float], None]


@dataclass
class RenderRequest:
    """Everything needed to produce a batch of images."""

    source: Image.Image
    style_key: str
    variants: int = DEFAULT_VARIANTS
    options: RenderOptions = field(default_factory=RenderOptions)
    max_side: int = DEFAULT_MAX_SIDE
    seed: Optional[int] = None

    def resolved_seed(self) -> int:
        if self.seed is not None:
            return int(self.seed)
        return int(time.time_ns() % (2**32))


@dataclass
class RenderedImage:
    """One produced image plus the metadata a UI wants to show."""

    image: Image.Image
    style_key: str
    style_label: str
    variant: int
    seed: int
    width: int
    height: int
    seconds: float

    def suggested_filename(self, index: int | None = None) -> str:
        suffix = self.variant if index is None else index
        return f"{self.style_key}_{suffix + 1:02d}.png"


def prepare_working_image(image: Image.Image, max_side: int = DEFAULT_MAX_SIDE) -> Array:
    """Return the float array the styles operate on, respecting *max_side*."""
    if max_side and max_side > 0:
        image, _ = imgio.fit_within(image, (max_side, max_side))
    if image.mode != "RGB":
        image = image.convert("RGB")
    return C.to_array(image)


def _variants_for(style: Style, count: int) -> int:
    return max(1, min(int(count), 16))


def render_style(
    request: RenderRequest, progress: Optional[ProgressFn] = None
) -> List[RenderedImage]:
    """Render every requested variant of a single style."""
    style = get_style(request.style_key)
    base = prepare_working_image(request.source, request.max_side)
    seed = request.resolved_seed()
    total = _variants_for(style, request.variants)

    results: List[RenderedImage] = []
    for index in range(total):
        if progress:
            progress(f"{style.label}: image {index + 1}/{total}", index / float(total))
        rng = np.random.default_rng(seed + index * 7919)
        options = request.options.child(variant=index)
        started = time.perf_counter()
        array = style.render(base, rng, options)
        elapsed = time.perf_counter() - started
        image = C.to_image(np.asarray(array, dtype=np.float32))
        results.append(
            RenderedImage(
                image=image,
                style_key=style.key,
                style_label=style.label,
                variant=index,
                seed=seed,
                width=image.width,
                height=image.height,
                seconds=elapsed,
            )
        )
    if progress:
        progress(f"{style.label}: done", 1.0)
    return results


def render_many(
    source: Image.Image,
    style_keys: Sequence[str],
    variants: int = DEFAULT_VARIANTS,
    options: Optional[RenderOptions] = None,
    max_side: int = DEFAULT_MAX_SIDE,
    seed: Optional[int] = None,
    progress: Optional[ProgressFn] = None,
) -> List[RenderedImage]:
    """Render several styles in one call, sharing the seed across styles."""
    shared = options or RenderOptions()
    seed_value = int(seed) if seed is not None else int(time.time_ns() % (2**32))
    output: List[RenderedImage] = []
    for position, key in enumerate(style_keys):
        request = RenderRequest(
            source=source,
            style_key=key,
            variants=variants,
            options=shared,
            max_side=max_side,
            seed=seed_value + position * 104729,
        )
        output.extend(render_style(request, progress=progress))
    return output


def iter_render_many(
    source: Image.Image,
    style_keys: Sequence[str],
    variants: int = DEFAULT_VARIANTS,
    options: Optional[RenderOptions] = None,
    max_side: int = DEFAULT_MAX_SIDE,
    seed: Optional[int] = None,
    progress: Optional[ProgressFn] = None,
) -> Iterator[RenderedImage]:
    """Lazy variant of :func:`render_many`, yielding images as they finish."""
    yield from render_many(
        source,
        style_keys,
        variants=variants,
        options=options,
        max_side=max_side,
        seed=seed,
        progress=progress,
    )


def save_rendered(
    images: Iterable[RenderedImage],
    output_dir: str | Path,
    format_ext: str = ".png",
    index_names: bool = False,
) -> List[Path]:
    """Write rendered images to *output_dir* and return the paths."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    counters: dict[str, int] = {}
    for item in images:
        counters[item.style_key] = counters.get(item.style_key, 0) + 1
        if index_names:
            name = f"{item.style_key}_{counters[item.style_key]:02d}{format_ext}"
        else:
            name = f"{item.style_key}_v{item.variant + 1:02d}_{item.seed % 100000:05d}{format_ext}"
        written.append(imgio.save_image(item.image, directory / name))
    return written


def available_styles() -> List[Style]:
    """All registered styles (importing this module registers the catalogues)."""
    return all_styles()


def styles_by_family() -> dict[str, List[Style]]:
    """Styles grouped by family, for building menus and grids."""
    grouped: dict[str, List[Style]] = {}
    for style in available_styles():
        grouped.setdefault(style.family, []).append(style)
    return grouped


def build_contact_sheet(images: Sequence[RenderedImage], columns: int = 2) -> Image.Image:
    """Compose a simple contact sheet, handy for previews and tests."""
    if not images:
        raise ValueError("no images to compose")
    tiles = [C.to_array(item.image) for item in images]
    height = max(tile.shape[0] for tile in tiles)
    width = max(tile.shape[1] for tile in tiles)
    rows = (len(tiles) + columns - 1) // columns
    margin = max(4, width // 100)
    sheet = np.ones((rows * height + margin * (rows + 1), columns * width + margin * (columns + 1), 3),
                    dtype=np.float32)
    for index, tile in enumerate(tiles):
        row, col = divmod(index, columns)
        top = margin + row * (height + margin)
        left = margin + col * (width + margin)
        sheet[top : top + tile.shape[0], left : left + tile.shape[1]] = tile
    return C.to_image(sheet)
