#!/usr/bin/env python3
# test_orchestration_workflow_run_link_routes.py
"""
Functional test for the links to saved workflow runs a chat orchestration plan started.
Version: 0.261.212
Implemented in: 0.261.212

This test ensures that only the requester, in a private conversation where starting workflows
from chat is turned on, can read the runs a plan started: each run's workflow name, its status
when read and the ids its Open run link uses. A closed gate, a conversation that is no longer
private and content review each make every link unavailable, with no name, no ids and no workflow
or run read. A deleted workflow or a run missing from its history is unavailable. A step that did
not start its workflow is not listed, and a sidecar that does not belong to the plan and step it
claims, including its derived run id, is left out. A retry shows the run its first attempt
started. Nothing is written, and logs carry codes only.

The production Flask route, Blueprint guards and link module run unchanged against in-memory
storage, with the network blocked.
"""

import ast
import hashlib
import importlib
import json
import re
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Blueprint, Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_orchestration_harness_routes import modules  # noqa: F401
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
TS_LINKS = REPO_ROOT / "application" / "v2_ui" / "src" / "lib" / "orchestrationWorkflowRuns.ts"

OWNER = "owner"
OTHER = "someone-else"
TENANT = "tenant-1"
EMAIL = "owner@example.com"
CONVERSATION = "conversation-1"
OTHER_CONVERSATION = "conversation-2"
TURN = "turn-1"
RUN = "run_" + "1" * 32
RETRY = "run_" + "2" * 32
SECOND = "run_" + "3" * 32
STEP = "run_digest"
SECOND_STEP = "run_watcher"
WORKFLOW_ID = "workflow-digest"
WATCHER_ID = "workflow-watcher"
NAME = "Weekly digest"
WATCHER = "Inbox watcher"
STARTED = ("queued", "running", "already_started")
RUN_SETTINGS = {
    "enable_chat_orchestration": True,
    "enable_chat_orchestration_workflow_runs": True,
    "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
    "chat_orchestration_enabled_capabilities": [],
}


class Reads(AtomicMemoryContainer):
    """A container that records every point read, so a test can show nothing was read."""

    def __init__(self, partition_field):
        super().__init__(partition_field)
        self.reads = []

    def read_item(self, item, partition_key):
        self.reads.append((partition_key, item))
        return super().read_item(item, partition_key)


def _log_recorder(logs, source):
    def log_event(message, *args, **kwargs):
        logs.append({
            "source": source, "message": str(message),
            "extra": json.dumps(kwargs.get("extra"), default=str, ensure_ascii=False),
        })
    return log_event


@pytest.fixture
def h(modules, monkeypatch):
    links = importlib.import_module("functions_orchestration_workflow_run_links")
    wr = importlib.import_module("functions_orchestration_workflow_runs")
    settings_module = importlib.import_module("functions_settings")
    conversations = AtomicMemoryContainer("id")
    runs = AtomicMemoryContainer("conversation_id")
    steps = AtomicMemoryContainer("run_id")
    workflows = Reads("user_id")
    workflow_runs = Reads("user_id")
    settings = {**deepcopy(settings_module.get_settings() or {}), **deepcopy(RUN_SETTINGS)}
    for module, name, value in (
        (modules.config, "cosmos_conversations_container", conversations),
        (modules.route, "cosmos_conversations_container", conversations),
        (modules.config, "cosmos_orchestration_runs_container", runs),
        (modules.runs, "cosmos_orchestration_runs_container", runs),
        (modules.config, "cosmos_orchestration_run_steps_container", steps),
        (modules.runs, "cosmos_orchestration_run_steps_container", steps),
        (modules.config, "cosmos_personal_workflows_container", workflows),
        (modules.config, "cosmos_personal_workflow_runs_container", workflow_runs),
    ):
        monkeypatch.setattr(module, name, value, raising=False)

    record = SimpleNamespace(logs=[], access_checks=[])

    def access_status(user_id):
        # The real check reads user settings, whose profile-image refresh would reach Microsoft Entra.
        record.access_checks.append(user_id)
        return True, None

    monkeypatch.setattr(modules.auth, "check_user_access_status", access_status)
    monkeypatch.setattr(modules.route, "get_settings", lambda: deepcopy(settings))
    for module in (links, modules.route):
        monkeypatch.setattr(module, "log_event", _log_recorder(record.logs, module.__name__))

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="workflow-run-link-routes")
    blueprint = Blueprint("backend_orchestration", __name__)
    blueprint.before_request(modules.auth.user_required_blueprint())
    modules.route.register_route_backend_orchestration(blueprint)
    app.register_blueprint(blueprint)
    conversations.create_item({"id": CONVERSATION, "user_id": OWNER, "title": "Private"})
    conversations.create_item({"id": OTHER_CONVERSATION, "user_id": OWNER, "title": "Another"})
    return SimpleNamespace(
        modules=modules, links=links, wr=wr, app=app, client=Client(app, Response),
        conversations=conversations, runs=runs, steps=steps, workflows=workflows,
        workflow_runs=workflow_runs, settings=settings, record=record,
    )


