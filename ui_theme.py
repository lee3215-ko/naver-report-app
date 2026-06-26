"""Modern UI theme, sidebar navigation, and shared widgets."""
import tkinter as tk
from tkinter import ttk

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

# ── Design tokens ──────────────────────────────────────────────
COLORS = {
    "bg": "#f1f5f9",
    "sidebar": "#0f172a",
    "sidebar_border": "#1e293b",
    "sidebar_hover": "#1e293b",
    "sidebar_active": "#334155",
    "sidebar_text": "#94a3b8",
    "sidebar_text_active": "#f8fafc",
    "card": "#ffffff",
    "card_border": "#e2e8f0",
    "tab_bg": "#ffffff",
    "tab_active": "#4f46e5",
    "tab_inactive": "#64748b",
    "tab_hover": "#eef2ff",
    "text": "#0f172a",
    "text_muted": "#64748b",
    "text_light": "#94a3b8",
    "accent": "#4f46e5",
    "accent_hover": "#4338ca",
    "accent_light": "#eef2ff",
    "danger": "#ef4444",
    "danger_hover": "#dc2626",
    "success": "#10b981",
    "success_hover": "#059669",
    "warning": "#f59e0b",
    "warning_hover": "#d97706",
    "border": "#e2e8f0",
    "input_bg": "#f8fafc",
    "input_border": "#cbd5e1",
    "preview_bg": "#f8fafc",
    "table_header": "#f1f5f9",
    "table_selected": "#c7d2fe",
}

FONT_FAMILY = "맑은 고딕"
FONTS = {
    "title": (FONT_FAMILY, 26, "bold"),
    "subtitle": (FONT_FAMILY, 13),
    "heading": (FONT_FAMILY, 15, "bold"),
    "subheading": (FONT_FAMILY, 12, "bold"),
    "body": (FONT_FAMILY, 11),
    "body_bold": (FONT_FAMILY, 11, "bold"),
    "small": (FONT_FAMILY, 10),
    "caption": (FONT_FAMILY, 9),
    "mono": ("Consolas", 10),
    "nav": (FONT_FAMILY, 13),
    "nav_active": (FONT_FAMILY, 13, "bold"),
    "badge": (FONT_FAMILY, 11, "bold"),
}

NAV_ITEMS = [
    ("Home", "대시보드"),
    ("신고 원본", "신고 원본"),
    ("리라이트 결과", "리라이트 결과"),
    ("Settings", "설정"),
    ("실행 로그", "실행 로그"),
]

PAGE_META = {
    "Home": ("대시보드", "등록된 신고 목록 및 작업 실행"),
    "신고 원본": ("신고 원본", "신고 원본 제목·내용 추가 및 관리"),
    "리라이트 결과": ("리라이트 결과", "GPT 변형 신고 문구 조회·수정"),
    "Settings": ("설정", "API 키 및 네이버 계정 관리"),
    "실행 로그": ("실행 로그", "자동 신고 진행 상황"),
}


def has_ctk():
    return ctk is not None


def frame(parent, bg=None, **kwargs):
    bg = bg or COLORS["bg"]
    if ctk:
        return ctk.CTkFrame(parent, fg_color=bg, corner_radius=0, **kwargs)
    f = tk.Frame(parent, bg=bg)
    return f


def card(parent, pad=0):
    if ctk:
        return ctk.CTkFrame(
            parent,
            fg_color=COLORS["card"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["card_border"],
        )
    return tk.Frame(
        parent,
        bg=COLORS["card"],
        highlightbackground=COLORS["card_border"],
        highlightthickness=1,
    )


def _parent_bg(parent):
    if ctk and isinstance(parent, ctk.CTkFrame):
        return parent.cget("fg_color")
    try:
        return parent.cget("bg")
    except tk.TclError:
        return COLORS["card"]


def label(parent, text, font_key="body", color=None, **kwargs):
    color = color or COLORS["text"]
    if ctk:
        kw = {"text": text, "font": FONTS[font_key], "text_color": color}
        kw.update(kwargs)
        return ctk.CTkLabel(parent, **kw)
    kw = {"text": text, "font": FONTS[font_key], "bg": _parent_bg(parent), "fg": color}
    kw.update(kwargs)
    return tk.Label(parent, **kw)


def button(parent, text, variant="primary", width=None, height=40, command=None):
    styles = {
        "primary": (COLORS["accent"], COLORS["accent_hover"], "#ffffff"),
        "danger": (COLORS["danger"], COLORS["danger_hover"], "#ffffff"),
        "success": (COLORS["success"], COLORS["success_hover"], "#ffffff"),
        "warning": (COLORS["warning"], COLORS["warning_hover"], "#ffffff"),
        "ghost": (COLORS["border"], "#e2e8f0", COLORS["text"]),
        "sidebar": (COLORS["sidebar_active"], COLORS["sidebar_hover"], COLORS["sidebar_text_active"]),
    }
    fg, hover, tc = styles.get(variant, styles["primary"])
    if ctk:
        kw = {
            "text": text,
            "height": height,
            "font": FONTS["body_bold"],
            "fg_color": fg,
            "hover_color": hover,
            "text_color": tc,
            "corner_radius": 10,
            "command": command,
        }
        if width:
            kw["width"] = width
        return ctk.CTkButton(parent, **kw)
    return tk.Button(
        parent, text=text, bg=fg, fg=tc, activebackground=hover,
        font=FONTS["body_bold"], relief=tk.FLAT, command=command,
    )


def configure_treeview(style_name: str):
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        style_name,
        background=COLORS["preview_bg"],
        foreground=COLORS["text"],
        fieldbackground=COLORS["preview_bg"],
        rowheight=38,
        font=FONTS["small"],
        borderwidth=0,
    )
    style.configure(
        f"{style_name}.Heading",
        background=COLORS["table_header"],
        foreground=COLORS["text_muted"],
        font=FONTS["subheading"],
        borderwidth=0,
        relief="flat",
    )
    style.map(
        style_name,
        background=[("selected", COLORS["table_selected"])],
        foreground=[("selected", COLORS["text"])],
    )


