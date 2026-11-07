#!/usr/bin/env python3
"""
Functional test for orchestration and personal workflow conversation sends.
Version: 0.261.381
Implemented in: 0.261.381

This test ensures that conversation_send enforces a manual approval floor and
external-effect tracking in orchestration plans, requires durable task approval
in personal workflows, validates exact approved send scope at admission and
dispatch, and prevents duplicate or cyclic handoffs.
"""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from functions_conversation_handoffs import (
    ConversationHandoffError,
    ConversationHandoffService,
    ConversationHandoffStore,
)
from functions_conversation_references import normalize_conversation_references
from functions_orchestration_conversation_capabilities import (
    normalize_conversation_send,
    run_conversation_capability,
    validate_conversation_send_approval,
)
from functions_workflow_conversation_references import (
    enqueue_workflow_conversation_send,
    validate_workflow_conversation_send_approval,
)
from functions_workflow_definitions import (
    WorkflowDefinitionError,
    normalize_workflow_definition,
)
from test_conversation_references import ReferenceContainer, setup as reference_setup  # noqa: F401
from test_support.m365 import CosmosContainer
from test_support.orchestration_research import stubbed_orchestration_imports
from test_support.versioning import assert_app_version_at_least


SETTINGS = {
    "enable_chat_orchestration": True,
    "enable_user_workspace": True,
    "chat_orchestration_max_steps": 6,
}


class HandoffContainer(CosmosContainer):
    """SDK-default container with batch support for handoff admission."""

    def execute_item_batch(self, batch_operations, partition_key):
        from azure.core import MatchConditions

        for op in batch_operations:
            kind = op[0]
            args = op[1]
            kwargs = op[2] if len(op) > 2 else {}
            if kind == "replace":
                item_id, body = args
                etag = kwargs.get("if_match_etag")
                self.replace_item(
                    item_id, body, etag=etag,
                    match_condition=MatchConditions.IfNotModified if etag else None,
                )
            elif kind == "create":
                (body,) = args
                self.create_item(body)
        return []


def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.381")


def test_conversation_send_enforces_manual_approval_floor_and_external_effects():
    with stubbed_orchestration_imports():
        import functions_orchestration_registry as registry
        import functions_orchestration_schema as schema

        assert "conversation_send" in registry.approval_floor_capability_ids()
        assert "conversation_send" in registry.external_effect_capability_ids()

        send_step = {
            "step_id": "send_followup",
            "capability_id": "conversation_send",
            "arguments": {
                "destination_conversation_id": "target",
                "instruction": "Draft the Q3 budget summary from this conversation.",
                "conversation_references": [{"kind": "conversation", "id": "source"}],
            },
        }
        plan = schema.normalize_plan(
            {"planner_contract_version": 2, "steps": [send_step]},
            "source",
            "owner",
            settings=SETTINGS,
            approval_mode="auto",
            available_capability_ids=["conversation_send", "compose"],
            contract_version=2,
        )
        assert plan["status"] == schema.PLAN_STATUS_AWAITING_APPROVAL
        assert plan["approval"]["mode"] == "manual"
        assert plan["approval"]["state"] == schema.APPROVAL_STATE_PENDING
        assert plan["approval"]["floor"] == {"mode": "manual", "reason": "conversation_send"}

        # Sending to the same conversation or referencing the destination as source is rejected.
        with pytest.raises(schema.PlanValidationError):
            schema.normalize_plan(
                {
                    "planner_contract_version": 2,
                    "steps": [
                        {
                            "step_id": "self_send",
                            "capability_id": "conversation_send",
                            "arguments": {
                                "destination_conversation_id": "source",
                                "instruction": "Send to self.",
                            },
                        },
                    ],
                },
                "source",
                "owner",
                settings=SETTINGS,
                available_capability_ids=["conversation_send"],
                contract_version=2,
            )


