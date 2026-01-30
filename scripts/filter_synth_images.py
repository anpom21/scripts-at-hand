#!/usr/bin/env python3
"""
Filter out erroneous synthetic images based on white pixel content.

This script analyzes images in a directory and flags those with excessive
white pixels by analyzing their histograms. Flagged images are moved to
a flagged/ folder at the same level as the category they were found in.

The script supports recursive searching:
- Images directly in category folders (e.g., normal_wood/*.jpg)
- Images in capture/images folders (e.g., capture_001/images/*.jpg)
"""

import argparse
import json
import shutil
from pathlib import Path
from typing import List, Tuple, Dict, Optional

import cv2
import numpy as np
from tqdm import tqdm


def decode_rle_mask(start_positions: List[int], run_lengths: List[int], image_shape: Tuple[int, int]) -> np.ndarray:
    """
    Decode RLE (Run-Length Encoding) mask from segmentation data.
    
    Args:
        start_positions: List of starting positions in the flattened image
        run_lengths: List of run lengths for each segment
        image_shape: Tuple of (height, width)
        
    Returns:
        Binary mask as numpy array
    """
    mask = np.zeros(image_shape[0] * image_shape[1], dtype=np.uint8)
    
    for start, length in zip(start_positions, run_lengths):
        mask[start : start + length] = 1
    
    return mask.reshape(image_shape)


