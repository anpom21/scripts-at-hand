#!/usr/bin/env python3
"""Parsing of dangerous-waste inference records into CSV rows.

Owns record parsing and every CSV shape decision for the two record shapes that
exist in Firestore:

* legacy  -- an ``eval`` map with the fixed keys ``category``, ``constituent``,
  ``instruction`` and ``un_number``.
* columns -- an ``eval`` map carrying a ``columns`` array of ``{id, display_name}``
  entries and a parallel ``values`` array, plus ``row_index``, ``is_unknown``
  and ``raw_llm_output``.

Both shapes land in one CSV per unit with a single set of ``eval_<id>`` columns,
so a record from before the cutover and one from after it put their constituent
in the same column. A ``record_format`` column says which shape a row came from.

This module performs no I/O: no Firestore client, no file reads, no file writes.
Callers fetch the documents and write the files.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# The four eval keys the legacy shape always carried.
LEGACY_EVAL_IDS = ["category", "constituent", "instruction", "un_number"]

# Values written to the record_format column.
FORMAT_COLUMNS = "columns"
FORMAT_LEGACY = "legacy"

IDENTITY_COLS = ["doc_id", "unit", "timestamp_ms", "timestamp_iso", "human_eval"]

# Written after the derived eval_<id> columns. inference_time,
# has_unresolved_review and system_prompt_version are deliberately absent: they
# are runtime telemetry rather than evaluation data.
RECORD_COLS = [
    "eval_reason",
    "row_index",
    "is_unknown",
    "raw_llm_output",
    "waste_receiver_id",
    "llm_model",
    "sorting_list_version",
    "record_format",
]

IMAGE_COLS = [
    "front_image_1",
    "front_image_2",
    "front_image_3",
    "back_image_1",
    "back_image_2",
    "back_image_3",
]

# Fields only the columns shape carries; blank on legacy rows.
NEW_FORMAT_ONLY_COLS = ["row_index", "is_unknown", "raw_llm_output", "waste_receiver_id"]

_DANISH_FOLDING = {"æ": "ae", "ø": "oe", "å": "aa"}


class DwRecordError(Exception):
    """Base class for failures that must abort a unit before anything is written."""


class ColumnSetDisagreement(DwRecordError):
    """Two new-format records in one unit declare different eval column ids."""

    def __init__(
        self,
        unit: str,
        first_doc_id: str,
        first_ids: Sequence[str],
        other_doc_id: str,
        other_ids: Sequence[str],
    ) -> None:
        self.unit = unit
        self.first_doc_id = first_doc_id
        self.first_ids = list(first_ids)
        self.other_doc_id = other_doc_id
        self.other_ids = list(other_ids)
        super().__init__(
            f"Unit '{unit}': records disagree about the eval column set.\n"
            f"  {first_doc_id}: {self.first_ids}\n"
            f"  {other_doc_id}: {self.other_ids}\n"
            f"Nothing was written for this unit. Compare those two documents in Firestore."
        )


class PruneWouldDropLabelledRows(DwRecordError):
    """Firestore no longer returns documents whose CSV rows carry a human_eval."""

    def __init__(self, unit: str, doc_ids: Sequence[str]) -> None:
        self.unit = unit
        self.doc_ids = list(doc_ids)
        listed = "\n".join(f"  {d}" for d in self.doc_ids)
        super().__init__(
            f"Unit '{unit}': {len(self.doc_ids)} row(s) with a human_eval are no longer "
            f"returned by Firestore:\n{listed}\n"
            f"Nothing was written for this unit. Remove those rows by hand, or clear their "
            f"human_eval, if they really should go."
        )


@dataclass(frozen=True)
class UnitTable:
    """The header and rows derived from one unit's documents."""

    unit: str
    header: List[str]
    rows: List[Dict[str, str]]
    eval_ids: List[str]
    display_names: Dict[str, str]
    warnings: List[str] = field(default_factory=list)
    skipped_no_timestamp: List[str] = field(default_factory=list)
    excluded_test_records: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DroppedColumn:
    name: str
    rows_with_values: int


