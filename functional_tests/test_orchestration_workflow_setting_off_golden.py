#!/usr/bin/env python3
# test_orchestration_workflow_setting_off_golden.py
"""
Functional test for the chat orchestration workflow proposal setting-off golden.
Version: 0.261.200
Implemented in: 0.261.200

This test ensures that, with ``enable_chat_orchestration_workflows`` off (the default),
orchestration planning is byte-identical to the release before workflow proposals
existed. It compares, against a committed golden fixture:

- the exact messages the planner model receives for a fixed request and context;
- the capability resolution and deliverable availability the planner is shown;
- the planner-facing strict-mode error for a ``workflow`` deliverable kind.

The fixture was captured on the unmodified base (0.261.197, before any workflow
proposal change). With the setting on but workflow proposals unavailable to this
request (a shared conversation, or a missing WorkflowUser role), the planner's system
prompt stays byte-identical and its context differs only in the documented keys that
tell it the ``workflow`` deliverable is unavailable and why.

Never regenerate the fixture to make this test pass. After merging an upstream planner
change, regenerate it from the upstream commit itself (without this feature):

    python functional_tests/test_orchestration_workflow_setting_off_golden.py --write-golden
"""

import importlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from difflib import unified_diff
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_support.versioning import assert_app_version_at_least


GOLDEN = Path(__file__).resolve().parent / "test_support" / "orchestration_workflow_setting_off_golden.json"
SETTING = "enable_chat_orchestration_workflows"
FROZEN_NOW = datetime(2026, 9, 27, 13, 0, tzinfo=timezone.utc)
MESSAGE = "Every Monday read my email and tell me what I should do this week."
DEPLOYMENT = "golden-deployment"
PLANNER_JSON = {"ensure_ascii": False, "separators": (",", ":"), "default": str}

BASE_SETTINGS = {
    "enable_chat_orchestration": True,
    "chat_orchestration_enabled_capabilities": [],
    "enable_semantic_kernel": True,
    "enable_chat_orchestration_actions": True,
    "enable_web_search": True,
    "enable_user_workspace": True,
    "enable_group_workspaces": False,
    "enable_public_workspaces": False,
    "enable_image_generation": False,
    "enable_url_access": False,
    "enable_source_review": False,
    "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
}
IDENTITY = {"user_email": "owner@example.com", "user_roles": ["User"], "user_enable_agents": True}
AGENTS = [{
    "id": "agent-record-1", "name": "mail_helper", "display_name": "Mail helper",
    "description": "Reads and summarizes the user's mail.", "action_labels": ["Outlook mail"],
    "scope_type": "personal", "scope_id": "owner", "is_global": False,
}]
ACTIONS = [{
    "action_ref": "personal:owner:action-record-1", "id": "action-record-1", "name": "crm_lookup",
    "display_name": "CRM lookup", "description": "Looks up customer accounts.", "type": "openapi",
    "scope_type": "personal", "scope_id": "owner", "scope_label": "Personal",
}]
CANDIDATES = [{
    "document_id": "document-record-1", "file_name": "Weekly priorities.docx", "title": "Weekly priorities",
    "source_kind": "narrative", "scope": "personal", "score": 0.91,
}]
# A context the workflow proposal feature would treat as ready: private, in quota, with
# catalogs. With the setting off it must be ignored completely.
READY_WORKFLOW_PLANNING = {
    "conversation_private": True,
    "quota_reached": False,
    "time_zone": "America/New_York",
    "request_local_time": "Current date and time: Sunday, 27 September 2026, 09:00 (America/New_York)",
    "limits": {"max_tasks": 5, "min_interval_seconds": 3600, "quota_used": 1, "quota_limit": 20},
    "catalog": {
        "agents": [{"handle": "agent-mail-helper-a1b2c3", "name": "Mail helper", "action_kinds": ["email"]}],
        "sources": [],
        "documents": [{"handle": "doc-weekly-priorities-d4e5f6", "name": "Weekly priorities.docx"}],
        "workflows": [],
    },
    "handles": {
        "agents": {"agent-mail-helper-a1b2c3": {"id": "agent-record-1", "name": "mail_helper", "is_global": False}},
        "documents": {"doc-weekly-priorities-d4e5f6": {
            "document_id": "document-record-1", "scope_type": "personal", "scope_id": "owner",
        }},
        "sources": {},
        "workflows": {},
    },
}

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
WORKFLOW_PLAN = {
    **PLAIN_PLAN,
    "deliverables": [
        {
            "id": "answer", "kind": "answer", "requested": "explicit", "status": "planned",
            "description": "This week's priorities.",
        },
        {
            "id": "weekly_review", "kind": "workflow", "requested": "explicit", "status": "planned",
            "description": "A workflow that reviews email every Monday.",
        },
    ],
}


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz is not None else FROZEN_NOW.replace(tzinfo=None)


class _Completions:
    def __init__(self, replies, calls):
        self.replies = [json.dumps(reply) for reply in replies]
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs["messages"]))
        content = self.replies.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop", message=SimpleNamespace(content=content, refusal=None),
            )],
            usage=None,
        )


