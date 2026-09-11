"""신고용 브라우저: 설치된 Chrome/Edge를 직접 실행한 뒤 Selenium만 연결합니다."""
import os
import re
import socket
import subprocess
import time
import urllib.request
import winreg

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from paths import get_data_dir

BROWSER_MODE_LABELS = {
    "chrome": "기존 Chrome",
    "chrome_real": "실제 Chrome",
    "edge": "Microsoft Edge",
}
DEFAULT_BROWSER_MODE = "chrome_real"

_CHROME_REG_KEYS = (
    (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Google\Chrome\BLBeacon"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Google\Chrome\BLBeacon"),
)
_EDGE_REG_KEYS = (
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Edge\BLBeacon"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Edge\BLBeacon"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Edge\BLBeacon"),
)

# 가짜 플러그인/코어 수/UA 덮어쓰기는 실제 Chrome과 어긋나 더 잘 탐지됩니다.
# webdriver 표시만 페이지 로드 전에 가립니다.
_STEALTH_JS = r"""
(() => {
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      get: () => undefined,
      configurable: true,
    });
  } catch (e) {}
  try { delete Navigator.prototype.webdriver; } catch (e) {}
})();
"""


def normalize_browser_mode(mode: str) -> str:
    if mode in BROWSER_MODE_LABELS:
        return mode
    for key, label in BROWSER_MODE_LABELS.items():
        if mode == label:
            return key
    return DEFAULT_BROWSER_MODE


def browser_mode_label(mode: str) -> str:
    return BROWSER_MODE_LABELS.get(normalize_browser_mode(mode), BROWSER_MODE_LABELS[DEFAULT_BROWSER_MODE])


def _read_reg_version(keys) -> str:
    try:
        for hive, key_path in keys:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    version, _ = winreg.QueryValueEx(key, "version")
                if version:
                    return str(version)
            except OSError:
                continue
    except Exception:
        pass
    return ""


def _version_from_app_dir(binary: str) -> str:
    if not binary:
        return ""
    app_dir = os.path.dirname(binary)
    try:
        versions = [
            name for name in os.listdir(app_dir)
            if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", name)
            and os.path.isdir(os.path.join(app_dir, name))
        ]
        if versions:
            return sorted(versions, key=lambda v: [int(p) for p in v.split(".")])[-1]
    except OSError:
        pass
    return ""


def find_chrome_binary() -> str:
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                     "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def find_edge_binary() -> str:
    candidates = [
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                     "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def get_chrome_version(binary: str = "") -> str:
    return _read_reg_version(_CHROME_REG_KEYS) or _version_from_app_dir(binary or find_chrome_binary())


def get_edge_version(binary: str = "") -> str:
    return _read_reg_version(_EDGE_REG_KEYS) or _version_from_app_dir(binary or find_edge_binary())


def _profile_dir(mode: str, profile_key: str | None = None) -> str:
    name = profile_key or normalize_browser_mode(mode)
    path = os.path.join(get_data_dir(), "browser-profile", name)
    os.makedirs(path, exist_ok=True)
    return path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_devtools(port: int, timeout: float = 25.0) -> bool:
    url = f"http://127.0.0.1:{port}/json/version"
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if getattr(resp, "status", 200) == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def _launch_browser(binary: str, profile: str, port: int, headless: bool) -> subprocess.Popen:
    args = [
        binary,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        "--profile-directory=Default",
        "--lang=ko-KR",
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
    ]
    if headless:
        args.append("--headless=new")
        args.append("--window-size=1280,900")
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _hide_webdriver_if_needed(driver):
    flag = None
    try:
        flag = driver.execute_script("return navigator.webdriver")
    except Exception:
        pass
    if not flag:
        return False
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": _STEALTH_JS},
        )
    except Exception:
        pass
    try:
        driver.execute_script(_STEALTH_JS)
    except Exception:
        pass
    return True


def _attach_driver(edge: bool, port: int):
    if edge:
        options = EdgeOptions()
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
        return webdriver.Edge(
            service=EdgeService(EdgeChromiumDriverManager().install()),
            options=options,
        )
    options = ChromeOptions()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    return webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options,
    )


def _selenium_launch_fallback(mode: str, binary: str, headless: bool, profile: str):
    """연결 실패 시에만 ChromeDriver가 브라우저를 띄웁니다."""
    if mode == "edge":
        options = EdgeOptions()
        if binary:
            options.binary_location = binary
        if headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--user-data-dir={profile}")
        options.add_argument("--lang=ko-KR")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        return webdriver.Edge(
            service=EdgeService(EdgeChromiumDriverManager().install()),
            options=options,
        )
    options = ChromeOptions()
    if binary:
        options.binary_location = binary
    options.add_argument(f"--user-data-dir={profile}")
    options.add_argument("--lang=ko-KR")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    if headless:
        options.add_argument("--headless=new")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options,
    )


def quit_webdriver(driver):
    if not driver:
        return
    proc = getattr(driver, "_nr_browser_proc", None)
    try:
        driver.quit()
    except Exception:
        pass
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=6)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def create_webdriver(
    browser_mode: str = DEFAULT_BROWSER_MODE,
    headless: bool = False,
    profile_key: str | None = None,
):
    """설치된 브라우저를 직접 실행한 뒤 연결합니다. (driver, info) 반환."""
    mode = normalize_browser_mode(browser_mode)
    edge = mode == "edge"
    binary = find_edge_binary() if edge else find_chrome_binary()
    version = get_edge_version(binary) if edge else get_chrome_version(binary)
    label = BROWSER_MODE_LABELS[mode]
    profile = _profile_dir(mode, profile_key)
    launch = "attach"
    proc = None
    driver = None

    if binary:
        port = _free_port()
        try:
            proc = _launch_browser(binary, profile, port, headless)
            if not _wait_devtools(port):
                raise RuntimeError("브라우저 디버깅 포트 대기 실패")
            driver = _attach_driver(edge, port)
            driver._nr_browser_proc = proc
            driver._nr_debug_port = port
        except Exception:
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            proc = None
            launch = "selenium"
            driver = _selenium_launch_fallback(mode, binary, headless, profile)
    else:
        launch = "selenium"
        driver = _selenium_launch_fallback(mode, binary, headless, profile)

    hidden = _hide_webdriver_if_needed(driver)
    ua = ""
    wd = None
    try:
        ua = driver.execute_script("return navigator.userAgent") or ""
    except Exception:
        pass
    try:
        wd = driver.execute_script("return navigator.webdriver")
    except Exception:
        pass
    return driver, {
        "mode": mode,
        "label": label,
        "binary": binary,
        "version": version,
        "user_agent": ua,
        "webdriver_flag": wd,
        "profile": profile,
        "launch": launch,
        "webdriver_hidden": hidden,
    }