@dataclass(frozen=True)
class Reconciliation:
    """The rows to write, plus what changed relative to the existing CSV."""

    header: List[str]
    rows: List[Dict[str, str]]
    new_doc_ids: List[str]
    pruned_doc_ids: List[str]
    dropped_columns: List[DroppedColumn]
    kept_outside_range: List[str] = field(default_factory=list)


def slugify_display_name(name: str) -> str:
    """Key a column that carries no id, the way the insights dashboard does.

    Danish folding of æ/ø/å, lowercasing, and runs of non-alphanumeric
    characters collapsed to single underscores.
    """
    s = str(name or "").lower()
    for src, dst in _DANISH_FOLDING.items():
        s = s.replace(src, dst)
    out: List[str] = []
    for ch in s:
        if unicodedata.category(ch)[0] in ("L", "N"):
            out.append(ch)
        else:
            out.append("_")
    slug = re.sub(r"_+", "_", "".join(out)).strip("_")
    return slug


def is_new_format(data: Dict[str, Any]) -> bool:
    """True when a document uses the columns shape.

    ``eval.columns`` being a list identifies it directly. ``waste_receiver_id``
    and ``is_test`` exist only in the new structure, so they identify the format
    even when the eval itself is empty.
    """
    if not isinstance(data, dict):
        return False
    eval_obj = data.get("eval")
    if isinstance(eval_obj, dict) and isinstance(eval_obj.get("columns"), list):
        return True
    return "waste_receiver_id" in data or "is_test" in data


