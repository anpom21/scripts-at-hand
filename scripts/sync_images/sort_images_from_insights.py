#!/usr/bin/env python3
import argparse
import csv
import os
import shutil
import sys


SORT_CLASS = {
    "outdoor_wood": "impregnated_wood",
    "indoor_wood": "normal_wood"
}



def parse_args():
    parser = argparse.ArgumentParser(
        description="Sort images into folders based on CSV annotations."
    )
    parser.add_argument(
        "--csv",
        required=True,
        help="Path to the CSV file."
    )
    parser.add_argument(
        "--images-dir",
        help="Directory where the images are located. "
             "If omitted, defaults to the directory of the CSV file."
    )
    parser.add_argument(
        "--priority",
        nargs="+",
        default=["christian", "charlotte.sonderborg"],
        help="Prioritized list of user columns to use (default: user3 user1 user2)."
    )
    parser.add_argument(
        "--default-col",
        default="machine_eval",
        help="Fallback column if all user columns are empty (default: machine_eval)."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually move files. Without this flag, script runs in DRY-RUN mode."
    )
    return parser.parse_args()


def main():
    args = parse_args()

    csv_file = args.csv

    # Determine images directory
    if args.images_dir:
        images_dir = args.images_dir
    else:
        images_dir = os.path.dirname(os.path.abspath(csv_file)) or "."

    user_priority = args.priority
    default_col = args.default_col
    do_move = args.run

    mode = "REAL RUN" if do_move else "DRY-RUN"
    print(f"Mode: {mode}")
    print(f"CSV file: {csv_file}")
    print(f"Images directory: {images_dir}")
    print(f"User priority order: {user_priority}")
    print(f"Default column: {default_col}")
    print("-" * 60)

    if not os.path.isfile(csv_file):
        print(f"ERROR: CSV file '{csv_file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    moved_count = 0
    missing_count = 0
    skipped_count = 0

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        # Basic sanity check on required columns
        required_cols = ["file_name", default_col] + user_priority
        for col in required_cols:
            if col not in reader.fieldnames:
                print(f"WARNING: Column '{col}' not found in CSV header.")

        for row in reader:
            image_name = (row.get("file_name") or "").strip()
            if not image_name:
                print("Skipping row with empty file_name.")
                skipped_count += 1
                continue

            # Determine destination based on priority
            destination = ""
            for user in user_priority:
                value = (row.get(user) or "").strip()
                if value:
                    destination = value
                    break

            # Fallback to default column
            if not destination:
                destination = (row.get(default_col) or "").strip()

            if not destination:
                print(f"Skipping '{image_name}': no valid category found.")
                skipped_count += 1
                continue

            # Check if destination is in SORTING_CLASS dictionary
            if destination in SORT_CLASS.keys():
                destination = SORT_CLASS[destination]
            


            src_path = os.path.join(images_dir, image_name)
            target_dir = os.path.join(images_dir, destination)
            dst_path = os.path.join(target_dir, image_name)

            if not os.path.isfile(src_path):
                print(f"File not found: '{src_path}'")
                missing_count += 1
                continue

            # Show what would / will happen
            if do_move:
                os.makedirs(target_dir, exist_ok=True)
                try:
                    shutil.move(src_path, dst_path)
                    print(f"Moved '{image_name}' -> '{destination}/'")
                    moved_count += 1
                except Exception as e:
                    print(f"Error moving '{image_name}': {e}")
            else:
                print(f"[DRY-RUN] Would move '{image_name}' -> '{destination}/'")
                moved_count += 1  # count as planned move

    print("-" * 60)
    print(f"Planned moves: {moved_count}")
    print(f"Missing files: {missing_count}")
    print(f"Skipped rows (no category or file_name): {skipped_count}")
    print(f"Finished in {mode} mode.")


if __name__ == "__main__":
    main()
