"""Run the pid-parser skill with a LangChain Deep Agent on a ChatGPT-authenticated Codex model.

One-time login: uv run python -c "from langchain_openai.chatgpt_oauth import login_chatgpt; login_chatgpt()"

Usage: uv run python agent/run.py <workdir> [--model gpt-6-luna] [--effort low|medium|high] [--tiled | --whole]
The workdir must contain the drawing (drawing.png or drawing.jpg) and skills/pid-parser/.

Without a flag the agent runs the whole skill: it reads the tiles for the symbols, then runs connect.py.

--tiled: code runs pass 1 (symbols) tile by tile, one model call per tile, so no tile is skipped. Then code runs
connect.py (the connections, from the pixels, no model), validate.py and export.py. No agent loop.

--whole: like --tiled, but pass 1 is one call on the whole sheet (downscaled to MAX_SIDE like tile.py).

run.json counts the tokens of every model call.
"""

import argparse
import base64
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage
from langchain_openai.chat_models.codex import _ChatOpenAICodex
from PIL import Image
from pydantic import BaseModel

TILE_RETRIES = 2  # extra tries for a tile whose answer could not be parsed
MAX_RETRIES = 2  # times the agent is sent back when validate.py still fails after it stops
MAX_SIDE = 3600  # same as skills/pid-parser/scripts/tile.py; larger images exceed the API's image limit

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


def batch_retry(structured, requests, names):
    """Run one call per request. A small model sometimes answers a crowded tile with free text instead of the
    schema, so failed calls are retried; a call that still fails comes back as None, with a warning."""
    results = structured.batch(requests, config={"max_concurrency": 4}, return_exceptions=True)
    for _ in range(TILE_RETRIES):
        bad = [i for i, r in enumerate(results) if isinstance(r, Exception)]
        if not bad:
            break
        again = structured.batch([requests[i] for i in bad], config={"max_concurrency": 4}, return_exceptions=True)
        for i, r in zip(bad, again):
            results[i] = r
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"warning: tile {names[i]} gave no answer ({type(r).__name__})")
            results[i] = None
    return results


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
    results = batch_retry(model.with_structured_output(TileSymbols), requests, [t["file"] for t in meta["tiles"]])
    detections = []  # (index of the tile that saw it, symbol in original pixels)
    for i, (t, r) in enumerate(zip(meta["tiles"], results)):
        for s in r.symbols if r else []:
            if len(s.bbox) == 4:
                detections.append((i, s.model_copy(update={"bbox": to_original(s.bbox, t["box_original_px"])})))
    return detections, meta["tiles"], meta["width"], meta["height"]


