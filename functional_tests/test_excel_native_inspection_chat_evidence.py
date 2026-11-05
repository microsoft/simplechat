# test_excel_native_inspection_chat_evidence.py
"""
Functional tests for complete, source-backed Excel native evidence.
Version: 0.261.408
Implemented in: 0.261.408

Real packages distinguish threaded compatibility copies from genuine notes,
preserve saved cell values and unavailable caches, and retain comment content.
No model or cloud service is called.
"""

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from openpyxl import Workbook
from openpyxl.comments import Comment

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from functions_accessibility import format_accessibility_metadata_for_chat  # noqa: E402
from functions_excel_accessibility import extract_excel_accessibility_metadata  # noqa: E402
import functions_excel_accessibility as excel  # noqa: E402
from functions_agent_document_citations import annotate_document_search_payload  # noqa: E402
from test_excel_document_accessibility_extraction import _load_functions  # noqa: E402


REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def add_relationship(parts, path, identifier, kind, target):
    root = ET.fromstring(parts.get(path, f'<Relationships xmlns="{REL_NS}"/>'))
    ET.SubElement(root, f"{{{REL_NS}}}Relationship", {
        "Id": identifier,
        "Type": f"http://schemas.microsoft.com/office/2017/10/relationships/{kind}",
        "Target": target,
    })
    parts[path] = ET.tostring(root)


@pytest.fixture
def review_workbook(tmp_path):
    path = tmp_path / "review.xlsx"
    workbook = Workbook()
    workbook.active.title = "Budget"
    workbook.create_sheet("Delivery")
    for sheet in workbook:
        sheet.append(["Delivery review"])
        sheet.append(["Site", "Cap", "Delivered", "Accepted"])
        sheet.append(["North", 12000, 18, True])
        sheet.append(["South", 15000, 12, False])
        sheet.append(["East", 9000, 9, True])
    workbook["Budget"]["B4"].comment = Comment(
        "[Threaded comment]\nSet cap to 19500.\nHold approval.",
        "tc={root-budget}",
    )
    workbook["Budget"]["D12"].comment = Comment(
        "[Threaded comment]\nArrange a review.", "tc={root-blank}",
    )
    workbook["Budget"]["A3"].comment = Comment("A genuine legacy note.", "Legacy reviewer")
    workbook["Delivery"]["B4"].comment = Comment(
        "[Threaded comment]\nKeep cap at 15000.", "tc={root-delivery}",
    )
    workbook.save(path)
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    add_relationship(parts, "xl/_rels/workbook.xml.rels", "people", "person", "persons/person.xml")
    parts["xl/persons/person.xml"] = b'<personList><person id="a" displayName="Reviewer A"/><person id="b" displayName="Reviewer B"/></personList>'
    for index, comments in enumerate((
        """<threadedComment ref="B4" id="{root-budget}" personId="a" dT="2026-01-01T10:00:00Z"><text>Set cap to 19500.</text></threadedComment>
        <threadedComment ref="B4" id="{reply-budget}" parentId="{root-budget}" personId="b"><text>Hold approval.</text></threadedComment>
        <threadedComment ref="D12" id="{root-blank}" personId="b"><text>Arrange a review.</text></threadedComment>""",
        """<threadedComment ref="B4" id="{root-delivery}" personId="a" done="1"><text>Keep cap at 15000.</text></threadedComment>""",
    ), start=1):
        add_relationship(
            parts, f"xl/worksheets/_rels/sheet{index}.xml.rels",
            "thread", "threadedComment", f"../threadedComments/comments{index}.xml",
        )
        parts[f"xl/threadedComments/comments{index}.xml"] = f"<ThreadedComments>{comments}</ThreadedComments>".encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return path


def test_threaded_compatibility_copies_do_not_become_legacy_notes(review_workbook):
    before = hashlib.sha256(review_workbook.read_bytes()).hexdigest()
    metadata, evidence = extract_excel_accessibility_metadata(review_workbook, ".xlsx")
    summary = metadata["comment_summary"]
    assert summary == {
        "legacy_notes": 1, "thread_roots": 3, "replies": 1,
        "thread_messages": 4, "compatibility_copies": 3, "raw_records": 8,
    }
    assert len(metadata["comments"]) == 5
    assert metadata["observed_counts"]["comments"] == 5
    assert all(not str(item.get("author")).startswith("tc=") for item in metadata["comments"])
    assert any(item["kind"] == "note" and item["text"] == "A genuine legacy note." for item in metadata["comments"])
    text = "\n".join(item["content"] for item in evidence)
    assert "[Threaded comment]" not in text
    assert hashlib.sha256(review_workbook.read_bytes()).hexdigest() == before


def test_native_records_include_saved_cell_values_and_blank_cells(review_workbook):
    metadata, _ = extract_excel_accessibility_metadata(review_workbook, ".xlsx")
    comments = {item["id"]: item for item in metadata["comments"] if item.get("id")}
    budget = comments["{root-budget}"]
    delivery = comments["{root-delivery}"]
    blank = comments["{root-blank}"]
    assert budget["sheet"] == "Budget" and budget["cell"] == "B4"
    assert budget["cell_value"] == 15000 and budget["cell_value_status"] == "saved"
    assert delivery["cell_value"] == 15000 and delivery["resolved"] is True
    assert blank["cell_value"] is None and blank["cell_value_status"] == "blank"
    assert comments["{reply-budget}"]["date"] is None
    assert comments["{reply-budget}"]["resolved"] is None
    assert comments["{reply-budget}"]["parent_id"] == "{root-budget}"


