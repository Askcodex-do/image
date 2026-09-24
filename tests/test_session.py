"""Tests for the headless app state that both UIs are built on."""

from __future__ import annotations

import zipfile

import pytest

from fixtures import synthetic_photo
from pixelmuse import session
from pixelmuse.styles import RenderOptions


@pytest.fixture
def state(tmp_path):
    st = session.AppState(output_dir=tmp_path / "out")
    source = tmp_path / "source.png"
    synthetic_photo(240, 180).save(source)
    session.load_source(st, source)
    return st


def test_load_source_builds_thumbnail(state):
    assert state.has_source
    assert state.source_path is not None
    assert state.thumbnail is not None
    assert max(state.thumbnail.size) <= 512
    assert not state.can_render, "no style selected yet"


def test_toggle_and_select_styles(state):
    session.toggle_style(state, "oil_painting")
    session.toggle_style(state, "charcoal")
    assert state.selected == ["oil_painting", "charcoal"]
    session.toggle_style(state, "oil_painting")
    assert state.selected == ["charcoal"]

    session.select_styles(state, ["pixel_art", "pixel_art", "noir"])
    assert state.selected == ["pixel_art", "noir"]
    assert state.can_render


def test_unknown_style_is_rejected(state):
    with pytest.raises(KeyError):
        session.toggle_style(state, "not_a_style")
    with pytest.raises(KeyError):
        session.select_styles(state, ["noir", "not_a_style"])


def test_render_sync_stores_results(state):
    session.select_styles(state, ["oil_painting"])
    state.variants = 2
    state.max_side = 180
    results = session.render_sync(state)
    assert len(results) == 2
    assert len(state.results) == 2
    assert state.current_result is not None
    assert session.summary(state).startswith("1 style(s)")


def test_render_requires_selection(state):
    with pytest.raises(RuntimeError):
        session.render_sync(state)


def test_navigation_wraps_around(state):
    session.select_styles(state, ["noir"])
    state.variants = 3
    state.max_side = 160
    session.render_sync(state)
    assert state.result_index == 0
    session.previous_result(state)
    assert state.result_index == 2
    session.next_result(state)
    assert state.result_index == 0


def test_clear_results_releases_memory(state):
    session.select_styles(state, ["noir"])
    state.variants = 2
    state.max_side = 160
    session.render_sync(state)
    session.clear_results(state)
    assert state.results == []
    assert state.current_result is None


def test_render_async_reports_back(state):
    import threading

    session.select_styles(state, ["comic_ink"])
    state.variants = 1
    state.max_side = 160

    finished = threading.Event()
    captured = {}

    def done(images, error):
        captured["images"] = images
        captured["error"] = error
        finished.set()

    thread = session.render_async(state, done=done)
    assert finished.wait(timeout=60), "render thread did not finish"
    thread.join(timeout=5)
    assert captured["error"] is None
    assert len(captured["images"]) == 1


def test_render_async_surfaces_errors(state):
    import threading

    state.selected = ["oil_painting"]  # bypass validation to force a failure
    state.source_image = None
    finished = threading.Event()
    captured = {}

    def done(images, error):
        captured["error"] = error
        finished.set()

    session.render_async(state, done=done)
    assert finished.wait(timeout=30)
    assert isinstance(captured["error"], RuntimeError)


