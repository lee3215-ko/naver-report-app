"""???怨몃뮔櫻????ш낄猷???嚥▲굧???뚪뜮?(??醫딆┻?믩베???/ PyInstaller exe ????댁봺??."""
import os
import shutil
import sys

APP_NAME = "NaverReport"
APP_VERSION = "1.0.8"
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
    """?????덊떀 ??????????run.py)???????됲닓 ?????"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir() -> str:
    """???繹먮냱?녑땱?뀐폍???影??낟???????????????????????????(exe ??data/)."""
    data_dir = os.path.join(get_app_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def data_path(filename: str) -> str:
    return os.path.join(get_data_dir(), filename)


def migrate_legacy_data():
    """????ㅼ굣???筌???????猷매?댚??json) ??data/ ?????筌???熬?留?????ㅼ굣??"""
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
    """?????????됰Ŧ??????쎈뼔??낅읇????????????????潁??용끏???"""
    os.chdir(get_app_dir())
    migrate_legacy_data()



