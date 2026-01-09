
# ---------------------------------------------------------------------------
# File: src/add.py
# ---------------------------------------------------------------------------
"""Add a new script or repository to ARIS CLI.

Features:
- Copies a Python or shell script to the scripts/ directory
- Adds a git repository to config.yaml with script discovery
- Updates config.yaml and computes hashes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils import add_script_to_config, add_repository_to_config


def main() -> None:
    """Main entry point for add command.

    Args:
        None

    Returns:
        None
    """

    description = """Add a new script or repository to ARIS CLI.

If the path is a .py or .sh file, it will be copied to the scripts/ directory.
If the path is a directory with a .git folder, it will be added as a repository.

Usage:
  aris --add <path>
  aris -a <path>

Examples:
  # Add a script
  aris --add /path/to/my_script.py
  aris -a ./my_script.sh
  
  # Add a git repository
  aris --add /path/to/repo
  aris -a ~/projects/my-repo"""

    ap = argparse.ArgumentParser(
        prog="aris --add",
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--root", required=True, help=argparse.SUPPRESS)
    ap.add_argument("path", help="Path to a script file or git repository directory")

    args = ap.parse_args()
    root = Path(args.root)
    target_path = Path(args.path)
    
    # Resolve path
    if not target_path.is_absolute():
        target_path = Path.cwd() / target_path
    
    if not target_path.exists():
        print(f"Error: Path not found: {target_path}", file=sys.stderr)
        sys.exit(1)
    
    # Determine if it's a file or directory
    if target_path.is_file():
        # Add as script
        if target_path.suffix.lower() in {".py", ".sh"}:
            success = add_script_to_config(root, target_path)
        else:
            print(f"Error: File must be a .py or .sh script", file=sys.stderr)
            success = False
    elif target_path.is_dir():
        # Check if it's a git repository
        git_dir = target_path / ".git"
        if git_dir.exists():
            success = add_repository_to_config(root, target_path)
        else:
            print(f"Error: Directory is not a git repository (no .git folder)", file=sys.stderr)
            success = False
    else:
        print(f"Error: Path is neither a file nor a directory: {target_path}", file=sys.stderr)
        success = False
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
