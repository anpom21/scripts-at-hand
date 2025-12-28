#!/usr/bin/env python3
"""Syncs missing machine images from GCS to local directory by comparing filenames and filtering by date range."""
import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Set, Optional
from datetime import date, datetime


def parse_machine_and_timestamp(filename: str):
    """
    Given a filename like 'img_bold-eagle_2024-11-24T17-59-00-260.png',
    return (machine_name, timestamp_string) or (None, None) if it doesn't fit.
    timestamp_string will be '2024-11-24T17-59-00-260'.
    """
    name = os.path.basename(filename)
    if not name.startswith("img_"):
        return None, None

    parts = name.split("_", 2)
    if len(parts) < 3:
        return None, None

    machine = parts[1]

    ts_with_ext = parts[2]
    if "." in ts_with_ext:
        ts_str = ts_with_ext.rsplit(".", 1)[0]
    else:
        ts_str = ts_with_ext

    return machine, ts_str


def timestamp_to_date(ts_str: str) -> Optional[date]:
    """
    Convert a timestamp string like '2024-11-24T17-59-00-260' to a date object (2024-11-24).
    Returns None if parsing fails.
    """
    # Expect first 10 chars = YYYY-MM-DD
    if len(ts_str) < 10:
        return None
    date_part = ts_str[:10]
    try:
        return date.fromisoformat(date_part)
    except ValueError:
        return None


def collect_existing_filenames(collection_root: Path, machine: str) -> Set[str]:
    """
    Walk the entire collection_root and collect all filenames for this machine.
    We only care about basenames that start with 'img_<machine>_'.
    """
    existing = set()
    prefix = f"img_{machine}_"

    if not collection_root.exists():
        return existing

    print(f"[INFO] Scanning collection root for existing files: {collection_root}")
    for root, _, files in os.walk(collection_root):
        for f in files:
            if f.startswith(prefix):
                existing.add(f)

    print(f"[INFO] Found {len(existing)} existing files for machine '{machine}' in collection.")
    return existing


def run_cmd(cmd: List[str], input_text: str = "") -> subprocess.CompletedProcess:
    print(f"[RUNNING] {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        input=input_text.encode("utf-8") if input_text else None,
        stdout=sys.stdout,
        stderr=sys.stderr,
        check=False,
    )


def list_remote_files_for_machine(bucket: str, machine: str, remote_prefix: str) -> List[str]:
    """
    Use 'gsutil ls' with a wildcard pattern to list all remote files for the machine.
    """
    pattern = f"gs://{bucket}/{remote_prefix}/img_{machine}_*"
    cmd = ["gsutil", "ls", pattern]

    try:
        print(f"[INFO] Listing remote files with pattern: {pattern}")
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print(f"[WARN] No remote files matched. Output:\n{e.output.decode('utf-8', 'ignore')}")
        return []

    lines = out.decode("utf-8").splitlines()
    uris = [line.strip() for line in lines if line.strip().startswith("gs://")]
    print(f"[INFO] Found {len(uris)} remote files for machine '{machine}'.")
    return uris


def filter_missing_and_in_date_range(
    uris: List[str],
    existing_basenames: Set[str],
    machine: str,
    begin_date: date,
    end_date: date,
) -> List[str]:
    """
    From the remote URIs, keep only those:
      - whose basename is not already present locally (missing),
      - and whose date (from timestamp) is between begin_date and end_date inclusive.
    """
    to_download = []
    for uri in uris:
        fname = os.path.basename(uri)

        # Skip if already present anywhere in the Collection
        if fname in existing_basenames:
            continue

        m, ts_str = parse_machine_and_timestamp(fname)
        if m != machine or ts_str is None:
            continue

        d = timestamp_to_date(ts_str)
        if d is None:
            # If we can't parse the date, skip to be safe
            continue

        if begin_date <= d <= end_date:
            to_download.append(uri)

    return to_download


def download_uris(uris: List[str], local_dir: Path, run_for_real: bool) -> int:
    """
    Download the given URIs into local_dir using 'gsutil -m cp -I'.
    If run_for_real is False, only print what would be done (dry-run).
    """
    if not uris:
        print("[INFO] Nothing to download; collection is already up to date for the given date range.")
        return 0

    local_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["gsutil", "-m", "cp", "-I", str(local_dir)]
    input_text = "\n".join(uris) + "\n"

    if not run_for_real:
        print("[DRY-RUN] Would download the following files:")
        for u in uris:
            print("  ", u)
        print("\n[DRY-RUN] To perform the actual download, run again with --run")
        return 0

    # Real download:
    result = run_cmd(cmd, input_text=input_text)
    return result.returncode


