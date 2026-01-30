#!/usr/bin/env python3
"""
Interactive mismatched image/annotation reviewer using Tkinter and PIL.

Finds image and annotation pairs that are in different category folders and provides
an interactive interface to select which category to move both files to.

Features:
- Recursively scans directory for mismatched image/annot pairs
- Displays image with two category buttons (image category and annot category)
- Shows category name, file type (image/annot), and path for each option
- Allows selection via:
  - Keyboard: Press 1 or 2 for each category
  - Mouse: Click on the category button
- Moves both image and annot to selected category
- Error checking for annots folder existence

Usage:
  python review_duplicates.py /path/to/collections/directory
"""

import argparse
import sys
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict, Counter
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont

# ANSI color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'

IMG_RE = re.compile(r'^img_(.+)\.png$', re.IGNORECASE)
ANN_RE = re.compile(r'^annot_(.+)\.json$', re.IGNORECASE)


def extract_key(filename: str, kind: str):
    """Extract the key from an image or annotation filename."""
    name = Path(filename).name
    m = IMG_RE.match(name) if kind == 'img' else ANN_RE.match(name)
    return m.group(1) if m else None


def deduce_category_dir(p: Path) -> Path:
    """
    Given a file path p (an image or annot), return the category directory.
      - if file is under .../<category>/(images|annots)/file -> category is parent of that
      - else if file is directly under .../<category>/file   -> category is its parent
    """
    parent = p.parent
    if parent.name.lower() in ('images', 'annots'):
        return parent.parent
    return parent


class MismatchInfo:
    """Stores information about a mismatched image/annotation pair."""
    def __init__(self, key: str, image_path: Path, annot_path: Path, image_category: str, annot_category: str):
        self.key = key
        self.image_path = image_path
        self.annot_path = annot_path
        self.image_category = image_category
        self.annot_category = annot_category


def scan_for_mismatches(root: Path) -> List[MismatchInfo]:
    """
    Scans root directory and returns list of image/annot pairs in different categories.
    """
    per_cat = defaultdict(lambda: {
        'image_keys': set(),
        'annot_keys': set(),
        'image_paths': {},  # key -> path
        'annot_paths': {},  # key -> path
    })

    root = root.resolve()

    # Scan all files
    for p in root.rglob('*'):
        if not p.is_file():
            continue

        name = p.name
        is_img = name.lower().startswith('img_') and name.lower().endswith('.png')
        is_annot = name.lower().startswith('annot_') and name.lower().endswith('.json')
        if not (is_img or is_annot):
            continue

        cat_dir = deduce_category_dir(p)
        try:
            cat_label = str(cat_dir.relative_to(root))
        except ValueError:
            cat_label = str(cat_dir)

        if is_img:
            key = extract_key(name, 'img')
            if key:
                per_cat[cat_label]['image_keys'].add(key)
                per_cat[cat_label]['image_paths'][key] = p
            continue

        if is_annot:
            key = extract_key(name, 'annot')
            if key:
                per_cat[cat_label]['annot_keys'].add(key)
                per_cat[cat_label]['annot_paths'][key] = p
            continue

    # Find mismatches - keys that have both image and annot but in different categories
    key_to_annot_cats = defaultdict(list)
    key_to_image_cats = defaultdict(list)
    
    for cat, stats in per_cat.items():
        for key in stats['annot_keys']:
            key_to_annot_cats[key].append(cat)
        for key in stats['image_keys']:
            key_to_image_cats[key].append(cat)
    
    # Find keys that appear in different categories
    mismatches = []
    all_keys = set(key_to_annot_cats.keys()) | set(key_to_image_cats.keys())
    
    for key in sorted(all_keys):
        annot_cats = key_to_annot_cats.get(key, [])
        image_cats = key_to_image_cats.get(key, [])
        
        # Find cases where image and annot are in different categories
        for annot_cat in annot_cats:
            for image_cat in image_cats:
                if annot_cat != image_cat:
                    image_path = per_cat[image_cat]['image_paths'][key]
                    annot_path = per_cat[annot_cat]['annot_paths'][key]
                    mismatches.append(MismatchInfo(key, image_path, annot_path, image_cat, annot_cat))
    
    return mismatches


