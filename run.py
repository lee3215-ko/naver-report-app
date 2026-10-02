"""네이버 사이트 자동 신고 프로그램 실행 진입점."""
import threading
import time
import traceback

from paths import (
    APP_NAME,
    APP_VERSION,
    UPDATE_VERSION_URL,
    get_icon_path,
    init_runtime_paths,
    is_frozen,
    set_admin_mode,
)

init_runtime_paths()
set_admin_mode(True)


def _preload_frozen_deps():
    """PyInstaller exe에서 Selenium 등 동적 import 누락 방지."""
    import selenium.webdriver.chrome.webdriver  # noqa: F401
    import selenium.webdriver.chrome.options  # noqa: F401
    import selenium.webdriver.chrome.service  # noqa: F401
    import selenium.webdriver.remote.webdriver  # noqa: F401
    import webdriver_manager.chrome  # noqa: F401


_preload_frozen_deps()

from app import ReportApp  # noqa: E402

try:
    import customtkinter as ctk
except ImportError:
    ctk = None


class _LiveSession:
    def __init__(self):
        self.root = None
        self.app = None
        self.applied = {}
        self.pending = False
        self._busy_notified = False
        self._debounce = None


def _log(session: _LiveSession, message: str) -> None:
    print(message, flush=True)
    app = session.app
    if app is None:
        return
    try:
        app.log(message)
    except Exception:
        pass


def _build_app(session: _LiveSession, *, preserve_window: bool) -> None:
    import app as app_mod

    session.app = app_mod.ReportApp(session.root, preserve_window=preserve_window)


def _rebuild_ui(session: _LiveSession) -> None:
    import tkinter as tk

    import dev_reload

    old = session.app
    if old is not None:
        try:
            old.prepare_reload()
        except Exception:
            pass
    for child in list(session.root.winfo_children()):
        try:
            child.destroy()
        except tk.TclError:
            pass
    try:
        dev_reload.reload_ui_modules()
        _build_app(session, preserve_window=True)
    except Exception:
        _log(session, "화면 다시 그리기 실패 — 창은 유지합니다")
        print(traceback.format_exc(), flush=True)
        try:
            _build_app(session, preserve_window=True)
        except Exception:
            print(traceback.format_exc(), flush=True)


def _apply_changes(session: _LiveSession) -> None:
    import dev_reload

    session._debounce = None
    snap = dev_reload.snapshot()
    changed = dev_reload.diff(session.applied, snap)
    if not changed and not session.pending:
        return

    kinds = dev_reload.classify(changed) if changed else {"ui", "logic"}
    if kinds == {"entrypoint"} or (changed and kinds <= {"entrypoint"}):
        _log(session, "[코드] run.py/감시 모듈 변경 — 지금 창은 유지, 다음 실행부터 적용")
        session.applied = snap
        session.pending = False
        return

    compile_names = [n for n in changed if n in dev_reload.WATCH and dev_reload.WATCH[n] != "entrypoint"]
    if not compile_names and session.pending:
        compile_names = [n for n in snap if n in dev_reload.WATCH and dev_reload.WATCH[n] != "entrypoint"]
    ok, err = dev_reload.compile_files(compile_names or changed)
    if not ok:
        session.pending = True
        _log(session, f"[코드] 문법 오류라 반영하지 않았습니다 (창 유지): {err}")
        return

    app = session.app
    if app is not None and (app.is_busy() or app.has_open_dialogs()):
        session.pending = True
        if not session._busy_notified:
            session._busy_notified = True
            why = "작업 진행 중" if app.is_busy() else "다른 창이 열려 있음"
            _log(session, f"[코드] {why} — 끝나면 자동 반영합니다")
        session.root.after(1200, lambda: _apply_changes(session))
        return

    session._busy_notified = False
    if changed and kinds <= {"logic"}:
        try:
            dev_reload.reload_logic()
        except Exception:
            session.pending = True
            _log(session, "[코드] 로직 반영 실패 — 창은 유지합니다")
            print(traceback.format_exc(), flush=True)
            return
        _log(session, f"[코드] 로직 반영 (창 유지): {', '.join(changed)}")
        session.applied = snap
        session.pending = False
        return

    _rebuild_ui(session)
    session.applied = snap
    session.pending = False
    _log(session, f"[코드] 화면 반영 (창 유지): {', '.join(changed) or '대기 중이던 변경'}")


def _schedule_apply(session: _LiveSession) -> None:
    if session.root is None:
        return
    if session._debounce is not None:
        try:
            session.root.after_cancel(session._debounce)
        except Exception:
            pass
    session.pending = True
    session._debounce = session.root.after(700, lambda: _apply_changes(session))


def _start_watcher(session: _LiveSession) -> None:
    import dev_reload

    session.applied = dev_reload.snapshot()
    seen = dict(session.applied)

    def loop():
        nonlocal seen
        while True:
            time.sleep(0.6)
            try:
                snap = dev_reload.snapshot()
                if dev_reload.diff(seen, snap):
                    seen = snap
                    session.root.after(0, lambda: _schedule_apply(session))
            except Exception:
                print(traceback.format_exc(), flush=True)

    threading.Thread(target=loop, daemon=True, name="code-watch").start()


if __name__ == "__main__":
    session = _LiveSession()
    session.root = ctk.CTk() if ctk else __import__("tkinter").Tk()
    icon = get_icon_path()
    if icon:
        try:
            session.root.iconbitmap(default=icon)
        except Exception:
            pass
    session.app = ReportApp(session.root)
    from update_ui import schedule_update_check

    schedule_update_check(
        session.root,
        version_url=UPDATE_VERSION_URL,
        current_version=APP_VERSION,
        app_name=APP_NAME,
        exe_name="NaverReport.exe",
        zip_inner_folder="NaverReport",
        log_callback=lambda m: session.app.log(m) if session.app else None,
    )
    if not is_frozen():
        _start_watcher(session)
        session.app.log("개발 모드: 코드를 저장해도 프로그램을 끄지 않고 반영합니다.")
    session.root.mainloop()
