#!/usr/bin/env bash
# One stream per harness/model, sheets in sequence, streams in parallel.
# Usage: eval/batch.sh <repeat>
repo=$(cd "$(dirname "$0")/.." && pwd)
rep=$1
sheets="open100-1 open100-0 open100-2 synth-0 synth-1 synth-2"
for cfg in "claude opus" "codex gpt-6-sol" "deepagents gpt-6-sol" "deepagents gpt-6-luna"; do
  (for s in $sheets; do "$repo/eval/run_one.sh" $cfg "$s" "$rep"; done) &
done
wait
