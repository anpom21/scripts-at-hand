#!/usr/bin/env python3
"""
Append a ground-truth category ("gt") column to a CSV by looking up
each file_name in a directory where images are organized in category folders.

No third-party packages required.

Folder layout (example):
  /path/to/images_root/
      indoor_wood/
          img1.png
      hands/
          hand_001.png

CSV layout (example):
  file_name,machine_eval,christian,flech,brbo,wvd,sovor19
  img1.png,0.91,1,1,0,1,0
  hand_001.png,0.87,1,0,1,1,1

Result:
  same columns + a new "gt" column with the category (e.g., "indoor_wood", "hands")
"""
from __future__ import annotations


import argparse
import csv
import sys
from pathlib import Path


def build_filename_to_category_map(images_root: Path) -> dict[str, str]:
    """
    Walk the images_root and return a map: basename -> category (parent folder name).
    If duplicates exist, the first occurrence wins; later duplicates are logged to stderr.
    """
    mapping: dict[str, str] = {}
    for p in images_root.rglob("*"):
        if not p.is_file():
            continue
        fname = p.name  # basename with extension
        category = p.parent.name
        if fname not in mapping:
            mapping[fname] = category
        else:
            # Duplicate basename in another category; warn and keep the first
            print(
                f"[WARN] Duplicate filename '{fname}' also found in '{category}'. "
                f"Already mapped to '{mapping[fname]}'; keeping the first.",
                file=sys.stderr,
            )
    return mapping


def main():
    ap = argparse.ArgumentParser(
        description="Append a 'gt' category column to a CSV by looking up file locations (stdlib only)."
    )
    ap.add_argument(
        "--images-root",
        required=True,
        type=Path,
        help="Path to the directory where images are organized in category folders.",
    )
    ap.add_argument(
        "--csv-in",
        required=True,
        type=Path,
        help="Path to the input CSV with at least 'file_name' and 'machine_eval' columns.",
    )
    ap.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="Path to write the augmented CSV. Default: <csv-in stem>_with_gt.csv next to the input.",
    )
    ap.add_argument(
        "--not-found-value",
        type=str,
        default="",
        help="Value to put in 'gt' when a file_name is not found. Default: empty string.",
    )
    ap.add_argument(
        "--encoding",
        type=str,
        default="utf-8-sig",
        help="CSV encoding for input and output. Default: utf-8-sig (handles BOM).",
    )
    ap.add_argument(
        "--overwrite-existing-gt",
        action="store_true",
        help="If the input CSV already has a 'gt' column, overwrite it instead of creating a second one.",
    )
    args = ap.parse_args()

    images_root: Path = args.images_root
    csv_in: Path = args.csv_in
    csv_out: Path = (
        args.csv_out
        if args.csv_out is not None
        else csv_in.with_name(f"{csv_in.stem}_with_gt{csv_in.suffix}")
    )

    if not images_root.exists() or not images_root.is_dir():
        print(f"[ERROR] images-root does not exist or is not a directory: {images_root}", file=sys.stderr)
        sys.exit(1)
    if not csv_in.exists() or not csv_in.is_file():
        print(f"[ERROR] csv-in does not exist or is not a file: {csv_in}", file=sys.stderr)
        sys.exit(1)

    # Build lookup map from filenames to category (parent folder)
    print(f"[INFO] Scanning images under: {images_root}", file=sys.stderr)
    name_to_cat = build_filename_to_category_map(images_root)
    print(f"[INFO] Indexed {len(name_to_cat)} unique filenames.", file=sys.stderr)

    # Stream read -> write to avoid loading the whole CSV in memory
    try:
        with csv_in.open("r", encoding=args.encoding, newline="") as fin:
            reader = csv.DictReader(fin)
            if reader.fieldnames is None:
                print("[ERROR] Input CSV appears to have no header row.", file=sys.stderr)
                sys.exit(1)

            # Validate required columns
            required = {"file_name", "machine_eval"}
            missing = [c for c in required if c not in reader.fieldnames]
            if missing:
                print(f"[ERROR] Missing required column(s) in CSV: {', '.join(missing)}", file=sys.stderr)
                sys.exit(1)

            fieldnames = list(reader.fieldnames)
            if "gt" in fieldnames:
                if args.overwrite_existing_gt:
                    print("[INFO] Input CSV already has 'gt'; will overwrite it.", file=sys.stderr)
                else:
                    # Keep existing 'gt' and append a new 'gt_2' to avoid clobbering
                    print("[WARN] Input CSV already has 'gt'; will write to 'gt_2'. "
                          "Use --overwrite-existing-gt to overwrite.", file=sys.stderr)
                    out_gt_col = "gt_2"
                    fieldnames.append(out_gt_col)
                out_gt_col = "gt" if args.overwrite_existing_gt else "gt_2"
            else:
                out_gt_col = "gt"
                fieldnames.append(out_gt_col)

            with csv_out.open("w", encoding=args.encoding, newline="") as fout:
                writer = csv.DictWriter(fout, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
                writer.writeheader()

                total = 0
                not_found_count = 0
                for row in reader:
                    fname = row.get("file_name", "")
                    gt_value = name_to_cat.get(fname, args.not_found_value)
                    if gt_value == args.not_found_value:
                        not_found_count += 1
                    row[out_gt_col] = gt_value
                    writer.writerow(row)
                    total += 1

        print(f"[INFO] Wrote: {csv_out}", file=sys.stderr)
        print(f"[INFO] Rows processed: {total}", file=sys.stderr)
        print(f"[INFO] '{out_gt_col}' not found for: {not_found_count}", file=sys.stderr)
        if not_found_count:
            print("[HINT] If many are missing, check that 'file_name' values match the actual "
                  "basenames (including extensions) in the image folders.", file=sys.stderr)

    except Exception as e:
        print(f"[ERROR] Failed processing CSV: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
