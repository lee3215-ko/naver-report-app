import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import re
import threading
import time
from datetime import datetime
from urllib.parse import quote

from naver_reporter import NaverReporter
from naver_search_url import build_naver_search_url as resolve_naver_search_url
from paths import data_path, APP_VERSION, is_admin_mode
from ui_theme import (
    COLORS,
    FONTS,
    SidebarNav,
    PageHeader,
    configure_treeview,
    get_nav_items,
    frame as ui_frame,
    card as ui_card,
    label as ui_label,
    button as ui_button,
)
from ui_layout import (
    apply_main_window,
    apply_window_geometry,
    bind_modal_dialog,
    cancel_modal_presentation,
    capture_window_geometry,
    fit_toplevel,
    make_scrollable,
    release_modal_grab,
    restore_main_window_input,
    scaled_px,
    screen_size,
    setup_toplevel,
)

try:
    import customtkinter as ctk
except ImportError:
    ctk = None

try:
    import openai
except ImportError:
    openai = None

ACCOUNTS_FILE = data_path("accounts.json")
SETTINGS_FILE = data_path("settings.json")
RESULTS_FILE = data_path("results.json")
TASKS_FILE = data_path("tasks.json")
TEMPLATES_FILE = data_path("templates.json")
CAFE_KEYWORDS_FILE = data_path("cafe_keywords.json")
CAFE_RESULTS_FILE = data_path("cafe_results.json")
CAFE_COLLECTED_FILE = data_path("cafe_collected.json")
BLOG_URLS_FILE = data_path("blog_urls.json")
BLOG_RESULTS_FILE = data_path("blog_results.json")

BLOG_REPORT_REASONS = {
    "0": "혐오/차별적/생명경시/욕설 표현입니다.",
    "1": "스팸홍보/도배입니다.",
    "2": "청소년에게 유해한 내용입니다.",
    "3": "불법정보를 포함하고 있습니다.",
    "4": "음란물입니다.",
    "5": "불쾌한 표현이 있습니다.",
}

SEARCH_URL_AUTO_PLACEHOLDER = "자동설정 중입니다"

DEFAULT_INQUIRY_CATEGORY = "illegal"
INQUIRY_CATEGORY_LABELS = {
    "illegal": "불법성",
    "spam": "스팸성",
}

DEFAULT_TEMPLATES = [
    {
        "id": "카드깡원본",
        "title": "카드깡 원본",
        "content": (
            "불법금융업 카드깡 업체입니다\n"
            "불법금융업에 불법홍보물까지 아이들이 포켓몬 카드깡 검색도중\n"
            "미성년자들에게도 이런게 노출이되어버리네요\n"
            "미성년자 교육이 정말 심각하게 안좋습니다\n"
            "네이버 측에서 빠르게 처리 해주세요"
        ),
    },
    {
        "id": "현금화원본",
        "title": "신용카드현금화 원본",
        "content": (
            "해당 사이트는 신용카드 현금화를 통해 불법적인 금융 거래를 조장합니다.\n"
            "미성년자나 금융에 취약한 이용자들까지 피해를 볼 수 있어 신고합니다.\n"
            "네이버 측에서 신속히 조치해 주시기 바랍니다."
        ),
    },
]


