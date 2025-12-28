
# ---------------------------------------------------------------------------
# File: src/search.py
# ---------------------------------------------------------------------------
"""Interactive search for scripts.

Behavior:
- `aris search` starts an interactive loop.
- User types tokens; matching scripts are displayed.
- Matches on name are primary; description is secondary.
- Shows snippets from name/description where token appears.
- Highlights the token in red bold.

This is intentionally implemented in Python for rich TUI behavior.
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
    """Run interactive search loop.

    Args:
        root: Repository root.

    Returns:
        Exit code.
    """

    cfg = load_config(root)
    entries = build_script_index(root, cfg)

    print("Interactive search (type 'exit' to quit).")

    while True:
        try:
            token = input("search> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if token.lower() in {"exit", "quit", ":q"}:
            break
        if not token:
            continue

        matches = []
        for e in entries:
            if token.lower() in e.name.lower() or token.lower() in (e.description or "").lower():
                matches.append(e)

        matches.sort(key=lambda e: score_match(e.name, e.description or "", token))

        if not matches:
            print("  (no matches)")
            continue

        print()
        for e in matches[:30]:
            # Build display line
            src = f"[{e.source}]" if e.source != "local" else ""
            name_h = highlight_token(e.name, token)
            desc = e.description or ""
            if token.lower() in desc.lower():
                snip = snippet_around(desc, token)
                snip_h = highlight_token(snip, token)
                print(f"  {name_h} {src}\n    {snip_h}")
            else:
                # token match in name
                print(f"  {name_h} {src}")
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
