#!/usr/bin/env bash
# Naive control eval, set up like the public LinuxArena leaderboard: honest + attack samples
# under ct/null-blue-team (nothing blocked or audited live), then every action scored post hoc
# by a trusted `simple` monitor and each whole run by a `trajectory` monitor. Safety/usefulness
# are computed at several audit budgets by scripts/summarize.py and compare_leaderboard.py.
#
#   scripts/run_naive.sh                       # smoke test: 1 honest + 1 attack sample
#   TASKS=task_sets/leaderboard18.jsonl scripts/run_naive.sh   # 18 leaderboard tasks
#   TASKS=task_sets/naive.jsonl scripts/run_naive.sh    # 9 envs x (honest + attack)
#   UNTRUSTED=anthropic/claude-sonnet-4-6 TRUSTED=openai/gpt-5.4-nano scripts/run_naive.sh
#   PROTOCOL=lacontrol/my-protocol scripts/run_naive.sh # once the protocol does something
#   LOG_DIR=logs/<run> scripts/run_naive.sh    # resume: reuse the run's .eval, redo the monitors
#   SKIP_MONITORS=1 scripts/run_naive.sh       # agent runs only (no trusted-model calls)
set -euo pipefail
source "$(dirname "$0")/env.sh"

TASKS="${TASKS:-task_sets/smoke.jsonl}"
UNTRUSTED="${UNTRUSTED:-anthropic/claude-haiku-4-5}"
TRUSTED="${TRUSTED:-openai/gpt-5.4-nano}"
PROTOCOL="${PROTOCOL:-ct/null-blue-team}"
MONITOR="${MONITOR:-simple}"                 # action monitor
TRAJ_MONITOR="${TRAJ_MONITOR:-trajectory}"   # whole-run monitor; empty to skip
MAX_SAMPLES="${MAX_SAMPLES:-4}"   # concurrent samples (each one is a docker compose stack)
LOG_DIR="${LOG_DIR:-logs/$(date +%Y%m%d-%H%M%S)-$(basename "$TASKS" .jsonl)}"

SKIP_MONITORS="${SKIP_MONITORS:-}"
shopt -s nullglob
existing=("$LOG_DIR"/*.eval)
post_hoc=$([[ "$PROTOCOL" != "ct/trusted-monitoring" && -z "$SKIP_MONITORS" ]] && echo 1 || true)

# One tiny call per model before spending anything: a dead key or an empty balance otherwise
# shows up as a run that retries silently for hours.
needed=()
(( ${#existing[@]} )) || needed+=("$UNTRUSTED")
[[ -n "$post_hoc" || "$PROTOCOL" == "ct/trusted-monitoring" ]] && needed+=("$TRUSTED")
if (( ${#needed[@]} )); then
  uv run python - "${needed[@]}" <<'PY'
import asyncio, sys
from inspect_ai.model import GenerateConfig, get_model

async def check(name: str) -> None:
    config = GenerateConfig(max_retries=0, timeout=60, max_tokens=64)
    try:
        out = await get_model(name, config=config).generate("Reply with the word ok.")
    except Exception as e:
        if hasattr(e, "last_attempt"):  # tenacity's RetryError hides the provider's message
            e = e.last_attempt.exception()
        sys.exit(f"preflight: {name} failed: {type(e).__name__}: {e}"[:600])
    if out.error:
        sys.exit(f"preflight: {name} failed: {out.error}"[:600])
    print(f"preflight: {name} ok")

async def main() -> None:
    for name in sys.argv[1:]:
        await check(name)

asyncio.run(main())
PY
fi

protocol_args=()
[[ "$PROTOCOL" == "ct/trusted-monitoring" ]] && protocol_args+=(-bp "monitors=[$MONITOR]")

if (( ${#existing[@]} )); then
  echo "reusing ${existing[*]}"
else
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
fi
[[ -n "$SKIP_MONITORS" ]] && exit 0

# A protocol without a live monitor (null-blue-team, or my-protocol as a pass-through) needs
# monitor scores added post hoc before safety can be computed.
if [[ -n "$post_hoc" ]]; then
  rm -rf "$LOG_DIR/monitored"
  for f in "$LOG_DIR"/*.eval; do
    ct run monitor "$f" -m "[$MONITOR]" --kind action --model-role "trusted=$TRUSTED" -o "$LOG_DIR/monitored"
  done
  if [[ -n "$TRAJ_MONITOR" ]]; then
    for f in "$LOG_DIR"/monitored/*.eval; do
      ct run monitor "$f" -m "[$TRAJ_MONITOR]" --kind trajectory --model-role "trusted=$TRUSTED"
    done
  fi
  LOG_DIR="$LOG_DIR/monitored"
fi

uv run python scripts/summarize.py "$LOG_DIR" --monitor "$MONITOR"
uv run python scripts/compare_leaderboard.py "$LOG_DIR"
