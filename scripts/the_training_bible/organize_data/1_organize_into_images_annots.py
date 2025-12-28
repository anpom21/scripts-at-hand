from pathlib import Path
import shutil
import sys
import argparse

PNG_EXTS = {'.png'}  # case-insensitive check applied at runtime

def unique_destination(base: Path) -> Path:
    """
    Return a non-colliding path by appending _1, _2, ... before the suffix.
    """
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    parent = base.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1

def ensure_category_structure(category_dir: Path, fix: bool = False) -> dict:
    """
    Ensure 'images' and 'annots' subfolders exist in category_dir,
    and move any direct .png files from category_dir into 'images'.
    Returns a summary dict.
    """
    images_dir = category_dir / "images"
    annots_dir = category_dir / "annots"
    created_images = False
    created_annots = False

    if not images_dir.exists():
        created_images = True
        if fix:
            images_dir.mkdir(parents=False, exist_ok=True)

    if not annots_dir.exists():
        created_annots = True
        if fix:
            annots_dir.mkdir(parents=False, exist_ok=True)

    moved = 0
    skipped = 0
    conflicts = 0

    for entry in category_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in {ext.lower() for ext in PNG_EXTS}:
            skipped += 1
            continue

        dest = images_dir / entry.name
        if dest.exists():
            conflicts += 1
            dest = unique_destination(dest)

        if not fix:
            print(f"[DRY-RUN] Would move: {entry} -> {dest}")
        else:
            shutil.move(str(entry), str(dest))
        moved += 1

    return {
        "category": str(category_dir),
        "created_images": created_images,
        "created_annots": created_annots,
        "moved_pngs": moved,
        "skipped_non_png_files": skipped,
        "filename_conflicts_resolved": conflicts,
    }

def find_category_dirs(capture_root: Path) -> list:
    """
    Iterate the immediate subfolders of capture_root,
    and treat each as a category directory.
    """
    category_dirs = []
    for category in capture_root.iterdir():
        if category.is_dir():
            category_dirs.append(category)
    return category_dirs

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Normalize category folders to have 'images' and 'annots' and move .png files into 'images'."
    )
    parser.add_argument(
        "capture_path",
        type=Path,
        help="Path to the capture directory (containing category subfolders)"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="Make changes (create folders, move files). Without this flag, runs in dry-run mode."
    )
    parser.add_argument(
        "--ext",
        action="append",
        default=None,
        help="Additional image file extensions to include (e.g., --ext .jpg --ext .jpeg). Defaults to only .png"
    )

    args = parser.parse_args(argv)

    capture_root = args.capture_path.expanduser().resolve()
    if not capture_root.exists() or not capture_root.is_dir():
        print(f"Error: {capture_root} is not a directory.", file=sys.stderr)
        return 2

    # Allow optional extra extensions
    global PNG_EXTS
    if args.ext:
        # Normalize to lower-case and ensure leading dot
        extra = set()
        for e in args.ext:
            e = e.strip().lower()
            if not e.startswith("."):
                e = "." + e
            extra.add(e)
        PNG_EXTS = PNG_EXTS.union(extra)

    category_dirs = find_category_dirs(capture_root)
    if not category_dirs:
        print("No category directories found. Nothing to do.")
        return 0

    total = {
        "categories_processed": 0,
        "images_dirs_created": 0,
        "annots_dirs_created": 0,
        "pngs_moved": 0,
        "non_pngs_skipped": 0,
        "conflicts_resolved": 0,
    }

    for category_dir in category_dirs:
        summary = ensure_category_structure(category_dir, fix=args.fix)
        total["categories_processed"] += 1
        total["images_dirs_created"] += 1 if summary["created_images"] else 0
        total["annots_dirs_created"] += 1 if summary["created_annots"] else 0
        total["pngs_moved"] += summary["moved_pngs"]
        total["non_pngs_skipped"] += summary["skipped_non_png_files"]
        total["conflicts_resolved"] += summary["filename_conflicts_resolved"]

        print(
            f"- {summary['category']} | created(images={summary['created_images']}, annots={summary['created_annots']}), "
            f"moved_pngs={summary['moved_pngs']}, non_pngs_skipped={summary['skipped_non_png_files']}, "
            f"conflicts_resolved={summary['filename_conflicts_resolved']}"
        )

    print("\nSummary:")
    print(f"  Categories processed:     {total['categories_processed']}")
    print(f"  'images' created:         {total['images_dirs_created']}")
    print(f"  'annots' created:         {total['annots_dirs_created']}")
    print(f"  PNGs moved:               {total['pngs_moved']}")
    print(f"  Non-PNG files skipped:    {total['non_pngs_skipped']}")
    print(f"  Filename conflicts fixed: {total['conflicts_resolved']}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
