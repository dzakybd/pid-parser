"""Connections without a model: erase the symbol boxes from the binarized sheet, label what is left as
line components, and call two symbols connected when both touch the same component.

Usage: cv_connect.py <sheet> [--ring 6] [--min 30]   (uses the ground-truth symbol boxes: the ceiling for this idea)
"""

import argparse
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/pid-parser/scripts"))
from connect import networks
from nets import load_gt
from score import f1

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def cv_pairs(image, symbols, ring=6, min_pixels=30):
    return {frozenset(p) for ids in networks(image, symbols, ring, min_pixels) for p in combinations(sorted(ids), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--ring", type=int, nargs="+", default=[3, 6, 10])
    ap.add_argument("--min", type=int, default=30)
    args = ap.parse_args()
    gt = SAMPLES / f"{args.sheet}.graphml"
    image = next(SAMPLES.glob(f"{args.sheet}.*[!l]"))
    sym, true = load_gt(gt)
    boxes = {k: v["box"] for k, v in sym.items()}
    for ring in args.ring:
        pred = cv_pairs(image, boxes, ring, args.min)
        hit = len(pred & true)
        p, r = hit / max(len(pred), 1), hit / max(len(true), 1)
        print(f"ring {ring:>2}: pred {len(pred):>5} true {len(true)} P {p:.2f} R {r:.2f} F1 {f1(p, r):.2f}")


if __name__ == "__main__":
    main()
