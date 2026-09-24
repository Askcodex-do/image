# PixelMuse - AI image generator

Turn one picture into many pictures. Two modes, one app:

1. **Style filters** (offline, fast). Tick the looks you want from a
   multiple-choice list (oil painting, oil painting realism, digital sketch,
   watercolour, pixel art, and more), choose how many images to make, and save
   the ones you like to your PC. No internet, no GPU, nothing uploaded.
2. **Describe a change** (needs internet). Upload a photo, pick a look, say
   what should happen - *"make this an old princess wearing a black dress and a
   crown"* - choose how many images you want (up to 16), and get that many
   different versions of *your* photo with the change applied.

Works on the machine you described: **Windows 8.1, 2 GB RAM, Python 3.10.11**.

---

## The two modes, honestly compared

| | Style filters | Describe a change |
|---|---|---|
| Internet needed | No | Yes |
| Speed | ~0.5-1.5 s per image | ~5-60 s per image |
| Can add new things (a crown, a dress) | No - only repaints what is there | Yes |
| Cost | Free, forever | Free, no account or API key |
| Privacy | Nothing leaves the machine | The photo is sent to the image service |

The second mode exists because no offline model can do what it does on 2 GB of
RAM - Stable Diffusion alone needs several gigabytes. So the offline mode stays
the default and the generative mode is opt-in, clearly labelled in the app.

**About reliability in the AI mode.** The free image service needs no account,
but it is shared, so requests occasionally fail. Measured over a real batch of
16, roughly one in eight comes back as a server error. Every image is therefore
retried automatically with a growing pause, and if one still fails you get the
other fifteen plus a note saying what happened, rather than an empty screen.

## Why this runs on 2 GB of RAM

For the offline mode there is no neural network to download and no GPU to warm
up. The styles are real image-processing algorithms - Kuwahara edge-preserving
smoothing, directional brush smears, XDoG line extraction, colour-dodge pencil
rendering, ordered dithering, palette quantisation - written on top of Pillow
and NumPy.

That choice is deliberate:

* **It is genuinely offline.** Nothing to download after the first install, so
  no internet dependency on a machine that may not have a reliable one.
* **It fits in 2 GB.** A diffusion model needs several gigabytes of RAM and a
  real GPU. Loading a 1 GB checkpoint would swap-thrash a 2 GB machine into
  unusability.
* **It is fast.** Roughly 0.5-1.5 seconds per image at 1400 px, instead of a
  minute or more per image on CPU.

The memory ceiling is respected everywhere: images are downscaled to a working
canvas before rendering, variants are produced one at a time, and results can
be freed from the UI with one button.

The AI mode is careful with memory for a different reason - each image is
fetched, decoded and handed straight back to the UI, so peak usage stays near
one image rather than sixteen.

## What it looks like

The desktop app has three columns:

1. **Choose a style** - checkbox list grouped into Painting and Drawing, each
   with a one-line description. (Hidden in AI mode, where the *Look* dropdown
   replaces it.)
2. **Preview** - before/after with next/previous through the batch.
3. **Settings & save** - a **Mode** switch at the top, then either the offline
   knobs (images per style, detail, strength, working size, texture/vignette/
   border toggles) or the AI controls (what should change, look, number of
   images, output size), a seed box, and the save buttons.


## The styles

| Painting | Drawing |
| --- | --- |
| Oil Painting | Pencil Sketch |
| Oil Painting (Realism) | Charcoal |
| Acrylic (Impasto) | Digital Sketch |
| Watercolour | Comic Ink (Halftone) |
| Gouache | Ballpoint Pen |
| Palette Knife | Ink Line Art |
| Soft Pastel | Blueprint |
| Ink Wash (Sumi-e) | Pop Art |
| Spray Paint / Stencil | Pixel Art |
| | Film Noir |

Every style produces a *different* image for each variant, so asking for four
oil paintings gives you four alternative takes rather than four copies. Among
the deterministic styles (pixel art, line art, halftone), variants step through
sprite resolutions, line weights, paper tones and grid pitches.

## Getting started

### Option 1 - download the ready-made EXE (easiest)

