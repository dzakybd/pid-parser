# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow", "numpy", "scipy"]
# ///
"""Connections with traditional computer vision, no model: binarize the sheet (thresholding), erase every symbol
box, label what is left with connected-component labeling, and join the symbols that touch the same component.

A network that joins two symbols becomes one edge; one that joins three or more becomes a junction node with
an edge to each symbol. An inline valve stays a symbol, so the line on each side of it is its own network.
Rewrites every edge and junction in graph.json, so it can be run again after the symbols change.

Usage: connect.py <graph.json> <image> [--ring 6] [--min 30]
"""

import argparse
import json
from collections import defaultdict
from itertools import count
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None
INK = 200  # gray level below which a pixel counts as drawn line


def networks(image, boxes, ring=6, min_pixels=30):
    """boxes: {id: (x1, y1, x2, y2)} in original pixels -> list of sets of ids that share one line network.

    ring: how far past a box (px) a line may start and still count as touching it. min_pixels: smaller
    specks (text, noise) are not lines."""
    ink = np.asarray(Image.open(image).convert("L")) < INK
    h, w = ink.shape
    boxes = {k: tuple(round(v) for v in b) for k, b in boxes.items()}
    lines = ink.copy()
    for x1, y1, x2, y2 in boxes.values():
        lines[max(y1, 0) : y2 + 1, max(x1, 0) : x2 + 1] = False
    labels, n = ndimage.label(lines, structure=np.ones((3, 3)))
    size = np.bincount(labels.ravel(), minlength=n + 1)
    touching = defaultdict(set)
    for k, (x1, y1, x2, y2) in boxes.items():
        near = labels[max(y1 - ring, 0) : min(y2 + ring + 1, h), max(x1 - ring, 0) : min(x2 + ring + 1, w)]
        for lab in np.unique(near):
            if lab and size[lab] >= min_pixels:
                touching[lab].add(k)
    return [ids for ids in touching.values() if len(ids) >= 2]


def add_networks(graph, nets):
    """Replace graph['edges'] and the junction nodes with one edge or one junction per network."""
    graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "junction"]
    box = {n["id"]: n["bbox"] for n in graph["nodes"]}
    edges, junctions = [], count(1)
    for ids in sorted(nets, key=lambda s: sorted(s)):
        ids = sorted(ids)
        if len(ids) == 2:
            edges.append({"source": ids[0], "target": ids[1], "kind": "process"})
            continue
        jid = f"j{next(junctions)}"
        cx = sum((box[i][0] + box[i][2]) / 2 for i in ids) / len(ids)
        cy = sum((box[i][1] + box[i][3]) / 2 for i in ids) / len(ids)
        graph["nodes"].append({"id": jid, "type": "junction", "tag": None, "bbox": [cx - 5, cy - 5, cx + 5, cy + 5]})
        edges += [{"source": i, "target": jid, "kind": "process"} for i in ids]
    graph["edges"] = edges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph", type=Path)
    ap.add_argument("image", type=Path)
    ap.add_argument("--ring", type=int, default=6)
    ap.add_argument("--min", type=int, default=30)
    args = ap.parse_args()
    graph = json.loads(args.graph.read_text())
    boxes = {n["id"]: n["bbox"] for n in graph["nodes"] if n["type"] != "junction"}
    nets = networks(args.image, boxes, args.ring, args.min)
    add_networks(graph, nets)
    args.graph.write_text(json.dumps(graph, indent=2))
    linked = {i for ids in nets for i in ids}
    print(f"{len(nets)} networks join {len(linked)} of {len(boxes)} symbols; {len(graph['edges'])} edges")


if __name__ == "__main__":
    main()
