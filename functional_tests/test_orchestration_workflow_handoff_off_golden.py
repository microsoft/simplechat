#!/usr/bin/env python3
# test_orchestration_workflow_handoff_off_golden.py
"""
Functional test for the chat orchestration workflow hand-off setting-off golden.
Version: 0.261.231
Implemented in: 0.261.231

This test ensures that, with ``enable_chat_orchestration_workflow_handoff`` off (absent, False
or the string "true"), or on while another hand-off gate is off, chat orchestration is
byte-identical to the release before the ``workflow_handoff`` capability existed. It compares,
against a committed golden fixture, for every gate variant:

- the workflow planning context the ``/plan`` route stores, and the storage reads it makes;
- the exact messages the planner model receives, the plan it produces, the plan validation
  errors and the planner's log entries;
- a plan over the step budget and a plan over the document limit, and how the planner answers
  each, including whether it asks the model to repair the plan;
- a workflow proposal and a workflow run step that cannot be repaired, and the degraded plan;
- the capability resolution and unavailable reasons, and the capability list the V2 bootstrap
  sends the browser;

and, for every value of the setting, the workflow proposal card, status, draft, accept and deny
responses, the workflow an accept creates and the decision it stores, and the workflow run
links response.

With the setting on and every other gate on, planning changes on purpose: those variants are
not compared with the setting on. The browser's capability list is resolved without a request,
so it lists ``workflow_handoff`` for a missing role or a shared conversation exactly as it lists
``workflow_propose``; that one entry is checked, then left out of the comparison.

The fixture was captured on the unmodified base (fd842e199, 0.261.228, before workflow hand-off).

Never regenerate the fixture to make this test pass. After merging an upstream planner or route
change, regenerate it from the upstream commit itself (without this feature):

    python functional_tests/test_orchestration_workflow_handoff_off_golden.py --write-golden
"""

import hashlib
import importlib
import json
import re
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Blueprint, Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_proposal_routes import (
    BLUEPRINT,
    CONVERSATION,
    EMAIL,
    FIELD,
    OTHER_CONVERSATION,
    READY_PLANNING,
    RUN,
    SECOND,
    STEP,
    TENANT,
    TURN,
    WORKFLOW_SETTINGS,
    RunStore,
    WorkflowStore,
    _log_recorder,
    _plan as _proposal_plan,
    _url,
)
from test_orchestration_workflow_results_off_golden import _client_projection, _handle, _with_run_step
from test_orchestration_workflow_runs_off_golden import (
    ANSWER_STEP,
    DOCUMENT_ID,
    FINAL_RESPONSE,
    MESSAGE,
    NOW,
    OWNER,
    PLAIN_PLAN,
    PRIVATE,
    PROPOSAL_PLAN,
    PROPOSALS,
    RUNS,
    SETTINGS,
    SHARED,
    USER_INFO,
    ZONE,
    _diff,
    _fail,
    _lines,
    _pretty,
    _readers,
    _request_context,
    _resolution,
)
from test_orchestration_workflow_setting_off_golden import (
    ACTIONS,
    AGENTS,
    CANDIDATES,
    DEPLOYMENT,
    PLANNER_JSON,
    _Completions,
    _FrozenDatetime,
)
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least


