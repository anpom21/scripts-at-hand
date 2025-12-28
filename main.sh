#!/usr/bin/env bash

set -euo pipefail

# ARIS CLI entrypoint.
# - Refreshes config + scripts index every invocation.
# - Routes subcommands: search, refresh, completion.
# - Runs scripts as: aris <script> [args...]

# Follow symlinks to find the real script location
SCRIPT_PATH="${BASH_SOURCE[0]}"
while [ -L "$SCRIPT_PATH" ]; do
  SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
  SCRIPT_PATH="$(readlink "$SCRIPT_PATH")"
  [[ $SCRIPT_PATH != /* ]] && SCRIPT_PATH="$SCRIPT_DIR/$SCRIPT_PATH"
done
ROOT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
export ARIS_ROOT="$ROOT_DIR"

PYTHON_BIN="${ARIS_PYTHON:-python3}"

# Ensure config exists
if [[ ! -f "$ROOT_DIR/config.yaml" ]]; then
  cat > "$ROOT_DIR/config.yaml" <<'YAML'
repositories: []


scripts: []
YAML
fi


# If no arguments are given run list, refresh, help
if [[ $# -eq 0 ]]; then
  "$PYTHON_BIN" "$ROOT_DIR/src/refresh.py" --root "$ROOT_DIR" --verbose "$@"
  echo
  "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" -h
  exit 0
fi

SUBCMD="$1"


# Handle flags first
case "$SUBCMD" in
  --list)
    shift
    "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" --list
    exit 0
    ;;
  --refresh)
    shift
    "$PYTHON_BIN" "$ROOT_DIR/src/refresh.py" --root "$ROOT_DIR" --verbose "$@"
    echo
    exit 0
    ;;
  --help|-h|help)
    "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" -h
    exit 0
    ;;
esac

# Now shift to get the script/command
shift || true

case "$SUBCMD" in
  search)
    "$PYTHON_BIN" "$ROOT_DIR/src/search.py" --root "$ROOT_DIR" "$@"
    ;;
  completion)
    "$PYTHON_BIN" "$ROOT_DIR/src/completion.py" --root "$ROOT_DIR" "$@"
    ;;
  *)
    # Treat as a script name.
    "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" --script "$SUBCMD" -- "$@"
    ;;
esac

