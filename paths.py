"""????⑤챶裕붹セ??????꾤뙴????β뼯援????る쑏?(???ル봿??誘⑸쿋???/ PyInstaller exe ?????곷뉴??."""
import os
import shutil
import sys

APP_NAME = "NaverReport"
APP_VERSION = "1.0.9"
UPDATE_VERSION_URL = (
    "https://raw.githubusercontent.com/lee3215-ko/naver-report-app/main/version.json"
)
DATA_FILES = (
    "accounts.json",
    "settings.json",
    "results.json",
    "tasks.json",
    "templates.json",
    "cafe_keywords.json",
    "cafe_results.json",
    "cafe_collected.json",
)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def get_app_dir() -> str:
    """??????딅? ??????????run.py)????????뀀땽 ?????"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir() -> str:
    """???濚밸Ŧ???묐빋??먰룏???壤굿??????????????????????????????(exe ??data/)."""
    data_dir = os.path.join(get_app_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def data_path(filename: str) -> str:
    return os.path.join(get_data_dir(), filename)


def migrate_legacy_data():
    """?????쇨덫???嶺????????룸ℓ????json) ??data/ ?????嶺?????筌??????쇨덫??"""
    app_dir = get_app_dir()
    data_dir = get_data_dir()
    for name in DATA_FILES:
        legacy = os.path.join(app_dir, name)
        target = os.path.join(data_dir, name)
        if os.path.isfile(legacy) and not os.path.isfile(target):
            shutil.copy2(legacy, target)


def get_resource_path(*parts: str) -> str:
    if is_frozen():
        base = getattr(sys, "_MEIPASS", get_app_dir())
    else:
        base = get_app_dir()
    return os.path.join(base, *parts)


def get_icon_path() -> str | None:
    ico = get_resource_path("assets", "app_icon.ico")
    if os.path.isfile(ico):
        return ico
    return None


def init_runtime_paths():
    """??????????거???????덈폇???낆쓦????????????????逆???⑸걦???"""
    os.chdir(get_app_dir())
    migrate_legacy_data()



