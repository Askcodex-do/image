"""Smoke tests: every style must render a real, non-degenerate image."""

from __future__ import annotations

import numpy as np
import pytest

from fixtures import synthetic_photo
from pixelmuse import imgio
from pixelmuse.effects import core as C
from pixelmuse.generator import (
    RenderRequest,
    available_styles,
    build_contact_sheet,
    prepare_working_image,
    render_many,
    render_style,
)
from pixelmuse.styles import RenderOptions, get_style


@pytest.fixture(scope="module")
def source():
    return synthetic_photo()


def test_all_styles_registered():
    styles = available_styles()
    assert len(styles) >= 16, "expected a broad style library"
    keys = [style.key for style in styles]
    assert len(keys) == len(set(keys)), "style keys must be unique"
    for style in styles:
        assert style.label and style.family and style.blurb


@pytest.mark.parametrize("style", [s.key for s in available_styles()])
def test_style_renders_and_changes_image(style, source):
    request = RenderRequest(
        source=source, style_key=style, variants=1, options=RenderOptions(), max_side=240, seed=11
    )
    results = render_style(request)
    assert len(results) == 1
    rendered = results[0]

    assert rendered.image.mode == "RGB"
    assert rendered.image.width == 240
    assert rendered.image.height > 0

    original = prepare_working_image(source, 240)
    produced = C.to_array(rendered.image)
    assert produced.shape == original.shape
    assert np.isfinite(produced).all()

    # A style must actually change the image, and must not be a flat colour.
    difference = float(np.abs(produced - original).mean())
    assert difference > 0.01, f"{style} barely changed the image ({difference:.4f})"
    assert float(produced.std()) > 0.02, f"{style} produced a near-flat image"
    assert float(np.abs(produced - 0.5).max()) > 0.25, f"{style} has no tonal range"


def test_variants_differ_from_each_other(source):
    request = RenderRequest(
        source=source, style_key="oil_painting", variants=4, max_side=200, seed=99
    )
    results = render_style(request)
    assert len(results) == 4
    arrays = [C.to_array(item.image) for item in results]
    for index in range(1, len(arrays)):
        difference = float(np.abs(arrays[0] - arrays[index]).mean())
        assert difference > 1e-4, f"variant {index} is a duplicate of variant 0"


@pytest.mark.parametrize("style", [s.key for s in available_styles()])
def test_every_style_produces_distinct_variants(style, source):
    """A batch of N images must be N different takes, including the styles
    that are deterministic by nature (pixel art, line art, halftone)."""
    results = render_style(
        RenderRequest(source=source, style_key=style, variants=4, max_side=180, seed=17)
    )
    arrays = [C.to_array(item.image) for item in results]
    for index in range(1, len(arrays)):
        difference = float(np.abs(arrays[0] - arrays[index]).mean())
        assert difference > 1e-5, (
            f"{style}: variant {index} is identical to variant 0"
        )


def test_seed_is_reproducible(source):
    def render(seed: int) -> np.ndarray:
        request = RenderRequest(
            source=source, style_key="charcoal", variants=1, max_side=160, seed=seed
        )
        return C.to_array(render_style(request)[0].image)

    first, second = render(1234), render(1234)
    assert np.array_equal(first, second)

    other = render(4321)
    assert not np.array_equal(first, other)


def test_render_many_covers_every_style(source):
    keys = ["oil_painting", "pencil_sketch", "pixel_art"]
    results = render_many(source, keys, variants=2, max_side=160, seed=5)
    assert len(results) == len(keys) * 2
    assert {item.style_key for item in results} == set(keys)
    assert {item.variant for item in results if item.style_key == "pixel_art"} == {0, 1}


def test_unknown_style_raises(source):
    with pytest.raises(KeyError):
        render_style(RenderRequest(source=source, style_key="nope_not_real", variants=1))


def test_options_are_respected(source):
    loose = render_style(
        RenderRequest(
            source=source, style_key="oil_painting", variants=1, max_side=200, seed=3,
            options=RenderOptions(detail=0.05, canvas_texture=False, vignette=False),
        )
    )[0]
    tight = render_style(
        RenderRequest(
            source=source, style_key="oil_painting", variants=1, max_side=200, seed=3,
            options=RenderOptions(detail=0.98, canvas_texture=False, vignette=False),
        )
    )[0]
    difference = float(np.abs(C.to_array(loose.image) - C.to_array(tight.image)).mean())
    assert difference > 0.005, "detail setting should visibly change the result"


def test_contact_sheet(source):
    results = render_many(source, ["oil_painting", "charcoal", "pixel_art"], variants=1,
                          max_side=140, seed=2)
    sheet = build_contact_sheet(results, columns=2)
    assert sheet.width > 0 and sheet.height > 0
    assert sheet.mode == "RGB"


def test_load_and_save_round_trip(source, tmp_path):
    path = tmp_path / "in.png"
    source.save(path)
    loaded = imgio.load_image(path)
    assert loaded.size == source.size

    for extension in (".png", ".jpg", ".bmp"):
        target = imgio.save_image(loaded, tmp_path / f"out{extension}")
        assert target.exists() and target.stat().st_size > 0
        reopened = imgio.load_image(target)
        assert reopened.size == loaded.size


def test_large_images_are_downscaled_to_protect_ram(source):
    working = prepare_working_image(source, max_side=100)
    assert max(working.shape[:2]) <= 100


def test_style_lookup_by_key():
    assert get_style("oil_painting").label == "Oil Painting"
    assert get_style("pencil_sketch").family == "Drawing"
