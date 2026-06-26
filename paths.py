"""?援용８???꾧숲 野껋럥以?(揶쏆뮆而?/ PyInstaller exe ?⑤벏??."""
import os
import shutil
import sys

APP_NAME = "NaverReport"
APP_VERSION = "1.0.5"
UPDATE_VERSION_URL = (
    "https://raw.githubusercontent.com/lee3215-ko/naver-report-app/main/version.json"
)
DATA_FILES = (
    "accounts.json",
    "settings.json",
    "results.json",
    "tasks.json",
    "templates.json",
)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def get_app_dir() -> str:
    """??쎈뻬 ???뵬(?癒?뮉 run.py)????덈뮉 ????"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir() -> str:
    """??쇱젟夷뚧④쑴?숈쮯?臾믩씜 ???怨대럡 ????????(exe ??data/)."""
    data_dir = os.path.join(get_app_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def data_path(filename: str) -> str:
    return os.path.join(get_data_dir(), filename)


def migrate_legacy_data():
    """??곸읈 甕곌쑴???룐뫂??json) ??data/ 嚥???甕곕뜄彛???곸읈."""
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
    """?臾믩씜 ?遺얠젂?怨뺚봺夷?怨쀬뵠???????λ뜃由??"""
    os.chdir(get_app_dir())
    migrate_legacy_data()