def _binding(*args, **kwargs):
    raise AssertionError("Planning must not call a runtime binding.")


def _case(name):
    """Settings and request context for one named case."""
    settings = dict(BASE_SETTINGS)
    identity = deepcopy(IDENTITY)
    workflow_planning = deepcopy(READY_WORKFLOW_PLANNING)
    if name == "setting_absent":
        pass
    elif name == "setting_false":
        settings[SETTING] = False
    elif name == "setting_false_without_workflow_access":
        settings.update({SETTING: False, "allow_user_workflows": False, "require_member_of_workflow_user": True})
        workflow_planning = {"conversation_private": False, "quota_reached": None}
    elif name == "shared_conversation":
        settings[SETTING] = True
        workflow_planning = {"conversation_private": False, "quota_reached": None}
    elif name == "role_missing":
        settings.update({SETTING: True, "require_member_of_workflow_user": True})
        workflow_planning = {"conversation_private": True, "quota_reached": None}
    else:
        raise AssertionError(name)
    return settings, identity, workflow_planning


def _capture(monkeypatch, case_name, replies):
    context_module = importlib.import_module("functions_orchestration_context")
    planner = importlib.import_module("functions_orchestration_planner")
    registry = importlib.import_module("functions_orchestration_registry")
    deliverables = importlib.import_module("functions_orchestration_deliverables")
    schema = importlib.import_module("functions_orchestration_schema")
    services = importlib.import_module("functions_orchestration_services")
    monkeypatch.setattr(context_module, "datetime", _FrozenDatetime)

    settings, identity, workflow_planning = _case(case_name)
    request_context = context_module.build_capability_request_context(
        "owner", identity, MESSAGE, deepcopy(AGENTS), deepcopy(ACTIONS), allowed_user_urls=[],
        native_bridge_for_step=_binding, external_source_admission=_binding,
        external_source_authorizer=_binding, external_source_preflight=_binding,
        capture_external_source_configuration=_binding,
    )
    request_context["workflow_planning"] = workflow_planning
    signals = context_module.build_conversation_signals([], MESSAGE)
    planner_context = context_module.build_planner_context(
        MESSAGE, candidates=deepcopy(CANDIDATES), seeds={}, ledger=None, signals=signals,
        agents=deepcopy(AGENTS), original_message=MESSAGE,
        request_resolution={"relationship": "new_topic", "resolved_message": MESSAGE},
        actions=deepcopy(ACTIONS), answered_questions=[], memory_context=None,
    )
    planner_context["export_catalog"] = []

    calls = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions(replies, calls)))
    monkeypatch.setattr(planner, "resolve_planner_client", lambda _settings: (client, DEPLOYMENT))
    kind, document = planner.plan_request(
        MESSAGE, planner_context, "conversation", "owner", settings=deepcopy(settings),
        authorized_document_ids=["document-record-1"], revision=0, allow_elicitation=True,
        turn_id="turn", seeds={}, document_labels={"document-record-1": "Weekly priorities.docx"},
        request_context=request_context, planner_model=None, existing_results={},
        composition_profiles=services.composition_profiles(), export_catalog=[],
    )

    unavailable = {}
    capabilities = registry.resolve_available_capabilities(
        settings, allowed_ids=settings.get("chat_orchestration_enabled_capabilities"),
        request_context=request_context, unavailable=unavailable, export_catalog=[],
    )
    availability = deliverables.build_deliverable_availability(
        settings, capabilities=capabilities, unavailable=unavailable, export_catalog=[],
    )
    try:
        schema.normalize_plan(
            deepcopy(WORKFLOW_PLAN), "conversation", "owner", settings=deepcopy(settings),
            available_capability_ids=[capability["id"] for capability in capabilities],
            turn_id="turn", seeds={}, deliverable_availability=availability,
        )
        strict_error = None
    except schema.PlanValidationError as exc:
        strict_error = {"code": exc.code, "rule": exc.rule, "message": str(exc)}
    return {
        "calls": calls,
        "kind": kind,
        "result": {
            "steps": [step["capability_id"] for step in document["steps"]],
            "deliverables": document.get("deliverables"),
            "validation": document.get("validation"),
        },
        "capability_ids": [capability["id"] for capability in capabilities],
        "unavailable": unavailable,
        "availability": availability,
        "strict_error": strict_error,
    }


def _lines(text):
    return text.split("\n")


def _golden_from(plain, workflow):
    """The committed fixture shape: readable, diffable, and exact once re-serialized."""
    (system, user), = [plain["calls"][0]]
    first, second = workflow["calls"]
    assert first == plain["calls"][0]
    assert second[:2] == first and [message["role"] for message in second[2:]] == ["assistant", "user"]
    return {
        "captured_from": "0.261.197 (before workflow proposals)",
        "system_prompt": _lines(system["content"]),
        "planner_payload": json.loads(user["content"]),
        "repair_message": _lines(second[3]["content"]),
        "plain_result": {"kind": plain["kind"], **plain["result"]},
        "workflow_result": {"kind": workflow["kind"], **workflow["result"]},
        "capability_ids": plain["capability_ids"],
        "unavailable": plain["unavailable"],
        "strict_workflow_kind_error": plain["strict_error"],
    }


