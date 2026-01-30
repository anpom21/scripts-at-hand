#!/usr/bin/env python3
"""
Analyze the distribution of base images used in synthetic data generation.

This script examines synthetic annotation files to count how frequently each
base image from a collection is used, and visualizes the distribution.
"""

import json
import os
import sys
from pathlib import Path
from collections import Counter
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator


# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def find_images_with_annots(collection_folder, category):
    """
    Find all images with matching annotation files in the given category.
    
    Args:
        collection_folder: Path to the collections folder
        category: Category name (e.g., 'impregnated_wood')
    
    Returns:
        List of image filenames
    """
    image_files = []
    collection_path = Path(collection_folder)
    
    # Search through all subdirectories for the category
    for subdir in collection_path.rglob(f"*/{category}/images"):
        annot_dir = subdir.parent / "annots"
        if not annot_dir.exists():
            continue
            
        # Find all images with matching annotations
        for img_file in subdir.glob("img_*.png"):
            annot_file = annot_dir / f"annot_{img_file.stem.replace('img_', '')}.json"
            if annot_file.exists():
                image_files.append(img_file.name)
    
    return image_files


def extract_base_images_from_synth(synth_category_folder):
    """
    Extract base image filenames from all synthetic annotation files.
    
    Args:
        synth_category_folder: Path to synthetic category folder
    
    Returns:
        Tuple of (list of base image filenames, dict mapping filename to full path)
    """
    base_images = []
    image_paths = {}  # Map filename to full path
    synth_path = Path(synth_category_folder)
    annot_dir = synth_path / "annots"
    
    if not annot_dir.exists():
        print(f"Error: Annotation directory not found: {annot_dir}")
        return base_images
    
    # Process all annotation files
    for annot_file in annot_dir.glob("annot_*.json"):
        try:
            with open(annot_file, 'r') as f:
                data = json.load(f)
            
            # Check if 'synth' section exists
            if 'synth' not in data:
                continue
            
            # Get base_images_fp list
            base_images_fp = data['synth'].get('base_images_fp', [])
            
            # Filter out background images and extract filename
            for img_path in base_images_fp:
                if '/background/' not in img_path:
                    filename = os.path.basename(img_path)
                    base_images.append(filename)
                    # Store the full path for the first occurrence
                    if filename not in image_paths:
                        image_paths[filename] = img_path
        
        except (json.JSONDecodeError, KeyError) as e:
            print(f"{Colors.WARNING}Warning: Error processing {annot_file}: {e}{Colors.ENDC}")
            continue
    
    return base_images, image_paths


