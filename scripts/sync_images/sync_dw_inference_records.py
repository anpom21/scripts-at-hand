#!/usr/bin/env python3
import argparse
import csv
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import firestore  # uses ADC via GOOGLE_APPLICATION_CREDENTIALS

EVAL_FIELDS = ["category", "constituent", "instruction", "un_number"]

# Column order requirement:
# ... timestamp_ms, timestamp_iso, human_eval, eval_category, ...
CSV_HEADER = (
    ["doc_id", "unit", "timestamp_ms", "timestamp_iso", "human_eval"]
    + [f"eval_{k}" for k in EVAL_FIELDS]
    + [
        "front_image_1", "front_image_2", "front_image_3",
        "back_image_1", "back_image_2", "back_image_3",
    ]
)


def ms_to_iso_utc(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def extract_doc_timestamp_ms(doc_id: str, unit: str) -> Optional[int]:
    prefix = f"{unit}_"
    if not doc_id.startswith(prefix):
        return None
    suffix = doc_id[len(prefix):]
    if not suffix.isdigit():
        return None
    try:
        return int(suffix)
    except ValueError:
        return None


def pad_images(values: Any, n: int = 3) -> List[str]:
    if not isinstance(values, list):
        values = []
    out = [str(x) for x in values[:n]]
    while len(out) < n:
        out.append("")
    return out


def safe_get(d: Dict[str, Any], path: str) -> str:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return ""
        cur = cur[part]
        if cur is None:
            return ""
    return str(cur)


def row_from_firestore_doc(unit: str, doc_id: str, data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Convert firestore document into a CSV row dict matching CSV_HEADER.
    Returns None if doc_id doesn't match '{unit}_{timestamp_ms}'.
    """
    ts = extract_doc_timestamp_ms(doc_id, unit)
    if ts is None:
        return None

    front = pad_images(data.get("front_images"), 3)
    back = pad_images(data.get("back_images"), 3)

    eval_obj = data.get("eval")
    has_eval_map = isinstance(eval_obj, dict)

    row: Dict[str, str] = {
        "doc_id": doc_id,
        "unit": unit,
        "timestamp_ms": str(ts),
        "timestamp_iso": ms_to_iso_utc(ts),
        # leave empty for now (but preserve if already present in an existing CSV)
        "human_eval": "",
        "front_image_1": front[0],
        "front_image_2": front[1],
        "front_image_3": front[2],
        "back_image_1": back[0],
        "back_image_2": back[1],
        "back_image_3": back[2],
    }

    if has_eval_map:
        for k in EVAL_FIELDS:
            row[f"eval_{k}"] = safe_get(data, f"eval.{k}")
    else:
        for k in EVAL_FIELDS:
            row[f"eval_{k}"] = ""

    # Ensure all columns exist
    for col in CSV_HEADER:
        row.setdefault(col, "")

    return row


def read_existing_csv(csv_path: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # tolerate older files that may miss human_eval etc.
        for r in reader:
            # normalize missing keys
            nr = {col: (r.get(col, "") or "") for col in CSV_HEADER}
            rows.append(nr)
    return rows


def write_csv(csv_path: str, rows: List[Dict[str, str]]) -> None:
    # sort newest first
    def ts_key(r: Dict[str, str]) -> int:
        try:
            return int(r.get("timestamp_ms", "0") or "0")
        except ValueError:
            return 0

    rows_sorted = sorted(rows, key=ts_key, reverse=True)

    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        for r in rows_sorted:
            # ensure any stray keys don't break writing
            writer.writerow({col: r.get(col, "") for col in CSV_HEADER})


def fetch_firestore_rows(unit: str, project: Optional[str] = None) -> List[Dict[str, str]]:
    db = firestore.Client(project=project) if project else firestore.Client()
    col_ref = db.collection("units").document(unit).collection("dangerous-waste-records")

    rows: List[Dict[str, str]] = []
    skipped_bad_ids = 0

    for snap in col_ref.stream():
        data = snap.to_dict() or {}
        row = row_from_firestore_doc(unit=unit, doc_id=snap.id, data=data)
        if row is None:
            skipped_bad_ids += 1
            continue
        rows.append(row)

    if skipped_bad_ids:
        print(f"Note: skipped {skipped_bad_ids} docs due to unexpected doc_id format.", file=sys.stderr)

    return rows


def prompt_yes_no(msg: str) -> bool:
    while True:
        ans = input(f"{msg} [y/N]: ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("", "n", "no"):
            return False
        print("Please answer 'y' or 'n'.")


def merge_preserving_human_eval(
    existing_rows: List[Dict[str, str]],
    firestore_rows: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Returns (merged_rows, new_rows_added)
    - Uses doc_id as primary key.
    - If doc_id exists, keep existing row but optionally refresh fields from firestore,
      while preserving human_eval (and any existing blank stays blank).
    """
    existing_by_id = {r["doc_id"]: r for r in existing_rows if r.get("doc_id")}
    merged_by_id: Dict[str, Dict[str, str]] = dict(existing_by_id)

    new_rows: List[Dict[str, str]] = []

    for fr in firestore_rows:
        doc_id = fr.get("doc_id", "")
        if not doc_id:
            continue

        if doc_id not in merged_by_id:
            merged_by_id[doc_id] = fr
            new_rows.append(fr)
        else:
            # Update row with firestore fields but preserve human_eval from CSV.
            cur = merged_by_id[doc_id]
            human_eval_val = cur.get("human_eval", "")
            # overwrite everything with firestore representation
            updated = {col: fr.get(col, "") for col in CSV_HEADER}
            updated["human_eval"] = human_eval_val  # preserve
            merged_by_id[doc_id] = updated

    merged_rows = list(merged_by_id.values())
    return merged_rows, new_rows


def summarize_new_rows(new_rows: List[Dict[str, str]], limit: int = 10) -> None:
    if not new_rows:
        return

    # Sort newest first for display
    new_rows_sorted = sorted(
        new_rows,
        key=lambda r: int(r.get("timestamp_ms", "0") or "0"),
        reverse=True,
    )

    print(f"Found {len(new_rows_sorted)} new record(s). Showing up to {limit}:")
    for r in new_rows_sorted[:limit]:
        print(f"  - {r['doc_id']} | {r['timestamp_iso']} | eval_un_number={r.get('eval_un_number','')}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Sync dangerous-waste-records from Firestore into a CSV for a given unit."
    )
    ap.add_argument("--unit", required=True, help="Unit id, e.g. brave-panther")
    ap.add_argument("--csv-path", required=True, help="Path to CSV file to create/update")
    ap.add_argument("--project", default=None, help="GCP project id (optional)")
    ap.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt and apply updates automatically.",
    )
    args = ap.parse_args()

    unit = args.unit.strip()
    csv_path = args.csv_path

    # Fetch current state from Firestore
    firestore_rows = fetch_firestore_rows(unit=unit, project=args.project)

    if not os.path.exists(csv_path):
        # Create new CSV
        print(f"CSV does not exist. Creating: {csv_path}")
        write_csv(csv_path, firestore_rows)
        print(f"Wrote {len(firestore_rows)} row(s).")
        return 0

    # Load existing CSV
    existing_rows = read_existing_csv(csv_path)

    merged_rows, new_rows = merge_preserving_human_eval(existing_rows, firestore_rows)

    if not new_rows:
        # Still rewrite to enforce header/order/sorting and to refresh fields from firestore
        # while preserving human_eval.
        write_csv(csv_path, merged_rows)
        print("No new records found. CSV refreshed/sorted.")
        return 0

    summarize_new_rows(new_rows, limit=10)

    if not args.yes:
        if not prompt_yes_no(f"Update CSV with {len(new_rows)} new record(s)?"):
            print("Aborted. CSV not modified.")
            return 0

    write_csv(csv_path, merged_rows)
    print(f"Updated CSV: {csv_path}")
    print(f"Rows before: {len(existing_rows)}")
    print(f"Rows after : {len(merged_rows)} (added {len(new_rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())