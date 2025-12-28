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
    python fix_category_annotations.py /path/to/Collections --fix --backup

By default this is a dry run (no files are changed). Use --fix to write changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any


def find_json_files(collections_root: Path) -> List[Path]:
    """
    Find all JSON files under .../<collection>/<category>/annots/*.json
    """
    #return sorted(collections_root.glob("*/*/annots/*.json")) # For when a complete collection is given: e.g. Collections_mineral_wool
    return sorted(collections_root.glob("*/annots/*.json")) # For when a specific collection is given, e.g. 2025-10-15_aris-dc_gallant-stag  


def expected_category_for(json_path: Path) -> str:
    """
    Given a path .../<collection>/<category>/annots/file.json,
    return <category>.
    """
    # json_path.parent is annots/, its parent is <category>
    category_dir = json_path.parent.parent.name
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
    parser = argparse.ArgumentParser(
        description="Verify and optionally fix 'category' fields in annotation JSON files."
    )
    parser.add_argument(
        "collections_dir",
        type=Path,
        help='Path to the "Collections" directory',
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Write changes to files by replacing any mismatched 'category' with the category folder name.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="When used with --fix, create a .bak (or .bakN) backup before writing.",
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

        t, m, mm, changed_flag = validate_and_optionally_fix(data, expected, args.fix)

        total_annots += t
        total_matches += m
        total_mismatches += mm

        if mm > 0:
            files_with_mismatch += 1
            if args.print_mismatches and not args.quiet:
                print(f"[MISMATCH] {jp} — expected category '{expected}', {mm} / {t} mismatched")

        if args.fix and changed_flag:
            try:
                if args.backup:
                    backup_path = backup_file(jp)
                    if not args.quiet:
                        print(f"Backed up: {jp} -> {backup_path}")
                save_json(jp, data)
                files_changed += 1
                if not args.quiet:
                    print(f"Fixed: {jp} (set category -> '{expected}')")
            except Exception as e:
                print(f"ERROR writing {jp}: {e}", file=sys.stderr)

        else:
            if not args.quiet:
                status = "OK" if mm == 0 else "NEEDS FIX"
                print(f"[{status}] {jp} — annots: {t}, matches: {m}, mismatches: {mm}")

    print("\nSummary")
    print("-------")
    print(f"Files scanned:        {total_files}")
    print(f"Files w/ mismatches:  {files_with_mismatch}")
    print(f"Files changed:        {files_changed}")
    print(f"Total annotations:    {total_annots}")
    print(f"Matching categories:  {total_matches}")
    print(f"Mismatched categories:{total_mismatches}")
    if args.fix:
        print("\nCompleted with --fix: mismatched 'category' fields were set to the category folder name where needed.")
    else:
        print("\nDry run complete. Re-run with --fix to apply changes.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
