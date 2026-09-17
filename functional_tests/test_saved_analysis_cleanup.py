# test_saved_analysis_cleanup.py
"""
Functional tests for scoped saved Analyze cleanup.
Version: 0.261.109
Implemented in: 0.261.109

Deleting a reply must not delete a referenced workflow or mirrored origin.
Interrupted chat writes are cleaned with their owning conversation.
"""

from copy import deepcopy

import pytest

from test_saved_analysis_service import saved, saved_chat


def test_deleting_origin_cleans_only_its_real_chat_result(saved_chat):
    removed = []
    thoughts = []
    saved.cleanup_chat_analysis_messages(
        [saved_chat["message"]], conversation_id="conversation-1", owner_user_id="owner",
        delete_result=lambda *args: removed.append(args),
        delete_thoughts=lambda *args: thoughts.append(args),
    )
    assert removed == [("owner", "conversation-1", "assistant-1")]
    assert thoughts == [("conversation-1", "assistant-1", "owner")]


def test_deleting_mirror_does_not_delete_the_original_analysis(saved_chat):
    message = {**deepcopy(saved_chat["message"]), "id": "mirror", "conversation_id": "another-chat"}
    saved.cleanup_chat_analysis_messages(
        [message], conversation_id="another-chat", owner_user_id="reader",
        delete_result=lambda *args: pytest.fail("The original result belongs to another message."),
        delete_thoughts=lambda *args: None,
    )


def test_workflow_results_are_not_deleted_with_a_chat_reference(saved_chat):
    message = deepcopy(saved_chat["message"])
    message["metadata"]["saved_analysis"]["binding"] = {
        "kind": "workflow", "workflow_id": "workflow-1", "run_id": "run-1", "task_id": "task-1",
    }
    saved.cleanup_chat_analysis_messages(
        [message], conversation_id="conversation-1", owner_user_id="owner",
        delete_result=lambda *args: pytest.fail("Workflow result retention is owned by the workflow."),
        delete_thoughts=lambda *args: None,
    )


def test_conversation_cleanup_includes_interrupted_producer_writes():
    deleted = []
    messages = [{
        "id": "user-message", "role": "user",
        "metadata": {"document_action": {"type": "analyze"}, "user_info": {"user_id": "participant"}},
    }]
    saved.cleanup_chat_analysis_conversation(
        "conversation-1", "owner", messages, delete_result=lambda *args: deleted.append(args),
    )
    assert set(deleted) == {("owner", "conversation-1"), ("participant", "conversation-1")}


def test_ordinary_chat_cleanup_does_not_require_result_storage():
    saved.cleanup_chat_analysis_conversation(
        "conversation-1", "owner", [{"role": "user", "content": "Hello"}],
        delete_result=lambda *args: pytest.fail("No analysis data was created."),
    )


def test_cleanup_failure_is_not_hidden(saved_chat):
    def failed(*args):
        raise ConnectionError("Storage is not available.")

    with pytest.raises(ConnectionError):
        saved.cleanup_chat_analysis_messages(
            [saved_chat["message"]], conversation_id="conversation-1", owner_user_id="owner",
            delete_result=failed, delete_thoughts=lambda *args: None,
        )


def test_pending_thoughts_require_current_conversation_access(monkeypatch):
    def missing_message(*args):
        raise LookupError("The pending assistant has not been saved.")

    monkeypatch.setattr(saved, "_authorize_conversation", lambda *args: {"id": "conversation-1"})
    assert saved.authorize_saved_analysis_message_read(
        "owner", "conversation-1", "pending", allow_pending=True, message_loader=missing_message,
    ) is False

    def denied(*args):
        raise PermissionError("The conversation is unavailable.")

    monkeypatch.setattr(saved, "_authorize_conversation", denied)
    with pytest.raises(PermissionError):
        saved.authorize_saved_analysis_message_read(
            "owner", "conversation-1", "pending", allow_pending=True, message_loader=missing_message,
        )
