"""Draw the answer key's symbols and pipe networks over the drawing (sanity check)."""

import colorsys
import sys

import networkx as nx
from nets import GT_DROP, GT_LINE, box_center
from PIL import Image, ImageDraw

graphml, image, out = sys.argv[1:4]
g = nx.read_graphml(graphml)
g.remove_nodes_from([n for n, d in g.nodes(data=True) if d["label"] in GT_DROP])
lines = g.subgraph(n for n, d in g.nodes(data=True) if d["label"] in GT_LINE)

im = Image.open(image).convert("RGB")
im = Image.blend(im, Image.new("RGB", im.size, "white"), 0.55)
draw = ImageDraw.Draw(im)
w = max(2, im.width // 600)


def center(n):
    d = g.nodes[n]
    return box_center((d["xmin"], d["ymin"], d["xmax"], d["ymax"]))


for i, comp in enumerate(nx.connected_components(lines)):
    r, gg, b = colorsys.hsv_to_rgb((i * 0.618) % 1, 0.9, 0.85)
    color = (int(r * 255), int(gg * 255), int(b * 255))
    for a, b2 in g.edges(comp):
        draw.line([center(a), center(b2)], fill=color, width=w)
for n, d in g.nodes(data=True):
    if d["label"] not in GT_LINE:
        draw.rectangle((d["xmin"], d["ymin"], d["xmax"], d["ymax"]), outline=(0, 0, 0), width=w)
        draw.text((d["xmin"], d["ymin"] - 12), d["label"][:5], fill=(0, 0, 0))
im.save(out)
