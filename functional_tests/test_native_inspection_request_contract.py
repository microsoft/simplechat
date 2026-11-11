# test_native_inspection_request_contract.py
"""Native inspection requests, bounded all-section paging and safe diagnostics.

Version: 0.261.425
Implemented in: 0.261.425
Real native readers and the existing private artifact store run offline. Missing
data remains evidence; invalid requests and stale sources remain genuine errors.
"""

import base64
import hashlib
import json
from copy import deepcopy

import pytest

from content_screening.contracts import Subject
from functions_excel_inventory import (
    EXCEL_INVENTORY_FIELD, EXCEL_INVENTORY_SECTION_ORDER,
    ExcelInventoryWriter, open_excel_inventory, open_stored_excel_inventory,
)
from functions_native_audit import (
    build_native_audit, decode_native_audit_answer, native_audit_contract, validate_native_audit_claims,
)
from functions_native_document_inspection import inspect_native_document
from native_document_evidence import NativeInspectionRequestError
from test_excel_inventory_persistence import inventory_store
from test_native_document_fidelity import native_source


__all__ = ["inventory_store", "native_source"]


def inventory_records(reader, section, *, max_bytes=4096, page_size=2):
    records, pieces, cursor = [], "", None
    for _ in range(1000):
        page = reader.page(section, cursor=cursor, page_size=page_size, max_bytes=max_bytes)
        encoded = json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()
        assert len(encoded) <= max_bytes
        assert len(page["records"]) <= page_size
        for record in page["records"]:
            if record.get("record_fragment"):
                assert record["fragment_offset"] == len(pieces)
                pieces += record["record_json_fragment"]
                if len(pieces) == record["record_characters"]:
                    records.append(json.loads(pieces))
                    pieces = ""
            else:
                assert not pieces
                records.append(record)
        cursor = page["next_cursor"]
        if cursor is None:
            assert not page["has_more"]
            assert not pieces
            return records, page
    raise AssertionError("Native inventory continuation did not terminate.")


@pytest.mark.parametrize("name", ["SC-C08.xlsx", "SC-C11.xlsx"])
@pytest.mark.parametrize("max_bytes", [2048, 4096, 14000])
def test_excel_all_is_the_complete_ordered_union_of_supported_sections(
    native_source, inventory_store, name, max_bytes,
):
    path = native_source(name)
    data = path.read_bytes()
    store, _ = inventory_store
    checks = []
    reader = open_excel_inventory(
        {"id": "workbook", "user_id": "owner", "version": 1},
        data, ".xlsx", storage=store, authorize=lambda: checks.append("checked"),
    )
    expected = []
    for section in EXCEL_INVENTORY_SECTION_ORDER:
        selected, _ = inventory_records(reader, section)
        expected.extend({**record, "inventory_section": section} for record in selected)
    actual, last = inventory_records(reader, "all", max_bytes=max_bytes)
    assert actual == expected
    assert len(actual) == sum(last["section_counts"].values()) == last["total_records"]
    assert list(last["section_counts"]) == list(EXCEL_INVENTORY_SECTION_ORDER)
    assert last["inventory_complete"] is True
    assert checks
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()
    objects = [record for record in actual if record["inventory_section"] == "objects"]
    chart = next(record for record in objects if record["type"] == "chart")
    assert chart["native_fields"]["description"]["state"] == "absent"
    if name == "SC-C11.xlsx":
        controls = [record for record in objects if record.get("control_representation") == "in_cell"]
        assert len(controls) == 1 and controls[0]["cell"] == "D3"
        assert controls[0]["checked"] is True


def test_excel_all_fragments_preserve_unicode_and_section_identity(inventory_store):
    store, _ = inventory_store
    subject = Subject("personal", "owner", "workbook", "1")
    writer = ExcelInventoryWriter(store, subject, "a" * 64)
    text = ('review "\\\\ quote ' + chr(0x03B1) + "\n") * 1800 + "TAIL"
    writer.add("comments", {"id": "comment", "sheet": "Budget", "cell": "B4", "text": text})
    writer.add("objects", {"id": "shape", "sheet": "Budget", "cell": "D3", "type": "checkbox"})
    reference = writer.finish({"format": "xlsx", "sheet_count": 0, "scanned_sheet_count": 0})
    reader = open_stored_excel_inventory(
        {"id": "workbook", "user_id": "owner", "version": 1, EXCEL_INVENTORY_FIELD: reference},
        storage=store, authorize=lambda: None,
    )
    records, page = inventory_records(reader, "all", max_bytes=2048)
    assert records == [
        {"id": "comment", "sheet": "Budget", "cell": "B4", "text": text, "inventory_section": "comments"},
        {"id": "shape", "sheet": "Budget", "cell": "D3", "type": "checkbox", "inventory_section": "objects"},
    ]
    assert page["section_counts"]["comments"] == page["section_counts"]["objects"] == 1
    source_records = []
    fragment = reader.page("all", max_bytes=2048, _audit_records=source_records)
    assert fragment["records"][0]["record_fragment"] is True
    assert source_records[0]["text"] == text


