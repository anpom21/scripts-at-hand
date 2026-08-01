#!/usr/bin/env python3
"""
Create a mirrored folder structure using symbolic links.

Use case:
- You have a reference directory structure containing files with specific filenames.
- The real matching files exist somewhere under another base directory.
- You want to recreate the reference structure in a new output directory, but with symlinks
  pointing to the real files instead of copying them.

Example:
    python make_symlink_dataset.py \
        --reference-dir /path/to/reference_structure \
        --source-dir /path/to/real_files_base \
        --output-dir /path/to/output_symlink_structure \
        --extensions .jpg .jpeg .png \
        --to-classes \
        --dry-run

Notes:
- Matching is done by filename only, not by relative path.
- Filenames in source-dir should be globally unique unless --allow-source-duplicates is used.
- By default, absolute symlinks are created. Use --relative-links for relative symlinks.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List
import shutil
from pathlib import PurePosixPath
from tqdm import tqdm
from colorama import Fore, Back, Style, init

# Initialize colorama for cross-platform color support
init(autoreset=True)

IMAGE_EXTENSIONS = {
    ".bmp",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
ANNOTATION_EXTENSIONS = {
    ".json",
    ".txt",
    ".xml",
}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | ANNOTATION_EXTENSIONS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recreate a folder structure with symlinks to matching files from another base directory."
    )
    parser.add_argument(
        "--reference-dir",
        type=Path,
        help=(
            "Directory whose folder structure and filenames should be mirrored. "
            "Required unless --to-classes is given; in that mode, source-dir is "
            "used as the reference tree when this option is omitted."
        ),
    )
    parser.add_argument(
        "--source-dir",
        required=True,
        type=Path,
        help="Base directory containing the real files to link to."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory where the mirrored symlink structure will be created."
    )
    parser.add_argument(
        "--extensions",
        nargs="*",
        default=None,
        help=(
            "Optional subset of supported image and annotation extensions to include. "
            "Defaults to: "
            + " ".join(sorted(SUPPORTED_EXTENSIONS))
        ),
    )
    parser.add_argument(
        "--relative-links",
        action="store_true",
        help="Create relative symlinks instead of absolute symlinks."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without creating directories or links."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files/symlinks in output."
    )
    parser.add_argument(
        "--allow-source-duplicates",
        action="store_true",
        help="Allow duplicate filenames in source-dir. First match will be used."
    )
    parser.add_argument(
        "--allow-missing",
        action="store_false",
        help="Skip files from reference-dir that cannot be found in source-dir."
    )
    parser.add_argument(
        "--copy-on-failure",
        action="store_true",
        help="If creating a symlink fails (permission/filesystem), copy the file instead."
    )
    parser.add_argument(
        "--tree",
        action="store_true",
        help="Show a tree-style folder structure summary (skips 'images' and 'annots')."
    )
    parser.add_argument(
        "--to-classes",
        action="store_true",
        help=(
            "Merge class folders from capture directories into top-level class folders "
            "in the output (capture/class/... becomes class/...)."
        ),
    )
    args = parser.parse_args()
    if args.reference_dir is None and not args.to_classes:
        parser.error("--reference-dir is required unless --to-classes is given")

    return args


def normalize_extensions(exts: List[str] | None) -> set[str]:
    if exts is None:
        return set(SUPPORTED_EXTENSIONS)
    out: set[str] = set()
    for ext in exts:
        ext = ext.strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        out.add(ext)

    unsupported = out - SUPPORTED_EXTENSIONS
    if unsupported:
        raise ValueError(
            "unsupported file extensions: "
            + ", ".join(sorted(unsupported))
            + ". Supported extensions are: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )
    return out


def should_include_file(path: Path, allowed_exts: set[str]) -> bool:
    return path.is_file() and path.suffix.lower() in allowed_exts


def output_relative_path(
    ref_path: Path,
    reference_dir: Path,
    to_classes: bool,
) -> Path:
    """Return the reference path, optionally without its capture directory."""
    rel_path = ref_path.relative_to(reference_dir)
    if not to_classes:
        return rel_path

    if len(rel_path.parts) < 3:
        raise ValueError(
            "--to-classes expects files below a capture and class directory, "
            f"but found: {rel_path}"
        )

    return Path(*rel_path.parts[1:])


def build_source_index(
    source_dir: Path,
    allowed_exts: set[str],
    allow_duplicates: bool
) -> Dict[str, Path]:
    """
    Build filename -> source path map.
    """
    filename_to_paths: dict[str, list[Path]] = defaultdict(list)

    source_iter = tqdm(
        source_dir.rglob("*"),
        desc=f"{Fore.GREEN}Indexing source files{Style.RESET_ALL}",
        unit=" files",
        colour="green",
        dynamic_ncols=True,
        leave=True,
        disable=False,
    )

    for path in source_iter:
        if should_include_file(path, allowed_exts):
            filename_to_paths[path.name].append(path.resolve())

    source_iter.close()

    duplicates = {name: paths for name, paths in filename_to_paths.items() if len(paths) > 1}
    if duplicates and not allow_duplicates:
        print(f"{Fore.RED}{Style.BRIGHT}Error: duplicate filenames found in source-dir. Matching by filename is unsafe.{Style.RESET_ALL}", file=sys.stderr)
        print(
            f"{Fore.RED}Found {len(duplicates)} duplicate filename keys. "
            f"Use --allow-source-duplicates to proceed (first match wins).{Style.RESET_ALL}",
            file=sys.stderr,
        )
        print(file=sys.stderr)

        max_names_to_show = 3
        for name, paths in sorted(duplicates.items())[:max_names_to_show]:
            print(f"{Fore.RED}{name} ({len(paths)} matches):{Style.RESET_ALL}", file=sys.stderr)
            for p in paths[:3]:
                print(f"  {Fore.RED}- {p}{Style.RESET_ALL}", file=sys.stderr)
            if len(paths) > 3:
                print(f"  {Fore.RED}- ... ({len(paths) - 3} more){Style.RESET_ALL}", file=sys.stderr)

        remaining = len(duplicates) - max_names_to_show
        if remaining > 0:
            print(
                f"{Fore.RED}... and {remaining} more duplicate names not shown.{Style.RESET_ALL}",
                file=sys.stderr,
            )
        sys.exit(1)

    index: dict[str, Path] = {}
    for name, paths in filename_to_paths.items():
        index[name] = paths[0]

    return index


def remove_existing(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        raise RuntimeError(f"Refusing to overwrite non-file/non-symlink path: {path}")


def make_symlink(
    link_path: Path,
    target_path: Path,
    relative_links: bool,
    dry_run: bool,
    copy_on_failure: bool = False,
) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)

    if relative_links:
        target_for_link = Path(os.path.relpath(target_path, start=link_path.parent))
    else:
        target_for_link = target_path

    if dry_run:
        # In dry-run mode, defer reporting to the end-of-run summary.
        return

    try:
        link_path.symlink_to(target_for_link)
    except (PermissionError, OSError) as e:
        # Some filesystems (exFAT, certain NTFS mounts) or mount options disallow symlinks
        # or require elevated privileges. Provide an optional fallback to copy the file.
        if copy_on_failure:
            try:
                shutil.copy2(target_path, link_path)
                print(f"Warning: symlink not permitted, copied instead: {link_path}")
            except Exception as copy_exc:
                raise
        else:
            if isinstance(e, PermissionError):
                raise PermissionError(
                    f"Operation not permitted while creating symlink: {link_path} -> {target_for_link}. "
                    f"If your filesystem does not support symlinks, rerun with --copy-on-failure."
                ) from e
            raise


def detect_mount_fstype(path: Path) -> str | None:
    """Return the filesystem type for the mountpoint that contains `path`, or None."""
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as f:
            mounts: list[tuple[str, str]] = []
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt_point = parts[1].replace("\\040", " ")
                fstype = parts[2]
                mounts.append((mnt_point, fstype))

        path_str = str(path)
        best: tuple[str, str] | tuple[str, None] = ("", None)
        for mnt_point, fstype in mounts:
            if path_str.startswith(mnt_point) and len(mnt_point) > len(best[0]):
                best = (mnt_point, fstype)

        return best[1]
    except Exception:
        return None


class FileStatistics:
    """Track file statistics and folder structure."""
    
    def __init__(self):
        self.png_count = 0
        self.jpeg_count = 0
        self.json_count = 0
        self.other_count = 0
        self.tree_nodes: set[tuple[str, ...]] = set()
        self.total_files = 0
    
    def add_file(self, rel_path: Path) -> None:
        """Record a file and update statistics."""
        self.total_files += 1
        suffix = rel_path.suffix.lower()
        
        # Count by type
        if suffix == ".png":
            self.png_count += 1
        elif suffix in {".jpeg", ".jpg"}:
            self.jpeg_count += 1
        elif suffix == ".json":
            self.json_count += 1
        else:
            self.other_count += 1

        # Build folder-tree nodes while skipping noisy leaf folders.
        filtered_parts = [p for p in rel_path.parent.parts if p not in {"images", "annots", ".", ""}]
        for i in range(1, len(filtered_parts) + 1):
            self.tree_nodes.add(tuple(filtered_parts[:i]))
    
    def build_tree_lines(self) -> List[str]:
        """Generate a tree-style structure like the `tree` CLI output."""
        lines = ["."]
        if not self.tree_nodes:
            return lines

        children: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for node in sorted(self.tree_nodes):
            parent = node[:-1]
            children[parent].append(node[-1])

        for parent in list(children.keys()):
            children[parent] = sorted(set(children[parent]))

        def walk(parent: tuple[str, ...], prefix: str) -> None:
            items = children.get(parent, [])
            for idx, name in enumerate(items):
                is_last = idx == len(items) - 1
                branch = "└── " if is_last else "├── "
                lines.append(f"{prefix}{branch}{name}")
                next_prefix = f"{prefix}{'    ' if is_last else '│   '}"
                walk(parent + (name,), next_prefix)

        walk((), "")
        return lines
    
    def print_summary(self, dry_run: bool = False, show_tree: bool = False) -> None:
        """Print a formatted summary of file statistics."""
        print()
        print(f"{Fore.GREEN}{Style.BRIGHT}{'='*80}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{Style.BRIGHT}📊 DATASET SUMMARY{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{Style.BRIGHT}{'='*80}{Style.RESET_ALL}")
        print()
        
        # Total files
        total_label = "Total Files Planned" if dry_run else "Total Files Created"
        print(f"{Fore.GREEN}📈 {total_label}: {Style.BRIGHT}{self.total_files}{Style.RESET_ALL}")
        print()
        
        # File type breakdown
        print(f"{Fore.GREEN}File Type Breakdown:{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}🖼️  PNG Files:      {Style.BRIGHT}{self.png_count}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}🖼️  JPEG Files:     {Style.BRIGHT}{self.jpeg_count}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}📋 JSON Files:     {Style.BRIGHT}{self.json_count}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}📄 Other Files:    {Style.BRIGHT}{self.other_count}{Style.RESET_ALL}")
        print()
        
        # Folder structure
        if show_tree:
            print(f"{Fore.GREEN}Folder Structure:{Style.RESET_ALL}")
            tree_lines = self.build_tree_lines()
            for line in tree_lines:
                print(f"  {line}")
            print()
        
        if dry_run:
            print(f"{Fore.YELLOW}{Style.BRIGHT}[DRY RUN - No files were actually created]{Style.RESET_ALL}")
            print()
        
        print(f"{Fore.GREEN}{Style.BRIGHT}{'='*80}{Style.RESET_ALL}")





def main() -> None:
    args = parse_args()

    source_dir = args.source_dir.resolve()
    reference_dir = (args.reference_dir or source_dir).resolve()
    output_dir = args.output_dir.resolve()

    if not reference_dir.is_dir():
        print(f"{Fore.RED}{Style.BRIGHT}Error: reference-dir does not exist or is not a directory: {reference_dir}{Style.RESET_ALL}", file=sys.stderr)
        sys.exit(1)
    if not source_dir.is_dir():
        print(f"{Fore.RED}{Style.BRIGHT}Error: source-dir does not exist or is not a directory: {source_dir}{Style.RESET_ALL}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run and not args.copy_on_failure:
        output_fstype = detect_mount_fstype(output_dir)
        if output_fstype in {"exfat", "ntfs", "fuseblk", "vfat"}:
            print(
                f"{Fore.YELLOW}{Style.BRIGHT}Warning: output filesystem '{output_fstype}' may block symlink creation. "
                f"Use --copy-on-failure to automatically copy files when symlinks are not allowed.{Style.RESET_ALL}",
                file=sys.stderr,
            )

    try:
        allowed_exts = normalize_extensions(args.extensions)
    except ValueError as exc:
        print(f"{Fore.RED}{Style.BRIGHT}Error: {exc}{Style.RESET_ALL}", file=sys.stderr)
        sys.exit(1)

    source_index = build_source_index(
        source_dir=source_dir,
        allowed_exts=allowed_exts,
        allow_duplicates=args.allow_source_duplicates,
    )

    # Collect all files to process
    reference_files: List[Path] = []
    reference_iter = tqdm(
        reference_dir.rglob("*"),
        desc=f"{Fore.GREEN}Scanning reference files{Style.RESET_ALL}",
        unit=" files",
        colour="green",
        dynamic_ncols=True,
        leave=True,
        disable=False,
    )
    for ref_path in reference_iter:
        if not should_include_file(ref_path, allowed_exts):
            continue
        if args.to_classes:
            rel_path = ref_path.relative_to(reference_dir)
            if len(rel_path.parts) < 3:
                continue
        reference_files.append(ref_path)
    reference_iter.close()

    file_stats = FileStatistics()
    total_reference_files = len(reference_files)
    linked_files = 0
    skipped_missing = 0
    overwritten = 0

    # Process files with progress bar
    progress_bar = tqdm(
        reference_files,
        desc=(
            f"{Fore.GREEN}Planning symlinks (dry-run){Style.RESET_ALL}"
            if args.dry_run
            else f"{Fore.GREEN}Creating symlinks{Style.RESET_ALL}"
        ),
        unit=" files",
        colour="green",
        dynamic_ncols=True,
        leave=True
    )

    for ref_path in progress_bar:
        try:
            rel_path = output_relative_path(
                ref_path=ref_path,
                reference_dir=reference_dir,
                to_classes=args.to_classes,
            )
        except ValueError as exc:
            print(f"{Fore.RED}{Style.BRIGHT}Error: {exc}{Style.RESET_ALL}", file=sys.stderr)
            sys.exit(1)
        output_path = output_dir / rel_path

        source_match = source_index.get(ref_path.name)
        if source_match is None:
            msg = f"Missing source match for: {ref_path.name}"
            if args.allow_missing:
                if not args.dry_run:
                    progress_bar.write(f"{Fore.YELLOW}⚠️  Skipping: {msg}{Style.RESET_ALL}")
                skipped_missing += 1
                continue
            print(f"{Fore.RED}{Style.BRIGHT}Error: {msg}{Style.RESET_ALL}", file=sys.stderr)
            sys.exit(1)

        if output_path.exists() or output_path.is_symlink():
            if args.overwrite:
                if not args.dry_run:
                    remove_existing(output_path)
                overwritten += 1
            else:
                print(f"{Fore.RED}{Style.BRIGHT}Error: output already exists: {output_path}{Style.RESET_ALL}", file=sys.stderr)
                sys.exit(1)

        make_symlink(
            link_path=output_path,
            target_path=source_match,
            relative_links=args.relative_links,
            dry_run=args.dry_run,
            copy_on_failure=args.copy_on_failure,
        )
        
        # Track statistics
        file_stats.add_file(rel_path)
        linked_files += 1

    progress_bar.close()

    # Print summary
    file_stats.print_summary(dry_run=args.dry_run, show_tree=args.tree)
    
    # Print operation statistics
    print(f"{Fore.GREEN}Operation Statistics:{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}Reference files scanned: {Style.BRIGHT}{total_reference_files}{Style.RESET_ALL}")
    if args.dry_run:
        print(f"  {Fore.CYAN}Symlinks planned:       {Style.BRIGHT}{linked_files}{Style.RESET_ALL}")
    else:
        print(f"  {Fore.CYAN}Symlinks created:       {Style.BRIGHT}{linked_files}{Style.RESET_ALL}")
    if skipped_missing > 0:
        print(f"  {Fore.YELLOW}Missing skipped:        {Style.BRIGHT}{skipped_missing}{Style.RESET_ALL}")
    if overwritten > 0:
        if args.dry_run:
            print(f"  {Fore.YELLOW}Would overwrite:        {Style.BRIGHT}{overwritten}{Style.RESET_ALL}")
        else:
            print(f"  {Fore.YELLOW}Overwritten:            {Style.BRIGHT}{overwritten}{Style.RESET_ALL}")
    print()


if __name__ == "__main__":
    main()