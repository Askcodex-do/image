#!/usr/bin/env bash
# Build PixelMuse.exe locally from any OS.
# Usage:
#   packaging/build_exe.sh          # build with the current interpreter
#   packaging/build_exe.sh wine     # build through Wine (Linux -> Windows EXE)
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT="$PWD"
MODE="${1:-local}"
echo "=== PixelMuse EXE build ($MODE) ==="
echo "Project root: $PROJECT_ROOT"

PYTHON="${PYTHON:-python3}"
if [[ "$MODE" == "wine" ]]; then
  PY="$PYTHON wine"
else
  if [[ ! -d .venv-build ]]; then
    echo "Creating build virtual environment..."
    "$PYTHON" -m venv .venv-build
  fi
  # shellcheck disable=SC1091
  source .venv-build/bin/activate
  PY="python"
fi

echo "Installing dependencies..."
$PY -m pip install --upgrade pip
$PY -m pip install -r requirements.txt pyinstaller pytest

echo "Running tests before packaging..."
$PY -m pytest tests -q

echo "Building the executable..."
$PY -m PyInstaller --clean --noconfirm packaging/pixelmuse.spec

if [[ -f dist/PixelMuse.exe ]]; then
  echo "Build finished: dist/PixelMuse.exe ($(du -h dist/PixelMuse.exe | cut -f1))"
elif [[ -f dist/PixelMuse ]]; then
  echo "Build finished: dist/PixelMuse ($(du -h dist/PixelMuse | cut -f1))"
else
  echo "Build failed: nothing in dist/" >&2
  exit 1
fi
