#!/usr/bin/env python3
"""Deduplicates images in capture folders by content hash, keeping newest files and removing copy suffixes."""
"""
Deduplicate Images Script

This script removes duplicate images in a capture folder structure:
    <capture>/<category>/<img.png>

For each set of duplicates found:
1. Keeps only the newest file (based on file birth/creation time)
2. Removes ' (Copy n)' suffix from filenames if present
3. Logs all operations clearly

Example Usage:
    # Dry run (default - shows what would be done without making changes)
    python3 deduplicate_images.py --capture-dir /path/to/capture

    # Actually perform the deduplication
    python3 deduplicate_images.py --capture-dir /path/to/capture --run

Example Scenario:
    Given structure:
        /data/captures/wood/img_001.png (created 2025-01-01 10:00:00)
        /data/captures/wood/img_001 (Copy 1).png (created 2025-01-01 10:05:00)
        /data/captures/wood/img_002.png (created 2025-01-01 11:00:00)
        /data/captures/plastic/img_001.png (created 2025-01-01 09:00:00)
        /data/captures/plastic/img_003.png
        /data/captures/plastic/img_003 (Copy 2).png (created 2025-01-01 12:00:00)
    
    After running:
        /data/captures/wood/img_001.png (the Copy 1 file from wood/, renamed - newest)
        /data/captures/wood/img_002.png (no duplicates, unchanged)
        /data/captures/plastic/img_003.png (the Copy 2 file, renamed - newest)
        
    Removed:
        - /data/captures/wood/img_001.png (older than Copy 1)
        - /data/captures/plastic/img_001.png (older duplicate of wood/img_001.png)
"""

import argparse
import os
import re
import sys
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# ANSI color codes for better visibility
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def log_info(message: str) -> None:
    """Log informational message."""
    print(f"{Colors.OKBLUE}[INFO]{Colors.ENDC} {message}")


def log_success(message: str) -> None:
    """Log success message."""
    print(f"{Colors.OKGREEN}[SUCCESS]{Colors.ENDC} {message}")


def log_warning(message: str) -> None:
    """Log warning message."""
    print(f"{Colors.WARNING}[WARNING]{Colors.ENDC} {message}")


def log_error(message: str) -> None:
    """Log error message."""
    print(f"{Colors.FAIL}[ERROR]{Colors.ENDC} {message}", file=sys.stderr)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Deduplicate images in a capture folder structure.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  # Dry run (shows what would be done)
  python3 deduplicate_images.py --capture-dir /home/user/data/captures
  
  # Actually perform the deduplication
  python3 deduplicate_images.py --capture-dir /home/user/data/captures --run
        """
    )
    parser.add_argument(
        "--capture-dir",
        required=True,
        help="Path to the capture directory containing category subdirectories."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually perform the deduplication. Without this flag, runs in DRY-RUN mode."
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=[".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"],
        help="Image file extensions to process (default: .png .jpg .jpeg .bmp .tiff .tif)."
    )
    return parser.parse_args()


def get_file_birth_time(file_path: Path) -> float:
    """
    Get the birth time (creation time) of a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Birth time as a float (seconds since epoch)
        Falls back to modification time if birth time is not available
    """
    try:
        stat_info = file_path.stat()
        # Try to get birth time (st_birthtime on some systems)
        if hasattr(stat_info, 'st_birthtime'):
            return stat_info.st_birthtime
        # Fall back to creation time (st_ctime) which is the closest on Linux
        # Note: On Linux, st_ctime is the last metadata change time, not creation time
        # but it's the best we have
        return stat_info.st_ctime
    except Exception as e:
        log_error(f"Failed to get birth time for {file_path}: {e}")
        raise


def normalize_filename(filename: str) -> str:
    """
    Remove ' (Copy n)' and ' (Copy)' patterns from filename while preserving the extension.
    
    Args:
        filename: Original filename
        
    Returns:
        Normalized filename without ' (Copy n)' or ' (Copy)' pattern
        
    Examples:
        'img_001 (Copy 1).png' -> 'img_001.png'
        'img_001 (Copy 23).png' -> 'img_001.png'
        'img_001 (Copy).png' -> 'img_001.png'
        'img_001.png' -> 'img_001.png'
    """
    # Pattern matches ' (Copy n)' where n is one or more digits, or just ' (Copy)'
    # The pattern must appear before the file extension
    pattern = r' \(Copy(?: \d+)?\)'
    normalized = re.sub(pattern, '', filename)
    return normalized


def compute_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    """
    Compute SHA256 hash of a file.
    
    Args:
        file_path: Path to the file
        chunk_size: Size of chunks to read (for memory efficiency)
        
    Returns:
        Hexadecimal hash string
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except Exception as e:
        log_error(f"Failed to compute hash for {file_path}: {e}")
        raise


