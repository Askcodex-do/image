"""Drawing-family styles: pencil, charcoal, ink, marker, digital art..."""

from __future__ import annotations

import numpy as np
from PIL import Image

from .effects import core as C
from .styles import dodge_sketch, xdog_lines
from .styles import (
    RenderOptions,
    Style,
    finish_pass,
    hatching_overlay,
    register,
)

Array = np.ndarray

_finish = finish_pass


# --------------------------------------------------------------------------- #
# graphite pencil sketch
# --------------------------------------------------------------------------- #
def render_pencil_sketch(array, rng, options: RenderOptions) -> Array:
    paper_colour = (247, 244, 236)
    paper = C.paper_base(array.shape, paper_colour)

    grey = C.luminance(array)
    grey = C.auto_contrast(grey[..., None], 1.5, 98.5)[..., 0]
    tone = 1.0 - C.blur(grey[..., None], 1.2 - options.detail)[..., 0]
    lines = xdog_lines(array, detail=options.detail)
    strokes = dodge_sketch(array, blade=0.55 + (1.0 - options.detail) * 0.4, smooth=2.2)

    graphite = np.clip(tone * 0.75 + (1.0 - C.luminance(strokes)) * 0.5, 0.0, 1.0)
    graphite = np.maximum(graphite, (1.0 - lines) * 0.85)

    hatch = hatching_overlay(array.shape, rng, tone, 28.0 + rng.random() * 14.0, 7.0)
    graphite = np.clip(graphite + hatch[..., 0] * 0.28 * (1.0 - options.detail * 0.4),
                       0.0, 1.0)

    darkness = np.clip(graphite * 0.72, 0.0, 0.82)
    out = paper * (1.0 - darkness[..., None])
    out = np.clip(out + C.paper_texture(array.shape, rng, 0.5), 0.0, 1.0)
    return _finish(out, options, rng, texture_strength=0.0, vignette_strength=0.12,
                   grain_amount=0.006)


register(Style(
    key="pencil_sketch",
    label="Pencil Sketch",
    family="Drawing",
    blurb="Graphite line work on paper with light hatching.",
    render=render_pencil_sketch,
    keywords=("pencil", "sketch", "graphite", "drawing"),
))


# --------------------------------------------------------------------------- #
# charcoal
# --------------------------------------------------------------------------- #
def render_charcoal(array, rng, options: RenderOptions) -> Array:
    paper = C.paper_base(array.shape, (240, 238, 232))
    grey = C.luminance(array)
    grey = C.auto_contrast(grey[..., None], 2.0, 98.0)[..., 0]
    soft = C.blur(grey[..., None], 2.6 - options.detail * 1.2)[..., 0]
    smudge = C.blur(grey[..., None], 4.0)[..., 0]

    mass = np.clip((1.0 - soft) * 0.75 + (1.0 - smudge) * 0.45, 0.0, 1.0)
    lines = xdog_lines(array, detail=max(0.4, options.detail))
    mass = np.maximum(mass, (1.0 - lines) * 0.95)
    mass = np.power(mass, 0.85)
    mass = np.clip(mass * (0.9 + 0.2 * rng.random()), 0.0, 0.94)

    out = paper * (1.0 - mass[..., None])
    dust = C.turbulence(array.shape, rng, octaves=3, persistence=0.65)
    out = np.clip(out * (0.94 + dust[..., None] * 0.12), 0.0, 1.0)
    out = np.clip(out + C.paper_texture(array.shape, rng, 0.55), 0.0, 1.0)
    return _finish(out, options, rng, texture_strength=0.0, vignette_strength=0.22,
                   grain_amount=0.02)


register(Style(
    key="charcoal",
    label="Charcoal",
    family="Drawing",
    blurb="Smudged dark masses with a dry, dusty edge.",
    render=render_charcoal,
    keywords=("charcoal", "smudge", "dark"),
))


