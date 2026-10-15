"""connect.py sanity check on a drawn image: a tee of three symbols, a line broken by a valve, a lone symbol."""

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/pid-parser/scripts"))
from connect import add_networks, networks

BOXES = {
    "a": (20, 90, 40, 110),
    "b": (160, 20, 180, 40),
    "c": (160, 160, 180, 180),
    "v": (230, 90, 250, 110),  # inline valve
    "d": (320, 90, 340, 110),
    "z": (20, 250, 40, 270),  # alone
}


def main():
    img = Image.new("L", (400, 300), 255)
    draw = ImageDraw.Draw(img)
    for box in BOXES.values():
        draw.rectangle(box, outline=0)
    draw.line([(40, 100), (170, 100)], fill=0, width=2)  # a to the tee
    draw.line([(170, 40), (170, 160)], fill=0, width=2)  # b - tee - c
    draw.line([(170, 100), (230, 100)], fill=0, width=2)  # tee to the valve
    draw.line([(250, 100), (320, 100)], fill=0, width=2)  # valve to d
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pid.png"
        img.save(path)
        nets = networks(path, BOXES)
    assert sorted(map(sorted, nets)) == [["a", "b", "c", "v"], ["d", "v"]], nets
    graph = {"nodes": [{"id": k, "type": "valve", "tag": None, "bbox": list(b)} for k, b in BOXES.items()], "edges": []}
    add_networks(graph, nets)
    assert sum(n["type"] == "junction" for n in graph["nodes"]) == 1  # the 4-symbol network
    assert len(graph["edges"]) == 5  # 4 spokes + the d-v edge
    print("connect OK", json.dumps(graph["edges"][-1]))


if __name__ == "__main__":
    main()