def find_all_images(capture_dir: Path, extensions: List[str]) -> List[Path]:
    """
    Find all image files in the capture directory structure.
    
    Args:
        capture_dir: Root capture directory
        extensions: List of file extensions to include (case-insensitive)
        
    Returns:
        List of Path objects for all found image files
    """
    image_files = []
    extensions_lower = [ext.lower() for ext in extensions]
    
    try:
        for root, dirs, files in os.walk(capture_dir):
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in extensions_lower:
                    image_files.append(file_path)
        
        log_info(f"Found {len(image_files)} image files")
        return image_files
    
    except Exception as e:
        log_error(f"Failed to scan directory {capture_dir}: {e}")
        raise


def are_filenames_related(file1: Path, file2: Path) -> bool:
    """
    Check if two filenames are related (same base name or one has Copy pattern).
    Works across directories - duplicates with same content are considered related
    regardless of which folder they're in.
    
    Args:
        file1: First file path
        file2: Second file path
        
    Returns:
        True if filenames are related (duplicates should be removed)
        
    Examples:
        'wood/img_001.png' and 'wood/img_001 (Copy 1).png' -> True
        'wood/img_001.png' and 'plastic/img_001.png' -> True (same name, cross-folder)
        'wood/img_001.png' and 'wood/img_001 (Copy).png' -> True
        'wood/img_version_a.png' and 'wood/img_version_b.png' -> False
    """
    name1 = file1.name
    name2 = file2.name
    
    # Exact same filename (even in different folders)
    if name1 == name2:
        return True
    
    # Normalize both names (remove Copy pattern)
    normalized1 = normalize_filename(name1)
    normalized2 = normalize_filename(name2)
    
    # If after normalization they're the same, they're related
    # e.g., 'img_001.png' and 'img_001 (Copy 1).png' -> both normalize to 'img_001.png'
    # or 'img_001 (Copy).png' -> normalizes to 'img_001.png'
    if normalized1 == normalized2:
        return True
    
    return False


def group_duplicates_by_content(image_files: List[Path]) -> Dict[str, List[Path]]:
    """
    Group files by their content hash (actual duplicates).
    Only groups files with related names (same name or Copy pattern).
    
    Args:
        image_files: List of image file paths
        
    Returns:
        Dictionary mapping hash -> list of files with that hash
    """
    hash_groups = defaultdict(list)
    
    log_info("Computing file hashes to identify duplicates...")
    
    for i, file_path in enumerate(image_files, 1):
        try:
            if i % 100 == 0:
                log_info(f"Processed {i}/{len(image_files)} files...")
            
            file_hash = compute_file_hash(file_path)
            hash_groups[file_hash].append(file_path)
        
        except Exception as e:
            log_warning(f"Skipping {file_path} due to error: {e}")
            continue
    
    # Filter to only groups with duplicates that have related names
    duplicate_groups = {}
    for file_hash, files in hash_groups.items():
        if len(files) < 2:
            continue
        
        # Group files by related names
        related_groups = []
        processed = set()
        
        for i, file1 in enumerate(files):
            if i in processed:
                continue
            
            related = [file1]
            processed.add(i)
            
            for j, file2 in enumerate(files):
                if j in processed:
                    continue
                
                if are_filenames_related(file1, file2):
                    related.append(file2)
                    processed.add(j)
            
            if len(related) > 1:
                related_groups.append(related)
        
        # Add each related group as a separate duplicate group
        for idx, related in enumerate(related_groups):
            duplicate_groups[f"{file_hash}_{idx}"] = related
    
    log_info(f"Found {len(duplicate_groups)} groups of duplicate files")
    return duplicate_groups


def select_file_to_keep(files: List[Path]) -> Tuple[Path, List[Path]]:
    """
    Select which file to keep from a group of duplicates.
    Keeps the newest file based on birth time.
    
    Args:
        files: List of duplicate file paths
        
    Returns:
        Tuple of (file_to_keep, files_to_remove)
    """
    # Sort by birth time (newest first)
    try:
        files_with_time = [(f, get_file_birth_time(f)) for f in files]
        files_with_time.sort(key=lambda x: x[1], reverse=True)
        
        file_to_keep = files_with_time[0][0]
        files_to_remove = [f[0] for f in files_with_time[1:]]
        
        return file_to_keep, files_to_remove
    
    except Exception as e:
        log_error(f"Failed to select file to keep: {e}")
        raise


def rename_if_needed(file_path: Path, dry_run: bool) -> Optional[Path]:
    """
    Rename file if it contains ' (Copy n)' pattern.
    
    Args:
        file_path: Current file path
        dry_run: If True, don't actually rename
        
    Returns:
        New path if renamed, None if no rename needed
    """
    original_name = file_path.name
    normalized_name = normalize_filename(original_name)
    
    if original_name == normalized_name:
        return None
    
    new_path = file_path.parent / normalized_name
    
    # Check if target already exists
    if new_path.exists() and new_path != file_path:
        log_warning(f"Cannot rename {file_path} to {new_path}: target already exists")
        return None
    
    if dry_run:
        log_info(f"Would rename: {file_path} -> {new_path.name}")
    else:
        try:
            file_path.rename(new_path)
            log_success(f"Renamed: {file_path} -> {new_path.name}")
        except Exception as e:
            log_error(f"Failed to rename {file_path}: {e}")
            raise
    
    return new_path


