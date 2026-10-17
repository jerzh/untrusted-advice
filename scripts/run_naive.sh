#!/usr/bin/env bash
# Naive control eval: honest + attack samples under one protocol, every action scored by a
# trusted monitor, nothing blocked or audited live. Safety/usefulness are computed post hoc
# at several audit budgets by scripts/summarize.py.
#
#   scripts/run_naive.sh                       # smoke test: 1 honest + 1 attack sample
#   TASKS=task_sets/naive.jsonl scripts/run_naive.sh    # 9 envs x (honest + attack)
#   UNTRUSTED=anthropic/claude-sonnet-4-6 TRUSTED=openai/gpt-5.4-nano scripts/run_naive.sh
#   PROTOCOL=lacontrol/my-protocol scripts/run_naive.sh # once the protocol does something
set -euo pipefail
source "$(dirname "$0")/env.sh"

TASKS="${TASKS:-task_sets/smoke.jsonl}"
UNTRUSTED="${UNTRUSTED:-anthropic/claude-haiku-4-5}"
TRUSTED="${TRUSTED:-openai/gpt-5-nano}"
PROTOCOL="${PROTOCOL:-ct/trusted-monitoring}"
MONITOR="${MONITOR:-simple}"
MAX_SAMPLES="${MAX_SAMPLES:-4}"   # concurrent samples (each one is a docker compose stack)
LOG_DIR="${LOG_DIR:-logs/$(date +%Y%m%d-%H%M%S)-$(basename "$TASKS" .jsonl)}"

protocol_args=()
[[ "$PROTOCOL" == "ct/trusted-monitoring" ]] && protocol_args+=(-bp "monitors=[$MONITOR]")

ct run control-eval \
  --task-file "$TASKS" \
  --honest-policy ct/honest \
  --attack-policy ct/attack \
  --protocol "$PROTOCOL" "${protocol_args[@]}" \
  --model-role "untrusted=$UNTRUSTED" \
  --model-role "trusted=$TRUSTED" \
  --eval-arg "max_samples=$MAX_SAMPLES" \
  --log-dir "$LOG_DIR" \
  --tag naive \
  --no-upload

# A protocol without a live monitor (e.g. my-protocol as a pass-through) needs monitor
# scores added post hoc before safety can be computed.
if [[ "$PROTOCOL" != "ct/trusted-monitoring" ]]; then
  for f in "$LOG_DIR"/*.eval; do
    ct run monitor "$f" -m "[$MONITOR]" --model-role "trusted=$TRUSTED" -o "$LOG_DIR/monitored"
  done
  LOG_DIR="$LOG_DIR/monitored"
fi

uv run python scripts/summarize.py "$LOG_DIR" --monitor "$MONITOR"
