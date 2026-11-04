# test_excel_document_accessibility_extraction.py
"""
Functional tests for native Excel inspection and workspace evidence persistence.
Version: 0.261.399
Implemented in: 0.261.399

Real workbook packages exercise saved properties, styles, notes, threaded comments,
drawings, controls, print metadata, limits, and unchanged original bytes. Ingestion
and route helpers run with isolated external-service boundaries and no cloud calls.
"""

import ast
import hashlib
import json
import logging
import os
import struct
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas
import pytest
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import functions_excel_accessibility as excel  # noqa: E402
from functions_accessibility import (  # noqa: E402
    extract_office_accessibility_metadata,
    format_accessibility_metadata_for_chat,
)
from functions_agent_document_citations import (  # noqa: E402
    annotate_document_search_payload,
    build_document_citations_from_result_payload,
)
from test_document_accessibility_report_action import _load_payload_namespace  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _rewrite(path, transform):
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    transform(parts)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)


def _relationships(parts, path, additions):
    root = ET.fromstring(parts.get(path, f'<Relationships xmlns="{REL_NS}"/>'))
    for identifier, kind, target, external in additions:
        attributes = {"Id": identifier, "Type": f"http://example.test/relationships/{kind}", "Target": target}
        if external:
            attributes["TargetMode"] = "External"
        ET.SubElement(root, f"{{{REL_NS}}}Relationship", attributes)
    parts[path] = ET.tostring(root)


@pytest.fixture
def workbook_path(tmp_path):
    path = tmp_path / "inspection.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Budget & Notes"
    workbook.properties.title = "Saved accessibility budget"
    workbook.properties.creator = "Test Author;Reviewer"
    workbook.properties.keywords = "budget;accessibility"
    workbook.properties.language = "en-US"
    sheet.append(["Account", "Amount"])
    sheet.append(["Operations", 42])
    sheet["B2"].font = Font(name="Arial", sz=9, bold=True, color="FF0000")
    sheet["B2"].fill = PatternFill("solid", fgColor="FFFF00")
    sheet["B2"].alignment = Alignment(horizontal="right", wrap_text=True)
    sheet["B2"].number_format = "$0.00"
    sheet["A2"].comment = Comment("Verify this budget note", "Reviewer")
    sheet["C4"] = "Theme color"
    sheet["C4"].font = Font(scheme="minor", sz=11, color="FF00FF")
    sheet.merge_cells("D5:E5")
    sheet.freeze_panes = "B2"
    sheet.row_dimensions[3].hidden = True
    sheet.column_dimensions["C"].width = 28
    sheet.oddHeader.left.text = "Confidential"
    sheet.oddFooter.right.text = "Page &P of &N"
    sheet.firstHeader.center.text = "First page"
    sheet.HeaderFooter.differentFirst = True
    sheet.print_title_rows = "1:1"
    sheet.conditional_formatting.add("B2:B20", CellIsRule(operator="greaterThan", formula=["50"]))
    blank = workbook.create_sheet("Blank hidden sheet")
    blank.sheet_state = "hidden"
    blank.oddFooter.center.text = "No worksheet rows"
    workbook.save(path)

    def add_native_parts(parts):
        _relationships(parts, "xl/worksheets/_rels/sheet1.xml.rels", [
            ("thread", "threadedComment", "../threadedComments/thread.xml", False),
            ("drawingExtra", "drawing", "../drawings/native.xml", False),
            ("external", "drawing", "https://example.test/never-fetch.xml", True),
        ])
        _relationships(parts, "xl/_rels/workbook.xml.rels", [
            ("persons", "person", "persons/person.xml", False),
        ])
        parts["xl/persons/person.xml"] = b'<personList><person id="p1" displayName="Thread Reviewer"/></personList>'
        parts["xl/threadedComments/thread.xml"] = b'''<ThreadedComments>
            <threadedComment ref="B2" id="t1" personId="p1" dT="2026-01-02T03:04:05Z" done="1"><text>Thread root</text></threadedComment>
            <threadedComment ref="B2" id="t2" parentId="t1" personId="p1"><text>Thread reply</text></threadedComment>
            </ThreadedComments>'''
        parts["xl/drawings/native.xml"] = b'''<wsDr xmlns:a="urn:a" xmlns:c="urn:c" xmlns:adec="urn:decorative">
            <twoCellAnchor><from><col>1</col><row>2</row></from><pic><nvPicPr>
            <cNvPr id="1" name="Budget image" descr="Budget summary chart"><a:extLst><a:ext><adec:decorative val="0"/></a:ext></a:extLst></cNvPr>
            </nvPicPr></pic></twoCellAnchor>
            <oneCellAnchor><from><col>3</col><row>4</row></from><graphicFrame><nvGraphicFramePr>
            <cNvPr id="2" name="Chart" title="Annual budget"/></nvGraphicFramePr><c:chart/></graphicFrame></oneCellAnchor>
            <absoluteAnchor><sp><nvSpPr><cNvPr id="3" name="Border"><adec:decorative val="1"/></cNvPr></nvSpPr></sp></absoluteAnchor>
            </wsDr>'''
        vml = next(name for name in parts if name.endswith(".vml"))
        root = ET.fromstring(parts[vml])
        shape = ET.SubElement(root, "{urn:schemas-microsoft-com:vml}shape", {"id": "checkbox1", "alt": "Approve budget"})
        client = ET.SubElement(shape, "{urn:schemas-microsoft-com:office:excel}ClientData", {"ObjectType": "Checkbox"})
        ET.SubElement(client, "{urn:schemas-microsoft-com:office:excel}Row").text = "6"
        ET.SubElement(client, "{urn:schemas-microsoft-com:office:excel}Column").text = "2"
        parts[vml] = ET.tostring(root)
        # Physical part names must not determine workbook order or sheet identity.
        parts["xl/worksheets/custom.xml"] = parts.pop("xl/worksheets/sheet1.xml")
        parts["xl/worksheets/_rels/custom.xml.rels"] = parts.pop("xl/worksheets/_rels/sheet1.xml.rels")
        parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
            b"/xl/worksheets/sheet1.xml", b"/xl/worksheets/custom.xml")
        parts["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(
            b"/xl/worksheets/sheet1.xml", b"/xl/worksheets/custom.xml")

    _rewrite(path, add_native_parts)
    return path


