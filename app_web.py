"""Run the optional browser upload mode: python app_web.py"""

from bootstrap import ensure_src_on_path

ensure_src_on_path()

from pixelmuse.web import main  # noqa: E402

if __name__ == "__main__":
    main()
