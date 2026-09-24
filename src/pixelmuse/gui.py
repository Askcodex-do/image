"""Tkinter desktop app - the offline EXE front end.

Layout:
    left   : style picker (checkboxes grouped by family, with descriptions)
    centre : before/after preview
    right  : render settings and export buttons
    bottom : status bar + progress

All logic lives in :mod:`pixelmuse.session`; this module is only the view.
"""

from __future__ import annotations

import queue
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from . import APP_NAME, APP_TAGLINE, __version__, imgio, session
from .generator import RenderedImage
from .styles import RenderOptions

try:  # tkinter ships with CPython on Windows; Linux may need python3-tk
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    TK_AVAILABLE = True
    TK_IMPORT_ERROR: Optional[BaseException] = None
except Exception as exc:  # pragma: no cover - depends on the host system
    tk = None  # type: ignore[assignment]
    ttk = None  # type: ignore[assignment]
    filedialog = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]
    TK_AVAILABLE = False
    TK_IMPORT_ERROR = exc


PAD = 8
SUPPORTED = imgio.supported_extensions()
FILE_TYPES = [
    ("Images", " ".join(f"*{ext}" for ext in SUPPORTED)),
    ("All files", "*.*"),
]


class PixelMuseApp:
    """The main window."""

    def __init__(self, root) -> None:
        self.root = root
        self.state = session.AppState()
        self._preview_refs: Dict[str, object] = {}
        self._events: "queue.Queue[tuple]" = queue.Queue()
        self._rendering = False

        root.title(f"{APP_NAME} {__version__} - {APP_TAGLINE}")
        root.minsize(1080, 680)
        self._build_style_vars()
        self._build_ui()
        self._pump_events()
        self._refresh_status()

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    def _build_style_vars(self) -> None:
        self.style_vars: Dict[str, "tk.BooleanVar"] = {}
        self.style_widgets: Dict[str, object] = {}

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=PAD)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0, minsize=290)
        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(2, weight=0, minsize=300)
        outer.rowconfigure(0, weight=1)

        self._build_style_panel(outer)
        self._build_preview_panel(outer)
        self._build_settings_panel(outer)
        self._build_status_bar()

    # -- style picker -------------------------------------------------- #
    def _build_style_panel(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text="1. Choose a style (description)", padding=PAD)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, PAD))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        canvas = tk.Canvas(frame, highlightthickness=0, width=260)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind(
            "<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        for widget in (canvas, inner):
            widget.bind("<MouseWheel>", self._on_mousewheel)
            widget.bind("<Button-4>", self._on_mousewheel)
            widget.bind("<Button-5>", self._on_mousewheel)

        for family, styles in session.styles_grouped().items():
            header = ttk.Label(inner, text=family, font=("Segoe UI", 10, "bold"))
            header.pack(anchor="w", pady=(PAD, 2))
            for style in styles:
                var = tk.BooleanVar(value=False)
                self.style_vars[style.key] = var
                check = ttk.Checkbutton(
                    inner,
                    text=style.label,
                    variable=var,
                    command=self._on_style_toggled,
                    takefocus=True,
                )
                check.pack(anchor="w")
                self.style_widgets[style.key] = check
                ttk.Label(
                    inner,
                    text=style.blurb,
                    wraplength=240,
                    foreground="#555555",
                    font=("Segoe UI", 8),
                    justify="left",
                ).pack(anchor="w", padx=(20, 0), pady=(0, 4))

        buttons = ttk.Frame(frame)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))
        ttk.Button(buttons, text="Select all", command=self._select_all_styles).pack(
            side="left", expand=True, fill="x", padx=(0, 4)
        )
        ttk.Button(buttons, text="Clear", command=self._clear_styles).pack(
            side="left", expand=True, fill="x"
        )

    # -- preview ------------------------------------------------------- #
    def _build_preview_panel(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text="2. Preview", padding=PAD)
        frame.grid(row=0, column=1, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.rowconfigure(1, weight=0)
        frame.columnconfigure(0, weight=1)

        self.preview = ttk.Label(
            frame, anchor="center", text="Open an image to begin", relief="sunken"
        )
        self.preview.grid(row=0, column=0, sticky="nsew")

        nav = ttk.Frame(frame)
        nav.grid(row=1, column=0, sticky="ew", pady=(PAD, 0))
        self.prev_button = ttk.Button(nav, text="< Previous", command=self._show_previous)
        self.prev_button.pack(side="left")
        self.next_button = ttk.Button(nav, text="Next >", command=self._show_next)
        self.next_button.pack(side="left", padx=(4, 0))
        self.counter = ttk.Label(nav, text="0 / 0")
        self.counter.pack(side="left", padx=PAD)
        self.caption = ttk.Label(nav, text="")
        self.caption.pack(side="right")

    # -- settings ------------------------------------------------------ #
    def _build_settings_panel(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text="3. Settings & save", padding=PAD)
        frame.grid(row=0, column=2, sticky="nsew", padx=(PAD, 0))
        frame.columnconfigure(0, weight=1)

        row = 0
        ttk.Button(frame, text="Open image...", command=self._open_image).grid(
            row=row, column=0, sticky="ew"
        )
        row += 1
        self.file_label = ttk.Label(
            frame, text="No image loaded", foreground="#555555", wraplength=260, justify="left"
        )
        self.file_label.grid(row=row, column=0, sticky="w", pady=(2, PAD))
        row += 1

        # --- mode switch: offline filters vs. text-guided changes ------
        self.mode_var = tk.StringVar(value="styles")
        modes = ttk.LabelFrame(frame, text="Mode", padding=(PAD, 4))
        modes.grid(row=row, column=0, sticky="ew")
        row += 1
        ttk.Radiobutton(
            modes, text="Style filters (offline, fast)",
            variable=self.mode_var, value="styles", command=self._on_mode_changed,
        ).pack(anchor="w")
        ttk.Radiobutton(
            modes, text="Describe a change (uses internet)",
            variable=self.mode_var, value="describe", command=self._on_mode_changed,
        ).pack(anchor="w")

        # --- text-guided controls, hidden until that mode is picked ----
        self.describe_frame = ttk.LabelFrame(frame, text="Describe", padding=(PAD, 4))
        self.describe_frame.grid(row=row, column=0, sticky="ew", pady=(PAD, 0))
        row += 1
        self.describe_frame.columnconfigure(0, weight=1)

        ttk.Label(
            self.describe_frame,
            text="What should change?",
            wraplength=250, justify="left",
        ).grid(row=0, column=0, sticky="w")
        self.description_text = tk.Text(self.describe_frame, height=4, width=28, wrap="word")
        self.description_text.grid(row=1, column=0, sticky="ew", pady=(2, 6))

        ttk.Label(self.describe_frame, text="Look").grid(row=2, column=0, sticky="w")
        look_keys = [key for key, _ in session.describe_choices()]
        self.look_var = tk.StringVar(value="oil_realism")
        ttk.Combobox(
            self.describe_frame, textvariable=self.look_var, state="readonly",
            values=look_keys,
        ).grid(row=3, column=0, sticky="ew")

        ttk.Label(self.describe_frame, text="Number of images").grid(
            row=4, column=0, sticky="w", pady=(6, 0)
        )
        self.describe_count_var = tk.IntVar(value=session.AppState().describe_count)
        ttk.Spinbox(
            self.describe_frame, from_=1, to=16, textvariable=self.describe_count_var, width=8
        ).grid(row=5, column=0, sticky="ew")

        ttk.Label(self.describe_frame, text="Output size").grid(
            row=6, column=0, sticky="w", pady=(6, 0)
        )
        self.describe_side_var = tk.StringVar(value="512 px")
        ttk.Combobox(
            self.describe_frame, textvariable=self.describe_side_var, state="readonly",
            values=["512 px", "640 px", "768 px"],
        ).grid(row=7, column=0, sticky="ew")

        ttk.Label(
            self.describe_frame,
            text="Roughly 5-60 s per image. Busy moments are retried automatically.",
            wraplength=250, justify="left", foreground="#555555", font=("Segoe UI", 8),
        ).grid(row=8, column=0, sticky="w", pady=(6, 0))

        self.describe_frame.grid_remove()

        self.variants_var = tk.IntVar(value=session.AppState().variants)
        self.detail_var = tk.DoubleVar(value=0.5)
        self.strength_var = tk.DoubleVar(value=0.75)
        self.colors_var = tk.IntVar(value=12)
        self.size_var = tk.StringVar(value="Standard (1400 px, ~300 MB)")
        self.texture_var = tk.BooleanVar(value=True)
        self.vignette_var = tk.BooleanVar(value=True)
        self.frame_var = tk.BooleanVar(value=False)
        self.seed_var = tk.StringVar(value="")

        # Knobs that only mean something to the offline renderers.  Hidden in
        # describe mode, where the model decides those details instead.
        self.offline_frame = ttk.Frame(frame)
        self.offline_frame.grid(row=row, column=0, sticky="ew")
        self.offline_frame.columnconfigure(0, weight=1)
        self.offline_frame.rowconfigure(0, weight=1)
        row += 1

        offline_inner = ttk.Frame(self.offline_frame)
        offline_inner.grid(row=0, column=0, sticky="ew")
        offline_inner.columnconfigure(0, weight=1)

        inner_row = 0
        inner_row = self._spin(offline_inner, inner_row, "Images per style", self.variants_var, 1, 16)
        inner_row = self._scale(offline_inner, inner_row, "Detail (loose -> fine)", self.detail_var, 0.0, 1.0)
        inner_row = self._scale(offline_inner, inner_row, "Effect strength", self.strength_var, 0.0, 1.0)
        inner_row = self._spin(offline_inner, inner_row, "Colour levels hint", self.colors_var, 3, 48)

        ttk.Label(offline_inner, text="Working size").grid(
            row=inner_row, column=0, sticky="w", pady=(PAD, 0)
        )
        inner_row += 1
        size_box = ttk.Combobox(
            offline_inner,
            textvariable=self.size_var,
            state="readonly",
            values=[
                "Small (800 px, ~120 MB)",
                "Medium (1100 px, ~190 MB)",
                "Standard (1400 px, ~300 MB)",
                "Large (1800 px, ~480 MB)",
            ],
        )
        size_box.grid(row=inner_row, column=0, sticky="ew")
        inner_row += 1

        ttk.Checkbutton(offline_inner, text="Canvas / paper texture", variable=self.texture_var).grid(
            row=inner_row, column=0, sticky="w", pady=(PAD, 0)
        )
        inner_row += 1
        ttk.Checkbutton(offline_inner, text="Vignette", variable=self.vignette_var).grid(
            row=inner_row, column=0, sticky="w"
        )
        inner_row += 1
        ttk.Checkbutton(offline_inner, text="Print border", variable=self.frame_var).grid(
            row=inner_row, column=0, sticky="w"
        )

        ttk.Label(frame, text="Seed (blank = random)").grid(row=row, column=0, sticky="w", pady=(PAD, 0))
        row += 1
        ttk.Entry(frame, textvariable=self.seed_var).grid(row=row, column=0, sticky="ew")
        row += 1

        self.render_button = ttk.Button(frame, text="Generate images", command=self._generate)
        self.render_button.grid(row=row, column=0, sticky="ew", pady=(PAD * 2, PAD))
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, sticky="ew", pady=PAD)
        row += 1

        self.save_button = ttk.Button(frame, text="Save this image...", command=self._save_current)
        self.save_button.grid(row=row, column=0, sticky="ew")
        row += 1
        self.save_all_button = ttk.Button(frame, text="Save all to folder...", command=self._save_all)
        self.save_all_button.grid(row=row, column=0, sticky="ew", pady=(4, 0))
        row += 1
        self.zip_button = ttk.Button(frame, text="Save all as ZIP...", command=self._save_zip)
        self.zip_button.grid(row=row, column=0, sticky="ew", pady=(4, 0))
        row += 1
        self.sheet_button = ttk.Button(
            frame, text="Save contact sheet...", command=self._save_sheet
        )
        self.sheet_button.grid(row=row, column=0, sticky="ew", pady=(4, 0))
        row += 1
        self.pdf_button = ttk.Button(frame, text="Save as PDF...", command=self._save_pdf)
        self.pdf_button.grid(row=row, column=0, sticky="ew", pady=(4, 0))
        row += 1
        self.clear_button = ttk.Button(frame, text="Clear results", command=self._clear_results)
        self.clear_button.grid(row=row, column=0, sticky="ew", pady=(4, 0))

    def _spin(self, parent, row: int, label: str, var, low: int, high: int) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(PAD, 0))
        row += 1
        ttk.Spinbox(parent, from_=low, to=high, textvariable=var, width=8).grid(
            row=row, column=0, sticky="ew"
        )
        return row + 1

    def _scale(self, parent, row: int, label: str, var, low: float, high: float) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(PAD, 0))
        row += 1
        ttk.Scale(parent, from_=low, to=high, variable=var, orient="horizontal").grid(
            row=row, column=0, sticky="ew"
        )
        return row + 1

    def _build_status_bar(self) -> None:
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", side="bottom")
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=PAD, pady=2)
        self.status = ttk.Label(bar, text="Ready", anchor="w")
        self.status.pack(side="left", padx=PAD)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _on_mousewheel(self, event) -> None:
        delta = 0
        if getattr(event, "num", None) == 4:
            delta = 1
        elif getattr(event, "num", None) == 5:
            delta = -1
        elif getattr(event, "delta", 0):
            delta = 1 if event.delta > 0 else -1
        if delta:
            event.widget.yview_scroll(-delta, "units")

    def _set_busy(self, busy: bool) -> None:
        self._rendering = busy
        state = "disabled" if busy else "normal"
        for widget in (
            self.render_button,
            self.save_button,
            self.save_all_button,
            self.zip_button,
            self.sheet_button,
            self.pdf_button,
            self.clear_button,
            self.prev_button,
            self.next_button,
        ):
            widget.configure(state=state)

    def _refresh_status(self) -> None:
        if self.state.results:
            done = self.state.result_index + 1
            total = len(self.state.results)
            current = self.state.current_result
            self.counter.configure(text=f"{done} / {total}")
            if current:
                self.caption.configure(
                    text=f"{current.style_label} #{current.variant + 1} "
                         f"({current.width}x{current.height}, {current.seconds:.1f}s)"
                )
            else:
                self.caption.configure(text="")
        else:
            self.counter.configure(text="0 / 0")
            self.caption.configure(text="")
        self.status.configure(text=session.summary(self.state))

    def _show_image(self, source: Optional[Image.Image], key: str = "main") -> None:
        if source is None:
            return
        width = max(200, self.preview.winfo_width() - 4)
        height = max(200, self.preview.winfo_height() - 4)
        preview = source.copy()
        preview.thumbnail((width, height), Image.Resampling.LANCZOS)
        photo = _to_photoimage(preview)
        self._preview_refs[key] = photo
        self.preview.configure(image=photo, text="")

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #
    def _open_image(self) -> None:
        path = filedialog.askopenfilename(title="Open an image", filetypes=FILE_TYPES)
        if not path:
            return
        try:
            session.load_source(self.state, path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.file_label.configure(text=str(Path(path).name))
        self._show_image(self.state.thumbnail)
        self.state.results = []
        self.state.result_index = 0
        self._refresh_status()
        self.status.configure(text="Image loaded. Pick a style and press Generate.")

    def _on_style_toggled(self) -> None:
        self.state.selected = [
            key for key, var in self.style_vars.items() if var.get()
        ]
        self._refresh_status()

    def _select_all_styles(self) -> None:
        for var in self.style_vars.values():
            var.set(True)
        self._on_style_toggled()

    def _clear_styles(self) -> None:
        for var in self.style_vars.values():
            var.set(False)
        self._on_style_toggled()

    def _collect_options(self) -> bool:
        """Read the widgets into ``state``. Returns False on bad input."""
        try:
            variants = int(self.variants_var.get())
            colors = int(self.colors_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror(APP_NAME, "Variants and colour levels must be whole numbers.")
            return False

        seed_text = self.seed_var.get().strip()
        seed: Optional[int] = None
        if seed_text:
            try:
                seed = int(seed_text)
            except ValueError:
                messagebox.showerror(APP_NAME, "Seed must be a whole number (or blank).")
                return False

        self.state.variants = max(1, min(16, variants))
        self.state.seed = seed
        self.state.max_side = _size_to_pixels(self.size_var.get())
        self.state.options = RenderOptions(
            detail=float(self.detail_var.get()),
            strength=float(self.strength_var.get()),
            colors=max(3, colors),
            canvas_texture=bool(self.texture_var.get()),
            vignette=bool(self.vignette_var.get()),
            frame=bool(self.frame_var.get()),
        )
        return True

    def _on_mode_changed(self) -> None:
        """Swap the visible controls and relabel the button for the mode."""
        describe = self.mode_var.get() == "describe"
        if describe:
            self.describe_frame.grid()
            self.offline_frame.grid_remove()
        else:
            self.describe_frame.grid_remove()
            self.offline_frame.grid()
        self.render_button.configure(
            text="Create from description" if describe else "Generate images"
        )
        self._refresh_status()

    def _collect_describe(self) -> bool:
        """Read the text-guided controls into the shared state."""
        text = self.description_text.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo(APP_NAME, "Describe what should change first.")
            return False
        if not self.state.has_source:
            messagebox.showinfo(APP_NAME, "Open an image first.")
            return False
        try:
            count = int(self.describe_count_var.get())
        except (tk.TclError, ValueError):
            count = session.AppState().describe_count
        side = int(self.describe_side_var.get().split()[0])

        self.state.mode = "describe"
        self.state.description = text
        self.state.describe_style = self.look_var.get() or "oil_realism"
        self.state.describe_count = max(1, min(16, count))
        self.state.describe_side = max(256, min(1024, side))
        self.state.seed = self._parse_seed()
        return True

    def _parse_seed(self) -> Optional[int]:
        raw = self.seed_var.get().strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _generate(self) -> None:
        if self._rendering:
            return
        self.state.selected = [key for key, var in self.style_vars.items() if var.get()]

        describing = self.mode_var.get() == "describe"
        if describing:
            if not self._collect_describe():
                return
        else:
            if not self.state.has_source:
                messagebox.showinfo(APP_NAME, "Open an image first.")
                return
            if not self.state.selected:
                messagebox.showinfo(APP_NAME, "Choose at least one style.")
                return
            if not self._collect_options():
                return

        self._set_busy(True)
        self.progress.configure(value=0)
        self.state.results = []
        self.state.result_index = 0
        self.state.warnings = []

        def on_progress(message: str, fraction: float) -> None:
            self._events.put(("progress", message, fraction))

        def on_done(images: List[RenderedImage], error: Optional[BaseException]) -> None:
            self._events.put(("done", images, error))

        if describing:
            session.describe_async(self.state, progress=on_progress, done=on_done)
        else:
            session.render_async(self.state, progress=on_progress, done=on_done)

    def _show_next(self) -> None:
        session.next_result(self.state)
        self._show_current()

    def _show_previous(self) -> None:
        session.previous_result(self.state)
        self._show_current()

    def _show_current(self) -> None:
        current = self.state.current_result
        if current is not None:
            self._show_image(current.image)
        self._refresh_status()

    def _save_current(self) -> None:
        current = self.state.current_result
        if current is None:
            messagebox.showinfo(APP_NAME, "Generate an image first.")
            return
        default = current.suggested_filename()
        path = filedialog.asksaveasfilename(
            title="Save image",
            initialfile=default,
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("WebP", "*.webp"), ("BMP", "*.bmp")],
        )
        if not path:
            return
        try:
            saved = session.save_current(self.state, path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.status.configure(text=f"Saved {saved}")

    def _save_all(self) -> None:
        if not self.state.results:
            messagebox.showinfo(APP_NAME, "Generate some images first.")
            return
        directory = filedialog.askdirectory(title="Choose an output folder")
        if not directory:
            return
        try:
            written = session.save_all(self.state, directory)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.status.configure(text=f"Saved {len(written)} image(s) to {directory}")

    def _save_zip(self) -> None:
        if not self.state.results:
            messagebox.showinfo(APP_NAME, "Generate some images first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save ZIP", initialfile="pixelmuse_batch.zip", defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")],
        )
        if not path:
            return
        try:
            target = session.save_zip(self.state, path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.status.configure(text=f"Saved {target}")

    def _save_sheet(self) -> None:
        if not self.state.results:
            messagebox.showinfo(APP_NAME, "Generate some images first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save contact sheet", initialfile="contact_sheet.png",
            defaultextension=".png", filetypes=[("PNG", "*.png")],
        )
        if not path:
            return
        try:
            target = session.save_contact_sheet(self.state, path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.status.configure(text=f"Saved {target}")

    def _save_pdf(self) -> None:
        if not self.state.results:
            messagebox.showinfo(APP_NAME, "Generate some images first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save PDF", initialfile="pixelmuse_batch.pdf",
            defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return
        try:
            target = session.save_pdf(self.state, path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.status.configure(text=f"Saved {target}")

    def _clear_results(self) -> None:
        session.clear_results(self.state)
        self.preview.configure(image="", text="Results cleared")
        self._preview_refs.pop("main", None)
        self._refresh_status()

    # ------------------------------------------------------------------ #
    # worker -> UI thread bridge
    # ------------------------------------------------------------------ #
    def _pump_events(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    _, message, fraction = event
                    self.progress.configure(value=fraction * 100.0)
                    self.status.configure(text=message)
                elif kind == "done":
                    _, images, error = event
                    self._set_busy(False)
                    if error is not None:
                        self.progress.configure(value=0)
                        self.status.configure(text="Render failed")
                        messagebox.showerror(APP_NAME, f"Rendering failed:\n\n{error}")
                    else:
                        self.progress.configure(value=100)
                        note = ""
                        if self.state.warnings:
                            note = f" ({len(self.state.warnings)} image(s) did not come back)"
                        self.status.configure(
                            text=f"Generated {len(images)} image(s).{note} "
                                 f"{session.summary(self.state)}"
                        )
                        self._show_current()
        except queue.Empty:
            pass
        self.root.after(80, self._pump_events)


def _to_photoimage(image: Image.Image):
    """Pillow image -> Tk photo image, preferring the bundled Tk 8.6 path."""
    try:
        from PIL import ImageTk

        return ImageTk.PhotoImage(image)
    except Exception:
        # Fallback that needs no ImageTk: hand Tk raw PPM bytes.
        from PIL import Image as _Image

        buffer = _Image.new("RGB", image.size)
        buffer.paste(image.convert("RGB"))
        header = f"P6 {buffer.width} {buffer.height} 255 ".encode("ascii")
        return tk.PhotoImage(data=header + buffer.tobytes())


def _size_to_pixels(label: str) -> int:
    for token in label.split():
        if token.isdigit():
            return int(token)
    return session.FULL_MAX_SIDE


def main(argv: Optional[List[str]] = None) -> int:
    """Launch the desktop app."""
    if not TK_AVAILABLE:
        print(
            "PixelMuse needs Tkinter, which is not available in this Python.\n"
            f"Import error: {TK_IMPORT_ERROR}\n\n"
            "On Windows the official python.org installer includes Tkinter.\n"
            "On Debian/Ubuntu install it with:  sudo apt install python3-tk",
            file=sys.stderr,
        )
        return 1

    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    try:
        app = PixelMuseApp(root)
    except Exception:
        traceback.print_exc()
        messagebox.showerror(APP_NAME, "The window failed to start. See the console for details.")
        return 1

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and Path(arguments[0]).is_file():
        try:
            session.load_source(app.state, arguments[0])
            app.file_label.configure(text=Path(arguments[0]).name)
            app._show_image(app.state.thumbnail)
            app._refresh_status()
        except Exception as exc:
            messagebox.showwarning(APP_NAME, str(exc))

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
