"""Reduce a P&ID graph to symbols plus the pipe networks that join them.

Both the PID2Graph ground truth and the skill's output go through the same
reduction, so they are scored on equal terms: two symbols are "connected"
when they touch the same pipe network (a run of line points, bends and
junctions with no symbol in between).
"""

from itertools import combinations

import networkx as nx

# PID2Graph classes that are points on a line, not symbols.
GT_LINE = {"connector", "crossing", "arrow"}
GT_DROP = {"background"}

# Skill types collapsed to the PID2Graph class vocabulary for scoring.
TO_GT_CLASS = {
    "valve": "valve",
    "control_valve": "valve",
    "relief_valve": "valve",
    "check_valve": "valve",
    "instrument": "instrumentation",
    "pump": "pump",
    "compressor": "pump",
    "tank": "tank",
    "vessel": "tank",
    "column": "tank",
    "off_page": "inlet/outlet",
}


def box_center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def reduce(nodes, edges, is_line):
    """nodes: {id: {"cls", "box"}}, edges: [(a, b)], is_line(id) -> bool.

    Returns (symbols, pairs): symbols {id: {"cls", "box"}} and the set of
    frozenset({a, b}) symbol pairs that share a pipe network.
    """
    g = nx.Graph()
    g.add_nodes_from(nodes)
    g.add_edges_from(edges)
    symbols = {n: nodes[n] for n in nodes if not is_line(n)}

    lines = g.subgraph(n for n in g if is_line(n))
    net_of = {}
    for i, comp in enumerate(nx.connected_components(lines)):
        for n in comp:
            net_of[n] = i

    members = {}
    pairs = set()
    for s in symbols:
        for nb in g.neighbors(s):
            if nb in net_of:
                members.setdefault(net_of[nb], set()).add(s)
            elif nb in symbols and nb != s:
                pairs.add(frozenset((s, nb)))
    for group in members.values():
        pairs.update(frozenset(p) for p in combinations(sorted(group), 2))
    return symbols, pairs


def load_gt(path):
    g = nx.read_graphml(path)
    nodes = {
        n: {"cls": d["label"], "box": (d["xmin"], d["ymin"], d["xmax"], d["ymax"])}
        for n, d in g.nodes(data=True)
        if d["label"] not in GT_DROP
    }
    edges = [(a, b) for a, b in g.edges() if a in nodes and b in nodes]
    return reduce(nodes, edges, lambda n: nodes[n]["cls"] in GT_LINE)


def load_pred(graph):
    """graph: parsed graph.json from the skill."""
    nodes = {
        n["id"]: {"cls": TO_GT_CLASS.get(n["type"], "general"), "box": tuple(n["bbox"]), "type": n["type"]}
        for n in graph["nodes"]
    }
    edges = [(e["source"], e["target"]) for e in graph["edges"]]
    return reduce(nodes, edges, lambda n: nodes[n]["type"] == "junction")
