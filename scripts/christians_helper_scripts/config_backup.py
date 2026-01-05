#!/usr/bin/env python3
"""
Config Backup Script

This script helps manage config file backups by keeping only the N newest config files
in a directory and moving older ones to a backup location.

Usage:
    # Default backup
    python config_backup.py -d /path/to/config/folder
    
    # Specify custom backup location
    python config_backup.py -d /path/to/config/folder -b /path/to/backup
    
    # Restore from a backup log
    python config_backup.py --restore /path/to/log.csv
"""

import os
import sys
import argparse
import shutil
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================
LOG_FOLDER_NAME = "config_backup"  # Easily changeable log folder name
DEFAULT_KEEP_COUNT = 5
DEFAULT_EXTENSIONS = ['.yaml', '.json']
DEFAULT_BACKUP_DIR = "backup/config_backup"

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_script_dir() -> Path:
    """Get the directory containing this script."""
    return Path(__file__).parent.resolve()

def get_logs_dir() -> Path:
    """Get the logs directory relative to the script location."""
    return get_script_dir() / "../../logs" / LOG_FOLDER_NAME

def ensure_logs_dir() -> Path:
    """Ensure the logs directory exists and return its path."""
    logs_dir = get_logs_dir().resolve()
    base_logs = logs_dir.parent
    
    if not base_logs.exists():
        print(f"WARNING: Base logs directory does not exist: {base_logs}")
        print(f"Creating logs directory at: {logs_dir}")
    
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir

def get_default_backup_dir() -> Path:
    """Get the default backup directory."""
    script_dir = get_script_dir()
    return (script_dir / f"../../{DEFAULT_BACKUP_DIR}").resolve()

def find_config_files(config_dir: Path, extensions: List[str]) -> List[Path]:
    """Find all config files with specified extensions in the directory."""
    config_files = []
    for ext in extensions:
        config_files.extend(config_dir.glob(f"*{ext}"))
    return config_files

def get_file_mtime_sorted(files: List[Path]) -> List[Tuple[Path, float]]:
    """
    Get files sorted by modification time (newest first).
    Returns list of (path, mtime) tuples.
    """
    files_with_mtime = [(f, f.stat().st_mtime) for f in files]
    return sorted(files_with_mtime, key=lambda x: x[1], reverse=True)

def prompt_user(message: str) -> bool:
    """Prompt user for yes/no confirmation."""
    while True:
        response = input(f"{message} (yes/no): ").strip().lower()
        if response in ['yes', 'y']:
            return True
        elif response in ['no', 'n']:
            return False
        else:
            print("Please answer 'yes' or 'no'")

def create_log_filename(config_dir: Path) -> str:
    """Create a log filename with ISO timestamp and directory name."""
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    dir_name = config_dir.name
    return f"{timestamp}_{dir_name}.csv"

# ============================================================================
# MAIN BACKUP LOGIC
# ============================================================================