1. Open the repository's **Actions** tab and pick the newest successful
   `build-windows-exe` run.
2. Download the `PixelMuse-windows-exe` artifact and unzip it.
3. Double-click **`PixelMuse.exe`**. That is the whole installation.

Tagged releases (`v1.1.0` and later) also appear on the **Releases** page with
the EXE attached, which is the simplest place to grab it from.

Windows SmartScreen may warn about an unsigned executable from the internet.
Choose *More info* then *Run anyway*. You can also build it yourself from
source, which is exactly what CI does.

> **A note about Windows 8.1.** The EXE is built on a modern Windows runner and
> has not been tested on 8.1. The Python code targets 3.10.11 and the offline
> engine uses nothing newer than Pillow and NumPy, so it should run - but
> Windows 8.1 is past end of life, and a wheel built for a newer Windows can
> refuse to load on it. If `PixelMuse.exe` will not start, first try **Option
> 2** from source with Python 3.10.11, and if pip tries to install a NumPy 2.x
> that will not import, pin the older build:
>
> ```bat
> pip install "numpy<2" Pillow
> ```
>
> NumPy 1.x explicitly supported Windows 8 and 8.1; the 2.x line moved its
> baseline forward. Everything here also works on NumPy 1.21+, so the pin is
> safe.

### Option 2 - run from source

```bat
git clone https://github.com/Askcodex-do/image.git
cd image
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app_gui.py
```

Python 3.10 from python.org already includes Tkinter, which is all the desktop
app needs.

### Option 3 - build the EXE yourself

```bat
packaging\build_exe.bat
```

This creates a virtual environment, installs dependencies, runs the test suite,
and only then packages `dist\PixelMuse.exe`. If the tests fail it refuses to
build, so you will not get a broken executable.

## Describe a change (AI mode)

The mode that adds things that were never in the photo.

**In the app:** open your image, switch **Mode** to *Describe a change*, type
what you want in the box, pick a *Look*, set the number of images (1-16) and the
output size, then press **Create from description**.

Example: upload a portrait, choose *Oil Painting (Realism)*, type
`make this an old princess wearing a black dress and a crown`, set 16 images.
You get 16 different paintings of your photo, each wearing the dress and crown,
which you can step through with *Previous* / *Next* and save one at a time, or
all at once as a folder, ZIP, contact sheet or PDF.

**From the command line:**

```bat
python app_cli.py describe photo.jpg ^
    -d "make this an old princess wearing a black dress and a crown" ^
    -t oil_realism -n 16 --side 768 -o outputs --zip outputs/batch.zip
```

| Flag | Meaning |
| --- | --- |
| `-d, --description` | what should change (required) |
| `-t, --look` | style key, same names as the offline list; default `oil_realism` |
| `-n, --count` | how many images to create (1-16) |
| `--side` | output size in pixels: 512, 640 or 768 |
| `-o, --out` | output folder |
| `--seed` | reproducible results |
| `--zip`, `--sheet`, `--pdf` | also write a zip / contact sheet PNG / multi-page PDF |

**What it sends, and where.** Your photo is downscaled to fit inside a 384 px
JPEG, base64-encoded into the request URL, and sent to a public image service
together with your text. The photo goes to that service and is not stored by
this app. Requests are trimmed to stay under the service's ~16 KB URL limit
(HTTP 431 if exceeded), which is why the reference is small rather than
full-size. If you would rather nothing left your machine, use the offline mode.

## Command line

Useful for batch work, or on a machine where you would rather not open a window.


```bat
python app_cli.py list

python app_cli.py generate photo.jpg --style oil_painting --style pixel_art ^
    -n 4 --max-side 1400 -o outputs

:: every style at once, plus a zip and a contact sheet
python app_cli.py generate photo.jpg --style all -n 2 ^
    -o outputs --zip outputs/batch.zip --sheet outputs/sheet.png

:: AI mode: change the photo from a text description
python app_cli.py describe photo.jpg -d "give this person a gold crown" -n 16
```