GOLDEN = Path(__file__).resolve().parent / "test_support" / "orchestration_workflow_handoff_off_golden.json"
CAPTURED_FROM = "fd842e199 (0.261.228, before workflow hand-off)"
HANDOFF = "enable_chat_orchestration_workflow_handoff"
RESULTS = "enable_chat_workflow_results"
HANDOFF_CAPABILITY = "workflow_handoff"
# The hand-off setting's values. ``None`` removes the key.
KEY_STATES = {
    "absent": None,
    "false": {HANDOFF: False},
    "string": {HANDOFF: "true"},
    "on": {HANDOFF: True},
}
ALLOWLIST = ["compose", "document_analyze", "workflow_propose", "workflow_run", "workflow_results"]
# Each variant: settings changes, conversation, planning reader overrides. Every other hand-off
# gate is on in ``all_on``; each other variant turns one gate off or breaks one read.
VARIANTS = {
    "all_on": ({}, PRIVATE, {}),
    "orchestration_off": ({"enable_chat_orchestration": False}, PRIVATE, {}),
    "user_workflows_off": ({"allow_user_workflows": False}, PRIVATE, {}),
    "proposals_off": ({PROPOSALS: False}, PRIVATE, {}),
    "runs_off": ({RUNS: False}, PRIVATE, {}),
    "results_off": ({RESULTS: False}, PRIVATE, {}),
    "role_missing": ({"require_member_of_workflow_user": True}, PRIVATE, {}),
    "shared_conversation": ({}, SHARED, {}),
    "not_allowlisted": ({"chat_orchestration_enabled_capabilities": ALLOWLIST}, PRIVATE, {}),
    "quota_reached": ({}, PRIVATE, {"quota_count": lambda user_id: 20}),
    "quota_unreadable": ({}, PRIVATE, {"quota_count": _fail}),
    "catalog_unreadable": ({}, PRIVATE, {"workflows": _fail}),
}
# With the setting on and these variants, hand-off is available and planning changes on purpose.
# Hand-off does not depend on the workflow proposal cap or the workflow catalog.
CHANGED_WHEN_ON = frozenset({"all_on", "quota_reached", "quota_unreadable", "catalog_unreadable"})
# The browser's capability list has no request, so it cannot see a role or a shared conversation.
PROJECTION_WITHOUT_REQUEST = frozenset({"role_missing", "shared_conversation"})

OVERFLOW_STEPS = 9
STEP_OVERFLOW_PLAN = {
    "kind": "plan", "intent": {"summary": "A long weekly plan."},
    "steps": [
        {
            "step_id": f"answer_{index}", "capability_id": "compose",
            "arguments": {"instruction": f"Write part {index} of this week's plan.", "knowledge_basis": "general_knowledge"},
            "inputs": {}, "outputs": [{"name": "answer", "kind": "markdown-v1"}],
        }
        for index in range(1, OVERFLOW_STEPS + 1)
    ],
    "final_response": {**FINAL_RESPONSE, "step_id": f"answer_{OVERFLOW_STEPS}"},
}
OVERFLOW_DOCUMENTS = [f"document-record-{index}" for index in range(1, 5)]
DOCUMENT_OVERFLOW_PLAN = {
    "kind": "plan", "intent": {"summary": "Review every priorities document."},
    "steps": [
        {
            "step_id": "analyze", "capability_id": "document_analyze",
            "arguments": {"analysis_prompt": "List the priorities in each document.", "document_ids": OVERFLOW_DOCUMENTS},
            "inputs": {}, "outputs": [{"name": "findings", "kind": "records-v1"}],
        },
        {
            **deepcopy(ANSWER_STEP),
            "inputs": {"findings": {
                "version": "orchestration-input-binding-v1", "step_id": "analyze",
                "output_name": "findings", "existing_result": None,
            }},
            "depends_on": ["analyze"],
        },
    ],
    "final_response": FINAL_RESPONSE,
}
PLAN_DOCUMENTS = {
    "plain": ["document-record-1"],
    "step_overflow": ["document-record-1"],
    "document_overflow": OVERFLOW_DOCUMENTS,
    "proposal_degrade": ["document-record-1"],
    "run_degrade": ["document-record-1"],
}

ROUTE_NOW = datetime(2031, 3, 4, 15, 0, tzinfo=timezone.utc)
ROUTE_CREATED_AT = ROUTE_NOW - timedelta(hours=1)
ROUTE_SETTINGS = {**WORKFLOW_SETTINGS, RUNS: True, RESULTS: True}
UNKNOWN_PROPOSAL = "00000000-0000-5000-8000-000000000000"
LINK_RUN = "run_" + "4" * 32
LINK_STEP = "run_digest"
LINK_WORKFLOW_ID = "workflow-digest"
LINK_NAME = "Weekly digest"

# Ids the plan schema draws at random, replaced by stable names in order of appearance.
_RANDOM_PLAN_IDS = re.compile(r"\b(plan|run|turn|ask)_[0-9a-f]{32}\b")
_RANDOM_UUIDS = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b")
_CLAIM_IDS = re.compile(r'("claim_id"\s*:\s*")[0-9a-f]{32}(")')
_MISSING = object()


def _apply_key(settings, key_state):
    settings.pop(HANDOFF, None)
    settings.update(deepcopy(KEY_STATES[key_state] or {}))
    return settings