def test_save_helpers(state, tmp_path):
    session.select_styles(state, ["noir", "pixel_art"])
    state.variants = 2
    state.max_side = 160
    session.render_sync(state)

    single = session.save_current(state, tmp_path / "one.png")
    assert single.exists()

    written = session.save_all(state, tmp_path / "all")
    assert len(written) == 4

    bundle = session.save_zip(state, tmp_path / "batch.zip")
    with zipfile.ZipFile(bundle) as archive:
        assert len(archive.namelist()) == 4

    sheet = session.save_contact_sheet(state, tmp_path / "sheet.png", columns=2)
    assert sheet.exists() and sheet.stat().st_size > 0

    pdf = session.save_pdf(state, tmp_path / "batch.pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    assert pdf.stat().st_size > 1000


def test_save_without_results_is_an_error(state, tmp_path):
    with pytest.raises(RuntimeError):
        session.save_current(state, tmp_path / "nope.png")
    with pytest.raises(RuntimeError):
        session.save_all(state)
    with pytest.raises(RuntimeError):
        session.save_zip(state, tmp_path / "nope.zip")
    with pytest.raises(RuntimeError):
        session.save_pdf(state, tmp_path / "nope.pdf")


def test_styles_grouped_covers_every_style():
    grouped = session.styles_grouped()
    total = sum(len(items) for items in grouped.values())
    assert total >= 16
    assert "Painting" in grouped and "Drawing" in grouped


def test_options_propagate_through_state(state):
    session.select_styles(state, ["oil_painting"])
    state.variants = 1
    state.max_side = 160
    state.options = RenderOptions(detail=0.1, canvas_texture=False, vignette=False)
    first = session.render_sync(state)[0]
    session.clear_results(state)
    state.options = RenderOptions(detail=0.95, canvas_texture=False, vignette=False)
    state.seed = 7
    second = session.render_sync(state)[0]
    from pixelmuse.effects import core as C
    import numpy as np

    difference = float(np.abs(C.to_array(first.image) - C.to_array(second.image)).mean())
    assert difference > 0.005


# ---------------------------------------------------------------------------
# Text-guided mode
# ---------------------------------------------------------------------------


def test_can_describe_needs_an_image_and_words(state):
    assert not state.can_describe          # no description yet
    state.description = "   "
    assert not state.can_describe          # whitespace is not a description
    state.description = "add a crown"
    assert state.can_describe


def test_can_describe_does_not_need_styles(state):
    """The description drives this mode; style checkboxes are irrelevant."""
    state.selected = []
    state.description = "make it snow"
    assert state.can_describe


def test_describe_sync_requires_input(state):
    with pytest.raises(RuntimeError):
        session.describe_sync(state)


def test_describe_sync_passes_settings_and_stores_results(state, monkeypatch):
    captured = {}

    def fake_generate_batch(settings, source, progress=None):
        captured["settings"] = settings
        captured["source"] = source
        return [session.RenderedImage(
            image=synthetic_photo(64, 64), style_key=settings.style_key,
            style_label=settings.style_label, variant=0, seed=1,
            width=64, height=64, seconds=0.1,
        )], []

    monkeypatch.setattr(session.textguide, "generate_batch", fake_generate_batch)

    state.description = "make this an old princess in a black dress and a crown"
    state.describe_style = "oil_realism"
    state.describe_count = 16
    state.describe_side = 640
    results = session.describe_sync(state)

    assert len(results) == 1
    assert state.results == results
    assert state.result_index == 0
    assert captured["settings"].count == 16
    assert captured["settings"].output_side == 640
    assert captured["settings"].description.startswith("make this an old princess")
    assert captured["settings"].style_prompt == session.style_prompts.prompt_for("oil_realism")


def test_describe_sync_records_warnings_without_raising(state, monkeypatch):
    """Partial batches must still reach the user, with an explanation."""
    monkeypatch.setattr(
        session.textguide, "generate_batch",
        lambda settings, source, progress=None: ([], ["image 1 failed: service busy"]),
    )
    state.description = "add a crown"
    results = session.describe_sync(state)
    assert results == []
    assert state.warnings == ["image 1 failed: service busy"]


def test_describe_async_reports_back(state, monkeypatch):
    import threading

    def fake_generate_batch(settings, source, progress=None):
        return [session.RenderedImage(
            image=synthetic_photo(32, 32), style_key="noir", style_label="Film Noir",
            variant=0, seed=1, width=32, height=32, seconds=0.1,
        )], []

    monkeypatch.setattr(session.textguide, "generate_batch", fake_generate_batch)
    state.description = "make it noir"

    finished = threading.Event()
    seen = {}

    def done(images, error):
        seen["images"] = images
        seen["error"] = error
        finished.set()

    session.describe_async(state, done=done)
    assert finished.wait(15), "worker thread did not finish"
    assert seen["error"] is None
    assert len(seen["images"]) == 1


def test_describe_async_surfaces_errors(state, monkeypatch):
    import threading

    def boom(settings, source, progress=None):
        raise session.textguide.TextGuidedError("no network")

    monkeypatch.setattr(session.textguide, "generate_batch", boom)
    state.description = "add a crown"

    finished = threading.Event()
    seen = {}

    def done(images, error):
        seen["images"] = images
        seen["error"] = error
        finished.set()

    session.describe_async(state, done=done)
    assert finished.wait(15)
    assert seen["images"] == []
    assert isinstance(seen["error"], session.textguide.TextGuidedError)


def test_describe_choices_match_the_catalog(state):
    choices = session.describe_choices()
    keys = [key for key, _ in choices]
    assert "oil_realism" in keys
    assert all(label for _, label in choices)


def test_summary_reflects_describe_mode(state):
    state.mode = "describe"
    state.description = "make this an old princess wearing a crown"
    state.describe_style = "oil_realism"
    state.describe_count = 16
    state.describe_side = 512
    text = session.summary(state)
    assert "Oil Painting (Realism)" in text
    assert "16 image(s)" in text
    assert "old princess" in text


def test_summary_unchanged_in_style_mode(state):
    state.mode = "styles"
    state.selected = ["oil_painting"]
    state.variants = 4
    assert "style(s)" in session.summary(state)

