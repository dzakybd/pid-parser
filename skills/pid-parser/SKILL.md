---
name: pid-parser
description: Parse a P&ID (piping and instrumentation diagram) image into components, tags and pipe connections. Produces graph.json plus CSV tables, a SQL file (SQLite/PostgreSQL), GraphML and Cypher (Neo4j). Use when asked to digitize, read, extract or convert a P&ID, process diagram or piping drawing into a table, database or graph.
---

# P&ID parser

Turn one P&ID image into a graph of components (nodes) and the pipes or signal lines between them (edges), then export it for an RDBMS or a graph database.

Scripts live next to this file in `scripts/`. Run them with `uv run` (installs Pillow on the fly) or `python3` if Pillow is already installed. `SKILL_DIR` below means the directory containing this file.

## 1. Tile the drawing

```bash
uv run SKILL_DIR/scripts/tile.py <image> <workdir>/tiles
```

This writes `overview.png` (whole sheet) and `tile_<row>_<col>.png` (overlapping crops), each with a cyan coordinate grid labeled in **original image pixels**, plus `tiles.json` (image size, tile boxes).

## 2. Pass 1: symbols

Skip this pass if `<workdir>/graph.json` already lists the symbols (some pipelines fill it for you); go to step 3.

1. Open `overview.png`. Note the layout, the title block, and which areas are border, notes or legend (ignore those).
2. Open **every** tile in order. For each tile, append to `<workdir>/notes.md` every symbol: type, tag text exactly as printed, and its box `[x1, y1, x2, y2]` read off the grid labels (original pixels, not tile pixels). Write the notes as you go; do not rely on memory across tiles.
3. Tiles overlap. A symbol seen in two tiles is one node: merge by tag, or by box centers within about 30 px.
4. Write `<workdir>/graph.json` with all symbol nodes and `"edges": []` (format below).

## 3. Pass 2: connections

```bash
uv run SKILL_DIR/scripts/mark.py <workdir>/graph.json <workdir>/tiles
```

This draws every node id on `marked_overview.png` and `marked_tile_<row>_<col>.png`. Open **every** marked tile and follow each drawn line from end to end. Record in `notes.md` which ids it connects, where it branches, and its printed line number. A pipe that runs across several tiles is one pipe: use its line number to join the pieces. Then add the edges to `graph.json`, plus a `junction` node at every tee. If you find a symbol that has no id, add it as a node.

## 4. `graph.json` format

```json
{
  "image": {"file": "drawing.png", "width": 2604, "height": 1744},
  "nodes": [
    {"id": "n1", "type": "control_valve", "tag": "TCV 1401", "bbox": [470, 683, 492, 705]},
    {"id": "j1", "type": "junction", "tag": null, "bbox": [420, 720, 430, 730]}
  ],
  "edges": [
    {"source": "n1", "target": "j1", "kind": "process", "line": "SIZE-MSS-140076"}
  ]
}
```

Node `type` is one of: `valve`, `control_valve`, `relief_valve`, `check_valve`, `pump`, `compressor`, `tank`, `vessel`, `column`, `heat_exchanger`, `instrument`, `fitting` (reducer, flange, nozzle, blind, strainer, flow element), `off_page` (connector arrow or box to another sheet), `equipment` (anything else), `junction`.

Edge `kind` is `process` (pipe) or `signal` (dashed or instrument line). `line` is the printed line number if one labels that pipe, else omit it.

Rules:
- **Edges follow drawn lines only.** Connect two nodes when a line runs between them with no other symbol in between. An inline valve splits a pipe: `A - valve - B` is two edges, not `A - B`.
- **Tees are `junction` nodes.** Where three or more pipe ends meet, add a junction at that point and connect each branch to it. Two lines that cross without a dot or tee are not connected.
- **Tags:** copy the text exactly (`TE 14089A`). If you cannot read it, use `null`. Never guess a number.
- **Boxes** are in original image pixels from the grid labels. Junction boxes are a small box around the point.
- **Digitize the sheet as drawn.** A detail or section view that repeats equipment gets its own nodes too; give them the same tag. Do not merge repeats.
- Leave out the border, title block, notes, legend, and line-number labels themselves.

## 5. Validate and fix

```bash
python3 SKILL_DIR/scripts/validate.py <workdir>/graph.json
```

Fix every `ERROR` and re-run until it prints `OK`. Review each `WARN`: an isolated valve or a junction with fewer than three edges usually means a missed connection; look at that tile again.

## 6. Export

```bash
python3 SKILL_DIR/scripts/export.py <workdir>/graph.json <workdir>/out
```

Writes:
- `nodes.csv`, `edges.csv`: plain tables
- `pid.sql`: `CREATE TABLE` + `INSERT` for SQLite or PostgreSQL (`sqlite3 pid.db < pid.sql`, `psql -f pid.sql`)
- `graph.graphml`: NetworkX, Gephi, yEd
- `graph.cypher`: Neo4j (`cypher-shell -f graph.cypher`)

Report to the user: node count by type, edge count, the validator's warnings you could not resolve, and where the files are.
