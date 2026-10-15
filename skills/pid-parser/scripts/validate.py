"""Check graph.json for structural errors. Standard library only.

Usage: validate.py <graph.json>
Exit code 1 when any ERROR is found.
"""

import json
import re
import sys
from collections import Counter

TYPES = {
    "valve",
    "control_valve",
    "relief_valve",
    "check_valve",
    "pump",
    "compressor",
    "tank",
    "vessel",
    "column",
    "heat_exchanger",
    "instrument",
    "fitting",
    "off_page",
    "equipment",
    "junction",
}
KINDS = {"process", "signal"}
TAG_RE = re.compile(r"^[A-Z]{1,6}[- ]?[0-9X]")
ISOLATED_MAX = 0.4  # in the PID2Graph ground truth at most 17% of symbols have no connection, in good graphs 18%


def check(graph):
    errors, warns = [], []
    image = graph.get("image") or {}
    w, h = image.get("width"), image.get("height")
    if not (isinstance(w, int) and isinstance(h, int)):
        errors.append("image.width and image.height must be integers")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return errors + ["nodes and edges must be lists"], warns

    ids = Counter(n.get("id") for n in nodes)
    for nid, count in ids.items():
        if count > 1:
            errors.append(f"duplicate node id {nid!r}")
    for n in nodes:
        nid = n.get("id")
        if n.get("type") not in TYPES:
            errors.append(f"node {nid}: type {n.get('type')!r} not in {sorted(TYPES)}")
        box = n.get("bbox")
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            errors.append(f"node {nid}: bbox must be [x1, y1, x2, y2]")
        elif not (box[0] < box[2] and box[1] < box[3]):
            errors.append(f"node {nid}: bbox needs x1 < x2 and y1 < y2")
        elif w and h and (box[0] < 0 or box[1] < 0 or box[2] > w or box[3] > h):
            errors.append(f"node {nid}: bbox outside the {w}x{h} image")
        tag = n.get("tag")
        if tag is not None and not isinstance(tag, str):
            errors.append(f"node {nid}: tag must be a string or null")
        elif tag and n.get("type") != "junction" and not TAG_RE.match(tag):
            warns.append(f"node {nid}: unusual tag {tag!r}")

    degree = Counter()
    seen = set()
    for i, e in enumerate(edges):
        s, t = e.get("source"), e.get("target")
        if s not in ids or t not in ids:
            errors.append(f"edge {i}: {s} -> {t} references a missing node")
            continue
        if s == t:
            errors.append(f"edge {i}: self loop on {s}")
        if e.get("kind") not in KINDS:
            errors.append(f"edge {i}: kind {e.get('kind')!r} not in {sorted(KINDS)}")
        key = frozenset((s, t))
        if key in seen:
            warns.append(f"edge {i}: duplicate connection {s} - {t}")
        seen.add(key)
        degree[s] += 1
        degree[t] += 1

    symbols = [n for n in nodes if n.get("type") != "junction"]
    alone = [n for n in symbols if degree[n.get("id")] == 0]
    if len(symbols) >= 4 and len(alone) > ISOLATED_MAX * len(symbols):
        errors.append(
            f"{len(alone)} of {len(symbols)} symbols have no connection: connect.py has not run, or the "
            "symbol boxes miss their lines (check the boxes against the image it was given)"
        )

    tags = Counter(n["tag"] for n in nodes if n.get("tag"))
    for tag, count in tags.items():
        if count > 1:
            warns.append(f"tag {tag!r} used by {count} nodes (merge duplicates from tile overlap?)")
    for n in nodes:
        nid, kind = n.get("id"), n.get("type")
        if kind == "junction" and degree[nid] < 3:
            warns.append(f"junction {nid} has {degree[nid]} edges (a tee needs 3)")
        elif kind not in ("instrument", "junction") and degree[nid] == 0:
            warns.append(f"{kind} {nid} ({n.get('tag')}) has no connections")
    return errors, warns


def main(path):
    with open(path) as f:
        graph = json.load(f)
    errors, warns = check(graph)
    for msg in errors:
        print("ERROR", msg)
    for msg in warns:
        print("WARN ", msg)
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    print(f"{len(nodes)} nodes, {len(edges)} edges, {len(errors)} errors, {len(warns)} warnings")
    if errors:
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
