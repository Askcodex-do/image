"""Painting-family styles: oils, acrylics, watercolour, pastel, gouache..."""

from __future__ import annotations

import numpy as np

from .effects import core as C
from .styles import xdog_lines
from .styles import (
    RenderOptions,
    Style,
    finish_pass,
    impasto,
    painterly_base,
    register,
)

Array = np.ndarray

_finish = finish_pass


# --------------------------------------------------------------------------- #
# oil painting
# --------------------------------------------------------------------------- #
def render_oil(array, rng, options: RenderOptions) -> Array:
    base = painterly_base(array, rng, options)
    base = C.adjust_saturation(base, 1.14)
    base = C.adjust_contrast(base, 1.06)
    relief = C.edges(base, radius=1.1, gain=0.8)[..., None]
    base = impasto(relief, base, amount=0.28 + 0.22 * options.strength)
    base = C.curve(base, [(0.0, 0.015), (0.28, 0.26), (0.72, 0.78), (1.0, 0.99)])
    return _finish(base, options, rng, texture_strength=0.11, weave=3)


register(Style(
    key="oil_painting",
    label="Oil Painting",
    family="Painting",
    blurb="Thick blended brush strokes with visible canvas grain.",
    render=render_oil,
    keywords=("oil", "painting", "canvas", "brush"),
))


# --------------------------------------------------------------------------- #
# oil painting, realism
# --------------------------------------------------------------------------- #
def render_oil_realism(array, rng, options: RenderOptions) -> Array:
    tight = options.child(detail=max(options.detail, 0.78))
    base = painterly_base(array, rng, tight)
    # Tighter strokes and gentler colour crushing keep the scene believable.
    base = C.blend(base, C.blur(base, 0.9), 0.5)
    base = C.unsharp(base, radius=1.6, amount=0.5)
    base = C.adjust_saturation(base, 1.09)
    base = C.adjust_contrast(base, 1.08)
    base = C.auto_contrast(base, 1.5, 98.5)
    relief = C.edges(base, radius=0.8, gain=0.9)[..., None]
    base = impasto(relief, base, amount=0.16 + 0.14 * options.strength)
    # Fresnel varnish: a warm sheen in the highlights.
    hot = np.clip((C.luminance(base) - 0.7) * 3.0, 0.0, 1.0)[..., None]
    varnish = C.colorize(hot, (255, 250, 235), (255, 246, 226))
    base = C.blend(base, C.soft_light(base, varnish), 0.35)
    return _finish(base, options, rng, texture_strength=0.055, weave=4,
                   vignette_strength=0.2, grain_amount=0.008)


register(Style(
    key="oil_realism",
    label="Oil Painting (Realism)",
    family="Painting",
    blurb="Realistic oil look: fine strokes, deep colour, subtle varnish.",
    render=render_oil_realism,
    keywords=("oil", "realism", "realistic", "portrait"),
))


