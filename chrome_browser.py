"""신고용 브라우저: 기존 Chrome / 실제 Chrome / Edge."""
import os
import re
import winreg

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

BROWSER_MODE_LABELS = {
    "chrome": "기존 Chrome",
    "chrome_real": "실제 Chrome",
    "edge": "Microsoft Edge",
}
DEFAULT_BROWSER_MODE = "chrome"

LEGACY_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

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


def _apply_common_args(options, headless: bool):
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)


def apply_legacy_chrome(options: ChromeOptions, headless: bool = False) -> tuple[str, str]:
    """예전 방식: Selenium 기본 Chrome + 고정 User-Agent(126)."""
    _apply_common_args(options, headless)
    options.add_argument(f"user-agent={LEGACY_CHROME_UA}")
    return find_chrome_binary(), get_chrome_version()


def apply_real_chrome(options: ChromeOptions, headless: bool = False) -> tuple[str, str]:
    """설치된 chrome.exe를 직접 사용. 가짜 User-Agent는 넣지 않습니다."""
    binary = find_chrome_binary()
    version = get_chrome_version(binary)
    if binary:
        options.binary_location = binary
    _apply_common_args(options, headless)
    return binary, version


def apply_edge(options: EdgeOptions, headless: bool = False) -> tuple[str, str]:
    binary = find_edge_binary()
    version = get_edge_version(binary)
    if binary:
        options.binary_location = binary
    _apply_common_args(options, headless)
    return binary, version


def create_webdriver(browser_mode: str = DEFAULT_BROWSER_MODE, headless: bool = False):
    """선택한 브라우저로 WebDriver를 만듭니다. (driver, info) 반환."""
    mode = normalize_browser_mode(browser_mode)
    if mode == "edge":
        options = EdgeOptions()
        binary, version = apply_edge(options, headless)
        driver = webdriver.Edge(
            service=EdgeService(EdgeChromiumDriverManager().install()),
            options=options,
        )
        label = BROWSER_MODE_LABELS["edge"]
    else:
        options = ChromeOptions()
        if mode == "chrome_real":
            binary, version = apply_real_chrome(options, headless)
            label = BROWSER_MODE_LABELS["chrome_real"]
        else:
            binary, version = apply_legacy_chrome(options, headless)
            label = BROWSER_MODE_LABELS["chrome"]
        driver = webdriver.Chrome(
            service=ChromeService(ChromeDriverManager().install()),
            options=options,
        )

    try:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except Exception:
        pass
    ua = ""
    try:
        ua = driver.execute_script("return navigator.userAgent") or ""
    except Exception:
        pass
    return driver, {
        "mode": mode,
        "label": label,
        "binary": binary,
        "version": version,
        "user_agent": ua,
    }
