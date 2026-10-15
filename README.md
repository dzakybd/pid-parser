# pid-parser

Turn a P&ID (piping and instrumentation diagram) image into a graph of components and pipe connections, ready for an RDBMS or a graph database. No GPU or training: a vision-language model finds the symbols, and small scripts do the tiling, the connections (traditional computer vision: thresholding and connected-component labeling), checking and export.

Useful for: asking the drawing questions (which valves sit between this pump and that tank), counting and listing components, checking what a valve isolates, loading the data into SQL, spreadsheets or Neo4j, giving an assistant a graph instead of a picture, and flagging isolated valves in a review. I tested the conversion on one dense sheet, not these workflows.

The repo has three parts:

- `skills/pid-parser/`: an agent skill for Claude Code, Codex and other harnesses that load `SKILL.md` skills
- `agent/run.py`: the same skill run by a LangChain Deep Agent on a ChatGPT sign-in (no API key)
- `eval/`: scoring against the PID2Graph ground truth on a handful of sheets

See the dense sample sheet converted (Sonnet 5.5 skill and gpt-6-luna Deep Agents runs), no install needed: [huggingface.co/spaces/dzakybd/pid-parser](https://huggingface.co/spaces/dzakybd/pid-parser). The write-up, step by step: [dzaky.ai.id/en/blog/pid-parser-pid-to-graph](https://dzaky.ai.id/en/blog/pid-parser-pid-to-graph) ([Bahasa Indonesia](https://dzaky.ai.id/id/blog/pid-parser-pid-to-graph)).

## Install the skill

```bash
npx skills add dzakybd/pid-parser
```

Then ask your agent: *"Use the pid-parser skill to parse drawing.png into a graph."* The skill scripts need Python 3.9+, Pillow, NumPy and SciPy; with [uv](https://docs.astral.sh/uv/) installed they fetch Pillow themselves.

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
3. Pass 2: `connect.py` finds the connections with traditional computer vision, no model and no learning. It binarizes the drawing (thresholding), erases the symbol boxes, labels the pieces of line that are left (connected-component labeling), and links the symbols that touch the same piece. A network that reaches three or more symbols becomes a `junction`.
4. `validate.py` validates the graph's structure with plain rules (ids, types, boxes, dangling edges, suspicious tags, isolated valves). It only reports: in the skill the agent reviews the warnings, in the code-driven `--tiled` path they are printed.
5. `export.py` writes the tables and graph files.

The model only has to find symbols and boxes, which is local work that tiles handle well. The connections are the part a model did worst and slowest, and the pixels answer them: on the dense sheet below the connection F1 went from 0.20 (agent reading the pipes) to 0.77 (best of three luna runs), with 20x fewer tokens. The catch is that it depends on exact boxes and clean lines (see Results).

## Deep Agents runner (ChatGPT sign-in)

```bash
uv sync
uv run python -c "from langchain_openai.chatgpt_oauth import login_chatgpt; login_chatgpt()"   # once

mkdir -p work/skills && cp -R skills/pid-parser work/skills/ && cp drawing.png work/
uv run python agent/run.py work --model gpt-6-luna --effort low --tiled
```

This uses `_ChatOpenAICodex` from `langchain-openai` 1.7.2 (experimental, private API) with `deepagents`. With `--tiled`, code runs pass 1 with one structured-output call per tile, then runs `connect.py`, `validate.py` and `export.py`: no agent loop, one model call per tile. `--whole` does pass 1 in one call on the whole sheet instead (see Results). Without either flag, one Deep Agent runs the whole skill. Output lands in `work/graph.json` and `work/out/`.

Tested with Python 3.12, deepagents 0.7.25, langchain-openai 1.7.2, langchain-core 1.6.10, langgraph 1.2.15.

## Evaluation

```bash
uv run python eval/fetch_samples.py            # the six densest PID2Graph "Dataset PID" sheets, via HTTP range requests
(cd eval && uv run python test_score.py ../samples/dpid-269.graphml 7168 4562)  # scorer sanity checks: GT, width, height
python eval/test_connect.py                    # connect.py on a drawn image
TILED=1 EFFORT=low eval/run_one.sh deepagents gpt-6-luna dpid-269 1
```

Scoring needs no model, only the ground truth:

- **Symbols:** one-to-one matching, closest centers first. A prediction matches a ground-truth symbol when its center lies within 0.75 × that symbol's width and height. Class accuracy is reported over matched symbols.
- **Connections:** two symbols are connected when they sit on the same pipe network. Line points (connectors, crossings, arrows, and the skill's junctions) are collapsed. P/R/F1 are computed over symbol pairs.

PID2Graph has no tag text, so tag accuracy is not scored.

### Results: one very dense sheet

The sheet is `dpid-269` (PID2Graph "Dataset PID"): 190 symbols and 732 connected symbol pairs, the densest of the benchmark. "Whole" is one model call on the whole image that returns the graph (`eval/whole_baseline.py`). "Ours" is tiles for the symbols, then `connect.py` for the connections. Same scorer, no model in the scoring. The skill runs on Claude Sonnet 5.5, the Deep Agents runner on gpt-6-luna (low effort).

| Harness / model | Approach | Symbol F1 | Connection F1 | Time | Cost |
|---|---|---|---|---|---|
| Skill, Sonnet 5.5 | whole image | 0.84 | 0.29 | 1.4 min | $0.34 |
| Skill, Sonnet 5.5 | **tiles + `connect.py` (traditional CV)** | **0.99** | **0.96** | 3.2 min | $0.74 |
| Deep Agents, gpt-6-luna | whole image | 0.34 | 0.08 | 20 s | 12K tokens |
| Deep Agents, gpt-6-luna | tiles + agent reads pipes | 0.88 | 0.20 | 2.3 min | 480K tokens |
| Deep Agents, gpt-6-luna | tiles + one call per tile reads pipes | 0.76 | 0.22 | 48 s | 49K tokens |
| Deep Agents, gpt-6-luna | **tiles + `connect.py` (traditional CV)**, best of 3 | 0.89 | **0.77** | 35 s | 25K tokens |

Sonnet ran once, luna three times: its symbol pass varies from run to run (symbol F1 0.81-0.89) and the connection score follows it (0.54, 0.68 and 0.77). With the true symbol boxes, `connect.py` alone scores 0.98 connection F1 on this sheet (`eval/cv_connect.py`), so the remaining gap is symbol quality, not the line reading.

Tiles or the whole sheet for pass 1, symbol F1 with Sonnet 5.5 on three more dense sheets (`eval/compare_tiling.py`, `runs/tiling_compare.json`):

| Sheet | Symbols | Whole sheet, 1 call | Tiles, 12 calls | Tiles with ownership stitching |
|---|---|---|---|---|
| dpid-36 | 183 | 0.60 | 0.96 | not run |
| dpid-126 | 177 | 0.86 | 0.96 | 0.98 |
| dpid-156 | 181 | 0.84 | 0.96 | 0.99 |

Ownership stitching keeps a detection only from the tile whose center is nearest to it, which removes the duplicates that overlapping tiles produce. `--tiled` uses it.

Tried and dropped:

- Having a model read the connections: a Deep Agent, one big call with every tile, a follow-up call for the missing pipes, one call per tile. The pipes it wrote were precise but too few (a header joining 17 symbols came back as 25 fragments), and all scored 0.22 or less with luna.
- Reading connections tile by tile and carrying pipe ends from one tile to the next. Errors compounded across tiles.
- Joining pipe pieces by their line-number label. Line numbers run through inline valves, so this over-merges.

Limits: `connect.py` needs exact boxes and clean lines, loses dashed signal lines (so there are no `signal` edges), and was scored on this one sheet. I did not measure small or scanned sheets.

## Data and licences

- **PID2Graph:** [Zenodo 14803338](https://zenodo.org/records/14803338), CC BY-SA 4.0 (paper: [arXiv 2411.13929](https://arxiv.org/abs/2411.13929)). The sheets here come from its "Dataset PID" part (Digitize-PID, Paliwal et al.), also CC BY-SA 4.0. `fetch_samples.py` downloads them; `samples/` and run outputs stay out of git, and the showcase Space ships one sheet and its outputs under CC BY-SA 4.0.

Code in this repo is MIT licensed (see `LICENSE`). The datasets above keep their own terms.