def test_native_excel_properties_comments_objects_styles_and_printing(workbook_path):
    before = hashlib.sha256(workbook_path.read_bytes()).digest()
    metadata, evidence = extract_office_accessibility_metadata(str(workbook_path), ".xlsx")
    assert metadata["coverage"] == "partial", metadata
    assert metadata["title"] == "Saved accessibility budget"
    assert metadata["authors"] == ["Test Author", "Reviewer"]
    assert metadata["keywords"] == ["budget", "accessibility"]
    assert metadata["sheet_count"] == 2
    assert metadata["sheets"][0]["part"].endswith("custom.xml")
    assert metadata["sheets"][1]["state"] == "hidden"
    assert metadata["sheets"][0]["conditional_format_rules"] == 1
    assert "Confidential" in metadata["sheets"][0]["header_footer"]["expressions"]["oddHeader"]
    assert "&P" in metadata["sheets"][0]["header_footer"]["expressions"]["oddFooter"]
    assert metadata["print_defined_names"][0]["name"] == "_xlnm.Print_Titles"
    notes = metadata["comments"]
    assert any(item["kind"] == "note" and item["cell"] == "A2" and item["author"] == "Reviewer" for item in notes)
    root = next(item for item in notes if item["id"] == "t1")
    reply = next(item for item in notes if item["id"] == "t2")
    assert root["resolved"] is True and root["author"] == "Thread Reviewer"
    assert reply["parent_id"] == "t1" and reply["resolved"] is None
    objects = metadata["objects"]
    assert any(item.get("alt_text") == "Budget summary chart" and item["cell"] == "B3" for item in objects)
    assert any(item.get("type") == "chart" and item["title"] == "Annual budget" for item in objects)
    assert any(item.get("is_decorative") is True for item in objects)
    assert any(item["type"] == "Checkbox" and item["cell"] == "C7" for item in objects)
    style = metadata["style_inventory"]
    assert any(item["name"] == "Arial" for item in style["fonts"])
    assert style["min_size_pt"] == 9
    assert any(item["color"] == "#FF0000" for item in style["colors"])
    body = "\n".join(item["content"] for item in evidence)
    assert "Thread reply" in body and "$0.00" in body and "#FFFF00" in body
    assert "Operations" not in body, "Native evidence must not become a copy of worksheet rows"
    assert "No worksheet rows" in body, "Blank sheets still have native evidence"
    assert any("External relationships" in note for note in metadata["coverage_notes"])
    summary = format_accessibility_metadata_for_chat(metadata)
    assert "Saved workbook properties" in summary and "coverage: partial" in summary
    assert "None flagged" not in summary
    assert hashlib.sha256(workbook_path.read_bytes()).digest() == before


