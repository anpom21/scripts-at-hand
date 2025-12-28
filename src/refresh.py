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
from pathlib import Path

from utils import (
    load_config,
    save_config,
    build_script_index,
    update_scripts_section,
    ensure_logs_structure,
    set_executable,
    list_local_scripts,
)


def refresh(root: Path) -> int:
    """Refresh config and filesystem structure.

    Args:
        root: ARIS CLI repository root.

    Returns:
        Exit code (0 on success).
    """

    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    cfg = load_config(root)
    entries = build_script_index(root, cfg)

    # Set executable for all shell scripts (local only)
    for p in list_local_scripts(root):
        if p.suffix.lower() == ".sh":
            set_executable(p)

    cfg = update_scripts_section(cfg, entries)
    save_config(root, cfg)

    ensure_logs_structure(root, entries)
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
    args = ap.parse_args()

    raise SystemExit(refresh(Path(args.root)))


if __name__ == "__main__":
    main()
