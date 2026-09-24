# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the PixelMuse command line executable.

A console build is what CI smoke-tests, because it can be run headlessly:

    pyinstaller --clean --noconfirm packaging/pixelmuse_cli.spec
    dist/PixelMuse-CLI.exe generate photo.png --style oil_painting -n 2 -o out

Set PIXELMUSE_ONEFILE=1 to get a single-file build instead of a folder.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent
SRC = PROJECT_ROOT / "src"
ONEFILE = os.environ.get("PIXELMUSE_ONEFILE", "0") == "1"

HIDDEN_IMPORTS = [
    "pixelmuse.catalog_draw",
    "pixelmuse.catalog_paint",
    "pixelmuse.cli",
    "pixelmuse.effects.core",
    "PIL.Image",
    "PIL.ImageFilter",
    "PIL.ImageOps",
    "numpy",
]

a = Analysis(
    [str(PROJECT_ROOT / "app_cli.py")],
    pathex=[str(SRC), str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy", "pandas", "IPython", "jupyter", "notebook",
        "tkinter", "pytest", "test", "unittest", "distutils",
        "numpy.f2py", "numpy.distutils",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="PixelMuse-CLI",
        debug=False,
        strip=False,
        upx=False,
        console=True,
        runtime_tmpdir=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="PixelMuse-CLI",
        debug=False,
        strip=False,
        upx=False,
        console=True,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="PixelMuse-CLI",
    )
