#!/usr/bin/env python3
import os
import re
import argparse
from datetime import datetime
from collections import defaultdict


def convert_timestamp_to_iso(timestamp_str):
    """
    Convert timestamp to ISO format with milliseconds.
    Supports:
    - Unix timestamp (with decimals): 1234567890.123
    - YYYYMMDD_hhmmss format: 20231005_151615
    """
    try:
        # Try YYYYMMDD_hhmmss format first (must check before Unix timestamp)
        if '_' in timestamp_str and len(timestamp_str) == 15:
            dt = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            return dt.strftime("%Y-%m-%dT%H-%M-%S") + "-000"
        # Try Unix timestamp
        elif '.' in timestamp_str or timestamp_str.isdigit():
            ts = float(timestamp_str)
            dt = datetime.fromtimestamp(ts)
            return dt.strftime("%Y-%m-%dT%H-%M-%S") + f"-{int(dt.microsecond/1000):03d}"
        else:
            return None
    except Exception:
        return None


def check_existing_capture_devices(base_dir, extensions):
    """
    Scan for files that already have the img_/annot_ format and extract their capture devices.
    Returns a set of unique capture device names found in filenames (normalized to use hyphens).
    """
    # Pattern that allows underscores in capture device names
    existing_pattern = re.compile(r'^(img|annot)_([a-zA-Z0-9_\-]+)_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}\.(png|json)$')
    capture_devices = set()
    
    for root, _, files in os.walk(base_dir):
        for file in files:
            if not any(file.endswith(ext) for ext in extensions):
                continue
            
            match = existing_pattern.match(file)
            if match:
                # Normalize capture device name (replace underscores with hyphens)
                capture_name = match.group(2).replace('_', '-')
                capture_devices.add(capture_name)
    
    return capture_devices


def rename_files(base_dir, capture_device, extensions, fix=False, update_existing=False):
    """
    Traverse all subdirectories and rename files matching timestamp patterns.
    Handles:
    - Unix timestamps: file_1234567890.123.png
    - YYYYMMDD_hhmmss: image_20231005_151615.png
    
    Renames to:
    - PNG files: img_<capture-device>_<iso_ts>.png
    - JSON files: annot_<capture-device>_<iso_ts>.json
    
    Args:
        update_existing: If True, will also update capture device in already formatted files
    """
    # Normalize capture device: convert spaces and underscores to hyphens
    capture_device = capture_device.replace(' ', '-').replace('_', '-')
    
    # Pattern for already correctly formatted files
    existing_pattern = re.compile(r'^(img|annot)_([a-zA-Z0-9\-]+)_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3})(\.(png|json))$')
    
    # Pattern 1: Unix timestamp (with or without decimals)
    # Matches: any_filename_1234567890.123.ext or any_filename_1234567890.ext
    pattern_unix = re.compile(r"^(.+?)_(\d+(?:\.\d+)?)(\.[^.]+)$")
    
    # Pattern 2: YYYYMMDD_hhmmss format
    # Matches: any_filename_20231005_151615.ext
    pattern_yyyymmdd = re.compile(r"^(.+?)_(\d{8}_\d{6})(\.[^.]+)$")

    renamed_total = 0
    counts = defaultdict(int)
    background_counts = defaultdict(int)  # Track background images separately

    for root, _, files in os.walk(base_dir):
        # Check if we're in a background folder (check if 'background' is anywhere in the path)
        is_background = 'background' in root.split(os.sep)
        
        for file in files:
            if not any(file.endswith(ext) for ext in extensions):
                continue

            # Check if file already matches target format (but may have underscores or wrong capture device)
            existing_match = existing_pattern.match(file)
            if not existing_match:
                # Try pattern that allows underscores in capture device name
                existing_pattern_with_underscore = re.compile(r'^(img|annot)_([a-zA-Z0-9_\-]+)_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3})(\.(png|json))$')
                existing_match = existing_pattern_with_underscore.match(file)
            
            if existing_match:
                # Extract components and check if capture device needs updating
                prefix, old_capture, timestamp, ext_with_dot, _ = existing_match.groups()
                
                # Normalize the old capture device (replace underscores with hyphens)
                normalized_old_capture = old_capture.replace('_', '-')
                
                # Check if we need to update (either capture device name is different or has underscores)
                needs_update = (normalized_old_capture != capture_device) or ('_' in old_capture)
                
                if needs_update and update_existing:
                    new_name = f"{prefix}_{capture_device}_{timestamp}{ext_with_dot}"
                    old_path = os.path.join(root, file)
                    new_path = os.path.join(root, new_name)
                    
                    renamed_total += 1
                    counts[ext_with_dot] += 1
                    if is_background and ext_with_dot == '.png':
                        background_counts[ext_with_dot] += 1
                    
                    relpath = os.path.relpath(old_path, base_dir)
                    if fix:
                        os.rename(old_path, new_path)
                        if '_' in old_capture:
                            print(f"Fixed underscore in capture name: {relpath} → {new_name}")
                        else:
                            print(f"Updated capture device: {relpath} → {new_name}")
                    else:
                        if '_' in old_capture:
                            print(f"Would fix underscore in capture name: {relpath} → {new_name}")
                        else:
                            print(f"Would update capture device: {relpath} → {new_name}")
                elif needs_update and not update_existing:
                    # Still need to fix underscores even if not updating capture devices
                    if '_' in old_capture:
                        new_name = f"{prefix}_{normalized_old_capture}_{timestamp}{ext_with_dot}"
                        old_path = os.path.join(root, file)
                        new_path = os.path.join(root, new_name)
                        
                        renamed_total += 1
                        counts[ext_with_dot] += 1
                        if is_background and ext_with_dot == '.png':
                            background_counts[ext_with_dot] += 1
                        
                        relpath = os.path.relpath(old_path, base_dir)
                        if fix:
                            os.rename(old_path, new_path)
                            print(f"Fixed underscore in capture name: {relpath} → {new_name}")
                        else:
                            print(f"Would fix underscore in capture name: {relpath} → {new_name}")
                    else:
                        print(f"Skipping (already renamed): {os.path.relpath(os.path.join(root, file), base_dir)}")
                else:
                    print(f"Skipping (already correct): {os.path.relpath(os.path.join(root, file), base_dir)}")
                continue

            # Try matching patterns - check YYYYMMDD format first for priority
            match_yyyymmdd = pattern_yyyymmdd.match(file)
            match_unix = pattern_unix.match(file)
            
            if match_yyyymmdd:
                match = match_yyyymmdd
            elif match_unix:
                match = match_unix
            else:
                continue

            _, timestamp_str, ext = match.groups()
            new_time = convert_timestamp_to_iso(timestamp_str)
            if not new_time:
                continue

            # Determine prefix based on file extension
            if ext.lower() == '.png':
                prefix = 'img'
            elif ext.lower() == '.json':
                prefix = 'annot'
            else:
                continue  # Skip unsupported extensions

            new_name = f"{prefix}_{capture_device}_{new_time}{ext}"
            old_path = os.path.join(root, file)
            new_path = os.path.join(root, new_name)

            if file == new_name:
                print(f"Skipping (already correct): {os.path.relpath(old_path, base_dir)}")
                continue

            renamed_total += 1
            counts[ext] += 1
            if is_background and ext == '.png':
                background_counts[ext] += 1

            relpath = os.path.relpath(old_path, base_dir)
            if fix:
                os.rename(old_path, new_path)
                print(f"Renamed: {relpath} → {new_name}")
            else:
                print(f"Would rename: {relpath} → {new_name}")

    return renamed_total, counts, background_counts


