#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
REQUIRED_PYTHON="3.12"
PYTHON_BIN="python3.12"

if ! command -v "$PYTHON_BIN" >/dev/null && command -v python3 >/dev/null; then
  if [ "$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" = "$REQUIRED_PYTHON" ]; then
    PYTHON_BIN="python3"
  fi
fi

require_cmd() {
  local name="$1"
  local install_hint="$2"
  if ! command -v "$name" >/dev/null; then
    echo "[ERROR] Missing required command: $name"
    echo "        Install hint: $install_hint"
    exit 1
  fi
}

optional_cmd_note() {
  local name="$1"
  local note="$2"
  if ! command -v "$name" >/dev/null; then
    echo "[WARN] Optional command not found: $name"
    echo "       $note"
  fi
}

echo "[INFO] Preflight checks"
require_cmd "$PYTHON_BIN" "Install Python 3.12 (binary: python3.12 or python3==3.12)"
require_cmd bun "Install Bun: https://bun.sh"
require_cmd redis-server "Install Redis server"
require_cmd redis-cli "Install Redis CLI"
require_cmd curl "Install curl"
require_cmd jq "Install jq"

optional_cmd_note docker "Needed for local container validation and HF parity checks."
optional_cmd_note uv "Used for regenerating uv.lock when dependencies change."

echo "[INFO] Creating virtual environment"
if [ -x "$VENV_DIR/bin/python" ]; then
  EXISTING_PY_VERSION="$($VENV_DIR/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [ "$EXISTING_PY_VERSION" != "$REQUIRED_PYTHON" ]; then
    echo "[INFO] Recreating .venv with Python 3.12 (found $EXISTING_PY_VERSION)"
    rm -rf "$VENV_DIR"
  fi
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
pip install -r "$ROOT_DIR/requirements.txt"

echo "[INFO] Installing Bun dependencies"
( cd "$ROOT_DIR/mesh/gateway" && bun install )
( cd "$ROOT_DIR/mesh/auth" && bun install )
( cd "$ROOT_DIR/mesh/worker" && bun install )

chmod +x "$ROOT_DIR/start.sh"
chmod +x "$ROOT_DIR/inference.py" || true

if command -v uv >/dev/null && [ ! -f "$ROOT_DIR/uv.lock" ]; then
  echo "[INFO] Generating uv.lock"
  ( cd "$ROOT_DIR" && uv lock )
fi

echo "[INFO] Running OpenEnv validation"
openenv validate "$ROOT_DIR"

echo "[INFO] Setup complete"
echo "[NEXT] Export required inference vars:"
echo "       API_BASE_URL=<endpoint>"
echo "       MODEL_NAME=<model>"
echo "       HF_TOKEN=<api_key>"
echo "[NEXT] Start services: APP_ROOT=$ROOT_DIR MESH_ROOT=$ROOT_DIR/mesh ./start.sh"
echo "[NEXT] Run baseline: HF_TOKEN=... API_BASE_URL=... MODEL_NAME=... python inference.py"
