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


PYTHON_BIN=$ROOT_DIR/.venv/bin/python3
# Check if Python binary exists
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: Python binary not found at $PYTHON_BIN"
  echo "Please set up the virtual environment by running:"
  echo "  uv venv --python /usr/bin/python3.12 $ROOT_DIR/.venv"
  echo "  uv sync"
  exit 1
fi
#echo "Using ARIS root: $ROOT_DIR"
#echo "Using Python binary: $PYTHON_BIN"

# Ensure config exists
if [[ ! -f "$ROOT_DIR/config.yaml" ]]; then
  cat > "$ROOT_DIR/config.yaml" <<'YAML'
repositories: []


scripts: []
YAML
fi


# If no arguments are given run list, refresh, help
if [[ $# -eq 0 ]]; then
  # "$PYTHON_BIN" "$ROOT_DIR/src/refresh.py" --root "$ROOT_DIR" --verbose "$@"
  # echo
  "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" -h
  exit 0
fi

SUBCMD="$1"


# Handle flags first
case "$SUBCMD" in
  --add|-a)
    shift
    "$PYTHON_BIN" "$ROOT_DIR/src/add.py" --root "$ROOT_DIR" "$@"
    echo "Refreshing config..."
    # Regenerate completion cache
    "$PYTHON_BIN" "$ROOT_DIR/src/completion.py" --root "$ROOT_DIR" --generate-cache 2>/dev/null
    "$PYTHON_BIN" "$ROOT_DIR/src/completion.py" --root "$ROOT_DIR" --generate-stub 2>/dev/null
    exit 0
    ;;
  --revert-config)
    shift
    "$PYTHON_BIN" "$ROOT_DIR/src/revert.py" --root "$ROOT_DIR" "$@"
    exit 0
    ;;
  --open|-o)
    echo "Repository location: $ROOT_DIR"
    if command -v code &> /dev/null; then
      echo "Opening in VS Code..."
      code "$ROOT_DIR"
    else
      echo "VS Code (code) not found in PATH"
    fi
    exit 0
    ;;
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
    # Regenerate completion cache
    "$PYTHON_BIN" "$ROOT_DIR/src/completion.py" --root "$ROOT_DIR" --generate-cache 2>/dev/null
    echo "Resetting configuration completed."
    exit 0
    ;;
  --refresh|-r)
    shift
    "$PYTHON_BIN" "$ROOT_DIR/src/refresh.py" --root "$ROOT_DIR" --verbose "$@"
    # Regenerate completion cache
    "$PYTHON_BIN" "$ROOT_DIR/src/completion.py" --root "$ROOT_DIR" --generate-cache 2>/dev/null
    echo "Refresh completed."
    exit 0
    ;;
  --help|-h|help)
    "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" -h
    exit 0
    ;;
  --search|-s)
    shift
    "$PYTHON_BIN" "$ROOT_DIR/src/search.py" --root "$ROOT_DIR" "$@"
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
    # Fast path: if stub file exists and user wants bash/zsh output, cat it directly
    if [[ "${1:-}" == "bash" && -f "$ROOT_DIR/logs/.completion_stub.bash" ]]; then
      cat "$ROOT_DIR/logs/.completion_stub.bash"
    elif [[ "${1:-}" == "zsh" && -f "$ROOT_DIR/logs/.completion_stub.zsh" ]]; then
      cat "$ROOT_DIR/logs/.completion_stub.zsh"
    else
      "$PYTHON_BIN" "$ROOT_DIR/src/completion.py" --root "$ROOT_DIR" "$@"
    fi
    ;;
  *)
    # Treat as a script name.
    "$PYTHON_BIN" "$ROOT_DIR/src/run.py" --root "$ROOT_DIR" --script "$SUBCMD" -- "$@"
    ;;
esac