def login(h, *, user_id=OWNER, roles=("User",)):
    serializer = h.app.session_interface.get_signing_serializer(h.app)
    cookie = serializer.dumps({
        "user": {"oid": user_id, "roles": list(roles), "tid": TENANT, "preferred_username": EMAIL},
    })
    h.client.set_cookie(h.app.config["SESSION_COOKIE_NAME"], cookie)


def _step(step_id=STEP, handle="weekly-digest", *, enabled=True):
    return {
        "step_id": step_id, "capability_id": "workflow_run", "enabled": enabled,
        "arguments": {"workflow": handle}, "inputs": {}, "outputs": [{"name": "run", "kind": "structured-v1"}],
    }


def _plan(*steps, turn_id=TURN, contract_version=2):
    return {"planner_contract_version": contract_version, "turn_id": turn_id, "steps": list(steps) or [_step()]}


def run_id_for(h, workflow_id=WORKFLOW_ID, *, root=RUN, step_id=STEP):
    return h.wr.started_workflow_run_id(OWNER, workflow_id, attempt_root_run_id=root, step_id=step_id)


def sidecar(h, *, step_id=STEP, workflow_id=WORKFLOW_ID, name=NAME, status="queued", root=RUN,
            orchestration_run_id=RUN, **changes):
    """The sidecar the run step stores, as ``functions_orchestration_workflow_runs._sidecar`` builds it."""
    value = {
        "version": 1, "step_id": step_id, "orchestration_run_id": orchestration_run_id,
        "attempt_root_run_id": root, "conversation_id": CONVERSATION, "requested_by": OWNER,
        "handle": "weekly-digest", "workflow_id": workflow_id,
        "run_id": run_id_for(h, workflow_id, root=root, step_id=step_id) if status in STARTED else None,
        "name": name, "status": status, "reason": None if status in STARTED else "workflow_already_running",
    }
    value.update(changes)
    return value


def seed_run(h, run_id=RUN, *, plan=None, entries=None, user_id=OWNER, **fields):
    record = {
        "id": run_id, "run_id": run_id, "conversation_id": CONVERSATION, "user_id": user_id,
        "turn_id": TURN, "status": "completed", "plan": plan or _plan(),
        "execution_steps": entries if entries is not None else [{
            "step_id": STEP, "capability_id": "workflow_run", "status": "completed",
            "workflow_run": sidecar(h),
        }],
    }
    record.update(deepcopy(fields))
    h.runs.create_item(record)
    return record


def seed_workflow(h, workflow_id=WORKFLOW_ID, *, name=NAME, **fields):
    h.workflows.upsert_item({
        "id": workflow_id, "user_id": OWNER, "name": name, "durable_execution": True, "is_enabled": True,
        **fields,
    })


def seed_workflow_run(h, workflow_id=WORKFLOW_ID, *, status="queued", root=RUN, step_id=STEP, **fields):
    run_id = run_id_for(h, workflow_id, root=root, step_id=step_id)
    h.workflow_runs.upsert_item({
        "id": run_id, "workflow_id": workflow_id, "user_id": OWNER, "workflow_name": NAME,
        "trigger_source": "chat_orchestration", "durable_execution": True, "status": status, **fields,
    })
    return run_id


def seed_started(h, *, status="queued"):
    seed_run(h)
    seed_workflow(h)
    return seed_workflow_run(h, status=status)


def links(h, run_id=RUN, conversation_id=CONVERSATION):
    return h.client.get(
        f"/api/v2/orchestration/runs/{run_id}/workflow-runs", query_string={"conversation_id": conversation_id},
    )


def listed(h, run_id=RUN):
    response = links(h, run_id)
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body["run_id"] == run_id
    return body["workflow_runs"]


