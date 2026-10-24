#!/usr/bin/env bash
# One-time setup: install deps, pull the public LinuxArena environments, sanity-check.
set -euo pipefail
source "$(dirname "$0")/env.sh"

uv sync
# Control Tower prices every call from this table and refuses to run without it.
[[ -f "${CONTROL_TOWER_MODEL_RATES:-$HOME/.cache/control-tower/model_rates.json}" ]] || uv run python scripts/generate_model_rates.py
ct settings pull linuxarena   # git clones into .settings/ (re-run after every `uv sync`)
ct settings envs
ct protocols protocols | grep -q 'lacontrol/my-protocol' && echo "plugin OK: lacontrol/my-protocol"
docker info >/dev/null 2>&1 || echo "WARNING: docker is not running; evals need it."