def test_evidence_budgets_and_macro_workbook_bytes(workbook_path):
    def add_macro(parts):
        parts["xl/vbaProject.bin"] = b"INERT TEST MACRO - MUST NEVER EXECUTE"
    _rewrite(workbook_path, add_macro)
    before = workbook_path.read_bytes()
    metadata, evidence = excel.extract_excel_accessibility_metadata(workbook_path, ".xlsm")
    assert metadata["format"] == "xlsm"
    chunks = excel.build_excel_evidence_chunks(evidence, "sample.xlsm", 600)
    assert len(chunks) > 1
    assert all(len(text) <= 600 and "Workbook: sample.xlsm" in text for text in chunks)
    assert "Thread reply" in "".join(chunks)
    assert workbook_path.read_bytes() == before


@pytest.mark.parametrize("failure", ["xml", "entities", "zip", "oversize", "duplicate"])
def test_malformed_packages_are_not_clean_reports(workbook_path, monkeypatch, failure):
    if failure == "zip":
        workbook_path.write_bytes(b"not an Excel ZIP")
    elif failure == "oversize":
        monkeypatch.setattr(excel, "EXCEL_MAX_PART_BYTES", 20)
    elif failure == "duplicate":
        with zipfile.ZipFile(workbook_path, "a") as archive:
            archive.writestr("xl/workbook.xml", b"<workbook/>")
    else:
        def mutate(parts):
            parts["xl/workbook.xml"] = (
                b"<broken" if failure == "xml" else
                b'<!DOCTYPE test [<!ENTITY x SYSTEM "file:///never-read">]><workbook>&x;</workbook>'
            )
        _rewrite(workbook_path, mutate)
    metadata, evidence = excel.extract_excel_accessibility_metadata(workbook_path, ".xlsx")
    assert metadata["coverage"] == "failed"
    assert metadata["issues"][0]["code"] == "EXCEL_INSPECTION_INCOMPLETE"
    assert any("failed" in item["content"] for item in evidence)


def test_cell_record_and_parent_limits_are_explicit(workbook_path, monkeypatch):
    monkeypatch.setattr(excel, "EXCEL_MAX_CELLS", 2)
    monkeypatch.setattr(excel, "EXCEL_MAX_RECORDS", 2)
    monkeypatch.setattr(excel, "EXCEL_MAX_PARENT_BYTES", 6000)
    metadata, evidence = excel.extract_excel_accessibility_metadata(workbook_path, ".xlsx")
    assert metadata["inspected_cells"] == 2
    assert len(metadata["comments"]) + len(metadata["objects"]) <= 2
    assert len(json.dumps(metadata, ensure_ascii=True).encode()) <= 6000
    assert any("sampled" in note for note in metadata["coverage_notes"])
    assert any("record limit" in note for note in metadata["coverage_notes"])
    assert evidence


def test_parent_byte_trimming_keeps_retained_object_counts_accurate(workbook_path, monkeypatch):
    monkeypatch.setattr(excel, "EXCEL_MAX_PARENT_BYTES", 6000)
    metadata, _ = excel.extract_excel_accessibility_metadata(workbook_path, ".xlsx")
    objects = metadata["objects"]
    figures = metadata["figures_summary"]
    assert len(json.dumps(metadata, ensure_ascii=True).encode()) <= 6000
    assert figures["with_alt"] == sum(bool(item.get("alt_text") or item.get("title")) for item in objects)
    assert figures["decorative"] == sum(item.get("is_decorative") is True for item in objects)
    assert figures["missing_alt"] == sum(
        item.get("alt_inspected") is True and not item.get("alt_text")
        and not item.get("title") and item.get("is_decorative") is not True
        for item in objects
    )
    assert metadata["forms_summary"]["controls_inspected"] == sum(
        item.get("type", "").lower() in ("checkbox", "check box", "button", "radio")
        for item in objects
    )
    assert any("serialized byte limit" in note for note in metadata["coverage_notes"])
    assert any("serialized byte limit" in note for note in metadata["style_inventory"]["coverage_notes"])


