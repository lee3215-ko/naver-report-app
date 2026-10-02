"""개발 중 창을 유지한 채 .py 변경을 반영한다. (PyInstaller exe에서는 사용하지 않음)"""
from __future__ import annotations

import importlib
import os
import py_compile
from py_compile import PyCompileError

from paths import get_app_dir

WATCH = {
    "app.py": "ui",
    "ui_theme.py": "ui",
    "ui_layout.py": "ui",
    "paths.py": "ui",
    "update_ui.py": "ui",
    "naver_reporter.py": "logic",
    "chrome_browser.py": "logic",
    "naver_search_url.py": "logic",
    "run.py": "entrypoint",
    "dev_reload.py": "entrypoint",
}

_LOGIC_ORDER = ("chrome_browser", "naver_search_url", "naver_reporter")
_UI_ORDER = ("paths", "ui_theme", "ui_layout", "update_ui", "app")
_LOGIC_FILES = ("naver_reporter.py", "chrome_browser.py", "naver_search_url.py")
_logic_mtime: dict[str, float] = {}


def _app_file(name: str) -> str:
    return os.path.join(get_app_dir(), name)


def snapshot() -> dict[str, float]:
    times: dict[str, float] = {}
    for name in WATCH:
        path = _app_file(name)
        if os.path.isfile(path):
            times[name] = os.path.getmtime(path)
    return times


def diff(old: dict[str, float], new: dict[str, float]) -> list[str]:
    changed = []
    for name, mtime in new.items():
        if old.get(name) != mtime:
            changed.append(name)
    return changed


def classify(names: list[str]) -> set[str]:
    kinds: set[str] = set()
    for name in names:
        kinds.add(WATCH.get(name, "ui"))
    return kinds


def compile_files(names: list[str]) -> tuple[bool, str]:
    for name in names:
        if name not in WATCH or WATCH[name] == "entrypoint":
            continue
        path = _app_file(name)
        if not os.path.isfile(path):
            continue
        try:
            py_compile.compile(path, doraise=True)
        except PyCompileError as exc:
            return False, str(exc)
        except SyntaxError as exc:
            return False, f"{name}: {exc}"
    return True, ""


def _reload_names(mod_names: tuple[str, ...]) -> None:
    for name in mod_names:
        mod = importlib.import_module(name)
        importlib.reload(mod)


def reload_logic():
    global _logic_mtime
    snap = snapshot()
    if (
        _logic_mtime
        and all(_logic_mtime.get(name) == snap.get(name) for name in _LOGIC_FILES)
    ):
        from naver_reporter import NaverReporter

        return NaverReporter
    _reload_names(_LOGIC_ORDER)
    _logic_mtime = {name: snap.get(name, 0.0) for name in _LOGIC_FILES}
    from naver_reporter import NaverReporter

    return NaverReporter


def reload_ui_modules() -> None:
    global _logic_mtime
    _reload_names(_LOGIC_ORDER)
    _reload_names(_UI_ORDER)
    snap = snapshot()
    _logic_mtime = {name: snap.get(name, 0.0) for name in _LOGIC_FILES}
