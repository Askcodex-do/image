"""Optional browser mode, for when a GUI toolkit is unavailable.

This is still fully offline: Flask serves a page on ``127.0.0.1`` and the
rendering happens in this process on your machine.  Nothing is uploaded
anywhere.  Only used if you prefer a browser over the desktop window, or if
your Python has no Tkinter.

    pip install -r requirements-web.txt
    python app_web.py            # then open http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import base64
import io
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Optional

from PIL import Image

from . import APP_NAME, APP_TAGLINE, __version__, export, imgio
from . import style_prompts, textguide
from .generator import render_many, styles_by_family
from .styles import RenderOptions

try:
    from flask import Flask, jsonify, render_template_string, request, send_file

    FLASK_AVAILABLE = True
except Exception as exc:  # pragma: no cover - optional dependency
    Flask = None  # type: ignore[assignment]
    FLASK_AVAILABLE = False
    FLASK_IMPORT_ERROR: Optional[BaseException] = exc

MAX_UPLOAD_BYTES = 24 * 1024 * 1024  # a generous cap for one photo

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ app_name }} - {{ tagline }}</title>
<style>
 :root { color-scheme: light dark; }
 * { box-sizing: border-box; }
 body { margin:0; font:15px/1.5 system-ui, "Segoe UI", sans-serif; background:#14161a; color:#e8e8ee; }
 header { padding:18px 24px; border-bottom:1px solid #2a2e36; }
 h1 { margin:0; font-size:19px; letter-spacing:.2px; }
 h1 span { color:#8b93a7; font-weight:400; font-size:14px; }
 main { display:grid; grid-template-columns: 340px 1fr; gap:20px; padding:20px 24px 48px; }
 .card { background:#1b1f26; border:1px solid #2a2e36; border-radius:12px; padding:16px; }
 label { display:block; font-size:13px; color:#aab2c4; margin:12px 0 4px; }
 input[type=file] { width:100%; }
 input[type=number], input[type=range], select { width:100%; }
 .styles { display:grid; gap:6px; max-height:340px; overflow:auto; margin-top:6px; }
 .styles label { display:flex; gap:8px; align-items:baseline; margin:0; padding:6px 8px;
                 border-radius:8px; background:#20252e; color:#e8e8ee; cursor:pointer; }
 .styles label:hover { background:#262c37; }
 .styles small { color:#8b93a7; }
 button { width:100%; margin-top:16px; padding:12px; border:0; border-radius:9px;
          background:#5b8cff; color:#08111f; font-weight:700; font-size:15px; cursor:pointer; }
 button:disabled { background:#39415a; color:#8b93a7; cursor:progress; }
 #grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:14px; }
 figure { margin:0; background:#12151a; border:1px solid #2a2e36; border-radius:10px; overflow:hidden; }
 figure img { width:100%; display:block; }
 figcaption { padding:8px 10px; font-size:12px; color:#9aa3b8; display:flex; justify-content:space-between; }
 a.dl { color:#9ecbff; text-decoration:none; }
 empty { color:#8b93a7; }
 #status { padding:10px 0; font-size:14px; color:#aab2c4; min-height:22px; }
 .modes { display:grid; gap:6px; margin-top:6px; }
 .modes label { display:flex; gap:8px; align-items:baseline; margin:0; padding:8px;
                border-radius:8px; background:#20252e; color:#e8e8ee; cursor:pointer; }
 .modes label:hover { background:#262c37; }
 .modes small { color:#8b93a7; }
 textarea { width:100%; font:inherit; padding:8px; border-radius:8px;
            border:1px solid #2a2e36; background:#12151a; color:#e8e8ee; resize:vertical; }
 .hint { font-size:12px; color:#8b93a7; margin:10px 0 0; }
 .warn { color:#ffcf7a; }
</style>
</head>
<body>
<header>
  <h1>{{ app_name }} <span>{{ version }} - {{ tagline }} (runs locally, nothing is uploaded)</span></h1>
</header>
<main>
  <section class="card">
    <form id="form">
      <label for="file">1. Your image</label>
      <input type="file" id="file" name="file" accept="image/*" required>

      <label>2. Mode</label>
      <div class="modes">
        <label><input type="radio" name="mode" value="styles" checked>
          <span>Style filters <small>offline, instant</small></span></label>
        <label><input type="radio" name="mode" value="describe">
          <span>Describe a change <small>needs internet, uses AI</small></span></label>
      </div>

      <div id="describe-block" hidden>
        <label for="description">What should change?</label>
        <textarea id="description" name="description" rows="4"
          placeholder="e.g. make this an old princess wearing a black dress and a crown"></textarea>

        <label for="tstyle">Look</label>
        <select id="tstyle" name="tstyle">
          {% for key, label in prompt_styles %}
            <option value="{{ key }}"{% if key == 'oil_realism' %} selected{% endif %}>{{ label }}</option>
          {% endfor %}
        </select>

        <label for="count">Number of images</label>
        <input type="number" id="count" name="count" value="4" min="1" max="16">

        <label for="output_side">Output size</label>
        <select id="output_side" name="output_side">
          <option value="512" selected>512 px (fastest)</option>
          <option value="640">640 px</option>
          <option value="768">768 px (best)</option>
        </select>
        <p class="hint">Each image takes roughly 5-60 seconds and is retried
        automatically if the service is busy. Nothing is stored anywhere except
        on this machine.</p>
      </div>

      <div id="styles-block">
        <label>2. Styles (multiple choice)</label>
        <div class="styles">
          {% for family, items in families.items() %}
            <strong>{{ family }}</strong>
            {% for style in items %}
              <label>
                <input type="checkbox" name="style" value="{{ style.key }}">
                <span>{{ style.label }}<br><small>{{ style.blurb }}</small></span>
              </label>
            {% endfor %}
          {% endfor %}
        </div>

        <label for="variants">Images per style</label>
        <input type="number" id="variants" name="variants" value="4" min="1" max="16">

        <label for="detail">Detail: loose &rarr; fine</label>
        <input type="range" id="detail" name="detail" min="0" max="1" step="0.05" value="0.5">

        <label for="strength">Effect strength</label>
        <input type="range" id="strength" name="strength" min="0" max="1" step="0.05" value="0.75">

        <label for="max_side">Working size (px, lower = less RAM)</label>
        <select id="max_side" name="max_side">
          <option value="800">800 - Small (~120 MB)</option>
          <option value="1100">1100 - Medium (~190 MB)</option>
          <option value="1400" selected>1400 - Standard (~300 MB)</option>
          <option value="1800">1800 - Large (~480 MB)</option>
        </select>
      </div>

      <button type="submit" id="go">Generate images</button>
    </form>
    <div id="status">Ready.</div>
  </section>

  <section>
    <div id="grid"><empty>Generated images appear here.</empty></div>
    <p><a class="dl" id="zip" href="#" style="display:none">Download everything as ZIP</a></p>
  </section>
</main>
<script>
const form = document.getElementById('form');
const status = document.getElementById('status');
const grid = document.getElementById('grid');
const go = document.getElementById('go');
const zipLink = document.getElementById('zip');
let batchId = null;

// Show only the controls that belong to the chosen mode.
const describeBlock = document.getElementById('describe-block');
const stylesBlock = document.getElementById('styles-block');
function syncMode() {
  const mode = form.querySelector('input[name=mode]:checked').value;
  describeBlock.hidden = mode !== 'describe';
  stylesBlock.hidden = mode !== 'styles';
}
for (const radio of form.querySelectorAll('input[name=mode]')) {
  radio.addEventListener('change', syncMode);
}
syncMode();

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const mode = data.get('mode') || 'styles';
  if (mode === 'styles' && !data.getAll('style').length) {
    status.textContent = 'Pick at least one style.'; return;
  }
  if (mode === 'describe' && !(data.get('description') || '').trim()) {
    status.textContent = 'Describe what should change.'; return;
  }
  go.disabled = true;
  status.textContent = mode === 'describe'
    ? 'Creating images from your description... each one takes a few seconds.'
    : 'Rendering... this happens on your machine.';
  grid.innerHTML = '';
  zipLink.style.display = 'none';
  try {
    const response = await fetch(
      mode === 'describe' ? '/api/describe' : '/api/generate',
      { method: 'POST', body: data });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || ('HTTP ' + response.status));
    }
    const payload = await response.json();
    batchId = payload.batch_id;
    let message = 'Done: ' + payload.images.length + ' image(s) in '
      + payload.seconds.toFixed(1) + 's.';
    if (payload.warnings && payload.warnings.length) {
      message += ' ' + payload.warnings.length + ' image(s) did not come back.';
    }
    status.textContent = message;
    if (payload.warnings && payload.warnings.length) {
      const note = document.createElement('div');
      note.className = 'warn';
      note.textContent = payload.warnings.join(' | ');
      status.appendChild(note);
    }
    for (const item of payload.images) {
      const figure = document.createElement('figure');
      figure.innerHTML = '<img alt="' + item.label + '" src="' + item.data_uri + '">'
        + '<figcaption><span>' + item.label + ' #' + (item.variant + 1) + '</span>'
        + '<a class="dl" download="' + item.filename + '" href="' + item.data_uri + '">save</a></figcaption>';
      grid.appendChild(figure);
    }
    if (payload.images.length) {
      zipLink.href = '/api/batch/' + batchId + '.zip';
      zipLink.style.display = 'inline';
    }
  } catch (error) {
    status.textContent = 'Failed: ' + error.message;
  } finally {
    go.disabled = false;
  }
});
</script>
</body>
</html>
"""