class DetailWindow:
    def __init__(self, parent, site, report_type, original, rewritten,
                 account_id="", account_password="",
                 search_url="", search_url_custom=False, search_url_auto=False,
                 app=None):
        self.top = ctk.CTkToplevel(parent) if ctk else tk.Toplevel(parent)
        self.top.title("신고 내용 상세")
        if ctk:
            self.top.configure(fg_color=COLORS["bg"])
        else:
            self.top.configure(bg=COLORS["bg"])
        self.top.transient(parent)
        self.top.resizable(True, True)

        outer = ui_frame(self.top, COLORS["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)
        outer.grid_rowconfigure(2, weight=1)
        outer.grid_rowconfigure(4, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        meta = ui_card(outer)
        meta.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        meta_inner = ui_frame(meta, COLORS["card"])
        meta_inner.pack(fill=tk.X, padx=20, pady=16)
        ui_label(meta_inner, "URL", "small", COLORS["text_muted"]).pack(anchor="w")
        self.site_box = self._url_textbox(meta_inner)
        self.site_box.pack(fill=tk.X, pady=(6, 10))
        self._set_text(self.site_box, site)
        self.site_box.bind("<Double-Button-1>", self._on_url_double_click)
        mode_label = ReportApp.search_url_mode_label(search_url_custom, search_url_auto)
        ui_label(meta_inner, f"유형 · {report_type}", "small", COLORS["text_muted"]).pack(anchor="w", pady=(0, 4))
        ui_label(meta_inner, f"검색결과 URL · {mode_label}", "small", COLORS["text_muted"]).pack(anchor="w", pady=(0, 8))
        display_search = (search_url or site).strip()
        if display_search and (search_url_auto or search_url_custom or display_search != site):
            self.search_url_box = self._url_textbox(meta_inner)
            self.search_url_box.pack(fill=tk.X, pady=(0, 10))
            self._set_text(self.search_url_box, display_search)
            self.search_url_box.bind("<Double-Button-1>", self._on_search_url_double_click)
        else:
            self.search_url_box = None

        cred_row = ui_frame(meta_inner, COLORS["card"])
        cred_row.pack(fill=tk.X, pady=(4, 0))
        cred_row.grid_columnconfigure(0, weight=1)
        cred_row.grid_columnconfigure(1, weight=1)

        id_col = ui_frame(cred_row, COLORS["card"])
        id_col.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ui_label(id_col, "네이버 아이디", "small", COLORS["text_muted"]).pack(anchor="w")
        self.account_id_box = self._cred_textbox(id_col, height=36)
        self.account_id_box.pack(fill=tk.X, pady=(4, 0))
        self._set_text(self.account_id_box, account_id or "")

        pw_col = ui_frame(cred_row, COLORS["card"])
        pw_col.grid(row=0, column=1, sticky="ew")
        ui_label(pw_col, "비밀번호", "small", COLORS["text_muted"]).pack(anchor="w")
        self.account_pw_box = self._cred_textbox(pw_col, height=36)
        self.account_pw_box.pack(fill=tk.X, pady=(4, 0))
        self._set_text(self.account_pw_box, account_password or "")

        ui_label(outer, "원본 신고 내용", "subheading", COLORS["text"]).grid(row=1, column=0, sticky="w")
        orig_card = ui_card(outer)
        orig_card.grid(row=2, column=0, sticky="nsew", pady=(6, 14))
        self.orig_box = self._textbox(orig_card, readonly=True)
        self.orig_box.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        self._set_text(self.orig_box, original, readonly=True)

        header_row = ui_frame(outer, COLORS["bg"])
        header_row.grid(row=3, column=0, sticky="ew")
        ui_label(header_row, "리라이트 신고 내용", "subheading", COLORS["text"]).pack(side=tk.LEFT)
        self.length_label = ui_label(header_row, "0자", "caption", COLORS["accent"])
        self.length_label.pack(side=tk.RIGHT)

        rew_card = ui_card(outer)
        rew_card.grid(row=4, column=0, sticky="nsew", pady=(6, 14))
        self.rew_box = self._textbox(rew_card)
        self.rew_box.pack(fill=tk.BOTH, expand=True, padx=14, pady=14)
        self._set_text(self.rew_box, rewritten)
        self.update_length()
        self.rew_box.bind("<KeyRelease>", lambda e: self.update_length())

        btn_frame = ui_frame(outer, COLORS["bg"])
        btn_frame.grid(row=5, column=0, sticky="e")
        ui_button(btn_frame, "닫기", "ghost", width=100, command=self.top.destroy).pack(side=tk.RIGHT)
        ui_button(btn_frame, "저장", "success", width=100, command=self.save_changes).pack(side=tk.RIGHT, padx=(0, 8))
        ui_button(btn_frame, "복사", "primary", width=100, command=self.copy_rewritten).pack(side=tk.RIGHT, padx=(0, 8))

        self.site = site
        self.report_type = report_type
        if app:
            app.setup_dialog(self.top, "detail", 860, 720, 640, 520, modal=True)
            bind_modal_dialog(self.top, parent)
        else:
            fit_toplevel(self.top, 860, 720, 640, 520, parent=parent, modal=True)
            self.top.resizable(True, True)

    def _url_textbox(self, parent):
        if ctk:
            tb = ctk.CTkTextbox(
                parent, wrap="char", font=FONTS["mono"], height=72,
                fg_color=COLORS["input_bg"], text_color=COLORS["accent"],
                border_color=COLORS["input_border"], border_width=1,
                corner_radius=10, activate_scrollbars=True,
            )
            tb.bind("<Key>", lambda e: "break")
            return tb
        tb = tk.Text(
            parent, wrap=tk.CHAR, font=FONTS["mono"], height=4,
            bg=COLORS["input_bg"], fg=COLORS["accent"],
            insertbackground=COLORS["accent"],
            highlightbackground=COLORS["input_border"], highlightthickness=1,
            padx=12, pady=10, relief=tk.FLAT,
        )
        tb.bind("<Key>", lambda e: "break")
        return tb

    def _on_url_double_click(self, event=None):
        text = self._get_text(self.site_box)
        if ctk and isinstance(self.site_box, ctk.CTkTextbox):
            self.site_box.tag_add("sel", "1.0", "end")
        else:
            self.site_box.tag_add(tk.SEL, "1.0", tk.END)
        self.top.clipboard_clear()
        self.top.clipboard_append(text)

    def _on_search_url_double_click(self, event=None):
        if not self.search_url_box:
            return
        text = self._get_text(self.search_url_box)
        if ctk and isinstance(self.search_url_box, ctk.CTkTextbox):
            self.search_url_box.tag_add("sel", "1.0", "end")
        else:
            self.search_url_box.tag_add(tk.SEL, "1.0", tk.END)
        self.top.clipboard_clear()
        self.top.clipboard_append(text)

    def _cred_textbox(self, parent, height=36):
        if ctk:
            tb = ctk.CTkTextbox(
                parent, wrap="char", font=FONTS["mono"], height=height,
                fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"], border_width=1,
                corner_radius=8, activate_scrollbars=False,
            )
            tb.bind("<Key>", lambda e: "break")
            return tb
        tb = tk.Text(
            parent, wrap=tk.CHAR, font=FONTS["mono"], height=2,
            bg=COLORS["input_bg"], fg=COLORS["text"],
            highlightbackground=COLORS["input_border"], highlightthickness=1,
            padx=10, pady=6, relief=tk.FLAT,
        )
        tb.bind("<Key>", lambda e: "break")
        return tb

    def _textbox(self, parent, readonly=False):
        if ctk:
            tb = ctk.CTkTextbox(
                parent, wrap=tk.WORD, font=FONTS["body"],
                fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"], border_width=1,
                corner_radius=10, activate_scrollbars=True,
            )
            if readonly:
                tb.configure(state="disabled")
            return tb
        return tk.Text(
            parent, wrap=tk.WORD, font=FONTS["body"],
            bg=COLORS["input_bg"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            highlightbackground=COLORS["input_border"], highlightthickness=1,
            padx=10, pady=10, relief=tk.FLAT,
        )

    def _set_text(self, widget, text, readonly=False):
        if ctk and isinstance(widget, ctk.CTkTextbox):
            widget.configure(state="normal")
            widget.delete("1.0", tk.END)
            widget.insert("1.0", text)
            if readonly:
                widget.configure(state="disabled")
        else:
            widget.configure(state=tk.NORMAL)
            widget.delete("1.0", tk.END)
            widget.insert(tk.END, text)
            if readonly:
                widget.configure(state=tk.DISABLED)

    def _get_text(self, widget):
        if ctk and isinstance(widget, ctk.CTkTextbox):
            return widget.get("1.0", tk.END).strip()
        return widget.get("1.0", tk.END).strip()

    def update_length(self):
        text = self._get_text(self.rew_box)
        self.length_label.configure(text=f"{len(text)}자")

    def copy_rewritten(self):
        text = self._get_text(self.rew_box)
        self.top.clipboard_clear()
        self.top.clipboard_append(text)

    def save_changes(self):
        text = self._get_text(self.rew_box)
        results = {}
        if os.path.exists(RESULTS_FILE):
            try:
                with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                    results = json.load(f)
            except Exception:
                pass
        key = f"{self.report_type}|{self.site}"
        if key not in results:
            results[key] = {}
        results[key]["rewritten"] = text
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("저장", "수정된 내용이 저장되었습니다.")


class BlogResultDetailWindow:
    STATUS_LABELS = {
        "ok": "완료",
        "already_reported": "이미신고(네이버)",
        "previously_reported": "이미 신고했습니다",
        "protected": "보호조치",
        "login_failed": "로그인실패",
        "stopped": "중단",
        "failed": "실패",
    }

    COPYABLE_FIELDS = {"네이버 계정", "비밀번호", "게시물 URL"}

    def __init__(self, parent, row: dict, report_count: int = 0, app=None):
        self.row = row
        self.report_count = report_count
        self.top = ctk.CTkToplevel(parent) if ctk else tk.Toplevel(parent)
        self.top.title("블로그 신고 상세")
        if ctk:
            self.top.configure(fg_color=COLORS["bg"])
        else:
            self.top.configure(bg=COLORS["bg"])
        self.top.transient(parent)
        self.top.resizable(True, True)

        outer = ui_frame(self.top, COLORS["bg"])
        outer.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        scroll_host = ui_frame(outer, COLORS["bg"])
        scroll_host.grid(row=0, column=0, sticky="nsew")
        scroll_host.grid_rowconfigure(0, weight=1)
        scroll_host.grid_columnconfigure(0, weight=1)

        if ctk:
            scroll = ctk.CTkScrollableFrame(
                scroll_host,
                fg_color=COLORS["bg"],
                scrollbar_button_color=COLORS["accent"],
                scrollbar_button_hover_color=COLORS["accent_hover"],
            )
            scroll.grid(row=0, column=0, sticky="nsew")
            content = scroll
        else:
            canvas = tk.Canvas(scroll_host, bg=COLORS["bg"], highlightthickness=0)
            scrollbar = ttk.Scrollbar(scroll_host, orient=tk.VERTICAL, command=canvas.yview)
            content = ui_frame(canvas, COLORS["bg"])
            content.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
            )
            canvas.create_window((0, 0), window=content, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")

            def _on_mousewheel(event):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

            canvas.bind_all("<MouseWheel>", _on_mousewheel, add="+")
            self.top.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        card = ui_card(content)
        card.pack(fill=tk.BOTH, expand=True)

        inner = ui_frame(card, COLORS["card"])
        inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        status = row.get("status", "")
        status_label = self.STATUS_LABELS.get(status, status or "-")

        fields = [
            ("네이버 계정", row.get("account_id", "")),
            ("비밀번호", row.get("account_password", "")),
            ("게시물 URL", row.get("url", "")),
            ("게시물 제목", row.get("title", "") or "(제목 없음)"),
            ("신고 사유", row.get("reason", "")),
            ("상태", status_label),
            ("일시", row.get("datetime", "")),
        ]

        for label, value in fields:
            if label == "게시물 URL":
                self._add_url_field(inner, value, self.report_count)
            else:
                self._add_field(inner, label, value)

        btn_row = ui_frame(outer, COLORS["bg"])
        btn_row.grid(row=1, column=0, sticky="e", pady=(12, 0))
        ui_button(btn_row, "닫기", "ghost", height=38, command=self.top.destroy).pack(side=tk.RIGHT)
        if app:
            app.setup_dialog(self.top, "blog_detail", 660, 580, 520, 420)
        else:
            fit_toplevel(self.top, 660, 580, 520, 420, parent=parent)
            self.top.resizable(True, True)

    def _add_url_field(self, parent, url: str, report_count: int):
        label_text = f"게시물 URL · 총 신고 {report_count}회"
        ui_label(parent, label_text, "small", COLORS["text_muted"]).pack(anchor="w", pady=(10, 4))
        row = ui_frame(parent, COLORS["card"])
        row.pack(fill=tk.X, pady=(0, 2))
        row.grid_columnconfigure(0, weight=1)
        box = self._read_only_box(row, url, tall=True)
        box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ui_button(
            row, "복사", "secondary", width=64, height=36,
            command=lambda v=url: self._copy_value(v, "게시물 URL"),
        ).grid(row=0, column=1, sticky="e")

    def _add_field(self, parent, label: str, value: str):
        ui_label(parent, label, "small", COLORS["text_muted"]).pack(anchor="w", pady=(10, 4))
        row = ui_frame(parent, COLORS["card"])
        row.pack(fill=tk.X, pady=(0, 2))
        row.grid_columnconfigure(0, weight=1)

        tall = label == "게시물 URL"
        box = self._read_only_box(row, value, tall=tall)
        box.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        if label in self.COPYABLE_FIELDS:
            ui_button(
                row, "복사", "secondary", width=64, height=36,
                command=lambda v=value, n=label: self._copy_value(v, n),
            ).grid(row=0, column=1, sticky="e")

    def _read_only_box(self, parent, text: str, tall: bool = False):
        height = 72 if tall else 38
        if ctk:
            tb = ctk.CTkTextbox(
                parent, wrap="char", font=FONTS["mono"], height=height,
                fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"], border_width=1,
                corner_radius=8, activate_scrollbars=tall,
            )
            tb.insert("1.0", text or "")
            tb.configure(state="disabled")
            return tb
        tb = tk.Text(
            parent, wrap=tk.CHAR, font=FONTS["mono"], height=4 if tall else 2,
            bg=COLORS["input_bg"], fg=COLORS["text"],
            highlightbackground=COLORS["input_border"], highlightthickness=1,
            padx=10, pady=6, relief=tk.FLAT,
        )
        tb.insert(tk.END, text or "")
        tb.configure(state=tk.DISABLED)
        return tb

    def _copy_value(self, text: str, label: str):
        self.top.clipboard_clear()
        self.top.clipboard_append(text or "")
        self.top.update_idletasks()


class RegisterWindow:
    def __init__(self, parent, app, task_index=None):
        self.task_index = task_index
        self.edit_mode = task_index is not None
        # tk.Toplevel avoids CTkToplevel titlebar withdraw/deiconify bugs on Windows
        # that leave the main window unresponsive after close + save.
        self.top = tk.Toplevel(parent)
        self.top.withdraw()
        self.top.title("신고 항목 수정" if self.edit_mode else "신고 항목 등록")
        self.top.configure(bg=COLORS["bg"])
        self.top.transient(parent)
        self.app = app

        _, screen_h = screen_size(parent)
        site_h = scaled_px(140, screen_h)
        search_h = scaled_px(100, screen_h)
        preview_h = scaled_px(110, screen_h)

        main = ui_frame(self.top, COLORS["bg"])
        main.pack(fill=tk.BOTH, expand=True)
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        ui_label(
            main,
            "신고 항목 수정" if self.edit_mode else "신고 항목 등록",
            "title",
            COLORS["text"],
        ).grid(row=0, column=0, sticky="w", padx=28, pady=(20, 12))

        content = ui_frame(main, COLORS["bg"])
        content.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 8))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=0, minsize=280)
        content.grid_columnconfigure(1, weight=1)

        left_card = ui_card(content)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left_inner = ui_frame(left_card, COLORS["card"])
        left_inner.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        ui_label(left_inner, "신고 원고", "body_bold", COLORS["text_muted"]).pack(
            anchor="w", pady=(0, 12),
        )
        self.template_var = tk.StringVar()
        self.tpl_buttons = {}
        self.tpl_frame = ui_frame(left_inner, COLORS["card"])
        self.tpl_frame.pack(fill=tk.X)
        self.tpl_frame.grid_columnconfigure(0, weight=1)
        self._build_template_buttons()

        scroll_host, scroll_body = make_scrollable(content)
        scroll_host.grid(row=0, column=1, sticky="nsew")

        card = ui_card(scroll_body)
        card.pack(fill=tk.X, expand=True)
        card_inner = ui_frame(card, COLORS["card"])
        card_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        card_inner.grid_columnconfigure(0, weight=1)

        self.dual_kind_report = False
        self.kind_report_row = ui_frame(card_inner, COLORS["card"])
        self.kind_report_row.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        if ctk:
            self.kind_report_btn = ctk.CTkButton(
                self.kind_report_row, text="종류신고", width=110, height=34,
                font=FONTS["body_bold"],
                fg_color=COLORS["input_bg"],
                hover_color=COLORS["border"],
                text_color=COLORS["text_muted"],
                border_color=COLORS["accent"],
                border_width=2,
                corner_radius=10,
                command=self._toggle_dual_kind_report,
            )
        else:
            self.kind_report_btn = tk.Button(
                self.kind_report_row, text="종류신고", width=12,
                font=FONTS["body_bold"],
                bg=COLORS["input_bg"], fg=COLORS["text_muted"],
                activebackground=COLORS["border"],
                relief=tk.GROOVE, bd=2,
                command=self._toggle_dual_kind_report,
            )
        self.kind_report_btn.pack(side=tk.LEFT)
        self.kind_report_hint = ui_label(
            self.kind_report_row,
            "OFF · 단일 등록  /  ON · 사이트마다 검색URL 자동+수동 2건",
            "caption",
            COLORS["text_light"],
        )
        self.kind_report_hint.pack(side=tk.LEFT, padx=(10, 0))
        if self.edit_mode:
            self.kind_report_row.grid_remove()

        ui_label(card_inner, "유형", "body_bold", COLORS["text_muted"]).grid(row=1, column=0, sticky="w", pady=(0, 6))
        self._preview_after_id = None
        if ctk:
            self.type_entry = ctk.CTkEntry(
                card_inner, height=42,
                font=FONTS["body"], fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"], corner_radius=10,
            )
        else:
            self.type_entry = tk.Entry(
                card_inner, font=FONTS["body"],
                bg=COLORS["input_bg"], fg=COLORS["text"],
                highlightbackground=COLORS["input_border"], highlightthickness=1,
            )
        self.type_entry.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.type_entry.bind("<Return>", lambda e: self.register())
        self.type_entry.bind("<KeyRelease>", self._schedule_url_preview)
        self.type_entry.bind("<FocusOut>", self._on_type_focus_out)

        reason_row = ui_frame(card_inner, COLORS["card"])
        reason_row.grid(row=3, column=0, sticky="w", pady=(0, 16))
        self.use_spam_category = False
        if ctk:
            self.spam_category_btn = ctk.CTkButton(
                reason_row, text="스팸성", width=96, height=34,
                font=FONTS["body_bold"],
                fg_color=COLORS["input_bg"],
                hover_color=COLORS["border"],
                text_color=COLORS["text_muted"],
                border_color=COLORS["accent"],
                border_width=2,
                corner_radius=10,
                command=self._toggle_spam_category,
            )
        else:
            self.spam_category_btn = tk.Button(
                reason_row, text="스팸성", width=10,
                font=FONTS["body_bold"],
                bg=COLORS["input_bg"], fg=COLORS["text_muted"],
                activebackground=COLORS["border"],
                relief=tk.GROOVE, bd=2,
                command=self._toggle_spam_category,
            )
        self.spam_category_btn.pack(side=tk.LEFT)
        self.spam_category_hint = ui_label(
            reason_row,
            "OFF · 불법성(기본)  /  ON · 스팸성",
            "caption",
            COLORS["text_light"],
        )
        self.spam_category_hint.pack(side=tk.LEFT, padx=(10, 0))

        ui_label(card_inner, "사이트 주소", "body_bold", COLORS["text_muted"]).grid(
            row=4, column=0, sticky="w", pady=(0, 4))
        ui_label(
            card_inner,
            "한 줄에 URL 하나 · Enter 줄바꿈 · Ctrl+Enter 등록",
            "caption",
            COLORS["text_light"],
        ).grid(row=5, column=0, sticky="w", pady=(0, 8))

        url_box = ui_frame(card_inner, COLORS["card"])
        url_box.grid(row=6, column=0, sticky="ew", pady=(0, 8), padx=16)
        url_box.grid_columnconfigure(0, weight=1)

        if ctk:
            self.site_text = ctk.CTkTextbox(
                url_box, wrap="char", font=FONTS["mono"],
                height=site_h, fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"], border_width=1, corner_radius=10,
                activate_scrollbars=True,
            )
        else:
            self.site_text = tk.Text(
                url_box, wrap=tk.CHAR, font=FONTS["mono"], height=8,
                bg=COLORS["input_bg"], fg=COLORS["text"],
                highlightbackground=COLORS["input_border"], highlightthickness=1,
                padx=12, pady=10, relief=tk.FLAT,
            )
        self.site_text.grid(row=0, column=0, sticky="nsew")

        search_header = ui_frame(card_inner, COLORS["card"])
        search_header.grid(row=7, column=0, sticky="ew", pady=(8, 4))
        search_header.grid_columnconfigure(0, weight=1)
        ui_label(search_header, "검색결과 URL", "body_bold", COLORS["text_muted"]).grid(
            row=0, column=0, sticky="w")
        self.search_url_auto = False
        if ctk:
            self.auto_search_btn = ctk.CTkButton(
                search_header, text="자동", width=84, height=34,
                font=FONTS["body_bold"],
                fg_color=COLORS["input_bg"],
                hover_color=COLORS["border"],
                text_color=COLORS["text_muted"],
                border_color=COLORS["warning"],
                border_width=2,
                corner_radius=10,
                command=self._toggle_search_auto,
            )
        else:
            self.auto_search_btn = tk.Button(
                search_header, text="자동", width=8,
                font=FONTS["body_bold"],
                bg=COLORS["input_bg"], fg=COLORS["text_muted"],
                activebackground=COLORS["border"],
                relief=tk.GROOVE, bd=2,
                command=self._toggle_search_auto,
            )
        self.auto_search_btn.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self.search_url_hint = ui_label(
            card_inner,
            "선택 · 줄 번호는 사이트 주소와 짝 · 미입력 시 사이트 주소가 검색결과 URL에 사용됨",
            "caption",
            COLORS["text_light"],
        )
        self.search_url_hint.grid(row=8, column=0, sticky="w", pady=(0, 8))

        search_box = ui_frame(card_inner, COLORS["card"])
        search_box.grid(row=9, column=0, sticky="ew", pady=(0, 8), padx=16)
        search_box.grid_columnconfigure(0, weight=1)

        if ctk:
            self.search_url_text = ctk.CTkTextbox(
                search_box, wrap="char", font=FONTS["mono"],
                height=search_h, fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"], border_width=1, corner_radius=10,
                activate_scrollbars=True,
            )
        else:
            self.search_url_text = tk.Text(
                search_box, wrap=tk.CHAR, font=FONTS["mono"], height=5,
                bg=COLORS["input_bg"], fg=COLORS["text"],
                highlightbackground=COLORS["input_border"], highlightthickness=1,
                padx=12, pady=10, relief=tk.FLAT,
            )
        self.search_url_text.grid(row=0, column=0, sticky="nsew")

        preview_header = ui_frame(card_inner, COLORS["card"])
        preview_header.grid(row=10, column=0, sticky="ew", pady=(4, 6))
        ui_label(preview_header, "등록 예정 URL", "body_bold", COLORS["text_muted"]).pack(side=tk.LEFT)
        self.url_count_label = ui_label(preview_header, "0개", "badge", COLORS["accent"])
        self.url_count_label.pack(side=tk.RIGHT)

        if ctk:
            self.url_preview = ctk.CTkTextbox(
                card_inner, wrap="char", font=FONTS["mono"], height=preview_h,
                fg_color=COLORS["accent_light"], text_color=COLORS["text"],
                border_color=COLORS["card_border"], border_width=1, corner_radius=10,
                activate_scrollbars=True, state="disabled",
            )
        else:
            self.url_preview = tk.Text(
                card_inner, wrap=tk.CHAR, font=FONTS["mono"], height=6,
                bg=COLORS["accent_light"], fg=COLORS["text"],
                highlightbackground=COLORS["card_border"], highlightthickness=1,
                padx=12, pady=10, relief=tk.FLAT, state=tk.DISABLED,
            )
        self.url_preview.grid(row=11, column=0, sticky="ew", pady=(0, 8), padx=16)

        btn_frame = ui_frame(main, COLORS["bg"])
        btn_frame.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 20))
        ui_button(btn_frame, "취소", "ghost", width=110, command=self.close).pack(side=tk.RIGHT, padx=(10, 0))
        save_label = "저장" if self.edit_mode else "등록"
        ui_button(btn_frame, save_label, "primary", width=110, command=self.register).pack(side=tk.RIGHT)

        self.site_text.bind("<KeyRelease>", lambda e: self._update_url_preview())
        self.site_text.bind("<Control-Return>", lambda e: self.register())
        self.search_url_text.bind("<KeyRelease>", lambda e: self._update_url_preview())
        self.search_url_text.bind("<Control-Return>", lambda e: self.register())
        if self.edit_mode:
            self._load_task(app.tasks[task_index])
        self._update_url_preview()
        self.top.resizable(True, True)
        self.app.setup_dialog(self.top, "register", 1180, 780, 920, 520, modal=False)
        self._closed = False
        self._focus_after_id = None
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.update_idletasks()
        self.top.deiconify()
        saved_geom = self.app.window_geometry.get("register")
        if saved_geom:
            apply_window_geometry(self.top, saved_geom)
        self.top.lift()
        self.top.focus_force()
        self.top.after(50, self._focus_type_entry)

    def _focus_type_entry(self):
        if self._closed:
            return
        try:
            self.type_entry.focus_set()
        except tk.TclError:
            pass

    def _cancel_pending_after(self):
        for after_id in (self._preview_after_id, self._focus_after_id):
            if after_id is None:
                continue
            try:
                self.top.after_cancel(after_id)
            except tk.TclError:
                pass
        self._preview_after_id = None
        self._focus_after_id = None

    def _save_window_geometry(self):
        geom = capture_window_geometry(self.top)
        if geom:
            self.app.window_geometry["register"] = geom
            self.app.save_window_geometry()

    def _finish_dialog(self, callback=None):
        if self._closed:
            return
        self._closed = True
        self._cancel_pending_after()
        self._save_window_geometry()
        try:
            self.top.destroy()
        except tk.TclError:
            pass

        def run_callback():
            try:
                if callback:
                    callback()
            except Exception as exc:
                self.app.log(f"등록 처리 오류: {exc}")
                try:
                    messagebox.showerror("등록 오류", f"항목 등록 중 오류가 발생했습니다.\n{exc}", parent=self.app.root)
                except tk.TclError:
                    pass
            self.app._clear_task_drag_ui()
            try:
                self.app.root.lift()
                self.app.root.focus_force()
                if hasattr(self.app, "task_tree"):
                    self.app.task_tree.focus_set()
            except tk.TclError:
                pass

        self.app.root.after_idle(run_callback)

    def close(self):
        self._finish_dialog()

    def _set_textbox(self, widget, text: str):
        if ctk and isinstance(widget, ctk.CTkTextbox):
            widget.delete("1.0", tk.END)
            widget.insert("1.0", text)
        else:
            widget.delete("1.0", tk.END)
            widget.insert(tk.END, text)

    def _get_type_text(self) -> str:
        if ctk and isinstance(self.type_entry, ctk.CTkEntry):
            return self.type_entry.get()
        return self.type_entry.get()

    def _set_type_text(self, text: str) -> None:
        if ctk and isinstance(self.type_entry, ctk.CTkEntry):
            self.type_entry.delete(0, tk.END)
            self.type_entry.insert(0, text)
        else:
            self.type_entry.delete(0, tk.END)
            self.type_entry.insert(0, text)

    def _schedule_url_preview(self, event=None):
        if self._preview_after_id is not None:
            self.top.after_cancel(self._preview_after_id)
        self._preview_after_id = self.top.after(150, self._deferred_url_preview)

    def _deferred_url_preview(self):
        self._preview_after_id = None
        if self._closed:
            return
        self._update_url_preview()

    def _on_type_focus_out(self, event=None):
        if self._preview_after_id is not None:
            try:
                self.top.after_cancel(self._preview_after_id)
            except tk.TclError:
                pass
            self._preview_after_id = None
        if self._focus_after_id is not None:
            try:
                self.top.after_cancel(self._focus_after_id)
            except tk.TclError:
                pass
        # IME 조합 완료 후 반영되도록 짧게 지연
        self._focus_after_id = self.top.after(80, self._deferred_focus_out_preview)

    def _deferred_focus_out_preview(self):
        self._focus_after_id = None
        if self._closed:
            return
        self._update_url_preview()

    def _toggle_search_auto(self):
        if self.dual_kind_report:
            return
        self.search_url_auto = not self.search_url_auto
        self._apply_search_auto_ui()
        self._update_url_preview()

    def _toggle_dual_kind_report(self):
        self.dual_kind_report = not self.dual_kind_report
        if self.dual_kind_report and self.search_url_auto:
            self.search_url_auto = False
            self._apply_search_auto_ui()
        self._apply_dual_kind_report_ui()
        self._update_url_preview()

    def _apply_dual_kind_report_ui(self):
        active = self.dual_kind_report
        if ctk and isinstance(self.kind_report_btn, ctk.CTkButton):
            self.kind_report_btn.configure(
                fg_color=COLORS["accent"] if active else COLORS["input_bg"],
                hover_color=COLORS["accent_hover"] if active else COLORS["border"],
                text_color="#ffffff" if active else COLORS["text_muted"],
                border_color=COLORS["accent_hover"] if active else COLORS["accent"],
                text="종류신고 ON" if active else "종류신고",
            )
        else:
            self.kind_report_btn.configure(
                bg=COLORS["accent"] if active else COLORS["input_bg"],
                fg="#ffffff" if active else COLORS["text_muted"],
                text="종류신고 ON" if active else "종류신고",
            )
        self.kind_report_hint.configure(
            text=(
                "ON · 유형·사이트 동일, 검색URL 자동+수동 각 1건씩 등록"
                if active
                else "OFF · 단일 등록  /  ON · 사이트마다 검색URL 자동+수동 2건"
            ),
        )
        if active:
            if self.search_url_auto:
                self.search_url_auto = False
                self._apply_search_auto_ui()
            self._set_auto_search_btn_enabled(False)
            self.search_url_hint.configure(
                text="종류신고: 아래 줄은 [수동] 검색URL · [자동]은 신고 시 유형으로 실시간 생성",
            )
            if ctk and isinstance(self.search_url_text, ctk.CTkTextbox):
                content = self._search_url_text_content()
                if content == SEARCH_URL_AUTO_PLACEHOLDER:
                    self._set_textbox(self.search_url_text, "")
            self._set_search_url_disabled(False)
        else:
            self._set_auto_search_btn_enabled(True)
            self._apply_search_auto_ui()

    def _set_auto_search_btn_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        if ctk and isinstance(self.auto_search_btn, ctk.CTkButton):
            self.auto_search_btn.configure(state=state)
        else:
            self.auto_search_btn.configure(state=state)

    def _toggle_spam_category(self):
        self.use_spam_category = not self.use_spam_category
        self._apply_spam_category_ui()

    def _apply_spam_category_ui(self):
        active = self.use_spam_category
        if ctk and isinstance(self.spam_category_btn, ctk.CTkButton):
            self.spam_category_btn.configure(
                fg_color=COLORS["accent"] if active else COLORS["input_bg"],
                hover_color=COLORS["accent_hover"] if active else COLORS["border"],
                text_color="#ffffff" if active else COLORS["text_muted"],
                border_color=COLORS["accent_hover"] if active else COLORS["accent"],
                text="스팸성 ON" if active else "스팸성",
            )
        else:
            self.spam_category_btn.configure(
                bg=COLORS["accent"] if active else COLORS["input_bg"],
                fg="#ffffff" if active else COLORS["text_muted"],
                text="스팸성 ON" if active else "스팸성",
            )
        self.spam_category_hint.configure(
            text="신고 시 스팸성 선택" if active else "OFF · 불법성(기본)  /  ON · 스팸성",
        )

    def _get_inquiry_category(self) -> str:
        return "spam" if self.use_spam_category else DEFAULT_INQUIRY_CATEGORY

    def _apply_search_auto_ui(self):
        if self.search_url_auto:
            if ctk and isinstance(self.auto_search_btn, ctk.CTkButton):
                self.auto_search_btn.configure(
                    fg_color=COLORS["warning"],
                    hover_color=COLORS["warning_hover"],
                    text_color="#ffffff",
                    border_color=COLORS["warning_hover"],
                    text="자동 ON",
                )
            else:
                self.auto_search_btn.configure(
                    bg=COLORS["warning"], fg="#ffffff", text="자동 ON",
                )
            self.search_url_hint.configure(
                text="신고할 때마다 유형으로 네이버 실시간 검색 → tqi·ackey 매번 새로 발급",
            )
            self._set_search_url_disabled(True)
        else:
            if ctk and isinstance(self.auto_search_btn, ctk.CTkButton):
                self.auto_search_btn.configure(
                    fg_color=COLORS["input_bg"],
                    hover_color=COLORS["border"],
                    text_color=COLORS["text_muted"],
                    border_color=COLORS["warning"],
                    text="자동",
                )
            else:
                self.auto_search_btn.configure(
                    bg=COLORS["input_bg"], fg=COLORS["text_muted"], text="자동",
                )
            self.search_url_hint.configure(
                text="선택 · 줄 번호는 사이트 주소와 짝 · 미입력 시 사이트 주소가 검색결과 URL에 사용됨",
            )
            self._set_search_url_disabled(False)

    def _set_search_url_disabled(self, disabled: bool):
        if disabled:
            self._set_textbox(self.search_url_text, SEARCH_URL_AUTO_PLACEHOLDER)
            if ctk and isinstance(self.search_url_text, ctk.CTkTextbox):
                self.search_url_text.configure(
                    state="disabled",
                    fg_color="#e2e8f0",
                    text_color=COLORS["text_muted"],
                )
            else:
                self.search_url_text.configure(
                    state=tk.DISABLED,
                    bg="#e2e8f0",
                    fg=COLORS["text_muted"],
                )
        else:
            if ctk and isinstance(self.search_url_text, ctk.CTkTextbox):
                self.search_url_text.configure(
                    state="normal",
                    fg_color=COLORS["input_bg"],
                    text_color=COLORS["text"],
                )
            else:
                self.search_url_text.configure(
                    state=tk.NORMAL,
                    bg=COLORS["input_bg"],
                    fg=COLORS["text"],
                )
            if self._search_url_text_content() == SEARCH_URL_AUTO_PLACEHOLDER:
                self._set_textbox(self.search_url_text, "")

    def _load_task(self, task: dict):
        self._set_type_text(task.get("report_type", ""))
        self.use_spam_category = task.get("inquiry_category", DEFAULT_INQUIRY_CATEGORY) == "spam"
        self._apply_spam_category_ui()
        self._set_textbox(self.site_text, task.get("site", ""))
        if task.get("search_url_auto"):
            self.search_url_auto = True
            self._apply_search_auto_ui()
        else:
            self.search_url_auto = False
            self._apply_search_auto_ui()
            if task.get("search_url_custom"):
                self._set_textbox(self.search_url_text, task.get("search_url", ""))
            else:
                self._set_textbox(self.search_url_text, "")
        tn = task.get("template_name", "")
        if tn:
            self.template_var.set(tn)
            self._build_template_buttons()
            self._on_tpl_select(tn)

    def _on_tpl_select(self, name):
        for n, btn in self.tpl_buttons.items():
            active = n == name
            if ctk:
                btn.configure(
                    fg_color=COLORS["accent"] if active else COLORS["input_bg"],
                    text_color="#ffffff" if active else COLORS["text"],
                    font=FONTS["body_bold"] if active else FONTS["body"],
                )
            else:
                btn.configure(
                    bg=COLORS["accent"] if active else COLORS["input_bg"],
                    fg="#ffffff" if active else COLORS["text"],
                    font=FONTS["body_bold"] if active else FONTS["body"],
                )

    def _build_template_buttons(self):
        for btn in self.tpl_buttons.values():
            btn.destroy()
        self.tpl_buttons.clear()

        options = self.app.get_template_options()
        if not options:
            return

        ids = [o[0] for o in options]
        if not self.template_var.get() or self.template_var.get() not in ids:
            self.template_var.set(ids[0])

        cols = 1
        for idx, (tid, title) in enumerate(options):
            row = idx
            col = 0
            active = tid == self.template_var.get()
            if ctk:
                btn = ctk.CTkButton(
                    self.tpl_frame, text=title, height=44,
                    font=FONTS["body_bold"] if active else FONTS["body"],
                    fg_color=COLORS["accent"] if active else COLORS["input_bg"],
                    hover_color=COLORS["accent_hover"] if active else COLORS["border"],
                    text_color="#ffffff" if active else COLORS["text"],
                    corner_radius=10,
                    anchor="w",
                    command=lambda n=tid: self._pick_template(n),
                )
            else:
                btn = tk.Button(
                    self.tpl_frame, text=title, height=2,
                    font=FONTS["body_bold"] if active else FONTS["body"],
                    bg=COLORS["accent"] if active else COLORS["input_bg"],
                    fg="#ffffff" if active else COLORS["text"],
                    relief=tk.FLAT, anchor="w", justify=tk.LEFT,
                    command=lambda n=tid: self._pick_template(n),
                )
            btn.grid(row=row, column=col, sticky="ew", pady=4)
            self.tpl_buttons[tid] = btn

    def _pick_template(self, name):
        self.template_var.set(name)
        self._on_tpl_select(name)

    def _parse_search_url_lines(self, *, ignore_auto: bool = False):
        if self.search_url_auto and not ignore_auto and not self.dual_kind_report:
            return []
        raw = self._search_url_text_content()
        if raw == SEARCH_URL_AUTO_PLACEHOLDER:
            return []
        urls = []
        for line in raw.splitlines():
            url = line.strip()
            if not url:
                urls.append("")
                continue
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            urls.append(url)
        return urls

    def _resolve_paired_sites(self):
        """(site, effective_search_url, search_url_custom, search_url_auto)."""
        sites = self._parse_site_lines()
        if not sites:
            return []

        if self.dual_kind_report and not self.edit_mode:
            kw = self._get_type_text().strip()
            preview_url = resolve_naver_search_url(kw, live=False) if kw else ""
            manual_pairs = self._parse_paired_sites(ignore_auto=True)
            resolved = []
            for site, search in manual_pairs:
                custom = bool(search)
                effective_manual = search if custom else site
                resolved.append((site, preview_url or site, True, True))
                resolved.append((site, effective_manual, custom, False))
            return resolved

        if self.search_url_auto:
            kw = self._get_type_text().strip()
            preview_url = resolve_naver_search_url(kw, live=False) if kw else ""
            return [(site, preview_url or site, True, True) for site in sites]

        raw_pairs = self._parse_paired_sites()
        resolved = []
        for site, search in raw_pairs:
            custom = bool(search)
            effective = search if custom else site
            resolved.append((site, effective, custom, False))
        return resolved

    def _parse_paired_sites(self, *, ignore_auto: bool = False):
        sites = self._parse_site_lines()
        search_lines = self._parse_search_url_lines(ignore_auto=ignore_auto)
        pairs = []
        for i, site in enumerate(sites):
            search = search_lines[i] if i < len(search_lines) else ""
            pairs.append((site, search))
        return pairs

    def _parse_site_lines(self):
        raw = self._site_text_content()
        sites = []
        for line in raw.splitlines():
            site = line.strip()
            if not site:
                continue
            if not site.startswith(("http://", "https://")):
                site = "https://" + site
            sites.append(site)
        return sites

    def _short_url(self, url, max_len=72):
        return url

    def _set_preview_text(self, text):
        if ctk and isinstance(self.url_preview, ctk.CTkTextbox):
            self.url_preview.configure(state="normal")
            self.url_preview.delete("1.0", tk.END)
            self.url_preview.insert("1.0", text)
            self.url_preview.configure(state="disabled")
        else:
            self.url_preview.configure(state=tk.NORMAL)
            self.url_preview.delete("1.0", tk.END)
            self.url_preview.insert(tk.END, text)
            self.url_preview.configure(state=tk.DISABLED)

    def _update_url_preview(self):
        pairs = self._resolve_paired_sites()
        count = len(pairs)
        if ctk and isinstance(self.url_count_label, ctk.CTkLabel):
            self.url_count_label.configure(
                text=f"{count}개",
                fg_color=COLORS["accent_light"] if count else COLORS["border"],
                text_color=COLORS["accent"] if count else COLORS["text_muted"],
            )
        else:
            self.url_count_label.configure(text=f"{count}개")

        if not pairs:
            self._set_preview_text("URL을 입력하면 여기에 번호와 함께 표시됩니다.")
            return

        lines = []
        for idx, (site, effective, custom, auto) in enumerate(pairs, 1):
            mode = "자동" if auto else "수동"
            lines.append(f"  {idx:02d}  [{mode}] 사이트: {self._short_url(site)}")
            if auto:
                lines.append("       검색: 신고 시 유형으로 실시간 생성 (tqi·ackey 매번 신규)")
            elif custom:
                lines.append(f"       검색: {self._short_url(effective)} (별도입력)")
            else:
                lines.append(f"       검색: {self._short_url(effective)} (사이트와 동일)")
        self._set_preview_text("\n".join(lines))

    def _site_text_content(self):
        if ctk and isinstance(self.site_text, ctk.CTkTextbox):
            return self.site_text.get("1.0", tk.END).strip()
        return self.site_text.get("1.0", tk.END).strip()

    def _search_url_text_content(self):
        if ctk and isinstance(self.search_url_text, ctk.CTkTextbox):
            return self.search_url_text.get("1.0", tk.END).strip()
        return self.search_url_text.get("1.0", tk.END).strip()

    def register(self):
        if self._closed:
            return

        report_type = self._get_type_text().strip()
        template_choice = self.template_var.get()

        if not report_type:
            messagebox.showwarning("입력 필요", "유형을 입력해주세요.", parent=self.top)
            return

        pairs = self._resolve_paired_sites()
        if not pairs:
            messagebox.showwarning("입력 필요", "사이트 주소를 입력해주세요.", parent=self.top)
            return

        template = self.app.get_template_text(template_choice)
        if not template:
            messagebox.showwarning("원본 없음", "해당 원본 신고 내용이 비어 있습니다.", parent=self.top)
            return

        if self.edit_mode:
            site, effective, custom, auto = pairs[0]
            idx = self.task_index
            category = self._get_inquiry_category()

            def apply_edit():
                self.app.update_task(
                    idx, site, report_type, template, template_choice,
                    search_url=effective, search_url_custom=custom, search_url_auto=auto,
                    inquiry_category=category,
                )
                self.app.log(f"신고 항목 수정: [{report_type}] {site}")

            self._finish_dialog(apply_edit)
            return

        category = self._get_inquiry_category()
        batch = list(pairs)
        site_count = len(self._parse_site_lines())
        dual_kind = self.dual_kind_report

        def apply_register():
            for site, effective, custom, auto in batch:
                self.app.add_task(
                    site, report_type, template, template_choice,
                    search_url=effective, search_url_custom=custom, search_url_auto=auto,
                    inquiry_category=category,
                    save=False,
                )
            self.app.save_tasks()
            self.app.refresh_task_list()
            if dual_kind:
                self.app.log(
                    f"종류신고 등록: 사이트 {site_count}개 → 항목 {len(batch)}개 (자동+수동)"
                )
            else:
                self.app.log(f"일괄 등록 완료: {len(batch)}개 URL")

        self._finish_dialog(apply_register)


