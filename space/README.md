---
title: pid-parser
emoji: 🛠️
colorFrom: green
colorTo: gray
sdk: static
pinned: false
license: cc-by-sa-4.0
short_description: "P&ID image to tables and a graph, with pixel connections"
---

# pid-parser showcase

Precomputed results of [pid-parser](https://github.com/dzakybd/pid-parser) on one very dense P&ID sheet (190 symbols, 732 connected pairs), run two ways, the skill on Claude Sonnet 5.5 and the Deep Agents runner on gpt-6-luna: the drawing with the symbols the model found, the connections read from the pixels, the graph, the tables, and the SQL, CSV, GraphML and Cypher exports. The page calls no model.

Install the skill in your own agent with `npx skills add dzakybd/pid-parser`. How it works, step by step: [the write-up](https://dzaky.ai.id/en/blog/pid-parser-pid-to-graph).

Drawing: sheet 269 of the "Dataset PID" part of [PID2Graph](https://zenodo.org/records/14803338) ([paper](https://arxiv.org/abs/2411.13929)), CC BY-SA 4.0. The drawings and the outputs derived from them are shared under CC BY-SA 4.0. The pid-parser code is MIT licensed.
