#!/usr/bin/env python3
# test_workflow_plan_replay_routes.py
"""
Functional test for the saved-plan replay routes: preview and save a completed chat plan.
Version: 0.261.307
Implemented in: 0.261.307

This test ensures that only the creator, in a private conversation they own, can preview or save a
completed chat orchestration plan as a personal workflow that repeats it. The preview discloses
every frozen step and writes nothing. Saving needs the previewed hash, creates one paused personal
workflow under the creator, and a repeat returns the same workflow. A refused step, a schedule that
is too frequent, a lost source, a stale hash or the setting being off creates nothing, with a fixed
reason. A workflow's frozen plan stays read-only through the ordinary save path, and the chat
routes never run, retry, edit, revise or cancel a replay run that a workflow run owns. A saved
workflow starts with one editable 'Run failed' alert rule that a re-save never adds back, and a
refused scheduled run reaches the creator's bell with its fixed reason through the production
workflow runner.

The production Flask routes, Blueprint guards, replay module and personal workflow store run
unchanged against in-memory storage, with the network blocked.
"""

import importlib
import json
import re
import sys
import uuid
from copy import deepcopy
from types import SimpleNamespace

import pytest
from azure.core.exceptions import AzureError
from flask import Blueprint, Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_orchestration_harness_routes import modules  # noqa: F401
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least


OWNER = "owner"
OTHER = "someone-else"
TENANT = "tenant-1"
EMAIL = "owner@example.com"
CONVERSATION = "conversation-1"
OTHER_CONVERSATION = "conversation-2"
RUN = "run_" + "1" * 32
REPLAY_RUN = "run_" + "2" * 32
# Hostile on purpose: the routes return them only as JSON data, and no log may carry them.
HOSTILE_NAME = '<img src=x onerror="alert(1)">Weekly"\'</script> notes'
HOSTILE_TITLE = '<script>alert("title")</script>Summarize'
HOSTILE_REQUEST = "SECRET_REQUEST <b onmouseover=alert(1)>Summarize my notes</b>"
REPLAY_SETTINGS = {
    "enable_workflow_plan_replay": True,
    "enable_chat_orchestration": True,
    "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
    "enable_user_workspace": True,
    "enable_group_workspaces": True,
    "chat_orchestration_enabled_capabilities": [],
}
DAILY = {"unit": "hours", "value": 24}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class WorkflowStore(AtomicMemoryContainer):
    """Personal workflows, answering the orchestration count query the per-user cap runs."""

    def query_items(self, query=None, parameters=None, partition_key=None, **kwargs):
        if query and "COUNT(1)" in query:
            values = {entry["name"]: entry["value"] for entry in parameters or []}
            with self._lock:
                return [sum(
                    1 for (partition, _), record in self.items.items()
                    if partition == partition_key and record.get("deleting") is not True
                    and (record.get("origin") or {}).get("source") == values.get("@source")
                )]
        return super().query_items(query, parameters=parameters, partition_key=partition_key, **kwargs)


def _log_recorder(logs, source):
    def log_event(message, *args, **kwargs):
        logs.append({
            "source": source, "message": str(message),
            "extra": json.dumps(kwargs.get("extra"), default=str, ensure_ascii=False),
        })
    return log_event


@pytest.fixture
def h(modules, monkeypatch):
    replay = importlib.import_module("functions_workflow_plan_replay")
    personal = importlib.import_module("functions_personal_workflows")
    settings_module = importlib.import_module("functions_settings")
    conversations = AtomicMemoryContainer("id")
    runs = AtomicMemoryContainer("conversation_id")
    steps = AtomicMemoryContainer("run_id")
    workflows = WorkflowStore("user_id")
    state = SimpleNamespace(
        settings={**deepcopy(settings_module.get_settings() or {}), **deepcopy(REPLAY_SETTINGS)},
        logs=[], created=[],
    )
    for module, name, value in (
        (modules.config, "cosmos_conversations_container", conversations),
        (modules.route, "cosmos_conversations_container", conversations),
        (modules.config, "cosmos_orchestration_runs_container", runs),
        (modules.runs, "cosmos_orchestration_runs_container", runs),
        (modules.config, "cosmos_orchestration_run_steps_container", steps),
        (modules.runs, "cosmos_orchestration_run_steps_container", steps),
        (modules.config, "cosmos_personal_workflows_container", workflows),
        (personal, "cosmos_personal_workflows_container", workflows),
    ):
        monkeypatch.setattr(module, name, value)

    def current_settings():
        return deepcopy(state.settings)

    # The real check reads user settings, whose profile-image refresh would reach Microsoft Entra.
    monkeypatch.setattr(modules.auth, "check_user_access_status", lambda user_id: (True, None))
    for module in (modules.route, settings_module, personal):
        monkeypatch.setattr(module, "get_settings", current_settings)
    monkeypatch.setattr(modules.route, "log_workflow_creation", lambda **kwargs: state.created.append(kwargs))
    for module in (modules.route, replay, personal):
        monkeypatch.setattr(module, "log_event", _log_recorder(state.logs, module.__name__))

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="workflow-plan-replay-routes")
    blueprint = Blueprint("backend_orchestration", __name__)
    blueprint.before_request(modules.auth.user_required_blueprint())
    modules.route.register_route_backend_orchestration(blueprint)
    app.register_blueprint(blueprint)
    conversations.create_item({"id": CONVERSATION, "user_id": OWNER, "title": "Private"})
    conversations.create_item({"id": OTHER_CONVERSATION, "user_id": OWNER, "title": "Another"})
    return SimpleNamespace(
        modules=modules, replay=replay, personal=personal, app=app, client=Client(app, Response),
        conversations=conversations, runs=runs, workflows=workflows, state=state,
    )


