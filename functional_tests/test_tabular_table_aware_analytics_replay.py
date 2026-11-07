# test_tabular_table_aware_analytics_replay.py
"""
Real-package tests for table-aware analytics and version-pinned durable replay.
Version: 0.261.408
Implemented in: 0.261.408

The existing offline native runtime replaces external I/O, not the workbook
reader, public analytical tools, source staging, checkpoints, or result reader.
OOXML packages are built in memory without Excel execution or temporary files.
"""

import asyncio
from copy import deepcopy
import importlib
import io
import json
import struct
from xml.sax.saxutils import escape, quoteattr
import zipfile

from flask import Flask, g
import pytest

from test_native_tabular_compute_service import (
    CONVERSATION,
    USER,
    compute_plan,
    native_runtime,
    open_result,
    submit,
)


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"


def _column_name(column):
    result = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _workbook_bytes(sheets):
    """Build a real spreadsheet package, including independently named tables."""
    contents = io.BytesIO()
    overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
    ]
    workbook_sheets, workbook_relationships = [], []
    table_number = 0
    with zipfile.ZipFile(contents, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "_rels/.rels",
            f'<Relationships xmlns="{PACKAGE_NS}"><Relationship Id="root" '
            f'Type="{REL_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        for sheet_number, sheet in enumerate(sheets, start=1):
            name, rows, tables = sheet["name"], sheet["rows"], sheet.get("tables") or []
            workbook_sheets.append(
                f'<sheet name={quoteattr(name)} sheetId="{sheet_number}" r:id="sheet{sheet_number}"/>'
            )
            workbook_relationships.append(
                f'<Relationship Id="sheet{sheet_number}" Type="{REL_NS}/worksheet" '
                f'Target="worksheets/sheet{sheet_number}.xml"/>'
            )
            overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{sheet_number}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            table_parts, table_relationships = [], []
            for name, reference, columns in tables:
                table_number += 1
                table_parts.append(f'<tablePart r:id="table{table_number}"/>')
                table_relationships.append(
                    f'<Relationship Id="table{table_number}" Type="{REL_NS}/table" '
                    f'Target="../tables/table{table_number}.xml"/>'
                )
                table_columns = "".join(
                    f'<tableColumn id="{index}" name={quoteattr(column)}/>'
                    for index, column in enumerate(columns, start=1)
                )
                package.writestr(
                    f"xl/tables/table{table_number}.xml",
                    f'<table xmlns="{MAIN_NS}" id="{table_number}" name={quoteattr(name)} '
                    f'displayName={quoteattr(name)} ref={quoteattr(reference)} totalsRowShown="0">'
                    f'<autoFilter ref={quoteattr(reference)}/><tableColumns count="{len(columns)}">'
                    f'{table_columns}</tableColumns></table>',
                )
                overrides.append(
                    f'<Override PartName="/xl/tables/table{table_number}.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
                )
            worksheet_rows = []
            for row_number, cells in sorted(rows.items()):
                serialized_cells = []
                for column, value in sorted(cells.items()):
                    reference = f"{_column_name(column)}{row_number}"
                    if isinstance(value, tuple) and value[0] == "formula":
                        cached = f"<v>{escape(str(value[2]))}</v>" if value[2] is not None else ""
                        body = f"<f>{escape(value[1])}</f>{cached}"
                        serialized_cells.append(f'<c r="{reference}">{body}</c>')
                    elif isinstance(value, bool):
                        serialized_cells.append(f'<c r="{reference}" t="b"><v>{int(value)}</v></c>')
                    elif isinstance(value, (int, float)):
                        serialized_cells.append(f'<c r="{reference}"><v>{value}</v></c>')
                    elif value is not None:
                        serialized_cells.append(
                            f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
                            f'{escape(str(value))}</t></is></c>'
                        )
                worksheet_rows.append(f'<row r="{row_number}">{"".join(serialized_cells)}</row>')
            table_xml = (
                f'<tableParts count="{len(table_parts)}">{"".join(table_parts)}</tableParts>'
                if table_parts else ""
            )
            package.writestr(
                f"xl/worksheets/sheet{sheet_number}.xml",
                f'<worksheet xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheetData>'
                f'{"".join(worksheet_rows)}</sheetData>{table_xml}</worksheet>',
            )
            if table_relationships:
                package.writestr(
                    f"xl/worksheets/_rels/sheet{sheet_number}.xml.rels",
                    f'<Relationships xmlns="{PACKAGE_NS}">{"".join(table_relationships)}</Relationships>',
                )
        package.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets>'
            f'{"".join(workbook_sheets)}</sheets></workbook>',
        )
        package.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PACKAGE_NS}">{"".join(workbook_relationships)}</Relationships>',
        )
        package.writestr(
            "[Content_Types].xml",
            f'<Types xmlns="{CONTENT_NS}"><Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="xml" ContentType="application/xml"/>{"".join(overrides)}</Types>',
        )
    return contents.getvalue()


def _five_tables(named):
    rows, tables = {}, []
    origins = [(3, 1), (3, 5), (10, 1), (10, 5), (17, 1)]
    for index, (header, column) in enumerate(origins, start=1):
        rows.setdefault(header - 1, {})[column] = f"Review table {index}"
        rows.setdefault(header, {}).update({column: "Case", column + 1: "Amount"})
        for offset in range(1, 4):
            rows.setdefault(header + offset, {}).update({
                column: f"T{index}-{offset}", column + 1: index * 100 + offset,
            })
        if named:
            reference = f"{_column_name(column)}{header}:{_column_name(column + 1)}{header + 3}"
            tables.append((f"Review{index}", reference, ["Case", "Amount"]))
    return _workbook_bytes([{"name": "Five tables", "rows": rows, "tables": tables}]), origins


