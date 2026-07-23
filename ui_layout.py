"""Responsive window geometry and scroll helpers."""
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


def fit_toplevel(
    window: tk.Toplevel,
    preferred_w: int,
    preferred_h: int,
    min_w: int,
    min_h: int,
    parent: tk.Misc | None = None,
    max_ratio: float = 0.92,
) -> tuple[int, int]:
    """Size and center a dialog within the available screen area."""
    window.update_idletasks()
    sw, sh = screen_size(window)
    max_w = max(min_w, int(sw * max_ratio))
    max_h = max(min_h, int(sh * max_ratio))
    w = max(min_w, min(preferred_w, max_w))
    h = max(min_h, min(preferred_h, max_h))

    if parent is not None:
        parent.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = max(parent.winfo_width(), 1)
        ph = max(parent.winfo_height(), 1)
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
    else:
        x = (sw - w) // 2
        y = (sh - h) // 2

    x = max(0, min(x, max(0, sw - w)))
    y = max(0, min(y, max(0, sh - h)))

    window.geometry(f"{w}x{h}+{x}+{y}")
    window.minsize(min_w, min_h)
    return w, h


def apply_main_window(
    root: tk.Misc,
    preferred_w: int = 1520,
    preferred_h: int = 960,
    min_w: int = 1024,
    min_h: int = 680,
) -> tuple[int, int]:
    """Open the main window sized for the current display."""
    sw, sh = screen_size(root)
    max_w = int(sw * 0.96)
    max_h = int(sh * 0.92)
    w = max(min_w, min(preferred_w, max_w))
    h = max(min_h, min(preferred_h, max_h))
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.minsize(min(min_w, w), min(min_h, h))
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