# --------------------------------------------------------------------------- #
# digital sketch (clean line art + flat colour)
# --------------------------------------------------------------------------- #
def render_digital_sketch(array, rng, options: RenderOptions) -> Array:
    # Each variant picks a different palette size and line weight so a batch
    # looks like a set of alternative takes rather than four copies.
    variant = options.variant % 4
    palette_size = max(8, min(28, options.colors * 2 + variant * 3))
    line_weight = 0.68 + variant * 0.09

    flat = C.median(array, 5)
    flat = C.blur(flat, 0.8 + variant * 0.12)
    flat = C.quantize_palette(flat, palette_size, dither=False)
    flat = C.adjust_saturation(flat, 1.12 + variant * 0.04)
    flat = C.adjust_contrast(flat, 1.05)

    lines = xdog_lines(array, detail=max(0.4, min(0.95, options.detail + variant * 0.08)))
    ink = np.clip((1.0 - lines) * line_weight, 0.0, 1.0)[..., None]
    line_colour = C.colorize(np.ones(array.shape[:2])[..., None], (26, 24, 32), (26, 24, 32))
    out = flat * (1.0 - ink) + line_colour * ink

    glow = np.clip((C.luminance(flat) - 0.82) * 4.0, 0.0, 1.0)[..., None]
    out = C.blend(out, C.screen(out, out), 0.18 * glow)
    out = C.unsharp(out, radius=0.9, amount=0.5)
    return _finish(out, options, rng, texture_strength=0.0, vignette_strength=0.08,
                   grain_amount=0.0)


register(Style(
    key="digital_sketch",
    label="Digital Sketch",
    family="Drawing",
    blurb="Clean vector-like line art with flat cel colour.",
    render=render_digital_sketch,
    keywords=("digital", "lineart", "cel", "vector"),
))


