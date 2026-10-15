"""Run the pid-parser skill with a LangChain Deep Agent on a ChatGPT-authenticated Codex model.

One-time login: uv run python -c "from langchain_openai.chatgpt_oauth import login_chatgpt; login_chatgpt()"

Usage: uv run python agent/run.py <workdir> [--model gpt-6-sol] [--effort low|medium|high] [--tiled [--pipe-model gpt-6-sol]]
The workdir must contain the drawing (drawing.png or drawing.jpg) and skills/pid-parser/.

--tiled: code runs pass 1 (symbols) tile by tile, one model call per tile, so no tile is skipped.
The agent then reads the connections on the whole sheet (pass 2), validates and exports, on
--pipe-model if set. Per-tile connection passes were tried and lost to the whole-sheet agent:
pipes cross tiles, so reading them needs the whole sheet.
"""

import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_core.messages import HumanMessage
from langchain_openai.chat_models.codex import _ChatOpenAICodex
from pydantic import BaseModel

SYSTEM = """You digitize engineering drawings. File tools and shell commands both use the real absolute
paths given in the task. Work without asking questions; nobody will answer. Finish by printing a short summary."""

SymbolType = Literal[
    "valve",
    "control_valve",
    "relief_valve",
    "check_valve",
    "pump",
    "compressor",
    "tank",
    "vessel",
    "column",
    "heat_exchanger",
    "instrument",
    "fitting",
    "off_page",
    "equipment",
]


class Symbol(BaseModel):
    type: SymbolType
    tag: str | None
    bbox: list[float]


class TileSymbols(BaseModel):
    symbols: list[Symbol]


TILE_PROMPT = """This is one crop of a P&ID (ignore the cyan grid). List every symbol that is fully or partly inside the crop:
valves, pumps, tanks/vessels, heat exchangers, instrument bubbles, fittings (reducers, flanges, nozzles,
blinds, strainers, flow elements), off-page connector boxes or arrows, other equipment.
For each: type, tag text exactly as printed (null if none or unreadable, never guess), and bbox
[x1, y1, x2, y2] normalized to this crop: 0 is the left/top edge, 1000 the right/bottom edge.
Skip the border, title block, notes, legends, line-number labels and plain text."""


def to_original(bbox, tile_box):
    """Crop-normalized 0-1000 box -> original drawing pixels."""
    tx1, ty1, tx2, ty2 = tile_box
    sx, sy = (tx2 - tx1) / 1000, (ty2 - ty1) / 1000
    return [tx1 + bbox[0] * sx, ty1 + bbox[1] * sy, tx1 + bbox[2] * sx, ty1 + bbox[3] * sy]


def tile_symbols(model, tiles_dir):
    meta = json.loads((tiles_dir / "tiles.json").read_text())
    requests = []
    for t in meta["tiles"]:
        b64 = base64.b64encode((tiles_dir / t["file"]).read_bytes()).decode()
        requests.append(
            [
                HumanMessage(
                    content=[
                        {"type": "text", "text": TILE_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ]
                )
            ]
        )
    results = model.with_structured_output(TileSymbols).batch(requests, config={"max_concurrency": 4})
    symbols = []
    for t, r in zip(meta["tiles"], results):
        for s in r.symbols:
            if len(s.bbox) == 4:
                symbols.append(s.model_copy(update={"bbox": to_original(s.bbox, t["box_original_px"])}))
    return symbols, meta["width"], meta["height"]


def merge(symbols, width, height):
    """Collapse duplicates from overlapping tiles: same spot means same symbol."""
    boxes = []
    for s in symbols:
        x1, y1, x2, y2 = s.bbox
        x1, x2 = sorted((max(0, min(x1, width)), max(0, min(x2, width))))
        y1, y2 = sorted((max(0, min(y1, height)), max(0, min(y2, height))))
        if x2 - x1 >= 1 and y2 - y1 >= 1:
            boxes.append({"type": s.type, "tag": s.tag, "bbox": [x1, y1, x2, y2]})
    boxes.sort(key=lambda b: (b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1]), reverse=True)

    kept = []
    for b in boxes:
        cx, cy = (b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2
        dup = next(
            (
                k
                for k in kept
                if k["bbox"][0] <= cx <= k["bbox"][2]
                and k["bbox"][1] <= cy <= k["bbox"][3]
                and (k["tag"] is None or b["tag"] is None or k["tag"] == b["tag"])
            ),
            None,
        )
        if dup is None:
            kept.append(b)
        elif dup["tag"] is None and b["tag"]:
            dup["tag"] = b["tag"]
    return [{"id": f"s{i + 1}", **k} for i, k in enumerate(kept)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--model", default="gpt-6-sol")
    ap.add_argument("--effort", choices=["low", "medium", "high"], help="reasoning effort (model default if unset)")
    ap.add_argument("--tiled", action="store_true", help="code runs pass 1 (symbols) tile by tile")
    ap.add_argument("--pipe-model", help="model for the agent: connections, validate, export (default: --model)")
    args = ap.parse_args()

    work = Path(args.workdir).resolve()
    drawing = next(work.glob("drawing.*"))
    skill = work / "skills" / "pid-parser"
    model = _ChatOpenAICodex(model=args.model, **({"reasoning": {"effort": args.effort}} if args.effort else {}))

    start = time.time()
    if args.tiled:
        subprocess.run([sys.executable, skill / "scripts" / "tile.py", drawing, work / "tiles"], check=True)
        symbols, width, height = tile_symbols(model, work / "tiles")
        nodes = merge(symbols, width, height)
        graph = {"image": {"file": drawing.name, "width": width, "height": height}, "nodes": nodes, "edges": []}
        (work / "graph.json").write_text(json.dumps(graph, indent=2))
        print(f"pass 1: {len(symbols)} tile detections -> {len(nodes)} symbols")
        if args.pipe_model:
            model = _ChatOpenAICodex(
                model=args.pipe_model, **({"reasoning": {"effort": args.effort}} if args.effort else {})
            )
        task = (
            f"Use the pid-parser skill (SKILL_DIR is {skill}) on the P&ID at {drawing}. Work directory: {work}. "
            f"Steps 1-2 are done: {work}/tiles has the tiles and {work}/graph.json lists the symbols. "
            f"Do steps 3, 5 and 6: mark the ids, add the connections, validate and fix, then export to {work}/out."
        )
    else:
        task = (
            f"Use the pid-parser skill (SKILL_DIR is {skill}) to parse the P&ID at {drawing}. "
            f"Use {work} as the work directory: graph.json goes there and the export goes to {work}/out."
        )

    agent = create_deep_agent(
        model=model,
        system_prompt=SYSTEM,
        skills=[str(work / "skills")],
        backend=LocalShellBackend(root_dir=work, virtual_mode=False, timeout=300, inherit_env=True),
    )
    result = agent.invoke({"messages": [{"role": "user", "content": task}]}, config={"recursion_limit": 400})
    elapsed = time.time() - start

    messages = result["messages"]
    usage = {"input_tokens": 0, "output_tokens": 0}
    for m in messages:
        for k in usage:
            usage[k] += (getattr(m, "usage_metadata", None) or {}).get(k, 0)
    meta = {
        "model": args.model,
        "effort": args.effort,
        "tiled": args.tiled,
        "pipe_model": args.pipe_model,
        "harness": "deepagents",
        "seconds": round(elapsed),
        "tool_calls": sum(len(getattr(m, "tool_calls", None) or []) for m in messages),
        **usage,  # agent only; the per-tile symbol calls of --tiled are not counted
    }
    (work / "run.json").write_text(json.dumps(meta, indent=2))
    print(messages[-1].text)
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
