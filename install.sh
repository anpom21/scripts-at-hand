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

echo "Adding ARIS command alias to ~/.bashrc..."
# Add alias to bashrc if not already present
if ! grep -q 'alias aris=' ~/.bashrc; then
    # Add alias and completion sourcing
  echo "" >> ~/.bashrc
  echo "#>>> aris-cli initialize >>>" >> ~/.bashrc
  echo "alias aris='$(pwd)/run.sh'" >> ~/.bashrc
  echo "source <(aris completion bash)" >> ~/.bashrc
  echo "#<<< aris-cli initialize <<<" >> ~/.bashrc
  echo "" >> ~/.bashrc

    # Source the updated bashrc
  echo "Added alias to ~/.bashrc." 
else
  echo "Alias already exists in ~/.bashrc."
fi
deactivate
source ~/.bashrc

echo "Installation complete. You can now use the 'aris' command."