def login(h, *, user_id=OWNER, roles=("User",), app=None, client=None):
    app, client = app or h.app, client or h.client
    serializer = app.session_interface.get_signing_serializer(app)
    cookie = serializer.dumps({
        "user": {"oid": user_id, "roles": list(roles), "tid": TENANT, "preferred_username": EMAIL},
    })
    client.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie)


def _step(capability_id, number=1, title=None, **arguments):
    return {
        "step_id": f"s{number}", "capability_id": capability_id, "title": title or f"Step {number}",
        "arguments": arguments, "depends_on": [], "enabled": True,
    }


def _plan(*steps):
    return {"plan_id": "plan-1", "planner_contract_version": 2, "steps": list(steps)}


def seed_run(h, run_id=RUN, **changes):
    record = {
        "id": run_id, "run_id": run_id, "conversation_id": CONVERSATION, "user_id": OWNER,
        "status": "completed", "outcome": "completed", "approval": {"state": "approved"},
        "plan": _plan(_step("compose", title=HOSTILE_TITLE, instruction="Summarize the notes.")),
        "user_message": HOSTILE_REQUEST,
        "resolved_message": f"{HOSTILE_REQUEST}\n\nCurrent date and time: Monday, 28 September 2026, 09:00 (UTC)",
        "seeds": {"doc_scope": "personal"}, "answered_questions": [], "conversation_context": {},
        "time_zone": "America/New_York",
    }
    record.update(deepcopy(changes))
    if isinstance(record.get("plan"), dict):
        # A saved plan always names its run, as the revision store checks.
        record["plan"].setdefault("run_id", run_id)
    h.runs.create_item(record)
    return record


def _url(run_id=RUN):
    return f"/api/v2/orchestration/runs/{run_id}/plan-replay"


def preview(h, run_id=RUN, conversation_id=CONVERSATION):
    query = f"?conversation_id={conversation_id}" if conversation_id is not None else ""
    response = h.client.get(_url(run_id) + query)
    return response.status_code, response.get_json()


def save(h, run_id=RUN, **body):
    response = h.client.post(_url(run_id), json=body)
    return response.status_code, response.get_json()


def save_previewed(h, run_id=RUN, **changes):
    status, shown = preview(h, run_id)
    require(status == 200 and shown["eligible"] is True, f"The preview must be eligible: {status} {shown}")
    body = {
        "conversation_id": CONVERSATION, "plan_sha256": shown["plan_sha256"], "name": HOSTILE_NAME,
        "trigger_type": "interval", "schedule": deepcopy(DAILY),
    }
    body.update(changes)
    return save(h, run_id, **body)


def stored(h):
    return [deepcopy(record) for (partition, _), record in h.workflows.items.items() if partition == OWNER]


def _refused(response, status, code):
    actual_status, body = response
    require(actual_status == status, f"Expected {status} {code}, got {actual_status}: {body}")
    require(isinstance(body, dict) and body.get("code") == code, f"Expected {code}: {body}")
    require(isinstance(body.get("error"), str) and body["error"], "Every refusal carries fixed text.")
    return body


def _require_no_hostile_text_in_logs(h):
    for entry in h.state.logs:
        text = entry["message"] + entry["extra"]
        for secret in (HOSTILE_NAME, HOSTILE_TITLE, "SECRET_REQUEST", "onerror", "<script>"):
            require(secret not in text, f"A log carried caller text: {entry}")


