# test_native_document_fidelity_http.py
"""Native source bytes through real HTTP/action/retention/composition/publication.

Version: 0.261.424
Implemented in: 0.261.424
Only external blob/model I/O is replaced. SDK-default document storage, source
authorization, real parsers, native claim validation and saved delivery execute.
"""

import importlib
import json

import pytest

from test_native_document_fidelity import native_source
from test_excel_inventory_persistence import inventory_store
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent
from test_orchestration_document_action_end_to_end import (
    LEFT, MESSAGE, TURN, action_proposal, frames, modules, native_http, real_http_harness, source_runtime,
)


__all__ = ["native_source", "modules", "native_http", "real_http_harness", "source_runtime", "inventory_store"]


@pytest.mark.parametrize("name", ["SC-C04.pdf", "SC-C10-R3.pptx", "SC-C11.xlsx"])
@pytest.mark.parametrize("bad_claims", [False, True, "persistent"])
def test_native_source_facts_reach_saved_http_answer(
    native_http, native_source, inventory_store, monkeypatch, name, bad_claims,
):
    state = native_http
    runtime, harness = state.runtime, state.runtime.harness
    harness.settings["enable_chat_orchestration_completeness_check"] = False
    path = native_source(name)
    source_bytes = path.read_bytes()
    documents = harness.config.cosmos_user_documents_container
    document = documents.read_item(LEFT, LEFT)
    document.update({
        "file_name": name, "blob_path": "synthetic-retained-source/" + name,
        "source_file_available": True, "enhanced_citations": True,
        "accessibility_metadata": {"format": path.suffix[1:], "schema_version": "1.0"},
    })
    documents.upsert_item(document)
    harness.blobs.records[(document["blob_container"], document["blob_path"])] = {
        "data": source_bytes, "metadata": {"document_id": LEFT}, "etag": "native-source-etag",
    }
    access = importlib.import_module("content_screening.access")
    downloads = []

    def download(container, blob_path, current):
        downloads.append(current["id"])
        return source_bytes

    monkeypatch.setattr(access, "_download_available_blob", download)
    if path.suffix == ".xlsx":
        search = importlib.import_module("functions_search_service")
        monkeypatch.setattr(search, "ScreeningStorage", lambda **kwargs: inventory_store[0])
    original_reply = AzureChatCompletion._inner_get_chat_message_contents

    async def native_reply_with_untrusted_findings(self, history, settings):
        replies = await original_reply(self, history, settings)
        if bad_claims and len(state.native_calls) > 1:
            return [ChatMessageContent(
                role=AuthorRole.ASSISTANT,
                content="Step 1 BEFORE Step 2 is the native order; absent native attributes are stored empty.",
            )]
        if path.suffix == ".xlsx":
            for reply in replies:
                for item in reply.items:
                    if isinstance(item, FunctionCallContent):
                        arguments = json.loads(item.arguments)
                        item.arguments = json.dumps({
                            **arguments, "native_section": "objects", "sheet_name": "Budget", "cell_range": "B4",
                        })
        return replies

    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", native_reply_with_untrusted_findings)
    proposal = action_proposal((LEFT,), action=state.action)
    proposal["steps"][0]["arguments"]["task"] = MESSAGE
    proposal["steps"][1]["arguments"]["instruction"] = "Report native facts without inventing field states or logical bindings."

    def claims():
        payload = next(
            json.loads(message["content"])
            for message in harness.model_calls[-1]["messages"]
            if message["role"] == "user" and message["content"].startswith('{"request":')
        )
        contract = payload["native_audit_contract"]
        if bad_claims:
            assert "Step 1 BEFORE Step 2" in json.dumps(payload["inputs"])
        return json.dumps({"native_claims": {
            "scope": "all_returned", "fact_set_sha256": contract["fact_set_sha256"],
        }})

    harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": MESSAGE, "message_ids": [],
            "requires_retrieval": True, "clarification": "",
        }),
        json.dumps(proposal),
        *(['The native order is Step 1 then Step 2 and all missing fields are stored empty.'] if bad_claims else []),
        'The native order is Step 1 then Step 2 and all missing fields are stored empty.'
        if bad_claims == "persistent" else claims,
    ]
    response = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": TURN, "message": MESSAGE,
        "planning_submission_id": "native-fidelity", "approval_mode": "auto",
        "selected_document_ids": [LEFT],
    }, buffered=True)
    events = frames(response)
    plan = next(event["plan"] for event in events if event.get("type") == "orchestration_plan")
    saved = harness.runs.read_item(plan["run_id"], "conversation-1")
    if bad_claims == "persistent":
        assert saved["status"] == "failed"
        assert not any(
            "all missing fields are stored empty" in answer.get("content", "")
            for answer in harness.assistant_messages()
        )
        return
    assert saved["status"] == "completed", "\n".join(state.failures)
    answers = harness.assistant_messages()
    assert len(answers) == 1
    text = answers[0]["content"]
    assert "Native file evidence" in text
    assert "all missing fields are stored empty" not in text
    assert "get_document_accessibility_report" in json.dumps(answers[0].get("agent_citations", []))
    assert downloads and set(downloads) == {LEFT}
    assert len(harness.model_calls) == (4 if bad_claims else 3)
    if path.suffix == ".pdf":
        assert text.index("Step 2: release") < text.index("Step 1: approve")
        assert "cedar-native-SC-C04, lantern-917" in text
        assert "CEDAR / SYNTHETIC / 1" in text and "vector_groups" in text
        assert "PDF_NO_HEADINGS" in text and "PDF_FONTS_NOT_EMBEDDED" in text
        assert "Column" in text and "native_table" in text
    elif path.suffix == ".pptx":
        assert "Decorative teal ellipse" in text
        assert "present_empty" in text and "absent" in text
        assert "#E8E8E8" in text and "#FCFAF6" in text and "1.18" in text
        assert "PPTX_LOW_TEXT_CONTRAST" in text
    else:
        assert "Budget!D3" in text and "checkbox" in text
        assert "Budget!B4" in text and "15000" in text
        assert "absent" in text and "Arial" in text