def test_theme_indexed_colors_and_row_style_inheritance(workbook_path):
    def mutate(parts):
        root = ET.fromstring(parts["xl/styles.xml"])
        fonts = root.find("{*}fonts")
        for font in fonts:
            color = font.find("{*}color")
            if color is not None:
                color.attrib.clear()
                color.set("theme", "1")
        # A custom indexed palette must take priority over the built-in one.
        font = fonts[-1]
        color = font.find("{*}color")
        color.attrib.clear()
        color.set("indexed", "0")
        existing_colors = root.find("{*}colors")
        if existing_colors is not None:
            root.remove(existing_colors)
        colors = ET.SubElement(root, "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}colors")
        indexed = ET.SubElement(colors, "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}indexedColors")
        ET.SubElement(indexed, "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}rgbColor", {"rgb": "00123456"})
        parts["xl/styles.xml"] = ET.tostring(root)
        sheet = ET.fromstring(parts["xl/worksheets/custom.xml"])
        cell = sheet.find(".//{*}c[@r='B2']")
        style = cell.attrib.pop("s")
        row = sheet.find(".//{*}row[@r='2']")
        row.set("s", style)
        row.set("customFormat", "1")
        parts["xl/worksheets/custom.xml"] = ET.tostring(sheet)
    _rewrite(workbook_path, mutate)
    metadata, evidence = excel.extract_excel_accessibility_metadata(workbook_path, ".xlsx")
    colors = [item["color"] for item in metadata["style_inventory"]["colors"]]
    assert "#123456" in colors and "#000000" in colors
    content = "\n".join(item["content"] for item in evidence)
    assert '"saved_style"' in content and '"size_pt": 9.0' in content


def test_chartsheet_and_print_headers_follow_relationships(workbook_path):
    def mutate(parts):
        root = ET.fromstring(parts["xl/workbook.xml"])
        sheets = root.find("{*}sheets")
        ET.SubElement(sheets, "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet", {
            "name": "Chart only", "sheetId": "19",
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id": "chartOnly",
        })
        parts["xl/workbook.xml"] = ET.tostring(root)
        _relationships(parts, "xl/_rels/workbook.xml.rels", [
            ("chartOnly", "chartsheet", "chartsheets/nonsequential.xml", False),
        ])
        parts["xl/chartsheets/nonsequential.xml"] = b'<chartsheet><headerFooter><oddHeader>&amp;LLeft&amp;CCenter&amp;RRight &amp;P</oddHeader></headerFooter></chartsheet>'
    _rewrite(workbook_path, mutate)
    metadata, evidence = excel.extract_excel_accessibility_metadata(workbook_path, ".xlsx")
    chart = next(sheet for sheet in metadata["sheets"] if sheet["name"] == "Chart only")
    assert chart["type"] == "chartsheet"
    assert chart["header_footer"]["sections"]["oddHeader"] == {
        "left": "Left", "center": "Center", "right": "Right &P",
    }
    assert excel._header_sections("&LUse &&R literally") == {"left": "Use &&R literally"}
    assert any("Chart only" in item["content"] for item in evidence)


def test_search_limit_preserves_coverage_and_external_targets_are_never_read(workbook_path, monkeypatch):
    monkeypatch.setattr(excel, "EXCEL_MAX_EVIDENCE_CHARS", 4000)
    def mutate(parts):
        _relationships(parts, "xl/worksheets/_rels/custom.xml.rels", [
            ("escape", "drawing", "../../../outside.xml", False),
        ])
    _rewrite(workbook_path, mutate)
    metadata, evidence = excel.extract_excel_accessibility_metadata(workbook_path, ".xlsx")
    assert sum(len(item["content"]) for item in evidence) <= 4000
    assert "inspection coverage" in evidence[0]["content"]
    assert "truncated" in evidence[0]["content"]
    assert any("Out-of-package" in note for note in metadata["coverage_notes"])


