# test_native_document_fidelity_pipeline.py
"""Source-backed native evidence, paging, canonical capture and claim contracts.

Version: 0.261.424
Implemented in: 0.261.424
Real parsers and capture/paging/claim code run offline against synthetic sources.
"""

from copy import deepcopy
import hashlib
import io
import json
import zipfile

import pytest

from test_native_document_fidelity import native_source
from test_document_accessibility_report_action import _load_payload_namespace
from content_screening.contracts import Subject
from content_screening.extraction import ExtractionCapture, capture_extraction, publication_chunks
from functions_accessibility import extract_office_accessibility_metadata, extract_pdf_accessibility_metadata
from functions_native_document_inspection import inspect_native_document
from functions_native_audit import (
    build_native_audit, native_audit_contract, render_native_audit, validate_native_audit_claims,
)


__all__ = ["native_source"]


def report_for(path):
    extension = path.suffix
    data = path.read_bytes()
    document = {"id": "synthetic-document", "file_name": path.name, "version": 1, "_etag": "revision-1"}
    if extension in (".pdf", ".pptx"):
        result = inspect_native_document(document, data, extension)
        metadata, inspection = result["metadata"], {"native_inspection": {"page": result["page"]}}
    else:
        metadata, _ = extract_office_accessibility_metadata(str(path), extension)
        metadata["inventory_storage"] = {"source_sha256": hashlib.sha256(data).hexdigest()}
        inspection = {}
    payload = {"document": document, "accessibility_metadata": metadata, **inspection}
    payload["native_audit"] = build_native_audit(payload)
    payload["citation"] = "(Source: synthetic, Page: 1) [#native-synthetic]"
    return payload


@pytest.mark.parametrize("name", ["SC-C03.pdf", "SC-C04.pdf", "SC-C05.pdf", "SC-C09-R3.pptx", "SC-C10-R3.pptx"])
def test_source_bound_pages_continue_and_refuse_changed_identity(native_source, name):
    path = native_source(name)
    data = path.read_bytes()
    document = {"id": "source", "version": 1, "_etag": "etag-1"}
    cursor, values, fragments = None, [], {}
    for _ in range(500):
        result = inspect_native_document(
            document, data, path.suffix, cursor=cursor, page_size=2, max_bytes=2048,
        )
        page = result["page"]
        assert page["inventory_complete"] is True
        assert len(json.dumps(page, ensure_ascii=True).encode()) <= 2048
        for record in page["records"]:
            if record.get("record_fragment"):
                current = fragments.get(record["id"], "")
                assert record["fragment_offset"] == len(current)
                current += record["record_json_fragment"]
                if len(current) == record["record_characters"]:
                    values.append(json.loads(current))
                    fragments.pop(record["id"], None)
                else:
                    fragments[record["id"]] = current
            else:
                values.append(record)
        if cursor is None and page["has_more"]:
            with pytest.raises(ValueError, match="different source"):
                inspect_native_document({**document, "_etag": "etag-2"}, data, path.suffix,
                                        cursor=page["next_cursor"], max_bytes=2048)
        cursor = page["next_cursor"]
        if not cursor:
            break
    else:
        raise AssertionError("Native cursor did not terminate")
    assert not fragments
    assert len(values) == page["total_records"]
    assert len({record["id"] for record in values}) == len(values)


