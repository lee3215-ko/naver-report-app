"""??댁슜竊???袁㏃댉 ?롪퍔?δ빳?(?띠룇裕녻?/ PyInstaller exe ??ㅻ쾹??."""
import os
import shutil
import sys

APP_NAME = "NaverReport"
APP_VERSION = "1.0.6"
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
    """???덈뺄 ???逾????裕?run.py)?????덈츎 ?????"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir() -> str:
    """???깆젧鸚룸슙??ｌ뫒??덉???얜???????⑤????????????(exe ??data/)."""
    data_dir = os.path.join(get_app_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def data_path(filename: str) -> str:
    return os.path.join(get_data_dir(), filename)


def migrate_legacy_data():
    """??怨몄쓧 ?뺢퀗????猷먮쳜??json) ??data/ ?????뺢퀡?꾢퐲???怨몄쓧."""
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
    """??얜?????븐뼚???⑤틲遊뷴ㅇ??⑥щ턄????????貫?껆뵳??"""
    os.chdir(get_app_dir())
    migrate_legacy_data()



