#!/usr/bin/env python3
# test_orchestration_workflow_run_planning_context.py
"""
Functional test for the workflow planning context when chat orchestration may start saved workflows.
Version: 0.261.212
Implemented in: 0.261.212

This test ensures that the ``workflow_run`` gates read ``enable_chat_orchestration_workflow_runs``
as a real boolean only, independently of the workflow proposals setting, and that they check the
capability allowlist for ``workflow_run`` itself, personal workflows and the WorkflowUser rule.

It also ensures that the planning context exists when either workflow capability is open: with
only runs on it reads just the workflows; the per-user proposal cap and a failed proposal read
never block runs; a failed workflows read leaves runs unavailable; shared and collaborative
conversations read nothing; a workflow the request names comes first, then durable ones; and the
``/plan`` route, the ``/run`` route, plan revisions and execution carry the context when only runs
are configured, while the time zone stays a proposals-only value.
"""

import importlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from itertools import product

import pytest

from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.versioning import assert_app_version_at_least


OWNER = "owner"
PROPOSALS = "enable_chat_orchestration_workflows"
RUNS = "enable_chat_orchestration_workflow_runs"
RUN_SETTINGS = {
    "enable_chat_orchestration": True,
    RUNS: True,
    "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
    "chat_orchestration_enabled_capabilities": [],
}
BOTH_SETTINGS = {**RUN_SETTINGS, PROPOSALS: True}
PROPOSALS_ONLY = {**BOTH_SETTINGS, RUNS: False}
NOW = datetime(2026, 9, 29, 12, 19, tzinfo=timezone.utc)
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PRIVATE = {"id": "conversation-1", "user_id": OWNER, "title": "Private"}
USER_INFO = {"userId": OWNER, "email": "owner@example.com", "roles": ["User"]}
SHARED_CHANGES = (
    {"collaboration_conversation_id": "collaboration-1"},
    {"conversation_kind": "collaborative"},
    {"chat_type": "personal_multi_user"},
    {"chat_type": "group_multi_user"},
    {"converted_to_collaboration_at": "2026-09-29T00:00:00+00:00"},
)
DIGEST_REQUEST = "Please run my WEEKLY DIGEST now."


def _workflow_id(index):
    return f"6d2e8c20-3f4a-4b5c-8d6e-{index:012d}"


DIGEST_ID = _workflow_id(1)
NOT_DURABLE_ID = _workflow_id(2)


def _workflows(user_id=None):
    """26 live workflows and one being deleted.

    The request names "Weekly digest", the oldest workflow; "Contract watcher" is the second
    oldest and not durable. Every third filler is durable, and the newest filler is not.
    """
    workflows = [
        {
            "id": DIGEST_ID, "name": "Weekly digest", "description": "Summarizes my week.",
            "trigger_type": "interval",
            "schedule": {
                "kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"],
                "time_of_day": "08:00", "timezone": "America/New_York",
            },
            "is_enabled": False, "durable_execution": True, "updated_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "id": NOT_DURABLE_ID, "name": "Contract watcher", "trigger_type": "manual",
            "is_enabled": True, "durable_execution": False, "updated_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "id": _workflow_id(3), "name": "Being deleted", "trigger_type": "manual", "deleting": True,
            "durable_execution": True, "updated_at": "2026-09-28T00:00:00+00:00",
        },
    ]
    for number in range(1, 25):
        workflows.append({
            "id": _workflow_id(100 + number), "name": f"Filler workflow {number:02d}", "trigger_type": "manual",
            "is_enabled": True, "durable_execution": number % 3 == 0,
            "updated_at": f"2026-09-{number:02d}T00:00:00+00:00",
        })
    return workflows


def _fail(*args):
    raise RuntimeError("storage failed")