# --------------------------------------------------------------------------- #
# acrylic / impasto pop
# --------------------------------------------------------------------------- #
def render_acrylic(array, rng, options: RenderOptions) -> Array:
    base = painterly_base(array, rng, options)
    base = C.adjust_saturation(base, 1.3)
    base = C.posterize(base, max(5, min(9, options.colors // 2)))
    base = C.adjust_contrast(base, 1.16)
    relief = C.edges(base, radius=1.6, gain=1.3)[..., None]
    base = impasto(relief, base, amount=0.5 + 0.3 * options.strength)
    base = np.clip(base * (1.0 - relief * 0.35) + base * 1.02, 0.0, 1.0)
    return _finish(base, options, rng, texture_strength=0.16, weave=5)


register(Style(
    key="acrylic",
    label="Acrylic (Impasto)",
    family="Painting",
    blurb="Bold flat colour, thick raised paint, strong texture.",
    render=render_acrylic,
    keywords=("acrylic", "impasto", "bold"),
))


# --------------------------------------------------------------------------- #
# watercolour
# --------------------------------------------------------------------------- #
def render_watercolour(array, rng, options: RenderOptions) -> Array:
    paper = C.paper_base(array.shape, (250, 246, 236))
    wash = C.blur(array, 1.6 - options.detail * 0.8)
    wash = C.adjust_saturation(wash, 1.35)
    wash = C.auto_contrast(wash, 2.0, 97.0)
    # Lifting the highlights gives that translucent, layered pigment feel.
    lighten = C.blend(wash, C.screen(wash, wash), 0.45)
    pigment = C.blend(wash, lighten, 0.4)
    pigment = C.quantize_palette(pigment, max(6, min(16, options.colors)), dither=True)
    pigment = C.adjust_contrast(pigment, 0.92)

    # Soft wet-on-wet blotches, one per generated variant.
    for index in range(6 + int(options.detail * 6)):
        blot = C.turbulence(array.shape, rng, octaves=2, persistence=0.7)
        threshold = 0.62 + rng.random() * 0.15
        mask = np.clip((blot - threshold) * 3.0, 0.0, 1.0)[..., None]
        colour = rng.random(3).astype(np.float32) * np.array(
            [0.4, 0.3, 0.35], dtype=np.float32
        )
        pigment = pigment * (1.0 - mask * 0.25) + colour[None, None, :] * mask * 0.25

    # Pigment only sticks to the wet paper, so let the tooth show through.
    tooth = C.paper_texture(array.shape, rng, strength=0.22)
    pigment = np.clip(paper + (pigment - paper) * (0.9 + tooth), 0.0, 1.0)
    pigment = C.unsharp(pigment, radius=1.4, amount=0.35)
    return _finish(pigment, options, rng, texture_strength=0.0, vignette_strength=0.12,
                   grain_amount=0.0)


register(Style(
    key="watercolour",
    label="Watercolour",
    family="Painting",
    blurb="Translucent washes, blooming edges, rough paper tooth.",
    render=render_watercolour,
    keywords=("watercolour", "watercolor", "wash", "aquarelle"),
))


# --------------------------------------------------------------------------- #
# gouache / poster paint
# --------------------------------------------------------------------------- #
def render_gouache(array, rng, options: RenderOptions) -> Array:
    base = C.median(array, 5)
    base = C.blur(base, 1.1)
    base = C.adjust_saturation(base, 1.2)
    base = C.posterize(base, max(5, min(10, options.colors // 2 + 3)))
    base = C.auto_contrast(base, 3.0, 97.0)
    base = C.adjust_contrast(base, 1.1)
    base = C.curve(base, [(0.0, 0.05), (0.5, 0.52), (1.0, 0.96)])
    return _finish(base, options, rng, texture_strength=0.07, weave=4,
                   vignette_strength=0.18, grain_amount=0.01)


register(Style(
    key="gouache",
    label="Gouache",
    family="Painting",
    blurb="Opaque matte colour, flattened planes, poster-paint feel.",
    render=render_gouache,
    keywords=("gouache", "matte", "poster"),
))


# --------------------------------------------------------------------------- #
# palette knife
# --------------------------------------------------------------------------- #
def render_palette_knife(array, rng, options: RenderOptions) -> Array:
    base = C.median(array, 5)
    base = C.adjust_saturation(base, 1.25)
    # A handful of large, angled smears approximate a knife dragging paint.
    result = C.clone(base)
    layers = 26 + int((1.0 - options.detail) * 24)
    for _ in range(layers):
        angle = rng.random() * 180.0
        length = int(rng.integers(18, 46))
        thickness = int(rng.integers(3, 9))
        smeared = C.shift(base, int(np.cos(np.deg2rad(angle)) * length),
                          int(-np.sin(np.deg2rad(angle)) * length))
        smeared = C.blur(smeared, thickness)
        tint = rng.uniform(-0.35, 0.35, size=3).astype(np.float32)
        smeared = np.clip(smeared + tint * 0.06, 0.0, 1.0)

        region = C.turbulence(array.shape, rng, octaves=2)
        threshold = 0.55 + rng.random() * 0.2
        mask = np.clip((region - threshold) * 2.5, 0.0, 1.0)[..., None]
        result = result * (1.0 - mask) + smeared * mask
    result = C.adjust_contrast(result, 1.1)
    relief = C.edges(result, radius=2.2, gain=0.9)[..., None]
    result = impasto(relief, result, amount=0.45)
    return _finish(result, options, rng, texture_strength=0.12, weave=6)


register(Style(
    key="palette_knife",
    label="Palette Knife",
    family="Painting",
    blurb="Sculpted smears of thick paint, one bold plane at a time.",
    render=render_palette_knife,
    keywords=("knife", "palette", "impasto", "spatula"),
))


# --------------------------------------------------------------------------- #
# pastel / chalk
# --------------------------------------------------------------------------- #
def render_pastel(array, rng, options: RenderOptions) -> Array:
    soft = C.blur(array, 1.0)
    soft = C.adjust_saturation(soft, 0.92)
    soft = C.adjust_contrast(soft, 0.9)
    pastel = C.blend(soft, C.paper_base(array.shape, (248, 242, 230)), 0.22)
    # Chalk dust and paper tooth.
    pastel = np.clip(pastel + C.paper_texture(array.shape, rng, 0.35), 0.0, 1.0)
    strokes = C.edges(array, radius=1.0, gain=1.0)[..., None]
    pastel = C.blend(pastel, C.screen(pastel, pastel), 0.25 * strokes)
    pastel = C.unsharp(pastel, radius=2.2, amount=0.3)
    return _finish(pastel, options, rng, texture_strength=0.04, vignette_strength=0.14,
                   grain_amount=0.02)


register(Style(
    key="pastel",
    label="Soft Pastel",
    family="Painting",
    blurb="Powdery chalk colour rubbed into textured paper.",
    render=render_pastel,
    keywords=("pastel", "chalk", "soft"),
))


# --------------------------------------------------------------------------- #
# ink wash / sumi-e
# --------------------------------------------------------------------------- #
def render_ink_wash(array, rng, options: RenderOptions) -> Array:
    grey = C.luminance(array)
    grey = C.auto_contrast(C.luminance(array)[..., None], 2.0, 98.0)[..., 0]
    wash = C.blur(grey[..., None], 2.4 - options.detail * 1.4)[..., 0]
    wash = C.adjust_contrast(wash, 1.25)
    ink = C.colorize(wash[..., None], (18, 20, 26), (246, 244, 238))
    # Brush lines: dark contours that fade with the surrounding grey.
    lines = xdog_lines(array, detail=options.detail)
    ink = np.clip(ink * (0.35 + lines[..., None] * 0.85), 0.0, 1.0)
    splashes = C.turbulence(array.shape, rng, octaves=3, persistence=0.55)
    splatter = np.clip((splashes - 0.8) * 6.0, 0.0, 1.0)[..., None]
    ink = ink * (1.0 - splatter * 0.6)
    ink = np.clip(ink + C.canvas_texture(array.shape, rng, 0.05, 8), 0.0, 1.0)
    return _finish(ink, options, rng, texture_strength=0.0, vignette_strength=0.1,
                   grain_amount=0.008)


register(Style(
    key="ink_wash",
    label="Ink Wash (Sumi-e)",
    family="Painting",
    blurb="Monochrome brush ink diffusing into wet rice paper.",
    render=render_ink_wash,
    keywords=("ink", "sumi", "wash", "brush"),
))


# --------------------------------------------------------------------------- #
# spray / street art
# --------------------------------------------------------------------------- #
def render_spray(array, rng, options: RenderOptions) -> Array:
    base = C.median(array, 5)
    base = C.adjust_saturation(base, 1.45)
    base = C.posterize(base, max(4, min(8, options.colors // 2)))
    base = C.adjust_contrast(base, 1.18)
    result = C.clone(base)
    for _ in range(10 + int((1.0 - options.detail) * 14)):
        canvas = C.turbulence(array.shape, rng, octaves=3, persistence=0.6)
        threshold = 0.5 + rng.random() * 0.25
        mask = np.clip((canvas - threshold) * 3.5, 0.0, 1.0)[..., None]
        colour = np.array([rng.random(), rng.random(), rng.random()], dtype=np.float32)
        result = result * (1.0 - mask * 0.5) + colour[None, None, :] * mask * 0.5
    speckles = (rng.random(array.shape) > 0.9955).astype(np.float32)
    result = np.clip(result + C.blur(speckles, 0.7) * 0.9, 0.0, 1.0)
    stencil = C.edges(result, radius=1.4, gain=1.2)[..., None]
    result = np.clip(result * (1.0 - stencil * 0.3), 0.0, 1.0)
    return _finish(result, options, rng, texture_strength=0.05, vignette_strength=0.3,
                   grain_amount=0.015)


register(Style(
    key="spray_paint",
    label="Spray Paint / Stencil",
    family="Painting",
    blurb="Urban stencil colour with soft aerosol edges and speckle.",
    render=render_spray,
    keywords=("spray", "graffiti", "stencil", "street"),
))