def find_duplicates(root: Path, case_sensitive: bool = False) -> Dict[str, List[Path]]:
    """
    DEPRECATED: This function is kept for compatibility but not used in the refactored script.
    Find duplicate PNG filenames in directory tree.
    
    Returns:
        Dict mapping (normalized_name, actual_name) to list of paths with that filename
    """
    buckets = {}
    
    for p in root.rglob("*.png"):
        try:
            if p.is_file():
                normalized_name = p.name if case_sensitive else p.name.lower()
                # Store both normalized name (for grouping) and actual name (for display)
                if normalized_name not in buckets:
                    buckets[normalized_name] = {'actual_name': p.name, 'paths': []}
                buckets[normalized_name]['paths'].append(p)
        except (PermissionError, OSError):
            continue
    
    # Return only duplicates (2+ files with same name)
    return {data['actual_name']: data['paths'] for name, data in buckets.items() if len(data['paths']) > 1}


class MismatchReviewerApp:
    """Tkinter application for reviewing mismatched image/annotation pairs."""
    
    def __init__(self, root: tk.Tk, mismatch: MismatchInfo, root_dir: Path, current: int = 1, total: int = 1):
        self.root = root
        self.mismatch = mismatch
        self.root_dir = root_dir
        self.current = current
        self.total = total
        self.selected_category = None  # Will be 'image' or 'annot'
        self.confirmed = False
        self.continue_to_next = True
        
        # Get screen dimensions
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        
        # Use 90% of screen size
        self.max_width = int(screen_width * 0.9)
        self.max_height = int(screen_height * 0.9)
        
        # Setup UI
        self.setup_window()
        self.create_widgets()
        self.bind_keys()
    
    def setup_window(self):
        """Configure main window."""
        self.root.title(f"Mismatch Review: {self.mismatch.key}")
        self.root.configure(bg="#2b2b2b")
        
        # Center window
        self.root.geometry(f"{self.max_width}x{self.max_height}")
        
        # Make window modal
        self.root.grab_set()
        self.root.focus_force()
    
    def create_widgets(self):
        """Create and layout all UI widgets."""
        # Title label
        title_frame = tk.Frame(self.root, bg="#2b2b2b")
        title_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Progress indicator
        progress_text = f"[{self.current}/{self.total}]"
        progress_label = tk.Label(
            title_frame,
            text=progress_text,
            font=("Arial", 14, "bold"),
            bg="#2b2b2b",
            fg="#00ff00"
        )
        progress_label.pack()
        
        title_text = "Image and Annotation in Different Categories - Select Category to Move Both To:"
        title = tk.Label(
            title_frame,
            text=title_text,
            font=("Arial", 16, "bold"),
            bg="#2b2b2b",
            fg="#ffaa00"
        )
        title.pack()
        
        # Selectable filename entry
        filename_text = f"img_{self.mismatch.key}.png / annot_{self.mismatch.key}.json"
        filename_entry = tk.Entry(
            title_frame,
            font=("Arial", 12),
            bg="#1a1a1a",
            fg="white",
            justify="center",
            readonlybackground="#1a1a1a",
            insertbackground="white",
            relief="flat"
        )
        filename_entry.pack(pady=5, padx=20, fill=tk.X)
        filename_entry.insert(0, filename_text)
        filename_entry.config(state="readonly")
        # Make text selectable
        filename_entry.bind("<Button-1>", lambda e: filename_entry.config(state="normal"))
        filename_entry.bind("<FocusOut>", lambda e: filename_entry.config(state="readonly"))
        
        # Instructions
        instruction_text = "Press [1] or [2] to select category | 's' to skip | 'q' to quit"
        
        instruction = tk.Label(
            title_frame,
            text=instruction_text,
            font=("Arial", 11),
            bg="#2b2b2b",
            fg="#00ffff"
        )
        instruction.pack(pady=5)
        
        # Create layout with image on top and category buttons below
        self.create_layout()
    
    def create_layout(self):
        """Create layout with image and category selection buttons."""
        main_frame = tk.Frame(self.root, bg="#2b2b2b")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Top - Image display
        image_frame = tk.Frame(main_frame, bg="#1a1a1a", relief=tk.RAISED, borderwidth=2)
        image_frame.pack(side=tk.TOP, padx=10, pady=(5, 10), fill=tk.BOTH, expand=True)
        
        # Load and display the image
        self.photo_images = []
        
        available_height = int(self.max_height * 0.6)
        available_width = int(self.max_width * 0.8)
        
        pil_img = self.load_image_simple(self.mismatch.image_path, available_height, available_width)
        photo = ImageTk.PhotoImage(pil_img)
        self.photo_images.append(photo)
        
        img_label = tk.Label(image_frame, image=photo, bg="#1a1a1a")
        img_label.pack(padx=10, pady=10)
        
        # Bottom - Category selection buttons (horizontal layout)
        categories_frame = tk.Frame(main_frame, bg="#2b2b2b")
        categories_frame.pack(side=tk.BOTTOM, padx=10, pady=10, fill=tk.BOTH, expand=False)
        
        categories_title = tk.Label(
            categories_frame,
            text="Select which category to move BOTH image and annotation to:",
            font=("Arial", 14, "bold"),
            bg="#2b2b2b",
            fg="white"
        )
        categories_title.pack(pady=10)
        
        buttons_frame = tk.Frame(categories_frame, bg="#2b2b2b")
        buttons_frame.pack(fill=tk.BOTH, expand=True)
        
        # Calculate button width (50% of available width for each)
        button_width = (self.max_width - 100) // 2
        
        # Create button for image category (left)
        self.create_category_button(
            buttons_frame,
            1,
            self.mismatch.image_category,
            "image",
            self.mismatch.image_path,
            button_width,
            tk.LEFT
        )
        
        # Create button for annot category (right)
        self.create_category_button(
            buttons_frame,
            2,
            self.mismatch.annot_category,
            "annot",
            self.mismatch.annot_path,
            button_width,
            tk.RIGHT
        )
    
    def create_category_button(self, parent, number, category, file_type, path, width, side):
        """Create a category selection button."""
        category_frame = tk.Frame(parent, bg="#1a1a1a", relief=tk.RAISED, borderwidth=2, width=width)
        category_frame.pack(side=side, padx=10, pady=5, fill=tk.BOTH, expand=True)
        
        # Button with number
        btn = tk.Button(
            category_frame,
            text=str(number),
            font=("Arial", 24, "bold"),
            bg="#00aa00",
            fg="white",
            activebackground="#00ff00",
            width=3,
            height=2,
            cursor="hand2",
            command=lambda: self.select_category(file_type)
        )
        btn.pack(side=tk.TOP, pady=10)
        
        # Info frame
        info_frame = tk.Frame(category_frame, bg="#1a1a1a")
        info_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Category label
        tk.Label(
            info_frame,
            text="Category:",
            font=("Arial", 12),
            bg="#1a1a1a",
            fg="white",
            anchor="w"
        ).pack(fill=tk.X, pady=2)
        
        tk.Label(
            info_frame,
            text=category,
            font=("Arial", 14, "bold"),
            bg="#1a1a1a",
            fg="#ffff00",
            anchor="w"
        ).pack(fill=tk.X, pady=2)
        
        # File type label
        tk.Label(
            info_frame,
            text="Contains:",
            font=("Arial", 12),
            bg="#1a1a1a",
            fg="white",
            anchor="w"
        ).pack(fill=tk.X, pady=2)
        
        contains_text = f"{file_type.upper()} (annot_{self.mismatch.key}.json)" if file_type == "annot" else f"{file_type.upper()} (img_{self.mismatch.key}.png)"
        tk.Label(
            info_frame,
            text=contains_text,
            font=("Arial", 12, "bold"),
            bg="#1a1a1a",
            fg="#00ff00" if file_type == "image" else "#ff8800",
            anchor="w"
        ).pack(fill=tk.X, pady=2)
        
        # Path label
        tk.Label(
            info_frame,
            text="Path:",
            font=("Arial", 12),
            bg="#1a1a1a",
            fg="white",
            anchor="w"
        ).pack(fill=tk.X, pady=2)
        
        # Selectable path using Text widget
        path_text_widget = tk.Text(
            info_frame,
            font=("Arial", 10),
            bg="#1a1a1a",
            fg="white",
            height=3,
            wrap=tk.WORD,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            cursor="xterm"
        )
        path_text_widget.insert("1.0", str(path))
        path_text_widget.config(state=tk.DISABLED)
        path_text_widget.pack(fill=tk.BOTH, expand=True, pady=2)
    
    def load_image_simple(self, path: Path, max_height: int, max_width: int) -> Image.Image:
        """Load image without overlay and resize to fit constraints."""
        try:
            img = Image.open(path)
        except Exception as e:
            # Create error placeholder
            img = Image.new('RGB', (400, 300), color='#333333')
            draw = ImageDraw.Draw(img)
            draw.text((50, 150), f"Failed to load\n{e}", fill='red')
            return img
        
        # Resize to fit both available height and width
        img_width, img_height = img.size
        
        # Calculate scale to fit both dimensions
        height_scale = max_height / img_height if img_height > max_height else 1
        width_scale = max_width / img_width if img_width > max_width else 1
        scale = min(height_scale, width_scale, 1)  # Use smallest scale, don't upscale
        
        if scale < 1:
            new_width = int(img_width * scale)
            new_height = int(img_height * scale)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        return img
    
    def bind_keys(self):
        """Bind keyboard shortcuts."""
        self.root.bind('<Escape>', lambda e: self.quit_app())
        self.root.bind('q', lambda e: self.quit_app())
        self.root.bind('s', lambda e: self.skip())
        self.root.bind('1', lambda e: self.select_category('image'))
        self.root.bind('2', lambda e: self.select_category('annot'))
    
    def select_category(self, category_type: str):
        """Handle category selection (either 'image' or 'annot')."""
        self.selected_category = category_type
        selected_cat = self.mismatch.image_category if category_type == 'image' else self.mismatch.annot_category
        
        print(f"\n>>> You selected category: {selected_cat}")
        print(f"    Will move BOTH image and annotation to this category")
        
        # Show confirmation dialog
        self.show_confirmation_dialog(category_type, selected_cat)
    
    def show_confirmation_dialog(self, category_type: str, category_name: str):
        """Show custom confirmation dialog with Yes button pre-selected."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Confirm Selection")
        dialog.configure(bg="#2b2b2b")
        dialog.geometry("700x350")
        dialog.resizable(False, False)
        
        # Center dialog on parent
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Message
        msg_frame = tk.Frame(dialog, bg="#2b2b2b")
        msg_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        tk.Label(
            msg_frame,
            text="Move both image and annotation to this category?",
            font=("Arial", 14, "bold"),
            bg="#2b2b2b",
            fg="#ffaa00"
        ).pack(pady=5)
        
        tk.Label(
            msg_frame,
            text=f"Target Category: {category_name}",
            font=("Arial", 12, "bold"),
            bg="#2b2b2b",
            fg="#00ff00"
        ).pack(pady=5)
        
        # Show what will be moved
        tk.Label(
            msg_frame,
            text="Files to move:",
            font=("Arial", 11),
            bg="#2b2b2b",
            fg="white"
        ).pack(pady=5)
        
        tk.Label(
            msg_frame,
            text=f"• img_{self.mismatch.key}.png",
            font=("Arial", 10),
            bg="#2b2b2b",
            fg="#00ff00"
        ).pack(pady=2)
        
        tk.Label(
            msg_frame,
            text=f"  From: {self.mismatch.image_category}",
            font=("Arial", 9),
            bg="#2b2b2b",
            fg="#888888"
        ).pack(pady=1)
        
        tk.Label(
            msg_frame,
            text=f"• annot_{self.mismatch.key}.json",
            font=("Arial", 10),
            bg="#2b2b2b",
            fg="#ff8800"
        ).pack(pady=2)
        
        tk.Label(
            msg_frame,
            text=f"  From: {self.mismatch.annot_category}",
            font=("Arial", 9),
            bg="#2b2b2b",
            fg="#888888"
        ).pack(pady=1)
        
        # Buttons
        btn_frame = tk.Frame(dialog, bg="#2b2b2b")
        btn_frame.pack(pady=10)
        
        yes_btn = tk.Button(
            btn_frame,
            text="Yes, Move Files (Enter)",
            font=("Arial", 12, "bold"),
            bg="#00aa00",
            fg="white",
            activebackground="#00ff00",
            activeforeground="white",
            width=20,
            command=lambda: self.confirm_selection(dialog)
        )
        yes_btn.pack(side=tk.LEFT, padx=10)
        yes_btn.focus_set()  # Auto-select Yes button
        
        no_btn = tk.Button(
            btn_frame,
            text="No, Cancel (Esc)",
            font=("Arial", 12),
            bg="#aa0000",
            fg="white",
            activebackground="#ff0000",
            activeforeground="white",
            width=20,
            command=lambda: self.cancel_selection(dialog)
        )
        no_btn.pack(side=tk.LEFT, padx=10)
        
        # Bind keys
        dialog.bind('<Return>', lambda e: self.confirm_selection(dialog))
        dialog.bind('<KP_Enter>', lambda e: self.confirm_selection(dialog))
        dialog.bind('<Escape>', lambda e: self.cancel_selection(dialog))
        
        # Center on screen
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
    
    def confirm_selection(self, dialog):
        """Confirm the selection and close."""
        self.confirmed = True
        print("Confirmed!")
        dialog.destroy()
        self.root.quit()  # Exit mainloop but don't destroy window
    
    def cancel_selection(self, dialog):
        """Cancel the selection."""
        self.selected_category = None
        print("Selection cancelled.")
        dialog.destroy()
    
    def skip(self):
        """Skip this mismatch."""
        print("Skipped.")
        self.selected_category = None
        self.continue_to_next = True
        self.root.quit()
    
    def quit_app(self):
        """Quit the application completely."""
        self.selected_category = None
        self.continue_to_next = False
        self.root.quit()
    
    def get_result(self) -> Optional[str]:
        """Return selected category type ('image' or 'annot') if confirmed."""
        return self.selected_category if self.confirmed else None
    
    def update_for_next_mismatch(self, mismatch: MismatchInfo, current: int, total: int):
        """Update window content for the next mismatch."""
        self.mismatch = mismatch
        self.current = current
        self.total = total
        self.selected_category = None
        self.confirmed = False
        
        # Clear and recreate widgets
        for widget in self.root.winfo_children():
            widget.destroy()
        
        self.create_widgets()
        self.bind_keys()
        self.root.title(f"Mismatch Review: {mismatch.key}")


def review_mismatch(mismatch: MismatchInfo, root_dir: Path, current: int, total: int, root: tk.Tk = None, app: MismatchReviewerApp = None) -> Tuple[Optional[str], tk.Tk, MismatchReviewerApp, bool]:
    """
    Show mismatched image/annotation pair and let user select which category to move both to.
    
    Returns:
        Tuple of (selected category type, root window, app instance, continue flag)
    """
    print(f"\n{'='*80}")
    print(f"Reviewing mismatch for: {mismatch.key}")
    print(f"Image in: {mismatch.image_category}")
    print(f"Annot in: {mismatch.annot_category}")
    print(f"Image path: {mismatch.image_path}")
    print(f"Annot path: {mismatch.annot_path}")
    print(f"{'='*80}")
    
    # Create or reuse Tkinter window
    if root is None or app is None:
        root = tk.Tk()
        app = MismatchReviewerApp(root, mismatch, root_dir, current, total)
    else:
        app.update_for_next_mismatch(mismatch, current, total)
    
    root.mainloop()
    
    return app.get_result(), root, app, app.continue_to_next


def move_files_to_category(mismatch: MismatchInfo, target_category_type: str, root_dir: Path) -> bool:
    """
    Move both image and annotation files to the selected category.
    Returns True if successful, False otherwise.
    """
    # Determine target category
    target_category = mismatch.image_category if target_category_type == 'image' else mismatch.annot_category
    target_category_dir = root_dir / target_category
    
    # Check if target category has images and annots folders
    images_dir = target_category_dir / 'images'
    annots_dir = target_category_dir / 'annots'
    
    # Determine where to put files
    if images_dir.exists() and images_dir.is_dir():
        target_image_dir = images_dir
    else:
        target_image_dir = target_category_dir
    
    if not annots_dir.exists() or not annots_dir.is_dir():
        print(f"{RED}ERROR: No 'annots' folder exists in category: {target_category}{RESET}")
        print(f"Expected path: {annots_dir}")
        return False
    
    target_annot_dir = annots_dir
    
    # Prepare file paths
    image_filename = f"img_{mismatch.key}.png"
    annot_filename = f"annot_{mismatch.key}.json"
    
    target_image_path = target_image_dir / image_filename
    target_annot_path = target_annot_dir / annot_filename
    
    # Move image file (if not already in target)
    if mismatch.image_path.resolve() != target_image_path.resolve():
        try:
            # Create directory if needed
            target_image_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(mismatch.image_path), str(target_image_path))
            print(f"{GREEN}✓ Moved image: {mismatch.image_path} -> {target_image_path}{RESET}")
        except Exception as e:
            print(f"{RED}✗ Failed to move image: {e}{RESET}")
            return False
    else:
        print(f"{YELLOW}Image already in target location: {target_image_path}{RESET}")
    
    # Move annotation file (if not already in target)
    if mismatch.annot_path.resolve() != target_annot_path.resolve():
        try:
            # Create directory if needed
            target_annot_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(mismatch.annot_path), str(target_annot_path))
            print(f"{GREEN}✓ Moved annot: {mismatch.annot_path} -> {target_annot_path}{RESET}")
        except Exception as e:
            print(f"{RED}✗ Failed to move annotation: {e}{RESET}")
            # Try to move image back if annot move failed
            if mismatch.image_path.resolve() != target_image_path.resolve():
                try:
                    shutil.move(str(target_image_path), str(mismatch.image_path))
                    print(f"{YELLOW}Rolled back image move{RESET}")
                except:
                    pass
            return False
    else:
        print(f"{YELLOW}Annotation already in target location: {target_annot_path}{RESET}")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Interactive mismatched image/annotation reviewer with Tkinter"
    )
    parser.add_argument("input_dir", type=str, help="Root Collections directory to scan")
    args = parser.parse_args()
    
    root_dir = Path(args.input_dir)
    if not root_dir.exists() or not root_dir.is_dir():
        print(f"Error: '{root_dir}' does not exist or is not a directory.", file=sys.stderr)
        sys.exit(2)
    
    print(f"Scanning for mismatched image/annotation pairs in: {root_dir}")
    print("Please wait...")
    
    mismatches = scan_for_mismatches(root_dir)
    
    if not mismatches:
        print("\nNo mismatches found! All image/annotation pairs are in the same categories.")
        sys.exit(0)
    
    print(f"\nFound {len(mismatches)} mismatched image/annotation pair(s)")
    
    # Track move operations
    moved_count = 0
    failed_count = 0
    skipped_count = 0
    
    # Review each mismatch - reuse window
    tk_root = None
    app = None
    total = len(mismatches)
    
    for idx, mismatch in enumerate(mismatches, 1):
        print(f"\n[Mismatch {idx}/{total}]")
        
        selected_category, tk_root, app, continue_to_next = review_mismatch(mismatch, root_dir, idx, total, tk_root, app)
        
        if not continue_to_next:
            print("Quit by user.")
            break
        
        if selected_category is None:
            print("Skipped.")
            skipped_count += 1
            continue
        
        # Move files to selected category
        if move_files_to_category(mismatch, selected_category, root_dir):
            moved_count += 1
        else:
            failed_count += 1
    
    # Clean up window
    if tk_root:
        tk_root.destroy()
    
    # Summary
    print(f"\n{'='*80}")
    print("REVIEW SUMMARY")
    print(f"{'='*80}")
    print(f"Total mismatches found: {total}")
    print(f"Successfully moved: {moved_count}")
    print(f"Failed: {failed_count}")
    print(f"Skipped: {skipped_count}")
    print(f"{'='*80}")
    
    sys.exit(0)


if __name__ == "__main__":
    main()