def only(h, run_id=RUN):
    entries = listed(h, run_id)
    assert len(entries) == 1, entries
    return entries[0]


def code(response):
    return (response.get_json() or {}).get("code")


def writes(h):
    return (h.runs.sequence, h.steps.sequence, h.workflows.sequence, h.workflow_runs.sequence)


def reads(h):
    return (len(h.workflows.reads), len(h.workflow_runs.reads))


def test_version_includes_the_workflow_run_links():
    assert_app_version_at_least("0.261.212")


# ---------------------------------------------------------------------------
# Who may read the links
# ---------------------------------------------------------------------------

def test_the_link_route_needs_a_signed_in_user_with_the_user_role(h):
    seed_started(h)
    anonymous = links(h)
    login(h, roles=())
    no_role = links(h)
    assert anonymous.status_code == 401 and no_role.status_code == 403
    assert h.record.access_checks == [] and reads(h) == (0, 0)
    login(h)
    assert links(h).status_code == 200
    assert h.record.access_checks and set(h.record.access_checks) == {OWNER}


def test_only_reading_is_allowed(h):
    seed_started(h)
    login(h)
    before = writes(h)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = h.client.open(
            f"/api/v2/orchestration/runs/{RUN}/workflow-runs", method=method,
            query_string={"conversation_id": CONVERSATION},
        )
        assert response.status_code == 405, method
    assert writes(h) == before


def test_the_requester_reads_each_started_run_with_its_current_status(h):
    run_id = seed_started(h, status="running")
    login(h)
    before = writes(h)
    response = links(h)
    assert response.status_code == 200
    assert response.get_json() == {"run_id": RUN, "workflow_runs": [{
        "step_id": STEP, "name": NAME, "state": "running", "reason": None,
        "workflow_id": WORKFLOW_ID, "workflow_run_id": run_id,
    }]}
    # Reading writes nothing, and reads the workflow and its run once each.
    assert writes(h) == before and reads(h) == (1, 1)
    # The server-only sidecar fields never leave the server.
    text = response.get_data(as_text=True)
    for private in ("weekly-digest", "attempt_root_run_id", "requested_by", "orchestration_run_id", "handle"):
        assert private not in text


def test_the_name_is_the_workflows_current_name_and_the_sidecar_name_only_as_a_fallback(h):
    seed_started(h)
    seed_workflow(h, name="Renamed digest")
    login(h)
    assert only(h)["name"] == "Renamed digest"
    seed_workflow(h, name="   ")
    assert only(h)["name"] == NAME


def test_a_hostile_name_is_returned_as_one_bounded_line_of_plain_data(h):
    limit = importlib.import_module("functions_orchestration_workflow_context").NAME_MAX_LENGTH
    hostile = "<img src=x onerror=alert(1)>\n\tDigest\u0000 " + "x" * (limit * 2)
    seed_started(h)
    seed_workflow(h, name=hostile)
    login(h)
    name = only(h)["name"]
    assert name.startswith("<img src=x onerror=alert(1)> Digest")
    assert len(name) <= limit and "\n" not in name and "\u0000" not in name


@pytest.mark.parametrize(("status", "state"), [
    ("queued", "queued"),
    ("running", "running"),
    ("cancelling", "running"),
    ("waiting_approval", "waiting"),
    ("waiting_output", "waiting"),
    ("waiting_recovery", "waiting"),
    ("paused", "waiting"),
    ("awaiting_sign_in", "waiting"),
    ("awaiting_run_as_approval", "waiting"),
    ("completed", "completed"),
    ("completed_partial", "completed_partial"),
    ("failed", "failed"),
    ("invalid", "failed"),
    ("incomplete", "failed"),
    ("cancelled", "cancelled"),
    ("skipped", "skipped"),
    ("COMPLETED", "completed"),
    ("a_state_added_later", "running"),
    ("", "running"),
])
def test_each_runtime_state_maps_to_one_link_state(h, status, state):
    seed_started(h, status=status)
    login(h)
    entry = only(h)
    assert entry["state"] == state and entry["reason"] is None
    assert entry["workflow_id"] == WORKFLOW_ID and entry["workflow_run_id"] == run_id_for(h)


