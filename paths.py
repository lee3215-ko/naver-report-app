"""???곸뒠塋???熬곥룂???濡ろ뜑?灌鍮?(??좊즵獒뺣끇??/ PyInstaller exe ???살씁??."""
import os
import shutil
import sys

APP_NAME = "NaverReport"
APP_VERSION = "1.0.7"
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
    """????덈틖 ????????獒?run.py)??????덉툗 ?????"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir() -> str:
    """???源놁젳勇싲８???節뚮쳮???????????????????????????(exe ??data/)."""
    data_dir = os.path.join(get_app_dir(), "data")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def data_path(filename: str) -> str:
    return os.path.join(get_data_dir(), filename)


def migrate_legacy_data():
    """???⑤챷???類??????룸Ŧ爾??json) ??data/ ?????類??袁?맪????⑤챷??"""
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
    """????????釉먮폏????ㅽ떜?딅럽????Β??????????縕?猿녿뎨??"""
    os.chdir(get_app_dir())
    migrate_legacy_data()



