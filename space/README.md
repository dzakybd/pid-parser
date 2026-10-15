---
title: pid-parser
emoji: 🛠️
colorFrom: green
colorTo: gray
sdk: static
pinned: false
license: cc-by-sa-4.0
short_description: "Your P&ID drawing, now data you can ask"
---

# pid-parser showcase

Turn a P&ID drawing into data you can ask: SQL tables and a graph that people and AI agents can query. A vision model finds the symbols, and traditional computer vision (thresholding and connected-component labeling) finds the connections.

Precomputed results of [pid-parser](https://github.com/dzakybd/pid-parser) on one very dense P&ID sheet (190 symbols, 732 connected pairs), run two ways, the skill on Claude Sonnet 5.5 and the Deep Agents runner on gpt-6-luna. Each run shows the drawing with the symbols found, the graph, the tables, and the SQL, CSV, GraphML and Cypher exports. The page calls no model.

Two versions: a skill for coding agents (`npx skills add dzakybd/pid-parser`) and a LangChain Deep Agents version for your own agent workflow. How it works, step by step: [the write-up](https://dzaky.ai.id/en/blog/pid-parser-pid-to-graph).

Drawing: sheet 269 of the "Dataset PID" part of [PID2Graph](https://zenodo.org/records/14803338) ([paper](https://arxiv.org/abs/2411.13929)), CC BY-SA 4.0. The drawings and the outputs derived from them are shared under CC BY-SA 4.0. The pid-parser code is MIT licensed.
