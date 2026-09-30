#!/usr/bin/env python3
# test_orchestration_workflow_runs_off_golden.py
"""
Functional test for the chat orchestration workflow runs setting-off golden.
Version: 0.261.211
Implemented in: 0.261.211

This test ensures that, with ``enable_chat_orchestration_workflow_runs`` off (the default) and
workflow proposals on, orchestration planning is byte-identical to the release before
workflow runs existed. It compares, against a committed golden fixture:

- the workflow planning context the ``/plan`` route stores, and the storage reads it makes,
  for a ready request, a user at the proposal cap, failed reads, a shared conversation, a
  missing WorkflowUser role, an allowlist without ``workflow_propose`` and proposals off;
- the exact messages the planner model receives with a ready context, at the cap and in a
  shared conversation;
- the repair message and the degraded plan when a proposal cannot be repaired;
- the capability resolution and unavailable reasons for each of those requests.

The fixture was captured on the unmodified base (0.261.209, before any workflow run change).
The request names an old workflow and the newest workflow is not durable, so ranking the
catalog for workflow runs would change it if that ranking leaked into proposals-only planning.

Never regenerate the fixture to make this test pass. After merging an upstream planner
change, regenerate it from the upstream commit itself (without this feature):

    python functional_tests/test_orchestration_workflow_runs_off_golden.py --write-golden
"""

import importlib
import inspect
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_setting_off_golden import (
    ACTIONS,
    AGENTS,
    BASE_SETTINGS,
    CANDIDATES,
    DEPLOYMENT,
    IDENTITY,
    PLANNER_JSON,
    _binding,
    _Completions,
    _FrozenDatetime,
)
from test_support.versioning import assert_app_version_at_least


GOLDEN = Path(__file__).resolve().parent / "test_support" / "orchestration_workflow_runs_off_golden.json"
PROPOSALS = "enable_chat_orchestration_workflows"
RUNS = "enable_chat_orchestration_workflow_runs"
OWNER = "owner"
NOW = datetime(2026, 9, 29, 12, 19, tzinfo=timezone.utc)
ZONE = "America/New_York"
MESSAGE = 'Every Monday read my email and tell me what to do this week. Also run my "Manual one" workflow now.'
UNKNOWN_AGENT = "agent-unknown-abc123"

SETTINGS = {
    **BASE_SETTINGS,
    PROPOSALS: True,
    "allow_user_agents": True,
    "allow_user_plugins": True,
    "per_user_semantic_kernel": True,
    "merge_global_semantic_kernel_with_workspace": True,
    "chat_orchestration_max_workflows_per_user": 20,
}
USER_INFO = {"userId": OWNER, "email": "owner@example.com", "roles": ["User"]}
PRIVATE = {"id": "conversation", "user_id": OWNER, "title": "Private"}
SHARED = {**PRIVATE, "chat_type": "personal_multi_user"}

AGENT_ID = "5c1e7b1f-2d3e-4f60-9bac-00000000a001"
GLOBAL_AGENT_ID = "5c1e7b1f-2d3e-4f60-9bac-00000000a002"
MAIL_ACTION_ID = "5c1e7b1f-2d3e-4f60-9bac-00000000b001"
MCP_ACTION_ID = "5c1e7b1f-2d3e-4f60-9bac-00000000b002"
SOURCE_ID = "5c1e7b1f-2d3e-4f60-9bac-00000000c001"
DOCUMENT_ID = "5c1e7b1f-2d3e-4f60-9bac-00000000d001"


def _workflow_id(index):
    return f"5c1e7b1f-2d3e-4f60-9bac-{index:012d}"


