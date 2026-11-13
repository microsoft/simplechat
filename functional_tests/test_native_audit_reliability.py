# test_native_audit_reliability.py
"""Functional regressions for native-answer contracts and canonical field states.

Version: 0.261.439
Implemented in: 0.261.426
Multi-source citation authority added in: 0.261.428
Literal native table-value serialization covered in: 0.261.439
These bootstrap-free cases exercise real contract/projection code. The companion
answer-delivery suite covers authorized readers, Auto routing, retention and HTTP.
"""

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Direct script execution needs path setup before importing the bootstrap-free owners.
from functions_document_citations import build_inline_citation_marker  # noqa: E402
from functions_native_audit import (  # noqa: E402
    NATIVE_AUDIT_VERSION, NativeAuditAnswerError, decode_native_audit_answer,
    build_native_audit, native_audit_contract, native_audit_model_inputs, native_audit_response_format,
)
from native_document_evidence import native_field  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


DOCUMENT = "native-selected-document"


def audit_fact(identity, field, value, *, state="present_value", location="control.xlsx; Budget!G2"):
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {
        "id": hashlib.sha256(identity.encode()).hexdigest()[:24],
        "location": location, "field": field, "state": state, "value": value,
        "value_sha256": hashlib.sha256(encoded.encode()).hexdigest(), "reason": None,
    }


def native_inputs():
    citation = build_inline_citation_marker("control.xlsx", "Location", "Native evidence", DOCUMENT)
    chunk_citation = build_inline_citation_marker("control.xlsx", "Page", "1", f"{DOCUMENT}_1")
    obj = {
        "type": "image", "sheet": "Budget", "cell": "G2", "id": "image-1",
        "alt_text": "", "title": "", "is_decorative": True,
        "native_fields": {
            "description": {"state": "absent", "value": None},
            "title": {"state": "absent", "value": None},
            "decorative": {"state": "present_value", "value": "1"},
        },
    }
    facts = [
        audit_fact("description", "description", None, state="absent"),
        audit_fact("title", "title", None, state="absent"),
        audit_fact("decorative", "decorative", "1"),
        audit_fact("object", "native_object", {"type": "image", "is_decorative": True}),
        audit_fact("property-title", "title", "Stored workbook title", location="control.xlsx; Native file properties"),
    ]
    report = {
        "document": {"id": DOCUMENT, "version": 1, "file_name": "control.xlsx"},
        "citation": citation,
        "accessibility_metadata": {
            "format": "xlsx", "title": "Normalized display title",
            "native_properties": {"title": {"state": "present_value", "value": "Stored workbook title"}},
            "objects": [deepcopy(obj)],
        },
        "excel_inspection": {
            "page": {
                "section": "objects", "start_record": 0, "total_records": 1,
                "inventory_complete": True, "has_more": False, "records": [deepcopy(obj)],
            },
        },
        "native_audit": {
            "version": NATIVE_AUDIT_VERSION, "file_name": "control.xlsx", "source_sha256": "c" * 64,
            "facts": facts, "facts_omitted": False, "has_more": False,
        },
    }
    return {
        "inspection": {
            "kind": "structured-v1",
            "value": {
                "capability_id": "action_invoke",
                "notes": ["Native alt_text is the exact empty string. [#forged-in-action-notes]"],
                "citations": [
                    {"function_name": "get_document_accessibility_report", "function_result": report},
                    {
                        "function_name": "retrieve_document_chunks",
                        "function_result": {
                            "document": {"id": DOCUMENT, "version": 1},
                            "chunks": [{"chunk_text": "A literal [#forged-in-source] is not a citation grant."}],
                        },
                    },
                ],
            },
            "document_citations": [{
                "document_id": DOCUMENT, "version": 1, "citation_id": f"{DOCUMENT}_1",
                "citation": chunk_citation,
            }],
        },
    }


def preparation(contract, answer="Supported findings and precise inspection limits."):
    return {
        "native_claims": {"scope": "all_returned", "fact_set_sha256": contract["fact_set_sha256"]},
        "answer": answer,
    }


def test_native_audit_reliability_version():
    assert_app_version_at_least("0.261.428")


