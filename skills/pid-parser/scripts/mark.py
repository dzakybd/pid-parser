# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
"""Draw each node's id on the tiles so connections can be read by id.

Writes marked_<tile>.png next to each tile and marked_overview.png.

Usage: mark.py <graph.json> <tiles_dir>
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

COLOR = (220, 30, 30)


def draw(img, nodes, x0, y0, scale):
    d = ImageDraw.Draw(img)
    w = max(1, round(2 * scale))
    for n in nodes:
        x1, y1, x2, y2 = [v * scale for v in n["bbox"]]
        x1, x2, y1, y2 = x1 - x0, x2 - x0, y1 - y0, y2 - y0
        if x2 < 0 or y2 < 0 or x1 > img.width or y1 > img.height:
            continue
        d.rectangle((x1, y1, x2, y2), outline=COLOR, width=w)
        label = n["id"]
        tx, ty = x1, max(0, y1 - 12)
        tw = d.textlength(label)
        d.rectangle((tx, ty, tx + tw + 2, ty + 11), fill=(255, 255, 255))
        d.text((tx + 1, ty), label, fill=COLOR)


def main(graph_path, tiles_dir):
    graph = json.loads(Path(graph_path).read_text())
    nodes = [n for n in graph["nodes"] if n["type"] != "junction"]
    tiles = Path(tiles_dir)
    meta = json.loads((tiles / "tiles.json").read_text())
    for t in meta["tiles"]:
        img = Image.open(tiles / t["file"]).convert("RGB")
        bx1, by1, bx2, _ = t["box_original_px"]
        scale = img.width / (bx2 - bx1)
        draw(img, nodes, bx1 * scale, by1 * scale, scale)
        img.save(tiles / f"marked_{t['file']}")
    ov = Image.open(tiles / "overview.png").convert("RGB")
    draw(ov, nodes, 0, 0, ov.width / meta["width"])
    ov.save(tiles / "marked_overview.png")
    print(f"marked {len(nodes)} nodes on {len(meta['tiles'])} tiles in {tiles}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