def test_version_includes_plan_replay():
    assert_app_version_at_least("0.261.307")


def test_the_preview_discloses_every_frozen_step_and_writes_nothing(h):
    seed_run(h, plan=_plan(
        _step("document_search", 1, title=HOSTILE_TITLE, query="notes"),
        _step("compose", 2, title="Write the summary", instruction="Summarize the notes."),
    ))
    before = deepcopy(h.runs.items)
    login(h)
    status, shown = preview(h)
    require(status == 200, f"{status} {shown}")
    require(shown["eligible"] is True and shown["refusals"] == [], str(shown))
    require([step["title"] for step in shown["steps"]] == [HOSTILE_TITLE, "Write the summary"],
            "Titles come back as data, unchanged, for the card to render as text.")
    require([step["capability_id"] for step in shown["steps"]] == ["document_search", "compose"], str(shown))
    labels = [step["capability_label"] for step in shown["steps"]]
    require(all(isinstance(label, str) and label and "<" not in label for label in labels),
            f"Each step carries the registry's label, never model text: {labels}")
    require(re.fullmatch(r"[0-9a-f]{64}", shown["plan_sha256"]), "The preview names the plan's SHA-256 hash.")
    require(shown["request"] == HOSTILE_REQUEST, "The request drops the run-time line and nothing else.")
    require(shown["time_handling"] == h.replay.PLAN_REPLAY_TIME_HANDLING, str(shown))
    require(shown["allowlist_version"] == h.replay.PLAN_REPLAY_ALLOWLIST_VERSION, str(shown))
    require(isinstance(shown["min_interval_seconds"], int) and shown["min_interval_seconds"] > 0, str(shown))
    require(h.runs.items == before and stored(h) == [], "A preview writes nothing.")


def test_saving_creates_one_paused_personal_workflow_that_repeats_the_frozen_plan(h):
    seed_run(h)
    login(h)
    _status, shown = preview(h)
    status, body = save_previewed(h)
    require(status == 201 and body["created"] is True, f"{status} {body}")
    records = stored(h)
    require(len(records) == 1, f"Exactly one workflow is created: {records}")
    workflow = records[0]
    require(workflow["id"] == body["workflow"]["id"], "The response names the stored workflow.")
    require(workflow["user_id"] == OWNER and workflow.get("created_by") == OWNER, "The creator owns it.")
    require(not workflow.get("group_id") and workflow.get("is_enabled") is False, "It is personal and paused.")
    require(workflow.get("durable_execution") is True, "A replay workflow runs under the durable workflow lease.")
    require(workflow["name"] == HOSTILE_NAME[:120], "The name is stored as data.")
    require(workflow["schedule"].get("unit") == "hours" and workflow["schedule"].get("value") == 24, str(workflow))
    origin = workflow.get("origin") or {}
    require(origin.get("source") == "orchestration" and origin.get("orchestration_run_id") == RUN, str(origin))
    require(origin.get("conversation_id") == CONVERSATION, "Provenance names the chat the plan came from.")
    tasks = workflow["tasks"]
    require(len(tasks) == 1 and tasks[0]["type"] == h.replay.PLAN_REPLAY_TASK_TYPE, str(tasks))
    data = tasks[0]["plan_replay"]
    require(data["plan_sha256"] == shown["plan_sha256"], "The saved hash is the previewed hash.")
    require(data["allowlist_version"] == h.replay.PLAN_REPLAY_ALLOWLIST_VERSION, str(data))
    require([step["title"] for step in data["frozen_plan"]["steps"]] == [HOSTILE_TITLE], str(data))
    require(len(h.state.created) == 1, "The creation is logged once.")

    again_status, again = save_previewed(h)
    require(again_status == 200 and again["created"] is False, f"{again_status} {again}")
    require(again["workflow"]["id"] == workflow["id"] and len(stored(h)) == 1, "Saving again adopts the first save.")
    require(len(h.state.created) == 1, "Only a created workflow is logged.")
    _require_no_hostile_text_in_logs(h)


RUN_FAILED_RULE = {
    "name": "Run failed", "enabled": True, "severity": "high", "delivery": "notify_only",
    "scope": {"type": "final", "task_id": ""},
    "condition": {"type": "run_status", "statuses": ["failed", "completed_with_task_errors"]},
    "order": 1,
}


def _rules_without_ids(workflow):
    rules = deepcopy(workflow.get("alert_rules") or [])
    for rule in rules:
        rule.pop("id", None)
    return rules


