"""Tests for the dual-format dangerous-waste record parser.

The seam under test is build_unit_table: documents in, header and rows out, or
a raised failure. Fixtures are literal dictionaries modelled on real Firestore
documents of both shapes. Nothing here touches Firestore or the network.
"""

from datetime import date, datetime, timezone

import pytest

import dw_records
from dw_records import ColumnSetDisagreement, PruneWouldDropLabelledRows

UNIT = "jolly-giraffe"


def legacy_doc(doc_id="jolly-giraffe_1786887753498", **overrides):
    doc = {
        "eval": {
            "category": "H",
            "constituent": "Epoxy (ikke faremærket)",
            "instruction": "Malingsrester i småemballager, sorteret (H2)",
            "un_number": 0,
            "reason": "Emballagen er mærket epoxy.",
        },
        "front_images": ["img_jolly-giraffe_2026-08-16T15-42-28-516.jpg"],
        "back_images": ["img_jolly-giraffe_2026-08-16T15-42-29-512.jpg"],
        "sorting_list_version": "v3",
        "llm_model": "gemini-2.0-flash",
    }
    doc.update(overrides)
    return (doc_id, doc)


def columns_doc(doc_id="jolly-giraffe_1789000000000", values=None, columns=None, **overrides):
    if columns is None:
        columns = [
            {"id": "constituent", "display_name": "Bestanddel"},
            {"id": "category", "display_name": "Kategori"},
            {"id": "un_number", "display_name": "UN-nummer"},
        ]
    if values is None:
        values = ["Spraydåser", "H", "1950"]
    doc = {
        "eval": {
            "columns": columns,
            "values": values,
            "row_index": 42,
            "is_unknown": False,
            "raw_llm_output": '{"row_index": 42}',
            "reason": "Dåsen er under tryk.",
        },
        "front_images": ["img_jolly-giraffe_2026-09-01T10-00-00-000.jpg"],
        "back_images": [],
        "waste_receiver_id": "marius-pedersen",
        "is_test": False,
        "sorting_list_version": 7,
        "llm_model": "gemini-2.5-flash",
    }
    doc.update(overrides)
    return (doc_id, doc)


def row_by_id(table, doc_id):
    return next(r for r in table.rows if r["doc_id"] == doc_id)


def test_legacy_record_maps_onto_derived_eval_columns():
    table = dw_records.build_unit_table(UNIT, [legacy_doc()])

    assert table.eval_ids == ["category", "constituent", "instruction", "un_number"]
    row = table.rows[0]
    assert row["eval_constituent"] == "Epoxy (ikke faremærket)"
    assert row["eval_category"] == "H"
    assert row["eval_reason"] == "Emballagen er mærket epoxy."
    assert row["record_format"] == "legacy"
    assert row["sorting_list_version"] == "v3"
    assert row["front_image_1"] == "img_jolly-giraffe_2026-08-16T15-42-28-516.jpg"
    assert row["front_image_2"] == ""


def test_new_format_record_lands_in_the_same_columns_as_a_legacy_one():
    table = dw_records.build_unit_table(UNIT, [legacy_doc(), columns_doc()])

    legacy_row = row_by_id(table, "jolly-giraffe_1786887753498")
    new_row = row_by_id(table, "jolly-giraffe_1789000000000")

    assert legacy_row["eval_constituent"] == "Epoxy (ikke faremærket)"
    assert new_row["eval_constituent"] == "Spraydåser"
    assert new_row["eval_category"] == "H"
    assert new_row["record_format"] == "columns"
    assert new_row["waste_receiver_id"] == "marius-pedersen"
    assert new_row["row_index"] == "42"
    assert new_row["is_unknown"] == "false"
    assert new_row["raw_llm_output"] == '{"row_index": 42}'
    assert new_row["sorting_list_version"] == "7"


def test_both_shapes_produce_one_header_with_legacy_only_ids_appended():
    table = dw_records.build_unit_table(UNIT, [columns_doc(), legacy_doc()])

    # Receiver order first, then the legacy ids the receiver does not configure.
    assert table.eval_ids == ["constituent", "category", "un_number", "instruction"]
    assert table.header[:5] == ["doc_id", "unit", "timestamp_ms", "timestamp_iso", "human_eval"]
    assert table.header[5:9] == [
        "eval_constituent",
        "eval_category",
        "eval_un_number",
        "eval_instruction",
    ]
    assert "record_format" in table.header
    assert table.header[-6:] == dw_records.IMAGE_COLS


def test_new_format_only_fields_are_blank_on_a_legacy_row():
    table = dw_records.build_unit_table(UNIT, [legacy_doc(), columns_doc()])
    legacy_row = row_by_id(table, "jolly-giraffe_1786887753498")

    assert legacy_row["row_index"] == ""
    assert legacy_row["is_unknown"] == ""
    assert legacy_row["raw_llm_output"] == ""
    assert legacy_row["waste_receiver_id"] == ""


