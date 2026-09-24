"""Run the CLI from a checkout: python app_cli.py generate photo.jpg"""

import sys

from bootstrap import ensure_src_on_path

ensure_src_on_path()

from pixelmuse.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
