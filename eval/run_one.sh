#!/usr/bin/env bash
# Run one harness on one sheet in an isolated folder that holds only the drawing and the skill.
# Usage: eval/run_one.sh <harness: claude|codex|deepagents> <model> <sheet, e.g. open100-1> <repeat>
# EFFORT=medium sets the Deep Agents reasoning effort; TILED=1 or WHOLE=1 runs pass 1 in code (per tile or one whole-sheet call), PIPES=oneshot does pass 2 in one call instead of an agent, PIPE_MODEL sets the agent model after pass 1 (Deep Agents only).
set -euo pipefail

harness=$1 model=$2 sheet=$3 rep=$4
repo=$(cd "$(dirname "$0")/.." && pwd)
for img in "$repo/samples/$sheet.png" "$repo/samples/$sheet.jpg"; do [ -f "$img" ] && break; done
ext=${img##*.}
out="$repo/runs/$harness-$model${EFFORT:+-$EFFORT}${TILED:+-tiled}${WHOLE:+-whole}${PIPES:+-$PIPES${ROUNDS:+$ROUNDS}}${PIPE_MODEL:+-agent-$PIPE_MODEL}/$sheet/r$rep"
work=$(mktemp -d "${TMPDIR:-/tmp}/pid-run.XXXXXX")

cp "$img" "$work/drawing.$ext"
mkdir -p "$work/skills" "$work/.claude/skills" "$work/.agents/skills"
for d in skills .claude/skills .agents/skills; do cp -R "$repo/skills/pid-parser" "$work/$d/"; done
export PATH="$repo/.venv/bin:$PATH"  # python3 with Pillow for tile.py

prompt="Use the pid-parser skill to parse the P&ID at drawing.$ext in the current directory. Use the current directory as the work directory: graph.json goes there and the export goes to ./out. Work without asking questions."
start=$(date +%s)
cd "$work"
case $harness in
  claude) timeout 2400 claude -p --model "$model" --allowedTools "Bash,Read,Write,Edit,Glob,Grep,Skill" \
            --output-format json "$prompt" > transcript.json 2>&1 || true ;;
  codex) timeout 2400 codex exec -m "$model" -s workspace-write --skip-git-repo-check "$prompt" \
            > transcript.txt 2>&1 || true ;;
  deepagents) timeout 2400 "$repo/.venv/bin/python" "$repo/agent/run.py" "$work" --model "$model" ${EFFORT:+--effort "$EFFORT"} ${TILED:+--tiled} ${WHOLE:+--whole} ${PIPES:+--pipes $PIPES} ${ROUNDS:+--rounds $ROUNDS} ${PIPE_MODEL:+--pipe-model "$PIPE_MODEL"} \
            > transcript.txt 2>&1 || true ;;
esac
secs=$(( $(date +%s) - start ))

mkdir -p "$out"
cp -R "$work"/. "$out"/
rm -rf "$out/skills" "$out/.claude" "$out/.agents" "$work"
[ -f "$out/run.json" ] || echo "{\"model\":\"$model\",\"harness\":\"$harness\",\"seconds\":$secs}" > "$out/run.json"
if [ -f "$out/graph.json" ]; then
  (cd "$repo/eval" && "$repo/.venv/bin/python" score.py "$out/graph.json" "$repo/samples/$sheet.graphml" \
     --overlay "$img" "$out/overlay.png" > "$out/score.json") || echo "score failed" > "$out/score_error.txt"
fi
echo "$harness $model $sheet r$rep ${secs}s $( [ -f "$out/score.json" ] && echo scored || echo NO-GRAPH )"
