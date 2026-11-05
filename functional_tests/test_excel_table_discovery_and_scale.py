# test_excel_table_discovery_and_scale.py
"""
Functional tests for streaming, table-aware saved Excel inspection.
Version: 0.261.405
Implemented in: 0.261.405

Named and ordinary regions retain their own headers and cell coordinates.
Large fixtures are generated incrementally and neither metadata nor previews
materialize the complete dataset.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook
from openpyxl.worksheet.table import Table

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))


def workbook_reader(path):
    from excel_workbook_reader import ExcelWorkbookReader
    return ExcelWorkbookReader(path)


@pytest.fixture(params=[False, True], ids=["ordinary-blocks", "named-tables"])
def five_tables(request, tmp_path):
    path = tmp_path / "five-tables.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Five tables"
    origins = [(3, 1), (3, 5), (10, 1), (10, 5), (17, 1)]
    for index, (row, column) in enumerate(origins, start=1):
        sheet.cell(row - 1, column, f"Review table {index}")
        sheet.cell(row, column, "Case")
        sheet.cell(row, column + 1, "Amount")
        for offset in range(1, 4):
            sheet.cell(row + offset, column, f"T{index}-{offset}")
            sheet.cell(row + offset, column + 1, index * 100 + offset)
        if request.param:
            from openpyxl.utils.cell import get_column_letter
            ref = f"{get_column_letter(column)}{row}:{get_column_letter(column + 1)}{row + 3}"
            sheet.add_table(Table(displayName=f"Review{index}", ref=ref))
    workbook.save(path)
    return path, request.param, origins


def test_five_tables_have_independent_headers_ranges_and_values(five_tables):
    path, named, origins = five_tables
    before = hashlib.sha256(path.read_bytes()).digest()
    with workbook_reader(path) as reader:
        manifest = reader.build_manifest()
        tables = manifest["sheets"][0]["tables"]
        assert len(tables) == 5
        assert len({table["id"] for table in tables}) == 5
        for index, (table, (row, column)) in enumerate(zip(tables, origins), start=1):
            assert table["header_row"] == row
            assert table["min_column"] == column
            assert table["row_count"] == 3
            assert table["origin"] == ("named" if named else "inferred")
            assert [item["name"] for item in table["columns"]] == ["Case", "Amount"]
            page = reader.read_table_page(table["id"], max_rows=2)
            assert page["rows"] == [[f"T{index}-1", index * 100 + 1], [f"T{index}-2", index * 100 + 2]]
            assert page["row_numbers"] == [row + 1, row + 2]
            assert page["has_more"] is True and page["next_start_row"] == 2
            last = reader.read_table_page(table["id"], start_row=2, max_rows=2)
            assert last["rows"] == [[f"T{index}-3", index * 100 + 3]]
            assert last["has_more"] is False
    assert hashlib.sha256(path.read_bytes()).digest() == before


@pytest.mark.parametrize("row_count", [50000, 100000])
def test_large_workbook_last_row_and_compact_manifest(tmp_path, row_count):
    path = tmp_path / f"large-{row_count}.xlsx"
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Large data")
    sheet.append(["Dataset review"])
    sheet.append(["Case", "Amount"])
    for index in range(1, row_count + 1):
        sheet.append([f"CASE-{index:06d}", index])
    workbook.save(path)
    with workbook_reader(path) as reader:
        manifest = reader.build_manifest()
        table = manifest["sheets"][0]["tables"][0]
        assert table["header_row"] == 2 and table["row_count"] == row_count
        assert len(json.dumps(manifest, ensure_ascii=True).encode()) < 20000
        page = reader.read_table_page(table["id"], start_row=row_count - 2, max_rows=2)
        assert page["rows"] == [[f"CASE-{row_count - 1:06d}", row_count - 1], [f"CASE-{row_count:06d}", row_count]]
        assert page["row_numbers"] == [row_count + 1, row_count + 2]
        assert page["has_more"] is False
        cells = reader.read_cells("Large data", [f"B{row_count + 2}"])
        assert cells[f"B{row_count + 2}"]["value"] == row_count


def test_repeated_headers_do_not_become_business_rows(tmp_path):
    path = tmp_path / "repeated.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    for row in [
        ["Case", "Amount"], ["A", 10], ["B", 20],
        ["Case", "Amount"], ["C", 30],
    ]:
        sheet.append(row)
    workbook.save(path)
    with workbook_reader(path) as reader:
        table = reader.build_manifest()["sheets"][0]["tables"][0]
        assert table["row_count"] == 3
        page = reader.read_table_page(table["id"])
        assert page["rows"] == [["A", 10], ["B", 20], ["C", 30]]
        assert page["row_numbers"] == [2, 3, 5]


def test_empty_and_unlabelled_regions_do_not_invent_headers(tmp_path):
    path = tmp_path / "unlabelled.xlsx"
    workbook = Workbook()
    workbook.active.title = "Values"
    workbook.active.append([10, False])
    workbook.active.append([20, True])
    workbook.create_sheet("Empty")
    workbook.save(path)
    with workbook_reader(path) as reader:
        manifest = reader.build_manifest()
        table = manifest["sheets"][0]["tables"][0]
        assert table["header_row"] is None
        assert table["header_status"] == "absent"
        assert table["row_count"] == 2
        assert manifest["sheets"][1]["tables"] == []
        page = reader.read_table_page(table["id"])
        assert page["columns"] == ["A", "B"]
        assert page["rows"] == [[10, False], [20, True]]


def test_invalid_table_and_oversized_preview_are_rejected(five_tables):
    path, _, _ = five_tables
    with workbook_reader(path) as reader:
        table = reader.build_manifest()["sheets"][0]["tables"][0]
        with pytest.raises(ValueError, match="table"):
            reader.read_table_page("../../another-document")
        with pytest.raises(ValueError, match="max_rows"):
            reader.read_table_page(table["id"], max_rows=501)
