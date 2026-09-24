"""Tests that the packaged entry points stay importable and wired up.

These run in CI on machines with no display, so the GUI is only imported,
never shown.  The point is to catch a broken hidden import or a typo in a
PyInstaller spec before an EXE is built and shipped.
"""

from __future__ import annotations

import importlib
import sys

import pytest


def test_launchers_import():
    """app_gui / app_web / app_cli must import without side effects."""
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    for module in ("bootstrap",):
        assert importlib.import_module(module)

    from bootstrap import ensure_src_on_path

    ensure_src_on_path()
    for module in ("pixelmuse.cli", "pixelmuse.session", "pixelmuse.generator", "pixelmuse.export"):
        importlib.import_module(module)


def test_gui_module_imports_without_a_display():
    """Importing the GUI must never require a screen or a Tk root window."""
    gui = importlib.import_module("pixelmuse.gui")
    assert hasattr(gui, "main")
    assert hasattr(gui, "PixelMuseApp")
    # TK_AVAILABLE reflects the host: present on Windows, optional on Linux.
    assert isinstance(gui.TK_AVAILABLE, bool)


def test_all_styles_are_registered_on_plain_import():
    """The catalogues register styles as an import side effect."""
    import pixelmuse.generator as generator

    styles = generator.available_styles()
    assert len(styles) >= 19
    keys = {style.key for style in styles}
    for expected in (
        "oil_painting", "oil_realism", "acrylic", "watercolour", "gouache",
        "palette_knife", "pastel", "ink_wash", "spray_paint",
        "pencil_sketch", "charcoal", "digital_sketch", "comic_ink",
        "ballpoint", "lineart", "blueprint", "pop_art", "pixel_art", "noir",
    ):
        assert expected in keys, f"{expected} is not registered"


def test_cli_parser_accepts_documented_invocations():
    from pixelmuse.cli import _build_parser, main

    parser = _build_parser()
    args = parser.parse_args(["generate", "photo.png", "--style", "noir", "-n", "3"])
    assert args.style == ["noir"]
    assert args.variants == 3

    assert parser.parse_args(["list"]).command == "list"
    assert main(["list"]) == 0


def test_cli_reports_unknown_style_cleanly(tmp_path):
    from pixelmuse.cli import main

    source = tmp_path / "in.png"
    from fixtures import synthetic_photo

    synthetic_photo(120, 90).save(source)

    with pytest.raises(SystemExit) as info:
        main(["generate", str(source), "--style", "not_a_real_style"])
    assert "not_a_real_style" in str(info.value)


def test_cli_reports_unreadable_file_cleanly(tmp_path):
    from pixelmuse.cli import main

    junk = tmp_path / "notes.txt"
    junk.write_text("not an image")

    assert main(["generate", str(junk), "--style", "noir"]) == 1


def test_version_is_exposed():
    import pixelmuse

    assert pixelmuse.__version__.count(".") == 2
    assert pixelmuse.APP_NAME == "PixelMuse"
