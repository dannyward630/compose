"""Cut a rendered design into images a Jev request accepts (280 to 1568 pixels a side), for compose's figma judge.

`python -m jev_ultrafast.tiles <src> <out_dir> <stem> <tiles_max>` prints the tile file names, top first, as one JSON list.
A frame wider than 1568 is shrunk to that width; a taller one is cut top to bottom into at most `tiles_max` tiles of at most
1568 each, shrunk further only when that is not enough, so its text stays readable. Transparency and a side under 280 are filled white.
"""
import json
import sys
from pathlib import Path

from PIL import Image

EDGE_MIN, EDGE_MAX = 280, 1568
BACKGROUND = (255, 255, 255)


def tiles(src, out_dir, stem, tiles_max):
    with Image.open(src) as opened:
        img = Image.new("RGBA", opened.size, BACKGROUND + (255,))
        img.alpha_composite(opened.convert("RGBA"))
    img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, EDGE_MAX / w, tiles_max * EDGE_MAX / h)
    if scale < 1:
        w, h = max(1, round(w * scale)), max(1, round(h * scale))
        img = img.resize((w, h), Image.LANCZOS)
    n = -(-h // EDGE_MAX)
    names = []
    for k in range(n):
        tile = img.crop((0, k * h // n, w, (k + 1) * h // n))
        if min(tile.size) < EDGE_MIN:
            padded = Image.new("RGB", (max(tile.width, EDGE_MIN), max(tile.height, EDGE_MIN)), BACKGROUND)
            padded.paste(tile, (0, 0))
            tile = padded
        name = f"{stem}.png" if n == 1 else f"{stem}.{k + 1}.png"
        tile.save(Path(out_dir) / name)
        names.append(name)
    return names


if __name__ == "__main__":
    src, out_dir, stem, tiles_max = sys.argv[1:5]
    print(json.dumps(tiles(src, out_dir, stem, int(tiles_max))))