def print_summary(total, counts, background_counts, fix):
    print("\n" + "=" * 60)
    print(f"SUMMARY ({'APPLIED' if fix else 'DRY RUN (use --fix to apply)'})")
    print("=" * 60)
    if total == 0:
        print("No matching files found.")
    else:
        print(f"Total files {'renamed' if fix else 'to be renamed'}: {total}")
        
        # Calculate object images (total images - background images)
        total_images = counts.get('.png', 0)
        total_bg_images = background_counts.get('.png', 0)
        object_images = total_images - total_bg_images
        total_annots = counts.get('.json', 0)
        
        if total_images > 0:
            print(f"  • Images: {total_images}")
            if total_bg_images > 0:
                print(f"    - Background images: {total_bg_images}")
                print(f"    - Object images: {object_images}")
        if total_annots > 0:
            print(f"  • Annotations: {total_annots}")
        
        # Show other extensions if any
        for ext, count in counts.items():
            if ext not in ['.png', '.json']:
                print(f"  • {ext}: {count}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Recursively rename files with Unix timestamps or YYYYMMDD_hhmmss timestamps to ISO format."
    )
    parser.add_argument(
        "base_dir",
        help="Base directory to start scanning."
    )
    parser.add_argument(
        "--capture_device", "-c", required=False,
        help="Capture device name (e.g., 'jolly-giraffe'). If not provided, defaults to parent folder name."
    )
    parser.add_argument(
        "--extensions", "-e", nargs="+", default=[".png", ".json"],
        help="File extensions to process (default: .png .json)."
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Actually rename files (default: dry run)."
    )

    args = parser.parse_args()

    # If no capture device is provided, use the parent folder name
    if args.capture_device is None:
        parent_folder = os.path.basename(os.path.abspath(args.base_dir))
        print(f"No capture device specified. Using parent folder name: '{parent_folder}'")
        response = input("Continue with this capture device? [y/n]: ").strip().lower()
        if response and response not in ['y', 'yes']:
            print("Aborted.")
            return
        args.capture_device = parent_folder
    
    # Normalize the capture device
    normalized_capture_device = args.capture_device.replace(' ', '-').replace('_', '-')
    
    # Check for existing capture devices in filenames
    existing_devices = check_existing_capture_devices(args.base_dir, args.extensions)
    
    if existing_devices:
        # Filter out the capture device we're planning to use
        mismatched_devices = [d for d in existing_devices if d != normalized_capture_device]
        
        if mismatched_devices:
            print(f"\n⚠️  WARNING: Found files with different capture device names in filenames!")
            print(f"  Intended capture device: '{normalized_capture_device}'")
            print(f"  Found in existing filenames: {', '.join(sorted(mismatched_devices))}")
            print(f"\nWhat would you like to do?")
            print(f"  1) Replace all capture device names with '{normalized_capture_device}'")
            print(f"  2) Keep existing capture device names (only rename files without proper format)")
            print(f"  3) Abort")
            
            choice = input("\nEnter choice [1/2/3]: ").strip()
            
            if choice == '1':
                print(f"✓ Will replace all capture device names with '{normalized_capture_device}'")
                update_existing_flag = True
            elif choice == '2':
                print(f"✓ Will keep existing capture device names in already formatted files")
                update_existing_flag = False
            else:
                print("Aborted.")
                return
        else:
            update_existing_flag = False
    else:
        update_existing_flag = False

    print(f"\nScanning directory: {os.path.abspath(args.base_dir)}")
    print(f"Capture device: {args.capture_device}")
    print(f"Extensions: {', '.join(args.extensions)}")
    print(f"Mode: {'APPLY CHANGES' if args.fix else 'DRY RUN'}")
    print("-" * 60)

    total, counts, background_counts = rename_files(args.base_dir, args.capture_device, args.extensions, args.fix, update_existing_flag)
    print_summary(total, counts, background_counts, args.fix)


if __name__ == "__main__":
    main()
