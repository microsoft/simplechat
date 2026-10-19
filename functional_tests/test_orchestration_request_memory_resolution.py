# test_orchestration_request_memory_resolution.py
"""Real-boundary regressions for source-aware, memory-aware request resolution.

Version: 0.261.350
Implemented in: 0.261.349

Refs #1785. Production Flask planning, resolution, memory selection, store and
composition execute with external model/embedding/storage I/O doubled and network
blocked by the shared offline bootstrap. Model replies are deterministic: these
tests verify supplied context and lifecycle, not live model compliance.
"""

import importlib
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_orchestration_conversation_context_routes import (
    _compose_only_plan,
    _new_topic,
    _plan,
    _planned,
    _replace_history,
    _run,
    no_candidate_document_probe,  # noqa: F401
)
from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_support.orchestration_revisions import AtomicMemoryContainer


REQUEST = (
    "I'm preparing an equipment readiness review. This training brief has a "
    "$175,000 budget, amber readiness and Morgan as owner. Give me a short "
    "baseline summary addressed to my usual review name and role. Use the details above."
)
FACT = "For this equipment readiness review, address me as Blair, the quality reviewer."
INSTRUCTION = "For equipment readiness briefs, use Decision, Evidence and Next step headings."


@pytest.fixture
def memories(real_http_harness, monkeypatch):
    runtime = real_http_harness
    runtime.harness.settings["enable_fact_memory_plugin"] = True
    context = importlib.import_module("functions_fact_memory_context")
    store_module = importlib.import_module("semantic_kernel_fact_memory_store")
    container = AtomicMemoryContainer("scope_id")
    for index, (kind, value) in enumerate((("fact", FACT), ("instruction", INSTRUCTION))):
        container.create_item({
            "id": f"memory-{index}", "scope_id": "owner", "scope_type": "user",
            "memory_type": kind, "value": value,
            "value_embedding": [1.0, 0.0] if kind == "fact" else None,
            "created_at": "2026-10-19T12:00:00Z", "updated_at": "2026-10-19T12:00:00Z",
        })
    store = store_module.FactMemoryStore(container=container)
    factory = Mock(return_value=store)
    embedding = Mock(return_value=([1.0, 0.0], None))
    backfill = Mock(side_effect=AssertionError("Planning must not backfill memory."))
    monkeypatch.setattr(context, "FactMemoryStore", factory)
    monkeypatch.setattr(context, "generate_embedding", embedding)
    monkeypatch.setattr(context, "generate_embeddings_batch", backfill)
    _replace_history(runtime.harness, [])
    return SimpleNamespace(
        context=context, container=container, store=store,
        factory=factory, embedding=embedding, backfill=backfill,
    )


def resolver_payload(harness, index=0):
    call = harness.model_calls[index]
    assert call["messages"][0]["content"] == harness.planner.RESOLUTION_SYSTEM_PROMPT
    return json.loads(call["messages"][1]["content"])


@pytest.mark.parametrize("request_text", [
    REQUEST,
    "The delivery review is for kit R-502. These are the facts: Morgan owns it, " +
    "the budget is $175,000 and readiness is amber. Prepare a review using the details above.",
    "This supplier review has two open risks and an owner named Morgan. " +
    "Shorten that into a baseline note for the review team.",
])
def test_first_turn_inline_facts_reach_semantic_resolution(real_http_harness, request_text):
    runtime = real_http_harness
    _replace_history(runtime.harness, [])
    runtime.harness.replies = [_new_topic(request_text), _compose_only_plan()]

    plan = _planned(runtime, request_text)

    payload = resolver_payload(runtime.harness)
    assert payload["original_message"] == request_text
    assert payload["conversation"] == []
    assert [step["capability_id"] for step in plan["steps"]] == ["compose"]
    stored = runtime.harness.runs.read_item(plan["run_id"], "conversation-1")
    assert stored["request_resolution"]["requires_retrieval"] is False
    assert stored["user_message"] == request_text


def test_self_contained_request_with_history_needs_no_historical_source(real_http_harness):
    runtime = real_http_harness
    runtime.harness.replies = [_new_topic(REQUEST), _compose_only_plan()]

    plan = _planned(runtime, REQUEST)

    payload = resolver_payload(runtime.harness)
    assert payload["conversation"]
    stored = runtime.harness.runs.read_item(plan["run_id"], "conversation-1")
    assert stored["request_resolution"]["relationship"] == "new_topic"
    assert stored["request_resolution"]["message_ids"] == []