def _one_table(count=3, *, header=2, table_name=None, column="amount"):
    rows = {header - 1: {1: "Saved dataset"}, header: {1: "Item_ID", 2: column}}
    rows.update({
        header + index: {1: f"item-{index:06d}", 2: index}
        for index in range(1, count + 1)
    })
    tables = [(table_name, f"A{header}:B{header + count}", ["Item_ID", column])] if table_name else []
    return _workbook_bytes([{"name": "Data", "rows": rows, "tables": tables}])


def _legacy_workbook_bytes():
    """A real BIFF8/OLE workbook with one saved numeric cell and no header."""
    def record(code, payload=b""):
        return struct.pack("<HH", code, len(payload)) + payload

    def bof(kind):
        return record(0x809, struct.pack("<HHHHII", 0x600, kind, 0x0DBB, 0x07CC, 0, 6))

    font = record(
        0x31, struct.pack("<HHHHHBBBBBB", 220, 0, 0x7FFF, 400, 0, 0, 0, 0, 0, 5, 0) + b"Arial",
    )
    prefix = bof(5) + record(0x42, struct.pack("<H", 1252)) + font + record(0xE0, b"\0" * 20)

    def boundsheet(offset):
        return record(0x85, struct.pack("<IBBBB", offset, 0, 0, 6, 0) + b"Sheet1")

    globals_size = len(prefix + boundsheet(0) + record(0xA))
    stream = prefix + boundsheet(globals_size) + record(0xA)
    stream += bof(0x10) + record(0x200, struct.pack("<IIHHH", 0, 1, 0, 1, 0))
    stream += record(0x203, struct.pack("<HHHd", 0, 0, 0, 42)) + record(0xA)
    stream = stream.ljust(4096, b"\0")
    header = bytearray(512)
    header[:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<HHHH", header, 24, 0x3E, 3, 0xFFFE, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, 1, 1, 0, 4096, 0xFFFFFFFE, 0, 0xFFFFFFFE, 0)
    struct.pack_into("<109I", header, 76, 0, *([0xFFFFFFFF] * 108))
    fat = [0xFFFFFFFD, 0xFFFFFFFE, 3, 4, 5, 6, 7, 8, 9, 0xFFFFFFFE] + [0xFFFFFFFF] * 118

    def directory(name, kind, child, start, size):
        entry = bytearray(128)
        encoded = (name + "\0").encode("utf-16le")
        entry[:len(encoded)] = encoded
        struct.pack_into("<HBBIII", entry, 64, len(encoded), kind, 1, 0xFFFFFFFF, 0xFFFFFFFF, child)
        struct.pack_into("<IQ", entry, 116, start, size)
        return bytes(entry)

    directory_data = directory("Root Entry", 5, 1, 0xFFFFFFFE, 0)
    directory_data += directory("Workbook", 2, 0xFFFFFFFF, 2, 4096)
    return bytes(header) + struct.pack("<128I", *fat) + directory_data.ljust(512, b"\0") + stream


def _set_source(runtime, contents, *, etag=None):
    source = runtime.source_manifest[0]["storage_locator"]
    blob = runtime.blobs.values[(source["container"], source["blob_path"])]
    blob["bytes"] = contents
    if etag is not None:
        blob["etag"] = etag


def _plugin(runtime):
    return runtime.engine.TabularProcessingPlugin(authorized_user_id=USER)


def _call(runtime, plugin, tool_name, **arguments):
    """Exercise real public scope rebinding, including spoofed tool-call IDs."""
    module = importlib.import_module("semantic_kernel_plugins.tabular_processing_plugin")
    runtime.patcher.setattr(module, "get_current_user_id", lambda: USER)
    app = Flask(__name__)
    with app.test_request_context("/"):
        g.authorized_chat_context = {
            "user_id": USER, "conversation_id": CONVERSATION,
            "authorized_blob_locations": [
                [runtime.document["blob_container"], runtime.document["blob_path"]],
            ],
        }
        result = asyncio.run(getattr(plugin, tool_name)(
            user_id="caller-controlled-user", conversation_id="caller-controlled-conversation",
            filename=runtime.document["file_name"], source="workspace", **arguments,
        ))
    return json.loads(str(result)), result


def _descriptor(runtime, **selectors):
    locator = runtime.source_manifest[0]["storage_locator"]
    return _plugin(runtime)._build_generated_export_query_descriptor_from_location(
        container_name=locator["container"], blob_path=locator["blob_path"],
        filename=runtime.document["file_name"], query_expression="index == index",
        sheet_names=["Data"], **selectors,
    )


def _replay(runtime, descriptor, *, resume=0, chunk_rows=2):
    return runtime.engine._iter_versioned_tabular_source_rows(
        descriptor, "xlsx", chunk_rows, resume, user_id=USER,
    )


@pytest.mark.parametrize("named", [False, True], ids=["ordinary-blocks", "named-tables"])
def test_five_tables_are_discovered_and_analyzed_without_global_headers(monkeypatch, named):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        contents, origins = _five_tables(named)
        _set_source(runtime, contents)
        plugin = _plugin(runtime)
        plugin._get_workbook_metadata(runtime.document["blob_container"], runtime.document["blob_path"])
        reader_module = importlib.import_module("excel_workbook_reader")
        original_scan = reader_module.ExcelWorkbookReader.iter_sheet_rows
        scans = []

        def schema_scan(reader, sheet):
            scans.append(sheet["name"])
            yield from original_scan(reader, sheet)

        with monkeypatch.context() as patcher:
            patcher.setattr(reader_module.ExcelWorkbookReader, "iter_sheet_rows", schema_scan)
            patcher.setattr(
                reader_module.ExcelWorkbookReader, "read_table_page",
                lambda *args, **kwargs: pytest.fail("Schema discovery rescanned each table separately."),
            )
            discovery, _ = _call(runtime, plugin, "describe_tabular_file")
        assert scans == ["Five tables"]
        assert discovery["table_count"] == 5
        assert discovery["selection_required"] is True
        tables = discovery["per_sheet_schemas"]["Five tables"]["tables"]
        assert len(tables) == 5
        assert [table["header_row"] for table in tables] == [row for row, _ in origins]
        assert all(table["row_count"] == 3 for table in tables)
        required, _ = _call(runtime, plugin, "aggregate_column", column="Amount", operation="sum")
        assert required["error_code"] == "table_selection_required"
        assert len(required["table_choices"]) == 5
        for index, table in enumerate(tables, start=1):
            aggregate, _ = _call(
                runtime, plugin, "aggregate_column", column="Amount", operation="sum",
                table_id=table["table_id"],
            )
            assert int(aggregate["result"]) == index * 300 + 6
            assert aggregate["selected_table"] == table["table_id"]
            assert aggregate["header_row"] == origins[index - 1][0]
        filtered, invocation = _call(
            runtime, plugin, "filter_rows", column="Amount", operator=">", value="402",
            table_id=tables[3]["table_id"], return_columns="Case",
        )
        assert filtered["total_matches"] == 1
        assert filtered["data"][0]["Case"] == "T4-3"
        assert filtered["data"][0]["_excel_source"] == {
            "sheet": "Five tables", "table_id": tables[3]["table_id"],
            "range": tables[3]["table_range"], "row": 13,
        }
        replay = invocation.internal_metadata["tabular_generated_export_source"]
        assert replay["version"] == 2 and replay["expected_row_count"] == 1
        rows = list(runtime.engine._iter_versioned_tabular_source_rows(replay, "xlsx", 2, 0, user_id=USER))
        assert rows[0][1] == filtered["data"][0]
        lookup, _ = _call(
            runtime, plugin, "lookup_value", lookup_column="Case", lookup_value="T5-2",
            target_column="Amount", table_id=tables[4]["table_id"],
        )
        assert int(lookup["value"]) == 502
        assert lookup["data"][0]["_excel_source"]["row"] == 19
        explicit, _ = _call(
            runtime, plugin, "aggregate_column", column="Amount", operation="sum",
            sheet_name="Five tables", cell_range="E3:F6", header_row="3",
        )
        assert int(explicit["result"]) == 606
        assert explicit["table_range"] == "E3:F6" and explicit["header_row"] == 3
        distinct, _ = _call(
            runtime, plugin, "get_distinct_values", column="Case", table_id=tables[2]["table_id"],
        )
        assert distinct["distinct_count"] == 3
        assert distinct["values"] == ["T3-1", "T3-2", "T3-3"]
        searched, _ = _call(
            runtime, plugin, "search_rows", search_value="T2-3", search_columns="Case",
            table_id=tables[1]["table_id"], return_columns="Case",
        )
        assert searched["total_matches"] == 1
        assert searched["data"][0]["_excel_source"]["row"] == 6
        all_tables, _ = _call(
            runtime, plugin, "aggregate_column", table_id="all", column="Amount", operation="sum",
        )
        assert int(all_tables["result"]) == 4530
        unselected, _ = _call(runtime, plugin, "count_rows")
        assert unselected["selection_required"] is True


def test_explicit_header_and_no_header_choices_are_independent(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        contents = _workbook_bytes([{
            "name": "Data", "rows": {1: {1: "Name"}, 2: {1: "Ada"}, 3: {1: "Bea"}},
        }])
        _set_source(runtime, contents)
        plugin = _plugin(runtime)
        discovery, _ = _call(runtime, plugin, "describe_tabular_file")
        table = discovery["per_sheet_schemas"]["Data"]["tables"][0]
        assert table["header_status"] == "ambiguous"
        ambiguous, _ = _call(runtime, plugin, "count_rows", table_id=table["table_id"])
        assert ambiguous["error_code"] == "header_selection_required"
        headed, _ = _call(runtime, plugin, "count_rows", table_id=table["table_id"], header_row="1")
        unheaded, _ = _call(runtime, plugin, "query_tabular_data", query_expression="index == index",
                            table_id=table["table_id"], header_row="0")
        assert headed["row_count"] == 2
        assert unheaded["total_matches"] == 3
        assert unheaded["data"][0]["A"] == "Name"
        assert unheaded["data"][0]["_excel_source"]["row"] == 1
        assert unheaded["header_row"] is None
        descriptor = _descriptor(runtime, table_id=table["table_id"], header_row=0)
        assert descriptor["header_row"] == 0
        assert [row["A"] for _, row in _replay(runtime, descriptor)] == ["Name", "Ada", "Bea"]


def test_50000_rows_have_exact_aggregates_late_reads_and_bounded_replay(monkeypatch):
    count = 50000
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _one_table(count))
        plugin = _plugin(runtime)
        aggregate, _ = _call(runtime, plugin, "aggregate_column", column="amount", operation="sum")
        assert int(aggregate["result"]) == count * (count + 1) // 2
        filtered, _ = _call(
            runtime, plugin, "filter_rows", column="amount", operator="==", value=str(count),
        )
        assert filtered["total_matches"] == 1
        assert filtered["data"][0]["_excel_source"]["row"] == count + 2
        assert filtered["data"][0]["Item_ID"] == f"item-{count:06d}"
        descriptor = _descriptor(runtime, expected_row_count=count)
        assert descriptor["source_row_count"] == count
        original_chunks = runtime.engine._iter_excel_table_source_chunks
        batch_sizes = []

        def bounded_chunks(*args, **kwargs):
            for chunk in original_chunks(*args, **kwargs):
                batch_sizes.append(len(chunk))
                yield chunk

        runtime.patcher.setattr(runtime.engine, "_iter_excel_table_source_chunks", bounded_chunks)
        runtime.patcher.setattr(
            runtime.engine.TabularProcessingPlugin, "_read_tabular_blob_to_dataframe",
            lambda *args, **kwargs: pytest.fail("Durable replay materialized a whole worksheet."),
        )
        rows = list(_replay(runtime, descriptor, chunk_rows=512))
        assert len(rows) == count
        assert sum(row["amount"] for _, row in rows) == count * (count + 1) // 2
        assert rows[-1][0] == count
        assert rows[-1][1]["_excel_source"]["row"] == count + 2
        assert max(batch_sizes) <= 512
        resumed = list(_replay(runtime, descriptor, resume=count - 2, chunk_rows=512))
        assert resumed == rows[-2:]


def test_source_versions_and_fresh_authorization_invalidate_cached_choices(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _one_table(3))
        plugin = _plugin(runtime)
        first, _ = _call(runtime, plugin, "aggregate_column", column="amount", operation="sum")
        assert int(first["result"]) == 6
        old_descriptor = _descriptor(runtime, expected_row_count=3)
        _set_source(runtime, _one_table(4, column="total"), etag="source-blob-2")
        changed, _ = _call(runtime, plugin, "aggregate_column", column="total", operation="sum")
        assert int(changed["result"]) == 10
        missing, _ = _call(runtime, plugin, "aggregate_column", column="amount", operation="sum")
        assert "error" in missing and "total" in missing["error"]
        with pytest.raises(ValueError, match="changed"):
            list(_replay(runtime, old_descriptor))
        runtime.state["allowed"] = False
        denied, _ = _call(runtime, plugin, "count_rows")
        assert denied["error_code"] == "tabular_source_unavailable"
        assert "row_count" not in denied and "Fixture" not in denied["error"]
        assert not plugin._df_cache and not plugin._workbook_metadata_cache


@pytest.mark.parametrize("selector", ["table", "header", "range", "cursor", "hash", "legacy"])
def test_durable_selection_and_cursor_mismatches_fail_closed(monkeypatch, selector):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _one_table(3, table_name="Facts"))
        descriptor = _descriptor(runtime, table_id="Facts", expected_row_count=3)
        resume = 0
        if selector == "table":
            descriptor["selected_table"] = "another-table"
        elif selector == "header":
            descriptor["header_row"] = 3
        elif selector == "range":
            descriptor.update({"table_id": None, "cell_range": "A2:B4", "header_row": 2})
        elif selector == "cursor":
            resume = 4
        elif selector == "hash":
            descriptor["source_sha256"] = "0" * 64
        else:
            descriptor["version"] = 1
        with pytest.raises(ValueError):
            list(_replay(runtime, descriptor, resume=resume))