def remove_file(file_path: Path, dry_run: bool) -> None:
    """
    Remove a duplicate file.
    
    Args:
        file_path: Path to file to remove
        dry_run: If True, don't actually remove
    """
    if dry_run:
        log_info(f"Would remove: {file_path}")
    else:
        try:
            file_path.unlink()
            log_success(f"Removed: {file_path}")
        except Exception as e:
            log_error(f"Failed to remove {file_path}: {e}")
            raise


def validate_capture_dir(capture_dir: Path) -> None:
    """
    Validate that the capture directory exists and is accessible.
    
    Args:
        capture_dir: Path to capture directory
        
    Raises:
        SystemExit if validation fails
    """
    if not capture_dir.exists():
        log_error(f"Capture directory does not exist: {capture_dir}")
        sys.exit(1)
    
    if not capture_dir.is_dir():
        log_error(f"Path is not a directory: {capture_dir}")
        sys.exit(1)
    
    if not os.access(capture_dir, os.R_OK):
        log_error(f"Cannot read capture directory: {capture_dir}")
        sys.exit(1)
    
    log_info(f"Validated capture directory: {capture_dir}")


def main():
    """Main execution function."""
    args = parse_args()
    
    # Convert to Path object
    capture_dir = Path(args.capture_dir).resolve()
    dry_run = not args.run
    
    # Print mode
    if dry_run:
        print(f"\n{Colors.BOLD}{Colors.WARNING}=== DRY RUN MODE ==={Colors.ENDC}")
        print(f"{Colors.WARNING}No changes will be made. Use --run to actually perform deduplication.{Colors.ENDC}\n")
    else:
        print(f"\n{Colors.BOLD}{Colors.OKGREEN}=== LIVE MODE ==={Colors.ENDC}")
        print(f"{Colors.OKGREEN}Changes will be applied!{Colors.ENDC}\n")
    
    # Validate capture directory
    validate_capture_dir(capture_dir)
    
    # Find all image files
    try:
        image_files = find_all_images(capture_dir, args.extensions)
    except Exception as e:
        log_error(f"Failed to find image files: {e}")
        sys.exit(1)
    
    if not image_files:
        log_warning("No image files found in the capture directory")
        sys.exit(0)
    
    # Group duplicates by content
    try:
        duplicate_groups = group_duplicates_by_content(image_files)
    except Exception as e:
        log_error(f"Failed to group duplicates: {e}")
        sys.exit(1)
    
    if not duplicate_groups:
        log_info("No duplicate files found!")
        sys.exit(0)
    
    # Process each group of duplicates
    total_duplicates = sum(len(files) - 1 for files in duplicate_groups.values())
    log_info(f"Processing {len(duplicate_groups)} duplicate groups ({total_duplicates} files to remove)...")
    
    removed_count = 0
    renamed_count = 0
    
    try:
        for group_hash, files in duplicate_groups.items():
            log_info(f"\nProcessing duplicate group ({len(files)} files):")
            for f in files:
                log_info(f"  - {f}")
            
            # Select file to keep
            file_to_keep, files_to_remove = select_file_to_keep(files)
            
            log_info(f"Keeping: {file_to_keep} (newest)")
            
            # Check if we need to rename the kept file
            original_name = file_to_keep.name
            normalized_name = normalize_filename(original_name)
            needs_rename = (original_name != normalized_name)
            target_path = file_to_keep.parent / normalized_name if needs_rename else None
            
            # Remove duplicates first (important: do this before renaming)
            for file_to_remove in files_to_remove:
                remove_file(file_to_remove, dry_run)
                if not dry_run:
                    removed_count += 1
            
            # Now rename the kept file if needed (after old files are removed)
            if needs_rename:
                if dry_run:
                    log_info(f"Would rename: {file_to_keep} -> {normalized_name}")
                else:
                    try:
                        file_to_keep.rename(target_path)
                        log_success(f"Renamed: {file_to_keep.name} -> {normalized_name}")
                        renamed_count += 1
                    except Exception as e:
                        log_error(f"Failed to rename {file_to_keep}: {e}")
                        raise
    
    except Exception as e:
        log_error(f"Fatal error during deduplication: {e}")
        sys.exit(1)
    
    # Summary
    print(f"\n{Colors.BOLD}=== SUMMARY ==={Colors.ENDC}")
    if dry_run:
        log_info(f"Would remove {total_duplicates} duplicate files")
        log_info(f"Would rename files with ' (Copy n)' pattern")
        log_info("Run with --run flag to apply these changes")
    else:
        log_success(f"Removed {removed_count} duplicate files")
        log_success(f"Renamed {renamed_count} files")
        log_info("Deduplication complete!")


if __name__ == "__main__":
    main()