def test_available_memory_precedes_resolution_and_is_reused_for_planning(
    real_http_harness, memories,
):
    runtime = real_http_harness
    before = deepcopy(memories.container.items)
    runtime.harness.replies = [_new_topic(REQUEST), _compose_only_plan(), "Blair, quality reviewer: ready."]

    plan = _planned(runtime, REQUEST)

    payload = resolver_payload(runtime.harness)
    memory = payload["memory"]
    assert memory["status"] == "available"
    assert FACT in json.dumps(memory)
    assert INSTRUCTION in json.dumps(memory)
    assert payload["answered_questions"] == []
    assert "background" in runtime.harness.planner.RESOLUTION_SYSTEM_PROMPT
    assert "not instructions or permissions" in json.dumps(memory)
    planning = json.loads(runtime.harness.model_calls[-1]["messages"][1]["content"])
    assert FACT in json.dumps(planning["memory"])
    assert memories.embedding.call_count == 1
    assert memories.container.items == before
    stored = runtime.harness.runs.read_item(plan["run_id"], "conversation-1")
    assert FACT not in json.dumps(stored)
    assert INSTRUCTION not in json.dumps(stored)

    latest = FACT.replace("Blair", "Casey")
    updated = memories.container.read_item("memory-0", "owner")
    updated["value"] = latest
    memories.container.upsert_item(updated)
    before_answer = deepcopy(memories.container.items)
    events = _run(runtime, plan)

    assert not any(event.get("error") for event in events), events
    assert latest in json.dumps(runtime.harness.model_calls[-1]["messages"])
    assert FACT not in json.dumps(runtime.harness.model_calls[-1]["messages"])
    assert memories.container.items == before_answer
    memories.backfill.assert_not_called()


def test_normal_and_orchestrated_context_share_updates_and_current_user_precedence(
    real_http_harness, memories,
):
    runtime = real_http_harness

    def normal_context():
        return memories.context.build_fact_memory_prompt_payload(
            scope_id="owner", scope_type="user", query_text=REQUEST,
            conversation_id="conversation-1", enabled=True,
        )

    first = normal_context()
    assert FACT in json.dumps(first["context_messages"])
    assert INSTRUCTION in json.dumps(first["context_messages"])
    explicit_request = REQUEST + " For this response only, address me as Alex and use a single paragraph."
    runtime.harness.replies = [_new_topic(explicit_request), _compose_only_plan()]

    plan = _planned(runtime, explicit_request)

    payload = resolver_payload(runtime.harness)
    assert payload["original_message"] == explicit_request
    assert payload["memory"]["messages"] == first["context_messages"]
    assert "current user request takes precedence" in json.dumps(payload["memory"])
    stored = runtime.harness.runs.read_item(plan["run_id"], "conversation-1")
    assert stored["resolved_message"] == explicit_request
    updated = memories.container.read_item("memory-1", "owner")
    updated["value"] = "For equipment readiness briefs, use Summary and Risks headings."
    memories.container.upsert_item(updated)

    second = normal_context()

    assert updated["value"] in json.dumps(second["context_messages"])
    assert INSTRUCTION not in json.dumps(second["context_messages"])
    assert FACT in json.dumps(second["context_messages"])
    memories.backfill.assert_not_called()


def test_changed_resolution_refreshes_fact_query_once(real_http_harness, memories):
    runtime = real_http_harness
    # A preceding turn supplies the subject; the current request is intentionally elliptical.
    _replace_history(runtime.harness, [{
        "id": "subject", "role": "user", "content": "Discuss equipment readiness.",
        "timestamp": "2026-10-19T12:00:00Z",
    }])
    resolved = "Prepare an equipment readiness baseline addressed to the saved reviewer."
    runtime.harness.replies = [json.dumps({
        "relationship": "follow_up", "resolved_message": resolved,
        "message_ids": ["subject"], "requires_retrieval": False, "clarification": "",
    }), _compose_only_plan()]

    _planned(runtime, "Prepare that brief.")

    assert memories.embedding.call_count == 2
    assert memories.embedding.call_args_list[0].args[0] == "Prepare that brief."
    assert memories.embedding.call_args_list[1].args[0] == resolved