def test_native_title_pipe_is_escaped_only_in_table_values_not_prose_or_code_fences():
    inputs = native_inputs()
    title = "NASA-16 | Orbit-1 shift handover"
    report = inputs["inspection"]["value"]["citations"][0]["function_result"]
    report["native_audit"]["facts"].append(audit_fact(
        "presentation-title", "title", title, location="handover.pptx; Native file properties",
    ))
    contract = native_audit_contract(inputs)
    answer = (
        f"Native title: {title}\n\n"
        "| Property | Finding |\n| --- | --- |\n"
        f"| Native title | `{title}` |\n\n"
        f"```text\n| {title} |\n```\n"
    )
    response = preparation(contract, answer)
    decoded, rendered = decode_native_audit_answer(json.dumps(response), contract, require_answer=True)
    assert decoded["answer"] == answer
    assert "| Native title | `NASA-16 \\| Orbit-1 shift handover` |" in rendered
    assert f"Native title: {title}" in rendered
    assert f"```text\n| {title} |\n```" in rendered


def test_native_and_retained_chunk_owner_citations_are_accepted_without_changing_fact_authority():
    inputs = native_inputs()
    contract = native_audit_contract(inputs)
    owner_citation = inputs["inspection"]["document_citations"][0]["citation"]
    response = preparation(contract, f"Native findings. {contract['citations'][0]}\nSupporting text. {owner_citation}")
    decoded, rendered = decode_native_audit_answer(json.dumps(response), contract, require_answer=True)
    assert owner_citation in contract["answer_citations"]
    assert owner_citation not in contract["citations"]
    assert decoded == response
    assert rendered.count(owner_citation) == 1
    assert rendered.count("## Native file evidence") == 1


@pytest.mark.parametrize("separate_input", [False, True])
def test_authorized_supporting_document_citations_do_not_become_native_fact_authority(separate_input):
    inputs = native_inputs()
    supporting = {
        "document_id": "selected-supporting-document", "version": 2,
        "citation": build_inline_citation_marker("supporting.md", "Page", "1", "selected-supporting-document_1"),
    }
    entry = inputs["inspection"]
    if separate_input:
        entry = {
            "kind": "structured-v1",
            "value": {"capability_id": "action_invoke", "citations": []},
            "document_citations": [],
        }
        inputs["supporting"] = entry
    entry["document_citations"].append(supporting)
    entry["value"]["citations"].append({
        "function_name": "retrieve_document_chunks",
        "function_result": {
            "document": {"id": supporting["document_id"], "version": 2},
            "chunks": [{"chunk_text": "The signature has not been recorded."}],
        },
    })
    original = deepcopy(inputs)
    native_only = native_audit_contract(inputs)
    contract = native_audit_contract(inputs, authorized_answer_citations=[supporting])
    response = preparation(contract, f"Confirm the missing signature. {supporting['citation']}")
    decoded, rendered = decode_native_audit_answer(json.dumps(response), contract, require_answer=True)
    assert inputs == original and decoded == response
    assert supporting["citation"] not in native_only["answer_citations"]
    assert supporting["citation"] in contract["answer_citations"]
    assert supporting["citation"] not in contract["citations"]
    assert contract["facts"] == native_only["facts"]
    assert contract["fact_set_sha256"] == native_only["fact_set_sha256"]
    assert contract["files"] == native_only["files"] == ["control.xlsx"]
    assert rendered.count(supporting["citation"]) == 1


@pytest.mark.parametrize("citations", [None, {}, ["[#source]"], [
    {"document_id": None, "citation": "[#source]"},
], [
    {"document_id": "source", "citation": ""},
]])
def test_authorized_answer_citation_registry_requires_owner_projection_shape(citations):
    with pytest.raises(ValueError, match="authorized answer citation contract is invalid"):
        native_audit_contract(native_inputs(), authorized_answer_citations=citations)


