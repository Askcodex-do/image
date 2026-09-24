"""Command line interface: usable without any GUI.

Examples
--------
    python -m pixelmuse list
    python -m pixelmuse generate photo.jpg --style oil_painting -n 4 -o out
    python -m pixelmuse generate photo.jpg --style all -n 2 --zip out/all.zip
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, __version__, export, imgio
from .generator import (
    DEFAULT_MAX_SIDE,
    DEFAULT_VARIANTS,
    build_contact_sheet,
    get_style,
    render_many,
    styles_by_family,
)
from .styles import RenderOptions


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pixelmuse",
        description=f"{APP_NAME} {__version__} - offline image styliser.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list every available style")

    gen = sub.add_parser("generate", help="turn one image into styled images")
    gen.add_argument("source", help="path to the input image")
    gen.add_argument(
        "-s", "--style", action="append", default=None,
        help="style key (repeatable). Use 'all' for every style.",
    )
    gen.add_argument("-n", "--variants", type=int, default=DEFAULT_VARIANTS,
                     help=f"images per style (default {DEFAULT_VARIANTS})")
    gen.add_argument("-o", "--out", default="outputs", help="output directory or file")
    gen.add_argument("--max-side", type=int, default=DEFAULT_MAX_SIDE,
                     help="long edge of the working canvas (lower = less RAM)")
    gen.add_argument("--detail", type=float, default=0.5, help="0 loose .. 1 fine")
    gen.add_argument("--strength", type=float, default=0.75, help="0 subtle .. 1 full")
    gen.add_argument("--colors", type=int, default=12, help="palette size hint")
    gen.add_argument("--seed", type=int, default=None, help="reproducible randomness")
    gen.add_argument("--format", default=".png", choices=[".png", ".jpg", ".webp", ".bmp"])
    gen.add_argument("--no-texture", action="store_true", help="disable canvas grain")
    gen.add_argument("--no-vignette", action="store_true", help="disable vignette")
    gen.add_argument("--frame", action="store_true", help="add a print border")
    gen.add_argument("--zip", dest="zip_path", default=None,
                     help="also write every result into this zip file")
    gen.add_argument("--sheet", dest="sheet_path", default=None,
                     help="also write a contact sheet PNG of the results")
    gen.add_argument("--pdf", dest="pdf_path", default=None,
                     help="also write a multi-page PDF, one image per page")
    return parser


def _resolve_styles(keys: list[str] | None) -> list[str]:
    if not keys:
        return ["oil_painting"]
    if any(key.lower() == "all" for key in keys):
        return [style.key for styles in styles_by_family().values() for style in styles]
    try:
        return [get_style(key).key for key in keys]
    except KeyError as exc:
        raise SystemExit(f"error: {exc}") from exc


def cmd_list() -> int:
    for family, styles in styles_by_family().items():
        print(f"\n{family}")
        print("-" * len(family))
        for style in styles:
            print(f"  {style.key:<16} {style.label:<26} {style.blurb}")
    print()
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    try:
        source = imgio.load_image(args.source)
    except imgio.ImageLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    options = RenderOptions(
        detail=max(0.0, min(1.0, args.detail)),
        strength=max(0.0, min(1.0, args.strength)),
        colors=max(2, args.colors),
        canvas_texture=not args.no_texture,
        vignette=not args.no_vignette,
        frame=args.frame,
    )
    style_keys = _resolve_styles(args.style)

    def progress(message: str, fraction: float) -> None:
        print(f"  [{fraction * 100:5.1f}%] {message}", flush=True)

    print(f"Rendering {len(style_keys)} style(s) x {args.variants} variant(s)")
    results = render_many(
        source,
        style_keys,
        variants=args.variants,
        options=options,
        max_side=args.max_side,
        seed=args.seed,
        progress=progress,
    )

    single_file = Path(args.out).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    if single_file and len(results) == 1:
        target = imgio.save_image(results[0].image, args.out)
        print(f"Wrote {target}")
    else:
        out_dir = Path(args.out)
        written = export.save_batch(results, out_dir, format_ext=args.format)
        print(f"Wrote {len(written)} file(s) to {out_dir.resolve()}")

    if args.zip_path:
        payload = export.batch_to_zip_bytes(results, format_ext=args.format)
        zip_target = Path(args.zip_path)
        zip_target.parent.mkdir(parents=True, exist_ok=True)
        zip_target.write_bytes(payload)
        print(f"Wrote {zip_target} ({len(payload) / 1024:.0f} KiB)")

    if args.sheet_path:
        sheet = build_contact_sheet(results, columns=min(4, max(1, len(results))))
        sheet_target = imgio.save_image(sheet, args.sheet_path)
        print(f"Wrote {sheet_target}")

    if args.pdf_path:
        payload = export.batch_to_pdf_bytes(results)
        pdf_target = Path(args.pdf_path)
        pdf_target.parent.mkdir(parents=True, exist_ok=True)
        pdf_target.write_bytes(payload)
        print(f"Wrote {pdf_target} ({len(payload) / 1024:.0f} KiB)")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "generate":
        return cmd_generate(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