def test_a_saved_replay_workflow_starts_with_one_editable_run_failed_alert(h):
    seed_run(h)
    login(h)
    # The server picks the starting alert; alert fields in the request body are ignored.
    status, body = save_previewed(h, alert_mode="off", alert_rules=[], alert_priority="high")
    require(status == 201, f"{status} {body}")
    workflow = stored(h)[0]
    require(workflow.get("alert_mode") == "rules", f"A failed run reaches the bell: {workflow.get('alert_mode')}")
    require(_rules_without_ids(workflow) == [RUN_FAILED_RULE], f"Exactly one default rule: {workflow.get('alert_rules')}")
    rule_id = workflow["alert_rules"][0]["id"]
    require(str(uuid.UUID(rule_id)) == rule_id, f"The rule has a stable UUID: {rule_id}")
    require(workflow.get("alert_priority") == "none", "No pop-up on every run.")

    again_status, again = save_previewed(h)
    require(again_status == 200 and again["created"] is False, f"{again_status} {again}")
    require(stored(h)[0]["alert_rules"] == workflow["alert_rules"], "Saving the plan again never adds a second rule.")

    editor = json.loads(json.dumps(body["workflow"]))
    editor["alert_mode"] = "off"
    editor["alert_rules"] = []
    saved = h.personal.save_personal_workflow(OWNER, editor, actor_user_id=OWNER)
    require(saved["alert_mode"] == "off" and saved["alert_rules"] == [], "The creator can change the alert.")
    require(saved["tasks"][0]["plan_replay"] == workflow["tasks"][0]["plan_replay"], "Editing alerts leaves the plan alone.")
    status, again = save_previewed(h)
    require(status == 200 and again["created"] is False, f"{status} {again}")
    require(stored(h)[0]["alert_rules"] == [] and stored(h)[0]["alert_mode"] == "off",
            "Saving the plan again never puts back an alert the creator removed.")


def test_a_refused_replay_run_reaches_the_bell_with_its_fixed_reason(h, monkeypatch):
    runner = importlib.import_module("functions_workflow_runner")
    seed_run(h)
    login(h)
    status, body = save_previewed(h, enabled=True)
    require(status == 201, f"{status} {body}")
    workflow = stored(h)[0]
    require(workflow["durable_execution"] is True and workflow["tasks"][0]["type"] == h.replay.PLAN_REPLAY_TASK_TYPE,
            "The saved replay workflow is the one the scheduler runs.")
    # An admin turns repeating off after the workflow was saved, so its next scheduled run is refused.
    h.state.settings["enable_workflow_plan_replay"] = False
    saved_items, notifications, harness, runner_logs = [], [], [], []
    conversation = {"id": "workflow-conversation", "user_id": OWNER, "chat_type": "workflow", "workflow_id": workflow["id"]}

    def never_replayed(*args, **kwargs):
        harness.append(kwargs)
        raise AssertionError("A refused replay never reaches the harness.")

    def notify(**kwargs):
        notifications.append(deepcopy(kwargs))
        return {"id": "notification-1", **kwargs}

    # The production runner, task sequence, replay task and alert rules run; only storage and the bell are stubbed.
    for name, value in (
        ("get_settings", lambda: deepcopy(h.state.settings)),
        ("_get_workflow_run_record", lambda workflow, run_id: None),
        ("_save_workflow_run_record", lambda workflow, record: record),
        ("_save_workflow_run_item_record", lambda workflow, item: saved_items.append(deepcopy(item)) or item),
        ("_is_workflow_run_cancellation_requested", lambda workflow, run_id: False),
        ("_ensure_workflow_conversation", lambda workflow: dict(conversation)),
        ("_create_user_message", lambda *args, **kwargs: {"id": "user-message", "conversation_id": conversation["id"]}),
        ("_initialize_workflow_assistant_tracking", lambda *args, **kwargs: ("assistant-message", None)),
        ("_prepare_workflow_url_access_context", lambda *args, **kwargs: {}),
        ("create_workflow_priority_notification", notify),
        ("log_workflow_run", lambda **kwargs: None),
        ("log_event", _log_recorder(runner_logs, runner.__name__)),
    ):
        monkeypatch.setattr(runner, name, value)
    monkeypatch.setattr(h.replay, "_authorize_current_workflow", never_replayed)
    monkeypatch.setattr(h.modules.runs, "create_orchestration_run", never_replayed)

    result = runner._run_authorized_workflow_impl(
        deepcopy(workflow), trigger_source="scheduled", actor_user_id=OWNER, run_id="workflow-run-1",
    )
    reason = h.replay.REFUSAL_MESSAGES["replay_disabled"]
    run = result["run"]
    require(result["success"] is False and run["status"] == "failed", f"The run fails: {run}")
    require(reason in run["error"], f"The run carries the fixed reason: {run['error']}")
    require(harness == [], "The refusal comes before anything is replayed.")
    failed = [item for item in saved_items if item.get("status") == "failed"]
    require(len(failed) == 1 and failed[0]["error"] == reason, f"The task shows the fixed reason: {saved_items}")
    require(len(notifications) == 1, f"Exactly one bell notification: {notifications} {runner_logs}")
    note = notifications[0]
    metadata = note["metadata"]
    require(note["user_id"] == OWNER and note["priority"] == "high", f"The creator's bell, high: {note}")
    require(note["title"] == f"High priority workflow alert: {runner._normalize_workflow_alert_title_text(HOSTILE_NAME)} failed",
            f"The bell names the failed workflow: {note['title']}")
    require(reason.split(". ")[0] in note["message"], f"The bell message carries the reason: {note['message']}")
    require(metadata["delivery"] == "notify_only" and metadata["alert_mode"] == "rules", f"The default rule: {metadata}")
    require([rule["rule_name"] for rule in metadata["matched_rules"]] == ["Run failed"], str(metadata["matched_rules"]))
    require(metadata["trigger_source"] == "scheduled" and metadata["status"] == "failed", str(metadata))
    require(reason in metadata["error"] and reason in metadata["alert_detail"], f"The full fixed reason: {metadata}")
    require(metadata["conversation_id"] == conversation["id"], "The bell links to the workflow's own conversation.")
    require(conversation["id"] in note["link_url"] and CONVERSATION not in note["link_url"],
            f"The bell opens the workflow's conversation, never the source chat: {note['link_url']}")
    require(result["notification"]["id"] == "notification-1", "The run returns the bell notification.")
    require(run["alert_decision"]["should_alert"] is True, f"The run explains its alert: {run.get('alert_decision')}")
    text = json.dumps(note, default=str, ensure_ascii=False)
    for secret in ("SECRET_REQUEST", HOSTILE_TITLE, "Summarize the notes"):
        require(secret not in text, f"No request, plan or model text reaches the bell: {secret}")


