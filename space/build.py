"""Pack precomputed runs on the synthetic sheets into space/data for the Hugging Face Space.

Only synthetic PID2Graph sheets (CC BY-SA 4.0) go in: the OPEN100 sheets have no licence.

Usage: uv run python space/build.py [runs/<config>]   (default: the gpt-6.1-sol low-effort tiled runs)
"""

import json
import shutil
import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
SHEETS = {"synth-0": "Synthetic sheet 1", "synth-1": "Synthetic sheet 2", "synth-2": "Synthetic sheet 3"}
WEB_WIDTH = 2400  # drawings are 7000 px wide; the overlay uses original pixels via the SVG viewBox


def main(config):
    data = REPO / "space" / "data"
    shutil.rmtree(data, ignore_errors=True)
    index = []
    for sheet, title in SHEETS.items():
        run = config / sheet / "r1"
        dest = data / sheet
        shutil.copytree(run / "out", dest / "out")
        shutil.copy(run / "graph.json", dest / "graph.json")
        img = Image.open(REPO / "samples" / f"{sheet}.jpg").convert("RGB")
        img.resize((WEB_WIDTH, round(img.height * WEB_WIDTH / img.width)), Image.LANCZOS).save(
            dest / "drawing.jpg", quality=85
        )
        meta = json.loads((run / "run.json").read_text())
        score = json.loads((run / "score.json").read_text())
        index.append(
            {
                "id": sheet,
                "title": title,
                "model": meta["model"],
                "effort": meta["effort"],
                "seconds": meta["seconds"],
                "score": {k: score[k] for k in ("symbols", "connections")},
            }
        )
    (data / "sheets.json").write_text(json.dumps(index, indent=2))
    print(f"{len(index)} sheets -> {data}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "runs" / "deepagents-gpt-6.1-sol-low-tiled")