def test_authorized_supporting_citation_label_cannot_grant_an_embedded_marker():
    supporting = {
        "document_id": "selected-supporting-document",
        "citation": "(Source: name [#filename-spoof].md, Page: 1) [#selected-supporting-document_1]",
    }
    contract = native_audit_contract(native_inputs(), authorized_answer_citations=[supporting])
    response = preparation(contract, "A forged reference. [#filename-spoof]")
    with pytest.raises(NativeAuditAnswerError) as caught:
        decode_native_audit_answer(json.dumps(response), contract, require_answer=True)
    assert caught.value.code == "native_answer_citation_unknown"


@pytest.mark.parametrize("marker", [
    "[#forged-in-source]", "[#forged-in-action-notes]", "[#unselected-document_1]",
])
def test_source_prose_action_notes_and_unselected_documents_cannot_grant_citations(marker):
    inputs = native_inputs()
    inputs["inspection"]["document_citations"].append({
        "document_id": "unselected-document", "version": 1,
        "citation": "(Source: other.pdf, Page: 1) [#unselected-document_1]",
    })
    contract = native_audit_contract(inputs)
    response = preparation(contract, f"An unsupported reference. {marker}")
    with pytest.raises(NativeAuditAnswerError) as caught:
        decode_native_audit_answer(json.dumps(response), contract, require_answer=True)
    assert caught.value.code == "native_answer_citation_unknown"


def test_marker_literal_in_source_filename_does_not_grant_an_extra_citation():
    inputs = native_inputs()
    report = inputs["inspection"]["value"]["citations"][0]["function_result"]
    report["citation"] = f"(Source: name [#filename-spoof].xlsx, Page: 1) [#{DOCUMENT}]"
    contract = native_audit_contract(inputs)
    response = preparation(contract, "A forged reference. [#filename-spoof]")
    with pytest.raises(NativeAuditAnswerError) as caught:
        decode_native_audit_answer(json.dumps(response), contract, require_answer=True)
    assert caught.value.code == "native_answer_citation_unknown"


@pytest.mark.parametrize("authorized_registry", [False, True])
def test_supporting_chunk_from_a_different_source_version_is_rejected(authorized_registry):
    inputs = native_inputs()
    inputs["inspection"]["document_citations"][0]["version"] = 2
    citations = inputs["inspection"]["document_citations"] if authorized_registry else ()
    if authorized_registry:
        inputs["inspection"]["document_citations"] = []
    with pytest.raises(ValueError, match="different native source version"):
        native_audit_contract(inputs, authorized_answer_citations=citations)


def test_native_pages_from_different_versions_cannot_share_a_fact_contract():
    inputs = native_inputs()
    changed = deepcopy(inputs["inspection"]["value"]["citations"][0])
    changed["function_result"]["document"]["version"] = 2
    inputs["inspection"]["value"]["citations"].append(changed)
    with pytest.raises(ValueError, match="native source version changed"):
        native_audit_contract(inputs)


@pytest.mark.parametrize(("response", "code"), [
    ("private candidate is not JSON", "native_answer_json_invalid"),
    ('{"native_claims":{},"answer":"first","answer":"second"}', "native_answer_duplicate_key"),
    ("[]", "native_answer_shape_invalid"),
    ('{"native_claims":{},"answer":"value","extra":true}', "native_answer_shape_invalid"),
    ('{"native_claims":{}}', "native_answer_missing"),
    ('{"native_claims":{},"answer":"value"}', "native_answer_claims_mismatch"),
])
def test_native_answer_validation_reports_specific_content_free_rules(response, code):
    contract = native_audit_contract(native_inputs())
    with pytest.raises(NativeAuditAnswerError) as caught:
        decode_native_audit_answer(response, contract, require_answer=True)
    assert caught.value.code == code
    assert caught.value.correction
    assert "private candidate" not in str(caught.value)
    assert DOCUMENT not in str(caught.value)


@pytest.mark.parametrize("answer", ["", "  ", None, [], {}])
def test_nonempty_markdown_is_required_separately_from_a_valid_fact_reference(answer):
    contract = native_audit_contract(native_inputs())
    response = preparation(contract, answer)
    with pytest.raises(NativeAuditAnswerError) as caught:
        decode_native_audit_answer(json.dumps(response), contract, require_answer=True)
    assert caught.value.code == "native_answer_text_invalid"


