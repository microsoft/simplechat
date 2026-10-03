#!/usr/bin/env python3
# test_tabular_merge_reconciliation.py
"""
Functional test for reconciling differently structured spreadsheets in the merge engine.
Version: 0.261.219
Implemented in: 0.261.219

This test ensures that functions_tabular_merge can merge files whose columns differ:
union keeps every column and leaves missing ones null, mapped keeps exactly the requested
columns and reports the rest, aliases line up renamed headers, a header row below a
title is honoured, every sheet of a workbook can be merged with its sheet name, files
that don't fit can be left out and reported, duplicate rows are removed exactly, rows
are sorted deterministically within a bound, and inspection describes each file and how
the files line up without failing on one unreadable file.
"""

import io
import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "application", "single_app"))

from test_support.versioning import assert_app_version_at_least

from functions_tabular_merge import (
    TabularInspectOptions,
    TabularMergeError,
    TabularMergeLimits,
    TabularMergeOptions,
    TabularMergeSort,
    TabularMergeSource,
    inspect_tabular_sources,
    merge_tabular_sources,
    squash_header_name,
)


def csv_source(name, text, source_id=None):
    data = text.encode("utf-8")
    return TabularMergeSource(source_id or name, name, lambda data=data: data)


def bytes_source(name, data, source_id=None):
    return TabularMergeSource(source_id or name, name, lambda data=data: data)


def xlsx_bytes(sheets):
    from openpyxl import Workbook

    workbook = Workbook()
    first = True
    for title, rows, state in sheets:
        worksheet = workbook.active if first else workbook.create_sheet()
        first = False
        worksheet.title = title
        worksheet.sheet_state = state
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def merged(sources, **options):
    with merge_tabular_sources(sources, options=TabularMergeOptions(**options)) as result:
        return result.columns, list(result.iter_records()), result.report, result.nullable_columns


def test_version_includes_reconciliation():
    assert_app_version_at_least("0.261.219")


def test_union_keeps_every_column_and_leaves_missing_values_null():
    first = csv_source("jan.csv", "Region,Amount\nEast,10\n")
    second = csv_source("feb.csv", "Amount,Region,Channel\n5,West,Online\n")
    third = csv_source("mar.csv", "Region\nNorth\n")
    columns, rows, report, nullable = merged([first, second, third], schema_policy="union")
    assert columns == ("Source File", "Region", "Amount", "Channel")
    assert rows == [
        {"Source File": "jan.csv", "Region": "East", "Amount": "10", "Channel": None},
        {"Source File": "feb.csv", "Region": "West", "Amount": "5", "Channel": "Online"},
        {"Source File": "mar.csv", "Region": "North", "Amount": None, "Channel": None},
    ]
    assert nullable == {"Amount", "Channel"}
    assert report["nullable_columns"] == ["Amount", "Channel"]
    assert report["sources"][1]["extra_columns"] == ["Channel"]
    assert report["sources"][2]["missing_columns"] == ["Amount", "Channel"]
    assert any("left blank" in text for text in report["limitations"])


def test_union_renames_a_later_column_that_collides_with_the_file_name_column():
    first = csv_source("a.csv", "Region\nEast\n")
    second = csv_source("b.csv", "Region,Source File\nWest,legacy\n")
    columns, rows, report, _ = merged([first, second], schema_policy="union")
    assert columns == ("Source File", "Region", "Source File (2)")
    assert rows[1] == {"Source File": "b.csv", "Region": "West", "Source File (2)": "legacy"}
    assert [warning["code"] for warning in report["warnings"]] == ["column_renamed"]


def test_aliases_line_up_renamed_headers_under_every_policy():
    first = csv_source("a.csv", "Customer ID,Amount\n001,10\n")
    second = csv_source("b.csv", "cust_id,Total\n002,5\n")
    aliases = {"Customer ID": ["cust_id", "CustomerID"], "Amount": ["Total"]}
    columns, rows, report, nullable = merged([first, second], column_aliases=aliases)
    assert columns == ("Source File", "Customer ID", "Amount")
    assert [row["Customer ID"] for row in rows] == ["001", "002"]
    assert report["sources"][1]["renamed_columns"] == [
        {"from": "cust_id", "to": "Customer ID"}, {"from": "Total", "to": "Amount"},
    ]
    assert nullable == frozenset()
    assert report["policy"]["column_aliases"] == {"Customer ID": ["cust_id", "CustomerID"], "Amount": ["Total"]}

    clash = csv_source("c.csv", "Customer ID,cust_id\n1,2\n")
    with pytest.raises(TabularMergeError) as caught:
        merged([first, clash], column_aliases=aliases)
    assert caught.value.code == "duplicate_columns"