def _settings(key_state, changes=None):
    settings = {**deepcopy(SETTINGS), RUNS: True, RESULTS: True}
    _apply_key(settings, key_state)
    settings.update(deepcopy(changes or {}))
    return settings


def _stable(value):
    """``value`` as plain JSON, with randomly drawn ids replaced by stable names."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    names = {}

    def rename(prefix):
        def replace(match):
            token = match.group(0)
            if token not in names:
                label = prefix or match.group(1)
                count = sum(1 for name in names.values() if name.startswith(f"<{label}_"))
                names[token] = f"<{label}_{count + 1}>"
            return names[token]
        return replace

    text = _RANDOM_PLAN_IDS.sub(rename(None), text)
    text = _RANDOM_UUIDS.sub(rename("uuid"), text)
    return json.loads(text)


def _build_context(wf, settings, conversation, overrides):
    calls = []
    documents = wf.workflow_planning_documents(
        {DOCUMENT_ID: {"scope": "personal", "scope_id": OWNER, "file_name": "Weekly priorities.docx"}},
        {}, [DOCUMENT_ID],
    )
    context = wf.build_workflow_planning_context(
        deepcopy(settings), user_id=OWNER, user_info=deepcopy(USER_INFO), conversation=deepcopy(conversation),
        time_zone=ZONE, now=NOW, documents=documents, readers=_readers(calls, **overrides), request_text=MESSAGE,
    )
    return context, calls


def _install_recorders(patch, planner):
    """Record every plan validation error and planner log entry, for the plan being made."""
    recorder = SimpleNamespace(errors=[], logs=[])
    normalize_plan = planner.normalize_plan

    def recording_normalize(*args, **kwargs):
        try:
            return normalize_plan(*args, **kwargs)
        except Exception as exc:
            recorder.errors.append({
                "type": type(exc).__name__, "code": getattr(exc, "code", None),
                "rule": getattr(exc, "rule", None), "message": str(exc),
            })
            raise

    def recording_log(message, *args, **kwargs):
        extra = {
            key: value for key, value in (kwargs.get("extra") or {}).items()
            if not str(key).endswith("_ms")
        }
        recorder.logs.append(_stable({"message": str(message), "level": kwargs.get("level"), "extra": extra}))

    patch.setattr(planner, "normalize_plan", recording_normalize)
    patch.setattr(planner, "log_event", recording_log)
    return recorder


def _plan(patch, recorder, settings, workflow_planning, replies, documents):
    """Plan the request through the real planner with scripted replies."""
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
    recorder.errors, recorder.logs = [], []
    try:
        kind, document = planner.plan_request(
            MESSAGE, planner_context, "conversation", OWNER, settings=deepcopy(settings),
            authorized_document_ids=list(documents), revision=0, allow_elicitation=True,
            turn_id="turn", seeds={},
            document_labels={value: f"{value}.docx" for value in documents},
            request_context=request_context, planner_model=None, existing_results={},
            composition_profiles=services.composition_profiles(), export_catalog=[],
        )
        outcome = {"kind": kind, "document": _stable(document)}
    except planner.PlannerError as exc:
        outcome = {"planner_error": {"reason": getattr(exc, "reason", None), "message": exc.message}}
    return {"calls": calls, "normalize_errors": recorder.errors, "logs": recorder.logs, "outcome": outcome}


def _attempt(function, *args):
    try:
        return {"value": function(*args)}
    except Exception as exc:
        return {"error": {"type": type(exc).__name__, "message": str(exc)}}


def _capture_planning(patch, key_state):
    """Everything the golden pins about planning, for one value of the hand-off setting."""
    wf = importlib.import_module("functions_orchestration_workflow_context")
    planner = importlib.import_module("functions_orchestration_planner")
    recorder = _install_recorders(patch, planner)
    captured = {}
    for name, (changes, conversation, overrides) in VARIANTS.items():
        settings = _settings(key_state, changes)
        context, reads = _build_context(wf, settings, conversation, overrides)
        scripts = {
            "plain": [PLAIN_PLAN],
            "step_overflow": [STEP_OVERFLOW_PLAN, PLAIN_PLAN],
            "document_overflow": [DOCUMENT_OVERFLOW_PLAN, PLAIN_PLAN],
        }
        if name == "all_on":
            scripts["proposal_degrade"] = [PROPOSAL_PLAN, PROPOSAL_PLAN]
            # The newest workflow is not durable, so a step that starts it is repaired once, then dropped.
            scripts["run_degrade"] = [_with_run_step(_handle(context, "Contract watcher"))] * 2
        plans = {
            plan_name: _plan(patch, recorder, settings, context, replies, PLAN_DOCUMENTS[plan_name])
            for plan_name, replies in scripts.items()
        }
        captured[name] = {
            "context": context,
            "reads": reads,
            "plans": plans,
            "resolution": _attempt(_resolution, settings, context),
            "client_projection": _attempt(_client_projection, settings),
        }
    return captured


def _response(response):
    """A route response, byte for byte, with the random decision claim id named."""
    text = _CLAIM_IDS.sub(r"\1<claim_id>\2", response.get_data(as_text=True))
    try:
        body = json.loads(text)
    except ValueError:
        body = _lines(text)
    return {
        "status": response.status_code,
        "content_type": response.content_type,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "body": body,
    }


def _record(value):
    return json.loads(_CLAIM_IDS.sub(r"\1<claim_id>\2", json.dumps(value, ensure_ascii=False, default=str)))


def _proposal_sidecar(ow, settings, run_id):
    """The proposal sidecar and card the executor stores, from the production builder and dry run."""
    step = {
        "step_id": STEP,
        "arguments": {"blueprint": deepcopy(BLUEPRINT), "task_actions": [[] for _ in BLUEPRINT["tasks"]]},
    }
    context = SimpleNamespace(
        workflow_planning=deepcopy(READY_PLANNING), time_zone=ZONE, user_email=EMAIL, user_roles=["User"],
    )
    producer = SimpleNamespace(run_id=run_id, step_id=STEP, conversation_id=CONVERSATION)
    sidecar, card = ow.build_workflow_proposal(
        step, context, settings=deepcopy(settings), user_id=OWNER, producer=producer, created_at=ROUTE_CREATED_AT,
    )
    if sidecar.get("status") != "ready":
        raise AssertionError(f"The golden proposal is not ready: {sidecar.get('reason')}")
    return sidecar, card


def _capture_routes(patch, ns, key_state):
    """The workflow proposal and workflow run link routes, for one value of the hand-off setting."""
    proposals = importlib.import_module("functions_orchestration_workflow_proposals")
    personal = importlib.import_module("functions_personal_workflows")
    drafts = importlib.import_module("functions_workflow_drafts")
    ow = importlib.import_module("functions_orchestration_workflows")
    links = importlib.import_module("functions_orchestration_workflow_run_links")
    wr = importlib.import_module("functions_orchestration_workflow_runs")
    settings_module = importlib.import_module("functions_settings")
    settings = {**deepcopy(settings_module.get_settings() or {}), **deepcopy(ROUTE_SETTINGS)}
    _apply_key(settings, key_state)
    conversations = AtomicMemoryContainer("id")
    runs = RunStore()
    steps = AtomicMemoryContainer("run_id")
    workflows = WorkflowStore("user_id")
    workflow_runs = AtomicMemoryContainer("user_id")
    for module, name, value in (
        (ns.config, "cosmos_conversations_container", conversations),
        (ns.route, "cosmos_conversations_container", conversations),
        (ns.config, "cosmos_orchestration_runs_container", runs),
        (ns.runs, "cosmos_orchestration_runs_container", runs),
        (ns.config, "cosmos_orchestration_run_steps_container", steps),
        (ns.runs, "cosmos_orchestration_run_steps_container", steps),
        (ns.config, "cosmos_personal_workflows_container", workflows),
        (personal, "cosmos_personal_workflows_container", workflows),
        (ns.config, "cosmos_personal_workflow_runs_container", workflow_runs),
    ):
        patch.setattr(module, name, value, raising=False)
    created, logs = [], []
    patch.setattr(ns.auth, "check_user_access_status", lambda user_id: (True, None))
    patch.setattr(ns.route, "get_settings", lambda: deepcopy(settings))
    patch.setattr(ns.route, "log_workflow_creation", lambda **kwargs: created.append(_record(kwargs)))
    patch.setattr(proposals, "_now", lambda: ROUTE_NOW)
    patch.setattr(proposals, "_m365_connected", lambda user_id, tenant_id: True)
    patch.setattr(ow, "_now", lambda: ROUTE_NOW)
    patch.setattr(personal, "_utc_now", lambda: ROUTE_NOW)
    patch.setattr(ns.runs, "_utc_now_iso", lambda: ROUTE_NOW.isoformat())
    for module in (proposals, ns.route, drafts, links):
        patch.setattr(module, "log_event", _log_recorder(logs, module.__name__))

    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="workflow-handoff-off-golden")
    blueprint = Blueprint("backend_orchestration", __name__)
    blueprint.before_request(ns.auth.user_required_blueprint())
    ns.route.register_route_backend_orchestration(blueprint)
    app.register_blueprint(blueprint)
    client = Client(app, Response)
    cookie = app.session_interface.get_signing_serializer(app).dumps({
        "user": {"oid": OWNER, "roles": ["User"], "tid": TENANT, "preferred_username": EMAIL},
    })
    client.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie)
    conversations.create_item({"id": CONVERSATION, "user_id": OWNER, "title": "Private"})
    conversations.create_item({"id": OTHER_CONVERSATION, "user_id": OWNER, "title": "Another"})

    def seed_proposal(run_id):
        sidecar, card = _proposal_sidecar(ow, settings, run_id)
        runs.create_item({
            "id": run_id, "run_id": run_id, "conversation_id": CONVERSATION, "user_id": OWNER,
            "turn_id": TURN, "status": "completed", "plan": _proposal_plan(BLUEPRINT),
            "execution_steps": [{
                "step_id": STEP, "capability_id": "workflow_propose", "status": "completed",
                "workflow_proposal": sidecar,
            }],
        })
        return {"sidecar": _record(sidecar), "card": _record(card)}

    query = {"conversation_id": CONVERSATION}
    proposal_id = ow.workflow_proposal_id(RUN, STEP)
    second_id = ow.workflow_proposal_id(SECOND, STEP)
    proposal = {"seeded": seed_proposal(RUN)}
    proposal["status"] = _response(client.get(_url(RUN), query_string=query))
    proposal["draft"] = _response(client.get(_url(RUN, proposal_id, "draft"), query_string=query))
    proposal["accept"] = _response(client.post(_url(RUN, proposal_id, "accept"), json={**query, "mode": "paused"}))
    proposal["workflow"] = _record(workflows.items.get((OWNER, drafts.orchestration_workflow_id(OWNER, proposal_id))))
    proposal["accept_again"] = _response(
        client.post(_url(RUN, proposal_id, "accept"), json={**query, "mode": "paused"}),
    )
    proposal["accept_unknown"] = _response(
        client.post(_url(RUN, UNKNOWN_PROPOSAL, "accept"), json={**query, "mode": "paused"}),
    )
    proposal["status_after_accept"] = _response(client.get(_url(RUN), query_string=query))
    proposal["second_seeded"] = seed_proposal(SECOND)
    proposal["deny"] = _response(client.post(_url(SECOND, second_id, "deny"), json=query))
    proposal["status_after_deny"] = _response(client.get(_url(SECOND), query_string=query))
    proposal["creation_logs"] = created
    proposal["decisions"] = {
        "accepted": _record(runs.items[(CONVERSATION, RUN)].get(FIELD)),
        "denied": _record(runs.items[(CONVERSATION, SECOND)].get(FIELD)),
    }

    run_step = {
        "step_id": LINK_STEP, "capability_id": "workflow_run", "enabled": True,
        "arguments": {"workflow": "weekly-digest"}, "inputs": {},
        "outputs": [{"name": "run", "kind": "structured-v1"}],
    }
    run_id = wr.started_workflow_run_id(OWNER, LINK_WORKFLOW_ID, attempt_root_run_id=LINK_RUN, step_id=LINK_STEP)
    runs.create_item({
        "id": LINK_RUN, "run_id": LINK_RUN, "conversation_id": CONVERSATION, "user_id": OWNER,
        "turn_id": TURN, "status": "completed",
        "plan": {"planner_contract_version": 2, "turn_id": TURN, "steps": [run_step]},
        "execution_steps": [{
            "step_id": LINK_STEP, "capability_id": "workflow_run", "status": "completed",
            "workflow_run": {
                "version": 1, "step_id": LINK_STEP, "orchestration_run_id": LINK_RUN,
                "attempt_root_run_id": LINK_RUN, "conversation_id": CONVERSATION, "requested_by": OWNER,
                "handle": "weekly-digest", "workflow_id": LINK_WORKFLOW_ID, "run_id": run_id,
                "name": LINK_NAME, "status": "queued", "reason": None,
            },
        }],
    })
    workflows.upsert_item({
        "id": LINK_WORKFLOW_ID, "user_id": OWNER, "name": LINK_NAME, "durable_execution": True, "is_enabled": True,
    })
    workflow_runs.upsert_item({
        "id": run_id, "workflow_id": LINK_WORKFLOW_ID, "user_id": OWNER, "workflow_name": LINK_NAME,
        "trigger_source": "chat_orchestration", "durable_execution": True, "status": "queued",
    })
    run_links = {
        "links": _response(client.get(f"/api/v2/orchestration/runs/{LINK_RUN}/workflow-runs", query_string=query)),
    }
    return {"proposal": proposal, "run_links": run_links}


def _check_repair_shape(calls, label):
    """Each repair call repeats the first call, then the reply it repairs and the repair message."""
    for call in calls[1:]:
        if call[:2] != calls[0]:
            raise AssertionError(f"{label}: a repair call does not start with the first call")
        roles = [message["role"] for message in call[2:]]
        if roles != ["assistant", "user"]:
            raise AssertionError(f"{label}: unexpected repair roles {roles}")


def _first_call(calls, label):
    if [message["role"] for message in calls[0]] != ["system", "user"]:
        raise AssertionError(f"{label}: the first planner call is not a system and a user message")
    return calls[0]


def _golden_from(planning, routes):
    """The committed fixture shape: readable, diffable, and exact once re-serialized.

    Each distinct system prompt and planner payload is stored once and named.
    """
    prompts, payloads = {}, {}

    def prompt_label(text):
        for label, lines in prompts.items():
            if "\n".join(lines) == text:
                return label
        label = f"prompt_{len(prompts) + 1}"
        prompts[label] = _lines(text)
        return label

    def payload_label(raw):
        parsed = json.loads(raw)
        if json.dumps(parsed, **PLANNER_JSON) != raw:
            raise AssertionError("A planner payload does not re-serialize exactly.")
        for label, value in payloads.items():
            if json.dumps(value, **PLANNER_JSON) == raw:
                return label
        label = f"payload_{len(payloads) + 1}"
        payloads[label] = parsed
        return label

    variants = {}
    for name, entry in planning.items():
        plans = {}
        for plan_name, plan in entry["plans"].items():
            calls = plan["calls"]
            first = None
            if calls:
                label = f"{name} {plan_name}"
                system, user = _first_call(calls, label)
                _check_repair_shape(calls, label)
                first = {"system_prompt": prompt_label(system["content"]), "planner_payload": payload_label(user["content"])}
            plans[plan_name] = {
                "first_call": first,
                "call_count": len(calls),
                "repair_messages": [_lines(call[3]["content"]) for call in calls[1:]],
                "normalize_errors": plan["normalize_errors"],
                "outcome": plan["outcome"],
                "logs": plan["logs"],
            }
        variants[name] = {
            "context": entry["context"],
            "reads": entry["reads"],
            "plans": plans,
            "resolution": entry["resolution"],
            "client_projection": entry["client_projection"],
        }
    return {
        "captured_from": CAPTURED_FROM,
        "system_prompts": prompts,
        "planner_payloads": payloads,
        "variants": variants,
        "routes": routes,
    }


def _load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _assert_same(expected, actual, label):
    if _pretty(expected) != _pretty(actual):
        raise AssertionError(_diff(_pretty(expected), _pretty(actual), label))


def _assert_plan_matches(golden, expected, actual, label):
    calls = actual["calls"]
    if len(calls) != expected["call_count"]:
        raise AssertionError(f"{label}: {len(calls)} planner calls, golden has {expected['call_count']}")
    if calls:
        system, user = _first_call(calls, label)
        prompt = "\n".join(golden["system_prompts"][expected["first_call"]["system_prompt"]])
        if system["content"] != prompt:
            raise AssertionError(_diff(prompt, system["content"], f"{label} system prompt"))
        payload = golden["planner_payloads"][expected["first_call"]["planner_payload"]]
        if user["content"] != json.dumps(payload, **PLANNER_JSON):
            raise AssertionError(_diff(
                _pretty(payload), _pretty(json.loads(user["content"])), f"{label} planner payload",
            ))
        _check_repair_shape(calls, label)
        for call, lines in zip(calls[1:], expected["repair_messages"]):
            repair = "\n".join(lines)
            if call[3]["content"] != repair:
                raise AssertionError(_diff(repair, call[3]["content"], f"{label} repair message"))
    _assert_same(expected["normalize_errors"], actual["normalize_errors"], f"{label} validation errors")
    _assert_same(expected["outcome"], actual["outcome"], f"{label} outcome")
    _assert_same(expected["logs"], actual["logs"], f"{label} planner logs")


def _without_handoff(projection):
    """The browser's capability list without the hand-off entry, which must be there once."""
    entries = projection.get("value") if isinstance(projection, dict) else None
    if not isinstance(entries, list):
        raise AssertionError("The capability list could not be resolved.")
    ids = [entry["id"] for entry in entries]
    if ids.count(HANDOFF_CAPABILITY) != 1:
        raise AssertionError(f"The capability list should offer {HANDOFF_CAPABILITY} once: {ids}")
    return {"value": [entry for entry in entries if entry["id"] != HANDOFF_CAPABILITY]}


