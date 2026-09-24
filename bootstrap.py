"""Set up sys.path so a plain checkout is importable without installing."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"


def ensure_src_on_path() -> Path:
    """Add ``src/`` to ``sys.path`` once; safe to call repeatedly."""
    for entry in (str(SRC_DIR), str(PROJECT_ROOT)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return SRC_DIR
