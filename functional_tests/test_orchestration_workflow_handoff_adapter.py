#!/usr/bin/env python3
# test_orchestration_workflow_handoff_adapter.py
"""
Functional test for the chat orchestration workflow_handoff step.
Version: 0.261.250
Implemented in: 0.261.250

This test ensures that the ``workflow_handoff`` step only dry-runs the one-time workflow it
describes, and that:

- the step retains a small card as its ``handoff`` result and keeps the blueprint, the handle map
  entries, the disclosure and the model selection and time zone captured on the server in a
  sidecar on its step record;
- the sidecar never reaches a stream frame, a public step record or the reply, and a later plan
  is never offered the card as a saved result;
- a hand-off that cannot be accepted as planned is still described, with a closed reason;
- the step refuses another user, a legacy plan, a cancelled run and a changed attempt before it
  writes anything, and fails closed without echoing an error;
- a recovered or reused step gets the same sidecar back, with the same id and expiry;
- the reply says nothing runs until the user approves the hand-off card;
- the module never imports Flask, a workflow store or the runtime, and never touches Flask when
  it runs.

Checks use explicit raises, so they hold under ``python -O``.
"""

import ast
import importlib
import json
import logging
import sys
import types
import uuid
from copy import copy, deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_handoff_planner import (
    HANDOFF_CAPABILITY,
    _catalog,
    _context,
    _handles,
    _handoff_step,
    _require,
    _same,
)
from test_orchestration_workflow_run_planning_context import RUN_SETTINGS
from test_orchestration_workflow_runs_off_golden import AGENT_ID, DOCUMENT_ID, GLOBAL_AGENT_ID, OWNER
from test_support.orchestration_harness_execution import (
    HarnessEnvironment,
    compose_step,
    decoded_frames,
    input_binding,
)
from test_support.versioning import assert_app_version_at_least


MINIMUM_VERSION = "0.261.250"
APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
HANDOFFS_MODULE = "functions_orchestration_workflow_handoffs"
ZONE = "America/New_York"
CREATED_AT = datetime(2026, 9, 29, 12, 19, tzinfo=timezone.utc)
LATER = CREATED_AT + timedelta(days=3)
INSTRUCTIONS = "SECRET_HANDOFF_INSTRUCTIONS: review this contract for indemnity terms."
SECRET_DEPLOYMENT = "SECRET-DEPLOYMENT-7A"
MODEL_SELECTION = {"deployment": SECRET_DEPLOYMENT, "source": "chat"}
DOCUMENTS_DISCLOSURE = {
    "kind": "documents", "count": 1, "limit_behavior": "exact", "text": "1 document",
    "scope_count": 0, "scope_names": [],
}
QUERY_DISCLOSURE = {
    "kind": "workspace_query", "limit": 500, "limit_behavior": "best_n",
    "text": "up to 500 best-matching documents", "scope_count": 1, "scope_names": ["Contracts"],
}
OUTCOME = {
    "ok": True, "workflow": {"name": "Review contracts"}, "errors": [],
    "disclosure": DOCUMENTS_DISCLOSURE, "loop_limit": 500,
}
USER_INFO = {"userId": OWNER, "email": "owner@example.com", "roles": ["User"]}
HARNESS_SETTINGS = {
    **RUN_SETTINGS,
    "enable_chat_orchestration_workflows": True,
    "enable_chat_workflow_results": True,
    "enable_chat_orchestration_workflow_handoff": True,
}
SIDECAR_KEYS = [
    "version", "handoff_id", "origin_run_id", "step_id", "conversation_id", "requester_user_id",
    "created_at", "expires_at", "status", "reason", "error_codes", "blueprint", "blueprint_digest",
    "handles", "dry_run", "disclosure", "loop_limit", "model_selection", "time_zone", "summary",
]
CARD_KEYS = ["version", "handoff_id", "name", "summary", "disclosure", "status", "reason", "created_at"]
SERVER_ONLY_KEYS = frozenset({
    "workflow_handoff", "model_selection", "requester_user_id", "blueprint_digest", "loop_limit",
})
EMPTY_HANDLES = {"documents": {}, "scopes": {}, "agents": {}}
WRITERS = (
    "create_personal_handoff_workflow",
    "create_personal_handoff_workflow_from_payload",
    "create_personal_workflow_from_blueprint",
    "create_personal_workflow_from_payload",
)


@pytest.fixture
def ho(modules):
    return importlib.import_module(HANDOFFS_MODULE)


@pytest.fixture
def drafts(modules):
    return importlib.import_module("functions_workflow_drafts")


@pytest.fixture
def executor(modules):
    return importlib.import_module("functions_orchestration_executor")


@pytest.fixture
def ready(modules):
    settings, planning = _context("on")
    return settings, planning, _handles(planning)


def test_version_is_at_least_the_hand_off_step_version():
    assert_app_version_at_least(MINIMUM_VERSION)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _Service:
    """The retained-result service the step writes through, recording each authorization and write."""

    def __init__(self, fail=None, value=None, read_error=None):
        self.authorized = []
        self.persisted = []
        self.opened = []
        self.fail = fail
        self.value = value
        self.read_error = read_error
        self.access = SimpleNamespace(authorize_producer=self._authorize)

    def _authorize(self, producer, *, for_write=False):
        self.authorized.append((producer.user_id, for_write))

    def persist_task_result(self, **kwargs):
        if self.fail is not None:
            raise self.fail
        self.persisted.append(kwargs)
        return SimpleNamespace(producer=kwargs["producer"], outputs=tuple(kwargs["outputs"]))

    def open_result(self, ref, *, allow_partial):
        self.opened.append((ref, allow_partial))
        if self.read_error is not None:
            raise self.read_error
        value = deepcopy(self.value)
        return SimpleNamespace(read_value=lambda: value)


def _producer(user_id=OWNER):
    return SimpleNamespace(user_id=user_id, run_id="run-1", step_id="handoff", conversation_id="conversation-1")


def _unit_context(service, planning, *, contract=2, tokens=("guard-1",), time_zone=ZONE):
    producer = _producer()
    issued = list(tokens)

    def guard(_step_id):
        return issued.pop(0) if len(issued) > 1 else issued[0]

    context = SimpleNamespace(
        result_service=service, plan_contract_version=contract, run_id="run-1",
        conversation_id="conversation-1", workflow_planning=planning, time_zone=time_zone,
        user_email="owner@example.com", user_roles=["User"], seeds={}, active_group_ids=[],
        result_producer=lambda _step: producer,
        result_guard_token_for_step=guard,
        result_input_fingerprint_for_step=lambda _step_id: "fingerprint-1",
    )
    return context, producer


