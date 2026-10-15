"""Run the pid-parser skill with a LangChain Deep Agent on a ChatGPT-authenticated Codex model.

One-time login: uv run python -c "from langchain_openai.chatgpt_oauth import login_chatgpt; login_chatgpt()"

Usage: uv run python agent/run.py <workdir> [--model gpt-6.1-sol] [--effort low|medium|high] [--tiled | --whole] [--pipes agent|oneshot] [--pipe-model MODEL]
The workdir must contain the drawing (drawing.png or drawing.jpg) and skills/pid-parser/.

--tiled: code runs pass 1 (symbols) tile by tile, one model call per tile, so no tile is skipped.
The agent then reads the connections on the whole sheet (pass 2), validates and exports, on
--pipe-model if set. Per-tile connection passes were tried and lost to the whole-sheet agent:
pipes cross tiles, so reading them needs the whole sheet.

--whole: like --tiled, but pass 1 is one call on the whole sheet (downscaled to MAX_SIDE like tile.py).
The tiles are still made for the agent's pipe pass.

--pipes oneshot (needs --tiled or --whole): pass 2 is one model call that sees the marked overview and every
marked tile at once, then code adds the edges, validates and exports. No agent loop, so the images are sent once
instead of being re-sent on every turn of a conversation. --rounds N adds N follow-up calls that ask only for
the pipes still missing, given the ones found so far.

run.json counts the tokens of every model call: pass 1, and the agent or the one-shot call.
"""

import argparse
import base64
import copy
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
    detections = []  # (index of the tile that saw it, symbol in original pixels)
    for i, (t, r) in enumerate(zip(meta["tiles"], results)):
        for s in r.symbols:
            if len(s.bbox) == 4:
                detections.append((i, s.model_copy(update={"bbox": to_original(s.bbox, t["box_original_px"])})))
    return detections, meta["tiles"], meta["width"], meta["height"]


def whole_symbols(model, image, width, height):
    """Pass 1 in one call on the whole sheet, downscaled like tile.py so it fits the API's image limit."""
    img = Image.open(image).convert("RGB")
    scale = min(1.0, MAX_SIDE / max(img.size))
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    msg = HumanMessage(
        content=[
            {"type": "text", "text": TILE_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
    )
    result = model.with_structured_output(TileSymbols).invoke([msg])
    box = [0, 0, width, height]
    return [s.model_copy(update={"bbox": to_original(s.bbox, box)}) for s in result.symbols if len(s.bbox) == 4]


class Pipe(BaseModel):
    ids: list[str]
    kind: Literal["process", "signal"]
    line: str | None


class Pipes(BaseModel):
    pipes: list[Pipe]


PIPE_PROMPT = """Image 1 is the whole P&ID. The other images are overlapping crops of it, in reading order.
Every symbol has a red id label. Follow every line on the drawing and report the ids it joins.
A line ends at any symbol it reaches, so an inline valve splits a pipe: A - valve - B is two pipes [A, valve] and
[valve, B]. A tee joins all its branches into one pipe [A, B, C]. Lines that cross without a dot are separate.
kind is signal for dashed or instrument lines, else process. line is the line-number label printed along the
pipe, copied exactly, or null if none. Use only ids that appear in the images. Report each pipe once, even if it
shows in several crops."""


def image_block(path):
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()},
    }


MORE_PROMPT = (
    PIPE_PROMPT
    + """

These pipes were already found, each written as the ids it joins: {found}.
Symbols with no pipe yet: {alone}.
List only the pipes that are still missing: a drawn line that joins symbols the pipes above do not already join.
If nothing is missing, return an empty list."""
)


def oneshot_graph(model, tiles_dir, base, rounds, work):
    """Pass 2 in one call that sees the marked overview and every marked tile, then up to `rounds` follow-up
    calls that show the pipes found so far and ask only for the missing ones. Each round's graph is saved too."""
    meta = json.loads((tiles_dir / "tiles.json").read_text())
    images = [image_block(tiles_dir / "marked_overview.png")]
    images += [image_block(tiles_dir / f"marked_{t['file']}") for t in meta["tiles"]]
    structured = model.with_structured_output(Pipes)

    def ask(prompt):
        return structured.invoke([HumanMessage(content=[{"type": "text", "text": prompt}, *images])]).pipes

    pipes = ask(PIPE_PROMPT)
    for k in range(rounds + 1):
        graph = copy.deepcopy(base)
        add_edges(graph, pipes)
        (work / f"graph_round{k}.json").write_text(json.dumps(graph))
        if k == rounds:
            return graph
        linked = {i for e in graph["edges"] for i in (e["source"], e["target"])}
        alone = [n["id"] for n in graph["nodes"] if n["type"] != "junction" and n["id"] not in linked]
        found = "; ".join("-".join(p.ids) for p in pipes)
        pipes += ask(MORE_PROMPT.format(found=found, alone=", ".join(alone) or "none"))