def _workflows(user_id):
    """21 live workflows and one being deleted; the oldest is the one the request names."""
    workflows = [
        {
            "id": _workflow_id(1), "name": "Weekly mail review", "description": "Reviews my mail.",
            "trigger_type": "interval",
            "schedule": {
                "kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"],
                "time_of_day": "08:00", "timezone": ZONE,
            },
            "is_enabled": True, "durable_execution": True, "updated_at": "2026-09-20T00:00:00+00:00",
        },
        {
            "id": _workflow_id(2), "name": "Contract watcher", "trigger_type": "file_sync",
            "schedule": {"unit": "hours", "value": 1},
            "file_sync": {"sources": [{"scope_type": "personal", "scope_id": OWNER, "source_id": SOURCE_ID}]},
            "is_enabled": False, "durable_execution": False, "updated_at": "2026-09-21T00:00:00+00:00",
        },
        {
            "id": _workflow_id(3), "name": "Being deleted", "trigger_type": "manual",
            "deleting": True, "durable_execution": True, "updated_at": "2026-09-22T00:00:00+00:00",
        },
    ]
    for number in range(1, 19):
        workflows.append({
            "id": _workflow_id(100 + number), "name": f"Filler workflow {number:02d}", "trigger_type": "manual",
            "is_enabled": True, "durable_execution": number % 2 == 0,
            "updated_at": f"2026-09-{number:02d}T00:00:00+00:00",
        })
    workflows.append({
        "id": _workflow_id(4), "name": "Manual one", "description": "Runs when I ask.", "trigger_type": "manual",
        "is_enabled": True, "durable_execution": True, "created_at": "2026-08-01T00:00:00+00:00",
    })
    return workflows


def _personal_agents(user_id):
    return [{
        "id": AGENT_ID, "user_id": OWNER, "name": "mail_helper", "display_name": "Mail helper",
        "description": "Reads and summarizes the user's mail.", "actions_to_load": [MAIL_ACTION_ID],
        "action_capabilities": {},
    }]


def _global_agents():
    return [{
        "id": GLOBAL_AGENT_ID, "name": "researcher", "display_name": "Researcher",
        "description": "Researches product documentation.", "actions_to_load": [{"id": MCP_ACTION_ID}],
    }]


def _actions(scope_type, scope_id):
    if scope_type == "global":
        return [{"id": MCP_ACTION_ID, "name": "docs_mcp", "display_name": "Docs MCP", "type": "mcp"}]
    return [{
        "id": MAIL_ACTION_ID, "user_id": OWNER, "name": "outlook_mail", "display_name": "Outlook mail",
        "type": "m365_email", "additionalFields": {"m365_capabilities": {"send_mail": True}},
    }]


def _sources(user_id, settings, user_info):
    return [{
        "scope_type": "personal", "scope_id": OWNER, "source_id": SOURCE_ID,
        "name": "Contracts folder", "source_type": "sharepoint", "enabled": True,
    }]


def _fail(*args):
    raise RuntimeError("storage failed")


def _readers(calls, **overrides):
    """Recording readers for every storage read the planning context can make."""
    implementations = {
        "personal_agents": _personal_agents,
        "global_agents": _global_agents,
        "actions": _actions,
        "govern": lambda user_id, scope_type, actions: actions,
        "sources": _sources,
        "workflows": _workflows,
        "quota_count": lambda user_id: 2,
        "max_tasks": lambda settings: 10,
        "default_model": lambda settings: True,
        **overrides,
    }

    def recorded(name, reader):
        def call(*args):
            calls.append(name)
            return reader(*args)
        return call

    return {name: recorded(name, reader) for name, reader in implementations.items()}