def _install(monkeypatch, ho, drafts, *, outcome=None, selection=None):
    calls = {"dry_runs": [], "logs": [], "writes": []}

    def dry_run(user_id, blueprint, handles, **kwargs):
        calls["dry_runs"].append({
            "user_id": user_id, "blueprint": deepcopy(blueprint), "handles": deepcopy(handles), **deepcopy(kwargs),
        })
        if isinstance(outcome, BaseException):
            raise outcome
        return deepcopy(OUTCOME if outcome is None else outcome)

    def model_selection(seeds, group_ids):
        if isinstance(selection, BaseException):
            raise selection
        return deepcopy(MODEL_SELECTION if selection is None else selection)

    def log(message, *args, **kwargs):
        calls["logs"].append({
            "message": message, "extra": deepcopy(kwargs.get("extra")), "level": kwargs.get("level"),
        })

    monkeypatch.setattr(drafts, "dry_run_handoff_workflow", dry_run)
    for name in WRITERS:
        monkeypatch.setattr(drafts, name, lambda *args, _name=name, **kwargs: calls["writes"].append(_name))
    monkeypatch.setattr(ho, "normalize_model_selection", model_selection)
    monkeypatch.setattr(ho, "log_event", log)
    monkeypatch.setattr(ho, "require_result_service", lambda context: context.result_service)
    monkeypatch.setattr(ho, "build_step_result", lambda **kwargs: dict(kwargs))
    monkeypatch.setattr(ho, "_now", lambda: CREATED_AT)
    return calls


def _tasks(runner=None):
    tasks = [
        {"title": "Review one", "instructions": INSTRUCTIONS},
        {"title": "Report", "instructions": "Write the report."},
    ]
    if runner is not None:
        tasks[0]["runner"] = deepcopy(runner)
    return tasks


def _documents_step(handles, runner=None):
    return _handoff_step({"source": "documents", "documents": handles["documents"]}, tasks=_tasks(runner))


def _build(ho, step, context, producer, settings, created_at=CREATED_AT):
    return ho.build_workflow_handoff(
        step, context, settings=settings, user_id=OWNER, producer=producer, created_at=created_at,
    )


def _expected_id():
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, "urn:simplechat:workflow-handoffs")
    return str(uuid.uuid5(namespace, "run-1:handoff"))


def _marker_handles(planning, kind, names):
    entries = planning["workflow_handoff"]["handles"][kind]
    return {name: deepcopy(entries[name]) for name in names}


def _real_ids(sidecar):
    """The real document and agent ids behind the sidecar's handles."""
    return [
        entry.get(field) for mapping in sidecar["handles"].values() for entry in mapping.values()
        for field in ("document_id", "id")
        if isinstance(entry, dict) and isinstance(entry.get(field), str)
    ]


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _keys(item)


def _assert_nothing_disclosed(surfaces, sidecar):
    secrets = [
        sidecar["handoff_id"], INSTRUCTIONS, SECRET_DEPLOYMENT, DOCUMENT_ID, AGENT_ID, GLOBAL_AGENT_ID,
        *_real_ids(sidecar),
    ]
    for index, surface in enumerate(surfaces):
        text = json.dumps(surface, default=str)
        for secret in secrets:
            _require(secret not in text, f"Surface {index} discloses a server-only value.")
        found = SERVER_ONLY_KEYS & set(_keys(surface))
        _require(not found, f"Surface {index} discloses server-only fields {sorted(found)}.")


def _log_text(calls):
    return json.dumps(calls["logs"], default=str)


def _assert_logs_clean(calls, sidecar=None):
    text = _log_text(calls)
    secrets = [INSTRUCTIONS, SECRET_DEPLOYMENT, DOCUMENT_ID, AGENT_ID, GLOBAL_AGENT_ID, "Review contracts"]
    if sidecar is not None:
        secrets.extend(_real_ids(sidecar))
    for secret in secrets:
        _require(secret not in text, "A log carries user text or a real id.")


def _messages(calls, level=None):
    return [entry["message"] for entry in calls["logs"] if level is None or entry["level"] == level]


# ---------------------------------------------------------------------------
# Describing a hand-off
# ---------------------------------------------------------------------------