def test_missing_formula_caches_are_not_zero_or_empty_conclusions(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _workbook_bytes([{
            "name": "Data",
            "rows": {
                2: {1: "Item_ID", 2: "amount"},
                3: {1: "missing", 2: ("formula", "'[external.xlsx]Data'!A1", None)},
                4: {1: "saved", 2: ("formula", "10+20", 30)},
            },
            "tables": [("Facts", "A2:B4", ["Item_ID", "amount"])],
        }]))
        plugin = _plugin(runtime)
        count, _ = _call(runtime, plugin, "count_rows", table_id="Facts")
        assert count["row_count"] == 2
        for operation, arguments in [
            ("aggregate_column", {"column": "amount", "operation": "sum"}),
            ("count_rows", {"filter_column": "amount", "filter_operator": ">=", "filter_value": "0"}),
            ("query_tabular_data", {"query_expression": "amount >= 0"}),
            ("lookup_value", {"lookup_column": "Item_ID", "lookup_value": "missing", "target_column": "amount"}),
        ]:
            payload, _ = _call(runtime, plugin, operation, table_id="Facts", **arguments)
            assert payload["error_code"] == "formula_cache_missing", payload
            assert "result" not in payload and "value" not in payload and "row_count" not in payload
        saved, _ = _call(
            runtime, plugin, "lookup_value", table_id="Facts", lookup_column="Item_ID",
            lookup_value="saved", target_column="amount",
        )
        assert saved["value"] == 30
        irrelevant, invocation = _call(
            runtime, plugin, "query_tabular_data", table_id="Facts",
            query_expression='Item_ID == "missing"', return_columns="Item_ID",
        )
        assert irrelevant["total_matches"] == 1
        descriptor = invocation.internal_metadata["tabular_generated_export_source"]
        assert len(list(_replay(runtime, descriptor))) == 1
        descriptor["return_columns"] = None
        with pytest.raises(ValueError, match="cached"):
            list(_replay(runtime, descriptor))
        counted, _ = _call(
            runtime, plugin, "count_rows", query_expression='Item_ID == "amount"',
            table_id="Facts",
        )
        assert counted["row_count"] == 0