def test_empty_all_inventory_is_an_explicit_empty_inspection(inventory_store):
    store, _ = inventory_store
    subject = Subject("personal", "owner", "empty", "1")
    writer = ExcelInventoryWriter(store, subject, "b" * 64)
    reference = writer.finish({"format": "xlsx", "sheet_count": 0, "scanned_sheet_count": 0})
    reader = open_stored_excel_inventory(
        {"id": "empty", "user_id": "owner", "version": 1, EXCEL_INVENTORY_FIELD: reference},
        storage=store, authorize=lambda: None,
    )
    records, page = inventory_records(reader, "all", max_bytes=2048)
    assert records == []
    assert page["total_records"] == 0 and page["inventory_complete"] is True
    assert all(count == 0 for count in page["section_counts"].values())


def test_all_continuations_remain_source_section_and_permission_bound(native_source, inventory_store):
    store, _ = inventory_store
    allowed = [True]

    def authorize():
        if not allowed[0]:
            raise PermissionError("Source access revoked.")

    reader = open_excel_inventory(
        {"id": "workbook", "user_id": "owner", "version": 1},
        native_source("SC-C11.xlsx").read_bytes(), ".xlsx", storage=store, authorize=authorize,
    )
    page = reader.page("all", page_size=1)
    with pytest.raises(NativeInspectionRequestError) as changed:
        reader.page("objects", cursor=page["next_cursor"])
    assert changed.value.code == "native_cursor_source_changed"
    assert changed.value.validation_rule == "native_cursor_section_changed"
    allowed[0] = False
    with pytest.raises(PermissionError, match="revoked"):
        reader.page("all", cursor=page["next_cursor"])


def change_cursor(token, **changes):
    value = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    value.update(changes)
    return base64.urlsafe_b64encode(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).decode().rstrip("=")


@pytest.mark.parametrize("mutation,code,rule", [
    ({"revision": "different-revision"}, "native_cursor_source_changed", "native_cursor_revision_changed"),
    ({"source_sha256": "0" * 64}, "native_cursor_source_changed", "native_cursor_source_sha256_changed"),
    ({"section": "objects"}, "native_cursor_source_changed", "native_cursor_section_changed"),
    ({"offset": 999999}, "native_cursor_out_of_range", None),
    ({"offset": 0, "fragment": 999999}, "native_cursor_fragment_invalid", None),
    ({"offset": -1}, "native_cursor_invalid", None),
])
def test_pdf_cursor_failure_identifies_the_actual_invariant(native_source, mutation, code, rule):
    data = native_source("SC-C04.pdf").read_bytes()
    document = {"id": "selected-source", "version": 1, "_etag": "revision-1"}
    first = inspect_native_document(document, data, ".pdf", page_size=1)
    token = change_cursor(first["page"]["next_cursor"], **mutation)
    with pytest.raises(NativeInspectionRequestError) as failure:
        inspect_native_document(document, data, ".pdf", cursor=token)
    assert failure.value.code == code
    assert failure.value.validation_rule == rule
    assert failure.value.argument_field == "native_cursor"
    assert token not in str(failure.value)
    assert "revision-1" not in str(failure.value)


@pytest.mark.parametrize("arguments,code", [
    ({"section": "not-a-section"}, "native_section_invalid"),
    ({"page_size": True}, "native_page_size_invalid"),
    ({"page_size": 201}, "native_page_size_invalid"),
    ({"max_bytes": 2047}, "native_response_budget_invalid"),
    ({"cursor": "not-a-native-cursor"}, "native_cursor_invalid"),
])
def test_native_request_errors_are_not_empty_successes(native_source, arguments, code):
    data = native_source("SC-C03.pdf").read_bytes()
    with pytest.raises(NativeInspectionRequestError) as failure:
        inspect_native_document({"id": "source"}, data, ".pdf", **arguments)
    assert failure.value.code == code


def test_native_audit_coverage_requires_a_contiguous_completed_page_chain(native_source):
    data = native_source("SC-C03.pdf").read_bytes()
    document = {"id": "source", "file_name": "SC-C03.pdf", "_etag": "revision-1"}
    citations, cursor = [], None
    for size in (1, 1, 200):
        inspected = inspect_native_document(document, data, ".pdf", cursor=cursor, page_size=size, max_bytes=65536)
        result = {
            "document": document, "accessibility_metadata": inspected["metadata"],
            "native_inspection": {"page": inspected["page"]}, "citation": "[#native-source]",
        }
        result["native_audit"] = build_native_audit(result)
        citations.append({"function_name": "get_document_accessibility_report", "function_result": result})
        cursor = inspected["page"]["next_cursor"]
    assert cursor is None

    def contract_for(selected):
        return native_audit_contract({"native": {"value": {
            "capability_id": "action_invoke", "citations": selected,
        }}})

    complete = contract_for(citations)
    duplicate = contract_for([*citations, deepcopy(citations[0])])
    gap = contract_for([citations[0], citations[2]])
    assert not any("continuation" in text for text in complete["limitations"])
    assert not any("continuation" in text for text in duplicate["limitations"])
    assert any("continuation" in text for text in gap["limitations"])
    assert complete["inventory_coverage"][0]["returned_chain_complete"] is True
    assert gap["inventory_coverage"][0]["returned_chain_complete"] is False