def _readers(calls, **overrides):
    """Recording readers for every storage read the planning context can make."""
    implementations = {
        "personal_agents": lambda user_id: [],
        "global_agents": lambda: [],
        "actions": lambda scope_type, scope_id: [],
        "govern": lambda user_id, scope_type, actions: actions,
        "sources": lambda user_id, settings, user_info: [],
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


def _settings(base, **changes):
    settings = deepcopy(base)
    for key, value in changes.items():
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = value
    return settings


@pytest.fixture
def wf(modules):
    return importlib.import_module("functions_orchestration_workflow_context")


def test_version_is_at_least_the_workflow_runs_release():
    assert_app_version_at_least("0.261.212")


@pytest.mark.parametrize("value", [None, False, "true", "True", 1, "on", [True]])
def test_only_a_real_true_configures_workflow_runs(wf, value):
    settings = {**RUN_SETTINGS}
    if value is None:
        settings.pop(RUNS)
    else:
        settings[RUNS] = value
    configured = wf.workflow_runs_configured(settings)
    reason = wf.workflow_run_gate(settings, ["User"])
    assert configured is False
    assert reason == wf.WORKFLOW_RUNS_REASON_DISABLED == "workflow_runs_disabled"


def test_workflow_runs_need_chat_orchestration(wf):
    settings = {**RUN_SETTINGS, "enable_chat_orchestration": False}
    configured = wf.workflow_runs_configured(settings)
    reason = wf.workflow_run_gate(settings, ["User"])
    assert configured is False
    assert reason == "workflow_runs_disabled"
    assert wf.workflow_runs_configured(None) is False


def test_the_two_workflow_settings_are_independent(wf):
    for proposals, runs in product((None, False, True), repeat=2):
        settings = {"enable_chat_orchestration": True, "allow_user_workflows": True}
        if proposals is not None:
            settings[PROPOSALS] = proposals
        if runs is not None:
            settings[RUNS] = runs
        proposals_configured = wf.workflow_proposals_configured(settings)
        runs_configured = wf.workflow_runs_configured(settings)
        either = wf.workflow_planning_configured(settings)
        assert proposals_configured is (proposals is True), (proposals, runs)
        assert runs_configured is (runs is True), (proposals, runs)
        assert either is (proposals is True or runs is True), (proposals, runs)
        # The proposals gate keeps its exact Phase 4 meaning whatever the runs setting says.
        proposal_reason = wf.workflow_planning_gate(settings, ["User"])
        assert proposal_reason == (None if proposals is True else "workflow_proposals_disabled"), (proposals, runs)


def test_workflow_runs_need_personal_workflows(wf):
    settings = {**RUN_SETTINGS, "allow_user_workflows": False}
    settings_reason = wf.workflow_run_settings_gate(settings)
    reason = wf.workflow_run_gate(settings, ["WorkflowUser"])
    assert settings_reason == reason == "workflow_runs_disabled"


@pytest.mark.parametrize("allowlist, admitted", [
    ([], True),
    (["workflow_run"], True),
    (["compose", "workflow_run"], True),
    (["workflow_propose"], False),
    (["compose", "web_search"], False),
    ("workflow_run", False),
    ([""], False),
])
def test_the_capability_allowlist_is_checked_for_workflow_run_itself(wf, allowlist, admitted):
    settings = {**RUN_SETTINGS, PROPOSALS: True, "chat_orchestration_enabled_capabilities": allowlist}
    settings_reason = wf.workflow_run_settings_gate(settings)
    reason = wf.workflow_run_gate(settings, ["User"])
    expected = None if admitted else "workflow_runs_disabled"
    assert settings_reason == reason == expected


def test_the_proposal_allowlist_entry_does_not_admit_runs_and_the_reverse(wf):
    both = {**RUN_SETTINGS, PROPOSALS: True}
    runs_only = {**both, "chat_orchestration_enabled_capabilities": ["workflow_run"]}
    proposals_only = {**both, "chat_orchestration_enabled_capabilities": ["workflow_propose"]}
    run_reasons = (wf.workflow_run_gate(runs_only, []), wf.workflow_run_gate(proposals_only, []))
    proposal_reasons = (wf.workflow_planning_gate(runs_only, []), wf.workflow_planning_gate(proposals_only, []))
    assert run_reasons == (None, "workflow_runs_disabled")
    assert proposal_reasons == ("workflow_proposals_disabled", None)


@pytest.mark.parametrize("roles, expected", [
    ([], "workflow_role_required"),
    (["User"], "workflow_role_required"),
    (None, "workflow_role_required"),
    ("WorkflowUser", "workflow_role_required"),
    (["WorkflowUser"], None),
    (("User", "workflowuser"), None),
])
def test_the_workflow_user_rule_is_checked_after_the_settings(wf, roles, expected):
    settings = {**RUN_SETTINGS, "require_member_of_workflow_user": True}
    settings_reason = wf.workflow_run_settings_gate(settings)
    reason = wf.workflow_run_gate(settings, roles)
    # The settings part never looks at roles, so linking an already started run needs none.
    assert settings_reason is None
    assert reason == expected


def test_no_role_rule_means_any_signed_in_user(wf):
    reason = wf.workflow_run_gate(RUN_SETTINGS, [])
    assert reason is None


# ---------------------------------------------------------------------------
# The planning context for either capability
# ---------------------------------------------------------------------------

def _build(wf, calls, settings, *, conversation=None, request_text=DIGEST_REQUEST, user_info=None, **overrides):
    return wf.build_workflow_planning_context(
        deepcopy(settings), user_id=OWNER, user_info=deepcopy(user_info or USER_INFO),
        conversation=deepcopy(conversation or PRIVATE), time_zone="America/New_York", now=NOW,
        documents=(), readers=_readers(calls, **overrides), request_text=request_text,
    )


def _reasons(wf, settings, context, roles=("User",)):
    request_context = {"user_roles": list(roles), "workflow_planning": context}
    proposal_reason = wf.workflow_planning_unavailable_reason(settings, request_context)
    run_reason = wf.workflow_run_unavailable_reason(settings, request_context)
    return proposal_reason, run_reason


def _names(context):
    return [entry["name"] for entry in context["catalog"]["workflows"]]


@pytest.mark.parametrize("runs", [None, False, "true", 1])
def test_nothing_is_read_when_both_workflow_settings_are_off(wf, runs):
    calls = []
    settings = _settings(RUN_SETTINGS, **{RUNS: runs})
    context = _build(wf, calls, settings)
    run_ready = wf.workflow_run_ready(context)
    projection = wf.workflow_run_projection(context)
    assert context == {"conversation_private": True, "quota_reached": None}
    assert calls == []
    assert run_ready is False and projection is None


@pytest.mark.parametrize("changes", [
    {"allow_user_workflows": False},
    {"chat_orchestration_enabled_capabilities": ["compose"]},
    {"require_member_of_workflow_user": True},
])
def test_nothing_is_read_when_runs_are_gated_out_and_proposals_are_off(wf, changes):
    calls = []
    context = _build(wf, calls, _settings(RUN_SETTINGS, **changes))
    assert context == {"conversation_private": True, "quota_reached": None}
    assert calls == []


@pytest.mark.parametrize("settings", [RUN_SETTINGS, BOTH_SETTINGS], ids=["runs_only", "both"])
@pytest.mark.parametrize("changes", SHARED_CHANGES)
def test_nothing_is_read_in_a_shared_or_collaborative_conversation(wf, settings, changes):
    calls = []
    context = _build(wf, calls, settings, conversation={**PRIVATE, **changes})
    proposal_reason, run_reason = _reasons(wf, settings, context)
    assert context == {"conversation_private": False, "quota_reached": None}
    assert calls == []
    assert run_reason == "workflow_shared_conversation"
    assert proposal_reason == ("workflow_shared_conversation" if settings is BOTH_SETTINGS else "workflow_proposals_disabled")


def test_nothing_is_read_without_a_requester(wf):
    calls = []
    context = wf.build_workflow_planning_context(
        deepcopy(RUN_SETTINGS), user_id=None, user_info=deepcopy(USER_INFO), conversation=deepcopy(PRIVATE),
        readers=_readers(calls), request_text=DIGEST_REQUEST,
    )
    assert context == {"conversation_private": False, "quota_reached": None}
    assert calls == []


def test_runs_only_reads_just_the_workflows(wf):
    calls = []
    context = _build(wf, calls, RUN_SETTINGS)
    proposal_ready = wf.workflow_planning_ready(context)
    run_ready = wf.workflow_run_ready(context)
    proposal_reason, run_reason = _reasons(wf, RUN_SETTINGS, context)
    projection = wf.workflow_run_projection(context)
    proposal_projection = wf.workflow_planner_projection(context)
    assert calls == ["workflows"]
    assert set(context) == {"conversation_private", "quota_reached", "catalog", "handles", "workflow_runs"}
    assert context["quota_reached"] is None and context["workflow_runs"] == {"ready": True}
    assert set(context["catalog"]) == {"workflows"} and set(context["handles"]) == {"workflows"}
    workflows = context["catalog"]["workflows"]
    assert len(workflows) == wf.CATALOG_MAX_WORKFLOWS
    assert "Being deleted" not in _names(context)
    assert list(context["handles"]["workflows"]) == [entry["handle"] for entry in workflows]
    digest = workflows[0]
    assert set(digest) == {"handle", "name", "description", "trigger_summary", "enabled", "durable"}
    assert digest["name"] == "Weekly digest" and digest["description"] == "Summarizes my week."
    assert digest["enabled"] is False and digest["durable"] is True
    assert isinstance(digest["trigger_summary"], str) and digest["trigger_summary"] not in ("", "Manual")
    assert context["handles"]["workflows"][digest["handle"]] == {"id": DIGEST_ID}
    # Proposals are off, so they stay unavailable for the same reason as before runs existed.
    assert proposal_ready is False and proposal_projection is None
    assert proposal_reason == "workflow_proposals_disabled"
    assert run_ready is True and run_reason is None
    # The planner sees handles and names only, and a copy.
    assert projection == {"catalog": {"workflows": workflows}}
    assert not UUID_PATTERN.search(json.dumps(projection))
    projection["catalog"]["workflows"].clear()
    assert context["catalog"]["workflows"] == workflows and workflows


def test_the_proposal_cap_does_not_block_starting_a_workflow(wf):
    calls = []
    settings = {**BOTH_SETTINGS, "chat_orchestration_max_workflows_per_user": 3}
    context = _build(wf, calls, settings, quota_count=lambda user_id: 3)
    proposal_reason, run_reason = _reasons(wf, settings, context)
    run_ready = wf.workflow_run_ready(context)
    assert calls == ["quota_count", "workflows"]
    assert context["quota_reached"] is True
    assert context["limits"] == {"quota_used": 3, "quota_limit": 3}
    assert context["workflow_runs"] == {"ready": True} and run_ready is True
    assert set(context["catalog"]) == {"workflows"}
    assert _names(context)[0] == "Weekly digest"
    assert proposal_reason == "workflow_quota_reached"
    assert run_reason is None


@pytest.mark.parametrize(("overrides", "reads"), [
    ({"quota_count": _fail}, ["quota_count", "workflows"]),
    ({"max_tasks": _fail}, ["quota_count", "max_tasks", "workflows"]),
])
def test_a_failed_proposal_read_does_not_block_starting_a_workflow(wf, overrides, reads):
    calls = []
    context = _build(wf, calls, BOTH_SETTINGS, **overrides)
    proposal_reason, run_reason = _reasons(wf, BOTH_SETTINGS, context)
    assert calls == reads
    assert context["context_unavailable"] is True and context["workflow_runs"] == {"ready": True}
    assert proposal_reason == "workflow_context_unavailable"
    assert run_reason is None


@pytest.mark.parametrize(("settings", "reads"), [
    (RUN_SETTINGS, ["workflows"]),
    (BOTH_SETTINGS, ["quota_count", "max_tasks", "workflows", "workflows"]),
], ids=["runs_only", "both"])
def test_a_failed_workflows_read_leaves_starting_a_workflow_unavailable(wf, settings, reads):
    calls = []
    context = _build(wf, calls, settings, workflows=_fail)
    run_ready = wf.workflow_run_ready(context)
    _proposal_reason, run_reason = _reasons(wf, settings, context)
    projection = wf.workflow_run_projection(context)
    assert [name for name in calls if name in ("quota_count", "max_tasks", "workflows")] == reads
    assert "workflow_runs" not in context and "catalog" not in context
    assert run_ready is False and projection is None
    assert run_reason == "workflow_context_unavailable"


def test_both_on_is_the_proposal_context_ranked_for_runs_plus_the_marker(wf):
    base_calls, both_calls = [], []
    base = _build(wf, base_calls, PROPOSALS_ONLY)
    both = _build(wf, both_calls, BOTH_SETTINGS)
    proposal_reason, run_reason = _reasons(wf, BOTH_SETTINGS, both)
    assert both_calls == base_calls and base_calls.count("workflows") == 1
    assert "workflow_runs" not in base
    assert proposal_reason is None and run_reason is None
    marker = both.pop("workflow_runs")
    assert marker == {"ready": True}
    # Only the workflows differ: ranked for starting one, so the named workflow is offered.
    assert _names(both)[0] == "Weekly digest" and "Weekly digest" not in _names(base)
    for context in (base, both):
        context["catalog"].pop("workflows")
        context["handles"].pop("workflows")
        context.pop("workflow_snapshots")
    assert both == base


def test_the_named_workflow_comes_first_then_durable_ones_each_newest_first(wf):
    calls = []
    context = _build(wf, calls, RUN_SETTINGS)
    fillers = sorted(
        (workflow for workflow in _workflows() if workflow["name"].startswith("Filler")),
        key=lambda workflow: workflow["updated_at"], reverse=True,
    )
    expected = [
        "Weekly digest",
        *(workflow["name"] for workflow in fillers if workflow["durable_execution"]),
        *(workflow["name"] for workflow in fillers if not workflow["durable_execution"]),
    ]
    assert _names(context) == expected[:wf.CATALOG_MAX_WORKFLOWS]


def test_without_a_name_durable_workflows_are_offered_before_newer_non_durable_ones(wf):
    calls = []
    context = _build(wf, calls, RUN_SETTINGS, request_text="Run my workflow now.")
    names = _names(context)
    durable = [entry["durable"] for entry in context["catalog"]["workflows"]]
    # The oldest workflow is durable, so it is still offered; the newer non-durable one is not.
    assert "Weekly digest" in names and "Contract watcher" not in names
    assert durable == sorted(durable, reverse=True)


def test_a_named_workflow_is_offered_even_when_it_is_not_durable(wf):
    calls = []
    context = _build(wf, calls, RUN_SETTINGS, request_text="Run the contract watcher.")
    entry = context["catalog"]["workflows"][0]
    # Offered, so the plan can say why it cannot be started from chat.
    assert entry["name"] == "Contract watcher" and entry["durable"] is False


def test_proposals_only_keeps_the_newest_first_order(wf):
    calls = []
    context = _build(wf, calls, PROPOSALS_ONLY)
    live = sorted(
        (workflow for workflow in _workflows() if not workflow.get("deleting")),
        key=lambda workflow: workflow["updated_at"], reverse=True,
    )
    assert _names(context) == [workflow["name"] for workflow in live][:wf.CATALOG_MAX_WORKFLOWS]


@pytest.mark.parametrize(("name", "request_text", "named"), [
    ("Weekly digest", "run my weekly digest now", True),
    ("Weekly digest", "RUN MY WEEKLY\u200b   DIGEST", True),
    ("\uff37eekly digest", "run my weekly digest", True),
    ("Weekly digest", "run my weekly digests now", False),
    ("Weekly digest", "run my weekly-digest now", False),
    ("Weekly digest", "run my weekly report", False),
    ("Digest", "run my weekly digest now", True),
    ("est", "run my weekly digest now", False),
    ("Go", "go run my go workflow", False),
    ("Q3 report", "Run the q3 report.", True),
    ("C++ build", "run the c++ build now", True),
    ("a.b", "run axb", False),
    ("", "anything at all", False),
    (None, "anything at all", False),
    ("Weekly digest", "", False),
    ("Weekly digest", None, False),
])
def test_a_workflow_is_named_only_by_its_whole_name(wf, name, request_text, named):
    predicate = wf._named_by(request_text)
    result = predicate({"name": name})
    assert result is named


def test_run_readiness_needs_every_part_of_the_context(wf):
    calls = []
    ready = _build(wf, calls, RUN_SETTINGS)
    broken = []
    for key, value in (
        ("conversation_private", False), ("workflow_runs", {"ready": "true"}), ("workflow_runs", None),
        ("catalog", {"agents": []}), ("catalog", None), ("handles", {"agents": {}}), ("handles", None),
    ):
        broken.append(wf.workflow_run_ready({**ready, key: value}))
    not_a_context = wf.workflow_run_ready("ready")
    assert broken == [False] * 7 and not_a_context is False


def test_run_reasons_never_raise_and_fail_closed(wf):
    reasons = [
        wf.workflow_run_unavailable_reason(RUN_SETTINGS, None),
        wf.workflow_run_unavailable_reason(RUN_SETTINGS, {"user_roles": ["User"]}),
        wf.workflow_run_unavailable_reason(RUN_SETTINGS, {"user_roles": ["User"], "workflow_planning": "x"}),
        wf.workflow_run_unavailable_reason(
            {**RUN_SETTINGS, "require_member_of_workflow_user": True},
            {"user_roles": ["User"], "workflow_planning": {"conversation_private": True}},
        ),
    ]

    class Exploding(dict):
        def get(self, *args):
            raise RuntimeError("broken context")

    exploded = wf.workflow_run_unavailable_reason(RUN_SETTINGS, Exploding())
    assert reasons == [
        "workflow_context_unavailable", "workflow_context_unavailable", "workflow_context_unavailable",
        "workflow_role_required",
    ]
    assert exploded == "workflow_context_unavailable"


# ---------------------------------------------------------------------------
# Wiring: the run route, plan revisions and execution
# ---------------------------------------------------------------------------

def test_the_run_route_rereads_privacy_when_only_runs_are_configured(modules, wf, monkeypatch):
    route = modules.route
    conversation = dict(PRIVATE)
    reads = []

    def authorize(conversation_id, user_id):
        reads.append((conversation_id, user_id))
        return dict(conversation)

    monkeypatch.setattr(route, "_authorize_context_conversation", authorize)
    stored = _build(wf, [], RUN_SETTINGS)
    record = {"conversation_id": "conversation-1", "workflow_planning": stored}

    off = route._current_workflow_planning(record, OWNER, _settings(RUN_SETTINGS, **{RUNS: False}))
    assert off is None and reads == []
    current = route._current_workflow_planning(record, OWNER, RUN_SETTINGS)
    current_ready = wf.workflow_run_ready(current)
    assert current == stored and current_ready is True and reads == [("conversation-1", OWNER)]

    conversation["chat_type"] = "personal_multi_user"
    shared = route._current_workflow_planning(record, OWNER, RUN_SETTINGS)
    shared_ready = wf.workflow_run_ready(shared)
    _proposal_reason, run_reason = _reasons(wf, RUN_SETTINGS, shared)
    assert shared["conversation_private"] is False and shared_ready is False
    assert run_reason == "workflow_shared_conversation"
    assert record["workflow_planning"]["conversation_private"] is True


@pytest.mark.parametrize(("proposals", "runs", "offered"), [
    (False, False, False), (True, False, True), (False, True, True), (True, True, True),
])
def test_plan_revisions_offer_the_stored_context_when_either_is_configured(modules, monkeypatch, proposals, runs, offered):
    editing = importlib.import_module("functions_orchestration_plan_editing")
    monkeypatch.setattr(editing, "resolve_agent_catalog", lambda *args, **kwargs: [])
    monkeypatch.setattr(editing, "resolve_action_catalog", lambda *args, **kwargs: [])
    settings = {**RUN_SETTINGS, PROPOSALS: proposals, RUNS: runs}
    context = {
        "user_message": "Run my weekly digest.", "resolved_message": "Run my weekly digest.", "seeds": {},
        "workflow_planning": {"conversation_private": True, "quota_reached": None},
    }
    identity = {"user_email": "owner@example.com", "user_roles": ["User"], "user_enable_agents": True}
    _agents, _actions, caller = editing._revision_catalogs(context, OWNER, settings, identity)
    assert ("workflow_planning" in caller) is offered


def _frames(response):
    return [
        json.loads(frame.partition("data:")[2].strip())
        for frame in response.get_data(as_text=True).split("\n\n")
        if frame.startswith("data:") and frame.partition("data:")[2].strip() != "[DONE]"
    ]


def _plan(runtime, turn_id, *, message, time_zone=None):
    runtime.harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": message,
            "message_ids": [], "requires_retrieval": False, "clarification": "",
        }),
        json.dumps({"kind": "plan", "steps": [compose_step()], "final_response": input_binding("prepare")}),
        "The complete note.",
    ]
    body = {
        "conversation_id": "conversation-1", "turn_id": turn_id, "message": message,
        "approval_mode": "manual", "planner_contract_version": 1,
    }
    if time_zone is not None:
        body["time_zone"] = time_zone
    response = runtime.client.post("/api/v2/orchestration/plan", json=body, buffered=True)
    text = response.get_data(as_text=True)
    frames = _frames(response)
    assert response.status_code == 200 and "plan" in frames[-1], frames
    record = runtime.harness.runs.read_item(frames[-1]["plan"]["run_id"], "conversation-1")
    return text, record


