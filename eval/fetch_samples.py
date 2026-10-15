"""Pull a few full sheets and their ground-truth GraphML out of the 9.3 GB PID2Graph zip.

Uses HTTP range requests, so only the requested files are downloaded (a few MB).
PID2Graph: https://zenodo.org/records/14803338 (CC BY-SA 4.0). The OPEN100 sheets
come from the Energy Impact Center (open-100.com) with no licence stated, so this
repo fetches them instead of redistributing them.

Usage: uv run python eval/fetch_samples.py [outdir]
"""

import sys
from pathlib import Path

from remotezip import RemoteZip

URL = "https://zenodo.org/records/14803338/files/PID2Graph.zip"
SHEETS = [("PID2Graph OPEN100", "open100", "png"), ("PID2Graph Synthetic", "synth", "jpg")]
IDS = ["0", "1", "2"]

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "samples")
out.mkdir(parents=True, exist_ok=True)
with RemoteZip(URL) as z:
    for folder, prefix, ext in SHEETS:
        for i in IDS:
            for suffix in ("graphml", ext):
                target = out / f"{prefix}-{i}.{suffix}"
                if not target.exists():
                    target.write_bytes(z.read(f"PID2Graph/Complete/{folder}/{i}.{suffix}"))
                print(target)
