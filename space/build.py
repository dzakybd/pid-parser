"""Pack precomputed runs on the dense sheet into space/data for the Hugging Face Space.

The sheet is PID2Graph "Dataset PID" 269 (CC BY-SA 4.0). Two runs of the same sheet are shown: the skill on Claude
Sonnet 5.5 and the Deep Agents runner on gpt-6-luna (best of three runs).

Usage: uv run python space/build.py
"""

import json
import shutil
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
REPO = Path(__file__).resolve().parent.parent
SHEET = "dpid-269"
RUNS = {
    "dpid-269-sonnet": ("Skill, Sonnet 5.5", REPO / "runs" / "claude-claude-sonnet-5-5-cv" / SHEET / "r1"),
    "dpid-269-luna": ("Deep Agents, gpt-6-luna", REPO / "runs" / "deepagents-gpt-6-luna-low-tiled-cv" / SHEET / "r1"),
}
WEB_WIDTH = 2400  # the drawing is 7000+ px wide; the overlay uses original pixels via the SVG viewBox


def main():
    data = REPO / "space" / "data"
    shutil.rmtree(data, ignore_errors=True)
    img = Image.open(REPO / "samples" / f"{SHEET}.png").convert("RGB")
    small = img.resize((WEB_WIDTH, round(img.height * WEB_WIDTH / img.width)), Image.LANCZOS)
    index = []
    for sheet, (title, run) in RUNS.items():
        dest = data / sheet
        shutil.copytree(run / "out", dest / "out")
        shutil.copy(run / "graph.json", dest / "graph.json")
        small.save(dest / "drawing.jpg", quality=85)
        meta = json.loads((run / "run.json").read_text())
        score = json.loads((run / "score.json").read_text())
        index.append(
            {
                "id": sheet,
                "title": title,
                "model": meta["model"],
                "effort": meta.get("effort"),
                "seconds": meta["seconds"],
                "score": {k: score[k] for k in ("symbols", "connections")},
            }
        )
    (data / "sheets.json").write_text(json.dumps(index, indent=2))
    print(f"{len(index)} runs -> {data}")


if __name__ == "__main__":
    main()