class BatchStore:
    """Keeps the last few batches in memory so the ZIP link keeps working.

    Bounded on purpose: a 2 GB machine must not hold every render forever.
    """

    def __init__(self, keep: int = 4) -> None:
        self._items: "dict[str, list]" = {}
        self._order: list[str] = []
        self._keep = max(1, keep)

    def put(self, images) -> str:
        key = f"batch{len(self._order) + 1}"
        self._items[key] = list(images)
        self._order.append(key)
        while len(self._order) > self._keep:
            self._items.pop(self._order.pop(0), None)
        return key

    def get(self, key: str):
        return self._items.get(key)


def _render_options(payload) -> tuple[RenderOptions, int, int]:
    def clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    options = RenderOptions(
        detail=clamp(float(payload.get("detail", 0.5)), 0.0, 1.0),
        strength=clamp(float(payload.get("strength", 0.75)), 0.0, 1.0),
        canvas_texture=payload.get("texture", "1") not in ("0", "false", "off"),
        vignette=payload.get("vignette", "1") not in ("0", "false", "off"),
        frame=payload.get("frame", "0") in ("1", "true", "on"),
    )
    variants = int(clamp(float(payload.get("variants", 4)), 1, 16))
    max_side = int(clamp(float(payload.get("max_side", 1400)), 320, 2200))
    return options, variants, max_side