def ms_to_iso_utc(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def extract_doc_timestamp_ms(doc_id: str, unit: str) -> Optional[int]:
    """Parse the millisecond suffix out of a document id.

    A fallback only: the document's own timestamp field is preferred, so a
    change to the id naming scheme cannot silently drop every record.
    """
    suffix = ""
    prefix = f"{unit}_"
    if doc_id.startswith(prefix):
        suffix = doc_id[len(prefix) :]
    elif "_" in doc_id:
        suffix = doc_id.rsplit("_", 1)[1]
    if not suffix.isdigit() or len(suffix) < 10:
        return None
    return int(suffix)


def timestamp_ms_from_field(value: Any) -> Optional[int]:
    """Coerce a Firestore timestamp field into epoch milliseconds."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    if isinstance(value, (int, float)):
        # Below 1e11 the number cannot be milliseconds of any plausible date,
        # so it is seconds.
        return int(value * 1000) if abs(value) < 1e11 else int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return timestamp_ms_from_field(int(text))
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return timestamp_ms_from_field(dt)
    return None


def resolve_timestamp_ms(doc_id: str, unit: str, data: Dict[str, Any]) -> Optional[int]:
    ts = timestamp_ms_from_field(data.get("timestamp"))
    if ts is not None:
        return ts
    return extract_doc_timestamp_ms(doc_id, unit)


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(_to_text(v) for v in value)
    return str(value)


def _un_number_text(value: Any) -> str:
    """The legacy shape uses an integer 0 to mean 'not set'.

    Written as empty so it can never be compared against as though it were a
    real UN number.
    """
    if isinstance(value, bool):
        return _to_text(value)
    if isinstance(value, (int, float)) and value == 0:
        return ""
    text = _to_text(value).strip()
    return "" if text == "0" else text


def pad_images(values: Any, n: int = 3) -> List[str]:
    if not isinstance(values, list):
        values = []
    out = [_to_text(x) for x in values[:n]]
    while len(out) < n:
        out.append("")
    return out


def _eval_map(data: Dict[str, Any]) -> Dict[str, Any]:
    eval_obj = data.get("eval")
    return eval_obj if isinstance(eval_obj, dict) else {}


def _column_key(entry: Any, doc_id: str, warnings: List[str]) -> Tuple[str, str]:
    """Return (id, display_name) for one eval.columns entry.

    A column with no id is keyed by the slug of its display name. The dashboard
    only offers the id field while a receiver is being created, so any column
    added to an existing receiver permanently has no id.
    """
    if not isinstance(entry, dict):
        return "", ""
    display = _to_text(entry.get("display_name")).strip()
    col_id = _to_text(entry.get("id")).strip()
    if col_id:
        return col_id, display or col_id
    slug = slugify_display_name(display)
    if slug:
        warnings.append(
            f"{doc_id}: eval column '{display}' has no id; keyed by its slug '{slug}'."
        )
    return slug, display


def _parse_columns(
    eval_map: Dict[str, Any], doc_id: str, warnings: List[str]
) -> Tuple[Optional[List[str]], Dict[str, str], Dict[str, str]]:
    """Return (column ids, values by id, display names by id).

    Column ids are None when the record declares no columns at all, which is how
    a new-format record with an empty eval looks. Such a record does not take
    part in the column-set agreement check.
    """
    columns = eval_map.get("columns")
    if not isinstance(columns, list) or not columns:
        return None, {}, {}

    values = eval_map.get("values")
    if not isinstance(values, list):
        values = []

    ids: List[str] = []
    by_id: Dict[str, str] = {}
    display_names: Dict[str, str] = {}
    for index, entry in enumerate(columns):
        col_id, display = _column_key(entry, doc_id, warnings)
        if not col_id:
            warnings.append(f"{doc_id}: eval column at position {index} has no id and no display name; skipped.")
            continue
        raw = values[index] if index < len(values) else None
        ids.append(col_id)
        by_id[col_id] = _to_text(raw)
        display_names[col_id] = display or col_id
    return ids, by_id, display_names


def _legacy_values(eval_map: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in LEGACY_EVAL_IDS:
        raw = eval_map.get(key)
        out[key] = _un_number_text(raw) if key == "un_number" else _to_text(raw)
    return out


def _first_present(data: Dict[str, Any], eval_map: Dict[str, Any], key: str) -> str:
    if key in data:
        return _to_text(data.get(key))
    return _to_text(eval_map.get(key))


def build_header(eval_ids: Sequence[str]) -> List[str]:
    return (
        list(IDENTITY_COLS)
        + [f"eval_{i}" for i in eval_ids]
        + list(RECORD_COLS)
        + list(IMAGE_COLS)
    )


def build_unit_table(unit: str, docs: Iterable[Tuple[str, Dict[str, Any]]]) -> UnitTable:
    """Turn one unit's documents into a derived header and its rows.

    Raises ColumnSetDisagreement when two new-format records in the unit declare
    different eval column ids, before any row is returned.
    """
    warnings: List[str] = []
    skipped_no_timestamp: List[str] = []
    excluded_test_records: List[str] = []
    display_names: Dict[str, str] = {}

    column_ids: Optional[List[str]] = None
    column_source_doc = ""
    saw_legacy = False

    staged: List[Tuple[str, int, bool, Dict[str, str], Dict[str, Any]]] = []

    for doc_id, raw_data in docs:
        data = raw_data if isinstance(raw_data, dict) else {}

        # Records from internal testing of the app, not from real users.
        if data.get("is_test") is True:
            excluded_test_records.append(doc_id)
            continue

        ts = resolve_timestamp_ms(doc_id, unit, data)
        if ts is None:
            skipped_no_timestamp.append(doc_id)
            continue

        eval_map = _eval_map(data)
        new_format = is_new_format(data)

        if new_format:
            ids, values_by_id, doc_display_names = _parse_columns(eval_map, doc_id, warnings)
            if ids is not None:
                if column_ids is None:
                    column_ids = ids
                    column_source_doc = doc_id
                elif ids != column_ids:
                    raise ColumnSetDisagreement(unit, column_source_doc, column_ids, doc_id, ids)
                display_names.update(doc_display_names)
        else:
            saw_legacy = True
            values_by_id = _legacy_values(eval_map)

        staged.append((doc_id, ts, new_format, values_by_id, data))

    eval_ids = list(column_ids or [])
    if saw_legacy:
        # Legacy records always map onto the four fixed ids; any of them missing
        # from the derived set is appended after it.
        eval_ids += [i for i in LEGACY_EVAL_IDS if i not in eval_ids]

    header = build_header(eval_ids)

    rows: List[Dict[str, str]] = []
    for doc_id, ts, new_format, values_by_id, data in staged:
        eval_map = _eval_map(data)
        front = pad_images(data.get("front_images"))
        back = pad_images(data.get("back_images"))

        row = {col: "" for col in header}
        row.update(
            {
                "doc_id": doc_id,
                "unit": unit,
                "timestamp_ms": str(ts),
                "timestamp_iso": ms_to_iso_utc(ts),
                "human_eval": "",
                "eval_reason": _to_text(eval_map.get("reason")),
                "llm_model": _first_present(data, eval_map, "llm_model"),
                "sorting_list_version": _first_present(data, eval_map, "sorting_list_version"),
                "record_format": FORMAT_COLUMNS if new_format else FORMAT_LEGACY,
                "front_image_1": front[0],
                "front_image_2": front[1],
                "front_image_3": front[2],
                "back_image_1": back[0],
                "back_image_2": back[1],
                "back_image_3": back[2],
            }
        )
        for col_id, value in values_by_id.items():
            key = f"eval_{col_id}"
            if key in row:
                row[key] = value

        if new_format:
            row["row_index"] = _to_text(eval_map.get("row_index"))
            row["is_unknown"] = _to_text(eval_map.get("is_unknown"))
            row["raw_llm_output"] = _to_text(eval_map.get("raw_llm_output"))
            row["waste_receiver_id"] = _to_text(data.get("waste_receiver_id"))

        rows.append(row)

    rows.sort(key=lambda r: int(r["timestamp_ms"]), reverse=True)

    return UnitTable(
        unit=unit,
        header=header,
        rows=rows,
        eval_ids=eval_ids,
        display_names=display_names,
        warnings=warnings,
        skipped_no_timestamp=skipped_no_timestamp,
        excluded_test_records=excluded_test_records,
    )


def _row_timestamp_ms(row: Dict[str, str], unit: str) -> Optional[int]:
    text = (row.get("timestamp_ms") or "").strip()
    if text.isdigit():
        return int(text)
    doc_id = (row.get("doc_id") or "").strip()
    return extract_doc_timestamp_ms(doc_id, unit) if doc_id else None


def row_in_date_range(
    row: Dict[str, str],
    unit: str,
    begin_date: Optional[date],
    end_date: Optional[date],
) -> bool:
    """True when the row was recorded between begin_date and end_date, both inclusive.

    Either bound may be None to leave that side open; with neither, every row is
    in range. Dates are local calendar dates, matching the wood/mineral wool image
    sync, which reads them from machine-local image filenames. With a bound set, a
    row carrying no timestamp is out of range.
    """
    if begin_date is None and end_date is None:
        return True
    ms = _row_timestamp_ms(row, unit)
    if ms is None:
        return False
    day = datetime.fromtimestamp(ms / 1000.0).date()
    if begin_date is not None and day < begin_date:
        return False
    if end_date is not None and day > end_date:
        return False
    return True


def reconcile(
    table: UnitTable,
    existing_rows: Sequence[Dict[str, str]],
    existing_header: Sequence[str] = (),
    begin_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Reconciliation:
    """Merge the derived rows onto an existing CSV's rows.

    human_eval is carried over for every row that survives. Rows whose document
    Firestore no longer returns are pruned, and columns the derived header no
    longer holds are dropped. Raises PruneWouldDropLabelledRows when a row queued
    for pruning carries a human_eval, before anything is returned.

    With begin_date and/or end_date only that window is synced: derived rows
    outside it are not added, and existing rows outside it are kept as they are
    and never pruned.
    """
    def in_range(row: Dict[str, str]) -> bool:
        return row_in_date_range(row, table.unit, begin_date, end_date)

    existing_by_id: Dict[str, Dict[str, str]] = {}
    outside_by_id: Dict[str, Dict[str, str]] = {}
    for row in existing_rows:
        doc_id = (row.get("doc_id") or "").strip()
        if doc_id:
            (existing_by_id if in_range(row) else outside_by_id)[doc_id] = row

    fresh_rows = [r for r in table.rows if in_range(r)]
    fresh_ids = {r["doc_id"] for r in fresh_rows}

    pruned_doc_ids = [d for d in existing_by_id if d not in fresh_ids]
    labelled = [d for d in pruned_doc_ids if (existing_by_id[d].get("human_eval") or "").strip()]
    if labelled:
        raise PruneWouldDropLabelledRows(table.unit, labelled)

    rows: List[Dict[str, str]] = []
    new_doc_ids: List[str] = []
    for fresh in fresh_rows:
        doc_id = fresh["doc_id"]
        row = dict(fresh)
        previous = existing_by_id.get(doc_id)
        if previous is None:
            new_doc_ids.append(doc_id)
        else:
            row["human_eval"] = previous.get("human_eval") or ""
        rows.append(row)

    kept_outside_range = [d for d in outside_by_id if d not in fresh_ids]
    if kept_outside_range:
        rows.extend(dict(outside_by_id[d]) for d in kept_outside_range)
        rows.sort(key=lambda r: _row_timestamp_ms(r, table.unit) or 0, reverse=True)

    header_set = set(table.header)
    dropped_columns: List[DroppedColumn] = []
    for col in existing_header:
        if col in header_set:
            continue
        held = sum(1 for r in existing_rows if (r.get(col) or "").strip())
        dropped_columns.append(DroppedColumn(name=col, rows_with_values=held))

    return Reconciliation(
        header=list(table.header),
        rows=rows,
        new_doc_ids=new_doc_ids,
        pruned_doc_ids=pruned_doc_ids,
        dropped_columns=dropped_columns,
        kept_outside_range=kept_outside_range,
    )


def summary_lines(
    table: UnitTable,
    rec: Optional[Reconciliation] = None,
    new_record_limit: int = 10,
) -> List[str]:
    """Human-readable report for one unit's sync. Callers print it."""
    lines: List[str] = []

    for warning in table.warnings:
        lines.append(f"[WARN] {warning}")

    if table.excluded_test_records:
        lines.append(f"Excluded {len(table.excluded_test_records)} test record(s) (is_test=true).")

    if table.skipped_no_timestamp:
        lines.append(
            f"[WARN] Skipped {len(table.skipped_no_timestamp)} doc(s) with no usable timestamp: "
            + ", ".join(table.skipped_no_timestamp[:5])
            + (" ..." if len(table.skipped_no_timestamp) > 5 else "")
        )

    if rec is not None:
        if rec.new_doc_ids:
            by_id = {r["doc_id"]: r for r in rec.rows}
            lines.append(f"Found {len(rec.new_doc_ids)} new record(s). Showing up to {new_record_limit}:")
            for doc_id in rec.new_doc_ids[:new_record_limit]:
                row = by_id[doc_id]
                lines.append(
                    f"  - {doc_id} | {row['timestamp_iso']} | {row['record_format']}"
                    f" | eval_un_number={row.get('eval_un_number', '')}"
                )
        if rec.pruned_doc_ids:
            lines.append(f"Pruning {len(rec.pruned_doc_ids)} row(s) no longer in Firestore:")
            for doc_id in rec.pruned_doc_ids:
                lines.append(f"  - {doc_id}")
        if rec.kept_outside_range:
            lines.append(f"Keeping {len(rec.kept_outside_range)} row(s) outside the date range untouched.")
        for dropped in rec.dropped_columns:
            lines.append(
                f"Dropping column '{dropped.name}' ({dropped.rows_with_values} row(s) held a value)."
            )

    lines.append("Eval columns (id -> display name):")
    for col_id in table.eval_ids:
        lines.append(f"  eval_{col_id} -> {table.display_names.get(col_id, '(legacy field)')}")

    return lines
