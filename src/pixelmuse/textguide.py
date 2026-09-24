"""Text-guided image creation: describe a change, get a batch of images.

This is the mode where the *description* changes the picture.  Unlike the
style filters in :mod:`pixelmuse.generator`, which repaint whatever is already
in the photo, this module sends the photo plus your words to a generative
image model, which can add or replace content - a crown, a dress, a
background - that was never in the original.

That capability has a price, and the design here is shaped by two hard facts
measured on the real service:

1. **It needs the internet.** There is no offline text-to-image model that
   fits in 2 GB of RAM; Stable Diffusion alone needs several GB.  So the
   offline style mode remains the fallback, and this module is opt-in.

2. **The service is anonymous, so requests fail sometimes.** The free
   endpoint needs no API key and no account, but it is shared and rate
   limited.  Measured over a 16-image batch: roughly 1 in 8 requests comes
   back HTTP 5xx.  A single failure would otherwise leave a hole in a batch
   of 16, so every image is retried automatically with backoff.

The reference photo travels inside the URL as base64.  The service rejects
request lines over ~16 KB (HTTP 431), so uploads are downscaled to a 384 px
JPEG at quality 70, which lands around 12 KB and has been verified to work.
"""

from __future__ import annotations

import base64
import io
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from PIL import Image

from .generator import RenderedImage
from .imgio import fit_within

# ---------------------------------------------------------------------------
# Service configuration
# ---------------------------------------------------------------------------

SERVICE_ROOT = "https://image.pollinations.ai/prompt"

#: Verified to honour the ``image`` reference parameter anonymously.  Other
#: model ids either ignore the reference (giving a style-only result) or
#: require an API key, so this is deliberately not configurable by default.
DEFAULT_MODEL = "tongyi-mai/z-image-turbo"

#: Total request line must stay under ~16 KB or the service answers 431.
MAX_URL_CHARS = 15000
REF_DEFAULT_SIDE = 384
REF_MAX_BYTES = 11000

#: "No logo" asks the service not to stamp a watermark into the corner.
EXTRA_QUERY = {"nologo": "true"}

#: How long to allow for one rendering.  Measured median is ~5 s with a tail
#: past 45 s, so this is generous on purpose.
DEFAULT_TIMEOUT = 180
DEFAULT_ATTEMPTS = 4
DEFAULT_BACKOFF = 4.0

#: Output canvas.  Bigger costs the same to render but takes longer to
#: download; 512-768 is the sweet spot for previewing and saving.
OUTPUT_SIDES = (512, 640, 768)


class TextGuidedError(RuntimeError):
    """Raised when a batch cannot be produced at all (e.g. no network)."""


@dataclass
class PromptRequest:
    """One text-guided image to produce."""

    source: Image.Image
    description: str
    style_prompt: str = ""
    model: str = DEFAULT_MODEL
    output_side: int = 512
    seed: Optional[int] = None
    timeout: int = DEFAULT_TIMEOUT
    attempts: int = DEFAULT_ATTEMPTS
    ref_side: int = REF_DEFAULT_SIDE


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class _Retryable(Exception):
    """A failure worth trying again: server hiccup or rate limit."""

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class _Permanent(Exception):
    """A failure that will repeat: bad request, blocked prompt."""


# ---------------------------------------------------------------------------
# Reference encoding
# ---------------------------------------------------------------------------


def encode_reference(image: Image.Image, side: int = REF_DEFAULT_SIDE,
                     max_bytes: int = REF_MAX_BYTES) -> str:
    """Return a ``data:`` URI for *image*, small enough for a URL.

    Steps the quality (and then the size) down until the encoded payload fits
    *max_bytes*, so unusual or very detailed photos still get through instead
    of being rejected with HTTP 431.
    """
    working = image.convert("RGB")
    working, _ = fit_within(working, (side, side))
    for attempt_side in (side, int(side * 0.85), int(side * 0.7)):
        candidate = working
        if attempt_side != side:
            candidate, _ = fit_within(working, (attempt_side, attempt_side))
        for quality in (70, 55, 40, 30):
            buffer = io.BytesIO()
            candidate.save(buffer, format="JPEG", quality=quality, optimize=True)
            payload = buffer.getvalue()
            if len(payload) <= max_bytes:
                return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")
    # Even the smallest attempt overshot; send it anyway rather than fail the
    # batch, since the caller will surface a clear error if the service balks.
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")