def _data_uri(image: Image.Image, quality: int = 88) -> str:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def create_app() -> "Flask":
    if not FLASK_AVAILABLE:
        raise RuntimeError(
            f"Flask is required for the browser mode ({FLASK_IMPORT_ERROR}).\n"
            "Install it with:  pip install -r requirements-web.txt"
        )

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    store = BatchStore()

    @app.get("/")
    def index():
        return render_template_string(
            PAGE,
            app_name=APP_NAME,
            tagline=APP_TAGLINE,
            version=__version__,
            families=styles_by_family(),
            prompt_styles=[(key, style_prompts.label_for(key)) for key, _ in style_prompts.style_choices()],
        )

    @app.post("/api/generate")
    def generate():
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return "No image was uploaded.", 400

        keys = [key for key in request.form.getlist("style") if key]
        if not keys:
            return "Pick at least one style.", 400

        try:
            options, variants, max_side = _render_options(request.form)
        except (TypeError, ValueError):
            return "Settings must be numbers.", 400

        # Save to a temp file and reuse the same loader the desktop app uses,
        # so EXIF rotation and validation behave identically.
        suffix = Path(upload.filename).suffix or ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            upload.save(handle)
            temp_path = Path(handle.name)
        try:
            source = imgio.load_image(temp_path)
        except imgio.ImageLoadError as exc:
            return str(exc), 400
        finally:
            temp_path.unlink(missing_ok=True)

        import time

        started = time.perf_counter()
        results = render_many(
            source, keys, variants=variants, options=options, max_side=max_side
        )
        elapsed = time.perf_counter() - started

        batch_id = store.put(results)
        return jsonify(
            batch_id=batch_id,
            seconds=elapsed,
            images=[
                {
                    "label": item.style_label,
                    "style": item.style_key,
                    "variant": item.variant,
                    "filename": item.suggested_filename(),
                    "width": item.width,
                    "height": item.height,
                    "data_uri": _data_uri(item.image),
                }
                for item in results
            ],
        )

    @app.post("/api/describe")
    def describe():
        """Text-guided mode: the description changes the picture."""
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return "No image was uploaded.", 400

        description = (request.form.get("description") or "").strip()
        if not description:
            return "Describe what should change.", 400

        style_key = (request.form.get("tstyle") or "").strip()

        def number(name: str, low: int, high: int, fallback: int) -> int:
            raw = request.form.get(name)
            if raw is None or raw == "":
                return fallback
            try:
                return min(high, max(low, int(float(raw))))
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be a number")

        try:
            count = number("count", 1, 16, 4)
            output_side = number("output_side", 256, 1024, 512)
        except ValueError as exc:
            return str(exc), 400

        suffix = Path(upload.filename).suffix or ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            upload.save(handle)
            temp_path = Path(handle.name)
        try:
            source = imgio.load_image(temp_path)
        except imgio.ImageLoadError as exc:
            return str(exc), 400
        finally:
            temp_path.unlink(missing_ok=True)

        settings = textguide.BatchSettings(
            style_key=style_key or "oil_realism",
            style_label=style_prompts.label_for(style_key or "oil_realism"),
            style_prompt=style_prompts.prompt_for(style_key),
            description=description,
            count=count,
            output_side=output_side,
        )

        import time

        started = time.perf_counter()
        results, warnings = textguide.generate_batch(settings, source)
        elapsed = time.perf_counter() - started

        if not results:
            return (
                "Could not reach the image service. Check your internet connection. "
                + " ".join(warnings[:2]),
                502,
            )

        batch_id = store.put(results)
        return jsonify(
            batch_id=batch_id,
            seconds=elapsed,
            warnings=warnings,
            images=[
                {
                    "label": item.style_label,
                    "style": item.style_key,
                    "variant": item.variant,
                    "filename": item.suggested_filename(),
                    "width": item.width,
                    "height": item.height,
                    "data_uri": _data_uri(item.image),
                }
                for item in results
            ],
        )

    @app.get("/api/batch/<batch_id>.zip")
    def download_zip(batch_id: str):
        images = store.get(batch_id)
        if not images:
            return "That batch has expired, please generate again.", 404
        payload = export.batch_to_zip_bytes(images, format_ext=".png")
        return send_file(
            io.BytesIO(payload),
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"pixelmuse_{batch_id}.zip",
        )

    @app.get("/api/styles")
    def list_styles():
        return jsonify(
            {
                family: [
                    {"key": style.key, "label": style.label, "blurb": style.blurb}
                    for style in items
                ]
                for family, items in styles_by_family().items()
            }
        )

    @app.get("/api/health")
    def health():
        return jsonify({"app": APP_NAME, "version": __version__, "offline": True})

    return app


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="pixelmuse-web", description=f"{APP_NAME} browser mode")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (localhost by default)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        app = create_app()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    url = f"http://{args.host}:{args.port}/"
    print(f"{APP_NAME} {__version__} running at {url}  (local only, offline)")
    if not args.no_browser:
        webbrowser.open(url)
    app.run(host=args.host, port=args.port, threaded=True, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
