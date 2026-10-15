"""Collect runs/*/<sheet>/r*/score.json into one table (markdown) and results.csv.

Usage: summary.py [runs_dir]
"""

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

runs = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "runs")
rows = []
for score in sorted(runs.glob("*/*/r*/score.json")):
    rep_dir = score.parent
    cfg, sheet, rep = rep_dir.parent.parent.name, rep_dir.parent.name, rep_dir.name
    if cfg.startswith("_"):
        continue
    s = json.loads(score.read_text())
    meta = json.loads((rep_dir / "run.json").read_text())
    rows.append(
        {
            "config": cfg,
            "sheet": sheet,
            "repeat": rep,
            "seconds": meta.get("seconds"),
            "sym_p": s["symbols"]["precision"],
            "sym_r": s["symbols"]["recall"],
            "sym_f1": s["symbols"]["f1"],
            "class_acc": s["symbols"]["class_accuracy"],
            "conn_p": s["connections"]["precision"],
            "conn_r": s["connections"]["recall"],
            "conn_f1": s["connections"]["f1"],
        }
    )
missing = [
    p
    for p in runs.glob("*/*/r*")
    if not p.name.startswith("_") and not (p / "score.json").exists() and not p.parent.parent.name.startswith("_")
]

with open(runs / "results.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

groups = defaultdict(list)
for r in rows:
    subset = "open100" if r["sheet"].startswith("open100") else "synth"
    groups[(r["config"], subset)].append(r)


def mean(rs, k):
    vals = [r[k] for r in rs if r[k] is not None]
    return statistics.mean(vals) if vals else float("nan")


print("| config | subset | runs | symbol P | symbol R | symbol F1 | class acc | conn P | conn R | conn F1 | avg s |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for (cfg, subset), rs in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
    print(
        f"| {cfg} | {subset} | {len(rs)} | "
        + " | ".join(
            f"{mean(rs, k):.2f}" for k in ("sym_p", "sym_r", "sym_f1", "class_acc", "conn_p", "conn_r", "conn_f1")
        )
        + f" | {mean(rs, 'seconds'):.0f} |"
    )
if missing:
    print("\nNo graph.json / score:", ", ".join(str(p.relative_to(runs)) for p in sorted(missing)))
