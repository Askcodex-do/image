"""Write a sample photo to disk, for CI and manual smoke checking.

    python tests/make_sample.py samples/demo_input.png 800 600
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tests"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fixtures import synthetic_photo  # noqa: E402


def main(argv: list[str]) -> int:
    target = Path(argv[0]) if argv else PROJECT_ROOT / "samples" / "demo_input.png"
    width = int(argv[1]) if len(argv) > 1 else 800
    height = int(argv[2]) if len(argv) > 2 else 600

    target.parent.mkdir(parents=True, exist_ok=True)
    synthetic_photo(width, height).save(target)
    print(f"Wrote {target} ({width}x{height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
