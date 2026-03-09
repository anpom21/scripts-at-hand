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

    # Save old config for comparison
    old_config_path = root / "logs" / ".old_config.yaml"
    config_path = root / "config.yaml"
    
    # Read old config if it exists
    old_config_text = ""
    if old_config_path.exists():
        old_config_text = old_config_path.read_text()
    
    # Load current config
    cfg = load_config(root)

    # If reset_config is requested we will reset per-script overrides except
    # for the `shortcut` field. To support this, build a minimal config that
    # preserves repository entries and only the shortcut values from the
    # existing scripts. This minimal config is then passed to
    # build_script_index so discovered scripts replace python3, execution_path,
    # name, hash_id and source, while shortcuts are retained.
    reset_requested = False
    # The caller may set an attribute on the function (handled below) but we
    # read this variable from the outer scope; it will be overridden in main().

    # Build entries (by default include overrides). If reset_requested is set
    # externally, we'll construct a minimal cfg for indexing further below.
    entries = None

    # If reset_config was requested, construct a minimal cfg preserving only
    # the script shortcuts and repository list, then build the index from it.
    if getattr(refresh, "reset_config", False):
        reset_requested = True

    if reset_requested:
        # Preserve repository definitions as-is
        minimal_cfg = {"repositories": cfg.get("repositories", []), "scripts": []}
        for s in cfg.get("scripts", []) or []:
            # Keep only name, shortcut, and tags so build_script_index will
            # apply the discovered values for other fields
            preserved = {"name": s.get("name")}
            if s.get("shortcut"):
                preserved["shortcut"] = s.get("shortcut")
            if s.get("tags"):
                preserved["tags"] = s.get("tags")
            if "ignore" in s:
                preserved["ignore"] = s.get("ignore")
            minimal_cfg["scripts"].append(preserved)

        entries = build_script_index(root, minimal_cfg)
    else:
        # Build new entries WITH overrides to preserve user edits
        entries = build_script_index(root, cfg)

    # Set executable for all shell scripts (local only)
    for p in list_local_scripts(root):
        if p.suffix.lower() == ".sh":
            set_executable(p)

    # Update config
    cfg = update_scripts_section(cfg, entries)
    save_config(root, cfg)
    
    # Save current config as old for next time
    if config_path.exists():
        import shutil
        shutil.copy(config_path, old_config_path)

    ensure_logs_structure(root, entries)
    
    # If verbose, show what changed in the config
    if verbose:
        new_config_text = config_path.read_text()
        
        if old_config_text and old_config_text != new_config_text:
            # Parse both configs to compare scripts sections
            import yaml
            old_data = yaml.safe_load(old_config_text) if old_config_text else {"scripts": []}
            new_data = yaml.safe_load(new_config_text)
            
            old_scripts = {s["name"]: s for s in old_data.get("scripts", [])}
            new_scripts = {s["name"]: s for s in new_data.get("scripts", [])}
            
            added = {name for name in new_scripts if name not in old_scripts}
            removed = {name for name in old_scripts if name not in new_scripts}
            modified = {}
            
            for name in new_scripts:
                if name in old_scripts:
                    changes = []
                    for key in ["python3", "execution_path", "hash_id", "source"]:
                        old_val = old_scripts[name].get(key, "")
                        new_val = new_scripts[name].get(key, "")
                        if old_val != new_val:
                            changes.append((key, old_val, new_val))
                    if changes:
                        modified[name] = changes
            
            if added or removed or modified:
                # Color codes
                GREEN = "\033[0;32m"
                RED = "\033[0;31m"
                YELLOW = "\033[0;33m"
                RESET = "\033[0m"
                BOLD_GREEN = "\033[1;32m"
                DIM = "\033[2m"
                
                print(f"\n{BOLD_GREEN}Config has been updated{RESET}", file=sys.stderr)
                
                for name in sorted(added):
                    src = new_scripts[name].get("source", "local")
                    src_label = f" [{src}]" if src != "local" else ""
                    print(f"{GREEN}+ {name}{src_label}{RESET}", file=sys.stderr)
                
                for name in sorted(removed):
                    src = old_scripts[name].get("source", "local")
                    src_label = f" [{src}]" if src != "local" else ""
                    print(f"{RED}- {name}{src_label}{RESET}", file=sys.stderr)
                
                for name in sorted(modified.keys()):
                    changes = modified[name]
                    src = new_scripts[name].get("source", "local")
                    src_label = f" [{src}]" if src != "local" else ""
                    print(f"{YELLOW}~ {name}{src_label}{RESET}", file=sys.stderr)
                    for key, old_val, new_val in changes:
                        # Show full old/new values (no truncation) so users can
                        # see the complete change.
                        print(f"{DIM}    {key}: {old_val} → {new_val}{RESET}", file=sys.stderr)
                
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
    ap.add_argument("--reset-config", action="store_true", help="Reset per-script config (python3, execution_path, name, hash_id, source) but keep shortcuts")
    args = ap.parse_args()

    # Communicate the reset flag into the refresh() function via attribute so
    # the inner logic can detect it without changing many call sites.
    setattr(refresh, "reset_config", args.reset_config)

    raise SystemExit(refresh(Path(args.root), verbose=args.verbose))


if __name__ == "__main__":
    main()