def test_real_legacy_biff_workbook_has_explicit_partial_coverage(tmp_path):
    def record(code, payload=b""):
        return struct.pack("<HH", code, len(payload)) + payload

    def bof(kind):
        return record(0x809, struct.pack("<HHHHII", 0x600, kind, 0x0DBB, 0x07CC, 0, 6))

    font = record(0x31, struct.pack("<HHHHHBBBBBB", 220, 0, 0x7FFF, 400, 0, 0, 0, 0, 0, 5, 0) + b"Arial")
    prefix = bof(5) + record(0x42, struct.pack("<H", 1252)) + font + record(0xE0, b"\0" * 20)
    boundsheet = lambda offset: record(0x85, struct.pack("<IBBBB", offset, 0, 0, 6, 0) + b"Sheet1")
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
    path = tmp_path / "legacy.xls"
    path.write_bytes(bytes(header) + struct.pack("<128I", *fat) + directory_data.ljust(512, b"\0") + stream)
    metadata, evidence = excel.extract_excel_accessibility_metadata(path, ".xls")
    assert metadata["coverage"] == "partial", metadata
    assert metadata["sheet_count"] == 1
    assert metadata["style_inventory"]["body_font"] == "Arial"
    assert metadata["style_inventory"]["body_size_pt"] == 11
    assert any("Legacy XLS inspection" in note for note in metadata["coverage_notes"])
    assert any("Legacy saved formatting summary" in item["content"] for item in evidence)


def _load_functions(file_name, names, namespace):
    tree = ast.parse((APP / file_name).read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), file_name, "exec"), namespace)
    return namespace


def _ingestion_namespace(fail_schema=False, fail_index=False):
    chunks, updates, uploads = [], [], []

    def save_chunks(**kwargs):
        if fail_index and kwargs["page_number"] == 1 and kwargs["page_text_content"] == "schema preview":
            raise ValueError("injected schema indexing failure")
        chunks.append(kwargs)
        return {"total_tokens": 2, "model_deployment_name": "test-embedding"}

    def save_batch(batch, user_id, document_id, **scope):
        chunks.extend({**item, **scope, "user_id": user_id, "document_id": document_id} for item in batch)
        return {"total_tokens": len(batch) * 2, "model_deployment_name": "test-embedding"}

    def schema(*args):
        if fail_schema:
            raise ValueError("injected schema extraction failure")
        return "schema preview"

    namespace = {
        "pandas": pandas, "os": os, "logging": logging,
        "log_event": lambda *args, **kwargs: None,
        "extract_office_accessibility_metadata": extract_office_accessibility_metadata,
        "build_excel_evidence_chunks": excel.build_excel_evidence_chunks,
        "get_embedding_safe_chunk_characters": lambda settings: 900,
        "get_settings": lambda: {"enable_extract_meta_data": True},
        "get_chunk_size_config": lambda settings: {"excel": {"value": 20}, "csv": {"value": 20}},
        "upload_to_blob": lambda **kwargs: uploads.append(kwargs),
        "_build_tabular_schema_summary": schema,
        "_build_minimal_tabular_summary": lambda *args: "compact schema",
        "save_chunks": save_chunks, "save_chunks_batch": save_batch,
        "extract_document_metadata": lambda **kwargs: {"title": "AI-generated title"},
    }
    _load_functions("functions_documents.py", {"process_tabular", "process_single_tabular_sheet"}, namespace)
    return namespace, chunks, updates, uploads


@pytest.mark.parametrize("enhanced", [False, True])
@pytest.mark.parametrize("scope", [{}, {"group_id": "group-1"}, {"public_workspace_id": "public-1"}])
@pytest.mark.parametrize("auto_metadata", [False, True])
def test_ingestion_modes_scopes_native_properties_and_chunk_identity(workbook_path, enhanced, scope, auto_metadata):
    namespace, chunks, updates, uploads = _ingestion_namespace()
    count, tokens, model = namespace["process_tabular"](
        "doc-1", "user-1", str(workbook_path), "inspection.xlsx", ".xlsx",
        enhanced, lambda **kwargs: updates.append(kwargs),
        auto_extract_metadata=auto_metadata, **scope,
    )
    assert count == len(chunks) and tokens == count * 2
    assert model == "test-embedding"
    sequences = [item["page_number"] for item in chunks]
    assert sequences == list(range(1, count + 1))
    assert len(uploads) == int(enhanced)
    assert all(all(item.get(key) == value for key, value in scope.items()) for item in chunks)
    stored = next(item["accessibility_metadata"] for item in updates if "accessibility_metadata" in item)
    assert stored["title"] == "Saved accessibility budget"
    assert any("Thread reply" in item["page_text_content"] for item in chunks)
    native = [item for item in chunks if excel.EXCEL_EVIDENCE_MARKER in item["page_text_content"]]
    assert native and all(len(item["page_text_content"]) <= 900 for item in native)
    if enhanced:
        assert chunks[0]["page_text_content"] == "schema preview"
        assert all("Operations" not in item["page_text_content"] for item in native)
    assert any(item.get("num_chunks") == count for item in updates)
    assert any(item.get("title") == "AI-generated title" for item in updates) is auto_metadata


