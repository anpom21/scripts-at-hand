"""
Merge annotation files listed in a tags.txt file to a destination directory.

The script reads paths from a text file (like tags.txt) and copies the annotation
files to the corresponding location in the destination directory.

Example path in tags.txt:
./2025-04-28_2025-07-16_vejen_employee_sorted/wood_wool_board/annots/annot_majestic-horse_2025-06-06T14-33-03-535.json

This will be copied to:
<destination>/2025-04-28_2025-07-16_vejen_employee_sorted/wood_wool_board/annots/annot_majestic-horse_2025-06-06T14-33-03-535.json

Usage:
    python merge_annots_from_tags.py tags.txt /path/to/destination
    python merge_annots_from_tags.py tags.txt /path/to/destination --dry-run
    python merge_annots_from_tags.py tags.txt /path/to/destination --force
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import List, Tuple, Optional

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


def parse_annotation_path(line: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Parse a line from tags.txt and extract components.
    
    Returns:
        (capture_folder, category_folder, annots_subfolder, filename) or None if invalid
    
    Example:
        "./2025-04-28_vejen/wood_wool_board/annots/annot_xxx.json"
        -> ("2025-04-28_vejen", "wood_wool_board", "annots", "annot_xxx.json")
    """
    line = line.strip()
    if not line or not line.endswith('.json'):
        return None
    
    # Remove leading "./" if present
    if line.startswith('./'):
        line = line[2:]
    
    parts = line.split('/')
    if len(parts) < 3:
        return None
    
    capture_folder = parts[0]
    category_folder = parts[1]
    
    # Check if there's an annots subfolder or if json is directly in category
    if len(parts) == 4 and parts[2] == 'annots':
        annots_subfolder = 'annots'
        filename = parts[3]
    elif len(parts) == 3:
        annots_subfolder = ''
        filename = parts[2]
    else:
        return None
    
    return (capture_folder, category_folder, annots_subfolder, filename)


