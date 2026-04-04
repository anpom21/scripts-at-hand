#!/usr/bin/env python3

import argparse
import csv
from datetime import date, datetime
from pathlib import Path
import re
import sys

from tqdm import tqdm

from probe_remote_machine import (
    REMOTE_CMD,
    ensure_credentials,
    establish_client_connection,
    execute_remote_command,
    load_machine,
)

TIMESTAMP_RE = re.compile(r"_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{1,6})(?:\.[A-Za-z0-9]+)?$")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
ANSI_RE = re.compile(r"(\x1b\[[0-9;]*m)")

ANSI_RESET = "\033[0m"
ANSI_BOLD_WHITE = "\033[1;97m"
ANSI_GREY = "\033[37m"


def format_prompt(text: str) -> str:
    return f"{ANSI_BOLD_WHITE}{text}{ANSI_RESET}"


def format_bold(text: str) -> str:
    return f"{ANSI_BOLD_WHITE}{text}{ANSI_RESET}"


def emphasize_numbers(text: str) -> str:
    parts = ANSI_RE.split(text)
    styled_parts: list[str] = []
    for part in parts:
        if ANSI_RE.fullmatch(part):
            styled_parts.append(part)
        else:
            styled_parts.append(NUMBER_RE.sub(lambda m: format_bold(m.group(0)), part))
    return "".join(styled_parts)


def format_message(text: str) -> str:
    return emphasize_numbers(text)


def format_path(text: str) -> str:
    return f"{ANSI_GREY}{text}{ANSI_RESET}"


def print_message(text: str) -> None:
    print(format_message(text))


def prompt_input(text: str) -> str:
    return input(format_prompt(text))


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe a machine and report files in a date range that exist remotely "
            "but are missing from a bulk_download.csv file."
        )
    )
    parser.add_argument(
        "--bulk-download-csv",
        required=True,
        help="Path to bulk_download.csv.",
    )
    parser.add_argument(
        "--machine",
        required=True,
        help="Machine name defined in machine_config.yaml (for example: fierce-wolf).",
    )
    parser.add_argument(
        "--machine-config",
        default=str(Path(__file__).with_name("machine_config.yaml")),
        help="Path to machine config YAML file.",
    )
    parser.add_argument(
        "--begin-date",
        required=True,
        type=parse_date,
        help="Inclusive begin date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        type=parse_date,
        help="Inclusive end date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--remote-cmd",
        default=REMOTE_CMD,
        help="Command used by probe_machine() when listing remote files.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra diagnostics while parsing and comparing.",
    )
    parser.add_argument(
        "--offline-suffix",
        default="",
        help=(
            "Optional suffix to append to downloaded offline image filenames "
            "before file extension."
        ),
    )
    return parser.parse_args()


def extract_capture_datetime_from_name(file_name: str) -> datetime | None:
    stem = Path(file_name).name
    match = TIMESTAMP_RE.search(stem)
    if not match:
        return None

    timestamp = match.group(1)
    try:
        return datetime.strptime(timestamp, "%Y-%m-%dT%H-%M-%S-%f")
    except ValueError:
        return None


def in_range(capture_date: date, begin_date: date, end_date: date) -> bool:
    return begin_date <= capture_date <= end_date


def load_bulk_download_names_in_range(
    csv_path: Path, begin_date: date, end_date: date, verbose: bool = False
) -> set[str]:
    if not csv_path.exists():
        raise FileNotFoundError(f"bulk_download.csv not found: {csv_path}")

    names: set[str] = set()
    skipped_no_timestamp = 0

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "file_name" not in (reader.fieldnames or []):
            raise ValueError("CSV must contain a 'file_name' column")

        for row in reader:
            file_name = (row.get("file_name") or "").strip()
            if not file_name:
                continue

            dt = extract_capture_datetime_from_name(file_name)
            if dt is None:
                skipped_no_timestamp += 1
                continue

            if in_range(dt.date(), begin_date, end_date):
                names.add(Path(file_name).name)

    if verbose:
        print_message(
            f"Loaded {len(names)} bulk_download filenames in range "
            f"[{begin_date}, {end_date}]"
        )
        if skipped_no_timestamp:
            print_message(f"Skipped {skipped_no_timestamp} CSV rows without parseable timestamp")

    return names


