"""Scorer sanity checks: a perfect answer built from the ground truth scores 1.0."""

import sys
from collections import defaultdict
from itertools import count

import networkx as nx
from nets import GT_DROP, GT_LINE
from score import score

TYPE_OF = {
    "valve": "valve",
    "instrumentation": "instrument",
    "pump": "pump",
    "tank": "tank",
    "inlet/outlet": "off_page",
    "general": "fitting",
}


def perfect_graph(gt_path, w, h):
    g = nx.read_graphml(gt_path)
    g.remove_nodes_from([n for n, d in g.nodes(data=True) if d["label"] in GT_DROP])
    sym = [n for n, d in g.nodes(data=True) if d["label"] not in GT_LINE]
    nodes = [
        {
            "id": n,
            "type": TYPE_OF[g.nodes[n]["label"]],
            "tag": None,
            "bbox": [g.nodes[n][k] for k in ("xmin", "ymin", "xmax", "ymax")],
        }
        for n in sym
    ]
    edges, ids = [], count()
    lines = g.subgraph(n for n in g if n not in sym)
    net = {n: i for i, c in enumerate(nx.connected_components(lines)) for n in c}
    members = defaultdict(set)
    for s in sym:
        for nb in g.neighbors(s):
            if nb in net:
                members[net[nb]].add(s)
            elif nb in sym and s < nb:
                edges.append({"source": s, "target": nb, "kind": "process"})
    for ms in members.values():
        if len(ms) < 2:
            continue
        j = f"j{next(ids)}"
        nodes.append({"id": j, "type": "junction", "tag": None, "bbox": [0, 0, 1, 1]})
        edges += [{"source": s, "target": j, "kind": "process"} for s in ms]
    return {"image": {"width": w, "height": h}, "nodes": nodes, "edges": edges}


gt, w, h = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
perfect = perfect_graph(gt, w, h)
r, _ = score(perfect, gt)
print("perfect", r["symbols"]["f1"], r["symbols"]["class_accuracy"], r["connections"]["f1"])
assert r["symbols"]["f1"] == 1.0 and r["connections"]["f1"] == 1.0

symbols = [n for n in perfect["nodes"] if n["type"] != "junction"]
keep = [n for n in perfect["nodes"] if n["type"] == "junction"] + [n for i, n in enumerate(symbols) if i % 5]
kept = {n["id"] for n in keep}
dropped = {
    **perfect,
    "nodes": keep,
    "edges": [e for e in perfect["edges"] if e["source"] in kept and e["target"] in kept],
}
r, _ = score(dropped, gt)
print(
    "drop20%",
    round(r["symbols"]["recall"], 3),
    round(r["symbols"]["precision"], 3),
    round(r["connections"]["recall"], 3),
)
assert 0.75 <= r["symbols"]["recall"] <= 0.85 and r["connections"]["recall"] < 1 and r["symbols"]["precision"] == 1.0

far = 0.03 * (w * w + h * h) ** 0.5
shifted = {
    **perfect,
    "nodes": [
        {**n, "bbox": [n["bbox"][0] + far, n["bbox"][1], n["bbox"][2] + far, n["bbox"][3]]} for n in perfect["nodes"]
    ],
}
r, _ = score(shifted, gt)
# Rows of evenly spaced bubbles mean some shifted boxes land on a real neighbour.
print("shifted", r["symbols"]["matched"], round(r["symbols"]["f1"], 3))
assert r["symbols"]["f1"] < 0.35
print("OK")
