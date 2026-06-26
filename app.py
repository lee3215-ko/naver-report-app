import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import re
import threading
import time
from datetime import datetime

from naver_reporter import NaverReporter
from paths import data_path
from ui_theme import (
    COLORS,
    FONTS,
    SidebarNav,
    PageHeader,
    configure_treeview,
    frame as ui_frame,
    card as ui_card,
    label as ui_label,
    button as ui_button,
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
                 account_id="", account_password=""):
        self.top = ctk.CTkToplevel(parent) if ctk else tk.Toplevel(parent)
        self.top.title("신고 내용 상세")
        self.top.geometry("860x720")
        if ctk:
            self.top.configure(fg_color=COLORS["bg"])
        else:
            self.top.configure(bg=COLORS["bg"])
        self.top.transient(parent)
        self.top.grab_set()

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
        ui_label(meta_inner, f"유형 · {report_type}", "small", COLORS["text_muted"]).pack(anchor="w", pady=(0, 8))

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


class RegisterWindow:
    def __init__(self, parent, app):
        self.top = ctk.CTkToplevel(parent) if ctk else tk.Toplevel(parent)
        self.top.title("신고 항목 등록")
        if ctk:
            self.top.configure(fg_color=COLORS["bg"])
        else:
            self.top.configure(bg=COLORS["bg"])
        self.top.transient(parent)
        self.top.grab_set()
        self.top.resizable(False, False)
        self.app = app
        self.center_window(parent)

        main = ui_frame(self.top, COLORS["bg"])
        main.pack(fill=tk.BOTH, expand=True, padx=28, pady=28)
        main.grid_columnconfigure(0, weight=1)

        ui_label(main, "신고 항목 등록", "title", COLORS["text"]).grid(row=0, column=0, sticky="w", pady=(0, 20))

        card = ui_card(main)
        card.grid(row=1, column=0, sticky="ew")
        card_inner = ui_frame(card, COLORS["card"])
        card_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        card_inner.grid_columnconfigure(0, weight=1)

        ui_label(card_inner, "유형", "body_bold", COLORS["text_muted"]).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.type_var = tk.StringVar()
        if ctk:
            self.type_entry = ctk.CTkEntry(
                card_inner, textvariable=self.type_var, height=42,
                font=FONTS["body"], fg_color=COLORS["input_bg"], text_color=COLORS["text"],
                border_color=COLORS["input_border"], corner_radius=10,
            )
        else:
            self.type_entry = tk.Entry(
                card_inner, textvariable=self.type_var, font=FONTS["body"],
                bg=COLORS["input_bg"], fg=COLORS["text"],
                highlightbackground=COLORS["input_border"], highlightthickness=1,
            )
        self.type_entry.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self.type_entry.bind("<Return>", lambda e: self.register())
        self.type_entry.focus()

        ui_label(card_inner, "사이트 주소", "body_bold", COLORS["text_muted"]).grid(
            row=2, column=0, sticky="w", pady=(0, 4))
        ui_label(
            card_inner,
            "한 줄에 URL 하나 · Enter 줄바꿈 · Ctrl+Enter 등록",
            "caption",
            COLORS["text_light"],
        ).grid(row=3, column=0, sticky="w", pady=(0, 8))

        url_box = ui_frame(card_inner, COLORS["card"])
        url_box.grid(row=4, column=0, sticky="ew", pady=(0, 8), padx=16)
        url_box.grid_columnconfigure(0, weight=1)

        if ctk:
            self.site_text = ctk.CTkTextbox(
                url_box, wrap="char", font=FONTS["mono"],
                height=140, fg_color=COLORS["input_bg"], text_color=COLORS["text"],
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

        preview_header = ui_frame(card_inner, COLORS["card"])
        preview_header.grid(row=5, column=0, sticky="ew", pady=(4, 6))
        ui_label(preview_header, "등록 예정 URL", "body_bold", COLORS["text_muted"]).pack(side=tk.LEFT)
        self.url_count_label = ui_label(preview_header, "0개", "badge", COLORS["accent"])
        self.url_count_label.pack(side=tk.RIGHT)

        if ctk:
            self.url_preview = ctk.CTkTextbox(
                card_inner, wrap="char", font=FONTS["mono"], height=110,
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
        self.url_preview.grid(row=6, column=0, sticky="ew", pady=(0, 16), padx=16)

        ui_label(card_inner, "신고 원고", "body_bold", COLORS["text_muted"]).grid(row=7, column=0, sticky="w", pady=(0, 10))
        tpl_frame = ui_frame(card_inner, COLORS["card"])
        tpl_frame.grid(row=8, column=0, sticky="ew", pady=(0, 8))
        tpl_frame.grid_columnconfigure(0, weight=1)
        tpl_frame.grid_columnconfigure(1, weight=1)

        self.template_var = tk.StringVar()
        self.tpl_buttons = {}
        self.tpl_frame = tpl_frame
        self._build_template_buttons()

        btn_frame = ui_frame(main, COLORS["bg"])
        btn_frame.grid(row=2, column=0, sticky="e", pady=(20, 0))
        ui_button(btn_frame, "취소", "ghost", width=110, command=self.top.destroy).pack(side=tk.RIGHT, padx=(10, 0))
        ui_button(btn_frame, "등록", "primary", width=110, command=self.register).pack(side=tk.RIGHT)

        self.site_text.bind("<KeyRelease>", lambda e: self._update_url_preview())
        self.site_text.bind("<Control-Return>", lambda e: self.register())
        self._update_url_preview()

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

        cols = 2
        for idx, (tid, title) in enumerate(options):
            row, col = divmod(idx, cols)
            active = tid == self.template_var.get()
            if ctk:
                btn = ctk.CTkButton(
                    self.tpl_frame, text=title, height=44,
                    font=FONTS["body_bold"] if active else FONTS["body"],
                    fg_color=COLORS["accent"] if active else COLORS["input_bg"],
                    hover_color=COLORS["accent_hover"] if active else COLORS["border"],
                    text_color="#ffffff" if active else COLORS["text"],
                    corner_radius=10,
                    command=lambda n=tid: self._pick_template(n),
                )
            else:
                btn = tk.Button(
                    self.tpl_frame, text=title, height=2,
                    font=FONTS["body_bold"] if active else FONTS["body"],
                    bg=COLORS["accent"] if active else COLORS["input_bg"],
                    fg="#ffffff" if active else COLORS["text"],
                    relief=tk.FLAT,
                    command=lambda n=tid: self._pick_template(n),
                )
            pad_left = 0 if col == 0 else 6
            pad_right = 6 if col == 0 else 0
            btn.grid(row=row, column=col, sticky="ew", padx=(pad_left, pad_right), pady=4)
            self.tpl_buttons[tid] = btn

    def _pick_template(self, name):
        self.template_var.set(name)
        self._on_tpl_select(name)

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
        sites = self._parse_site_lines()
        count = len(sites)
        if ctk and isinstance(self.url_count_label, ctk.CTkLabel):
            self.url_count_label.configure(
                text=f"{count}개",
                fg_color=COLORS["accent_light"] if count else COLORS["border"],
                text_color=COLORS["accent"] if count else COLORS["text_muted"],
            )
        else:
            self.url_count_label.configure(text=f"{count}개")

        if not sites:
            self._set_preview_text("URL을 입력하면 여기에 번호와 함께 표시됩니다.")
            return

        lines = []
        for idx, site in enumerate(sites, 1):
            lines.append(f"  {idx:02d}  {self._short_url(site)}")
        self._set_preview_text("\n".join(lines))

    def center_window(self, parent):
        self.top.update_idletasks()
        width, height = 640, 880
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        x = parent_x + (parent_w - width) // 2
        y = parent_y + (parent_h - height) // 2
        self.top.geometry(f"{width}x{height}+{x}+{y}")

    def _site_text_content(self):
        if ctk and isinstance(self.site_text, ctk.CTkTextbox):
            return self.site_text.get("1.0", tk.END).strip()
        return self.site_text.get("1.0", tk.END).strip()

    def register(self):
        report_type = self.type_var.get().strip()
        template_choice = self.template_var.get()

        if not report_type:
            messagebox.showwarning("입력 필요", "유형을 입력해주세요.")
            return

        sites = self._parse_site_lines()
        if not sites:
            messagebox.showwarning("입력 필요", "사이트 주소를 입력해주세요.")
            return

        template = self.app.get_template_text(template_choice)
        if not template:
            messagebox.showwarning("원본 없음", "해당 원본 신고 내용이 비어 있습니다.")
            return

        for site in sites:
            self.app.add_task(site, report_type, template, template_choice)

        self.app.log(f"일괄 등록 완료: {len(sites)}개 URL")
        self.app.root.update_idletasks()
        self.top.destroy()


class ReportApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Naver Report · 사이트 자동 신고")
        self.root.geometry("1520x960")
        self.root.minsize(1280, 800)
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

        self.hidden_results = {}
        self.tasks = []
        self.templates = []
        self._editing_template_id = None

        self.sidebar = SidebarNav(self.root, self.on_tab_change)

        self.content = ui_frame(self.root, COLORS["bg"])
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.page_header = PageHeader(self.content)

        self.pages_container = ui_frame(self.content, COLORS["bg"])
        self.pages_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        self.pages = {}
        for name in ["Home", "신고 원본", "리라이트 결과", "Settings", "실행 로그"]:
            page = ui_frame(self.pages_container, COLORS["bg"])
            page.pack(fill=tk.BOTH, expand=True)
            self.pages[name] = page

        self.load_templates()
        self.build_home_tab(self.pages["Home"])
        self.build_templates_tab(self.pages["신고 원본"])
        self.build_results_tab(self.pages["리라이트 결과"])
        self.build_settings_tab(self.pages["Settings"])
        self.build_log_tab(self.pages["실행 로그"])

        for name, page in self.pages.items():
            if name != "Home":
                page.pack_forget()

        self.tabs = self.sidebar  # compat: preview_all / start_report call self.tabs.select()

        self.accounts = []
        self.load_settings()
        self.load_accounts()
        self.load_results()
        self.load_tasks()
        self._report_running = False
        self._report_stop_requested = False
        self._active_reporter = None
        self.page_header.set("Home")

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

    def _frame(self, parent, bg=None):
        return ui_frame(parent, bg or COLORS["bg"])

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
        self.stop_report_btn = ui_button(btn_frame, "신고 정지", "danger", height=44, command=self.stop_report)
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

        tree = ttk.Treeview(parent, columns=("no", "report_type", "site", "template_name"),
                            show="headings", style="Task.Treeview")
        tree.heading("no", text="No.")
        tree.heading("report_type", text="유형")
        tree.heading("site", text="사이트")
        tree.heading("template_name", text="원고")
        tree.column("no", width=50, anchor="center")
        tree.column("report_type", width=100, anchor="center")
        tree.column("site", width=500, anchor="w")
        tree.column("template_name", width=120, anchor="center")
        tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=sb.set)
        tree.bind("<Delete>", lambda e: self.delete_selected_task())
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
            columns=("datetime", "account", "site", "report_type", "site_count", "original", "rewritten"),
            show="headings", style="Preview.Treeview",
        )
        tree.heading("datetime", text="생성 시간")
        tree.heading("account", text="사용 계정")
        tree.heading("site", text="사이트")
        tree.heading("report_type", text="유형")
        tree.heading("site_count", text="사이트 신고")
        tree.heading("original", text="원본 신고 내용")
        tree.heading("rewritten", text="리라이트 된 내용")
        tree.column("datetime", width=110, anchor="center")
        tree.column("account", width=100, anchor="center")
        tree.column("site", width=160, anchor="w")
        tree.column("report_type", width=70, anchor="center")
        tree.column("site_count", width=80, anchor="center")
        tree.column("original", width=260, anchor="w")
        tree.column("rewritten", width=260, anchor="w")
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

        self.account_tree = ttk.Treeview(tree_frame, columns=("id", "password"),
                                         show="headings", style="Account.Treeview")
        self.account_tree.heading("id", text="아이디")
        self.account_tree.heading("password", text="비밀번호")
        self.account_tree.column("id", width=150, anchor="center")
        self.account_tree.column("password", width=220, anchor="w")
        self.account_tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.account_tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.account_tree.configure(yscrollcommand=sb.set)
        self.account_tree.bind("<Delete>", lambda e: self.delete_selected_account())

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
    def build_log_tab(self, parent):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        card = self._card(parent)
        card.pack(fill=tk.BOTH, expand=True)
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        self._section_label(card, "실행 로그", row=0, pady=(16, 12))

        if ctk:
            self.log_text = ctk.CTkTextbox(
                card, wrap=tk.WORD, font=FONTS["mono"],
                fg_color=COLORS["preview_bg"], text_color=COLORS["text"],
                border_color=COLORS["border"], border_width=1,
                corner_radius=10, state=tk.DISABLED,
            )
        else:
            self.log_text = tk.Text(
                card, wrap=tk.WORD, font=FONTS["mono"],
                bg=COLORS["preview_bg"], fg=COLORS["text"],
                insertbackground=COLORS["text"], state=tk.DISABLED,
            )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

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
            except Exception:
                pass

    def save_settings(self):
        data = {
            "api_key": self.api_key_var.get().strip(),
            "model": self.model_var.get(),
            "hagrid_mode": bool(self.hagrid_mode_var.get()) if hasattr(self, "hagrid_mode_var") else False,
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
        self.refresh_task_list()

    def save_tasks(self):
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.tasks, f, ensure_ascii=False, indent=2)

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

    def add_task(self, site, report_type, template, template_name=None):
        if template_name is None:
            options = self.get_template_options()
            template_name = options[0][0] if options else ""
        self.tasks.append({
            "site": site,
            "report_type": report_type,
            "template": template,
            "template_name": template_name,
        })
        self.save_tasks()
        self.refresh_task_list()
        self.log(f"등록: [{report_type}] {site}")

    def refresh_task_list(self):
        for item in self.task_tree.get_children():
            self.task_tree.delete(item)
        for idx, task in enumerate(self.tasks, 1):
            self.task_tree.insert("", tk.END, values=(
                idx,
                task.get("report_type", ""),
                task.get("site", ""),
                self.get_template_title(task.get("template_name", "")),
            ))
        self.task_count_label.configure(text=f"{len(self.tasks)}개")

    def delete_selected_task(self):
        selected = self.task_tree.selection()
        if not selected:
            messagebox.showwarning("선택 오류", "삭제할 항목을 선택해주세요.")
            return
        idx = self.task_tree.index(selected[0])
        del self.tasks[idx]
        self.save_tasks()
        self.refresh_task_list()
        self.log("항목 삭제 완료")

    def refresh_account_list(self):
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)
        for acc in self.accounts:
            self.account_tree.insert("", tk.END, values=(acc.get("id", ""), acc.get("password", "")))

    def open_register_window(self):
        RegisterWindow(self.root, self)

    def toggle_api_visibility(self):
        current = self.api_key_entry.cget("show")
        if current == "*":
            self.api_key_entry.configure(show="")
            self.show_api_btn.configure(text="숨김")
        else:
            self.api_key_entry.configure(show="*")
            self.show_api_btn.configure(text="표시")

    def log(self, message):
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
        naver_id = self.account_tree.item(selected[0])["values"][0]
        self.accounts = [acc for acc in self.accounts if acc["id"] != naver_id]
        self.save_accounts()
        self.refresh_account_list()
        self.log(f"계정 삭제 완료: {naver_id}")

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

    def insert_preview(self, site, report_type, original, rewritten, dt=None, account_id=None, status=None):
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
        self.results_tree.insert("", tk.END, values=(
            dt, account_id, site, report_type, site_count,
            self._truncate(original, 45), self._truncate(display_rewritten, 45)),
            tags=tags)
        self.refresh_site_stats_panel()
        selected = self.results_tree.selection()
        if not selected:
            return
        row = self.results_tree.item(selected[0])["values"]
        if len(row) < 4:
            return
        dt, account_id, site, report_type = row[0], row[1], row[2], row[3]
        tags = self.results_tree.item(selected[0])["tags"]
        if not tags:
            return
        if tags[0] == "protected":
            site, report_type, original, rewritten = tags[1], tags[2], tags[3], tags[4]
        else:
            site, report_type, original, rewritten = tags[0], tags[1], tags[2], tags[3]
        account_password = self.get_account_password_for_result(dt, account_id, site, report_type)
        DetailWindow(
            self.root, site, report_type, original, rewritten,
            account_id=account_id, account_password=account_password,
        )

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

    def _disable_buttons(self, for_report: bool = False):
        try:
            self.preview_btn.configure(state=tk.DISABLED)
        except Exception:
            pass
        try:
            self.report_btn.configure(state=tk.DISABLED)
        except Exception:
            pass
        if for_report:
            try:
                self.stop_report_btn.configure(state=tk.NORMAL)
            except Exception:
                pass

    def _enable_buttons(self):
        try:
            self.preview_btn.configure(state=tk.NORMAL)
        except Exception:
            pass
        try:
            self.report_btn.configure(state=tk.NORMAL)
        except Exception:
            pass
        try:
            self.stop_report_btn.configure(state=tk.DISABLED)
        except Exception:
            pass

    def stop_report(self):
        if not self._report_running:
            return
        self._report_stop_requested = True
        self.log("[정지] 신고 작업을 중단합니다...")
        try:
            self.stop_report_btn.configure(state=tk.DISABLED)
        except Exception:
            pass
        if self._active_reporter:
            self._active_reporter.request_cancel()

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
        self._disable_buttons()

        def run():
            for task in self.tasks:
                results = self.generate_variants(task["site"], task["report_type"], [task["template"]], api_key, self.model_var.get())
                for url, data in results.items():
                    self._add_result(url, task["report_type"], data)
            self.root.after(0, self._enable_buttons)
            self.root.after(0, lambda: self.log("[미리보기] 완료"))
            self.root.after(0, self.save_results)
            self.root.after(0, lambda: self.tabs.select("리라이트 결과"))
            self.root.after(0, self.refresh_results_tree)

        threading.Thread(target=run, daemon=True).start()

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
        self.log("=" * 55)
        self.log(f"신고 시작 | 항목:{len(self.tasks)}개, 계정:{len(self.accounts)}개, 총:{total}개")
        self._report_running = True
        self._report_stop_requested = False
        self._active_reporter = None
        self._disable_buttons(for_report=True)
        self.progress["value"] = 0

        def on_log(message):
            self.root.after(0, lambda: self.log(message))

        def on_result(item):
            status = item.get("status", "")
            data = {
                "original": item["original"],
                "rewritten": item["rewritten"],
                "status": status,
                "account_password": item.get("account_password", ""),
            }
            dt = self._add_result(item["site"], item["report_type"], data, item["account_id"])
            self.root.after(
                0,
                lambda s=item["site"], rt=item["report_type"], o=item["original"], r=item["rewritten"],
                       d=dt, a=item["account_id"], st=status:
                self.insert_preview(s, rt, o, r, d, a, st)
            )

        current = [0]
        def on_progress(delta):
            current[0] += delta
            self.root.after(0, lambda c=current[0]: self.progress.configure(value=min(c / total * 100, 100)))

        def run():
            stopped = False
            for account in self.accounts:
                if self._report_stop_requested:
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
                self._active_reporter = reporter
                try:
                    reporter.report(account_id, account["password"], self.tasks)
                    if reporter.cancel_requested or self._report_stop_requested:
                        stopped = True
                except Exception as e:
                    on_log(f"[{account_id}] 처리 오류: {e}")
                finally:
                    self._active_reporter = None
                on_log(f"[계정 완료] {account_id}")
                if self._report_stop_requested:
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
        self._report_stop_requested = False
        self._active_reporter = None
        self._enable_buttons()
        if not stopped:
            self.progress.configure(value=100)
        self.log("=" * 55)
        if stopped:
            self.log("신고 작업이 중단되었습니다.")
        else:
            self.log("신고 내용 생성 완료")
        stats = self.compute_site_report_stats()
        protected_accounts = set()
        for info in stats.values():
            protected_accounts.update(info["protected_accounts"])
        if protected_accounts:
            self.log(f"보호조치 제외 계정 (신고 횟수 미포함): {', '.join(sorted(protected_accounts))}")
        for site, info in sorted(stats.items(), key=lambda x: -x[1]["valid"]):
            if info["valid"] or info["protected"]:
                msg = f"[집계] {self._truncate(site, 60)} — 신고 {info['valid']}회"
                if info["protected"]:
                    msg += f", 보호조치 {info['protected']}건 제외"
                self.log(msg)
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
            tags = (data["site"], data["report_type"], data["original"], data["rewritten"])
            if status == "protected":
                tags = ("protected", data["site"], data["report_type"], data["original"], data["rewritten"])
            self.results_tree.insert("", tk.END, values=(
                dt, account_id, site, data["report_type"], site_count,
                self._truncate(data["original"], 45), self._truncate(display_rewritten, 45)),
                tags=tags)

    def delete_selected_result(self):
        selected = self.results_tree.selection()
        if not selected:
            return
        values = self.results_tree.item(selected[0])["values"]
        dt, account, site, rt = values[0], values[1], values[2], values[3]
        matched = None
        for key, data in self.hidden_results.items():
            if (data.get("datetime") == dt and data.get("account_id", "") == account
                    and data.get("site") == site and data.get("report_type") == rt):
                matched = key
                break
        if matched:
            del self.hidden_results[matched]
            self.save_results()
            self.refresh_results_tree(self.search_var.get())
            self.log(f"결과 삭제: {site}")

    def filter_results(self):
        self.refresh_results_tree(self.search_var.get())

    def clear_filter(self):
        self.search_var.set("")
        self.refresh_results_tree()


if __name__ == "__main__":
    root = ctk.CTk() if ctk else tk.Tk()
    app = ReportApp(root)
    root.mainloop()