def test_every_runtime_state_has_a_link_state_the_client_knows():
    store = importlib.import_module("functions_workflow_runtime_store")
    links = importlib.import_module("functions_orchestration_workflow_run_links")
    for status in sorted(store.ALL_STATES):
        state = links._link_state({"status": status})
        assert state in links.WORKFLOW_RUN_LINK_STATES and state != links.LINK_STATE_UNAVAILABLE, status
    match = re.search(r"WORKFLOW_RUN_LINK_STATES = \[(.*?)\] as const", TS_LINKS.read_text(encoding="utf-8"), re.S)
    assert match, "the client's link states moved"
    client_states = tuple(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert client_states == links.WORKFLOW_RUN_LINK_STATES


def test_every_reason_the_route_returns_has_client_text():
    links = importlib.import_module("functions_orchestration_workflow_run_links")
    context = importlib.import_module("functions_orchestration_workflow_context")
    source = TS_LINKS.read_text(encoding="utf-8")
    block = re.search(r"const REASON_TEXT: Record<string, string> = \{(.*?)\n\};", source, re.S)
    assert block, "the client's reason text moved"
    keys = set(re.findall(r"^\s+([a-z_]+):", block.group(1), re.M))
    reasons = {
        links.REASON_WORKFLOW_DELETED, links.REASON_RUN_MISSING, links.REASON_CONTENT_REVIEW,
        context.WORKFLOW_RUNS_REASON_DISABLED, context.WORKFLOW_REASON_ROLE_REQUIRED,
        context.WORKFLOW_REASON_SHARED_CONVERSATION,
    }
    assert reasons == keys


def test_a_run_or_conversation_the_requester_cannot_open_is_not_found(h):
    seed_started(h)
    h.runs.create_item({
        "id": SECOND, "run_id": SECOND, "conversation_id": CONVERSATION, "user_id": OTHER, "turn_id": TURN,
        "status": "completed", "plan": _plan(), "execution_steps": [],
    })
    login(h)
    missing_conversation = links(h, conversation_id="")
    assert missing_conversation.status_code == 400 and missing_conversation.get_json() == {
        "error": "This request is not valid.", "code": "invalid_request",
    }
    refusals = [
        links(h, run_id="run_unknown"),
        links(h, conversation_id=OTHER_CONVERSATION),
        links(h, conversation_id="conversation-missing"),
        links(h, run_id=SECOND),
    ]
    login(h, user_id=OTHER)
    refusals.append(links(h))
    h.conversations.items[(CONVERSATION, CONVERSATION)]["orchestration_deleted"] = True
    login(h)
    refusals.append(links(h))
    # Every refusal is the same body, so a run the requester cannot open looks like a missing one.
    for response in refusals:
        assert response.status_code == 404
        assert response.get_json() == {"error": "Run not found.", "code": "run_not_found"}
    assert reads(h) == (0, 0)


def test_a_run_whose_record_names_another_conversation_is_not_found(h):
    run_id = seed_started(h)
    # Runs are partitioned by conversation, so a real point read cannot return another
    # conversation's run. A copy planted under the wrong partition pins the route's own check.
    h.runs.items[(OTHER_CONVERSATION, RUN)] = deepcopy(h.runs.items[(CONVERSATION, RUN)])
    login(h)
    response = links(h, conversation_id=OTHER_CONVERSATION)
    assert response.status_code == 404
    assert response.get_json() == {"error": "Run not found.", "code": "run_not_found"}
    assert reads(h) == (0, 0)
    # The same record still opens from the conversation it names.
    assert only(h)["workflow_run_id"] == run_id


def test_a_legacy_plan_is_refused_like_every_other_run_route(h):
    seed_run(h, plan=_plan(contract_version=1))
    login(h)
    response = links(h)
    assert response.status_code == 409 and code(response) == "legacy_plan"


def _close(h, case):
    if case == "setting_off":
        h.settings["enable_chat_orchestration_workflow_runs"] = False
    elif case == "setting_not_a_real_boolean":
        h.settings["enable_chat_orchestration_workflow_runs"] = "true"
    elif case == "orchestration_off":
        h.settings["enable_chat_orchestration"] = False
    elif case == "workflows_off":
        h.settings["allow_user_workflows"] = False
    elif case == "allowlist":
        h.settings["chat_orchestration_enabled_capabilities"] = ["compose", "workflow_propose"]
    elif case == "role":
        h.settings["require_member_of_workflow_user"] = True
    elif case == "shared":
        h.conversations.items[(CONVERSATION, CONVERSATION)]["chat_type"] = "personal_multi_user"
    elif case == "converted":
        h.conversations.items[(CONVERSATION, CONVERSATION)]["converted_to_collaboration_at"] = "2026-01-01T00:00:00+00:00"


@pytest.mark.parametrize(("case", "reason"), [
    ("setting_off", "workflow_runs_disabled"),
    ("setting_not_a_real_boolean", "workflow_runs_disabled"),
    ("orchestration_off", "workflow_runs_disabled"),
    ("workflows_off", "workflow_runs_disabled"),
    ("allowlist", "workflow_runs_disabled"),
    ("role", "workflow_role_required"),
    ("shared", "workflow_shared_conversation"),
    ("converted", "workflow_shared_conversation"),
])
def test_a_closed_gate_shows_every_link_unavailable_without_names_ids_or_reads(h, case, reason):
    seed_started(h)
    login(h)
    assert only(h)["state"] == "queued"
    before = reads(h)
    _close(h, case)
    response = links(h)
    assert response.status_code == 200
    assert response.get_json()["workflow_runs"] == [{
        "step_id": STEP, "name": "", "state": "unavailable", "reason": reason,
        "workflow_id": None, "workflow_run_id": None,
    }]
    assert NAME not in response.get_data(as_text=True)
    assert reads(h) == before


def test_proposals_alone_do_not_open_the_links(h):
    seed_started(h)
    h.settings.update(enable_chat_orchestration_workflow_runs=False, enable_chat_orchestration_workflows=True)
    login(h)
    assert only(h)["reason"] == "workflow_runs_disabled"


def test_content_review_hides_every_link_without_reading_the_workflow(h):
    seed_run(h, chat_content_output_pending=True)
    seed_workflow(h)
    seed_workflow_run(h)
    login(h)
    assert only(h) == {
        "step_id": STEP, "name": "", "state": "unavailable", "reason": "content_review",
        "workflow_id": None, "workflow_run_id": None,
    }
    assert reads(h) == (0, 0)


# ---------------------------------------------------------------------------
# What a link shows
# ---------------------------------------------------------------------------

def test_a_deleted_workflow_is_unavailable_and_keeps_the_name_it_started_with(h):
    seed_run(h)
    seed_workflow_run(h)
    login(h)
    missing = only(h)
    assert missing == {
        "step_id": STEP, "name": NAME, "state": "unavailable", "reason": "workflow_deleted",
        "workflow_id": None, "workflow_run_id": None,
    }
    # The run is not read once its workflow is gone.
    assert reads(h) == (1, 0)
    for changes in ({"deleting": True}, {"status": "deleting"}, {"user_id": OTHER}):
        h.workflows.items.clear()
        workflow = {"id": WORKFLOW_ID, "user_id": OWNER, "name": NAME, **changes}
        h.workflows.items[(OWNER, WORKFLOW_ID)] = workflow
        assert only(h)["reason"] == "workflow_deleted", changes


def test_a_run_missing_from_the_workflows_history_is_unavailable(h):
    seed_run(h)
    seed_workflow(h, name="Renamed digest")
    login(h)
    assert only(h) == {
        "step_id": STEP, "name": "Renamed digest", "state": "unavailable", "reason": "workflow_run_missing",
        "workflow_id": None, "workflow_run_id": None,
    }
    run_id = seed_workflow_run(h, workflow_id=WORKFLOW_ID)
    h.workflow_runs.items[(OWNER, run_id)]["workflow_id"] = WATCHER_ID
    assert only(h)["reason"] == "workflow_run_missing"
    h.workflow_runs.items[(OWNER, run_id)].update(workflow_id=WORKFLOW_ID, user_id=OTHER)
    assert only(h)["reason"] == "workflow_run_missing"


def test_links_follow_plan_order_and_skip_steps_that_did_not_start(h):
    plan = _plan(_step(SECOND_STEP, "inbox-watcher"), _step(), _step("run_off", enabled=False))
    entries = [
        {"step_id": STEP, "status": "completed", "workflow_run": sidecar(h)},
        {"step_id": SECOND_STEP, "status": "completed",
         "workflow_run": sidecar(h, step_id=SECOND_STEP, workflow_id=WATCHER_ID, name=WATCHER, status="running")},
        {"step_id": "run_off", "status": "completed",
         "workflow_run": sidecar(h, step_id="run_off", workflow_id=WATCHER_ID)},
    ]
    seed_run(h, plan=plan, entries=entries)
    seed_workflow(h)
    seed_workflow(h, WATCHER_ID, name=WATCHER)
    seed_workflow_run(h, status="completed")
    seed_workflow_run(h, WATCHER_ID, step_id=SECOND_STEP, status="waiting_output")
    login(h)
    assert [(entry["step_id"], entry["name"], entry["state"]) for entry in listed(h)] == [
        (SECOND_STEP, WATCHER, "waiting"), (STEP, NAME, "completed"),
    ]


@pytest.mark.parametrize("status", ["unavailable", "not_a_status", None])
def test_a_step_that_did_not_start_its_workflow_is_not_listed(h, status):
    seed_run(h, entries=[{"step_id": STEP, "status": "completed", "workflow_run": sidecar(h, status=status)}])
    seed_workflow(h)
    login(h)
    assert listed(h) == [] and reads(h) == (0, 0)
    assert not [entry for entry in h.record.logs if "workflow_run_link_mismatch" in entry["extra"]]


def test_a_step_without_a_sidecar_is_not_listed(h):
    seed_run(h, entries=[{"step_id": STEP, "status": "failed"}])
    login(h)
    assert listed(h) == []


@pytest.mark.parametrize("changes", [
    {"requested_by": OTHER},
    {"conversation_id": OTHER_CONVERSATION},
    {"step_id": "another-step"},
    {"version": 2},
    {"attempt_root_run_id": SECOND},
    {"run_id": str(uuid.uuid4())},
    {"run_id": None},
    {"workflow_id": WATCHER_ID},
    {"workflow_id": ""},
])
def test_a_sidecar_that_does_not_belong_to_its_plan_and_step_is_left_out(h, changes):
    # Changed after the sidecar is built, so its run id stays the one the original fields derive.
    value = sidecar(h)
    value.update(changes)
    seed_run(h, entries=[{"step_id": STEP, "status": "completed", "workflow_run": value}])
    seed_workflow(h)
    seed_workflow(h, WATCHER_ID, name=WATCHER)
    seed_workflow_run(h)
    login(h)
    assert listed(h) == [] and reads(h) == (0, 0)
    mismatches = [entry for entry in h.record.logs if "workflow_run_link_mismatch" in entry["extra"]]
    assert len(mismatches) == 1
    # Application Insights keeps the code: the logger drops any text not under an allowlisted key.
    appinsights = importlib.import_module("functions_appinsights")
    kept = appinsights._build_logger_extra(
        mismatches[0]["message"], appinsights.sanitize_log_properties(json.loads(mismatches[0]["extra"])),
    )
    assert kept["sc_reason"] == "workflow_run_link_mismatch"


def test_the_link_is_read_from_the_step_record_when_the_run_has_none(h):
    seed_run(h, entries=[{"step_id": STEP, "status": "completed"}])
    h.modules.runs.save_orchestration_step(RUN, {"step_id": STEP, "status": "completed", "workflow_run": sidecar(h)})
    seed_workflow(h)
    run_id = seed_workflow_run(h)
    login(h)
    assert only(h)["workflow_run_id"] == run_id


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------

def _retry(h, run_id, *, turn_id=TURN, root=RUN, entry=None):
    h.runs.create_item({
        "id": run_id, "run_id": run_id, "conversation_id": CONVERSATION, "user_id": OWNER, "turn_id": turn_id,
        "status": "completed", "plan": _plan(turn_id=turn_id), "retry_of_run_id": RUN,
        "attempt_root_run_id": root, "attempt_index": 2,
        "execution_steps": [entry or {"step_id": STEP, "capability_id": "workflow_run", "status": "pending"}],
        "inherited_checkpoints": {STEP: {
            "source_run_id": RUN, "status": "completed", "provenance": {"run_id": RUN, "step_id": STEP},
        }},
    })


def test_a_retry_links_the_run_its_first_attempt_started(h):
    run_id = seed_started(h)
    _retry(h, RETRY)
    login(h)
    first, retried = only(h), only(h, RETRY)
    assert first == retried and retried["workflow_run_id"] == run_id

    # A retry that reused the step carries the sidecar rebuilt for its first attempt.
    _retry(h, SECOND, entry={
        "step_id": STEP, "capability_id": "workflow_run", "status": "completed", "reused": True,
        "reused_from_run_id": RUN, "workflow_run": sidecar(h, orchestration_run_id=RUN),
    })
    assert only(h, SECOND) == first


def test_a_retry_that_ran_the_step_again_links_the_same_run(h):
    run_id = seed_started(h)
    _retry(h, RETRY, entry={
        "step_id": STEP, "capability_id": "workflow_run", "status": "completed",
        "workflow_run": sidecar(h, orchestration_run_id=RETRY, status="already_started"),
    })
    login(h)
    assert only(h, RETRY)["workflow_run_id"] == run_id


def test_a_run_from_another_turn_or_plan_cannot_borrow_a_link(h):
    seed_started(h)
    _retry(h, RETRY, turn_id="turn-2")
    _retry(h, SECOND, root=SECOND)
    login(h)
    assert listed(h, RETRY) == [] and listed(h, SECOND) == []


# ---------------------------------------------------------------------------
# Failures, logs and the module's shape
# ---------------------------------------------------------------------------

def test_a_storage_failure_is_unavailable_and_echoes_nothing(h):
    seed_started(h)
    login(h)
    expected = {"error": "Workflow run links are unavailable right now. Try again later.", "code": "service_unavailable"}
    for container in (h.workflows, h.workflow_runs, h.steps, h.runs):
        container.fail_reads = True
        if container is h.steps:
            h.runs.items[(CONVERSATION, RUN)]["execution_steps"] = [{"step_id": STEP, "status": "completed"}]
        response = links(h)
        container.fail_reads = False
        assert response.status_code == 503 and response.get_json() == expected
    route_logs = [entry for entry in h.record.logs if entry["source"] == "route_backend_orchestration"]
    assert len(route_logs) == 4 and all('"error_type": "AzureError"' in entry["extra"] for entry in route_logs)
    assert all("Private test" not in entry["extra"] for entry in route_logs)
    # Application Insights keeps the stage, the error type and the hashed ids, never the raw ids.
    appinsights = importlib.import_module("functions_appinsights")
    for entry in route_logs:
        assert RUN not in entry["extra"] and CONVERSATION not in entry["extra"]
        kept = appinsights._build_logger_extra(
            entry["message"], appinsights.sanitize_log_properties(json.loads(entry["extra"])),
        )
        assert kept["sc_stage"] == "workflow_run_links" and kept["sc_error_type"] == "AzureError"
        assert kept["sc_run_id_hash"] == hashlib.sha256(RUN.encode("utf-8")).hexdigest()
        assert kept["sc_conversation_id_hash"] == hashlib.sha256(CONVERSATION.encode("utf-8")).hexdigest()


def test_logs_carry_codes_only(h):
    seed_run(h, entries=[{"step_id": STEP, "status": "completed", "workflow_run": sidecar(h, requested_by=OTHER)}])
    login(h)
    listed(h)
    ours = [entry for entry in h.record.logs if entry["source"] == "functions_orchestration_workflow_run_links"]
    assert ours and all(entry["message"].startswith("[ORCHESTRATION_WORKFLOW_RUN_LINKS] ") for entry in ours)
    text = json.dumps(ours, ensure_ascii=False)
    for private in (NAME, WORKFLOW_ID, RUN, CONVERSATION, OWNER, OTHER, run_id_for(h)):
        assert private not in text


def _imports(nodes):
    names = {}
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            names.setdefault(node.module, set()).update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.setdefault(alias.name, set())
    return names


def test_the_link_module_only_reads_and_never_imports_flask():
    tree = ast.parse((APP_ROOT / "functions_orchestration_workflow_run_links.py").read_text(encoding="utf-8"))
    everything = _imports(ast.walk(tree))
    top_level = _imports(tree.body)
    lazy = _imports(
        node for function in ast.walk(tree) if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
    )
    assert not any(name.split(".")[0] == "flask" for name in everything)
    assert not {"config", "functions_workflow_runtime", "functions_workflow_runtime_store"} & set(top_level)
    assert lazy == {
        "config": {"cosmos_personal_workflows_container", "cosmos_personal_workflow_runs_container"},
        "functions_workflow_runtime_store": {"WAITING_STATES"},
    }
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    writes = {"create_item", "upsert_item", "replace_item", "delete_item", "patch_item", "execute_item_batch"}
    assert not writes & called
    logged = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_log"]
    assert logged
    for call in logged:
        assert call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str), call.lineno


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