def test_saving_can_turn_the_workflow_on_when_the_creator_chooses(h):
    seed_run(h)
    login(h)
    status, body = save_previewed(h, enabled=True)
    require(status == 201 and stored(h)[0]["is_enabled"] is True, f"{status} {body}")


def test_running_a_saved_replay_workflow_queues_one_durable_run_for_its_creator(h, monkeypatch):
    routes = importlib.import_module("route_backend_workflows")
    seed_run(h)
    login(h)
    status, body = save_previewed(h)
    require(status == 201, f"{status} {body}")
    workflow_id = body["workflow"]["id"]
    queued = []

    def queue(workflow, **kwargs):
        queued.append({"workflow": deepcopy(workflow), **kwargs})
        return {"success": True, "workflow": deepcopy(workflow), "run": {
            "id": "workflow-run-1", "workflow_id": workflow["id"], "status": "queued", "success": None,
            "durable_execution": True, "started_at": None, "completed_at": None, "actor_user_id": OWNER,
        }}

    def run_in_request(*args, **kwargs):
        raise AssertionError("A durable replay workflow never runs inside the request.")

    monkeypatch.setattr(routes, "queue_durable_workflow_run", queue)
    monkeypatch.setattr(routes, "run_personal_workflow", run_in_request)
    # The production registration: the workflow routes behind the user Blueprint guard.
    app = Flask("workflow_plan_replay_run")
    app.config.update(TESTING=True, SECRET_KEY=h.app.config["SECRET_KEY"])
    blueprint = Blueprint("backend_workflows", __name__)
    blueprint.before_request(h.modules.auth.user_required_blueprint())
    routes.register_route_backend_workflows(blueprint)
    app.register_blueprint(blueprint)
    client = Client(app, Response)
    login(h, app=app, client=client)

    response = client.post(f"/api/user/workflows/{workflow_id}/run", json={})
    payload = response.get_json()
    require(response.status_code == 202, f"A replay run is queued, not run inline: {response.status_code} {payload}")
    require(payload["run"] == {
        "id": "workflow-run-1", "workflow_id": workflow_id, "status": "queued", "success": None,
        "durable_execution": True, "started_at": None, "completed_at": None,
    }, f"Only the public run fields come back: {payload['run']}")
    require(len(queued) == 1, f"Exactly one durable run is queued: {queued}")
    call = queued[0]
    require(call["actor_user_id"] == OWNER and call.get("request_id") is None, f"The creator is the actor: {call}")
    require(set(call) == {"workflow", "actor_user_id", "request_id"}, f"No other identity is passed: {call}")
    require(call["workflow"]["id"] == workflow_id and call["workflow"]["durable_execution"] is True,
            "The stored durable workflow is the one queued.")
    require(call["workflow"]["tasks"][0]["type"] == h.replay.PLAN_REPLAY_TASK_TYPE, str(call["workflow"]["tasks"]))


