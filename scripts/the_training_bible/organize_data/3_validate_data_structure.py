#!/usr/bin/env python3
import os
import re
import argparse
from collections import defaultdict
from pathlib import Path


class DataValidator:
    """Validates data structure and filename conventions for collection/capture folders."""
    
    # Expected filename patterns - only hyphens allowed in capture device names, no underscores
    IMG_PATTERN = re.compile(r'^img_[a-zA-Z0-9\-]+_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}\.png$')
    ANNOT_PATTERN = re.compile(r'^annot_[a-zA-Z0-9\-]+_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}\.json$')
    
    def __init__(self, base_dir, mode='collection'):
        """
        Initialize validator.
        
        Args:
            base_dir: Path to collection or capture folder
            mode: 'collection' or 'capture' - determines validation level
        """
        self.base_dir = Path(base_dir).resolve()
        self.mode = mode
        self.errors = []
        self.warnings = []
        self.stats = defaultdict(int)
    
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
        
    def validate(self):
        """Run validation and return results."""
        if not self.base_dir.exists():
            self.errors.append(f"Directory does not exist: {self.base_dir}")
            return False
            
        if self.mode == 'collection':
            self._validate_collection()
        elif self.mode == 'capture':
            self._validate_capture()
        else:
            self.errors.append(f"Invalid mode: {self.mode}")
            return False
            
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
            self.warnings.append(f"Images folder is empty: {self._format_path(images_path, capture_name, obj_name)}")
            return
        
        self.stats['total_images'] += len(images)
        self.stats['object_images'] += len(images)  # Track object images separately
        
        for img in images:
            self._validate_filename(img, capture_name, 'image', obj_path, capture_path, obj_name)
    
    def _validate_annots_folder(self, annots_path, capture_name, obj_path, capture_path, obj_name):
        """Validate annotations folder contents."""
        annots = list(annots_path.glob("*.json"))
        
        if not annots:
            self.warnings.append(f"Annotations folder is empty: {self._format_path(annots_path, capture_name, obj_name)}")
            return
        
        self.stats['total_annots'] += len(annots)
        
        for annot in annots:
            self._validate_filename(annot, capture_name, 'annot', obj_path, capture_path, obj_name)
    
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
    
    def print_report(self):
        """Print validation report."""
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
        print(f"  Total images: {self.stats['total_images']}")
        if self.stats['background_images'] > 0:
            print(f"    - Background images: {self.stats['background_images']}")
        if self.stats['object_images'] > 0:
            print(f"    - Object images: {self.stats['object_images']}")
        print(f"  Total annotations: {self.stats['total_annots']}")
        print(f"  Valid filenames: {self.stats['valid_filenames']}")
        if self.stats['invalid_filenames'] > 0:
            print(f"  Invalid filenames: {self.stats['invalid_filenames']}")
        
        # Print errors
        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"  • {error}")
        else:
            print("\n✅ No errors found!")
        
        # Separate empty folder warnings from other warnings
        empty_folder_warnings = [w for w in self.warnings if 'folder is empty' in w]
        other_warnings = [w for w in self.warnings if 'folder is empty' not in w]
        
        # Print non-empty folder warnings
        if other_warnings:
            print(f"\n⚠️  WARNINGS ({len(other_warnings)}):")
            for warning in other_warnings[:20]:  # Limit to first 20
                print(f"  • {warning}")
            if len(other_warnings) > 20:
                print(f"  ... and {len(other_warnings) - 20} more warnings")
        
        # Print empty folder warnings in a cleaner format if they are the only warnings
        if empty_folder_warnings and not other_warnings:
            print(f"\nNOTE:")
            print(f"The following folders are empty:")
            for warning in empty_folder_warnings:
                # Extract the folder path from the warning message
                folder_path = warning.split(': ')[-1]
                print(f"  - {folder_path}")
        elif empty_folder_warnings and other_warnings:
            # If there are other warnings, include empty folders in regular warnings
            print(f"\n⚠️  ADDITIONAL WARNINGS - Empty folders ({len(empty_folder_warnings)}):")
            for warning in empty_folder_warnings[:10]:
                folder_path = warning.split(': ')[-1]
                print(f"  - {folder_path}")
            if len(empty_folder_warnings) > 10:
                print(f"  ... and {len(empty_folder_warnings) - 10} more empty folders")
        
        print("\n" + "=" * 70)
        
        # Final verdict
        if not self.errors and not self.warnings:
            print("✅ VALIDATION PASSED: Structure and filenames are correct!")
        elif not self.errors and len(other_warnings) == 0 and len(empty_folder_warnings) > 0:
            print("✅ VALIDATION PASSED: Structure and filenames are correct!")
            print("   (Some folders are empty but this is acceptable)")
        elif not self.errors:
            print("⚠️  VALIDATION PASSED WITH WARNINGS: Check warnings above.")
            print("   Consider using 2_rename_files.py to fix common filename issues.")
        else:
            print("❌ VALIDATION FAILED: Fix errors above.")
            print("   Consider using 1_organize_into_images_annots.py to fix structure issues.")
            print("   Consider using 2_rename_files.py to fix common filename issues.")
        print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Validate data structure and filename conventions for collection or capture folders.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Expected folder structure:
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

Filename conventions:
  Images:      img_<capture-name>_YYYY-MM-DDTHH-MM-SS-mmm.png
  Annotations: annot_<capture-name>_YYYY-MM-DDTHH-MM-SS-mmm.json
  
Example:
  img_jolly-giraffe_2024-11-14T12-35-46-485.png
  annot_jolly-giraffe_2024-11-14T12-35-46-485.json
        """
    )
    
    parser.add_argument(
        "directory",
        help="Path to collection or capture folder to validate"
    )
    
    parser.add_argument(
        "--mode", "-m",
        choices=['collection', 'capture'],
        default='capture',
        help="Validation mode: 'collection' (has multiple captures) or 'capture' (single capture folder). Default: capture"
    )
    
    args = parser.parse_args()
    
    # Run validation
    validator = DataValidator(args.directory, args.mode)
    is_valid = validator.validate()
    validator.print_report()
    
    # Exit with appropriate code
    exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