def test_explicit_all_native_tables_keep_heterogeneous_identities(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _workbook_bytes([{
            "name": "Data",
            "rows": {
                3: {1: "Item_ID", 2: "amount"}, 4: {1: "A", 2: 10}, 5: {1: "B", 2: 20},
                10: {1: "Region", 2: "Units", 3: "Flag"},
                11: {1: "East", 2: 4, 3: True}, 12: {1: "West", 2: 8, 3: False},
            },
            "tables": [
                ("Facts", "A3:B5", ["Item_ID", "amount"]),
                ("Regions", "A10:C12", ["Region", "Units", "Flag"]),
            ],
        }]))
        descriptor = _descriptor(runtime, table_id="all", expected_row_count=4)
        assert len(descriptor["table_selections"]) == 2
        rows = list(_replay(runtime, descriptor))
        assert [cursor for cursor, _ in rows] == [1, 2, 3, 4]
        assert set(rows[0][1]) == {"Item_ID", "amount", "_excel_source"}
        assert set(rows[2][1]) == {"Region", "Units", "Flag", "_excel_source"}
        assert [row["_excel_source"]["row"] for _, row in rows] == [4, 5, 11, 12]
        assert len({row["_excel_source"]["table_id"] for _, row in rows}) == 2
        plan = compute_plan(runtime, durable=True)
        plan["requested_output_hints"]["selected_table"] = "all"
        request = runtime.service._compute_request(plan, "Compute doubled amounts.")
        candidate, pinned = runtime.service._prepare_native_source(
            runtime.engine, runtime.source_manifest[0], request, USER,
        )
        assert pinned["expected_row_count"] == candidate["total_matches"] == 4
        assert len(candidate["table_selections"]) == 2
        assert candidate["full_result_available"] is False
        foreground, _ = _call(
            runtime, _plugin(runtime), "aggregate_column", table_id="all", column="amount", operation="sum",
        )
        assert foreground["error_code"] == "table_schema_mismatch"


