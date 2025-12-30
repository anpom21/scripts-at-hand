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
  --config|-c)
    CONFIG_PATH="$ROOT_DIR/config.yaml"
    echo "Opening config: $CONFIG_PATH"
    
    # Try to find the default editor for YAML files
    # Priority: EDITOR env var, xdg-open (Linux), open (macOS), fallback to vi
    if [[ -n "${EDITOR:-}" ]]; then
      exec "$EDITOR" "$CONFIG_PATH"
    elif command -v xdg-open &> /dev/null; then
      xdg-open "$CONFIG_PATH"
    elif command -v open &> /dev/null; then
      open "$CONFIG_PATH"
    else
      # Fallback to vi/vim/nano
      if command -v vim &> /dev/null; then
        exec vim "$CONFIG_PATH"
      elif command -v nano &> /dev/null; then
        exec nano "$CONFIG_PATH"
      else
        exec vi "$CONFIG_PATH"
      fi
    fi
    exit 0
    ;;
  --list)
    shift
    "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" --list
    exit 0
    ;;
  --reset-config)
    shift
    "$PYTHON_BIN" "$ROOT_DIR/src/refresh.py" --root "$ROOT_DIR" --verbose --reset-config "$@"
    echo "Resetting configuration completed."
    exit 0
    ;;
  --refresh)
    shift
    "$PYTHON_BIN" "$ROOT_DIR/src/refresh.py" --root "$ROOT_DIR" --verbose "$@"
    echo "Refresh completed."
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

