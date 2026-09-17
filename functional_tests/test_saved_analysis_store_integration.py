# test_saved_analysis_store_integration.py
"""
Functional tests for saved Analyze helpers with the real shared result store.
Version: 0.261.109
Implemented in: 0.261.109

Cosmos/Blob SDK doubles verify pre-message orchestration loading, source access,
snapshot integrity, and public record/evidence projections without live services.
"""

from copy import deepcopy
import json

from azure.cosmos.exceptions import CosmosResourceNotFoundError
import pytest

from test_saved_analysis_service import saved
from test_workflow_result_store import FakeBlobService, FakeCosmosContainer, store_module


SOURCE = {
    "document_id": "document-1", "scope": "personal", "scope_id": "owner",
    "source_version": "1", "source_revision": "etag-1", "authorization_status": "authorized",
}


def analysis_result(count=121, validation="valid"):
    return {
        "reply": "Accepted findings from the saved result.",
        "analysis_result": {
            "analysis_result_version": "analyze-final-v1",
            "analysis_sources": [deepcopy(SOURCE)],
            "authoritative_result": {"kind": "records", "value": [{
                "record_id": f"record-{index}", "document_id": SOURCE["document_id"],
                "source": {"file_name": "controls.txt"},
                "values": {"finding": f"Control {index} needs an owner."},
                "evidence_refs": [f"evidence-{index}"],
            } for index in range(count)]},
            "analysis_evidence": [{
                "evidence_id": f"evidence-{index}", "document_id": SOURCE["document_id"],
                "source": {"file_name": "controls.txt"}, "work_unit_ids": ["window-1"],
                "location": {"page_number": index + 1, "chunk_id": f"chunk-{index}"},
                "text": "Owner: unassigned",
            } for index in range(count)],
            "analysis_validation": {"status": validation},
        },
    }


@pytest.fixture(params=["cosmos", "blob"])
def sdk_store(request):
    container = FakeCosmosContainer()
    blobs = FakeBlobService() if request.param == "blob" else None
    return store_module.WorkflowResultStore(
        container, blobs, "personal-chat" if blobs else None, chunk_size_bytes=2048,
    )


def resolve_sources(document_ids, **kwargs):
    return [deepcopy(SOURCE) for _ in document_ids]


def authorize_run(user_id, binding):
    assert user_id == "owner"
    assert binding == {
        "kind": "orchestration", "user_id": "owner", "conversation_id": "conversation-1",
        "run_id": "real-run", "step_id": "analyze-step",
    }


def save_orchestration(store, result=None):
    return saved.save_orchestration_analysis(
        result or analysis_result(), user_id="owner", conversation_id="conversation-1",
        run_id="real-run", step_id="analyze-step", authorize_run=authorize_run,
        save_result=lambda *args, **kwargs: store.save_orchestration(*args),
        source_resolver=resolve_sources,
    )


def save_chat(store, result):
    descriptor = saved.save_chat_analysis(
        result, user_id="owner", conversation_id="conversation-1", message_id="assistant-1",
        authorize_conversation=lambda *args: True,
        save_result=lambda *args, **kwargs: store.save_chat(*args), source_resolver=resolve_sources,
    )
    message = {
        "id": "assistant-1", "conversation_id": "conversation-1", "role": "assistant",
        "metadata": {"saved_analysis": descriptor},
    }
    return descriptor, {
        "message_loader": lambda *args: message, "chat_loader": store.load_chat,
        "source_resolver": resolve_sources,
    }


def test_orchestration_can_reload_before_any_assistant_message_exists(sdk_store):
    descriptor = save_orchestration(sdk_store)
    reloaded = store_module.WorkflowResultStore(
        sdk_store.container, sdk_store.blob_client, sdk_store.blob_container_name,
    )
    text, consumed = saved.load_orchestration_analysis_input(
        "owner", descriptor, authorize_run=authorize_run,
        load_result=reloaded.load_orchestration, source_resolver=resolve_sources,
    )
    payload = json.loads(text)
    assert payload["records"] == analysis_result()["analysis_result"]["authoritative_result"]["value"]
    assert len(payload["evidence"]) == 121
    assert payload["original_sources_reanalyzed"] is False
    assert payload["saved_analysis"] == {
        "producer": descriptor["binding"], "result_sha256": descriptor["result_sha256"],
    }
    assert consumed == descriptor
    assert "message_id" not in descriptor


def test_orchestration_authorization_precedes_result_reads(sdk_store):
    descriptor = save_orchestration(sdk_store)

    def deny(*args):
        raise PermissionError("Not permitted.")

    with pytest.raises(PermissionError):
        saved.load_orchestration_analysis_input(
            "owner", descriptor, authorize_run=deny,
            load_result=lambda *args: pytest.fail("Unauthorized result read."),
            source_resolver=resolve_sources,
        )


