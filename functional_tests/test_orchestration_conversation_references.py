#!/usr/bin/env python3
"""
Functional test for orchestration conversation references and capabilities.
Version: 0.261.381
Implemented in: 0.261.381

This test ensures that orchestration seeds, planner context, plan inputs,
capability registry/adapters, and plan-editor Ask AI revisions enforce bounded
private conversation reference rules.
"""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from functions_conversation_references import ConversationReferenceError
from functions_orchestration_conversation_capabilities import (
    conversation_request_allowed,
    resolve_conversation_snapshot,
    run_conversation_capability,
)
from test_conversation_references import ReferenceContainer, setup as reference_setup  # noqa: F401
from test_support.orchestration_research import stubbed_orchestration_imports
from test_support.versioning import assert_app_version_at_least


SETTINGS = {
    "enable_chat_orchestration": True,
    "enable_user_workspace": True,
    "chat_orchestration_max_steps": 6,
}


def _binding(step_id, output="answer"):
    return {
        "version": "orchestration-input-binding-v1",
        "step_id": step_id,
        "output_name": output,
        "existing_result": None,
    }


def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.381")


def test_registry_and_adapters_expose_conversation_capabilities():
    with stubbed_orchestration_imports():
        import functions_orchestration_adapters as adapters
        import functions_orchestration_registry as registry

        for cap_id, role in (
            ("conversation_search", registry.ROLE_GATHER),
            ("conversation_read", registry.ROLE_GATHER),
            ("conversation_send", registry.ROLE_REASON),
        ):
            descriptor = registry.get_capability(cap_id, contract_version=2)
            assert descriptor is not None
            assert descriptor["role"] == role
            assert descriptor["result_outputs"] == {"result": "structured-v1"}
            adapter = adapters.get_adapter(cap_id, contract_version=2)
            assert callable(adapter)


def test_seeds_planner_context_and_plan_inputs_preserve_conversation_references():
    with stubbed_orchestration_imports():
        import functions_orchestration_context as context_mod
        import functions_orchestration_schema as schema

        seeds = context_mod.resolve_seeds({
            "conversation_references": [
                {"kind": "conversation", "id": "source-1", "message_ids": ["msg-1"]},
            ],
        })
        assert seeds["conversation_references"] == [
            {"kind": "conversation", "id": "source-1", "message_ids": ["msg-1"]},
        ]

        planner_ctx = context_mod.build_planner_context("Summarize earlier chat.", seeds=seeds)
        assert planner_ctx["conversation_references"] == seeds["conversation_references"]
        assert planner_ctx["user_selected"]["conversation_references"] == seeds["conversation_references"]

        plan = schema.normalize_plan(
            {
                "planner_contract_version": 2,
                "steps": [
                    {
                        "step_id": "read_conv",
                        "capability_id": "conversation_read",
                        "arguments": {
                            "conversation_references": seeds["conversation_references"],
                            "query": "budget",
                        },
                    },
                    {
                        "step_id": "draft",
                        "capability_id": "compose",
                        "arguments": {"instruction": "Summarize the budget."},
                        "depends_on": ["read_conv"],
                        "inputs": {
                            "conv": {
                                "binding": _binding("read_conv", "result"),
                                "allow_partial": False,
                            },
                        },
                        "outputs": [{"name": "answer", "kind": "markdown-v1"}],
                    },
                ],
                "final_response": _binding("draft"),
            },
            "conv-dest",
            "owner",
            settings=SETTINGS,
            seeds=seeds,
            available_capability_ids=["conversation_read", "compose"],
            contract_version=2,
        )
        assert plan["inputs"]["conversation_references"] == seeds["conversation_references"]

        # Self-referencing the active conversation in conversation_read is rejected.
        with pytest.raises(schema.PlanValidationError):
            schema.normalize_plan(
                {
                    "planner_contract_version": 2,
                    "steps": [
                        {
                            "step_id": "read_self",
                            "capability_id": "conversation_read",
                            "arguments": {
                                "conversation_references": [{"kind": "conversation", "id": "conv-dest"}],
                            },
                        },
                    ],
                },
                "conv-dest",
                "owner",
                settings=SETTINGS,
                available_capability_ids=["conversation_read", "compose"],
                contract_version=2,
            )


