"""Utility script to merge capture folders into one output directory."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def prompt_overwrite(path: Path) -> bool:
	"""Ask the user if an existing file should be overwritten."""

	print(f"Warning: duplicate detected at {path}")
	while True:
		choice = input("Overwrite this file? [y/N]: ").strip().lower()
		if choice in {"y", "yes"}:
			return True
		if choice in {"", "n", "no"}:
			return False
		print("Please answer with 'y' or 'n'.")


def merge_folders(
	source_dirs: list[Path],
	output_dir: Path,
	overwrite: bool,
	skip_duplicates: bool,
) -> None:
	"""Move the contents of each source directory into output_dir."""

	output_dir.mkdir(parents=True, exist_ok=True)

	for src in source_dirs:
		if not src.exists():
			raise FileNotFoundError(f"Source folder not found: {src}")
		if not src.is_dir():
			raise NotADirectoryError(f"Source path is not a folder: {src}")

		for item in src.rglob("*"):
			rel_path = item.relative_to(src)
			destination = output_dir / rel_path

			if item.is_dir():
				destination.mkdir(parents=True, exist_ok=True)
				continue

			destination.parent.mkdir(parents=True, exist_ok=True)

			if destination.exists():
				if destination.is_dir():
					raise IsADirectoryError(
						f"Cannot overwrite directory with file: {destination}"
					)
				if overwrite:
					destination.unlink()
				elif skip_duplicates:
					print(f"Skipping duplicate (kept existing file): {destination}")
					continue
				elif prompt_overwrite(destination):
					destination.unlink()
				else:
					print(f"Skipping {item} -> {destination} (kept existing file)")
					continue

			shutil.move(str(item), destination)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Merge capture folders by moving their contents into a shared directory,"
			" preserving the inner structure."
		)
	)
	parser.add_argument(
		"output",
		type=Path,
		help="Directory that will contain the merged folders.",
	)
	parser.add_argument(
		"sources",
		nargs="+",
		type=Path,
		help="One or more source folders to move into the output directory.",
	)
	parser.add_argument(
		"--overwrite",
		action="store_true",
		help=(
			"Automatically overwrite duplicate files without prompting."
		),
	)
	parser.add_argument(
		"--skip-duplicates",
		action="store_true",
		help="Keep existing files whenever duplicates are encountered.",
	)
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	merge_folders(
		args.sources,
		args.output,
		args.overwrite,
		args.skip_duplicates,
	)


if __name__ == "__main__":
	main()
