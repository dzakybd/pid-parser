"""Symbol pass only: one call on the whole sheet vs one call per overlapping tile.

Same model, prompt and merge as agent/run.py --tiled; only the cropping differs.
Scores symbols against the PID2Graph ground truth (no model in the scoring).

Usage: uv run python eval/compare_tiling.py [sheet ...] [--model gpt-6.1-sol] [--effort low]
       uv run python eval/compare_tiling.py [sheet ...] --model claude-sonnet-5-5   (runs on the local `claude` CLI)
       GOOGLE_API_KEY=... uv run python eval/compare_tiling.py [sheet ...] --model gemini-3.8-flash
"""

import argparse
import base64
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_openai.chat_models.codex import _ChatOpenAICodex

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
from run import merge, stitch, tile_symbols, whole_symbols
from score import score


class ClaudeCLI:
    """Stands in for the LangChain model: runs a Claude model headless through the local `claude` CLI."""

    def __init__(self, model):
        self.model = model

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, messages):
        parts = messages[0].content
        text = next(p["text"] for p in parts if p["type"] == "text")
        b64 = next(p["image_url"]["url"] for p in parts if p["type"] == "image_url").split(",", 1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.png"
            image.write_bytes(base64.b64decode(b64))
            out = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--model",
                    self.model,
                    "--allowedTools",
                    "Read",
                    "--output-format",
                    "json",
                    "--json-schema",
                    json.dumps(self.schema.model_json_schema()),
                    f"Read the image {image}. {text}",
                ],
                cwd=tmp,
                check=False,  # a SessionEnd hook can fail at exit; the answer is already on stdout
                capture_output=True,
                text=True,
                timeout=900,
            )
        events, _ = json.JSONDecoder().raw_decode(out.stdout)
        result = next(e for e in reversed(events) if e.get("type") == "result")
        if "structured_output" not in result:  # e.g. a usage limit: say so instead of a bare KeyError
            raise RuntimeError(f"claude returned no structured output: {str(result.get('result'))[:300]}")
        return self.schema.model_validate(result["structured_output"])

    def batch(self, requests, config=None):
        with ThreadPoolExecutor((config or {}).get("max_concurrency", 4)) as pool:
            return list(pool.map(self.invoke, requests))


# The dense benchmark, fixed by rule before any run: the six PID2Graph "Dataset PID" sheets with the most symbols
# (176-190), plus the two densest OPEN100 sheets (134 and 102). Fetched by eval/fetch_samples.py.
SHEETS = ["dpid-269", "dpid-227", "dpid-36", "dpid-156", "dpid-126", "dpid-61", "open100-10", "open100-0"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheets", nargs="*", default=SHEETS)
    ap.add_argument("--model", default="gpt-6.1-sol")
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()
    if args.model.startswith("claude"):
        model = ClaudeCLI(args.model)
    elif args.model.startswith("gemini"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = ChatGoogleGenerativeAI(model=args.model, max_retries=6)  # free tier: retry on 429/503
    else:
        model = _ChatOpenAICodex(model=args.model, reasoning={"effort": args.effort})

    rows = []
    for sheet in args.sheets:
        image = next((REPO / "samples").glob(f"{sheet}.*[!l]"))  # .png/.jpg, not .graphml
        gt = REPO / "samples" / f"{sheet}.graphml"
        with tempfile.TemporaryDirectory() as tmp:
            tiles = Path(tmp) / "tiles"
            subprocess.run(
                [sys.executable, REPO / "skills/pid-parser/scripts/tile.py", image, tiles],
                check=True,
                capture_output=True,
            )
            detections, tile_boxes, w, h = tile_symbols(model, tiles)
        nodes_by_mode = {
            "whole": merge(whole_symbols(model, image, w, h), w, h),
            "tiled": merge([s for _, s in detections], w, h),  # union of the tiles, fuzzy duplicate merge
            "stitched": stitch(detections, tile_boxes, w, h),  # tile ownership: what agent/run.py --tiled uses
        }
        for mode, nodes in nodes_by_mode.items():
            graph = {"image": {"width": w, "height": h}, "nodes": nodes, "edges": []}
            s = score(graph, gt)[0]["symbols"]
            rows.append(
                {
                    "sheet": sheet,
                    "model": args.model,
                    "mode": mode,
                    "calls": 1 if mode == "whole" else len(tile_boxes),
                    "pred": s["pred"],
                    "gt": s["gt"],
                    "precision": round(s["precision"], 2),
                    "recall": round(s["recall"], 2),
                    "f1": round(s["f1"], 2),
                }
            )
            print(json.dumps(rows[-1]), flush=True)
        save(rows[-len(nodes_by_mode) :])  # after every sheet, so a crash or usage limit keeps what finished


def save(new):
    """Merge rows into runs/tiling_compare.json, replacing the same sheet, model and mode."""
    out = REPO / "runs" / "tiling_compare.json"
    keys = {(r["sheet"], r["model"], r["mode"]) for r in new}
    old = json.loads(out.read_text()) if out.exists() else []
    old = [r for r in old if (r["sheet"], r.get("model", "gpt-6.1-sol"), r["mode"]) not in keys]
    out.write_text(json.dumps(old + new, indent=2))


if __name__ == "__main__":
    main()
