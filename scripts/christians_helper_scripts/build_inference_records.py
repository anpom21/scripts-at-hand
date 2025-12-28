#!/usr/bin/env python3
import argparse
import csv
import os
from pathlib import Path
from typing import Dict, Any, Set

import json
from google.cloud import firestore


def collect_local_images(local_dir: Path, unit: str) -> Set[str]:
    """
    Collect all local image filenames for this unit in local_dir.
    Looks for files starting with 'img_<unit>_'.
    Returns a set of basenames like 'img_blushing-lion_2025-11-13T10-10-58-029.png'.
    """
    prefix = f"img_{unit}_"
    local_files: Set[str] = set()

    if not local_dir.exists():
        raise FileNotFoundError(f"Local directory does not exist: {local_dir}")

    print(f"[INFO] Scanning local images in: {local_dir}")
    for root, _, files in os.walk(local_dir):
        for f in files:
            if f.startswith(prefix):
                local_files.add(f)

    print(f"[INFO] Found {len(local_files)} local images for unit '{unit}'.")
    return local_files


def load_inference_records(client: firestore.Client, unit: str) -> Dict[str, Dict[str, Any]]:
    """
    Load all inference records for a unit from Firestore.

    Firestore path: units/<unit>/inference-records

    Returns a dict keyed by img_name:
        {
          "img_blushing-lion_2025-11-13T10-10-58-029.png": {
              "eval": ...,
              "highest_voted_eval": ...,
              "inference": [...],
              ...
          },
          ...
        }
    """
    print(f"[INFO] Loading inference records from Firestore for unit '{unit}'...")

    unit_doc = client.collection("units").document(unit)
    coll = unit_doc.collection("inference-records")

    records_by_img: Dict[str, Dict[str, Any]] = {}

    # Stream all docs in the collection
    for doc in coll.stream():
        data = doc.to_dict() or {}
        img_name = data.get("img_name")
        if not img_name:
            continue
        records_by_img[img_name] = data

    print(f"[INFO] Loaded {len(records_by_img)} inference records for unit '{unit}'.")
    return records_by_img


def build_csv(
    local_files: Set[str],
    records_by_img: Dict[str, Dict[str, Any]],
    csv_path: Path,
) -> None:
    """
    Build the CSV with header:
        file_name, machine_eval, user_eval, inference_1, inference_2, ...
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Writing CSV to: {csv_path}")

    # Determine maximum inference length so we can build a consistent header
    max_len = 0
    for fname in local_files:
        rec = records_by_img.get(fname)
        if rec and isinstance(rec.get("inference"), list):
            max_len = max(max_len, len(rec["inference"]))

    # Build header
    base_header = ["file_name", "machine_eval", "user_eval"]
    inference_headers = [f"inference_{i+1}" for i in range(max_len)]
    header = base_header + inference_headers

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        missing_count = 0

        for file_name in sorted(local_files):
            record = records_by_img.get(file_name)

            if record is None:
                machine_eval = ""
                user_eval = ""
                inference_list = []
                missing_count += 1
            else:
                machine_eval = record.get("eval", "")
                user_eval = record.get("highest_voted_eval", "")
                inference_list = record.get("inference", [])

                # Ensure inference_list is list-like
                if not isinstance(inference_list, list):
                    inference_list = []

            # Pad inference list so all rows have same number of columns
            padded = inference_list + [""] * (max_len - len(inference_list))

            row = [file_name, machine_eval, user_eval] + padded
            writer.writerow(row)

    print(f"[INFO] CSV written with {len(local_files)} rows.")
    print(f"[INFO] Local images without matching inference record: {missing_count}")



def main():
    parser = argparse.ArgumentParser(
        description=(
            "Build a CSV of inference metadata for downloaded images of a unit, "
            "using Firestore inference records."
        )
    )
    parser.add_argument(
        "--unit",
        required=True,
        help="Unit name as used in Firestore and img_name, e.g. 'blushing-lion'.",
    )
    parser.add_argument(
        "--local-dir",
        required=True,
        help="Directory where the unit's images are stored (e.g. your Collection/Wood/blushing-lion).",
    )
    parser.add_argument(
        "--csv-out",
        required=True,
        help="Path to the output CSV file.",
    )
    parser.add_argument(
        "--project-id",
        help="Optional GCP project id for Firestore. If omitted, uses default credentials/project.",
    )

    args = parser.parse_args()

    unit = args.unit
    local_dir = Path(args.local_dir).expanduser().resolve()
    csv_path = Path(args.csv_out).expanduser().resolve()

    print(f"[INFO] Unit      : {unit}")
    print(f"[INFO] Local dir : {local_dir}")
    print(f"[INFO] CSV out   : {csv_path}")

    # 1) Collect local image filenames
    local_files = collect_local_images(local_dir, unit)

    # 2) Connect to Firestore
    if args.project_id:
        client = firestore.Client(project=args.project_id)
    else:
        client = firestore.Client()

    # 3) Load inference records for this unit
    records_by_img = load_inference_records(client, unit)

    # 4) Build CSV
    build_csv(local_files, records_by_img, csv_path)


if __name__ == "__main__":
    main()
