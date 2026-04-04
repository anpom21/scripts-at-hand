#!/usr/bin/env python3
import argparse
import csv
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


IMAGE_COLS = [
    "front_image_1",
    "front_image_2",
    "front_image_3",
    "back_image_1",
    "back_image_2",
    "back_image_3",
]


def unit_normalize(unit_id: str) -> str:
    """
    Accepts 'brave_panther' or 'brave-panther' and normalizes to bucket/filename style: 'brave-panther'.
    """
    return unit_id.strip().replace("_", "-")


def parse_year_from_image_filename(fname: str) -> Optional[int]:
    """
    Expect filenames like:
      img_brave-panther_2026-03-03T13-25-46-681.jpg
    Extract year = 2026.
    """
    base = os.path.basename(fname)
    if not base.startswith("img_"):
        return None

    parts = base.split("_", 2)
    if len(parts) < 3:
        return None

    ts_with_ext = parts[2]
    ts_str = ts_with_ext.rsplit(".", 1)[0] if "." in ts_with_ext else ts_with_ext

    # Expect ts_str starts with YYYY-
    if len(ts_str) < 4:
        return None
    year_str = ts_str[:4]
    if not year_str.isdigit():
        return None
    return int(year_str)


def collect_existing_basenames_under_root(root: Path, unit_hyphen: str) -> Set[str]:
    """
    Scan base directory recursively and collect existing image basenames for this unit.
    This is fast enough for typical collections and avoids needing to know which year dirs exist.
    """
    existing: Set[str] = set()
    prefix = f"img_{unit_hyphen}_"

    if not root.exists():
        return existing

    print(f"[INFO] Scanning local base dir for existing files: {root}")
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            if f.startswith(prefix):
                existing.add(f)

    print(f"[INFO] Found {len(existing)} existing local files for unit '{unit_hyphen}'.")
    return existing


@dataclass(frozen=True)
class DownloadItem:
    uri: str
    dest_dir: Path
    basename: str


def read_csv_and_plan_downloads(
    csv_path: Path,
    base_dir: Path,
    unit_hyphen: str,
    bucket: str,
    remote_prefix: str,
    existing_basenames: Set[str],
) -> List[DownloadItem]:
    """
    For each row, look at the 6 image columns; if an image is missing locally, plan a download
    into base_dir/<unit_hyphen>_<year>/.
    """
    planned: List[DownloadItem] = []
    remote_prefix = remote_prefix.strip("/")

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = [c for c in IMAGE_COLS if c not in reader.fieldnames]
        if missing_cols:
            raise RuntimeError(
                f"CSV is missing expected columns: {missing_cols}. "
                f"Found columns: {reader.fieldnames}"
            )

        row_count = 0
        image_refs = 0

        for row in reader:
            row_count += 1
            for col in IMAGE_COLS:
                fname = (row.get(col) or "").strip()
                if not fname:
                    continue

                image_refs += 1
                base = os.path.basename(fname)

                # Only handle this unit's images (safety)
                expected_prefix = f"img_{unit_hyphen}_"
                if not base.startswith(expected_prefix):
                    continue

                if base in existing_basenames:
                    continue

                year = parse_year_from_image_filename(base)
                if year is None:
                    # If you prefer: you could fall back to timestamp_iso in row here.
                    # For now: skip unparseable filenames to avoid wrong placement.
                    print(f"[WARN] Could not parse year from filename '{base}' (row {row_count}); skipping.")
                    continue

                if year == 1970:  # suspicious year often from parsing failures
                    print(f"[WARN] Parsed suspicious year 1970 from filename '{base}' (row {row_count}); skipping.")
                    continue

                dest_dir = base_dir / f"{unit_hyphen}_{year}"
                uri = f"gs://{bucket}/{remote_prefix}/{base}"

                planned.append(DownloadItem(uri=uri, dest_dir=dest_dir, basename=base))

        print(f"[INFO] Processed {row_count} CSV rows; saw {image_refs} image references total.")
        print(f"[INFO] Planned {len(planned)} downloads (missing locally).")

    # Deduplicate by basename (same image might appear multiple times across rows)
    unique: Dict[str, DownloadItem] = {}
    for item in planned:
        # keep first occurrence; dest_dir should be identical for same basename anyway
        unique.setdefault(item.basename, item)

    deduped = list(unique.values())
    if len(deduped) != len(planned):
        print(f"[INFO] Deduplicated downloads: {len(planned)} -> {len(deduped)} unique files.")

    return deduped


def run_cmd(cmd: List[str], input_text: str = "") -> int:
    print(f"[RUNNING] {' '.join(cmd)}")
    p = subprocess.run(
        cmd,
        input=input_text.encode("utf-8") if input_text else None,
        stdout=sys.stdout,
        stderr=sys.stderr,
        check=False,
    )
    return p.returncode


