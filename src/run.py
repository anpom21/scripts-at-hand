
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

    print("Available scripts:\n")
    for e in entries:
        src = f"[{e.source}]" if e.source != "local" else ""
        desc = f" - {e.description}" if e.description else ""
        print(f"  {e.name} {src}{desc}")

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

    if path.lower().endswith(".py"):
        cmd = [entry.python3, path] + script_args
    else:
        cmd = ["bash", path] + script_args

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

    ap = argparse.ArgumentParser(
        prog="aris",
        description="Unified runner for ARIS production scripts.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    ap.add_argument("--root", required=True, help="Path to aris-cli repo root")
    ap.add_argument("--list", action="store_true", help="List all scripts")
    ap.add_argument("--script", help="Script name to run")
    ap.add_argument("--", dest="_sep", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("args", nargs=argparse.REMAINDER, help="Args passed to the script")

    args = ap.parse_args()
    root = Path(args.root)

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