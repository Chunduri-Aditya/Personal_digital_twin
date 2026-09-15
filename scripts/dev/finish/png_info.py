"""Print the pixel size of PNG files (run as a file). Usage: python scripts/dev/finish/png_info.py <png> [<png> ...]"""
import sys

from PIL import Image

for path in sys.argv[1:]:
    with Image.open(path) as im:
        print(f"{im.size[0]}x{im.size[1]}  {path}")
try:
    import websockets
    print("websockets", websockets.__version__)
except Exception as e:  # noqa: BLE001
    print("websockets import failed:", type(e).__name__, e)