def test_related_tables_use_independent_ranges_and_physical_rows(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _workbook_bytes([{
            "name": "Data",
            "rows": {
                3: {1: "Owner", 2: "Team"}, 4: {1: "Ada", 2: "Blue"},
                5: {1: "Bea", 2: "Green"}, 10: {1: "Assignee", 2: "amount"},
                11: {1: "Ada", 2: ("formula", "1+2", None)}, 12: {1: "Bea", 2: 20},
            },
            "tables": [
                ("People", "A3:B5", ["Owner", "Team"]),
                ("Work", "A10:B12", ["Assignee", "amount"]),
            ],
        }]))
        arguments = {
            "source_sheet_name": "Data", "source_value_column": "Owner",
            "target_sheet_name": "Data", "target_match_column": "Assignee",
            "source_table_id": "People", "target_cell_range": "A10:B12", "target_header_row": "10",
            "source_filter_column": "Team", "source_filter_value": "Blue",
        }
        count, _ = _call(runtime, _plugin(runtime), "count_rows_by_related_values", **arguments)
        assert count["row_count"] == 1
        rows, _ = _call(
            runtime, _plugin(runtime), "filter_rows_by_related_values",
            return_columns="Assignee", **arguments,
        )
        assert rows["matched_target_row_count"] == 1
        assert rows["data"][0]["Assignee"] == "Ada"
        assert rows["data"][0]["_excel_source"]["row"] == 11
        assert rows["source_selection"]["header_row"] == 3
        assert rows["target_selection"]["header_row"] == 10


def test_csv_and_single_table_compatibility(monkeypatch):
    with native_runtime(monkeypatch, row_count=3) as runtime:
        plugin = _plugin(runtime)
        aggregate, _ = _call(runtime, plugin, "aggregate_column", column="amount", operation="sum")
        assert int(aggregate["result"]) == 6 and aggregate["selected_sheet"] is None
        queried, invocation = _call(runtime, plugin, "query_tabular_data", query_expression="amount >= 2")
        assert queried["total_matches"] == 2
        descriptor = invocation.internal_metadata["tabular_generated_export_source"]
        assert descriptor["version"] == 1 and "table_selections" not in descriptor
        invalid, _ = _call(
            runtime, plugin, "query_tabular_data", query_expression="index == index", header_row="0",
        )
        assert invalid["error_code"] == "table_selection_invalid"


def test_cross_sheet_tools_and_replay_preserve_table_scope_and_global_cursor(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _workbook_bytes([
            {
                "name": "First ",
                "rows": {2: {1: "Item_ID", 2: "amount"}, 3: {1: "A", 2: 10}, 4: {1: "B", 2: 20}},
                "tables": [("FirstFacts", "A2:B4", ["Item_ID", "amount"])],
            },
            {
                "name": "Second",
                "rows": {7: {1: "Item_ID", 2: "amount"}, 8: {1: "C", 2: 30}, 9: {1: "D", 2: 40}},
                "tables": [("SecondFacts", "A7:B9", ["Item_ID", "amount"])],
            },
        ]))
        plugin = _plugin(runtime)
        query, invocation = _call(
            runtime, plugin, "query_tabular_data", query_expression="index >= 1", return_columns="Item_ID",
        )
        assert query["total_matches"] == 3
        assert [row["Item_ID"] for row in query["data"]] == ["B", "C", "D"]
        assert [row["_excel_source"]["row"] for row in query["data"]] == [4, 8, 9]
        descriptor = invocation.internal_metadata["tabular_generated_export_source"]
        assert descriptor["sheet_names"] == ["First ", "Second"]
        replayed = list(_replay(runtime, descriptor, chunk_rows=1))
        assert [cursor for cursor, _ in replayed] == [2, 3, 4]
        assert [row for _, row in replayed] == query["data"]
        count, _ = _call(runtime, plugin, "count_rows", filter_column="amount", filter_operator=">", filter_value="15")
        assert count["row_count"] == 3
        lookup, _ = _call(
            runtime, plugin, "lookup_value", lookup_column="Item_ID", lookup_value="C", target_column="amount",
        )
        assert lookup["total_matches"] == 1
        assert lookup["data"][0]["_excel_source"]["row"] == 8
        mismatch, _ = _call(
            runtime, plugin, "aggregate_column", column="amount", operation="sum",
            sheet_name="Second", table_id="FirstFacts",
        )
        assert mismatch["error_code"] == "table_selection_invalid"
        explicit, _ = _call(
            runtime, plugin, "count_rows", table_id="FirstFacts",
        )
        assert explicit["selected_sheet"] == "First " and explicit["header_row"] == 2


