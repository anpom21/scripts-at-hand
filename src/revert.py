
# ---------------------------------------------------------------------------
# File: src/revert.py
# ---------------------------------------------------------------------------
"""Revert config.yaml to a previous backup.

Features:
- Restores config.yaml from logs/.old_config.yaml
- Creates a pre-revert backup for safety
- Automatically refreshes the script index
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from utils import revert_config


def main() -> None:
    """Main entry point for revert command.

    Args:
        None

    Returns:
        None
    """

    description = """Revert config.yaml to the previous backup.

This command restores config.yaml from logs/.old_config.yaml
and refreshes the script index.

Usage:
  aris --revert

The current config.yaml is backed up to logs/.pre_revert_config.yaml
before reverting, in case you change your mind."""

    ap = argparse.ArgumentParser(
        prog="aris --revert",
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--root", required=True, help=argparse.SUPPRESS)

    args = ap.parse_args()
    root = Path(args.root)

    # Revert the config
    success = revert_config(root)
    
    if success:
        # Refresh the script index
        print("\nRefreshing script index...")
        refresh_script = root / "src" / "refresh.py"
        python_bin = root / ".venv" / "bin" / "python3"
        
        if refresh_script.exists() and python_bin.exists():
            subprocess.run([str(python_bin), str(refresh_script), "--root", str(root)])
        else:
            print("Warning: Could not refresh script index", file=sys.stderr)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
