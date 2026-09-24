"""Low level, dependency-light image helpers shared by every style.

Everything works on ``numpy.float32`` arrays in 0..1 range, shape ``(H, W, 3)``.
Colour work is done in linear-ish sRGB space (i.e. the raw 0..1 values), which
is fast and good enough for stylisation.
"""

from __future__ import annotations

from typing import Iterable, Sequence, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageFilter

Array = np.ndarray

RGB = Tuple[int, int, int]


# --------------------------------------------------------------------------- #
# conversion
# --------------------------------------------------------------------------- #
def to_array(image: Image.Image) -> Array:
    """PIL image -> float32 array in 0..1, always 3 channels."""
    if image.mode != "RGB":
        image = image.convert("RGB")
    return np.asarray(image, dtype=np.float32) / 255.0


def to_image(array: Array) -> Image.Image:
    """float32 array in any range -> 8-bit PIL image (always 3 channels)."""
    if array.ndim == 2:
        array = np.repeat(array[..., None], 3, axis=2)
    elif array.shape[-1] == 1:
        array = np.repeat(array, 3, axis=2)
    return Image.fromarray(to_uint8(array), mode="RGB")


def to_uint8(array: Array) -> Array:
    """Clip to 0..1 and scale to 0..255 uint8, shape preserved."""
    return (np.clip(array, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def luminance(array: Array) -> Array:
    """Perceptual luma, shape ``(H, W)``, float32 in 0..1."""
    if array.ndim == 2:
        return array.astype(np.float32)
    if array.shape[-1] == 1:
        return array[..., 0].astype(np.float32)
    return (
        array[..., 0] * 0.2126 + array[..., 1] * 0.7152 + array[..., 2] * 0.0722
    ).astype(np.float32)


def clone(array: Array) -> Array:
    return np.array(array, dtype=np.float32, copy=True)


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #
def resize_array(array: Array, size: Tuple[int, int]) -> Array:
    """Resize a float array to ``size`` = (width, height)."""
    img = to_image(array).resize(size, Image.Resampling.LANCZOS)
    return to_array(img)


def crop_center(array: Array, size: Tuple[int, int]) -> Array:
    """Centre crop to ``size`` = (width, height); pads if the source is smaller."""
    height, width = array.shape[:2]
    target_w, target_h = size
    if target_w > width or target_h > height:
        out_w, out_h = max(width, target_w), max(height, target_h)
        canvas = np.zeros((out_h, out_w, 3), dtype=np.float32)
        top = (out_h - height) // 2
        left = (out_w - width) // 2
        canvas[top : top + height, left : left + width] = array
        array = canvas
        height, width = out_h, out_w

    left = (width - target_w) // 2
    top = (height - target_h) // 2
    return np.ascontiguousarray(array[top : top + target_h, left : left + target_w])


def blur(array: Array, radius: float) -> Array:
    """Gaussian blur; radius <= 0 returns an unchanged copy."""
    if radius <= 0:
        return clone(array)
    img = to_image(array).filter(ImageFilter.GaussianBlur(radius=float(radius)))
    return to_array(img)


def median(array: Array, size: int = 5) -> Array:
    """Median denoise, the classic first step of a painterly pipeline."""
    if size < 3:
        return clone(array)
    img = to_image(array).filter(ImageFilter.MedianFilter(size=int(size) | 1))
    return to_array(img)


def mode_filter(array: Array, size: int = 5) -> Array:
    """Mode filter: keeps flat regions flat, useful before quantising colour."""
    img = to_image(array).filter(ImageFilter.ModeFilter(size=int(size) | 1))
    return to_array(img)


def box_area_mean(array: Array, window: int) -> Array:
    """Average pooling with a square window, keeping the original shape."""
    if window < 2:
        return clone(array)
    img = to_image(array).resize(
        (max(1, array.shape[1] // window), max(1, array.shape[0] // window)),
        Image.Resampling.BOX,
    )
    return to_array(img.resize((array.shape[1], array.shape[0]), Image.Resampling.NEAREST))


def shift(array: Array, dx: int, dy: int) -> Array:
    """Translate by (dx, dy) pixels, filling the gap by edge replication."""
    shifted = np.roll(array, (dy, dx), axis=(0, 1))
    if dy > 0:
        shifted[:dy] = shifted[dy : dy + 1]
    elif dy < 0:
        shifted[dy:] = shifted[dy - 1 : dy]
    if dx > 0:
        shifted[:, :dx] = shifted[:, dx : dx + 1]
    elif dx < 0:
        shifted[:, dx:] = shifted[:, dx - 1 : dx]
    return shifted


# --------------------------------------------------------------------------- #
# tone / colour
# --------------------------------------------------------------------------- #
def blend(base: Array, top: Array, alpha) -> Array:
    """Linear interpolation ``base*(1-a) + top*a``.

    *alpha* may be a scalar or an array broadcastable against the images.
    """
    if np.isscalar(alpha):
        if alpha <= 0.0:
            return clone(base)
        if alpha >= 1.0:
            return clone(top)
    return np.clip(base * (1.0 - alpha) + top * alpha, 0.0, 1.0)


def multiply(base: Array, top: Array) -> Array:
    return base * top


def screen(base: Array, top: Array) -> Array:
    return 1.0 - (1.0 - base) * (1.0 - top)


def overlay(base: Array, top: Array) -> Array:
    low = 2.0 * base * top
    high = 1.0 - 2.0 * (1.0 - base) * (1.0 - top)
    return np.where(base < 0.5, low, high)


def soft_light(base: Array, top: Array) -> Array:
    return np.clip(base + (2.0 * top - 1.0) * 0.5, 0.0, 1.0)


def color_dodge(base: Array, top: Array, strength: float = 0.6) -> Array:
    """Brighten *base* with *top*; strength keeps the highlights from clipping."""
    safe_top = np.clip(top, 1e-3, 1.0)
    dodged = np.clip(base / safe_top, 0.0, 4.0) * 0.25 + base * 0.75
    return blend(base, np.clip(dodged, 0.0, 1.0), strength)


def adjust_contrast(array: Array, amount: float) -> Array:
    """``amount`` > 1 increases contrast, < 1 flattens it. Pivot at mid grey."""
    return np.clip((array - 0.5) * amount + 0.5, 0.0, 1.0)


def adjust_saturation(array: Array, amount: float) -> Array:
    luma = luminance(array)[..., None]
    return np.clip(luma + (array - luma) * amount, 0.0, 1.0)


def gamma(array: Array, value: float) -> Array:
    return np.clip(np.power(np.clip(array, 0.0, 1.0), value), 0.0, 1.0)


def auto_contrast(array: Array, low_pct: float = 1.0, high_pct: float = 99.0) -> Array:
    """Stretch the luma histogram, then re-apply the original colour ratios."""
    luma = luminance(array)
    lo = float(np.percentile(luma, low_pct))
    hi = float(np.percentile(luma, high_pct))
    if hi - lo < 1e-4:
        return clone(array)
    stretched = np.clip((array - lo) / (hi - lo), 0.0, 1.0)
    return stretched


def white_balance(array: Array) -> Array:
    """Grey-world correction; mild because references are usually already fine."""
    means = array.reshape(-1, 3).mean(axis=0)
    grey = float(means.mean())
    gain = grey / np.maximum(means, 1e-4)
    gain = 1.0 + (gain - 1.0) * 0.5
    return np.clip(array * gain[None, None, :], 0.0, 1.0)


def posterize(array: Array, levels: int) -> Array:
    """Snap each channel to *levels* evenly spaced steps."""
    levels = max(2, int(levels))
    scale = levels - 1
    return np.clip(np.round(array * scale) / scale, 0.0, 1.0)


def curve(array: Array, points: Sequence[Tuple[float, float]]) -> Array:
    """Apply a monotonic tone curve defined by (x, y) control points."""
    xs = np.array([p[0] for p in points], dtype=np.float32)
    ys = np.array([p[1] for p in points], dtype=np.float32)
    order = np.argsort(xs)
    lut_x = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    lut_y = np.interp(lut_x, xs[order], ys[order]).astype(np.float32)
    idx = np.clip((array * 255.0).astype(np.int32), 0, 255)
    return lut_y[idx]


def colorize(grey: Array, dark: RGB, light: RGB) -> Array:
    """Map a greyscale image onto a two-colour ramp."""
    g = luminance(grey)[..., None]
    dark_arr = np.array(dark, dtype=np.float32) / 255.0
    light_arr = np.array(light, dtype=np.float32) / 255.0
    return np.clip(dark_arr + (light_arr - dark_arr) * g, 0.0, 1.0)


def gradient_map(grey: Array, stops: Sequence[RGB]) -> Array:
    """Map luma through a multi-stop gradient (dark -> light)."""
    g = np.clip(luminance(grey), 0.0, 1.0)
    positions = np.linspace(0.0, 1.0, len(stops), dtype=np.float32)
    palette = np.array(stops, dtype=np.float32) / 255.0
    out = np.zeros(g.shape + (3,), dtype=np.float32)
    for channel in range(3):
        out[..., channel] = np.interp(g, positions, palette[:, channel])
    return out


def quantize_palette(array: Array, colors: int, dither: bool = True) -> Array:
    """Reduce to *colors* using PIL's median-cut + optional Floyd-Steinberg."""
    img = to_image(array).convert("P", palette=Image.Palette.ADAPTIVE, colors=int(colors))
    if dither:
        img = img.convert("RGB").quantize(colors=int(colors), dither=Image.Dither.FLOYDSTEINBERG)
    return to_array(img.convert("RGB"))


def extract_palette(array: Array, colors: int = 6) -> list[RGB]:
    """Return the dominant colours as RGB tuples, darkest first."""
    img = to_image(array).convert("P", palette=Image.Palette.ADAPTIVE, colors=int(colors))
    raw = img.getpalette() or []
    counts = img.getcolors(maxcolors=1 << 20) or []
    used: list[Tuple[int, RGB]] = []
    for count, index in counts:
        base = index * 3
        rgb = (
            int(raw[base]) if base + 2 < len(raw) else 128,
            int(raw[base + 1]) if base + 2 < len(raw) else 128,
            int(raw[base + 2]) if base + 2 < len(raw) else 128,
        )
        used.append((count, rgb))
    used.sort(key=lambda item: luminance(np.array(item[1], dtype=np.float32) / 255.0))
    palette = [rgb for _, rgb in used]
    while len(palette) < colors:
        palette.append((128, 128, 128) if not palette else palette[-1])
    return palette[:colors]


# --------------------------------------------------------------------------- #
# edges / structure
# --------------------------------------------------------------------------- #
def edges(array: Array, radius: float = 1.0, gain: float = 1.0) -> Array:
    """Edge magnitude as float 0..1, ``(H, W)``, roughly smoothed Sobel."""
    grey = to_image(luminance(array)[..., None].repeat(3, axis=2))
    found = grey.filter(ImageFilter.FIND_EDGES)
    if radius > 0:
        found = found.filter(ImageFilter.GaussianBlur(radius=radius))
    edge = luminance(to_array(found))
    edge = np.clip(edge * (4.0 * gain), 0.0, 1.0)
    return edge


def laplacian(array: Array) -> Array:
    """Second-derivative detail map, signed; positive = brighter than neighbours."""
    grey = luminance(array)
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    padded = np.pad(grey, 1, mode="edge")
    out = np.zeros_like(grey)
    for dy in range(3):
        for dx in range(3):
            weight = kernel[dy, dx]
            if weight:
                out += weight * padded[dy : dy + grey.shape[0], dx : dx + grey.shape[1]]
    return out


def high_pass(array: Array, radius: float) -> Array:
    """Detail layer: original minus blurred, plus mid grey."""
    return np.clip(array - blur(array, radius) + 0.5, 0.0, 1.0)


def unsharp(array: Array, radius: float = 2.0, amount: float = 1.0, threshold: float = 0.0) -> Array:
    """Sharpen by boosting the high-pass detail layer."""
    detail = array - blur(array, radius)
    if threshold > 0:
        mask = (np.abs(detail) >= threshold).astype(np.float32)
        detail = detail * mask
    return np.clip(array + detail * amount, 0.0, 1.0)


def edge_mask(array: Array, radius: float = 1.0, gain: float = 1.0) -> Array:
    """``(H, W, 1)`` edge mask ready for broadcasting."""
    return edges(array, radius=radius, gain=gain)[..., None]


# --------------------------------------------------------------------------- #
# texture / framing
# --------------------------------------------------------------------------- #
def grain(shape: Tuple[int, int], rng: np.random.Generator, amount: float = 0.03) -> Array:
    """Additive gaussian noise broadcastable over an ``(H, W, 3)`` image."""
    height, width = shape[:2]
    noise = rng.normal(0.0, 1.0, size=(height, width, 1)).astype(np.float32)
    return np.clip(noise * amount, -0.5, 0.5)


def turbulence(
    shape: Tuple[int, int], rng: np.random.Generator, octaves: int = 4, persistence: float = 0.5
) -> Array:
    """Cheap fractal noise in 0..1, used for canvas/paper/stone textures."""
    height, width = shape[:2]
    total = np.zeros((height, width), dtype=np.float32)
    amplitude = 1.0
    norm = 0.0
    for octave in range(max(1, octaves)):
        cells = 2 ** octave
        grid = rng.random((max(2, cells + 1), max(2, cells + 1))).astype(np.float32)
        layer = np.asarray(
            Image.fromarray((grid * 255).astype(np.uint8)).resize(
                (width, height), Image.Resampling.BICUBIC
            ),
            dtype=np.float32,
        ) / 255.0
        total += layer * amplitude
        norm += amplitude
        amplitude *= persistence
    total /= max(norm, 1e-6)
    return np.clip(total, 0.0, 1.0)


def canvas_texture(
    shape: Tuple[int, int],
    rng: np.random.Generator,
    strength: float = 0.08,
    weave: int = 3,
) -> Array:
    """Woven canvas/linen weave plus fine tooth, broadcastable over RGB."""
    height, width = shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    warp = np.sin(xx * (np.pi / max(1, weave))) * 0.5
    weft = np.sin(yy * (np.pi / max(1, weave))) * 0.5
    linen = (warp * weft) * 0.5 + (warp + weft) * 0.25
    fuzz = rng.normal(0.0, 1.0, size=(height, width)).astype(np.float32) * 0.25
    texture = linen + fuzz
    return np.clip(texture * strength, -0.5, 0.5)[..., None]


def paper_texture(
    shape: Tuple[int, int], rng: np.random.Generator, strength: float = 0.09
) -> Array:
    """Soft fibrous grain for watercolour / pencil looks."""
    fibres = turbulence(shape, rng, octaves=3, persistence=0.6)
    fibres = (fibres - 0.5) * 1.4
    speckle = rng.normal(0.0, 0.35, size=fibres.shape).astype(np.float32)
    return np.clip((fibres + speckle) * strength, -0.5, 0.5)[..., None]


def vignette(shape: Tuple[int, int], strength: float = 0.35, power: float = 2.0) -> Array:
    """Radial darkening mask, broadcastable over RGB, 1 = untouched."""
    height, width = shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    radius = np.sqrt(((xx - cx) / max(cx, 1.0)) ** 2 + ((yy - cy) / max(cy, 1.0)) ** 2)
    radius = np.clip(radius / np.sqrt(2.0), 0.0, 1.0)
    mask = 1.0 - strength * np.power(radius, power)
    return np.clip(mask, 0.0, 1.0)[..., None]


def frame_border(array: Array, width: int, color: RGB = (245, 243, 236)) -> Array:
    """Paint a matte border around the image, like a mounted print."""
    if width <= 0:
        return clone(array)
    out = clone(array)
    width = min(width, min(out.shape[0], out.shape[1]) // 3)
    strip = np.array(color, dtype=np.float32) / 255.0
    out[:width, :, :] = strip
    out[-width:, :, :] = strip
    out[:, :width, :] = strip
    out[:, -width:, :] = strip
    return out


def paper_base(shape: Tuple[int, int], color: RGB = (250, 247, 238)) -> Array:
    """Flat paper colour image to composite onto."""
    height, width = shape[:2]
    return np.broadcast_to(
        np.array(color, dtype=np.float32) / 255.0, (height, width, 3)
    ).copy()


def dominant_tint(array: Array) -> Array:
    """Average colour of the image, shape ``(3,)``."""
    return array.reshape(-1, 3).mean(axis=0)


def mix_hue(array: Array, target: RGB, amount: float) -> Array:
    """Push the whole image towards a single tint (sepia, cyanotype, ...)."""
    tint = np.array(target, dtype=np.float32) / 255.0
    luma = luminance(array)[..., None]
    tinted = np.clip(tint[None, None, :] * (0.35 + luma * 0.9), 0.0, 1.0)
    return blend(array, tinted, amount)


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #
def ensure_min_size(array: Array, min_side: int) -> Array:
    """Upscale so the shortest side is at least *min_side*."""
    height, width = array.shape[:2]
    if min(height, width) >= min_side:
        return clone(array)
    scale = min_side / float(min(height, width))
    return resize_array(array, (max(1, int(width * scale)), max(1, int(height * scale))))


def luminance_to_rgb(grey: Array) -> Array:
    """``(H, W)`` -> ``(H, W, 3)``."""
    return np.repeat(grey[..., None], 3, axis=2) if grey.ndim == 2 else grey


def stack_arrays(arrays: Iterable[Array], margin: int = 0, background: float = 1.0) -> Array:
    """Horizontally concatenate arrays, optionally with a margin between them."""
    items = [luminance_to_rgb(np.asarray(a, dtype=np.float32)) for a in arrays]
    if not items:
        raise ValueError("stack_arrays needs at least one array")
    if margin <= 0:
        return np.concatenate(items, axis=1)
    height = max(item.shape[0] for item in items)
    padded: list[Array] = []
    for index, item in enumerate(items):
        if item.shape[0] < height:
            pad = height - item.shape[0]
            item = np.pad(item, ((pad // 2, pad - pad // 2), (0, 0), (0, 0)), mode="edge")
        if index:
            gap = np.full((height, margin, 3), background, dtype=np.float32)
            padded.append(gap)
        padded.append(item)
    return np.concatenate(padded, axis=1)


def diff_image(a: Array, b: Array) -> Array:
    """Absolute difference of two arrays, handy for tests."""
    return np.abs(a - b)


def to_pil_ops(image: Image.Image) -> Image.Image:
    """Round trip through ImageChops for Pillow-only filter paths."""
    return ImageChops.duplicate(image)
