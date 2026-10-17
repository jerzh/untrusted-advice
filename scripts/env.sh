# Sourced by the other scripts. Keeps this project's venv and settings inside the repo,
# even if UV_PROJECT_ENVIRONMENT is set globally on this machine.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_PROJECT_ENVIRONMENT="$REPO_ROOT/.venv"
export CONTROL_TOWER_SETTINGS_DIR="$REPO_ROOT/.settings"
cd "$REPO_ROOT"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
ct() { uv run ct "$@"; }