def test_grouped_and_datetime_operations_respect_nonfirst_table_headers(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _workbook_bytes([{
            "name": "Data",
            "rows": {
                2: {1: "Category", 2: "amount"}, 3: {1: "unrelated", 2: 9999},
                7: {1: "Category", 2: "amount", 3: "When"},
                8: {1: "Blue", 2: 10, 3: "2026-01-05"},
                9: {1: "Blue", 2: 20, 3: "2026-01-06"},
                10: {1: "Green", 2: 40, 3: "2026-01-12"},
            },
            "tables": [
                ("Unrelated", "A2:B3", ["Category", "amount"]),
                ("Events", "A7:C10", ["Category", "amount", "When"]),
            ],
        }]))
        plugin = _plugin(runtime)
        grouped, _ = _call(
            runtime, plugin, "group_by_aggregate", group_by_column="Category",
            aggregate_column="amount", operation="sum", table_id="Events",
        )
        assert grouped["result"] == {"Blue": 30, "Green": 40}
        assert grouped["header_row"] == 7
        dated, _ = _call(
            runtime, plugin, "group_by_datetime_component", datetime_column="When",
            datetime_component="day_name", aggregate_column="amount", operation="sum",
            cell_range="A7:C10", header_row="7",
        )
        expected = dict.fromkeys(plugin.DAY_NAME_ORDER, 0)
        expected.update({"Monday": 50, "Tuesday": 20})
        assert dated["result"] == expected
        assert dated["parsed_rows"] == 3 and dated["table_range"] == "A7:C10"


