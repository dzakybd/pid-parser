"""Export graph.json to CSV, SQL, GraphML and Cypher. Standard library only.

Usage: export.py <graph.json> <outdir>
"""

import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NODE_COLS = ["id", "type", "tag", "x1", "y1", "x2", "y2"]
EDGE_COLS = ["source", "target", "kind", "line"]


def rows(graph):
    nodes = [
        {
            "id": n["id"],
            "type": n["type"],
            "tag": n.get("tag"),
            "x1": n["bbox"][0],
            "y1": n["bbox"][1],
            "x2": n["bbox"][2],
            "y2": n["bbox"][3],
        }
        for n in graph["nodes"]
    ]
    edges = [
        {"source": e["source"], "target": e["target"], "kind": e["kind"], "line": e.get("line")} for e in graph["edges"]
    ]
    return nodes, edges


def write_csv(path, cols, data):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows({k: ("" if v is None else v) for k, v in r.items()} for r in data)


def sql_value(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(path, nodes, edges):
    lines = [
        "-- P&ID graph: SQLite and PostgreSQL compatible",
        "CREATE TABLE components (id TEXT PRIMARY KEY, type TEXT NOT NULL, tag TEXT, x1 REAL, y1 REAL, x2 REAL, y2 REAL);",
        "CREATE TABLE connections (source TEXT NOT NULL REFERENCES components(id),"
        + " target TEXT NOT NULL REFERENCES components(id), kind TEXT NOT NULL, line TEXT);",
    ]
    for n in nodes:
        lines.append(f"INSERT INTO components VALUES ({', '.join(sql_value(n[c]) for c in NODE_COLS)});")
    for e in edges:
        lines.append(f"INSERT INTO connections VALUES ({', '.join(sql_value(e[c]) for c in EDGE_COLS)});")
    Path(path).write_text("\n".join(lines) + "\n")


def write_graphml(path, nodes, edges):
    ns = "http://graphml.graphdrawing.org/xmlns"
    root = ET.Element("graphml", xmlns=ns)
    keys = [("type", "node", "string"), ("tag", "node", "string")]
    keys += [(c, "node", "double") for c in ("x1", "y1", "x2", "y2")]
    keys += [("kind", "edge", "string"), ("line", "edge", "string")]
    for name, scope, typ in keys:
        ET.SubElement(root, "key", {"id": f"{scope}_{name}", "for": scope, "attr.name": name, "attr.type": typ})
    g = ET.SubElement(root, "graph", edgedefault="undirected")
    for n in nodes:
        el = ET.SubElement(g, "node", id=n["id"])
        for c in NODE_COLS[1:]:
            if n[c] is not None:
                ET.SubElement(el, "data", key=f"node_{c}").text = str(n[c])
    for i, e in enumerate(edges):
        el = ET.SubElement(g, "edge", id=f"e{i}", source=e["source"], target=e["target"])
        for c in ("kind", "line"):
            if e[c] is not None:
                ET.SubElement(el, "data", key=f"edge_{c}").text = str(e[c])
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def cypher_value(v):
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def cypher_props(d, cols):
    return ", ".join(f"{c}: {cypher_value(d[c])}" for c in cols if d[c] is not None)


def write_cypher(path, nodes, edges):
    """CREATE, not MERGE: Neo4j rejects MERGE on null properties (untagged nodes)."""
    lines = []
    for n in nodes:
        label = "Junction" if n["type"] == "junction" else "Component"
        lines.append(f"CREATE (:{label} {{{cypher_props(n, NODE_COLS)}}});")
    for e in edges:
        rel = "PIPE" if e["kind"] == "process" else "SIGNAL"
        props = cypher_props(e, ["line"])
        lines.append(
            f"MATCH (a {{id: {cypher_value(e['source'])}}}), (b {{id: {cypher_value(e['target'])}}}) "
            f"CREATE (a)-[:{rel}{' {' + props + '}' if props else ''}]->(b);"
        )
    Path(path).write_text("\n".join(lines) + "\n")


def main(src, outdir):
    graph = json.loads(Path(src).read_text())
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    nodes, edges = rows(graph)
    write_csv(out / "nodes.csv", NODE_COLS, nodes)
    write_csv(out / "edges.csv", EDGE_COLS, edges)
    write_sql(out / "pid.sql", nodes, edges)
    write_graphml(out / "graph.graphml", nodes, edges)
    write_cypher(out / "graph.cypher", nodes, edges)
    print(
        f"{len(nodes)} nodes, {len(edges)} edges -> {out}/(nodes.csv, edges.csv, pid.sql, graph.graphml, graph.cypher)"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
