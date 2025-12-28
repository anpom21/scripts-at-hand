"""Compares images between two collection directories by filename and reports which images in B are missing from A."""
"""
Check if each image in Collection B exists in Collection A (original).
Optionally write a summary file containing the *B-side paths* of images
that are in B but not in A.

Directory layout assumptions
----------------------------
A (original "Collections"):
  A/
    <subfolder>/
      <category>/
        images/
          <image files>

B ("Collection B")("Capture"):
  B/
    <category>/
      images/
        <image files>

Behavior
--------
- For every file under B/*/images/, we check if a file with the **same filename**
  exists anywhere under A/*/*/images/.
- By default, matching is **case-sensitive** on filenames. You can use
  --case-insensitive to compare names case-insensitively.
- You can restrict which files to consider with --ext (repeatable). Default:
  .png, .jpg, .jpeg, .bmp, .tif, .tiff, .webp
- If --report is provided, we write a summary text file listing **one path per line**
  for each image that is present in B but not found in A.
  Optionally, use --csv to write a CSV with columns:
  b_image_path, filename, found_in_A, matched_paths_in_A

Usage
-----
# Compare only
python check_images_simple.py /path/to/A "/path/to/Collection B"

# Case-insensitive matching
python check_images_simple.py /path/to/A "/path/to/Collection B" --case-insensitive

# Report missing (paths only, text file)
python check_images_simple.py /path/to/A "/path/to/Collection B" --report /tmp/missing_images.txt

# CSV report
python check_images_simple.py /path/to/A "/path/to/Collection B" --report /tmp/missing_images.csv --csv

# Restrict to certain extensions
python check_images_simple.py /path/to/A "/path/to/Collection B" --ext .png --ext .jpg
"""

from pathlib import Path
import argparse
import csv
import sys
from typing import Dict, List, Set, Tuple

DEFAULT_EXTS = [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"]

def index_A_images(A: Path, case_insensitive: bool, valid_exts: Set[str]) -> Tuple[Set[str], Dict[str, List[Path]]]:
    """
    Walk A and collect all image filenames and a map to their full paths.
      - names_A: set of normalized filenames (case as per flag)
      - paths_map: {normalized filename -> [full paths in A]}
    Only files under images/ with extension in valid_exts are included.
    """
    names_A: Set[str] = set()
    paths_map: Dict[str, List[Path]] = {}

    for sub in A.iterdir():
        if not sub.is_dir():
            continue
        for category in sub.iterdir():
            if not category.is_dir():
                continue
            images_dir = category / "images"
            if not images_dir.is_dir():
                continue
            for p in images_dir.iterdir():
                if not p.is_file():
                    continue
                if p.suffix.lower() not in valid_exts:
                    continue
                key = p.name.lower() if case_insensitive else p.name
                names_A.add(key)
                paths_map.setdefault(key, []).append(p)
    return names_A, paths_map

def iter_B_images(B: Path, valid_exts: Set[str]) -> List[Path]:
    imgs: List[Path] = []
    for category in B.iterdir():
        if not category.is_dir():
            continue

        # 1. Images directly in the category
        for p in category.iterdir():
            if p.is_file() and p.suffix.lower() in valid_exts:
                imgs.append(p)

        # 2. Images in the category/images subdir
        images_dir = category / "images"
        if images_dir.is_dir():
            for p in images_dir.iterdir():
                if p.is_file() and p.suffix.lower() in valid_exts:
                    imgs.append(p)

    return imgs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check if images in Collection B also exist in Collection A (by filename).")
    parser.add_argument("A", type=Path, help="Path to original 'Collections' (A)")
    parser.add_argument("B", type=Path, help="Path to 'Collection B' (B)")
    parser.add_argument("--case-insensitive", action="store_true", help="Compare filenames case-insensitively")
    parser.add_argument("--ext", action="append", default=None, help="Image extensions to include (repeatable). Default common image types.")
    parser.add_argument("--report", type=Path, default=None, help="Write a summary file of B images missing in A (paths only if not --csv)")
    parser.add_argument("--csv", action="store_true", help="Write report as CSV with extra columns")
    args = parser.parse_args(argv)

    A = args.A.expanduser().resolve()
    B = args.B.expanduser().resolve()

    if not A.is_dir():
        print(f"Error: {A} is not a directory.", file=sys.stderr)
        return 2
    if not B.is_dir():
        print(f"Error: {B} is not a directory.", file=sys.stderr)
        return 2

    valid_exts = set([e.lower() if e.startswith(".") else "." + e.lower() for e in (args.ext or DEFAULT_EXTS)])

    names_A, paths_map = index_A_images(A, args.case_insensitive, valid_exts)
    b_images = iter_B_images(B, valid_exts)

    totals = {
        "total_B_images": 0,
        "found_in_A": 0,
        "missing_in_A": 0,
    }
    missing_paths: List[Path] = []
    csv_rows: List[Dict[str, str]] = []

    for p in b_images:
        totals["total_B_images"] += 1
        key = p.name.lower() if args.case_insensitive else p.name
        if key in names_A:
            totals["found_in_A"] += 1
            print(f"[FOUND] {p}")
            if args.csv:
                csv_rows.append({
                    "b_image_path": str(p),
                    "filename": p.name,
                    "found_in_A": "YES",
                    "matched_paths_in_A": "|".join(str(x) for x in paths_map.get(key, []))
                })
        else:
            totals["missing_in_A"] += 1
            print(f"[MISSING] {p}")
            missing_paths.append(p)
            if args.csv:
                csv_rows.append({
                    "b_image_path": str(p),
                    "filename": p.name,
                    "found_in_A": "NO",
                    "matched_paths_in_A": ""
                })

    # Summary
    print("\nSummary")
    print("-------")
    print(f"Total images in B:  {totals['total_B_images']}")
    print(f"Present in A:       {totals['found_in_A']}")
    print(f"Missing in A:       {totals['missing_in_A']}")

    # Report
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        if args.csv:
            with args.report.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["b_image_path","filename","found_in_A","matched_paths_in_A"])
                writer.writeheader()
                for r in csv_rows:
                    writer.writerow(r)
            print(f"\nCSV report written to: {args.report}")
        else:
            with args.report.open("w", encoding="utf-8") as f:
                for mp in missing_paths:
                    f.write(str(mp) + "\n")
            print(f"\nReport written to: {args.report} (paths of images present in B but not in A)")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