def _record_run_contexts(monkeypatch):
    execution = importlib.import_module("functions_orchestration_execution")
    seen = []

    class RecordingRunContext(execution.RunContext):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seen.append({"time_zone": self.time_zone, "workflow_planning": deepcopy(self.workflow_planning)})

    monkeypatch.setattr(execution, "RunContext", RecordingRunContext)
    return seen


def test_real_http_runs_only_planning_stores_a_workflows_context_and_runs_with_it(real_http_harness, wf, monkeypatch):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings.update(enable_user_workspace=False, allow_user_workflows=True, **{RUNS: True})
    calls = []
    for name, reader in _readers(calls).items():
        monkeypatch.setitem(wf._DEFAULT_READERS, name, reader)
    seen = _record_run_contexts(monkeypatch)

    text, record = _plan(runtime, "runs-turn", message=DIGEST_REQUEST, time_zone="America/New_York")
    planning = record["workflow_planning"]
    assert calls == ["workflows"]
    # The time zone is only for proposals, which are off.
    assert "time_zone" not in record
    assert planning["workflow_runs"] == {"ready": True} and planning["quota_reached"] is None
    # The route passes the request, so the oldest workflow, which it names, is offered first.
    assert _names(planning)[0] == "Weekly digest"
    for leaked in ("workflow_planning", "workflow_runs", DIGEST_ID, "Weekly digest", "Filler workflow"):
        assert leaked not in text

    executed = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": record["id"],
    }, buffered=True)
    frames = _frames(executed)
    saved = harness.runs.read_item(record["id"], "conversation-1")
    assert executed.status_code == 200 and saved["status"] == "completed", frames
    assert seen and seen[-1]["workflow_planning"] == planning and seen[-1]["time_zone"] is None


def test_real_http_both_off_reads_nothing_even_for_a_request_naming_a_workflow(real_http_harness, wf, monkeypatch):
    runtime = real_http_harness
    runtime.harness.settings.update(enable_user_workspace=False, allow_user_workflows=True)
    calls = []
    for name, reader in _readers(calls).items():
        monkeypatch.setitem(wf._DEFAULT_READERS, name, reader)
    _text, record = _plan(runtime, "off-turn", message=DIGEST_REQUEST, time_zone="America/New_York")
    assert "workflow_planning" not in record and "time_zone" not in record
    assert calls == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
