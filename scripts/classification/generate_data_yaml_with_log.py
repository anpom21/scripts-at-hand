import argparse
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
import yaml
import re
import datetime

# ---------------------- YAML loading & helpers ----------------------

def load_yaml(path: Path):
    if not path.exists():
        sys.exit(f"ERROR: File not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        sys.exit(f"ERROR: Failed to parse YAML '{path}': {e}")

def normalize(name: str) -> str:
    s = name.strip().lower()
    s = s.replace("-", "_").replace(" ", "_").replace("/", "_")
    s = re.sub(r"_+", "_", s)
    return s

def reverse_subclass_map(class_sep: Dict) -> Tuple[Dict[str, str], List[str]]:
    rev = {}
    warnings = []
    for main_class, subclasses in (class_sep or {}).items():
        if subclasses is None:
            continue
        for sub in subclasses:
            key = normalize(str(sub))
            if key in rev and rev[key] != main_class:
                warnings.append(
                    f"Subclass '{sub}' appears under both '{rev[key]}' and '{main_class}'. "
                    f"Using '{rev[key]}' (first seen)."
                )
                continue
            rev[key] = main_class
    return rev, warnings

def list_images_in_dir(d: Path, allowed_exts: Set[str], recursive: bool) -> List[Path]:
    if not d.exists() or not d.is_dir():
        return []
    if recursive:
        it = d.rglob("*")
    else:
        it = d.iterdir()
    return [p.resolve() for p in it if p.is_file() and p.suffix.lower() in allowed_exts]

# ---------------------- Main data building ----------------------

def build_data_direct_dataset(
    base_dir: Path,
    subclass_to_main: Dict[str, str],
    allowed_exts: Set[str],
    prefer_images_subdir: str,
    ignore_subdirs: Set[str],
    recursive_within_images: bool
) -> Dict[str, Dict[str, List[str]]]:
    all_main_classes = sorted(set(subclass_to_main.values()))
    data = {
        "train": {mc: [] for mc in all_main_classes},
        "val": {mc: [] for mc in all_main_classes},
    }

    for split in ("train", "val"):
        split_path = (base_dir / split).resolve()

        if not split_path.exists() or not split_path.is_dir():
            print(f"WARNING: {split} folder not found or not a directory: {split_path}", file=sys.stderr)
            continue

        for subdir in split_path.iterdir():
            if not subdir.is_dir():
                continue

            subclass_name = subdir.name
            key = normalize(subclass_name)
            main_class = subclass_to_main.get(key)

            if main_class is None:
                continue

            images_root = subdir / prefer_images_subdir if prefer_images_subdir else subdir

            if prefer_images_subdir and images_root.exists() and images_root.is_dir():
                imgs = list_images_in_dir(images_root, allowed_exts, recursive_within_images)
            else:
                imgs = [
                    p.resolve()
                    for p in subdir.iterdir()
                    if p.is_file() and p.suffix.lower() in allowed_exts
                ]

                for child in subdir.iterdir():
                    if child.is_dir() and normalize(child.name) not in ignore_subdirs:
                        imgs.extend(list_images_in_dir(child, allowed_exts, recursive=False))

            if imgs:
                data[split][main_class].extend(str(p) for p in imgs)

        for mc, paths in data[split].items():
            data[split][mc] = sorted(set(paths))

    return data

def build_data(
    base_dir: Path,
    split_to_folders: Dict[str, List[str]],
    subclass_to_main: Dict[str, str],
    allowed_exts: Set[str],
    prefer_images_subdir: str,
    ignore_subdirs: Set[str],
    recursive_within_images: bool
) -> Dict[str, Dict[str, List[str]]]:
    all_main_classes = sorted(set(subclass_to_main.values()))
    data = {"train": {mc: [] for mc in all_main_classes},
            "val": {mc: [] for mc in all_main_classes}}

    for split in ("train", "val"):
        folders = split_to_folders.get(split, []) or []
        for folder_name in folders:
            folder_path = (base_dir / split / folder_name).resolve()
            if not folder_path.exists() or not folder_path.is_dir():
                print(f"WARNING: {split} folder not found or not a directory: {folder_path}", file=sys.stderr)
                continue

            for subdir in folder_path.iterdir():
                if not subdir.is_dir():
                    continue
                subclass_name = subdir.name
                key = normalize(subclass_name)
                main_class = subclass_to_main.get(key)
                if main_class is None:
                    continue

                images_root = subdir / prefer_images_subdir if prefer_images_subdir else subdir
                if prefer_images_subdir and images_root.exists() and images_root.is_dir():
                    imgs = list_images_in_dir(images_root, allowed_exts, recursive_within_images)
                else:
                    imgs = [p.resolve() for p in subdir.iterdir() if p.is_file() and p.suffix.lower() in allowed_exts]
                    for child in subdir.iterdir():
                        if child.is_dir() and normalize(child.name) not in ignore_subdirs:
                            imgs.extend(list_images_in_dir(child, allowed_exts, recursive=False))

                if imgs:
                    data[split][main_class].extend(str(p) for p in imgs)

        for mc, paths in data[split].items():
            data[split][mc] = sorted(set(paths))

    return data

# ---------------------- Summary helpers ----------------------

def compute_summary(data: Dict[str, Dict[str, List[str]]]):
    totals_by_split = {split: sum(len(v) for v in data[split].values()) for split in ("train", "val")}
    overall = sum(totals_by_split.values()) or 1
    split_summary = []
    for split in ("train", "val"):
        split_summary.append({
            "split": split,
            "count": totals_by_split[split],
            "share_overall": totals_by_split[split] / overall
        })
    class_summary = []
    for split in ("train", "val"):
        split_total = totals_by_split[split] or 1
        for cls, items in sorted(data[split].items()):
            class_summary.append({
                "split": split,
                "class": cls,
                "count": len(items),
                "share_of_split": (len(items) / split_total)
            })
    return split_summary, class_summary

def format_pct(x: float) -> str:
    return f"{x*100:.2f}%"

def _print_table(headers: List[str], rows: List[List[str]], logf=None):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    def fmt_row(r):
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r))
    lines = []
    lines.append(fmt_row(headers))
    lines.append("  ".join("-"*w for w in widths))
    for r in rows:
        lines.append(fmt_row(r))
    for line in lines:
        print(line)
        if logf:
            logf.write(line + "\n")