def add_edges(graph, pipes):
    """Two ids on a pipe: one edge. Three or more (a tee): a junction node joined to each id."""
    boxes = {n["id"]: n["bbox"] for n in graph["nodes"]}
    seen = set()
    for pipe in pipes:
        members = tuple(sorted({i for i in pipe.ids if i in boxes}))
        if len(members) < 2 or (members, pipe.kind) in seen:
            continue
        seen.add((members, pipe.kind))
        attrs = {"kind": pipe.kind, **({"line": pipe.line} if pipe.line else {})}
        if len(members) == 2:
            graph["edges"].append({"source": members[0], "target": members[1], **attrs})
            continue
        cx = sum((boxes[m][0] + boxes[m][2]) / 2 for m in members) / len(members)
        cy = sum((boxes[m][1] + boxes[m][3]) / 2 for m in members) / len(members)
        jid = f"j{sum(n['type'] == 'junction' for n in graph['nodes']) + 1}"
        graph["nodes"].append({"id": jid, "type": "junction", "tag": None, "bbox": [cx - 3, cy - 3, cx + 3, cy + 3]})
        graph["edges"] += [{"source": m, "target": jid, **attrs} for m in members]


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
    ap.add_argument("--model", default="gpt-6.1-sol")
    ap.add_argument("--effort", choices=["low", "medium", "high"], help="reasoning effort (model default if unset)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--tiled", action="store_true", help="code runs pass 1 (symbols) tile by tile")
    mode.add_argument("--whole", action="store_true", help="code runs pass 1 in one call on the whole sheet")
    ap.add_argument("--pipes", choices=["agent", "oneshot"], default="agent", help="pass 2: a Deep Agent, or one call")
    ap.add_argument(
        "--rounds", type=int, default=0, help="with --pipes oneshot: follow-up calls asking for missing pipes"
    )
    ap.add_argument("--pipe-model", help="model for the agent: connections, validate, export (default: --model)")
    args = ap.parse_args()
    if args.pipes == "oneshot" and not (args.tiled or args.whole):
        ap.error("--pipes oneshot needs --tiled or --whole")

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
        if args.pipe_model:
            model = _ChatOpenAICodex(model=args.pipe_model, callbacks=[usage], **reasoning)
        if args.pipes == "oneshot":
            subprocess.run(
                [sys.executable, skill / "scripts" / "mark.py", work / "graph.json", work / "tiles"], check=True
            )
            graph = oneshot_graph(model, work / "tiles", graph, args.rounds, work)
            (work / "graph.json").write_text(json.dumps(graph, indent=2))
            print(f"pass 2: {len(graph['edges'])} edges")
            subprocess.run([sys.executable, skill / "scripts" / "validate.py", work / "graph.json"], check=False)
            subprocess.run(
                [sys.executable, skill / "scripts" / "export.py", work / "graph.json", work / "out"], check=True
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

    messages = []
    if args.pipes == "agent":
        agent = create_deep_agent(
            model=model,
            system_prompt=SYSTEM,
            skills=[str(work / "skills")],
            backend=LocalShellBackend(root_dir=work, virtual_mode=False, timeout=300, inherit_env=True),
        )
        result = agent.invoke({"messages": [{"role": "user", "content": task}]}, config={"recursion_limit": 400})
        messages = result["messages"]
    elapsed = time.time() - start

    total = tokens(usage)
    meta = {
        "model": args.model,
        "effort": args.effort,
        "tiled": args.tiled,
        "whole": args.whole,
        "pipes": args.pipes,
        "rounds": args.rounds if args.pipes == "oneshot" else None,
        "pipe_model": args.pipe_model,
        "harness": "deepagents",
        "seconds": round(elapsed),
        "tool_calls": sum(len(getattr(m, "tool_calls", None) or []) for m in messages),
        "input_tokens": total["input"],  # every model call, pass 1 included
        "cached_tokens": total["cached"],
        "output_tokens": total["output"],
        "pass1_input_tokens": pass1["input"] if args.tiled or args.whole else None,
    }
    (work / "run.json").write_text(json.dumps(meta, indent=2))
    print(messages[-1].text if messages else "done")
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
