#!/usr/bin/env python3
"""Moves random paired image/annotation files into a sibling 'val' directory by matching normalized filename keys."""
"""
Split a subset of paired (image, annot) files from a dataset into a sibling 'val' directory.

Pairs are determined by matching keys derived from filenames:
- We strip known prefixes from image and annot stems (defaults: img_, annot_).
- If no known prefix is present, we also try removing everything up to the first underscore.
- After normalization, image and annot keys must match exactly.

Examples:
  img_gallant-stag_2025-10-15T10-03-23-644.png
  annot_gallant-stag_2025-10-15T10-03-23-644.json
  => key = "gallant-stag_2025-10-15T10-03-23-644"

Usage examples:
  python split_to_val.py /path/to/collection --count 50 --seed 42 --run
  python split_to_val.py /path/to/collection --counts wood=20 --counts metal=5 --run
  python split_to_val.py /path/to/collection --counts-file counts.json --run
    python split_to_val.py /path/to/collection --counts normal_wood=2198 --no-annot --run
    python split_to_val.py /path/to/collection --count 100 --unpaired --run
  python split_to_val.py /path/to/collection --count 5  # dry-run by default
  python split_to_val.py /path/to/collection --percent 20 --run  # move 20% of images per folder
  # Custom prefixes:
  python split_to_val.py /path/to/collection --img-prefix img_ --annot-prefix annot_ --run

Notes:
- Dry-run is the default mode (preview only). Use --run to actually move files.
- Files are MOVED (not copied).
- Only pairs whose normalized keys match are eligible.
- With --no-annot, only images without matching annotation keys are eligible and only images are moved.
- With --unpaired, all images are eligible regardless of whether a matching annotation exists. If a selected image has a matching annotation, that annotation is moved too.
- If requested count > available pairs, it moves all available pairs for that category.
"""

import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Set

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable

IMG_EXT_DEFAULT = ".png"
ANN_EXT_DEFAULT = ".json"

def parse_counts_arg(items: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"Invalid --counts entry '{item}'. Use category=count (e.g., wood=20).")
        cat, val = item.split("=", 1)
        cat = cat.strip()
        try:
            num = int(val)
        except ValueError:
            raise ValueError(f"Invalid count '{val}' for category '{cat}'. Must be an integer.")
        if num < 0:
            raise ValueError(f"Count must be non-negative for category '{cat}'.")
        out[cat] = num
    return out

def load_counts_file(path: Path) -> Dict[str, int]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("--counts-file must be a JSON object mapping category -> count")
    out: Dict[str, int] = {}
    for k, v in data.items():
        if not isinstance(v, int) or v < 0:
            raise ValueError(f"Count for category '{k}' must be a non-negative integer, got: {v}")
        out[str(k)] = v
    return out

def discover_categories(collection_dir: Path) -> List[Path]:
    return [p for p in collection_dir.iterdir() if p.is_dir()]

def strip_prefix(stem: str, prefixes: List[str]) -> str:
    """Strip the first matching prefix from stem. If none match, try removing up to the first underscore."""
    for pre in prefixes:
        if pre and stem.startswith(pre):
            return stem[len(pre):]
    # Fallback: remove text up to first underscore, if present
    if "_" in stem:
        return stem.split("_", 1)[1]
    return stem

def build_key_maps(
    dir_path: Path,
    ext: str,
    prefixes: List[str]
) -> Tuple[Dict[str, str], Set[str]]:
    """
    Returns:
      key_to_stem: mapping from normalized key -> original stem
      unmatched_stems: stems that exist but (by themselves) will only be unmatched if the other side lacks the same key
    """
    key_to_stem: Dict[str, str] = {}
    stems: Set[str] = set()
    for p in dir_path.glob(f"*{ext}"):
        if not p.is_file():
            continue
        stem = p.stem
        stems.add(stem)
        key = strip_prefix(stem, prefixes)
        # If key collision happens (multiple files map to same key), keep the first; warn upstream via duplicates detection if desired
        if key not in key_to_stem:
            key_to_stem[key] = stem
    return key_to_stem, stems