def plot_distribution(frequency_counter, reference_images, image_paths):
    """
    Plot the frequency distribution of base images.
    
    Args:
        frequency_counter: Counter object with image frequencies
        reference_images: List of all reference images
        image_paths: Dict mapping filename to full path
    """
    # Get frequencies for all reference images (0 if not used)
    all_images = sorted(reference_images)
    frequencies = [frequency_counter.get(img, 0) for img in all_images]
    
    # Calculate statistics
    non_zero_frequencies = [f for f in frequencies if f > 0]
    if non_zero_frequencies:
        min_freq = min(non_zero_frequencies)
        max_freq = max(non_zero_frequencies)
        mean_freq = np.mean(non_zero_frequencies)
    else:
        min_freq = max_freq = mean_freq = 0
    
    # Print statistics
    print("\n" + Colors.BOLD + Colors.HEADER + "="*60)
    print("FREQUENCY STATISTICS")
    print("="*60 + Colors.ENDC)
    print(f"{Colors.OKCYAN}Total reference images:{Colors.ENDC} {len(all_images)}")
    print(f"{Colors.OKGREEN}Images used in synthesis:{Colors.ENDC} {len(non_zero_frequencies)}")
    print(f"{Colors.WARNING}Images not used:{Colors.ENDC} {len(all_images) - len(non_zero_frequencies)}")
    print(f"\n{Colors.OKBLUE}Minimum frequency:{Colors.ENDC} {min_freq}")
    print(f"{Colors.OKBLUE}Maximum frequency:{Colors.ENDC} {max_freq}")
    print(f"{Colors.OKBLUE}Mean frequency:{Colors.ENDC} {mean_freq:.2f}")
    if non_zero_frequencies:
        print(f"{Colors.OKBLUE}Standard deviation:{Colors.ENDC} {np.std(non_zero_frequencies):.2f}")
    else:
        print(f"{Colors.OKBLUE}Standard deviation:{Colors.ENDC} N/A")
    print(Colors.BOLD + Colors.HEADER + "="*60 + Colors.ENDC + "\n")
    
    # Create bar chart
    plt.figure(figsize=(16, 8))
    
    # If there are too many images, create a histogram instead
    if len(all_images) > 50:
        # Use integer bins for discrete frequency values
        if max_freq > 0:
            bins = np.arange(0, max_freq + 2) - 0.5  # Center bins on integers
        else:
            bins = 30
        plt.hist(frequencies, bins=bins, edgecolor='black', alpha=0.7, align='mid')
        plt.xlabel('Frequency', fontsize=12)
        plt.ylabel('Number of Images', fontsize=12)
        plt.title('Distribution of Base Image Usage Frequencies', fontsize=14, fontweight='bold')
        # Force x-axis to show every integer value
        if max_freq > 0:
            plt.xticks(range(0, int(max_freq) + 1))
        plt.grid(axis='y', alpha=0.3)
        plt.grid(axis='x', alpha=0.15, linestyle=':')
    else:
        # Bar chart for smaller datasets
        x_pos = np.arange(len(all_images))
        bars = plt.bar(x_pos, frequencies, edgecolor='black', alpha=0.7, width=0.8)
        
        # Color bars based on frequency (green for mean, red for outliers)
        if mean_freq > 0:
            for i, (bar, freq) in enumerate(zip(bars, frequencies)):
                if freq == 0:
                    bar.set_color('lightgray')
                elif freq < mean_freq * 0.5:
                    bar.set_color('orange')
                elif freq > mean_freq * 1.5:
                    bar.set_color('red')
                else:
                    bar.set_color('green')
        
        plt.xlabel('Image Index', fontsize=12)
        plt.ylabel('Frequency', fontsize=12)
        plt.title('Base Image Usage Frequency Distribution', fontsize=14, fontweight='bold')
        # Show discrete x-axis values
        step = max(1, len(all_images)//20)
        plt.xticks(x_pos[::step], [i for i in range(0, len(all_images), step)], rotation=45, ha='right')
        # Force y-axis to show only integer values
        plt.gca().yaxis.set_major_locator(MaxNLocator(integer=True))
        plt.grid(axis='y', alpha=0.3, linestyle='--')
        plt.grid(axis='x', alpha=0.15, linestyle=':')
        
        # Add legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='green', label=f'Normal (±50% of mean)'),
            Patch(facecolor='orange', label=f'Underused (<50% of mean)'),
            Patch(facecolor='red', label=f'Overused (>150% of mean)'),
            Patch(facecolor='lightgray', label='Not used')
        ]
        plt.legend(handles=legend_elements, loc='upper right')
    
    plt.tight_layout()
    plt.show()
    
    # Print top 5 most used images with full paths
    if frequency_counter:
        print(f"\n{Colors.BOLD}{Colors.OKGREEN}Top 5 Most Used Images:{Colors.ENDC}")
        print(Colors.OKCYAN + "-" * 80 + Colors.ENDC)
        for i, (img, count) in enumerate(frequency_counter.most_common(5), 1):
            full_path = image_paths.get(img, 'Path not found')
            print(f"{Colors.BOLD}{i}.{Colors.ENDC} {Colors.WARNING}[{count}x]{Colors.ENDC} {full_path}")
        
        print(f"\n{Colors.BOLD}{Colors.FAIL}Top 10 Least Used Images (excluding unused):{Colors.ENDC}")
        print(Colors.OKCYAN + "-" * 80 + Colors.ENDC)
        least_common = sorted([(img, count) for img, count in frequency_counter.items()], 
                            key=lambda x: x[1])[:10]
        for i, (img, count) in enumerate(least_common, 1):
            print(f"{Colors.BOLD}{i}.{Colors.ENDC} {Colors.WARNING}[{count}x]{Colors.ENDC} {img}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python analyze_synth_base_images.py <collection_folder> <synth_category_folder>")
        print("\nExample:")
        print("  python analyze_synth_base_images.py \\")
        print("    /home/simon/Data/Collections_wood \\")
        print("    /home/simon/Desktop/WoodDataset-2026-01/synth_no_augmentation/impregnated_wood")
        sys.exit(1)
    
    collection_folder = sys.argv[1]
    synth_category_folder = sys.argv[2]
    
    # Validate inputs
    if not os.path.exists(collection_folder):
        print(f"Error: Collection folder does not exist: {collection_folder}")
        sys.exit(1)
    
    if not os.path.exists(synth_category_folder):
        print(f"Error: Synthetic category folder does not exist: {synth_category_folder}")
        sys.exit(1)
    
    # Extract category name from synth folder path
    category = os.path.basename(synth_category_folder)
    
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'='*80}")
    print(f"  Synthetic Base Image Distribution Analysis")
    print(f"{'='*80}{Colors.ENDC}")
    print(f"{Colors.OKCYAN}Category:{Colors.ENDC} {Colors.BOLD}{category}{Colors.ENDC}")
    print(f"{Colors.OKCYAN}Collection folder:{Colors.ENDC} {collection_folder}")
    print(f"{Colors.OKCYAN}Synthetic folder:{Colors.ENDC} {synth_category_folder}")
    print()
    
    # Step 1: Find all reference images with annotations
    print(f"{Colors.BOLD}Step 1:{Colors.ENDC} Finding reference images with annotations...")
    reference_images = find_images_with_annots(collection_folder, category)
    print(f"{Colors.OKGREEN}✓{Colors.ENDC} Found {Colors.BOLD}{len(reference_images)}{Colors.ENDC} reference images with annotations")
    
    if not reference_images:
        print(f"{Colors.FAIL}Error: No reference images found!{Colors.ENDC}")
        sys.exit(1)
    
    # Step 2: Extract base images from synthetic annotations
    print(f"\n{Colors.BOLD}Step 2:{Colors.ENDC} Extracting base images from synthetic annotations...")
    base_images, image_paths = extract_base_images_from_synth(synth_category_folder)
    print(f"{Colors.OKGREEN}✓{Colors.ENDC} Found {Colors.BOLD}{len(base_images)}{Colors.ENDC} base image references in synthetic data")
    
    if not base_images:
        print(f"{Colors.FAIL}Error: No base images found in synthetic annotations!{Colors.ENDC}")
        sys.exit(1)
    
    # Step 3: Count frequencies
    print(f"\n{Colors.BOLD}Step 3:{Colors.ENDC} Counting frequencies...")
    frequency_counter = Counter(base_images)
    print(f"{Colors.OKGREEN}✓{Colors.ENDC} Processed {Colors.BOLD}{len(frequency_counter)}{Colors.ENDC} unique images")
    
    # Step 4: Plot and display results
    print(f"\n{Colors.BOLD}Step 4:{Colors.ENDC} Generating visualization...")
    plot_distribution(frequency_counter, reference_images, image_paths)


if __name__ == "__main__":
    main()