def test_native_object_facts_use_owned_records_before_preview_or_fragment_transport(native_source):
    data = native_source("SC-C10-R3.pptx").read_bytes()
    document = {"id": "source", "file_name": "SC-C10-R3.pptx", "_etag": "revision-1"}
    citations, cursor, fragments = [], None, 0
    for _ in range(500):
        source_records = []
        inspected = inspect_native_document(
            document, data, ".pptx", cursor=cursor, page_size=1, max_bytes=2048,
            _audit_records=source_records,
        )
        metadata = deepcopy(inspected["metadata"])
        for obj in (metadata.get("objects_summary") or {}).get("items", []):
            obj["native_fields"]["description"] = {
                "state": "inaccessible", "value": None, "reason": "native_parent_byte_limit",
            }
        payload = {
            "document": document, "accessibility_metadata": metadata,
            "native_inspection": {"page": inspected["page"]}, "citation": "[#native-source]",
        }
        audit = build_native_audit(payload, _source_records=source_records)
        if any(record.get("record_fragment") for record in inspected["page"]["records"]):
            fragments += 1
            assert source_records
        payload["native_audit"] = audit
        citations.append({"function_name": "get_document_accessibility_report", "function_result": payload})
        cursor = inspected["page"]["next_cursor"]
        if cursor is None:
            break
    else:
        raise AssertionError("Native object paging did not terminate.")
    contract = native_audit_contract({"native": {"value": {
        "capability_id": "action_invoke", "citations": citations,
    }}})
    objects = [fact for fact in contract["facts"] if fact["field"] == "native_object"]
    empty_descriptions = [
        fact for fact in contract["facts"]
        if fact["field"] == "description" and fact["state"] == "present_empty"
    ]
    assert fragments > 0
    assert {str(fact["value"]["object_id"]) for fact in objects} == {str(number) for number in range(2, 10)}
    assert len(empty_descriptions) == 2
    assert not any("continuation" in text for text in contract["limitations"])


def answer_contract():
    result = {
        "document": {"id": "source", "file_name": "selected.pdf"},
        "accessibility_metadata": {
            "format": "pdf", "schema_version": "2.0", "source_sha256": "a" * 64,
            "native_properties": {
                "title": {"state": "absent", "value": None},
                "author": {"state": "present_empty", "value": ""},
            },
        },
        "citation": "(Source: selected.pdf, Page: 1) [#native-source]",
    }
    result["native_audit"] = build_native_audit(result)
    return native_audit_contract({"native": {"value": {
        "capability_id": "action_invoke", "citations": [{
            "function_name": "get_document_accessibility_report", "function_result": result,
        }],
    }}})


def test_customer_answer_and_native_fields_have_separate_validated_roles():
    contract = answer_contract()
    before = deepcopy(contract)
    claims = {"scope": "all_returned", "fact_set_sha256": contract["fact_set_sha256"]}
    answer = "The title is not in the supplied data; the author is stored but empty. [#native-source]"
    preparation, rendered = decode_native_audit_answer(
        json.dumps({"native_claims": claims, "answer": answer}), contract, require_answer=True,
    )
    assert preparation["answer"] == answer
    assert rendered.startswith(answer) and "present_empty" in rendered and "absent" in rendered
    assert contract == before
    legacy = validate_native_audit_claims(json.dumps({"native_claims": claims}), contract)
    assert legacy.startswith("## Native file evidence")
    with pytest.raises(ValueError, match="customer answer"):
        decode_native_audit_answer(json.dumps({"native_claims": claims}), contract, require_answer=True)


@pytest.mark.parametrize("mutation", ["empty", "wrong_hash", "unknown_citation", "extra_values", "duplicate_key"])
def test_native_answer_rejects_invalid_transport_or_source_references(mutation):
    contract = answer_contract()
    value = {
        "native_claims": {"scope": "all_returned", "fact_set_sha256": contract["fact_set_sha256"]},
        "answer": "The provided data has no stored title. [#native-source]",
    }
    if mutation == "empty":
        value["answer"] = ""
    elif mutation == "wrong_hash":
        value["native_claims"]["fact_set_sha256"] = "0" * 64
    elif mutation == "unknown_citation":
        value["answer"] += " [#not-a-selected-source]"
    elif mutation == "extra_values":
        value["native_values"] = {"title": "Invented title"}
    response = json.dumps(value)
    if mutation == "duplicate_key":
        response = response[:-1] + ', "answer": "Another answer"}'
    with pytest.raises(ValueError):
        decode_native_audit_answer(response, contract, require_answer=True)