def paired_keys(
    images_dir: Path,
    annots_dir: Path,
    img_ext: str,
    ann_ext: str,
    img_prefixes: List[str],
    annot_prefixes: List[str],
) -> Tuple[List[str], List[str], List[str]]:
    """
    Returns (paired_keys, img_only_keys, annot_only_keys) based on normalized keys.
    """
    img_keys, img_stems = build_key_maps(images_dir, img_ext, img_prefixes)
    ann_keys, ann_stems = build_key_maps(annots_dir, ann_ext, annot_prefixes)

    paired = sorted(set(img_keys.keys()) & set(ann_keys.keys()))
    img_only = sorted(set(img_keys.keys()) - set(ann_keys.keys()))
    ann_only = sorted(set(ann_keys.keys()) - set(img_keys.keys()))
    return paired, img_only, ann_only

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def move_pair_by_key(
    key: str,
    img_keys: Dict[str, str],
    ann_keys: Dict[str, str],
    src_imgs: Path,
    src_ann: Path,
    dst_imgs: Path,
    dst_ann: Path,
    img_ext: str,
    ann_ext: str,
    dry_run: bool = False
):
    img_stem = img_keys[key]
    ann_stem = ann_keys[key]

    src_img = src_imgs / f"{img_stem}{img_ext}"
    src_jsn = src_ann / f"{ann_stem}{ann_ext}"
    dst_img = dst_imgs / src_img.name
    dst_jsn = dst_ann / src_jsn.name

    ensure_dir(dst_imgs)
    ensure_dir(dst_ann)

    if dry_run:
        print(f"[DRY-RUN] Move {src_img} -> {dst_img}")
        print(f"[DRY-RUN] Move {src_jsn} -> {dst_jsn}")
    else:
        shutil.move(str(src_img), str(dst_img))
        shutil.move(str(src_jsn), str(dst_jsn))

def move_image_by_key(
    key: str,
    img_keys: Dict[str, str],
    src_imgs: Path,
    dst_imgs: Path,
    img_ext: str,
    dry_run: bool = False,
):
    img_stem = img_keys[key]
    src_img = src_imgs / f"{img_stem}{img_ext}"
    dst_img = dst_imgs / src_img.name

    ensure_dir(dst_imgs)

    if dry_run:
        print(f"[DRY-RUN] Move {src_img} -> {dst_img}")
    else:
        shutil.move(str(src_img), str(dst_img))

