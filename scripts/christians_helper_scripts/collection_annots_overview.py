#!/usr/bin/env python3
import argparse
import csv
import re
from pathlib import Path
from collections import Counter, defaultdict

IMG_RE = re.compile(r'^img_(.+)\.png$', re.IGNORECASE)
ANN_RE = re.compile(r'^annot_(.+)\.json$', re.IGNORECASE)

def extract_key(filename: str, kind: str):
    name = Path(filename).name
    m = IMG_RE.match(name) if kind == 'img' else ANN_RE.match(name)
    return m.group(1) if m else None

def deduce_category_dir(p: Path) -> Path:
    """
    Given a file path p (an image or annot), return the category directory.
      - if file is under .../<category>/(images|annots)/file -> category is parent of that
      - else if file is directly under .../<category>/file   -> category is its parent
    """
    parent = p.parent
    if parent.name.lower() in ('images', 'annots'):
        return parent.parent
    return parent

def scan(root: Path):
    """
    Scans root and returns:
      - totals: dict with overall counts & key sets
      - per_cat: dict[rel_category_path] -> stats dict
    """
    image_count = 0
    annot_count = 0
    image_keys = set()
    annot_keys = set()
    image_key_counts = Counter()
    annot_key_counts = Counter()

    per_cat = defaultdict(lambda: {
        'image_count': 0,
        'annot_count': 0,
        'image_keys': set(),
        'annot_keys': set(),
        'image_key_counts': Counter(),
        'annot_key_counts': Counter(),
    })

    root = root.resolve()

    for p in root.rglob('*'):
        if not p.is_file():
            continue

        name = p.name
        is_img = name.lower().startswith('img_') and name.lower().endswith('.png')
        is_annot = name.lower().startswith('annot_') and name.lower().endswith('.json')
        if not (is_img or is_annot):
            continue

        cat_dir = deduce_category_dir(p)
        try:
            cat_label = str(cat_dir.relative_to(root))
        except ValueError:
            cat_label = str(cat_dir)

        if is_img:
            key = extract_key(name, 'img')
            if key:
                image_count += 1
                image_keys.add(key)
                image_key_counts[key] += 1

                per_cat[cat_label]['image_count'] += 1
                per_cat[cat_label]['image_keys'].add(key)
                per_cat[cat_label]['image_key_counts'][key] += 1
            continue

        if is_annot:
            key = extract_key(name, 'annot')
            if key:
                annot_count += 1
                annot_keys.add(key)
                annot_key_counts[key] += 1

                per_cat[cat_label]['annot_count'] += 1
                per_cat[cat_label]['annot_keys'].add(key)
                per_cat[cat_label]['annot_key_counts'][key] += 1
            continue

    totals = {
        'image_count': image_count,
        'annot_count': annot_count,
        'image_keys': image_keys,
        'annot_keys': annot_keys,
        'image_key_counts': image_key_counts,
        'annot_key_counts': annot_key_counts,
    }
    return totals, per_cat

def print_report(root: Path, totals, per_cat, list_missing: bool):
    image_keys = totals['image_keys']
    annot_keys = totals['annot_keys']
    missing_annot_for_images = sorted(image_keys - annot_keys)
    missing_images_for_annots = sorted(annot_keys - image_keys)

    print("=== Dataset Pairing Summary (Overall) ===")
    print(f"Root: {root}")
    print(f"Total image files (img_*.png): {totals['image_count']}")
    print(f"Total annot files (annot_*.json): {totals['annot_count']}")
    print(f"Image keys without corresponding annot: {len(missing_annot_for_images)}")
    print(f"Annot keys without corresponding image: {len(missing_images_for_annots)}")

    if list_missing:
        if missing_annot_for_images:
            print("\n-- [OVERALL] Image keys missing annot --")
            for k in missing_annot_for_images:
                print(k)
        if missing_images_for_annots:
            print("\n-- [OVERALL] Annot keys missing image --")
            for k in missing_images_for_annots:
                print(k)

    print("\n=== Per-Category Details ===")
    if not per_cat:
        print("(No categories found)")
        return

    for cat, stats in sorted(per_cat.items()):
        ik = stats['image_keys']
        ak = stats['annot_keys']
        miss_ann = sorted(ik - ak)
        miss_img = sorted(ak - ik)
        print(f"\n[{cat}]")
        print(f"  Image files: {stats['image_count']}  |  Annot files: {stats['annot_count']}")
        print(f"  Unique image keys: {len(ik)}        |  Unique annot keys: {len(ak)}")
        print(f"  Missing annots for images: {len(miss_ann)}")
        print(f"  Missing images for annots: {len(miss_img)}")

        if list_missing:
            if miss_ann:
                print("    - Image keys missing annot:")
                for k in miss_ann:
                    print(f"      {k}")
            if miss_img:
                print("    - Annot keys missing image:")
                for k in miss_img:
                    print(f"      {k}")

