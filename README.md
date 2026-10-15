# pid-parser

Turn a P&ID (piping and instrumentation diagram) image into a graph of components and pipe connections, ready for an RDBMS or a graph database. No GPU or training: a vision-language model reads the drawing, and small scripts do the tiling, checking and export.

The repo has three parts:

- `skills/pid-parser/`: an agent skill for Claude Code, Codex and other harnesses that load `SKILL.md` skills
- `agent/run.py`: the same skill run by a LangChain Deep Agent on a ChatGPT sign-in (no API key)
- `eval/`: scoring against the PID2Graph ground truth on a handful of sheets

## Install the skill

```bash
npx skills add dzakybd/pid-parser
```

Then ask your agent: *"Use the pid-parser skill to parse drawing.png into a graph."* The skill scripts need Python 3.9+ and Pillow; with [uv](https://docs.astral.sh/uv/) installed they fetch Pillow themselves.

## What you get

Everything starts from `graph.json`:

```json
{
  "image": {"file": "drawing.png", "width": 2604, "height": 1744},
  "nodes": [{"id": "n1", "type": "control_valve", "tag": "TCV 1401", "bbox": [470, 683, 492, 705]}],
  "edges": [{"source": "n1", "target": "j1", "kind": "process", "line": "SIZE-MSS-140076"}]
}
```

`scripts/export.py` turns it into:

| File | Load with |
|---|---|
| `nodes.csv`, `edges.csv` | any spreadsheet or `COPY` |
| `pid.sql` | `sqlite3 pid.db < pid.sql` or `psql -f pid.sql` (tables `components`, `connections`) |
| `graph.graphml` | NetworkX, Gephi, yEd |
| `graph.cypher` | `cypher-shell -f graph.cypher` (Neo4j) |

Node types: valve, control_valve, relief_valve, check_valve, pump, compressor, tank, vessel, column, heat_exchanger, instrument, fitting, off_page, equipment, junction. Edges are `process` (pipe) or `signal` (dashed or instrument line). A tee becomes a `junction` node.

## How the skill works

1. `tile.py` cuts the sheet into overlapping tiles with a coordinate grid in original pixels.
2. Pass 1: the model lists every symbol tile by tile, and duplicates from the overlaps are merged.
3. Pass 2: `mark.py` draws each symbol's id on the tiles, and the model follows every line between ids.
4. `validate.py` checks the graph (ids, types, boxes, dangling edges, suspicious tags, isolated valves), and the model fixes what it flags.
5. `export.py` writes the tables and graph files.

Reading symbols and reading connections are separate passes on purpose. Symbols are local, so tiles help. Pipes run across the whole sheet, so the connection pass needs the full drawing in view.

## Deep Agents runner (ChatGPT sign-in)

```bash
uv sync
uv run python -c "from langchain_openai.chatgpt_oauth import login_chatgpt; login_chatgpt()"   # once

mkdir -p work/skills && cp -R skills/pid-parser work/skills/ && cp drawing.png work/
uv run python agent/run.py work --model gpt-6-luna --effort medium --tiled --pipe-model gpt-6-sol
```

This uses `_ChatOpenAICodex` from `langchain-openai` 1.7.2 (experimental, private API) with `deepagents`. With `--tiled`, code runs pass 1 with one structured-output call per tile on the cheap model. A Deep Agent on `--pipe-model` then does the connections, validation and export. Without `--tiled`, one agent runs the whole skill. Output lands in `work/graph.json` and `work/out/`.

## Evaluation

```bash
uv run python eval/fetch_samples.py            # 3 OPEN100 + 3 synthetic sheets, a few MB via HTTP range requests
(cd eval && uv run python test_score.py ../samples/open100-1.graphml 2288 1528)  # scorer sanity checks: GT, width, height
eval/run_one.sh deepagents gpt-6-luna open100-1 1   # EFFORT=medium TILED=1 PIPE_MODEL=gpt-6-sol
uv run python eval/summary.py                  # runs/results.csv
```

Scoring needs no model, only the ground truth:

- **Symbols:** one-to-one matching, closest centers first. A prediction matches a ground-truth symbol when its center lies within 0.75 × that symbol's width and height. Class accuracy is reported over matched symbols.
- **Connections:** two symbols are connected when they sit on the same pipe network. Line points (connectors, crossings, arrows, and the skill's junctions) are collapsed. P/R/F1 are computed over symbol pairs.

PID2Graph has no tag text, so tag accuracy is not scored.

### Results

One run per sheet, so differences under about 0.15 are noise.

| Setup | Sheets | Symbol F1 | Connection F1 | Avg time |
|---|---|---|---|---|
| Claude Code, Opus | OPEN100 ×3 | 0.78 | 0.59 | 3 min |
| Codex, gpt-6-sol | OPEN100 ×3 | 0.73 | 0.49 | 3 min |
| Deep Agents, gpt-6-sol | OPEN100 ×3 | 0.76 | 0.30 | 5 min |
| Deep Agents, luna symbols (tiled) + sol agent | OPEN100 ×2 | 0.85 | 0.54 | 8 min |
| Deep Agents, gpt-6-luna (medium) | OPEN100 ×1 | 0.33 | 0.08 | 1 min |
| Claude Code, Opus | Synthetic ×3 | 0.99 | 0.85 | 3 min |
| Codex, gpt-6-sol | Synthetic ×3 | 0.96 | 0.65 | 2.5 min |
| Deep Agents, gpt-6-sol | Synthetic ×3 | 0.98 | 0.79 | 9 min |

The tiled setup scored 0.81 connection F1 on `open100-1` and 0.26 on `open100-0`. On that dense sheet, most ground-truth pairs come from two long headers.

Tried and dropped:

- Reading connections tile by tile, including carrying pipe ends from one tile to the next. It peaked at 0.44 F1 and errors compounded across tiles.
- Joining pipe pieces by their line-number label. Line numbers run through inline valves, so this over-merges.
- An OpenCV line tracer. The goal was a VLM-only pipeline, and the tracer was fragile once the symbol boxes were not exact.

## Data and licences

- **PID2Graph:** [Zenodo 14803338](https://zenodo.org/records/14803338), CC BY-SA 4.0 (paper: [arXiv 2411.13929](https://arxiv.org/abs/2411.13929)).
- **OPEN100 sheets:** from the Energy Impact Center ([open-100.com](https://open-100.com)), with no licence stated. They are not redistributed here: `fetch_samples.py` downloads them, and `samples/` and run outputs stay out of git.
