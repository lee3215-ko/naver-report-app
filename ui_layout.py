"""Responsive window geometry, centering, and persistence helpers."""
import tkinter as tk
from tkinter import ttk

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

from ui_theme import COLORS, FONTS, frame as ui_frame


def screen_size(window: tk.Misc) -> tuple[int, int]:
    window.update_idletasks()
    return window.winfo_screenwidth(), window.winfo_screenheight()


def center_on_parent(parent: tk.Misc, width: int, height: int) -> tuple[int, int]:
    """Return screen coordinates to center *width* x *height* on *parent*."""
    parent.update_idletasks()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    pw = max(parent.winfo_width(), 1)
    ph = max(parent.winfo_height(), 1)
    x = px + (pw - width) // 2
    y = py + (ph - height) // 2
    sw, sh = screen_size(parent)
    x = max(0, min(x, max(0, sw - width)))
    y = max(0, min(y, max(0, sh - height)))
    return x, y


def _clamp_size(
    width: int,
    height: int,
    min_w: int,
    min_h: int,
    max_w: int,
    max_h: int,
) -> tuple[int, int]:
    return (
        max(min_w, min(width, max_w)),
        max(min_h, min(height, max_h)),
    )


def resolve_geometry(
    saved: dict | None,
    preferred_w: int,
    preferred_h: int,
    min_w: int,
    min_h: int,
    parent: tk.Misc | None,
    max_ratio: float = 0.92,
    *,
    screen_ref: tk.Misc | None = None,
) -> tuple[int, int, int, int]:
    ref = screen_ref or parent
    if ref is not None:
        ref.update_idletasks()
        sw, sh = screen_size(ref)
    else:
        sw, sh = 1920, 1080
    max_w = max(min_w, int(sw * max_ratio))
    max_h = max(min_h, int(sh * max_ratio))

    if saved and saved.get("w") and saved.get("h"):
        w, h = _clamp_size(int(saved["w"]), int(saved["h"]), min_w, min_h, max_w, max_h)
        x = int(saved.get("x", 0))
        y = int(saved.get("y", 0))
    else:
        w, h = _clamp_size(preferred_w, preferred_h, min_w, min_h, max_w, max_h)
        if parent is not None:
            x, y = center_on_parent(parent, w, h)
        else:
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)

    x = max(0, min(x, max(0, sw - w)))
    y = max(0, min(y, max(0, sh - h)))
    return w, h, x, y


def bind_geometry_persistence(
    window: tk.Misc,
    geometry_key: str,
    geometry_store: dict,
    save_callback,
    *,
    debounce_ms: int = 0,
) -> None:
    """Remember user-resized window geometry when the window closes (and optionally while resizing)."""
    last_good: dict | None = None

    def capture() -> dict | None:
        try:
            window.update_idletasks()
            w = window.winfo_width()
            h = window.winfo_height()
            if w < 80 or h < 80:
                return None
            return {
                "w": w,
                "h": h,
                "x": window.winfo_rootx(),
                "y": window.winfo_rooty(),
            }
        except tk.TclError:
            return None

    def persist(_event=None):
        nonlocal last_good
        if not geometry_key:
            return
        geom = capture() or last_good
        if not geom:
            return
        geometry_store[geometry_key] = geom
        if save_callback:
            save_callback()

    after_id: list[str | None] = [None]

    def on_configure(_event=None):
        nonlocal last_good
        snap = capture()
        if snap:
            last_good = snap
        if debounce_ms <= 0:
            return
        if after_id[0] is not None:
            window.after_cancel(after_id[0])
        after_id[0] = window.after(debounce_ms, persist)

    window.bind("<Configure>", on_configure, add="+")
    window.bind("<Destroy>", persist, add="+")


def setup_toplevel(
    window: tk.Toplevel,
    geometry_key: str,
    preferred_w: int,
    preferred_h: int,
    min_w: int,
    min_h: int,
    parent: tk.Misc | None = None,
    geometry_store: dict | None = None,
    save_callback=None,
    max_ratio: float = 0.92,
) -> tuple[int, int]:
    """Place a dialog on first open centered on *parent*; later opens restore last size/position."""
    store = geometry_store if geometry_store is not None else {}
    saved = store.get(geometry_key)
    w, h, x, y = resolve_geometry(saved, preferred_w, preferred_h, min_w, min_h, parent, max_ratio)
    window.geometry(f"{w}x{h}+{x}+{y}")
    window.minsize(min_w, min_h)
    if geometry_key and geometry_store is not None:
        bind_geometry_persistence(
            window, geometry_key, geometry_store, save_callback, debounce_ms=300
        )
    return w, h


def fit_toplevel(
    window: tk.Toplevel,
    preferred_w: int,
    preferred_h: int,
    min_w: int,
    min_h: int,
    parent: tk.Misc | None = None,
    max_ratio: float = 0.92,
) -> tuple[int, int]:
    """Size and center a dialog on *parent* without persistence."""
    w, h, x, y = resolve_geometry(None, preferred_w, preferred_h, min_w, min_h, parent, max_ratio)
    window.geometry(f"{w}x{h}+{x}+{y}")
    window.minsize(min_w, min_h)
    return w, h


def apply_main_window(
    root: tk.Misc,
    preferred_w: int = 1520,
    preferred_h: int = 960,
    min_w: int = 1024,
    min_h: int = 680,
    geometry_store: dict | None = None,
    save_callback=None,
    max_ratio: float = 0.96,
) -> tuple[int, int]:
    """Open or restore the main window geometry."""
    w, h, x, y = resolve_geometry(
        geometry_store.get("main") if geometry_store else None,
        preferred_w,
        preferred_h,
        min_w,
        min_h,
        parent=None,
        max_ratio=max_ratio,
        screen_ref=root,
    )
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.minsize(min(min_w, w), min_h)
    if geometry_store is not None:
        bind_geometry_persistence(root, "main", geometry_store, save_callback, debounce_ms=400)
    return w, h


def scaled_px(base: int, screen_h: int, ref: int = 1080, floor_ratio: float = 0.55) -> int:
    ratio = min(1.0, screen_h / ref)
    return max(int(base * floor_ratio), int(base * ratio))


def make_scrollable(parent: tk.Misc) -> tuple[tk.Widget, tk.Widget]:
    """Return (host, content). Host should receive grid weight; form goes in content."""
    host = ui_frame(parent, COLORS["bg"])
    host.grid_rowconfigure(0, weight=1)
    host.grid_columnconfigure(0, weight=1)

    if ctk:
        scroll = ctk.CTkScrollableFrame(
            host,
            fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["accent"],
            scrollbar_button_hover_color=COLORS["accent_hover"],
        )
        scroll.grid(row=0, column=0, sticky="nsew")
        return host, scroll

    canvas = tk.Canvas(host, bg=COLORS["bg"], highlightthickness=0)
    scrollbar = ttk.Scrollbar(host, orient=tk.VERTICAL, command=canvas.yview)
    content = ui_frame(canvas, COLORS["bg"])
    content.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    win_id = canvas.create_window((0, 0), window=content, anchor="nw")

    def _on_canvas_configure(event):
        canvas.itemconfigure(win_id, width=event.width)

    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")

    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind_wheel(_event=None):
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _unbind_wheel(_event=None):
        canvas.unbind_all("<MouseWheel>")

    canvas.bind("<Enter>", _bind_wheel)
    canvas.bind("<Leave>", _unbind_wheel)
    host.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))
    return host, content