@pytest.mark.parametrize("aliases", [
    {"Customer ID": ["Amount"], "Amount": ["Total"]},
    {"Customer ID": ["Key"], "Account": ["key"]},
    {"Customer ID": []},
    {"Customer ID": "cust_id"},
    {"": ["x"]},
])
def test_invalid_aliases_are_refused(aliases):
    with pytest.raises(TabularMergeError) as caught:
        TabularMergeOptions(column_aliases=aliases)
    assert caught.value.code == "invalid_options"


def test_identity_aliases_are_ignored():
    options = TabularMergeOptions(column_aliases={"Region": ["region", " REGION "]})
    assert options.column_aliases == ()


def test_mapped_keeps_exactly_the_requested_columns_and_reports_the_rest():
    first = csv_source("a.csv", "cust_id,Amount,Notes\n001,10,hello\n")
    second = csv_source("b.csv", "Amount,Region\n5,West\n")
    columns, rows, report, nullable = merged(
        [first, second], schema_policy="mapped", columns=["Customer ID", "Amount", "Region"],
        column_aliases={"Customer ID": ["cust_id"]}, include_source_column=False,
    )
    assert columns == ("Customer ID", "Amount", "Region")
    assert rows == [
        {"Customer ID": "001", "Amount": "10", "Region": None},
        {"Customer ID": None, "Amount": "5", "Region": "West"},
    ]
    assert nullable == {"Customer ID", "Region"}
    assert report["sources"][0]["ignored_columns"] == ["Notes"]
    assert report["sources"][0]["missing_columns"] == ["Region"]
    assert any("left out" in text for text in report["limitations"])


def test_mapped_fails_or_excludes_a_file_with_none_of_the_columns():
    first = csv_source("a.csv", "Amount\n10\n")
    stray = csv_source("notes.csv", "Comment\nhello\n")
    with pytest.raises(TabularMergeError) as caught:
        merged([first, stray], schema_policy="mapped", columns=["Amount"])
    assert caught.value.code == "schema_mismatch"
    assert caught.value.report["sources"][1]["reason"] == "no_matching_columns"

    columns, rows, report, _ = merged(
        [first, stray], schema_policy="mapped", columns=["Amount"], on_incompatible="exclude",
    )
    assert [row["Amount"] for row in rows] == ["10"]
    assert report["sources"][1]["status"] == "excluded"
    assert report["totals"]["excluded"] == 1


def test_mapped_requires_columns_and_columns_require_mapped():
    with pytest.raises(TabularMergeError):
        TabularMergeOptions(schema_policy="mapped")
    with pytest.raises(TabularMergeError):
        TabularMergeOptions(columns=["Amount"])
    with pytest.raises(TabularMergeError):
        TabularMergeOptions(schema_policy="mapped", columns=["Amount", "amount"])
    with pytest.raises(TabularMergeError):
        TabularMergeOptions(schema_policy="mapped", columns=["Amount"], column_aliases={"Region": ["Area"]})


def test_excluding_files_whose_columns_differ_keeps_completeness_honest():
    first = csv_source("a.csv", "Region,Amount\nEast,10\n")
    odd = csv_source("odd.csv", "Region,Total\nWest,5\n")
    third = csv_source("c.csv", "Amount,Region\n7,North\n")
    with pytest.raises(TabularMergeError) as caught:
        merged([first, odd, third])
    assert caught.value.code == "schema_mismatch"
    statuses = [entry["status"] for entry in caught.value.report["sources"]]
    assert statuses == ["compatible", "schema_mismatch", "compatible"]

    columns, rows, report, _ = merged([first, odd, third], on_incompatible="exclude")
    assert [row["Source File"] for row in rows] == ["a.csv", "c.csv"]
    assert [entry["status"] for entry in report["sources"]] == ["merged", "excluded", "merged"]
    assert report["sources"][1]["reason"] == "columns_differ"
    assert report["sources"][1]["missing_columns"] == ["Amount"]
    assert report["totals"]["excluded"] == 1 and report["totals"]["tables_merged"] == 2
    assert "1 of 3 file(s) or sheet(s) were left out" in report["limitations"][0]


def test_nothing_to_merge_when_every_file_is_left_out():
    empty = csv_source("empty.csv", "\n\n")
    other = csv_source("blank.csv", " , \n")
    with pytest.raises(TabularMergeError) as caught:
        merged([empty, other], on_incompatible="exclude")
    assert caught.value.code == "nothing_to_merge"