def test_conversation_search_and_read_adapter_and_snapshot_consistency(reference_setup, monkeypatch):
    service, conversations, messages = reference_setup
    import functions_conversation_reference_runtime as runtime_mod

    monkeypatch.setattr(runtime_mod, "get_conversation_reference_service", lambda: service)

    assert conversation_request_allowed({"user_message": "What did we decide in the previous chat?"}) is True
    assert conversation_request_allowed({"user_message": "Hello world"}) is False
    assert conversation_request_allowed({
        "user_message": "Summarize this",
        "conversation_references": [{"kind": "conversation", "id": "source"}],
    }) is True

    from functions_orchestration_result_contracts import ProducerIdentity, ResultRef, TaskResult
    from functions_orchestration_results import OrchestrationResults

    persisted = []

    class FakeResultService(OrchestrationResults):
        def __init__(self):
            pass

        def persist_task_result(self, **kwargs):
            persisted.append(kwargs)
            ref = ResultRef(
                kwargs["producer"], "result", "structured-v1",
                "a" * 64, "b" * 64, 64, 1, kwargs["outputs"][0].completeness,
            )
            return TaskResult(kwargs["producer"], kwargs["role"], "complete", (ref,))

    ctx = SimpleNamespace(
        user_id="owner",
        conversation_id="target",
        run_id="run-1",
        attempt_root_run_id="run-1",
        user_message="Search my previous chat for budget.",
        seeds={},
        result_service=FakeResultService(),
        result_producer=lambda step: ProducerIdentity(
            "owner", "target", "run-1", 1, step["step_id"], step["capability_id"], "conversation-read-v1",
        ),
        result_guard_token_for_step=lambda step_id: "token-1",
        result_input_fingerprint_for_step=lambda step_id: "fp-1",
    )

    search_step = {
        "step_id": "s_search",
        "capability_id": "conversation_search",
        "role": "gather",
        "arguments": {"query": "Title", "limit": 5},
    }
    search_res = run_conversation_capability(search_step, ctx, settings=SETTINGS, user_id="owner")
    assert search_res["status"] == "completed"
    assert [c["id"] for c in persisted[-1]["outputs"][0].value["conversations"]] == ["source"]

    # Without user intent or attached references, conversation_search is refused.
    ctx_disallowed = deepcopy(ctx)
    ctx_disallowed.user_message = "Write a poem about clouds."
    with pytest.raises(ConversationReferenceError):
        run_conversation_capability(search_step, ctx_disallowed, settings=SETTINGS, user_id="owner")

    read_step = {
        "step_id": "s_read",
        "capability_id": "conversation_read",
        "role": "gather",
        "arguments": {
            "conversation_references": [{"kind": "conversation", "id": "source"}],
            "query": "budget",
        },
    }
    read_res = run_conversation_capability(read_step, ctx, settings=SETTINGS, user_id="owner")
    assert read_res["status"] == "completed"
    snapshot = persisted[-1]["outputs"][0].value
    assert snapshot["excerpts"][0]["message_id"] == "message-1"

    # Re-resolving unchanged snapshot succeeds.
    reused = resolve_conversation_snapshot(
        "owner", [{"kind": "conversation", "id": "source"}],
        destination_id="target", snapshot=snapshot, resolver=service.resolve,
    )
    assert reused["revision"] == snapshot["revision"]

    # Mutating the referenced message invalidates the snapshot on reuse.
    msg = messages.read_item("message-1", "source")
    messages.upsert_item({**msg, "content": "The project budget changed to 9900."})
    with pytest.raises(ConversationReferenceError) as err:
        run_conversation_capability(read_step, ctx, settings=SETTINGS, user_id="owner")
    assert err.value.code == "conversation_reference_changed"


def test_plan_editing_authorizes_conversation_references_and_records_revisions(reference_setup, monkeypatch):
    service, _, _ = reference_setup
    from types import ModuleType

    fake_runs = ModuleType("functions_orchestration_runs")
    fake_runs.RUN_RECORD_TYPE = "orchestration_run"
    fake_runs._is_run_record = lambda r: isinstance(r, dict)
    fake_runs._strip_cosmos_metadata = lambda r: {k: v for k, v in r.items() if not k.startswith("_")}
    fake_runs.cosmos_orchestration_runs_container = None
    fake_planner = ModuleType("functions_orchestration_planner")
    fake_planner.conversation_retrieval_allowed = lambda *a, **kw: False
    fake_planner.plan_request = lambda *a, **kw: ("plan", {})
    monkeypatch.setitem(sys.modules, "functions_orchestration_runs", fake_runs)
    monkeypatch.setitem(sys.modules, "functions_orchestration_planner", fake_planner)
    with stubbed_orchestration_imports():
        import functions_orchestration_plan_editing as plan_editing
        import functions_orchestration_plan_revisions as plan_revisions

        monkeypatch.setattr(plan_editing, "resolve_conversation_references", service.resolve)

        normalized_req = plan_revisions._normalize_request(
            {
                "conversation_id": "target",
                "expected_version": "v1",
                "submission_id": "11111111-2222-4333-8444-555555555555",
                "action": "ask",
                "instruction": "Include ~[Title source] in the plan.",
                "conversation_references": [{"kind": "conversation", "id": "source"}],
            },
            "target",
        )
        assert normalized_req["conversation_references"] == [{"kind": "conversation", "id": "source"}]

        record = {"conversation_id": "target", "seeds": {}}
        resolved_refs = plan_editing.resolve_plan_edit_conversation_references(
            record, [{"kind": "conversation", "id": "source"}], "owner",
            conversation_id="target", query="budget",
        )
        assert resolved_refs == [{"kind": "conversation", "id": "source"}]

        # Self-reference or unowned conversation is rejected with PlanRevisionError.
        with pytest.raises(plan_editing.PlanRevisionError):
            plan_editing.resolve_plan_edit_conversation_references(
                record, [{"kind": "conversation", "id": "target"}], "owner",
                conversation_id="target",
            )
        with pytest.raises(plan_editing.PlanRevisionError):
            plan_editing.resolve_plan_edit_conversation_references(
                record, [{"kind": "conversation", "id": "source"}], "intruder",
                conversation_id="target",
            )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