@pytest.mark.parametrize("name", ["SC-C03.pdf", "SC-C09-R3.pptx"])
def test_native_blocks_survive_screened_canonical_capture(native_source, name):
    path = native_source(name)
    capture = ExtractionCapture(Subject("personal", "owner", "synthetic-document", "1"), "scan", name)
    with capture_extraction(capture):
        metadata, details = (
            extract_pdf_accessibility_metadata(str(path)) if path.suffix == ".pdf"
            else extract_office_accessibility_metadata(str(path), path.suffix)
        )
        capture.add_pages([{"page_number": 1, "content": "Rendered body before native enrichment."}])
        capture.add_chunk("This late chunk is intentionally ignored in page mode.", 1)
        capture.completed = True
        units = capture.finish({"keywords": metadata["native_properties"]["keywords"]["value"]})
    native = [unit for unit in units if unit.locator.get("kind") == "native_accessibility"]
    assert native and all(unit.locator["page_number"] == 1 for unit in native)
    assert "Accessibility" in "\n".join(unit.text for unit in native)
    assert metadata["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    keywords = next(unit for unit in units if unit.locator.get("field") == "keywords")
    assert json.loads(keywords.text) == [metadata["native_properties"]["keywords"]["value"]]
    published = publication_chunks(units, 4000)
    assert "Accessibility" in "\n".join(chunk["chunk_text"] for chunk in published)


@pytest.mark.parametrize("name", ["SC-C04.pdf", "SC-C08.xlsx", "SC-C11.xlsx", "SC-C10-R3.pptx"])
def test_final_claims_reference_source_values_not_model_paraphrases(native_source, name):
    payload = report_for(native_source(name))
    inputs = {"native": {"value": {"citations": [{
        "function_name": "get_document_accessibility_report", "function_result": payload,
    }]}}}
    contract = native_audit_contract(inputs)
    identifiers = [fact["id"] for fact in contract["facts"]]
    answer = validate_native_audit_claims(json.dumps({"native_claims": identifiers}), contract)
    assert answer == render_native_audit(contract)
    compact = validate_native_audit_claims(json.dumps({"native_claims": {
        "scope": "all_returned", "fact_set_sha256": contract["fact_set_sha256"],
    }}), contract)
    assert compact == answer
    with pytest.raises(ValueError):
        validate_native_audit_claims(json.dumps({"native_claims": {
            "scope": "all_returned", "fact_set_sha256": "0" * 64,
        }}), contract)
    with pytest.raises(ValueError):
        validate_native_audit_claims("Step 1 comes before Step 2 and the native fields are blank.", contract)
    with pytest.raises(ValueError):
        validate_native_audit_claims(json.dumps({"native_claims": identifiers[::-1]}), contract)
    with pytest.raises(ValueError):
        validate_native_audit_claims(json.dumps({"native_claims": identifiers + ["invented"]}), contract)
    wrong_values = deepcopy(contract["facts"])
    wrong_values[0]["state"] = "present_empty"
    with pytest.raises(ValueError):
        validate_native_audit_claims(json.dumps({"native_claims": wrong_values}), contract)
    if "C04" in name:
        assert answer.index("Step 2: release") < answer.index("Step 1: approve")
        assert "CEDAR / SYNTHETIC / 1" in answer and "vector_groups" in answer
        assert "/Info/Author" in answer and "/Info/Keywords" in answer
    elif "xlsx" in name:
        assert "absent" in answer
        if "C11" in name:
            assert "Budget!D3" in answer and "checkbox" in answer


def test_unavailable_native_documents_are_not_empty_success():
    with pytest.raises(ValueError):
        inspect_native_document({"id": "source"}, b"", ".pdf")
    with pytest.raises(ValueError):
        inspect_native_document({"id": "source"}, b"not a PDF", ".pdf")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("unrelated.xml", "<unrelated/>")
    with pytest.raises(ValueError, match="native presentation"):
        inspect_native_document({"id": "source"}, stream.getvalue(), ".pptx")


def test_redacted_transport_is_inaccessible_not_a_stored_value(native_source):
    payload = report_for(native_source("SC-C08.xlsx"))
    payload["native_audit"]["facts"][0]["value"] = "***REDACTED***"
    contract = native_audit_contract({"native": {"value": {"citations": [{
        "function_name": "get_document_accessibility_report", "function_result": payload,
    }]}}})
    assert contract["facts"][0]["state"] == "inaccessible"
    assert contract["facts"][0]["value"] is None


def test_native_contract_does_not_replace_mixed_research_or_computed_answers(native_source):
    payload = report_for(native_source("SC-C04.pdf"))
    inputs = {
        "native": {"value": {"capability_id": "action_invoke", "citations": [{
            "function_name": "get_document_accessibility_report", "function_result": payload,
        }]}},
        "web": {"value": {"capability_id": "web_search", "evidence": ["Different evidence"]}},
    }
    contract = native_audit_contract(inputs)
    assert contract is None


def test_old_source_metadata_cannot_describe_a_sanitized_active_file():
    document = {
        "id": "source", "file_name": "released.docx",
        "accessibility_metadata": {
            "format": "pdf", "schema_version": "2.0", "source_sha256": "a" * 64,
            "native_properties": {"keywords": {"state": "present_value", "value": "PRIVATE_ORIGINAL_VALUE"}},
        },
        "content_screening": {"active_blob": {"content_hash": "b" * 64}},
    }
    namespace = _load_payload_namespace(document)
    with pytest.raises(LookupError, match="authorized active representation"):
        namespace["get_document_accessibility_payload"]("source", "owner")


def test_literal_placeholder_text_is_not_mistaken_for_transport_redaction(native_source):
    payload = report_for(native_source("SC-C08.xlsx"))
    payload["accessibility_metadata"]["native_properties"]["title"]["value"] = "***REDACTED***"
    payload["native_audit"] = build_native_audit(payload)
    contract = native_audit_contract({"native": {"value": {"citations": [{
        "function_name": "get_document_accessibility_report", "function_result": payload,
    }]}}})
    assert contract["facts"][0]["state"] == "present_value"
    assert contract["facts"][0]["value"] == "***REDACTED***"