def test_orchestration_conversation_send_approval_and_deduplication(reference_setup, monkeypatch):
    ref_service, _, _ = reference_setup
    handoff_container = HandoffContainer("destination_conversation_id")
    store = ConversationHandoffStore(handoff_container)

    runs = {
        "run-1": {
            "id": "run-1",
            "user_id": "owner",
            "conversation_id": "source",
            "status": "running",
            "plan": {
                "revision": 2,
                "approval": {"state": "approved", "mode": "manual", "approved_by": "owner"},
                "steps": [
                    {
                        "step_id": "send_1",
                        "capability_id": "conversation_send",
                        "enabled": True,
                        "arguments": {
                            "destination_conversation_id": "target",
                            "instruction": "Summarize the budget numbers.",
                            "conversation_references": [{"kind": "conversation", "id": "source"}],
                        },
                    },
                ],
            },
        },
    }

    from types import ModuleType

    runs_mod = ModuleType("functions_orchestration_runs")
    runs_mod.get_orchestration_run = lambda run_id, user_id, conversation_id, strict=True: (
        runs.get(run_id)
        if runs.get(run_id, {}).get("user_id") == user_id
        and runs.get(run_id, {}).get("conversation_id") == conversation_id
        else None
    )
    monkeypatch.setitem(sys.modules, "functions_orchestration_runs", runs_mod)

    handoff_service = ConversationHandoffService(
        store,
        authorize=ref_service.authorize,
        normalize_references=normalize_conversation_references,
        resolve_references=ref_service.resolve,
        resolve_destination=lambda user_id, dest_id: {"conversation_id": dest_id, "revision": "cfg-1"},
        generate=lambda job, evidence, before_effect: (before_effect(), {"id": job["destination_message_id"]})[1],
        validate_approval=lambda job: validate_conversation_send_approval(
            job["user_id"], job["source_conversation_id"], job["destination_conversation_id"],
            job["instruction"], job["conversation_references"], job["approval"],
        ),
        mark_unread=lambda job: None,
    )

    import functions_conversation_handoff_runtime as handoff_runtime
    import functions_conversation_reference_runtime as ref_runtime

    monkeypatch.setattr(ref_runtime, "get_conversation_reference_service", lambda: ref_service)
    monkeypatch.setattr(handoff_runtime, "get_handoff_service", lambda: handoff_service)

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
        conversation_id="source",
        run_id="run-1",
        attempt_root_run_id="run-1",
        conversation_send_plan_revision=2,
        user_message="Send the budget summary to target.",
        seeds={},
        result_service=FakeResultService(),
        result_producer=lambda step: ProducerIdentity(
            "owner", "source", "run-1", 1, step["step_id"], step["capability_id"], "conversation-send-v1",
        ),
        result_guard_token_for_step=lambda step_id: "token-1",
        result_input_fingerprint_for_step=lambda step_id: "fp-1",
    )

    step = deepcopy(runs["run-1"]["plan"]["steps"][0])
    step["role"] = "reason"
    result = run_conversation_capability(step, ctx, settings=SETTINGS, user_id="owner")
    assert result["status"] == "completed"
    queued = persisted[-1]["outputs"][0].value
    assert queued["status"] == "queued"

    # Retrying from the same attempt_root_run_id + step_id deduplicates the handoff.
    result_retry = run_conversation_capability(step, ctx, settings=SETTINGS, user_id="owner")
    assert result_retry["status"] == "completed"
    assert persisted[-1]["outputs"][0].value["id"] == queued["id"]

    # Tampering with the instruction or unapproving the plan causes dispatch to fail closed.
    runs["run-1"]["plan"]["steps"][0]["arguments"]["instruction"] = "Changed instruction"
    dispatched = handoff_service.dispatch("target")
    assert dispatched["status"] == "failed"
    assert dispatched["error_code"] == "approval_required"


def test_workflow_conversation_send_requires_durable_approval_and_validates_scope(reference_setup):
    ref_service, _, _ = reference_setup
    handoff_container = HandoffContainer("destination_conversation_id")
    store = ConversationHandoffStore(handoff_container)

    send_task = {
        "id": "t1",
        "type": "instructions",
        "name": "Send",
        "instructions": "Send summary.",
        "order": 1,
        "runner": {"type": "inherit"},
        "document_action": {"type": "none"},
        "conversation_send": {
            "destination_conversation_id": "target",
            "instruction": "Follow up on the budget.",
            "conversation_references": [{"kind": "conversation", "id": "source"}],
        },
    }
    # Non-durable workflow cannot configure conversation_send.
    with pytest.raises(WorkflowDefinitionError):
        normalize_workflow_definition(
            {"definition_version": 2, "durable_execution": False, "tasks": [send_task]},
            {},
            [send_task],
            user_id="owner",
        )

    normalized = normalize_workflow_definition(
        {"definition_version": 2, "durable_execution": True, "tasks": [send_task]},
        {},
        [send_task],
        user_id="owner",
    )
    workflow = {"id": "wf-send", "user_id": "owner", "conversation_id": "source", **normalized}
    assert workflow["tasks"][0]["approval"]["required"] is True

    runtime_control = {
        "state": "running",
        "memory": {
            "decisions": [
                {"unit_id": "task:t1", "input_digest": "digest-1", "choice": "approve"},
            ],
        },
    }
    runtime_store = SimpleNamespace(read=lambda: runtime_control)

    handoff_service = ConversationHandoffService(
        store,
        authorize=ref_service.authorize,
        normalize_references=normalize_conversation_references,
        resolve_references=ref_service.resolve,
        resolve_destination=lambda user_id, dest_id: {"conversation_id": dest_id, "revision": "cfg-1"},
        generate=lambda job, evidence, before_effect: (before_effect(), {"id": job["destination_message_id"]})[1],
        validate_approval=lambda job: validate_workflow_conversation_send_approval(
            job["user_id"], job["source_conversation_id"], job["destination_conversation_id"],
            job["instruction"], job["conversation_references"], job["approval"],
            load_workflow=lambda uid, wid: workflow if (uid, wid) == ("owner", "wf-send") else None,
            runtime_store_factory=lambda wf_doc, rid: runtime_store,
        ),
        mark_unread=lambda job: None,
    )

    queued = enqueue_workflow_conversation_send(
        workflow,
        "wf-run-1",
        workflow["tasks"][0],
        actor_user_id="owner",
        source_conversation_id="source",
        input_digest="digest-1",
        enqueuer=handoff_service.enqueue,
    )
    assert queued["status"] == "queued"
    completed = handoff_service.dispatch("target")
    assert completed["status"] == "completed"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
