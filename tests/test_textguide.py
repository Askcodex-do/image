"""Tests for text-guided mode.

These never touch the real service.  A local HTTP server stands in for it, so
the tests are fast, deterministic and work with no internet connection.  One
separate, explicitly-marked test exercises the live service and is skipped
unless it is asked for.
"""

from __future__ import annotations

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from pixelmuse import style_prompts, textguide
from pixelmuse.textguide import (
    BatchSettings,
    PromptRequest,
    TextGuidedError,
    build_prompt,
    encode_reference,
    generate_batch,
    generate_one,
)


def _jpeg(colour=(120, 80, 200), size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


class _Handler(BaseHTTPRequestHandler):
    """Serves scripted responses so retry behaviour can be tested."""

    script: list = []
    calls: list = []

    def do_GET(self):  # noqa: N802 - required by the base class
        _Handler.calls.append(self.path)
        index = len(_Handler.calls) - 1
        if index < len(_Handler.script):
            status, body = _Handler.script[index]
        else:
            status, body = _Handler.script[-1]
        self.send_response(status)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the test output
        pass


@pytest.fixture
def fake_service(monkeypatch):
    """Point the module at a local server and let the test script replies."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    monkeypatch.setattr(textguide, "SERVICE_ROOT", f"http://{host}:{port}/prompt")
    # Retries sleep between attempts; drop that so tests stay fast.
    monkeypatch.setattr(textguide, "DEFAULT_BACKOFF", 0.01)
    _Handler.calls = []
    _Handler.script = []
    try:
        yield _Handler
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Prompt and reference encoding
# ---------------------------------------------------------------------------


def test_build_prompt_keeps_the_subject():
    prompt = build_prompt("add a crown", "an oil painting")
    assert "same subject" in prompt
    assert "an oil painting" in prompt
    assert "add a crown" in prompt


def test_build_prompt_without_style_still_works():
    prompt = build_prompt("make it night")
    assert "make it night" in prompt
    assert "render it as" not in prompt


def test_encode_reference_fits_in_a_url():
    big = Image.new("RGB", (3000, 2000), (200, 100, 50))
    uri = encode_reference(big)
    assert uri.startswith("data:image/jpeg;base64,")
    # The service rejects request lines over ~16 KB, so the payload must stay
    # well inside that budget.
    assert len(uri) < 15000


def test_encode_reference_stays_small_for_noisy_photos():
    """Detailed photos compress worst; the encoder must still fit the budget."""
    import random

    rng = random.Random(7)
    noise = Image.new("RGB", (1500, 1500))
    noise.putdata([(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
                   for _ in range(1500 * 1500)])
    uri = encode_reference(noise)
    assert len(uri) < 15000
    assert Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))).size[0] <= 384


def test_encode_reference_is_a_real_jpeg():
    uri = encode_reference(Image.new("RGB", (500, 500), (10, 200, 10)))
    payload = base64.b64decode(uri.split(",", 1)[1])
    assert payload[:2] == b"\xff\xd8"
    assert Image.open(io.BytesIO(payload)).size == (384, 384)


# ---------------------------------------------------------------------------
# Single image
# ---------------------------------------------------------------------------


def test_generate_one_returns_an_image(fake_service):
    fake_service.script = [(200, _jpeg())]
    image = generate_one(PromptRequest(source=Image.new("RGB", (400, 400)), description="add a hat"))
    assert image.size == (64, 64)
    assert image.mode == "RGB"


def test_generate_one_sends_description_and_reference(fake_service):
    fake_service.script = [(200, _jpeg())]
    generate_one(PromptRequest(source=Image.new("RGB", (400, 400)), description="give her a crown",
                              style_prompt=style_prompts.prompt_for("oil_realism")))
    from urllib.parse import unquote, urlparse

    query = urlparse(fake_service.calls[0]).query
    assert "crown" in unquote(fake_service.calls[0])
    assert "image=data%3Aimage%2Fjpeg%3Bbase64%2C" in query or "image=data:image" in unquote(query)
    assert "seed=" in query


def test_generate_one_retries_a_server_error(fake_service):
    fake_service.script = [(500, b"busy"), (500, b"busy"), (200, _jpeg())]
    image = generate_one(
        PromptRequest(source=Image.new("RGB", (300, 300)), description="x", attempts=3)
    )
    assert image.size == (64, 64)
    assert len(fake_service.calls) == 3


def test_generate_one_gives_up_after_the_attempt_budget(fake_service):
    fake_service.script = [(503, b"busy")]
    with pytest.raises(TextGuidedError):
        generate_one(PromptRequest(source=Image.new("RGB", (300, 300)), description="x", attempts=2))
    assert len(fake_service.calls) == 2


def test_generate_one_does_not_retry_a_rejected_prompt(fake_service):
    """A 400 means the request itself is wrong; retrying would just repeat it."""
    fake_service.script = [(400, b"bad prompt")]
    with pytest.raises(Exception):
        generate_one(PromptRequest(source=Image.new("RGB", (300, 300)), description="x", attempts=4))
    assert len(fake_service.calls) == 1


def test_generate_one_retries_when_the_body_is_not_an_image(fake_service):
    """A 200 carrying HTML or JSON is a transient glitch, not a result."""
    fake_service.script = [(200, b"<html>nope</html>"), (200, _jpeg())]
    image = generate_one(PromptRequest(source=Image.new("RGB", (300, 300)), description="x", attempts=3))
    assert image.size == (64, 64)
    assert len(fake_service.calls) == 2


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


def test_generate_batch_produces_the_requested_count(fake_service):
    fake_service.script = [(200, _jpeg())]
    settings = BatchSettings(description="add a crown", count=3, requests_per_second=1000)
    results, warnings = generate_batch(settings, Image.new("RGB", (300, 300)))
    assert len(results) == 3
    assert warnings == []
    assert [item.variant for item in results] == [0, 1, 2]


def test_generate_batch_keeps_going_when_some_images_fail(fake_service):
    """One bad image must not cost the user the other fifteen."""
    # Fail, then succeed, then fail again.
    fake_service.script = [(500, b"busy"), (200, _jpeg()), (500, b"busy")]

    # Each image gets one attempt, so the script maps 1:1 onto the images.
    settings = BatchSettings(description="x", count=3, requests_per_second=1000)
    results, warnings = generate_batch(settings, Image.new("RGB", (300, 300)))
    assert len(results) + len(warnings) == 3
    assert len(results) >= 1
    assert all("failed" in warning for warning in warnings)


def test_generate_batch_reports_progress(fake_service):
    fake_service.script = [(200, _jpeg())]
    seen: list = []
    settings = BatchSettings(description="x", count=2, requests_per_second=1000)
    generate_batch(settings, Image.new("RGB", (300, 300)),
                   progress=lambda message, fraction: seen.append((message, fraction)))
    assert seen
    assert seen[-1][1] == 1.0


def test_generate_batch_results_carry_labels(fake_service):
    fake_service.script = [(200, _jpeg())]
    settings = BatchSettings(
        description="add a crown", count=1, style_key="oil_realism",
        style_label="Oil Painting (Realism)", requests_per_second=1000,
    )
    results, _ = generate_batch(settings, Image.new("RGB", (300, 300)))
    assert results[0].style_label == "Oil Painting (Realism)"
    assert results[0].suggested_filename() == "oil_realism_01.png"


# ---------------------------------------------------------------------------
# Style prompt table
# ---------------------------------------------------------------------------


def test_every_offline_style_has_a_prompt():
    """The two modes should offer the same named choices."""
    from pixelmuse.styles import style_keys

    for key in style_keys():
        assert key in style_prompts.STYLE_PROMPTS, f"{key} has no text prompt"


def test_style_choices_are_labelled():
    choices = style_prompts.style_choices()
    assert choices
    for key, prompt in choices:
        assert prompt
        assert style_prompts.label_for(key) != ""


def test_unknown_style_falls_back_to_a_title():
    assert style_prompts.label_for("not_a_style") == "Not A Style"
    assert style_prompts.prompt_for("not_a_style") == ""


# ---------------------------------------------------------------------------
# Live service (opt-in only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not __import__("os").environ.get("PIXELMUSE_LIVE_TEST"),
    reason="set PIXELMUSE_LIVE_TEST=1 to hit the real image service",
)
def test_live_service_returns_a_real_image():
    source = Image.new("RGB", (600, 600), (200, 180, 160))
    image = generate_one(
        PromptRequest(source=source, description="recolour this in bright green",
                      output_side=384, attempts=4)
    )
    assert image.width >= 128