def backup_configs(
    config_dir: Path,
    backup_dir: Path,
    keep_count: int,
    extensions: List[str],
    dry_run: bool
) -> List[dict]:
    """
    Main backup logic. Returns list of operations performed.
    
    Returns:
        List of dictionaries containing operation details for logging.
    """
    print(f"\n{'='*70}")
    print(f"Config Backup Operation")
    print(f"{'='*70}")
    print(f"Config Directory: {config_dir}")
    print(f"Backup Directory: {backup_dir}")
    print(f"Keep Count: {keep_count}")
    print(f"Extensions: {', '.join(extensions)}")
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    print(f"{'='*70}\n")
    
    # Validate config directory
    if not config_dir.exists():
        print(f"ERROR: Config directory does not exist: {config_dir}")
        sys.exit(1)
    
    if not config_dir.is_dir():
        print(f"ERROR: Path is not a directory: {config_dir}")
        sys.exit(1)
    
    # Find config files
    print(f"Searching for config files with extensions: {', '.join(extensions)}")
    config_files = find_config_files(config_dir, extensions)
    
    if not config_files:
        print(f"WARNING: No files found with extensions {', '.join(extensions)}")
        
        # Check if there are any other files
        all_files = [f for f in config_dir.iterdir() if f.is_file()]
        if all_files:
            print(f"Found {len(all_files)} files with other extensions:")
            # Get unique extensions
            other_exts = set(f.suffix for f in all_files if f.suffix)
            for ext in sorted(other_exts):
                count = sum(1 for f in all_files if f.suffix == ext)
                print(f"  {ext}: {count} file(s)")
            
            if prompt_user("Would you like to include these extensions?"):
                extensions = list(other_exts)
                config_files = find_config_files(config_dir, extensions)
                print(f"\nFound {len(config_files)} files with new extensions")
            else:
                print("Exiting without making changes.")
                sys.exit(0)
        else:
            print("No files found in directory. Exiting.")
            sys.exit(0)
    
    print(f"Found {len(config_files)} config file(s)")
    
    # Check if we need to do anything
    if len(config_files) <= keep_count:
        print(f"INFO: Number of files ({len(config_files)}) is less than or equal to keep count ({keep_count})")
        print("No files need to be moved. Exiting.")
        return []
    
    # Sort files by modification time (newest first)
    files_sorted = get_file_mtime_sorted(config_files)
    
    # Split into files to keep and files to move
    files_to_keep = files_sorted[:keep_count]
    files_to_move = files_sorted[keep_count:]
    
    print(f"\nFiles to keep ({len(files_to_keep)}):")
    for file_path, mtime in files_to_keep:
        mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  KEEP: {file_path.name} (modified: {mtime_str})")
    
    print(f"\nFiles to move to backup ({len(files_to_move)}):")
    operations = []
    for file_path, mtime in files_to_move:
        mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        dest_path = backup_dir / file_path.name
        print(f"  MOVE: {file_path.name} -> {dest_path} (modified: {mtime_str})")
        
        operations.append({
            'operation': 'move',
            'source': str(file_path),
            'destination': str(dest_path),
            'filename': file_path.name,
            'mtime': mtime_str,
            'timestamp': datetime.now().isoformat()
        })
    
    # Execute or dry run
    if dry_run:
        print(f"\n{'='*70}")
        print("DRY RUN MODE - No changes made")
        print("Run with --run flag to execute the backup operation")
        print(f"{'='*70}\n")
        return []
    
    # Create backup directory
    print(f"\nCreating backup directory: {backup_dir}")
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"ERROR: Failed to create backup directory: {e}")
        sys.exit(1)
    
    # Move files
    print("\nMoving files...")
    successful_ops = []
    for op in operations:
        source = Path(op['source'])
        dest = Path(op['destination'])
        
        try:
            # Check if destination already exists
            if dest.exists():
                print(f"WARNING: Destination file already exists: {dest}")
                # Add timestamp to make it unique
                timestamp_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
                stem = dest.stem
                suffix = dest.suffix
                dest = dest.parent / f"{stem}_{timestamp_suffix}{suffix}"
                op['destination'] = str(dest)
                print(f"         Using new destination: {dest}")
            
            shutil.move(str(source), str(dest))
            print(f"  ✓ Moved: {source.name}")
            successful_ops.append(op)
        except Exception as e:
            print(f"  ✗ ERROR moving {source.name}: {e}")
            # Don't exit, try to move remaining files
    
    print(f"\nSuccessfully moved {len(successful_ops)} out of {len(operations)} files")
    
    return successful_ops

# ============================================================================
# LOGGING FUNCTIONS
# ============================================================================

def write_log_csv(operations: List[dict], log_path: Path):
    """Write operations to CSV log file."""
    if not operations:
        print("No operations to log.")
        return
    
    try:
        with open(log_path, 'w', newline='') as csvfile:
            fieldnames = ['timestamp', 'operation', 'source', 'destination', 'filename', 'mtime']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for op in operations:
                writer.writerow(op)
        
        print(f"\n✓ Log file written: {log_path}")
    except Exception as e:
        print(f"\nERROR: Failed to write log file: {e}")
        sys.exit(1)

# ============================================================================
# RESTORE FUNCTIONS
# ============================================================================

