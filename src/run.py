
# ---------------------------------------------------------------------------
# File: src/run.py
# ---------------------------------------------------------------------------
"""Run scripts via `aris <script_name> [args...]`.

Features:
- Lists scripts when invoked with --list.
- Executes python scripts with configured python3 interpreter.
- Executes shell scripts via bash.
- Pass-through args to scripts.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from utils import load_config, build_script_index, find_entry


def list_scripts(root: Path) -> int:
    """Print available scripts.

    Args:
        root: Repository root.

    Returns:
        Exit code.
    """

    cfg = load_config(root)
    entries = build_script_index(root, cfg)

    # Color codes
    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print("Available scripts:\n")
    for e in entries:
        # Script name in green
        name_colored = f"{GREEN}{e.name}{RESET}"
        
        # Shortcut in dim grey if present
        shortcut_colored = f" {DIM}({e.shortcut}){RESET}" if getattr(e, "shortcut", "") else ""
        
        # Source in red brackets if not local
        src_colored = f" {RED}[{e.source}]{RESET}" if e.source != "local" else ""
        
        # Description in dim grey
        desc_colored = f" {DIM}- {e.description}{RESET}" if e.description else ""
        
        print(f"  {name_colored}{shortcut_colored}{src_colored}{desc_colored}")

    return 0


def run_script(root: Path, script_name: str, script_args: list[str]) -> int:
    """Execute a script by name.

    Args:
        root: Repository root.
        script_name: Normalized script name.
        script_args: Remaining CLI args passed to the script.

    Returns:
        Exit code from executed script.
    """

    cfg = load_config(root)
    entries = build_script_index(root, cfg)

    entry = find_entry(entries, script_name)
    if not entry:
        print(f"Unknown script: {script_name}", file=sys.stderr)
        print("Run `aris` to see available scripts.", file=sys.stderr)
        return 2

    path = entry.abspath
    
    # Convert relative paths in script_args to absolute paths
    # This preserves paths relative to the user's current directory
    # before we change to execution_path
    resolved_args = []
    for arg in script_args:
        # Check if arg looks like a path or if it exists as a file/directory
        # Skip obvious flags/options (start with -)
        if not arg.startswith('-'):
            arg_path = Path(arg)
            # If it's a relative path, convert to absolute
            if not arg_path.is_absolute():
                abs_path = Path.cwd() / arg_path
                # If the path exists from current directory, use absolute path
                if abs_path.exists():
                    resolved_args.append(str(abs_path))
                else:
                    # Path doesn't exist - could be a path argument that will be created,
                    # or just a regular string argument. If it looks like a path (has separators
                    # or starts with ./ or ../), resolve it anyway
                    if ('/' in arg or '\\' in arg or arg.startswith('./')):
                        resolved_args.append(str(abs_path.resolve()))
                    else:
                        # Keep as-is (probably just a string argument)
                        resolved_args.append(arg)
            else:
                resolved_args.append(arg)
        else:
            resolved_args.append(arg)

    if path.lower().endswith(".py"):
        cmd = [entry.python3, path] + resolved_args
    else:
        cmd = ["bash", path] + resolved_args

    # Execute in script's execution_path (or script's directory if not set)
    cwd = entry.execution_path if entry.execution_path else str(Path(path).parent)

    p = subprocess.run(cmd, cwd=cwd)
    return p.returncode


def main() -> None:
    """Main CLI router for run.

    Args:
        None

    Returns:
        None
    """

    description = """Unified runner for ARIS production scripts.

Execute aris scripts with: aris <script> <args>

Example:
  aris collection_annots_overview.py <collection_dir>
  aris 2_rename_files.py --help
  aris review_annotations.py -d ./my_collection -n collection_review

Options:
  search              Interactive search for scripts
  --add, -a <path>    Add a script (.py/.sh) or git repository (with .git folder)
  --open, -o          Open repository in VS Code and show repo path
  --list              List all available scripts
  --config, -c        Open config.yaml in default editor
  --refresh           Refresh script index and show changes
  --revert            Revert config.yaml to previous backup and refresh
  --reset-config      Reset per-script config (python3, execution_path, name, hash_id, source) but keep shortcuts
  --help, -h          Show this help message"""

    ap = argparse.ArgumentParser(
        prog="aris",
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    ap.add_argument("--root", required=True, help=argparse.SUPPRESS)
    ap.add_argument("--list", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--script", help=argparse.SUPPRESS)
    ap.add_argument("--", dest="_sep", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    ap.add_argument("-h", "--help", action="store_true", help=argparse.SUPPRESS)

    args = ap.parse_args()
    root = Path(args.root)

    if args.help:
        print(description)
        return

    if args.list:
        raise SystemExit(list_scripts(root))

    if not args.script:
        ap.print_help()
        raise SystemExit(0)

    # argparse includes leading '--' in args.args sometimes; strip it
    script_args = args.args
    if script_args and script_args[0] == "--":
        script_args = script_args[1:]

    raise SystemExit(run_script(root, args.script, script_args))


if __name__ == "__main__":
    main()