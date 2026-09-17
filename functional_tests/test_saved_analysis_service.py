# test_saved_analysis_service.py
"""
Functional tests for saved Analyze data in chat and follow-up reads.
Version: 0.261.109
Implemented in: 0.261.109

The production result builder/readers use serialized sections and authorized
message/source seams without re-uploading, indexing, or analyzing source files.
"""

import hashlib
import json
from copy import deepcopy

import pytest

from test_support.app_stubs import import_app_module


saved = import_app_module("functions_saved_analysis")
access = import_app_module("functions_analysis_access")


class ChatSections:
    def __init__(self, contents=None):
        self.contents = contents if contents is not None else {}
        self.reads = []

    def save(self, user_id, conversation_id, message_id, section, **kwargs):
        payload = json.dumps(section, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
        self.contents[(user_id, conversation_id, message_id, digest)] = payload
        return {
            "storage": "cosmos", "schema_version": 1, "sha256": digest,
            "size_bytes": len(payload), "chunk_count": 1,
        }

    def load(self, user_id, conversation_id, message_id, reference):
        key = (user_id, conversation_id, message_id, reference["sha256"])
        self.reads.append(key)
        return json.loads(self.contents[key])


@pytest.fixture
def saved_chat():
    source = {
        "document_id": "document-1", "scope": "group", "scope_id": "source-group",
        "source_version": "1", "source_revision": "etag-1", "authorization_status": "authorized",
    }
    state = {"source_allowed": True, "conversation_allowed": True, "resolutions": 0}
    store = ChatSections()
    result = {
        "reply": "The review found controls needing an owner.",
        "analysis_result": {
            "analysis_result_version": "analyze-final-v1",
            "analysis_reply": "## Findings\n\nThe review found controls needing an owner.",
            "source_manifest": [source],
            "authoritative_result": {
                "kind": "records",
                "value": [{
                    "record_id": f"record-{index}", "document_id": "document-1",
                    "source": {"file_name": "controls.txt"},
                    "values": {"control": f"Control {index}", "finding": "Owner unassigned"},
                    "evidence_refs": [f"evidence-{index}"],
                } for index in range(60)],
            },
            "analysis_evidence": [{
                "evidence_id": f"evidence-{index}", "document_id": "document-1",
                "file_name": "controls.txt", "page_number": index + 1, "quote": "Owner: unassigned",
            } for index in range(60)],
            "analysis_validation": {"status": "valid", "limitations": ["Judgments are not independently verified."]},
            "raw_analysis_items": [{"text": "RAW-NOTE-ONLY"}],
        },
    }

    def authorize(user_id, conversation_id):
        if user_id not in ("owner", "reader") or conversation_id != "conversation-1" or not state["conversation_allowed"]:
            raise PermissionError("not allowed")
        return {"id": conversation_id, "user_id": "owner"}

    def source_resolver(document_ids, **context):
        state["resolutions"] += 1
        return [{**source, "authorization_status": "authorized" if state["source_allowed"] else "unresolved"}]

    descriptor = saved.save_chat_analysis(
        result, user_id="owner", conversation_id="conversation-1", message_id="assistant-1",
        authorize_conversation=authorize, save_result=store.save, source_resolver=source_resolver,
    )
    message = {
        "id": "assistant-1", "conversation_id": "conversation-1", "role": "assistant",
        "content": result["reply"], "metadata": {"saved_analysis": descriptor},
        "agent_citations": [{"function_result": "PRIVATE-DERIVED-RESULT"}],
    }

    def message_loader(user_id, conversation_id, message_id):
        authorize(user_id, conversation_id)
        if message_id != "assistant-1":
            raise LookupError("message not found")
        return message

    return {
        "state": state, "store": store, "descriptor": descriptor, "message": message,
        "message_loader": message_loader, "source_resolver": source_resolver,
    }


def read_options(fixture, store=None):
    return {
        "message_loader": fixture["message_loader"],
        "chat_loader": (store or fixture["store"]).load,
        "source_resolver": fixture["source_resolver"],
    }


def test_saved_chat_uses_a_real_chat_identity_and_survives_reload(saved_chat):
    fixture = saved_chat
    reloaded = ChatSections(dict(fixture["store"].contents))
    context = saved.saved_analysis_context(fixture["descriptor"])
    manifest, load, checked = saved.load_saved_analysis("reader", context, **read_options(fixture, reloaded))
    assert manifest["identity"] == {
        "kind": "chat", "user_id": "owner", "conversation_id": "conversation-1", "message_id": "assistant-1",
    }
    assert "workflow_id" not in manifest["identity"]
    assert checked["source_count"] == 1
    assert fixture["descriptor"]["record_count"] == 60
    assert fixture["descriptor"]["result_sha256"] == context["result_sha256"]


def test_page_two_returns_complete_final_records_not_raw_notes(saved_chat):
    fixture = saved_chat
    context = saved.saved_analysis_context(fixture["descriptor"])
    page = saved.read_saved_analysis_page("reader", context, offset=25, limit=25, **read_options(fixture))
    assert [record["record_id"] for record in page["records"]] == [f"record-{index}" for index in range(25, 50)]
    assert page["total_records"] == 60
    assert page["next_offset"] == 50
    assert "RAW-NOTE-ONLY" not in json.dumps(page)


def test_evidence_is_selected_from_the_same_saved_record(saved_chat):
    fixture = saved_chat
    context = saved.saved_analysis_context(fixture["descriptor"])
    page = saved.read_saved_analysis_page(
        "reader", context, representation="evidence", record_id="record-7", **read_options(fixture)
    )
    assert [item["evidence_id"] for item in page["evidence"]] == ["evidence-7"]
    assert page["evidence"][0]["quote"] == "Owner: unassigned"


def test_source_revocation_blocks_record_and_evidence_reads(saved_chat):
    fixture = saved_chat
    fixture["state"]["source_allowed"] = False
    context = saved.saved_analysis_context(fixture["descriptor"])
    for representation in ("records", "evidence"):
        with pytest.raises(access.AnalysisResultUnavailable):
            saved.read_saved_analysis_page(
                "reader", context, representation=representation, record_id="record-0", **read_options(fixture)
            )


def test_conversation_denial_happens_before_result_storage_reads(saved_chat):
    fixture = saved_chat
    fixture["state"]["conversation_allowed"] = False
    context = saved.saved_analysis_context(fixture["descriptor"])
    with pytest.raises(PermissionError):
        saved.read_saved_analysis_page("reader", context, **read_options(fixture))
    assert fixture["store"].reads == []


def test_a_stale_browser_digest_cannot_select_another_result(saved_chat):
    fixture = saved_chat
    context = {**saved.saved_analysis_context(fixture["descriptor"]), "result_sha256": "0" * 64}
    with pytest.raises(ValueError, match="changed"):
        saved.read_saved_analysis_page("reader", context, **read_options(fixture))
    assert fixture["store"].reads == []


def test_masked_analysis_cannot_be_recovered_through_record_pages(saved_chat):
    fixture = saved_chat
    fixture["message"]["metadata"]["masked_ranges"] = [{"start": 0, "end": 10}]
    context = saved.saved_analysis_context(fixture["descriptor"])
    with pytest.raises(access.AnalysisResultUnavailable) as failure:
        saved.read_saved_analysis_page("reader", context, **read_options(fixture))
    assert failure.value.code == "analysis_message_masked"


def test_history_withholds_content_and_citations_after_revocation(saved_chat):
    fixture = saved_chat
    fixture["state"]["source_allowed"] = False
    original = deepcopy(fixture["message"])
    messages = saved.sanitize_saved_analysis_messages(
        [fixture["message"], {"id": "ordinary", "content": "Unrelated message."}],
        "reader",
        result_reader=lambda user_id, context: saved.load_saved_analysis(user_id, context, **read_options(fixture)),
    )
    assert messages[0]["content"] == saved.UNAVAILABLE_ANALYSIS_MESSAGE
    assert messages[0]["metadata"]["saved_analysis"]["available"] is False
    assert messages[0]["agent_citations"] == []
    assert "PRIVATE-DERIVED-RESULT" not in json.dumps(messages)
    assert messages[1]["content"] == "Unrelated message."
    assert fixture["message"] == original


@pytest.mark.parametrize("offset,limit", [(-1, 25), (0, 0), (0, 101), (0, True)])
def test_invalid_page_bounds_do_not_load_results(saved_chat, offset, limit):
    fixture = saved_chat
    with pytest.raises(ValueError):
        saved.read_saved_analysis_page(
            "reader", saved.saved_analysis_context(fixture["descriptor"]),
            offset=offset, limit=limit, **read_options(fixture),
        )
    assert fixture["store"].reads == []


def test_workflow_history_cannot_reveal_a_blocked_result_preview():
    workflow = {"id": "workflow-1", "user_id": "owner"}
    summary = {
        "analysis_result": True,
        "producer": {"workflow_id": "workflow-1", "run_id": "run-1", "task_id": "analyze"},
        "result_ref": {"sha256": "digest"},
    }
    task = {"task_id": "analyze", "response_preview": "PRIVATE FINDING", "workflow_result": summary}
    run = {
        "id": "run-1", "response_preview": "PRIVATE FINDING", "error": "PRIVATE ERROR",
        "task_results": [task], "status": "completed",
    }
    item = {**deepcopy(task), "output_summary": "PRIVATE FINDING"}

    def deny(*args, **kwargs):
        raise PermissionError("source revoked")

    filtered_run, items, allowed = saved.sanitize_workflow_analysis_history(
        workflow, run, "viewer", items=[item], result_reader=deny,
    )
    assert allowed is False
    assert "PRIVATE" not in json.dumps([filtered_run, items])
    assert filtered_run["status"] == "completed"
    assert filtered_run["analysis_access_available"] is False
    assert run["response_preview"] == "PRIVATE FINDING"


def test_legacy_workflow_history_requires_no_saved_analysis_lookup():
    run = {"id": "run-1", "response_preview": "Ordinary reply.", "task_results": []}
    result = saved.sanitize_workflow_analysis_history(
        {"id": "workflow-1"}, run, "reader",
        result_reader=lambda *args, **kwargs: pytest.fail("No Analyze result to look up."),
    )
    assert result == (run, None, True)
