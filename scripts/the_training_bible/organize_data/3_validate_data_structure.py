#!/usr/bin/env python3
import os
import re
import json
import argparse
from collections import defaultdict
from pathlib import Path


BOLD = '\033[1m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'

class DataValidator:
    """Validates data structure and filename conventions for collection/capture folders."""
    
    # Expected filename patterns - only hyphens allowed in capture device names, no underscores
    IMG_PATTERN = re.compile(r'^img_[a-zA-Z0-9\-]+_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}\.png$')
    ANNOT_PATTERN = re.compile(r'^annot_[a-zA-Z0-9\-]+_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}\.json$')
    
    def __init__(self, base_dir, mode='collection', verbose=False):
        """
        Initialize validator.
        
        Args:
            base_dir: Path to collection or capture folder
            mode: 'collection' or 'capture' - determines validation level
            verbose: If True, print detailed category information
        """
        
        self.base_dir = Path(base_dir).resolve()
        self.mode = mode
        self.verbose = verbose
        self.errors = []
        self.warnings = []
        self.infos = []
        self.stats = defaultdict(int)
        self.filename_registry = {}  # Maps filename -> list of (path, mtime) tuples
        self.all_categories = set()  # Track unique categories across all splits
        self.split_categories = {}  # Maps split name -> set of categories
        self.category_mismatches = []  # Track annotation files with incorrect category fields
    
    def _format_path(self, path, capture_name=None, obj_name=None):
        """
        Format path for display in messages.
        In collection mode, show capture/object path and full path.
        In capture mode, show relative path from base_dir.
        """
        if self.mode == 'collection' and capture_name:
            if obj_name:
                relative = f"{capture_name}/{obj_name}"
            else:
                relative = capture_name
            return f"{relative}\n      Full path: {path}"
        else:
            return str(path)
    
    def _load_json(self, path):
        """Load and parse a JSON file, return None if it fails."""
        try:
            with path.open('r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.warnings.append(f"Failed to parse JSON file {path}: {e}")
            return None
    
    def _expected_category_for(self, json_path):
        """Extract expected category from annotation path."""
        # json_path.parent is annots/ (or category/ in train mode),
        # its parent is the category folder
        parent = json_path.parent
        if parent.name == "annots":
            return parent.parent.name
        else:
            # In train mode, might be directly in category folder
            return parent.name
    
    def _validate_annotation_category(self, annot_path, expected_category):
        """Validate that annotation's category field matches expected category."""
        data = self._load_json(annot_path)
        if data is None:
            return  # Already warned in _load_json
        
        annots = data.get("annotations")
        if not isinstance(annots, list):
            return
        
        mismatched_count = 0
        actual_categories = set()
        
        for a in annots:
            if not isinstance(a, dict):
                continue
            cat = a.get("category")
            if cat:
                actual_categories.add(cat)
                if cat != expected_category:
                    mismatched_count += 1
        
        if mismatched_count > 0:
            actual_cats_str = ", ".join(f"'{c}'" for c in sorted(actual_categories) if c != expected_category)
            self.category_mismatches.append({
                "path": annot_path,
                "expected": expected_category,
                "actual": actual_cats_str,
                "mismatched_count": mismatched_count,
                "total_count": len(annots)
            })
        
    def validate(self):
        """Run validation and return results."""
        if not self.base_dir.exists():
            self.errors.append(f"Directory does not exist: {self.base_dir}")
            return False
            
        if self.mode == 'collection':
            self._validate_collection()
        elif self.mode == 'capture':
            self._validate_capture()
        elif self.mode == 'train':
            self._validate_train()
        else:
            self.errors.append(f"Invalid mode: {self.mode}")
            return False
        
        # Check for duplicate filenames after traversing all folders
        self._check_for_duplicates()
            
        return len(self.errors) == 0
    
    def _validate_collection(self):
        """Validate collection folder structure."""
        # Check for capture folders
        capture_folders = [d for d in self.base_dir.iterdir() if d.is_dir()]
        
        if not capture_folders:
            self.errors.append(f"No capture folders found in collection: {self.base_dir}")
            return
            
        self.stats['capture_folders'] = len(capture_folders)
        
        for capture_folder in capture_folders:
            self._validate_capture_folder(capture_folder)
    
    def _validate_capture(self):
        """Validate a single capture folder."""
        self._validate_capture_folder(self.base_dir)
    
    def _validate_train(self):
        """Validate training data structure (train/val/test splits)."""
        # Expected split folders
        expected_splits = ['train', 'val', 'test']
        found_splits = []
        
        for split_name in expected_splits:
            split_path = self.base_dir / split_name
            if split_path.exists() and split_path.is_dir():
                found_splits.append(split_name)
                self._validate_split_folder(split_path, split_name)
            else:
                # It's okay if split doesn't exist, but note it
                self.warnings.append(f"Split folder '{split_name}' not found at: {split_path}")
        
        if not found_splits:
            self.errors.append(f"No split folders (train/val/test) found in: {self.base_dir}")
            return
        
        self.stats['split_folders'] = len(found_splits)
    
    def _validate_split_folder(self, split_path, split_name):
        """Validate a split folder (train/val/test) - recursively find all images and annotations."""
        # Recursively find all images and annotations
        all_images = list(split_path.glob("**/*.png"))
        all_annots = list(split_path.glob("**/*.json"))
        
        if not all_images and not all_annots:
            self.infos.append(f"Split folder '{split_name}' is empty: {split_path}")
            return
        
        # Track categories found in this split
        categories_in_split = set()
        
        # Process all images
        for img_path in all_images:
            # Determine category: parent folder, or parent's parent if parent is "images"
            parent = img_path.parent
            if parent.name == "images":
                category_name = parent.parent.name
            else:
                category_name = parent.name
            
            # Skip augmentation_backgrounds and background
            if category_name in ["augmentation_backgrounds", "background"]:
                continue
            
            self._register_file(img_path)
            categories_in_split.add(category_name)
            self.all_categories.add(category_name)  # Track globally
            self.stats['total_images'] += 1
            self.stats[f'{split_name}_images'] = self.stats.get(f'{split_name}_images', 0) + 1
        
        # Process all annotations
        for annot_path in all_annots:
            # Determine category: parent folder, or parent's parent if parent is "annots"
            parent = annot_path.parent
            if parent.name == "annots":
                category_name = parent.parent.name
            else:
                category_name = parent.name
            
            # Skip augmentation_backgrounds and background
            if category_name in ["augmentation_backgrounds", "background"]:
                continue
            
            self._register_file(annot_path)
            categories_in_split.add(category_name)
            self.all_categories.add(category_name)  # Track globally
            self.stats['total_annots'] += 1
            self.stats[f'{split_name}_annots'] = self.stats.get(f'{split_name}_annots', 0) + 1
            
            # Validate annotation category field
            self._validate_annotation_category(annot_path, category_name)
        
        # Update category statistics for this split
        self.stats[f'{split_name}_categories'] = len(categories_in_split)
        self.split_categories[split_name] = categories_in_split  # Store for verbose output

    
    def _validate_capture_folder(self, capture_path):
        """Validate structure of a capture folder."""
        capture_name = capture_path.name
        
        # Check for background folder (optional but common)
        background_path = capture_path / "background"
        if background_path.exists():
            self.stats['background_folders'] += 1
            self._validate_background_folder(background_path, capture_name, capture_path)
        
        # Check for object folders
        object_folders = [d for d in capture_path.iterdir() 
                         if d.is_dir() and d.name != "background"]
        
        if not object_folders:
            self.errors.append(f"No object folders found in capture: {self._format_path(capture_path, capture_name)}")
            return
        
        self.stats['object_folders'] += len(object_folders)
        
        for obj_folder in object_folders:
            self._validate_object_folder(obj_folder, capture_name, capture_path)
    
    def _validate_background_folder(self, bg_path, capture_name, capture_path):
        """Validate background folder - should contain images directly."""
        images = list(bg_path.glob("*.png"))
        
        if not images:
            self.warnings.append(f"Background folder is empty: {self._format_path(bg_path, capture_name, 'background')}")
            return
        
        self.stats['background_images'] += len(images)
        
        for img in images:
            self._register_file(img)  # Register for duplicate detection
            self._validate_filename(img, capture_name, 'image', bg_path, capture_path, 'background')
    
    def _validate_object_folder(self, obj_path, capture_name, capture_path):
        """Validate object folder structure (images/ and annots/ subfolders)."""
        obj_name = obj_path.name
        images_path = obj_path / "images"
        annots_path = obj_path / "annots"
        
        # Check for required subfolders
        if not images_path.exists():
            self.errors.append(f"Missing 'images' folder in: {self._format_path(obj_path, capture_name, obj_name)}")
        else:
            self._validate_images_folder(images_path, capture_name, obj_path, capture_path, obj_name)
        
        if not annots_path.exists():
            self.errors.append(f"Missing 'annots' folder in: {self._format_path(obj_path, capture_name, obj_name)}")
        else:
            self._validate_annots_folder(annots_path, capture_name, obj_path, capture_path, obj_name)
        
        # Check for files directly in object folder (should not exist)
        direct_files = [f for f in obj_path.iterdir() if f.is_file()]
        if direct_files:
            self.warnings.append(
                f"Found {len(direct_files)} file(s) directly in object folder (should be in images/ or annots/): {self._format_path(obj_path, capture_name, obj_name)}"
            )
            for f in direct_files[:5]:  # Show first 5
                self.warnings.append(f"  - {f.name}")
    
    def _validate_images_folder(self, images_path, capture_name, obj_path, capture_path, obj_name):
        """Validate images folder contents."""
        images = list(images_path.glob("*.png"))
        
        if not images:
            self.infos.append(f"Images folder is empty: {self._format_path(images_path, capture_name, obj_name)}")
            return
        
        self.stats['total_images'] += len(images)
        self.stats['object_images'] += len(images)  # Track object images separately
        
        for img in images:
            self._register_file(img)  # Register for duplicate detection
            self._validate_filename(img, capture_name, 'image', obj_path, capture_path, obj_name)
    
    def _validate_annots_folder(self, annots_path, capture_name, obj_path, capture_path, obj_name):
        """Validate annotations folder contents."""
        annots = list(annots_path.glob("*.json"))
        
        if not annots:
            self.infos.append(f"Annotations folder is empty: {self._format_path(annots_path, capture_name, obj_name)}")
            return
        
        self.stats['total_annots'] += len(annots)
        
        for annot in annots:
            self._register_file(annot)  # Register for duplicate detection
            self._validate_filename(annot, capture_name, 'annot', obj_path, capture_path, obj_name)
            # Validate annotation category field
            expected_category = self._expected_category_for(annot)
            self._validate_annotation_category(annot, expected_category)
    
    def _validate_filename(self, file_path, capture_name, file_type, parent_path, capture_path, obj_name):
        """Validate individual filename against convention."""
        filename = file_path.name
        
        if file_type == 'image':
            if not self.IMG_PATTERN.match(filename):
                self.errors.append(
                    f"Invalid image filename format in {self._format_path(parent_path, capture_name, obj_name)}: {filename}"
                )
                self.stats['invalid_filenames'] += 1
                return
            
            # Check if capture name in filename matches folder structure
            parts = filename.split('_')
            if len(parts) >= 3:
                file_capture_name = parts[1]
                # Normalize both names for comparison (convert to lowercase and replace _ with -)
                normalized_file_capture = file_capture_name.lower().replace('_', '-')
                normalized_folder_capture = capture_name.lower().replace('_', '-')
                
                # Check if file capture name is contained in folder name or vice versa
                # This allows for partial matches (e.g., "jolly-giraffe" matches "jolly-giraffe-v2")
                if normalized_file_capture not in normalized_folder_capture and normalized_folder_capture not in normalized_file_capture:
                    # Only warn if they're completely different
                    self.warnings.append(
                        f"Capture name mismatch - folder: '{capture_name}', filename: '{file_capture_name}' in {self._format_path(file_path, capture_name, obj_name)}"
                    )
        
        elif file_type == 'annot':
            if not self.ANNOT_PATTERN.match(filename):
                self.errors.append(
                    f"Invalid annotation filename format in {self._format_path(parent_path, capture_name, obj_name)}: {filename}"
                )
                self.stats['invalid_filenames'] += 1
                return
            
            # Check if capture name in filename matches folder structure
            parts = filename.split('_')
            if len(parts) >= 3:
                file_capture_name = parts[1]
                # Normalize both names for comparison (convert to lowercase and replace _ with -)
                normalized_file_capture = file_capture_name.lower().replace('_', '-')
                normalized_folder_capture = capture_name.lower().replace('_', '-')
                
                # Check if file capture name is contained in folder name or vice versa
                if normalized_file_capture not in normalized_folder_capture and normalized_folder_capture not in normalized_file_capture:
                    self.warnings.append(
                        f"Capture name mismatch - folder: '{capture_name}', filename: '{file_capture_name}' in {self._format_path(file_path, capture_name, obj_name)}"
                    )
        
        self.stats['valid_filenames'] += 1
    
    def _register_file(self, file_path):
        """Register a file for duplicate detection."""
        filename = file_path.name
        mtime = os.path.getmtime(file_path)
        
        if filename not in self.filename_registry:
            self.filename_registry[filename] = []
        
        self.filename_registry[filename].append((file_path, mtime))
    
    def _check_for_duplicates(self):
        """Check for duplicate filenames across all folders."""
        duplicates_found = False
        
        for filename, occurrences in sorted(self.filename_registry.items()):
            if len(occurrences) > 1:
                duplicates_found = True
                self.stats['duplicate_files'] = self.stats.get('duplicate_files', 0) + 1
                
                

                # Create warning message with all duplicate paths
                warning_lines = [f"DUPLICATE FILENAME FOUND: {filename}"]

                splits_with_duplicate = []
                for path, mtime in occurrences:
                    from datetime import datetime
                    mod_date = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
                    warning_lines.append(f"  Path: {path}")
                    warning_lines.append(f"  Modified: {BOLD}{mod_date}{RESET}")
                    
                    if self.mode == 'train':
                        # Determine split from path
                        relative_parts = path.relative_to(self.base_dir).parts
                        if relative_parts:
                            possible_split = relative_parts[0]
                            if possible_split in ['train', 'val', 'test']:
                                splits_with_duplicate.append(possible_split)
                
                # Check if there are different train/test/val entries in split array
                if self.mode == 'train' and len(set(splits_with_duplicate)) > 1:
                    warning_lines.append(f"  {RED}{BOLD}   CRITICAL: Duplicate found across different splits: {', '.join(sorted(set(splits_with_duplicate)))}{RESET}")
                    # This is a critical error - treat it as an error not a warning
                    self.errors.append('\n'.join(warning_lines))
                    self.stats['cross_split_duplicates'] = self.stats.get('cross_split_duplicates', 0) + 1
                else:
                    # Regular duplicate within same split/folder - just a warning
                    warning_lines.append(f"  {YELLOW}Duplicate found in: {', '.join(sorted(set(splits_with_duplicate)))}{RESET}")

                    self.warnings.append('\n'.join(warning_lines))

    
    def print_report(self):
        """Print validation report."""
        BOLD = '\033[1m'
        YELLOW = '\033[93m'
        RED = '\033[91m'
        RESET = '\033[0m'
        GREEN = '\033[92m'

        print("\n" + "=" * 70)
        print("DATA STRUCTURE VALIDATION REPORT")
        print("=" * 70)
        print(f"Directory: {self.base_dir}")
        print(f"Mode: {self.mode}")
        print("-" * 70)
        
        # Print statistics
        print("\nSTATISTICS:")
        if self.mode == 'collection':
            print(f"  Capture folders: {self.stats['capture_folders']}")
            print(f"  Object folders: {self.stats['object_folders']}")
            if self.stats['background_folders'] > 0:
                print(f"  Background folders: {self.stats['background_folders']}")
        elif self.mode == 'train':
            if self.stats.get('split_folders', 0) > 0:
                print(f"  Split folders found: {self.stats['split_folders']}")
            if len(self.all_categories) > 0:
                print(f"  Total unique categories: {len(self.all_categories)}")
                # Show per-split breakdown
                for split in ['train', 'val', 'test']:
                    if self.stats.get(f'{split}_categories', 0) > 0:
                        print(f"    - {split}: {self.stats[f'{split}_categories']} categories")
                
                # Verbose: show actual category names
                if self.verbose:
                    # ANSI color codes
                    GREEN = '\033[92m'
                    BLUE = '\033[94m'
                    YELLOW = '\033[93m'
                    RESET = '\033[0m'
                    
                    # Determine which categories are in which splits
                    train_cats = self.split_categories.get('train', set())
                    val_cats = self.split_categories.get('val', set())
                    test_cats = self.split_categories.get('test', set())
                    
                    # Find common and unique categories
                    common_train_val = train_cats & val_cats
                    train_only = train_cats - val_cats - test_cats
                    val_only = val_cats - train_cats - test_cats
                    
                    print(f"\n  Categories found:")
                    for split in ['train', 'val', 'test']:
                        if split in self.split_categories and self.split_categories[split]:
                            categories = sorted(self.split_categories[split])
                            print(f"    {split}:")
                            for cat in categories:
                                # Color code based on presence in splits
                                if cat in common_train_val:
                                    color = GREEN
                                    marker = "✓"
                                elif split == 'train' and cat in train_only:
                                    color = BLUE
                                    marker = "■"
                                elif split == 'val' and cat in val_only:
                                    color = YELLOW
                                    marker = "▲"
                                else:
                                    color = RESET
                                    marker = "-"
                                
                                print(f"      {color}{marker} {cat}{RESET}")
        else:  # capture mode
            print(f"  Object folders: {self.stats['object_folders']}")
            if self.stats['background_folders'] > 0:
                print(f"  Background folders: {self.stats['background_folders']}")
        
        print(f"  Total images: {self.stats['total_images']}")
        if self.mode == 'train':
            # Show per-split image breakdown
            for split in ['train', 'val', 'test']:
                if self.stats.get(f'{split}_images', 0) > 0:
                    print(f"    - {split}: {self.stats[f'{split}_images']} images")
        else:
            if self.stats['background_images'] > 0:
                print(f"    - Background images: {self.stats['background_images']}")
            if self.stats['object_images'] > 0:
                print(f"    - Object images: {self.stats['object_images']}")
        
        print(f"  Total annotations: {self.stats['total_annots']}")
        if self.mode == 'train':
            # Show per-split annotation breakdown
            for split in ['train', 'val', 'test']:
                if self.stats.get(f'{split}_annots', 0) > 0:
                    print(f"    - {split}: {self.stats[f'{split}_annots']} annotations")
        
        if self.mode != 'train':
            print(f"  Valid filenames: {self.stats['valid_filenames']}")
            if self.stats['invalid_filenames'] > 0:
                print(f"  Invalid filenames: {self.stats['invalid_filenames']}")
        
        if self.stats.get('duplicate_files', 0) > 0:
            print(f"  Duplicate filenames found: {self.stats['duplicate_files']}")
            if self.stats.get('cross_split_duplicates', 0) > 0:
                print(f"    {RED}  Cross-split duplicates (CRITICAL): {self.stats['cross_split_duplicates']}{RESET}")
        
        # Print errors
        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"  • {error}")
        else:
            print(f"\n{GREEN} No errors found!{RESET}")
        
        # Separate empty folder infos from other warnings
        empty_folder_infos = [w for w in self.infos if 'folder is empty' in w]
        duplicate_warnings = [w for w in self.warnings if 'DUPLICATE FILENAME FOUND' in w]
        other_warnings = [w for w in self.warnings 
                         if 'folder is empty' not in w and 'DUPLICATE FILENAME FOUND' not in w]
        
        # Print duplicate warnings first (most critical)
        if duplicate_warnings:
            print(f"\n⚠️  DUPLICATE FILES DETECTED ({len(duplicate_warnings)}):")
            for warning in duplicate_warnings:
                print(f"\n{warning}")
        
        # Print non-empty folder warnings
        if other_warnings:
            print(f"\n⚠️  WARNINGS ({len(other_warnings)}):")
            for warning in other_warnings[:20]:  # Limit to first 20
                print(f"  • {warning}")
            if len(other_warnings) > 20:
                print(f"  ... and {len(other_warnings) - 20} more warnings")
        
        
        # Print category mismatch warnings
        if self.category_mismatches:
            print(f"\n⚠️  INCORRECT ANNOTATION CATEGORIES ({len(self.category_mismatches)}):")            
            print("   The following annotation files have category fields that don't match their folder structure:")
            for mismatch in self.category_mismatches[:20]:  # Limit to first 20
                print(f"\n  File: {mismatch['path']}")
                print(f"  Folder category: {BOLD}{YELLOW}'{mismatch['expected']}'{RESET}")
                print(f"  Annotation categories: {BOLD}{YELLOW}{mismatch['actual']}{RESET}")
                print(f"  Mismatched: {mismatch['mismatched_count']} / {mismatch['total_count']} annotations")
            if len(self.category_mismatches) > 20:
                print(f"\n  ... and {len(self.category_mismatches) - 20} more files with category mismatches")
            print(f"\n  {BOLD}💡 TIP:{RESET} These can be fixed automatically using:")
            print(f"       {BOLD}fix_category_annotations.py <directory> --run{RESET}")
        
        # Print empty folder warnings in a cleaner format if they are the only warnings
        if empty_folder_infos:
            # If there are other warnings, include empty folders in regular warnings
            print(f"\nℹ️  NOTTICE - Empty folders ({len(empty_folder_infos)}):")
            for warning in empty_folder_infos[:10]:
                folder_path = warning.split(': ')[-1]
                print(f"  - {folder_path}")
            if len(empty_folder_infos) > 10:
                print(f"  ... and {len(empty_folder_infos) - 10} more empty folders")
        print("\n" + "=" * 70)
        
        # Final verdict
        if not self.errors and not self.warnings and not self.category_mismatches and len(empty_folder_infos) == 0:
            print("✅ VALIDATION PASSED: Structure and filenames are correct!")
        elif not self.errors and len(other_warnings) == 0 and len(duplicate_warnings) == 0 and len(empty_folder_infos) > 0 and not self.category_mismatches:
            print("✅ VALIDATION PASSED: Structure and filenames are correct!")
            print("   (Some folders are empty but this is acceptable)")
        elif not self.errors and len(duplicate_warnings) > 0:
            print("⚠️  VALIDATION PASSED WITH WARNINGS: Duplicate files detected!")
            print("   It is imperative to remove duplicates before training.")
            if self.category_mismatches:
                print("   Also found annotation files with incorrect category fields.")
        elif not self.errors and self.category_mismatches:
            print("⚠️  VALIDATION PASSED WITH WARNINGS: Annotation category mismatches detected!")
            print(f"   Fix these before training using {BOLD}fix_category_annotations.py{RESET}")
        elif not self.errors:
            print("⚠️  VALIDATION PASSED WITH WARNINGS: Check warnings above.")
            if self.mode != 'train':
                print("   Consider using 2_rename_files.py to fix common filename issues.")
        else:
            # Check if errors include cross-split duplicates
            if self.stats.get('cross_split_duplicates', 0) > 0 and self.mode == 'train': 
                print(f"{RED}{BOLD}❌ VALIDATION FAILED: CRITICAL - Cross-split duplicates detected!{RESET}")
                print(f"   {RED}{BOLD}Found {self.stats['cross_split_duplicates']} file(s) duplicated across train/val/test splits.{RESET}")
                print("   This will cause data leakage and MUST be fixed before training!")
            else:
                print("❌ VALIDATION FAILED: Fix errors above.")
                if self.mode != 'train':
                    print("   Consider using 1_organize_into_images_annots.py to fix structure issues.")
                    print("   Consider using 2_rename_files.py to fix common filename issues.")
        print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Validate data structure and filename conventions for collection, capture, or training data folders.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COLLECTION/CAPTURE MODE - Expected folder structure:
  collection/
  └── capture/
      ├── background/                    (optional)
      │   ├── img_<capture-name>_<iso_timestamp>.png
      │   └── ...
      ├── object1/
      │   ├── images/
      │   │   ├── img_<capture-name>_<iso_timestamp>.png
      │   │   └── ...
      │   └── annots/
      │       ├── annot_<capture-name>_<iso_timestamp>.json
      │       └── ...
      └── object2/
          ├── images/
          └── annots/