def probe_remote_names_in_range(
    client,
    remote_cmd: str,
    begin_date: date,
    end_date: date,
    verbose: bool = False,
) -> dict[str, str]:
    paths = execute_remote_command(client=client, remote_cmd=remote_cmd)

    names_to_path: dict[str, str] = {}
    skipped_no_timestamp = 0

    for path in paths:
        dt = extract_capture_datetime_from_name(path)
        if dt is None:
            skipped_no_timestamp += 1
            continue

        if in_range(dt.date(), begin_date, end_date):
            base_name = Path(path).name
            names_to_path.setdefault(base_name, path)

    if verbose:
        print_message(
            f"Probed {len(names_to_path)} remote filenames in range "
            f"[{begin_date}, {end_date}]"
        )
        if skipped_no_timestamp:
            print_message(f"Skipped {skipped_no_timestamp} remote paths without parseable timestamp")

    return names_to_path


def ask_yes_no(prompt: str) -> bool:
    return ask_yes_no_with_default(prompt, default=True)


def ask_yes_no_with_default(prompt: str, default: bool) -> bool:
    raw = prompt_input(prompt).strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def choose_output_dir(csv_path: Path) -> Path:
    parent_name = csv_path.parent.name or str(csv_path.parent)
    use_default = ask_yes_no_with_default(
        f"Place images in a new 'offline_samples' folder in: '{parent_name}'? [Y/n]: ",
        default=True,
    )
    if use_default:
        return csv_path.parent / "offline_samples"

    custom_output = prompt_input("Enter output directory path: ").strip()
    if not custom_output:
        raise ValueError("Output directory cannot be empty")
    return Path(custom_output).expanduser().resolve()


def resolve_remote_identity(machine_config: str, machine: str) -> tuple[str, str, str]:
    machine_info = load_machine(Path(machine_config).expanduser().resolve(), machine)
    ip, username, password = ensure_credentials(machine_info)
    return username, ip, password


def establish_machine_client(machine_config: str, machine: str):
    username, ip, password = resolve_remote_identity(
        machine_config=machine_config,
        machine=machine,
    )
    client = establish_client_connection(ip=ip, username=username, password=password)
    return client, username, ip


def filter_existing_in_collection_dir(
    remote_paths: list[str], output_dir: Path, suffix: str = ""
) -> tuple[list[str], list[str]]:
    if not output_dir.exists():
        return remote_paths, []

    to_download: list[str] = []
    already_exists: list[str] = []

    for remote_path in tqdm(remote_paths, desc="Checking existing files"):
        base_name = Path(remote_path).name
        suffixed_name = (
            f"{Path(base_name).stem}{suffix}{Path(base_name).suffix}" if suffix else ""
        )
        

        has_match = any(output_dir.rglob(f"*{base_name}"))
        if not has_match and suffixed_name:
            has_match = any(output_dir.rglob(f"*{suffixed_name}"))
        if has_match:
            already_exists.append(remote_path)
        else:
            to_download.append(remote_path)

    return to_download, already_exists


def find_existing_offline_dir(csv_path: Path) -> Path | None:
    parent = csv_path.parent
    preferred = parent / "offline_Samples"
    fallback = parent / "offline_samples"

    if preferred.exists() and preferred.is_dir():
        return preferred
    if fallback.exists() and fallback.is_dir():
        return fallback
    return None


def apply_suffix_to_downloaded_files(
    output_dir: Path, remote_paths: list[str], suffix: str
) -> None:
    if not suffix:
        return

    for remote_path in remote_paths:
        downloaded = output_dir / Path(remote_path).name
        if not downloaded.exists():
            continue

        target = downloaded.with_name(f"{downloaded.stem}{suffix}{downloaded.suffix}")
        if target.exists():
            print(f"Skipping rename because target exists: {target}", file=sys.stderr)
            continue
        downloaded.rename(target)


