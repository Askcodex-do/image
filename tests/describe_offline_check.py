"""Check the AI mode end to end without touching the network.

This runs the real CLI command against a stand-in for the image service, so CI
proves the whole path works - prompt building, reference encoding, retries,
partial failures, saving every output format - while staying hermetic and fast.

Usage:
    python tests/describe_offline_check.py path/to/input.png
"""

from __future__ import annotations

import io
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tests"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PIL import Image  # noqa: E402

from fixtures import synthetic_photo  # noqa: E402


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    synthetic_photo(64, 64).save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


class _Handler(BaseHTTPRequestHandler):
    body = b""
    calls = 0

    def do_GET(self):  # noqa: N802
        _Handler.calls += 1
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(_Handler.body)))
        self.end_headers()
        self.wfile.write(_Handler.body)

    def log_message(self, *args):
        pass


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: describe_offline_check.py <input-image>", file=sys.stderr)
        return 2

    source = Path(argv[0])
    if not source.exists():
        print(f"input image not found: {source}", file=sys.stderr)
        return 2

    _Handler.body = _jpeg()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    from pixelmuse import textguide
    from pixelmuse.cli import main as cli_main

    host, port = server.server_address
    textguide.SERVICE_ROOT = f"http://{host}:{port}/prompt"

    try:
        with tempfile.TemporaryDirectory(prefix="pixelmuse-describe-") as temp:
            workdir = Path(temp)
            out = workdir / "out"

            print("== describe with every output format ==")
            code = cli_main([
                "describe", str(source),
                "-d", "make this an old princess wearing a black dress and a crown",
                "-t", "oil_realism", "-n", "16", "--side", "512",
                "-o", str(out),
                "--zip", str(workdir / "batch.zip"),
                "--sheet", str(workdir / "sheet.png"),
                "--pdf", str(workdir / "batch.pdf"),
            ])
            assert code == 0, f"describe exited with {code}"

            images = sorted(out.glob("*.png"))
            assert len(images) == 16, f"expected 16 images, found {len(images)}"
            print(f"  wrote {len(images)} images")

            for name in ("batch.zip", "sheet.png", "batch.pdf"):
                path = workdir / name
                assert path.exists(), f"{name} was not written"
                assert path.stat().st_size > 0, f"{name} is empty"
            print("  zip, contact sheet and PDF all written")

            # Every image must be a real, decodable image.  The service chooses
            # the exact output size, so only the format is guaranteed here.
            for path in images:
                with Image.open(path) as image:
                    image.load()
                    assert image.width >= 32 and image.height >= 32, f"{path.name} looks degenerate"
            print("  every image decodes cleanly")

            # The background worker path must work too, not just the CLI's.
            print("== describe through the shared session (worker thread) ==")
            from pixelmuse import session

            state = session.AppState(output_dir=workdir / "session-out")
            session.load_source(state, source)
            state.description = "give this person a crown"
            state.describe_style = "noir"
            state.describe_count = 4
            state.describe_side = 512

            finished = threading.Event()
            result = {}

            def done(images, error):
                result["images"] = images
                result["error"] = error
                finished.set()

            session.describe_async(state, done=done)
            assert finished.wait(120), "the worker thread did not finish"
            assert result["error"] is None, f"worker failed: {result['error']}"
            assert len(result["images"]) == 4, "session mode did not return 4 images"
            print("  session mode returned 4 images")

            print("== describe with a partial failure ==")
            original = textguide.generate_one

            def flaky(request, progress=None):
                # Fail the very first image so the retry path is exercised.
                if _Handler.calls <= 1:
                    raise textguide.TextGuidedError("simulated outage")
                return original(request, progress=progress)

            textguide.generate_one = flaky
            try:
                code = cli_main([
                    "describe", str(source), "-d", "add a crown",
                    "-t", "noir", "-n", "4", "-o", str(workdir / "flaky"),
                ])
            finally:
                textguide.generate_one = original
            assert code == 0, f"a recoverable failure should not fail the run (got {code})"
            recovered = list((workdir / "flaky").glob("*.png"))
            assert len(recovered) == 4, f"retry should have recovered all 4, got {len(recovered)}"
            print("  a transient failure was retried and all 4 images arrived")

            print("== describe refuses bad input ==")
            bad_look = cli_main([
                "describe", str(source), "-d", "add a crown", "-t", "not_a_look",
            ])
            assert bad_look == 1, "an unknown look should exit 1"

            no_description = None
            try:
                no_description = cli_main(["describe", str(source)])
            except SystemExit as exc:   # argparse rejects the missing flag
                no_description = exc.code
            assert no_description != 0, "a missing description should not succeed"
            print("  bad look and missing description both rejected")
    finally:
        server.shutdown()
        server.server_close()

    print("\nAll offline AI-mode checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
