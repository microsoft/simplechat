# test_saved_analysis_cosmos_owner_contract.py
"""
Runtime SDK mapping evidence for the saved-analysis storage owners.
Version: 0.261.398
Implemented in: 0.261.398

Execute real owners with the shared SDK-default transactional containers.
Point/write responses are installed-SDK CosmosDict objects; query rows are plain
dictionaries. Preserve authorization, partition routing, ETags and failure paths.
"""

from copy import deepcopy
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace

from azure.core import MatchConditions
from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos.exceptions import CosmosAccessConditionFailedError
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Application imports follow the standalone path setup.
from test_support.app_stubs import import_app_module, stubbed_config
from test_support.orchestration_revisions import AtomicMemoryContainer


USER = "owner"
CONVERSATION = "conversation-1"
PRODUCER = {"kind": "chat", "conversation_id": CONVERSATION, "message_id": "assistant-original"}


class SavedAnalysisContainer(AtomicMemoryContainer):
    """Keep the shared SDK-default behavior and add its missing nested metadata patch API."""

    def patch_item(self, item, partition_key, patch_operations, **kwargs):
        self._hook("before_replace")
        with self._lock:
            current = self.read_item(item, partition_key)
            if (
                kwargs.get("match_condition") != MatchConditions.IfNotModified
                or kwargs.get("etag") != current["_etag"]
            ):
                raise CosmosAccessConditionFailedError(status_code=412, message="Fixture item changed.")
            body = deepcopy(dict(current))
            for operation in patch_operations:
                parts = operation["path"].split("/")
                if operation["op"] != "set" or len(parts) != 3 or parts[:2] != ["", "metadata"]:
                    raise ValueError("This fixture supports the owner's metadata set operations only.")
                body.setdefault("metadata", {})[parts[2]] = deepcopy(operation["value"])
            return self._save(body)


