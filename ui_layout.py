"""Responsive window geometry, centering, and persistence helpers."""
import re
import tkinter as tk
from tkinter import ttk

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

from ui_theme import COLORS, FONTS, frame as ui_frame


def parse_tk_geometry(geo: str) -> dict | None:
    """Parse Tk geometry string ``WxH+X+Y`` (supports negative offsets)."""
    if not geo:
        return None
    m = re.match(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$", geo)
    if not m:
        return None
    return {
        "w": int(m.group(1)),
        "h": int(m.group(2)),
        "x": int(m.group(3)),
        "y": int(m.group(4)),
    }


def capture_window_geometry(window: tk.Misc) -> dict | None:
    """Return stable window geometry using the geometry string, not winfo root coords."""
    try:
        window.update_idletasks()
        parsed = parse_tk_geometry(window.geometry())
        if parsed and parsed["w"] >= 80 and parsed["h"] >= 80:
            return parsed
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


def apply_window_geometry(window: tk.Misc, geom: dict) -> None:
    """Apply a saved geometry dict without re-centering."""
    try:
        window.geometry(f"{int(geom['w'])}x{int(geom['h'])}+{int(geom['x'])}+{int(geom['y'])}")
        window.update_idletasks()
    except (tk.TclError, KeyError, TypeError, ValueError):
        pass


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
    return _clamp_position(width, height, x, y, sw, sh)


def _clamp_position(width: int, height: int, x: int, y: int, sw: int, sh: int) -> tuple[int, int]:
    x = max(0, min(x, max(0, sw - width)))
    y = max(0, min(y, max(0, sh - height)))
    return x, y


def is_visible_on_screen(
    width: int,
    height: int,
    x: int,
    y: int,
    sw: int,
    sh: int,
    min_visible: int = 120,
) -> bool:
    visible_w = min(x + width, sw) - max(x, 0)
    visible_h = min(y + height, sh) - max(y, 0)
    return visible_w >= min_visible and visible_h >= min_visible


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
        if not is_visible_on_screen(w, h, x, y, sw, sh):
            if parent is not None:
                x, y = center_on_parent(parent, w, h)
            else:
                x = max(0, (sw - w) // 2)
                y = max(0, (sh - h) // 2)
    else:
        w, h = _clamp_size(preferred_w, preferred_h, min_w, min_h, max_w, max_h)
        if parent is not None:
            x, y = center_on_parent(parent, w, h)
        else:
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)

    x, y = _clamp_position(w, h, x, y, sw, sh)
    return w, h, x, y


def bind_geometry_persistence(
    window: tk.Misc,
    geometry_key: str,
    geometry_store: dict,
    save_callback,
    *,
    debounce_ms: int = 0,
) -> None:
    """Remember user-resized window geometry when the window closes."""
    last_good: dict | None = None
    destroyed = [False]

    def capture() -> dict | None:
        if destroyed[0]:
            return last_good
        try:
            if not window.winfo_viewable():
                return None
        except tk.TclError:
            return None
        return capture_window_geometry(window)

    def persist(_event=None):
        if not geometry_key:
            return
        geom = capture() or last_good
        if not geom:
            return
        geometry_store[geometry_key] = geom
        if save_callback:
            save_callback()

    after_id: list[str | None] = [None]

    def on_configure(event=None):
        if destroyed[0] or event is not None and event.widget is not window:
            return
        try:
            if not window.winfo_viewable():
                return
        except tk.TclError:
            return
        nonlocal last_good
        snap = capture()
        if snap:
            last_good = snap
        if debounce_ms <= 0:
            return
        if after_id[0] is not None:
            window.after_cancel(after_id[0])
        after_id[0] = window.after(debounce_ms, persist)

    def on_destroy(event=None):
        if event is not None and event.widget is not window:
            return
        destroyed[0] = True
        if after_id[0] is not None:
            try:
                window.after_cancel(after_id[0])
            except tk.TclError:
                pass
        geom = capture_window_geometry(window) or last_good
        if geom and geometry_key:
            geometry_store[geometry_key] = geom
            if save_callback:
                save_callback()

    window.bind("<Configure>", on_configure, add="+")
    window.bind("<Destroy>", on_destroy, add="+")


def release_modal_grab(window: tk.Misc, parent: tk.Misc | None = None) -> None:
    """Release modal grabs held by a dialog, its parent, or any active grab widget."""
    seen: set[int] = set()
    candidates: list[tk.Misc] = []

    def add(widget: tk.Misc | None) -> None:
        if widget is None:
            return
        try:
            key = widget.winfo_id()
        except tk.TclError:
            return
        if key in seen:
            return
        seen.add(key)
        candidates.append(widget)

    add(window)
    add(parent)
    if window is not None:
        add(_widget_toplevel(window))
    if parent is not None:
        add(_widget_toplevel(parent))

    for widget in candidates:
        try:
            widget.grab_release()
        except tk.TclError:
            pass

    anchor = parent or window
    for _ in range(6):
        current = None
        if anchor is not None:
            try:
                current = anchor.grab_current()
            except tk.TclError:
                current = None
        if not current:
            break
        try:
            current.grab_release()
        except tk.TclError:
            break

    if anchor is not None:
        for args in (("grab", "release", anchor), ("grab", "release", "-global", anchor)):
            try:
                anchor.tk.call(*args)
            except tk.TclError:
                pass


def _widget_toplevel(widget: tk.Misc) -> tk.Misc | None:
    try:
        return widget.winfo_toplevel()
    except tk.TclError:
        return None


def restore_main_window_input(parent: tk.Misc | None) -> None:
    """Return keyboard/mouse focus to the main window after a modal closes."""
    if parent is None:
        return
    release_modal_grab(parent, parent)

    def _focus() -> None:
        try:
            if not parent.winfo_exists():
                return
            try:
                parent.deiconify()
            except tk.TclError:
                pass
            try:
                parent.state("normal")
            except tk.TclError:
                pass
            parent.lift()
            parent.focus_force()
        except tk.TclError:
            pass

    try:
        parent.after_idle(_focus)
    except tk.TclError:
        pass


def cancel_modal_presentation(window: tk.Misc | None) -> None:
    """Stop deferred modal grab/focus callbacks for a closing dialog."""
    if window is None:
        return
    setattr(window, "_modal_closed", True)
    after_ids = getattr(window, "_modal_after_ids", None)
    if not after_ids:
        return
    for after_id in after_ids:
        try:
            window.after_cancel(after_id)
        except tk.TclError:
            pass
    window._modal_after_ids = []


def _track_modal_after(window: tk.Misc, after_id: str) -> None:
    ids = getattr(window, "_modal_after_ids", None)
    if ids is None:
        ids = []
        window._modal_after_ids = ids
    ids.append(after_id)


def _set_window_normal(window: tk.Misc) -> None:
    try:
        window.deiconify()
    except tk.TclError:
        pass
    try:
        window.state("normal")
    except tk.TclError:
        pass


def _safe_topmost_off(window: tk.Misc) -> None:
    try:
        window.attributes("-topmost", False)
    except tk.TclError:
        pass


def present_modal_dialog(window: tk.Misc, parent: tk.Misc | None = None, *, _attempt: int = 0) -> None:
    """Show a CTk/tk dialog and only then grab input (avoids invisible modal freeze)."""
    if getattr(window, "_modal_closed", False):
        return
    if _attempt > 20:
        release_modal_grab(window, parent)
        return
    try:
        if not window.winfo_exists():
            return
        window.update_idletasks()
        _set_window_normal(window)
        window.update_idletasks()
        window.lift()
        try:
            window.attributes("-topmost", True)
            _track_modal_after(window, window.after(80, lambda: _safe_topmost_off(window)))
        except tk.TclError:
            pass
        window.update_idletasks()

        if not window.winfo_viewable():
            _track_modal_after(
                window,
                window.after(20, lambda: present_modal_dialog(window, parent, _attempt=_attempt + 1)),
            )
            return

        try:
            window.wait_visibility()
        except tk.TclError:
            pass

        if getattr(window, "_modal_closed", False) or not window.winfo_exists():
            return

        window.focus_force()
        try:
            window.grab_set()
        except tk.TclError:
            release_modal_grab(window, parent)
    except tk.TclError:
        release_modal_grab(window, parent)


def schedule_modal_dialog(window: tk.Misc, parent: tk.Misc | None = None) -> None:
    """Defer modal presentation until the widget tree is realized."""
    window.after(0, lambda: present_modal_dialog(window, parent))


def bind_modal_dialog(window: tk.Misc, parent: tk.Misc | None, on_close=None) -> None:
    """Ensure modal grab is released when the dialog closes."""

    def close():
        cancel_modal_presentation(window)
        if on_close:
            on_close()
            return
        release_modal_grab(window, parent)
        try:
            window.destroy()
        except tk.TclError:
            pass
        restore_main_window_input(parent)

    window.protocol("WM_DELETE_WINDOW", close)

    def on_destroy(event=None):
        if event is not None and event.widget is not window:
            return
        cancel_modal_presentation(window)
        restore_main_window_input(parent)

    window.bind("<Destroy>", on_destroy, add="+")


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
    *,
    modal: bool = False,
) -> tuple[int, int]:
    """Place a dialog; first open centers on *parent*, later opens restore last size/position."""
    store = geometry_store if geometry_store is not None else {}
    saved = store.get(geometry_key)
    w, h, x, y = resolve_geometry(saved, preferred_w, preferred_h, min_w, min_h, parent, max_ratio)
    window.geometry(f"{w}x{h}+{x}+{y}")
    window.minsize(min_w, min_h)
    window.update_idletasks()
    if geometry_key and geometry_store is not None:
        window.after_idle(
            lambda: bind_geometry_persistence(
                window, geometry_key, geometry_store, save_callback, debounce_ms=300
            )
        )
    if modal:
        schedule_modal_dialog(window, parent)
    return w, h


def fit_toplevel(
    window: tk.Toplevel,
    preferred_w: int,
    preferred_h: int,
    min_w: int,
    min_h: int,
    parent: tk.Misc | None = None,
    max_ratio: float = 0.92,
    *,
    modal: bool = False,
) -> tuple[int, int]:
    """Size and center a dialog on *parent* without persistence."""
    w, h, x, y = resolve_geometry(None, preferred_w, preferred_h, min_w, min_h, parent, max_ratio)
    window.geometry(f"{w}x{h}+{x}+{y}")
    window.minsize(min_w, min_h)
    window.update_idletasks()
    if modal:
        schedule_modal_dialog(window, parent)
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
        root.after_idle(
            lambda: bind_geometry_persistence(
                root, "main", geometry_store, save_callback, debounce_ms=400
            )
        )
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
