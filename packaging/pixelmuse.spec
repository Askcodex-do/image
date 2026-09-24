# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PixelMuse.

Build with:
    pyinstaller --clean --noconfirm packaging/pixelmuse.spec

Produces a single-file windowed EXE in ``dist/`` named PixelMuse.exe.
No model weights and no network access are required at runtime.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent
SRC = PROJECT_ROOT / "src"

# Keep every module the app imports at runtime, including the style
# catalogues, which are imported for their side effects (style registration).
HIDDEN_IMPORTS = [
    "pixelmuse.catalog_draw",
    "pixelmuse.catalog_paint",
    "pixelmuse.cli",
    "pixelmuse.effects.core",
    "pixelmuse.style_prompts",
    "pixelmuse.textguide",
    "PIL._tkinter_finder",
    "PIL.Image",
    "PIL.ImageFilter",
    "PIL.ImageOps",
    "PIL.ImageTk",
    "numpy",
    # Text-guided mode talks to an HTTPS service; PyInstaller sometimes misses
    # these because they are pulled in indirectly by urllib.
    "ssl",
    "urllib.request",
    "urllib.error",
    "urllib.parse",
    "http.client",
    "email",
]

# Flask is optional; only bundle it when it is actually installed.
try:
    import flask  # noqa: F401

    HIDDEN_IMPORTS += ["flask", "jinja2", "werkzeug", "pixelmuse.web"]
except Exception:
    pass

a = Analysis(
    [str(PROJECT_ROOT / "app_gui.py")],
    pathex=[str(SRC), str(PROJECT_ROOT)],
    binaries=[],
    datas=[(str(PROJECT_ROOT / "README.md"), ".")],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    runtime_hooks=[],
    # Trim the heavy scientific stack: the app only needs core NumPy.
    excludes=[
        "matplotlib", "scipy", "pandas", "IPython", "jupyter", "notebook",
        "pytest", "setuptools", "pip", "test", "unittest", "distutils",
        "numpy.f2py", "numpy.distutils",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PixelMuse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,   # windowed app, no black console box
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