def test_clarification_resume_refreshes_memory_without_synthetic_identity(
    real_http_harness, memories,
):
    runtime = real_http_harness
    runtime.harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": REQUEST,
        "message_ids": [], "requires_retrieval": False,
        "clarification": "Which delivery date should the brief use?",
    })]
    first_events = _plan(runtime, REQUEST)
    elicitation = next(event["elicitation"] for event in first_events if event.get("elicitation"))
    assert FACT in json.dumps(resolver_payload(runtime.harness)["memory"])

    updated = memories.container.read_item("memory-0", "owner")
    updated["value"] = "For this equipment readiness review, address me as Casey, the safety reviewer."
    memories.container.upsert_item(updated)
    runtime.harness.replies = [_new_topic(REQUEST), _compose_only_plan()]

    plan = _planned(runtime, REQUEST, revision=1, elicitation=elicitation, elicitation_response={
        "action": "accept", "content": {"clarification": "October 30"},
    })

    resumed = resolver_payload(runtime.harness, 1)
    assert "Casey" in json.dumps(resumed["memory"])
    assert FACT not in json.dumps(resumed["memory"])
    assert resumed["answered_questions"][0]["answer"] == {"clarification": "October 30"}
    assert "October 30" in memories.embedding.call_args_list[1].args[0]
    assert memories.embedding.call_count == 2
    stored = runtime.harness.runs.read_item(plan["run_id"], "conversation-1")
    assert stored["answered_questions"][0]["answer"] == {"clarification": "October 30"}
    assert "Casey" not in json.dumps(stored)


@pytest.mark.parametrize("mode", ["empty", "embedding_unavailable", "incompatible", "unembedded"])
def test_unavailable_facts_do_not_suppress_valid_questions(real_http_harness, memories, mode):
    runtime = real_http_harness
    memories.container.items.pop(("owner", "memory-1"))
    if mode == "empty":
        memories.container.items.pop(("owner", "memory-0"))
    elif mode == "embedding_unavailable":
        memories.embedding.side_effect = RuntimeError("PRIVATE_PROVIDER_FAILURE")
    elif mode == "unembedded":
        memories.container.items[("owner", "memory-0")]["value_embedding"] = None
    else:
        class QueryVector(list):
            profile_id = "current-profile"
            legacy = False

        memories.embedding.return_value = (QueryVector([1.0, 0.0]), None)
        memories.container.items[("owner", "memory-0")]["embedding_profile_id"] = "old-profile"
    runtime.harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": REQUEST,
        "message_ids": [], "requires_retrieval": False,
        "clarification": "What review name and role should I use?",
    })]

    events = _plan(runtime, REQUEST)

    assert any(event.get("elicitation") for event in events), events
    payload = resolver_payload(runtime.harness)
    assert FACT not in json.dumps(payload["memory"])
    assert not runtime.harness.runs.items or not any(
        row.get("plan") for row in runtime.harness.runs.items.values()
    )
    assert "PRIVATE_PROVIDER_FAILURE" not in json.dumps(events)
    memories.backfill.assert_not_called()


@pytest.mark.parametrize("mode", ["disabled", "shared"])
def test_withheld_memory_is_not_read_before_resolution(real_http_harness, memories, mode):
    runtime = real_http_harness
    if mode == "disabled":
        runtime.harness.settings["enable_fact_memory_plugin"] = False
    else:
        runtime.harness.conversations.items[("conversation-1", "conversation-1")]["is_hidden"] = True
    runtime.harness.replies = [_new_topic(REQUEST), _compose_only_plan()]

    _planned(runtime, REQUEST)

    memory = resolver_payload(runtime.harness)["memory"]
    assert memory["status"] == ("disabled" if mode == "disabled" else "unavailable")
    assert memory["messages"] == []
    memories.factory.assert_not_called()
    memories.embedding.assert_not_called()


def test_embedding_failure_preserves_instruction_memory(real_http_harness, memories):
    runtime = real_http_harness
    memories.embedding.side_effect = RuntimeError("PRIVATE_PROVIDER_FAILURE")
    runtime.harness.replies = [_new_topic(REQUEST), _compose_only_plan()]

    _planned(runtime, REQUEST)

    memory = resolver_payload(runtime.harness)["memory"]
    assert memory["status"] == "partial"
    assert INSTRUCTION in json.dumps(memory)
    assert FACT not in json.dumps(memory)
    assert "PRIVATE_PROVIDER_FAILURE" not in json.dumps(memory)


@pytest.mark.parametrize("revoked", [False, True])
def test_group_memory_requires_current_membership_before_resolution(
    real_http_harness, memories, monkeypatch, revoked,
):
    runtime = real_http_harness
    runtime.harness.settings["enable_group_workspaces"] = True
    groups = importlib.import_module("functions_group")
    membership = Mock(return_value="User")
    if revoked:
        membership.side_effect = PermissionError("PRIVATE_MEMBERSHIP_FAILURE")
    monkeypatch.setattr(groups, "assert_group_role", membership)
    memories.container.create_item({
        "id": "group-fact", "scope_id": "selected-group", "scope_type": "group",
        "memory_type": "fact", "value": "The group reviewer is Parker.",
        "value_embedding": [1.0, 0.0],
    })
    runtime.harness.replies = [_new_topic(REQUEST), _compose_only_plan()]

    events = _plan(runtime, REQUEST, doc_scope="group", active_group_ids=["selected-group"])

    membership.assert_called_with(
        "owner", "selected-group", allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
    )
    if revoked:
        assert any(event.get("error") for event in events), events
        assert "PRIVATE_MEMBERSHIP_FAILURE" not in json.dumps(events)
        memories.factory.assert_not_called()
        assert runtime.harness.model_calls == []
    else:
        assert any(event.get("plan") for event in events), events
        memory = resolver_payload(runtime.harness)["memory"]
        assert "Parker" in json.dumps(memory)
        assert FACT not in json.dumps(memory)
        assert INSTRUCTION not in json.dumps(memory)


