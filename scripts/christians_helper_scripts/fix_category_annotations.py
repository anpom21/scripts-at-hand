"""
Scan a Collections directory for JSON annotation files and verify/optionally fix
the "category" field in each annotation to match the category subfolder name.

Directory layout assumed:

Collections/
  <collection_name>/
    <category_name>/
      annots/
        *.json
      images/
        ...

Example:
    python fix_category_annotations.py /path/to/Collections
    python fix_category_annotations.py /path/to/Collections --run --backup

By default this is a dry run (no files are changed). Use --run to write changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any

GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

def find_json_files(collections_root: Path) -> List[Path]:
    """
    Find all JSON files under:
    - .../<collection>/<category>/annots/*.json
    - .../<collection>/<category>/*.json (root of category folder)
    Automatically detects whether collections_root is a collection or contains captures.
    """
    files_set = set()
    
    # Try collection-level pattern first (when run from Collections_wood)
    # Check both annots/ folder and root of category folder
    files_set.update(collections_root.glob("*/*/annots/*.json"))
    files_set.update(collections_root.glob("*/*/*.json"))
    
    # If no files found, try capture-level pattern (when run from 2025-10-15_aris-dc_gallant-stag)
    # Check both annots/ folder and root of category folder
    if not files_set:
        files_set.update(collections_root.glob("*/annots/*.json"))
        files_set.update(collections_root.glob("*/*.json"))
    
    # Filter out files that are in images/ or other non-annotation directories
    # Keep only files that are either in annots/ or directly in category folder
    filtered_files = []
    for f in files_set:
        # Exclude files from images/ or other known non-annotation directories
        if "images" not in f.parts:
            filtered_files.append(f)
    
    return sorted(filtered_files)  


def expected_category_for(json_path: Path) -> str:
    """
    Given a path:
    - .../<collection>/<category>/annots/file.json OR
    - .../<collection>/<category>/file.json
    return <category>.
    """
    # Check if file is in annots/ subdirectory
    if json_path.parent.name == "annots":
        # json_path.parent is annots/, its parent is <category>
        category_dir = json_path.parent.parent.name
    else:
        # json_path is directly in <category> folder
        category_dir = json_path.parent.name
    
    return category_dir


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def validate_and_optionally_fix(
    data: Dict[str, Any], expected_category: str, do_fix: bool
) -> Tuple[int, int, int, bool]:
    """
    Validate "category" values in the annotations list.

    Returns:
        (total_annots, matches, mismatches, changed)
    """
    annots = data.get("annotations")
    if not isinstance(annots, list):
        return (0, 0, 0, False)

    total = len(annots)
    matches = 0
    mismatches = 0
    changed = False

    for a in annots:
        if not isinstance(a, dict):
            mismatches += 1
            continue
        cat = a.get("category")
        if cat == expected_category:
            matches += 1
        else:
            mismatches += 1
            if do_fix:
                a["category"] = expected_category
                changed = True

    return (total, matches, mismatches, changed)


def backup_file(path: Path) -> Path:
    backup = path.with_suffix(path.suffix + ".bak")
    # Avoid overwriting an existing backup unintentionally
    if backup.exists():
        i = 1
        while True:
            alt = path.with_suffix(path.suffix + f".bak{i}")
            if not alt.exists():
                backup = alt
                break
            i += 1
    backup.write_bytes(path.read_bytes())
    return backup


def main(argv: List[str] | None = None) -> int:
    global GREEN, YELLOW, RESET
    parser = argparse.ArgumentParser(
        description="Verify and optionally fix 'category' fields in annotation JSON files."
    )
    parser.add_argument(
        "collections_dir",
        type=Path,
        help='Path to the "Collections" directory',
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Write changes to files by replacing any mismatched 'category' with the category folder name.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="When used with --run, create a .bak (or .bakN) backup before writing.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce per-file logging; only print a final summary and changes.",
    )
    parser.add_argument(
        "--print-mismatches",
        action="store_true",
        help="Print a line for each file that has mismatches (useful in dry-run).",
    )

    args = parser.parse_args(argv)

    root = args.collections_dir
    if not root.exists() or not root.is_dir():
        print(f"ERROR: Path does not exist or is not a directory: {root}", file=sys.stderr)
        return 2

    json_files = find_json_files(root)
    if not json_files:
        print("No JSON files found under */*/annots/*.json", file=sys.stderr)
        return 1

    total_files = 0
    files_with_mismatch = 0
    files_changed = 0
    total_annots = 0
    total_matches = 0
    total_mismatches = 0

    for jp in json_files:
        total_files += 1
        expected = expected_category_for(jp)

        try:
            data = load_json(jp)
        except Exception as e:
            print(f"ERROR reading {jp}: {e}", file=sys.stderr)
            continue

        t, m, mm, changed_flag = validate_and_optionally_fix(data, expected, args.run)

        total_annots += t
        total_matches += m
        total_mismatches += mm

        if mm > 0:
            files_with_mismatch += 1
            if args.print_mismatches and not args.quiet:
                # Collect actual categories found in mismatched annotations
                actual_cats = set()
                for a in data.get("annotations", []):
                    if isinstance(a, dict):
                        cat = a.get("category")
                        if cat and cat != expected:
                            actual_cats.add(cat)
                actual_cats_str = ", ".join(f"'{c}'" for c in sorted(actual_cats))
                print(f"[MISMATCH] {jp} — folder category: '{expected}', annotation categories: {actual_cats_str}, {mm} / {t} mismatched")

        if args.run and changed_flag:
            try:
                if args.backup:
                    backup_path = backup_file(jp)
                    if not args.quiet:
                        print(f"Backed up: {jp} -> {backup_path}")
                save_json(jp, data)
                files_changed += 1
                if not args.quiet:
                    print(f"[{BOLD}{GREEN}FIXED{RESET}]: {jp} (folder category: {BOLD}{GREEN}'{expected}'{RESET}, corrected {mm} annotations)")
            except Exception as e:
                print(f"ERROR writing {jp}: {e}", file=sys.stderr)

        else:
            if not args.quiet:
                # Collect actual categories for better logging
                actual_cats = set()
                for a in data.get("annotations", []):
                    if isinstance(a, dict):
                        cat = a.get("category")
                        if cat:
                            actual_cats.add(cat)
                actual_cats_str = ", ".join(f"'{c}'" for c in sorted(actual_cats))
                status = f"{GREEN}OK{RESET}" if mm == 0 else f"{YELLOW}NEEDS FIX{RESET}"
                if mm == 0:
                    print(f"[{status}] {jp} — folder category: '{expected}', annotation category: '{expected}', annots: {t}")
                else:
                    print(f"[{status}] {jp} — folder category: {BOLD}'{expected}'{RESET}, annotation categories: {BOLD}{YELLOW}{actual_cats_str}{RESET}, annots: {t}, matches: {m}, mismatches: {mm}")

    print("\nSummary")
    print("-------")
    print(f"Files scanned:        {total_files}")
    print(f"Files w/ mismatches:  {files_with_mismatch}")
    print(f"Files changed:        {files_changed}")
    print(f"Total annotations:    {total_annots}")
    print(f"Matching categories:  {total_matches}")
    print(f"Mismatched categories:{total_mismatches}")
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    if files_with_mismatch == 0:
        print(f"\n{GREEN}All files are consistent. No changes needed.{RESET}")
    elif args.run:
        print("\nCompleted with --run: mismatched 'category' fields were set to the category folder name where needed.")
    else:
        print(f"\n{YELLOW}Dry run complete. Re-run with --run to apply changes.{RESET}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