def build_prompt(description: str, style_prompt: str = "") -> str:
    """Combine the user's words with the chosen style's look.

    The instruction phrasing matters: without it the model tends to *replace*
    the subject with a newly invented scene rather than restyling the photo
    that was supplied.
    """
    parts = ["Using this exact photo as the reference and keeping the same subject"]
    if style_prompt:
        parts.append(f"render it as {style_prompt}")
    if description:
        parts.append(f"and apply this change: {description}")
    parts.append("Preserve the person's identity, pose and composition.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


def _classify(status: int, body: bytes) -> Optional[_Retryable | _Permanent]:
    """Map an HTTP status onto the retry policy."""
    if status == 200:
        return None
    text = body[:300].decode("utf-8", "replace")
    if status in (429, 500, 502, 503, 504):
        return _Retryable(f"service busy (HTTP {status})")
    if status == 431:
        return _Permanent("reference image too large for the service")
    if 400 <= status < 500:
        return _Permanent(f"rejected (HTTP {status}): {text}")
    return _Retryable(f"HTTP {status}: {text}")


def _fetch(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "PixelMuse/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read()
        except Exception:  # pragma: no cover - body is best-effort only
            pass
        problem = _classify(exc.code, body)
        assert problem is not None
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if isinstance(problem, _Retryable) and retry_after:
            try:
                problem.retry_after = float(retry_after)
            except ValueError:
                pass
        raise problem
    except urllib.error.URLError as exc:
        raise _Retryable(f"network unavailable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise _Retryable("timed out") from exc


def _decode_image(payload: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(payload))
        image.load()
        return image.convert("RGB")
    except Exception as exc:
        raise _Retryable(f"response was not an image ({exc})") from exc


def generate_one(request: PromptRequest, progress: Optional[Callable[[str], None]] = None) -> Image.Image:
    """Produce a single text-guided image, retrying transient failures."""
    prompt = build_prompt(request.description, request.style_prompt)
    reference = encode_reference(request.source, request.ref_side)
    seed = request.seed if request.seed is not None else random.randint(1, 2**31 - 1)

    params = {
        "seed": str(seed),
        "width": str(request.output_side),
        "height": str(request.output_side),
        "model": request.model,
        "image": reference,
        **EXTRA_QUERY,
    }
    url = f"{SERVICE_ROOT}/{urllib.parse.quote(prompt)}?{urllib.parse.urlencode(params)}"
    if len(url) > MAX_URL_CHARS:  # safety net; encode_reference should prevent this
        reference = encode_reference(request.source, int(request.ref_side * 0.6), 6000)
        params["image"] = reference
        url = f"{SERVICE_ROOT}/{urllib.parse.quote(prompt)}?{urllib.parse.urlencode(params)}"

    last: Exception = TextGuidedError("no attempt was made")
    for attempt in range(1, request.attempts + 1):
        try:
            payload = _fetch(url, request.timeout)
            if payload[:2] != b"\xff\xd8" and payload[:8] != b"\x89PNG\r\n\x1a\n":
                raise _Retryable("response was not an image")
            return _decode_image(payload)
        except _Permanent:
            raise
        except _Retryable as exc:
            last = exc
            if attempt < request.attempts:
                # Vary the seed so a retry is not a repeat of the same bad luck.
                params["seed"] = str(random.randint(1, 2**31 - 1)) if request.seed is None else str(seed + attempt)
                url = f"{SERVICE_ROOT}/{urllib.parse.quote(prompt)}?{urllib.parse.urlencode(params)}"
                delay = exc.retry_after or min(request.attempts, attempt) * DEFAULT_BACKOFF
                if progress:
                    progress(f"{exc}; retrying in {delay:.0f}s")
                time.sleep(delay)
    raise TextGuidedError(str(last))


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


@dataclass
class BatchSettings:
    """What the user picked, in one place."""

    style_key: str = "oil_realism"
    style_label: str = "Oil Painting (Realism)"
    style_prompt: str = ""
    description: str = ""
    count: int = 16
    output_side: int = 512
    seed: Optional[int] = None
    model: str = DEFAULT_MODEL
    keep_failures: bool = True
    requests_per_second: float = 2.0


def generate_batch(
    settings: BatchSettings,
    source: Image.Image,
    progress: Optional[Callable[[str, float], None]] = None,
) -> tuple[List[RenderedImage], List[str]]:
    """Produce *settings.count* images, returning the successes and any warnings.

    Individual failures do not abort the batch: the point is to hand back as
    many images as possible, with warnings explaining anything that was lost.
    """
    results: List[RenderedImage] = []
    warnings: List[str] = []
    total = max(1, settings.count)
    interval = 1.0 / settings.requests_per_second if settings.requests_per_second > 0 else 0.0
    last_started = 0.0

    for index in range(total):
        if progress:
            progress(f"{settings.style_label}: image {index + 1}/{total}", index / total)

        wait = interval - (time.time() - last_started)
        if wait > 0:
            time.sleep(wait)
        last_started = time.time()

        request = PromptRequest(
            source=source,
            description=settings.description,
            style_prompt=settings.style_prompt,
            model=settings.model,
            output_side=settings.output_side,
            seed=settings.seed,
        )
        started = time.time()
        try:
            image = generate_one(
                request,
                progress=(lambda m, i=index: progress(f"{settings.style_label}: image {i + 1}/{total} - {m}", i / total))
                if progress else None,
            )
        except (TextGuidedError, _Permanent) as exc:
            warnings.append(f"image {index + 1} failed: {exc}")
            if progress:
                progress(f"{settings.style_label}: image {index + 1}/{total} failed", (index + 1) / total)
            continue

        results.append(
            RenderedImage(
                image=image,
                style_key=settings.style_key,
                style_label=settings.style_label,
                variant=index,
                seed=settings.seed if settings.seed is not None else 0,
                width=image.width,
                height=image.height,
                seconds=time.time() - started,
            )
        )

    if progress:
        progress(f"{settings.style_label}: done", 1.0)
    return results, warnings


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


def service_available(timeout: int = 12) -> bool:
    """True when the text-guided service can be reached right now."""
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"{SERVICE_ROOT}/{urllib.parse.quote('ok')}?width=32&height=32&nologo=true",
                                   headers={"User-Agent": "PixelMuse/2.0"}),
            timeout=timeout,
        ) as response:
            return response.status == 200
    except Exception:
        return False
