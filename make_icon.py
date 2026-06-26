"""Windows exe / Explorer용 ICO 생성."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
PNG = ASSETS / "app_icon.png"
ICO = ASSETS / "app_icon.ico"


def build_ico():
    ASSETS.mkdir(exist_ok=True)
    if not PNG.is_file():
        raise SystemExit(f"원본 이미지 없음: {PNG}")

    src = Image.open(PNG).convert("RGBA")
    w, h = src.size
    side = min(w, h)
    src = src.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))

    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = src.resize((256, 256), Image.Resampling.LANCZOS)
    base.save(
        ICO,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    print(f"ICO 생성: {ICO}")


if __name__ == "__main__":
    build_ico()
