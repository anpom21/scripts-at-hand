#!/bin/bash

echo "Starting ARIS CLI installation..."
# Install uv if not already installed
if ! command -v uv &> /dev/null; then
  echo "uv not found. Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "Setting up virtual environment with uv..."
# To use uv, we need to set up a virtual environment

if [[ -d ".venv" ]]; then # Check if .venv directory exists
  echo ".venv directory already exists. Skipping virtual environment creation."
else
  echo "Creating virtual environment in .venv..."
  uv venv --python /usr/bin/python3.12 .venv
fi

# Then source and sync the libraries:
source .venv/bin/activate
echo "Syncing dependencies with uv..."
uv sync --active

echo "Dependencies installed and virtual environment set up."

echo "Running initial refresh to discover scripts..."
"$PWD/.venv/bin/python3" "$PWD/src/refresh.py" --root "$PWD"

echo "Adding ARIS to shell rc file..."

# Detect shell and set appropriate rc file
if [ -n "${ZSH_VERSION:-}" ] || [[ "$SHELL" == *"zsh"* ]]; then
  SHELL_RC="$HOME/.zshrc"
  COMPLETE_VAR="zsh_source"
  SHELL_NAME="zsh"
else
  SHELL_RC="$HOME/.bashrc"
  COMPLETE_VAR="bash_source"
  SHELL_NAME="bash"
fi

echo "Detected $SHELL_NAME shell, will update $SHELL_RC"

ARIS_VENV_BIN="$(pwd)/.venv/bin"

# Remove old aris-cli block if present, then add new one
NEEDS_UPDATE=true
if grep -q '# >>> aris-cli initialize >>>' "$SHELL_RC" 2>/dev/null; then
  if grep -q "$ARIS_VENV_BIN" "$SHELL_RC"; then
    echo "aris-cli already installed with correct path in $SHELL_RC"
    NEEDS_UPDATE=false
  else
    echo "aris-cli path mismatch in $SHELL_RC, updating..."
    sed -i '/# >>> aris-cli initialize >>>/,/# <<< aris-cli initialize <<</d' "$SHELL_RC"
  fi
fi

if [ "$NEEDS_UPDATE" = true ]; then
  echo "" >> "$SHELL_RC"
  echo "# >>> aris-cli initialize >>>" >> "$SHELL_RC"
  echo "export PATH=\"$ARIS_VENV_BIN:\$PATH\"" >> "$SHELL_RC"
  echo "eval \"\$(_ARIS_COMPLETE=${COMPLETE_VAR} aris)\"" >> "$SHELL_RC"
  echo "# <<< aris-cli initialize <<<" >> "$SHELL_RC"
  echo "" >> "$SHELL_RC"
  echo "Added aris-cli to $SHELL_RC"
fi

echo "Installation complete. You can now use the 'aris' command."