"""Symbol pass only: one call on the whole sheet vs one call per overlapping tile.

Same model, prompt and merge as agent/run.py --tiled; only the cropping differs.
Scores symbols against the PID2Graph ground truth (no model in the scoring).

Usage: uv run python eval/compare_tiling.py [sheet ...] [--model gpt-6.1-sol] [--effort low]
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from langchain_openai.chat_models.codex import _ChatOpenAICodex

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
from run import merge, tile_symbols, whole_symbols
from score import score

SHEETS = ["open100-0", "open100-1", "open100-2", "synth-0", "synth-1", "synth-2"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheets", nargs="*", default=SHEETS)
    ap.add_argument("--model", default="gpt-6.1-sol")
    ap.add_argument("--effort", default="low")
    args = ap.parse_args()
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
            n_tiles = len(json.loads((tiles / "tiles.json").read_text())["tiles"])
            tiled, w, h = tile_symbols(model, tiles)
        for mode, symbols in (("whole", whole_symbols(model, image, w, h)), ("tiled", tiled)):
            graph = {"image": {"width": w, "height": h}, "nodes": merge(symbols, w, h), "edges": []}
            s = score(graph, gt)[0]["symbols"]
            rows.append(
                {
                    "sheet": sheet,
                    "mode": mode,
                    "calls": 1 if mode == "whole" else n_tiles,
                    "pred": s["pred"],
                    "gt": s["gt"],
                    "precision": round(s["precision"], 2),
                    "recall": round(s["recall"], 2),
                    "f1": round(s["f1"], 2),
                }
            )
            print(json.dumps(rows[-1]), flush=True)
    out = REPO / "runs" / "tiling_compare.json"
    old = [r for r in json.loads(out.read_text()) if r["sheet"] not in args.sheets] if out.exists() else []
    out.write_text(json.dumps(old + rows, indent=2))


if __name__ == "__main__":
    main()
