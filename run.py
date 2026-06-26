"""네이버 사이트 자동 신고 프로그램 실행 진입점."""
from paths import init_runtime_paths, get_icon_path, APP_VERSION, UPDATE_VERSION_URL, APP_NAME

init_runtime_paths()


def _preload_frozen_deps():
    """PyInstaller exe에서 Selenium 등 동적 import 누락 방지."""
    import selenium.webdriver.chrome.webdriver  # noqa: F401
    import selenium.webdriver.chrome.service  # noqa: F401
    import selenium.webdriver.chrome.options  # noqa: F401
    import selenium.webdriver.remote.webdriver  # noqa: F401
    import webdriver_manager.chrome  # noqa: F401


_preload_frozen_deps()

from app import ReportApp
try:
    import customtkinter as ctk
except ImportError:
    ctk = None

if __name__ == "__main__":
    root = ctk.CTk() if ctk else __import__("tkinter").Tk()
    icon = get_icon_path()
    if icon:
        try:
            root.iconbitmap(default=icon)
        except Exception:
            pass
    app = ReportApp(root)
    from update_ui import schedule_update_check

    schedule_update_check(
        root,
        version_url=UPDATE_VERSION_URL,
        current_version=APP_VERSION,
        app_name=APP_NAME,
        exe_name="NaverReport.exe",
        zip_inner_folder="NaverReport",
        log_callback=app.log,
    )
    root.mainloop()