# Each case: settings changes, conversation, reader overrides.
CONTEXT_CASES = {
    "ready": ({}, PRIVATE, {}),
    "quota_reached": ({}, PRIVATE, {"quota_count": lambda user_id: 20}),
    "quota_unreadable": ({}, PRIVATE, {"quota_count": _fail}),
    "catalog_unreadable": ({}, PRIVATE, {"workflows": _fail}),
    "shared_conversation": ({}, SHARED, {}),
    "role_missing": ({"require_member_of_workflow_user": True}, PRIVATE, {}),
    "propose_not_allowlisted": ({"chat_orchestration_enabled_capabilities": ["compose"]}, PRIVATE, {}),
    "proposals_off": ({PROPOSALS: False}, PRIVATE, {}),
}
# The requests the planner is shown: ready, at the cap, and in a shared conversation.
PLANNER_CASES = ("ready", "quota_reached", "shared_conversation")
RESOLUTION_CASES = ("ready", "quota_reached", "shared_conversation", "role_missing")
# The runs setting's values that must leave planning exactly as it was.
RUNS_OFF = {"runs_absent": {}, "runs_false": {RUNS: False}, "runs_string": {RUNS: "true"}}

ANSWER_STEP = {
    "step_id": "answer", "capability_id": "compose",
    "arguments": {"instruction": "List what to focus on this week.", "knowledge_basis": "general_knowledge"},
    "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}],
}
FINAL_RESPONSE = {
    "version": "orchestration-input-binding-v1", "step_id": "answer",
    "output_name": "answer", "existing_result": None,
}
PLAIN_PLAN = {
    "kind": "plan", "intent": {"summary": "Suggest this week's priorities"},
    "steps": [ANSWER_STEP], "final_response": FINAL_RESPONSE,
}
BAD_PROPOSAL = {
    "step_id": "propose", "capability_id": "workflow_propose",
    "arguments": {
        "blueprint": {
            "name": "Monday email review",
            "trigger": {"type": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "time_of_day": "08:00"},
            "tasks": [{
                "title": "Review email", "instructions": "Read my email and list what needs my attention.",
                "runner": {"type": "agent", "agent_ref": UNKNOWN_AGENT},
            }],
            "run_as": "self",
        },
        "task_actions": [["email"]],
    },
    "inputs": {}, "outputs": [{"name": "proposal", "kind": "structured-v1"}], "delivers": ["weekly_review"],
}
PROPOSAL_PLAN = {
    "kind": "plan", "intent": {"summary": "Weekly priorities and a Monday email review."},
    "deliverables": [
        {"id": "answer", "kind": "answer", "requested": "explicit", "status": "planned",
         "description": "This week's priorities."},
        {"id": "weekly_review", "kind": "workflow", "requested": "explicit", "status": "planned",
         "description": "A Monday email review."},
    ],
    "steps": [ANSWER_STEP, BAD_PROPOSAL], "final_response": FINAL_RESPONSE,
}


def _settings(runs, changes=None):
    return {**deepcopy(SETTINGS), **deepcopy(runs), **deepcopy(changes or {})}


def _build_context(wf, runs, case_name):
    changes, conversation, overrides = CONTEXT_CASES[case_name]
    calls = []
    documents = wf.workflow_planning_documents(
        {DOCUMENT_ID: {"scope": "personal", "scope_id": OWNER, "file_name": "Weekly priorities.docx"}},
        {}, [DOCUMENT_ID],
    )
    options = {}
    if "request_text" in inspect.signature(wf.build_workflow_planning_context).parameters:
        # The /plan route passes the request; the base, captured before it existed, had no such argument.
        options["request_text"] = MESSAGE
    context = wf.build_workflow_planning_context(
        _settings(runs, changes), user_id=OWNER, user_info=deepcopy(USER_INFO), conversation=deepcopy(conversation),
        time_zone=ZONE, now=NOW, documents=documents, readers=_readers(calls, **overrides), **options,
    )
    return context, calls


def _request_context(context_module, workflow_planning):
    request_context = context_module.build_capability_request_context(
        OWNER, deepcopy(IDENTITY), MESSAGE, deepcopy(AGENTS), deepcopy(ACTIONS), allowed_user_urls=[],
        native_bridge_for_step=_binding, external_source_admission=_binding,
        external_source_authorizer=_binding, external_source_preflight=_binding,
        capture_external_source_configuration=_binding,
    )
    request_context["workflow_planning"] = deepcopy(workflow_planning)
    return request_context


