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

from utils import load_config, build_script_index


def bash_completion(root: Path) -> str:
    """Generate bash completion script.

    Args:
        root: ARIS CLI repo root.

    Returns:
        Bash completion script as string.
    """

    # Load all scripts from the index
    cfg = load_config(root)
    entries = build_script_index(root, cfg)

    # Include both script names and configured shortcuts in completions
    names: list[str] = []
    for e in entries:
        names.append(e.name)
        if getattr(e, "shortcut", None):
            names.append(e.shortcut)
    # Ensure unique ordering
    script_names = " ".join(sorted(set(names), key=str.lower))

    # Build a map of script names (and shortcuts) to their execution paths
    script_exec_paths: dict[str, str] = {}
    for e in entries:
        if e.execution_path:
            script_exec_paths[e.name] = e.execution_path
            if getattr(e, "shortcut", None):
                script_exec_paths[e.shortcut] = e.execution_path

    # Format for bash associative array
    exec_paths_bash = ""
    for name, path in script_exec_paths.items():
        exec_paths_bash += f'  ["{name}"]={path!r}\n'

    return f"""# Bash completion for aris
# Usage:
#   source <(aris completion bash)

_aris_complete() {{
  local cur prev words
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev="${{COMP_WORDS[COMP_CWORD-1]}}"

  # subcommands
  local subcmds="search refresh completion help"

  # Map of script names to execution paths
  declare -A script_paths=(
{exec_paths_bash}  )

  if [[ $COMP_CWORD -eq 1 ]]; then
    # First argument: complete subcommands and script names
    local all_options="$subcmds {script_names}"
    COMPREPLY=( $(compgen -W "$all_options" -- "$cur") )
    return 0
  elif [[ $COMP_CWORD -ge 2 ]]; then
    # Check if the first argument (COMP_WORDS[1]) is a script with an execution_path
    local script_name="${{COMP_WORDS[1]}}"
    if [[ -n "${{script_paths[$script_name]}}" ]]; then
      # Complete files/directories from BOTH execution_path and current directory
      local exec_path="${{script_paths[$script_name]}}"
      local current_pwd="$PWD"
      local completions_exec=()
      local completions_cwd=()
      
      # Get completions from execution_path
      cd "$exec_path" 2>/dev/null && {{
        completions_exec=( $(compgen -f -- "$cur") )
        cd "$current_pwd"
      }}
      
      # Get completions from current working directory
      completions_cwd=( $(compgen -f -- "$cur") )
      
      # Combine both sets of completions, removing duplicates
      local combined=()
      local seen=()
      
      # Add execution_path completions first
      for item in "${{completions_exec[@]}}"; do
        combined+=("$item")
        seen+=("$item")
      done
      
      # Add current directory completions if not already in list
      for item in "${{completions_cwd[@]}}"; do
        local is_duplicate=0
        for seen_item in "${{seen[@]}}"; do
          if [[ "$item" == "$seen_item" ]]; then
            is_duplicate=1
            break
          fi
        done
        if [[ $is_duplicate -eq 0 ]]; then
          combined+=("$item")
        fi
      done
      
      COMPREPLY=( "${{combined[@]}}" )
      return 0
    fi
  fi
  
  # Default: file/directory completion from current directory
  COMPREPLY=( $(compgen -f -- "$cur") )
  return 0
}}

complete -o filenames -F _aris_complete aris
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