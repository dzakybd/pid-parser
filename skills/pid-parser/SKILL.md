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

This draws every symbol id on `marked_overview.png` and on `marked_tile_<row>_<col>.png`. Then read **every** marked tile, one at a time, in the order `tiles.json` lists them. Keep a checklist with one item per tile and tick each off; do not stop or write the summary before the last tile is done. The overview is too coarse to trace pipes on a dense sheet, so the tiles are where the pipes are read.

For each tile:
1. Open the marked tile and follow each drawn line from end to end.
2. Append one line to `<workdir>/pipes.txt` for every pipe: the ids it joins, separated by spaces. A tee lists all its branches on one line. Start the line with `signal` for a dashed or instrument line, and put the printed line number last, after `|`. An inline valve splits a pipe, so `A - valve - B` is two lines, `A valve` and `valve B`.

```
s12 s40
s7 s9 s15 | SIZE-MSS-140076
signal s3 s21
```

3. When a line leaves the tile, check the overview or the neighbouring tile to see which symbol it reaches. Tiles overlap, so the same pipe may appear in two tiles; listing it twice is fine.

When all tiles are read, build the edges:

```bash
python3 SKILL_DIR/scripts/add_pipes.py <workdir>/graph.json <workdir>/pipes.txt
```

It rebuilds every edge and every tee junction from `pipes.txt` (so you can add lines and run it again) and warns about any id that does not exist. Do not write edges or junctions into `graph.json` by hand. If you find a symbol that has no id, add it to `graph.json` as a node first.

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

Edge `kind` is `process` (pipe) or `signal` (dashed or instrument line). `line` is the printed line number if one labels that pipe, else omit it. `add_pipes.py` (step 3) writes the edges and junctions for you from `pipes.txt`, so this format is what you check, not what you type.

Rules:
- **Edges follow drawn lines only.** Connect two nodes when a line runs between them with no other symbol in between. An inline valve splits a pipe: `A - valve - B` is two edges, not `A - B`.
- **Tees are `junction` nodes.** Where three or more pipe ends meet, put all the branches on one line of `pipes.txt`; `add_pipes.py` makes the junction. Two lines that cross without a dot or tee are not connected.
- **Tags:** copy the text exactly (`TE 14089A`). If you cannot read it, use `null`. Never guess a number.
- **Boxes** are in original image pixels from the grid labels. Junction boxes are a small box around the point.
- **Digitize the sheet as drawn.** A detail or section view that repeats equipment gets its own nodes too; give them the same tag. Do not merge repeats.
- Leave out the border, title block, notes, legend, and line-number labels themselves.

## 5. Validate and fix

```bash
python3 SKILL_DIR/scripts/validate.py <workdir>/graph.json
```

Fix every `ERROR` and re-run until it prints `OK`. An error that says most symbols have no connection means the pipe pass is not finished: go back to step 3 and read the tiles you have not read yet. Review each `WARN`: an isolated valve or a junction with fewer than three edges usually means a missed connection; look at that tile again.

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
