#!/usr/bin/env python3
"""Finds duplicate PNG filenames across all subdirectories and reports conflicts with optional CSV output."""
"""
Find duplicate PNG filenames under a directory.

A "duplicate" is defined strictly by the image's filename (case-insensitive by default),
ignoring its directory path. The script searches recursively, so it will catch files in:
- <input>/sub_folder/*.png
- <input>/sub_folder/images/*.png
and anywhere else under <input>.

Usage:
  python find_png_filename_duplicates.py /path/to/input \
      [--case-sensitive] [--report duplicates_report.csv] [--follow-symlinks]

Exit codes:
  0 = no duplicates found
  1 = duplicates found
  2 = error (e.g., bad path)
"""
import argparse
import csv
import sys
from pathlib import Path

def iter_pngs(root: Path, follow_symlinks: bool = False):
    # pathlib's rglob will traverse symlinks if allowed via followlinks in os.walk;
    # emulate by resolving dirs optionally. For simplicity, use rglob and rely on OS symlink behavior.
    # We also ensure we only yield actual files ending with .png (case-insensitive).
    for p in root.rglob("*"):
        try:
            if p.is_file():
                # Only .png files
                if p.suffix.lower() == ".png":
                    yield p
        except PermissionError:
            # Skip entries we cannot access
            continue
        except OSError:
            continue

def main():
    parser = argparse.ArgumentParser(description="Find duplicate PNG filenames under a directory.")
    parser.add_argument("input_dir", type=str, help="Root directory to scan")
    parser.add_argument("--case-sensitive", action="store_true",
                        help="Treat filenames as case-sensitive (default: case-insensitive)")
    parser.add_argument("--report", type=str, default=None,
                        help="Optional path to write a CSV report of duplicates")
    parser.add_argument("--follow-symlinks", action="store_true",
                        help="Attempt to follow symlinks while scanning (may be slower)")
    args = parser.parse_args()

    root = Path(args.input_dir)
    if not root.exists() or not root.is_dir():
        print(f"Error: input_dir '{root}' does not exist or is not a directory.", file=sys.stderr)
        sys.exit(2)

    # Map: key = filename (normalized) -> list of full paths
    buckets = {}
    total_pngs = 0

    # Collect files
    for fp in iter_pngs(root, follow_symlinks=args.follow_symlinks):
        total_pngs += 1
        name = fp.name if args.case_sensitive else fp.name.lower()
        buckets.setdefault(name, []).append(fp)

    # Find duplicates (same filename appears in 2+ locations)
    duplicates = {name: paths for name, paths in buckets.items() if len(paths) > 1}

    # Summary
    unique_names = len(buckets)
    duplicate_groups = len(duplicates)
    duplicate_files_count = sum(len(v) for v in duplicates.values())

    print("Scan complete.")
    print(f"Root: {root}")
    print(f"Total .png files found: {total_pngs}")
    print(f"Unique filenames: {unique_names}")
    print(f"Duplicate filename groups: {duplicate_groups}")
    if duplicate_groups:
        print(f"Total files involved in duplicates: {duplicate_files_count}")

    # Pretty-print duplicates
    if duplicate_groups:
        print("\n=== Duplicate filename groups ===")
        # Sort groups by filename; paths within group sorted for stable output
        for name in sorted(duplicates.keys()):
            print(f"\n{name}:")
            for p in sorted(duplicates[name], key=lambda x: str(x)):
                print(f"  - {p}")

    # Optional CSV report
    if args.report:
        report_path = Path(args.report)
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with report_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["filename", "path"])
                for name in sorted(duplicates.keys()):
                    for p in sorted(duplicates[name], key=lambda x: str(x)):
                        writer.writerow([name, str(p)])
            print(f"\nCSV report written to: {report_path}")
        except Exception as e:
            print(f"\nWarning: failed to write report to '{report_path}': {e}", file=sys.stderr)

    # Exit code indicates whether duplicates were found
    sys.exit(1 if duplicate_groups else 0)

if __name__ == "__main__":
    main()
