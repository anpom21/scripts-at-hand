
# ---------------------------------------------------------------------------
# File: src/search.py
# ---------------------------------------------------------------------------
"""Interactive search for scripts.

Behavior:
- `aris search` starts an interactive loop.
- User types search query and presses Enter.
- Results appear below with highlighted matches.
- Type a new query to search again.
- Type 'exit' or Ctrl+C to quit.
- Type a number to select that result.

Simple and reliable approach.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from utils import (
    load_config,
    build_script_index,
    highlight_token,
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


def interactive_search(root: Path) -> int:
    """Run interactive search loop with simple input.

    Args:
        root: Repository root.

    Returns:
        Exit code.
    """

    cfg = load_config(root)
    entries = build_script_index(root, cfg)

    print("=" * 70)
    print("ARIS Script Search")
    print("=" * 70)
    print("Type your search query and press Enter.")
    print("Type a number (1-10) to select that result.")
    print("Type 'exit', 'quit', or press Ctrl+C to quit.\n")

    while True:
        try:
            query = input("search> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting search.")
            return 0

        if query.lower() in {"exit", "quit", "q"}:
            return 0

        if not query:
            continue

        # Check if user typed a number to select a previous result
        if query.isdigit():
            print("Please search first, then type a number to select.")
            continue

        # Find matches
        matches = []
        for e in entries:
            if query.lower() in e.name.lower() or query.lower() in (e.description or "").lower():
                matches.append(e)

        matches.sort(key=lambda e: score_match(e.name, e.description or "", query))

        if not matches:
            print("  No matches found.\n")
            continue

        # Display results with numbers
        print(f"\nFound {len(matches)} result(s):\n")
        max_display = 10
        for i, e in enumerate(matches[:max_display], 1):
            src = f"[{e.source}]" if e.source != "local" else ""
            name_h = highlight_token(e.name, query)
            desc = e.description or ""
            
            if query.lower() in desc.lower():
                snip = snippet_around(desc, query, radius=60)
                snip_h = highlight_token(snip, query)
                print(f"  {i}. {name_h} {src}")
                print(f"     {snip_h}")
            else:
                print(f"  {i}. {name_h} {src}")

        if len(matches) > max_display:
            print(f"\n  ... and {len(matches) - max_display} more (refine your search)")

        # Prompt for selection
        print()
        try:
            selection = input("Select [1-10] or search again> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting search.")
            return 0

        if selection.lower() in {"exit", "quit", "q"}:
            return 0

        # Check if selection is a number
        if selection.isdigit():
            idx = int(selection) - 1
            if 0 <= idx < min(len(matches), max_display):
                selected = matches[idx]
                print(f"\n{'=' * 70}")
                print(f"Selected: {selected.name}")
                print(f"Command:  aris {selected.name}")
                print(f"{'=' * 70}\n")
                return 0
            else:
                print(f"Invalid selection. Please choose 1-{min(len(matches), max_display)}.\n")
        else:
            # Treat as new search query
            query = selection
            if not query:
                continue

            # Find matches for new query
            matches = []
            for e in entries:
                if query.lower() in e.name.lower() or query.lower() in (e.description or "").lower():
                    matches.append(e)

            matches.sort(key=lambda e: score_match(e.name, e.description or "", query))

            if not matches:
                print("  No matches found.\n")
                continue

            # Display results
            print(f"\nFound {len(matches)} result(s):\n")
            for i, e in enumerate(matches[:max_display], 1):
                src = f"[{e.source}]" if e.source != "local" else ""
                name_h = highlight_token(e.name, query)
                desc = e.description or ""
                
                if query.lower() in desc.lower():
                    snip = snippet_around(desc, query, radius=60)
                    snip_h = highlight_token(snip, query)
                    print(f"  {i}. {name_h} {src}")
                    print(f"     {snip_h}")
                else:
                    print(f"  {i}. {name_h} {src}")

            if len(matches) > max_display:
                print(f"\n  ... and {len(matches) - max_display} more (refine your search)")
            print()

    return 0


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