def test_record_with_empty_eval_still_produces_a_row():
    table = dw_records.build_unit_table(UNIT, [legacy_doc(eval={})])

    assert len(table.rows) == 1
    assert table.rows[0]["eval_constituent"] == ""
    assert table.rows[0]["record_format"] == "legacy"


def test_new_format_record_with_empty_eval_is_still_new_format():
    by_receiver = ("jolly-giraffe_1789000000001", {"eval": {}, "waste_receiver_id": "marius-pedersen"})
    by_is_test = ("jolly-giraffe_1789000000002", {"eval": {}, "is_test": False})

    table = dw_records.build_unit_table(UNIT, [by_receiver, by_is_test])

    assert [r["record_format"] for r in table.rows] == ["columns", "columns"]


def test_test_records_are_excluded():
    table = dw_records.build_unit_table(
        UNIT, [legacy_doc(), columns_doc(doc_id="jolly-giraffe_1789000000003", is_test=True)]
    )

    assert [r["doc_id"] for r in table.rows] == ["jolly-giraffe_1786887753498"]
    assert table.excluded_test_records == ["jolly-giraffe_1789000000003"]


def test_column_with_no_id_is_keyed_by_its_slugified_display_name():
    columns = [
        {"id": "constituent", "display_name": "Bestanddel"},
        {"display_name": "Farlige egenskaber (å, ø)"},
    ]
    table = dw_records.build_unit_table(
        UNIT, [columns_doc(columns=columns, values=["Spraydåser", "H3"])]
    )

    assert table.eval_ids == ["constituent", "farlige_egenskaber_aa_oe"]
    assert table.rows[0]["eval_farlige_egenskaber_aa_oe"] == "H3"
    assert any("has no id" in w for w in table.warnings)


def test_disagreeing_column_sets_raise_naming_both_documents():
    first = columns_doc(doc_id="jolly-giraffe_1789000000004")
    second = columns_doc(
        doc_id="jolly-giraffe_1789000000005",
        columns=[
            {"id": "constituent", "display_name": "Bestanddel"},
            {"id": "category", "display_name": "Kategori"},
        ],
        values=["Maling", "H"],
    )

    with pytest.raises(ColumnSetDisagreement) as excinfo:
        dw_records.build_unit_table(UNIT, [first, second])

    message = str(excinfo.value)
    assert "jolly-giraffe_1789000000004" in message
    assert "jolly-giraffe_1789000000005" in message
    assert "un_number" in message


def test_legacy_un_number_sentinel_of_zero_becomes_empty():
    table = dw_records.build_unit_table(UNIT, [legacy_doc()])
    assert table.rows[0]["eval_un_number"] == ""


def test_real_un_number_survives_as_a_string():
    doc_id, doc = legacy_doc()
    doc["eval"]["un_number"] = 1950
    table = dw_records.build_unit_table(UNIT, [(doc_id, doc)])

    assert table.rows[0]["eval_un_number"] == "1950"


def test_timestamp_field_is_used_when_the_doc_id_carries_none():
    doc_id, doc = columns_doc(doc_id="AbCdEf0123456789", timestamp="2026-09-01T10:00:00Z")

    table = dw_records.build_unit_table(UNIT, [(doc_id, doc)])

    assert table.skipped_no_timestamp == []
    assert table.rows[0]["timestamp_ms"] == "1788256800000"
    assert table.rows[0]["timestamp_iso"] == "2026-09-01T10:00:00.000Z"


def test_document_with_no_timestamp_at_all_is_skipped():
    table = dw_records.build_unit_table(UNIT, [("no-timestamp-here", {"eval": {}})])

    assert table.rows == []
    assert table.skipped_no_timestamp == ["no-timestamp-here"]


def test_rows_are_ordered_newest_first():
    table = dw_records.build_unit_table(UNIT, [legacy_doc(), columns_doc()])

    assert [r["doc_id"] for r in table.rows] == [
        "jolly-giraffe_1789000000000",
        "jolly-giraffe_1786887753498",
    ]


def test_reconcile_preserves_human_eval_and_reports_new_rows():
    table = dw_records.build_unit_table(UNIT, [legacy_doc(), columns_doc()])
    existing = [{"doc_id": "jolly-giraffe_1786887753498", "human_eval": "correct"}]

    rec = dw_records.reconcile(table, existing, ["doc_id", "human_eval"])

    assert rec.new_doc_ids == ["jolly-giraffe_1789000000000"]
    assert rec.pruned_doc_ids == []
    kept = next(r for r in rec.rows if r["doc_id"] == "jolly-giraffe_1786887753498")
    assert kept["human_eval"] == "correct"