def test_a_ready_hand_off_is_dry_run_once_and_described_for_the_server_and_the_card(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    calls = _install(monkeypatch, ho, drafts)
    service = _Service()
    context, producer = _unit_context(service, planning)

    sidecar, card = _build(ho, _documents_step(handles), context, producer, settings)

    handoff_id = _expected_id()
    _same(ho.workflow_handoff_id("run-1", "handoff"), handoff_id, "hand-off id")
    _same(list(sidecar), SIDECAR_KEYS, "sidecar fields")
    _same(list(card), CARD_KEYS, "card fields")
    expected_handles = {**EMPTY_HANDLES, "documents": _marker_handles(planning, "documents", handles["documents"])}
    _require(DOCUMENT_ID in json.dumps(expected_handles), "The offered handle map must hold the real document id.")
    _same(
        {key: sidecar[key] for key in SIDECAR_KEYS if key not in ("blueprint", "blueprint_digest", "summary")},
        {
            "version": 1, "handoff_id": handoff_id, "origin_run_id": "run-1", "step_id": "handoff",
            "conversation_id": "conversation-1", "requester_user_id": OWNER,
            "created_at": ho._iso(CREATED_AT), "expires_at": ho._iso(CREATED_AT + timedelta(days=14)),
            "status": "ready", "reason": None, "error_codes": [], "handles": expected_handles,
            "dry_run": {"ok": True, "error_codes": []}, "disclosure": DOCUMENTS_DISCLOSURE, "loop_limit": 500,
            "model_selection": MODEL_SELECTION, "time_zone": ZONE,
        },
        "sidecar",
    )
    _same(sidecar["blueprint"]["tasks"][0]["instructions"], INSTRUCTIONS, "stored instructions")
    _same(sidecar["blueprint_digest"], ho.canonical_digest(sidecar["blueprint"]), "blueprint digest")
    summary = sidecar["summary"]
    _same(
        {key: summary[key] for key in ("name", "tasks", "alerts", "durable", "one_time")},
        {
            "name": "Review contracts",
            "tasks": [
                {"title": "Review one", "runner": "model", "agent_name": ""},
                {"title": "Report", "runner": "model", "agent_name": ""},
            ],
            "alerts": {"mode": "every_run", "severity": "info"}, "durable": True, "one_time": True,
        },
        "summary",
    )
    _require(isinstance(summary["description"], str), "The summary description must be text.")
    _same(
        card,
        {
            "version": 1, "handoff_id": handoff_id, "name": "Review contracts", "summary": summary,
            "disclosure": DOCUMENTS_DISCLOSURE, "status": "ready", "reason": None,
            "created_at": ho._iso(CREATED_AT),
        },
        "card",
    )
    card_text = json.dumps(card)
    for secret in (INSTRUCTIONS, SECRET_DEPLOYMENT, DOCUMENT_ID, "model_selection", "fingerprint-1"):
        _require(secret not in card_text, "The card carries a server-only value.")

    _same(len(calls["dry_runs"]), 1, "dry runs")
    call = calls["dry_runs"][0]
    _same(call["user_id"], OWNER, "dry-run user")
    _same(call["blueprint"], sidecar["blueprint"], "dry-run blueprint")
    _same(call["handles"], expected_handles, "dry-run handles")
    _same(
        call["origin"],
        {
            "source": "orchestration", "conversation_id": "conversation-1", "orchestration_run_id": "run-1",
            "proposal_id": handoff_id, "created_at": ho._iso(CREATED_AT), "edited": False,
        },
        "dry-run origin",
    )
    _same(call["user_info"], USER_INFO, "dry-run user info")
    _same(call["settings"], settings, "dry-run settings")
    _require("enabled" not in call, "A dry run never chooses whether the workflow is enabled.")
    _same((calls["writes"], service.authorized, service.persisted), ([], [], []), "writes")
    _assert_logs_clean(calls, sidecar)


def test_a_workspace_query_hand_off_names_its_scopes_and_discloses_its_bound(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    _require(handles["scopes"], "The planning context must offer a workspace scope.")
    calls = _install(monkeypatch, ho, drafts, outcome={**OUTCOME, "disclosure": QUERY_DISCLOSURE})
    context, producer = _unit_context(_Service(), planning)
    loop = {"source": "workspace_query", "scopes": handles["scopes"], "selection": "all_matches", "content": "indemnity"}

    sidecar, card = _build(ho, _handoff_step(loop, tasks=_tasks()), context, producer, settings)

    _same(sidecar["status"], "ready", "status")
    _same(sidecar["handles"], {**EMPTY_HANDLES, "scopes": _marker_handles(planning, "scopes", handles["scopes"])},
          "handles")
    _same(sidecar["disclosure"], QUERY_DISCLOSURE, "sidecar disclosure")
    _same(card["disclosure"], QUERY_DISCLOSURE, "card disclosure")
    _same(calls["dry_runs"][0]["handles"], sidecar["handles"], "dry-run handles")


def test_the_time_zone_comes_from_the_run_then_the_hand_off_then_the_planning_context(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    _install(monkeypatch, ho, drafts)
    both = deepcopy(planning)
    both["workflow_handoff"]["time_zone"] = "Europe/Paris"
    both["time_zone"] = "Asia/Tokyo"
    planning_only = deepcopy(both)
    planning_only["workflow_handoff"].pop("time_zone")
    neither = deepcopy(planning_only)
    neither.pop("time_zone")
    cases = (
        (ZONE, both, ZONE),
        (None, both, "Europe/Paris"),
        (None, planning_only, "Asia/Tokyo"),
        (None, neither, ho.WORKFLOW_DEFAULT_TIME_ZONE),
    )
    for run_zone, context_planning, expected in cases:
        context, producer = _unit_context(_Service(), context_planning, time_zone=run_zone)
        sidecar, _card = _build(ho, _documents_step(handles), context, producer, settings)
        _same(sidecar["time_zone"], expected, f"time zone for {run_zone!r}")


def test_a_hand_off_without_its_planning_context_is_described_as_unavailable(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    calls = _install(monkeypatch, ho, drafts)
    shared = {**deepcopy(planning), "conversation_private": False}
    unmarked = deepcopy(planning)
    unmarked.pop("workflow_handoff")
    not_ready = deepcopy(planning)
    not_ready["workflow_handoff"]["ready"] = False
    step = _documents_step(handles)
    for label, context_planning in (("none", None), ("shared", shared), ("unmarked", unmarked), ("not ready", not_ready)):
        context, producer = _unit_context(_Service(), context_planning)
        sidecar, card = _build(ho, step, context, producer, settings)
        _same(
            {key: sidecar[key] for key in ("status", "reason", "error_codes", "handles", "dry_run", "disclosure",
                                           "loop_limit")},
            {
                "status": "unavailable", "reason": "workflow_context_unavailable", "error_codes": [],
                "handles": EMPTY_HANDLES, "dry_run": {"ok": False, "error_codes": []}, "disclosure": None,
                "loop_limit": None,
            },
            f"sidecar ({label})",
        )
        _same(sidecar["blueprint"], step["arguments"]["blueprint"], f"stored blueprint ({label})")
        _same((card["status"], card["reason"], card["disclosure"]), ("unavailable", "workflow_context_unavailable", None),
              f"card ({label})")
    _same(calls["dry_runs"], [], "dry runs")


def test_a_hosted_agent_makes_the_hand_off_invalid_and_a_local_agent_is_named_on_the_card(
    ho, drafts, ready, monkeypatch,
):
    settings, planning, handles = ready
    _require(handles["hosted_agents"] and handles["local_agents"], "The context must offer both kinds of agent.")
    calls = _install(monkeypatch, ho, drafts)
    context, producer = _unit_context(_Service(), planning)

    hosted = {"type": "agent", "agent_ref": handles["hosted_agents"][0]}
    sidecar, card = _build(ho, _documents_step(handles, hosted), context, producer, settings)
    _same(
        (sidecar["status"], sidecar["reason"], sidecar["error_codes"], sidecar["handles"], sidecar["dry_run"]),
        ("invalid", "handoff_agent_unsupported", ["handoff_agent_unsupported"], EMPTY_HANDLES,
         {"ok": False, "error_codes": []}),
        "hosted agent",
    )
    _same((card["status"], card["disclosure"]), ("invalid", None), "hosted card")
    _same(calls["dry_runs"], [], "dry runs for a hosted agent")

    local = handles["local_agents"][0]
    sidecar, card = _build(ho, _documents_step(handles, {"type": "agent", "agent_ref": local}), context, producer,
                           settings)
    name = next(entry["name"] for entry in _catalog(planning)["agents"] if entry["handle"] == local)
    _same(sidecar["status"], "ready", "local agent status")
    _same(sidecar["summary"]["tasks"][0], {"title": "Review one", "runner": "agent", "agent_name": name},
          "local agent task")
    _same(sidecar["handles"]["agents"], _marker_handles(planning, "agents", [local]), "agent handles")
    _require(GLOBAL_AGENT_ID in json.dumps(sidecar["handles"]), "The sidecar must hold the local agent's real id.")
    _require(GLOBAL_AGENT_ID not in json.dumps(card), "The card never holds an agent id.")
    _same(len(calls["dry_runs"]), 1, "dry runs for a local agent")


def test_an_unknown_handle_leaves_the_sources_unavailable_without_a_dry_run(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    calls = _install(monkeypatch, ho, drafts)
    context, producer = _unit_context(_Service(), planning)
    step = _handoff_step({"source": "documents", "documents": ["zz-not-offered"]}, tasks=_tasks())

    sidecar, _card = _build(ho, step, context, producer, settings)

    _same((sidecar["status"], sidecar["reason"]), ("unavailable", "handoff_sources_unavailable"), "status")
    _require("reference_unknown" in sidecar["error_codes"], "The unknown handle must be reported by code.")
    _same(calls["dry_runs"], [], "dry runs")


def test_each_dry_run_outcome_maps_to_a_closed_reason(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    cases = (
        ({"ok": False, "errors": []}, "invalid", "workflow_handoff_invalid", ["blueprint_invalid"]),
        (
            {"ok": False, "errors": [{"code": "scope_unavailable", "message": INSTRUCTIONS},
                                     {"code": "reference_unauthorized"}]},
            "unavailable", "handoff_sources_unavailable", ["reference_unauthorized", "scope_unavailable"],
        ),
        ({"ok": False, "errors": [{"code": "handoff_limit_changed"}]}, "invalid", "handoff_loop_limit",
         ["handoff_limit_changed"]),
        ({"ok": False, "errors": [{"code": "workflows_unavailable"}]}, "unavailable", "handoff_unavailable",
         ["workflows_unavailable"]),
    )
    for outcome, status, reason, codes in cases:
        calls = _install(monkeypatch, ho, drafts, outcome=outcome)
        context, producer = _unit_context(_Service(), planning)
        sidecar, card = _build(ho, _documents_step(handles), context, producer, settings)
        _same(
            {key: sidecar[key] for key in ("status", "reason", "error_codes", "dry_run", "disclosure", "loop_limit")},
            {"status": status, "reason": reason, "error_codes": codes, "dry_run": {"ok": False, "error_codes": codes},
             "disclosure": None, "loop_limit": None},
            f"outcome {codes}",
        )
        _same((card["status"], card["reason"], card["disclosure"]), (status, reason, None), f"card {codes}")
        _require(INSTRUCTIONS not in json.dumps(card), "The card never repeats a dry-run message.")
        _same(len(calls["dry_runs"]), 1, f"dry runs for {codes}")


def test_a_dry_run_that_raises_is_described_as_unavailable_without_its_error(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    for error, reason, message in (
        (drafts.WorkflowLoopLimitError(SECRET_DEPLOYMENT), "handoff_unavailable",
         "Hand-off loop limit is misconfigured; handing work off is unavailable."),
        (RuntimeError(SECRET_DEPLOYMENT), "handoff_prepare_failed", "A workflow hand-off could not be dry-run."),
    ):
        calls = _install(monkeypatch, ho, drafts, outcome=error)
        context, producer = _unit_context(_Service(), planning)
        sidecar, card = _build(ho, _documents_step(handles), context, producer, settings)
        _same(
            {key: sidecar[key] for key in ("status", "reason", "error_codes", "dry_run", "disclosure", "loop_limit")},
            {"status": "unavailable", "reason": reason, "error_codes": [], "dry_run": {"ok": False, "error_codes": []},
             "disclosure": None, "loop_limit": None},
            f"sidecar for {type(error).__name__}",
        )
        _same(card["status"], "unavailable", "card status")
        _require(any(message in text for text in _messages(calls, logging.WARNING)), f"The {message!r} log is missing.")
        _assert_logs_clean(calls, sidecar)


def test_a_model_selection_that_cannot_be_captured_leaves_the_default_model(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    calls = _install(monkeypatch, ho, drafts, selection=RuntimeError(SECRET_DEPLOYMENT))
    context, producer = _unit_context(_Service(), planning)

    sidecar, _card = _build(ho, _documents_step(handles), context, producer, settings)

    _same((sidecar["status"], sidecar["model_selection"]), ("ready", None), "sidecar")
    _require(
        any("model selection could not be captured" in text for text in _messages(calls, logging.WARNING)),
        "The model selection failure must be logged.",
    )
    _assert_logs_clean(calls, sidecar)


# ---------------------------------------------------------------------------
# The step
# ---------------------------------------------------------------------------

def test_the_step_retains_only_the_card_and_returns_the_sidecar_to_the_executor(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    calls = _install(monkeypatch, ho, drafts)
    service = _Service()
    context, producer = _unit_context(service, planning)

    result = ho.adapter_workflow_handoff(_documents_step(handles), context, settings=settings, user_id=OWNER)

    _same(result["status"], ho.STEP_STATUS_COMPLETED, "status")
    _same(result["summary"], "Prepared a one-time workflow hand-off for your approval.", "summary")
    sidecar = result["workflow_handoff"]
    _same(sidecar["status"], "ready", "sidecar status")
    _same(service.authorized, [(OWNER, True), (OWNER, True)], "authorizations")
    _same(len(service.persisted), 1, "writes")
    persisted = service.persisted[0]
    _require(persisted["producer"] is producer, "The step writes as its own producer.")
    _same(
        {key: persisted[key] for key in ("role", "status", "sources", "origin", "guard_token", "upstream",
                                         "input_fingerprint")},
        {"role": "reason", "status": "complete", "sources": [], "origin": "generated", "guard_token": "guard-1",
         "upstream": (), "input_fingerprint": "fingerprint-1"},
        "write",
    )
    _same(len(persisted["outputs"]), 1, "outputs")
    output = persisted["outputs"][0]
    _same((output.name, output.kind), ("handoff", "structured-v1"), "output")
    _same(output.completeness.checks, ("workflow_handoff_dry_run",), "output checks")
    _same(output.value, {
        "version": 1, "handoff_id": sidecar["handoff_id"], "name": "Review contracts",
        "summary": sidecar["summary"], "disclosure": DOCUMENTS_DISCLOSURE, "status": "ready", "reason": None,
        "created_at": ho._iso(CREATED_AT),
    }, "retained card")
    _require(result["task_result"].producer is producer, "The step result carries the retained task.")
    _same(calls["writes"], [], "workflow writes")
    _require("Prepared a workflow hand-off." in " ".join(_messages(calls, logging.INFO)), "The step must log.")
    _assert_logs_clean(calls, sidecar)

    calls = _install(monkeypatch, ho, drafts, outcome={"ok": False, "errors": [{"code": "scope_unavailable"}]})
    unavailable = ho.adapter_workflow_handoff(
        _documents_step(handles), _unit_context(_Service(), planning)[0], settings=settings, user_id=OWNER,
    )
    _same(unavailable["status"], ho.STEP_STATUS_COMPLETED, "an unavailable hand-off still completes")
    _same(unavailable["summary"], "Prepared a one-time workflow hand-off that cannot be handed off as planned.",
          "unavailable summary")


def test_the_step_refuses_another_user_or_a_legacy_plan_before_it_touches_anything(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    calls = _install(monkeypatch, ho, drafts)
    for user_id, contract in (("intruder", 2), (OWNER, 1)):
        service = _Service()
        context, _unused = _unit_context(service, planning, contract=contract)
        with pytest.raises(ho.ResultUnavailableError):
            ho.adapter_workflow_handoff(_documents_step(handles), context, settings=settings, user_id=user_id)
        _same((service.authorized, service.persisted), ([], []), f"service for {user_id}/{contract}")
    _same((calls["dry_runs"], calls["writes"]), ([], []), "dry runs and writes")


def test_a_cancelled_run_stops_the_step_before_it_writes(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    calls = _install(monkeypatch, ho, drafts)
    service = _Service()
    context, _unused = _unit_context(service, planning)
    with pytest.raises(ho.MixedSourceCancellationError):
        ho.adapter_workflow_handoff(
            _documents_step(handles), context, settings=settings, user_id=OWNER, cancel_requested=lambda: True,
        )
    _same((service.authorized, service.persisted, calls["dry_runs"]), ([], [], []), "cancelled before")

    flags = iter((False, True))
    service = _Service()
    context, _unused = _unit_context(service, planning)
    with pytest.raises(ho.MixedSourceCancellationError):
        ho.adapter_workflow_handoff(
            _documents_step(handles), context, settings=settings, user_id=OWNER,
            cancel_requested=lambda: next(flags),
        )
    _same((service.authorized, service.persisted, len(calls["dry_runs"])), ([(OWNER, True)], [], 1),
          "cancelled during")


def test_a_changed_attempt_or_a_failed_write_fails_closed_without_the_error(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    cases = (
        ("changed attempt", {"tokens": ("guard-1", "guard-1", "guard-2")}, None, "result_unavailable"),
        ("failed write", {}, RuntimeError(SECRET_DEPLOYMENT), "step_failed"),
        ("invalid write", {}, ho.ResultContractError(SECRET_DEPLOYMENT), "result_invalid"),
    )
    for label, context_fields, failure, code in cases:
        calls = _install(monkeypatch, ho, drafts)
        service = _Service(fail=failure)
        context, _unused = _unit_context(service, planning, **context_fields)
        result = ho.adapter_workflow_handoff(_documents_step(handles), context, settings=settings, user_id=OWNER)
        _same(result["status"], ho.STEP_STATUS_FAILED, f"{label} status")
        _same(result["failure"]["code"], code, f"{label} code")
        _same((result["summary"], result["error"]), (result["failure"]["message"],) * 2, f"{label} message")
        _require("workflow_handoff" not in result, f"A failed step never carries a sidecar ({label}).")
        _require(SECRET_DEPLOYMENT not in json.dumps(result, default=str), f"The {label} echoes its error.")
        _same(service.persisted, [], f"{label} writes")
        warnings = [entry for entry in calls["logs"] if entry["level"] == logging.WARNING]
        _require(
            any("A workflow hand-off could not be prepared." in entry["message"]
                and entry["extra"].get("failure_code") == code for entry in warnings),
            f"The {label} must be logged by code.",
        )
        _assert_logs_clean(calls)


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------

def _task(producer):
    return SimpleNamespace(producer=producer, output=lambda name: f"ref:{name}")


def test_a_recovered_hand_off_keeps_its_id_and_creation_time(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    _install(monkeypatch, ho, drafts)
    step = _documents_step(handles)
    context, producer = _unit_context(_Service(), planning)
    original, card = _build(ho, step, context, producer, settings)

    monkeypatch.setattr(ho, "_now", lambda: LATER)
    service = _Service(value=card)
    context, _unused = _unit_context(service, planning)
    rebuilt = ho.rebuild_workflow_handoff(step, context, settings=settings, user_id=OWNER, task=_task(producer))
    _same(rebuilt, original, "rebuilt sidecar")
    _same(service.opened, [("ref:handoff", False)], "read")
    _same(service.persisted, [], "writes")


def test_a_recovered_hand_off_whose_card_cannot_be_read_is_unavailable(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    step = _documents_step(handles)
    for label, service in (
        ("read error", _Service(read_error=RuntimeError(SECRET_DEPLOYMENT))),
        ("bad time", _Service(value={"created_at": "not-a-time"})),
        ("not a card", _Service(value="text")),
    ):
        calls = _install(monkeypatch, ho, drafts)
        context, producer = _unit_context(service, planning)
        rebuilt = ho.rebuild_workflow_handoff(step, context, settings=settings, user_id=OWNER, task=_task(producer))
        _same(
            {key: rebuilt[key] for key in ("handoff_id", "status", "reason", "created_at", "expires_at")},
            {"handoff_id": _expected_id(), "status": "unavailable", "reason": "handoff_prepare_failed",
             "created_at": None, "expires_at": None},
            label,
        )
        _assert_logs_clean(calls)

    calls = _install(monkeypatch, ho, drafts)
    context, producer = _unit_context(_Service(read_error=RuntimeError(SECRET_DEPLOYMENT)), planning)
    ho.rebuild_workflow_handoff(step, context, settings=settings, user_id=OWNER, task=_task(producer))
    _require(
        "A recovered workflow hand-off could not be read." in " ".join(_messages(calls, logging.WARNING)),
        "An unreadable card must be logged.",
    )

    calls = _install(monkeypatch, ho, drafts)
    broken = ho.rebuild_workflow_handoff(step, context, settings=settings, user_id=OWNER, task=object())
    _same(broken, None, "a task without a producer")
    _require(
        "A recovered workflow hand-off could not be described." in " ".join(_messages(calls, logging.WARNING)),
        "An undescribable hand-off must be logged.",
    )


def test_the_executor_restores_a_sidecar_only_for_a_completed_hand_off_without_one(ho, executor, monkeypatch):
    rebuilt = {"handoff_id": "rebuilt"}
    calls, logs = [], []
    outcome = {"value": rebuilt}

    def rebuild(step, context, *, settings, user_id, task):
        calls.append((step["step_id"], settings, user_id, task))
        if isinstance(outcome["value"], BaseException):
            raise outcome["value"]
        return deepcopy(outcome["value"])

    monkeypatch.setattr(ho, "rebuild_workflow_handoff", rebuild)
    monkeypatch.setattr(executor, "log_event", lambda message, *args, **kwargs: logs.append((message, kwargs)))
    step = {"step_id": "handoff", "capability_id": HANDOFF_CAPABILITY, "role": "reason"}
    context = SimpleNamespace(run_id="run-1", conversation_id="conversation-1")
    task = object()
    completed = {"status": executor.STEP_STATUS_COMPLETED, "task_result": task}
    unchanged = (
        ({**step, "capability_id": "workflow_propose"}, executor.STEP_STATUS_COMPLETED, completed),
        (step, executor.STEP_STATUS_FAILED, completed),
        (step, executor.STEP_STATUS_COMPLETED, {**completed, "task_result": None}),
        (step, executor.STEP_STATUS_COMPLETED, {**completed, "workflow_handoff": {"handoff_id": "kept"}}),
        (step, executor.STEP_STATUS_COMPLETED, None),
    )
    for index, (case_step, status, result) in enumerate(unchanged):
        returned = executor._restore_workflow_handoff(case_step, context, status, result, settings={}, user_id=OWNER)
        _require(returned is result, f"Case {index} must be returned unchanged.")
    _same(calls, [], "rebuilds for unchanged cases")

    restored = executor._restore_workflow_handoff(
        step, context, executor.STEP_STATUS_COMPLETED, completed, settings={"a": 1}, user_id=OWNER,
    )
    _same(restored, {**completed, "workflow_handoff": rebuilt}, "restored")
    _require("workflow_handoff" not in completed, "The original result must not change.")
    _same(calls, [("handoff", {"a": 1}, OWNER, task)], "rebuild call")

    for value in (None, RuntimeError(SECRET_DEPLOYMENT)):
        outcome["value"] = value
        returned = executor._restore_workflow_handoff(
            step, context, executor.STEP_STATUS_COMPLETED, completed, settings={}, user_id=OWNER,
        )
        _require(returned is completed, f"A rebuild returning {type(value).__name__} leaves the result unchanged.")
    _same(len(logs), 1, "restore failure logs")
    _require("hand-off could not be described" in logs[0][0], "The restore failure must be logged.")
    _require(SECRET_DEPLOYMENT not in json.dumps(logs, default=str), "The restore log echoes its error.")


def test_the_step_record_keeps_the_sidecar_and_the_public_record_drops_it(ho, drafts, executor, ready, monkeypatch):
    runs = importlib.import_module("functions_orchestration_runs")
    settings, planning, handles = ready
    _install(monkeypatch, ho, drafts)
    context, producer = _unit_context(_Service(), planning)
    sidecar, _card = _build(ho, _documents_step(handles), context, producer, settings)
    step = {"step_id": "handoff", "capability_id": HANDOFF_CAPABILITY, "role": "reason", "title": "Hand off"}
    result = {"status": "completed", "summary": "Prepared.", "workflow_handoff": sidecar}

    record = executor._step_record(context, step, 0, "completed", result, "t0", "t1", 5)
    _same(record["workflow_handoff"], sidecar, "record sidecar")
    _require(record["workflow_handoff"] is not sidecar, "The record holds its own copy.")

    other = executor._step_record(context, {**step, "capability_id": "compose"}, 0, "completed", result, "t0", "t1", 5)
    _require("workflow_handoff" not in other, "Another capability never stores a hand-off sidecar.")
    text_only = executor._step_record(
        context, step, 0, "completed", {**result, "workflow_handoff": "text"}, "t0", "t1", 5,
    )
    _require("workflow_handoff" not in text_only, "Only a sidecar object is stored.")

    public = runs.public_step_record(record)
    _assert_nothing_disclosed([public], sidecar)


# ---------------------------------------------------------------------------
# The reply's note
# ---------------------------------------------------------------------------

def test_the_reply_notes_a_ready_hand_off_and_says_why_another_was_not_handed_off(ho):
    def plan(**fields):
        return {"steps": [{"step_id": "handoff", "capability_id": HANDOFF_CAPABILITY, **fields}]}

    def record(**fields):
        return [{"step_id": "handoff", "capability_id": HANDOFF_CAPABILITY, "status": "completed", **fields}]

    not_handed_off = ho.NO_WORKFLOW_HANDED_OFF
    cases = (
        (plan(), record(workflow_handoff={"status": "ready"}), ho.WORKFLOW_HANDOFF_NOTE),
        (plan(), record(workflow_handoff={"status": "invalid", "reason": "handoff_agent_unsupported"}),
         f"{not_handed_off} {ho.workflow_handoff_reason_text('handoff_agent_unsupported')}"),
        (plan(), record(), f"{not_handed_off} {ho.workflow_handoff_reason_text('handoff_prepare_failed')}"),
        (plan(), record(workflow_handoff={"status": "other"}),
         f"{not_handed_off} {ho.workflow_handoff_reason_text('handoff_prepare_failed')}"),
        (plan(), record(status="failed", workflow_handoff={"status": "ready"}), ""),
        (plan(enabled=False), record(workflow_handoff={"status": "ready"}), ""),
        (plan(), [], ""),
        ({"steps": [{"step_id": "propose", "capability_id": "workflow_propose"}]},
         [{"step_id": "propose", "capability_id": "workflow_propose", "status": "completed"}], ""),
        ({"steps": [{"step_id": "run", "capability_id": "workflow_run"}]},
         [{"step_id": "run", "capability_id": "workflow_run", "status": "completed",
           "workflow_handoff": {"status": "ready"}}], ""),
        ({"steps": [], "workflow_handoff_notes": [{"reason": "handoff_loop_limit"}] * 2}, [],
         f"{not_handed_off} {ho.workflow_handoff_reason_text('handoff_loop_limit')}"),
        (None, None, ""),
    )
    for index, (case_plan, records, expected) in enumerate(cases):
        _same(ho.workflow_handoff_note(case_plan, records), expected, f"note {index}")
    for text in ho.WORKFLOW_HANDOFF_REASON_TEXT.values():
        _require("{" not in text and "#" not in text, "Reason text never carries a placeholder or a handle.")


# ---------------------------------------------------------------------------
# Hygiene
# ---------------------------------------------------------------------------

def _imports(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    modules_seen, names = set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules_seen.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules_seen.add(node.module or "")
            names.setdefault(node.module, set()).update(alias.name for alias in node.names)
    return modules_seen, names


def test_the_module_imports_no_flask_store_or_runtime():
    path = APP_ROOT / f"{HANDOFFS_MODULE}.py"
    seen, names = _imports(path)
    forbidden = ("flask", "werkzeug", "azure", "functions_workflows", "functions_personal", "functions_workflow_runtime",
                 "functions_workflow_runner", "functions_workflow_definition_store", "route_")
    found = sorted(module for module in seen if module.startswith(forbidden))
    _same(found, [], "forbidden imports")
    _same(
        names.get("functions_workflow_drafts"),
        {"draft_error", "check_handoff_blueprint", "validate_handoff_blueprint", "BLUEPRINT_TASK_TITLE_MAX_LENGTH",
         "WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION", "WorkflowLoopLimitError", "dry_run_handoff_workflow"},
        "draft service names",
    )
    _same(names.get("functions_workflow_handoff_builder"),
          {"HANDOFF_HANDLE_KINDS", "handoff_handle_uses", "HANDOFF_ALERTS"}, "builder names")
    source = path.read_text(encoding="utf-8")
    for text in ("create_personal", "cosmos_", "queue_durable"):
        _require(text not in source, f"The module must not use {text!r}.")
    flask_names = sorted({
        node.id for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name) and node.id in ("request", "session", "current_app", "g")
    })
    _same(flask_names, [], "Flask request globals")


def test_the_step_never_touches_flask_when_it_runs(ho, drafts, ready, monkeypatch):
    settings, planning, handles = ready
    _install(monkeypatch, ho, drafts)
    touched = []

    class _Forbidden(types.ModuleType):
        def __getattr__(self, name):
            touched.append(name)
            raise AssertionError(f"flask.{name} was touched")

    monkeypatch.setitem(sys.modules, "flask", _Forbidden("flask"))
    service = _Service()
    context, _unused = _unit_context(service, planning)
    result = ho.adapter_workflow_handoff(_documents_step(handles), context, settings=settings, user_id=OWNER)
    _same(touched, [], "flask names touched")
    _same(result["status"], ho.STEP_STATUS_COMPLETED, "status")
    _same(len(service.persisted), 1, "writes")


# ---------------------------------------------------------------------------
# Running the step in a plan
# ---------------------------------------------------------------------------

def _harness(monkeypatch, planning, steps, replies):
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(HARNESS_SETTINGS)
    drafts = importlib.import_module("functions_workflow_drafts")
    ho = importlib.import_module(HANDOFFS_MODULE)
    dry_runs, writes = [], []

    def dry_run(user_id, blueprint, handles, **kwargs):
        dry_runs.append({"user_id": user_id, "blueprint": deepcopy(blueprint), **deepcopy(kwargs)})
        return deepcopy(OUTCOME)

    monkeypatch.setattr(drafts, "dry_run_handoff_workflow", dry_run)
    for name in WRITERS:
        monkeypatch.setattr(drafts, name, lambda *args, _name=name, **kwargs: writes.append(_name))
    runtime = sys.modules.get("functions_workflow_runtime")
    if runtime is not None:
        monkeypatch.setattr(runtime, "queue_durable_workflow_run",
                            lambda *args, **kwargs: writes.append("queue_durable_workflow_run"))
    monkeypatch.setattr(ho, "normalize_model_selection", lambda seeds, group_ids: deepcopy(MODEL_SELECTION))
    real_normalize = env.schema.normalize_plan

    def normalize(raw, *args, **kwargs):
        # The harness offers only its own capabilities and plans without a planning context.
        capability_ids = kwargs.get("available_capability_ids")
        if capability_ids is not None and HANDOFF_CAPABILITY not in capability_ids:
            kwargs["available_capability_ids"] = [*capability_ids, HANDOFF_CAPABILITY]
        kwargs.setdefault("workflow_planning", planning)
        return real_normalize(raw, *args, **kwargs)

    monkeypatch.setattr(env.schema, "normalize_plan", normalize)
    env.create(steps, replies=replies, final_response=input_binding("answer"), workflow_planning=planning,
               time_zone=ZONE)
    return env, dry_runs, writes


def _plan_step(plan, step_id):
    return next(step for step in plan["steps"] if step["step_id"] == step_id)


def test_the_step_keeps_its_sidecar_on_the_server_and_retains_only_the_card(modules, monkeypatch):
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    events = importlib.import_module("functions_orchestration_events")
    runs = importlib.import_module("functions_orchestration_runs")
    services = importlib.import_module("functions_orchestration_services")
    ho = importlib.import_module(HANDOFFS_MODULE)
    _settings, planning = _context("on")
    handles = _handles(planning)
    env, dry_runs, writes = _harness(
        monkeypatch, planning, [compose_step("answer"), _documents_step(handles)], ["Your priorities."],
    )
    approval = env.read()["plan"]["approval"]
    _same(approval["mode"], "manual", "approval mode")
    _same(approval.get("floor"), {"mode": "manual", "reason": HANDOFF_CAPABILITY}, "approval floor")

    execution = env.prepare()
    progress = []
    frames = decoded_frames(execution.execute(emit=progress.append))
    streamed = decoded_frames(progress)

    step = env.steps.read_item("run-1:handoff", "run-1")
    sidecar = step["workflow_handoff"]
    _same((step["status"], sidecar["status"]), ("completed", "ready"), "step")
    _same(sidecar["handoff_id"], ho.workflow_handoff_id("run-1", "handoff"), "hand-off id")
    _same((sidecar["model_selection"], sidecar["time_zone"]), (MODEL_SELECTION, ZONE), "captured selections")
    _require(DOCUMENT_ID in _real_ids(sidecar), "The sidecar must hold the real document id.")
    _same(writes, [], "workflow writes")
    _same(len(dry_runs), 1, "dry runs")
    _same(dry_runs[0]["origin"]["orchestration_run_id"], "run-1", "dry-run run")
    _same(dry_runs[0]["origin"]["proposal_id"], sidecar["handoff_id"], "dry-run hand-off id")
    _same(dry_runs[0]["blueprint"]["tasks"][0]["instructions"], INSTRUCTIONS, "dry-run instructions")
    _require("enabled" not in dry_runs[0], "A dry run never chooses whether the workflow is enabled.")

    # The sidecar never leaves the server: not streamed, listed or stored on the message.
    _require(
        any(frame.get("type") == events.EVENT_TYPE_STEP and frame.get("step_id") == "handoff" for frame in streamed),
        "The hand-off step's progress must be streamed.",
    )
    public = runs.list_run_steps("run-1", user_id=OWNER, conversation_id="conversation-1")
    messages = env.assistant_messages()
    _assert_nothing_disclosed((frames, streamed, public, messages), sidecar)
    _require(
        any(ho.WORKFLOW_HANDOFF_NOTE in str(message.get("content") or "") for message in messages),
        "The reply must say nothing runs until the card is approved.",
    )

    run = env.read()
    _same(run["status"], "completed", "run status")
    _same(set(run["task_results"]), {"answer", "handoff"}, "task results")
    task = contracts.TaskResult.from_dict(step["task_result"])
    results = env.services().results
    card = results.open_result(task.output("handoff"), allow_partial=False).read_value()
    _same(card, {
        "version": 1, "handoff_id": sidecar["handoff_id"], "name": "Review contracts", "summary": sidecar["summary"],
        "disclosure": DOCUMENTS_DISCLOSURE, "status": "ready", "reason": None, "created_at": sidecar["created_at"],
    }, "retained card")

    # A later plan is never offered the hand-off card as a saved result.
    found = services.discover_result_aliases([run], results)
    answer = contracts.TaskResult.from_dict(run["task_results"]["answer"])
    expected = sorted(json.dumps(ref.to_dict(), sort_keys=True) for ref in answer.outputs)
    offered = sorted(json.dumps(ref.to_dict(), sort_keys=True) for ref in found["aliases"].values())
    _require(expected and offered == expected, "Only the answer may be offered as a saved result.")

    # A recovered step is described again with the same id, creation time and expiry.
    probe = copy(execution.context)
    probe.result_service = results
    rebuilt = ho.rebuild_workflow_handoff(
        _plan_step(run["plan"], "handoff"), probe, settings=env.settings, user_id=OWNER, task=task,
    )
    _same(rebuilt, sidecar, "rebuilt sidecar")


def test_a_retried_run_reuses_the_hand_off_it_already_prepared(modules, monkeypatch):
    _settings, planning = _context("on")
    handles = _handles(planning)
    env, dry_runs, writes = _harness(
        monkeypatch, planning, [_documents_step(handles), compose_step("answer")], [RuntimeError("FIXTURE_FAILURE")],
    )
    execution = env.prepare()
    try:
        failed = env.run_engine(execution)
    finally:
        execution.close()
    _same(failed["status"], "failed", "first run")
    parent = env.read()
    first = env.steps.read_item("run-1:handoff", "run-1")
    _same((first["status"], first["checkpoint_available"]), ("completed", True), "first hand-off step")

    def authorize():
        return env.bootstrap.read_owned_conversation(OWNER, "conversation-1")

    probe = copy(execution.context)
    probe.result_service = env.services().results
    child = env.recovery.prepare_retry(
        "run-1", OWNER,
        {"conversation_id": "conversation-1", "submission_id": "explicit-user-retry",
         "expected_version": parent["recovery_version"]},
        authorize=authorize, message_container=env.messages,
        validate=lambda current: env.recovery.validate_resume(
            current, probe, env.settings, authorize, source_run_id=current["id"],
        ),
    )
    _require(child["time_zone"] == ZONE and "workflow_planning" in child, "The retry keeps the planning context.")
    _same(child["plan"]["approval"].get("floor"), {"mode": "manual", "reason": HANDOFF_CAPABILITY}, "retry floor")
    services = env.services()
    claimed = env.revisions.claim_plan_run(
        child["id"], OWNER, "conversation-1", expected_version=child["edit_version"],
        result_alias_resolver=lambda current: env.service_bindings.admitted_result_aliases(current, services.results),
    )
    lease = env.recovery.ExecutionLease(claimed, authorize, message_container=env.messages)
    second = env.execution.prepare_harness_execution(claimed, settings=env.settings, lease=lease)
    env.replies.append("Your priorities.")
    try:
        done = env.run_engine(second)
    finally:
        second.close()
    _same(done["status"], "completed", "retried run")
    again = env.steps.read_item(f"{child['id']}:handoff", child["id"])
    _same((again["status"], again["reused_from_run_id"]), ("completed", "run-1"), "reused step")
    _require(again.get("effects_uncertain") is not True, "A hand-off step never has uncertain effects.")
    # The hand-off keeps its id, creation time and expiry, so a card already shown still applies.
    _same(again["workflow_handoff"], first["workflow_handoff"], "reused sidecar")
    _same([call["origin"]["orchestration_run_id"] for call in dry_runs], ["run-1"], "dry runs")
    _same(writes, [], "workflow writes")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