@pytest.mark.parametrize("field,value", [("user_id", "other"), ("step_id", "other-step")])
def test_orchestration_identity_cannot_retarget_saved_bytes(sdk_store, field, value):
    descriptor = save_orchestration(sdk_store)
    descriptor["binding"][field] = value
    with pytest.raises((PermissionError, ValueError, LookupError, CosmosResourceNotFoundError)):
        saved.load_orchestration_analysis_input(
            "owner", descriptor, authorize_run=lambda *args: True,
            load_result=sdk_store.load_orchestration, source_resolver=resolve_sources,
        )


def test_orchestration_source_revocation_blocks_pre_message_reuse(sdk_store):
    descriptor = save_orchestration(sdk_store)
    reads = []

    def load(*args):
        reads.append(args[-1]["sha256"])
        return sdk_store.load_orchestration(*args)

    with pytest.raises(PermissionError):
        saved.load_orchestration_analysis_input(
            "owner", descriptor, authorize_run=authorize_run, load_result=load,
            source_resolver=lambda *args, **kwargs: [{**SOURCE, "authorization_status": "unresolved"}],
        )
    assert reads == [descriptor["result_sha256"]]


def test_evidence_projection_preserves_the_canonical_nested_evidence(sdk_store):
    descriptor, options = save_chat(sdk_store, analysis_result())
    context = saved.saved_analysis_context(descriptor)
    page = saved.read_saved_analysis_page(
        "owner", context, representation="evidence", record_id="record-120", **options,
    )
    evidence = page["evidence"][0]
    assert evidence["file_name"] == "controls.txt"
    assert evidence["page_number"] == 121
    assert evidence["chunk_id"] == "chunk-120"
    text, _ = saved.load_saved_analysis_input("owner", context, **options)
    original = json.loads(text)["evidence"][-1]
    assert "file_name" not in original
    assert original["source"]["file_name"] == evidence["file_name"]
    assert original["text"] == evidence["text"]


@pytest.mark.parametrize("status", ["not_requested", "unknown_check", None])
def test_public_validation_never_promotes_unknown_checks(sdk_store, status):
    descriptor, options = save_chat(sdk_store, analysis_result(validation=status))
    page = saved.read_saved_analysis_page("owner", saved.saved_analysis_context(descriptor), **options)
    assert descriptor["validation_status"] == page["validation"]["status"] == "not_validated"


@pytest.mark.parametrize("kind,value", [("text", "Final narrative."), ("json", {"finding": "Final finding."})])
def test_native_text_and_json_have_explicit_readable_record_shapes(sdk_store, kind, value):
    result = analysis_result()
    result["analysis_result"]["authoritative_result"] = {"kind": kind, "value": value}
    descriptor, options = save_chat(sdk_store, result)
    page = saved.read_saved_analysis_page("owner", saved.saved_analysis_context(descriptor), **options)
    assert page["total_records"] == descriptor["record_count"] == 1
    record = page["records"][0]
    assert record["document_id"] == SOURCE["document_id"]
    assert record["source"]["scope"] == "personal"
    assert isinstance(record["values"], dict)
    assert record["evidence_refs"] == []
    assert saved.read_saved_analysis_page(
        "owner", saved.saved_analysis_context(descriptor),
        representation="evidence", record_id=record["record_id"], **options,
    )["evidence"] == []


def test_public_page_bounds_include_json_unicode_and_metadata(sdk_store, monkeypatch):
    result = analysis_result(count=2)
    for row in result["analysis_result"]["authoritative_result"]["value"]:
        row["values"]["finding"] = "\U0001f600" * 80
    descriptor, options = save_chat(sdk_store, result)
    monkeypatch.setattr(saved, "MAX_ANALYSIS_PAGE_BYTES", 1900)
    page = saved.read_saved_analysis_page("owner", saved.saved_analysis_context(descriptor), **options)
    assert len(page["records"]) == 1
    assert page["next_offset"] == 1
    assert saved._analysis_response_size(page) <= saved.MAX_ANALYSIS_PAGE_BYTES


def test_empty_result_remains_readable_with_integer_counts(sdk_store):
    descriptor, options = save_chat(sdk_store, analysis_result(count=0))
    page = saved.read_saved_analysis_page("owner", saved.saved_analysis_context(descriptor), **options)
    assert descriptor["record_count"] == page["total_records"] == 0
    assert page["records"] == []
    assert page["next_offset"] is None