def restore_from_log(log_path: Path, dry_run: bool):
    """Restore files from a backup log (undo operations)."""
    print(f"\n{'='*70}")
    print(f"Restore Operation")
    print(f"{'='*70}")
    print(f"Log File: {log_path}")
    print(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    print(f"{'='*70}\n")
    
    if not log_path.exists():
        print(f"ERROR: Log file does not exist: {log_path}")
        sys.exit(1)
    
    # Read operations from CSV
    operations = []
    try:
        with open(log_path, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            operations = list(reader)
    except Exception as e:
        print(f"ERROR: Failed to read log file: {e}")
        sys.exit(1)
    
    if not operations:
        print("No operations found in log file.")
        return
    
    print(f"Found {len(operations)} operations to reverse\n")
    
    # Reverse operations (undo from bottom up)
    operations.reverse()
    
    print("Operations to reverse (in order):")
    for i, op in enumerate(operations, 1):
        source = op['destination']  # Note: reversed
        dest = op['source']
        print(f"  {i}. MOVE: {source} -> {dest}")
    
    if dry_run:
        print(f"\n{'='*70}")
        print("DRY RUN MODE - No changes made")
        print("Run with --run flag to execute the restore operation")
        print(f"{'='*70}\n")
        return
    
    # Execute restore
    print("\nRestoring files...")
    success_count = 0
    for i, op in enumerate(operations, 1):
        source = Path(op['destination'])  # Reversed
        dest = Path(op['source'])
        
        if not source.exists():
            print(f"  {i}. ✗ ERROR: Source file not found: {source}")
            continue
        
        if dest.exists():
            print(f"  {i}. ✗ WARNING: Destination already exists: {dest}")
            if not prompt_user(f"     Overwrite {dest.name}?"):
                print(f"     Skipping...")
                continue
        
        try:
            # Ensure destination directory exists
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
            print(f"  {i}. ✓ Restored: {dest.name}")
            success_count += 1
        except Exception as e:
            print(f"  {i}. ✗ ERROR restoring {source.name}: {e}")
    
    print(f"\nSuccessfully restored {success_count} out of {len(operations)} files")

# ============================================================================
# MAIN FUNCTION
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Backup config files by keeping only N newest files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '-d', '--config-dir',
        type=str,
        help='Path to config directory to backup'
    )
    
    parser.add_argument(
        '-b', '--backup-dir',
        type=str,
        help=f'Path to backup directory (default: {DEFAULT_BACKUP_DIR})'
    )
    
    parser.add_argument(
        '-n', '--keep-count',
        type=int,
        default=DEFAULT_KEEP_COUNT,
        help=f'Number of newest files to keep (default: {DEFAULT_KEEP_COUNT})'
    )
    
    parser.add_argument(
        '-e', '--extensions',
        type=str,
        nargs='+',
        default=DEFAULT_EXTENSIONS,
        help=f'File extensions to backup (default: {" ".join(DEFAULT_EXTENSIONS)})'
    )
    
    parser.add_argument(
        '--run',
        action='store_true',
        help='Execute the operation (default is dry-run mode)'
    )
    
    parser.add_argument(
        '--restore',
        type=str,
        metavar='LOG_FILE',
        help='Restore from a backup log file (requires --run to execute)'
    )
    
    args = parser.parse_args()
    
    # Restore mode
    if args.restore:
        log_path = Path(args.restore).resolve()
        restore_from_log(log_path, dry_run=not args.run)
        return
    
    # Backup mode - require config-dir
    if not args.config_dir:
        parser.error("the following arguments are required: -d/--config-dir (or use --restore)")
    
    config_dir = Path(args.config_dir).resolve()
    
    # Determine backup directory
    if args.backup_dir:
        backup_dir = Path(args.backup_dir).resolve()
    else:
        backup_dir = get_default_backup_dir()
    
    # Ensure extensions have leading dot
    extensions = [ext if ext.startswith('.') else f'.{ext}' for ext in args.extensions]
    
    # Run backup
    operations = backup_configs(
        config_dir=config_dir,
        backup_dir=backup_dir,
        keep_count=args.keep_count,
        extensions=extensions,
        dry_run=not args.run
    )
    
    # Write log if operations were performed
    if operations and args.run:
        logs_dir = ensure_logs_dir()
        log_filename = create_log_filename(config_dir)
        log_path = logs_dir / log_filename
        write_log_csv(operations, log_path)

if __name__ == "__main__":
    main()
