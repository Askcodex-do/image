"""Tests for the Tkinter desktop view.

Skipped where Tkinter is unavailable, which includes most Linux CI containers
and this development sandbox.  It *does* run on the Windows CI runners, where
Tkinter ships with Python, and that is where it earns its keep: it builds the
real window and drives the describe controls, so a broken widget name or a
missing attribute in the AI-mode wiring fails the build instead of crashing on
a user's machine.

The window is never shown and is withdrawn during the tests, so nothing can
depend on a widget actually being mapped.  Visibility is checked with
``grid_info``, which still reports whether a widget has been removed from the
grid.  Nothing here touches the network - the shared batch function is replaced
with a stub, and the message boxes are stubbed so no dialog can block the run.
"""

from __future__ import annotations

import pytest

# Tkinter ships with Python on Windows but is often absent on Linux, and the
# import can fail at the C-extension level, so guard it explicitly.
try:
    import tkinter as tk
except Exception as _tk_error:  # pragma: no cover - depends on the host
    pytest.skip(f"Tkinter is not available: {_tk_error}", allow_module_level=True)

from fixtures import synthetic_photo  # noqa: E402
from pixelmuse import gui, session  # noqa: E402


def _all(widget, kind):
    """Every descendant of the given Tk class, in creation order."""
    found = []
    for child in widget.winfo_children():
        if child.winfo_class() == kind:
            found.append(child)
        found.extend(_all(child, kind))
    return found


def _shown(widget) -> bool:
    """True when the widget is currently placed by the grid manager."""
    return bool(widget.grid_info())


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A real PixelMuseApp window, with dialogs stubbed out, torn down after."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - headless CI
        pytest.skip(f"no display available: {exc}")
    root.withdraw()

    # A modal dialog would hang the build, so record instead of showing.
    dialogs: list = []
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: dialogs.append(a))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: dialogs.append(a))

    application = gui.PixelMuseApp(root)
    application.state.output_dir = tmp_path / "out"
    application.dialogs = dialogs
    try:
        yield application
    finally:
        root.destroy()


def test_window_builds(app):
    assert app.state is not None
    assert app.render_button.cget("text") == "Generate images"


def test_default_state_is_the_offline_mode(app):
    """The internet-free path must stay the default."""
    assert app.mode_var.get() == "styles"
    assert app.state.mode == "styles"
    assert _shown(app.offline_frame)
    assert not _shown(app.describe_frame)


def test_mode_switch_swaps_the_controls(app):
    app.mode_var.set("describe")
    app._on_mode_changed()
    assert app.render_button.cget("text") == "Create from description"
    assert _shown(app.describe_frame)
    assert not _shown(app.offline_frame)

    app.mode_var.set("styles")
    app._on_mode_changed()
    assert app.render_button.cget("text") == "Generate images"
    assert _shown(app.offline_frame)
    assert not _shown(app.describe_frame)


def test_describe_controls_start_from_the_defaults(app):
    state = session.AppState()
    assert app.look_var.get() == "oil_realism"
    assert int(app.describe_count_var.get()) == state.describe_count
    assert app.describe_side_var.get() == "512 px"


def test_look_dropdown_lists_every_style(app):
    """The AI look list must match the offline style catalogue exactly.

    The panel holds two comboboxes (look, then output size), so search them all
    rather than depending on construction order.
    """
    keys = [key for key, _ in session.describe_choices()]
    dropdowns = [list(box.cget("values")) for box in _all(app.describe_frame, "TCombobox")]
    assert any(entries == keys for entries in dropdowns), "no combobox lists the styles"


def test_count_spinbox_allows_a_full_batch(app):
    spins = _all(app.describe_frame, "TSpinbox")
    assert spins, "no spinbox found in the describe panel"
    ranges = [(int(float(s.cget("from"))), int(float(s.cget("to")))) for s in spins]
    assert (1, 16) in ranges


def test_collect_describe_reads_the_controls(app, tmp_path):
    source = tmp_path / "photo.png"
    synthetic_photo(200, 150).save(source)
    session.load_source(app.state, source)

    app.description_text.insert("1.0", "make this an old princess with a crown")
    app.mode_var.set("describe")
    app.look_var.set("watercolour")
    app.describe_count_var.set(16)
    app.describe_side_var.set("768 px")

    assert app._collect_describe() is True
    assert app.state.mode == "describe"
    assert app.state.description == "make this an old princess with a crown"
    assert app.state.describe_style == "watercolour"
    assert app.state.describe_count == 16
    assert app.state.describe_side == 768


def test_collect_describe_clamps_out_of_range_values(app, tmp_path):
    source = tmp_path / "photo.png"
    synthetic_photo(200, 150).save(source)
    session.load_source(app.state, source)
    app.description_text.insert("1.0", "add a crown")

    # The spinbox normally prevents this, but a typed value can still get in.
    app.describe_count_var.set(99)
    app.describe_side_var.set("512 px")
    assert app._collect_describe() is True
    assert app.state.describe_count == 16


def test_collect_describe_needs_an_image(app):
    app.description_text.insert("1.0", "add a crown")
    assert app.state.has_source is False
    assert app._collect_describe() is False
    assert app.dialogs, "the user should have been told an image is required"


def test_collect_describe_needs_a_description(app, tmp_path):
    source = tmp_path / "photo.png"
    synthetic_photo(200, 150).save(source)
    session.load_source(app.state, source)
    assert app.state.has_source is True
    assert app._collect_describe() is False
    assert app.dialogs, "the user should have been told to describe something"


def test_generate_routes_to_describe(app, tmp_path, monkeypatch):
    """Pressing the button in describe mode must call the AI path, not the
    offline renderer."""
    source = tmp_path / "photo.png"
    synthetic_photo(200, 150).save(source)
    session.load_source(app.state, source)

    app.mode_var.set("describe")
    app._on_mode_changed()
    app.description_text.insert("1.0", "add a crown")

    called = {}

    def fake_describe_async(state, progress=None, done=None):
        called["describe"] = True
        if done:
            done([], None)

    def fake_render_async(state, progress=None, done=None):
        called["render"] = True
        if done:
            done([], None)

    monkeypatch.setattr(session, "describe_async", fake_describe_async)
    monkeypatch.setattr(session, "render_async", fake_render_async)

    app._generate()
    assert called.get("describe") is True
    assert "render" not in called


def test_generate_routes_to_offline_renderer(app, tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    synthetic_photo(200, 150).save(source)
    session.load_source(app.state, source)
    session.select_styles(app.state, ["noir"])

    called = {}

    def fake_describe_async(state, progress=None, done=None):
        called["describe"] = True

    def fake_render_async(state, progress=None, done=None):
        called["render"] = True
        if done:
            done([], None)

    monkeypatch.setattr(session, "describe_async", fake_describe_async)
    monkeypatch.setattr(session, "render_async", fake_render_async)

    app._generate()
    assert called.get("render") is True
    assert "describe" not in called


def test_status_bar_describes_the_ai_batch(app, tmp_path):
    source = tmp_path / "photo.png"
    synthetic_photo(200, 150).save(source)
    session.load_source(app.state, source)
    app.mode_var.set("describe")
    app.description_text.insert("1.0", "make this an old princess")
    app._collect_describe()
    app._refresh_status()
    assert "old princess" in app.status.cget("text")