def _plan(patch, settings, workflow_planning, replies):
    context_module = importlib.import_module("functions_orchestration_context")
    planner = importlib.import_module("functions_orchestration_planner")
    services = importlib.import_module("functions_orchestration_services")
    patch.setattr(context_module, "datetime", _FrozenDatetime)
    request_context = _request_context(context_module, workflow_planning)
    planner_context = context_module.build_planner_context(
        MESSAGE, candidates=deepcopy(CANDIDATES), seeds={}, ledger=None,
        signals=context_module.build_conversation_signals([], MESSAGE),
        agents=deepcopy(AGENTS), original_message=MESSAGE,
        request_resolution={"relationship": "new_topic", "resolved_message": MESSAGE},
        actions=deepcopy(ACTIONS), answered_questions=[], memory_context=None,
    )
    planner_context["export_catalog"] = []
    calls = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions(deepcopy(replies), calls)))
    patch.setattr(planner, "resolve_planner_client", lambda _settings: (client, DEPLOYMENT))
    kind, document = planner.plan_request(
        MESSAGE, planner_context, "conversation", OWNER, settings=deepcopy(settings),
        authorized_document_ids=["document-record-1"], revision=0, allow_elicitation=True,
        turn_id="turn", seeds={}, document_labels={"document-record-1": "Weekly priorities.docx"},
        request_context=request_context, planner_model=None, existing_results={},
        composition_profiles=services.composition_profiles(), export_catalog=[],
    )
    return calls, {
        "kind": kind,
        "steps": [step["capability_id"] for step in document["steps"]],
        "deliverables": document.get("deliverables"),
        "validation": document.get("validation"),
        "approval": document.get("approval"),
        "status": document.get("status"),
    }


def _resolution(settings, workflow_planning):
    context_module = importlib.import_module("functions_orchestration_context")
    registry = importlib.import_module("functions_orchestration_registry")
    unavailable = {}
    capabilities = registry.resolve_available_capabilities(
        settings, allowed_ids=settings.get("chat_orchestration_enabled_capabilities"),
        request_context=_request_context(context_module, workflow_planning), unavailable=unavailable,
        export_catalog=[],
    )
    return {"capability_ids": [capability["id"] for capability in capabilities], "unavailable": unavailable}


def _capture(patch, runs):
    """Everything the golden pins, for one value of the runs setting."""
    wf = importlib.import_module("functions_orchestration_workflow_context")
    captured = {"contexts": {}, "planner": {}, "resolution": {}}
    contexts = {}
    for case_name in CONTEXT_CASES:
        context, calls = _build_context(wf, runs, case_name)
        contexts[case_name] = context
        captured["contexts"][case_name] = {"context": context, "reads": calls}
    for case_name in PLANNER_CASES:
        changes = CONTEXT_CASES[case_name][0]
        calls, result = _plan(patch, _settings(runs, changes), contexts[case_name], [PLAIN_PLAN])
        assert len(calls) == 1
        system, user = calls[0]
        captured["planner"][case_name] = {
            "system_prompt": system["content"], "planner_payload": user["content"], "result": result,
        }
    calls, result = _plan(patch, _settings(runs), contexts["ready"], [PROPOSAL_PLAN, PROPOSAL_PLAN])
    assert len(calls) == 2
    captured["degrade"] = {"calls": calls, "result": result}
    for case_name in RESOLUTION_CASES:
        changes = CONTEXT_CASES[case_name][0]
        captured["resolution"][case_name] = _resolution(_settings(runs, changes), contexts[case_name])
    return captured


def _lines(text):
    return text.split("\n")


def _proposal_reasons(payload):
    """The two places a planner payload names why a workflow proposal is unavailable."""
    availability = payload["capability_availability"]
    return (availability["unavailable"].get("workflow_propose"), availability["deliverables"]["workflow"]["reason"])