def read_image_safe(image_path: Path) -> Optional[np.ndarray]:
    """
    Read image using a path-safe method that handles special characters.
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Image array or None if it cannot be read
    """
    if not image_path.exists():
        return None
    try:
        data = np.fromfile(str(image_path), dtype=np.uint8)
        if data.size == 0:
            return None
        img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
        if img is not None:
            return img
    except Exception:
        pass

    try:
        data = np.frombuffer(image_path.read_bytes(), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except Exception:
        return None


def load_annotation(image_path: Path) -> Tuple[Optional[Dict], bool]:
    """
    Load annotation file for a given image.
    
    Looks for annotation files with matching name and .json extension
    in the same directory as the image.
    
    Handles naming patterns:
    - img_<name>.png -> annot_<name>.json
    - <name>.png -> annot_<name>.json
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Tuple of (annotation_dict_or_none, annotation_found)
    """
    stem = image_path.stem
    
    # Remove 'img_' prefix if present
    if stem.startswith('img_'):
        stem_without_prefix = stem[4:]  # Remove 'img_' prefix
    else:
        stem_without_prefix = stem
    
    # Determine annotation search directories
    annot_dirs = [image_path.parent]
    if image_path.parent.name.lower() == "images":
        sibling_annots = image_path.parent.parent / "annots"
        if sibling_annots.exists():
            annot_dirs.insert(0, sibling_annots)
    
    # Try to find annotation file with the stem
    annot_path = None
    for annot_dir in annot_dirs:
        candidate = annot_dir / f"annot_{stem_without_prefix}.json"
        if candidate.exists():
            annot_path = candidate
            break
    
    if annot_path and annot_path.exists():
        try:
            with open(annot_path, 'r') as f:
                return json.load(f), True
        except Exception:
            return None, False
    
    # Fallback: try with full stem (in case naming is different)
    annot_path = None
    for annot_dir in annot_dirs:
        candidate = annot_dir / f"annot_{stem}.json"
        if candidate.exists():
            annot_path = candidate
            break
    if annot_path and annot_path.exists():
        try:
            with open(annot_path, 'r') as f:
                return json.load(f), True
        except Exception:
            return None, False
    
    # Final fallback: try without 'annot_' prefix
    annot_path = None
    for annot_dir in annot_dirs:
        candidate = annot_dir / f"{stem_without_prefix}.json"
        if candidate.exists():
            annot_path = candidate
            break
    if annot_path and annot_path.exists():
        try:
            with open(annot_path, 'r') as f:
                return json.load(f), True
        except Exception:
            return None, False
    
    return None, False


def count_white_pixels_in_mask(
    image_path: Path,
    annotation: Optional[Dict] = None,
    white_threshold: int = 250
) -> Tuple[float, int, int, bool]:
    """
    Count the percentage of white pixels in the image's mask region.
    
    If annotation is provided, only counts pixels within the segmentation mask.
    If no annotation, counts all pixels in the image (fallback method).
    
    Args:
        image_path: Path to the image file
        annotation: Optional annotation dictionary with segmentation data
        white_threshold: Pixel value threshold to consider as white (0-255)
        
    Returns:
        Tuple of (white_pixel_percentage, white_pixel_count, total_pixels_in_mask, used_fallback)
        where used_fallback is True if no annotation was available
    """
    # Read image
    img = read_image_safe(image_path)
    
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")
    
    # Convert to grayscale for easier analysis
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    image_shape = gray.shape
    
    # Get mask from annotation if available
    if annotation and 'annotations' in annotation and len(annotation['annotations']) > 0:
        # Use the first annotation's segmentation
        seg_data = annotation['annotations'][0].get('segmentation', {})
        start_positions = seg_data.get('start_positions', [])
        run_lengths = seg_data.get('run_lengths', [])
        
        if start_positions and run_lengths:
            mask = decode_rle_mask(start_positions, run_lengths, image_shape)
            used_fallback = False
        else:
            mask = np.ones(image_shape, dtype=np.uint8)
            used_fallback = True
    else:
        mask = np.ones(image_shape, dtype=np.uint8)
        used_fallback = True
    
    # Count white pixels only within the mask region
    masked_pixels = gray[mask == 1]
    white_pixels = np.sum(masked_pixels >= white_threshold)
    total_pixels = len(masked_pixels)
    
    if total_pixels == 0:
        return 0.0, 0, 0, used_fallback
    
    white_percentage = (white_pixels / total_pixels) * 100
    
    return white_percentage, white_pixels, total_pixels, used_fallback


def find_images_recursive(root_dir: Path) -> Dict[Path, List[Path]]:
    """
    Recursively find all image files and group them by their parent directory.
    
    This handles two patterns:
    1. Images directly in category folders (e.g., normal_wood/*.jpg)
    2. Images in capture/images folders (e.g., capture_001/images/*.jpg)
    
    Args:
        root_dir: Root directory to search from
        
    Returns:
        Dictionary mapping image parent directories to lists of image paths
    """
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}
    excluded_dirs = {"annots", "annotations"}
    images_by_dir = {}
    
    # Recursively find all image files
    for path in root_dir.rglob('*'):
        if path.is_file() and path.suffix.lower() in image_extensions:
            if any(part.lower() in excluded_dirs for part in path.parts):
                continue
            parent = path.parent
            if parent not in images_by_dir:
                images_by_dir[parent] = []
            images_by_dir[parent].append(path)
    
    # Sort images in each directory
    for parent_dir in images_by_dir:
        images_by_dir[parent_dir] = sorted(images_by_dir[parent_dir])
    
    return images_by_dir


def find_images(images_dir: Path) -> List[Path]:
    """
    Find all image files in the given directory.
    
    Args:
        images_dir: Directory containing images
        
    Returns:
        List of image file paths
    """
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'}
    excluded_dirs = {"annots", "annotations"}
    if any(part.lower() in excluded_dirs for part in images_dir.parts):
        return []
    images = []
    
    for ext in image_extensions:
        images.extend(images_dir.glob(f"*{ext}"))
        images.extend(images_dir.glob(f"*{ext.upper()}"))
    
    return sorted(images)