def test_audience_change_after_clarification_blocks_private_memory_reuse(
    real_http_harness, memories,
):
    runtime = real_http_harness
    runtime.harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": REQUEST,
        "message_ids": [], "requires_retrieval": False,
        "clarification": "Which delivery date should the brief use?",
    })]
    first = _plan(runtime, REQUEST)
    elicitation = next(event["elicitation"] for event in first if event.get("elicitation"))
    runtime.harness.conversations.items[("conversation-1", "conversation-1")]["is_hidden"] = True
    memories.factory.reset_mock()
    calls = len(runtime.harness.model_calls)

    events = _plan(runtime, REQUEST, revision=1, elicitation=elicitation, elicitation_response={
        "action": "accept", "content": {"clarification": "October 30"},
    })

    assert any(event.get("error") for event in events), events
    assert len(runtime.harness.model_calls) == calls
    memories.factory.assert_not_called()


def test_audience_change_during_resolution_blocks_planner_memory_reuse(
    real_http_harness, memories,
):
    runtime = real_http_harness

    def resolve_then_share():
        runtime.harness.conversations.items[("conversation-1", "conversation-1")]["is_hidden"] = True
        return _new_topic(REQUEST)

    runtime.harness.replies = [resolve_then_share, _compose_only_plan()]

    events = _plan(runtime, REQUEST)

    assert any(event.get("error") for event in events), events
    assert len(runtime.harness.model_calls) == 1
    assert memories.embedding.call_count == 1


def test_unauthorized_conversation_does_not_read_memory_or_call_model(
    real_http_harness, memories,
):
    runtime = real_http_harness
    runtime.harness.conversations.items[("conversation-1", "conversation-1")]["user_id"] = "another-user"

    events = _plan(runtime, REQUEST)

    assert any(event.get("error") for event in events)
    memories.factory.assert_not_called()
    assert runtime.harness.model_calls == []


def test_memory_read_failure_blocks_resolution_explicitly(real_http_harness, memories):
    runtime = real_http_harness
    memories.container.fail_queries = True

    events = _plan(runtime, REQUEST)

    assert any(event.get("error") for event in events), events
    assert runtime.harness.model_calls == []
    assert "Private test" not in json.dumps(events)


def test_memory_counts_are_bounded_and_diagnostics_are_private(real_http_harness, memories, monkeypatch):
    runtime = real_http_harness
    for index in range(12):
        for kind in ("fact", "instruction"):
            memories.container.create_item({
                "id": f"{kind}-{index}", "scope_id": "owner", "scope_type": "user",
                "memory_type": kind, "value": f"PRIVATE_{kind}_{index}",
                "value_embedding": [1.0, 0.0] if kind == "fact" else None,
                "updated_at": f"2026-10-19T13:00:{index:02d}Z",
            })
    memory_module = importlib.import_module("functions_orchestration_memory")
    logs = Mock()
    monkeypatch.setattr(memory_module, "log_event", logs)
    runtime.harness.replies = [_new_topic(REQUEST), _compose_only_plan()]

    _planned(runtime, REQUEST)

    memory_messages = resolver_payload(runtime.harness)["memory"]["messages"]
    serialized = json.dumps(memory_messages)
    assert serialized.count("PRIVATE_instruction_") == 8
    assert serialized.count("PRIVATE_fact_") == 4
    lines = {line for message in memory_messages for line in message["content"].splitlines()}
    for index in range(12):
        assert (f"- PRIVATE_instruction_{index}" in lines) == (index >= 4)
        assert (f"- PRIVATE_fact_{index}" in lines) == (index >= 8)
    diagnostic = next(
        call.kwargs["extra"] for call in logs.call_args_list
        if call.args[0] == "[ORCHESTRATION] Loaded saved memory context."
    )
    assert diagnostic["instruction_available_count"] == 13
    assert diagnostic["instruction_selected_count"] == 8
    assert diagnostic["fact_selected_count"] == 4
    assert len(diagnostic["conversation_id_hash"]) == 64
    assert "PRIVATE_" not in repr(logs.call_args_list)
    assert FACT not in repr(logs.call_args_list)
    assert "conversation-1" not in repr(logs.call_args_list)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
