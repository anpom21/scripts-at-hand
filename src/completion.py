# ---------------------------------------------------------------------------
# File: src/completion.py
# ---------------------------------------------------------------------------
"""Shell completion helpers.

Supports:
- `aris completion bash` prints a bash completion script.

This relies on `aris` being on PATH and the repository root being stable.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def bash_completion(root: Path) -> str:
    """Generate bash completion script.

    Args:
        root: ARIS CLI repo root.

    Returns:
        Bash completion script as string.
    """

    return f"""# Bash completion for aris
# Usage:
#   source <(aris completion bash)

_aris_complete() {{
  local cur prev
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev="${{COMP_WORDS[COMP_CWORD-1]}}"

  # subcommands
  local subcmds="search refresh completion help"

  if [[ $COMP_CWORD -eq 1 ]]; then
    # list scripts + subcommands
    local scripts
    scripts=$(python3 \"{root}/src/run.py\" --root \"{root}\" --list | awk '{{print $1}}' | tr '\n' ' ')
    COMPREPLY=( $(compgen -W "$subcmds $scripts" -- "$cur") )
    return 0
  fi
}}

complete -F _aris_complete aris
"""


def main() -> None:
    """CLI entrypoint for completion.

    Args:
        None

    Returns:
        None
    """

    ap = argparse.ArgumentParser(description="Generate shell completion")
    ap.add_argument("--root", required=True)
    ap.add_argument("shell", choices=["bash"], help="Shell type")
    args = ap.parse_args()

    if args.shell == "bash":
        print(bash_completion(Path(args.root)))


if __name__ == "__main__":
    main()