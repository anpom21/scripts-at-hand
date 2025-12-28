# ---------------------------------------------------------------------------
# File: src/refresh.py
# ---------------------------------------------------------------------------
"""Refresh config.yaml and local script registry.

Responsibilities:
- Ensure scripts/ and logs/ exist.
- Discover scripts in scripts/ folder.
- Merge discovered scripts with repository scripts defined in config.yaml.
- Update config.yaml scripts section with python3 mappings.
- Ensure executable permissions for all .sh scripts.
- Ensure logs/<script_name>/ exists for each script.

This runs fast and is safe to call on each invocation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils import (
    load_config,
    save_config,
    build_script_index,
    update_scripts_section,
    ensure_logs_structure,
    set_executable,
    list_local_scripts,
    bold,
)


def refresh(root: Path, verbose: bool = False) -> int:
    """Refresh config and filesystem structure.

    Args:
        root: ARIS CLI repository root.
        verbose: If True, print changes to stdout.

    Returns:
        Exit code (0 on success).
    """

    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    # Load old config to compare
    cfg = load_config(root)
    old_scripts = {s["name"]: s.get("source", "local") for s in cfg.get("scripts", [])}
    
    # Build new entries
    entries = build_script_index(root, cfg)

    # Set executable for all shell scripts (local only)
    for p in list_local_scripts(root):
        if p.suffix.lower() == ".sh":
            set_executable(p)

    # Update config
    cfg = update_scripts_section(cfg, entries)
    save_config(root, cfg)

    ensure_logs_structure(root, entries)
    
    # If verbose, show what changed
    if verbose:
        new_scripts = {e.name: e.source for e in entries}
        
        added = {name: src for name, src in new_scripts.items() if name not in old_scripts}
        removed = {name: src for name, src in old_scripts.items() if name not in new_scripts}
        
        if added or removed:
            # Green color code
            GREEN = "\033[0;32m"
            # Non bold greem
            GREEN_THIN = "\033[0;32m"
            RED = "\033[0;31m"
            RESET = "\033[0m"
            BOLD_GREEN = "\033[1;32m"
            
            print(f"\n{BOLD_GREEN}Config has been updated successfully{RESET}", file=sys.stderr)
            
            for name, src in sorted(added.items()):
                src_label = f" [{src}]" if src != "local" else ""
                print(f"{GREEN}+ {name}{src_label}{RESET}", file=sys.stderr)
            
            for name, src in sorted(removed.items()):
                src_label = f" [{src}]" if src != "local" else ""
                print(f"{RED}- {name}{src_label}{RESET}", file=sys.stderr)
            
            print(file=sys.stderr)
    
    return 0


def main() -> None:
    """CLI entrypoint for refresh.

    Args:
        None

    Returns:
        None
    """

    ap = argparse.ArgumentParser(description="Refresh scripts index and config.yaml")
    ap.add_argument("--root", required=True, help="Path to aris-cli repo root")
    ap.add_argument("--verbose", "-v", action="store_true", help="Show changes")
    args = ap.parse_args()

    raise SystemExit(refresh(Path(args.root), verbose=args.verbose))


if __name__ == "__main__":
    main()
