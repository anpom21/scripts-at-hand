
"""
Image comparison and optional move utility

Features
--------
- Compare images in Collection B (found in <category>/ and <category>/images/)
  against images in Collection A (found in */*/images/).
- Optionally write a report of B images that are NOT found in A.
- Optionally MOVE images that are present in BOTH A and B from B to a
  new destination root, creating <dest>/<category>/images/ and resolving
  name conflicts by appending _1, _2, ...

Assumptions
-----------
A (original "Collections"):
  A/
    <subfolder>/
      <category>/
        images/
          <image files>

B ("Collection B"):
  B/
    <category>/
      images/
        <image files>
      <image files may also live directly here>

Destination:
  DEST/
    <category>/
      images/
        <moved files>

Usage
-----
# Compare only
python check_and_move_images.py /path/to/A "/path/to/Collection B"

# Write a plain-text report listing B-only image paths
python check_and_move_images.py /path/to/A "/path/to/Collection B" --report /tmp/missing_images.txt

# CSV report with extra columns
python check_and_move_images.py /path/to/A "/path/to/Collection B" --report /tmp/missing_images.csv --csv

# Case-insensitive filename comparison
python check_and_move_images.py /path/to/A "/path/to/Collection B" --case-insensitive

# Restrict to certain extensions
python check_and_move_images.py /path/to/A "/path/to/Collection B" --ext .png --ext .jpg

# COPY images that exist ONLY in B (not in A) into DEST/<category>/images/ (DEFAULT)
python check_and_move_images.py /path/to/A "/path/to/Collection B" --dest /path/to/DEST

# MOVE images that exist in BOTH A & B into DEST/<category>/images/
python check_and_move_images.py /path/to/A "/path/to/Collection B" --dest /path/to/DEST --exists-in-both

# Dry-run (show what would be moved without changing anything)
python check_and_move_images.py /path/to/A "/path/to/Collection B" --dest /path/to/DEST --dry-run
"""

from pathlib import Path
import argparse
import csv
import shutil
import sys
from typing import Dict, List, Set, Tuple, Optional

