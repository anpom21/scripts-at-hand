
# ---------------------------------------------------------------------------
# File: src/search.py
# ---------------------------------------------------------------------------
"""Interactive search for scripts.

Behavior:
- `aris search` starts an interactive real-time search.
- Results update as you type each character.
- Uses curses for proper terminal handling.
- Press Enter/TAB to select top result and run with --help.
- Press ESC or Ctrl+C to quit.

Clean, real-time search with proper terminal handling and automatic help display.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import curses
from pathlib import Path

from utils import (
    load_config,
    build_script_index,
    snippet_around,
    find_entry,
)


def score_match(name: str, desc: str, tags: list[str], source: str, group: str, token: str) -> tuple[int, int, int]:
    """Compute a match score tuple for sorting.

    The tuple is ordered such that lower values are better.
    Priority:
      1) Tag/source/group contains token (0) vs name contains token (1) vs desc contains token (2)
      2) Earlier occurrence index in name/desc/tags/source/group
      3) Shorter name

    Args:
        name: Script name.
        desc: Description.
        tags: List of tags.
        source: Source repository (treated as special tag if not "local").
        group: Group name.
        token: Query token.

    Returns:
        Score tuple.
    """

    token_l = token.lower()
    name_l = name.lower()
    desc_l = desc.lower()
    tags_l = [t.lower() for t in tags]
    source_l = source.lower() if source != "local" else ""
    group_l = group.lower() if group else ""

    # Check if token matches any tag, source, or group
    in_tags = any(token_l in tag for tag in tags_l)
    in_source = source_l and token_l in source_l
    in_group = group_l and token_l in group_l
    in_name = token_l in name_l
    in_desc = token_l in desc_l

    # Priority: tags/source/group > name > desc
    if in_tags or in_source or in_group:
        primary = 0
        # Find first tag/source/group match position
        idx = 0
        if in_tags:
            for i, tag in enumerate(tags_l):
                if token_l in tag:
                    idx = i
                    break
        else:
            idx = 0  # source or group match
    elif in_name:
        primary = 1
        idx = name_l.index(token_l)
    elif in_desc:
        primary = 2
        idx = desc_l.index(token_l)
    else:
        primary = 3
        idx = 10**9

    return (primary, idx, len(name))


def search_curses(stdscr, entries):
    """Run curses-based real-time search.
    
    Args:
        stdscr: curses window object
        entries: List of ScriptEntry objects
        
    Returns:
        Selected script name or None
    """
    # Setup
    curses.curs_set(1)  # Show cursor
    stdscr.nodelay(False)
    stdscr.keypad(True)
    
    # Color setup
    if curses.has_colors():
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)     # Name matches
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)   # (unused)
        curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)    # Tag matches
        curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Source matches
    
    search_query = ""
    selected_script = None
    
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # Header
        header = "ARIS Search - Type to search (ESC/Ctrl+C: quit, Enter/TAB: select top + show help)"
        stdscr.addstr(0, 0, header[:width-1], curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * min(width-1, 70))
        
        # Search prompt
        prompt = f"Search: {search_query}"
        stdscr.addstr(3, 0, prompt[:width-1])
        
        # Find and display matches
        if search_query:
            matches = []
            for e in entries:
                tags = getattr(e, "tags", []) or []
                source = getattr(e, "source", "local")
                group = getattr(e, "group", "")
                # Match in name, description, tags, source (if not local), or group
                if search_query.lower() in e.name.lower() or \
                   search_query.lower() in (e.description or "").lower() or \
                   any(search_query.lower() in tag.lower() for tag in tags) or \
                   (source != "local" and search_query.lower() in source.lower()) or \
                   (group and search_query.lower() in group.lower()):
                    matches.append(e)
            
            # Prioritize scripts that have a configured shortcut. Within each
            # group (has shortcut vs not), use the existing score_match ordering.
            matches.sort(
                key=lambda e: (
                    0 if getattr(e, "shortcut", "") else 1,
                    *score_match(e.name, e.description or "", getattr(e, "tags", []) or [], 
                                getattr(e, "source", "local"), getattr(e, "group", ""), search_query),
                )
            )
            
            if matches:
                stdscr.addstr(4, 0, f"Found {len(matches)} result(s):", curses.A_DIM)
                
                # Display up to 10 results
                max_results = min(10, height - 7)
                line = 6
                for i, e in enumerate(matches[:max_results]):
                    if line >= height - 1:
                        break
                    
                    # Format the result
                    group_label = getattr(e, "group", "")
                    src = f" [{group_label}]" if group_label else ""
                    result_line = f"  {i+1}. {e.name}{src}"
                    
                    # Highlight the match in the name
                    if search_query.lower() in e.name.lower():
                        # Find position of match
                        idx = e.name.lower().index(search_query.lower())
                        before = result_line[:result_line.index(e.name) + idx]
                        match = result_line[len(before):len(before) + len(search_query)]
                        after = result_line[len(before) + len(search_query):]
                        
                        stdscr.addstr(line, 0, before[:width-1])
                        if curses.has_colors():
                            stdscr.addstr(match[:width-1-len(before)], curses.color_pair(1) | curses.A_BOLD)
                        else:
                            stdscr.addstr(match[:width-1-len(before)], curses.A_REVERSE)
                        stdscr.addstr(after[:width-1-len(before)-len(match)])
                    else:
                        stdscr.addstr(line, 0, result_line[:width-1])
                    
                    line += 1
                    
                    # Show matching tags in bold cyan if present
                    tags = getattr(e, "tags", []) or []
                    source = getattr(e, "source", "local")
                    group = getattr(e, "group", "")
                    matching_tags = [tag for tag in tags if search_query.lower() in tag.lower()]
                    group_matches = group and search_query.lower() in group.lower()
                    
                    # Display tags and/or group if they match
                    if line < height - 1 and (matching_tags or group_matches):
                        stdscr.addstr(line, 0, "     tags: ", curses.A_DIM)
                        
                        # Show group first in yellow if it matches
                        if group_matches:
                            if curses.has_colors():
                                stdscr.addstr(group, curses.color_pair(4) | curses.A_BOLD)
                            else:
                                stdscr.addstr(group, curses.A_BOLD)
                            if matching_tags:
                                stdscr.addstr(", ", curses.A_DIM)
                        
                        # Show matching tags in cyan
                        for idx_tag, tag in enumerate(matching_tags):
                            if idx_tag > 0:
                                stdscr.addstr(", ", curses.A_DIM)
                            if curses.has_colors():
                                stdscr.addstr(tag, curses.color_pair(3) | curses.A_BOLD)
                            else:
                                stdscr.addstr(tag, curses.A_BOLD)
                        line += 1
                    # If group doesn't match but we still want to show it, display it even without search match
                    elif line < height - 1 and group:
                        stdscr.addstr(line, 0, "     tags: ", curses.A_DIM)
                        if curses.has_colors():
                            stdscr.addstr(group, curses.color_pair(4) | curses.A_DIM)
                        else:
                            stdscr.addstr(group, curses.A_DIM)
                        line += 1
                    
                    # Show description snippet if match is in description
                    if line < height - 1 and search_query.lower() in (e.description or "").lower():
                        snip = snippet_around(e.description or "", search_query, radius=40)
                        desc_line = f"     {snip}"
                        stdscr.addstr(line, 0, desc_line[:width-1], curses.A_DIM)
                        line += 1
                
                if len(matches) > max_results:
                    if line < height - 1:
                        stdscr.addstr(line, 0, f"     ... and {len(matches) - max_results} more", curses.A_DIM)
            else:
                stdscr.addstr(5, 0, "  No matches found", curses.A_DIM)
        else:
            stdscr.addstr(5, 0, "  Start typing to search...", curses.A_DIM)
        
        # Position cursor at end of search query
        stdscr.move(3, len(prompt))
        stdscr.refresh()
        
        # Get input
        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            break
        
        # Handle input
        if ch == 27:  # ESC
            break
        elif ch in (curses.KEY_ENTER, 10, 13):  # Enter
            if search_query and matches:
                selected_script = matches[0].name
                break
        elif ch == 9:  # TAB
            if search_query and matches:
                selected_script = matches[0].name
                break
        elif ch in (curses.KEY_BACKSPACE, 127, 8):  # Backspace
            if search_query:
                search_query = search_query[:-1]
        elif ch == curses.KEY_RESIZE:
            # Handle terminal resize
            continue
        elif 32 <= ch <= 126:  # Printable characters
            search_query += chr(ch)
    
    return selected_script


def interactive_search(root: Path) -> int:
    """Run interactive search with curses for real-time updates.

    Args:
        root: Repository root.

    Returns:
        Exit code.
    """

    cfg = load_config(root)
    entries = build_script_index(root, cfg)

    # Filter ignored scripts
    entries = [e for e in entries if not e.ignore]

    try:
        selected = curses.wrapper(search_curses, entries)
        
        if selected:
            # Find the entry
            entry = find_entry(entries, selected)
            if not entry:
                print(f"Error: Script not found: {selected}", file=sys.stderr)
                return 1
            
            # Run the script with --help or -h
            print(f"\n{'=' * 70}")
            print(f"Running: aris {selected} --help")
            print(f"{'=' * 70}\n")
            
            # Determine the command
            path = entry.abspath
            if path.lower().endswith(".py"):
                cmd = [entry.python3, path, "--help"]
            else:
                cmd = ["bash", path, "--help"]
            
            # Execute in script's execution_path
            cwd = entry.execution_path if entry.execution_path else str(Path(path).parent)
            
            # Try --help first, if it fails try -h
            try:
                result = subprocess.run(cmd, cwd=cwd)
                if result.returncode != 0:
                    # Try with -h instead
                    cmd[-1] = "-h"
                    subprocess.run(cmd, cwd=cwd)
            except Exception as e:
                print(f"Error running script: {e}", file=sys.stderr)
                return 1
        else:
            print("\nSearch cancelled.\n")
        
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main() -> None:
    """CLI entrypoint for search.

    Args:
        None

    Returns:
        None
    """

    ap = argparse.ArgumentParser(description="Interactive search over scripts")
    ap.add_argument("--root", required=True, help="Path to aris-cli repo root")
    args = ap.parse_args()

    raise SystemExit(interactive_search(Path(args.root)))


if __name__ == "__main__":
    main()
