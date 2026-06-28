# PyInstaller spec — Naver Report 배포용 (onedir: PKG 손상 방지)
import os
import certifi
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
ICON_FILE = os.path.join(SPEC_DIR, "assets", "app_icon.ico")

datas = [(ICON_FILE, "assets")] if os.path.isfile(ICON_FILE) else []
datas += [(certifi.where(), "certifi")]
binaries = []
hiddenimports = [
    "certifi",
    "customtkinter",
    "openai",
    "httpx",
    "pydantic",
    "jiter",
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.chrome",
    "selenium.webdriver.chrome.webdriver",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.remote.webdriver",
    "selenium.webdriver.remote.webelement",
    "selenium.webdriver.remote.remote_connection",
    "selenium.webdriver.common.by",
    "selenium.webdriver.common.keys",
    "selenium.webdriver.common.service",
    "selenium.webdriver.support.ui",
    "selenium.webdriver.support.expected_conditions",
    "selenium.common.exceptions",
    "webdriver_manager",
    "webdriver_manager.chrome",
    "webdriver_manager.core",
    "webdriver_manager.drivers",
    "webdriver_manager.drivers.chrome",
]

for pkg in ("customtkinter", "selenium", "webdriver_manager"):
    tmp = collect_all(pkg)
    datas += tmp[0]
    binaries += tmp[1]
    hiddenimports += tmp[2]

hiddenimports += collect_submodules("selenium.webdriver")
hiddenimports = list(dict.fromkeys(hiddenimports))

a = Analysis(
    ["run.py"],
    pathex=[SPEC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NaverReport",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_FILE if os.path.isfile(ICON_FILE) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NaverReport",
)
