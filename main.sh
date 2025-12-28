#!/usr/bin/env bash
set -euo pipefail

# ARIS CLI entrypoint.
# - Refreshes config + scripts index every invocation.
# - Routes subcommands: search, refresh, completion.
# - Runs scripts as: aris <script> [args...]

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ARIS_ROOT="$ROOT_DIR"

PYTHON_BIN="${ARIS_PYTHON:-python3}"

# Ensure config exists
if [[ ! -f "$ROOT_DIR/config.yaml" ]]; then
  cat > "$ROOT_DIR/config.yaml" <<'YAML'
repositories: []

scripts: []
YAML
fi

# Refresh on every run (fast; uses file mtimes)
"$PYTHON_BIN" "$ROOT_DIR/src/refresh.py" --root "$ROOT_DIR" >/dev/null || true

if [[ $# -eq 0 ]]; then
  "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" --list
  echo
  "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" -h
  exit 0
fi

SUBCMD="$1"; shift || true

case "$SUBCMD" in
  search)
    "$PYTHON_BIN" "$ROOT_DIR/src/search.py" --root "$ROOT_DIR" "$@"
    ;;
  refresh)
    "$PYTHON_BIN" "$ROOT_DIR/src/refresh.py" --root "$ROOT_DIR" "$@"
    ;;
  completion)
    "$PYTHON_BIN" "$ROOT_DIR/src/completion.py" --root "$ROOT_DIR" "$@"
    ;;
  -h|--help|help)
    "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" -h
    ;;
  *)
    # Treat as a script name.
    "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" --script "$SUBCMD" -- "$@"
    ;;
esac
