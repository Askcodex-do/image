"""Run the desktop GUI from a checkout: python app_gui.py"""

from bootstrap import ensure_src_on_path

ensure_src_on_path()

from pixelmuse.gui import main  # noqa: E402

if __name__ == "__main__":
    main()
