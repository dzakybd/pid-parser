# /// script
# requires-python = ">=3.9"
# ///
"""Rebuild the edges and junctions of graph.json from a pipes file.

One pipe per line: the ids it joins, separated by spaces. A tee lists all its branches on one line. Start the
line with `signal` for a dashed or instrument line, and put a printed line number last, after `|`. Blank lines
and lines starting with # are ignored.

    s12 s40
    s7 s9 s15 | SIZE-MSS-140076
    signal s3 s21

Two ids make one edge. Three or more make a junction node at their centre, joined to each id. Every run starts
from the symbols alone, so you can append lines to the file and run it again.

Usage: add_pipes.py <graph.json> <pipes.txt>
"""

import json
import sys
from pathlib import Path


def parse(text, ids):
    pipes, problems = [], []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        body, _, label = line.partition("|")
        words = body.split()
        kind = words.pop(0) if words and words[0] in ("signal", "process") else "process"
        unknown = [w for w in words if w not in ids]
        if unknown:
            problems.append(f"line {n}: no symbol {', '.join(unknown)}")
        members = sorted({w for w in words if w in ids})
        if len(members) < 2:
            problems.append(f"line {n}: needs two ids that exist: {line}")
            continue
        pipes.append((members, kind, label.strip() or None))
    return pipes, problems


def main(graph_path, pipes_path):
    graph = json.loads(Path(graph_path).read_text())
    graph["nodes"] = [n for n in graph["nodes"] if n["type"] != "junction"]
    boxes = {n["id"]: n["bbox"] for n in graph["nodes"]}
    pipes, problems = parse(Path(pipes_path).read_text(), boxes)

    graph["edges"], seen, junctions = [], set(), 0
    for members, kind, line in pipes:
        if (tuple(members), kind) in seen:
            continue
        seen.add((tuple(members), kind))
        attrs = {"kind": kind, **({"line": line} if line else {})}
        if len(members) == 2:
            graph["edges"].append({"source": members[0], "target": members[1], **attrs})
            continue
        junctions += 1
        cx = sum((boxes[m][0] + boxes[m][2]) / 2 for m in members) / len(members)
        cy = sum((boxes[m][1] + boxes[m][3]) / 2 for m in members) / len(members)
        graph["nodes"].append(
            {"id": f"j{junctions}", "type": "junction", "tag": None, "bbox": [cx - 3, cy - 3, cx + 3, cy + 3]}
        )
        graph["edges"] += [{"source": m, "target": f"j{junctions}", **attrs} for m in members]

    Path(graph_path).write_text(json.dumps(graph, indent=2))
    for message in problems:
        print("WARN ", message)
    print(f"{len(pipes)} pipes -> {len(graph['edges'])} edges, {junctions} junctions in {graph_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