class SidebarNav:
    """Left sidebar navigation."""

    def __init__(self, parent, command):
        self.command = command
        self.buttons = {}
        self.current = NAV_ITEMS[0][0]

        self.frame = frame(parent, COLORS["sidebar"], width=232)
        self.frame.pack(side=tk.LEFT, fill=tk.Y)
        self.frame.pack_propagate(False)

        brand = frame(self.frame, COLORS["sidebar"])
        brand.pack(fill=tk.X, padx=20, pady=(28, 8))
        label(brand, "Naver Report", "heading", COLORS["sidebar_text_active"]).pack(anchor="w")
        label(brand, "자동 신고 도우미", "caption", COLORS["sidebar_text"]).pack(anchor="w", pady=(4, 0))

        sep = frame(self.frame, COLORS["sidebar_border"], height=1)
        sep.pack(fill=tk.X, padx=16, pady=(16, 12))
        if ctk:
            sep.configure(height=1)

        nav_wrap = frame(self.frame, COLORS["sidebar"])
        nav_wrap.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        for key, display in NAV_ITEMS:
            active = key == self.current
            if ctk:
                btn = ctk.CTkButton(
                    nav_wrap,
                    text=display,
                    height=44,
                    font=FONTS["nav_active"] if active else FONTS["nav"],
                    fg_color=COLORS["sidebar_active"] if active else "transparent",
                    hover_color=COLORS["sidebar_hover"],
                    text_color=COLORS["sidebar_text_active"] if active else COLORS["sidebar_text"],
                    anchor="w",
                    corner_radius=10,
                    command=lambda n=key: self.select(n),
                )
            else:
                btn = tk.Button(
                    nav_wrap,
                    text=display,
                    height=2,
                    font=FONTS["nav_active"] if active else FONTS["nav"],
                    bg=COLORS["sidebar_active"] if active else COLORS["sidebar"],
                    fg=COLORS["sidebar_text_active"] if active else COLORS["sidebar_text"],
                    activebackground=COLORS["sidebar_hover"],
                    relief=tk.FLAT,
                    anchor="w",
                    padx=12,
                    command=lambda n=key: self.select(n),
                )
            btn.pack(fill=tk.X, pady=3)
            self.buttons[key] = btn

        footer = frame(self.frame, COLORS["sidebar"])
        footer.pack(fill=tk.X, padx=20, pady=(0, 20))
        label(footer, "GPT · Selenium", "caption", COLORS["sidebar_text"]).pack(anchor="w")

    def select(self, name):
        self.current = name
        for key, btn in self.buttons.items():
            active = key == name
            if ctk:
                btn.configure(
                    fg_color=COLORS["sidebar_active"] if active else "transparent",
                    text_color=COLORS["sidebar_text_active"] if active else COLORS["sidebar_text"],
                    font=FONTS["nav_active"] if active else FONTS["nav"],
                )
            else:
                btn.configure(
                    bg=COLORS["sidebar_active"] if active else COLORS["sidebar"],
                    fg=COLORS["sidebar_text_active"] if active else COLORS["sidebar_text"],
                    font=FONTS["nav_active"] if active else FONTS["nav"],
                )
        self.command(name)


class PageHeader:
    """Top page title bar inside content area."""

    def __init__(self, parent):
        self.frame = frame(parent, COLORS["bg"])
        self.frame.pack(fill=tk.X, padx=28, pady=(24, 8))
        self.title = label(self.frame, "", "title", COLORS["text"])
        self.title.pack(anchor="w")
        self.subtitle = label(self.frame, "", "subtitle", COLORS["text_muted"])
        self.subtitle.pack(anchor="w", pady=(4, 0))

    def set(self, key):
        title, sub = PAGE_META.get(key, (key, ""))
        if ctk:
            self.title.configure(text=title)
            self.subtitle.configure(text=sub)
        else:
            self.title.configure(text=title)
            self.subtitle.configure(text=sub)