def filter_images(
    images_dir: Path,
    white_pixel_threshold: float = 30.0,
    white_value_threshold: int = 250,
    verbose: bool = False
) -> Tuple[List[Tuple[Path, float, int, int, bool]], List[Tuple[Path, bool]]]:
    """
    Filter images based on white pixel percentage in mask region.
    
    Args:
        images_dir: Directory containing images
        white_pixel_threshold: Percentage threshold for white pixels (0-100)
        white_value_threshold: Pixel value threshold to consider as white (0-255)
        verbose: If True, print detailed information for each image
        
    Returns:
        Tuple of (flagged_images_with_stats, clean_images)
        flagged_images_with_stats is a list of (path, percentage, count, total, used_fallback) tuples
        clean_images is a list of (path, used_fallback) tuples
    """
    # Find all images
    images = find_images(images_dir)
    
    if not images:
        print(f"No images found in {images_dir}")
        return [], []
    
    print(f"Found {len(images)} images in {images_dir}")
    print(f"Analyzing images for white pixel content in mask regions...")
    print(f"  White pixel threshold: {white_pixel_threshold}%")
    print(f"  White value threshold: {white_value_threshold}/255")
    print()
    
    flagged_images = []
    clean_images = []
    
    # Analyze each image
    for img_path in tqdm(images, desc="Analyzing images"):
        try:
            # Load annotation if available
            annotation, annotation_found = load_annotation(img_path)
            
            white_pct, white_count, total_count, used_fallback = count_white_pixels_in_mask(
                img_path, annotation, white_value_threshold
            )
            
            fallback_indicator = "[FALLBACK]" if used_fallback else "[MASK]"
            
            if white_pct >= white_pixel_threshold:
                flagged_images.append((img_path, white_pct, white_count, total_count, used_fallback))
                if verbose:
                    print(f"  [FLAGGED] {fallback_indicator} {img_path.name}: {white_pct:.2f}% ({white_count}/{total_count} pixels)")
            else:
                clean_images.append((img_path, used_fallback))
                if verbose:
                    print(f"  [CLEAN]   {fallback_indicator} {img_path.name}: {white_pct:.2f}% ({white_count}/{total_count} pixels)")
                
        except Exception as e:
            print(f"  [ERROR] Failed to process {img_path.name}: {e}")
    
    return flagged_images, clean_images


def move_flagged_images(
    flagged_images: List[Tuple[Path, float, int, int, bool]],
    images_dir: Path,
    fix: bool = False
) -> None:
    """
    Move flagged images to flagged/ folder at the same level as the images directory.
    
    For images in pattern like:
    - category/image.jpg -> category/flagged/image.jpg
    - category/capture/images/image.jpg -> category/capture/flagged/image.jpg
    
    Args:
        flagged_images: List of (image_path, white_pct, white_count, total_count, used_fallback) tuples
        images_dir: Directory where images were found
        fix: If False, don't actually move files
    """
    if not flagged_images:
        print("\nNo images were flagged. Nothing to move.")
        return
    
    # Determine the flagged directory based on the images directory structure
    # If images_dir is named 'images', create flagged as a sibling directory
    # Otherwise, create flagged as a subdirectory of images_dir
    if images_dir.name.lower() == 'images':
        flagged_dir = images_dir.parent / "flagged"
    else:
        flagged_dir = images_dir / "flagged"
    
    if not fix:
        print(f"\n[DRY RUN] Would create directory: {flagged_dir}")
        print(f"[DRY RUN] Would move {len(flagged_images)} images to {flagged_dir}")
        return
    
    # Create the flagged directory
    flagged_dir.mkdir(exist_ok=True)
    print(f"\nCreated flagged directory: {flagged_dir}")
    
    # Move flagged images
    print(f"Moving {len(flagged_images)} flagged images...")
    for img_path, white_pct, white_count, total_count, used_fallback in tqdm(flagged_images, desc="Moving images"):
        dest_path = flagged_dir / img_path.name
        
        # Handle name conflicts
        counter = 1
        while dest_path.exists():
            stem = img_path.stem
            suffix = img_path.suffix
            dest_path = flagged_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        
        shutil.move(str(img_path), str(dest_path))
    
    print(f"Successfully moved {len(flagged_images)} images to {flagged_dir}")


