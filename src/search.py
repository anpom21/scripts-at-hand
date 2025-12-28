
# ---------------------------------------------------------------------------
# File: src/search.py
# ---------------------------------------------------------------------------
"""Interactive search for scripts.

Behavior:
- `aris search` starts an interactive real-time search.
- Results update as you type each character.
- Uses curses for proper terminal handling.
- Press Enter/TAB to select top result.
- Press ESC or Ctrl+C to quit.

Clean, real-time search with proper terminal handling.
"""

from __future__ import annotations

import argparse
import sys
import curses
from pathlib import Path

from utils import (
    load_config,
    build_script_index,
    snippet_around,
)


def score_match(name: str, desc: str, token: str) -> tuple[int, int, int]:
    """Compute a match score tuple for sorting.

    The tuple is ordered such that lower values are better.
    Priority:
      1) Name contains token (0) vs not (1)
      2) Earlier occurrence index in name/desc
      3) Shorter name

    Args:
        name: Script name.
        desc: Description.
        token: Query token.

    Returns:
        Score tuple.
    """

    token_l = token.lower()
    name_l = name.lower()
    desc_l = desc.lower()

    in_name = token_l in name_l
    in_desc = token_l in desc_l

    primary = 0 if in_name else 1
    if in_name:
        idx = name_l.index(token_l)
    elif in_desc:
        idx = desc_l.index(token_l)
    else:
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
        curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)
    
    search_query = ""
    selected_script = None
    
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # Header
        header = "ARIS Search - Type to search (ESC/Ctrl+C: quit, Enter/TAB: select top)"
        stdscr.addstr(0, 0, header[:width-1], curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * min(width-1, 70))
        
        # Search prompt
        prompt = f"Search: {search_query}"
        stdscr.addstr(3, 0, prompt[:width-1])
        
        # Find and display matches
        if search_query:
            matches = []
            for e in entries:
                if search_query.lower() in e.name.lower() or \
                   search_query.lower() in (e.description or "").lower():
                    matches.append(e)
            
            matches.sort(key=lambda e: score_match(e.name, e.description or "", search_query))
            
            if matches:
                stdscr.addstr(4, 0, f"Found {len(matches)} result(s):", curses.A_DIM)
                
                # Display up to 10 results
                max_results = min(10, height - 7)
                line = 6
                for i, e in enumerate(matches[:max_results]):
                    if line >= height - 1:
                        break
                    
                    # Format the result
                    src = f" [{e.source}]" if e.source != "local" else ""
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

    try:
        selected = curses.wrapper(search_curses, entries)
        
        if selected:
            print(f"\n{'=' * 70}")
            print(f"Selected: {selected}")
            print(f"Command:  aris {selected}")
            print(f"{'=' * 70}\n")
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