def whole_image_b64(image):
    """The whole sheet as a base64 PNG, downscaled like tile.py so it fits the API's image limit."""
    img = Image.open(image).convert("RGB")
    scale = min(1.0, MAX_SIDE / max(img.size))
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def whole_symbols(model, image, width, height):
    """Pass 1 in one call on the whole sheet."""
    b64 = whole_image_b64(image)
    msg = HumanMessage(
        content=[
            {"type": "text", "text": TILE_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
    )
    result = model.with_structured_output(TileSymbols).invoke([msg])
    box = [0, 0, width, height]
    return [s.model_copy(update={"bbox": to_original(s.bbox, box)}) for s in result.symbols if len(s.bbox) == 4]


def tokens(handler):
    """Sum the usage the callback recorded over all models: input, cached input, output."""
    total = {"input": 0, "cached": 0, "output": 0}
    for u in handler.usage_metadata.values():
        total["input"] += u.get("input_tokens", 0)
        total["cached"] += (u.get("input_token_details") or {}).get("cache_read", 0)
        total["output"] += u.get("output_tokens", 0)
    return total


def centre(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def stitch(detections, tiles, width, height):
    """Drop the duplicates that overlapping tiles produce by ownership: a detection counts only in the tile whose
    centre is nearest to it, so each symbol is kept from the tile that sees it furthest from the cut edges.
    Boxes are then clipped and numbered by merge(). On the dense benchmark this raised precision from 0.93-0.94
    to 0.98-0.99 at the same recall; letting a neighbouring tile fill in when the owner missed a symbol added
    false positives and no recall."""
    centres = [centre(t["box_original_px"]) for t in tiles]

    def owner(s):
        cx, cy = centre(s.bbox)
        return min(range(len(tiles)), key=lambda j: (cx - centres[j][0]) ** 2 + (cy - centres[j][1]) ** 2)

    return merge([s for i, s in detections if owner(s) == i], width, height)


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
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--effort", choices=["low", "medium", "high"], help="reasoning effort (model default if unset)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--tiled", action="store_true", help="code runs pass 1 (symbols) tile by tile")
    mode.add_argument("--whole", action="store_true", help="code runs pass 1 in one call on the whole sheet")
    args = ap.parse_args()

    work = Path(args.workdir).resolve()
    drawing = next(work.glob("drawing.*"))
    skill = work / "skills" / "pid-parser"
    usage = UsageMetadataCallbackHandler()
    reasoning = {"reasoning": {"effort": args.effort}} if args.effort else {}
    model = _ChatOpenAICodex(model=args.model, callbacks=[usage], **reasoning)

    start = time.time()
    if args.tiled or args.whole:
        subprocess.run([sys.executable, skill / "scripts" / "tile.py", drawing, work / "tiles"], check=True)
        if args.whole:
            meta = json.loads((work / "tiles" / "tiles.json").read_text())
            width, height = meta["width"], meta["height"]
            symbols = whole_symbols(model, drawing, width, height)
        else:
            detections, tiles, width, height = tile_symbols(model, work / "tiles")
            symbols = [s for _, s in detections]
        nodes = merge(symbols, width, height) if args.whole else stitch(detections, tiles, width, height)
        graph = {"image": {"file": drawing.name, "width": width, "height": height}, "nodes": nodes, "edges": []}
        (work / "graph.json").write_text(json.dumps(graph, indent=2))
        print(f"pass 1: {len(symbols)} detections -> {len(nodes)} symbols")
        pass1 = tokens(usage)
        for script, extra in (("connect.py", [drawing]), ("validate.py", []), ("export.py", [work / "out"])):
            # a failing validation is reported, not fatal: the graph is still scored and exported
            subprocess.run(
                [sys.executable, skill / "scripts" / script, work / "graph.json", *extra], check=script != "validate.py"
            )
    else:
        pass1 = None
        task = (
            f"Use the pid-parser skill (SKILL_DIR is {skill}) to parse the P&ID at {drawing}. "
            f"Use {work} as the work directory: graph.json goes there and the export goes to {work}/out."
        )

    messages = []
    if not (args.tiled or args.whole):
        agent = create_deep_agent(
            model=model,
            system_prompt=SYSTEM,
            skills=[str(work / "skills")],
            backend=LocalShellBackend(root_dir=work, virtual_mode=False, timeout=300, inherit_env=True),
        )
        messages = [{"role": "user", "content": task}]
        for attempt in range(MAX_RETRIES + 1):
            result = agent.invoke({"messages": messages}, config={"recursion_limit": 400})
            messages = result["messages"]
            check = subprocess.run(
                [sys.executable, skill / "scripts" / "validate.py", work / "graph.json"],
                capture_output=True,
                text=True,
                check=False,  # a failing validation is the signal, not an error
            )
            if check.returncode == 0 or attempt == MAX_RETRIES:
                break
            # A small model can stop early. The validator says so (most symbols unconnected), so send it back.
            problem = (check.stdout + check.stderr)[-1500:]
            messages.append(
                {
                    "role": "user",
                    "content": f"validate.py still fails:\n{problem}\nFix it, run connect.py again if you changed "
                    "the symbols, then validate and export again.",
                }
            )
    elapsed = time.time() - start

    total = tokens(usage)
    meta = {
        "model": args.model,
        "effort": args.effort,
        "tiled": args.tiled,
        "whole": args.whole,
        "harness": "deepagents",
        "seconds": round(elapsed),
        "tool_calls": sum(len(getattr(m, "tool_calls", None) or []) for m in messages),
        "input_tokens": total["input"],  # every model call, pass 1 included
        "cached_tokens": total["cached"],
        "output_tokens": total["output"],
        "pass1_input_tokens": pass1["input"] if pass1 else None,
    }
    (work / "run.json").write_text(json.dumps(meta, indent=2))
    print(messages[-1].text if messages else "done")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