def write_csv(csv_path: Path, root: Path, totals, per_cat):
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
        writer.writerow(headers)

        for cat, stats in sorted(per_cat.items()):
            ik = stats['image_keys']
            ak = stats['annot_keys']
            miss_ann = len(ik - ak)
            miss_img = len(ak - ik)
            writer.writerow([
                cat,
                stats['image_count'],
                stats['annot_count'],
                len(ik),
                len(ak),
                miss_ann,
                miss_img,
            ])

        overall_miss_ann = len(totals['image_keys'] - totals['annot_keys'])
        overall_miss_img = len(totals['annot_keys'] - totals['image_keys'])
        writer.writerow([
            "__TOTALS__",
            totals['image_count'],
            totals['annot_count'],
            len(totals['image_keys']),
            len(totals['annot_keys']),
            overall_miss_ann,
            overall_miss_img,
        ])

def safe_cat_filename(cat_label: str) -> str:
    """
    Make a safe filename segment from a category label (which may contain slashes).
    Example: 'wood/impregnated' -> 'wood__impregnated'
    """
    return cat_label.replace('/', '__').replace('\\', '__')

def write_missing_annots_texts(output_dir: Path, per_cat):
    """
    For each category, write a text file listing filenames of missing annot files.
    Only filenames, one per line; no headers or extra text.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for cat, stats in per_cat.items():
        miss_keys = sorted(stats['image_keys'] - stats['annot_keys'])
        if not miss_keys:
            continue
        fname = f"{safe_cat_filename(cat)}_missing_annots.txt"
        out_path = output_dir / fname
        with open(out_path, 'w') as f:
            for k in miss_keys:
                f.write(f"annot_{k}.json\n")

def main():
    parser = argparse.ArgumentParser(
        description="Check image/annot pairing in a Collections directory (with per-category details)."
    )
    parser.add_argument("collections_dir", type=str,
                        help="Path to the Collections root or a subfolder")
    parser.add_argument("--list-missing", dest="list_missing", action="store_true",
                        help="List missing keys for overall and each category")
    parser.add_argument("--csv", type=str, default=None,
                        help="Optional path to write per-category summary as CSV")
    parser.add_argument("--missing-annots-dir", type=str, default=None,
                        help="Directory to write per-category text files of missing annot filenames")
    args = parser.parse_args()

    root = Path(args.collections_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"Error: '{root}' is not a directory.")
        raise SystemExit(1)

    totals, per_cat = scan(root)
    print_report(root, totals, per_cat, args.list_missing)

    if args.csv:
        csv_path = Path(args.csv).expanduser().resolve()
        write_csv(csv_path, root, totals, per_cat)
        print(f"\nCSV summary written to: {csv_path}")

    if args.missing_annots_dir:
        out_dir = Path(args.missing_annots_dir).expanduser().resolve()
        write_missing_annots_texts(out_dir, per_cat)
        print(f"Per-category missing annot filename lists written under: {out_dir}")

if __name__ == "__main__":
    main()
