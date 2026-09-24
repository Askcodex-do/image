# AGENTS.md - working notes for this repository

Repository-specific knowledge for future agent sessions. Keep it factual and
short; it is loaded automatically for every conversation.

## What this project is

PixelMuse: an image styliser with **two modes**. One input image becomes many
images either way.

1. **Style filters** (default, offline) - a multiple-choice list of looks (oil
   painting, pencil sketch, pixel art, ...), applied with real image processing.
2. **Describe a change** (opt-in, needs internet) - sends the photo plus a text
   instruction to a public image service and returns up to 16 variants.

Ships as a single-file Windows EXE.

## Hard constraints (do not violate)

* **Target machine: Windows 8.1, 2 GB RAM, Python 3.10.11.** This is the
  compatibility floor. Windows 8.1 means Python 3.10 is the newest usable
  interpreter; keep CI green on 3.10.
* **RAM budget.** Peak allocation for a default offline batch must stay under
  ~300 MB. Never build an unbounded list of full-size float arrays. Downscale
  to a working canvas first (see `generator.prepare_working_image`), render
  variants one at a time, and let callers drop results. The AI mode keeps *one*
  image in flight at a time for the same reason.
* **Offline by default.** The desktop path must work with no network. The only
  network-facing components are:
  * the local Flask page, bound to `127.0.0.1`; it must never bind a public
    interface by default;
  * `textguide.py`, the AI mode, which contacts a public image service **only
    when the user explicitly picks that mode** and sends the image. It must
    never be called as a side effect of anything else, and no telemetry or
    analytics may ever be added.
  The default mode stays offline and the AI mode is always labelled in the UI as
  needing internet, so the user is never surprised by an upload.
* **No heavy dependencies.** Runtime is Pillow + NumPy only (Flask is an
  optional extra documented in `requirements-web.txt`). Do not add SciPy,
  OpenCV, torch, matplotlib, etc. The PyInstaller specs actively exclude them.
  The AI mode is deliberately implemented on `urllib` from the standard library
  rather than pulling in `requests`.
* **No binary fixtures.** Test images are generated procedurally in
  `tests/fixtures.py` so the repository stays text-only and reproducible.

## Commands

```bash
python -m pytest tests -q                      # full suite (127 tests)
python tests/make_sample.py /tmp/in.png 800 600  # synthetic input image
python app_cli.py list                         # style catalogue
python app_cli.py generate /tmp/in.png --style all -n 1 -o /tmp/out
python app_cli.py describe /tmp/in.png -d "add a gold crown" -n 4   # needs internet
python app_gui.py                              # desktop app (needs Tkinter)
python app_web.py                              # local browser mode (needs Flask)

# end-to-end AI-mode check with no network (used by CI)
python tests/describe_offline_check.py /tmp/in.png

# live AI mode against the real service (opt-in)
PIXELMUSE_LIVE_TEST=1 python -m pytest tests/test_textguide.py -q

# build + verify the EXE the way CI does
PIXELMUSE_ONEFILE=1 python -m PyInstaller --clean --noconfirm packaging/pixelmuse_cli.spec
python tests/exe_smoke.py dist/PixelMuse-CLI oil_painting,pencil_sketch,pixel_art
```

Launch scripts (`app_*.py`) call `bootstrap.ensure_src_on_path()` so a plain
checkout works without `pip install -e`. `conftest.py` does the same for tests.

## Architecture

`styles.py` holds the registry (`register`/`get_style`/`all_styles`) plus the
shared primitives. The two catalogues (`catalog_paint.py`, `catalog_draw.py`)
register styles **as an import side effect**, which is why `generator.py`
imports them and why both PyInstaller specs list them as hidden imports.

`session.py` is the headless app state. `gui.py` (Tkinter) and `web.py` (Flask)
are thin views over it and must not contain rendering logic. Keep it that way -
it is what makes the behaviour testable without a display, which matters
because CI runners have no Tkinter.

Array convention: `numpy.float32` in 0..1, shape `(H, W, 3)`. Helpers in
`effects/core.py`. `core.luminance` and `core.to_image` accept `(H, W)` and
`(H, W, 1)` as well as `(H, W, 3)`; `core.blend` accepts an array alpha.