def main():
    def visualize_analysis(
        image_path: Path,
        annotation: Optional[Dict] = None,
        white_threshold: int = 250
    ) -> bool:
        """
        Visualize image with mask overlay and white pixel highlights.
    
        Opens the image with:
        1. Original image with mask overlay (green, 30% opacity)
        2. White pixels highlighted (red overlay)
    
        Press any key to move to the next image, 'q' to quit.
    
        Args:
            image_path: Path to the image file
            annotation: Optional annotation dictionary with segmentation data
            white_threshold: Pixel value threshold to consider as white (0-255)
        
        Returns:
            True if user pressed 'q' to quit, False otherwise
        """
        # Read image
        img = read_image_safe(image_path)
        if img is None:
            print(f"Could not read image: {image_path}")
            return False
    
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        image_shape = gray.shape
    
        # Get mask from annotation if available
        if annotation and 'annotations' in annotation and len(annotation['annotations']) > 0:
            seg_data = annotation['annotations'][0].get('segmentation', {})
            start_positions = seg_data.get('start_positions', [])
            run_lengths = seg_data.get('run_lengths', [])
        
            if start_positions and run_lengths:
                mask = decode_rle_mask(start_positions, run_lengths, image_shape)
                has_annotation = True
            else:
                mask = np.ones(image_shape, dtype=np.uint8)
                has_annotation = False
        else:
            mask = np.ones(image_shape, dtype=np.uint8)
            has_annotation = False
    
        # Calculate statistics
        masked_pixels = gray[mask == 1]
        white_pixels = np.sum(masked_pixels >= white_threshold)
        total_pixels = len(masked_pixels)
        white_percentage = (white_pixels / total_pixels * 100) if total_pixels > 0 else 0.0
    
        # Create visualization
        img_display = img.copy()
    
        # Overlay mask in transparent green
        mask_overlay = np.zeros_like(img)
        mask_overlay[:, :, 1] = (mask * 200).astype(np.uint8)  # Green channel
        img_display = cv2.addWeighted(img_display, 0.7, mask_overlay, 0.3, 0)
    
        # Highlight white pixels in red
        white_pixel_mask = np.zeros_like(gray)
        masked_pixels_indices = np.where(mask == 1)
        for y, x in zip(masked_pixels_indices[0], masked_pixels_indices[1]):
            if gray[y, x] >= white_threshold:
                white_pixel_mask[y, x] = 1
    
        white_overlay = np.zeros_like(img)
        white_overlay[:, :, 2] = (white_pixel_mask * 255).astype(np.uint8)  # Red channel
        img_display = cv2.addWeighted(img_display, 1.0, white_overlay, 0.5, 0)
    
        # Add text information
        cv2.putText(img_display, f"File: {image_path.name}", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
        annot_status = "WITH ANNOTATION" if has_annotation else "NO ANNOTATION (FALLBACK)"
        color = (255, 255, 255) if has_annotation else (0, 165, 255)
        cv2.putText(img_display, f"Status: {annot_status}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    
        cv2.putText(img_display, f"White Pixels: {white_percentage:.2f}% ({white_pixels}/{total_pixels})", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    
        cv2.putText(img_display, "Press any key to continue, 'q' to quit", (10, img_display.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    
        # Display image
        cv2.imshow(f"Image Analysis", img_display)
        key = cv2.waitKey(0)
    
        if key == ord('q'):
            cv2.destroyAllWindows()
            return True  # Signal to quit
    
        return False

    parser = argparse.ArgumentParser(
        description="Filter out synthetic images with excessive white pixels in mask regions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Filter images recursively from a root directory
  %(prog)s /path/to/dataset
  
  # Show verbose output with pixel counts for each image
  %(prog)s /path/to/dataset -v
  
  # Use custom white pixel threshold of 40%%
  %(prog)s /path/to/dataset --white-pixel-threshold 40
  
  # Adjust white value threshold (pixel brightness)
  %(prog)s /path/to/dataset --white-value-threshold 240
  
  # Dry run to see what would be flagged without moving files
  %(prog)s /path/to/dataset --dry-run
    # Visualize flagged images with mask overlay and white pixel highlights
    %(prog)s /path/to/dataset --visualize

Analysis Details:
  - Analyzes white pixels ONLY within the segmentation mask region
  - Looks for annotation files (annot_<image_name>.json) in the same directory
  - Falls back to analyzing whole image if no annotation is found
  
The script supports two directory patterns:
  1. Images directly in category folders: category/*.jpg
  2. Images in capture folders: category/capture/images/*.jpg
  
Flagged images are always moved to: category/flagged/ or category/capture/flagged/
        """
    )
    
    parser.add_argument(
        "root_dir",
        type=Path,
        help="Path to the root directory containing images (will search recursively)"
    )
    
    parser.add_argument(
        "--white-pixel-threshold",
        type=float,
        default=90.0,
        help="Percentage threshold for white pixels (0-100). Images with more white pixels "
             "than this will be flagged. Default: 90.0"
    )
    
    parser.add_argument(
        "--white-value-threshold",
        type=int,
        default=250,
        help="Pixel value threshold to consider as white (0-255). Pixels with grayscale "
             "value >= this are counted as white. Default: 250"
    )
    
    parser.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="Analyze images and report findings without moving any files"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed information for each image (white pixel percentage and count)"
    )
    
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Open images in OpenCV for visualization with mask overlay and white pixel highlights"
    )
    args = parser.parse_args()
    
    # Validate inputs
    root_dir = args.root_dir.resolve()
    
    if not root_dir.exists():
        parser.error(f"Directory does not exist: {root_dir}")
    
    if not root_dir.is_dir():
        parser.error(f"Path is not a directory: {root_dir}")
    
    if not (0 <= args.white_pixel_threshold <= 100):
        parser.error("white-pixel-threshold must be between 0 and 100")
    
    if not (0 <= args.white_value_threshold <= 255):
        parser.error("white-value-threshold must be between 0 and 255")
    
    print("=" * 70)
    print("Synthetic Image Filter - White Pixel Detection in Mask Regions")
    print("=" * 70)
    print(f"Root directory: {root_dir}")
    print()
    
    # Find all images recursively
    print("Searching for images recursively...")
    images_by_dir = find_images_recursive(root_dir)
    
    if not images_by_dir:
        print(f"No images found in {root_dir} or its subdirectories")
        return
    
    total_images = sum(len(imgs) for imgs in images_by_dir.values())
    print(f"Found {total_images} images in {len(images_by_dir)} directories")
    print()
    
    # Process each directory
    all_flagged = []
    all_clean = []
    fallback_count = 0
    
    for images_dir, images in images_by_dir.items():
        print(f"\nProcessing: {images_dir.relative_to(root_dir)}")
        print(f"  Found {len(images)} images")
        
        # Filter images in this directory
        flagged_images, clean_images = filter_images(
            images_dir,
            args.white_pixel_threshold,
            args.white_value_threshold,
            args.verbose
        )
        
        all_flagged.extend(flagged_images)
        all_clean.extend(clean_images)
        
        # Count fallback usage
        for _, used_fallback in clean_images:
            if used_fallback:
                fallback_count += 1
        for _, _, _, _, used_fallback in flagged_images:
            if used_fallback:
                fallback_count += 1
        
        # Move flagged images for this directory
        if flagged_images:
            move_flagged_images(flagged_images, images_dir, args.fix)
    
    # Print overall summary
        
            # Visualize images if requested
            if args.visualize:
                print("\n  Opening images for visualization...")
                for img_path, white_pct, white_count, total_count, used_fallback in flagged_images:
                    annotation, _ = load_annotation(img_path)
                    if visualize_analysis(img_path, annotation, args.white_value_threshold):
                        break
    
        # Print overall summary
        print()
    print()
    print("=" * 70)
    print("OVERALL SUMMARY")
    print("=" * 70)
    print(f"Total images analyzed: {len(all_flagged) + len(all_clean)}")
    print(f"Flagged images (excessive white): {len(all_flagged)}")
    print(f"Clean images: {len(all_clean)}")
    print(f"Images analyzed with fallback method (no annotation): {fallback_count}")
    
    if all_flagged:
        flagged_pct = (len(all_flagged) / (len(all_flagged) + len(all_clean)) * 100)
        print(f"\nFlagged images: {flagged_pct:.1f}%")
        
        if args.verbose:
            print("\nFlagged image details:")
            for img_path, white_pct, white_count, total_count, used_fallback in sorted(all_flagged, key=lambda x: x[1], reverse=True):
                fallback_indicator = "[FALLBACK]" if used_fallback else "[MASK]"
                print(f"  {fallback_indicator} {img_path.name}: {white_pct:.2f}% ({white_count}/{total_count} pixels)")
    
    print()
    print("Done!")


if __name__ == "__main__":
    main()
