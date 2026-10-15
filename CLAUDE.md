# pid-parser

P&ID image -> graph.json -> CSV / SQL / GraphML / Cypher. Agent skill + Deep Agents runner + eval.

## Stack
- Python >= 3.12, uv. Skill scripts are standalone (PEP 723, Python 3.9+, Pillow, NumPy, SciPy).
- Deep Agents (`deepagents`) on `_ChatOpenAICodex` from `langchain-openai==1.7.2` (ChatGPT sign-in, no API key).

## Commands
- Install: `uv sync`
- Format / lint: `uvx ruff format . && uvx ruff check .`
- Scorer tests: `(cd eval && uv run python test_score.py ../samples/dpid-269.graphml 7168 4562)` and `python eval/test_connect.py`
- Samples: `uv run python eval/fetch_samples.py`
- One run: `TILED=1 EFFORT=low eval/run_one.sh deepagents gpt-6-luna dpid-269 1`
- Showcase Space: `uv run python space/build.py`, then `hf upload dzakybd/pid-parser space . --type space --exclude build.py` (unset a stale `HF_TOKEN` first)

## Layout
- `skills/pid-parser/`: the published skill (`npx skills add dzakybd/pid-parser`). Keep it dependency-light.
- `agent/run.py`: Deep Agents runner. `eval/`: ground-truth scoring, no model involved.
- Not in git: `samples/`, `runs/` except `runs/tiling_compare.json`, `space/data/` (CC BY-SA, ships only to the Space).
- `space/`: static Hugging Face Space, the dense sheet dpid-269 (PID2Graph Dataset PID, CC BY-SA 4.0).

## Project Learnings
- Read connections from the pixels (`connect.py`), not with a model: agent, one-call and per-tile pipe passes all scored 0.20-0.22 on the dense sheet against 0.54-0.77 for pixels. The symbol pass sets the ceiling.
- Ask the model for crop-normalized 0-1000 boxes and convert in code; models misreport pixel coordinates.
- Deep Agents `LocalShellBackend` needs `virtual_mode=False` and absolute paths in the task, or the agent cannot find the skill scripts.
- Neo4j Cypher: use CREATE and omit null properties (MERGE fails on nulls).