def resolve_counts(
    categories: List[Path],
    default_count: int,
    overrides: Dict[str, int],
    file_counts: Dict[str, int],
    percent: float,
    no_annot: bool,
    unpaired: bool,
    images_dir_name: str,
    annots_dir_name: str,
    img_ext: str,
    ann_ext: str,
    img_prefixes: List[str],
    annot_prefixes: List[str],
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for cat_path in categories:
        cat = cat_path.name
        if cat in file_counts:
            counts[cat] = file_counts[cat]
        elif cat in overrides:
            counts[cat] = overrides[cat]
        elif percent > 0:
            # Calculate count based on percentage of available items in the chosen mode
            images_dir = cat_path / images_dir_name
            annots_dir = cat_path / annots_dir_name
            if images_dir.exists():
                img_keys_map, _ = build_key_maps(images_dir, img_ext, img_prefixes)
                ann_keys_map: Dict[str, str] = {}
                if annots_dir.exists():
                    ann_keys_map, _ = build_key_maps(annots_dir, ann_ext, annot_prefixes)

                if unpaired:
                    available = set(img_keys_map.keys())
                elif no_annot:
                    available = set(img_keys_map.keys()) - set(ann_keys_map.keys())
                else:
                    available = set(img_keys_map.keys()) & set(ann_keys_map.keys())

                counts[cat] = max(1, int(len(available) * percent / 100.0))
            else:
                counts[cat] = 0
        else:
            counts[cat] = max(0, default_count)
    return counts

def main():
    parser = argparse.ArgumentParser(description="Move random paired image/annot files into a sibling 'val' directory, pairing by normalized filename keys.")
    parser.add_argument("collection", type=str, help="Path to the collection directory (containing category folders).")
    parser.add_argument("--count", type=int, default=0, help="Default number of pairs to move per category (overridden by --counts/--counts-file/--percent).")
    parser.add_argument("--percent", type=float, default=0.0, help="Percentage of pairs to move per category (e.g., 20 for 20%%). Overridden by --counts/--counts-file.")
    parser.add_argument("--counts", action="append", default=[],
                        help="Per-category override like 'wood=20'. May be provided multiple times.")
    parser.add_argument("--counts-file", type=str, default=None,
                        help="Path to a JSON file with a mapping of { category: count }.")
    parser.add_argument("--no-annot", action="store_true",
                        help="Move only images that do not have a matching annotation file. In this mode, only images are moved.")
    parser.add_argument("--unpaired", action="store_true",
                        help="Ignore pairing for selection and sample from all images. If a selected image has a matching annotation, that annotation is also moved.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    parser.add_argument("--run", action="store_true", help="Actually move files. Without this flag, only a dry-run preview is shown.")
    parser.add_argument("--img-ext", type=str, default=IMG_EXT_DEFAULT, help="Image file extension (default: .png).")
    parser.add_argument("--ann-ext", type=str, default=ANN_EXT_DEFAULT, help="Annot file extension (default: .json).")
    parser.add_argument("--img-prefix", action="append", default=["img_"],
                        help="Prefix to strip from image stems (repeatable). Default: img_")
    parser.add_argument("--annot-prefix", action="append", default=["annot_"],
                        help="Prefix to strip from annot stems (repeatable). Default: annot_")
    args = parser.parse_args()

    collection_dir = Path(args.collection).resolve()
    if not collection_dir.exists() or not collection_dir.is_dir():
        print(f"ERROR: '{collection_dir}' does not exist or is not a directory.", file=sys.stderr)
        sys.exit(1)

    parent_dir = collection_dir.parent
    val_dir = parent_dir / "val"

    # Dry-run is default; only run if --run is specified
    dry_run = not args.run

    # Validate percent if provided
    if args.percent < 0 or args.percent > 100:
        print(f"ERROR: --percent must be between 0 and 100, got {args.percent}", file=sys.stderr)
        sys.exit(2)

    if args.no_annot and args.unpaired:
        print("ERROR: --no-annot and --unpaired cannot be used together.", file=sys.stderr)
        sys.exit(2)

    if args.seed is not None:
        random.seed(args.seed)

    try:
        overrides = parse_counts_arg(args.counts)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(3)

    file_counts: Dict[str, int] = {}
    if args.counts_file:
        try:
            file_counts = load_counts_file(Path(args.counts_file))
        except Exception as e:
            print(f"ERROR reading --counts-file: {e}", file=sys.stderr)
            sys.exit(4)

    categories = discover_categories(collection_dir)
    if not categories:
        print(f"WARNING: No category directories found in {collection_dir}. Nothing to do.")
        sys.exit(0)

    counts_map = resolve_counts(
        categories,
        args.count,
        overrides,
        file_counts,
        args.percent,
        args.no_annot,
        args.unpaired,
        "images",
        "annots",
        args.img_ext,
        args.ann_ext,
        args.img_prefix,
        args.annot_prefix,
    )

    print(f"Collection: {collection_dir}")
    print(f"Target val dir: {val_dir}")
    if args.unpaired:
        print("Mode: unpaired (ignoring pair status for selection; moving matching annots when present)")
    elif args.no_annot:
        print("Mode: no-annot (moving only images without matching annotations)")
    if dry_run:
        print("[DRY-RUN] No changes will be made. Use --run to actually move files.")
    else:
        print("[RUN MODE] Files will be moved.")

    grand_total_requested = 0
    grand_total_moved = 0
    moved_per_category: Dict[str, int] = {}

    for cat_path in sorted(categories, key=lambda p: p.name):
        cat = cat_path.name
        images_dir = cat_path / "images"
        annots_dir = cat_path / "annots"

        if not images_dir.exists():
            print(f"\n[SKIP] {cat}: missing 'images' directory.")
            continue
        if (not args.no_annot) and (not args.unpaired) and (not annots_dir.exists()):
            print(f"\n[SKIP] {cat}: missing 'annots' directory.")
            continue

        # Build key maps for images and annots
        img_keys_map, _ = build_key_maps(images_dir, args.img_ext, args.img_prefix)
        ann_keys_map: Dict[str, str] = {}
        if annots_dir.exists():
            ann_keys_map, _ = build_key_maps(annots_dir, args.ann_ext, args.annot_prefix)

        paired = sorted(set(img_keys_map.keys()) & set(ann_keys_map.keys()))
        img_only = sorted(set(img_keys_map.keys()) - set(ann_keys_map.keys()))
        ann_only = sorted(set(ann_keys_map.keys()) - set(img_keys_map.keys()))

        req = counts_map.get(cat, 0)
        grand_total_requested += req

        if img_only:
            print(f"\n[WARN] {cat}: {len(img_only)} image key(s) without matching annot key: first few -> {img_only[:5]}")
        if ann_only:
            print(f"[WARN] {cat}: {len(ann_only)} annot key(s) without matching image key: first few -> {ann_only[:5]}")

        if args.unpaired:
            selectable = sorted(img_keys_map.keys())
            empty_msg = "no images found"
            do_label = "images"
        elif args.no_annot:
            selectable = img_only
            empty_msg = "no image-only keys found"
            do_label = "images without annotations"
        else:
            selectable = paired
            empty_msg = "no paired keys found"
            do_label = "pairs"

        if not selectable:
            print(f"[INFO] {cat}: {empty_msg}. Requested {req}, will move 0.")
            continue

        k = min(req, len(selectable))
        if k <= 0:
            print(f"\n[INFO] {cat}: requested {req}, skipping.")
            continue

        selected_keys = random.sample(selectable, k)
        print(f"\n[DO] {cat}: requested {req}, available {do_label} {len(selectable)}, selecting {k}.")

        dst_imgs = val_dir / cat / "images"
        dst_ann = val_dir / cat / "annots"

        moved = 0
        for key in tqdm(selected_keys, desc=f"{cat}", unit="item"):
            try:
                if args.no_annot:
                    move_image_by_key(
                        key,
                        img_keys_map,
                        images_dir,
                        dst_imgs,
                        args.img_ext,
                        dry_run=dry_run,
                    )
                elif args.unpaired:
                    if key in ann_keys_map:
                        move_pair_by_key(
                            key,
                            img_keys_map,
                            ann_keys_map,
                            images_dir,
                            annots_dir,
                            dst_imgs,
                            dst_ann,
                            args.img_ext,
                            args.ann_ext,
                            dry_run=dry_run,
                        )
                    else:
                        move_image_by_key(
                            key,
                            img_keys_map,
                            images_dir,
                            dst_imgs,
                            args.img_ext,
                            dry_run=dry_run,
                        )
                else:
                    move_pair_by_key(
                        key,
                        img_keys_map,
                        ann_keys_map,
                        images_dir,
                        annots_dir,
                        dst_imgs,
                        dst_ann,
                        args.img_ext,
                        args.ann_ext,
                        dry_run=dry_run,
                    )
                moved += 1
            except Exception as e:
                print(f"[ERROR] Failed to move item for key '{key}' in category '{cat}': {e}", file=sys.stderr)

        grand_total_moved += moved
        moved_per_category[cat] = moved
        print(f"[DONE] {cat}: moved {moved} item(s).")

    print("\n=== Summary ===")
    if args.unpaired:
        summary_label = "images (unpaired mode)"
    elif args.no_annot:
        summary_label = "images (no-annot mode)"
    else:
        summary_label = "pairs"
    print(f"Requested total {summary_label}: {grand_total_requested}")
    print(f"Moved total {summary_label}:     {grand_total_moved}")
    if moved_per_category:
        print("\nItems moved per category:")
        for cat in sorted(moved_per_category.keys()):
            count = moved_per_category[cat]
            if count > 0:
                print(f"  {cat}: {count}")
    if dry_run:
        print("\n[DRY-RUN] No files were moved. Use --run to actually move files.")
    else:
        print("\n[RUN MODE] Files were actually moved.")

if __name__ == "__main__":
    main()