def test_header_row_skips_title_rows_in_csv_and_workbooks():
    titled = csv_source("titled.csv", "Quarterly sales\n\nRegion,Amount\nEast,10\n")
    plain = bytes_source("plain.xlsx", xlsx_bytes([(
        "Data", [["Report"], [None], ["Region", "Amount"], ["West", 5]], "visible",
    )]))
    columns, rows, report, _ = merged([titled, plain], header_row=3)
    assert columns == ("Source File", "Region", "Amount")
    assert [row["Region"] for row in rows] == ["East", "West"]
    assert [entry["header_row"] for entry in report["sources"]] == [3, 3]

    blank_at_header = csv_source("gap.csv", "Title\n\n\nRegion\n")
    with pytest.raises(TabularMergeError) as caught:
        merged([titled, blank_at_header], header_row=3)
    assert caught.value.code == "empty_source"
    for invalid in (0, 1001, True, "3"):
        with pytest.raises(TabularMergeError):
            TabularMergeOptions(header_row=invalid)


def test_all_sheets_merges_every_visible_sheet_with_its_name():
    workbook = bytes_source("regions.xlsx", xlsx_bytes([
        ("East", [["Region", "Amount"], ["East", 1]], "visible"),
        ("Hidden", [["Region", "Amount"], ["Secret", 99]], "hidden"),
        ("Empty", [], "visible"),
        ("West", [["Amount", "Region"], [2, "West"]], "visible"),
    ]))
    loose = csv_source("north.csv", "Region,Amount\nNorth,3\n")
    columns, rows, report, nullable = merged([workbook, loose], sheets="all")
    assert columns == ("Source File", "Source Sheet", "Region", "Amount")
    assert rows == [
        {"Source File": "regions.xlsx", "Source Sheet": "East", "Region": "East", "Amount": "1"},
        {"Source File": "regions.xlsx", "Source Sheet": "West", "Region": "West", "Amount": "2"},
        {"Source File": "north.csv", "Source Sheet": None, "Region": "North", "Amount": "3"},
    ]
    assert nullable == {"Source Sheet"}
    assert report["sheet_column"] == "Source Sheet"
    assert [(entry["sheet"], entry["status"], entry["reason"]) for entry in report["sources"]] == [
        ("East", "merged", None), ("Hidden", "skipped", "hidden_sheet"), ("Empty", "skipped", "no_header_row"),
        ("West", "merged", None), (None, "merged", None),
    ]
    with pytest.raises(TabularMergeError):
        TabularMergeOptions(sheet="East", sheets="all")


def test_all_sheets_with_exclusion_merges_only_the_matching_sheets():
    workbook = bytes_source("book.xlsx", xlsx_bytes([
        ("Data", [["Region", "Amount"], ["East", 1]], "visible"),
        ("Notes", [["Comment"], ["Checked"]], "visible"),
    ]))
    other = bytes_source("other.xlsx", xlsx_bytes([("Data", [["Region", "Amount"], ["West", 2]], "visible")]))
    _, rows, report, _ = merged([workbook, other], sheets="all", on_incompatible="exclude")
    assert [(row["Source Sheet"], row["Region"]) for row in rows] == [("Data", "East"), ("Data", "West")]
    assert [entry["status"] for entry in report["sources"]] == ["merged", "excluded", "merged"]


def test_a_missing_named_sheet_can_be_left_out():
    first = bytes_source("a.xlsx", xlsx_bytes([("Totals", [["A"], [1]], "visible")]))
    second = bytes_source("b.xlsx", xlsx_bytes([("Other", [["A"], [2]], "visible")]))
    with pytest.raises(TabularMergeError) as caught:
        merged([first, second], sheet="Totals")
    assert caught.value.code == "sheet_not_found"
    _, rows, report, _ = merged([first, second], sheet="Totals", on_incompatible="exclude")
    assert [row["A"] for row in rows] == ["1"]
    assert report["sources"][1]["reason"] == "sheet_not_found"


def test_exact_duplicate_rows_are_removed_across_files_keeping_the_first():
    first = csv_source("a.csv", "Region,Amount\nEast,10\nWest,5\nEast,10\n")
    second = csv_source("b.csv", "Amount,Region\n10,East\n7,North\n")
    _, rows, report, _ = merged([first, second], dedupe="exact_rows")
    assert [(row["Source File"], row["Region"]) for row in rows] == [
        ("a.csv", "East"), ("a.csv", "West"), ("b.csv", "North"),
    ]
    assert report["totals"]["duplicates_removed"] == 2
    assert [entry["duplicates_removed"] for entry in report["sources"]] == [1, 1]
    assert [entry["rows"] for entry in report["sources"]] == [2, 1]