| Flag | Meaning |
| --- | --- |
| `--style KEY` | repeatable, or `all` |
| `-n, --variants` | images per style (1-16) |
| `-o, --out` | output folder, or a single file when there is one result |
| `--max-side` | working canvas long edge; lower means less RAM |
| `--detail` | 0 loose and painterly, 1 fine and tight |
| `--strength` | 0 subtle, 1 full effect |
| `--colors` | palette size hint for the quantising styles |
| `--seed` | reproduce an exact batch |
| `--format` | `.png`, `.jpg`, `.webp`, `.bmp` |
| `--zip`, `--sheet`, `--pdf` | also write a zip / contact sheet PNG / multi-page PDF |
| `--frame`, `--no-texture`, `--no-vignette` | finish toggles |

## Browser mode (optional)

If you prefer a browser, or your Python has no Tkinter, there is a local web UI.
It is still offline: Flask serves a page on `127.0.0.1` and rendering happens in
that process on your machine. Nothing is uploaded anywhere.

```bat
pip install -r requirements-web.txt
python app_web.py
```

Then open <http://127.0.0.1:8000>. The page has the same mode switch, style
picker and *Describe a change* box as the desktop app, shows the results inline
with a save link on each image, and offers the whole batch as a ZIP.

## Memory guide

Pick the working size that matches what you have free:

| Working size | Peak RAM | Typical use |
| --- | --- | --- |
| 800 px | ~120 MB | smallest footprint, quick drafts |
| 1100 px | ~190 MB | comfortable on 2 GB |
| 1400 px (default) | ~300 MB | good quality, still safe |
| 1800 px | ~480 MB | print-ish, close other apps first |

Measured peak Python allocation for six styles at 1400 px with two variants
each (12 images) was **283 MB**, in about 9 seconds total.

The AI mode is bounded differently: one image is in flight at a time, so peak
memory depends on the output size, not the count. A 16-image batch at 768 px
never holds more than a couple of images at once.

## Project layout

```
app_gui.py             desktop app launcher
app_cli.py             command line launcher
app_web.py             browser mode launcher
bootstrap.py           makes src/ importable from a plain checkout
src/pixelmuse/
    styles.py          style registry + shared painterly/sketch primitives
    catalog_paint.py   the painting family
    catalog_draw.py    the drawing family
    effects/core.py    numeric helpers: colour, texture, edges, framing
    generator.py       rendering engine and RAM-bounded batching
    textguide.py       AI mode: text-guided image creation and retries
    style_prompts.py   maps style keys onto prompt phrases
    session.py         headless app state shared by all three UIs
    gui.py             Tkinter view
    web.py             Flask view
    export.py          save batch / zip / PDF / contact sheet
    cli.py             argparse front end
    imgio.py           loading, EXIF rotation, format-aware saving
packaging/             PyInstaller specs + build scripts
tests/                 pytest suite and the built-EXE smoke test
.github/workflows/     CI: run tests, build and smoke-test the EXE
```

## Development

```bat
pip install -r requirements.txt -r requirements-web.txt pytest
python -m pytest tests -q
```

127 tests cover every style rendering a real non-degenerate image, variant
diversity, seed reproducibility, export formats, the headless session, the web
API, the CLI's error handling, and the AI mode - including its prompt building,
URL-budgeted reference encoding, and its retry, partial-failure and
total-failure paths.

The AI-mode tests run against a local stand-in server, so the suite still passes
with no internet connection. To exercise the real service instead:

```bat
set PIXELMUSE_LIVE_TEST=1
python -m pytest tests/test_textguide.py -q
```

To verify a built executable the way CI does:

```bat
python tests/exe_smoke.py dist\PixelMuse-CLI.exe oil_painting,pencil_sketch,pixel_art
```

That runs the real binary, checks it lists styles, renders the expected number
of images at the right size, writes the zip and contact sheet, produces
byte-identical output for the same seed, and fails cleanly on a non-image.

## Releases

Push a tag and GitHub Actions builds and smoke-tests the EXE, then attaches it
to a release:

```bat
git tag v1.1.0
git push origin v1.1.0
```

Releases are named after the tag, so `v1.1.0` publishes `PixelMuse 1.1.0`.
Update `__version__` in `src/pixelmuse/__init__.py` to match before tagging.

## Licence

MIT.
