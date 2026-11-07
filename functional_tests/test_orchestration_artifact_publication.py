# test_orchestration_artifact_publication.py
"""
Functional tests for explicit publication of committed orchestration files.
Version: 0.261.127
Implemented in: 0.261.127

Real retained results, rendering, upload, source authorization and publication
execute with external I/O doubles. Workflow-only receipts are never fabricated.
"""

from copy import deepcopy
import sys

import pytest

from test_analysis_artifact_publication import publication  # noqa: F401
from test_orchestration_output_lifecycle import lifecycle, production_modules  # noqa: F401
from test_orchestration_publication_policy import effect_snapshot
from functions_orchestration_execution_policy import (
    OrchestrationFilePolicyError,
    orchestration_file_policy,
)
from functions_orchestration_output_store import OutputUnavailableError


@pytest.fixture
def retained_publication(lifecycle, request, monkeypatch):
    prepared = lifecycle.prepare("json")
    completed = lifecycle.run(prepared)
    assert completed["state"] == "completed"
    artifact = lifecycle.messages.read_item(
        item=completed["artifact_message_id"], partition_key="conversation-1",
    )
    content = lifecycle.blobs.data[(artifact["blob_container"], artifact["blob_path"])]
    # Materialize through the real uploader before installing destination I/O doubles.
    fixture = request.getfixturevalue("publication")
    fixture.conversations.put({"id": "conversation-1", "user_id": "owner"})
    fixture.messages.put(artifact)
    fixture.artifact = artifact
    fixture.lifecycle = lifecycle
    fixture.state["content"] = content
    monkeypatch.setattr(
        fixture.module, "authorize_generated_artifact_source",
        lifecycle.modules.sources.authorize_generated_artifact_source,
    )
    monkeypatch.setattr(
        fixture.module, "assert_generated_chat_artifact_is_published_for_user",
        lifecycle.modules.operations.assert_generated_chat_artifact_is_published_for_user,
    )
    monkeypatch.setattr(
        sys.modules["functions_simplechat_operations"], "open_generated_chat_artifact_stream",
        lifecycle.modules.operations.open_generated_chat_artifact_stream, raising=False,
    )
    queue = fixture.module.queue_generated_document_processing

    def queue_stream(**values):
        content = values["file_content_bytes"]
        if hasattr(content, "read"):
            values["file_content_bytes"] = content.read()
        return queue(**values)

    monkeypatch.setattr(fixture.module, "queue_generated_document_processing", queue_stream)
    return fixture


def promote(fixture, scope="personal"):
    destination = {"workspace_scope": scope}
    if scope != "personal":
        destination["group_id" if scope == "group" else "public_workspace_id"] = f"fixed-{scope}"
    return fixture.module.publish_generated_chat_artifact_for_user(
        "owner", conversation_id="conversation-1", message_id=fixture.artifact["id"],
        destination=destination, request_id="explicit-retained-output-promotion",
    )


def test_authorized_retained_output_keeps_its_actual_producer_kind(retained_publication):
    fixture = retained_publication
    artifact = fixture.module._authorize_artifact("owner", "conversation-1", fixture.artifact["id"])
    binding = artifact["metadata"]["generated_artifact_source"]
    producer = fixture.module._artifact_producer(artifact)
    assert producer == {"kind": "orchestration_retained_output", **binding["producer"]}
    assert "source_receipt" not in binding
    assert not {"workflow_id", "execution_id", "task_id", "node_id"} & producer.keys()


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_manual_retained_output_promotion_reuses_bytes_without_workflow_receipts(retained_publication, scope):
    fixture = retained_publication
    first = promote(fixture, scope)
    repeated = promote(fixture, scope)
    assert first["publication"] == repeated["publication"]
    assert first["publication"]["state"] == ("queued" if scope == "personal" else "pending_approval")
    receipt = fixture.messages.records[fixture.artifact["id"]]["metadata"][fixture.module.RECEIPTS_FIELD][
        first["publication"]["id"]
    ]
    assert receipt.get("source_receipt") is None
    assert "completion_policy" not in receipt
    assert receipt["source_identity"]["generated_source"] == fixture.artifact["metadata"]["generated_artifact_source"]
    assert len(fixture.calls["create"]) == 1
    if scope != "personal":
        assert not fixture.calls["queue"]
        assert len(fixture.calls["notify"]) == 2
        fixture.state["group_role"] = "DocumentManager"
        document = deepcopy(fixture.destinations[scope].records[first["document"]["id"]])
        decision = fixture.module.decide_artifact_publication("reviewer", document, "approved")
        assert decision["message"] == "Publication approved."
        assert len(fixture.calls["notify"]) == 3
    assert len(fixture.calls["queue"]) == 1
    assert fixture.calls["queue"][0]["file_content_bytes"] == fixture.state["content"]
    assert fixture.lifecycle.blobs.uploads == 1
    assert len(fixture.lifecycle.render_calls) == 1


@pytest.mark.parametrize("entry", ["publish_workflow_artifact", "publish_workflow_analysis_artifact"])
@pytest.mark.parametrize("completion_policy", [None, "submitted"])
def test_workflow_publication_rejects_orchestration_bindings_before_effects(
    retained_publication, entry, completion_policy,
):
    fixture = retained_publication
    before = effect_snapshot(fixture)
    publication_config = {"source_kind": "saved_output", "artifact_format": "json", "workspace_scope": "personal"}
    if completion_policy is not None:
        publication_config["completion_policy"] = completion_policy
    with pytest.raises(ValueError, match="not bound to saved workflow records"):
        getattr(fixture.module, entry)(
            "owner", publication=publication_config,
            artifact_reference={
                "conversation_id": "conversation-1", "artifact_message_id": fixture.artifact["id"],
                "producer": fixture.module._artifact_producer(fixture.artifact),
            },
            request_id="workflow-cannot-adopt-an-orchestration-output",
        )
    after = effect_snapshot(fixture)
    assert after == before


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_retained_output_promotion_still_obeys_file_policy(retained_publication, scope):
    before = effect_snapshot(retained_publication)
    with orchestration_file_policy(allow_generated_files=False):
        with pytest.raises(OrchestrationFilePolicyError):
            promote(retained_publication, scope)
    after = effect_snapshot(retained_publication)
    assert after == before


@pytest.mark.parametrize("scope", ["group", "public"])
def test_retained_output_approval_rechecks_current_source_authority(retained_publication, scope):
    fixture = retained_publication
    submitted = promote(fixture, scope)
    fixture.state["group_role"] = "DocumentManager"
    document = deepcopy(fixture.destinations[scope].records[submitted["document"]["id"]])
    fixture.lifecycle.capabilities = False
    before = effect_snapshot(fixture)
    with pytest.raises((PermissionError, OutputUnavailableError)):
        fixture.module.decide_artifact_publication("reviewer", document, "approved")
    after = effect_snapshot(fixture)
    assert after == before