def test_reconcile_prunes_unlabelled_rows_firestore_no_longer_returns():
    table = dw_records.build_unit_table(UNIT, [legacy_doc()])
    existing = [
        {"doc_id": "jolly-giraffe_1786887753498", "human_eval": ""},
        {"doc_id": "jolly-giraffe_1700000000000", "human_eval": ""},
    ]

    rec = dw_records.reconcile(table, existing, ["doc_id", "human_eval"])

    assert rec.pruned_doc_ids == ["jolly-giraffe_1700000000000"]
    assert [r["doc_id"] for r in rec.rows] == ["jolly-giraffe_1786887753498"]


def test_reconcile_refuses_to_prune_a_labelled_row():
    table = dw_records.build_unit_table(UNIT, [legacy_doc()])
    existing = [{"doc_id": "jolly-giraffe_1700000000000", "human_eval": "wrong"}]

    with pytest.raises(PruneWouldDropLabelledRows) as excinfo:
        dw_records.reconcile(table, existing, ["doc_id", "human_eval"])

    assert "jolly-giraffe_1700000000000" in str(excinfo.value)


def test_reconcile_drops_dead_columns_with_a_count_of_rows_that_held_values():
    table = dw_records.build_unit_table(UNIT, [legacy_doc()])
    existing_header = ["doc_id", "human_eval", "eval_gammelt_navn"]
    existing = [
        {"doc_id": "jolly-giraffe_1786887753498", "human_eval": "", "eval_gammelt_navn": "H3"},
        {"doc_id": "jolly-giraffe_1786887753499", "human_eval": "", "eval_gammelt_navn": ""},
    ]

    rec = dw_records.reconcile(table, existing, existing_header)

    dropped = {d.name: d.rows_with_values for d in rec.dropped_columns}
    assert dropped == {"eval_gammelt_navn": 1}


def test_slugify_folds_danish_characters():
    assert dw_records.slugify_display_name("Farlige egenskaber") == "farlige_egenskaber"
    assert dw_records.slugify_display_name("Æblegrød, Øl & Ål") == "aeblegroed_oel_aal"
    assert dw_records.slugify_display_name("UN-nummer ") == "un_nummer"


def september_noon_ms(day):
    # Noon UTC lands on the same local date in any timezone the machines run in.
    return int(datetime(2026, 9, day, 12, tzinfo=timezone.utc).timestamp() * 1000)


def doc_on(day):
    return legacy_doc(doc_id=f"{UNIT}_{september_noon_ms(day)}")


def existing_row_on(day, human_eval=""):
    ms = september_noon_ms(day)
    return {"doc_id": f"{UNIT}_{ms}", "timestamp_ms": str(ms), "human_eval": human_eval}


def test_reconcile_with_a_date_range_only_adds_records_inside_it():
    table = dw_records.build_unit_table(UNIT, [doc_on(1), doc_on(5), doc_on(9)])

    rec = dw_records.reconcile(table, [], [], date(2026, 9, 4), date(2026, 9, 6))

    assert rec.new_doc_ids == [f"{UNIT}_{september_noon_ms(5)}"]
    assert [r["doc_id"] for r in rec.rows] == [f"{UNIT}_{september_noon_ms(5)}"]


def test_reconcile_with_a_date_range_leaves_rows_outside_it_untouched_and_unpruned():
    table = dw_records.build_unit_table(UNIT, [doc_on(5)])
    existing = [existing_row_on(1, human_eval="correct"), existing_row_on(3), existing_row_on(5)]

    rec = dw_records.reconcile(table, existing, ["doc_id", "timestamp_ms", "human_eval"], date(2026, 9, 2), date(2026, 9, 6))

    assert rec.pruned_doc_ids == [f"{UNIT}_{september_noon_ms(3)}"]
    assert rec.kept_outside_range == [f"{UNIT}_{september_noon_ms(1)}"]
    assert [r["doc_id"] for r in rec.rows] == [f"{UNIT}_{september_noon_ms(5)}", f"{UNIT}_{september_noon_ms(1)}"]
    assert rec.rows[1]["human_eval"] == "correct"


def test_date_range_bounds_are_inclusive_and_either_side_may_be_open():
    row = existing_row_on(5)

    assert dw_records.row_in_date_range(row, UNIT, date(2026, 9, 5), date(2026, 9, 5))
    assert dw_records.row_in_date_range(row, UNIT, date(2026, 9, 5), None)
    assert dw_records.row_in_date_range(row, UNIT, None, date(2026, 9, 5))
    assert not dw_records.row_in_date_range(row, UNIT, date(2026, 9, 6), None)
    assert not dw_records.row_in_date_range(row, UNIT, None, date(2026, 9, 4))


def test_date_range_falls_back_to_the_doc_id_timestamp():
    row = {"doc_id": f"{UNIT}_{september_noon_ms(5)}"}

    assert dw_records.row_in_date_range(row, UNIT, date(2026, 9, 5), date(2026, 9, 5))
    assert not dw_records.row_in_date_range({"doc_id": "no-timestamp"}, UNIT, date(2026, 9, 5), None)