DEFAULT_EXTS = [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"]

def unique_destination(base: Path) -> Path:
    """Return a non-colliding path by appending _1, _2, ... before the extension."""
    if not base.exists():
        return base
    stem, suffix = base.stem, base.suffix
    parent = base.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1

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
                #continue
                images_dir = category  # Fallback: maybe images are directly here
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
    """
    Gather images from Collection B found either directly inside each category
    or inside category/images/.
    """
    imgs: List[Path] = []
    for category in B.iterdir():
        if not category.is_dir():
            continue
        # 1) Files directly in the category dir
        for p in category.iterdir():
            if p.is_file() and p.suffix.lower() in valid_exts:
                imgs.append(p)
        # 2) Files in category/images/
        images_dir = category / "images"
        if images_dir.is_dir():
            for p in images_dir.iterdir():
                if p.is_file() and p.suffix.lower() in valid_exts:
                    imgs.append(p)
    return imgs

def category_name_for_B_image(p: Path, B_root: Path) -> str:
    """
    Determine the category name for a B image path.
    If it's under <category>/images/ -> category = parent.parent.name
    If it's directly under <category>/ -> category = parent.name
    """
    parent = p.parent
    if parent.name == "images":
        return parent.parent.name
    else:
        return parent.name

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check if images in Collection B exist in A; optionally copy unique images from B into a destination root by category.")
    parser.add_argument("A", type=Path, help="Path to original 'Collections' (A)")
    parser.add_argument("B", type=Path, help="Path to 'Collection B' (B)")
    parser.add_argument("--case-insensitive", action="store_true", help="Compare filenames case-insensitively")
    parser.add_argument("--ext", action="append", default=None, help="Image extensions to include (repeatable). Default common image types.")
    parser.add_argument("--report", type=Path, default=None, help="Write a summary file of B images missing in A (paths only if not --csv)")
    parser.add_argument("--csv", action="store_true", help="Write report as CSV with extra columns")
    parser.add_argument("--dest", type=Path, default=None, help="Destination root where images will be copied/moved into <dest>/<category>/images/")
    parser.add_argument("--exists-in-both", action="store_true", help="When used with --dest, MOVE images found in BOTH A & B (instead of default: copy images only in B)")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without making any changes")
    args = parser.parse_args(argv)

    A = args.A.expanduser().resolve()
    B = args.B.expanduser().resolve()
    dest_root = args.dest.expanduser().resolve() if args.dest else None

    if not A.is_dir():
        print(f"Error: {A} is not a directory.", file=sys.stderr)
        return 2
    if not B.is_dir():
        print(f"Error: {B} is not a directory.", file=sys.stderr)
        return 2
    if dest_root and not dest_root.exists():
        try:
            if not args.dry_run:
                dest_root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Error: could not create destination root {dest_root}: {e}", file=sys.stderr)
            return 2

    valid_exts = set([e.lower() if e.startswith(".") else "." + e.lower() for e in (args.ext or DEFAULT_EXTS)])

    names_A, paths_map = index_A_images(A, args.case_insensitive, valid_exts)
    b_images = iter_B_images(B, valid_exts)

    # Check if no images found in Collection B
    if len(b_images) == 0:
        print(f"\nWARNING: No images found in Collection B: {B}", file=sys.stderr)
        print(f"Please check your Collection B path.", file=sys.stderr)
        print(f"\nFolders found in {B}:", file=sys.stderr)
        try:
            folders = [item.name for item in B.iterdir() if item.is_dir()]
            if folders:
                for folder in sorted(folders):
                    print(f"  - {folder}", file=sys.stderr)
            else:
                print(f"  (no subdirectories found)", file=sys.stderr)
        except Exception as e:
            print(f"  Error listing directories: {e}", file=sys.stderr)
        print(f"\nExpected structure: {B}/<category>/images/<images.png> or {B}/<category>/<images.png>", file=sys.stderr)
        return 1

    totals = {
        "total_B_images": 0,
        "found_in_A": 0,
        "missing_in_A": 0,
        "moved": 0,
        "copied": 0,
        "move_conflicts": 0,
        "move_errors": 0,
    }
    missing_paths: List[Path] = []
    csv_rows: List[Dict[str, str]] = []

    for p in b_images:
        totals["total_B_images"] += 1
        key = p.name.lower() if args.case_insensitive else p.name
        in_A = key in names_A

        # Print status
        print(f"[{'FOUND' if in_A else 'MISSING'}] {p}")

        # For report/CSV tracking
        if not in_A:
            missing_paths.append(p)

        if args.csv:
            csv_rows.append({
                "b_image_path": str(p),
                "filename": p.name,
                "found_in_A": "YES" if in_A else "NO",
                "matched_paths_in_A": "|".join(str(x) for x in paths_map.get(key, [])) if in_A else ""
            })

        # Optional move/copy to destination
        # Default: copy images that are NOT in A (only in B)
        # If --exists-in-both is set, move images that ARE in both A & B
        should_process = False
        if dest_root:
            if args.exists_in_both:
                should_process = in_A  # Move images found in BOTH A & B
            else:
                should_process = not in_A  # Copy images found in B but NOT in A (default)

        if should_process:
            cat = category_name_for_B_image(p, B)
            dest_images = dest_root / cat / "images"
            try:
                if not args.dry_run:
                    dest_images.mkdir(parents=True, exist_ok=True)
                dest_path = dest_images / p.name
                if dest_path.exists():
                    dest_path = unique_destination(dest_path)
                    totals["move_conflicts"] += 1
                
                if args.dry_run:
                    action = "Move" if args.exists_in_both else "Copy"
                    print(f"  [DRY-RUN] {action} -> {dest_path}")
                else:
                    if args.exists_in_both:
                        shutil.move(str(p), str(dest_path))
                        print(f"  [MOVED] -> {dest_path}")
                        totals["moved"] += 1
                    else:
                        shutil.copy2(str(p), str(dest_path))
                        print(f"  [COPIED] -> {dest_path}")
                        totals["copied"] += 1
            except Exception as e:
                totals["move_errors"] += 1
                print(f"  [ERROR] Failed to process {p}: {e}")

        # Update counts
        if in_A:
            totals["found_in_A"] += 1
        else:
            totals["missing_in_A"] += 1

    # Summary
    print("\nSummary")
    print("-------")
    print(f"Total images in B:  {totals['total_B_images']}")
    print(f"Present in A:       {totals['found_in_A']}")
    print(f"Missing in A:       {totals['missing_in_A']}")
    if dest_root:
        if args.exists_in_both:
            print(f"Moved to dest:      {totals['moved']}")
        else:
            print(f"Copied to dest:     {totals['copied']}")
        print(f"Conflicts (renamed):{totals['move_conflicts']}")
        print(f"Move errors:        {totals['move_errors']}")

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