def _load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _diff(expected, actual, label):
    return "\n".join(list(unified_diff(
        _lines(expected), _lines(actual), fromfile=f"golden {label}", tofile=f"actual {label}", lineterm="",
    ))[:80])


def _pretty(value):
    return json.dumps(value, indent=1, ensure_ascii=False, sort_keys=False, default=str)


def _assert_system_prompt(golden, actual):
    expected = "\n".join(golden["system_prompt"])
    assert actual == expected, _diff(expected, actual, "system prompt")


def _assert_payload(golden_payload, actual_content):
    expected = json.dumps(golden_payload, **PLANNER_JSON)
    if actual_content != expected:
        raise AssertionError(_diff(_pretty(golden_payload), _pretty(json.loads(actual_content)), "planner payload"))


def _strip_documented_workflow_keys(payload):
    """Remove only what tells the planner that a workflow deliverable is unavailable, and why."""
    payload = deepcopy(payload)
    availability = payload["capability_availability"]
    availability["unavailable"].pop("workflow_propose", None)
    deliverables = availability["deliverables"]
    deliverables.pop("workflow", None)
    for reason in [reason for reason in deliverables["unavailable_reasons"] if reason.startswith("workflow_")]:
        deliverables["unavailable_reasons"].pop(reason)
    return payload


def test_version_includes_the_setting_off_golden():
    assert_app_version_at_least("0.261.200")


@pytest.mark.parametrize("case_name", [
    "setting_absent", "setting_false", "setting_false_without_workflow_access",
])
def test_setting_off_planning_is_byte_identical_to_the_base(modules, monkeypatch, case_name):
    golden = _load_golden()
    plain = _capture(monkeypatch, case_name, [PLAIN_PLAN])
    workflow = _capture(monkeypatch, case_name, [WORKFLOW_PLAN, PLAIN_PLAN])

    assert len(plain["calls"]) == 1 and len(workflow["calls"]) == 2
    system, user = plain["calls"][0]
    _assert_system_prompt(golden, system["content"])
    _assert_payload(golden["planner_payload"], user["content"])
    assert workflow["calls"][0] == plain["calls"][0]
    assert workflow["calls"][1][:2] == plain["calls"][0]
    expected_repair = "\n".join(golden["repair_message"])
    actual_repair = workflow["calls"][1][3]["content"]
    assert actual_repair == expected_repair, _diff(expected_repair, actual_repair, "repair message")
    assert {"kind": plain["kind"], **plain["result"]} == golden["plain_result"]
    assert {"kind": workflow["kind"], **workflow["result"]} == golden["workflow_result"]


@pytest.mark.parametrize("case_name", [
    "setting_absent", "setting_false", "setting_false_without_workflow_access",
])
def test_setting_off_resolution_and_strict_error_match_the_base(modules, monkeypatch, case_name):
    golden = _load_golden()
    captured = _capture(monkeypatch, case_name, [PLAIN_PLAN])

    assert captured["capability_ids"] == golden["capability_ids"]
    assert captured["unavailable"] == golden["unavailable"]
    assert "workflow_propose" not in captured["capability_ids"]
    assert "workflow_propose" not in captured["unavailable"]
    availability = golden["planner_payload"]["capability_availability"]["deliverables"]
    assert json.dumps(captured["availability"], **PLANNER_JSON) == json.dumps(availability, **PLANNER_JSON)
    assert "workflow" not in captured["availability"]
    assert captured["strict_error"] == golden["strict_workflow_kind_error"]
    assert captured["strict_error"]["rule"] == "invalid_deliverable_kind"


@pytest.mark.parametrize("case_name", ["shared_conversation", "role_missing"])
def test_setting_on_but_unavailable_changes_only_the_documented_keys(modules, monkeypatch, case_name):
    golden = _load_golden()
    captured = _capture(monkeypatch, case_name, [PLAIN_PLAN])

    system, user = captured["calls"][0]
    _assert_system_prompt(golden, system["content"])
    payload = json.loads(user["content"])
    assert "workflow_planning" not in payload
    assert "workflow_propose" not in [capability["id"] for capability in payload["capabilities"]]
    _assert_payload(golden["planner_payload"], json.dumps(_strip_documented_workflow_keys(payload), **PLANNER_JSON))
    assert "workflow_propose" not in captured["capability_ids"]
    assert {"kind": captured["kind"], **captured["result"]} == golden["plain_result"]


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
            plain = _capture(patch, "setting_absent", [PLAIN_PLAN])
            patch.restore()
            workflow = _capture(patch, "setting_absent", [WORKFLOW_PLAN, PLAIN_PLAN])
        finally:
            patch.restore()
    GOLDEN.write_text(_pretty(_golden_from(plain, workflow)) + "\n", encoding="utf-8")
    print(f"Wrote {GOLDEN}")


if __name__ == "__main__":
    if "--write-golden" in sys.argv:
        _write_golden()
        sys.exit(0)
    sys.exit(pytest.main([__file__, "-q"]))