def test_separate_file_relationships_authorize_each_explicit_table(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        source_bytes = _workbook_bytes([{
            "name": "Data", "rows": {3: {1: "Owner", 2: "Team"}, 4: {1: "Ada", 2: "Blue"}},
            "tables": [("People", "A3:B4", ["Owner", "Team"])],
        }])
        target_bytes = _workbook_bytes([{
            "name": "Data",
            "rows": {7: {1: "Assignee", 2: "amount"}, 8: {1: "Ada", 2: 15}, 9: {1: "Bea", 2: 20}},
            "tables": [("Work", "A7:B9", ["Assignee", "amount"])],
        }])
        _set_source(runtime, source_bytes)
        second = {
            **deepcopy(runtime.document), "id": "target-1", "file_name": "target.xlsx",
            "blob_path": f"{USER}/target.xlsx",
        }
        runtime.blobs.values[("user-documents", second["blob_path"])] = {
            "bytes": target_bytes, "etag": "target-blob-1", "metadata": {},
        }
        reads = []

        def resolve_document(container, blob_path, user_id):
            reads.append(blob_path)
            if user_id != USER or container != "user-documents" or not runtime.state["allowed"]:
                raise PermissionError("Fixture relationship source denied.")
            if blob_path == second["blob_path"]:
                return deepcopy(second)
            if blob_path == runtime.document["blob_path"]:
                return deepcopy(runtime.document)
            raise PermissionError("Fixture relationship source denied.")

        runtime.patcher.setattr(runtime.screening, "_resolve_blob_document", resolve_document)

        def read_document(document_id, user_id, **kwargs):
            if document_id == second["id"]:
                return resolve_document("user-documents", second["blob_path"], user_id)
            if document_id == runtime.document["id"]:
                return resolve_document("user-documents", runtime.document["blob_path"], user_id)
            raise PermissionError("Fixture relationship source denied.")

        runtime.patcher.setattr(runtime.screening, "_read_authorized_document", read_document)
        plugin = _plugin(runtime)
        arguments = {
            "source_sheet_name": "Data", "source_value_column": "Owner", "source_table_id": "People",
            "target_sheet_name": "Data", "target_match_column": "Assignee", "target_table_id": "Work",
            "target_filename": "target.xlsx",
        }
        payload, _ = _call(runtime, plugin, "filter_rows_by_related_values", **arguments)
        assert payload["matched_target_row_count"] == 1
        assert payload["source_filename"] == "source.xlsx"
        assert payload["target_filename"] == "target.xlsx"
        assert payload["data"][0]["_excel_source"]["row"] == 8
        assert set(reads) == {runtime.document["blob_path"], second["blob_path"]}
        runtime.state["allowed"] = False
        denied, _ = _call(runtime, plugin, "count_rows_by_related_values", **arguments)
        assert denied["error_code"] == "tabular_source_unavailable"
        assert "row_count" not in denied


def test_streamed_numeric_conversion_checks_late_rows_before_querying(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        rows = {2: {1: "Item_ID", 2: "amount"}}
        rows.update({index + 2: {1: f"row-{index}", 2: index} for index in range(1, 1201)})
        rows[1202][2] = "unknown"
        _set_source(runtime, _workbook_bytes([{"name": "Data", "rows": rows}]))
        query, invocation = _call(
            runtime, _plugin(runtime), "query_tabular_data", query_expression='amount == "2"',
        )
        assert query["total_matches"] == 1
        descriptor = invocation.internal_metadata["tabular_generated_export_source"]
        replayed = list(_replay(runtime, descriptor, chunk_rows=100))
        assert [row for _, row in replayed] == query["data"]
        assert replayed[0][0] == 2 and replayed[0][1]["amount"] == "2"


def test_native_range_hints_pin_actual_headers_and_selected_ranges(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _one_table(3))
        plan = compute_plan(runtime, durable=True)
        plan["requested_output_hints"].update({
            "selected_sheet": "", "selected_range": "A2:B5", "selected_header_row": "2",
        })
        request = runtime.service._compute_request(plan, "Compute doubled amounts.")
        candidate, descriptor = runtime.service._prepare_native_source(
            runtime.engine, runtime.source_manifest[0], request, USER,
        )
        assert candidate["cell_range"] == descriptor["cell_range"] == "A2:B5"
        assert candidate["header_row"] == descriptor["header_row"] == 2
        assert candidate["total_matches"] == descriptor["expected_row_count"] == 3
        assert descriptor["table_selections"][0]["origin"] == "range"
        assert [row["_excel_source"]["row"] for row in candidate["rows"]] == [3, 4, 5]


def test_same_schema_all_tables_keep_full_data_numeric_semantics_on_replay(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _workbook_bytes([{
            "name": "Data",
            "rows": {
                2: {1: "Item_ID", 2: "amount"}, 3: {1: "A", 2: 1}, 4: {1: "B", 2: 2},
                8: {1: "Item_ID", 2: "amount"}, 9: {1: "C", 2: 3}, 10: {1: "D", 2: "unknown"},
            },
            "tables": [
                ("FirstFacts", "A2:B4", ["Item_ID", "amount"]),
                ("SecondFacts", "A8:B10", ["Item_ID", "amount"]),
            ],
        }]))
        payload, invocation = _call(
            runtime, _plugin(runtime), "query_tabular_data",
            table_id="all", query_expression='amount == "2"',
        )
        descriptor = invocation.internal_metadata["tabular_generated_export_source"]
        replayed = list(_replay(runtime, descriptor, chunk_rows=1))
        assert payload["total_matches"] == len(replayed) == 1
        assert descriptor["numeric_conversion_scope"] == "sheet"
        assert [row for _, row in replayed] == payload["data"]
        plan = compute_plan(runtime, durable=True, query='amount == "2"')
        plan["requested_output_hints"]["selected_table"] = "all"
        request = runtime.service._compute_request(plan, "Compute doubled amounts.")
        candidate, pinned = runtime.service._prepare_native_source(
            runtime.engine, runtime.source_manifest[0], request, USER,
        )
        assert pinned["numeric_conversion_scope"] == "sheet"
        assert candidate["total_matches"] == 1 and candidate["rows"] == payload["data"]


def test_repeated_headers_keep_physical_rows_separate_from_replay_cursors(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _workbook_bytes([{
            "name": "Data",
            "rows": {
                2: {1: "Item_ID", 2: "amount"}, 3: {1: "A", 2: 10},
                4: {1: "Item_ID", 2: "amount"}, 5: {1: "B", 2: 20},
            },
        }]))
        descriptor = _descriptor(runtime, expected_row_count=2)
        assert descriptor["source_row_count"] == 2
        rows = list(_replay(runtime, descriptor, chunk_rows=1))
        assert [cursor for cursor, _ in rows] == [1, 2]
        assert [row["_excel_source"]["row"] for _, row in rows] == [3, 5]
        assert list(_replay(runtime, descriptor, resume=1, chunk_rows=1)) == rows[-1:]


def test_source_columns_cannot_replace_protected_excel_provenance(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _workbook_bytes([{
            "name": "Data", "rows": {2: {1: "Item_ID", 2: "_excel_source"}, 3: {1: "A", 2: "spoofed"}},
            "tables": [("Facts", "A2:B3", ["Item_ID", "_excel_source"])],
        }]))
        payload, _ = _call(
            runtime, _plugin(runtime), "query_tabular_data",
            query_expression="index == index", return_columns="Item_ID",
        )
        assert payload["error_code"] == "reserved_excel_column"
        assert "data" not in payload
        descriptor = _descriptor(runtime, expected_row_count=1)
        with pytest.raises(ValueError, match="reserved"):
            list(_replay(runtime, descriptor))


def test_existing_csv_request_fingerprints_and_durable_jobs_remain_replayable(monkeypatch):
    with native_runtime(monkeypatch, row_count=3) as runtime:
        plan = compute_plan(runtime, durable=True)
        pending = submit(runtime, plan)
        job_id = pending["handle"]["job_id"]
        stored = runtime.engine._read_run(USER, job_id)
        legacy_request = runtime.service._compute_request(plan, "Compute doubled amounts.")
        for field in ("selected_table", "cell_range", "header_row"):
            legacy_request.pop(field, None)
        legacy_fingerprint = runtime.service.native_compute_digest({
            "request": legacy_request, "sources": stored["compute_context"]["sources"],
        })
        stored["compute_context"]["request_fingerprint"] = legacy_fingerprint
        runtime.jobs.replace_item(job_id, stored)
        reopened = submit(runtime, plan)
        assert reopened["status"] == "pending" and reopened["handle"]["job_id"] == job_id
        assert reopened["handle"]["request_fingerprint"] == legacy_fingerprint
        finished = runtime.engine.process_tabular_generated_output_run(job_id, USER)
        assert finished["status"] == "completed", finished.get("last_error")
        ready = open_result(runtime, reopened["handle"])
        rows = list(ready["reader"].iter_records())
        assert rows == [
            {"Item_ID": "item-000001", "doubled": 2},
            {"Item_ID": "item-000002", "doubled": 4},
            {"Item_ID": "item-000003", "doubled": 6},
        ]
        assert runtime.jobs.created == 1


def test_provider_exceptions_never_reach_public_tool_payloads(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        plugin = _plugin(runtime)
        runtime.patcher.setattr(
            plugin, "_get_workbook_metadata",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("Provider failure with private endpoint and credential details."),
            ),
        )
        payload, _ = _call(runtime, plugin, "describe_tabular_file")
        assert payload["error_code"] == "tabular_analysis_failed"
        assert "Provider" not in payload["error"] and "credential" not in payload["error"]


@pytest.mark.parametrize("corruption", ["duplicate_cursor", "expected_count", "checkpoint_identity"])
def test_staging_rejects_repeated_cursors_and_inconsistent_checkpoint_counts(monkeypatch, corruption):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _one_table(3, table_name="Facts"))
        plan = compute_plan(runtime, durable=True)
        plan["requested_output_hints"]["selected_table"] = "Facts"
        pending = submit(runtime, plan)
        job_id = pending["handle"]["job_id"]
        run = runtime.engine._read_run(USER, job_id)
        if corruption == "expected_count":
            run["source_descriptor"]["expected_row_count"] = 4
        runtime.jobs.replace_item(job_id, run)
        claimed = runtime.engine._try_claim_run(USER, job_id, runtime.settings)
        if corruption == "duplicate_cursor":
            runtime.patcher.setattr(
                runtime.engine, "_iter_versioned_tabular_source_rows",
                lambda *args, **kwargs: iter([(1, {"Item_ID": "A"}), (1, {"Item_ID": "A"})]),
            )
        elif corruption == "checkpoint_identity":
            original = runtime.engine._download_json_blob

            def corrupt_checkpoint(path):
                result = original(path)
                if isinstance(result, list) and result:
                    result[0][runtime.engine.TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD] = 9
                return result

            runtime.patcher.setattr(runtime.engine, "_download_json_blob", corrupt_checkpoint)
        with pytest.raises(ValueError):
            runtime.engine._stage_tabular_generated_output_source(claimed, runtime.settings)
        saved = runtime.engine._read_run(USER, job_id)
        assert saved["source_staging_complete"] is False
        assert saved["status"] != "completed"
        assert runtime.publications == []


def test_durable_checkpoint_resume_preserves_exact_selected_table_count(monkeypatch):
    with native_runtime(monkeypatch, filename="source.xlsx") as runtime:
        _set_source(runtime, _one_table(37, header=7, table_name="Facts"))
        plan = compute_plan(runtime, durable=True)
        plan["requested_output_hints"].update({"selected_table": "Facts", "header_row": "7"})
        pending = submit(runtime, plan)
        assert pending["status"] == "pending" and pending["reader"] is None
        job_id = pending["handle"]["job_id"]
        run = runtime.engine._read_run(USER, job_id)
        assert run["source_descriptor"]["expected_row_count"] == 37
        assert run["source_descriptor"]["header_row"] == 7
        run["source_descriptor"].update({"batch_max_rows": 5, "schema_probe_rows": 5})
        runtime.jobs.replace_item(job_id, run)
        claimed = runtime.engine._try_claim_run(USER, job_id, runtime.settings)
        original = runtime.engine._checkpoint_source_input_batch
        calls = []

        def interrupt_after_checkpoint(*args, **kwargs):
            saved = original(*args, **kwargs)
            calls.append(saved["source_staged_rows"])
            if len(calls) == 2:
                raise RuntimeError("Injected worker interruption after a durable checkpoint.")
            return saved

        with monkeypatch.context() as patcher:
            patcher.setattr(runtime.engine, "_checkpoint_source_input_batch", interrupt_after_checkpoint)
            with pytest.raises(RuntimeError, match="Injected worker"):
                runtime.engine._stage_tabular_generated_output_source(claimed, runtime.settings)
        interrupted = runtime.engine._read_run(USER, job_id)
        assert interrupted["source_staged_rows"] == 10
        assert interrupted["source_scan_row_count"] == 10
        assert interrupted["source_staging_complete"] is False
        interrupted["last_heartbeat_at"] = "2000-01-01T00:00:00+00:00"
        runtime.jobs.replace_item(job_id, interrupted)
        finished = runtime.engine.process_tabular_generated_output_run(job_id, USER)
        assert finished["status"] == "completed", finished.get("last_error")
        ready = open_result(runtime, pending["handle"])
        rows = list(ready["reader"].iter_records())
        assert len(rows) == 37
        assert sum(row["doubled"] for row in rows) == 37 * 38
        assert rows[-1] == {"Item_ID": "item-000037", "doubled": 74}
        stored = runtime.engine._read_run(USER, job_id)
        checkpoint_rows = []
        for number in range(1, stored["source_staged_batches"] + 1):
            checkpoint_rows.extend(runtime.engine._download_json_blob(
                runtime.engine._input_blob_path(USER, CONVERSATION, job_id, number),
            ))
        assert len(checkpoint_rows) == stored["source_staged_rows"] == 37
        assert [row["_excel_source"]["row"] for row in checkpoint_rows] == list(range(8, 45))
        token_field = runtime.engine.TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD
        assert len({row[token_field] for row in checkpoint_rows}) == 37
        assert runtime.publications == []