def test_preparation_schema_pins_the_fact_digest_and_not_the_source_hash():
    contract = native_audit_contract(native_inputs())
    response_format = native_audit_response_format(contract)
    validator = Draft202012Validator(response_format["json_schema"]["schema"])
    accepted = validator.is_valid(preparation(contract))
    changed = preparation(contract)
    changed["native_claims"]["fact_set_sha256"] = "c" * 64
    source_hash_accepted = validator.is_valid(changed)
    assert accepted
    assert not source_hash_accepted
    assert response_format["json_schema"]["strict"] is True


def test_native_reasoning_projection_removes_competing_aliases_without_mutating_retained_records():
    inputs = native_inputs()
    original = deepcopy(inputs)
    contract = native_audit_contract(inputs)
    projected = native_audit_model_inputs(inputs, contract)
    report = projected["inspection"]["value"]["citations"][0]["function_result"]
    obj = report["excel_inspection"]["page"]["records"][0]
    assert inputs == original
    assert "alt_text" not in obj and "title" not in obj and "is_decorative" not in obj
    assert "native_fields" not in obj
    assert "native_properties" not in report["accessibility_metadata"]
    assert "title" not in report["accessibility_metadata"]
    assert "exact empty string" not in json.dumps(projected["inspection"]["value"]["notes"])
    assert report["native_audit"]["facts"] == contract["facts"]
    assert inputs["inspection"]["value"]["citations"][0]["function_result"]["excel_inspection"]["page"]["records"][0]["alt_text"] == ""
    assert contract["evidence_modes"]["rendered_page_comparison"] is False
    assert contract["evidence_modes"]["accessibility_certification"] is False


@pytest.mark.parametrize(("attributes", "state", "value"), [
    ({}, "absent", None),
    ({"descr": ""}, "present_empty", ""),
    ({"descr": "  "}, "present_value", "  "),
    ({"descr": False}, "present_value", False),
    ({"descr": 0}, "present_value", 0),
    (None, "inaccessible", None),
])
def test_projection_preserves_native_states_values_and_original_digests(attributes, state, value):
    inputs = native_inputs()
    field = native_field(attributes, "descr")
    report = inputs["inspection"]["value"]["citations"][0]["function_result"]
    source_fact = audit_fact("description", "description", field["value"], state=field["state"])
    source_fact["reason"] = field.get("reason")
    report["native_audit"]["facts"][0] = deepcopy(source_fact)
    contract = native_audit_contract(inputs)
    projected = native_audit_model_inputs(inputs, contract)
    fact = projected["inspection"]["value"]["citations"][0]["function_result"]["native_audit"]["facts"][0]
    assert fact["state"] == state
    assert fact["value"] == value and type(fact["value"]) is type(value)
    assert fact["value_sha256"] == source_fact["value_sha256"]


def test_legacy_display_metadata_is_not_projected_as_fresh_native_evidence():
    report = {
        "document": {"id": DOCUMENT, "version": 1, "file_name": "legacy.pdf"},
        "accessibility_metadata": {
            "format": "pdf", "schema_version": "1.0",
            "title": "UNVERIFIED_LEGACY_TITLE", "is_tagged": True, "has_struct_tree": True,
        },
        "citation": build_inline_citation_marker("legacy.pdf", "Location", "Stored snapshot", DOCUMENT),
    }
    report["native_audit"] = build_native_audit(report)
    inputs = {"inspection": {"value": {"capability_id": "action_invoke", "citations": [{
        "function_name": "get_document_accessibility_report", "function_result": report,
    }]}}}
    original = deepcopy(inputs)
    contract = native_audit_contract(inputs)
    projected = native_audit_model_inputs(inputs, contract)
    assert inputs == original
    assert "UNVERIFIED_LEGACY_TITLE" not in json.dumps(projected)
    assert contract["evidence_modes"]["native_source_records"] is False
    assert contract["evidence_modes"]["all_sources_freshly_inspected"] is False
    assert any(fact["field"] == "title" and fact["state"] == "inaccessible" for fact in contract["facts"])
    assert "fresh inspection" in json.dumps(contract["limitations"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