TRAIN MODE - Expected folder structure:
  dataset/
  ├── train/
  │   ├── category1/
  │   │   └── image1.png (...)
  │   └── category2/
  │       ├── images/
  │       │   └── image1.png (...)
  │       └── annots/
  │           └── annot1.json (...)
  ├── val/
  │   └── category1/
  │       └── image2.png (...)
  └── test/
      └── category1/
          └── image3.png (...)

Note: In train mode, images can be directly in category folders OR in an images/ subfolder.
      Empty split folders (e.g., empty val/) are acceptable.
      NO DUPLICATES are allowed across any folders.

Filename conventions (collection/capture mode):
  Images:      img_<capture-name>_YYYY-MM-DDTHH-MM-SS-mmm.png
  Annotations: annot_<capture-name>_YYYY-MM-DDTHH-MM-SS-mmm.json
  
Example:
  img_jolly-giraffe_2024-11-14T12-35-46-485.png
  annot_jolly-giraffe_2024-11-14T12-35-46-485.json
        """
    )
    
    parser.add_argument(
        "directory",
        help="Path to collection, capture, or training data folder to validate"
    )
    
    parser.add_argument(
        "--mode", "-m",
        choices=['collection', 'capture', 'train'],
        default='capture',
        help="Validation mode: 'collection' (has multiple captures), 'capture' (single capture folder), or 'train' (train/val/test splits). Default: capture"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action='store_true',
        help="Print detailed information including category names for each split (train mode only)"
    )
    
    args = parser.parse_args()
    
    # Run validation
    validator = DataValidator(args.directory, args.mode, args.verbose)
    is_valid = validator.validate()
    validator.print_report()
    
    # Exit with appropriate code
    exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
