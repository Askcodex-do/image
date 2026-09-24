"""Style library: every "description" the user can pick from.

A style is a pure function ``(array, rng, options) -> array``.  Everything is
implemented with Pillow + NumPy only, so the whole app runs offline on a
2 GB Windows machine with no model weights to download.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Sequence

import numpy as np

from .effects import core as C

Array = np.ndarray


# --------------------------------------------------------------------------- #
# options
# --------------------------------------------------------------------------- #
@dataclass
class RenderOptions:
    """User facing knobs shared by every style."""

    detail: float = 0.5          # 0 = loose/painterly, 1 = fine/tight
    strength: float = 0.75       # 0 = subtle, 1 = full effect
    colors: int = 12             # palette size for posterise-style looks
    variant: int = 0             # changes randomness between generated images
    canvas_texture: bool = True  # add woven canvas / paper grain
    vignette: bool = True        # add a subtle vignette
    frame: bool = False          # add a print border

    def child(self, **overrides) -> "RenderOptions":
        data = dict(self.__dict__)
        data.update(overrides)
        return RenderOptions(**data)


@dataclass
class Style:
    """A selectable rendering recipe."""

    key: str
    label: str
    family: str
    blurb: str
    render: Callable[[Array, np.random.Generator, RenderOptions], Array]
    keywords: Sequence[str] = field(default_factory=tuple)


_STYLES: Dict[str, Style] = {}
_ORDER: List[str] = []


def register(style: Style) -> Style:
    """Add a style to the global registry (used as a decorator)."""
    if style.key in _STYLES:
        raise ValueError(f"duplicate style key: {style.key}")
    _STYLES[style.key] = style
    _ORDER.append(style.key)
    return style


def get_style(key: str) -> Style:
    try:
        return _STYLES[key]
    except KeyError as exc:
        raise KeyError(f"Unknown style '{key}'. Available: {', '.join(_ORDER)}") from exc


def all_styles() -> List[Style]:
    """Every registered style, in registration order."""
    return [_STYLES[key] for key in _ORDER]


def style_keys() -> List[str]:
    return list(_ORDER)


# --------------------------------------------------------------------------- #
# painterly building blocks
# --------------------------------------------------------------------------- #
def _box_sum(plane: Array, kh: int, kw: int) -> Array:
    """``out[y, x]`` = sum of ``plane[y-kh+1:y+1, x-kw+1:x+1]``."""
    pad_top, pad_left = kh - 1, kw - 1
    padded = np.pad(plane.astype(np.float32), ((pad_top, 0), (pad_left, 0)), mode="edge")
    integral = padded.cumsum(axis=0).cumsum(axis=1)
    integral = np.pad(integral, ((1, 0), (1, 0)), mode="constant")
    height, width = plane.shape
    return (
        integral[kh : kh + height, kw : kw + width]
        - integral[0:height, kw : kw + width]
        - integral[kh : kh + height, 0:width]
        + integral[0:height, 0:width]
    )


def kuwahara(array: Array, radius: int = 3) -> Array:
    """Edge-preserving smoothing: the classic "painted" look.

    Splits a square window into four quadrants, keeps the mean of the quadrant
    with the lowest variance.  Implemented with integral images so it stays
    fast on large images.
    """
    radius = max(1, int(radius))
    size = radius + 1
    height, width = array.shape[:2]
    grey = C.luminance(array)

    sums = _box_sum(grey, size, size)
    sums2 = _box_sum(grey * grey, size, size)
    count = float(size * size)
    mean = sums / count
    variance = np.maximum(sums2 / count - mean * mean, 0.0)

    # Quadrant windows, expressed as shifts of the window that ends at (y, x).
    offset = radius
    variance_tr = C.shift(variance, offset, 0)   # window starts at x -> ends x+r
    variance_bl = C.shift(variance, 0, offset)   # rows y..y+r
    variance_br = C.shift(variance, offset, offset)

    stacked = np.stack([variance, variance_tr, variance_bl, variance_br], axis=0)
    winner = stacked.argmin(axis=0).astype(np.int8)

    sums_rgb = np.stack([_box_sum(array[..., ch], size, size) for ch in range(3)], axis=-1)
    variants = [
        sums_rgb,
        C.shift(sums_rgb, offset, 0),
        C.shift(sums_rgb, 0, offset),
        C.shift(sums_rgb, offset, offset),
    ]
    output = np.empty_like(array, dtype=np.float32)
    for index, cube in enumerate(variants):
        mask = winner == index
        if mask.any():
            output[mask] = cube[mask] / count
    return np.clip(output, 0.0, 1.0)


def stroke_smear(array: Array, angle_deg: float, length: int, edge_aware: bool = True) -> Array:
    """Average shifted copies along one direction -> directional brush stroke."""
    length = max(1, int(length))
    angle = np.deg2rad(angle_deg)
    dx = np.cos(angle)
    dy = -np.sin(angle)  # image y grows downwards

    total = C.clone(array)
    weight_sum = 1.0
    for step in range(1, length + 1):
        weight = 1.0 - (step / (length + 1.0)) * 0.65
        shifted = C.shift(
            array, int(round(dx * step)), int(round(dy * step))
        )
        total = total + shifted * weight
        weight_sum += weight
    smeared = total / weight_sum

    if not edge_aware:
        return smeared
    edge = C.edge_mask(array, radius=0.6, gain=1.1)
    # Keep real contours crisp, smear only the flat regions.
    return C.blend(smeared, array, 0.0) * (1.0 - edge) + array * edge


def painterly_base(array: Array, rng: np.random.Generator, options: RenderOptions) -> Array:
    """Shared first stage for the oil/acrylic styles."""
    detail = float(np.clip(options.detail, 0.0, 1.0))
    radius = int(round(4 - 2.5 * detail))
    painted = kuwahara(array, radius=radius)

    # Two crossing strokes give the woven, layered look of real brushwork.
    strokes_a = stroke_smear(painted, 35.0 + rng.random() * 20.0, int(round(6 - 3 * detail)))
    strokes_b = stroke_smear(painted, 125.0 + rng.random() * 20.0, int(round(5 - 2 * detail)))
    painted = C.blend(strokes_a, strokes_b, 0.45)

    # Colour simplification: oil paint mixes into fewer, chunkier tones.
    levels = 6 if detail < 0.4 else (8 if detail < 0.75 else 12)
    painted = C.posterize(C.blend(painted, C.median(painted, 3), 0.5), levels)
    return C.adjust_saturation(painted, 1.06)


def impasto(relief: Array, base: Array, amount: float = 0.35) -> Array:
    """Fake thick paint: light the surface using a height field from the edges."""
    height = C.luminance(relief)
    grad_y = np.gradient(height, axis=0)
    grad_x = np.gradient(height, axis=1)
    light = np.clip(0.5 + (-grad_x * 0.5 - grad_y * 0.5), 0.0, 1.0)
    shade = C.blend(base, C.overlay(base, light[..., None]), amount)
    return C.adjust_contrast(shade, 1.03)


# --------------------------------------------------------------------------- #
# sketch / drawing building blocks
# --------------------------------------------------------------------------- #
def dodge_sketch(array: Array, blade: float = 0.5, smooth: float = 2.0) -> Array:
    """The classic "colour dodge" pencil render."""
    grey = C.luminance(array)[..., None]
    inverted = C.blur(1.0 - grey, smooth)
    safe = np.clip(inverted, 1e-2, 1.0)
    dodge = np.clip(grey / safe, 0.0, 8.0)
    sketch = 1.0 - np.clip(dodge, 0.0, 1.0)
    sketch = np.power(np.clip(sketch, 0.0, 1.0), max(0.25, blade))
    return C.luminance_to_rgb(C.adjust_contrast(sketch, 1.15))


def xdog_lines(array: Array, detail: float = 0.5) -> Array:
    """Extended difference-of-gaussians *whiteness* map, ``(H, W)`` in 0..1.

    Returns 1.0 on blank paper and dips towards 0.0 along contours, which is
    how the drawing styles expect "ink" to be measured: ``ink = 1 - lines``.
    Reference: Winnemoeller et al., "XDoG: Advanced Image Stylization with
    eXtended Difference-of-Gaussians".
    """
    sigma = 1.0 + (1.0 - detail) * 1.6
    grey = C.luminance(array)
    blur_small = C.luminance(C.blur(array, sigma * 0.6))
    blur_large = C.luminance(C.blur(array, sigma * 1.8))
    dog = blur_small - 0.985 * blur_large

    # Classic XDoG soft ramp: flat areas stay white, contours fall to black.
    eps = 0.010 + 0.022 * (1.0 - detail)
    phi = 20.0 + 20.0 * detail
    whiteness = np.clip(1.0 + np.tanh(phi * (dog - eps)), 0.0, 1.0)

    # Gate out isolated speckle: where the source has no local contrast there
    # is nothing to draw, so force the paper back to white.
    local = C.luminance(C.blur(C.edges(array, radius=sigma * 1.5, gain=1.0)[..., None], sigma))
    whiteness = np.where(local < 0.01, 1.0, whiteness)
    del grey
    return np.clip(whiteness, 0.0, 1.0)


def finish_pass(
    array: Array,
    options: RenderOptions,
    rng: np.random.Generator,
    texture_strength: float = 0.09,
    weave: int = 3,
    vignette_strength: float = 0.28,
    grain_amount: float = 0.012,
) -> Array:
    """Shared final pass: texture, grain, vignette, optional print border."""
    out = C.adjust_saturation(array, 1.0 + (options.strength - 0.5) * 0.25)
    if options.canvas_texture and texture_strength > 0:
        out = np.clip(out + C.canvas_texture(out.shape, rng, texture_strength, weave), 0.0, 1.0)
    if grain_amount > 0:
        out = np.clip(out + C.grain(out.shape, rng, grain_amount), 0.0, 1.0)
    if options.vignette:
        out = np.clip(out * C.vignette(out.shape, vignette_strength), 0.0, 1.0)
    if options.frame:
        out = C.frame_border(out, max(6, min(out.shape[0], out.shape[1]) // 28))
    return np.clip(out, 0.0, 1.0)


def hatching_overlay(shape, rng: np.random.Generator, tone: Array, angle: float, spacing: float) -> Array:
    """Diagonal pencil hatching weighted by the darkness of *tone*."""
    height, width = shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    theta = np.deg2rad(angle)
    projected = xx * np.cos(theta) + yy * np.sin(theta)
    line = np.abs(np.sin(projected * (np.pi / max(2.0, spacing))))
    line = np.power(np.clip(line, 0.0, 1.0), 3.0)
    dark = np.clip(1.0 - tone, 0.0, 1.0)
    return np.clip(line * dark, 0.0, 1.0)[..., None]
