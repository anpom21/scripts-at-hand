#!/usr/bin/env python3
"""Syncs local unit images with Firestore inference records and exports eval data to CSV for ML tracking."""
import argparse
import csv
import os
from pathlib import Path
from typing import Dict, Any, Set

import json
# Check pythom path used to execute script
import sys
print(f"[INFO] Python executable: {sys.executable}")
import re
import unicodedata
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

def load_username_mappings(client: firestore.Client) -> Dict[str, Any]:
    print(f"[INFO] Loading username mappings for unit")

    def _sanitize_username(name: Any) -> str:
        """Normalize usernames:
        - replace spaces and dashes with '_'
        - remove commas
        - drop emojis and other symbol characters
        - keep only letters, numbers and underscores
        - collapse multiple underscores and strip edge underscores
        """
        if name is None:
            return "user"
        s = str(name)
        # replace spaces and dashes with underscore
        s = re.sub(r"[ \-\.]+", "_", s)
        # remove commas
        s = s.replace(",", "")

        parts: list[str] = []
        for ch in s:
            cat = unicodedata.category(ch)
            # Keep letters (L*), numbers (N*) and underscores only
            if cat[0] in ("L", "N") or ch == "_":
                parts.append(ch)
            # else: drop the character (removes emojis, punctuation, symbols)

        out = "".join(parts)
        out = re.sub(r"_+", "_", out).strip("_")
        return out or "user"

    user_col = client.collection("users")

    # Loop through all user documents and build a mapping of user_id to normalized username
    user_mapping: Dict[str, str] = {}
    for user_doc in user_col.stream():
        user_data = user_doc.to_dict() or {}
        user_id = user_data.get("user_id") or user_doc.id
        # try common name fields, fall back to user_id
        raw_name = user_data.get("name") or user_data.get("username") or user_data.get("display_name") or user_id
        username = _sanitize_username(raw_name)

        if user_id:
            user_mapping[user_id] = username

    return user_mapping

def build_csv(
    local_files: Set[str],
    records_by_img: Dict[str, Dict[str, Any]],
    csv_path: Path,
    username_map: Dict[str, Any],
) -> None:
    """
    Build the CSV with header:
        file_name, machine_eval,
        user_eval_<name>..., user_eval_1..N,
        admin_eval_<name>..., admin_eval_1..M,
        inference_1..K
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Writing CSV to: {csv_path}")

    def ensure_list(value: Any) -> list:
        return value if isinstance(value, list) else []

    def get_first_present(record: Dict[str, Any], keys: list[str]) -> Any:
        for key in keys:
            if key in record:
                return record.get(key)
        return None

    def extract_eval_value(value: Any) -> Any:
        if isinstance(value, dict):
            for candidate in ("eval", "value", "label"):
                if candidate in value:
                    return value.get(candidate)
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value

    def normalize_eval_field(raw: Any) -> tuple[Dict[str, Any], list[Any]]:
        """Normalize eval field into a named map and an ordered list."""
        named: Dict[str, Any] = {}
        ordered: list[Any] = []

        if raw is None:
            return named, ordered

        if isinstance(raw, dict):
            for key, value in raw.items():
                named[str(key)] = extract_eval_value(value)
            return named, ordered

        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    name = None
                    for name_key in ("uid", "user_id", "userId", "id", "name"):
                        if name_key in item:
                            name = str(item[name_key])
                            break

                    value = None
                    for eval_key in ("eval", "value", "label"):
                        if eval_key in item:
                            value = item[eval_key]
                            break

                    if name is not None and value is not None:
                        named[name] = value
                    elif value is not None:
                        ordered.append(value)
                    else:
                        ordered.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
                else:
                    ordered.append(item)
            return named, ordered

        # Fallback for scalar values.
        ordered.append(raw)
        return named, ordered

    # Determine max lengths so we can build a consistent header
    max_inference_len = 0
    max_user_eval_len = 0
    max_admin_eval_len = 0
    user_eval_names = set()
    admin_eval_names = set()

    for fname in local_files:
        rec = records_by_img.get(fname)
        if not rec:
            continue

        max_inference_len = max(max_inference_len, len(ensure_list(rec.get("inference"))))

        raw_user_eval = get_first_present(rec, ["user_eval", "user_evals"])
        user_eval_map, user_eval_list = normalize_eval_field(raw_user_eval)
        user_eval_names.update(user_eval_map.keys())
        max_user_eval_len = max(max_user_eval_len, len(user_eval_list))

        raw_admin_eval = get_first_present(rec, ["admin_evals", "admin_eval"])
        admin_eval_map, admin_eval_list = normalize_eval_field(raw_admin_eval)
        admin_eval_names.update(admin_eval_map.keys())
        max_admin_eval_len = max(max_admin_eval_len, len(admin_eval_list))

    # Build header
    base_header = ["file_name", "machine_eval"]
    user_eval_name_headers = [f"user_eval_{username_map.get(name, name)}" for name in sorted(user_eval_names)]
    user_eval_index_headers = [f"user_eval_{i+1}" for i in range(max_user_eval_len)]
    admin_eval_name_headers = [f"admin_eval_{username_map.get(name, name)}" for name in sorted(admin_eval_names)]
    admin_eval_index_headers = [f"admin_eval_{i+1}" for i in range(max_admin_eval_len)]
    inference_headers = [f"inference_{i+1}" for i in range(max_inference_len)]
    header = (
        base_header
        + user_eval_name_headers
        + user_eval_index_headers
        + admin_eval_name_headers
        + admin_eval_index_headers
        + inference_headers
    )

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        missing_count = 0

        for file_name in sorted(local_files):
            record = records_by_img.get(file_name)

            if record is None:
                machine_eval = ""
                user_eval_list = []
                user_eval_map = {}
                admin_eval_list = []
                admin_eval_map = {}
                inference_list = []
                missing_count += 1
            else:
                machine_eval = record.get("eval", "")

                raw_user_eval = get_first_present(record, ["user_eval", "user_evals"])
                user_eval_map, user_eval_list = normalize_eval_field(raw_user_eval)

                raw_admin_eval = get_first_present(record, ["admin_evals", "admin_eval"])
                admin_eval_map, admin_eval_list = normalize_eval_field(raw_admin_eval)

                inference_list = ensure_list(record.get("inference"))

            # Pad all variable-length fields so rows match header width.
            named_user_evals = [user_eval_map.get(name, "") for name in sorted(user_eval_names)]
            padded_user_evals = user_eval_list + [""] * (max_user_eval_len - len(user_eval_list))
            named_admin_evals = [admin_eval_map.get(name, "") for name in sorted(admin_eval_names)]
            padded_admin_evals = admin_eval_list + [""] * (max_admin_eval_len - len(admin_eval_list))
            padded_inference = inference_list + [""] * (max_inference_len - len(inference_list))

            row = (
                [file_name, machine_eval]
                + named_user_evals
                + padded_user_evals
                + named_admin_evals
                + padded_admin_evals
                + padded_inference
            )
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
    # --unit bold-eagle --local-dir /home/simon/Data/Collections_wood/2026-04-11_2026-04-12_prod-data_bold-eagle --csv-out ./test.csv
    arg = ["--unit", "bold-eagle", "--local-dir", "/home/simon/Data/Collections_wood/2026-04-11_2026-04-12_prod-data_bold-eagle", "--csv-out", "./test.csv"]
    args = parser.parse_args(arg)

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
    load_username_mappings(client)

    # 4) Load username mappings for user evals
    username_map = load_username_mappings(client)

    # 5) Build CSV
    build_csv(local_files, records_by_img, csv_path, username_map)


if __name__ == "__main__":
    main()
