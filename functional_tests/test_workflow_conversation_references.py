#!/usr/bin/env python3
"""
Functional test for personal workflow conversation references.
Version: 0.261.381
Implemented in: 0.261.381

This test ensures that personal workflow definitions, task input bindings,
snapshot reuse/invalidation, and workflow Ask AI operations support private
conversation references while rejecting group and shared workflows.
"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import functions_workflow_assist as assist_core
from functions_workflow_assist_operations import (
    AssistApplyContext,
    AssistHandles,
    apply_assist_operations,
    build_draft_view,
)
from functions_workflow_bindings import (
    WorkflowInputError,
    load_workflow_conversation_reference,
    resolve_workflow_task_inputs,
)
from functions_workflow_definitions import (
    WorkflowDefinitionError,
    normalize_workflow_definition,
)
from test_conversation_references import setup as reference_setup  # noqa: F401
from test_support.versioning import assert_app_version_at_least


def _base_task(task_id="task-1", name="Summarize", instructions="Summarize the conversation.", **extra):
    return {
        "id": task_id,
        "type": "instructions",
        "name": name,
        "instructions": instructions,
        "order": 1,
        "runner": {"type": "inherit"},
        "document_action": {"type": "none"},
        **extra,
    }


def _conv_input(ref_id="conv-input-1", name="research_chat", conv_id="source"):
    return {
        "reference_id": ref_id,
        "name": name,
        "conversation_references": [{"kind": "conversation", "id": conv_id}],
    }


def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.381")


def test_personal_workflow_normalizes_conversation_references_and_rejects_group_or_shared():
    task = _base_task(conversation_reference_ids=["conv-input-1"])
    normalized = normalize_workflow_definition(
        {
            "definition_version": 2,
            "durable_execution": True,
            "conversation_reference_inputs": [_conv_input()],
            "tasks": [task],
        },
        {},
        [task],
        user_id="owner",
    )
    assert normalized["conversation_reference_inputs"] == [_conv_input()]
    assert normalized["tasks"][0]["conversation_reference_ids"] == ["conv-input-1"]

    # Missing task conversation reference input ID is rejected.
    bad_task = _base_task(conversation_reference_ids=["missing-id"])
    with pytest.raises(WorkflowDefinitionError):
        normalize_workflow_definition(
            {
                "definition_version": 2,
                "durable_execution": True,
                "conversation_reference_inputs": [_conv_input()],
                "tasks": [bad_task],
            },
            {},
            [bad_task],
            user_id="owner",
        )

    # Group workflows cannot bind private conversation references.
    plain_task = _base_task()
    with pytest.raises(WorkflowDefinitionError):
        normalize_workflow_definition(
            {
                "definition_version": 2,
                "durable_execution": True,
                "conversation_reference_inputs": [_conv_input()],
                "tasks": [plain_task],
            },
            {},
            [plain_task],
            user_id="owner",
            group_id="group-1",
        )

    # Shared results delivery cannot publish private conversation evidence.
    with pytest.raises(WorkflowDefinitionError):
        normalize_workflow_definition(
            {
                "definition_version": 2,
                "durable_execution": True,
                "conversation_reference_inputs": [_conv_input()],
                "tasks": [plain_task],
                "results_delivery": {
                    "version": 1,
                    "mode": "conversation",
                    "conversation_type": "shared",
                    "recipient_ids": ["11111111-2222-4333-8444-555555555555"],
                    "all_group_members": False,
                },
            },
            {},
            [plain_task],
            user_id="owner",
        )


def test_workflow_runtime_resolves_bounded_excerpts_and_validates_snapshot_consistency(reference_setup):
    service, _, messages = reference_setup
    workflow = {
        "id": "wf-1",
        "user_id": "owner",
        "durable_execution": True,
        "conversation_reference_inputs": [_conv_input()],
        "tasks": [_base_task(conversation_reference_ids=["conv-input-1"])],
    }
    cache = {}
    resolved = resolve_workflow_task_inputs(
        workflow,
        workflow["tasks"][0],
        {},
        load_output=lambda *_args, **_kwargs: ('{"kind":"text","value":"ok"}', {}),
        conversation_reference_cache=cache,
        conversation_resolver=service.resolve,
    )
    assert len(resolved["conversation_references"]) == 1
    assert resolved["conversation_reference_sources"][0]["reference_id"] == "conv-input-1"
    payload = json.loads(resolved["reference_context"])
    assert payload["conversation_references"][0]["excerpts"][0]["message_id"] == "message-1"

    # Re-running with the cached snapshot while unchanged succeeds.
    resolved_again = resolve_workflow_task_inputs(
        workflow,
        workflow["tasks"][0],
        {},
        load_output=lambda *_args, **_kwargs: ('{"kind":"text","value":"ok"}', {}),
        conversation_reference_cache=cache,
        conversation_resolver=service.resolve,
    )
    assert resolved_again["conversation_reference_sources"] == resolved["conversation_reference_sources"]

    # Modifying the underlying conversation message invalidates the cached snapshot on retry/resume.
    msg = messages.read_item("message-1", "source")
    messages.upsert_item({**msg, "content": "The project budget changed to 8000."})
    with pytest.raises(WorkflowInputError):
        load_workflow_conversation_reference(
            workflow,
            _conv_input(),
            snapshot=cache["conv-input-1"],
            resolver=service.resolve,
        )


def test_workflow_assist_attaches_and_removes_conversation_references():
    draft = {
        "definition_version": 2,
        "durable_execution": True,
        "name": "Weekly summary",
        "description": "Summarize project threads.",
        "runner_type": "model",
        "model_endpoint_id": "",
        "model_id": "",
        "trigger_type": "manual",
        "schedule": {"unit": "minutes", "value": 15},
        "is_enabled": True,
        "error_handling": {"strategy": "halt", "retry_count": 0},
        "reference_inputs": [],
        "tasks": [
            _base_task("task-1", "First task", "Review notes."),
            _base_task("task-2", "Second task", "Draft report."),
        ],
    }
    req = assist_core.parse_assist_request(
        {
            "submission_id": "11111111-2222-4333-8444-555555555555",
            "base": None,
            "instruction": "Bind ~[Title source] to the first task.",
            "draft": deepcopy(draft),
            "conversation_references": [{"kind": "conversation", "id": "source"}],
        },
        "owner",
    )
    assert req.conversation_references == [{"kind": "conversation", "id": "source"}]

    # Group workflow assist rejects conversation_references.
    with pytest.raises(assist_core.WorkflowAssistError) as err:
        assist_core.parse_assist_request(
            {
                "submission_id": "11111111-2222-4333-8444-555555555555",
                "base": None,
                "instruction": "Bind ~[Title source].",
                "draft": {**deepcopy(draft), "group_id": "group-1"},
                "conversation_references": [{"kind": "conversation", "id": "source"}],
            },
            "owner",
            group_id="group-1",
        )
    assert err.value.code == "group_workflow_unsupported"

    handles = AssistHandles(
        draft,
        user_id="owner",
        options={},
        request_conversations=[{"kind": "conversation", "id": "source", "title": "Budget thread"}],
    )
    view = build_draft_view(draft, handles)
    assert view["attached_conversations"] == [{"conversation": "conv_1", "label": "Budget thread"}]
    assert "source" not in json.dumps(view)

    bound_draft, _ = apply_assist_operations(
        draft,
        {
            "outcome": "changed",
            "reply": "Bound Budget thread to First task.",
            "operations": [
                {"op": "bind_conversation_reference", "conversation": "conv_1", "tasks": ["task_1"]},
            ],
        },
        handles,
        AssistApplyContext(),
    )
    assert len(bound_draft["conversation_reference_inputs"]) == 1
    ref_id = bound_draft["conversation_reference_inputs"][0]["reference_id"]
    assert bound_draft["tasks"][0]["conversation_reference_ids"] == [ref_id]
    assert bound_draft["tasks"][1]["conversation_reference_ids"] == []

    # Unbinding removes the conversation reference from the draft and task bindings.
    handles_after = AssistHandles(bound_draft, user_id="owner", options={})
    ref_handle = handles_after.conversation_reference_handles[ref_id]
    unbound_draft, _ = apply_assist_operations(
        bound_draft,
        {
            "outcome": "changed",
            "reply": "Removed Budget thread.",
            "operations": [
                {"op": "unbind_conversation_reference", "reference": ref_handle},
            ],
        },
        handles_after,
        AssistApplyContext(),
    )
    assert unbound_draft["conversation_reference_inputs"] == []
    assert unbound_draft["tasks"][0]["conversation_reference_ids"] == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
