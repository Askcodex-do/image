"""Shared test fixtures: a deterministic synthetic photo to stylise."""

from __future__ import annotations

import numpy as np
from PIL import Image


def synthetic_photo(width: int = 320, height: int = 240, seed: int = 7) -> Image.Image:
    """A synthetic but photo-like scene: sky gradient, sun, hills, foliage.

    Deterministic so tests can assert on stable numbers without shipping
    binary fixtures in the repository.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    v = yy / float(height - 1)

    # Sky: blue to warm at the horizon.
    sky = np.stack(
        [
            0.28 + 0.45 * v,
            0.45 + 0.25 * v,
            0.78 - 0.30 * v,
        ],
        axis=-1,
    )
    # Sun with a soft halo.
    cx, cy = width * 0.72, height * 0.24
    distance = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    sun = np.exp(-(distance / (width * 0.09)) ** 2)
    sky = np.clip(sky + sun[..., None] * np.array([0.9, 0.75, 0.35], dtype=np.float32), 0.0, 1.0)

    # Hills: two rolling bands of green/brown.
    horizon = height * 0.62
    hill_a = horizon + np.sin(xx / 26.0) * 8.0
    hill_b = horizon + 42.0 + np.sin(xx / 41.0 + 1.4) * 12.0
    ground = np.where(v * height > hill_a, 1.0, 0.0)
    deeper = np.where(v * height > hill_b, 1.0, 0.0)
    scene = sky * (1.0 - ground[..., None])
    grass = np.array([0.22, 0.42, 0.20], dtype=np.float32)
    soil = np.array([0.30, 0.24, 0.16], dtype=np.float32)
    texture = (np.sin(xx / 3.0) * np.cos(yy / 4.0) * 0.5 + 0.5) * 0.12
    scene = scene + ground[..., None] * (grass + texture[..., None])
    scene = np.where(deeper[..., None] > 0.5, soil + texture[..., None] * 0.4, scene)

    # A couple of dark blobs, so edge-based styles have real contours.
    for bx, by, br, colour in ((0.22, 0.5, 0.13, (0.10, 0.16, 0.09)),
                               (0.45, 0.45, 0.09, (0.14, 0.20, 0.10))):
        blob = np.sqrt((xx - width * bx) ** 2 + (yy - height * by) ** 2) < width * br
        scene = np.where(blob[..., None], np.array(colour, dtype=np.float32), scene)

    scene = scene + rng.normal(0.0, 0.008, scene.shape).astype(np.float32)
    return Image.fromarray((np.clip(scene, 0.0, 1.0) * 255.0).astype(np.uint8), mode="RGB")