def test_keeping_the_last_duplicate_and_exact_counts_survive_rereads():
    first = csv_source("a.csv", "ID,Status\n1,open\n2,open\n")
    second = csv_source("b.csv", "ID,Status\n1,closed\n3,open\n")
    options = TabularMergeOptions(dedupe="key_columns", dedupe_columns=["id"], dedupe_keep="last")
    with merge_tabular_sources([first, second], options=options) as result:
        rows = list(result.iter_records())
        assert rows == [
            {"Source File": "a.csv", "ID": "2", "Status": "open"},
            {"Source File": "b.csv", "ID": "1", "Status": "closed"},
            {"Source File": "b.csv", "ID": "3", "Status": "open"},
        ]
        assert result.row_count == 3
        assert list(result.iter_records()) == rows
        report = result.report
    assert [entry["rows"] for entry in report["sources"]] == [1, 2]
    assert [entry["duplicates_removed"] for entry in report["sources"]] == [1, 0]
    assert report["totals"]["rows"] == 3 and report["totals"]["duplicates_removed"] == 1


def test_rows_with_blank_keys_are_never_treated_as_duplicates():
    first = csv_source("a.csv", "ID,Name\n,Ann\n,Bob\n7,Cy\n")
    second = csv_source("b.csv", "ID,Name\n7,Dee\n")
    _, rows, report, _ = merged([first, second], dedupe="key_columns", dedupe_columns=["ID"])
    assert [row["Name"] for row in rows] == ["Ann", "Bob", "Cy"]
    assert report["totals"]["duplicates_removed"] == 1


def test_union_rows_missing_a_later_column_match_rows_with_it_blank():
    first = csv_source("a.csv", "Region\nEast\n")
    second = csv_source("b.csv", "Region,Channel\nEast,\nWest,Online\n")
    _, rows, report, _ = merged([first, second], schema_policy="union", dedupe="exact_rows")
    assert [(row["Region"], row["Channel"]) for row in rows] == [("East", None), ("West", "Online")]
    assert report["totals"]["duplicates_removed"] == 1


def test_dedupe_and_sort_columns_must_exist():
    first = csv_source("a.csv", "Region\nEast\n")
    second = csv_source("b.csv", "Region\nWest\n")
    with pytest.raises(TabularMergeError) as caught:
        merged([first, second], dedupe="key_columns", dedupe_columns=["ID"])
    assert caught.value.code == "dedupe_column_not_found"
    with pytest.raises(TabularMergeError) as caught:
        merged([first, second], sort_by=[{"column": "Amount"}])
    assert caught.value.code == "sort_column_not_found"
    with pytest.raises(TabularMergeError) as caught:
        merged([first, second], schema_policy="union", sort_by=[{"column": "Amount"}])
    assert caught.value.code == "sort_column_not_found"
    with pytest.raises(TabularMergeError):
        TabularMergeOptions(dedupe_columns=["Region"])
    with pytest.raises(TabularMergeError):
        TabularMergeOptions(dedupe="key_columns")


def test_sorting_by_number_puts_text_after_numbers_and_blanks_last():
    first = csv_source("a.csv", "Item,Amount\na,\"1,200\"\nb,n/a\nc,15\n")
    second = csv_source("b.csv", "Item,Amount\nd,\ne,$3.5\nf,-2\n")
    _, rows, _, _ = merged(
        [first, second], include_source_column=False,
        sort_by=[{"column": "amount", "value_type": "number"}],
    )
    assert [row["Item"] for row in rows] == ["f", "e", "c", "a", "b", "d"]
    _, rows, _, _ = merged(
        [first, second], include_source_column=False,
        sort_by=[TabularMergeSort("Amount", descending=True, value_type="number")],
    )
    assert [row["Item"] for row in rows] == ["a", "c", "e", "f", "b", "d"]


def test_sorting_by_date_and_several_keys_is_stable():
    first = csv_source("a.csv", "Team,When,Seq\nB,2024-03-01,1\nA,2024-01-15T09:30:00,2\nA,2024-01-15,3\n")
    second = csv_source("b.csv", "Team,When,Seq\nB,2023-12-31,4\nA,not a date,5\n")
    _, rows, _, _ = merged(
        [first, second], include_source_column=False,
        sort_by=[{"column": "Team"}, {"column": "When", "value_type": "date"}],
    )
    assert [row["Seq"] for row in rows] == ["3", "2", "5", "4", "1"]


