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


def test_save_without_results_is_an_error(state, tmp_path):
    with pytest.raises(RuntimeError):
        session.save_current(state, tmp_path / "nope.png")
    with pytest.raises(RuntimeError):
        session.save_all(state)
    with pytest.raises(RuntimeError):
        session.save_zip(state, tmp_path / "nope.zip")


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