@pytest.mark.parametrize("enhanced", [False, True])
@pytest.mark.parametrize("populated", [False, True])
def test_empty_and_multiple_populated_sheets_keep_native_evidence(tmp_path, enhanced, populated):
    path = tmp_path / "multiple.xlsx"
    workbook = Workbook()
    workbook.active.title = "First"
    workbook.create_sheet("Second")
    for index, sheet in enumerate(workbook.worksheets):
        sheet.oddHeader.left.text = f"Header for {sheet.title}"
        if populated:
            sheet.append(["Name", "Value"])
            sheet.append([f"Row {index + 1}", index + 10])
    workbook.save(path)
    namespace, chunks, updates, _ = _ingestion_namespace()
    count, _, _ = namespace["process_tabular"](
        "doc", "user", str(path), path.name, ".xlsx", enhanced,
        lambda **kwargs: updates.append(kwargs), auto_extract_metadata=False,
    )
    assert count == len(chunks)
    assert [item["page_number"] for item in chunks] == list(range(1, count + 1))
    native = [item for item in chunks if excel.EXCEL_EVIDENCE_MARKER in item["page_text_content"]]
    assert "Header for First" in "".join(item["page_text_content"] for item in native)
    assert "Header for Second" in "".join(item["page_text_content"] for item in native)
    rows = [item for item in chunks if excel.EXCEL_EVIDENCE_MARKER not in item["page_text_content"]]
    if enhanced:
        assert [item["page_text_content"] for item in rows] == ["schema preview"]
    else:
        assert len(rows) == (2 if populated else 0)
        if populated:
            assert {item["file_name"] for item in rows} == {"multiple-First.xlsx", "multiple-Second.xlsx"}


@pytest.mark.parametrize("failure", ["schema", "index"])
def test_compact_schema_fallback_keeps_native_evidence(workbook_path, failure):
    namespace, chunks, updates, _ = _ingestion_namespace(fail_schema=failure == "schema", fail_index=failure == "index")
    namespace["process_tabular"](
        "doc", "user", str(workbook_path), "inspection.xlsx", ".xlsx", True,
        lambda **kwargs: updates.append(kwargs), auto_extract_metadata=False,
    )
    assert chunks[0]["page_text_content"] == "compact schema"
    assert any("Thread reply" in chunk["page_text_content"] for chunk in chunks)


def test_report_and_citations_reuse_authorized_contract(workbook_path):
    metadata, _ = excel.extract_excel_accessibility_metadata(workbook_path, ".xlsx")
    document = {"id": "doc-1", "accessibility_metadata": metadata}
    namespace = _load_payload_namespace(document)
    payload = namespace["get_document_accessibility_payload"]("doc-1", "user-1")
    assert payload["accessibility_metadata"]["properties"]["title"] == "Saved accessibility budget"
    assert payload["style_inventory"]["min_size_pt"] == 9
    payload["document"]["file_name"] = "inspection.xlsx"
    annotated = annotate_document_search_payload(payload, "get_document_accessibility_report")
    citations = build_document_citations_from_result_payload(
        annotated, "document_search", "get_document_accessibility_report",
    )
    assert annotated["citation"] and citations[0]["document_id"] == "doc-1"
    denied = _load_payload_namespace(None)
    with pytest.raises(LookupError, match="access denied"):
        denied["get_document_accessibility_payload"]("doc-1", "different-user")


