#!/usr/bin/env python3
# test_orchestration_workflow_handoff_routes.py
"""
Functional test for the one-time workflow hand-off accept-and-run routes.
Version: 0.261.239
Implemented in: 0.261.239

This test ensures that the requester-only routes under
``/api/v2/orchestration/runs/<run_id>/workflow-handoffs``:

- re-authorize every request: a signed-in user with the user role, Allow User Workflows, the
  workflow role, the requester's own private conversation, the run and its hand-off step, and
  every hand-off gate;
- refuse a Phase 4 workflow proposal, while Phase 4's accept refuses a hand-off and never takes a
  one-time workflow at a proposal's id for that proposal's workflow;
- rebuild and revalidate the blueprint before anything is written, with the bound the card
  disclosed: a loop limit lowered below it refuses the accept, and a raised one never widens it;
- claim the hand-off before the create and release the claim when the create fails;
- create the one-time workflow disabled, with a deterministic id and a one-time origin, and queue
  exactly one durable run through the real durable queue, with the chat invocation and delivery
  record 6b-1 reads;
- retry a created-but-not-queued accept without a second workflow or a second run;
- hold the rolling daily hand-off limit, and keep hand-offs out of Phase 4's workflow cap;
- never return exception text, the model selection or an internal document or scope id outside
  the editor draft, and never log them.

Checks use explicit raises, so they hold under ``python -O``.
"""

import functools
import importlib
import json
import sys
import uuid
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos import exceptions
from flask import Blueprint, Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_handoff_planner import (
    _context,
    _handles,
    _handoff_step,
    _require,
    _same,
)
from test_orchestration_workflow_proposal_routes import (
    CONVERSATION,
    CREATED_AT,
    EMAIL,
    OTHER,
    OTHER_CONVERSATION,
    OWNER,
    RUN,
    SECOND,
    STEP as PROPOSAL_STEP,
    TURN,
    WORKFLOW_SETTINGS,
    ZONE,
    RunStore,
    _log_recorder,
    accept as accept_proposal_route,
    deny as deny_proposal_route,
    draft as draft_proposal_route,
    login,
    seed_run as seed_proposal_run,
    status as proposal_status_route,
)
from test_orchestration_workflow_runs_off_golden import DOCUMENT_ID
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least


SECRET = "SECRET-DEPLOYMENT-7A"
SEEDS = {"model": {"model_deployment": SECRET}}
STEP = "handoff"
FIELD = "workflow_handoff_decisions"
HANDOFF_SETTINGS = {
    "enable_chat_orchestration_workflow_runs": True,
    "enable_chat_workflow_results": True,
    "enable_chat_orchestration_workflow_handoff": True,
    "chat_orchestration_max_workflow_handoffs_per_day": 5,
}
REQUEST_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:simplechat:workflow-handoff-runs")
EXCEPTION_TEXT = "Private failure detail 7a"


# ---------------------------------------------------------------------------
# Storage doubles
# ---------------------------------------------------------------------------

class Items(AtomicMemoryContainer):
    """A memory container that records point reads and can fail the next one."""

    def __init__(self, partition_field):
        super().__init__(partition_field)
        self.reads = []
        self.read_error = None

    def read_item(self, item, partition_key):
        self.reads.append((partition_key, item))
        error, self.read_error = self.read_error, None
        if error is not None:
            raise error
        return super().read_item(item, partition_key)

    def delete_item(self, item, partition_key, **kwargs):
        # The runtime deletes an unbound run record without an etag.
        with self._lock:
            super().read_item(item, partition_key)
            del self.items[(partition_key, item)]

    def get(self, partition, item_id):
        record = self.items.get((partition, item_id))
        return deepcopy(record) if record is not None else None

    def patch(self, partition, item_id, **changes):
        record = {key: value for key, value in self.items[(partition, item_id)].items() if not key.startswith("_")}
        self.upsert_item({**record, **changes})

    def records(self, partition):
        with self._lock:
            return [deepcopy(record) for (key, _), record in self.items.items() if key == partition]


class HandoffWorkflowStore(Items):
    """Personal workflows, answering the two count queries clause by clause.

    Phase 4's cap count and the rolling hand-off count are both ``COUNT(1)`` queries. Each clause
    the production query carries is applied here, so dropping or adding a clause changes the count.
    """

    def query_items(self, query=None, parameters=None, partition_key=None, **kwargs):
        if query and "COUNT(1)" in query:
            if self.fail_queries:
                raise AzureError("Private test query failure")
            values = {entry["name"]: entry["value"] for entry in parameters or []}
            with self._lock:
                records = [
                    deepcopy(record) for (partition, _), record in self.items.items()
                    if partition == partition_key and record.get("user_id") == values.get("@user_id")
                ]
            if "c.origin.source = @source" in query:
                records = [r for r in records if (r.get("origin") or {}).get("source") == values.get("@source")]
            if "c.deleting != true" in query:
                records = [r for r in records if r.get("deleting") is not True]
            if "(NOT IS_DEFINED(c.origin.one_time) OR c.origin.one_time != true)" in query:
                records = [r for r in records if (r.get("origin") or {}).get("one_time") is not True]
            if "c.origin.one_time = true" in query:
                records = [r for r in records if (r.get("origin") or {}).get("one_time") is True]
            if "c.created_at >= @since" in query:
                records = [r for r in records if str(r.get("created_at") or "") >= values["@since"]]
            return [len(records)]
        return super().query_items(query, parameters=parameters, partition_key=partition_key, **kwargs)


# ---------------------------------------------------------------------------
# The app, over memory containers and the real durable queue
# ---------------------------------------------------------------------------