# --------------------------------------------------------------------------- #
# manga / comic ink
# --------------------------------------------------------------------------- #
def render_comic_ink(array, rng, options: RenderOptions) -> Array:
    # Vary the screentone pitch and contrast between variants.
    variant = options.variant % 4
    cell = max(3, int(round(7 - options.detail * 3 - variant * 0.5)))
    levels = max(2, min(5, 2 + int(options.detail * 3) + (1 if variant % 2 else 0)))

    grey = C.luminance(array)
    grey = C.auto_contrast(grey[..., None], 2.0, 98.0)[..., 0]
    quant = C.posterize(grey[..., None], levels)[..., 0]

    # Halftone dots: dot radius follows the tone, mimicking screentone.
    height, width = array.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    cx = (xx % cell) - (cell - 1) / 2.0
    cy = (yy % cell) - (cell - 1) / 2.0
    distance = np.sqrt(cx * cx + cy * cy) / (cell * 0.62)
    dots = np.where(distance < np.clip(1.0 - quant, 0.0, 1.0), 0.0, 1.0)

    lines = xdog_lines(array, detail=max(0.4, min(0.95, options.detail + variant * 0.07)))
    ink = np.minimum(dots, np.clip(lines, 0.0, 1.0))
    ink = np.clip(ink * (0.85 + variant * 0.04) + 0.05, 0.0, 1.0)

    wash = np.clip(0.5 + variant * 0.05 + grey * 0.45, 0.0, 1.0)[..., None]
    out = (ink[..., None] * 0.72 + wash * 0.28)
    out = C.quantize_palette(out, max(3, min(6, options.colors // 3)), dither=False)
    return _finish(out, options, rng, texture_strength=0.0, vignette_strength=0.06,
                   grain_amount=0.0)


register(Style(
    key="comic_ink",
    label="Comic Ink (Halftone)",
    family="Drawing",
    blurb="Bold black outlines with screentone dot shading.",
    render=render_comic_ink,
    keywords=("comic", "manga", "halftone", "screentone"),
))


# --------------------------------------------------------------------------- #
# ballpoint pen doodle
# --------------------------------------------------------------------------- #
def render_ballpoint(array, rng, options: RenderOptions) -> Array:
    paper = C.paper_base(array.shape, (250, 249, 244))
    grey = C.auto_contrast(C.luminance(array)[..., None], 2.0, 98.0)[..., 0]
    tone = 1.0 - C.blur(grey[..., None], 1.0)[..., 0]

    result = paper.copy()
    density = 14 + int((1.0 - options.detail) * 12)
    for _ in range(density):
        angle = rng.uniform(15.0, 165.0)
        spacing = rng.uniform(4.5, 9.0)
        hatch = hatching_overlay(array.shape, rng, tone, angle, spacing)[..., 0]
        weight = rng.uniform(0.10, 0.26)
        result = result * (1.0 - hatch[..., None] * weight)

    lines = xdog_lines(array, detail=max(0.5, options.detail))
    contour = (1.0 - lines)[..., None] * 0.55
    pen_colour = C.colorize(np.ones(array.shape[:2])[..., None], (22, 42, 132), (22, 42, 132))
    result = result * (1.0 - contour) + pen_colour * contour
    result = np.clip(result + C.paper_texture(array.shape, rng, 0.4), 0.0, 1.0)
    return _finish(result, options, rng, texture_strength=0.0, vignette_strength=0.1,
                   grain_amount=0.005)


register(Style(
    key="ballpoint",
    label="Ballpoint Pen",
    family="Drawing",
    blurb="Fine blue biro hatching, like a sketchbook doodle.",
    render=render_ballpoint,
    keywords=("pen", "ballpoint", "biro", "doodle"),
))


# --------------------------------------------------------------------------- #
# ink line art (white background, pure contours)
# --------------------------------------------------------------------------- #
def render_lineart(array, rng, options: RenderOptions) -> Array:
    # Variants trade off line weight and how much grey shading is left in.
    variant = options.variant % 4
    paper_tone = (252, 251, 248) if variant % 2 == 0 else (249, 247, 242)
    paper = C.paper_base(array.shape, paper_tone)

    detail = max(0.35, min(0.95, options.detail + variant * 0.09))
    lines = xdog_lines(array, detail=detail)
    strength = 0.55 + 0.35 * options.strength + variant * 0.06
    contour = np.clip((1.0 - lines) * strength, 0.0, 1.0)[..., None]

    ink_rgb = (30, 30, 34) if variant % 2 == 0 else (44, 38, 32)
    ink = C.colorize(np.ones(array.shape[:2])[..., None], ink_rgb, ink_rgb)
    out = paper * (1.0 - contour) + ink * contour

    # A whisper of grey so large shapes do not read as flat white.
    shadow_amount = 0.10 - variant * 0.022
    shadow = np.clip(1.0 - C.blur(C.luminance(array)[..., None], 6.0), 0.0, 1.0) * shadow_amount
    out = np.clip(out * (1.0 - shadow), 0.0, 1.0)
    return _finish(out, options, rng, texture_strength=0.0, vignette_strength=0.05,
                   grain_amount=0.0)


register(Style(
    key="lineart",
    label="Ink Line Art",
    family="Drawing",
    blurb="Pure black contours on clean white, colouring-book style.",
    render=render_lineart,
    keywords=("lineart", "outline", "colouring", "vector"),
))


# --------------------------------------------------------------------------- #
# blueprint / technical drawing
# --------------------------------------------------------------------------- #
def render_blueprint(array, rng, options: RenderOptions) -> Array:
    # Variants vary the paper blue and the grid pitch, like different sheets.
    variant = options.variant % 4
    paper_colours = [(14, 42, 92), (20, 52, 104), (10, 34, 78), (26, 60, 112)]
    paper = C.paper_base(array.shape, paper_colours[variant])
    grid_step = 18 + variant * 6

    height, width = array.shape[:2]
    lines = xdog_lines(array, detail=max(0.45, min(0.95, options.detail + variant * 0.06)))
    edges_ink = np.clip((1.0 - lines) * (0.65 + 0.3 * options.strength), 0.0, 1.0)

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    grid = ((np.abs((xx % grid_step) - grid_step / 2) < 0.8) |
            (np.abs((yy % grid_step) - grid_step / 2) < 0.8)).astype(np.float32)
    major = ((np.abs((xx % (grid_step * 4)) - grid_step * 2) < 0.9) |
             (np.abs((yy % (grid_step * 4)) - grid_step * 2) < 0.9)).astype(np.float32)
    grid = np.clip(grid * 0.12 + major * 0.22, 0.0, 1.0)

    white = np.array([225, 238, 255], dtype=np.float32) / 255.0
    out = np.clip(paper + grid[..., None], 0.0, 1.0)
    ink = np.clip(edges_ink * 0.92 + grid * 0.35, 0.0, 1.0)
    out = out * (1.0 - ink[..., None] * 0.55) + white * ink[..., None] * 0.55

    dimension = np.clip((C.luminance(array) - 0.6) * 2.0, 0.0, 1.0) * 0.25
    out = np.clip(out + dimension[..., None] * white, 0.0, 1.0)
    return _finish(out, options, rng, texture_strength=0.0, vignette_strength=0.18,
                   grain_amount=0.004)


register(Style(
    key="blueprint",
    label="Blueprint",
    family="Drawing",
    blurb="Cyan engineering paper with grid and white line work.",
    render=render_blueprint,
    keywords=("blueprint", "technical", "grid", "cyan"),
))


# --------------------------------------------------------------------------- #
# pop art (Warhol-style flats)
# --------------------------------------------------------------------------- #
def render_pop_art(array, rng, options: RenderOptions) -> Array:
    palette_pool = [
        (255, 214, 0), (255, 65, 108), (0, 180, 216), (140, 82, 255),
        (0, 220, 130), (255, 120, 40),
    ]
    base = C.median(array, 5)
    base = C.blur(base, 1.2)
    base = C.posterize(base, 4)
    base = C.adjust_saturation(base, 1.5)

    shift = int(rng.integers(0, len(palette_pool)))
    ramp = [palette_pool[(shift + i) % len(palette_pool)] for i in range(4)]
    ramp.sort(key=lambda rgb: C.luminance(np.array(rgb, dtype=np.float32) / 255.0))
    mapped = C.gradient_map(base, ramp)

    lines = xdog_lines(array, detail=max(0.5, options.detail))
    contour = np.clip((1.0 - lines) * 0.85, 0.0, 1.0)[..., None]
    out = mapped * (1.0 - contour) + 0.03 * contour
    out = C.adjust_contrast(out, 1.12)
    return _finish(out, options, rng, texture_strength=0.0, vignette_strength=0.1,
                   grain_amount=0.008)


register(Style(
    key="pop_art",
    label="Pop Art",
    family="Drawing",
    blurb="Four-screen print with a loud, limited colour ramp.",
    render=render_pop_art,
    keywords=("pop", "warhol", "screenprint", "poster"),
))


# --------------------------------------------------------------------------- #
# pixel art
# --------------------------------------------------------------------------- #
def render_pixel_art(array, rng, options: RenderOptions) -> Array:
    # Variants step through sprite resolutions, from chunky to detailed.
    variant = options.variant % 4
    height, width = array.shape[:2]
    block = max(2, int(round(2 + (1.0 - options.detail) * 5 + variant)))

    small = (max(16, width // block), max(16, height // block))
    pixels = C.resize_array(C.median(array, 3), small)
    palette_size = max(8, min(32, options.colors + variant * 4))
    pixels = C.quantize_palette(pixels, palette_size, dither=False)
    pixels = C.adjust_saturation(pixels, 1.18 + variant * 0.05)
    pixels = C.adjust_contrast(pixels, 1.06 + variant * 0.02)
    out = C.to_image(pixels).resize((width, height), Image.Resampling.NEAREST)
    return _finish(C.to_array(out), options, rng, texture_strength=0.0,
                   vignette_strength=0.08, grain_amount=0.0)


register(Style(
    key="pixel_art",
    label="Pixel Art",
    family="Drawing",
    blurb="Chunky low-resolution sprite, hard pixels and flat colour.",
    render=render_pixel_art,
    keywords=("pixel", "8bit", "retro", "sprite"),
))


# --------------------------------------------------------------------------- #
# noir / high contrast
# --------------------------------------------------------------------------- #
def render_noir(array, rng, options: RenderOptions) -> Array:
    grey = C.luminance(array)
    grey = C.auto_contrast(grey[..., None], 1.0, 99.0)[..., 0]
    grey = C.adjust_contrast(grey[..., None], 1.55)[..., 0]
    grey = C.curve(grey[..., None], [(0.0, 0.0), (0.42, 0.12), (0.62, 0.82), (1.0, 1.0)])[..., 0]
    out = C.colorize(grey[..., None], (8, 9, 12), (238, 236, 230))
    out = np.clip(out + C.grain(out.shape, rng, 0.03), 0.0, 1.0)
    return _finish(out, options, rng, texture_strength=0.0, vignette_strength=0.4,
                   grain_amount=0.012)


register(Style(
    key="noir",
    label="Film Noir",
    family="Drawing",
    blurb="Crushed blacks, blown highlights, heavy 1940s mood.",
    render=render_noir,
    keywords=("noir", "black", "white", "contrast", "film"),
))
