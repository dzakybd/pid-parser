"""Score a skill graph.json against the PID2Graph ground truth.

Symbols are matched one-to-one, closest centers first, ignoring class. A
predicted center matches a true symbol when it falls inside that symbol's
box enlarged by half its size (|dx| <= 0.75 w, |dy| <= 0.75 h, at least
MIN_HALF px), so a misplaced box cannot claim a neighbouring symbol. Class accuracy is reported over
matched symbols. Connections are symbol pairs sharing a pipe network (see
nets.py); a predicted pair counts when both ends matched and the mapped pair
is in the ground truth.

Usage: score.py <graph.json> <gt.graphml> [--overlay <image> <out.png>]
"""

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from nets import box_center, load_gt, load_pred

MIN_HALF = 10


def f1(p, r):
    return 2 * p * r / (p + r) if p + r else 0.0


def match(pred, gt):
    cand = []
    for a, pa in pred.items():
        ca = box_center(pa["box"])
        for b, gb in gt.items():
            cb, (x1, y1, x2, y2) = box_center(gb["box"]), gb["box"]
            if abs(ca[0] - cb[0]) <= max(0.75 * (x2 - x1), MIN_HALF) and abs(ca[1] - cb[1]) <= max(
                0.75 * (y2 - y1), MIN_HALF
            ):
                cand.append((math.dist(ca, cb), a, b))
    cand.sort()
    m, used = {}, set()
    for _, a, b in cand:
        if a not in m and b not in used:
            m[a] = b
            used.add(b)
    return m


def symbol_f1(m, pr_pairs, gt_pairs):
    """Macro average, over the real symbols, of the F1 between a symbol's predicted and true neighbours.

    Pair F1 counts every connected pair, so one header joining 20 symbols weighs 190 pairs. Here the same
    header weighs 20 symbols, which keeps a few big networks from deciding the score on a dense sheet. Every
    real symbol that has a neighbour counts, and one the model missed scores 0, so finding few symbols cannot
    look good."""
    pred = defaultdict(set)
    for pair in pr_pairs:
        a, b = tuple(pair)
        if a in m and b in m:
            pred[m[a]].add(m[b])
            pred[m[b]].add(m[a])
    true = defaultdict(set)
    for pair in gt_pairs:
        a, b = tuple(pair)
        true[a].add(b)
        true[b].add(a)
    scores = []
    for g in set(true) | set(m.values()):
        t, p = true[g], pred[g]
        if not t and not p:
            continue
        hit = len(t & p)
        scores.append(f1(hit / len(p) if p else 0.0, hit / len(t) if t else 0.0))
    return sum(scores) / len(scores) if scores else 0.0


def score(graph, gt_path):
    gt_sym, gt_pairs = load_gt(gt_path)
    pr_sym, pr_pairs = load_pred(graph)
    m = match(pr_sym, gt_sym)

    sp = len(m) / len(pr_sym) if pr_sym else 0.0
    sr = len(m) / len(gt_sym) if gt_sym else 0.0
    cls_ok = sum(pr_sym[a]["cls"] == gt_sym[b]["cls"] for a, b in m.items())

    hit = 0
    for pair in pr_pairs:
        a, b = tuple(pair)
        if a in m and b in m and frozenset((m[a], m[b])) in gt_pairs:
            hit += 1
    cp = hit / len(pr_pairs) if pr_pairs else 0.0
    cr = hit / len(gt_pairs) if gt_pairs else 0.0

    missed = Counter(gt_sym[b]["cls"] for b in gt_sym if b not in set(m.values()))
    return {
        "symbols": {
            "pred": len(pr_sym),
            "gt": len(gt_sym),
            "matched": len(m),
            "precision": sp,
            "recall": sr,
            "f1": f1(sp, sr),
            "class_accuracy": cls_ok / len(m) if m else 0.0,
        },
        "connections": {
            "pred": len(pr_pairs),
            "gt": len(gt_pairs),
            "correct": hit,
            "precision": cp,
            "recall": cr,
            "f1": f1(cp, cr),
            "symbol_f1": symbol_f1(m, pr_pairs, gt_pairs),
        },
        "missed_by_class": dict(missed),
    }, (pr_sym, gt_sym, m, graph)


def overlay(image, out, pr_sym, gt_sym, m, graph):
    from PIL import Image, ImageDraw

    im = Image.open(image).convert("RGB")
    im = Image.blend(im, Image.new("RGB", im.size, "white"), 0.5)
    d = ImageDraw.Draw(im)
    lw = max(2, im.width // 700)
    nodes = {n["id"]: n for n in graph["nodes"]}
    for e in graph["edges"]:
        a, b = nodes[e["source"]]["bbox"], nodes[e["target"]]["bbox"]
        d.line([box_center(a), box_center(b)], fill=(40, 90, 230), width=lw)
    matched_gt = set(m.values())
    for b, g in gt_sym.items():
        if b not in matched_gt:
            d.rectangle(g["box"], outline=(240, 140, 0), width=lw + 1)  # missed
    for a, p in pr_sym.items():
        d.rectangle(p["box"], outline=(0, 160, 60) if a in m else (220, 30, 30), width=lw + 1)
    im.save(out)


def main(argv):
    graph = json.loads(Path(argv[0]).read_text())
    result, ctx = score(graph, argv[1])
    print(json.dumps(result, indent=2))
    if len(argv) == 5 and argv[2] == "--overlay":
        overlay(argv[3], argv[4], *ctx)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 6):
        sys.exit(__doc__)
    main(sys.argv[1:])
