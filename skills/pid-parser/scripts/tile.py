# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
"""Split a P&ID image into overlapping tiles with a coordinate grid.

Grid labels are in original image pixels, so a box read off any tile is
already in the coordinates graph.json expects.

Usage: tile.py <image> <outdir>
"""

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

MAX_SIDE = 3600  # downscale huge sheets before tiling
TILE = 1200  # tile size in working pixels
OVERLAP = 150
GRID_COLOR = (0, 170, 200)


def grid_step(scale):
    """Grid spacing in original pixels, about 100 working pixels apart."""
    raw = 100 / scale
    for step in (25, 50, 100, 200, 250, 500, 1000):
        if step >= raw:
            return step
    return 1000


def draw_grid(img, x0, y0, scale, step):
    """Draw grid lines for original-pixel multiples of step on a crop at (x0, y0)."""
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    ox, oy = x0 / scale, y0 / scale
    gx = math.ceil(ox / step) * step
    while (gx - ox) * scale < w:
        px = (gx - ox) * scale
        draw.line([(px, 0), (px, h)], fill=GRID_COLOR + (110,), width=1)
        draw.text((px + 2, 2), str(gx), fill=GRID_COLOR + (255,))
        draw.text((px + 2, h - 12), str(gx), fill=GRID_COLOR + (255,))
        gx += step
    gy = math.ceil(oy / step) * step
    while (gy - oy) * scale < h:
        py = (gy - oy) * scale
        draw.line([(0, py), (w, py)], fill=GRID_COLOR + (110,), width=1)
        draw.text((2, py + 2), str(gy), fill=GRID_COLOR + (255,))
        draw.text((w - 40, py + 2), str(gy), fill=GRID_COLOR + (255,))
        gy += step


def starts(length):
    if length <= TILE:
        return [0]
    n = math.ceil((length - OVERLAP) / (TILE - OVERLAP))
    stride = (length - TILE) / (n - 1)
    return [round(i * stride) for i in range(n)]


def main(src, outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    orig = Image.open(src).convert("RGB")
    width, height = orig.size
    scale = min(1.0, MAX_SIDE / max(width, height))
    work = orig.resize((round(width * scale), round(height * scale)), Image.LANCZOS) if scale < 1 else orig

    ov_scale = min(1.0, 1600 / max(width, height))
    overview = orig.resize((round(width * ov_scale), round(height * ov_scale)), Image.LANCZOS)
    draw_grid(overview, 0, 0, ov_scale, grid_step(ov_scale) * 2)
    overview.save(out / "overview.png")

    tiles = []
    for r, y in enumerate(starts(work.height)):
        for c, x in enumerate(starts(work.width)):
            crop = work.crop((x, y, min(x + TILE, work.width), min(y + TILE, work.height)))
            draw_grid(crop, x, y, scale, grid_step(scale))
            name = f"tile_{r}_{c}.png"
            crop.save(out / name)
            box = [
                round(x / scale),
                round(y / scale),
                round((x + crop.width) / scale),
                round((y + crop.height) / scale),
            ]
            tiles.append({"file": name, "box_original_px": box})

    meta = {"image": str(src), "width": width, "height": height, "tiles": tiles}
    (out / "tiles.json").write_text(json.dumps(meta, indent=2))
    print(f"{width}x{height} -> overview.png + {len(tiles)} tiles in {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