### AI mode

`textguide.py` does the talking; `style_prompts.py` maps a style key onto a
prompt phrase (and a human label). `session.describe_sync` / `describe_async`
are the shared entry points, so `gui.py`, `web.py` and `cli.py` all go through
the same code - keep it that way.

Three things in `textguide.py` are load-bearing and easy to break:

* **The URL is the payload.** The reference photo is downscaled to <=384 px and
  base64-encoded into the query string. The service rejects request lines over
  roughly 16 KB with HTTP 431, and `MAX_URL_CHARS` is checked against the real
  limit. If you raise `ref_side`, verify the encoded URI still fits - there is a
  test with random noise, which compresses worst.
* **Retries are the normal case, not an error path.** The service is free and
  shared, so transient 5xx and non-image bodies are expected. `_Retryable`
  triggers a retry with a grown pause and a varied seed; `_Permanent` (a 4xx,
  i.e. a bad request) must *not* be retried. A 200 carrying HTML or JSON is
  treated as retryable, because that is what a glitch looks like.
* **Partial batches are a success.** `generate_batch` returns
  `(results, warnings)` and never raises for individual failures. Callers show
  the images that arrived plus a note. Only a total failure is an error.

## Style gotchas

* **`xdog_lines` returns *whiteness*.** 1.0 on blank paper, dipping towards 0.0
  along contours. Drawing styles compute `ink = 1 - lines`. It previously
  returned the inverse, which silently turned eight styles nearly black while
  still passing "the image changed" tests. If you touch it, re-run the tonal
  range assertions in `tests/test_styles.py`.
* **Every style must produce distinct variants.** Deterministic styles (pixel
  art, line art, halftone, digital sketch, blueprint) vary via
  `options.variant % 4`: resolution, line weight, paper tone, palette size,
  grid pitch. `test_every_style_produces_distinct_variants` enforces this.
* Style render functions are pure: `(array, rng, options) -> array`. Any
  randomness must come from the passed `rng`, or seeded batches stop being
  reproducible and `test_seed_is_reproducible` fails.
* `core.posterize`, `quantize_palette` and `gradient_map` clip to 0..1
  internally; downstream code can assume that range.

## Testing expectations

When adding or changing a style, the suite verifies: it renders, it differs
from the input, it is not a flat fill, it has real tonal range, its variants are
distinct, and the same seed reproduces byte-identical output. Run the whole
suite - it takes about four seconds.

`tests/exe_smoke.py` is not part of pytest. It runs a **built** executable and
is what CI uses to prove an artifact works before it is published. If you change
the CLI surface, update it. It now also checks that the AI mode is bundled, by
running `describe --help` and confirming a bad look is rejected - that stays
hermetic, because CI must not depend on the network.

AI-mode tests never touch the real service by default. `test_textguide.py`
starts a local stand-in HTTP server so retry, partial-failure and
total-failure paths can be scripted deterministically. The one live test is
skipped unless `PIXELMUSE_LIVE_TEST` is set.

## CI

`tests.yml` runs pytest on Ubuntu and Windows across Python 3.10-3.12, plus a
from-source CLI check and `tests/describe_offline_check.py`, which drives the
whole AI mode against a local stand-in so CI stays hermetic. `build-windows-exe.yml`
builds the console EXE (`PIXELMUSE_ONEFILE=1`, smoke-tested) and the windowed
GUI EXE on `windows-latest`, uploads both as artifacts, and attaches them to a
GitHub Release when a `v*` tag is pushed.

The GUI EXE cannot be scripted, so CI verifies it exists, is not suspiciously
small, and then runs the packaged console EXE to prove the shared modules were
bundled. Do not remove that check - it is the only thing standing between a
missing hidden import and a broken download.

## Conventions

* No comments that restate the code. Comments explain *why*: a memory budget, a
  non-obvious algorithm choice, a compatibility workaround.
* Imports at module top. `gui.py` deliberately guards its Tkinter import so the
  module can be imported on a headless machine - keep that guard.
* Prefer editing existing files over adding new ones.