@pytest.fixture
def owners(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Saved-analysis owner tests must not use the network.")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    conversations = AtomicMemoryContainer("id")
    messages = SavedAnalysisContainer("conversation_id")
    original = conversations.create_item({"id": CONVERSATION, "user_id": USER, "title": "Original"})

    def participation(user_id, conversation, **kwargs):
        if conversation.get("user_id") != user_id:
            raise PermissionError("The fixture conversation belongs to another user.")
        return {"actor_user_id": user_id}

    collaboration = ModuleType("functions_collaboration")
    collaboration.build_conversation_participation_context = participation
    collaboration.assert_user_can_view_collaboration_conversation = participation
    collaboration.get_collaboration_conversation = lambda conversation_id: conversations.read_item(
        conversation_id, conversation_id,
    )
    collaboration.get_collaboration_message = lambda message_id: messages.read_item(message_id, CONVERSATION)
    monkeypatch.setitem(sys.modules, "functions_collaboration", collaboration)
    with stubbed_config(
        CLIENTS={}, cognitive_services_scope="offline",
        cosmos_conversations_container=conversations, cosmos_messages_container=messages,
    ):
        saved = import_app_module("functions_saved_analysis")
        yield SimpleNamespace(saved=saved, conversations=conversations, messages=messages, original=original)


def test_conversation_authorization_and_personal_reads_keep_sdk_mapping_contract(owners):
    authorized = owners.saved._authorize_conversation(USER, CONVERSATION)
    personal = owners.saved._read_personal_conversation(CONVERSATION)
    assert type(authorized) is CosmosDict
    assert type(personal) is CosmosDict
    assert authorized["_etag"] == owners.original["_etag"]
    with pytest.raises(PermissionError):
        owners.saved._authorize_conversation("another-user", CONVERSATION)


def test_conversation_update_uses_current_sdk_etag(owners):
    updated = owners.saved.update_analysis_conversation(USER, {**owners.original, "title": "Updated"})
    assert type(updated) is CosmosDict
    assert updated["title"] == "Updated"
    assert updated["_etag"] != owners.original["_etag"]


def test_conversation_update_does_not_overwrite_a_concurrent_deletion_fence(owners):
    owners.conversations.before_replace = lambda: owners.conversations.upsert_item({
        **owners.original, "orchestration_deleted": True,
    })
    with pytest.raises(owners.saved.AnalysisResultUnavailable) as failure:
        owners.saved.update_analysis_conversation(USER, {**owners.original, "title": "Late answer"})
    current = owners.conversations.read_item(CONVERSATION, CONVERSATION)
    assert failure.value.code == "analysis_conversation_changed"
    assert current["orchestration_deleted"] is True
    assert current["title"] == "Original"


def test_attempt_binding_uses_sdk_actor_metadata_and_conditional_replace(owners):
    owners.messages.create_item({
        "id": "user-1", "conversation_id": CONVERSATION, "role": "user", "user_id": USER,
        "metadata": {"analysis_attempt_message_id": "previous-assistant"},
    })
    previous = owners.saved.bind_chat_analysis_attempt(USER, CONVERSATION, "user-1", "new-assistant")
    current = owners.messages.read_item("user-1", CONVERSATION)
    assert previous == "previous-assistant"
    assert type(current) is CosmosDict
    assert current["metadata"]["analysis_attempt_message_id"] == "new-assistant"


def test_attempt_binding_rejects_another_actor_without_writing(owners):
    owners.messages.create_item({
        "id": "user-1", "conversation_id": CONVERSATION, "role": "user", "user_id": "another-user",
    })
    before = owners.messages.sequence
    with pytest.raises(owners.saved.AnalysisResultUnavailable) as failure:
        owners.saved.bind_chat_analysis_attempt(USER, CONVERSATION, "user-1", "new-assistant")
    assert failure.value.code == "analysis_retry_unavailable"
    assert owners.messages.sequence == before


def test_attempt_binding_keeps_a_concurrent_attempt_instead_of_replacing_it(owners):
    message = owners.messages.create_item({
        "id": "user-1", "conversation_id": CONVERSATION, "role": "user", "user_id": USER,
        "metadata": {},
    })
    owners.messages.before_replace = lambda: owners.messages.upsert_item({
        **message, "metadata": {"analysis_attempt_message_id": "concurrent-assistant"},
    })
    with pytest.raises(owners.saved.AnalysisResultUnavailable) as failure:
        owners.saved.bind_chat_analysis_attempt(USER, CONVERSATION, "user-1", "new-assistant")
    current = owners.messages.read_item("user-1", CONVERSATION)
    assert failure.value.code == "analysis_retry_changed"
    assert current["metadata"]["analysis_attempt_message_id"] == "concurrent-assistant"


def test_authorized_message_owner_accepts_sdk_point_response(owners):
    owners.messages.create_item({
        "id": "assistant-1", "conversation_id": CONVERSATION, "role": "assistant", "metadata": {},
    })
    message = owners.saved._load_authorized_message(USER, CONVERSATION, "assistant-1")
    assert type(message) is CosmosDict
    assert message["id"] == "assistant-1"
    with pytest.raises(PermissionError):
        owners.saved._load_authorized_message("another-user", CONVERSATION, "assistant-1")


def test_artifact_parent_owner_reads_plain_query_rows_in_the_conversation_partition(owners):
    owners.messages.create_item({
        "id": "assistant-1", "conversation_id": CONVERSATION, "role": "assistant",
        "metadata": {"generated_analysis_artifacts": [{"artifact_message_id": "artifact-1"}]},
    })
    rows = owners.saved._analysis_artifact_parents(CONVERSATION, "artifact-1", native_run_id="native-1")
    assert len(rows) == 1
    assert type(rows[0]) is dict
    query, parameters, partition = owners.messages.queries[-1]
    assert partition == CONVERSATION
    assert "ARRAY_CONTAINS" in query
    assert {item["name"]: item["value"] for item in parameters}["@artifact"] == {
        "artifact_message_id": "artifact-1",
    }


def test_native_artifact_binding_patches_sdk_document_with_its_etag(owners):
    original = owners.messages.create_item({
        "id": "artifact-1", "conversation_id": CONVERSATION, "role": "file",
        "metadata": {"is_generated_chat_artifact": True, "generated_artifact_run_id": "native-1"},
    })
    owners.saved.bind_native_analysis_artifacts(
        USER, CONVERSATION, "native-1", [{"artifact_message_id": "artifact-1"}], PRODUCER,
    )
    current = owners.messages.read_item("artifact-1", CONVERSATION)
    assert type(current) is CosmosDict
    assert current["_etag"] != original["_etag"]
    assert current["metadata"]["analysis_result_required"] is True
    assert current["metadata"]["analysis_producer"] == PRODUCER


def test_native_artifact_binding_does_not_overwrite_a_concurrent_sdk_document(owners):
    original = owners.messages.create_item({
        "id": "artifact-1", "conversation_id": CONVERSATION, "role": "file",
        "metadata": {"is_generated_chat_artifact": True, "generated_artifact_run_id": "native-1"},
    })
    owners.messages.before_replace = lambda: owners.messages.upsert_item({
        **original, "metadata": {**original["metadata"], "outside_change": "preserved"},
    })
    with pytest.raises(CosmosAccessConditionFailedError):
        owners.saved.bind_native_analysis_artifacts(
            USER, CONVERSATION, "native-1", [{"artifact_message_id": "artifact-1"}], PRODUCER,
        )
    current = owners.messages.read_item("artifact-1", CONVERSATION)
    assert current["metadata"]["outside_change"] == "preserved"
    assert "analysis_result_required" not in current["metadata"]


def test_projection_context_binding_preserves_sdk_scope_and_checks_producer(owners):
    owners.messages.create_item({
        "id": "artifact-1", "conversation_id": CONVERSATION, "role": "file",
        "metadata": {"analysis_producer": deepcopy(PRODUCER)},
    })
    artifact = {"artifact_message_id": "artifact-1", "conversation_id": CONVERSATION}
    contexts = [{"conversation_id": CONVERSATION, "message_id": "assistant-original", "result_sha256": "a" * 64}]
    owners.saved._bind_analysis_projection_contexts(artifact, contexts, PRODUCER)
    current = owners.messages.read_item("artifact-1", CONVERSATION)
    assert type(current) is CosmosDict
    assert current["metadata"]["analysis_result_contexts"] == contexts
    with pytest.raises(owners.saved.AnalysisResultUnavailable):
        owners.saved._bind_analysis_projection_contexts(
            artifact, contexts, {**PRODUCER, "message_id": "unrelated-assistant"},
        )