class ReportApp:
    def __init__(self, root):
        self.root = root
        self.window_geometry = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    _boot = json.load(f)
                self.window_geometry = _boot.get("window_geometry", {}) or {}
            except Exception:
                pass

        self.root.title(f"Naver Report · v{APP_VERSION}")
        apply_main_window(
            self.root,
            geometry_store=self.window_geometry,
            save_callback=self.save_window_geometry,
        )
        if ctk:
            ctk.set_appearance_mode("light")
            ctk.set_default_color_theme("blue")
            self.root.configure(fg_color=COLORS["bg"])
        else:
            self.root.configure(bg=COLORS["bg"])

        configure_treeview("Task.Treeview")
        configure_treeview("Preview.Treeview")
        configure_treeview("Account.Treeview")
        configure_treeview("Template.Treeview")
        configure_treeview("Cafe.Treeview")
        configure_treeview("Blog.Treeview")

        self.hidden_results = {}
        self.tasks = []
        self.templates = []
        self._editing_template_id = None
        self._task_drag_state = None
        self._task_drag_indicator = None
        self._task_drag_ghost = None

        self.sidebar = SidebarNav(
            self.root,
            self.on_tab_change,
            app_version=APP_VERSION,
            nav_items=get_nav_items(is_admin_mode()),
        )
        self.admin_mode = is_admin_mode()

        self.content = ui_frame(self.root, COLORS["bg"])
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.page_header = PageHeader(self.content, app_version=APP_VERSION)

        self.pages_container = ui_frame(self.content, COLORS["bg"])
        self.pages_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        self.pages = {}
        for name, _display in get_nav_items(self.admin_mode):
            page = ui_frame(self.pages_container, COLORS["bg"])
            page.pack(fill=tk.BOTH, expand=True)
            self.pages[name] = page

        self.load_templates()
        self.build_home_tab(self.pages["웹사이트신고"])
        self.build_blog_tab(self.pages["블로그신고"])
        if self.admin_mode:
            self.build_cafe_tab(self.pages["카페신고"])
            self.build_cafe_collected_tab(self.pages["카페수집리스트"])
        self.build_templates_tab(self.pages["신고 원본"])
        self.build_results_tab(self.pages["리라이트 결과"])
        self.build_settings_tab(self.pages["Settings"])
        self.build_log_tab(self.pages["실행 로그"])

        for name, page in self.pages.items():
            if name != "웹사이트신고":
                page.pack_forget()

        self.tabs = self.sidebar  # compat: preview_all / start_report call self.tabs.select()

        self.accounts = []
        self.load_settings()
        self.load_accounts()
        self.load_results()
        self.load_tasks()
        self.load_cafe_keywords()
        self.load_cafe_results()
        self.load_cafe_collected()
        self.load_blog_urls()
        self.load_blog_results()
        self._report_running = False
        self._cafe_running = False
        self._blog_running = False
        self._preview_running = False
        self._website_stop_requested = False
        self._cafe_stop_requested = False
        self._blog_stop_requested = False
        self._website_reporter = None
        self._cafe_reporter = None
        self._blog_reporter = None
        self.page_header.set("웹사이트신고")

    def on_tab_change(self, name):
        for n, page in self.pages.items():
            if n == name:
                page.pack(fill=tk.BOTH, expand=True)
            else:
                page.pack_forget()
        self.page_header.set(name)
        if name == "리라이트 결과":
            self.refresh_results_tree()
            self.refresh_site_stats_panel()
        if name == "신고 원본":
            self.refresh_template_list()
        if name == "카페신고":
            self.refresh_cafe_keyword_list()
            self.refresh_cafe_results_tree()
        if name == "블로그신고":
            self.refresh_blog_url_list()
            self.refresh_blog_results_tree()
        if name == "카페수집리스트":
            self.refresh_cafe_collected_tree()

    def setup_dialog(
        self,
        window,
        key: str,
        preferred_w: int,
        preferred_h: int,
        min_w: int,
        min_h: int,
        *,
        modal: bool = False,
    ):
        setup_toplevel(
            window,
            key,
            preferred_w,
            preferred_h,
            min_w,
            min_h,
            parent=self.root,
            geometry_store=self.window_geometry,
            save_callback=self.save_window_geometry,
            modal=modal,
        )
        window.resizable(True, True)

    def save_window_geometry(self):
        if not hasattr(self, "api_key_var"):
            data = {}
            if os.path.exists(SETTINGS_FILE):
                try:
                    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            data["window_geometry"] = self.window_geometry
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return
        self.save_settings()

    def _frame(self, parent, bg=None):
        return ui_frame(parent, bg or COLORS["bg"])

    def _center_toplevel(
        self,
        window,
        width: int,
        height: int,
        key: str,
        min_w: int | None = None,
        min_h: int | None = None,
    ):
        self.setup_dialog(
            window,
            key,
            width,
            height,
            min_w or max(360, width - 120),
            min_h or max(280, height - 120),
        )

    def _card(self, parent):
        return ui_card(parent)

    def _section_label(self, parent, text, row=0, pady=(10, 5), badge_text=None):
        row_frame = self._frame(parent, COLORS["card"])
        if hasattr(parent, "grid"):
            row_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=pady)
        row_frame.grid_columnconfigure(0, weight=1)
        ui_label(row_frame, text, "heading", COLORS["text"]).pack(side=tk.LEFT)
        if badge_text is not None:
            if ctk:
                badge = ctk.CTkLabel(
                    row_frame, text=badge_text, font=FONTS["badge"],
                    fg_color=COLORS["accent_light"], text_color=COLORS["accent"],
                    corner_radius=8, padx=10, pady=4,
                )
            else:
                badge = tk.Label(
                    row_frame, text=badge_text, font=FONTS["badge"],
                    bg=COLORS["accent_light"], fg=COLORS["accent"], padx=8, pady=2,
                )
            badge.pack(side=tk.RIGHT)
        return row_frame

    # ===================== Home Tab =====================
    def build_home_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        bottom_card = self._card(parent)
        bottom_card.grid(row=0, column=0, sticky="nsew")
        bottom_card.grid_rowconfigure(1, weight=1)
        bottom_card.grid_columnconfigure(0, weight=1)

        header = self._frame(bottom_card, COLORS["card"])
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 10))
        ui_label(header, "등록된 신고 목록", "heading", COLORS["text"]).pack(side=tk.LEFT)
        ui_label(
            header,
            "드래그하여 순서 변경",
            "caption",
            COLORS["text_light"],
        ).pack(side=tk.LEFT, padx=(12, 0))
        if ctk:
            self.task_count_label = ctk.CTkLabel(
                header, text="0개", font=FONTS["badge"],
                fg_color=COLORS["accent_light"], text_color=COLORS["accent"],
                corner_radius=8, padx=12, pady=4,
            )
        else:
            self.task_count_label = tk.Label(
                header, text="0개", font=FONTS["badge"],
                bg=COLORS["accent_light"], fg=COLORS["accent"], padx=10, pady=2,
            )
        self.task_count_label.pack(side=tk.RIGHT)

        task_container = self._frame(bottom_card, COLORS["card"])
        task_container.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 14))
        task_container.grid_rowconfigure(0, weight=1)
        task_container.grid_columnconfigure(0, weight=1)
        self.task_tree = self._build_task_tree(task_container)

        btn_frame = self._frame(bottom_card, COLORS["card"])
        btn_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 12))

        ui_button(btn_frame, "+ 신고 항목 등록", "primary", height=44, command=self.open_register_window).pack(side=tk.LEFT, padx=(0, 8))
        ui_button(btn_frame, "선택 삭제", "danger", height=44, command=self.delete_selected_task).pack(side=tk.LEFT, padx=(0, 8))

        hagrid_frame = self._frame(btn_frame, COLORS["card"])
        hagrid_frame.pack(side=tk.LEFT, padx=(12, 0))
        self.hagrid_mode_var = tk.BooleanVar(value=False)
        if ctk:
            self.hagrid_toggle = ctk.CTkCheckBox(
                hagrid_frame, text="해그리드 모드 (브라우저 숨김)",
                variable=self.hagrid_mode_var, font=FONTS["body"],
                text_color=COLORS["text"], command=self._on_hagrid_toggle,
            )
        else:
            self.hagrid_toggle = tk.Checkbutton(
                hagrid_frame, text="해그리드 모드 (브라우저 숨김)",
                variable=self.hagrid_mode_var, font=FONTS["body"],
                bg=COLORS["card"], fg=COLORS["text"],
                activebackground=COLORS["card"], activeforeground=COLORS["text"],
                command=self._on_hagrid_toggle,
            )
        self.hagrid_toggle.pack(side=tk.LEFT)

        self.preview_btn = ui_button(btn_frame, "리라이트 미리보기", "warning", height=44, command=self.preview_all)
        self.preview_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.stop_report_btn = ui_button(btn_frame, "신고 정지", "danger", height=44, command=self.stop_website_report)
        self.stop_report_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.stop_report_btn.configure(state=tk.DISABLED)
        self.report_btn = ui_button(btn_frame, "신고 시작", "success", height=44, command=self.start_report)
        self.report_btn.pack(side=tk.RIGHT, padx=(8, 0))

        prog_frame = self._frame(bottom_card, COLORS["card"])
        prog_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 16))
        style = ttk.Style()
        style.configure("Modern.Horizontal.TProgressbar",
                        troughcolor=COLORS["border"], background=COLORS["accent"], thickness=8)
        self.progress = ttk.Progressbar(prog_frame, mode="determinate", maximum=100, style="Modern.Horizontal.TProgressbar")
        self.progress.pack(fill=tk.X)

    # ===================== Cafe Report Tab =====================
    def build_cafe_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        top_card = self._card(parent)
        top_card.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        top_card.grid_rowconfigure(2, weight=1)
        top_card.grid_columnconfigure(0, weight=1)

        self._section_label(top_card, "검색 키워드", row=0, pady=(16, 8))
        hint = self._frame(top_card, COLORS["card"])
        hint.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))
        ui_label(
            hint,
            "키워드로 통합검색(최대 3페이지) → cafe URL 전체 수집 후, "
            "검색 상위 노출 순서대로 계정마다 순차 신고합니다.",
            "small",
            COLORS["text_muted"],
        ).pack(anchor="w")

        kw_container = self._frame(top_card, COLORS["card"])
        kw_container.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        kw_container.grid_rowconfigure(0, weight=1)
        kw_container.grid_columnconfigure(0, weight=1)

        self.cafe_keyword_tree = ttk.Treeview(
            kw_container, columns=("keyword",), show="headings", style="Cafe.Treeview", height=5,
        )
        self.cafe_keyword_tree.heading("keyword", text="키워드")
        self.cafe_keyword_tree.column("keyword", width=400, anchor="w")
        self.cafe_keyword_tree.grid(row=0, column=0, sticky="nsew")
        kw_sb = ttk.Scrollbar(kw_container, orient=tk.VERTICAL, command=self.cafe_keyword_tree.yview)
        kw_sb.grid(row=0, column=1, sticky="ns")
        self.cafe_keyword_tree.configure(yscrollcommand=kw_sb.set)

        kw_btn = self._frame(top_card, COLORS["card"])
        kw_btn.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 16))
        ui_button(kw_btn, "+ 키워드 추가", "primary", height=40, command=self.add_cafe_keyword).pack(side=tk.LEFT, padx=(0, 8))
        ui_button(kw_btn, "선택 삭제", "danger", height=40, command=self.delete_cafe_keyword).pack(side=tk.LEFT)

        bottom_card = self._card(parent)
        bottom_card.grid(row=1, column=0, sticky="nsew")
        bottom_card.grid_rowconfigure(1, weight=1)
        bottom_card.grid_columnconfigure(0, weight=1)

        self._section_label(bottom_card, "카페 신고 결과", row=0, pady=(16, 10))

        res_container = self._frame(bottom_card, COLORS["card"])
        res_container.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 12))
        res_container.grid_rowconfigure(0, weight=1)
        res_container.grid_columnconfigure(0, weight=1)

        self.cafe_result_tree = ttk.Treeview(
            res_container,
            columns=("account", "keyword", "url", "status", "datetime"),
            show="headings",
            style="Cafe.Treeview",
            height=8,
        )
        for col, title, width in [
            ("account", "계정", 100),
            ("keyword", "키워드", 120),
            ("url", "게시물 URL", 320),
            ("status", "상태", 90),
            ("datetime", "일시", 130),
        ]:
            self.cafe_result_tree.heading(col, text=title)
            self.cafe_result_tree.column(col, width=width, anchor="w")
        self.cafe_result_tree.grid(row=0, column=0, sticky="nsew")
        res_sb = ttk.Scrollbar(res_container, orient=tk.VERTICAL, command=self.cafe_result_tree.yview)
        res_sb.grid(row=0, column=1, sticky="ns")
        self.cafe_result_tree.configure(yscrollcommand=res_sb.set)
        self.cafe_result_tree.bind("<Delete>", lambda e: self.delete_selected_cafe_result())

        cafe_btn_frame = self._frame(bottom_card, COLORS["card"])
        cafe_btn_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 12))
        if ctk:
            ctk.CTkCheckBox(
                cafe_btn_frame, text="해그리드 모드 (브라우저 숨김)",
                variable=self.hagrid_mode_var, font=FONTS["body"],
                text_color=COLORS["text"],
            ).pack(side=tk.LEFT, padx=(0, 12))
        else:
            tk.Checkbutton(
                cafe_btn_frame, text="해그리드 모드 (브라우저 숨김)",
                variable=self.hagrid_mode_var, font=FONTS["body"],
                bg=COLORS["card"], fg=COLORS["text"],
            ).pack(side=tk.LEFT, padx=(0, 12))
        self.cafe_report_btn = ui_button(
            cafe_btn_frame, "카페 신고 시작", "success", height=44, command=self.start_cafe_report,
        )
        self.cafe_report_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.cafe_stop_btn = ui_button(
            cafe_btn_frame, "신고 정지", "danger", height=44, command=self.stop_cafe_report,
        )
        self.cafe_stop_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.cafe_stop_btn.configure(state=tk.DISABLED)

        cafe_prog = self._frame(bottom_card, COLORS["card"])
        cafe_prog.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 16))
        self.cafe_progress = ttk.Progressbar(
            cafe_prog, mode="determinate", maximum=100, style="Modern.Horizontal.TProgressbar",
        )
        self.cafe_progress.pack(fill=tk.X)

    # ===================== Blog Report Tab =====================
    def build_blog_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        top_card = self._card(parent)
        top_card.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        top_card.grid_rowconfigure(2, weight=1)
        top_card.grid_columnconfigure(0, weight=1)

        self._section_label(top_card, "블로그 게시물 URL", row=0, pady=(16, 8))
        hint = self._frame(top_card, COLORS["card"])
        hint.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))
        ui_label(
            hint,
            "네이버 블로그 게시물 URL과 신고 사유를 등록합니다. "
            "한 계정으로 등록된 모든 URL을 순차 신고하며, "
            "이미 신고한 URL·계정 조합은 「이미 신고했습니다」로 표시됩니다.",
            "small",
            COLORS["text_muted"],
        ).pack(anchor="w")

        url_container = self._frame(top_card, COLORS["card"])
        url_container.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        url_container.grid_rowconfigure(0, weight=1)
        url_container.grid_columnconfigure(0, weight=1)

        self.blog_url_tree = ttk.Treeview(
            url_container, columns=("url", "reason"), show="headings", style="Blog.Treeview",
            height=5, selectmode="extended",
        )
        self.blog_url_tree.heading("url", text="블로그 URL")
        self.blog_url_tree.heading("reason", text="신고 사유")
        self.blog_url_tree.column("url", width=380, anchor="w")
        self.blog_url_tree.column("reason", width=260, anchor="w")
        self.blog_url_tree.grid(row=0, column=0, sticky="nsew")
        url_sb = ttk.Scrollbar(url_container, orient=tk.VERTICAL, command=self.blog_url_tree.yview)
        url_sb.grid(row=0, column=1, sticky="ns")
        self.blog_url_tree.configure(yscrollcommand=url_sb.set)
        self.blog_url_tree.bind("<Delete>", lambda e: self.delete_blog_url())

        url_btn = self._frame(top_card, COLORS["card"])
        url_btn.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 16))
        ui_button(url_btn, "+ URL 추가", "primary", height=40, command=self.add_blog_url).pack(side=tk.LEFT, padx=(0, 8))
        ui_button(url_btn, "선택 삭제", "danger", height=40, command=self.delete_blog_url).pack(side=tk.LEFT)

        bottom_card = self._card(parent)
        bottom_card.grid(row=1, column=0, sticky="nsew")
        bottom_card.grid_rowconfigure(1, weight=1)
        bottom_card.grid_columnconfigure(0, weight=1)

        self._section_label(bottom_card, "블로그 신고 결과", row=0, pady=(16, 10))

        res_container = self._frame(bottom_card, COLORS["card"])
        res_container.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 12))
        res_container.grid_rowconfigure(0, weight=1)
        res_container.grid_columnconfigure(0, weight=1)

        self.blog_result_tree = ttk.Treeview(
            res_container,
            columns=("account", "url", "reason", "status", "datetime"),
            show="headings",
            style="Blog.Treeview",
            height=8,
            selectmode="extended",
        )
        for col, title, width in [
            ("account", "계정", 100),
            ("url", "게시물 URL", 320),
            ("reason", "신고 사유", 180),
            ("status", "상태", 90),
            ("datetime", "일시", 130),
        ]:
            self.blog_result_tree.heading(col, text=title)
            self.blog_result_tree.column(col, width=width, anchor="w")
        self.blog_result_tree.grid(row=0, column=0, sticky="nsew")
        res_sb = ttk.Scrollbar(res_container, orient=tk.VERTICAL, command=self.blog_result_tree.yview)
        res_sb.grid(row=0, column=1, sticky="ns")
        self.blog_result_tree.configure(yscrollcommand=res_sb.set)
        self.blog_result_tree.bind("<Delete>", lambda e: self.delete_selected_blog_result())
        self.blog_result_tree.bind("<Double-1>", self.open_blog_result_detail)

        blog_btn_frame = self._frame(bottom_card, COLORS["card"])
        blog_btn_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 12))
        if ctk:
            ctk.CTkCheckBox(
                blog_btn_frame, text="해그리드 모드 (브라우저 숨김)",
                variable=self.hagrid_mode_var, font=FONTS["body"],
                text_color=COLORS["text"],
            ).pack(side=tk.LEFT, padx=(0, 12))
        else:
            tk.Checkbutton(
                blog_btn_frame, text="해그리드 모드 (브라우저 숨김)",
                variable=self.hagrid_mode_var, font=FONTS["body"],
                bg=COLORS["card"], fg=COLORS["text"],
            ).pack(side=tk.LEFT, padx=(0, 12))
        self.blog_report_btn = ui_button(
            blog_btn_frame, "블로그 신고 시작", "success", height=44, command=self.start_blog_report,
        )
        self.blog_report_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.blog_stop_btn = ui_button(
            blog_btn_frame, "신고 정지", "danger", height=44, command=self.stop_blog_report,
        )
        self.blog_stop_btn.pack(side=tk.RIGHT, padx=(8, 0))
        self.blog_stop_btn.configure(state=tk.DISABLED)

        blog_prog = self._frame(bottom_card, COLORS["card"])
        blog_prog.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 16))
        self.blog_progress = ttk.Progressbar(
            blog_prog, mode="determinate", maximum=100, style="Modern.Horizontal.TProgressbar",
        )
        self.blog_progress.pack(fill=tk.X)

    def build_cafe_collected_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        card = self._card(parent)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_rowconfigure(2, weight=1)
        card.grid_columnconfigure(0, weight=1)

        self._section_label(card, "카페 수집 목록", row=0, pady=(16, 8))
        hint = self._frame(card, COLORS["card"])
        hint.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))
        ui_label(
            hint,
            "카페 신고 실행 시 통합검색에서 수집된 게시물입니다. "
            "재수집 시 검색결과에서 빠진 게시물은 「사라짐」으로 표시됩니다.",
            "small",
            COLORS["text_muted"],
        ).pack(anchor="w")

        container = self._frame(card, COLORS["card"])
        container.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self.cafe_collected_tree = ttk.Treeview(
            container,
            columns=("datetime", "keyword", "title", "url", "rank", "status"),
            show="headings",
            style="Cafe.Treeview",
            height=16,
        )
        for col, title, width in [
            ("datetime", "수집일시", 130),
            ("keyword", "키워드", 100),
            ("title", "게시물 제목", 240),
            ("url", "URL", 220),
            ("rank", "순위", 45),
            ("status", "상태", 70),
        ]:
            self.cafe_collected_tree.heading(col, text=title)
            self.cafe_collected_tree.column(col, width=width, anchor="w")
        self.cafe_collected_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self.cafe_collected_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.cafe_collected_tree.configure(yscrollcommand=sb.set)
        self.cafe_collected_tree.tag_configure(
            "disappeared", background="#f1f5f9", foreground="#94a3b8",
        )

        btn_frame = self._frame(card, COLORS["card"])
        btn_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 16))
        ui_button(
            btn_frame, "목록 비우기", "danger", height=40, command=self.clear_cafe_collected,
        ).pack(side=tk.RIGHT)

    # ===================== Templates Tab =====================
    def build_templates_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=2)
        parent.grid_columnconfigure(0, weight=1)

        list_card = self._card(parent)
        list_card.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        list_card.grid_rowconfigure(1, weight=1)
        list_card.grid_columnconfigure(0, weight=1)

        self._section_label(list_card, "신고 원본 목록", row=0, pady=(16, 10))

        list_frame = self._frame(list_card, COLORS["card"])
        list_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 16))
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self.template_tree = ttk.Treeview(
            list_frame, columns=("title",), show="headings", style="Template.Treeview", height=6,
        )
        self.template_tree.heading("title", text="제목")
        self.template_tree.column("title", width=400, anchor="w")
        self.template_tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.template_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.template_tree.configure(yscrollcommand=sb.set)
        self.template_tree.bind("<<TreeviewSelect>>", self.on_template_select)

        edit_card = self._card(parent)
        edit_card.grid(row=1, column=0, sticky="nsew")
        edit_card.grid_rowconfigure(2, weight=1)
        edit_card.grid_columnconfigure(0, weight=1)

        self._section_label(edit_card, "원본 편집", row=0, pady=(16, 12))

        title_row = self._frame(edit_card, COLORS["card"])
        title_row.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
        title_row.grid_columnconfigure(1, weight=1)
        ui_label(title_row, "제목", "body_bold", COLORS["text_muted"]).grid(row=0, column=0, padx=(0, 12))
        self.tpl_title_var = tk.StringVar()
        if ctk:
            self.tpl_title_entry = ctk.CTkEntry(
                title_row, textvariable=self.tpl_title_var, height=40,
                font=FONTS["body"], fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"], corner_radius=10,
            )
        else:
            self.tpl_title_entry = tk.Entry(
                title_row, textvariable=self.tpl_title_var, font=FONTS["body"],
                bg=COLORS["input_bg"], fg=COLORS["text"],
                highlightbackground=COLORS["input_border"], highlightthickness=1,
            )
        self.tpl_title_entry.grid(row=0, column=1, sticky="ew")

        content_frame = self._frame(edit_card, COLORS["card"])
        content_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))
        content_frame.grid_rowconfigure(1, weight=1)
        content_frame.grid_columnconfigure(0, weight=1)
        ui_label(content_frame, "내용", "body_bold", COLORS["text_muted"]).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.tpl_content_text = self._text_area(content_frame, height=200)
        self.tpl_content_text.grid(row=1, column=0, sticky="nsew")

        btn_row = self._frame(edit_card, COLORS["card"])
        btn_row.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 16))
        ui_button(btn_row, "+ 새 원본", "primary", height=40, command=self.new_template).pack(side=tk.LEFT, padx=(0, 8))
        ui_button(btn_row, "저장", "success", height=40, command=self.save_current_template).pack(side=tk.LEFT, padx=(0, 8))
        ui_button(btn_row, "삭제", "danger", height=40, command=self.delete_selected_template).pack(side=tk.LEFT)

        self.refresh_template_list()

    def _text_area(self, parent, height=110):
        if ctk:
            return ctk.CTkTextbox(
                parent, wrap=tk.WORD, font=FONTS["body"],
                fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"], border_width=1,
                corner_radius=10, height=height, activate_scrollbars=True)
        return tk.Text(
            parent, wrap=tk.WORD, font=FONTS["body"],
            bg=COLORS["input_bg"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            highlightbackground=COLORS["input_border"],
            highlightcolor=COLORS["accent"],
            highlightthickness=1, relief=tk.FLAT,
            padx=10, pady=10, height=height // 18,
        )

    def _build_task_tree(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        tree = ttk.Treeview(
            parent, columns=("no", "report_type", "site", "template_name"),
            show="headings", style="Task.Treeview", selectmode="extended",
        )
        tree.heading("no", text="No.")
        tree.heading("report_type", text="유형")
        tree.heading("site", text="사이트")
        tree.heading("template_name", text="원고")
        tree.column("no", width=50, anchor="center")
        tree.column("report_type", width=100, anchor="center")
        tree.column("site", width=500, anchor="w")
        tree.column("template_name", width=200, anchor="center")
        tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=sb.set)
        tree.tag_configure("drag_source", background="#dbeafe")
        tree.tag_configure("drag_target", background="#e0f2fe")
        tree.tag_configure("drop_flash", background="#bbf7d0")
        tree.bind("<Delete>", lambda e: self.delete_selected_task())
        tree.bind("<Double-1>", lambda e: self.open_edit_task())
        tree.bind("<ButtonPress-1>", self._on_task_drag_press, add="+")
        tree.bind("<B1-Motion>", self._on_task_drag_motion, add="+")
        tree.bind("<ButtonRelease-1>", self._on_task_drag_release, add="+")
        tree.bind("<MouseWheel>", self._on_task_tree_mousewheel, add="+")
        return tree

    # ===================== Results Tab =====================
    def build_results_tab(self, parent):
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        search_card = self._card(parent)
        search_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        search_inner = self._frame(search_card, COLORS["card"])
        search_inner.pack(fill=tk.X, padx=20, pady=16)
        search_inner.grid_columnconfigure(1, weight=1)

        ui_label(search_inner, "검색", "body_bold", COLORS["text"]).grid(row=0, column=0, padx=(0, 12))
        self.search_var = tk.StringVar()
        if ctk:
            self.search_entry = ctk.CTkEntry(
                search_inner, textvariable=self.search_var, height=40,
                border_color=COLORS["input_border"], fg_color=COLORS["input_bg"],
                text_color=COLORS["text"], corner_radius=10, font=FONTS["body"],
            )
        else:
            self.search_entry = tk.Entry(
                search_inner, textvariable=self.search_var,
                bg=COLORS["input_bg"], fg=COLORS["text"],
                highlightbackground=COLORS["input_border"], highlightthickness=1,
            )
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        ui_button(search_inner, "검색", "primary", width=90, height=40, command=self.filter_results).grid(row=0, column=2, padx=(0, 8))
        ui_button(search_inner, "초기화", "ghost", width=90, height=40, command=self.clear_filter).grid(row=0, column=3)

        stats_card = self._card(parent)
        stats_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        stats_inner = self._frame(stats_card, COLORS["card"])
        stats_inner.pack(fill=tk.X, padx=20, pady=14)
        ui_label(stats_inner, "사이트별 신고 집계", "body_bold", COLORS["text"]).pack(anchor="w")
        ui_label(
            stats_inner,
            "보호조치 계정은 신고 횟수에서 제외됩니다.",
            "caption",
            COLORS["text_light"],
        ).pack(anchor="w", pady=(2, 8))
        if ctk:
            self.site_stats_text = ctk.CTkTextbox(
                stats_inner, wrap=tk.WORD, font=FONTS["mono"], height=88,
                fg_color=COLORS["accent_light"], text_color=COLORS["text"],
                border_color=COLORS["card_border"], border_width=1, corner_radius=10,
                activate_scrollbars=True, state="disabled",
            )
        else:
            self.site_stats_text = tk.Text(
                stats_inner, wrap=tk.WORD, font=FONTS["mono"], height=5,
                bg=COLORS["accent_light"], fg=COLORS["text"],
                highlightbackground=COLORS["card_border"], highlightthickness=1,
                padx=10, pady=8, relief=tk.FLAT, state=tk.DISABLED,
            )
        self.site_stats_text.pack(fill=tk.X)

        card = self._card(parent)
        card.grid(row=2, column=0, sticky="nsew")
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        self._section_label(card, "리라이트 결과", row=0, pady=(16, 10))
        self.results_tree = self._build_preview_tree(card, row=1)

    def _build_preview_tree(self, parent, row=1):
        frame = self._frame(parent, COLORS["card"])
        frame.grid(row=row, column=0, sticky="nsew", padx=20, pady=(0, 16))
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        tree = ttk.Treeview(
            frame,
            columns=("datetime", "account", "site", "search_mode", "report_type", "site_count", "original", "rewritten"),
            show="headings", style="Preview.Treeview", selectmode="extended",
        )
        tree.heading("datetime", text="생성 시간")
        tree.heading("account", text="사용 계정")
        tree.heading("site", text="사이트")
        tree.heading("search_mode", text="검색URL")
        tree.heading("report_type", text="유형")
        tree.heading("site_count", text="사이트 신고")
        tree.heading("original", text="원본 신고 내용")
        tree.heading("rewritten", text="리라이트 된 내용")
        tree.column("datetime", width=110, anchor="center")
        tree.column("account", width=90, anchor="center")
        tree.column("site", width=150, anchor="w")
        tree.column("search_mode", width=72, anchor="center")
        tree.column("report_type", width=70, anchor="center")
        tree.column("site_count", width=80, anchor="center")
        tree.column("original", width=220, anchor="w")
        tree.column("rewritten", width=220, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=sb.set)

        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        tree.configure(xscrollcommand=hsb.set)

        del_btn = ui_button(frame, "선택 항목 삭제", "danger", height=38, command=self.delete_selected_result)
        del_btn.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        tree.bind("<Double-1>", lambda e: self.open_preview_detail())
        tree.bind("<Delete>", lambda e: self.delete_selected_result())
        tree.tag_configure("protected", background="#d1d5db", foreground="#6b7280")
        return tree

    # ===================== Settings Tab =====================
    def build_settings_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        api_card = self._card(parent)
        api_card.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        api_card.grid_columnconfigure(0, weight=1)

        self._section_label(api_card, "OpenAI API 설정", row=0, pady=(15, 12))

        api_frame = self._frame(api_card, COLORS["card"])
        api_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 15))
        api_frame.grid_columnconfigure(0, weight=1)

        if ctk:
            ctk.CTkLabel(api_frame, text="API Key", font=("맑은 고딕", 10, "bold"),
                         text_color=COLORS["text_muted"]).grid(row=0, column=0, sticky="w")
        else:
            tk.Label(api_frame, text="API Key", font=("맑은 고딕", 10, "bold"),
                     bg=COLORS["card"], fg=COLORS["text_muted"]).grid(row=0, column=0, sticky="w")

        inner = self._frame(api_frame, COLORS["card"])
        inner.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        inner.grid_columnconfigure(0, weight=1)

        self.api_key_var = tk.StringVar()
        if ctk:
            self.api_key_entry = ctk.CTkEntry(inner, textvariable=self.api_key_var, height=36,
                                              border_color=COLORS["input_border"],
                                              fg_color=COLORS["input_bg"],
                                              text_color=COLORS["text"], show="*")
            self.api_key_entry.grid(row=0, column=0, sticky="ew")
            self.api_key_entry.bind("<FocusOut>", lambda e: self.save_settings())
            self.show_api_btn = ui_button(inner, "표시", "ghost", width=72, height=40, command=self.toggle_api_visibility)
        else:
            self.api_key_entry = tk.Entry(inner, textvariable=self.api_key_var, show="*",
                                          bg=COLORS["input_bg"], fg=COLORS["text"],
                                          insertbackground=COLORS["text"],
                                          highlightbackground=COLORS["input_border"],
                                          highlightthickness=1)
            self.api_key_entry.grid(row=0, column=0, sticky="ew", ipady=5)
            self.api_key_entry.bind("<FocusOut>", lambda e: self.save_settings())
            self.show_api_btn = tk.Button(inner, text="표시", width=8,
                                          bg="#e2e8f0", fg=COLORS["text"],
                                          activebackground="#cbd5e1",
                                          command=self.toggle_api_visibility)
        self.show_api_btn.grid(row=0, column=1, padx=(8, 0))

        if ctk:
            ctk.CTkLabel(api_frame, text="GPT 모델", font=("맑은 고딕", 10, "bold"),
                         text_color=COLORS["text_muted"]).grid(row=2, column=0, sticky="w", pady=(15, 5))
            self.model_var = tk.StringVar(value="gpt-4o")
            self.model_combo = ctk.CTkComboBox(api_frame, values=["gpt-4o"],
                                                variable=self.model_var, height=36,
                                                border_color=COLORS["input_border"],
                                                fg_color=COLORS["input_bg"],
                                                text_color=COLORS["text"],
                                                button_color=COLORS["accent"],
                                                button_hover_color=COLORS["accent_hover"],
                                                dropdown_fg_color=COLORS["card"],
                                                dropdown_text_color=COLORS["text"])
            self.model_combo.grid(row=3, column=0, sticky="ew", pady=(0, 15))
        else:
            tk.Label(api_frame, text="GPT 모델", font=("맑은 고딕", 10, "bold"),
                     bg=COLORS["card"], fg=COLORS["text_muted"]).grid(row=2, column=0, sticky="w", pady=(15, 5))
            self.model_var = tk.StringVar(value="gpt-4o")
            self.model_combo = ttk.Combobox(api_frame, textvariable=self.model_var,
                                            values=["gpt-4o"],
                                            state="readonly")
            self.model_combo.grid(row=3, column=0, sticky="ew", pady=(0, 15))

        account_card = self._card(parent)
        account_card.grid(row=1, column=0, sticky="nsew")
        account_card.grid_rowconfigure(1, weight=1)
        account_card.grid_columnconfigure(0, weight=1)

        self._section_label(account_card, "네이버 계정 관리", row=0, pady=(15, 12))

        tree_frame = self._frame(account_card, COLORS["card"])
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 14))
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        self.account_tree = ttk.Treeview(
            tree_frame, columns=("id", "password"),
            show="headings", style="Account.Treeview", selectmode="extended",
        )
        self.account_tree.heading("id", text="아이디")
        self.account_tree.heading("password", text="비밀번호")
        self.account_tree.column("id", width=150, anchor="center")
        self.account_tree.column("password", width=220, anchor="w")
        self.account_tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.account_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.account_tree.configure(yscrollcommand=sb.set)
        self.account_tree.bind("<Delete>", lambda e: self.delete_selected_account())
        self.account_tree.bind("<Double-1>", self._on_account_tree_double_click)
        self.account_tree.bind("<Button-1>", self._on_account_tree_click, add="+")
        self._account_cell_entry = None

        bulk_frame = self._frame(account_card, COLORS["card"])
        bulk_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 10))
        bulk_frame.grid_columnconfigure(0, weight=1)
        bulk_frame.grid_columnconfigure(1, weight=1)
        ui_label(
            bulk_frame,
            "계정 일괄 등록 — 줄 순서대로 아이디·비밀번호가 짝을 이룹니다",
            "body_bold",
            COLORS["text_muted"],
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ui_label(bulk_frame, "아이디 (한 줄에 하나)", "caption", COLORS["text_light"]).grid(
            row=1, column=0, sticky="w", padx=(0, 8))
        ui_label(bulk_frame, "비밀번호 (한 줄에 하나)", "caption", COLORS["text_light"]).grid(
            row=1, column=1, sticky="w")

        self.bulk_id_text = self._text_area(bulk_frame, height=100)
        self.bulk_id_text.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=(4, 0))
        self.bulk_pw_text = self._text_area(bulk_frame, height=100)
        self.bulk_pw_text.grid(row=2, column=1, sticky="nsew", pady=(4, 0))

        add_frame = self._frame(account_card, COLORS["card"])
        add_frame.grid(row=3, column=0, sticky="ew", padx=15, pady=(0, 12))
        add_frame.grid_columnconfigure((0, 1), weight=1)

        ui_button(add_frame, "일괄 등록", "primary", height=38, command=self.add_accounts_bulk).grid(
            row=0, column=0, sticky="ew", padx=(0, 8))
        ui_button(add_frame, "선택 삭제", "danger", height=38, command=self.delete_selected_account).grid(
            row=0, column=1, sticky="ew")

    # ===================== Log Tab =====================
    _LOG_CHANNEL_LABELS = {
        "general": "공통",
        "website": "웹사이트",
        "blog": "블로그",
        "cafe": "카페",
    }

    def _make_log_textbox(self, parent, *, pack_fill: bool = True):
        if ctk:
            box = ctk.CTkTextbox(
                parent,
                wrap=tk.WORD,
                font=FONTS["log"],
                fg_color=COLORS["log_bg"],
                text_color=COLORS["log_fg"],
                border_color=COLORS["log_border"],
                border_width=2,
                corner_radius=8,
                state=tk.DISABLED,
                activate_scrollbars=True,
            )
        else:
            box = tk.Text(
                parent,
                wrap=tk.WORD,
                font=FONTS["log"],
                bg=COLORS["log_bg"],
                fg=COLORS["log_fg"],
                insertbackground=COLORS["log_fg"],
                selectbackground=COLORS["table_selected"],
                relief=tk.SOLID,
                bd=2,
                highlightbackground=COLORS["log_border"],
                highlightthickness=1,
                padx=10,
                pady=8,
                spacing1=2,
                spacing3=2,
                state=tk.DISABLED,
            )
        if pack_fill:
            box.pack(fill=tk.BOTH, expand=True)
        return box

    def _set_log_widget_text(self, widget, text: str):
        widget.configure(state=tk.NORMAL)
        if ctk and isinstance(widget, ctk.CTkTextbox):
            widget.delete("1.0", tk.END)
            widget.insert("1.0", text)
        else:
            widget.delete("1.0", tk.END)
            widget.insert(tk.END, text)
        widget.configure(state=tk.DISABLED)
        widget.see(tk.END)

    def _append_log_widget(self, widget, line: str):
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, f"{line}\n")
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def build_log_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        card = self._card(parent)
        card.pack(fill=tk.BOTH, expand=True)
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        header = self._frame(card, COLORS["card"])
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        ui_label(header, "실행 로그", "subheading", COLORS["text"]).pack(side=tk.LEFT)
        self.log_layout_hint = ui_label(header, "", "caption", COLORS["text_muted"])
        self.log_layout_hint.pack(side=tk.LEFT, padx=(12, 0))

        self.log_body = self._frame(card, COLORS["card"])
        self.log_body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.log_body.grid_rowconfigure(0, weight=1)
        self.log_body.grid_columnconfigure(0, weight=1)

        self._log_buffers = {c: [] for c in ("general", "website", "blog", "cafe")}
        self._log_all_lines: list[tuple[str, str]] = []
        self._log_active_channels: set[str] = set()
        self._log_widgets: dict[str, object] = {}
        self._log_split_visible = False

        self.log_single_frame = self._frame(self.log_body, COLORS["card"])
        self.log_single_frame.grid(row=0, column=0, sticky="nsew")
        self._log_widgets["single"] = self._make_log_textbox(self.log_single_frame)

        self.log_split_frame = self._frame(self.log_body, COLORS["card"])
        self.log_split_frame.grid(row=0, column=0, sticky="nsew")
        self.log_split_frame.grid_rowconfigure(1, weight=1)
        self.log_split_frame.grid_columnconfigure(0, weight=1)

        general_wrap = self._frame(self.log_split_frame, COLORS["card"])
        general_wrap.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        general_wrap.grid_columnconfigure(0, weight=1)
        ui_label(general_wrap, "공통", "log_bold", COLORS["log_muted"]).grid(row=0, column=0, sticky="w")
        general_box = self._frame(general_wrap, COLORS["card"])
        general_box.grid(row=1, column=0, sticky="ew")
        if ctk:
            self._log_widgets["general"] = ctk.CTkTextbox(
                general_box, wrap=tk.WORD, font=FONTS["log"], height=140,
                fg_color=COLORS["log_bg"], text_color=COLORS["log_fg"],
                border_color=COLORS["log_border"], border_width=2, corner_radius=8,
                state=tk.DISABLED, activate_scrollbars=True,
            )
            self._log_widgets["general"].pack(fill=tk.X)
        else:
            self._log_widgets["general"] = tk.Text(
                general_box, wrap=tk.WORD, font=FONTS["log"], height=6,
                bg=COLORS["log_bg"], fg=COLORS["log_fg"],
                relief=tk.SOLID, bd=2, state=tk.DISABLED,
            )
            self._log_widgets["general"].pack(fill=tk.X)

        self.log_split_channels = self._frame(self.log_split_frame, COLORS["card"])
        self.log_split_channels.grid(row=1, column=0, sticky="nsew")
        for col in range(3):
            self.log_split_channels.grid_columnconfigure(col, weight=1)
            self.log_split_channels.grid_rowconfigure(0, weight=1)

        self._log_channel_cols: dict[str, tk.Frame] = {}
        for col, (ch, title) in enumerate([
            ("website", "웹사이트 신고"),
            ("blog", "블로그 신고"),
            ("cafe", "카페 신고"),
        ]):
            col_frame = self._frame(self.log_split_channels, COLORS["card"])
            col_frame.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0))
            ui_label(col_frame, title, "log_bold", COLORS["accent"]).pack(anchor="w", pady=(0, 6))
            self._log_widgets[ch] = self._make_log_textbox(col_frame)
            self._log_channel_cols[ch] = col_frame

        self.log_split_frame.grid_remove()

    def _register_log_channel(self, channel: str):
        if channel not in self._log_buffers:
            return
        self._log_active_channels.add(channel)
        self._refresh_log_layout()
        if len(self._log_active_channels) >= 2 and hasattr(self, "tabs"):
            self.tabs.select("실행 로그")

    def _unregister_log_channel(self, channel: str):
        self._log_active_channels.discard(channel)
        self._refresh_log_layout()

    def _refresh_log_layout(self):
        if not hasattr(self, "log_single_frame"):
            return
        use_split = len(self._log_active_channels) >= 2
        self._log_split_visible = use_split

        if use_split:
            self.log_single_frame.grid_remove()
            self.log_split_frame.grid()
            active = [c for c in ("website", "blog", "cafe") if c in self._log_active_channels]
            labels = " · ".join(self._LOG_CHANNEL_LABELS.get(c, c) for c in active)
            self.log_layout_hint.configure(text=f"분할 표시 — {labels}")
            col_map = {ch: i for i, ch in enumerate(active)}
            for ch, col_frame in self._log_channel_cols.items():
                if ch in col_map:
                    col_frame.grid(
                        row=0,
                        column=col_map[ch],
                        sticky="nsew",
                        padx=(0 if col_map[ch] == 0 else 6, 0),
                    )
                    self._rebuild_channel_log(ch)
                else:
                    col_frame.grid_remove()
            for col in range(len(active), 3):
                self.log_split_channels.grid_columnconfigure(col, weight=0)
            for col in range(len(active)):
                self.log_split_channels.grid_columnconfigure(col, weight=1)
            self._rebuild_channel_log("general")
        else:
            self.log_split_frame.grid_remove()
            self.log_single_frame.grid()
            if self._log_active_channels:
                only = next(iter(self._log_active_channels))
                self.log_layout_hint.configure(
                    text=f"{self._LOG_CHANNEL_LABELS.get(only, only)} 진행 중"
                )
            else:
                self.log_layout_hint.configure(text="")
            self._rebuild_channel_log("single")

    def _rebuild_channel_log(self, channel: str):
        widget = self._log_widgets.get(channel)
        if widget is None:
            return
        if channel == "single":
            lines = []
            for ch, msg in self._log_all_lines:
                if ch == "general" or len(self._log_active_channels) <= 1:
                    lines.append(msg)
                else:
                    tag = self._LOG_CHANNEL_LABELS.get(ch, ch)
                    lines.append(f"[{tag}] {msg}")
            self._set_log_widget_text(widget, "\n".join(lines))
            return
        if channel == "general":
            self._set_log_widget_text(widget, "\n".join(self._log_buffers["general"]))
            return
        self._set_log_widget_text(widget, "\n".join(self._log_buffers.get(channel, [])))

    def _append_log_ui(self, message: str, channel: str):
        if self._log_split_visible:
            if channel == "general":
                self._append_log_widget(self._log_widgets["general"], message)
            elif channel in self._log_active_channels:
                self._append_log_widget(self._log_widgets[channel], message)
            return
        if channel == "general" or channel in self._log_active_channels or not self._log_active_channels:
            self._append_log_widget(self._log_widgets["single"], message)
        else:
            tag = self._LOG_CHANNEL_LABELS.get(channel, channel)
            self._append_log_widget(self._log_widgets["single"], f"[{tag}] {message}")

    # ===================== Logic =====================
    def text_of(self, widget):
        return widget.get("1.0", tk.END)

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.api_key_var.set(data.get("api_key", ""))
                self.model_var.set(data.get("model", "gpt-4o"))
                if hasattr(self, "hagrid_mode_var"):
                    self.hagrid_mode_var.set(data.get("hagrid_mode", False))
                saved_geom = data.get("window_geometry")
                if isinstance(saved_geom, dict):
                    self.window_geometry = saved_geom
            except Exception:
                pass

    def save_settings(self):
        data = {
            "api_key": self.api_key_var.get().strip(),
            "model": self.model_var.get(),
            "hagrid_mode": bool(self.hagrid_mode_var.get()) if hasattr(self, "hagrid_mode_var") else False,
            "window_geometry": getattr(self, "window_geometry", {}),
        }
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _on_hagrid_toggle(self):
        self.save_settings()
        mode = "ON" if self.hagrid_mode_var.get() else "OFF"
        self.log(f"해그리드 모드 {mode}")

    def load_accounts(self):
        if os.path.exists(ACCOUNTS_FILE):
            try:
                with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    self.accounts = json.load(f)
            except Exception:
                self.accounts = []
        self.refresh_account_list()

    def save_accounts(self):
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.accounts, f, ensure_ascii=False, indent=2)

    def load_results(self):
        if os.path.exists(RESULTS_FILE):
            try:
                with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, value in data.items():
                    self.hidden_results[key] = {
                        "site": value.get("site", ""),
                        "report_type": value.get("report_type", ""),
                        "account_id": value.get("account_id", ""),
                        "account_password": value.get("account_password", ""),
                        "original": value.get("original", ""),
                        "rewritten": value.get("rewritten", ""),
                        "datetime": value.get("datetime", ""),
                        "status": value.get("status", ""),
                        "search_url": value.get("search_url", ""),
                        "search_url_custom": value.get("search_url_custom", False),
                        "search_url_auto": value.get("search_url_auto", False),
                    }
            except Exception:
                self.hidden_results = {}

    def save_results(self):
        data = {}
        for key, value in self.hidden_results.items():
            data[key] = {
                "site": value["site"],
                "report_type": value["report_type"],
                "account_id": value.get("account_id", ""),
                "account_password": value.get("account_password", ""),
                "original": value["original"],
                "rewritten": value["rewritten"],
                "datetime": value.get("datetime", ""),
                "status": value.get("status", ""),
                "search_url": value.get("search_url", ""),
                "search_url_custom": value.get("search_url_custom", False),
                "search_url_auto": value.get("search_url_auto", False),
            }
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_tasks(self):
        if os.path.exists(TASKS_FILE):
            try:
                with open(TASKS_FILE, "r", encoding="utf-8") as f:
                    self.tasks = json.load(f)
            except Exception:
                self.tasks = []
        for task in self.tasks:
            site = task.get("site", "")
            if "search_url_custom" not in task:
                stored = (task.get("search_url") or "").strip()
                if stored and stored != site:
                    task["search_url_custom"] = True
                    task["search_url"] = stored
                else:
                    task["search_url_custom"] = False
                    task["search_url"] = site
            elif not (task.get("search_url") or "").strip():
                task["search_url"] = site
            if "inquiry_category" not in task:
                task["inquiry_category"] = DEFAULT_INQUIRY_CATEGORY
        self.refresh_task_list()

    def save_tasks(self):
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.tasks, f, ensure_ascii=False, indent=2)

    def load_cafe_keywords(self):
        self.cafe_keywords = []
        if os.path.exists(CAFE_KEYWORDS_FILE):
            try:
                with open(CAFE_KEYWORDS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.cafe_keywords = [str(k).strip() for k in data if str(k).strip()]
            except Exception:
                self.cafe_keywords = []
        self.refresh_cafe_keyword_list()

    def save_cafe_keywords(self):
        with open(CAFE_KEYWORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cafe_keywords, f, ensure_ascii=False, indent=2)

    def load_cafe_results(self):
        self.cafe_results = []
        if os.path.exists(CAFE_RESULTS_FILE):
            try:
                with open(CAFE_RESULTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.cafe_results = data
            except Exception:
                self.cafe_results = []

    def save_cafe_results(self):
        with open(CAFE_RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cafe_results, f, ensure_ascii=False, indent=2)

    def load_blog_urls(self):
        self.blog_urls = []
        if os.path.exists(BLOG_URLS_FILE):
            try:
                with open(BLOG_URLS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("url"):
                            self.blog_urls.append({
                                "url": self._normalize_blog_url(item["url"]),
                                "reason_id": str(item.get("reason_id", "3")),
                            })
                        elif isinstance(item, str) and item.strip():
                            self.blog_urls.append({
                                "url": self._normalize_blog_url(item),
                                "reason_id": "3",
                            })
            except Exception:
                self.blog_urls = []
        self.refresh_blog_url_list()

    def save_blog_urls(self):
        with open(BLOG_URLS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.blog_urls, f, ensure_ascii=False, indent=2)

    def load_blog_results(self):
        self.blog_results = []
        if os.path.exists(BLOG_RESULTS_FILE):
            try:
                with open(BLOG_RESULTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.blog_results = data
            except Exception:
                self.blog_results = []

    def save_blog_results(self):
        with open(BLOG_RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.blog_results, f, ensure_ascii=False, indent=2)

    def _normalize_blog_url(self, url: str) -> str:
        url = (url or "").strip()
        m = re.search(
            r"blog\.naver\.com/(?:([^/?#]+)/(\d+)|PostView\.naver\?[^#]*?blogId=([^&]+)[^#]*?logNo=(\d+))",
            url,
            re.IGNORECASE,
        )
        if not m:
            return url
        if m.group(1) and m.group(2):
            return f"https://blog.naver.com/{m.group(1)}/{m.group(2)}"
        return f"https://blog.naver.com/{m.group(3)}/{m.group(4)}"

    def _is_valid_blog_url(self, url: str) -> bool:
        return bool(re.search(r"blog\.naver\.com/", self._normalize_blog_url(url), re.IGNORECASE))

    def _blog_entry_url(self, entry) -> str:
        if isinstance(entry, dict):
            return entry.get("url", "")
        return str(entry or "")

    def refresh_blog_url_list(self):
        if not hasattr(self, "blog_url_tree"):
            return
        for item in self.blog_url_tree.get_children():
            self.blog_url_tree.delete(item)
        for entry in self.blog_urls:
            url = self._blog_entry_url(entry)
            reason_id = str(entry.get("reason_id", "3")) if isinstance(entry, dict) else "3"
            reason = BLOG_REPORT_REASONS.get(reason_id, reason_id)
            self.blog_url_tree.insert("", tk.END, values=(url, reason))

    def refresh_blog_results_tree(self):
        if not hasattr(self, "blog_result_tree"):
            return
        for item in self.blog_result_tree.get_children():
            self.blog_result_tree.delete(item)
        status_labels = {
            "ok": "완료",
            "already_reported": "이미신고",
            "previously_reported": "이미 신고했습니다",
            "protected": "보호조치",
            "login_failed": "로그인실패",
            "stopped": "중단",
            "failed": "실패",
        }
        for row in reversed(self.blog_results):
            st = row.get("status", "")
            label = status_labels.get(st, st or "-")
            popup = (row.get("popup_message") or "").strip()
            if popup and st in ("ok", "already_reported", "failed"):
                label = f"{label} · {self._truncate(popup, 36)}"
            restriction = (row.get("restriction_reason") or "").strip()
            if restriction and st in ("protected", "login_failed"):
                label = f"{label} · {self._truncate(restriction, 36)}"
            self.blog_result_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("account_id", ""),
                    self._truncate(row.get("url", ""), 80),
                    self._truncate(row.get("reason", ""), 40),
                    label,
                    row.get("datetime", ""),
                ),
                tags=(
                    row.get("account_id", ""),
                    row.get("url", ""),
                    row.get("datetime", ""),
                ),
            )

    def add_blog_url(self):
        dialog = ctk.CTkToplevel(self.root) if ctk else tk.Toplevel(self.root)
        dialog.title("블로그 URL 추가")
        dialog.transient(self.root)
        if ctk:
            dialog.configure(fg_color=COLORS["bg"])
        else:
            dialog.configure(bg=COLORS["bg"])

        def close():
            release_modal_grab(dialog, self.root)
            dialog.destroy()

        container = self._frame(dialog, COLORS["bg"])
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_rowconfigure(1, weight=1)
        container.grid_columnconfigure(0, weight=1)

        header = self._frame(container, COLORS["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 0))
        ui_label(header, "블로그 게시물 URL", "body_bold", COLORS["text"]).pack(anchor="w")
        url_var = tk.StringVar()
        if ctk:
            entry = ctk.CTkEntry(
                header, textvariable=url_var, height=38,
                fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"],
            )
        else:
            entry = tk.Entry(header, textvariable=url_var, font=FONTS["body"])
        entry.pack(fill=tk.X, pady=(8, 0))

        scroll_host, scroll_body = make_scrollable(container)
        scroll_host.grid(row=1, column=0, sticky="nsew", padx=20, pady=(12, 8))

        ui_label(scroll_body, "사유선택", "body_bold", COLORS["text"]).pack(anchor="w", pady=(0, 8))

        reason_box = ui_card(scroll_body)
        reason_box.pack(fill=tk.X, expand=True)

        reason_var = tk.StringVar(value="3")
        for rid, label in BLOG_REPORT_REASONS.items():
            row = self._frame(reason_box, COLORS["card"])
            row.pack(fill=tk.X, padx=12, pady=6)
            if ctk:
                rb = ctk.CTkRadioButton(
                    row, text=label, variable=reason_var, value=rid,
                    font=FONTS["body"], text_color=COLORS["text"],
                    fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
                    border_color=COLORS["input_border"],
                )
            else:
                rb = tk.Radiobutton(
                    row, text=label, variable=reason_var, value=rid,
                    font=FONTS["body"], bg=COLORS["card"], fg=COLORS["text"],
                    activebackground=COLORS["card"], activeforeground=COLORS["text"],
                    selectcolor=COLORS["input_bg"], anchor="w", justify=tk.LEFT,
                )
            rb.pack(anchor="w", fill=tk.X)

        btn_row = self._frame(container, COLORS["bg"])
        btn_row.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))

        def ok():
            raw = url_var.get().strip()
            if not raw:
                messagebox.showwarning("입력 필요", "블로그 URL을 입력해주세요.", parent=dialog)
                return
            norm = self._normalize_blog_url(raw)
            if not self._is_valid_blog_url(norm):
                messagebox.showwarning(
                    "URL 형식 오류",
                    "네이버 블로그 게시물 URL 형식이 아닙니다.\n예: https://blog.naver.com/아이디/글번호",
                    parent=dialog,
                )
                return
            existing = {self._normalize_blog_url(self._blog_entry_url(e)) for e in self.blog_urls}
            if norm in existing:
                messagebox.showinfo("중복", "이미 등록된 URL입니다.", parent=dialog)
                return
            self.blog_urls.append({
                "url": norm,
                "reason_id": str(reason_var.get() or "3"),
            })
            self.save_blog_urls()
            self.refresh_blog_url_list()
            close()

        ui_button(btn_row, "추가", "primary", height=38, command=ok).pack(side=tk.RIGHT)
        ui_button(btn_row, "취소", "secondary", height=38, command=close).pack(side=tk.RIGHT, padx=(0, 8))
        entry.bind("<Return>", lambda e: ok())
        dialog.bind("<Escape>", lambda e: close())
        dialog.resizable(True, True)
        self.setup_dialog(dialog, "blog_url_add", 560, 520, 480, 380, modal=True)
        bind_modal_dialog(dialog, self.root, on_close=close)
        dialog.after(100, lambda: entry.focus_set())

    def delete_blog_url(self):
        selected = self.blog_url_tree.selection()
        if not selected:
            messagebox.showinfo("선택 필요", "삭제할 URL을 선택해주세요.")
            return
        urls_to_remove = set()
        for item in selected:
            vals = self.blog_url_tree.item(item, "values")
            if vals:
                urls_to_remove.add(self._normalize_blog_url(vals[0]))
        if not urls_to_remove:
            return
        before = len(self.blog_urls)
        self.blog_urls = [
            e for e in self.blog_urls
            if self._normalize_blog_url(self._blog_entry_url(e)) not in urls_to_remove
        ]
        removed = before - len(self.blog_urls)
        self.save_blog_urls()
        self.refresh_blog_url_list()
        if removed == 1:
            self.log("블로그 URL 삭제 완료")
        else:
            self.log(f"블로그 URL {removed}개 삭제 완료")

    def delete_selected_blog_result(self):
        selected = self.blog_result_tree.selection()
        if not selected:
            return
        remove_keys: set[tuple[str, str, str]] = set()
        for item in selected:
            tags = self.blog_result_tree.item(item)["tags"]
            if len(tags) >= 3:
                remove_keys.add((tags[0], tags[1], tags[2]))
        if not remove_keys:
            return
        before = len(self.blog_results)
        self.blog_results = [
            r for r in self.blog_results
            if (r.get("account_id"), r.get("url"), r.get("datetime")) not in remove_keys
        ]
        removed = before - len(self.blog_results)
        self.save_blog_results()
        self.refresh_blog_results_tree()
        if removed == 1:
            self.log(f"블로그 신고 결과 삭제: {self._truncate(next(iter(remove_keys))[1], 60)}")
        else:
            self.log(f"블로그 신고 결과 {removed}개 삭제 완료")

    def _find_blog_result_row(self, account_id: str, url: str, dt: str) -> dict | None:
        norm = self._normalize_blog_url(url)
        for row in self.blog_results:
            if (
                row.get("account_id") == account_id
                and self._normalize_blog_url(row.get("url", "")) == norm
                and row.get("datetime") == dt
            ):
                return row
        return None

    def _blog_url_report_count(self, url: str) -> int:
        norm = self._normalize_blog_url(url)
        return sum(
            1 for r in self.blog_results
            if self._normalize_blog_url(r.get("url", "")) == norm
            and r.get("status") in ("ok", "already_reported", "previously_reported")
        )

    def open_blog_result_detail(self, event=None):
        selected = self.blog_result_tree.selection()
        if not selected:
            return
        tags = self.blog_result_tree.item(selected[0])["tags"]
        if len(tags) < 3:
            return
        account, url, dt = tags[0], tags[1], tags[2]
        row = self._find_blog_result_row(account, url, dt)
        if not row:
            return
        report_count = self._blog_url_report_count(row.get("url", ""))
        BlogResultDetailWindow(self.root, row, report_count=report_count, app=self)

    def _cafe_article_key(self, url: str) -> str:
        m = re.search(r"/([A-Za-z0-9_-]+)/(\d+)", url or "", re.IGNORECASE)
        if m:
            return f"{m.group(1).lower()}/{m.group(2)}"
        return (url or "").strip()

    def _merge_cafe_collection(self, targets: list[dict], collected_at: str) -> int:
        """재수집 시 이전 노출 대비 검색결과에서 빠진 게시물을 사라짐으로 표시."""
        by_keyword: dict[str, list[dict]] = {}
        for t in targets:
            kw = t.get("keyword", "")
            if kw:
                by_keyword.setdefault(kw, []).append(t)

        disappeared_count = 0
        for kw, items in by_keyword.items():
            new_keys = {self._cafe_article_key(t.get("url", "")) for t in items}
            for row in self.cafe_collected:
                if row.get("keyword") != kw or row.get("status") == "disappeared":
                    continue
                key = self._cafe_article_key(row.get("url", ""))
                if key not in new_keys:
                    row["status"] = "disappeared"
                    row["disappeared_datetime"] = collected_at
                    disappeared_count += 1

            existing: dict[str, dict] = {}
            for row in self.cafe_collected:
                if row.get("keyword") == kw:
                    existing[self._cafe_article_key(row.get("url", ""))] = row

            for i, t in enumerate(items, 1):
                url = t.get("url", "")
                key = self._cafe_article_key(url)
                if key in existing:
                    row = existing[key]
                    row["status"] = "active"
                    row["rank"] = i
                    row["datetime"] = collected_at
                    row["title"] = t.get("title") or row.get("title", "")
                    row.pop("disappeared_datetime", None)
                else:
                    self.cafe_collected.append({
                        "datetime": collected_at,
                        "keyword": kw,
                        "title": t.get("title", ""),
                        "url": url,
                        "rank": i,
                        "status": "active",
                    })
        return disappeared_count

    def load_cafe_collected(self):
        self.cafe_collected = []
        if os.path.isfile(CAFE_COLLECTED_FILE):
            try:
                with open(CAFE_COLLECTED_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.cafe_collected = data
            except (json.JSONDecodeError, OSError):
                self.cafe_collected = []

    def save_cafe_collected(self):
        with open(CAFE_COLLECTED_FILE, "w", encoding="utf-8") as f:
            json.dump(self.cafe_collected, f, ensure_ascii=False, indent=2)

    def refresh_cafe_collected_tree(self):
        if not hasattr(self, "cafe_collected_tree"):
            return
        for item in self.cafe_collected_tree.get_children():
            self.cafe_collected_tree.delete(item)
        status_labels = {"active": "노출", "disappeared": "사라짐"}
        for row in reversed(self.cafe_collected):
            st = row.get("status", "active")
            label = status_labels.get(st, st or "노출")
            tags = ("disappeared",) if st == "disappeared" else ()
            self.cafe_collected_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("datetime", ""),
                    row.get("keyword", ""),
                    row.get("title", ""),
                    self._truncate(row.get("url", ""), 80),
                    row.get("rank", ""),
                    label,
                ),
                tags=tags,
            )

    def clear_cafe_collected(self):
        if not self.cafe_collected:
            return
        if not messagebox.askyesno("목록 비우기", "수집 목록을 모두 삭제하시겠습니까?"):
            return
        self.cafe_collected = []
        self.save_cafe_collected()
        self.refresh_cafe_collected_tree()

    def refresh_cafe_keyword_list(self):
        if not hasattr(self, "cafe_keyword_tree"):
            return
        for item in self.cafe_keyword_tree.get_children():
            self.cafe_keyword_tree.delete(item)
        for kw in self.cafe_keywords:
            self.cafe_keyword_tree.insert("", tk.END, values=(kw,))

    def refresh_cafe_results_tree(self):
        if not hasattr(self, "cafe_result_tree"):
            return
        for item in self.cafe_result_tree.get_children():
            self.cafe_result_tree.delete(item)
        status_labels = {
            "ok": "완료",
            "already_reported": "이미신고",
            "protected": "보호조치",
            "login_failed": "로그인실패",
            "no_reportable": "대상없음",
            "stopped": "중단",
            "failed": "실패",
        }
        for row in reversed(self.cafe_results):
            st = row.get("status", "")
            label = status_labels.get(st, st or "-")
            restriction = (row.get("restriction_reason") or "").strip()
            if restriction and st in ("protected", "login_failed"):
                label = f"{label} · {self._truncate(restriction, 36)}"
            self.cafe_result_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("account_id", ""),
                    row.get("keyword", ""),
                    self._truncate(row.get("url", ""), 80),
                    label,
                    row.get("datetime", ""),
                ),
                tags=(
                    row.get("account_id", ""),
                    row.get("keyword", ""),
                    row.get("url", ""),
                    row.get("datetime", ""),
                ),
            )

    def add_cafe_keyword(self):
        dialog = ctk.CTkToplevel(self.root) if ctk else tk.Toplevel(self.root)
        dialog.title("검색 키워드 추가")
        dialog.transient(self.root)
        dialog.grab_set()
        if ctk:
            dialog.configure(fg_color=COLORS["bg"])
        else:
            dialog.configure(bg=COLORS["bg"])

        container = self._frame(dialog, COLORS["bg"])
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ui_label(container, "통합검색 키워드", "body_bold", COLORS["text"]).pack(anchor="w")
        kw_var = tk.StringVar()
        if ctk:
            entry = ctk.CTkEntry(
                container, textvariable=kw_var, height=38,
                fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"],
            )
        else:
            entry = tk.Entry(
                container, textvariable=kw_var, font=FONTS["body"],
                bg=COLORS["input_bg"], fg=COLORS["text"],
            )
        entry.pack(fill=tk.X, pady=(8, 0))
        entry.focus_set()

        def ok():
            kw = kw_var.get().strip()
            if not kw:
                messagebox.showwarning("입력 필요", "키워드를 입력해주세요.", parent=dialog)
                return
            if kw not in self.cafe_keywords:
                self.cafe_keywords.append(kw)
                self.save_cafe_keywords()
                self.refresh_cafe_keyword_list()
            dialog.destroy()

        btn_row = self._frame(container, COLORS["bg"])
        btn_row.pack(fill=tk.X, pady=(16, 0))
        ui_button(btn_row, "취소", "ghost", width=90, height=36, command=dialog.destroy).pack(side=tk.RIGHT)
        ui_button(btn_row, "추가", "primary", width=90, height=36, command=ok).pack(side=tk.RIGHT, padx=(0, 8))

        entry.bind("<Return>", lambda e: ok())
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        self.setup_dialog(dialog, "cafe_keyword_add", 440, 200, 380, 180)

    def delete_selected_cafe_result(self):
        selected = self.cafe_result_tree.selection()
        if not selected:
            return
        tags = self.cafe_result_tree.item(selected[0])["tags"]
        if len(tags) < 4:
            return
        account, keyword, url, dt = tags[0], tags[1], tags[2], tags[3]
        self.cafe_results = [
            r for r in self.cafe_results
            if not (
                r.get("account_id") == account
                and r.get("keyword") == keyword
                and r.get("url") == url
                and r.get("datetime") == dt
            )
        ]
        self.save_cafe_results()
        self.refresh_cafe_results_tree()
        self.log(f"카페 신고 결과 삭제: {keyword}")

    def delete_cafe_keyword(self):
        selected = self.cafe_keyword_tree.selection()
        if not selected:
            messagebox.showinfo("선택 필요", "삭제할 키워드를 선택해주세요.")
            return
        for item in selected:
            vals = self.cafe_keyword_tree.item(item, "values")
            if vals:
                kw = vals[0]
                self.cafe_keywords = [k for k in self.cafe_keywords if k != kw]
        self.save_cafe_keywords()
        self.refresh_cafe_keyword_list()

    def load_templates(self):
        if os.path.exists(TEMPLATES_FILE):
            try:
                with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list) and data:
                    self.templates = data
                    return
            except Exception:
                pass
        self.templates = [dict(t) for t in DEFAULT_TEMPLATES]
        self.save_templates()

    def save_templates(self):
        with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.templates, f, ensure_ascii=False, indent=2)

    def _make_template_id(self, title: str) -> str:
        base = re.sub(r"[^\w가-힣]", "", title.replace(" ", "_"))[:30] or "원본"
        existing = {t["id"] for t in self.templates}
        if base not in existing:
            return base
        for i in range(2, 100):
            cand = f"{base}_{i}"
            if cand not in existing:
                return cand
        return f"tpl_{int(time.time())}"

    def get_template_options(self):
        return [(t["id"], t.get("title", t["id"])) for t in self.templates]

    def get_template_title(self, template_id):
        for t in self.templates:
            if t["id"] == template_id:
                return t.get("title", template_id)
        return template_id

    def get_template_text(self, template_id):
        for t in self.templates:
            if t["id"] == template_id:
                return t.get("content", "")
        return ""

    def refresh_template_list(self):
        if not hasattr(self, "template_tree"):
            return
        for item in self.template_tree.get_children():
            self.template_tree.delete(item)
        for t in self.templates:
            self.template_tree.insert("", tk.END, iid=t["id"], values=(t.get("title", t["id"]),))

    def on_template_select(self, event=None):
        selected = self.template_tree.selection()
        if not selected:
            return
        tid = selected[0]
        self._editing_template_id = tid
        for t in self.templates:
            if t["id"] == tid:
                self.tpl_title_var.set(t.get("title", ""))
                self._set_textbox_content(self.tpl_content_text, t.get("content", ""))
                break

    def _set_textbox_content(self, widget, text):
        if ctk and isinstance(widget, ctk.CTkTextbox):
            widget.delete("1.0", tk.END)
            widget.insert("1.0", text)
        else:
            widget.delete("1.0", tk.END)
            widget.insert(tk.END, text)

    def new_template(self):
        self._editing_template_id = None
        self.tpl_title_var.set("")
        self._set_textbox_content(self.tpl_content_text, "")
        if hasattr(self, "template_tree"):
            self.template_tree.selection_remove(self.template_tree.selection())

    def save_current_template(self):
        title = self.tpl_title_var.get().strip()
        content = self._textbox_get(self.tpl_content_text)
        if not title:
            messagebox.showwarning("입력 필요", "제목을 입력해주세요.")
            return
        if not content.strip():
            messagebox.showwarning("입력 필요", "내용을 입력해주세요.")
            return

        if self._editing_template_id:
            for t in self.templates:
                if t["id"] == self._editing_template_id:
                    t["title"] = title
                    t["content"] = content
                    break
            self.log(f"신고 원본 수정: {title}")
        else:
            tid = self._make_template_id(title)
            self.templates.append({"id": tid, "title": title, "content": content})
            self._editing_template_id = tid
            self.log(f"신고 원본 추가: {title}")

        self.save_templates()
        self.refresh_template_list()
        if self._editing_template_id:
            self.template_tree.selection_set(self._editing_template_id)
        messagebox.showinfo("저장", "신고 원본이 저장되었습니다.")

    def delete_selected_template(self):
        selected = self.template_tree.selection() if hasattr(self, "template_tree") else []
        if not selected:
            messagebox.showwarning("선택 오류", "삭제할 원본을 선택해주세요.")
            return
        tid = selected[0]
        title = self.get_template_title(tid)
        if not messagebox.askyesno("삭제 확인", f"'{title}' 원본을 삭제하시겠습니까?"):
            return
        self.templates = [t for t in self.templates if t["id"] != tid]
        self.save_templates()
        self.refresh_template_list()
        self.new_template()
        self.log(f"신고 원본 삭제: {title}")

    def _textbox_get(self, widget):
        if ctk and isinstance(widget, ctk.CTkTextbox):
            return widget.get("1.0", tk.END).strip()
        return widget.get("1.0", tk.END).strip()

    @staticmethod
    def build_naver_search_url(keyword: str, *, live: bool = True, log=None) -> str:
        return resolve_naver_search_url(keyword, live=live, log=log)

    @staticmethod
    def search_url_mode_label(search_url_custom: bool = False, search_url_auto: bool = False) -> str:
        if search_url_auto:
            return "자동"
        return "별도입력" if search_url_custom else "사이트동일"

    @staticmethod
    def task_template_display(template_title: str, search_url_auto: bool = False) -> str:
        tag = "자동URL" if search_url_auto else "수동URL"
        return f"{template_title} [{tag}]"

    def add_task(
        self, site, report_type, template, template_name=None,
        search_url="", search_url_custom=False, search_url_auto=False,
        inquiry_category=DEFAULT_INQUIRY_CATEGORY,
        *, save=True,
    ):
        if template_name is None:
            options = self.get_template_options()
            template_name = options[0][0] if options else ""
        category = inquiry_category if inquiry_category in INQUIRY_CATEGORY_LABELS else DEFAULT_INQUIRY_CATEGORY
        self.tasks.append({
            "site": site,
            "report_type": report_type,
            "template": template,
            "template_name": template_name,
            "search_url": search_url or site,
            "search_url_custom": bool(search_url_custom),
            "search_url_auto": bool(search_url_auto),
            "inquiry_category": category,
        })
        mode = self.search_url_mode_label(search_url_custom, search_url_auto)
        reason_label = INQUIRY_CATEGORY_LABELS.get(category, "불법성")
        if search_url_auto:
            self.log(f"등록: [{report_type}] {site} (사유:{reason_label}, 검색URL: {mode}, 신고 시 실시간 생성)")
        else:
            self.log(f"등록: [{report_type}] {site} (사유:{reason_label}, 검색URL: {mode})")
        if save:
            self.save_tasks()
            self.refresh_task_list()

    def update_task(
        self, index, site, report_type, template, template_name,
        search_url="", search_url_custom=False, search_url_auto=False,
        inquiry_category=DEFAULT_INQUIRY_CATEGORY,
    ):
        category = inquiry_category if inquiry_category in INQUIRY_CATEGORY_LABELS else DEFAULT_INQUIRY_CATEGORY
        self.tasks[index] = {
            "site": site,
            "report_type": report_type,
            "template": template,
            "template_name": template_name,
            "search_url": search_url or site,
            "search_url_custom": bool(search_url_custom),
            "search_url_auto": bool(search_url_auto),
            "inquiry_category": category,
        }
        self.save_tasks()
        self.refresh_task_list()

    def open_edit_task(self):
        self._clear_task_drag_ui()
        release_modal_grab(self.root)
        selected = self.task_tree.selection()
        if not selected:
            return
        idx = self.task_tree.index(selected[0])
        RegisterWindow(self.root, self, task_index=idx)

    def refresh_task_list(self):
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        for idx, task in enumerate(self.tasks, 1):
            template_title = self.get_template_title(task.get("template_name", ""))
            template_cell = self.task_template_display(
                template_title,
                bool(task.get("search_url_auto", False)),
            )
            self.task_tree.insert("", tk.END, values=(
                idx,
                task.get("report_type", ""),
                task.get("site", ""),
                template_cell,
            ))
        self.task_count_label.configure(text=f"{len(self.tasks)}개")

    def _clear_task_drag_ui(self):
        tree = self.task_tree
        for iid in tree.get_children():
            tree.item(iid, tags=())
        if self._task_drag_indicator is not None:
            self._task_drag_indicator.place_forget()
        if self._task_drag_ghost is not None:
            self._task_drag_ghost.destroy()
            self._task_drag_ghost = None
        self._task_drag_state = None

    def _ensure_task_drag_indicator(self):
        if self._task_drag_indicator is None:
            self._task_drag_indicator = tk.Frame(
                self.task_tree,
                bg=COLORS["accent"],
                height=3,
            )
        return self._task_drag_indicator

    def _task_tree_pointer_y(self) -> int:
        tree = self.task_tree
        return tree.winfo_pointery() - tree.winfo_rooty()

    def _scroll_task_tree(self, event) -> int:
        tree = self.task_tree
        if event.delta:
            delta = -1 * (event.delta // 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        else:
            delta = -1
        if delta == 0:
            return 0
        tree.yview_scroll(delta, "units")
        return delta

    def _refresh_task_drag_overlays(self, pointer_y: int | None = None):
        state = self._task_drag_state
        if not state or not state.get("active"):
            return
        y = pointer_y if pointer_y is not None else self._task_tree_pointer_y()
        drop_idx = self._task_drop_index(y)
        state["drop_idx"] = drop_idx
        self._show_task_drag_indicator(drop_idx)
        self._show_task_drag_ghost(state["drag_iids"], y)
        self._highlight_task_drop_target(
            min(drop_idx, max(len(self.task_tree.get_children()) - 1, 0)),
        )

    def _on_task_tree_mousewheel(self, event):
        tree = self.task_tree
        state = self._task_drag_state
        preserve = None
        if state:
            preserve = state.get("drag_iids") or list(tree.selection())
        elif len(tree.selection()) > 1:
            preserve = list(tree.selection())

        self._scroll_task_tree(event)

        if preserve:
            tree.selection_set(preserve)
            if state and state.get("active"):
                for drag_iid in state["drag_iids"]:
                    if tree.exists(drag_iid):
                        tree.item(drag_iid, tags=("drag_source",))

        if state and state.get("active"):
            self._refresh_task_drag_overlays()
        return "break"

    def _task_drop_index(self, event_y: int) -> int:
        tree = self.task_tree
        children = tree.get_children()
        if not children:
            return 0
        item = tree.identify_row(event_y)
        if not item:
            return len(children)
        bbox = tree.bbox(item)
        if not bbox:
            return tree.index(item)
        _, y, _, h = bbox
        idx = tree.index(item)
        return idx + 1 if event_y > y + h / 2 else idx

    def _show_task_drag_indicator(self, drop_idx: int):
        tree = self.task_tree
        children = tree.get_children()
        indicator = self._ensure_task_drag_indicator()
        if not children:
            indicator.place(x=0, y=2, relwidth=1, anchor="nw")
            indicator.lift()
            return
        if drop_idx >= len(children):
            bbox = tree.bbox(children[-1])
            y = bbox[1] + bbox[3] - 1 if bbox else 0
        else:
            bbox = tree.bbox(children[drop_idx])
            y = bbox[1] - 1 if bbox else 0
        indicator.place(x=0, y=max(y, 0), relwidth=1, anchor="nw")
        indicator.lift()

    def _show_task_drag_ghost(self, drag_iids: list[str], event_y: int):
        tree = self.task_tree
        if not drag_iids:
            return
        if len(drag_iids) > 1:
            label_text = f"  {len(drag_iids)}개 항목 이동"
        else:
            values = tree.item(drag_iids[0], "values")
            if not values:
                return
            label_text = f"  {values[1]}  {str(values[2])[:48]}"
        if self._task_drag_ghost is None:
            self._task_drag_ghost = tk.Label(
                tree,
                text=label_text,
                bg=COLORS["accent_light"],
                fg=COLORS["text"],
                font=FONTS["small"],
                relief=tk.RAISED,
                borderwidth=1,
                padx=10,
                pady=6,
            )
        else:
            self._task_drag_ghost.configure(text=label_text)
        ghost_y = max(event_y - 18, 2)
        self._task_drag_ghost.place(x=8, y=ghost_y, relwidth=0.96, anchor="nw")
        self._task_drag_ghost.lift()
        self._task_drag_ghost.bind("<MouseWheel>", self._on_task_tree_mousewheel, add="+")

    def _highlight_task_drop_target(self, drop_idx: int):
        tree = self.task_tree
        children = tree.get_children()
        for iid in children:
            tags = list(tree.item(iid, "tags") or ())
            if "drag_target" in tags:
                tags.remove("drag_target")
            tree.item(iid, tags=tuple(tags))
        if 0 <= drop_idx < len(children):
            iid = children[drop_idx]
            tags = tuple(set((tree.item(iid, "tags") or ()) + ("drag_target",)))
            tree.item(iid, tags=tags)

    def _on_task_drag_press(self, event):
        tree = self.task_tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        iid = tree.identify_row(event.y)
        if not iid:
            return
        current_selection = tree.selection()
        if iid in current_selection:
            drag_iids = list(current_selection)
        else:
            drag_iids = [iid]
        source_indices = sorted(tree.index(item) for item in drag_iids)
        self._task_drag_state = {
            "iid": iid,
            "drag_iids": drag_iids,
            "source_indices": source_indices,
            "source_idx": tree.index(iid),
            "start_x": event.x,
            "start_y": event.y,
            "active": False,
            "drop_idx": tree.index(iid),
        }

    def _on_task_drag_motion(self, event):
        state = self._task_drag_state
        if not state:
            return
        if not state["active"]:
            if abs(event.y - state["start_y"]) < 8 and abs(event.x - state["start_x"]) < 8:
                return
            state["active"] = True
            tree = self.task_tree
            drag_iids = state["drag_iids"]
            tree.selection_set(drag_iids)
            for drag_iid in drag_iids:
                tree.item(drag_iid, tags=("drag_source",))
        self._refresh_task_drag_overlays(event.y)

    def _move_tasks_to_drop(self, source_indices: list[int], drop_idx: int) -> int | None:
        source_indices = sorted(set(source_indices))
        if not source_indices or not self.tasks:
            return None

        insert_idx = drop_idx
        for i in source_indices:
            if i < drop_idx:
                insert_idx -= 1

        if insert_idx == source_indices[0]:
            return None

        block = [self.tasks[i] for i in source_indices]
        for i in reversed(source_indices):
            del self.tasks[i]

        insert_idx = max(0, min(insert_idx, len(self.tasks)))
        for offset, task in enumerate(block):
            self.tasks.insert(insert_idx + offset, task)
        return insert_idx

    def _on_task_drag_release(self, event):
        state = self._task_drag_state
        if not state:
            return
        source_indices = state["source_indices"]
        drop_idx = state.get("drop_idx", state["source_idx"])
        was_active = state["active"]
        self._clear_task_drag_ui()

        if not was_active:
            return

        insert_idx = self._move_tasks_to_drop(source_indices, drop_idx)
        if insert_idx is None:
            return

        self.save_tasks()
        self.refresh_task_list()
        children = self.task_tree.get_children()
        pulse_start = insert_idx
        pulse_end = min(insert_idx + len(source_indices), len(children))
        for idx in range(pulse_start, pulse_end):
            self._pulse_task_row(children[idx])

        if len(source_indices) == 1:
            self.log(
                f"신고 목록 순서 변경: {source_indices[0] + 1}번 → {insert_idx + 1}번"
            )
        else:
            self.log(
                f"신고 목록 순서 변경: {len(source_indices)}개 항목 → {insert_idx + 1}번 위치"
            )

    def _pulse_task_row(self, iid: str, step: int = 0):
        if step >= 6:
            self.task_tree.item(iid, tags=())
            return
        tag = ("drop_flash",) if step % 2 == 0 else ()
        self.task_tree.item(iid, tags=tag)
        self.root.after(70, lambda: self._pulse_task_row(iid, step + 1))

    def delete_selected_task(self):
        selected = self.task_tree.selection()
        if not selected:
            messagebox.showwarning("선택 오류", "삭제할 항목을 선택해주세요.")
            return
        indices = sorted((self.task_tree.index(item) for item in selected), reverse=True)
        for idx in indices:
            del self.tasks[idx]
        self.save_tasks()
        self.refresh_task_list()
        if len(indices) == 1:
            self.log("항목 삭제 완료")
        else:
            self.log(f"항목 {len(indices)}개 삭제 완료")

    def refresh_account_list(self):
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)
        for acc in self.accounts:
            self.account_tree.insert("", tk.END, values=(acc.get("id", ""), acc.get("password", "")))

    def _destroy_account_cell_entry(self):
        if self._account_cell_entry is not None:
            self._account_cell_entry.destroy()
            self._account_cell_entry = None

    def _on_account_tree_click(self, event):
        if self._account_cell_entry is not None:
            try:
                if self._account_cell_entry.winfo_exists():
                    ex = self._account_cell_entry.winfo_rootx()
                    ey = self._account_cell_entry.winfo_rooty()
                    ew = self._account_cell_entry.winfo_width()
                    eh = self._account_cell_entry.winfo_height()
                    if ex <= event.x_root <= ex + ew and ey <= event.y_root <= ey + eh:
                        return
            except tk.TclError:
                pass
        self._destroy_account_cell_entry()

    def _on_account_tree_double_click(self, event):
        tree = self.account_tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        item = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not item or not col:
            return
        col_idx = int(col.lstrip("#")) - 1
        values = tree.item(item, "values")
        if col_idx < 0 or col_idx >= len(values):
            return
        text = str(values[col_idx])
        bbox = tree.bbox(item, col)
        if not bbox:
            return

        self._destroy_account_cell_entry()
        x, y, w, h = bbox
        entry = tk.Entry(
            tree,
            font=FONTS["mono"],
            bg=COLORS["input_bg"],
            fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            highlightbackground=COLORS["accent"],
            highlightthickness=1,
            relief=tk.SOLID,
            borderwidth=1,
        )
        entry.insert(0, text)
        entry.place(x=x, y=y, width=max(w, 80), height=h)
        entry.focus_set()
        entry.selection_range(0, tk.END)
        entry.bind("<FocusOut>", lambda e: self._destroy_account_cell_entry())
        entry.bind("<Escape>", lambda e: (self._destroy_account_cell_entry(), "break"))
        self._account_cell_entry = entry

    def open_register_window(self):
        try:
            release_modal_grab(self.root)
            RegisterWindow(self.root, self)
        except Exception as e:
            release_modal_grab(self.root)
            messagebox.showerror("오류", f"신고 항목 등록 창을 열 수 없습니다.\n{e}")

    def toggle_api_visibility(self):
        current = self.api_key_entry.cget("show")
        if current == "*":
            self.api_key_entry.configure(show="")
            self.show_api_btn.configure(text="숨김")
        else:
            self.api_key_entry.configure(show="*")
            self.show_api_btn.configure(text="표시")

    def log(self, message, channel: str = "general"):
        ch = channel if channel in self._log_buffers else "general"
        self._log_buffers[ch].append(message)
        self._log_all_lines.append((ch, message))
        if hasattr(self, "_log_widgets"):
            self._append_log_ui(message, ch)
        elif hasattr(self, "log_text"):
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"{message}\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

    def parse_sites(self, text):
        sites = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if not line.startswith(("http://", "https://")):
                line = "https://" + line
            sites.append(line)
        return sites

    def parse_templates(self, text):
        cleaned = "\n".join(line.rstrip() for line in text.splitlines())
        return [cleaned] if cleaned.strip() else []

    # Accounts
    def _parse_line_list(self, text):
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                lines.append(line)
        return lines

    def pair_accounts_by_order(self, id_text, pw_text):
        ids = self._parse_line_list(id_text)
        pws = self._parse_line_list(pw_text)
        if not ids:
            return None, "아이디를 입력해주세요."
        if not pws:
            return None, "비밀번호를 입력해주세요."
        if len(ids) != len(pws):
            return None, (
                f"아이디와 비밀번호 줄 수가 같아야 합니다.\n"
                f"(아이디 {len(ids)}줄, 비밀번호 {len(pws)}줄)"
            )
        return list(zip(ids, pws)), None

    def add_accounts_bulk(self):
        id_raw = self._textbox_get(self.bulk_id_text)
        pw_raw = self._textbox_get(self.bulk_pw_text)
        entries, err = self.pair_accounts_by_order(id_raw, pw_raw)
        if err:
            messagebox.showwarning("입력 오류", err)
            return

        added, skipped = 0, 0
        for naver_id, naver_pw in entries:
            if any(acc["id"] == naver_id for acc in self.accounts):
                skipped += 1
                continue
            self.accounts.append({"id": naver_id, "password": naver_pw})
            added += 1

        if added == 0:
            messagebox.showwarning("등록 없음", "추가된 계정이 없습니다. (중복 또는 형식 오류)")
            return

        self.save_accounts()
        self.refresh_account_list()
        self._set_textbox_content(self.bulk_id_text, "")
        self._set_textbox_content(self.bulk_pw_text, "")
        self.log(f"계정 일괄 등록: {added}개 추가, {skipped}개 중복 스킵")
        messagebox.showinfo("완료", f"{added}개 계정이 등록되었습니다.")

    def delete_selected_account(self):
        selected = self.account_tree.selection()
        if not selected:
            messagebox.showwarning("선택 오류", "삭제할 계정을 선택해주세요.")
            return
        ids_to_remove = {self.account_tree.item(item)["values"][0] for item in selected}
        removed = [acc["id"] for acc in self.accounts if acc["id"] in ids_to_remove]
        self.accounts = [acc for acc in self.accounts if acc["id"] not in ids_to_remove]
        self.save_accounts()
        self.refresh_account_list()
        if len(removed) == 1:
            self.log(f"계정 삭제 완료: {removed[0]}")
        else:
            self.log(f"계정 삭제 완료: {len(removed)}개")

    # GPT / Preview / Report
    def generate_variants_with_account(self, site_url, report_type, templates, api_key, model, account_id):
        if not templates or (len(templates) == 1 and templates[0].strip() == ""):
            templates = [f"해당 사이트는 {report_type} 관련 불법 행위를 조장하는 곳으로 신고합니다. 신속한 조치를 요청드립니다."]
        results = {}
        client = openai.OpenAI(api_key=api_key)
        original_template = templates[0]
        for template in templates:
            prompt = (
                "아래 원본 신고 내용을 토대로, 같은 의미와 맥락을 유지하면서 "
                "단어, 문장구조, 어체(해라체/합쇼체/해요체), 표현 방식을 바꿔서 "
                "새로운 신고 내용을 250~400자 내외로 작성해주세요.\n\n"
                f"[원본 신고 내용]\n{template}\n\n"
                "[규칙]\n"
                "- '신고 대상:', '사이트:', '신고 사항:', '유형:', 'URL:', '---' 같은 구조적 요약은 절대 넣지 마세요.\n"
                "- 한국어 자연스러운 문단 형식으로만 작성하세요.\n"
                "- 사이트 주소는 신고 내용 중 필요한 곳에만 자연스럽게 포함하세요.\n"
                "- 네이버 아이디, 계정명, '저는 ... 계정을 사용' 같은 계정 관련 표현은 절대 넣지 마세요.\n"
                "- 다른 신고 문구와 겹치지 않도록 표현/어체/문장 흐름을 다양하게 바꿔주세요."
            )
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "당신은 불법 금융 사이트 신고 내용을 자연스럽고 다양하게 변형하는 전문 보조원입니다."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.85,
                    max_tokens=700,
                )
                content = response.choices[0].message.content.strip()
                content = self._clean_output(content)
                results[site_url] = {"original": original_template, "rewritten": content}
            except Exception as e:
                results[site_url] = {"original": original_template, "rewritten": f"GPT 오류: {e}"}
        return results

    def _clean_output(self, text):
        lines = text.splitlines()
        cleaned = []
        skip_prefixes = ("신고 대상", "사이트", "신고 사항", "유형", "URL", "주소", "---")
        account_phrases = ("계정을 사용", "네이버 계정", "네이버 아이디", "아이디를 사용")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("---") and "계정" in stripped:
                continue
            if any(stripped.startswith(p) for p in skip_prefixes):
                continue
            if any(p in stripped for p in account_phrases):
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    def _add_result(self, site, report_type, data, account_id=None):
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        key = f"{dt}|{report_type}|{site}"
        self.hidden_results[key] = {"site": site, "report_type": report_type, "account_id": account_id or "", **data, "datetime": dt}
        return dt

    def insert_preview(
        self, site, report_type, original, rewritten, dt=None, account_id=None,
        status=None, search_url_custom=False, search_url_auto=False,
    ):
        if dt is None:
            dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        account_id = account_id or ""
        display_rewritten = rewritten
        if status == "protected":
            display_rewritten = "보호조치 해제 필요"
        tags = (site, report_type, original, rewritten)
        if status == "protected":
            tags = ("protected", site, report_type, original, rewritten)
        stats = self.compute_site_report_stats()
        site_count = self._format_site_count_cell(site, status or "", stats)
        search_label = self.search_url_mode_label(bool(search_url_custom), bool(search_url_auto))
        self.results_tree.insert("", tk.END, values=(
            dt, account_id, site, search_label, report_type, site_count,
            self._truncate(original, 45), self._truncate(display_rewritten, 45)),
            tags=tags)
        self.refresh_site_stats_panel()

    def open_preview_detail(self):
        selected = self.results_tree.selection()
        if not selected:
            return
        row = self.results_tree.item(selected[0])["values"]
        if len(row) < 5:
            return
        dt, account_id, site, report_type = row[0], row[1], row[2], row[4]
        tags = self.results_tree.item(selected[0])["tags"]
        if not tags:
            return
        if tags[0] == "protected":
            site, report_type, original, rewritten = tags[1], tags[2], tags[3], tags[4]
        else:
            site, report_type, original, rewritten = tags[0], tags[1], tags[2], tags[3]
        account_password = self.get_account_password_for_result(dt, account_id, site, report_type)
        result_meta = self.get_result_meta(dt, account_id, site, report_type)
        DetailWindow(
            self.root, site, report_type, original, rewritten,
            account_id=account_id, account_password=account_password,
            search_url=result_meta.get("search_url", ""),
            search_url_custom=result_meta.get("search_url_custom", False),
            search_url_auto=result_meta.get("search_url_auto", False),
            app=self,
        )

    def get_result_meta(self, dt, account_id, site, report_type):
        for data in self.hidden_results.values():
            if (data.get("datetime") == dt
                    and data.get("account_id", "") == account_id
                    and data.get("site") == site
                    and data.get("report_type") == report_type):
                return data
        return {}

    def get_account_password_for_result(self, dt, account_id, site, report_type):
        for data in self.hidden_results.values():
            if (data.get("datetime") == dt
                    and data.get("account_id", "") == account_id
                    and data.get("site") == site
                    and data.get("report_type") == report_type):
                pw = data.get("account_password", "")
                if pw:
                    return pw
        for acc in self.accounts:
            if acc.get("id") == account_id:
                return acc.get("password", "")
        return ""

    def _sync_report_buttons(self):
        """각 신고 탭은 독립 실행 — 해당 탭만 시작/정지 버튼 상태 갱신."""
        try:
            self.preview_btn.configure(state=tk.DISABLED if self._preview_running else tk.NORMAL)
        except Exception:
            pass
        for start_btn, stop_btn, running in (
            (getattr(self, "report_btn", None), getattr(self, "stop_report_btn", None), self._report_running),
            (getattr(self, "cafe_report_btn", None), getattr(self, "cafe_stop_btn", None), self._cafe_running),
            (getattr(self, "blog_report_btn", None), getattr(self, "blog_stop_btn", None), self._blog_running),
        ):
            if start_btn is not None:
                try:
                    start_btn.configure(state=tk.DISABLED if running else tk.NORMAL)
                except Exception:
                    pass
            if stop_btn is not None:
                try:
                    stop_btn.configure(state=tk.NORMAL if running else tk.DISABLED)
                except Exception:
                    pass

    def stop_website_report(self):
        if not self._report_running:
            return
        self._website_stop_requested = True
        self.log("[웹사이트 신고 정지] 브라우저를 즉시 종료합니다...")
        try:
            self.stop_report_btn.configure(state=tk.DISABLED)
        except Exception:
            pass
        if self._website_reporter:
            self._website_reporter.request_cancel()

    def stop_cafe_report(self):
        if not self._cafe_running:
            return
        self._cafe_stop_requested = True
        self.log("[카페 신고 정지] 브라우저를 즉시 종료합니다...")
        try:
            self.cafe_stop_btn.configure(state=tk.DISABLED)
        except Exception:
            pass
        if self._cafe_reporter:
            self._cafe_reporter.request_cancel()

    def stop_blog_report(self):
        if not self._blog_running:
            return
        self._blog_stop_requested = True
        self.log("[블로그 신고 정지] 브라우저를 즉시 종료합니다...")
        try:
            self.blog_stop_btn.configure(state=tk.DISABLED)
        except Exception:
            pass
        if self._blog_reporter:
            self._blog_reporter.request_cancel()

    def preview_all(self):
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("API 키 필요", "OpenAI API Key를 입력해주세요.")
            self.tabs.select("Settings")
            return
        if not self.tasks:
            messagebox.showwarning("등록 필요", "신고 항목을 하나 이상 등록해주세요.")
            return

        self.log("[미리보기] 리라이트 생성 중...")
        self._preview_running = True
        self._sync_report_buttons()

        def run():
            try:
                for task in self.tasks:
                    results = self.generate_variants(
                        task["site"], task["report_type"], [task["template"]],
                        api_key, self.model_var.get(),
                    )
                    for url, data in results.items():
                        data["search_url"] = task.get("search_url", url)
                        data["search_url_custom"] = task.get("search_url_custom", False)
                        data["search_url_auto"] = task.get("search_url_auto", False)
                        self._add_result(url, task["report_type"], data)
            finally:
                def done():
                    self._preview_running = False
                    self._sync_report_buttons()
                    self.log("[미리보기] 완료")
                    self.save_results()
                    self.tabs.select("리라이트 결과")
                    self.refresh_results_tree()

                self.root.after(0, done)

        threading.Thread(target=run, daemon=True).start()

    def start_cafe_report(self):
        if not self.accounts:
            messagebox.showwarning("계정 필요", "네이버 계정을 하나 이상 등록해주세요.")
            self.tabs.select("Settings")
            return
        if not self.cafe_keywords:
            messagebox.showwarning("키워드 필요", "검색 키워드를 하나 이상 등록해주세요.")
            return

        total = len(self.accounts)
        self.log("=" * 55, channel="cafe")
        self.log(
            f"카페 신고 시작 | 키워드:{len(self.cafe_keywords)}개, 계정:{total}개 "
            f"(URL 수집 후 계정별 전체 신고)",
            channel="cafe",
        )
        self._cafe_running = True
        self._cafe_stop_requested = False
        self._cafe_reporter = None
        self._register_log_channel("cafe")
        self._sync_report_buttons()
        self.cafe_progress["value"] = 0

        skip_pairs = {
            (r.get("account_id"), r.get("url"))
            for r in self.cafe_results
            if r.get("url") and r.get("account_id")
            and r.get("status") in ("ok", "already_reported")
        }

        def on_log(message):
            self.root.after(0, lambda m=message: self.log(m, channel="cafe"))

        def on_result(item):
            self.cafe_results.append(item)
            self.root.after(0, self.save_cafe_results)
            self.root.after(0, self.refresh_cafe_results_tree)

        current = [0]
        total_work = [max(total, 1)]

        def on_targets_ready(targets):
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            disappeared = self._merge_cafe_collection(targets, now)
            self.root.after(0, self.save_cafe_collected)
            self.root.after(0, self.refresh_cafe_collected_tree)
            if disappeared:
                on_log(f"[수집] 검색결과에서 사라진 게시물 {disappeared}건 → 수집 목록에 「사라짐」 표시")
            total_work[0] = max(len(targets) * total, 1)
            on_log(f"진행 예정: URL {len(targets)}건 × 계정 {total}개 = {total_work[0]}회 시도")

        def on_progress(delta):
            current[0] += delta
            self.root.after(
                0,
                lambda c=current[0]: self.cafe_progress.configure(
                    value=min(c / total_work[0] * 100, 100)
                ),
            )

        api_key = self.api_key_var.get().strip()

        def run():
            stopped = False
            reporter = NaverReporter(
                api_key=api_key or "cafe-only",
                model=self.model_var.get(),
                headless=bool(self.hagrid_mode_var.get()),
                log_callback=on_log,
                result_callback=on_result,
                progress_callback=on_progress,
            )
            self._cafe_reporter = reporter
            try:
                reporter.report_cafe_batch(
                    self.accounts,
                    self.cafe_keywords,
                    skip_pairs,
                    targets_callback=lambda t: self.root.after(0, lambda targets=t: on_targets_ready(targets)),
                )
                if reporter.cancel_requested or self._cafe_stop_requested:
                    stopped = True
            except Exception as e:
                on_log(f"[카페] 처리 오류: {e}")
            finally:
                self._cafe_reporter = None
            self.root.after(0, lambda: self.cafe_report_finished(stopped=stopped))

        threading.Thread(target=run, daemon=True).start()

    def cafe_report_finished(self, stopped: bool = False):
        self._cafe_running = False
        self._cafe_stop_requested = False
        self._cafe_reporter = None
        self._unregister_log_channel("cafe")
        self._sync_report_buttons()
        if not stopped:
            self.cafe_progress.configure(value=100)
        self.log("=" * 55, channel="cafe")
        if stopped:
            self.log("카페 신고 작업이 중단되었습니다.", channel="cafe")
        else:
            ok_count = sum(1 for r in self.cafe_results if r.get("success"))
            self.log(f"카페 신고 완료 — 성공 {ok_count}건", channel="cafe")
        self.save_cafe_results()
        self.refresh_cafe_results_tree()
        self.tabs.select("카페신고" if self.admin_mode else "웹사이트신고")

    def start_blog_report(self):
        if not self.accounts:
            messagebox.showwarning("계정 필요", "네이버 계정을 하나 이상 등록해주세요.")
            self.tabs.select("Settings")
            return
        if not self.blog_urls:
            messagebox.showwarning("URL 필요", "블로그 URL을 하나 이상 등록해주세요.")
            return

        total_accounts = len(self.accounts)

        self.log("=" * 55, channel="blog")
        self.log(
            f"블로그 신고 시작 | URL:{len(self.blog_urls)}개, 계정:{total_accounts}개",
            channel="blog",
        )
        self._blog_running = True
        self._blog_stop_requested = False
        self._blog_reporter = None
        self._register_log_channel("blog")
        self._sync_report_buttons()
        self.blog_progress["value"] = 0

        skip_pairs = {
            (r.get("account_id"), self._normalize_blog_url(r.get("url", "")))
            for r in self.blog_results
            if r.get("url") and r.get("account_id")
            and r.get("status") in ("ok", "already_reported", "previously_reported")
        }
        known_titles = {
            (r.get("account_id"), self._normalize_blog_url(r.get("url", ""))): r.get("title", "")
            for r in self.blog_results
            if r.get("url") and r.get("account_id") and r.get("title")
        }

        def on_log(message):
            self.root.after(0, lambda m=message: self.log(m, channel="blog"))

        def on_result(item):
            aid = item.get("account_id", "")
            url = self._normalize_blog_url(item.get("url", ""))
            updated = False
            for row in self.blog_results:
                if (
                    row.get("account_id") == aid
                    and self._normalize_blog_url(row.get("url", "")) == url
                ):
                    prev = row.get("status", "")
                    new_st = item.get("status", "")
                    if new_st == "previously_reported":
                        row["status"] = "previously_reported"
                    elif prev == "failed" and new_st in ("ok", "already_reported"):
                        row["status"] = new_st
                        row["success"] = item.get("success", new_st == "ok")
                    elif prev not in ("ok", "already_reported", "previously_reported"):
                        row["status"] = new_st
                        row["success"] = item.get("success", row.get("success", False))
                    if item.get("title"):
                        row["title"] = item["title"]
                    if item.get("reason"):
                        row["reason"] = item["reason"]
                    if item.get("popup_message"):
                        row["popup_message"] = item["popup_message"]
                    if item.get("restriction_reason"):
                        row["restriction_reason"] = item["restriction_reason"]
                    if item.get("restriction_date"):
                        row["restriction_date"] = item["restriction_date"]
                    row["datetime"] = item.get("datetime", row.get("datetime"))
                    updated = True
                    break
            if not updated:
                self.blog_results.append(item)
            self.root.after(0, self.save_blog_results)
            self.root.after(0, self.refresh_blog_results_tree)

        current = [0]
        total_work = [max(len(self.accounts) * len(self.blog_urls), 1)]

        def on_progress(delta):
            current[0] += delta
            self.root.after(
                0,
                lambda c=current[0]: self.blog_progress.configure(
                    value=min(c / total_work[0] * 100, 100)
                ),
            )

        api_key = self.api_key_var.get().strip()

        def run():
            stopped = False
            reporter = NaverReporter(
                api_key=api_key or "blog-only",
                model=self.model_var.get(),
                headless=bool(self.hagrid_mode_var.get()),
                log_callback=on_log,
                result_callback=on_result,
                progress_callback=on_progress,
            )
            self._blog_reporter = reporter
            try:
                on_log(
                    f"진행 예정: 계정 {len(self.accounts)}개 × URL {len(self.blog_urls)}개 "
                    f"(이미 신고한 항목은 스킵)"
                )
                reporter.report_blog_batch(
                    self.accounts,
                    self.blog_urls,
                    skip_pairs,
                    known_titles,
                )
                if reporter.cancel_requested or self._blog_stop_requested:
                    stopped = True
            except Exception as e:
                on_log(f"[블로그] 처리 오류: {e}")
            finally:
                self._blog_reporter = None
            self.root.after(0, lambda: self.blog_report_finished(stopped=stopped))

        threading.Thread(target=run, daemon=True).start()

    def blog_report_finished(self, stopped: bool = False):
        self._blog_running = False
        self._blog_stop_requested = False
        self._blog_reporter = None
        self._unregister_log_channel("blog")
        self._sync_report_buttons()
        if not stopped:
            self.blog_progress.configure(value=100)
        self.log("=" * 55, channel="blog")
        if stopped:
            self.log("블로그 신고 작업이 중단되었습니다.", channel="blog")
        else:
            ok_count = sum(1 for r in self.blog_results if r.get("success"))
            self.log(f"블로그 신고 완료 — 성공 {ok_count}건", channel="blog")
        self.save_blog_results()
        self.refresh_blog_results_tree()
        self.tabs.select("블로그신고")

    def generate_variants(self, site_url, report_type, templates, api_key, model):
        return self.generate_variants_with_account(site_url, report_type, templates, api_key, model, "default")

    def start_report(self):
        self.save_settings()
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("API 키 필요", "OpenAI API Key를 입력해주세요.")
            self.tabs.select("Settings")
            return
        if not self.accounts:
            messagebox.showwarning("계정 필요", "네이버 계정을 하나 이상 등록해주세요.")
            self.tabs.select("Settings")
            return
        if not self.tasks:
            messagebox.showwarning("등록 필요", "신고 항목을 하나 이상 등록해주세요.")
            return

        total = len(self.accounts) * len(self.tasks)
        self.log("=" * 55, channel="website")
        self.log(f"신고 시작 | 항목:{len(self.tasks)}개, 계정:{len(self.accounts)}개, 총:{total}개", channel="website")
        self._report_running = True
        self._website_stop_requested = False
        self._website_reporter = None
        self._register_log_channel("website")
        self._sync_report_buttons()
        self.progress["value"] = 0

        def on_log(message):
            self.root.after(0, lambda m=message: self.log(m, channel="website"))

        def on_result(item):
            status = item.get("status", "")
            data = {
                "original": item["original"],
                "rewritten": item["rewritten"],
                "status": status,
                "account_password": item.get("account_password", ""),
                "search_url": item.get("search_url", ""),
                "search_url_custom": item.get("search_url_custom", False),
                "search_url_auto": item.get("search_url_auto", False),
            }
            dt = self._add_result(item["site"], item["report_type"], data, item["account_id"])
            self.root.after(
                0,
                lambda s=item["site"], rt=item["report_type"], o=item["original"], r=item["rewritten"],
                       d=dt, a=item["account_id"], st=status,
                       suc=item.get("search_url_custom", False), sa=item.get("search_url_auto", False):
                self.insert_preview(s, rt, o, r, d, a, st, search_url_custom=suc, search_url_auto=sa)
            )

        current = [0]
        def on_progress(delta):
            current[0] += delta
            self.root.after(0, lambda c=current[0]: self.progress.configure(value=min(c / total * 100, 100)))

        def run():
            stopped = False
            for account in self.accounts:
                if self._website_stop_requested:
                    stopped = True
                    break
                account_id = account["id"]
                on_log(f"[계정 시작] {account_id}")
                reporter = NaverReporter(
                    api_key=api_key,
                    model=self.model_var.get(),
                    headless=bool(self.hagrid_mode_var.get()),
                    log_callback=on_log,
                    result_callback=on_result,
                    progress_callback=on_progress,
                )
                self._website_reporter = reporter
                try:
                    reporter.report(account_id, account["password"], self.tasks)
                    if reporter.cancel_requested or self._website_stop_requested:
                        stopped = True
                except Exception as e:
                    on_log(f"[{account_id}] 처리 오류: {e}")
                finally:
                    self._website_reporter = None
                on_log(f"[계정 완료] {account_id}")
                if self._website_stop_requested:
                    stopped = True
                    break
            self.root.after(0, lambda: self.report_finished(stopped=stopped))

        threading.Thread(target=run, daemon=True).start()

    def _report_callback(self, site, report_type, content):
        self.log(f"[{report_type}] 생성: {site}")
        for line in content.splitlines():
            self.log(f"   {line}")

    def report_finished(self, stopped: bool = False):
        self._report_running = False
        self._website_stop_requested = False
        self._website_reporter = None
        self._unregister_log_channel("website")
        self._sync_report_buttons()
        if not stopped:
            self.progress.configure(value=100)
        self.log("=" * 55, channel="website")
        if stopped:
            self.log("신고 작업이 중단되었습니다.", channel="website")
        else:
            self.log("신고 내용 생성 완료", channel="website")
        stats = self.compute_site_report_stats()
        protected_accounts = set()
        for info in stats.values():
            protected_accounts.update(info["protected_accounts"])
        if protected_accounts:
            self.log(
                f"보호조치 제외 계정 (신고 횟수 미포함): {', '.join(sorted(protected_accounts))}",
                channel="website",
            )
        for site, info in sorted(stats.items(), key=lambda x: -x[1]["valid"]):
            if info["valid"] or info["protected"]:
                msg = f"[집계] {self._truncate(site, 60)} — 신고 {info['valid']}회"
                if info["protected"]:
                    msg += f", 보호조치 {info['protected']}건 제외"
                self.log(msg, channel="website")
        self.save_results()
        self.refresh_results_tree()
        self.tabs.select("리라이트 결과")

    def _truncate(self, text, length):
        if not text:
            return ""
        return text[:length] + "..." if len(text) > length else text

    def compute_site_report_stats(self):
        stats = {}
        for data in self.hidden_results.values():
            site = data.get("site", "")
            if not site:
                continue
            if site not in stats:
                stats[site] = {"valid": 0, "protected": 0, "protected_accounts": set()}
            if data.get("status") == "protected":
                stats[site]["protected"] += 1
                acc = data.get("account_id", "")
                if acc:
                    stats[site]["protected_accounts"].add(acc)
            else:
                stats[site]["valid"] += 1
        return stats

    def _format_site_count_cell(self, site, status, stats):
        if status == "protected":
            return "제외"
        info = stats.get(site, {})
        valid = info.get("valid", 0)
        return f"{valid}회" if valid else "-"

    def refresh_site_stats_panel(self):
        if not hasattr(self, "site_stats_text"):
            return
        stats = self.compute_site_report_stats()
        lines = []
        all_protected_accounts = set()
        if not stats:
            lines.append("등록된 신고 결과가 없습니다.")
        else:
            for site, info in sorted(stats.items(), key=lambda x: (-x[1]["valid"], x[0])):
                short = self._truncate(site, 90)
                line = f"• {short}  →  신고 {info['valid']}회"
                if info["protected"]:
                    accs = ", ".join(sorted(info["protected_accounts"]))
                    line += f"  (보호조치 {info['protected']}건 제외"
                    if accs:
                        line += f": {accs}"
                    line += ")"
                    all_protected_accounts.update(info["protected_accounts"])
                lines.append(line)
            if all_protected_accounts:
                lines.append("")
                lines.append(
                    f"⚠ 보호조치 제외 계정: {', '.join(sorted(all_protected_accounts))}"
                )
        text = "\n".join(lines)
        if ctk and isinstance(self.site_stats_text, ctk.CTkTextbox):
            self.site_stats_text.configure(state="normal")
            self.site_stats_text.delete("1.0", tk.END)
            self.site_stats_text.insert("1.0", text)
            self.site_stats_text.configure(state="disabled")
        else:
            self.site_stats_text.configure(state=tk.NORMAL)
            self.site_stats_text.delete("1.0", tk.END)
            self.site_stats_text.insert(tk.END, text)
            self.site_stats_text.configure(state=tk.DISABLED)

    def refresh_results_tree(self, keyword=""):
        stats = self.compute_site_report_stats()
        self.refresh_site_stats_panel()
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        for key, data in self.hidden_results.items():
            k = keyword.strip().lower()
            search_target = " ".join([
                data.get("site", ""),
                data.get("report_type", ""),
                data.get("account_id", ""),
                data.get("rewritten", "")
            ]).lower()
            if k and k not in search_target:
                continue
            dt = data.get("datetime", "")
            account_id = data.get("account_id", "")
            status = data.get("status", "")
            site = data.get("site", "")
            display_rewritten = data["rewritten"]
            if status == "protected":
                display_rewritten = "보호조치 해제 필요"
            site_count = self._format_site_count_cell(site, status, stats)
            search_label = self.search_url_mode_label(
                bool(data.get("search_url_custom")), bool(data.get("search_url_auto")),
            )
            tags = (data["site"], data["report_type"], data["original"], data["rewritten"])
            if status == "protected":
                tags = ("protected", data["site"], data["report_type"], data["original"], data["rewritten"])
            self.results_tree.insert("", tk.END, values=(
                dt, account_id, site, search_label, data["report_type"], site_count,
                self._truncate(data["original"], 45), self._truncate(display_rewritten, 45)),
                tags=tags)

    def delete_selected_result(self):
        selected = self.results_tree.selection()
        if not selected:
            return
        keys_to_remove: set[str] = set()
        for item in selected:
            values = self.results_tree.item(item)["values"]
            if len(values) < 5:
                continue
            dt, account, site, rt = values[0], values[1], values[2], values[4]
            for key, data in self.hidden_results.items():
                if (data.get("datetime") == dt and data.get("account_id", "") == account
                        and data.get("site") == site and data.get("report_type") == rt):
                    keys_to_remove.add(key)
                    break
        if not keys_to_remove:
            return
        for key in keys_to_remove:
            del self.hidden_results[key]
        self.save_results()
        self.refresh_results_tree(self.search_var.get())
        if len(keys_to_remove) == 1:
            self.log("결과 삭제 완료")
        else:
            self.log(f"결과 {len(keys_to_remove)}개 삭제 완료")

    def filter_results(self):
        self.refresh_results_tree(self.search_var.get())

    def clear_filter(self):
        self.search_var.set("")
        self.refresh_results_tree()


if __name__ == "__main__":
    root = ctk.CTk() if ctk else tk.Tk()
    app = ReportApp(root)
    root.mainloop()
