"""`python -m jev_ultrafast.tiles`: a rendered design cut into images a Jev request accepts, nothing of it lost."""

import json
import subprocess
import sys

import pytest
from PIL import Image

from jev_ultrafast.tiles import EDGE_MAX, EDGE_MIN, tiles


def render(tmp_path, w, h, mode="RGB", color=(0, 0, 0)):
    src = tmp_path / f"{w}x{h}.png"
    Image.new(mode, (w, h), color).save(src)
    return src


@pytest.mark.parametrize("size, want", [
    ((100, 40), [(280, 280)]),
    ((800, 600), [(800, 600)]),
    ((4000, 500), [(1568, 280)]),
    ((1440, 4000), [(1440, 1333), (1440, 1333), (1440, 1334)]),
    ((1000, 20000), [(314, 1568)] * 4),
])
def test_every_tile_is_inside_jevs_limits(tmp_path, size, want):
    names = tiles(render(tmp_path, *size), tmp_path, "1-2", 4)
    got = [Image.open(tmp_path / n).size for n in names]
    assert got == want
    assert all(EDGE_MIN <= side <= EDGE_MAX for s in got for side in s)


def test_tiles_run_top_to_bottom_and_keep_the_first_and_last_row(tmp_path):
    img = Image.new("RGB", (400, 4000), (0, 0, 0))
    for x in range(400):
        img.putpixel((x, 0), (255, 0, 0))
        img.putpixel((x, 3999), (0, 0, 255))
    img.save(tmp_path / "src.png")
    names = tiles(tmp_path / "src.png", tmp_path, "9-1", 4)
    assert names == ["9-1.1.png", "9-1.2.png", "9-1.3.png"]
    first, last = Image.open(tmp_path / names[0]), Image.open(tmp_path / names[-1])
    assert first.getpixel((10, 0)) == (255, 0, 0)
    assert last.getpixel((10, last.height - 1)) == (0, 0, 255)


def test_transparency_and_padding_are_white_never_black(tmp_path):
    names = tiles(render(tmp_path, 100, 40, "RGBA", (0, 0, 0, 0)), tmp_path, "t", 4)
    tile = Image.open(tmp_path / names[0])
    assert tile.mode == "RGB"
    assert tile.getpixel((5, 5)) == tile.getpixel((200, 200)) == (255, 255, 255)


def test_the_command_prints_the_tile_names(tmp_path):
    src = render(tmp_path, 600, 2000)
    out = subprocess.run([sys.executable, "-m", "jev_ultrafast.tiles", str(src), str(tmp_path), "3-4", "4"],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["3-4.1.png", "3-4.2.png"]
