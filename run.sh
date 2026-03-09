#!/usr/bin/env bash

set -euo pipefail

# ARIS CLI thin wrapper.
# The real entry point is the `aris` console script installed by `uv sync`.
# This file exists for backward compatibility and bootstrapping.

# Follow symlinks to find the real script location
SCRIPT_PATH="${BASH_SOURCE[0]}"
while [ -L "$SCRIPT_PATH" ]; do
  SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
  SCRIPT_PATH="$(readlink "$SCRIPT_PATH")"
  [[ $SCRIPT_PATH != /* ]] && SCRIPT_PATH="$SCRIPT_DIR/$SCRIPT_PATH"
done
ROOT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
export ARIS_ROOT="$ROOT_DIR"

# Check if the Click CLI is installed
if [[ ! -x "$ROOT_DIR/.venv/bin/aris" ]]; then
  echo "Error: aris CLI not installed in the virtual environment."
  echo "Run:  cd $ROOT_DIR && uv sync"
  exit 1
fi

exec "$ROOT_DIR/.venv/bin/aris" "$@"

