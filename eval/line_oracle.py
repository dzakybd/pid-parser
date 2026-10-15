"""Diagnostic: how good is classical line tracing if the symbol boxes were perfect?

Takes the ground-truth symbol boxes, finds pipe networks with OpenCV morphology
(long horizontal/vertical strokes), links each symbol to the networks its box
touches, and scores the resulting connections against the ground truth.

Usage: line_oracle.py <image> <gt.graphml> [--debug out.png]
"""

import sys
from itertools import combinations

import cv2
import numpy as np
from nets import load_gt


def line_mask(gray, min_len):
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    h = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1)))
    v = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_len)))
    return cv2.bitwise_or(h, v), binary


def pairs_from_lines(mask, boxes, pad):
    """boxes: {id: (x1, y1, x2, y2)}. Symbol interiors are cut out so lines inside a symbol don't link."""
    cut = mask.copy()
    for x1, y1, x2, y2 in boxes.values():
        cut[int(y1) + 2 : int(y2) - 1, int(x1) + 2 : int(x2) - 1] = 0
    _, labels = cv2.connectedComponents(cut, connectivity=8)
    H, W = mask.shape
    members = {}
    for sid, (x1, y1, x2, y2) in boxes.items():
        xa, ya = max(0, int(x1 - pad)), max(0, int(y1 - pad))
        xb, yb = min(W, int(x2 + pad) + 1), min(H, int(y2 + pad) + 1)
        for net in np.unique(labels[ya:yb, xa:xb]):
            if net:
                members.setdefault(int(net), set()).add(sid)
    pairs = set()
    for group in members.values():
        pairs.update(frozenset(p) for p in combinations(sorted(group), 2))
    return pairs, labels


def main(image, graphml, debug=None, min_len=None, pad=4):
    gray = cv2.imread(image, cv2.IMREAD_GRAYSCALE)
    min_len = min_len or max(20, gray.shape[1] // 100)
    mask, _ = line_mask(gray, min_len)
    symbols, gt_pairs = load_gt(graphml)
    boxes = {k: v["box"] for k, v in symbols.items()}
    pairs, labels = pairs_from_lines(mask, boxes, pad)
    hit = len(pairs & gt_pairs)
    p = hit / len(pairs) if pairs else 0
    r = hit / len(gt_pairs) if gt_pairs else 0
    f = 2 * p * r / (p + r) if p + r else 0
    print(
        f"min_len={min_len} pad={pad} pred={len(pairs)} gt={len(gt_pairs)} correct={hit} P={p:.2f} R={r:.2f} F1={f:.2f}"
    )
    if debug:
        rng = np.random.default_rng(0)
        colors = rng.integers(40, 220, size=(labels.max() + 1, 3), dtype=np.uint8)
        colors[0] = 255
        out = colors[labels]
        for x1, y1, x2, y2 in boxes.values():
            cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 0), 2)
        cv2.imwrite(debug, out)
    return f


if __name__ == "__main__":
    args = sys.argv[1:]
    dbg = args[args.index("--debug") + 1] if "--debug" in args else None
    main(args[0], args[1], dbg)