@pytest.mark.parametrize("question", [
    "Show the cell notes and comments", "What is the document title and author?",
    "Which images have missing alt text?", "List decorative charts",
    "Inspect font colors and headers/footers", "Are checkboxes labelled?",
])
def test_native_question_routing(question):
    result = excel.is_excel_native_inspection_question(question)
    assert result


@pytest.mark.parametrize("question", [
    "What was total revenue?", "Calculate the total and list comments",
    "What worksheets and columns does the workbook have?", "Find account number 123",
    "Average sales by region", "Comment on this year's sales performance",
])
def test_data_questions_keep_existing_routing(question):
    result = excel.is_excel_native_inspection_question(question)
    assert not result


@pytest.mark.parametrize("file_names,expected", [
    (["budget.xlsx"], True),
    (["budget.XLSM", "legacy.xls"], True),
    (["comments.csv"], False),
    (["budget.xlsx", "comments.csv"], False),
    ([], False),
    ([None], False),
])
def test_native_routing_preserves_non_excel_data_analysis(file_names, expected):
    result = excel.is_excel_native_inspection_question("Show comments", file_names=file_names)
    assert result is expected


def test_mixed_source_inspection_uses_report_search_authorization_and_citations():
    calls = []
    report = {
        "document": {"id": "doc-1", "file_name": "inspection.xlsx"},
        "accessibility_metadata": {"format": "xlsx", "coverage": "partial", "properties": {"title": "Native"}},
        "style_inventory": {},
    }

    def get_report(document_id, user_id, **kwargs):
        calls.append(("report", document_id, user_id, kwargs))
        return report

    def search(**kwargs):
        calls.append(("search", kwargs))
        return {"results": [{
            "id": "doc-1_2", "document_id": "doc-1", "file_name": "inspection.xlsx",
            "page_number": 2, "chunk_text": excel.EXCEL_EVIDENCE_MARKER + "\nThread reply at Budget!B2",
        }]}

    def execute(sources, callback, selection_mode, **kwargs):
        return [callback(source) for source in sources]

    namespace = {
        "get_document_accessibility_payload": get_report, "search_documents": search,
        "annotate_document_search_payload": annotate_document_search_payload,
        "format_accessibility_metadata_for_chat": format_accessibility_metadata_for_chat,
        "EXCEL_EVIDENCE_MARKER": excel.EXCEL_EVIDENCE_MARKER,
        "execute_tabular_evidence_sources": execute,
    }
    _load_functions("route_backend_chats.py", {"_execute_excel_native_inspection_evidence"}, namespace)
    result = namespace["_execute_excel_native_inspection_evidence"](
        [{"document_id": "doc-1", "scope": "group", "group_id": "group-1"}],
        "Show comments", "user-1", "conv-1", "selected",
    )
    assert calls[0][3]["active_group_ids"] == ["group-1"]
    assert calls[1][1]["document_ids"] == ["doc-1"]
    assert "Thread reply" in result["evidence_envelopes"][0]["summary"]
    assert result["agent_citations"] and not result["generated_outputs"]
    assert result["evidence_envelopes"][0]["coverage"]["worksheet_data_computed"] is False
    _load_functions("route_backend_chats.py", {"_execute_mixed_source_tabular_evidence"}, namespace)
    namespace["is_excel_native_inspection_question"] = excel.is_excel_native_inspection_question
    routed = namespace["_execute_mixed_source_tabular_evidence"](
        tabular_sources=[{"document_id": "doc-1", "file_name": "inspection.xlsx", "scope": "group", "group_id": "group-1"}],
        user_question="Show comments", user_id="user-1", conversation_id="conv-1",
        selection_mode="selected", has_narrative_sources=False, gpt_model="unused",
        settings={"enable_tabular_processing": False},
    )
    assert "Thread reply" in routed["evidence_envelopes"][0]["summary"]


def test_version_and_both_route_paths():
    assert_app_version_at_least("0.261.399")
    source = (APP / "route_backend_chats.py").read_text(encoding="utf-8")
    assert source.count("and not is_excel_native_inspection_question(user_message, file_names=workspace_tabular_files)") == 2
    assert "user_question, file_names=[source.get('file_name') for source in tabular_sources]" in source
    assert "explicitly labelled Excel native inspection evidence" in source


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
