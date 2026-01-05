import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import argparse
import subprocess
import sys
from PIL import Image, ImageTk, ImageDraw
import csv
import re
import json
import numpy as np
from collections import defaultdict


class ImageSortingTool:
    # Annotation overlay alpha value (0.0 = transparent, 1.0 = opaque)
    ANNOTATION_ALPHA = 0.3
    
    def __init__(self, capture_dir):
        self.capture_dir = Path(capture_dir)
        self.moves_file = self.capture_dir / ".moves"
        self.all_categories = []  # All folders including empty ones
        self.categories = []  # Only categories with images (for backward compatibility)
        self.images_by_category = {}
        self.moves = {}  # {source_path: (dest_path, is_moved)}
        self.current_category = None
        self.current_image_index = 0
        self.current_images = []
        
        # Image viewing state
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.is_panning = False
        self.pan_start_x = 0
        self.pan_start_y = 0
        self.original_image = None
        self.photo_image = None
        self.show_annotation = False
        self.annotation_preference = False  # Track user's preference for annotation overlay
        self.annotation_button = None
        
        # UI Zoom configuration (continuous with 0.2 increments)
        self.ui_zoom = 1.0  # Current zoom level
        self.ui_zoom_increment = 0.2  # Zoom step size
        self.ui_zoom_min = 0.4  # Minimum zoom
        self.ui_zoom_max = 3.0  # Maximum zoom
        
        # GUI
        self.root = tk.Tk()
        self.root.title("Image Collection Sorting Tool")
        self.root.geometry("1800x1200")
        
        # Validate and load directory
        if not self.validate_directory():
            return

        self.load_moves_file()
        # Ensure images are loaded/refreshed before showing the start screen
        self.reload_images()
        self.show_start_screen()

    def add_category_emoji(self, category_name):
        """Add emoji prefix to recognized category names."""
        emoji_map = {
            'normal_wood': '🪵 normal_wood',
            'normal_wood_painted': '🎨 normal_wood_painted',
            'impregnated_wood': '🪵 impregnated_wood',
            'impregnated_wood_painted': '🎨 impregnated_wood_painted',
            'outdoor_wood': '🪵🍃 outdoor_wood',
            'outdoor_wood_painted': '🎨🍃 outdoor_wood_painted',
        }
        return emoji_map.get(category_name, category_name)

    def format_category_label(self, name, threshold=5):
        """Return a label for a category that breaks lines at underscores
        if the name is longer than threshold. Preserves the original name
        for internal mapping keys.
        Recursively adds line breaks at underscores until all segments are below threshold.
        """
        # First add emoji if recognized category
        display_name = self.add_category_emoji(name)
        
        # Base case: if no line is too long, return as is
        lines = display_name.split('\n')
        max_line_len = max(len(line) for line in lines)
        
        if max_line_len <= threshold:
            return display_name
        
        # Find the longest line that has an underscore
        for i, line in enumerate(lines):
            if len(line) > threshold and '_' in line:
                # Find the first underscore and split there
                parts = line.split('_', 1)
                if len(parts) == 2:
                    # Replace this line with two lines (keeping the underscore on the first line)
                    new_lines = lines[:i] + [parts[0] + '_', parts[1]] + lines[i+1:]
                    new_name = '\n'.join(new_lines)
                    # Recurse to check if we need more breaks
                    return self.format_category_label_recursive(new_name, threshold)
        
        # No more underscores to break on, return as is
        return display_name
    
    def format_category_label_recursive(self, display_name, threshold=5):
        """Helper method for recursive formatting without re-adding emoji."""
        # Base case: if no line is too long, return as is
        lines = display_name.split('\n')
        max_line_len = max(len(line) for line in lines)
        
        if max_line_len <= threshold:
            return display_name
        
        # Find the longest line that has an underscore
        for i, line in enumerate(lines):
            if len(line) > threshold and '_' in line:
                # Find the first underscore and split there
                parts = line.split('_', 1)
                if len(parts) == 2:
                    # Replace this line with two lines (keeping the underscore on the first line)
                    new_lines = lines[:i] + [parts[0] + '_', parts[1]] + lines[i+1:]
                    new_name = '\n'.join(new_lines)
                    # Recurse to check if we need more breaks
                    return self.format_category_label_recursive(new_name, threshold)
        
        # No more underscores to break on, return as is
        return display_name

    def reload_images(self):
        """Reload images_by_category and categories from all_categories.
        Call this before rebuilding the summary to ensure data is up-to-date.
        """
        self.images_by_category.clear()
        for category_path in self.all_categories:
            images = self.get_images_in_directory(category_path)
            if images:
                self.images_by_category[category_path.name] = images

        # Update categories list
        self.categories = [d for d in self.all_categories if d.name in self.images_by_category]

    def run_duplicates_script(self):
        """Attempt to run capture_sorting_duplicates.py if present.
        Try script located next to this file first, then in the capture dir.
        """
        # Locate script: try several likely locations (script dir, capture dir, capture dir parents, cwd)
        this_dir = Path(__file__).parent
        candidates = []
        candidates.append(Path('/home/simon/Documents/christians_helper_scripts/capture_sorting_duplicates.py'))
        candidates.append(this_dir / 'capture_sorting_duplicates.py')
        candidates.append(self.capture_dir / 'capture_sorting_duplicates.py')

        # Walk up from capture_dir a few levels
        p = self.capture_dir
        for _ in range(4):
            p = p.parent
            candidates.append(p / 'capture_sorting_duplicates.py')

        # Also try current working directory
        candidates.append(Path.cwd() / 'capture_sorting_duplicates.py')

        script_path = None
        checked = []
        for c in candidates:
            checked.append(str(c))
            if c.exists():
                script_path = c.resolve()  # Convert to absolute path
                break

        if not script_path:
            messagebox.showerror("Script not found",
                                 "Could not find capture_sorting_duplicates.py in any of:\n" + "\n".join(checked))
            return

        # Run the script with the same Python executable and pass capture-dir and --run
        cmd = [sys.executable, str(script_path), '--capture-dir', str(self.capture_dir), '--run']
        try:
            result = subprocess.run(cmd, cwd=str(script_path.parent), capture_output=True, text=True)
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            if result.returncode == 0:
                msg = "Duplicates script finished successfully."
                if stdout:
                    msg += "\n\nOutput:\n" + (stdout[:2000] + ('\n...[truncated]' if len(stdout) > 2000 else ''))
                messagebox.showinfo("Duplicates", msg)
            else:
                msg = f"Script exited with code {result.returncode}."
                if stderr:
                    msg += "\n\nError output:\n" + (stderr[:2000] + ('\n...[truncated]' if len(stderr) > 2000 else ''))
                else:
                    if stdout:
                        msg += "\n\nOutput:\n" + (stdout[:2000] + ('\n...[truncated]' if len(stdout) > 2000 else ''))
                messagebox.showwarning("Duplicates", msg)

            # Refresh image lists after script runs (regardless of success)
            self.reload_images()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to run script:\n{e}")
        
    def validate_directory(self):
        """Validate that the capture directory has the expected structure."""
        if not self.capture_dir.exists():
            messagebox.showwarning("Directory Not Found", 
                f"Directory does not exist: {self.capture_dir}\n\nPlease select a valid capture directory.")
            self.change_directory()
            return False
        
        if not self.capture_dir.is_dir():
            messagebox.showwarning("Invalid Path", 
                f"Path is not a directory: {self.capture_dir}\n\nPlease select a valid capture directory.")
            self.change_directory()
            return False
        
        # Find all subdirectories (including empty ones)
        subdirs = [d for d in self.capture_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
        
        if not subdirs:
            contents = list(self.capture_dir.iterdir())
            msg = f"No category folders found in: {Path(self.capture_dir).resolve()}\n\n"
            if contents:
                msg += "Contents:\n"
                msg += "\n".join([f"  - {item.name}" for item in contents[:10]])
                if len(contents) > 10:
                    msg += f"\n  ... and {len(contents) - 10} more items"
                msg += "\n\n"
            msg += "Please select a directory with category subfolders."
            messagebox.showwarning("No Category Folders", msg)
            self.change_directory()
            return False
        
        # Load all categories (including empty ones)
        self.all_categories = sorted(subdirs, key=lambda x: x.name)
        
        # Load images for each category
        for category in self.all_categories:
            images = self.get_images_in_directory(category)
            if images:
                self.images_by_category[category.name] = images
        
        # Keep backward compatibility
        self.categories = [d for d in self.all_categories if d.name in self.images_by_category]
        
        if not self.images_by_category:
            messagebox.showwarning("No Images Found", 
                f"No images found in any category folder found in\n{Path(self.capture_dir).resolve()}\nSupported formats: .png, .jpg, .jpeg\n\nPlease select a directory with images.")
            self.change_directory()
            return False
        
        return True
    
    def get_images_in_directory(self, directory):
        """Get all supported image files in a directory.
        Handles both flat structure and images/annots subfolder structure.
        """
        supported_extensions = {'.png', '.jpg', '.jpeg'}
        images = []
        
        # Check if there's an 'images' subdirectory
        images_dir = directory / 'images'
        if images_dir.exists() and images_dir.is_dir():
            # Use images subdirectory
            search_dir = images_dir
        else:
            # Use the category directory directly
            search_dir = directory
        
        for ext in supported_extensions:
            images.extend(search_dir.glob(f'*{ext}'))
            images.extend(search_dir.glob(f'*{ext.upper()}'))
        return sorted(images)
    
    def get_annotation_path(self, image_path):
        """Get the corresponding annotation path for an image.
        Returns None if no annotation exists.
        
        Matches format:
        images/img_<capture_name>_<iso_timestamp>.png
        -> annots/annot_<capture_name>_<iso_timestamp>.json
        """
        # Check if image is in an 'images' subfolder structure
        if image_path.parent.name == 'images':
            annots_dir = image_path.parent.parent / 'annots'
            
            # Parse the image filename
            # Expected format: img_<capture_name>_<timestamp>.png
            filename = image_path.stem  # Remove extension
            
            # Check if filename starts with 'img_'
            if filename.startswith('img_'):
                # Replace 'img_' with 'annot_' and change extension to .json
                annot_filename = 'annot_' + filename[4:] + '.json'
                annotation_path = annots_dir / annot_filename
                
                if annotation_path.exists():
                    return annotation_path
        
        # Flat structure or no matching annotation
        return None
    
    def load_annotation_mask(self, annotation_path, image_size):
        """Load annotation from JSON and create a colored mask image.
        
        Args:
            annotation_path: Path to the .json annotation file
            image_size: Tuple (width, height) of the image
            
        Returns:
            PIL Image in RGBA mode with colored segmentation masks
        """
        try:
            with open(annotation_path, 'r') as f:
                annot_data = json.load(f)
            
            # Get image dimensions from annotation
            annot_height, annot_width = annot_data.get('image_size', image_size[::-1])
            
            # Create a transparent RGBA image
            mask_image = Image.new('RGBA', (annot_width, annot_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(mask_image)
            
            # Define colors for different categories (with alpha)
            category_colors = {
                'normal_wood': (0, 255, 0, 180),      # Green
                'abnormal_wood': (255, 0, 0, 180),    # Red
                'abnormal': (255, 0, 0, 180),         # Red (alternate name)
                'background': (128, 128, 128, 100),   # Gray
                'wood': (0, 200, 0, 180),             # Dark green
            }
            default_color = (255, 255, 0, 180)  # Yellow for unknown categories
            
            # Create a numpy array for the full RGBA image
            rgba_array = np.zeros((annot_height, annot_width, 4), dtype=np.uint8)
            
            # Process each annotation
            for annotation in annot_data.get('annotations', []):
                category = annotation.get('category', 'unknown')
                segmentation = annotation.get('segmentation', {})
                
                # Get the color for this category
                color = category_colors.get(category, default_color)
                
                # Decode run-length encoding
                start_positions = segmentation.get('start_positions', [])
                run_lengths = segmentation.get('run_lengths', [])
                
                if start_positions and run_lengths:
                    # Create binary mask from RLE
                    mask = np.zeros(annot_width * annot_height, dtype=np.uint8)
                    for start, length in zip(start_positions, run_lengths):
                        mask[start:start + length] = 1
                    
                    # Reshape to 2D (height, width) - RLE is in row-major order
                    mask_2d = mask.reshape((annot_height, annot_width))
                    
                    # Apply color to masked regions
                    for c in range(4):  # RGBA channels
                        rgba_array[:, :, c][mask_2d == 1] = color[c]
            
            # Convert numpy array to PIL Image
            mask_image = Image.fromarray(rgba_array, mode='RGBA')
            
            # Resize mask to match display image size if needed
            if (annot_width, annot_height) != image_size:
                mask_image = mask_image.resize(image_size, Image.Resampling.LANCZOS)
            
            return mask_image
            
        except Exception as e:
            print(f"Error loading annotation: {e}")
            return None
    
    def normalize_filename(self, filename):
        """Normalize filename by removing '(Copy n)' patterns."""
        # Remove ' (Copy n)' pattern before the extension
        base = Path(filename).stem
        normalized = re.sub(r' \(Copy \d+\)$', '', base)
        return normalized
    
    def find_duplicates(self):
        """Find duplicate images across categories by filename."""
        filename_to_paths = defaultdict(list)
        
        for category, images in self.images_by_category.items():
            for img_path in images:
                normalized_name = self.normalize_filename(img_path.name)
                filename_to_paths[normalized_name].append(img_path)
        
        # Count duplicates (filenames that appear more than once)
        duplicate_count = sum(1 for paths in filename_to_paths.values() if len(paths) > 1)
        return duplicate_count
    
    def find_duplicates_per_category(self, category):
        """Find duplicate images for a specific category."""
        filename_to_paths = defaultdict(list)
        
        for cat, images in self.images_by_category.items():
            for img_path in images:
                normalized_name = self.normalize_filename(img_path.name)
                filename_to_paths[normalized_name].append((cat, img_path))
        
        # Count duplicates in this category
        duplicate_count = 0
        for normalized_name, paths in filename_to_paths.items():
            if len(paths) > 1:
                # Check if any duplicate is in this category
                if any(cat == category for cat, _ in paths):
                    duplicate_count += 1
        
        return duplicate_count
    
    def load_moves_file(self):
        """Load existing .moves file if it exists."""
        if self.moves_file.exists():
            with open(self.moves_file, 'r') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) == 3:
                        source, dest, is_moved = row
                        self.moves[source] = (dest, is_moved == '1')
    
    def save_moves_file(self):
        """Save moves to .moves file."""
        with open(self.moves_file, 'w', newline='') as f:
            writer = csv.writer(f)
            for source, (dest, is_moved) in self.moves.items():
                writer.writerow([source, dest, '1' if is_moved else '0'])
    
    def show_start_screen(self):
        """Show the start screen with category summary."""
        # Refresh data and clear any existing widgets
        self.reload_images()
        
        # Clear any existing widgets
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Force update to ensure all widgets are cleared
        self.root.update_idletasks()
        
        frame = ttk.Frame(self.root, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Top bar with Change Directory button and info
        top_bar = ttk.Frame(frame)
        top_bar.pack(fill=tk.X, pady=(0, 10), anchor='w')
        
        # Use tk.Button instead of ttk.Button to support font parameter
        change_dir_btn = tk.Button(top_bar, text="Change Directory", command=self.change_directory,
                                   font=('Arial', int(10 * self.ui_zoom)), 
                                   padx=int(5 * self.ui_zoom), pady=int(2 * self.ui_zoom))
        change_dir_btn.pack(anchor='w')
        
        # Collection name (parent directory of capture directory)
        collection_name = self.capture_dir.parent.name
        collection_frame = ttk.Frame(top_bar)
        collection_frame.pack(anchor='w', pady=(2, 0))
        ttk.Label(collection_frame, text="Collection:", font=('Arial', int(12 * self.ui_zoom), 'bold')).pack(side=tk.LEFT)
        ttk.Label(collection_frame, text=f" {collection_name}", font=('Arial', int(12 * self.ui_zoom))).pack(side=tk.LEFT)
        
        # Capture name (full path to capture directory)
        capture_frame = ttk.Frame(top_bar)
        capture_frame.pack(anchor='w', pady=(2, 0))
        ttk.Label(capture_frame, text="Capture:", font=('Arial', int(12 * self.ui_zoom), 'bold')).pack(side=tk.LEFT)
        ttk.Label(capture_frame, text=f" {Path(self.capture_dir).name}", font=('Arial', int(12 * self.ui_zoom))).pack(side=tk.LEFT)
        
        # Title
        title = ttk.Label(frame, text="Image Collection Sorting Tool", font=('Arial', int(30 * self.ui_zoom), 'bold'))
        title.pack(pady=20)
        
        # Instructions
        instructions = ttk.Label(frame, text="Select a category to start sorting:", font=('Arial', int(18 * self.ui_zoom), 'bold'))
        instructions.pack(pady=10)
        
        # Create main content frame with margins (1/5 on each side)
        content_frame = ttk.Frame(frame)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # Left margin (1/5 width)
        left_margin = ttk.Frame(content_frame)
        left_margin.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Center frame for category buttons (3/5 width)
        center_frame = ttk.Frame(content_frame)
        center_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Right margin (1/5 width)
        right_margin = ttk.Frame(content_frame)
        right_margin.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Category buttons in matrix layout (no scrolling)
        button_frame = ttk.Frame(center_frame)
        button_frame.pack(pady=10, fill=tk.BOTH, expand=True)
        
        categories = sorted(self.images_by_category.keys())
        # Reset current_category
        self.current_category = None

        # Calculate layout: max 4 columns, adjust based on number of categories
        max_cols = min(4, len(categories))
        
        # Store labels for font size updates
        category_labels = []
        
        for i, category in enumerate(categories):
            row = i // max_cols
            col = i % max_cols
            btn_text = self.format_category_label(category, threshold=45)
            image_count = len(self.images_by_category[category])
            
            # Create a clickable frame that acts as a button
            btn = tk.Frame(button_frame, relief=tk.RAISED, borderwidth=1, cursor="hand2",
                          bg='#f0f0f0', padx=5, pady=5)
            btn.grid(row=row, column=col, padx=5, pady=5, sticky='nsew')
            
            # Left label with category name
            left_label = tk.Label(btn, text=btn_text, anchor='w', bg='#f0f0f0', font=('Arial', 10))
            left_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            # Right label with count
            right_label = tk.Label(btn, text=f"({image_count})", anchor='e', bg='#f0f0f0', font=('Arial', 10))
            right_label.pack(side=tk.RIGHT)
            
            # Store labels for font updates
            category_labels.append((left_label, right_label))
            
            # Make the frame and labels clickable
            def make_handler(cat):
                return lambda e: self.start_sorting(cat)
            
            handler = make_handler(category)
            btn.bind("<Button-1>", handler)
            left_label.bind("<Button-1>", handler)
            right_label.bind("<Button-1>", handler)
            
            # Add hover effect
            def on_enter(e, frame=btn, left=left_label, right=right_label):
                frame.config(bg='#e0e0e0')
                left.config(bg='#e0e0e0')
                right.config(bg='#e0e0e0')
            
            def on_leave(e, frame=btn, left=left_label, right=right_label):
                frame.config(bg='#f0f0f0')
                left.config(bg='#f0f0f0')
                right.config(bg='#f0f0f0')
            
            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)
            left_label.bind("<Enter>", on_enter)
            left_label.bind("<Leave>", on_leave)
            right_label.bind("<Enter>", on_enter)
            right_label.bind("<Leave>", on_leave)
        
        # Configure grid columns to expand evenly with window size
        for col in range(max_cols):
            button_frame.columnconfigure(col, weight=1)
        
        # Configure grid rows to expand as well (optional, for vertical spacing)
        num_rows = (len(categories) + max_cols - 1) // max_cols
        for row in range(num_rows):
            button_frame.rowconfigure(row, weight=1)
        
        # Function to update font sizes based on button dimensions
        def update_font_sizes(event=None):
            button_frame.update_idletasks()
            frame_height = button_frame.winfo_height()
            frame_width = button_frame.winfo_width()
            
            # Calculate font size based on button width
            # Use approximately 1/30 of button width as base font size
            if max_cols > 0 and frame_width > 0:
                button_width = frame_width / max_cols
                base_font_size = max(8, min(24, int(button_width / 22)))
            else:
                base_font_size = 10
            
            # Update all label fonts
            for left_label, right_label in category_labels:
                left_label.config(font=('Arial', base_font_size))
                right_label.config(font=('Arial', base_font_size))
        
        # Bind to window resize and initial update
        button_frame.bind('<Configure>', update_font_sizes)
        self.root.after(100, update_font_sizes)
        
        # Statistics below buttons
        total_images = sum(len(images) for images in self.images_by_category.values())
        duplicate_count = self.find_duplicates()
        
        stats_frame = ttk.Frame(center_frame)
        stats_frame.pack(pady=10)
        
        stats_text = f"Total Images: {total_images}  |  Duplicate Filenames: {duplicate_count}"
        stats_label = ttk.Label(stats_frame, text=stats_text, font=('Arial', int(12 * self.ui_zoom)))
        stats_label.pack()
        
        # If duplicates exist, show a button to run the duplicates script
        if duplicate_count > 0:
            dup_btn = tk.Button(stats_frame, text=f"Run Duplicates Script ({duplicate_count})", 
                                command=lambda: (self.run_duplicates_script(), self.show_start_screen()),
                                font=('Arial', int(10 * self.ui_zoom)),
                                padx=int(5 * self.ui_zoom), pady=int(2 * self.ui_zoom))
            dup_btn.pack(pady=5)
        
        # Directory path - label on separate line, path selectable
        path_frame = ttk.Frame(frame)
        path_frame.pack(side=tk.BOTTOM, pady=10, fill=tk.X)
        
        path_label = ttk.Label(path_frame, text="Directory:", font=('Arial', 9), foreground='gray')
        path_label.pack(anchor='w')
        
        # Frame for text and scrollbar
        path_text_frame = ttk.Frame(path_frame)
        path_text_frame.pack(fill=tk.X)
        
        path_text = tk.Text(path_text_frame, height=1, font=('Arial', 9), foreground='gray', 
                           relief=tk.FLAT, wrap=tk.NONE, borderwidth=0, highlightthickness=0)
        path_text.insert('1.0', str(self.capture_dir))
        path_text.config(state='disabled')  # Make read-only but still selectable
        
        # Add horizontal scrollbar
        path_scrollbar = ttk.Scrollbar(path_text_frame, orient=tk.HORIZONTAL, command=path_text.xview)
        path_text.config(xscrollcommand=path_scrollbar.set)
        
        path_text.pack(side=tk.TOP, fill=tk.X, expand=True)
        
        # Show scrollbar only if text content is wider than the widget
        def check_scrollbar_needed():
            path_text.update_idletasks()
            # Get the bbox of all content in the text widget
            try:
                bbox = path_text.bbox("1.0")
                end_bbox = path_text.bbox("end-1c")
                if bbox and end_bbox:
                    text_width = path_text.winfo_width()
                    # If text extends beyond visible area, show scrollbar
                    if len(str(self.capture_dir)) > 80:  # Heuristic: long paths likely need scrolling
                        path_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
            except:
                # If we can't determine, show scrollbar for paths longer than 80 chars
                if len(str(self.capture_dir)) > 80:
                    path_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        

        # Schedule check after widget is fully rendered
        self.root.after(100, check_scrollbar_needed)
        
        # Set up keyboard bindings for zoom in main menu
        self.root.bind("<plus>", lambda e: self.cycle_ui_zoom(1))
        self.root.bind("<equal>", lambda e: self.cycle_ui_zoom(1))  # + without shift
        self.root.bind("<minus>", lambda e: self.cycle_ui_zoom(-1))
    
    def change_directory(self):
        """Open a folder picker to change the capture directory."""
        # Get the directory where the script was run from
        initial_dir = Path.cwd()
        
        # Open folder picker dialog
        new_dir = filedialog.askdirectory(
            title="Select Capture Directory",
            initialdir=str(initial_dir)
        )
        
        if new_dir:
            # Update capture directory
            self.capture_dir = Path(new_dir)
            self.moves_file = self.capture_dir / ".moves"
            
            # Clear existing data
            self.all_categories = []
            self.categories = []
            self.images_by_category = {}
            self.moves = {}
            
            # Validate and load new directory
            if self.validate_directory():
                self.load_moves_file()
                self.reload_images()
                self.show_start_screen()
            # If validation fails, validate_directory will call change_directory again
        else:
            # User cancelled - if we have no valid directory yet, show a message and keep trying
            if not self.images_by_category:
                result = messagebox.askretrycancel("No Directory Selected", 
                    "You must select a valid capture directory to continue.\n\nClick Retry to select a directory, or Cancel to exit.")
                if result:
                    self.change_directory()
                else:
                    self.root.destroy()
    
    def start_sorting(self, category):
        """Start sorting images in the selected category."""
        self.current_category = category
        self.current_images = self.images_by_category[category].copy()
        self.current_image_index = 0
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.show_sorting_screen()
    
    def show_sorting_screen(self):
        """Show the main sorting screen with image and category buttons."""
        # Clear any existing widgets
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Main container with top menu bar
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Get current UI zoom level
        ui_zoom = self.ui_zoom
        
        # Top menu bar
        menu_frame = ttk.Frame(main_frame, relief=tk.RIDGE, borderwidth=1)
        menu_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        # Use tk.Button instead of ttk.Button to support font scaling
        back_btn = tk.Button(menu_frame, text="↑ Back to Menu", command=self.show_start_screen,
                            font=('Arial', int(10 * ui_zoom)), padx=int(5 * ui_zoom), pady=int(3 * ui_zoom))
        back_btn.pack(side=tk.LEFT, padx=5, pady=3)
        
        apply_btn = tk.Button(menu_frame, text="Apply Moves (Space)", command=self.apply_moves,
                             font=('Arial', int(10 * ui_zoom)), padx=int(5 * ui_zoom), pady=int(3 * ui_zoom))
        apply_btn.pack(side=tk.LEFT, padx=5, pady=3)
        
        nav_label = ttk.Label(menu_frame, text=f"Navigate: ← → arrows | Zoom: +/- ({ui_zoom:.1f}x)", 
                             font=('Arial', int(9 * ui_zoom)))
        nav_label.pack(side=tk.LEFT, padx=15, pady=3)
        
        # Content frame with left and right sections
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left frame for categories - width scales with zoom
        left_frame_width = int(350 * ui_zoom)
        left_frame = ttk.Frame(content_frame, relief=tk.RIDGE, borderwidth=2, width=left_frame_width)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 5))
        left_frame.pack_propagate(False)
        
        # Category label - font scales with zoom
        cat_label = ttk.Label(left_frame, text="Move to Category:", font=('Arial', int(11 * ui_zoom), 'bold'))
        cat_label.pack(pady=5)
        
        # Create canvas and scrollbar for category buttons
        cat_canvas = tk.Canvas(left_frame, borderwidth=0, highlightthickness=0)
        cat_scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=cat_canvas.yview)
        self.cat_button_frame = ttk.Frame(cat_canvas)
        
        # Configure canvas scrolling
        cat_canvas.configure(yscrollcommand=cat_scrollbar.set)
        
        # Create window in canvas for the frame
        cat_canvas_window = cat_canvas.create_window((0, 0), window=self.cat_button_frame, anchor="nw")
        
        # Store category buttons for later reference
        self.category_buttons = {}
        
        # Use ALL categories (including empty ones) for buttons
        categories = sorted([cat.name for cat in self.all_categories])
        
        # Create buttons in 2-column grid
        for i, category in enumerate(categories):
            row = i // 2
            col = i % 2
            btn_text = self.format_category_label(category, threshold=20)
            
            # Scale button properties with UI zoom
            btn_height = int(2 * ui_zoom)
            btn_font_size = int(10 * ui_zoom)
            
            # Disable button if it's the current category being sorted
            if category == self.current_category:
                btn = tk.Button(self.cat_button_frame, text=btn_text,
                               width=20, height=btn_height, wraplength=int(180 * ui_zoom),
                               font=('Arial', btn_font_size),
                               bg="#7ED3F0", fg='black',  # Light blue for current category
                               state='disabled', disabledforeground='black')
            else:
                btn = tk.Button(self.cat_button_frame, text=btn_text,
                               command=lambda c=category: self.mark_for_move(c),
                               width=20, height=btn_height, wraplength=int(180 * ui_zoom),
                               font=('Arial', btn_font_size),
                               activebackground='#d3d3d3')  # Slightly darker gray for hover
            
            btn.grid(row=row, column=col, padx=3, pady=3, sticky='nsew')
            self.category_buttons[category] = btn
        
        # Configure column weights for even distribution
        self.cat_button_frame.columnconfigure(0, weight=1)
        self.cat_button_frame.columnconfigure(1, weight=1)
        
        # Function to update canvas scroll region and check if scrollbar is needed
        def update_scrollregion():
            self.cat_button_frame.update_idletasks()
            cat_canvas.config(scrollregion=cat_canvas.bbox("all"))
            
            # Check if scrollbar is needed
            content_height = self.cat_button_frame.winfo_reqheight()
            canvas_height = cat_canvas.winfo_height()
            
            if content_height > canvas_height:
                cat_scrollbar.pack(side="right", fill="y", padx=(0, 5))
            else:
                cat_scrollbar.pack_forget()
        
        # Function to update canvas width when frame changes
        def configure_cat_canvas(event):
            cat_canvas.itemconfig(cat_canvas_window, width=event.width)
            # Also update scroll region when window resizes
            self.root.after(10, update_scrollregion)
        
        cat_canvas.bind('<Configure>', configure_cat_canvas)
        
        # Enable mouse wheel scrolling only when hovering over the category area
        def on_mousewheel(event):
            cat_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def on_linux_scroll_up(event):
            cat_canvas.yview_scroll(-1, "units")
            
        def on_linux_scroll_down(event):
            cat_canvas.yview_scroll(1, "units")
        
        # Bind to canvas and frame (not bind_all)
        cat_canvas.bind("<MouseWheel>", on_mousewheel)
        cat_canvas.bind("<Button-4>", on_linux_scroll_up)
        cat_canvas.bind("<Button-5>", on_linux_scroll_down)
        self.cat_button_frame.bind("<MouseWheel>", on_mousewheel)
        self.cat_button_frame.bind("<Button-4>", on_linux_scroll_up)
        self.cat_button_frame.bind("<Button-5>", on_linux_scroll_down)
        
        # Pack canvas first
        cat_canvas.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        
        # Schedule scrollbar check after window is fully rendered
        self.root.after(100, update_scrollregion)
        
        # Right frame for image display
        image_frame = ttk.Frame(content_frame, relief=tk.RIDGE, borderwidth=2)
        image_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Top controls frame for annotation toggle and image info
        controls_frame = ttk.Frame(image_frame)
        controls_frame.pack(side=tk.TOP, fill=tk.X, pady=5)
        
        # Annotation toggle button (will be shown/hidden based on annotation availability)
        self.annotation_button = tk.Button(controls_frame, text="Toggle Annotation Overlay", 
                                           command=self.toggle_annotation, state='disabled',
                                           font=('Arial', int(9 * ui_zoom)), 
                                           padx=int(5 * ui_zoom), pady=int(2 * ui_zoom))
        self.annotation_button.pack(side=tk.LEFT, padx=5)
        
        # Image info frame (for category and image count)
        self.info_frame = ttk.Frame(controls_frame)
        self.info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        
        # Image info label - font scales with zoom (will be populated in display_current_image)
        self.info_label = ttk.Label(self.info_frame, text="", font=('Arial', int(10 * ui_zoom)))
        self.info_label.pack(side=tk.TOP, anchor='w')
        
        # Filename text widget (selectable, read-only)
        self.filename_text = tk.Text(self.info_frame, height=1, font=('Arial', int(9 * ui_zoom)),
                                     relief=tk.FLAT, wrap=tk.NONE, borderwidth=0, 
                                     highlightthickness=0, bg=self.root.cget('bg'))
        self.filename_text.pack(side=tk.TOP, anchor='w', fill=tk.X)
        self.filename_text.config(state='disabled')  # Make read-only but still selectable
        
        # Canvas for image display
        self.canvas = tk.Canvas(image_frame, bg='gray30')
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Bind mouse events for zoom and pan
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)  # Linux scroll up
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)  # Linux scroll down
        self.canvas.bind("<ButtonPress-1>", self.on_pan_start)
        self.canvas.bind("<B1-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_pan_end)
        
        # Bind keyboard events
        self.root.bind("<Left>", lambda e: self.navigate_image(-1))
        self.root.bind("<Right>", lambda e: self.navigate_image(1))
        self.root.bind("<Up>", lambda e: self.show_start_screen())
        self.root.bind("<space>", lambda e: self.apply_moves())
        # UI Zoom works in both main menu and sorting screen
        self.root.bind("<plus>", lambda e: self.cycle_ui_zoom(1))
        self.root.bind("<equal>", lambda e: self.cycle_ui_zoom(1))  # + without shift
        self.root.bind("<minus>", lambda e: self.cycle_ui_zoom(-1))
        
        # Display first image
        self.display_current_image()
        
        # Update button colors for first image
        self.update_all_category_button_colors()
    
    def cycle_ui_zoom(self, direction):
        """Cycle through UI zoom levels (+1 for zoom in, -1 for zoom out)."""
        # Adjust zoom with increment, clamped to min/max
        self.ui_zoom = max(self.ui_zoom_min, min(self.ui_zoom_max, self.ui_zoom + (direction * self.ui_zoom_increment)))
        
        # Refresh the appropriate screen based on current state
        if self.current_category:
            # In sorting screen
            self.show_sorting_screen()
        else:
            # In main menu
            self.show_start_screen()
    
    def display_current_image(self):
        """Display the current image on the canvas."""
        if not self.current_images:
            if hasattr(self, 'info_label') and self.info_label.winfo_exists():
                self.info_label.config(text="No images in this category")
            if hasattr(self, 'annotation_button') and self.annotation_button and self.annotation_button.winfo_exists():
                self.annotation_button.config(state='disabled')
            return
        
        current_img_path = self.current_images[self.current_image_index]
        
        # Check if annotation exists for this image
        annotation_path = self.get_annotation_path(current_img_path)
        if annotation_path and hasattr(self, 'annotation_button') and self.annotation_button and self.annotation_button.winfo_exists():
            self.annotation_button.config(state='normal')
            # Restore annotation overlay if user preference is enabled
            self.show_annotation = self.annotation_preference
        elif hasattr(self, 'annotation_button') and self.annotation_button and self.annotation_button.winfo_exists():
            self.annotation_button.config(state='disabled')
            # Can't show annotation if none exists, but keep preference
            self.show_annotation = False
        
        # Check if marked for move
        is_marked = str(current_img_path) in self.moves and not self.moves[str(current_img_path)][1]
        mark_status = " [MARKED FOR MOVE]" if is_marked else ""
        
        # Update info label with bold image count
        info_text = f"Category: {self.current_category} | "
        if hasattr(self, 'info_label') and self.info_label.winfo_exists():
            # Configure font to use bold for the image count portion
            normal_font = ('Arial', int(10 * self.ui_zoom))
            bold_font = ('Arial', int(10 * self.ui_zoom), 'bold')
            
            # Create rich text by combining normal and bold parts
            self.info_label.config(text=f"{info_text}Image {self.current_image_index + 1}/{len(self.current_images)}{mark_status}", 
                                   font=normal_font)
            # Note: For true bold portion, we'd need tk.Text widget, but this keeps it simple
            # Updating the entire label with bold font for the count portion
            self.info_label.config(font=bold_font)
        
        # Update filename text widget (selectable)
        if hasattr(self, 'filename_text') and self.filename_text.winfo_exists():
            self.filename_text.config(state='normal')
            self.filename_text.delete('1.0', tk.END)
            self.filename_text.insert('1.0', current_img_path.name)
            self.filename_text.config(state='disabled')  # Make read-only but selectable
        
        # Load and display image
        try:
            self.original_image = Image.open(current_img_path)
            self.update_image_display(is_marked)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image: {e}")
    
    def toggle_annotation(self):
        """Toggle annotation overlay on/off."""
        self.show_annotation = not self.show_annotation
        # Save the user's preference
        self.annotation_preference = self.show_annotation
        current_img_path = self.current_images[self.current_image_index]
        is_marked = str(current_img_path) in self.moves and not self.moves[str(current_img_path)][1]
        self.update_image_display(is_marked)
    
    def update_image_display(self, is_marked=False):
        """Update the image display with current zoom and pan."""
        if self.original_image is None:
            return
        
        # Check if canvas still exists
        if not hasattr(self, 'canvas') or not self.canvas.winfo_exists():
            return
        
        # Get canvas size
        self.canvas.update_idletasks()
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        # Calculate display size
        img_width, img_height = self.original_image.size
        
        # Fit image to canvas initially
        scale = min(canvas_width / img_width, canvas_height / img_height) * 0.95
        display_width = int(img_width * scale * self.zoom_level)
        display_height = int(img_height * scale * self.zoom_level)
        
        # Start with the original image
        display_image = self.original_image.copy()
        
        # Apply annotation overlay if enabled
        if self.show_annotation:
            current_img_path = self.current_images[self.current_image_index]
            annotation_path = self.get_annotation_path(current_img_path)
            if annotation_path:
                try:
                    # Load and render the annotation mask
                    annotation_mask = self.load_annotation_mask(annotation_path, display_image.size)
                    
                    if annotation_mask:
                        # Apply alpha blending with the adjustable ANNOTATION_ALPHA
                        display_image = display_image.convert('RGBA')
                        
                        # Adjust overall alpha of the mask
                        annotation_with_alpha = annotation_mask.copy()
                        alpha = annotation_with_alpha.split()[3]
                        alpha = alpha.point(lambda p: int(p * self.ANNOTATION_ALPHA))
                        annotation_with_alpha.putalpha(alpha)
                        
                        # Composite the images
                        display_image = Image.alpha_composite(display_image, annotation_with_alpha)
                except Exception as e:
                    print(f"Failed to render annotation overlay: {e}")
        
        # Resize image for display
        resized_image = display_image.resize((display_width, display_height), Image.Resampling.LANCZOS)
        
        self.photo_image = ImageTk.PhotoImage(resized_image)
        
        # Clear canvas
        self.canvas.delete("all")
        
        # Calculate position with pan (reset pan if zoomed out)
        if self.zoom_level <= 1.0:
            self.pan_x = 0
            self.pan_y = 0
        
        x = canvas_width // 2 + self.pan_x
        y = canvas_height // 2 + self.pan_y
        
        # Display image
        self.canvas.create_image(x, y, image=self.photo_image, anchor=tk.CENTER)
    
    def on_mouse_wheel(self, event):
        """Handle mouse wheel for zooming towards cursor position."""
        if self.original_image is None:
            return
        
        # Get canvas dimensions
        self.canvas.update_idletasks()
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        # Get mouse position relative to canvas center
        mouse_x = event.x - canvas_width // 2
        mouse_y = event.y - canvas_height // 2
        
        # Calculate mouse position in image space (before zoom)
        # Taking into account current pan offset
        img_x_before = (mouse_x - self.pan_x) / self.zoom_level
        img_y_before = (mouse_y - self.pan_y) / self.zoom_level
        
        # Store old zoom level
        old_zoom = self.zoom_level
        
        # Determine zoom direction
        if event.num == 4 or event.delta > 0:
            # Zoom in
            self.zoom_level *= 1.1
        elif event.num == 5 or event.delta < 0:
            # Zoom out
            self.zoom_level *= 0.9
        
        # Limit zoom level
        self.zoom_level = max(0.1, min(self.zoom_level, 10.0))
        
        # Calculate mouse position in image space (after zoom)
        img_x_after = (mouse_x - self.pan_x) / self.zoom_level
        img_y_after = (mouse_y - self.pan_y) / self.zoom_level
        
        # Adjust pan to keep the point under the mouse cursor stable
        self.pan_x += (img_x_after - img_x_before) * self.zoom_level
        self.pan_y += (img_y_after - img_y_before) * self.zoom_level
        
        # Update display
        current_img_path = self.current_images[self.current_image_index]
        is_marked = str(current_img_path) in self.moves and not self.moves[str(current_img_path)][1]
        self.update_image_display(is_marked)
    
    def on_pan_start(self, event):
        """Start panning."""
        if self.zoom_level > 1.0:
            self.is_panning = True
            self.pan_start_x = event.x
            self.pan_start_y = event.y
    
    def on_pan_move(self, event):
        """Handle panning movement."""
        if self.is_panning:
            dx = event.x - self.pan_start_x
            dy = event.y - self.pan_start_y
            self.pan_x += dx
            self.pan_y += dy
            self.pan_start_x = event.x
            self.pan_start_y = event.y
            
            current_img_path = self.current_images[self.current_image_index]
            is_marked = str(current_img_path) in self.moves and not self.moves[str(current_img_path)][1]
            self.update_image_display(is_marked)
    
    def on_pan_end(self, event):
        """End panning."""
        self.is_panning = False
    
    def navigate_image(self, direction):
        """Navigate to next/previous image."""
        if not self.current_images:
            return
        
        # Reset zoom and pan (but keep annotation overlay state)
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        
        # Update index
        self.current_image_index = (self.current_image_index + direction) % len(self.current_images)
        
        # Display new image
        self.display_current_image()
        
        # Update button colors for new image
        self.update_all_category_button_colors()
    
    def update_category_button_colors(self, target_category):
        """Update the color of the target category button."""
        # Reset all button colors first (except current category which stays blue and disabled)
        for cat, btn in self.category_buttons.items():
            if cat == self.current_category:
                btn.config(bg='#7ED3F0', fg='black', state='disabled', disabledforeground='black')
            else:
                btn.config(bg='#f0f0f0', fg='black', activebackground='#d3d3d3', state='normal')
        
        # Highlight the target category with darker green hover unless it's current category
        if target_category in self.category_buttons and target_category != self.current_category:
            self.category_buttons[target_category].config(bg='#90EE90', fg='black', activebackground='#70CC70')
    
    def update_all_category_button_colors(self):
        """Update all category button colors based on current image marks."""
        if not self.current_images:
            return
        
        # Check if category_buttons exists and contains valid widgets
        if not hasattr(self, 'category_buttons'):
            return
        
        current_img_path = self.current_images[self.current_image_index]
        source = str(current_img_path)
        
        # Reset all buttons (except current category which stays blue and disabled)
        for cat, btn in self.category_buttons.items():
            # Check if the button widget still exists
            if not btn.winfo_exists():
                continue
                
            if cat == self.current_category:
                btn.config(bg='#7ED3F0', fg='black', state='disabled', disabledforeground='black')
            else:
                btn.config(bg='#f0f0f0', fg='black', activebackground='#d3d3d3', state='normal')
        
        # Highlight if current image is marked with darker green hover unless it's current category
        if source in self.moves and not self.moves[source][1]:
            dest_path = Path(self.moves[source][0])
            target_category = dest_path.parent.name
            if target_category in self.category_buttons and target_category != self.current_category:
                btn = self.category_buttons[target_category]
                if btn.winfo_exists():
                    btn.config(bg='#90EE90', fg='black', activebackground='#70CC70')
    
    def mark_for_move(self, target_category):
        """Mark current image for moving to target category, or unmark if already marked to that category."""
        if not self.current_images:
            return
        
        current_img_path = self.current_images[self.current_image_index]
        source = str(current_img_path)
        dest = str(self.capture_dir / target_category / current_img_path.name)
        
        # Check if already marked to move to this category
        if source in self.moves and not self.moves[source][1]:
            existing_dest = self.moves[source][0]
            existing_category = Path(existing_dest).parent.name
            
            # If clicking the same category again, remove the move marking
            if existing_category == target_category:
                del self.moves[source]
                self.save_moves_file()
                # Update button colors (all back to default)
                self.update_all_category_button_colors()
                # Update display
                self.display_current_image()
                return
        
        # Add to moves (marked as not yet moved)
        self.moves[source] = (dest, False)
        self.save_moves_file()
        
        # Update button colors
        self.update_category_button_colors(target_category)
        
        # Update display
        self.display_current_image()
    
    def apply_moves(self):
        """Apply all pending moves."""
        pending_moves = [(src, dst) for src, (dst, moved) in self.moves.items() if not moved]
        
        if not pending_moves:
            messagebox.showinfo("Info", "No pending moves to apply.")
            return
        
        # Confirm with user
        confirm = messagebox.askyesno("Confirm", 
                                      f"Apply {len(pending_moves)} pending move(s)?")
        if not confirm:
            return
        
        # Perform moves
        success_count = 0
        for source, dest in pending_moves:
            try:
                source_path = Path(source)
                dest_path = Path(dest)
                
                if source_path.exists():
                    # Create destination directory if needed
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Move (overwrite if exists)
                    if dest_path.exists():
                        dest_path.unlink()
                    
                    source_path.rename(dest_path)
                    
                    # Update moves record
                    self.moves[source] = (dest, True)
                    success_count += 1
            except Exception as e:
                messagebox.showerror("Error", f"Failed to move {source}:\n{e}")
        
        # Save updated moves file
        self.save_moves_file()
        
        # Reload ALL category images to update counts (including previously empty folders)
        self.reload_images()

        
        # Check if we're in a sorting screen (current_category is set)
        if self.current_category:
            # Update current category images
            self.current_images = self.images_by_category.get(self.current_category, [])
            
            # Adjust current index if needed
            if self.current_image_index >= len(self.current_images):
                self.current_image_index = max(0, len(self.current_images) - 1)
            
            # Update display
            if self.current_images:
                self.display_current_image()
                self.update_all_category_button_colors()
                messagebox.showinfo("Success", f"Successfully moved {success_count} image(s).")
                return
            else:
                messagebox.showinfo("Info", "No more images in this category.")
                messagebox.showinfo("Success", f"Successfully moved {success_count} image(s).")
                #self.show_start_screen()
                return
        else:
            # We're on the main menu, refresh it
            messagebox.showinfo("2Success", f"Successfully moved {success_count} image(s).")
            self.show_start_screen()
            
            return
        self.show_start_screen()
        messagebox.showinfo("3Success", f"Successfully moved {success_count} image(s).")
    
    def run(self):
        """Run the application."""
        self.root.mainloop()


def main():
    parser = argparse.ArgumentParser(description='Image Collection Sorting Tool')
    parser.add_argument('capture_dir', nargs='?', default=None, 
                       help='Path to the capture directory (optional, defaults to file picker from cwd)')
    parser.add_argument('-d', '--capture-dir', dest='capture_dir_flag', default=None,
                       help='Alternative: Path to the capture directory using -d flag')
    args = parser.parse_args()
    
    # Use positional argument first, then -d flag, then file picker
    capture_dir = args.capture_dir or args.capture_dir_flag
    
    # If no directory provided, open file picker
    if capture_dir is None:
        root = tk.Tk()
        root.withdraw()  # Hide the root window
        capture_dir = filedialog.askdirectory(
            title="Select Capture Directory",
            initialdir=str(Path.cwd())  # Start from current working directory
        )
        root.destroy()
        
        if not capture_dir:
            print("No directory selected. Exiting.")
            sys.exit(0)
    
    app = ImageSortingTool(capture_dir)
    app.run()


if __name__ == "__main__":
    main()
