"""Pull a few full sheets and their ground-truth GraphML out of the 9.3 GB PID2Graph zip.

Uses HTTP range requests, so only the requested files are downloaded (a few MB).
PID2Graph: https://zenodo.org/records/14803338 (CC BY-SA 4.0). The sheets come from its "Dataset PID" part
(Digitize-PID, Paliwal et al., CC BY-SA 4.0).

Usage: uv run python eval/fetch_samples.py [outdir]
"""

import sys
from pathlib import Path

from remotezip import RemoteZip

URL = "https://zenodo.org/records/14803338/files/PID2Graph.zip"
# (folder in the zip, file prefix, image extension, sheet ids): the dense benchmark, the six sheets with the most
# symbols (176-190). dpid-269 (190 symbols, 732 connected pairs) is the one the results are about.
SHEETS = [
    ("PID2Graph/Complete/Dataset PID", "dpid", "png", ["269", "227", "36", "156", "126", "61"]),
]

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "samples")
out.mkdir(parents=True, exist_ok=True)
with RemoteZip(URL) as z:
    for folder, prefix, ext, ids in SHEETS:
        for i in ids:
            for suffix in ("graphml", ext):
                target = out / f"{prefix}-{i}.{suffix}"
                if not target.exists():
                    target.write_bytes(z.read(f"{folder}/{i}.{suffix}"))
                print(target)