def test_sort_with_keep_last_dedupe_and_the_sort_bound():
    first = csv_source("a.csv", "ID,Amount\n1,5\n2,9\n")
    second = csv_source("b.csv", "ID,Amount\n1,7\n")
    _, rows, _, _ = merged(
        [first, second], include_source_column=False, dedupe="key_columns", dedupe_columns=["ID"],
        dedupe_keep="last", sort_by=[{"column": "Amount", "value_type": "number"}],
    )
    assert rows == [{"ID": "1", "Amount": "7"}, {"ID": "2", "Amount": "9"}]

    options = TabularMergeOptions(sort_by=[{"column": "ID"}])
    with pytest.raises(TabularMergeError) as caught:
        merge_tabular_sources([first, second], options=options, limits=TabularMergeLimits(max_sort_rows=2))
    assert caught.value.code == "sort_limit_exceeded"
    for invalid in (
        [{"column": "A"}, {"column": "B"}, {"column": "C"}, {"column": "D"}],
        [{"column": "A"}, {"column": "a"}],
        [{"column": "A", "value_type": "money"}],
        [{"column": "A", "descending": "yes"}],
        [{"column": "A", "order": "asc"}],
    ):
        with pytest.raises(TabularMergeError):
            TabularMergeOptions(sort_by=invalid)


def test_inspection_describes_files_and_how_their_columns_line_up():
    first = csv_source("a.csv", "Customer ID,Amount,Region\n001," + "x" * 120 + ",East\n002,5,West\n\n")
    second = csv_source("b.csv", "Region,Customer_ID,Amount\nNorth,003,7\n")
    broken = bytes_source("broken.xlsx", b"PK\x03\x04not really a workbook")
    report = inspect_tabular_sources([first, second, broken], options=TabularInspectOptions(sample_rows=1))
    assert report["version"] == "tabular-inspection-v1"
    first_table = report["sources"][0]["tables"][0]
    assert first_table["columns"] == ["Customer ID", "Amount", "Region"]
    assert first_table["row_count"] == 2
    assert len(first_table["sample_rows"]) == 1
    assert len(first_table["sample_rows"][0][1]) == 80 and first_table["sample_rows"][0][1].endswith("\u2026")
    assert report["sources"][2]["status"] == "problem"
    assert report["sources"][2]["problem"]["code"] == "unreadable_workbook"
    compatibility = report["compatibility"]
    assert compatibility["tables"] == 2
    assert compatibility["identical_columns"] is False
    assert compatibility["similar_columns"] == [{"names": ["Customer ID", "Customer_ID"]}]
    assert compatibility["suggested_policy"] == "mapped"
    assert {item["name"]: item["present_in"] for item in compatibility["columns"]} == {
        "Customer ID": 1, "Amount": 2, "Region": 2, "Customer_ID": 1,
    }


def test_inspection_suggests_by_name_for_identical_files_and_flags_title_rows():
    first = csv_source("a.csv", "Region,Amount\nEast,1\n")
    second = csv_source("b.csv", "Amount,Region\n2,West\n")
    report = inspect_tabular_sources([first, second])
    assert report["compatibility"]["identical_columns"] is True
    assert report["compatibility"]["same_order"] is False
    assert report["compatibility"]["suggested_policy"] == "by_name"

    titled = bytes_source("titled.xlsx", xlsx_bytes([
        ("Data", [["Sales report"], ["Region", "Amount"], ["East", 1]], "visible"),
        ("Archive", [["Region", "Amount"]], "hidden"),
    ]))
    report = inspect_tabular_sources([titled], options=TabularInspectOptions(sheets="all"))
    source = report["sources"][0]
    assert source["sheets"] == [{"name": "Data", "visible": True}, {"name": "Archive", "visible": False}]
    assert [table["status"] for table in source["tables"]] == ["inspected", "skipped"]
    hint = source["tables"][0]["warnings"][0]
    assert hint["code"] == "possible_title_row" and hint["suggested_header_row"] == 2
    unrelated = csv_source("c.csv", "Comment\nhi\n")
    report = inspect_tabular_sources([first, unrelated])
    assert report["compatibility"]["suggested_policy"] == "union"


def test_inspection_drops_samples_to_stay_small():
    wide = ",".join(f"Column {index}" for index in range(200))
    values = ",".join("v" * 79 for _ in range(200))
    sources = [csv_source(f"{index}.csv", f"{wide}\n{values}\n{values}\n") for index in range(4)]
    report = inspect_tabular_sources(sources, options=TabularInspectOptions(sample_rows=2))
    assert report["samples_omitted"] is True
    assert all(not table["sample_rows"] for entry in report["sources"] for table in entry["tables"])
    assert report["limitations"][-1] == "Sample rows were left out to keep the inspection small."


def test_squashed_header_names_ignore_spacing_and_punctuation():
    assert squash_header_name(" Customer_ID ") == squash_header_name("customer id") == "customerid"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