def print_summary(split_summary, class_summary, log_path=None):
    logf = None
    if log_path:
        logf = open(log_path, "a", encoding="utf-8")
        logf.write(f"\n=== Run at {datetime.datetime.now().isoformat()} ===\n")
    try:
        # Split level
        hdr = ["Split", "Count", "Share of overall"]
        rows = [[r["split"], str(r["count"]), format_pct(r["share_overall"])] for r in split_summary]
        print("\n=== Summary: by split ===")
        if logf: logf.write("\n=== Summary: by split ===\n")
        _print_table(hdr, rows, logf)

        # Class level
        for split in ("train", "val"):
            hdr = ["Class", "Count", "Share of split"]
            rows = []
            for r in class_summary:
                if r["split"] == split:
                    rows.append([r["class"], str(r["count"]), format_pct(r["share_of_split"])])
            print(f"\n=== Summary: by class (within {split}) ===")
            if logf: logf.write(f"\n=== Summary: by class (within {split}) ===\n")
            _print_table(hdr, rows, logf)
    finally:
        if logf:
            logf.close()

# ---------------------- Main entry ----------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base_dir", required=True, type=Path)
    parser.add_argument("--input_folders", required=False, type=Path)
    parser.add_argument("--class_separation", required=True, type=Path)
    parser.add_argument("--out", default="data.yaml", type=Path)
    parser.add_argument("--exts", default=".jpg,.jpeg,.png,.bmp,.tif,.tiff,.webp")
    parser.add_argument("--images_subdir", default="images")
    parser.add_argument("--ignore_subdirs", default="annots,annotations,labels")
    parser.add_argument("--recursive_within_images", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--log_file", type=Path, help="Optional log file to also write the summary tables")
    args = parser.parse_args()

    allowed_exts = {e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
                    for e in args.exts.split(",") if e.strip()}
    ignore_subdirs = {normalize(x) for x in args.ignore_subdirs.split(",") if x.strip()}
    prefer_images_subdir = args.images_subdir.strip() or None

    class_sep = load_yaml(args.class_separation)

    subclass_to_main, warnings = reverse_subclass_map(class_sep)

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    if args.input_folders is not None:
        input_cfg = load_yaml(args.input_folders)

        data = build_data(
            base_dir=args.base_dir,
            split_to_folders={
                "train": input_cfg.get("train", []),
                "val": input_cfg.get("val", []),
            },
            subclass_to_main=subclass_to_main,
            allowed_exts=allowed_exts,
            prefer_images_subdir=prefer_images_subdir,
            ignore_subdirs=ignore_subdirs,
            recursive_within_images=args.recursive_within_images,
        )
    else:
        data = build_data_direct_dataset(
            base_dir=args.base_dir,
            subclass_to_main=subclass_to_main,
            allowed_exts=allowed_exts,
            prefer_images_subdir=prefer_images_subdir,
            ignore_subdirs=ignore_subdirs,
            recursive_within_images=args.recursive_within_images,
        )

    with args.out.open("w", encoding="utf-8") as f:
        yaml.dump({"train": data["train"], "val": data["val"]}, f, sort_keys=False, allow_unicode=True)

    split_summary, class_summary = compute_summary(data)
    print_summary(split_summary, class_summary, log_path=args.log_file)

if __name__ == "__main__":
    main()
