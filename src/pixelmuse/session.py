"""Headless application state.

Everything the app knows lives here, with no dependency on Tkinter, Flask or
any other UI toolkit.  ``gui.py`` and ``web.py`` are thin views over this
module, which keeps the behaviour testable in environments without a display.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from PIL import Image

from . import export, imgio
from .generator import (
    DEFAULT_MAX_SIDE,
    DEFAULT_VARIANTS,
    RenderedImage,
    build_contact_sheet,
    render_many,
    styles_by_family,
)
from .styles import RenderOptions, Style, get_style

# Small canvases keep the preview responsive on a 2 GB machine; the user can
# raise this in the UI when they want a print-sized result.
PREVIEW_MAX_SIDE = 720
FULL_MAX_SIDE = DEFAULT_MAX_SIDE

ProgressFn = Callable[[str, float], None]
DoneFn = Callable[[List[RenderedImage], Optional[BaseException]], None]


@dataclass
class AppState:
    """Mutable state shared by the UI and the render worker."""

    source_path: Optional[Path] = None
    source_image: Optional[Image.Image] = None
    thumbnail: Optional[Image.Image] = None
    selected: List[str] = field(default_factory=list)
    options: RenderOptions = field(default_factory=RenderOptions)
    variants: int = DEFAULT_VARIANTS
    max_side: int = FULL_MAX_SIDE
    seed: Optional[int] = None
    results: List[RenderedImage] = field(default_factory=list)
    result_index: int = 0
    output_dir: Path = field(default_factory=lambda: Path.cwd() / "outputs")
    format_ext: str = ".png"

    @property
    def current_result(self) -> Optional[RenderedImage]:
        if not self.results:
            return None
        index = min(max(0, self.result_index), len(self.results) - 1)
        return self.results[index]

    @property
    def has_source(self) -> bool:
        return self.source_image is not None

    @property
    def can_render(self) -> bool:
        return self.has_source and bool(self.selected)


def load_source(state: AppState, path: str | Path, preview_side: int = 512) -> AppState:
    """Load an image into the state and build a small preview of it."""
    image = imgio.load_image(path)
    state.source_path = Path(path)
    state.source_image = image
    preview = image.copy()
    preview.thumbnail((preview_side, preview_side), Image.Resampling.LANCZOS)
    state.thumbnail = preview
    return state


def toggle_style(state: AppState, key: str) -> List[str]:
    """Add or remove a style from the selection; returns the new selection."""
    get_style(key)  # validates the key
    if key in state.selected:
        state.selected = [item for item in state.selected if item != key]
    else:
        state.selected = state.selected + [key]
    return list(state.selected)


def select_styles(state: AppState, keys: Sequence[str]) -> List[str]:
    """Replace the selection, ignoring duplicates and unknown keys."""
    seen: List[str] = []
    for key in keys:
        get_style(key)
        if key not in seen:
            seen.append(key)
    state.selected = seen
    return list(seen)


def styles_grouped() -> Dict[str, List[Style]]:
    """Families and their styles, for building the picker UI."""
    return styles_by_family()


def clear_results(state: AppState) -> None:
    """Drop rendered images so a 2 GB machine can release the memory."""
    state.results = []
    state.result_index = 0


def add_results(state: AppState, images: Sequence[RenderedImage]) -> None:
    state.results = list(state.results) + list(images)
    if state.results and state.result_index >= len(state.results):
        state.result_index = len(state.results) - 1


def next_result(state: AppState) -> Optional[RenderedImage]:
    if state.results:
        state.result_index = (state.result_index + 1) % len(state.results)
    return state.current_result


def previous_result(state: AppState) -> Optional[RenderedImage]:
    if state.results:
        state.result_index = (state.result_index - 1) % len(state.results)
    return state.current_result


def render_sync(
    state: AppState,
    progress: Optional[ProgressFn] = None,
    max_side: Optional[int] = None,
) -> List[RenderedImage]:
    """Render the selection on the calling thread and store the results."""
    if not state.can_render:
        raise RuntimeError("Pick an image and at least one style first")
    results = render_many(
        state.source_image,
        state.selected,
        variants=state.variants,
        options=state.options,
        max_side=max_side or state.max_side,
        seed=state.seed,
        progress=progress,
    )
    add_results(state, results)
    state.result_index = 0
    return results


def render_async(
    state: AppState,
    progress: Optional[ProgressFn] = None,
    done: Optional[DoneFn] = None,
    max_side: Optional[int] = None,
) -> threading.Thread:
    """Run :func:`render_sync` on a daemon thread and report back.

    The caller is responsible for marshalling the ``done`` callback back onto
    the UI thread (Tkinter's ``after`` works well for that).
    """

    def worker() -> None:
        error: Optional[BaseException] = None
        produced: List[RenderedImage] = []
        try:
            produced = render_sync(state, progress=progress, max_side=max_side)
        except BaseException as exc:  # surfaced to the UI, not swallowed
            error = exc
        if done is not None:
            done(produced, error)

    thread = threading.Thread(target=worker, name="pixelmuse-render", daemon=True)
    thread.start()
    return thread


def save_current(state: AppState, path: str | Path) -> Path:
    """Save the image currently shown."""
    item = state.current_result
    if item is None:
        raise RuntimeError("There is nothing to save yet")
    return imgio.save_image(item.image, path)


def save_all(state: AppState, directory: Optional[str | Path] = None) -> List[Path]:
    """Save the whole batch into the output directory."""
    if not state.results:
        raise RuntimeError("There is nothing to save yet")
    target = Path(directory) if directory else state.output_dir
    return export.save_batch(state.results, target, format_ext=state.format_ext)


def save_zip(state: AppState, path: str | Path) -> Path:
    if not state.results:
        raise RuntimeError("There is nothing to save yet")
    payload = export.batch_to_zip_bytes(state.results, format_ext=state.format_ext)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def save_contact_sheet(state: AppState, path: str | Path, columns: int = 4) -> Path:
    if not state.results:
        raise RuntimeError("There is nothing to save yet")
    sheet = build_contact_sheet(state.results, columns=columns)
    return imgio.save_image(sheet, path)


def summary(state: AppState) -> str:
    """One-line description of the current selection, used in status bars."""
    if not state.selected:
        return "No styles selected"
    labels = [get_style(key).label for key in state.selected]
    joined = ", ".join(labels[:3])
    if len(labels) > 3:
        joined += f" +{len(labels) - 3} more"
    return f"{len(labels)} style(s): {joined} | {state.variants} image(s) each"


__all__ = [
    "AppState",
    "PREVIEW_MAX_SIDE",
    "FULL_MAX_SIDE",
    "load_source",
    "toggle_style",
    "select_styles",
    "styles_grouped",
    "clear_results",
    "add_results",
    "next_result",
    "previous_result",
    "render_sync",
    "render_async",
    "save_current",
    "save_all",
    "save_zip",
    "save_contact_sheet",
    "summary",
]