@pytest.fixture
def hw(modules, monkeypatch):
    proposals = importlib.import_module("functions_orchestration_workflow_proposals")
    personal = importlib.import_module("functions_personal_workflows")
    drafts = importlib.import_module("functions_workflow_drafts")
    ow = importlib.import_module("functions_orchestration_workflows")
    ho = importlib.import_module("functions_orchestration_workflow_handoffs")
    decisions = importlib.import_module("functions_orchestration_workflow_handoff_decisions")
    wr = importlib.import_module("functions_orchestration_workflow_runs")
    runtime = importlib.import_module("functions_workflow_runtime")
    runtime_store = importlib.import_module("functions_workflow_runtime_store")
    result_store = importlib.import_module("functions_workflow_result_store")
    settings_module = importlib.import_module("functions_settings")

    handoff_settings, planning = _context("on")
    settings = {
        **deepcopy(settings_module.get_settings() or {}),
        **deepcopy(handoff_settings),
        **deepcopy(WORKFLOW_SETTINGS),
        **deepcopy(HANDOFF_SETTINGS),
    }
    conversations = AtomicMemoryContainer("id")
    runs = RunStore()
    steps = AtomicMemoryContainer("run_id")
    workflows = HandoffWorkflowStore("user_id")
    wf_runs = Items("user_id")
    controls = Items("run_id")
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
    monkeypatch.setattr(modules.config, "cosmos_personal_workflow_runs_container", wf_runs, raising=False)

    clock = SimpleNamespace(now=CREATED_AT + timedelta(hours=1))
    record = SimpleNamespace(logs=[], created=[], access_checks=[], queued=[])
    state = SimpleNamespace(
        settings=settings, snapshots={}, deleted_results=[], fail_queue=None, documents=True, scopes=True,
    )

    def access_status(user_id):
        # The real check reads user settings, whose profile-image refresh would reach Microsoft Entra.
        record.access_checks.append(user_id)
        return True, None

    def current_settings():
        return deepcopy(state.settings)

    monkeypatch.setattr(modules.auth, "check_user_access_status", access_status)
    monkeypatch.setattr(modules.route, "get_settings", current_settings)
    # Allow User Workflows and the workflow role are checked by decorators that read this module.
    monkeypatch.setattr(settings_module, "get_settings", current_settings)
    monkeypatch.setattr(modules.route, "log_workflow_creation", lambda **kwargs: record.created.append(kwargs))
    monkeypatch.setattr(proposals, "_now", lambda: clock.now)
    monkeypatch.setattr(proposals, "_m365_connected", lambda user_id, tenant_id: True)
    monkeypatch.setattr(decisions, "_now", lambda: clock.now)
    for module in (proposals, modules.route, drafts, ho, decisions, wr, personal, runtime):
        monkeypatch.setattr(module, "log_event", _log_recorder(record.logs, module.__name__))

    # The draft service's document, user-settings and scope seams, so no store or directory is read.
    def resolve_document(**kwargs):
        if state.documents and kwargs.get("document_id") == DOCUMENT_ID and kwargs.get("doc_scope") == "personal":
            return {"scope": "personal", "document": {"id": DOCUMENT_ID, "user_id": OWNER}, "group_id": None}
        return None

    def user_settings_reader(user_id, *args, **kwargs):
        return {"id": user_id, "settings": {}}

    def authorize_scope(scope, actor_user_id=None):
        return state.scopes

    seams = {
        "resolve_document": resolve_document, "user_settings_reader": user_settings_reader,
        "authorize_scope": authorize_scope,
    }
    for name in (
        "dry_run_handoff_workflow", "create_personal_handoff_workflow",
        "create_personal_handoff_workflow_from_payload",
    ):
        seamed = functools.partial(getattr(drafts, name), **seams)
        monkeypatch.setattr(drafts, name, seamed)
        monkeypatch.setattr(decisions, name, seamed)
    monkeypatch.setattr(decisions, "dry_run_personal_workflow", functools.partial(
        drafts.dry_run_personal_workflow,
        resolve_document=resolve_document, user_settings_reader=user_settings_reader,
    ))

    # The real durable queue, over memory containers for the requester's workflows and runs.
    def services(workflow):
        _require(not workflow.get("group_id"), "A hand-off workflow is personal.")
        user_id, workflow_id = workflow["user_id"], workflow["id"]

        def load_workflow():
            try:
                return workflows.read_item(item=workflow_id, partition_key=user_id)
            except exceptions.CosmosResourceNotFoundError:
                return None

        return {
            "definitions": workflows, "runs": wf_runs, "partition": user_id,
            "load_workflow": load_workflow, "settings": current_settings,
        }

    def save_result(workflow, run_id, task_id, result, *, settings=None):
        state.snapshots[(run_id, task_id)] = deepcopy(result)
        return {"kind": "test-result", "run_id": run_id, "task_id": task_id}

    def load_result(workflow, run_id, task_id, reference):
        return deepcopy(state.snapshots[(reference["run_id"], reference["task_id"])])

    def save_runtime_result(workflow, run_id, result, *, settings=None):
        # The definition snapshot and the completion share this writer, so each save gets its own key.
        return save_result(workflow, run_id, f"runtime:{len(state.snapshots)}", result)

    def load_runtime_result(workflow, run_id, control, reference):
        return load_result(workflow, run_id, None, reference)

    real_queue = runtime.queue_durable_workflow_run

    def queue(workflow, **options):
        record.queued.append(deepcopy(options))
        error, state.fail_queue = state.fail_queue, None
        if error is not None:
            raise error
        return real_queue(workflow, **options)

    monkeypatch.setattr(runtime, "_services", services)
    monkeypatch.setattr(
        runtime, "workflow_runtime_store",
        lambda workflow, run_id: runtime_store.WorkflowRuntimeStore(controls, workflow, run_id, clock=lambda: clock.now),
    )
    monkeypatch.setattr(runtime, "save_workflow_task_result", save_result)
    monkeypatch.setattr(runtime, "load_workflow_task_result", load_result)
    monkeypatch.setattr(runtime, "save_workflow_runtime_result", save_runtime_result)
    monkeypatch.setattr(runtime, "load_workflow_runtime_result", load_runtime_result, raising=False)
    monkeypatch.setattr(result_store, "save_workflow_runtime_result", save_runtime_result)
    monkeypatch.setattr(result_store, "load_workflow_runtime_result", load_runtime_result)
    monkeypatch.setattr(result_store, "load_workflow_task_result", load_result)
    monkeypatch.setattr(runtime, "delete_workflow_run_results",
                        lambda workflow, run_id: state.deleted_results.append(run_id))
    monkeypatch.setattr(runtime, "queue_durable_workflow_run", queue)

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="workflow-handoff-routes")
    blueprint = Blueprint("backend_orchestration", __name__)
    blueprint.before_request(modules.auth.user_required_blueprint())
    modules.route.register_route_backend_orchestration(blueprint)
    app.register_blueprint(blueprint)
    conversations.create_item({"id": CONVERSATION, "user_id": OWNER, "title": "Private"})
    conversations.create_item({"id": OTHER_CONVERSATION, "user_id": OWNER, "title": "Another"})
    handoff_id = ho.workflow_handoff_id(RUN, STEP)
    return SimpleNamespace(
        modules=modules, proposals=proposals, personal=personal, drafts=drafts, ow=ow, ho=ho, D=decisions,
        wr=wr, runtime=runtime, app=app, client=Client(app, Response), conversations=conversations, runs=runs,
        steps=steps, workflows=workflows, wf_runs=wf_runs, controls=controls, settings=settings, state=state,
        planning=planning, clock=clock, record=record, handoff_id=handoff_id,
        workflow_id=drafts.orchestration_workflow_id(OWNER, handoff_id),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def expected_request_id(handoff_id):
    return str(uuid.uuid5(REQUEST_NAMESPACE, f"{OWNER}:{handoff_id}"))


def expected_run_id(workflow_id, handoff_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow:{OWNER}:{workflow_id}:{expected_request_id(handoff_id)}"))


def documents_loop(hw):
    return {"source": "documents", "documents": _handles(hw.planning)["documents"]}


def query_loop(hw):
    return {
        "source": "workspace_query", "scopes": _handles(hw.planning)["scopes"], "selection": "all_matches",
        "content": "indemnity",
    }


def build_sidecar(hw, run_id, *, loop=None, tasks=None, created_at=CREATED_AT):
    """The hand-off sidecar the executor stores, built by the production step builder and dry run."""
    step = _handoff_step(documents_loop(hw) if loop is None else loop, tasks)
    context = SimpleNamespace(
        workflow_planning=deepcopy(hw.planning), time_zone=ZONE, user_email=EMAIL, user_roles=["User"],
        seeds=deepcopy(SEEDS), active_group_ids=[],
    )
    producer = SimpleNamespace(run_id=run_id, step_id=STEP, conversation_id=CONVERSATION)
    sidecar, card = hw.ho.build_workflow_handoff(
        step, context, settings=deepcopy(hw.settings), user_id=OWNER, producer=producer, created_at=created_at,
    )
    return step, sidecar, card


def seed_handoff_run(hw, run_id=RUN, *, loop=None, tasks=None, turn_id=TURN, user_id=OWNER, created_at=CREATED_AT,
                     sidecar_changes=None, ready=True, **fields):
    step, sidecar, _card = build_sidecar(hw, run_id, loop=loop, tasks=tasks, created_at=created_at)
    if ready:
        _require(sidecar["status"] == "ready", f"The hand-off must be ready: {sidecar['reason']!r} "
                                               f"{sidecar['error_codes']!r}")
    sidecar.update(deepcopy(sidecar_changes or {}))
    record = {
        "id": run_id, "run_id": run_id, "conversation_id": CONVERSATION, "user_id": user_id,
        "turn_id": turn_id, "status": "completed",
        "plan": {"planner_contract_version": 2, "turn_id": turn_id, "steps": [{**step, "enabled": True}]},
        "execution_steps": [{
            "step_id": STEP, "capability_id": "workflow_handoff", "status": "completed",
            "workflow_handoff": sidecar,
        }],
    }
    record.update(deepcopy(fields))
    hw.runs.create_item(record)
    return sidecar


def _url(run_id, handoff_id=None, action=None):
    path = f"/api/v2/orchestration/runs/{run_id}/workflow-handoffs"
    if handoff_id is not None:
        path += f"/{handoff_id}"
    if action:
        path += f"/{action}"
    return path


def status(hw, run_id=RUN, conversation_id=CONVERSATION):
    return hw.client.get(_url(run_id), query_string={"conversation_id": conversation_id})


def accept(hw, handoff_id=None, *, run_id=RUN, conversation_id=CONVERSATION, mode="as_proposed", **fields):
    payload = {"conversation_id": conversation_id, **fields}
    if mode is not None:
        payload["mode"] = mode
    return hw.client.post(_url(run_id, handoff_id or hw.handoff_id, "accept"), json=payload)


def deny(hw, handoff_id=None, *, run_id=RUN, conversation_id=CONVERSATION, **fields):
    return hw.client.post(
        _url(run_id, handoff_id or hw.handoff_id, "deny"), json={"conversation_id": conversation_id, **fields},
    )


def draft(hw, handoff_id=None, *, run_id=RUN, conversation_id=CONVERSATION):
    return hw.client.get(
        _url(run_id, handoff_id or hw.handoff_id, "draft"), query_string={"conversation_id": conversation_id},
    )


def body(response):
    return response.get_json(silent=True) or {}


def code(response):
    return body(response).get("code")


def expect(response, status_code, error_code=None):
    """The response's JSON body, after checking its status and, for a refusal, its closed code."""
    _same(response.status_code, status_code, f"the status of {response.get_data(as_text=True)[:400]!r}")
    if error_code is not None:
        _same(code(response), error_code, "the error code")
    return body(response)


def run(hw, run_id=RUN):
    return hw.runs.items[(CONVERSATION, run_id)]


def decision(hw, run_id=RUN, handoff_id=None):
    return (run(hw, run_id).get(FIELD) or {}).get(handoff_id or hw.handoff_id)


def stored_workflow(hw, workflow_id=None):
    return hw.workflows.get(OWNER, workflow_id or hw.workflow_id)


def stored_runs(hw):
    return hw.wf_runs.records(OWNER)


def writes(hw):
    return (hw.runs.sequence, hw.steps.sequence, hw.workflows.sequence, hw.wf_runs.sequence, hw.controls.sequence)


def private_values(hw):
    """What no response outside the editor draft, and no log, may carry."""
    values = {SECRET, DOCUMENT_ID, EXCEPTION_TEXT, "Private test"}
    for entries in (hw.planning["workflow_handoff"].get("handles") or {}).values():
        for entry in (entries or {}).values():
            for key in ("document_id", "scope_id", "id"):
                value = entry.get(key) if isinstance(entry, dict) else None
                if isinstance(value, str) and len(value) >= 8:
                    values.add(value)
    return values


def internal_ids(hw):
    return {hw.handoff_id, hw.workflow_id, expected_run_id(hw.workflow_id, hw.handoff_id), RUN, CONVERSATION}


def require_no_leak(hw, *responses):
    private = private_values(hw)
    for response in responses:
        text = response.get_data(as_text=True)
        for value in private:
            _require(value not in text, f"A response carries a private value {value[:12]!r}: {text[:300]!r}")
    for entry in hw.record.logs:
        text = entry["message"] + entry["extra"]
        for value in private | internal_ids(hw):
            _require(value not in text, f"A log from {entry['source']} carries {value[:12]!r}: {entry['message']!r}")


def status_rows(hw):
    """The requester's chat-started runs as 6b-1's status route lists them for this conversation."""
    from test_workflow_chat_delivery_status_route import services_for, status as delivery_status

    harness = services_for(stored_runs(hw), [stored_workflow(hw)])
    return delivery_status.workflow_run_status_payload(OWNER, [CONVERSATION], services=harness.services)["runs"]


def identity(user_id=OWNER, roles=("User",)):
    """The identity the route builds for a signed-in requester, for a direct decision call."""
    return {"user_id": user_id, "email": EMAIL, "roles": list(roles), "tenant_id": None}


def conversation_item(hw):
    return deepcopy(hw.conversations.items[(CONVERSATION, CONVERSATION)])


def refusal(hw, call):
    """The closed code ``call`` refused with. Raises when it was not refused."""
    try:
        call()
    except hw.D.HandoffError as exc:
        return exc.code
    raise AssertionError("The call was not refused.")


def direct(hw, action, *, user_id=OWNER, roles=("User",), body=None, run_id=RUN, handoff_id=None):
    """A decision called directly, as the route calls it once the conversation and run are authorized."""
    record = deepcopy(run(hw, run_id))
    who = identity(user_id, roles)
    settings = deepcopy(hw.settings)
    handoff_id = handoff_id or hw.handoff_id
    if action == "accept":
        payload = {"conversation_id": CONVERSATION, "mode": "as_proposed"} if body is None else body
        return lambda: hw.D.accept_handoff(
            record, conversation_item(hw), handoff_id, payload, identity=who, settings=settings,
            response_removed=lambda: False,
        )
    if action == "deny":
        payload = {"conversation_id": CONVERSATION} if body is None else body
        return lambda: hw.D.deny_handoff(
            record, conversation_item(hw), handoff_id, payload, identity=who, settings=settings,
        )
    if action == "draft":
        return lambda: hw.D.handoff_draft(
            record, conversation_item(hw), handoff_id, identity=who, settings=settings,
            response_removed=lambda: False,
        )
    return lambda: hw.D.handoff_status(
        record, conversation_item(hw), identity=who, settings=settings, response_removed=lambda: False,
    )


def _close_handoff(hw, case):
    conversation = hw.conversations.items[(CONVERSATION, CONVERSATION)]
    if case == "handoff_off":
        hw.settings["enable_chat_orchestration_workflow_handoff"] = False
    elif case == "runs_off":
        hw.settings["enable_chat_orchestration_workflow_runs"] = False
    elif case == "results_off":
        hw.settings["enable_chat_workflow_results"] = False
    elif case == "setting_off":
        hw.settings["enable_chat_orchestration_workflows"] = False
    elif case == "orchestration_off":
        hw.settings["enable_chat_orchestration"] = False
    elif case == "allowlist":
        hw.settings["chat_orchestration_enabled_capabilities"] = ["compose"]
    elif case == "shared":
        conversation["chat_type"] = "personal_multi_user"
    elif case == "converted":
        conversation["converted_to_collaboration_at"] = "2026-01-01T00:00:00+00:00"
    else:
        raise AssertionError(f"Unknown gate case {case!r}.")


def _reopen_handoff(hw, settings, conversation):
    hw.settings.clear()
    hw.settings.update(deepcopy(settings))
    hw.conversations.items[(CONVERSATION, CONVERSATION)] = deepcopy(conversation)


def capture_creates(hw, monkeypatch, *, fail_first=None):
    """Record the stored decision each create sees; optionally raise ``fail_first`` from the first."""
    seen = []
    seamed = hw.D.create_personal_handoff_workflow

    def create(*args, **kwargs):
        seen.append(deepcopy(decision(hw)))
        if fail_first is not None and len(seen) == 1:
            raise fail_first
        return seamed(*args, **kwargs)

    monkeypatch.setattr(hw.D, "create_personal_handoff_workflow", create)
    return seen


def without_times(record):
    return {key: value for key, value in (record or {}).items() if key not in ("created_at", "updated_at", "expires_at")}


# ---------------------------------------------------------------------------
# Accept and run
# ---------------------------------------------------------------------------

def test_version_includes_the_workflow_handoff_routes():
    assert_app_version_at_least("0.261.239")


def test_accept_creates_the_workflow_disabled_and_queues_exactly_one_durable_run(hw):
    sidecar = seed_handoff_run(hw)
    login(hw)

    response = accept(hw)

    payload = expect(response, 201)
    workflow = stored_workflow(hw)
    runs = stored_runs(hw)
    run_id = expected_run_id(hw.workflow_id, hw.handoff_id)
    _require(workflow is not None, "The one-time workflow was not created.")
    _same(workflow["id"], hw.workflow_id, "the workflow id")
    _same(workflow["is_enabled"], False, "the workflow is created disabled")
    _same(workflow["origin"].get("one_time"), True, "the one-time origin marker")
    _same(workflow["origin"].get("proposal_id"), hw.handoff_id, "the origin hand-off id")
    _same(workflow["definition_version"], 3, "the definition version")
    _same(workflow["durable_execution"], True, "durable execution")
    _same(workflow["active_run_id"], run_id, "the bound run")
    _same([entry["id"] for entry in runs], [run_id], "exactly one run, with the deterministic id")
    stored = runs[0]
    _same(stored["trigger_source"], "chat_orchestration", "the trigger source")
    invocation = stored["chat_invocation"]
    _same(invocation["conversation_id"], CONVERSATION, "the invocation's conversation")
    _same(invocation["orchestration_run_id"], RUN, "the invocation's run")
    _same(invocation["step_id"], STEP, "the invocation's step")
    _same(invocation["handoff_id"], hw.handoff_id, "the invocation's hand-off")
    _same(invocation["requested_by"], OWNER, "the requester")
    _same(stored["chat_delivery"]["model_selection"]["model"]["model_deployment"], SECRET,
          "the server-captured model selection")
    _same(stored["chat_delivery"]["time_zone"], sidecar["time_zone"], "the server-captured time zone")
    _same(len(hw.record.queued), 1, "queue calls")
    _same(hw.record.queued[0]["request_id"], expected_request_id(hw.handoff_id), "the deterministic request id")
    _same(hw.record.queued[0]["actor_user_id"], OWNER, "the actor")
    _same(payload["handoff_id"], hw.handoff_id, "the response hand-off")
    _same(payload["state"], "queued", "the response state")
    _same(payload["created"], True, "the response says it created the workflow")
    _same(payload["workflow"], {"id": hw.workflow_id, "name": workflow["name"], "is_enabled": False}, "the workflow")
    _same(payload["run"]["id"], run_id, "the response run")
    _same(decision(hw)["state"], "queued", "the stored decision")
    _same(len(hw.record.created), 1, "creation logs")
    _same([row["run_id"] for row in status_rows(hw)], [run_id], "6b-1's status route lists the run")
    require_no_leak(hw, response)


def test_the_decision_field_claim_window_and_request_ids_are_the_hand_offs_own(hw):
    runs_module = hw.modules.runs
    _same(FIELD, runs_module.WORKFLOW_HANDOFF_DECISIONS_FIELD, "the hand-off decision field")
    _require(FIELD != runs_module.WORKFLOW_PROPOSAL_DECISIONS_FIELD, "Hand-offs and proposals share a decision map.")
    _same(runs_module._DECISION_WRITE_ATTEMPTS, 8, "the decision write attempts")
    _same(hw.D.HANDOFF_CLAIM_SECONDS, 120, "the claim window")
    _same(hw.D.HANDOFF_DAILY_WINDOW, timedelta(hours=24), "the rolling daily window")
    _same(hw.D.WORKFLOW_HANDOFF_REQUEST_NAMESPACE, REQUEST_NAMESPACE, "the run request namespace")
    others = {
        hw.ow.WORKFLOW_PROPOSAL_NAMESPACE, hw.ho.WORKFLOW_HANDOFF_NAMESPACE, hw.wr.WORKFLOW_RUN_REQUEST_NAMESPACE,
    }
    _same(len(others), 3, "the other namespaces are distinct")
    _require(REQUEST_NAMESPACE not in others, "The hand-off run requests reuse another namespace.")
    owner_request = hw.D.workflow_handoff_request_id(OWNER, hw.handoff_id)
    other_request = hw.D.workflow_handoff_request_id(OTHER, hw.handoff_id)
    _same(owner_request, expected_request_id(hw.handoff_id), "the deterministic request id")
    _same(hw.D.workflow_handoff_request_id(OWNER, hw.handoff_id), owner_request, "the request id on a retry")
    _require(other_request != owner_request, "Two users' hand-offs share a run request id.")
    _same(hw.workflow_id, hw.drafts.orchestration_workflow_id(OWNER, hw.handoff_id), "the workflow id")


# ---------------------------------------------------------------------------
# Who may act on a hand-off
# ---------------------------------------------------------------------------

def test_every_handoff_route_needs_a_signed_in_user_with_the_user_role(hw):
    seed_handoff_run(hw)
    before = writes(hw)
    anonymous = [status(hw), accept(hw), deny(hw), draft(hw)]
    login(hw, roles=())
    no_role = [status(hw), accept(hw), deny(hw), draft(hw)]

    _same([response.status_code for response in anonymous], [401] * 4, "anonymous statuses")
    _same([response.status_code for response in no_role], [403] * 4, "statuses without the User role")
    _same(writes(hw), before, "writes")
    _same(hw.record.queued, [], "queue calls")
    _same(hw.record.access_checks, [], "access checks")
    login(hw)
    signed_in = status(hw)
    expect(signed_in, 200)
    _require(hw.record.access_checks, "The requester's access was not checked.")
    _same(set(hw.record.access_checks), {OWNER}, "the users whose access was checked")


def test_allow_user_workflows_and_the_workflow_role_guard_every_handoff_route(hw):
    seed_handoff_run(hw)
    login(hw)
    before = writes(hw)
    hw.settings["allow_user_workflows"] = False
    disabled = [status(hw), accept(hw), deny(hw), draft(hw)]
    hw.settings["allow_user_workflows"] = True
    hw.settings["require_member_of_workflow_user"] = True
    no_workflow_role = [status(hw), accept(hw), deny(hw), draft(hw)]

    for response in disabled:
        _same((response.status_code, body(response)), (400, {"error": "Allow User Workflows is disabled."}),
              "a route with Allow User Workflows off")
    for response in no_workflow_role:
        _same(
            (response.status_code, body(response)),
            (403, {"error": "Forbidden", "message": "Personal workflows require the WorkflowUser app role."}),
            "a route without the WorkflowUser role",
        )
    _same(writes(hw), before, "writes")
    _same(stored_workflow(hw), None, "the workflow")
    login(hw, roles=("User", "WorkflowUser"))
    accepted = accept(hw)
    expect(accepted, 201)
    _same(stored_workflow(hw)["is_enabled"], False, "the workflow is created disabled")


def test_only_the_requester_can_read_or_decide_a_handoff(hw):
    seed_handoff_run(hw)
    login(hw, user_id=OTHER)
    before = writes(hw)
    responses = [status(hw), accept(hw), deny(hw), draft(hw)]

    for response in responses:
        expect(response, 404, "run_not_found")
    # Past the route, the requester check itself refuses someone else, before any gate could
    # disclose that the conversation is not theirs.
    _same(refusal(hw, direct(hw, "accept", user_id=OTHER)), "handoff_not_found", "another user's accept")
    _same(refusal(hw, direct(hw, "deny", user_id=OTHER)), "handoff_not_found", "another user's deny")
    _same(refusal(hw, direct(hw, "draft", user_id=OTHER)), "handoff_not_found", "another user's draft")
    _same(refusal(hw, direct(hw, "status", user_id=OTHER)), "run_not_found", "another user's status")
    hw.settings["require_member_of_workflow_user"] = True
    role_refusal = refusal(hw, direct(hw, "accept"))
    _same(role_refusal, "workflow_role_required", "the requester without the WorkflowUser role")
    _same(writes(hw), before, "writes")
    _same(stored_workflow(hw), None, "the workflow")
    _same(decision(hw), None, "the decision")
    _same(hw.record.queued, [], "queue calls")
    require_no_leak(hw, *responses)


def test_a_run_or_conversation_the_requester_cannot_open_is_not_found(hw):
    seed_handoff_run(hw)
    seed_handoff_run(hw, SECOND, user_id=OTHER)
    login(hw)
    before = writes(hw)
    missing_conversation = status(hw, conversation_id="")
    responses = [
        status(hw, run_id="run_unknown"),
        status(hw, conversation_id=OTHER_CONVERSATION),
        status(hw, conversation_id="conversation-missing"),
        status(hw, run_id=SECOND),
        accept(hw, conversation_id=OTHER_CONVERSATION),
        deny(hw, conversation_id=OTHER_CONVERSATION),
        draft(hw, run_id=SECOND),
        accept(hw, run_id=SECOND),
    ]

    expect(missing_conversation, 400, "invalid_request")
    for response in responses:
        expect(response, 404, "run_not_found")
    hw.conversations.items[(CONVERSATION, CONVERSATION)]["orchestration_deleted"] = True
    deleted = status(hw)
    expect(deleted, 404)
    _same(writes(hw), before, "writes")
    _same(stored_workflow(hw), None, "the workflow")
    _same(decision(hw), None, "the decision")
    _same(hw.record.queued, [], "queue calls")


# ---------------------------------------------------------------------------
# The gates, and the kind refusal both ways
# ---------------------------------------------------------------------------

ROW_KEYS = {"handoff_id", "step_id", "state", "reason", "created_at", "expires_at", "actions", "summary", "disclosure"}
GATE_CASES = [
    ("handoff_off", "workflow_handoff_disabled", "workflow_handoff_disabled"),
    ("runs_off", "workflow_handoff_disabled", "workflow_handoff_disabled"),
    ("setting_off", "workflow_handoff_disabled", "workflow_handoff_disabled"),
    ("orchestration_off", "workflow_handoff_disabled", "workflow_handoff_disabled"),
    ("allowlist", "workflow_handoff_disabled", "workflow_handoff_disabled"),
    ("results_off", "workflow_results_disabled", "handoff_results_off"),
    ("shared", "workflow_shared_conversation", "workflow_shared_conversation"),
    ("converted", "workflow_shared_conversation", "workflow_shared_conversation"),
]


def only_handoff(hw, run_id=RUN):
    rows = expect(status(hw, run_id), 200)["handoffs"]
    _same(len(rows), 1, "the hand-offs the run shows")
    return rows[0]


def _require_closed(hw, reason, error):
    row = only_handoff(hw)
    _same((row["state"], row["reason"]), ("unavailable", reason), "a closed hand-off's state")
    _same(set(row), ROW_KEYS, "a closed hand-off discloses no workflow, run or delivery")
    _same(row["actions"], [], "a closed hand-off's actions")
    _same((row["summary"], row["disclosure"]), (None, None), "a closed hand-off's summary and disclosure")
    responses = [accept(hw), deny(hw), draft(hw)]
    for response in responses:
        expect(response, 403, error)
    require_no_leak(hw, *responses)


@pytest.mark.parametrize(("case", "reason", "error"), GATE_CASES)
def test_a_closed_gate_discloses_nothing_and_refuses_every_decision(hw, case, reason, error):
    seed_handoff_run(hw)
    login(hw)
    settings, conversation = deepcopy(hw.settings), conversation_item(hw)
    _close_handoff(hw, case)
    before = writes(hw)
    _require_closed(hw, reason, error)
    _same(writes(hw), before, "writes while the gate is closed")
    _same(stored_workflow(hw), None, "the workflow")
    _same(hw.record.queued, [], "queue calls")

    _reopen_handoff(hw, settings, conversation)
    expect(accept(hw), 201)
    _close_handoff(hw, case)
    _require_closed(hw, reason, error)
    _same(decision(hw)["state"], "queued", "the decision after the gate closed")
    _same(len(stored_runs(hw)), 1, "durable runs")
    _same(len(hw.record.created), 1, "creation logs")


def test_phase_4_refuses_a_handoff_and_a_handoff_route_refuses_a_proposal(hw):
    seed_handoff_run(hw)
    login(hw)
    before = writes(hw)
    proposal_routes = [
        accept_proposal_route(hw, hw.handoff_id, mode="paused"),
        deny_proposal_route(hw, hw.handoff_id),
        draft_proposal_route(hw, hw.handoff_id),
    ]
    for response in proposal_routes:
        expect(response, 409, "proposal_kind_mismatch")
    _same(expect(proposal_status_route(hw), 200)["proposals"], [], "the proposals a hand-off run shows")
    _same(writes(hw), before, "writes after Phase 4 refused a hand-off")

    seed_proposal_run(hw, SECOND)
    proposal_id = hw.ow.workflow_proposal_id(SECOND, PROPOSAL_STEP)
    before = writes(hw)
    handoff_routes = [
        accept(hw, proposal_id, run_id=SECOND),
        deny(hw, proposal_id, run_id=SECOND),
        draft(hw, proposal_id, run_id=SECOND),
    ]
    for response in handoff_routes:
        expect(response, 409, "handoff_kind_mismatch")
    _same(expect(status(hw, SECOND), 200)["handoffs"], [], "the hand-offs a proposal run shows")
    _same(writes(hw), before, "writes after a hand-off route refused a proposal")
    _same(hw.workflows.records(OWNER), [], "workflows")
    _same(run(hw).get(FIELD), None, "hand-off decisions")
    _same(run(hw, SECOND).get(FIELD), None, "hand-off decisions on the proposal run")
    _same(run(hw, SECOND).get("workflow_proposal_decisions"), None, "proposal decisions")
    _same(hw.record.queued, [], "queue calls")
    require_no_leak(hw, *proposal_routes, *handoff_routes)


# ---------------------------------------------------------------------------
# The delivery record, and the claim around the create
# ---------------------------------------------------------------------------

def test_the_handoff_records_chat_delivery_exactly_as_a_workflow_run_step_does(hw):
    _require(hw.D.chat_delivery_seed_for is hw.wr.chat_delivery_seed_for, "The hand-off builds its own seed.")
    settings = deepcopy(hw.settings)
    context = SimpleNamespace(
        user_roles=["User"], time_zone=ZONE, seeds=deepcopy(SEEDS), active_group_ids=[], run_id=RUN,
    )
    via_step = hw.wr._chat_delivery_seed(settings, context, {"time_zone": ZONE})
    shared = hw.wr.chat_delivery_seed_for(
        settings, user_roles=["User"], time_zone=ZONE,
        model_selection=hw.wr.normalize_model_selection(deepcopy(SEEDS), []), run_id=RUN,
    )
    _require(isinstance(shared, dict), "The shared helper built no delivery record.")
    _same(without_times(via_step), without_times(shared), "a workflow_run step's delivery record")

    sidecar = seed_handoff_run(hw)
    login(hw)
    expect(accept(hw), 201)
    stored = stored_runs(hw)[0]["chat_delivery"]
    expected = hw.wr.chat_delivery_seed_for(
        settings, user_roles=["User"], time_zone=sidecar["time_zone"],
        model_selection=deepcopy(sidecar["model_selection"]), run_id=RUN,
    )
    _same(without_times(stored), without_times(expected), "the hand-off run's delivery record")
    _same(stored["model_selection"], via_step["model_selection"], "the server-captured model selection")


def test_a_create_runs_under_a_claim_that_is_released_when_it_fails(hw, monkeypatch):
    seed_handoff_run(hw)
    login(hw)
    hw.state.documents = False
    lost = accept(hw)
    expect(lost, 403, "handoff_access_lost")
    _same(decision(hw), None, "the decision after a refused rebuild")
    _same(stored_workflow(hw), None, "the workflow after a refused rebuild")
    hw.state.documents = True

    seen = capture_creates(hw, monkeypatch, fail_first=RuntimeError(EXCEPTION_TEXT))
    failed = accept(hw)
    expect(failed, 503, "service_unavailable")
    _same(len(seen), 1, "creates")
    _same(seen[0]["state"], "creating", "the decision the create ran under")
    _require(seen[0]["claim_id"], "The claim has no id.")
    _same(seen[0]["mode"], "as_proposed", "the claim's mode")
    _same(decision(hw), None, "the decision after the create failed")
    _same(stored_workflow(hw), None, "the workflow after the create failed")
    _same(hw.record.queued, [], "queue calls after the create failed")
    require_no_leak(hw, lost, failed)

    retried = accept(hw)
    expect(retried, 201)
    _same(len(seen), 2, "creates")
    _require(seen[1]["claim_id"] != seen[0]["claim_id"], "A retry reused the released claim.")
    _same(decision(hw)["state"], "queued", "the decision after the retry")
    _same(len(stored_runs(hw)), 1, "durable runs")


def test_a_fresh_claim_is_busy_and_a_stale_one_gives_way(hw, monkeypatch):
    seed_handoff_run(hw)
    login(hw)
    run(hw)[FIELD] = {hw.handoff_id: {
        "state": "creating", "claim_id": "another-request", "claimed_at": hw.clock.now.isoformat(),
        "mode": "as_proposed", "edited": False, "previous": None,
    }}
    _same(only_handoff(hw)["state"], "creating", "a claimed hand-off's state")
    _same(only_handoff(hw)["actions"], [], "a claimed hand-off's actions")
    for response in (accept(hw), deny(hw)):
        expect(response, 409, "handoff_busy")
    expect(draft(hw), 409, "handoff_busy")
    _same(stored_workflow(hw), None, "the workflow")
    _same(decision(hw)["claim_id"], "another-request", "the other request's claim")

    hw.clock.now += timedelta(seconds=hw.D.HANDOFF_CLAIM_SECONDS)
    _same(only_handoff(hw)["state"], "pending", "a hand-off whose claim went stale")
    seen = capture_creates(hw, monkeypatch)
    expect(accept(hw), 201)
    _same(len(seen), 1, "creates")
    _require(seen[0]["claim_id"] != "another-request", "The accept created under a stale claim.")
    _same(decision(hw)["state"], "queued", "the decision")


def test_a_claim_that_keeps_losing_is_busy_and_creates_nothing(hw, monkeypatch):
    seed_handoff_run(hw)
    login(hw)
    seen = capture_creates(hw, monkeypatch)
    hw.runs.replace_attempts = 0
    hw.runs.lose_write = lambda record: True
    busy = accept(hw)
    hw.runs.lose_write = None

    expect(busy, 409, "handoff_busy")
    _same(hw.runs.replace_attempts, 8, "claim write attempts")
    _same(seen, [], "creates")
    _same(stored_workflow(hw), None, "the workflow")
    _same(decision(hw), None, "the decision")
    _same(hw.record.queued, [], "queue calls")


# ---------------------------------------------------------------------------
# Created but not queued: a retry finishes the same accept
# ---------------------------------------------------------------------------

def handoff_logs(hw, message):
    """The extras of every recorded log whose message carries ``message``."""
    return [json.loads(entry["extra"]) or {} for entry in hw.record.logs if message in entry["message"]]


def test_a_created_but_unqueued_handoff_retries_to_the_same_workflow_and_run(hw):
    seed_handoff_run(hw)
    login(hw)
    run_id = expected_run_id(hw.workflow_id, hw.handoff_id)
    hw.state.fail_queue = AzureError(EXCEPTION_TEXT)
    failed = accept(hw)

    payload = expect(failed, 503, "handoff_queue_failed")
    _same(payload.get("state"), "created", "the failed accept's state")
    workflow = stored_workflow(hw)
    _require(workflow is not None, "The workflow was not created before the queue failed.")
    _same(workflow["is_enabled"], False, "the workflow is created disabled")
    _same(decision(hw)["state"], "created", "the decision after the queue failed")
    _same(stored_runs(hw), [], "durable runs after the queue failed")
    _same(len(hw.record.created), 1, "creation logs")
    _same(len(hw.record.queued), 1, "queue calls")
    _same(
        [entry.get("code") for entry in handoff_logs(hw, "A workflow hand-off run was not queued.")],
        ["handoff_queue_failed"], "the queue failure log",
    )

    retried = accept(hw)
    retry = expect(retried, 200)
    _same(retry["created"], False, "the retry created nothing")
    _same(retry["state"], "queued", "the retry's state")
    _same(retry["run"]["id"], run_id, "the retry's run")
    _same(retry["workflow"], {"id": hw.workflow_id, "name": workflow["name"], "is_enabled": False}, "the workflow")
    _same([entry["id"] for entry in hw.workflows.records(OWNER)], [hw.workflow_id], "workflows")
    _same([entry["id"] for entry in stored_runs(hw)], [run_id], "durable runs")
    _same(
        [options["request_id"] for options in hw.record.queued], [expected_request_id(hw.handoff_id)] * 2,
        "every queue call uses the same request",
    )
    _same(stored_workflow(hw)["active_run_id"], run_id, "the bound run")
    _same(decision(hw)["state"], "queued", "the decision after the retry")
    _same(decision(hw)["run_id"], run_id, "the decision's run")
    _same(len(hw.record.created), 1, "creation logs after the retry")

    third = accept(hw)
    _same(expect(third, 200)["run"]["id"], run_id, "a third accept's run")
    _same(len(hw.record.queued), 2, "queue calls after a third accept")
    _same(len(stored_runs(hw)), 1, "durable runs after a third accept")
    require_no_leak(hw, failed, retried, third)


QUEUE_FAILURES = [
    ("conflict", 409, "handoff_run_conflict", "workflow_already_running"),
    ("unknown_conflict", 409, "handoff_run_conflict", "workflow_run_not_started"),
    ("runtime_unavailable", 503, "handoff_queue_failed", None),
    ("permission", 403, "handoff_access_lost", None),
    ("value", 409, "handoff_unavailable", None),
    ("lookup", 409, "handoff_unavailable", None),
    ("runtime", 503, "handoff_queue_failed", None),
]


def queue_failure(case):
    """The exception a queue raises, built from the live runtime store, whose classes the accept catches."""
    store = importlib.import_module("functions_workflow_runtime_store")
    return {
        "conflict": lambda: store.WorkflowRuntimeConflict("workflow_already_running", EXCEPTION_TEXT),
        "unknown_conflict": lambda: store.WorkflowRuntimeConflict("brand_new_code", EXCEPTION_TEXT),
        "runtime_unavailable": lambda: store.RuntimeUnavailable("runtime_unavailable", EXCEPTION_TEXT),
        "permission": lambda: PermissionError(EXCEPTION_TEXT),
        "value": lambda: ValueError(EXCEPTION_TEXT),
        "lookup": lambda: LookupError(EXCEPTION_TEXT),
        "runtime": lambda: RuntimeError(EXCEPTION_TEXT),
    }[case]()


@pytest.mark.parametrize(("case", "status_code", "error_code", "reason"), QUEUE_FAILURES)
def test_a_queue_failure_is_a_closed_code_and_a_retry_queues_the_same_run(hw, case, status_code, error_code,
                                                                          reason):
    seed_handoff_run(hw)
    login(hw)
    hw.state.fail_queue = queue_failure(case)
    failed = accept(hw)

    payload = expect(failed, status_code, error_code)
    _same(payload.get("state"), "created", "the failed accept's state")
    _same(payload.get("reason"), reason, "the failed accept's reason")
    _same(payload["error"], hw.D.ERROR_MESSAGES[error_code], "the fixed message")
    _same(stored_workflow(hw)["is_enabled"], False, "the workflow is created disabled")
    _same(stored_runs(hw), [], "durable runs after the queue failed")
    _same(decision(hw)["state"], "created", "the decision after the queue failed")
    _same(len(hw.record.created), 1, "creation logs")

    retried = accept(hw)
    _same(expect(retried, 200)["run"]["id"], expected_run_id(hw.workflow_id, hw.handoff_id), "the retry's run")
    _same(len(stored_runs(hw)), 1, "durable runs after the retry")
    _same(len(hw.record.queued), 2, "queue calls")
    _same(len(hw.record.created), 1, "creation logs after the retry")
    require_no_leak(hw, failed, retried)


def test_an_accept_whose_decisions_were_not_recorded_still_settles_on_one_run(hw):
    seed_handoff_run(hw)
    login(hw)
    run_id = expected_run_id(hw.workflow_id, hw.handoff_id)

    def settled(record):
        return ((record.get(FIELD) or {}).get(hw.handoff_id) or {}).get("state") in ("created", "queued")

    hw.runs.lose_write = settled
    accepted = accept(hw)

    expect(accepted, 201)
    _same(decision(hw)["state"], "creating", "the decision when neither confirmation was recorded")
    _same(
        [entry.get("decision_state") for entry in handoff_logs(hw, "A workflow hand-off decision was not recorded.")],
        ["created", "queued"], "the unrecorded decisions",
    )
    _same([entry["id"] for entry in stored_runs(hw)], [run_id], "durable runs")
    for _ in range(2):
        row = only_handoff(hw)
        _same((row["state"], row["actions"]), ("created", ["accept"]), "the hand-off once its workflow exists")
        _same(row["workflow"]["id"], hw.workflow_id, "the hand-off's workflow")
        _require("run" not in row, "An unrecorded run was shown.")
        hw.clock.now += timedelta(seconds=hw.D.HANDOFF_CLAIM_SECONDS)

    hw.runs.lose_write = None
    settled_accept = accept(hw)
    payload = expect(settled_accept, 200)
    _same((payload["created"], payload["run"]["id"], payload["chat_delivery"]), (False, run_id, True),
          "the accept that settled the hand-off")
    _same(len(hw.record.queued), 1, "queue calls")
    _same(len(stored_runs(hw)), 1, "durable runs")
    _same(
        {key: decision(hw).get(key) for key in ("state", "workflow_id", "run_id", "chat_delivery")},
        {"state": "queued", "workflow_id": hw.workflow_id, "run_id": run_id, "chat_delivery": True},
        "the settled decision",
    )
    row = only_handoff(hw)
    _same((row["state"], row["actions"], row["run"]["id"], row["chat_delivery"]), ("queued", [], run_id, True),
          "the settled hand-off")
    require_no_leak(hw, accepted, settled_accept)


# ---------------------------------------------------------------------------
# Declining
# ---------------------------------------------------------------------------

def test_a_declined_handoff_stays_declined(hw):
    seed_handoff_run(hw)
    login(hw)
    declined = deny(hw)

    _same(expect(declined, 200), {"handoff_id": hw.handoff_id, "state": "denied"}, "the deny response")
    _same(decision(hw)["state"], "denied", "the decision")
    _require(decision(hw).get("denied_at"), "The decline has no time.")
    before = writes(hw)
    again = deny(hw)
    _same(expect(again, 200), {"handoff_id": hw.handoff_id, "state": "denied"}, "a second deny")
    refused = [accept(hw), draft(hw)]
    for response in refused:
        expect(response, 409, "handoff_denied")
    row = only_handoff(hw)
    _same((row["state"], row["actions"]), ("denied", []), "a declined hand-off")
    _same(writes(hw), before, "writes after the hand-off was declined")
    _same(stored_workflow(hw), None, "the workflow")
    _same(hw.record.queued, [], "queue calls")
    _same(len(handoff_logs(hw, "A workflow hand-off was declined.")), 1, "decline logs")
    require_no_leak(hw, declined, again, *refused)


def test_an_accepted_handoff_cannot_be_declined(hw):
    seed_handoff_run(hw)
    login(hw)
    expect(accept(hw), 201)
    before = writes(hw)
    refused = deny(hw)

    payload = expect(refused, 409, "handoff_accepted")
    _same(payload.get("state"), "created", "the refusal's state")
    _same(writes(hw), before, "writes")
    _same(decision(hw)["state"], "queued", "the decision")
    _same(stored_workflow(hw)["is_enabled"], False, "the workflow")
    require_no_leak(hw, refused)


# ---------------------------------------------------------------------------
# Editing before accepting
# ---------------------------------------------------------------------------

DRAFT_SERVER_ONLY = (
    "origin", "one_time", "conversation_id", "model_selection", "id", "user_id", "url_access_authorized",
    "created_by", "modified_by",
)


def handoff_draft(hw):
    """The pending hand-off's editor draft, after checking it wrote nothing and carries no server field.

    The draft names the loop's documents for the editor, so it is not held to ``require_no_leak``.
    """
    before = writes(hw)
    response = draft(hw)

    payload = expect(response, 200)
    _same(writes(hw), before, "writes while reading the draft")
    _same(set(payload), {"handoff_id", "workflow", "url_access_note"}, "the draft's keys")
    _same(payload["handoff_id"], hw.handoff_id, "the draft's hand-off")
    workflow = payload["workflow"]
    for key in DRAFT_SERVER_ONLY:
        _require(key not in workflow, f"The draft carries the server field {key!r}.")
    _same((workflow.get("is_enabled"), workflow.get("durable_execution")), (False, True), "the draft's run settings")
    text = response.get_data(as_text=True)
    for value in (SECRET, EXCEPTION_TEXT, '"handles"'):
        _require(value not in text, f"The draft carries {value!r}.")
    return workflow


@pytest.mark.parametrize("changed", [False, True])
def test_an_edited_handoff_is_saved_through_the_same_accept_with_the_same_checks(hw, changed):
    seed_handoff_run(hw)
    login(hw)
    workflow = handoff_draft(hw)
    # Server-owned fields a client sends are ignored: the server sets the origin, the state and the id.
    workflow.update({
        "origin": {"source": "manual", "one_time": False, "proposal_id": "forged"},
        "one_time": False, "conversation_id": CONVERSATION, "is_enabled": True,
    })
    if changed:
        workflow["name"] = "Contract review, renamed"
    accepted = accept(hw, mode="edited", workflow=workflow)

    payload = expect(accepted, 201)
    stored = stored_workflow(hw)
    _require(stored is not None, "The edited workflow was not created.")
    origin = stored["origin"]
    _same(
        (origin.get("source"), origin.get("one_time"), origin.get("proposal_id"), origin.get("edited")),
        ("orchestration", True, hw.handoff_id, changed), "the stored origin",
    )
    _same((stored["id"], stored["is_enabled"], stored["name"]), (hw.workflow_id, False, workflow["name"]),
          "the stored workflow")
    _same(stored.get("conversation_id"), "", "the workflow's conversation")
    _same(len(hw.conversations.items), 2, "conversations: an accept creates none")
    _same((stored.get("created_by"), stored.get("modified_by")), (OWNER, OWNER), "who created the workflow")
    _same((payload["state"], payload["created"]), ("queued", True), "the response")
    _same(decision(hw)["state"], "queued", "the decision")
    _same(len(stored_runs(hw)), 1, "durable runs")
    _same(stored_runs(hw)[0]["chat_invocation"]["handoff_id"], hw.handoff_id, "the run's hand-off")
    _same(len(hw.record.created), 1, "creation logs")
    _same(
        [entry.get("edited") for entry in handoff_logs(hw, "A workflow hand-off created its workflow.")], [changed],
        "the creation log's edited flag",
    )
    _same(handoff_logs(hw, "A workflow hand-off edit could not be compared."), [], "comparison failures")
    require_no_leak(hw, accepted)


def test_an_invalid_edit_is_refused_and_releases_its_claim(hw):
    seed_handoff_run(hw)
    login(hw)
    workflow = handoff_draft(hw)

    url_access = accept(hw, mode="edited", workflow={**workflow, "url_access_enabled": True})
    payload = expect(url_access, 400, "handoff_edit_invalid")
    _same((payload["errors"][0]["code"], payload["errors"][0]["path"]), ("unsupported_field", "/url_access_enabled"),
          "the URL Access refusal")
    another = accept(hw, mode="edited", workflow={**workflow, "id": "workflow-another"})
    expect(another, 409, "handoff_unavailable")
    for label in ("URL Access", "another workflow id"):
        _same(decision(hw), None, f"the decision after the {label} refusal")
    _same(stored_workflow(hw), None, "the workflow")
    _same(hw.workflows.records(OWNER), [], "workflows")
    _same(hw.record.queued, [], "queue calls")

    before = writes(hw)
    malformed = [
        accept(hw, mode="edited"),
        accept(hw, workflow=workflow),
        accept(hw, mode="edited", workflow={}),
        accept(hw, mode="other"),
        accept(hw, mode=None),
        accept(hw, extra=1),
        deny(hw, extra=1),
    ]
    for response in malformed:
        expect(response, 400, "invalid_request")
    _same(writes(hw), before, "writes after malformed requests")
    _same(decision(hw), None, "the decision after malformed requests")
    require_no_leak(hw, url_access, another, *malformed)

    expect(accept(hw, mode="edited", workflow=workflow), 201)
    _same(stored_workflow(hw)["origin"].get("edited"), False, "an unchanged edit after the refusals")


# ---------------------------------------------------------------------------
# The rolling daily limit, and Phase 4's workflow cap
# ---------------------------------------------------------------------------

def seed_workflow(hw, workflow_id, *, hours_ago=1, one_time=True, source="orchestration", user_id=OWNER, **fields):
    """A stored workflow, created ``hours_ago`` before the test clock."""
    origin = {"source": source, "proposal_id": str(uuid.uuid4())}
    if one_time:
        origin["one_time"] = True
    hw.workflows.create_item({
        "id": workflow_id, "user_id": user_id, "name": f"Workflow {workflow_id}", "origin": origin,
        "created_at": (hw.clock.now - timedelta(hours=hours_ago)).isoformat(), **fields,
    })


def daily_count(hw):
    since = (hw.clock.now - hw.D.HANDOFF_DAILY_WINDOW).isoformat()
    return hw.personal.count_personal_handoff_workflows_since(OWNER, since)


def phase_4_count(hw):
    return hw.personal.count_personal_orchestration_workflows(OWNER, "orchestration")


def test_the_daily_limit_counts_recent_handoffs_including_ones_being_deleted(hw):
    seed_handoff_run(hw)
    login(hw)
    for index in range(4):
        seed_workflow(hw, f"handoff-recent-{index}")
    seed_workflow(hw, "handoff-deleting", deleting=True, status="deleting")
    _same(daily_count(hw), 5, "the hand-offs created in the last day")
    before = writes(hw)
    refused = accept(hw)

    payload = expect(refused, 429, "handoff_daily_limit")
    _same(payload["error"], hw.D.ERROR_MESSAGES["handoff_daily_limit"], "the fixed message")
    _same(writes(hw), before, "writes at the daily limit")
    _same(decision(hw), None, "the decision at the daily limit")
    _same(stored_workflow(hw), None, "the workflow at the daily limit")
    _same(hw.record.queued, [], "queue calls at the daily limit")
    # The limit is checked when the requester accepts, so the card still offers the hand-off.
    row = only_handoff(hw)
    _same((row["state"], row["actions"]), ("pending", ["accept", "edit", "deny"]), "the hand-off at the limit")
    require_no_leak(hw, refused)


def test_the_daily_limit_skips_older_and_other_workflows_and_holds_after_an_accept(hw):
    seed_handoff_run(hw)
    seed_handoff_run(hw, SECOND)
    login(hw)
    for index in range(4):
        seed_workflow(hw, f"handoff-recent-{index}")
    seed_workflow(hw, "handoff-old", hours_ago=25)
    seed_workflow(hw, "proposal-recent", one_time=False)
    seed_workflow(hw, "manual-recent", one_time=False, source="manual")
    seed_workflow(hw, "handoff-someone-else", user_id=OTHER)
    _same(daily_count(hw), 4, "the hand-offs created in the last day")

    expect(accept(hw), 201)
    _same(daily_count(hw), 5, "the hand-offs created in the last day after an accept")
    second_id = hw.ho.workflow_handoff_id(SECOND, STEP)
    second_workflow_id = hw.drafts.orchestration_workflow_id(OWNER, second_id)
    before = writes(hw)
    refused = accept(hw, second_id, run_id=SECOND)

    expect(refused, 429, "handoff_daily_limit")
    _same(writes(hw), before, "writes at the daily limit")
    _same(decision(hw, SECOND, second_id), None, "the second hand-off's decision")
    _same(stored_workflow(hw, second_workflow_id), None, "the second hand-off's workflow")
    _same(len(hw.record.queued), 1, "queue calls")
    require_no_leak(hw, refused)

    hw.settings["chat_orchestration_max_workflow_handoffs_per_day"] = 6
    expect(accept(hw, second_id, run_id=SECOND), 201)
    _same(stored_workflow(hw, second_workflow_id)["is_enabled"], False, "the second hand-off's workflow")
    _same(len(stored_runs(hw)), 2, "durable runs once the limit was raised")


def test_a_daily_count_that_cannot_be_read_fails_closed(hw):
    seed_handoff_run(hw)
    login(hw)
    hw.workflows.fail_queries = True
    before = writes(hw)
    failed = accept(hw)

    expect(failed, 503, "service_unavailable")
    _same(writes(hw), before, "writes when the daily count failed")
    _same(decision(hw), None, "the decision when the daily count failed")
    _same(stored_workflow(hw), None, "the workflow when the daily count failed")
    _same(hw.record.queued, [], "queue calls when the daily count failed")
    _same(
        [entry.get("error_type") for entry in handoff_logs(hw, "The workflow hand-off daily count could not be read.")],
        ["AzureError"], "the daily count failure log",
    )
    _same(len(handoff_logs(hw, "Error counting hand-off workflows.")), 1, "the store's count failure log")
    require_no_leak(hw, failed)

    hw.workflows.fail_queries = False
    expect(accept(hw), 201)
    _same(len(stored_runs(hw)), 1, "durable runs once the count could be read")


def test_a_handoff_does_not_count_toward_phase_4s_workflow_cap(hw):
    seed_handoff_run(hw)
    seed_proposal_run(hw, SECOND)
    login(hw)
    seed_workflow(hw, "proposal-earlier", one_time=False)
    _same(phase_4_count(hw), 1, "Phase 4's count before the hand-off")

    expect(accept(hw), 201)
    _same(phase_4_count(hw), 1, "Phase 4's count after the hand-off")
    _same(daily_count(hw), 1, "the hand-offs created in the last day")
    capped = {**deepcopy(hw.settings), "chat_orchestration_max_workflows_per_user": 2}
    _same(hw.drafts.check_orchestration_workflow_quota(OWNER, capped), None, "Phase 4's cap with a slot left")

    # With a cap of two, the hand-off would fill the last slot if it were counted.
    hw.settings["chat_orchestration_max_workflows_per_user"] = 2
    proposal_id = hw.ow.workflow_proposal_id(SECOND, PROPOSAL_STEP)
    accepted = accept_proposal_route(hw, proposal_id, run_id=SECOND, mode="paused")
    expect(accepted, 201)
    _same(phase_4_count(hw), 2, "Phase 4's count after a Phase 4 accept")
    _same(daily_count(hw), 1, "the hand-offs created in the last day after a Phase 4 accept")
    quota = hw.drafts.check_orchestration_workflow_quota(OWNER, capped)
    _same((quota or {}).get("code"), "quota_exceeded", "Phase 4's cap once its own workflows fill it")


# ---------------------------------------------------------------------------
# A workflow at the hand-off's id that is not a hand-off workflow
# ---------------------------------------------------------------------------

def test_a_workflow_at_the_handoff_id_that_is_not_one_time_is_refused_as_another_kind(hw):
    seed_handoff_run(hw)
    login(hw)
    hw.workflows.create_item({
        "id": hw.workflow_id, "user_id": OWNER, "name": "A Phase 4 workflow",
        "origin": {"source": "orchestration", "proposal_id": hw.handoff_id, "conversation_id": CONVERSATION},
        "created_at": hw.clock.now.isoformat(),
    })
    before = writes(hw)
    refused = [accept(hw), deny(hw), draft(hw), accept(hw, mode="edited", workflow={"name": "Edited"})]

    for response in refused:
        expect(response, 409, "handoff_kind_mismatch")
    _same(writes(hw), before, "writes")
    _same(hw.record.queued, [], "queue calls")
    _same(decision(hw), None, "the decision")
    _same(stored_workflow(hw).get("origin", {}).get("one_time"), None, "the other workflow is untouched")
    _same(stored_runs(hw), [], "durable runs")
    row = only_handoff(hw)
    _same((row["state"], row["actions"]), ("pending", ["accept", "edit", "deny"]), "the hand-off's card")
    _require("workflow" not in row, "The card shows a workflow that is not the hand-off's.")
    _same(
        [entry.get("error_type") for entry in handoff_logs(hw, "A hand-off workflow could not be read.")],
        ["HandoffError"], "the status read's log",
    )
    require_no_leak(hw, *refused)


def test_a_one_time_workflow_at_a_proposals_id_is_never_taken_for_the_proposals_workflow(hw):
    seed_proposal_run(hw, SECOND)
    login(hw)
    proposal_id = hw.ow.workflow_proposal_id(SECOND, PROPOSAL_STEP)
    workflow_id = hw.drafts.orchestration_workflow_id(OWNER, proposal_id)
    hw.workflows.create_item({
        "id": workflow_id, "user_id": OWNER, "name": "A hand-off workflow", "is_enabled": False,
        "origin": {
            "source": "orchestration", "proposal_id": proposal_id, "one_time": True,
            "conversation_id": CONVERSATION, "orchestration_run_id": SECOND,
        },
        "created_at": hw.clock.now.isoformat(),
    })
    original = deepcopy(stored_workflow(hw, workflow_id))

    def proposal_card(label):
        proposals = expect(proposal_status_route(hw, SECOND), 200)["proposals"]
        _same(len(proposals), 1, f"the proposals {label}")
        row = proposals[0]
        _same((row["proposal_id"], row["state"], row["workflow"]), (proposal_id, "pending", None),
              f"the proposal's card {label}")
        _same(row["actions"]["open_workflow"], False, f"the card's open-workflow action {label}")
        return row

    proposal_card("before any decision")
    expect(draft_proposal_route(hw, proposal_id, run_id=SECOND), 200)
    refused = accept_proposal_route(hw, proposal_id, run_id=SECOND, mode="paused")

    expect(refused, 409, "workflow_conflict")
    _same(stored_workflow(hw, workflow_id), original, "the one-time workflow after Phase 4's accept")
    _same((run(hw, SECOND).get("workflow_proposal_decisions") or {}).get(proposal_id), None,
          "the proposal's decision after the refused accept")
    proposal_card("after the refused accept")
    denied = expect(deny_proposal_route(hw, proposal_id, run_id=SECOND), 200)
    _same(denied, {"proposal_id": proposal_id, "state": "denied"}, "the deny")
    _same(stored_workflow(hw, workflow_id), original, "the one-time workflow after the deny")
    _same(hw.workflows.records(OWNER), [original], "workflows")
    _same(hw.record.queued, [], "queue calls")
    require_no_leak(hw, refused)


# ---------------------------------------------------------------------------
# Expiry, integrity and the card
# ---------------------------------------------------------------------------

def nothing_left(hw, label):
    _same((decision(hw), stored_workflow(hw), hw.record.queued), (None, None, []), label)


def test_an_expired_handoff_shows_what_it_covered_and_refuses_every_decision(hw):
    seed_handoff_run(hw)
    login(hw)
    expires_at = CREATED_AT + hw.ho.WORKFLOW_HANDOFF_TTL
    hw.clock.now = expires_at - timedelta(seconds=1)
    _same(only_handoff(hw)["state"], "pending", "the hand-off a second before it expires")

    hw.clock.now = expires_at
    shown = status(hw)
    row = only_handoff(hw)
    _same((row["state"], row["reason"], row["actions"]), ("expired", None, []), "the expired card")
    _require(
        isinstance(row["summary"], dict) and isinstance(row["disclosure"], dict),
        "An expired hand-off no longer shows what it would have covered.",
    )
    before = writes(hw)
    refused = [accept(hw), accept(hw, mode="edited", workflow={"name": "Edited"}), deny(hw), draft(hw)]
    for response in refused:
        _same(expect(response, 409, "handoff_expired").get("state"), "expired", "an expired refusal's state")
    _same(writes(hw), before, "writes after the hand-off expired")
    nothing_left(hw, "what an expired hand-off left")
    require_no_leak(hw, shown, *refused)


def test_an_accepted_handoff_outlives_its_expiry(hw):
    seed_handoff_run(hw)
    login(hw)
    first = expect(accept(hw), 201)
    hw.clock.now = CREATED_AT + hw.ho.WORKFLOW_HANDOFF_TTL + timedelta(days=1)

    row = only_handoff(hw)
    _same((row["state"], row["reason"], row["actions"]), ("queued", None, []), "the accepted card after expiry")
    _same(row["run"]["id"], first["run"]["id"], "the card's run")
    again = accept(hw)
    payload = expect(again, 200)
    _same((payload["created"], payload["run"]["id"]), (False, first["run"]["id"]), "an accept after expiry")
    declined = deny(hw)
    _same(expect(declined, 409, "handoff_accepted").get("state"), "created", "a decline after expiry")
    drafted = draft(hw)
    _same(expect(drafted, 409, "handoff_accepted").get("state"), "created", "a draft after expiry")
    _same(len(hw.record.queued), 1, "queue calls")
    _same(len(stored_runs(hw)), 1, "durable runs")
    _same(decision(hw)["state"], "queued", "the decision")
    require_no_leak(hw, again, declined, drafted)


def test_a_created_but_unqueued_handoff_still_queues_after_it_expires(hw):
    seed_handoff_run(hw)
    login(hw)
    hw.state.fail_queue = AzureError(EXCEPTION_TEXT)
    failed = accept(hw)
    _same(expect(failed, 503, "handoff_queue_failed").get("state"), "created", "the failed accept's state")
    hw.clock.now = CREATED_AT + hw.ho.WORKFLOW_HANDOFF_TTL + timedelta(hours=1)

    row = only_handoff(hw)
    _same((row["state"], row["actions"]), ("created", ["accept"]), "the unqueued card after expiry")
    _same(row["workflow"], {"id": hw.workflow_id, "name": stored_workflow(hw)["name"], "is_enabled": False},
          "the unqueued card's workflow")
    retried = accept(hw)
    run_id = expected_run_id(hw.workflow_id, hw.handoff_id)
    _same(expect(retried, 200)["run"]["id"], run_id, "the retry's run")
    _same([entry["id"] for entry in stored_runs(hw)], [run_id], "durable runs")
    _same([entry["id"] for entry in hw.workflows.records(OWNER)], [hw.workflow_id], "workflows")
    _same(len(hw.record.created), 1, "creation logs")
    _same(len(hw.record.queued), 2, "queue calls")
    require_no_leak(hw, failed, retried)


@pytest.mark.parametrize("handoff_id", [
    "not-a-uuid", "00000000-0000-0000-0000-000000000000", "{handoff}".upper(), "{handoff} ",
])
def test_a_handoff_id_that_is_not_the_runs_own_is_not_found(hw, handoff_id):
    seed_handoff_run(hw)
    login(hw)
    handoff_id = handoff_id.replace("{handoff}", hw.handoff_id).replace("{HANDOFF}", hw.handoff_id.upper())
    before = writes(hw)
    responses = [
        accept(hw, handoff_id), accept(hw, handoff_id, mode="edited", workflow={"name": "Edited"}),
        deny(hw, handoff_id), draft(hw, handoff_id),
    ]
    for response in responses:
        expect(response, 404, "handoff_not_found")
    _same(writes(hw), before, "writes")
    nothing_left(hw, "what the requests left")
    require_no_leak(hw, *responses)


def test_a_legacy_plan_is_refused_like_every_other_run_route(hw):
    seed_handoff_run(hw)
    login(hw)
    run(hw)["plan"]["planner_contract_version"] = 1
    before = writes(hw)
    for response in (status(hw), accept(hw), deny(hw), draft(hw)):
        expect(response, 409, "legacy_plan")
    _same(writes(hw), before, "writes")
    nothing_left(hw, "what the requests left")


@pytest.mark.parametrize("changes", [
    {"requester_user_id": OTHER},
    {"conversation_id": OTHER_CONVERSATION},
    {"handoff_id": "00000000-0000-4000-8000-000000000000"},
    {"step_id": "another-step"},
    {"version": 2},
], ids=["requester", "conversation", "handoff", "step", "version"])
def test_a_sidecar_that_does_not_match_its_run_is_never_shown_or_decided(hw, changes):
    seed_handoff_run(hw, sidecar_changes=changes)
    login(hw)
    before = writes(hw)
    shown = status(hw)
    _same(expect(shown, 200)["handoffs"], [], "the hand-offs a mismatched sidecar shows")
    responses = [accept(hw), deny(hw), draft(hw)]
    for response in responses:
        expect(response, 404, "handoff_not_found")
    logs = handoff_logs(hw, "A workflow hand-off did not match the run that produced it.")
    _require(logs, "The mismatch was not logged.")
    _same({entry.get("code") for entry in logs}, {"handoff_integrity_mismatch"}, "the mismatch log's code")
    _same(writes(hw), before, "writes")
    nothing_left(hw, "what the requests left")
    require_no_leak(hw, shown, *responses)


def test_a_tampered_blueprint_is_invalid_and_can_only_be_declined(hw):
    seed_handoff_run(hw, sidecar_changes={"blueprint_digest": "0" * 64})
    login(hw)
    row = only_handoff(hw)
    _same((row["state"], row["reason"], row["actions"]), ("invalid", None, ["deny"]), "the tampered card")
    _same((row["summary"], row["disclosure"]), (None, None), "a tampered card's summary and disclosure")
    before = writes(hw)
    refused = [accept(hw), accept(hw, mode="edited", workflow={"name": "Edited"}), draft(hw)]
    for response in refused:
        _same(expect(response, 422, "handoff_invalid").get("state"), "invalid", "a tampered refusal's state")
    _same(writes(hw), before, "writes")
    nothing_left(hw, "what the refusals left")

    declined = deny(hw)
    _same(expect(declined, 200), {"handoff_id": hw.handoff_id, "state": "denied"}, "the decline")
    _same(decision(hw)["state"], "denied", "the decision")
    row = only_handoff(hw)
    _same((row["state"], row["actions"]), ("denied", []), "the declined card")
    _same((stored_workflow(hw), hw.record.queued), (None, []), "what the decline left")
    require_no_leak(hw, *refused, declined)


def test_a_decision_for_another_conversation_or_with_client_fields_is_invalid(hw):
    seed_handoff_run(hw)
    login(hw)
    before = writes(hw)
    for action, payload in (
        ("deny", {"conversation_id": OTHER_CONVERSATION}),
        ("deny", {"conversation_id": CONVERSATION, "reason": "Not now"}),
        ("accept", {"conversation_id": OTHER_CONVERSATION, "mode": "as_proposed"}),
        ("accept", {"conversation_id": CONVERSATION, "mode": "as_proposed", "model_selection": deepcopy(SEEDS)}),
        ("accept", {"conversation_id": CONVERSATION, "mode": "as_proposed", "time_zone": "UTC"}),
        ("accept", {"conversation_id": CONVERSATION, "mode": "as_proposed", "one_time": False}),
    ):
        _same(refusal(hw, direct(hw, action, body=payload)), "invalid_request", f"a direct {action} of {sorted(payload)}")
    responses = [accept(hw, model_selection=deepcopy(SEEDS)), accept(hw, time_zone="UTC"), accept(hw, one_time=False)]
    for response in responses:
        expect(response, 400, "invalid_request")
    _same(writes(hw), before, "writes")
    nothing_left(hw, "what the refusals left")
    require_no_leak(hw, *responses)


def count_text(count, noun):
    return f"{count:,} {noun}" if count != 1 else f"1 {noun[:-1]}"


def test_the_card_discloses_exactly_what_a_handoff_covers_and_never_an_id(hw):
    seed_handoff_run(hw)
    login(hw)
    shown = status(hw)
    row = only_handoff(hw)
    _same(set(row), ROW_KEYS, "a pending card's fields")
    _same((row["state"], row["reason"], row["actions"]), ("pending", None, ["accept", "edit", "deny"]), "the card")
    _same((row["handoff_id"], row["step_id"]), (hw.handoff_id, STEP), "the card's hand-off")
    _same(row["summary"]["one_time"], True, "the summary's one-time marker")
    _same(row["summary"]["durable"], True, "the summary's durable marker")
    count = len(documents_loop(hw)["documents"])
    _same(row["disclosure"], {
        "kind": "documents", "count": count, "limit_behavior": "exact", "text": count_text(count, "documents"),
        "scope_count": 0, "scope_names": [],
    }, "the named documents' disclosure")

    accepted = expect(accept(hw), 201)
    row = only_handoff(hw)
    stored = stored_runs(hw)[0]
    _same(set(row), ROW_KEYS | {"workflow", "run", "chat_delivery"}, "a queued card's fields")
    _same((row["state"], row["reason"], row["actions"]), ("queued", None, []), "the queued card")
    _same(row["workflow"], {"id": hw.workflow_id, "name": stored_workflow(hw)["name"], "is_enabled": False},
          "the queued card's workflow")
    _same(row["run"], {"id": accepted["run"]["id"], "status": str(stored["status"]).strip().lower()},
          "the queued card's run")
    _same(row["chat_delivery"], True, "the queued card's chat delivery")
    require_no_leak(hw, shown, status(hw))


def test_a_workspace_query_is_disclosed_as_up_to_its_bound_with_workspace_names(hw):
    builder = importlib.import_module("functions_workflow_handoff_builder")
    sidecar = seed_handoff_run(hw, loop=query_loop(hw))
    login(hw)
    shown = status(hw)
    disclosure = only_handoff(hw)["disclosure"]
    limit = disclosure["limit"]
    _require(type(limit) is int and limit > 1, f"A workspace query's bound must be a count: {limit!r}")
    _same(limit, sidecar["loop_limit"], "the disclosed bound is the dry run's")
    _same(
        {key: value for key, value in disclosure.items() if key != "scope_names"},
        {
            "kind": "workspace_query", "limit": limit, "limit_behavior": "pause",
            "text": f"up to {limit:,} matching documents. {builder.HANDOFF_PAUSE_NOTE}",
            "scope_count": len(query_loop(hw)["scopes"]),
        },
        "the workspace query's disclosure",
    )
    names = disclosure["scope_names"]
    _require(names and all(isinstance(name, str) and name for name in names), f"Unnamed workspaces: {names!r}")
    _same(len(names), disclosure["scope_count"], "a name for every workspace")
    require_no_leak(hw, shown)


def test_an_accept_creates_the_disclosed_bound_and_refuses_a_limit_lowered_below_it(hw):
    sidecar = seed_handoff_run(hw, loop=query_loop(hw))
    login(hw)
    disclosed = sidecar["loop_limit"]
    _require(type(disclosed) is int and 1 < disclosed < 2000, f"The disclosed bound must leave room: {disclosed!r}")

    # A limit lowered below what the card disclosed refuses the accept, so the card never overstates the run.
    hw.settings["workflow_max_loop_items"] = disclosed - 1
    refused = accept(hw)

    expect(refused, 409, "handoff_limit_changed")
    nothing_left(hw, "what a lowered limit left")
    _same(stored_runs(hw), [], "durable runs after a lowered limit")
    require_no_leak(hw, refused)

    # A raised limit still creates the bound the card disclosed, never the new one.
    hw.settings["workflow_max_loop_items"] = disclosed + 1
    expect(accept(hw), 201)
    loop = stored_workflow(hw)["flow"]["nodes"][0]
    _same((loop["kind"], loop["max_items"]), ("for_each", disclosed), "the stored loop's bound")


def test_a_workflow_deleted_after_its_accept_is_not_created_again(hw):
    seed_handoff_run(hw)
    login(hw)
    accepted = expect(accept(hw), 201)
    del hw.workflows.items[(OWNER, hw.workflow_id)]

    row = only_handoff(hw)
    _same((row["state"], row["reason"], row["actions"]), ("queued", "workflow_deleted", []), "the deleted card")
    _require("workflow" not in row, "A deleted workflow is still shown.")
    _same((row["run"]["id"], row["chat_delivery"]), (accepted["run"]["id"], True), "the deleted card's run")
    before = writes(hw)
    responses = [accept(hw), deny(hw), draft(hw)]
    for response, error in zip(responses, ("workflow_deleted", "handoff_accepted", "workflow_deleted")):
        _same(expect(response, 409, error).get("state"), "queued", f"the {error} refusal's state")
    _same(writes(hw), before, "writes after the workflow was deleted")
    _same((stored_workflow(hw), len(hw.record.queued), len(stored_runs(hw))), (None, 1, 1), "what was left")
    require_no_leak(hw, *responses)


def test_a_handoff_whose_response_content_review_removed_can_only_be_declined(hw):
    seed_handoff_run(hw, chat_content_output_pending=True)
    login(hw)
    shown = status(hw)
    row = only_handoff(hw)
    _same((row["state"], row["reason"], row["actions"]), ("unavailable", "content_review", ["deny"]), "the card")
    _same((row["summary"], row["disclosure"]), (None, None), "a removed run's summary and disclosure")
    before = writes(hw)
    refused = [accept(hw), accept(hw, mode="edited", workflow={"name": "Edited"}), draft(hw)]
    for response in refused:
        expect(response, 409, "handoff_unavailable")
    _same(writes(hw), before, "writes")
    nothing_left(hw, "what the refusals left")

    declined = deny(hw)
    _same(expect(declined, 200), {"handoff_id": hw.handoff_id, "state": "denied"}, "the decline")
    row = only_handoff(hw)
    _same((row["state"], row["reason"], row["actions"]), ("unavailable", "content_review", []), "the declined card")
    _same((stored_workflow(hw), hw.record.queued), (None, []), "what the decline left")
    require_no_leak(hw, shown, *refused, declined)


def test_a_storage_failure_is_a_closed_code_and_a_card_never_mistakes_it_for_a_deletion(hw):
    seed_handoff_run(hw)
    login(hw)
    hw.workflows.read_error = AzureError(EXCEPTION_TEXT)
    failed = accept(hw)
    expect(failed, 503, "service_unavailable")
    logs = handoff_logs(hw, "A workflow hand-off request could not be completed.")
    _same([(entry.get("stage"), entry.get("error_type")) for entry in logs], [("workflow_handoff", "AzureError")],
          "the route's failure log")
    nothing_left(hw, "what the failed accept left")

    hw.workflows.read_error = AzureError(EXCEPTION_TEXT)
    row = only_handoff(hw)
    _same((row["state"], row["actions"]), ("pending", ["accept", "edit", "deny"]), "a card whose workflow read failed")
    _require("workflow" not in row, "A workflow that could not be read is shown.")

    accepted = expect(accept(hw), 201)
    hw.workflows.read_error = AzureError(EXCEPTION_TEXT)
    row = only_handoff(hw)
    _same((row["state"], row["reason"], row["actions"]), ("queued", None, []), "a queued card whose workflow read failed")
    _require("workflow" not in row, "A queued workflow that could not be read is shown.")
    _same(row["run"]["id"], accepted["run"]["id"], "the queued card's run")
    _same(
        [entry.get("error_type") for entry in handoff_logs(hw, "A hand-off workflow could not be read.")],
        ["AzureError", "AzureError"], "the workflow read logs",
    )

    hw.wf_runs.read_error = AzureError(EXCEPTION_TEXT)
    row = only_handoff(hw)
    _same(row["run"], {"id": accepted["run"]["id"]}, "a run that could not be read")
    _same(
        [entry.get("error_type") for entry in handoff_logs(hw, "A hand-off run could not be read.")],
        ["AzureError"], "the run read log",
    )
    _same(len(hw.record.queued), 1, "queue calls")
    require_no_leak(hw, failed)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
