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

echo "Generating completion files..."
"$PWD/.venv/bin/python3" "$PWD/src/completion.py" --root "$PWD" --generate-stub
"$PWD/.venv/bin/python3" "$PWD/src/completion.py" --root "$PWD" --generate-cache

echo "Adding ARIS command alias to available shell rc files..."

ARIS_REPO_ROOT="$(pwd)"

install_for_shell() {
  local shell_name="$1"
  local shell_rc="$2"
  local stub_path="$3"
  local needs_update=true

  touch "$shell_rc"
  echo "Configuring $shell_name in $shell_rc"

  if grep -Eq '# ?>>> aris-cli initialize >>>' "$shell_rc" 2>/dev/null; then
    if grep -q "ARIS_CLI_ROOT=\"$ARIS_REPO_ROOT\"" "$shell_rc"; then
      echo "aris-cli already installed with correct root path in $shell_rc"
      needs_update=false
    else
      echo "aris-cli root path mismatch in $shell_rc, updating..."
      sed -i '/# >>> aris-cli initialize >>>/,/# <<< aris-cli initialize <<</d' "$shell_rc"
      sed -i '/#>>> aris-cli initialize >>>/,/#<<< aris-cli initialize <<</d' "$shell_rc"
    fi
  fi

  if [ "$needs_update" = true ]; then
    {
      echo ""
      echo "# >>> aris-cli initialize >>>"
      echo "ARIS_CLI_ROOT=\"$ARIS_REPO_ROOT\""
      echo "aris() {"
      echo "  \"\$ARIS_CLI_ROOT/run.sh\" \"\$@\""
      echo "}"
      echo "source \"\$ARIS_CLI_ROOT/$stub_path\""
      echo "# <<< aris-cli initialize <<<"
      echo ""
    } >> "$shell_rc"

    echo "Added alias and completion sourcing to $shell_rc"
  else
    echo "Alias already exists in $shell_rc"
  fi
}

if command -v bash >/dev/null 2>&1; then
  install_for_shell "bash" "$HOME/.bashrc" "logs/.completion_stub.bash"
else
  echo "bash not found; skipping bash rc update"
fi

if command -v zsh >/dev/null 2>&1; then
  install_for_shell "zsh" "$HOME/.zshrc" "logs/.completion_stub.zsh"
else
  echo "zsh not found; skipping zsh rc update"
fi
deactivate

# Source bash rc only when running in bash; zsh users should source manually.
if [ -n "${BASH_VERSION:-}" ]; then
  source ~/.bashrc
fi

echo "If you use zsh, run: source ~/.zshrc"

echo "Installation complete. You can now use the 'aris' command."