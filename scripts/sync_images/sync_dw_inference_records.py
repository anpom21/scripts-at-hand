#!/usr/bin/env python3
import argparse
import csv
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from google.cloud import firestore  # uses ADC via GOOGLE_APPLICATION_CREDENTIALS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dw_records
from dw_records import DwRecordError


def fetch_documents(unit: str, project: Optional[str] = None) -> List[Tuple[str, Dict[str, Any]]]:
    db = firestore.Client(project=project) if project else firestore.Client()
    col_ref = db.collection("units").document(unit).collection("dangerous-waste-records")
    return [(snap.id, snap.to_dict() or {}) for snap in col_ref.stream()]


def read_existing_csv(csv_path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """Return the existing rows as written, plus the header they were written with."""
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = [{k: (v or "") for k, v in r.items() if k is not None} for r in reader]
    return rows, header


def write_csv(csv_path: str, header: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(header))
        writer.writeheader()
        for r in rows:
            writer.writerow({col: r.get(col, "") for col in header})


def prompt_yes_no(msg: str) -> bool:
    while True:
        ans = input(f"{msg} [y/N]: ").strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("", "n", "no"):
            return False
        print("Please answer 'y' or 'n'.")


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

    docs = fetch_documents(unit=unit, project=args.project)

    existing_rows: List[Dict[str, str]] = []
    existing_header: List[str] = []
    if os.path.exists(csv_path):
        existing_rows, existing_header = read_existing_csv(csv_path)
    else:
        print(f"CSV does not exist. Creating: {csv_path}")

    try:
        table = dw_records.build_unit_table(unit, docs)
        rec = dw_records.reconcile(table, existing_rows, existing_header)
    except DwRecordError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    for line in dw_records.summary_lines(table, rec):
        print(line)

    changed = bool(rec.new_doc_ids or rec.pruned_doc_ids or rec.dropped_columns)
    if changed and not args.yes:
        if not prompt_yes_no(f"Update CSV at {csv_path}?"):
            print("Aborted. CSV not modified.")
            return 0

    write_csv(csv_path, rec.header, rec.rows)
    print(f"Updated CSV: {csv_path}")
    print(f"Rows before: {len(existing_rows)}")
    print(
        f"Rows after : {len(rec.rows)} "
        f"(added {len(rec.new_doc_ids)}, pruned {len(rec.pruned_doc_ids)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