def write_output_file(path: Path, uris: List[str]):
    """
    Writes the URIs to a text file, one per line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for u in uris:
            f.write(u + "\n")
    print(f"[INFO] Wrote {len(uris)} URIs to {path}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Sync missing images for a single machine from GCS into a local directory, "
            "by comparing filenames against the entire Collection and restricting to a date range."
        )
    )
    parser.add_argument("--bucket", default="aris-platform-dev.appspot.com", help="GCS bucket name (without gs://).")
    parser.add_argument("--machine", required=True, help="Machine name as in filenames, e.g. 'bold-eagle'.")
    parser.add_argument(
        "--remote-prefix",
        default="images",
        help="Prefix in the bucket where images are stored (default: 'images').",
    )
    parser.add_argument(
        "--local-dir",
        required=True,
        help="Directory where new images for this machine should be stored.",
    )
    parser.add_argument(
        "--collection-root",
        help=(
            "Root of the Collection for this task (all subfolders will be scanned). "
            "If omitted, defaults to the parent directory of --local-dir."
        ),
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Perform the real download. Without this flag, dry-run mode is used.",
    )
    parser.add_argument(
        "--output-file",
        help="Optional path to write the list of files that would/will be downloaded.",
    )
    parser.add_argument(
        "--begin-date",
        help="Optional begin date (YYYY-MM-DD). Defaults to 2021-01-01.",
    )
    parser.add_argument(
        "--end-date",
        help="Optional end date (YYYY-MM-DD). Defaults to today's date.",
    )

    args = parser.parse_args()

    bucket = args.bucket
    machine = args.machine
    remote_prefix = args.remote_prefix.strip("/")
    local_dir = Path(args.local_dir).expanduser().resolve()
    collection_root = (
        Path(args.collection_root).expanduser().resolve()
        if args.collection_root
        else local_dir.parent
    )
    run_for_real = args.run

    # Defaults for date range
    default_begin = date(2021, 1, 1)
    default_end = date.today()

    if args.begin_date:
        try:
            begin_date_val = date.fromisoformat(args.begin_date)
        except ValueError:
            print(f"[ERROR] Invalid --begin-date: {args.begin_date}. Expected YYYY-MM-DD.")
            sys.exit(1)
    else:
        begin_date_val = default_begin

    if args.end_date:
        try:
            end_date_val = date.fromisoformat(args.end_date)
        except ValueError:
            print(f"[ERROR] Invalid --end-date: {args.end_date}. Expected YYYY-MM-DD.")
            sys.exit(1)
    else:
        end_date_val = default_end

    if begin_date_val > end_date_val:
        print("[ERROR] begin-date cannot be after end-date.")
        sys.exit(1)

    print(f"[INFO] Machine         : {machine}")
    print(f"[INFO] Bucket          : {bucket}")
    print(f"[INFO] Remote prefix   : {remote_prefix}")
    print(f"[INFO] Local dir       : {local_dir}")
    print(f"[INFO] Collection root : {collection_root}")
    print(f"[INFO] Mode            : {'REAL DOWNLOAD' if run_for_real else 'DRY-RUN'}")
    print(f"[INFO] Begin date      : {begin_date_val.isoformat()}")
    print(f"[INFO] End date        : {end_date_val.isoformat()}")

    # 1) Collect existing filenames in the entire Collection for this machine
    existing_basenames = collect_existing_filenames(collection_root, machine)

    # 2) List remote files for this machine
    remote_uris = list_remote_files_for_machine(bucket, machine, remote_prefix)

    # 3) Filter to missing files AND within date range
    to_download = filter_missing_and_in_date_range(
        remote_uris,
        existing_basenames,
        machine,
        begin_date_val,
        end_date_val,
    )
    print(f"[INFO] {len(to_download)} files need to be downloaded (missing & within date range).\n\n")

    # 4) Optionally write list to file
    if args.output_file:
        output_path = Path(args.output_file).expanduser().resolve()
        
        write_output_file(output_path, to_download)
        #write output file with all files:
        all_output_path = output_path.with_name(output_path.stem + "_all" + output_path.suffix)
        write_output_file(all_output_path, remote_uris)
        # append text: "all" to the name of the output file  


    # 5) Download (or just show)
    rc = download_uris(to_download, local_dir, run_for_real)

    print(f"\n\n[INFO] Machine         : {machine}")
    print(f"[INFO] Bucket          : {bucket}")
    print(f"[INFO] Remote prefix   : {remote_prefix}")
    print(f"[INFO] Local dir       : {local_dir}")
    print(f"[INFO] Collection root : {collection_root}")
    print(f"[INFO] Mode            : {'REAL DOWNLOAD' if run_for_real else 'DRY-RUN'}")
    print(f"[INFO] Begin date      : {begin_date_val.isoformat()}")
    print(f"[INFO] End date        : {end_date_val.isoformat()}")
    print(f"[INFO] Found {len(existing_basenames)} existing files for machine '{machine}' in collection.")
    print(f"[INFO] Found {len(remote_uris)} remote files for machine '{machine}'.")
    print(f"[INFO] {len(to_download)} files need to be downloaded (missing & within date range).\n")

    if rc == 0:
        status = "completed" if run_for_real else "dry-run complete"
        print(f"[INFO] Sync {status} successfully.")
    else:
        print(f"[ERROR] Sync ended with exit code {rc}.")
    sys.exit(rc)




if __name__ == "__main__":
    main()
