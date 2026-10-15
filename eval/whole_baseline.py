"""The naive approach: one model call, the whole sheet in, the complete graph out. No tiles, no ids drawn on the
image, no second pass. Scored with the same scorer and the same pipes-to-edges conversion as the pipeline.

Usage: uv run python eval/whole_baseline.py <sheet> [--model gpt-6-luna | claude-sonnet-5-5]
"""

import argparse
import json
import sys
import time
from pathlib import Path

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import HumanMessage
from langchain_openai.chat_models.codex import _ChatOpenAICodex
from pydantic import BaseModel

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
from compare_tiling import ClaudeCLI
from run import Pipe, SymbolType, add_edges, to_original, tokens, whole_image_b64
from score import score


class DirectSymbol(BaseModel):
    id: str
    type: SymbolType
    tag: str | None
    bbox: list[float]


class DirectGraph(BaseModel):
    symbols: list[DirectSymbol]
    pipes: list[Pipe]


PROMPT = """This is a whole P&ID. Digitize it into a graph in one pass.
symbols: every symbol (valves, pumps, tanks/vessels, heat exchangers, instrument bubbles, fittings such as
reducers, flanges and strainers, off-page connectors, other equipment). Give each a unique id (s1, s2, ...), its
type, its tag text exactly as printed (null if none or unreadable, never guess), and bbox [x1, y1, x2, y2]
normalized to the image: 0 is the left/top edge, 1000 the right/bottom edge.
pipes: follow every drawn line and report the symbol ids it joins. A line ends at any symbol it reaches, so an
inline valve splits a pipe: A - valve - B is two pipes [A, valve] and [valve, B]. A tee joins all its branches
into one pipe [A, B, C]. Lines that cross without a dot are separate. kind is signal for dashed or instrument
lines, else process. line is the line-number label printed along the pipe, copied exactly, or null.
Skip the border, title block, notes and plain text. Use only ids you gave in symbols."""


def to_graph(result, width, height):
    nodes, seen = [], set()
    for s in result.symbols:
        if s.id in seen or len(s.bbox) != 4:
            continue
        x1, y1, x2, y2 = to_original(s.bbox, [0, 0, width, height])
        x1, x2 = sorted((max(0, min(x1, width)), max(0, min(x2, width))))
        y1, y2 = sorted((max(0, min(y1, height)), max(0, min(y2, height))))
        if x2 - x1 >= 1 and y2 - y1 >= 1:
            seen.add(s.id)
            nodes.append({"id": s.id, "type": s.type, "tag": s.tag, "bbox": [x1, y1, x2, y2]})
    graph = {"image": {"width": width, "height": height}, "nodes": nodes, "edges": []}
    add_edges(graph, result.pipes)
    return graph


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--model", default="gpt-6-luna")
    args = ap.parse_args()

    image = next((REPO / "samples").glob(f"{args.sheet}.*[!l]"))
    usage = UsageMetadataCallbackHandler()
    model = (
        ClaudeCLI(args.model)
        if args.model.startswith("claude")
        else _ChatOpenAICodex(model=args.model, callbacks=[usage])
    )
    from PIL import Image

    width, height = Image.open(image).size
    msg = HumanMessage(
        content=[
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{whole_image_b64(image)}"}},
        ]
    )
    start = time.time()
    graph = to_graph(model.with_structured_output(DirectGraph).invoke([msg]), width, height)
    seconds = round(time.time() - start)

    out = REPO / "runs" / "whole" / args.model / args.sheet
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text(json.dumps(graph, indent=2))
    result = score(graph, REPO / "samples" / f"{args.sheet}.graphml")[0]
    cost = {"usd": round(model.cost, 2)} if isinstance(model, ClaudeCLI) else tokens(usage)
    (out / "score.json").write_text(json.dumps(result, indent=2))
    (out / "run.json").write_text(
        json.dumps({"model": args.model, "approach": "whole", "seconds": seconds, "cost": cost})
    )
    s, c = result["symbols"], result["connections"]
    print(f"whole {args.model} {args.sheet}: {seconds}s {cost}")
    print(
        f"  symbols     P {s['precision']:.2f} R {s['recall']:.2f} F1 {s['f1']:.2f}  ({s['pred']} predicted, {s['gt']} real)"
    )
    print(
        f"  connections P {c['precision']:.2f} R {c['recall']:.2f} F1 {c['f1']:.2f}  symbol-F1 {c['symbol_f1']:.2f}  ({c['pred']} pairs, {c['gt']} real)"
    )


if __name__ == "__main__":
    main()