@pytest.mark.parametrize("plan_sha256", [None, "", "0" * 64, "not-a-hash"])
def test_saving_needs_the_previewed_hash(h, plan_sha256):
    seed_run(h)
    login(h)
    body = {"conversation_id": CONVERSATION, "name": "Weekly", "schedule": deepcopy(DAILY)}
    if plan_sha256 is not None:
        body["plan_sha256"] = plan_sha256
    _refused(save(h, **body), 409, "plan_hash_mismatch")
    require(stored(h) == [], "A stale or missing hash creates nothing.")


def test_a_plan_that_changed_after_the_preview_is_refused(h):
    seed_run(h)
    login(h)
    _status, shown = preview(h)
    h.runs.items[(CONVERSATION, RUN)]["plan"]["steps"][0]["arguments"]["instruction"] = "Email everyone."
    _refused(save(h, conversation_id=CONVERSATION, plan_sha256=shown["plan_sha256"], schedule=deepcopy(DAILY)),
             409, "plan_hash_mismatch")
    require(stored(h) == [], "A plan that changed since the preview creates nothing.")


def test_requests_without_a_conversation_are_refused(h):
    seed_run(h)
    login(h)
    _refused(preview(h, conversation_id=None), 422, "invalid_request")
    for raw in ("[]", "null", "not json"):
        response = h.client.post(_url(), data=raw, content_type="application/json")
        _refused((response.status_code, response.get_json()), 422, "invalid_request")
    _refused(save(h, name="Weekly"), 422, "invalid_request")
    require(stored(h) == [], "Nothing is created.")


def test_another_users_run_or_conversation_reads_as_missing(h):
    seed_run(h)
    seed_run(h, run_id=REPLAY_RUN, user_id=OTHER)
    login(h, user_id=OTHER)
    _refused(preview(h), 404, "run_not_found")
    _refused(save(h, conversation_id=CONVERSATION, plan_sha256="0" * 64), 404, "run_not_found")
    login(h)
    _refused(preview(h, run_id=REPLAY_RUN), 404, "run_not_found")
    _refused(preview(h, conversation_id=OTHER_CONVERSATION), 404, "run_not_found")
    _refused(preview(h, conversation_id="missing-conversation"), 404, "run_not_found")
    _refused(preview(h, run_id="run_" + "9" * 32), 404, "run_not_found")
    require(stored(h) == [], "Nothing is created.")


@pytest.mark.parametrize("setting, status, code", [
    ("enable_workflow_plan_replay", 403, "replay_disabled"),
    ("enable_chat_orchestration", 403, "orchestration_disabled"),
])
def test_the_settings_are_checked_before_anything_is_read(h, setting, status, code):
    seed_run(h)
    login(h)
    h.state.settings[setting] = False
    _refused(preview(h), status, code)
    _refused(save(h, conversation_id=CONVERSATION, plan_sha256="0" * 64), status, code)
    require(stored(h) == [], "Nothing is created.")


def test_personal_workflows_off_blocks_both_routes(h):
    seed_run(h)
    login(h)
    h.state.settings["allow_user_workflows"] = False
    status, body = preview(h)
    require(status == 400 and "disabled" in body["error"], f"{status} {body}")
    status, body = save(h, conversation_id=CONVERSATION, plan_sha256="0" * 64)
    require(status == 400 and stored(h) == [], f"{status} {body}")


def test_a_schedule_faster_than_the_chat_minimum_is_refused(h):
    seed_run(h)
    login(h)
    _refused(save_previewed(h, schedule={"unit": "minutes", "value": 5}), 422, "cadence_below_minimum")
    require(stored(h) == [], "A too-frequent schedule creates nothing.")


