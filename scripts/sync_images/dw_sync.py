#!/usr/bin/env python3
import argparse
import csv
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import inquirer
import yaml
from google.cloud import firestore

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dw_records
from dw_records import IMAGE_COLS, DwRecordError

# Returned when the user declines a prompt, so sync_and_sort_images.sh can tell an
# abort from a completed sync and leave last_sync alone.
EXIT_ABORTED = 3


@dataclass(frozen=True)
class UnitConfig:
	name: str
	csv_path: str


@dataclass(frozen=True)
class SyncConfig:
	base_dir: Path
	units: List[UnitConfig]


@dataclass(frozen=True)
class DownloadItem:
	uri: str
	dest_dir: Path
	basename: str


def fetch_documents(unit: str, project: Optional[str] = None) -> List[Tuple[str, Dict[str, Any]]]:
	db = firestore.Client(project=project) if project else firestore.Client()
	col_ref = db.collection("units").document(unit).collection("dangerous-waste-records")
	return [(snap.id, snap.to_dict() or {}) for snap in col_ref.stream()]


def read_existing_csv(csv_path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
	"""Return the existing rows as written, plus the header they were written with."""
	with csv_path.open("r", newline="", encoding="utf-8") as f:
		reader = csv.DictReader(f)
		header = list(reader.fieldnames or [])
		rows = [{k: (v or "") for k, v in r.items() if k is not None} for r in reader]
	return rows, header


def write_csv(csv_path: Path, header: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
	csv_path.parent.mkdir(parents=True, exist_ok=True)
	with csv_path.open("w", newline="", encoding="utf-8") as f:
		writer = csv.DictWriter(f, fieldnames=list(header))
		writer.writeheader()
		for r in rows:
			writer.writerow({col: r.get(col, "") for col in header})


def unit_normalize(unit_id: str) -> str:
	return unit_id.strip().replace("_", "-")


def parse_year_from_image_filename(fname: str) -> Optional[int]:
	base = os.path.basename(fname)
	if not base.startswith("img_"):
		return None

	parts = base.split("_", 2)
	if len(parts) < 3:
		return None

	ts_with_ext = parts[2]
	ts_str = ts_with_ext.rsplit(".", 1)[0] if "." in ts_with_ext else ts_with_ext

	if len(ts_str) < 4:
		return None
	year_str = ts_str[:4]
	if not year_str.isdigit():
		return None
	return int(year_str)


def collect_existing_basenames_under_root(root: Path, unit_hyphen: str) -> Set[str]:
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


def read_csv_and_plan_downloads(
	csv_path: Path,
	base_dir: Path,
	unit_hyphen: str,
	bucket: str,
	remote_prefix: str,
	existing_basenames: Set[str],
	begin_date: Optional[date] = None,
	end_date: Optional[date] = None,
) -> List[DownloadItem]:
	planned: List[DownloadItem] = []
	remote_prefix = remote_prefix.strip("/")

	with csv_path.open("r", encoding="utf-8", newline="") as f:
		reader = csv.DictReader(f)
		missing_cols = [c for c in IMAGE_COLS if c not in (reader.fieldnames or [])]
		if missing_cols:
			raise RuntimeError(
				f"CSV is missing expected columns: {missing_cols}. Found columns: {reader.fieldnames}"
			)

		row_count = 0
		image_refs = 0
		out_of_range = 0

		for row in reader:
			row_count += 1
			if not dw_records.row_in_date_range(row, unit_hyphen, begin_date, end_date):
				out_of_range += 1
				continue
			for col in IMAGE_COLS:
				fname = (row.get(col) or "").strip()
				if not fname:
					continue

				image_refs += 1
				base = os.path.basename(fname)

				expected_prefix = f"img_{unit_hyphen}_"
				if not base.startswith(expected_prefix):
					continue

				if base in existing_basenames:
					continue

				year = parse_year_from_image_filename(base)
				if year is None:
					print(f"[WARN] Could not parse year from filename '{base}' (row {row_count}); skipping.")
					continue

				if year == 1970:
					print(f"[WARN] Parsed suspicious year 1970 from filename '{base}' (row {row_count}); skipping.")
					continue

				dest_dir = base_dir / f"{unit_hyphen}_{year}"
				uri = f"gs://{bucket}/{remote_prefix}/{base}"

				planned.append(DownloadItem(uri=uri, dest_dir=dest_dir, basename=base))

		print(f"[INFO] Processed {row_count} CSV rows; saw {image_refs} image references total.")
		if out_of_range:
			print(f"[INFO] Skipped {out_of_range} CSV row(s) outside the date range.")
		print(f"[INFO] Planned {len(planned)} downloads (missing locally).")

	unique: Dict[str, DownloadItem] = {}
	for item in planned:
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
	if not items:
		print("[INFO] Nothing to download; local base dir already contains all referenced images.")
		return 0

	by_dest: Dict[Path, List[DownloadItem]] = {}
	for it in items:
		by_dest.setdefault(it.dest_dir, []).append(it)

	if not run_for_real:
		print("[DRY-RUN] Would download:")
		total = 0
		for dest, group in sorted(by_dest.items(), key=lambda x: str(x[0])):
			print(f"  -> {dest} ({len(group)} files)")
			for it in group:
				print(f"     {it.uri}")
			total += len(group)
		print(f"[DRY-RUN] Total: {total} files")
		print("[DRY-RUN] Re-run without --dry-run-images to perform downloads.")
		return 0

	overall_rc = 0
	for dest, group in sorted(by_dest.items(), key=lambda x: str(x[0])):
		dest.mkdir(parents=True, exist_ok=True)
		uris = [it.uri for it in group]
		input_text = "\n".join(uris) + "\n"
		cmd = ["gsutil", "-m", "cp", "-I", str(dest)]
		rc = run_cmd(cmd, input_text=input_text)
		if rc != 0:
			overall_rc = rc
			print(f"[ERROR] Download group to {dest} failed with exit code {rc}.")

	return overall_rc


def prompt_yes_no(msg: str) -> bool:
	while True:
		ans = input(f"{msg} [y/N]: ").strip().lower()
		if ans in ("y", "yes"):
			return True
		if ans in ("", "n", "no"):
			return False
		print("Please answer 'y' or 'n'.")


def parse_date_arg(value: Optional[str], flag: str) -> Optional[date]:
	if not value:
		return None
	try:
		return date.fromisoformat(value)
	except ValueError:
		raise ValueError(f"Invalid {flag}: {value}. Expected YYYY-MM-DD.")


def load_sync_config(config_path: Path) -> SyncConfig:
	with config_path.open("r", encoding="utf-8") as f:
		data = yaml.safe_load(f) or {}

	base_dir_raw = ((data.get("data") or {}).get("base_dir") or "").strip()
	if not base_dir_raw:
		raise ValueError(f"Config missing data.base_dir: {config_path}")

	units_raw = data.get("units") or []
	units: List[UnitConfig] = []
	for u in units_raw:
		if not isinstance(u, dict):
			continue
		name = str(u.get("name", "")).strip()
		csv_path = str(u.get("csv_path", "")).strip()
		if not name or not csv_path:
			continue
		units.append(UnitConfig(name=name, csv_path=csv_path))

	if not units:
		raise ValueError(f"Config has no valid units entries: {config_path}")

	return SyncConfig(base_dir=Path(base_dir_raw).expanduser().resolve(), units=units)


def pick_unit_interactively(unit_names: List[str]) -> Optional[str]:
	if not sys.stdin.isatty():
		return None

	answers = inquirer.prompt(
		[
			inquirer.List(
				"unit",
				message="Select a unit to sync",
				choices=unit_names,
			)
		]
	)

	if not answers:
		return None
	return answers.get("unit")


def main() -> int:
	default_config_path = Path(__file__).resolve().parent / "dw_config.yaml"

	parser = argparse.ArgumentParser(
		description="Sync Firestore dangerous-waste records and referenced images using config defaults."
	)
	parser.add_argument("--config", default=str(default_config_path), help="Path to YAML config file.")
	parser.add_argument("--unit", help="Unit id. If omitted, an interactive picker is shown.")
	parser.add_argument(
		"--begin-date",
		help="Only sync records on or after this local date (YYYY-MM-DD). CSV rows outside the range are left untouched.",
	)
	parser.add_argument("--end-date", help="Only sync records on or before this local date (YYYY-MM-DD).")
	parser.add_argument("--csv-path", help="Optional CSV override; defaults to selected unit csv_path in config.")
	parser.add_argument("--base-dir", help="Optional base dir override; defaults to data.base_dir in config.")
	parser.add_argument("--project", default=None, help="GCP project id (optional)")
	parser.add_argument("--bucket", default="aris-platform-dev.appspot.com", help="GCS bucket name.")
	parser.add_argument("--remote-prefix", default="images", help="Prefix in bucket where images are stored.")
	parser.add_argument("--skip-records", action="store_true", help="Skip Firestore -> CSV sync stage.")
	parser.add_argument("--skip-images", action="store_true", help="Skip image download stage.")
	parser.add_argument(
		"--dry-run-images",
		action="store_true",
		help="Plan/list missing image downloads without running gsutil cp.",
	)
	parser.add_argument("--output-missing-uris", help="Optional path to write planned missing image URIs.")
	parser.add_argument("--yes", action="store_true", help="Skip confirmation prompts.")
	args = parser.parse_args()

	try:
		begin_date = parse_date_arg(args.begin_date, "--begin-date")
		end_date = parse_date_arg(args.end_date, "--end-date")
	except ValueError as e:
		print(f"[ERROR] {e}")
		return 1
	if begin_date and end_date and begin_date > end_date:
		print("[ERROR] begin-date cannot be after end-date.")
		return 1

	config_path = Path(args.config).expanduser().resolve()
	if not config_path.exists():
		print(f"[ERROR] Config file not found: {config_path}")
		return 1

	try:
		config = load_sync_config(config_path)
	except Exception as e:
		print(f"[ERROR] Failed to load config: {e}")
		return 1

	unit_names = [u.name for u in config.units]
	unit = unit_normalize(args.unit) if args.unit else None

	if not unit:
		unit = pick_unit_interactively(unit_names)
		if not unit:
			print("[ERROR] No unit selected. Use --unit in non-interactive environments.")
			return 1

	unit_entry = next((u for u in config.units if unit_normalize(u.name) == unit), None)
	if unit_entry is None:
		print(f"[ERROR] Unit '{unit}' is not in config. Available: {', '.join(unit_names)}")
		return 1

	base_dir = Path(args.base_dir).expanduser().resolve() if args.base_dir else config.base_dir
	csv_path = Path(args.csv_path).expanduser().resolve() if args.csv_path else Path(unit_entry.csv_path).expanduser().resolve()

	print(f"[INFO] Config         : {config_path}")
	print(f"[INFO] Unit           : {unit}")
	print(f"[INFO] Base dir       : {base_dir}")
	print(f"[INFO] CSV path       : {csv_path}")
	print(f"[INFO] Bucket         : {args.bucket}")
	print(f"[INFO] Remote prefix  : {args.remote_prefix.strip('/')}")
	print(f"[INFO] Date range	 : {begin_date or 'earliest'} -> {end_date or 'latest'}")

	if not base_dir.exists():
		print(f"[ERROR] Base dir does not exist: {base_dir}")
		return 1

	if not args.skip_records:
		print("[STAGE] Syncing Firestore inference records -> CSV")
		docs = fetch_documents(unit=unit, project=args.project)

		existing_rows: List[Dict[str, str]] = []
		existing_header: List[str] = []
		if csv_path.exists():
			existing_rows, existing_header = read_existing_csv(csv_path)
		else:
			print(f"CSV does not exist. Creating: {csv_path}")

		try:
			table = dw_records.build_unit_table(unit, docs)
			rec = dw_records.reconcile(table, existing_rows, existing_header, begin_date, end_date)
		except DwRecordError as e:
			print(f"[ERROR] {e}", file=sys.stderr)
			return 1

		for line in dw_records.summary_lines(table, rec):
			print(line)

		changed = bool(rec.new_doc_ids or rec.pruned_doc_ids or rec.dropped_columns)
		if changed and not args.yes:
			if not prompt_yes_no(f"Update CSV at {csv_path}?"):
				print("Aborted. CSV not modified.")
				return EXIT_ABORTED

		write_csv(csv_path, rec.header, rec.rows)
		print(f"Updated CSV: {csv_path}")
		print(f"Rows before: {len(existing_rows)}")
		print(f"Rows after : {len(rec.rows)} (added {len(rec.new_doc_ids)}, pruned {len(rec.pruned_doc_ids)})")
	else:
		print("[STAGE] Skipping Firestore inference record sync (--skip-records).")

	if args.skip_images:
		print("[STAGE] Skipping image sync (--skip-images).")
		return 0

	if not csv_path.exists():
		print(f"[ERROR] CSV file not found for image sync: {csv_path}")
		return 1

	print("[STAGE] Syncing referenced image files")
	existing_basenames = collect_existing_basenames_under_root(base_dir, unit)
	try:
		items = read_csv_and_plan_downloads(
			csv_path=csv_path,
			base_dir=base_dir,
			unit_hyphen=unit,
			bucket=args.bucket,
			remote_prefix=args.remote_prefix,
			existing_basenames=existing_basenames,
			begin_date=begin_date,
			end_date=end_date,
		)
	except Exception as e:
		print(f"[ERROR] Failed to plan image downloads: {e}")
		return 1

	if args.output_missing_uris:
		out_path = Path(args.output_missing_uris).expanduser().resolve()
		out_path.parent.mkdir(parents=True, exist_ok=True)
		with out_path.open("w", encoding="utf-8") as f:
			for it in items:
				f.write(it.uri + "\n")
		print(f"[INFO] Wrote {len(items)} missing URIs to {out_path}")

	run_for_real = not args.dry_run_images
	if run_for_real and not args.yes and items:
		if not prompt_yes_no(f"Download {len(items)} missing image file(s) now?"):
			print("Aborted image download stage.")
			return EXIT_ABORTED

	rc = download_grouped(items, run_for_real=run_for_real)
	if rc == 0:
		print(f"[INFO] Image sync {'completed' if run_for_real else 'dry-run complete'} successfully.")
	else:
		print(f"[ERROR] Image sync ended with exit code {rc}.")
	return rc


if __name__ == "__main__":
	raise SystemExit(main())
