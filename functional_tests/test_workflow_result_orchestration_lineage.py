# test_workflow_result_orchestration_lineage.py
"""
Functional test for keeping workflow-result answers out of orchestration history.
Version: 0.261.213
Implemented in: 0.261.213

This test ensures that an answer built from a stored workflow result, and any later
answer that inherited its workflow-result context, never enter an orchestration
conversation snapshot, while the user's own follow-up question stays. It also ensures
a snapshot built beside such answers still validates, and a saved snapshot that names
a message which later gained workflow-result lineage is rejected. The real history
normalizer, snapshot builder and snapshot validator run; nothing else is needed.
"""

import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

from functions_orchestration_context import (  # noqa: E402
    ConversationContextError,
    build_conversation_snapshot,
    normalize_history_message,
    validate_conversation_snapshot,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402


CONTEXT = {"workflow_id": "wf-digest-3c1", "run_id": "run-digest-9a7", "result_sha256": "b" * 64}
DESCRIPTOR = {
    "version": "workflow-result-v1", **CONTEXT, "workflow_name": "Weekly digest",
    "status": "completed", "completed_at": "2026-01-05T14:02:00+00:00", "available": True,
}
SETTINGS = {"conversation_history_limit": 20}


def message(message_id, role, content, minute, metadata=None):
    return {
        "id": message_id, "conversation_id": "conv-private-1", "role": role, "content": content,
        "timestamp": f"2026-01-06T09:{minute:02d}:00+00:00", "metadata": metadata or {},
    }


def conversation():
    return [
        message("u1", "user", "What changed in the budget?", 1),
        message("a1", "assistant", "The travel budget went up.", 2),
        message("u2", "user", "What did the digest find?", 3, {"workflow_result_context": dict(CONTEXT)}),
        message("a2", "assistant", "The digest found that markets rose.", 4, {
            "workflow_result": dict(DESCRIPTOR), "workflow_result_contexts": [dict(CONTEXT)],
        }),
        message("u3", "user", "Summarize that in one line.", 5),
        message("a3", "assistant", "Markets rose this week.", 6, {"workflow_result_contexts": [dict(CONTEXT)]}),
    ]


def snapshot_ids(snapshot):
    return [item["id"] for item in snapshot["messages"]]


def test_version_is_at_least_the_workflow_results_release():
    assert_app_version_at_least("0.261.213")


def test_a_follow_up_answer_and_answers_that_inherited_it_stay_out_of_history():
    snapshot = build_conversation_snapshot(conversation(), SETTINGS)

    # a2 used the stored result; a3 inherited its context. The questions stay.
    assert snapshot_ids(snapshot) == ["u1", "a1", "u2", "u3"]
    assert "markets rose" not in str(snapshot["messages"]).lower()


def test_the_users_follow_up_question_keeps_its_text_and_fingerprint():
    plain = message("u2", "user", "What did the digest find?", 3)
    selected = conversation()[2]

    normalized = normalize_history_message(selected)

    assert normalized is not None
    assert normalized["content"] == "What did the digest find?"
    assert normalized["fingerprint"] == normalize_history_message(plain)["fingerprint"]


@pytest.mark.parametrize("metadata", [
    {"workflow_result": dict(DESCRIPTOR)},
    {"workflow_result_contexts": [dict(CONTEXT)]},
    {"workflow_result": {"version": "workflow-result-v1", "available": False}},
    {"workflow_result": None},
    {"workflow_result_contexts": []},
    {"workflow_result_contexts": "not-a-list"},
], ids=["descriptor", "inherited", "masked", "null", "empty", "malformed"])
def test_any_workflow_result_lineage_key_excludes_the_message(metadata):
    assert normalize_history_message(message("a9", "assistant", "An answer.", 9, metadata)) is None


def test_a_snapshot_built_beside_workflow_answers_still_validates():
    messages = conversation()
    snapshot = build_conversation_snapshot(messages, SETTINGS)

    validated = validate_conversation_snapshot(deepcopy(snapshot), messages)

    assert validated == snapshot


def test_a_saved_snapshot_naming_a_message_that_gained_lineage_is_rejected():
    messages = conversation()
    snapshot = build_conversation_snapshot(messages, SETTINGS)
    # a1 is in the snapshot; if it later carried workflow-result lineage, the plan can't use it.
    messages[1]["metadata"]["workflow_result_contexts"] = [dict(CONTEXT)]

    with pytest.raises(ConversationContextError):
        validate_conversation_snapshot(snapshot, messages)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