def read_tags_file(tags_file: Path) -> List[str]:
    """Read all lines from the tags file."""
    try:
        with tags_file.open('r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"{RED}ERROR reading {tags_file}: {e}{RESET}", file=sys.stderr)
        return []


def find_paired_image(annot_path: Path, source_dir: Path, capture_folder: str, category_folder: str, verbose: bool = False) -> Optional[Path]:
    """
    Find the image file that corresponds to an annotation file.
    
    Looks in:
    - <capture>/<category>/images/<image_name>
    - <capture>/<category>/<image_name>
    
    Handles both annot_xxx.json -> img_xxx.ext and annot_xxx.json -> xxx.ext patterns
    """
    # Extract base name from annotation (remove annot_ prefix and .json extension)
    annot_name = annot_path.stem
    if annot_name.startswith('annot_'):
        base_without_prefix = annot_name[6:]  # Remove 'annot_' prefix
    else:
        base_without_prefix = annot_name
    
    # Try both with img_ prefix and without
    image_basenames = [
        f"img_{base_without_prefix}",  # annot_xxx.json -> img_xxx.ext
        base_without_prefix,            # annot_xxx.json -> xxx.ext
    ]
    
    # Common image extensions
    extensions = ['.jpg', '.jpeg', '.png', '.JPG', '.JPEG', '.PNG']
    
    searched_paths = []
    
    # Check in images/ subfolder
    images_dir = source_dir / capture_folder / category_folder / 'images'
    if images_dir.exists():
        for image_base in image_basenames:
            for ext in extensions:
                image_path = images_dir / f"{image_base}{ext}"
                searched_paths.append(str(image_path))
                if image_path.exists():
                    return image_path
    
    # Check in category root
    category_dir = source_dir / capture_folder / category_folder
    if category_dir.exists():
        for image_base in image_basenames:
            for ext in extensions:
                image_path = category_dir / f"{image_base}{ext}"
                searched_paths.append(str(image_path))
                if image_path.exists():
                    return image_path
    
    if verbose:
        print(f"{YELLOW}  Searched for image (showing first 5 paths):{RESET}")
        for path in searched_paths[:5]:
            print(f"{YELLOW}    - {path}{RESET}")
    
    return None


def merge_annotations(
    tags_file: Path,
    source_dir: Path,
    destination_dir: Path,
    dry_run: bool = False,
    force: bool = False
) -> int:
    """
    Merge annotation files from tags.txt to destination directory.
    
    Args:
        tags_file: Path to the tags.txt file
        source_dir: Source directory containing the files (usually same as tags.txt location)
        destination_dir: Destination directory where files should be copied
        dry_run: If True, only show what would be done without copying
        force: If True, copy images and annots to "forced_moves" folder when capture folder missing
    
    Returns:
        0 on success, non-zero on error
    """
    lines = read_tags_file(tags_file)
    if not lines:
        print(f"{YELLOW}No lines found in {tags_file}{RESET}")
        return 1
    
    total_files = 0
    copied_files = 0
    skipped_files = 0
    forced_moves = 0
    missing_annots_folders = set()
    errors = []
    forced_moves_dir = destination_dir / "forced_moves" if force else None
    
    for line in lines:
        parsed = parse_annotation_path(line)
        if not parsed:
            print(f"{YELLOW}[SKIP] Invalid path format: {line}{RESET}")
            skipped_files += 1
            continue
        
        capture_folder, category_folder, annots_subfolder, filename = parsed
        total_files += 1
        
        # Build source path
        if annots_subfolder:
            source_path = source_dir / capture_folder / category_folder / annots_subfolder / filename
        else:
            source_path = source_dir / capture_folder / category_folder / filename
        
        # Check if source file exists
        if not source_path.exists():
            errors.append(f"Source file not found: {source_path}")
            skipped_files += 1
            continue
        
        # Build destination path
        dest_capture_dir = destination_dir / capture_folder
        use_forced_moves = False
        
        if not dest_capture_dir.exists():
            if force:
                # Use forced_moves folder instead
                use_forced_moves = True
                dest_capture_dir = forced_moves_dir
            else:
                warning_msg = f"Capture folder does not exist at destination: {dest_capture_dir.absolute()}"
                missing_annots_folders.add(warning_msg)
                skipped_files += 1
                continue
        
        if annots_subfolder:
            dest_annots_dir = dest_capture_dir / category_folder / annots_subfolder
        else:
            dest_annots_dir = dest_capture_dir / category_folder
        
        # Check if destination annots directory exists
        if not dest_annots_dir.exists():
            if use_forced_moves:
                # Create the directory structure in forced_moves
                if not dry_run:
                    dest_annots_dir.mkdir(parents=True, exist_ok=True)
            else:
                warning_msg = f"Annots directory does not exist: {dest_annots_dir.absolute()}"
                missing_annots_folders.add(warning_msg)
                skipped_files += 1
                continue
        
        dest_path = dest_annots_dir / filename
        
        # Copy the annotation file
        if dry_run:
            action = "[FORCED MOVE]" if use_forced_moves else "[DRY RUN]"
            print(f"{action} Would copy annot: {source_path} -> {dest_path}")
            copied_files += 1
        else:
            try:
                shutil.copy2(source_path, dest_path)
                if use_forced_moves:
                    print(f"{YELLOW}[FORCED MOVE]{RESET} {filename} -> forced_moves/{category_folder}/")
                    forced_moves += 1
                else:
                    print(f"{GREEN}[COPIED]{RESET} {filename} -> {capture_folder}/{category_folder}/")
                copied_files += 1
            except Exception as e:
                error_msg = f"Error copying {source_path} to {dest_path}: {e}"
                errors.append(error_msg)
                skipped_files += 1
                continue
        
        # If using forced moves, also copy the paired image
        if use_forced_moves:
            image_path = find_paired_image(source_path, source_dir, capture_folder, category_folder, verbose=True)
            if image_path:
                # Determine destination for image
                if annots_subfolder:
                    # Images go in images/ folder parallel to annots/
                    dest_images_dir = dest_capture_dir / category_folder / 'images'
                else:
                    # Images go in category root
                    dest_images_dir = dest_capture_dir / category_folder
                
                dest_image_path = dest_images_dir / image_path.name
                
                if dry_run:
                    print(f"[FORCED MOVE] Would copy image: {image_path} -> {dest_image_path}")
                else:
                    try:
                        dest_images_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(image_path, dest_image_path)
                        print(f"{YELLOW}[FORCED MOVE]{RESET} {image_path.name} -> forced_moves/{category_folder}/images/")
                    except Exception as e:
                        error_msg = f"Error copying image {image_path} to {dest_image_path}: {e}"
                        errors.append(error_msg)
            else:
                warning_msg = f"Paired image not found for: {source_path}"
                if warning_msg not in errors:
                    errors.append(warning_msg)
    
    # Print warnings
    if missing_annots_folders:
        print(f"\n{YELLOW}{BOLD}Warnings - Missing directories:{RESET}")
        for warning in sorted(missing_annots_folders):
            print(f"{YELLOW}  ⚠ {warning}{RESET}")
    
    # Print errors
    if errors:
        print(f"\n{RED}{BOLD}Errors:{RESET}")
        for error in errors:
            print(f"{RED}  ✗ {error}{RESET}")
    
    # Print summary
    print(f"\n{BOLD}Summary{RESET}")
    print("-------")
    print(f"Total files in tags.txt: {total_files}")
    print(f"Files copied:            {GREEN}{copied_files}{RESET}")
    print(f"Files skipped:           {YELLOW}{skipped_files}{RESET}")
    if force:
        print(f"Forced moves:            {YELLOW}{forced_moves}{RESET}")
    print(f"Missing directories:     {len(missing_annots_folders)}")
    print(f"Errors:                  {len(errors)}")
    
    if dry_run:
        print(f"\n{YELLOW}This was a dry run. Use without --dry-run to actually copy files.{RESET}")
    
    if force and forced_moves > 0:
        print(f"\n{YELLOW}Forced moves were made to: {forced_moves_dir}{RESET}")
    
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge annotation files from a tags.txt file to a destination directory."
    )
    parser.add_argument(
        "tags_file",
        type=Path,
        help="Path to the tags.txt file containing annotation paths",
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="Destination directory where annotations should be merged",
    )
    parser.add_argument(
        "--source-dir",
        "--source",
        type=Path,
        dest="source_dir",
        help="Source directory (defaults to the directory containing tags.txt)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without actually copying files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Copy images with paired annots to 'forced_moves' folder when capture folder is missing at destination",
    )
    
    args = parser.parse_args(argv)
    
    # Validate tags file
    if not args.tags_file.exists():
        print(f"{RED}ERROR: Tags file does not exist: {args.tags_file}{RESET}", file=sys.stderr)
        return 2
    
    # Validate destination
    if not args.destination.exists() or not args.destination.is_dir():
        print(f"{RED}ERROR: Destination does not exist or is not a directory: {args.destination}{RESET}", file=sys.stderr)
        return 2
    
    # Default source directory to tags file location
    source_dir = args.source_dir if args.source_dir else args.tags_file.parent
    
    if not source_dir.exists() or not source_dir.is_dir():
        print(f"{RED}ERROR: Source directory does not exist: {source_dir}{RESET}", file=sys.stderr)
        return 2
    
    print(f"{BOLD}Merge Annotations from Tags{RESET}")
    print(f"Tags file:    {args.tags_file}")
    print(f"Source dir:   {source_dir}")
    print(f"Destination:  {args.destination}")
    print(f"Mode:         {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Force:        {'Yes' if args.force else 'No'}")
    print()
    
    return merge_annotations(args.tags_file, source_dir, args.destination, args.dry_run, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
