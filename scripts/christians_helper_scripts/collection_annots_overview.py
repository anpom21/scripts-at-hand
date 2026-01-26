#!/usr/bin/env python3
"""Analyzes image/annotation pairing in collections, identifies missing pairs per category, and generates summary reports."""
import argparse
import csv
import re
import shutil
from pathlib import Path
from collections import Counter, defaultdict

# ANSI color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
RESET = '\033[0m'

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

def find_matches_between_categories(per_cat):
    """
    Find samples that have both images and annotations but in different categories.
    Returns a list of tuples: (key, annot_category, image_category)
    """
    matches = []
    
    # Build mappings: key -> list of categories where it appears
    key_to_annot_cats = defaultdict(list)
    key_to_image_cats = defaultdict(list)
    
    for cat, stats in per_cat.items():
        for key in stats['annot_keys']:
            key_to_annot_cats[key].append(cat)
        for key in stats['image_keys']:
            key_to_image_cats[key].append(cat)
    
    # Find keys that appear in different categories for annots and images
    all_keys = set(key_to_annot_cats.keys()) | set(key_to_image_cats.keys())
    
    for key in sorted(all_keys):
        annot_cats = set(key_to_annot_cats.get(key, []))
        image_cats = set(key_to_image_cats.get(key, []))
        
        # Find categories where annot exists but image doesn't, and vice versa
        for annot_cat in annot_cats:
            for image_cat in image_cats:
                if annot_cat != image_cat:
                    matches.append((key, annot_cat, image_cat))
    
    return matches

def print_matches(matches):
    """
    Print matches in the specified format with colors.
    """
    if not matches:
        print("\n=== No Mismatched Samples Found ===")
        return
    
    print("\n=== Mismatched Samples Between Categories ===")
    print(f"Found {len(matches)} mismatch(es):\n")
    
    for key, annot_cat, image_cat in matches:
        print(f"Sample: {GREEN}{key}{RESET}")
        print(f"Annot: {YELLOW}{annot_cat}{RESET}")
        print(f"Image: {YELLOW}{image_cat}{RESET}")
        print()

def move_files(root: Path, matches, move_type: str):
    """
    Move files based on the move_type:
    - 'image': Move all annots to the matching image folder
    - 'annot': Move all images to the matching annot folder
    
    Returns a summary dict with moved files count.
    """
    moved_count = 0
    errors = []
    
    for key, annot_cat, image_cat in matches:
        if move_type == 'image':
            # Move annots to image folder
            src_category = annot_cat
            dest_category = image_cat
            file_pattern = f"annot_{key}.json"
        else:  # move_type == 'annot'
            # Move images to annot folder
            src_category = image_cat
            dest_category = annot_cat
            file_pattern = f"img_{key}.png"
        
        # Find source file
        src_base = root / src_category
        src_files = list(src_base.rglob(file_pattern))
        
        if not src_files:
            errors.append(f"Could not find {file_pattern} in {src_category}")
            continue
        
        # Find destination directory (prefer images/annots subdirs if they exist)
        dest_base = root / dest_category
        
        for src_file in src_files:
            # Determine destination path
            if move_type == 'image':
                # Moving annot file
                annots_dir = dest_base / 'annots'
                if annots_dir.exists() and annots_dir.is_dir():
                    dest_file = annots_dir / file_pattern
                else:
                    dest_file = dest_base / file_pattern
            else:
                # Moving image file
                images_dir = dest_base / 'images'
                if images_dir.exists() and images_dir.is_dir():
                    dest_file = images_dir / file_pattern
                else:
                    dest_file = dest_base / file_pattern
            
            # Create destination directory if needed
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Move file
            try:
                shutil.move(str(src_file), str(dest_file))
                moved_count += 1
                print(f"Moved: {src_file} -> {dest_file}")
            except Exception as e:
                errors.append(f"Error moving {src_file}: {e}")
    
    return {'moved_count': moved_count, 'errors': errors}

def print_move_summary(summary, move_type):
    """
    Print a summary of the move operation.
    """
    print("\n=== Move Summary ===")
    print(f"Move type: {'Annotations to Image folders' if move_type == 'image' else 'Images to Annotation folders'}")
    print(f"Files moved: {summary['moved_count']}")
    
    if summary['errors']:
        print(f"\nErrors encountered: {len(summary['errors'])}")
        for error in summary['errors']:
            print(f"  - {error}")
    else:
        print("No errors encountered.")

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
    parser.add_argument("-m", "--move", type=str, choices=['annot', 'image'], default=None,
                        help="Move files to match: 'image' moves annots to image folders, 'annot' moves images to annot folders")
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
    
    # Find and display matches between categories
    matches = find_matches_between_categories(per_cat)
    print_matches(matches)
    
    # Handle move operation if requested
    if args.move and matches:
        print(f"\nProceeding to move files (move type: {args.move})...")
        summary = move_files(root, matches, args.move)
        print_move_summary(summary, args.move)
    elif args.move and not matches:
        print("\nNo mismatches found, nothing to move.")
    else:
        print(f"\n{YELLOW}Consider moving files to resolve mismatches using the --move option.{RESET}")

if __name__ == "__main__":
    main()