def test_chat_formatter_supplies_comment_text_not_just_counts(review_workbook):
    metadata, _ = extract_excel_accessibility_metadata(review_workbook, ".xlsx")
    rendered = format_accessibility_metadata_for_chat(metadata)
    assert "Set cap to 19500." in rendered
    assert "Hold approval." in rendered
    assert "Keep cap at 15000." in rendered
    assert "Budget!B4" in rendered and "Delivery!B4" in rendered
    assert "15000" in rendered
    assert "reviewer feedback" in rendered.lower()


def test_comment_inventory_sink_preserves_text_beyond_parent_preview(tmp_path):
    path = tmp_path / "long-note.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "Value"
    workbook.active["A2"] = 0
    text = "Start " + "long review text " * 1000 + "END-OF-COMMENT"
    workbook.active["A2"].comment = Comment(text, "Reviewer")
    workbook.save(path)
    records = []
    metadata, _ = extract_excel_accessibility_metadata(
        path, ".xlsx", record_sink=lambda kind, record: records.append((kind, record)),
    )
    note = next(record for kind, record in records if kind == "comments")
    assert note["text"] == text
    assert note["cell_value"] == 0
    assert len(json.dumps(metadata, ensure_ascii=True).encode()) <= 500000
    assert metadata["comments"][0]["text_truncated"] is True


def test_formula_without_cache_is_not_blank_or_zero(tmp_path):
    path = tmp_path / "formula.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "Amount"
    workbook.active["A2"] = "=1+2"
    workbook.active["A2"].comment = Comment("Confirm calculated amount.", "Reviewer")
    workbook.save(path)
    metadata, _ = extract_excel_accessibility_metadata(path, ".xlsx")
    note = metadata["comments"][0]
    assert note["formula"] == "=1+2"
    assert note["cell_value"] is None
    assert note["cell_value_status"] == "cache_missing"
    assert note["cached_value_available"] is False


def test_actual_chat_handoff_uses_known_records_when_relevance_has_no_matches(review_workbook):
    metadata, _ = extract_excel_accessibility_metadata(review_workbook, ".xlsx")
    metadata["properties"]["long_context"] = "irrelevant prefix " * 1200
    metadata["style_inventory"]["long_context"] = "layout prefix " * 1500
    report = {
        "document": {"id": "doc", "file_name": "review.xlsx"},
        "accessibility_metadata": metadata,
        "style_inventory": metadata["style_inventory"],
        "citation_chunk": {"id": "doc_2", "document_id": "doc", "file_name": "review.xlsx",
                           "page_number": 2, "chunk_text": excel.EXCEL_EVIDENCE_MARKER + "\nNative comments"},
    }
    calls = []

    def get_report(document_id, user_id, **kwargs):
        calls.append((document_id, user_id, kwargs))
        return report

    def unexpected_search(**kwargs):
        raise AssertionError("A known complete comment inventory must not depend on relevance search.")

    namespace = {
        "get_document_accessibility_payload": get_report, "search_documents": unexpected_search,
        "annotate_document_search_payload": annotate_document_search_payload,
        "build_excel_native_chat_evidence": excel.build_excel_native_chat_evidence,
        "excel_native_question_sections": excel.excel_native_question_sections,
        "EXCEL_EVIDENCE_MARKER": excel.EXCEL_EVIDENCE_MARKER,
        "execute_tabular_evidence_sources": lambda sources, callback, mode, **kwargs: [callback(source) for source in sources],
    }
    _load_functions("route_backend_chats.py", {"_execute_excel_native_inspection_evidence"}, namespace)
    result = namespace["_execute_excel_native_inspection_evidence"](
        [{"document_id": "doc", "scope": "group", "group_id": "group"}],
        "List every cell note and threaded comment and the saved cell values",
        "owner", "conversation", "selected",
    )
    text = result["evidence_envelopes"][0]["summary"]
    assert "Set cap to 19500." in text and "Hold approval." in text
    assert "Keep cap at 15000." in text and "Arrange a review." in text
    assert "Budget!B4" in text and "Delivery!B4" in text
    assert "Native evidence segment 2" in text and "[#doc_2]" in text
    assert len(text.encode("utf-8")) <= 16384
    assert calls[0][2]["active_group_ids"] == ["group"]
    assert result["evidence_envelopes"][0]["coverage"]["worksheet_data_computed"] is False


def test_mixed_calculation_handoff_preserves_native_and_computed_evidence(review_workbook):
    metadata, _ = extract_excel_accessibility_metadata(review_workbook, ".xlsx")
    report = {"document": {"id": "doc", "file_name": "review.xlsx"}, "accessibility_metadata": metadata}
    native = {
        "evidence_envelopes": [{"document_id": "doc", "status": "completed", "summary": "native", "citations": []}],
        "agent_citations": [{"function_name": "get_document_accessibility_report",
                             "function_arguments": {"document_id": "doc"}, "function_result": report}],
    }
    computed = {
        "evidence_envelopes": [{"document_id": "doc", "status": "completed",
                              "summary": "Computed total cap = 36000.", "coverage": {}, "citations": []}],
        "agent_citations": [],
    }
    merged = excel.merge_excel_native_evidence(computed, native, "Calculate total cap and list comments")
    text = merged["evidence_envelopes"][0]["summary"]
    assert "Set cap to 19500." in text
    assert "Computed total cap = 36000." in text
    assert len(text.encode("utf-8")) <= 16384
    assert computed["evidence_envelopes"][0]["summary"] == "Computed total cap = 36000."