def download_grouped(items: List[DownloadItem], run_for_real: bool) -> int:
    """
    Download using gsutil -m cp -I <dest_dir>, grouped by destination directory.
    """
    if not items:
        print("[INFO] Nothing to download; local base dir already contains all referenced images.")
        return 0

    # Group by dest_dir
    by_dest: Dict[Path, List[DownloadItem]] = {}
    for it in items:
        by_dest.setdefault(it.dest_dir, []).append(it)

    # Dry-run listing
    if not run_for_real:
        print("[DRY-RUN] Would download:")
        total = 0
        for dest, group in sorted(by_dest.items(), key=lambda x: str(x[0])):
            print(f"  -> {dest} ({len(group)} files)")
            for it in group:
                print(f"     {it.uri}")
            total += len(group)
        print(f"[DRY-RUN] Total: {total} files")
        print("[DRY-RUN] Re-run with --run to perform downloads.")
        return 0

    # Real downloads
    overall_rc = 0
    for dest, group in sorted(by_dest.items(), key=lambda x: str(x[0])):
        dest.mkdir(parents=True, exist_ok=True)
        uris = [it.uri for it in group]
        input_text = "\n".join(uris) + "\n"
        cmd = ["gsutil", "-m", "cp", "-I", str(dest)]
        rc = run_cmd(cmd, input_text=input_text)
        if rc != 0:
            overall_rc = rc  # keep last non-zero
            print(f"[ERROR] Download group to {dest} failed with exit code {rc}.")

    return overall_rc


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Sync images referenced in dw_records_<unit>.csv from a GCS bucket to local unit/year subdirectories.\n"
            "Example local layout:\n"
            "  <base_dir>/dw_records_brave-panther.csv\n"
            "  <base_dir>/brave-panther_2025/\n"
            "  <base_dir>/brave-panther_2026/\n"
        )
    )
    parser.add_argument("--unit", required=True, help="Unit id, e.g. 'brave_panther' or 'brave-panther'.")
    parser.add_argument("--base-dir", required=True, help="Directory containing the CSV and unit/year subdirs.")
    parser.add_argument("--bucket", default="aris-platform-dev.appspot.com", help="GCS bucket name (without gs://).")
    parser.add_argument(
        "--remote-prefix",
        default="images",
        help="Prefix in the bucket where images are stored (default: 'images').",
    )
    parser.add_argument(
        "--csv",
        help=(
            "Optional explicit CSV path. If omitted, defaults to <base-dir>/dw_records_<unit-hyphen>.csv"
        ),
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Perform real downloads. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--output-file",
        help="Optional path to write the list of missing URIs (one per line).",
    )

    args = parser.parse_args()

    unit_hyphen = unit_normalize(args.unit)
    base_dir = Path(args.base_dir).expanduser().resolve()
    bucket = args.bucket
    remote_prefix = args.remote_prefix

    csv_path = (
        Path(args.csv).expanduser().resolve()
        if args.csv
        else (base_dir / f"dw_records_{unit_hyphen}.csv")
    )

    print(f"[INFO] Unit           : {unit_hyphen}")
    print(f"[INFO] Base dir       : {base_dir}")
    print(f"[INFO] CSV path       : {csv_path}")
    print(f"[INFO] Bucket         : {bucket}")
    print(f"[INFO] Remote prefix  : {remote_prefix.strip('/')}")
    print(f"[INFO] Mode           : {'REAL DOWNLOAD' if args.run else 'DRY-RUN'}")

    if not base_dir.exists():
        print(f"[ERROR] Base dir does not exist: {base_dir}")
        sys.exit(1)

    if not csv_path.exists():
        print(f"[ERROR] CSV file not found: {csv_path}")
        sys.exit(1)

    existing_basenames = collect_existing_basenames_under_root(base_dir, unit_hyphen)

    items = read_csv_and_plan_downloads(
        csv_path=csv_path,
        base_dir=base_dir,
        unit_hyphen=unit_hyphen,
        bucket=bucket,
        remote_prefix=remote_prefix,
        existing_basenames=existing_basenames,
    )

    if args.output_file:
        out_path = Path(args.output_file).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            for it in items:
                f.write(it.uri + "\n")
        print(f"[INFO] Wrote {len(items)} missing URIs to {out_path}")

    rc = download_grouped(items, run_for_real=args.run)

    if rc == 0:
        print(f"[INFO] Sync {'completed' if args.run else 'dry-run complete'} successfully.")
    else:
        print(f"[ERROR] Sync ended with exit code {rc}.")
    sys.exit(rc)


if __name__ == "__main__":
    main()