def test_a_refused_step_is_named_and_nothing_is_created(h):
    seed_run(h, plan=_plan(
        _step("deep_research", 1, title=HOSTILE_TITLE, query="news"),
        _step("render_file", 2, format="pdf"),
        _step("compose", 3, instruction="Summarize."),
    ))
    login(h)
    status, shown = preview(h)
    require(status == 200 and shown["eligible"] is False, f"{status} {shown}")
    codes = [(refusal["step_number"], refusal["code"]) for refusal in shown["refusals"]]
    require(codes == [(1, "capability_not_replayable"), (2, "replay_wait_unsupported")], str(codes))
    require(all(refusal["message"] for refusal in shown["refusals"]), "Each refusal carries fixed text.")
    body = _refused(save(h, conversation_id=CONVERSATION, plan_sha256=shown["plan_sha256"]),
                    422, "capability_not_replayable")
    require([item["code"] for item in body["refusals"]] == ["capability_not_replayable", "replay_wait_unsupported"],
            str(body))
    require(stored(h) == [], "A refused plan creates nothing.")


@pytest.mark.parametrize("changes, status, code", [
    ({"collaboration_conversation_id": "collab-1"}, 403, "shared_conversation_not_allowed"),
    ({"chat_type": "personal_multi_user"}, 403, "shared_conversation_not_allowed"),
])
def test_a_shared_conversation_cannot_be_saved(h, changes, status, code):
    seed_run(h)
    h.conversations.items[(CONVERSATION, CONVERSATION)].update(changes)
    login(h)
    _refused(preview(h), status, code)
    _refused(save(h, conversation_id=CONVERSATION, plan_sha256="0" * 64), status, code)
    require(stored(h) == [], "Nothing is created.")


@pytest.mark.parametrize("changes, code", [
    ({"status": "running"}, "source_run_not_eligible"),
    ({"approval": {"state": "pending"}}, "source_run_not_eligible"),
    ({"workflow_replay": {"workflow_id": "workflow-1"}}, "source_run_not_eligible"),
    ({"answered_questions": [{"question": "Which?", "answer": "This"}]}, "elicitation_not_replayable"),
])
def test_a_run_that_must_not_repeat_cannot_be_saved(h, changes, code):
    seed_run(h, **changes)
    login(h)
    status = h.replay.PLAN_REPLAY_ERROR_STATUS.get(code, 422)
    _refused(preview(h), status, code)
    _refused(save(h, conversation_id=CONVERSATION, plan_sha256="0" * 64), status, code)
    require(stored(h) == [], "Nothing is created.")


def test_a_group_the_creator_left_is_refused_when_saving(h, monkeypatch):
    seed_run(h, seeds={"doc_scope": "group", "active_group_ids": ["group-1"]})
    group_module = importlib.import_module("functions_group")
    monkeypatch.setattr(group_module, "find_group_by_id", lambda group_id: None)
    login(h)
    _refused(save_previewed(h), 422, "source_unavailable")
    require(stored(h) == [], "A source the creator cannot reach creates nothing.")


def test_a_store_failure_is_a_fixed_error_without_detail(h, monkeypatch):
    seed_run(h)
    login(h)
    _status, shown = preview(h)

    def fail(*_args, **_kwargs):
        raise AzureError("Private test failure SECRET_STORE_DETAIL")

    monkeypatch.setattr(h.workflows, "create_item", fail)
    status, body = save(h, conversation_id=CONVERSATION, plan_sha256=shown["plan_sha256"],
                        schedule=deepcopy(DAILY))
    require(status == 503 and body["code"] == "service_unavailable", f"{status} {body}")
    require("SECRET_STORE_DETAIL" not in json.dumps(body), "The response never echoes a store error.")
    require(all("SECRET_STORE_DETAIL" not in entry["message"] + entry["extra"] for entry in h.state.logs),
            "Logs carry the error type, never its text.")


def test_a_workflow_being_deleted_is_a_conflict_and_a_deleted_one_is_created_again(h):
    seed_run(h)
    login(h)
    _status, first = save_previewed(h)
    key = (OWNER, first["workflow"]["id"])
    h.workflows.items[key]["deleting"] = True
    _refused(save_previewed(h), 409, "workflow_conflict")
    del h.workflows.items[key]
    status, again = save_previewed(h)
    require(status == 201 and again["created"] is True, f"{status} {again}")
    require(stored(h)[0]["is_enabled"] is False, "A workflow created again starts paused.")