def download_offline_images(
    client,
    output_dir: Path,
    remote_paths: list[str],
    offline_suffix: str,
) -> int:
    if not remote_paths:
        print_message("No offline images to download.")
        return 0

    print_message(f"Downloading {len(remote_paths)} images over SSH...")
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        sftp = client.open_sftp()
    except Exception as exc:
        print(f"Failed to open SFTP session: {exc}", file=sys.stderr)
        return 3

    try:
        for remote_path in tqdm(remote_paths, desc="Downloading"):
            local_path = output_dir / Path(remote_path).name
            sftp.get(remote_path, str(local_path))
    except Exception as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 4
    finally:
        sftp.close()

    apply_suffix_to_downloaded_files(output_dir, remote_paths, offline_suffix)
    print(f"{format_message('Downloaded images to:')} {format_path(str(output_dir))}")
    if offline_suffix:
        print_message(f"Applied suffix '{offline_suffix}' to downloaded filenames")

    return 0


def main() -> int:
    args = parse_args()

    if args.begin_date > args.end_date:
        print("Error: --begin-date must be <= --end-date", file=sys.stderr)
        return 2

    csv_path = Path(args.bulk_download_csv).expanduser().resolve()

    bulk_names = load_bulk_download_names_in_range(
        csv_path=csv_path,
        begin_date=args.begin_date,
        end_date=args.end_date,
        verbose=args.verbose,
    )

    client, username, ip = establish_machine_client(
        machine_config=args.machine_config,
        machine=args.machine,
    )

    try:
        remote_names_to_path = probe_remote_names_in_range(
            client=client,
            remote_cmd=args.remote_cmd,
            begin_date=args.begin_date,
            end_date=args.end_date,
            verbose=args.verbose,
        )

        missing_remote_paths = sorted(
            path
            for name, path in remote_names_to_path.items()
            if name not in bulk_names
        )

        # Pre-filter against the collection directory (parent of output dir)
        # so the missing count shown to the user reflects already-existing files.
        collection_dir = csv_path.parent.parent
        
        missing_remote_paths, already_existing = filter_existing_in_collection_dir(
            remote_paths=missing_remote_paths,
            output_dir=collection_dir,
            suffix=args.offline_suffix,
        )
        print_message(f"Collection directory: {format_path(str(collection_dir))}")
        if already_existing:
            print(
                f"{format_message(f'Skipping {len(already_existing)} files already present in')} "
                f"{format_path(str(collection_dir))}"
            )

        print_message(
            "Checked machine "
            f"{format_bold(args.machine)} "
            "for files in range "
            f"[{format_bold(str(args.begin_date))}, {format_bold(str(args.end_date))}]"
        )
        print_message(f"bulk_download files in range: {len(bulk_names)}")
        print_message(f"remote files in range: {len(remote_names_to_path)}")

        missing_count = len(missing_remote_paths)
        if missing_count == 0:
            print_message(
                "No missing downloads found."
            )
            return 0
        print_message(
            f"Found {missing_count} missing offline files:"
        )
        for path in missing_remote_paths[:5]:
            print(format_path(path))
        if missing_count > 5:
            print(format_message(f"... and {missing_count - 5} more"))

        if not ask_yes_no("Do you want to download the offline images? [Y/n]: "):
            return 1

        output_dir = choose_output_dir(csv_path)

        # Keep the pre-filtered missing list so we do not reintroduce already-present files.
        filtered_remote_paths, already_existing = filter_existing_in_collection_dir(
            remote_paths=missing_remote_paths,
            output_dir=collection_dir,
            suffix=args.offline_suffix,
        )
        if already_existing:
            print(
                f"{format_message(f'Skipping {len(already_existing)} files already found under collection directory:')} "
                f"{format_path(str(collection_dir))}"
            )

        return download_offline_images(
            client=client,
            output_dir=output_dir,
            remote_paths=filtered_remote_paths,
            offline_suffix=args.offline_suffix,
        )
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
