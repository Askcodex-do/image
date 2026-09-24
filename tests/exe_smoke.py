"""Smoke-test a *built* PixelMuse executable.

CI runs this after PyInstaller finishes, so the artifact that users download
is verified to actually run and produce real images - not just that it exists.

Usage:
    python tests/exe_smoke.py path/to/PixelMuse-CLI.exe
    python tests/exe_smoke.py path/to/PixelMuse-CLI --styles oil_painting,pixel_art
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tests"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fixtures import synthetic_photo  # noqa: E402
from PIL import Image  # noqa: E402

DEFAULT_STYLES = ["oil_painting", "pencil_sketch", "pixel_art"]


def run(exe: Path, args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    print(f"$ {exe} {' '.join(args)}", flush=True)
    completed = subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed


def check_style_list(exe: Path, expected: list[str]) -> None:
    result = run(exe, ["list"])
    assert result.returncode == 0, f"`list` exited with {result.returncode}"
    listing = result.stdout
    for key in expected:
        assert key in listing, f"style '{key}' missing from `list` output"


def check_generation(exe: Path, workdir: Path, styles: list[str]) -> None:
    source = workdir / "input.png"
    synthetic_photo(480, 360).save(source)

    out_dir = workdir / "rendered"
    style_args = [value for style in styles for value in ("--style", style)]
    result = run(
        exe,
        [
            "generate",
            str(source),
            *style_args,
            "--variants", "2",
            "--max-side", "320",
            "--out", str(out_dir),
            "--zip", str(workdir / "batch.zip"),
            "--sheet", str(workdir / "sheet.png"),
            "--pdf", str(workdir / "batch.pdf"),
        ],
    )
    assert result.returncode == 0, f"`generate` exited with {result.returncode}"

    produced = sorted(out_dir.glob("*.png"))
    expected_count = len(styles) * 2
    assert len(produced) == expected_count, (
        f"expected {expected_count} images, found {len(produced)}: {produced}"
    )

    for path in produced:
        assert path.stat().st_size > 1000, f"{path} looks empty ({path.stat().st_size} bytes)"
        with Image.open(path) as image:
            assert image.size == (320, int(320 * 360 / 480)), f"unexpected size for {path}"
            # A real render must not be a single flat colour.
            colours = image.convert("RGB").getcolors(maxcolors=1 << 20)
            assert colours is None or len(colours) > 50, f"{path} looks like a flat fill"

    archive = workdir / "batch.zip"
    assert archive.exists() and archive.stat().st_size > 1000, "zip was not written"

    sheet = workdir / "sheet.png"
    assert sheet.exists() and sheet.stat().st_size > 1000, "contact sheet was not written"

    pdf = workdir / "batch.pdf"
    assert pdf.exists() and pdf.read_bytes().startswith(b"%PDF"), "pdf was not written"


def check_reproducible_seed(exe: Path, workdir: Path) -> None:
    source = workdir / "input.png"
    first = workdir / "seed_a"
    second = workdir / "seed_b"
    for target in (first, second):
        result = run(
            exe,
            [
                "generate", str(source), "--style", "noir",
                "--variants", "1", "--max-side", "200",
                "--seed", "424242", "--out", str(target),
            ],
        )
        assert result.returncode == 0, f"seeded run failed with {result.returncode}"

    a = next(iter(sorted(first.glob("*.png")))).read_bytes()
    b = next(iter(sorted(second.glob("*.png")))).read_bytes()
    assert a == b, "the same seed produced different bytes"


def check_bad_input(exe: Path, workdir: Path) -> None:
    junk = workdir / "junk.txt"
    junk.write_text("definitely not an image")
    result = run(exe, ["generate", str(junk), "--style", "noir", "--out", str(workdir / "bad")])
    assert result.returncode != 0, "a non-image input should fail with a non-zero exit code"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: exe_smoke.py <path-to-exe> [style,style,...]", file=sys.stderr)
        return 2

    exe = Path(argv[0]).resolve()
    if not exe.exists():
        print(f"executable not found: {exe}", file=sys.stderr)
        return 2

    styles = argv[1].split(",") if len(argv) > 1 else DEFAULT_STYLES

    with tempfile.TemporaryDirectory(prefix="pixelmuse-smoke-") as temp:
        workdir = Path(temp)
        print("== checking `list` ==")
        check_style_list(exe, styles)
        print("== checking generation ==")
        check_generation(exe, workdir, styles)
        print("== checking reproducible seed ==")
        check_reproducible_seed(exe, workdir)
        print("== checking bad input handling ==")
        check_bad_input(exe, workdir)

    print("\nAll executable smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