def test_the_frozen_plan_stays_read_only_through_the_ordinary_save(h):
    seed_run(h)
    login(h)
    _status, body = save_previewed(h)
    # The editor's copy goes through JSON, as it would through a browser.
    editor = json.loads(json.dumps(body["workflow"]))
    original = stored(h)[0]["tasks"][0]["plan_replay"]

    renamed = deepcopy(editor)
    renamed["name"] = "Renamed weekly notes"
    saved = h.personal.save_personal_workflow(OWNER, renamed, actor_user_id=OWNER)
    require(saved["name"] == "Renamed weekly notes", "The name stays editable.")
    require(saved["tasks"][0]["type"] == h.replay.PLAN_REPLAY_TASK_TYPE, "The task keeps its type.")
    require(saved["tasks"][0]["plan_replay"]["plan_sha256"] == original["plan_sha256"], "The plan is unchanged.")

    # The chat-workflow cadence floor applies every time the schedule is saved, not only at creation.
    faster = json.loads(json.dumps(saved))
    faster["schedule"] = {"unit": "minutes", "value": 5}
    cadence_error = importlib.import_module("functions_workflow_definitions").WorkflowCadenceError
    with pytest.raises(cadence_error):
        h.personal.save_personal_workflow(OWNER, faster, actor_user_id=OWNER)

    tampered = json.loads(json.dumps(stored(h)[0]))
    tampered["tasks"][0]["plan_replay"]["frozen_plan"]["steps"][0]["arguments"]["instruction"] = "Email everyone."
    with pytest.raises(h.replay.PlanReplaySaveError) as caught:
        h.personal.save_personal_workflow(OWNER, tampered, actor_user_id=OWNER)
    require(caught.value.code == "plan_replay_read_only", caught.value.code)

    forged = {
        "name": "Forged", "trigger_type": "manual",
        "tasks": [deepcopy(stored(h)[0]["tasks"][0])],
    }
    with pytest.raises(h.replay.PlanReplaySaveError) as caught:
        h.personal.save_personal_workflow(OWNER, forged, actor_user_id=OWNER)
    require(caught.value.code == "plan_replay_read_only", "Only the replay builder creates a replay task.")
    require(stored(h)[0]["tasks"][0]["plan_replay"] == original, "The stored frozen plan never changed.")


def _replay_run(h):
    return seed_run(h, run_id=REPLAY_RUN, status="running", outcome=None, workflow_replay={
        "workflow_id": "workflow-1", "workflow_run_id": "workflow-run-1", "task_id": "task-1", "attempt": 0,
    })


def _managed(response):
    status, body = response.status_code, response.get_json()
    require(status == 409 and body.get("code") == "workflow_replay_run_managed", f"{status} {body}")
    require(body["error"] == h_message(), body)


def h_message():
    return importlib.import_module("functions_workflow_plan_replay").REFUSAL_MESSAGES["workflow_replay_run_managed"]


def test_chat_routes_never_drive_a_run_its_workflow_owns(h):
    _replay_run(h)
    before = deepcopy(h.runs.items[(CONVERSATION, REPLAY_RUN)])
    login(h)
    _managed(h.client.post("/api/v2/orchestration/run", json={
        "run_id": REPLAY_RUN, "conversation_id": CONVERSATION,
    }))
    _managed(h.client.post(f"/api/v2/orchestration/cancel/{REPLAY_RUN}", json={"conversation_id": CONVERSATION}))
    _managed(h.client.post(f"/api/v2/orchestration/runs/{REPLAY_RUN}/edit", json={"conversation_id": CONVERSATION}))
    _managed(h.client.post(f"/api/v2/orchestration/runs/{REPLAY_RUN}/revisions", json={
        "conversation_id": CONVERSATION, "submission_id": str(uuid.uuid4()),
    }))
    require(h.runs.items[(CONVERSATION, REPLAY_RUN)] == before, "A refused chat request changes nothing.")


def test_retry_refuses_a_failed_replay_attempt_that_recovery_would_otherwise_accept(h):
    recovery = importlib.import_module("functions_orchestration_recovery")
    seed_run(
        h, run_id=REPLAY_RUN, status="failed", outcome="failed", started_at="2026-09-28T09:00:00+00:00",
        checkpoint_version=recovery.CHECKPOINT_VERSION, execution_binding="binding-1", recovery_version="v1",
        workflow_replay={"workflow_id": "workflow-1", "workflow_run_id": "workflow-run-1", "task_id": "task-1"},
    )
    require(recovery.recovery_projection(h.runs.items[(CONVERSATION, REPLAY_RUN)])["eligible"],
            "Without the replay guard this attempt could be retried from chat.")
    before = deepcopy(h.runs.items[(CONVERSATION, REPLAY_RUN)])
    login(h)
    _managed(h.client.post(f"/api/v2/orchestration/runs/{REPLAY_RUN}/retry", json={
        "conversation_id": CONVERSATION, "submission_id": str(uuid.uuid4()), "expected_version": "v1",
    }))
    require(h.runs.items[(CONVERSATION, REPLAY_RUN)] == before, "A refused retry changes nothing.")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:langsmith_plugin", "-p", "no:cacheprovider"]))