def _assert_planning_matches(golden, captured, key_state):
    for name, expected in golden["variants"].items():
        if key_state == "on" and name in CHANGED_WHEN_ON:
            continue
        actual = captured[name]
        _assert_same(expected["context"], actual["context"], f"{name} planning context")
        _assert_same(expected["reads"], actual["reads"], f"{name} planning reads")
        for plan_name, plan in expected["plans"].items():
            _assert_plan_matches(golden, plan, actual["plans"][plan_name], f"{name} {plan_name}")
        _assert_same(expected["resolution"], actual["resolution"], f"{name} capability resolution")
        projection = actual["client_projection"]
        if key_state == "on" and name in PROJECTION_WITHOUT_REQUEST:
            projection = _without_handoff(projection)
        _assert_same(expected["client_projection"], projection, f"{name} client capability projection")


def _real_dates():
    return {datetime.now(timezone.utc).strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d")}


def _check_no_real_date(golden):
    """A fixture that holds today's date was captured with a clock the harness did not freeze."""
    text = _pretty(golden)
    for value in _real_dates():
        if value in text:
            raise AssertionError(f"The golden holds today's date {value}; a clock is not frozen.")


def test_version_includes_the_workflow_handoff_off_golden():
    assert_app_version_at_least("0.261.231")


def test_the_fixture_covers_the_cases_that_matter():
    golden = _load_golden()
    text = GOLDEN.read_text(encoding="utf-8")
    if HANDOFF_CAPABILITY in text or "workflow-handoff" in text or HANDOFF in text:
        raise AssertionError("The golden must come from a base without workflow hand-off.")
    if golden["captured_from"] != CAPTURED_FROM:
        raise AssertionError(golden["captured_from"])
    variants = golden["variants"]
    if set(variants) != set(VARIANTS):
        raise AssertionError(sorted(variants))
    ready = variants["all_on"]
    available = ready["resolution"]["value"]["capability_ids"]
    for capability_id in ("workflow_propose", "workflow_run", "workflow_results", "document_analyze", "compose"):
        if capability_id not in available:
            raise AssertionError(f"all_on does not offer {capability_id}")
    if set(ready["plans"]) != set(PLAN_DOCUMENTS):
        raise AssertionError(sorted(ready["plans"]))
    if ready["plans"]["plain"]["outcome"].get("kind") != "plan":
        raise AssertionError(ready["plans"]["plain"]["outcome"])
    step_overflow = ready["plans"]["step_overflow"]
    if [error["code"] for error in step_overflow["normalize_errors"]] != ["result_step_limit"]:
        raise AssertionError(step_overflow["normalize_errors"])
    document_overflow = ready["plans"]["document_overflow"]
    if [error["code"] for error in document_overflow["normalize_errors"]] != ["plan_invalid"]:
        raise AssertionError(document_overflow["normalize_errors"])
    # Before hand-off, a plan over either budget fails without a repair round.
    for plan in (step_overflow, document_overflow):
        if plan["call_count"] != 1 or "planner_error" not in plan["outcome"]:
            raise AssertionError(plan)
    if ready["plans"]["proposal_degrade"]["call_count"] != 2 or ready["plans"]["run_degrade"]["call_count"] != 2:
        raise AssertionError("The degrade plans must each repair once.")
    for name in PROJECTION_WITHOUT_REQUEST:
        ids = [entry["id"] for entry in variants[name]["client_projection"]["value"]]
        if "workflow_propose" not in ids:
            raise AssertionError(f"{name}: the browser's capability list should offer workflow_propose")
    routes = golden["routes"]["proposal"]
    expected = {"status": 200, "draft": 200, "accept": 201, "accept_again": 200, "accept_unknown": 404, "deny": 200}
    actual = {name: routes[name]["status"] for name in expected}
    if actual != expected:
        raise AssertionError(actual)
    if routes["workflow"] is None or routes["workflow"].get("is_enabled") is not False:
        raise AssertionError("A paused accept must store a disabled workflow.")
    if golden["routes"]["run_links"]["links"]["status"] != 200:
        raise AssertionError(golden["routes"]["run_links"])
    _check_no_real_date(golden)


@pytest.mark.parametrize("key_state", sorted(KEY_STATES))
def test_planning_is_byte_identical_when_handoff_is_unavailable(modules, monkeypatch, key_state):
    golden = _load_golden()
    captured = _capture_planning(monkeypatch, key_state)
    _assert_planning_matches(golden, captured, key_state)
    for name in VARIANTS:
        if key_state == "on" and name in CHANGED_WHEN_ON:
            continue
        resolution = captured[name]["resolution"]["value"]
        if HANDOFF_CAPABILITY in resolution["capability_ids"] or HANDOFF_CAPABILITY in resolution["unavailable"]:
            raise AssertionError(f"{name}: {HANDOFF_CAPABILITY} must be neither offered nor reported")


@pytest.mark.parametrize("key_state", sorted(KEY_STATES))
def test_proposal_and_run_link_routes_are_byte_identical(modules, monkeypatch, key_state):
    golden = _load_golden()
    captured = _capture_routes(monkeypatch, modules, key_state)
    _assert_same(golden["routes"], captured, f"routes with the hand-off setting {key_state}")


class _Patch:
    """``monkeypatch.setattr`` for writing the golden outside pytest."""

    def __init__(self):
        self.undo = []

    def setattr(self, target, name, value, raising=True):
        previous = getattr(target, name, _MISSING)
        if previous is _MISSING and raising:
            raise AttributeError(f"{target!r} has no attribute {name!r}")
        self.undo.append((target, name, previous))
        setattr(target, name, value)

    def restore(self):
        for target, name, value in reversed(self.undo):
            if value is _MISSING:
                delattr(target, name)
            else:
                setattr(target, name, value)
        self.undo.clear()


def _write_golden():
    from test_support.offline_bootstrap import offline_app_imports

    with offline_app_imports() as environment:
        # Same import order as the shared ``modules`` fixture, which avoids a settings cycle.
        ns = SimpleNamespace(
            route=importlib.import_module("route_backend_orchestration"),
            auth=importlib.import_module("functions_authentication"),
            config=importlib.import_module("config"),
            runs=importlib.import_module("functions_orchestration_runs"),
        )
        patch = _Patch()
        try:
            planning = _capture_planning(patch, "absent")
        finally:
            patch.restore()
        patch = _Patch()
        try:
            routes = _capture_routes(patch, ns, "absent")
        finally:
            patch.restore()
        if environment.network_attempts:
            raise AssertionError(f"Network attempts while capturing: {environment.network_attempts}")
    golden = _golden_from(planning, routes)
    _check_no_real_date(golden)
    GOLDEN.write_text(_pretty(golden) + "\n", encoding="utf-8")
    print(f"Wrote {GOLDEN}")


if __name__ == "__main__":
    if "--write-golden" in sys.argv:
        _write_golden()
        sys.exit(0)
    sys.exit(pytest.main([__file__, "-q"]))
