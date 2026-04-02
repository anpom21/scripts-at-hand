#!/usr/bin/env python3
"""Aggregates image/annotation pairing statistics by category name across capture directories with optional CSV output."""
import argparse
import csv
import re
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

IMG_RE = re.compile(r'^img_(.+)\.png$', re.IGNORECASE)
ANN_RE = re.compile(r'^annot_(.+)\.json$', re.IGNORECASE)
TIMESTAMP_RE = re.compile(r'(\d{4}-\d{2}-\d{2})T[\d-]+', re.IGNORECASE)

def extract_key(filename: str, kind: str):
    name = Path(filename).name
    m = IMG_RE.match(name) if kind == 'img' else ANN_RE.match(name)
    print(f"m: {m} for filename: {filename} with kind: {kind}")
    if not m:
        print(f"Warning: Filename '{filename}' does not match expected pattern for {kind}.")
        m = re.match(r'^(.+)\.(png|json)$', name, re.IGNORECASE)
        if not m:
            #print(f"Warning: Filename '{filename}' does not match fallback pattern either.")
            return None
    return m.group(1) if m else None

def deduce_category_dir(p: Path) -> Path:
    parent = p.parent
    if parent.name.lower() in ('images', 'annots'):
        return parent.parent
    return parent

def scan_aggregate_by_category(root: Path):
    per_cat_name = defaultdict(lambda: {
        'image_count': 0,
        'annot_count': 0,
        'image_keys': set(),
        'annot_keys': set(),
        'image_key_counts': Counter(),
        'annot_key_counts': Counter(),
    })

    overall = {
        'image_count': 0,
        'annot_count': 0,
        'image_keys': set(),
        'annot_keys': set(),
        'image_key_counts': Counter(),
        'annot_key_counts': Counter(),
        'earliest_date': None,
        'latest_date': None,
    }

    root = root.resolve()

    for p in root.rglob('*'):
        if not p.is_file():
            continue
        name = p.name
        is_img = name.lower().startswith('img_') and name.lower().endswith('.png')
        is_annot = name.lower().startswith('annot_') and name.lower().endswith('.json')
        if not (is_img or is_annot):
            is_img =  name.lower().endswith('.png')
            is_annot = name.lower().endswith('.json')
            if not (is_img or is_annot):
                print(f"Skipping file that is not recognized as image or annot: {p}")
                continue
            

        cat_dir = deduce_category_dir(p)
        cat_name = cat_dir.name
        stats = per_cat_name[cat_name]

        if is_img:
            key = extract_key(name, 'img')
            if key:
                stats['image_count'] += 1
                stats['image_keys'].add(key)
                stats['image_key_counts'][key] += 1

                overall['image_count'] += 1
                overall['image_keys'].add(key)
                overall['image_key_counts'][key] += 1
                
                # Extract and track timestamp
                timestamp_match = TIMESTAMP_RE.search(name)
                if timestamp_match:
                    date_str = timestamp_match.group(1)
                    if overall['earliest_date'] is None or date_str < overall['earliest_date']:
                        overall['earliest_date'] = date_str
                    if overall['latest_date'] is None or date_str > overall['latest_date']:
                        overall['latest_date'] = date_str
            continue

        if is_annot:
            key = extract_key(name, 'annot')
            if key:
                stats['annot_count'] += 1
                stats['annot_keys'].add(key)
                stats['annot_key_counts'][key] += 1

                overall['annot_count'] += 1
                overall['annot_keys'].add(key)
                overall['annot_key_counts'][key] += 1
            continue

    return per_cat_name, overall

def print_aggregate_report(root: Path, per_cat_name, overall):
    today_str = datetime.now().astimezone().date().isoformat()

    overall_miss_ann = len(overall['image_keys'] - overall['annot_keys'])
    overall_miss_img = len(overall['annot_keys'] - overall['image_keys'])

    print(f"=== Aggregated Dataset Pairing by Category Name ===")
    print(f"Date: {today_str}")
    print(f"Root: {root}")
    
    # Display earliest and latest image dates
    if overall.get('earliest_date'):
        print(f"Earliest image: {overall['earliest_date']}")
    if overall.get('latest_date'):
        print(f"Latest image: {overall['latest_date']}")
    print()

    # Prepare rows
    headers = [
        "Category",
        "Image files",
        "Annot files",
        "Unique image keys",
        "Unique annot keys",
        "Missing annots",
        "Missing images",
    ]
    rows = []

    for cat in sorted(per_cat_name.keys(), key=lambda s: s.lower()):
        s = per_cat_name[cat]
        miss_ann = len(s['image_keys'] - s['annot_keys'])
        miss_img = len(s['annot_keys'] - s['image_keys'])
        rows.append([
            cat,
            s['image_count'],
            s['annot_count'],
            len(s['image_keys']),
            len(s['annot_keys']),
            miss_ann,
            miss_img,
        ])

    # Add overall row
    rows.append([
        "__TOTALS__",
        overall['image_count'],
        overall['annot_count'],
        len(overall['image_keys']),
        len(overall['annot_keys']),
        overall_miss_ann,
        overall_miss_img,
    ])

    # Calculate column widths
    cols = list(zip(headers, *rows))
    col_widths = [max(len(str(item)) for item in col) for col in cols]

    # Print header
    header_line = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_line)
    print("-" * len(header_line))

    # Print rows
    for row in rows:
        print("  ".join(str(val).ljust(w) for val, w in zip(row, col_widths)))

def write_csv(csv_path: Path, per_cat_name, overall):
    headers = [
        "category",
        "image_files",
        "annot_files",
        "unique_image_keys",
        "unique_annot_keys",
        "missing_annots_for_images",
        "missing_images_for_annots",
    ]

    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["date", datetime.now().astimezone().date().isoformat()])
        writer.writerow(headers)

        for cat in sorted(per_cat_name.keys(), key=lambda s: s.lower()):
            s = per_cat_name[cat]
            miss_ann = len(s['image_keys'] - s['annot_keys'])
            miss_img = len(s['annot_keys'] - s['image_keys'])
            writer.writerow([
                cat,
                s['image_count'],
                s['annot_count'],
                len(s['image_keys']),
                len(s['annot_keys']),
                miss_ann,
                miss_img,
            ])

        overall_miss_ann = len(overall['image_keys'] - overall['annot_keys'])
        overall_miss_img = len(overall['annot_keys'] - overall['image_keys'])
        writer.writerow([
            "__TOTALS__",
            overall['image_count'],
            overall['annot_count'],
            len(overall['image_keys']),
            len(overall['annot_keys']),
            overall_miss_ann,
            overall_miss_img,
        ])

def main():
    parser = argparse.ArgumentParser(
        description="Aggregate image/annot pairing by CATEGORY NAME across all folders."
    )
    parser.add_argument("collections_dir", type=str,
                        help="Path to the Collections root or a subfolder")
    parser.add_argument("--csv", type=str, default=None,
                        help="Optional path to write aggregated per-category CSV")
    args = parser.parse_args()

    root = Path(args.collections_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"Error: '{root}' is not a directory.")
        raise SystemExit(1)

    per_cat_name, overall = scan_aggregate_by_category(root)
    print_aggregate_report(root, per_cat_name, overall)

    if args.csv:
        csv_path = Path(args.csv).expanduser().resolve()
        write_csv(csv_path, per_cat_name, overall)
        print(f"\nCSV written to: {csv_path}")

if __name__ == "__main__":
    main()