def _with_proposal_reason(payload, reason):
    payload = deepcopy(payload)
    availability = payload["capability_availability"]
    availability["unavailable"]["workflow_propose"] = reason
    availability["deliverables"]["workflow"]["reason"] = reason
    return payload


def _golden_from(captured):
    """The committed fixture shape: readable, diffable, and exact once re-serialized.

    The shared-conversation payload is stored as the at-the-cap payload plus its own reason,
    because those two reasons are the only difference between them.
    """
    ready = captured["planner"]["ready"]
    quota = captured["planner"]["quota_reached"]
    shared = captured["planner"]["shared_conversation"]
    assert shared["system_prompt"] == quota["system_prompt"]
    quota_payload = json.loads(quota["planner_payload"])
    shared_payload = json.loads(shared["planner_payload"])
    shared_reason = _proposal_reasons(shared_payload)[0]
    assert _proposal_reasons(shared_payload) == (shared_reason, shared_reason)
    assert _with_proposal_reason(shared_payload, _proposal_reasons(quota_payload)[0]) == quota_payload
    degrade_calls = captured["degrade"]["calls"]
    assert degrade_calls[0] == [
        {"role": "system", "content": ready["system_prompt"]}, {"role": "user", "content": ready["planner_payload"]},
    ]
    return {
        "captured_from": "0.261.209 (before workflow runs)",
        "contexts": captured["contexts"],
        "system_prompts": {
            "workflow_planning": _lines(ready["system_prompt"]),
            "without_workflow_planning": _lines(quota["system_prompt"]),
        },
        "planner": {
            "ready": {
                "system_prompt": "workflow_planning",
                "planner_payload": json.loads(ready["planner_payload"]),
                "result": ready["result"],
            },
            "quota_reached": {
                "system_prompt": "without_workflow_planning",
                "planner_payload": quota_payload,
                "result": quota["result"],
            },
            "shared_conversation": {
                "system_prompt": "without_workflow_planning",
                "planner_payload_as": "quota_reached",
                "proposal_reason": shared_reason,
                "result": shared["result"],
            },
        },
        "degrade": {
            "first_call_as": "ready",
            "repair_message": _lines(degrade_calls[1][3]["content"]),
            "result": captured["degrade"]["result"],
        },
        "resolution": captured["resolution"],
    }


def _load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _pretty(value):
    return json.dumps(value, indent=1, ensure_ascii=False, sort_keys=False, default=str)


def _diff(expected, actual, label):
    return "\n".join(list(unified_diff(
        _lines(expected), _lines(actual), fromfile=f"golden {label}", tofile=f"actual {label}", lineterm="",
    ))[:80])


def _assert_same(expected, actual, label):
    if _pretty(expected) != _pretty(actual):
        raise AssertionError(_diff(_pretty(expected), _pretty(actual), label))


def _assert_payload(golden_payload, actual_content, label):
    expected = json.dumps(golden_payload, **PLANNER_JSON)
    if actual_content != expected:
        raise AssertionError(_diff(_pretty(golden_payload), _pretty(json.loads(actual_content)), label))


def _assert_matches_golden(golden, captured):
    for case_name, expected in golden["contexts"].items():
        _assert_same(expected, captured["contexts"][case_name], f"{case_name} planning context")
    for case_name, expected in golden["planner"].items():
        actual = captured["planner"][case_name]
        prompt = "\n".join(golden["system_prompts"][expected["system_prompt"]])
        assert actual["system_prompt"] == prompt, _diff(prompt, actual["system_prompt"], f"{case_name} system prompt")
        if "planner_payload_as" in expected:
            base = golden["planner"][expected["planner_payload_as"]]["planner_payload"]
            payload = json.loads(actual["planner_payload"])
            reasons = _proposal_reasons(payload)
            assert reasons == (expected["proposal_reason"], expected["proposal_reason"]), reasons
            actual_content = json.dumps(
                _with_proposal_reason(payload, _proposal_reasons(base)[0]), **PLANNER_JSON,
            )
            _assert_payload(base, actual_content, f"{case_name} planner payload")
        else:
            _assert_payload(expected["planner_payload"], actual["planner_payload"], f"{case_name} planner payload")
        _assert_same(expected["result"], actual["result"], f"{case_name} plan")
    calls = captured["degrade"]["calls"]
    first = captured["planner"][golden["degrade"]["first_call_as"]]
    assert calls[0] == [
        {"role": "system", "content": first["system_prompt"]}, {"role": "user", "content": first["planner_payload"]},
    ]
    assert calls[1][:2] == calls[0]
    assert [message["role"] for message in calls[1][2:]] == ["assistant", "user"]
    repair = "\n".join(golden["degrade"]["repair_message"])
    assert calls[1][3]["content"] == repair, _diff(repair, calls[1][3]["content"], "repair message")
    _assert_same(golden["degrade"]["result"], captured["degrade"]["result"], "degraded plan")
    _assert_same(golden["resolution"], captured["resolution"], "capability resolution")


