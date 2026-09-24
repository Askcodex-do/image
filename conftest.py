"""Make ``src`` and the fixture helpers importable when running pytest."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC = PROJECT_ROOT / "src"
for entry in (str(SRC), str(PROJECT_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)