def test_version_includes_the_workflow_runs_off_golden():
    assert_app_version_at_least("0.261.211")


def test_the_fixture_covers_the_cases_that_matter():
    golden = _load_golden()
    contexts = golden["contexts"]
    ready = contexts["ready"]["context"]
    # The named workflow is the oldest, so the top 20 by update time leaves it out.
    names = [entry["name"] for entry in ready["catalog"]["workflows"]]
    assert len(names) == 20 and "Manual one" not in names
    assert names[0] == "Contract watcher" and ready["catalog"]["workflows"][0]["durable"] is False
    assert contexts["quota_reached"]["context"]["quota_reached"] is True
    assert contexts["quota_reached"]["reads"] == ["quota_count"]
    assert contexts["quota_unreadable"]["context"]["context_unavailable"] is True
    assert contexts["catalog_unreadable"]["context"]["context_unavailable"] is True
    for case_name in ("shared_conversation", "role_missing", "propose_not_allowlisted", "proposals_off"):
        assert contexts[case_name]["reads"] == [], case_name
    assert "workflow_planning" in golden["planner"]["ready"]["planner_payload"]
    assert golden["planner"]["shared_conversation"]["proposal_reason"] == "workflow_shared_conversation"
    assert golden["degrade"]["result"]["steps"] == ["compose"]
    assert golden["resolution"]["quota_reached"]["unavailable"]["workflow_propose"] == "workflow_quota_reached"


@pytest.mark.parametrize("runs_case", sorted(RUNS_OFF))
def test_proposals_only_planning_is_byte_identical_to_the_base(modules, monkeypatch, runs_case):
    golden = _load_golden()
    captured = _capture(monkeypatch, RUNS_OFF[runs_case])
    _assert_matches_golden(golden, captured)
    for case_name in RESOLUTION_CASES:
        resolution = captured["resolution"][case_name]
        assert "workflow_run" not in resolution["capability_ids"]
        assert "workflow_run" not in resolution["unavailable"]


def _write_golden():
    from test_support.offline_bootstrap import offline_app_imports

    class _Patch:
        def __init__(self):
            self.undo = []

        def setattr(self, target, name, value):
            self.undo.append((target, name, getattr(target, name)))
            setattr(target, name, value)

        def restore(self):
            for target, name, value in reversed(self.undo):
                setattr(target, name, value)

    with offline_app_imports():
        # Same import order as the shared ``modules`` fixture, which avoids a settings cycle.
        importlib.import_module("route_backend_orchestration")
        patch = _Patch()
        try:
            captured = _capture(patch, RUNS_OFF["runs_absent"])
        finally:
            patch.restore()
    GOLDEN.write_text(_pretty(_golden_from(captured)) + "\n", encoding="utf-8")
    print(f"Wrote {GOLDEN}")


if __name__ == "__main__":
    if "--write-golden" in sys.argv:
        _write_golden()
        sys.exit(0)
    sys.exit(pytest.main([__file__, "-q"]))
