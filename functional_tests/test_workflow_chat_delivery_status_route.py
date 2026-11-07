#!/usr/bin/env python3
# test_workflow_chat_delivery_status_route.py
"""
Functional test for the workflow chat delivery status route.
Version: 0.261.227
Implemented in: 0.261.227

This test ensures that the workflow-run status payload and Flask route stay owner-scoped, bounded
and safe: queries are single-partition projections, global and conversation modes include exactly
the intended runs, rows expose stable status/action/retry fields without leaking run output or
exception text, live and workflow reads observe their caps, runtime resume versions match the
durable store, and the authenticated route preserves the workflow feature gates and fixed errors.
"""

import ast
import copy
import importlib
import json
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from flask import Blueprint, Flask  # noqa: E402
from werkzeug.test import Client  # noqa: E402
from werkzeug.wrappers import Response  # noqa: E402

import functions_workflow_chat_delivery_status as status  # noqa: E402
from functions_m365_workflow_binding import M365_WAITING_STATES  # noqa: E402
from functions_workflow_alert_safety import sanitize_workflow_alert_record  # noqa: E402
from functions_workflow_chat_delivery import (  # noqa: E402
    DELIVERY_MESSAGE_ID_PREFIX,
    OPEN_STATUSES,
    REASON_DEADLINE_EXCEEDED,
    RUN_DOCUMENT_TERMINAL_STATUSES,
    STATUS_DELIVERED,
    STATUS_READY,
    failure_reason_text,
    format_delivery_timestamp,
)
from functions_workflow_definitions import workflow_definition_for_editor, workflow_definition_revision  # noqa: E402
from functions_workflow_runtime_store import (  # noqa: E402
    WorkflowRuntimeConflict,
    WorkflowRuntimeStore,
    workflow_runtime_projection,
)
from test_orchestration_harness_routes import modules  # noqa: F401, E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    CONVERSATION_ID,
    NOW,
    OTHER_USER,
    REQUESTED_AT,
    RUN_ID,
    USER,
    WORKFLOW_ID,
    FakeCheckFailed,
    FakeClock,
    FakeContainer,
    cosmos_error,
    make_invocation,
    make_record,
    make_run,
    make_workflow,
    parse_iso,
    require,
    shift,
)
from test_workflow_durable_execution import Clock, RuntimeContainer  # noqa: E402
from test_workflow_structured_flow import create_structured_runtime, definition  # noqa: E402


APP_ROOT = ROOT / "application" / "single_app"
STATUS_PATH = APP_ROOT / "functions_workflow_chat_delivery_status.py"
WORKFLOW_RUNS_PATH = APP_ROOT / "functions_orchestration_workflow_runs.py"
SETTINGS = {
    "enable_chat_orchestration": True,
    "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
}

ALLOWED_PROJECTION_PATHS = {
    "id",
    "workflow_id",
    "workflow_name",
    "status",
    "started_at",
    "completed_at",
    "progress",
    "runtime_version",
    "definition_revision",
    "chat_invocation.conversation_id",
    "chat_invocation.orchestration_run_id",
    "chat_invocation.step_id",
    "chat_invocation.requested_at",
    "runtime.version",
    "runtime.state",
    "runtime.phase",
    "runtime.progress",
    "runtime.can_resume",
    "runtime.deleted",
    "runtime.limits.deadline_at",
    "runtime.gate.id",
    "runtime.gate.reason_code",
    "chat_delivery.status",
    "chat_delivery.generation",
    "chat_delivery.message_id",
    "chat_delivery.delivered_at",
    "chat_delivery.outcome_reason",
}


class StrictQueryContainer(FakeContainer):
    """FakeContainer that refuses cross-partition status queries and keeps every refusal it raised."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.refusals = []

    def query_items(self, query=None, parameters=None, partition_key=None,
                    enable_cross_partition_query=None, **kwargs):
        try:
            require(enable_cross_partition_query is None, "status queries must not enable cross-partition reads")
            return super().query_items(
                query=query,
                parameters=parameters,
                partition_key=partition_key,
                enable_cross_partition_query=enable_cross_partition_query,
                **kwargs,
            )
        except AssertionError as exc:
            self.refusals.append(str(exc))
            raise


class LiveRecorder:
    """Recording live-status fake keyed by run id."""

    def __init__(self, projections=None, raises=None):
        self.projections = dict(projections or {})
        self.raises = set(raises or ())
        self.calls = []

    def __call__(self, workflow, run_id, *, reader_user_id):
        self.calls.append({"workflow": copy.deepcopy(workflow), "run_id": run_id, "reader_user_id": reader_user_id})
        if run_id in self.raises:
            raise RuntimeError("secret-live-exception")
        return copy.deepcopy(self.projections.get(run_id))


def _path_value(document, dotted):
    current = document
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None, False
        current = current[part]
    return current, True


def _projection_pairs(query):
    select = re.search(r"SELECT TOP \d+ (.*?) FROM c ", query)
    require(select is not None, f"query must have a SELECT projection: {query!r}")
    pairs = re.findall(r"c\.([A-Za-z0-9_.]+) AS ([A-Za-z0-9_]+)", select.group(1))
    require(pairs, "status query must project aliased paths")
    return pairs


def _top(query):
    match = re.search(r"SELECT TOP (\d+)", query)
    require(match is not None, f"query must have TOP: {query!r}")
    return int(match.group(1))


def _project_run(document, pairs):
    row = {}
    for path, alias in pairs:
        value, present = _path_value(document, path)
        if present:
            row[alias] = copy.deepcopy(value)
    return row


def _selects_whole_document(query):
    return re.search(r"SELECT\s+(?:TOP\s+\d+\s+)?\*", query or "") is not None


def status_query_handler(container, query, params, partition_key):
    require(partition_key == params.get("@user_id"), "status query must use the signed-in user's partition")
    require(not _selects_whole_document(query), "status query must not use SELECT *; it projects only the allowed paths")
    pairs = _projection_pairs(query)
    require({path for path, _alias in pairs} <= ALLOWED_PROJECTION_PATHS, "status projection includes an unsafe path")
    rows = []
    for item in container.items.values():
        invocation = item.get("chat_invocation")
        delivery = item.get("chat_delivery") if isinstance(item.get("chat_delivery"), dict) else {}
        if item.get("user_id") != params.get("@user_id"):
            continue
        if item.get("trigger_source") != params.get("@source"):
            continue
        if not isinstance(invocation, dict):
            continue
        if not invocation.get("requested_at"):
            continue
        if "@conversation_id" in params:
            if invocation.get("conversation_id") != params["@conversation_id"]:
                continue
        else:
            terminal = item.get("status") in set(params.get("@terminal") or [])
            open_delivery = delivery.get("status") in set(params.get("@open") or [])
            recent_delivery = (
                isinstance(delivery.get("delivered_at"), str)
                and delivery.get("delivered_at") >= params.get("@recent", "")
            )
            if terminal and not open_delivery and not recent_delivery:
                continue
        rows.append(item)
    rows.sort(key=lambda row: str((row.get("chat_invocation") or {}).get("requested_at") or ""), reverse=True)
    return [_project_run(row, pairs) for row in rows[:_top(query)]]


def editor_workflow(workflow):
    cleaned = {key: value for key, value in workflow.items() if not str(key).startswith("_")}
    return workflow_definition_for_editor(sanitize_workflow_alert_record(cleaned))


def with_revision(workflow):
    value = copy.deepcopy(workflow)
    value["definition_revision"] = workflow_definition_revision(editor_workflow(value))
    return value


def services_for(runs=None, workflows=None, *, live=None, settings=None, gate=None, clock=None):
    runs_container = StrictQueryContainer("runs", runs or [], query_handler=status_query_handler)
    workflow_container = FakeContainer(
        "workflows",
        [with_revision(make_workflow())] if workflows is None else workflows,
    )
    live_reader = live if live is not None else LiveRecorder()
    return SimpleNamespace(
        runs=runs_container,
        workflows=workflow_container,
        live=live_reader,
        services=status.WorkflowRunStatusServices(
            runs=runs_container,
            workflows=workflow_container,
            get_settings=lambda: copy.deepcopy(settings if settings is not None else SETTINGS),
            settings_gate=gate if gate is not None else (lambda value: None),
            live_status=live_reader,
            clock=clock or FakeClock(NOW),
        ),
    )


def payload_for(runs, workflows=None, conversation_values=None, **kwargs):
    harness = services_for(runs, workflows, **kwargs)
    try:
        payload = status.workflow_run_status_payload(USER, conversation_values, services=harness.services)
    except status.WorkflowRunStatusError as exc:
        # The route correctly fails closed on any query error; name the fake's refusal so a failure says why.
        if harness.runs.refusals:
            raise FakeCheckFailed(f"{harness.runs.refusals[0]} (the route failed closed with {exc.code})") from exc
        raise
    return payload, harness


def row_for(run, workflows=None, conversation_values=None, **kwargs):
    payload, harness = payload_for([run], workflows, conversation_values or [CONVERSATION_ID], **kwargs)
    require(len(payload["runs"]) == 1, f"expected one status row, got {payload['runs']!r}")
    return payload["runs"][0], harness


def run_doc(identifier, *, state="queued", workflow_id=WORKFLOW_ID, user_id=USER,
            conversation_id=CONVERSATION_ID, requested_at=REQUESTED_AT, runtime=None,
            delivery=None, status_value=None, runtime_version=4, **overrides):
    value = make_run(
        status=status_value or state,
        workflow_id=workflow_id,
        user_id=user_id,
        id=identifier,
        chat_invocation=make_invocation(conversation_id=conversation_id, requested_at=requested_at),
        chat_delivery=make_record() if delivery is None else delivery,
        runtime=runtime if runtime is not None else {"version": 4, "state": state, "can_resume": False},
        runtime_version=runtime_version,
        started_at=shift(REQUESTED_AT, minutes=-5),
    )
    value.update(overrides)
    return value


def resumable_run(identifier=RUN_ID, *, workflow=None, runtime=None, delivery=None, **overrides):
    wf = with_revision(workflow or make_workflow())
    view = runtime or {"version": 7, "state": "failed", "can_resume": True}
    runtime_version = overrides.pop("runtime_version", view.get("version", 7))
    definition_revision = overrides.pop("definition_revision", workflow_definition_revision(editor_workflow(wf)))
    return run_doc(
        identifier,
        state="failed",
        runtime=view,
        delivery=delivery if delivery is not None else make_record(status=STATUS_READY),
        definition_revision=definition_revision,
        runtime_version=runtime_version,
        **overrides,
    ), wf


def require_codes(response, expected_status, expected_code):
    body = response.get_json()
    require(response.status_code == expected_status, f"expected {expected_status}, got {response.status_code}: {body}")
    require(body.get("code") == expected_code, f"expected code {expected_code}, got {body}")
    return body


def test_query_shape_is_single_partition_and_projection_only_in_both_modes():
    for conversation_values, expected_top in (([CONVERSATION_ID], "TOP 21"), (None, "TOP 51")):
        payload, harness = payload_for([run_doc(RUN_ID)], conversation_values=conversation_values)
        require(payload["checked_at"] == "2026-05-04T15:00:00Z", "checked_at should use the request clock")
        require(len(harness.runs.query_calls) == 1, "exactly one runs query should be issued")
        call = harness.runs.query_calls[0]
        query = call["query"]
        params = {entry["name"]: entry["value"] for entry in call["parameters"]}
        require(call["partition_key"] == USER, "status query must use the requester partition key")
        require(call.get("enable_cross_partition_query") is None, "status query must not enable cross-partition")
        require(not _selects_whole_document(query), "status query must not project the whole document")
        require(expected_top in query, f"query must use {expected_top}: {query}")
        require("ORDER BY c.chat_invocation.requested_at DESC" in query, "query must sort newest first")
        require(
            "c.user_id = @user_id AND c.trigger_source = @source AND IS_DEFINED(c.chat_invocation)" in query,
            "query must keep the owner/source/invocation filter",
        )
        require({path for path, _alias in _projection_pairs(query)} <= ALLOWED_PROJECTION_PATHS, "unsafe projection")
        if conversation_values:
            require(params.get("@conversation_id") == CONVERSATION_ID, "conversation query must bind conversation_id")
        else:
            expected_recent = (parse_iso(NOW) - timedelta(seconds=status.RECENT_DELIVERY_SECONDS)).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            require("canceled" in params["@terminal"] and "cancelled" in params["@terminal"], "terminal params need both spellings")
            require(params["@open"] == sorted(OPEN_STATUSES), "open delivery statuses must be sorted")
            require(params["@recent"] == expected_recent, "recent boundary must be exactly ten minutes")


def test_global_query_includes_only_active_open_or_recent_owner_runs():
    recent = format_delivery_timestamp(parse_iso(NOW) - timedelta(minutes=10))
    old = format_delivery_timestamp(parse_iso(NOW) - timedelta(minutes=11))
    runs = [
        run_doc("run-active", state="running", requested_at=shift(REQUESTED_AT, minutes=5)),
        run_doc("run-open-delivery", state="failed", delivery=make_record(status=STATUS_READY), requested_at=shift(REQUESTED_AT, minutes=4)),
        run_doc("run-recent", state="completed", delivery=make_record(status=STATUS_DELIVERED, delivered_at=recent), requested_at=shift(REQUESTED_AT, minutes=3)),
        run_doc("run-old", state="completed", delivery=make_record(status=STATUS_DELIVERED, delivered_at=old), requested_at=shift(REQUESTED_AT, minutes=2)),
        run_doc("run-undeliverable", state="failed", delivery=make_record(status="undeliverable"), requested_at=shift(REQUESTED_AT, minutes=1)),
        run_doc("run-other-user", state="running", user_id=OTHER_USER, requested_at=shift(REQUESTED_AT, minutes=6)),
    ]
    payload, _harness = payload_for(runs)
    ids = [row["run_id"] for row in payload["runs"]]
    require(ids == ["run-active", "run-open-delivery", "run-recent"], f"unexpected global rows: {ids}")


@pytest.mark.parametrize("runtime_state,expected_status,expected_phase,waiting_reason,waiting_action", [
    ("queued", "queued", "running", None, None),
    ("running", "running", "running", None, None),
    ("completed", "completed", "finished", None, None),
    ("completed_partial", "completed_partial", "finished", None, None),
    ("failed", "failed", "failed", None, None),
    ("invalid", "failed", "failed", None, None),
    ("incomplete", "failed", "failed", None, None),
    ("skipped", "failed", "failed", None, None),
    ("cancelled", "cancelled", "cancelled", None, None),
    ("canceled", "cancelled", "cancelled", None, None),
    ("waiting_approval", "waiting", "needs_you", "approval", status.WAITING_ACTION_APPROVE),
    ("awaiting_sign_in", "waiting", "needs_you", "microsoft_365_reconnect", status.WAITING_ACTION_RECONNECT),
    (sorted(M365_WAITING_STATES - {"awaiting_sign_in"})[0], "waiting", "needs_you", "microsoft_365_approval", status.WAITING_ACTION_OPEN_RUN),
    ("waiting_output", "waiting", "needs_you", "output_review", status.WAITING_ACTION_OPEN_RUN),
    ("waiting_recovery", "running", "running", "recovery", status.WAITING_ACTION_OPEN_RUN),
    ("paused", "waiting", "needs_you", "paused", status.WAITING_ACTION_OPEN_RUN),
    ("cancelling", "running", "running", None, None),
])
def test_status_phase_waiting_and_action_mappings(runtime_state, expected_status, expected_phase,
                                                  waiting_reason, waiting_action):
    state_for_doc = runtime_state
    runtime = {
        "version": 3,
        "state": runtime_state,
        "can_resume": runtime_state in {"failed", "invalid", "incomplete"},
        "gate": {"id": "gate-1", "reason_code": None},
        "progress": {"completed": 2, "total": 5},
    }
    if runtime_state in RUN_DOCUMENT_TERMINAL_STATUSES:
        extra = {"completed_at": shift(REQUESTED_AT, minutes=8)}
    else:
        extra = {}
    run = run_doc(RUN_ID, state=state_for_doc, runtime=runtime, **extra)
    row, _harness = row_for(run)
    require(row["status"] == expected_status, f"{runtime_state} status mismatch: {row}")
    require(row["phase"] == expected_phase, f"{runtime_state} phase mismatch: {row}")
    require(row["step_index"] == 2 and row["step_count"] == 5, "progress should map to step counts")
    require(row["step_label"] is None, "step_label is intentionally null")
    require(row["actions"]["open_run"] is True, "open_run is always available")
    require(row["actions"]["cancel"] == (runtime_state not in RUN_DOCUMENT_TERMINAL_STATUSES and runtime_state != "cancelling"), "cancel rule mismatch")
    if waiting_reason is None:
        require(row["waiting"] is None, f"{runtime_state} should not expose waiting info")
        require(row["actions"]["approve"] is False, "approve needs an approval wait")
    else:
        require(row["waiting"]["reason"] == waiting_reason, f"{runtime_state} waiting reason mismatch")
        require(row["waiting"]["action"] == waiting_action, f"{runtime_state} waiting action mismatch")
        require(row["waiting"]["gate_id"] == "gate-1", "waiting gate id should be carried")
        require(row["actions"]["approve"] == (waiting_action == status.WAITING_ACTION_APPROVE), "approve rule mismatch")


def test_unknown_runtime_state_falls_back_to_stored_status_then_reads_as_running():
    fallback, _harness = row_for(run_doc(
        RUN_ID, state="failed", runtime={"version": 3, "state": "future_state", "can_resume": False},
    ))
    require(
        fallback["status"] == "failed" and fallback["phase"] == "failed",
        f"an unknown projection state should fall back to the stored run status: {fallback}",
    )
    unknown, _harness = row_for(run_doc(
        "run-unknown", state="future_state", runtime={"version": 3, "state": "future_state", "can_resume": True},
    ))
    require(
        unknown["status"] == "running" and unknown["phase"] == "running",
        f"a state the status module doesn't know yet should read as running: {unknown}",
    )
    require(unknown["actions"]["retry"] is False, "a state the module doesn't know is never retryable")
    require(unknown["retry_blocked"] is None, "retry_blocked applies only to resumable states")


def test_expired_approval_cancel_delivery_error_and_secret_mapping():
    secret = "SECRET-RUN-OUTPUT-TEXT"
    run = run_doc(
        RUN_ID,
        state="paused",
        runtime={
            "version": 3,
            "state": "paused",
            "can_resume": False,
            "phase": REASON_DEADLINE_EXCEEDED,
            "gate": {"id": "gate-1", "reason_code": REASON_DEADLINE_EXCEEDED},
        },
        delivery=make_record(
            status=STATUS_DELIVERED,
            message_id=f"{DELIVERY_MESSAGE_ID_PREFIX}abc",
            delivered_at=format_delivery_timestamp(parse_iso(NOW)),
            outcome_reason=REASON_DEADLINE_EXCEEDED,
        ),
        error=secret,
        output={"text": secret},
    )
    row, _harness = row_for(run)
    encoded = json.dumps(row, sort_keys=True)
    require(row["status"] == "expired" and row["phase"] == "failed", "paused deadline should show expired")
    require(row["error_code"] == REASON_DEADLINE_EXCEEDED, "expired rows should use deadline_exceeded")
    require(row["actions"]["cancel"] is False and row["actions"]["approve"] is False, "expired rows should not cancel or approve")
    require(row["delivery"]["status"] == STATUS_DELIVERED, "delivered status should be preserved")
    require(row["delivery"]["message_id"] == f"{DELIVERY_MESSAGE_ID_PREFIX}abc", "valid delivery message id should be exposed")
    require(row["delivery"]["delivered_at"] == "2026-05-04T15:00:00Z", "delivered_at should be seconds precision")
    require(row["delivery"]["reason"] == REASON_DEADLINE_EXCEEDED, "known delivery reason should be exposed")
    require(secret not in encoded, "run output and raw error text must not appear in status payload")


def test_delivery_not_applicable_and_ready_mapping():
    missing_delivery, _harness = row_for(run_doc(RUN_ID, delivery={}))
    ready_delivery, _harness = row_for(run_doc("run-ready", delivery=make_record(status=STATUS_READY)))
    require(missing_delivery["delivery"] == {
        "status": status.DELIVERY_NOT_APPLICABLE,
        "generation": None,
        "message_id": None,
        "delivered_at": None,
        "reason": None,
    }, "missing delivery should be not_applicable")
    require(ready_delivery["delivery"]["status"] == "pending", "ready delivery should display as pending")


def test_delivery_message_id_requires_delivered_status_and_prefix():
    pending_with_message, _harness = row_for(run_doc(
        RUN_ID,
        delivery=make_record(
            status=STATUS_READY,
            message_id=f"{DELIVERY_MESSAGE_ID_PREFIX}pending",
        ),
    ))
    require(
        pending_with_message["delivery"]["message_id"] is None,
        f"pending delivery must not expose a message id: {pending_with_message}",
    )

    delivered_without_prefix, _harness = row_for(run_doc(
        "run-delivered-without-prefix",
        delivery=make_record(
            status=STATUS_DELIVERED,
            message_id="message-without-delivery-prefix",
            delivered_at=format_delivery_timestamp(parse_iso(NOW)),
        ),
    ))
    require(
        delivered_without_prefix["delivery"]["message_id"] is None,
        f"delivered rows must hide message ids without the delivery prefix: {delivered_without_prefix}",
    )


def test_failed_unknown_gate_reason_maps_to_generic_failure_sentence():
    runtime = {
        "version": 6,
        "state": "failed",
        "can_resume": False,
        "gate": {"id": "gate-unknown", "reason_code": "future_failure_reason"},
    }
    row, _harness = row_for(run_doc(RUN_ID, state="failed", runtime=runtime, completed_at=NOW))
    expected_error = f"{failure_reason_text('failed')[:1].upper()}{failure_reason_text('failed')[1:]}."
    require(row["error_code"] == "failed", f"unknown gate reason should fall back to failed: {row}")
    require(row["error"] == expected_error, f"generic failure sentence mismatch: {row}")


def test_live_reads_are_capped_fallback_safe_and_use_editor_workflow():
    workflows = [with_revision(make_workflow(_etag="etag-secret", _ts=123, active_run_id=""))]
    projections = {
        "run-11": {
            "version": 99,
            "state": "waiting_approval",
            "phase": "approval",
            "can_resume": False,
            "gate": {"id": "gate-live", "reason_code": "approval"},
            "progress": {"completed": 4, "total": 4},
        },
    }
    live = LiveRecorder(projections, raises={"run-10"})
    runs = [
        run_doc(f"run-{index:02d}", state="running", requested_at=shift(REQUESTED_AT, minutes=index))
        for index in range(12)
    ]
    payload, _harness = payload_for(runs, workflows, live=live)
    rows = {row["run_id"]: row for row in payload["runs"]}
    require(len(live.calls) == status.LIVE_READ_LIMIT, "live reads should stop at the cap")
    require(rows["run-11"]["live"] is True, "live override should mark the row live")
    require(rows["run-11"]["status"] == "waiting", "live state should override stored state")
    require(rows["run-11"]["runtime_version"] == 99, "live version should become runtime_version")
    require(rows["run-10"]["live"] is False and rows["run-10"]["status"] == "running", "raising live read should fall back")
    require(rows["run-00"]["live"] is False and rows["run-01"]["live"] is False, "rows beyond live cap should use stored values")
    require(all(call["reader_user_id"] == USER for call in live.calls), "live reads need reader_user_id")
    require(all("_etag" not in call["workflow"] and "_ts" not in call["workflow"] for call in live.calls), "live workflow must be editor form")


def test_workflow_reads_are_cached_and_capped_for_retry_projection():
    workflow = with_revision(make_workflow(active_run_id=""))
    runs = []
    workflows = []
    for index in range(22):
        workflow_id = f"workflow-{index:02d}"
        wf = with_revision({**workflow, "id": workflow_id})
        workflows.append(wf)
        run, _wf = resumable_run(
            f"run-{index:02d}",
            workflow=wf,
            workflow_id=workflow_id,
            requested_at=shift(REQUESTED_AT, minutes=index),
        )
        runs.append(run)
    # Add a second row for workflow-00 to prove point reads are cached per workflow id.
    repeated = copy.deepcopy(runs[0])
    repeated["id"] = "run-repeat"
    repeated["chat_invocation"]["requested_at"] = shift(REQUESTED_AT, minutes=30)
    runs.insert(0, repeated)
    payload, harness = payload_for(runs, workflows)
    by_id = {row["run_id"]: row for row in payload["runs"]}
    read_calls = [call for call in harness.workflows.calls if call[0] == "read_item"]
    require(len(read_calls) == status.WORKFLOW_READ_LIMIT, f"workflow reads should stop at cap: {read_calls}")
    require(sum(1 for call in read_calls if call[1] == "workflow-00") == 1, "workflow reads should be cached")
    require(by_id["run-repeat"]["actions"]["retry"] is True, "cached workflow row should still be retryable")
    require(by_id["run-02"]["retry_blocked"] == status.RETRY_BLOCKED_UNAVAILABLE, "21st workflow should be over cap")
    require(by_id["run-01"]["retry_blocked"] == status.RETRY_BLOCKED_UNAVAILABLE, "22nd workflow should be over cap")


@pytest.mark.parametrize("case_name,runtime_changes,workflow_changes,run_changes,expected", [
    ("projection-deleted", {"deleted": True}, {}, {}, status.RETRY_BLOCKED_WORKFLOW_DELETED),
    ("not-resumable", {"can_resume": False}, {}, {}, status.RETRY_BLOCKED_NOT_RESUMABLE),
    ("deadline", {"limits": {"deadline_at": "2026-05-04T14:59:59.000000Z"}}, {}, {}, status.RETRY_BLOCKED_DEADLINE_EXCEEDED),
    ("workflow-deleting", {}, {"deleting": True}, {}, status.RETRY_BLOCKED_WORKFLOW_DELETED),
    ("revision-mismatch", {}, {"name": "Changed name"}, {}, status.RETRY_BLOCKED_DEFINITION_CHANGED),
    ("already-running", {}, {"active_run_id": "other-run"}, {}, status.RETRY_BLOCKED_ALREADY_RUNNING),
    ("missing-revision", {}, {}, {"definition_revision": ""}, status.RETRY_BLOCKED_UNAVAILABLE),
    ("missing-version", {"version": None}, {}, {"runtime_version": None}, status.RETRY_BLOCKED_UNAVAILABLE),
])
def test_retry_blocked_codes(case_name, runtime_changes, workflow_changes, run_changes, expected):
    workflow_body = make_workflow(active_run_id="")
    workflow_body.update(workflow_changes)
    workflow = with_revision(workflow_body)
    runtime = {"version": 7, "state": "failed", "can_resume": True}
    runtime.update(runtime_changes)
    run, _workflow = resumable_run(workflow=workflow, runtime=runtime, **run_changes)
    if case_name == "revision-mismatch":
        run["definition_revision"] = "old-revision"
    row, _harness = row_for(run, [workflow])
    require(row["retry_blocked"] == expected, f"{case_name} retry block mismatch: {row}")
    require(row["actions"]["retry"] is False, f"{case_name} should not be retryable")


def test_retry_blocked_workflow_read_errors_and_retry_ok():
    workflow = with_revision(make_workflow(active_run_id=""))
    ok_run, _workflow = resumable_run(workflow=workflow)
    ok_row, _harness = row_for(ok_run, [workflow])
    require(ok_row["retry_blocked"] is None and ok_row["actions"]["retry"] is True, "valid failed run should be retryable")

    gone_row, _harness = row_for(ok_run, [])
    require(gone_row["retry_blocked"] == status.RETRY_BLOCKED_WORKFLOW_DELETED, "missing workflow should block as deleted")

    harness = services_for([ok_run], [workflow])
    harness.workflows.fail("read_item", cosmos_error(500, "secret-workflow-error"))
    payload = status.workflow_run_status_payload(USER, [CONVERSATION_ID], services=harness.services)
    require(payload["runs"][0]["retry_blocked"] == status.RETRY_BLOCKED_UNAVAILABLE, "read errors should be unavailable")


def test_retry_blocks_foreign_and_group_workflow_documents_as_deleted():
    for case_name, workflow_changes in (
        ("foreign-owner", {"user_id": OTHER_USER}),
        ("group-workflow", {"group_id": "group-1"}),
    ):
        workflow = with_revision(make_workflow(active_run_id="", **workflow_changes))
        run, _workflow = resumable_run(workflow=workflow)
        row, _harness = row_for(run, [workflow])
        require(
            row["retry_blocked"] == status.RETRY_BLOCKED_WORKFLOW_DELETED,
            f"{case_name} workflow should be treated as deleted: {row}",
        )
        require(row["actions"]["retry"] is False, f"{case_name} workflow must block retry: {row}")


@pytest.mark.parametrize("terminal_state", ["skipped", "cancelled"])
def test_skipped_and_cancelled_are_never_retryable_even_with_can_resume(terminal_state):
    runtime = {"version": 8, "state": terminal_state, "can_resume": True}
    run = run_doc(RUN_ID, state=terminal_state, runtime=runtime, runtime_version=8, completed_at=NOW)
    row, _harness = row_for(run)
    require(row["retry_blocked"] is None, "non-resumable terminal states should not compute retry_blocked")
    require(row["actions"]["retry"] is False, f"{terminal_state} must not be retryable")


def schema_one_failed_control():
    workflow = with_revision({"id": WORKFLOW_ID, "user_id": USER, "durable_execution": True, "active_run_id": ""})
    container = RuntimeContainer()
    clock = Clock()
    store = WorkflowRuntimeStore(container, workflow, RUN_ID, clock=clock)
    store.initialize(
        snapshot_ref={"storage": "cosmos", "schema_version": 1, "sha256": "a" * 64, "size_bytes": 100, "chunk_count": 1},
        definition_revision=workflow_definition_revision(editor_workflow(workflow)),
        actor_user_id=USER,
        request_id="request-one",
    )
    token = store.claim(owner_id="worker")
    control = store.transition(token, state="failed")
    return workflow, store, control, clock


def status_row_for_control(workflow, run_id, control, clock_value, *, user_id=USER, conversation_id=CONVERSATION_ID):
    run = run_doc(
        run_id,
        state=control["state"],
        workflow_id=workflow["id"],
        user_id=user_id,
        conversation_id=conversation_id,
        runtime=workflow_runtime_projection(control),
        runtime_version=control["version"],
        definition_revision=workflow_definition_revision(editor_workflow(workflow)),
        delivery=make_record(status=STATUS_READY),
    )
    harness = services_for([run], [workflow], clock=lambda: clock_value)
    payload = status.workflow_run_status_payload(user_id, [conversation_id], services=harness.services)
    require(len(payload["runs"]) == 1, f"expected runtime row: {payload}")
    return payload["runs"][0]


def test_schema_one_status_runtime_version_is_resume_expected_version():
    workflow, store, control, clock = schema_one_failed_control()
    row = status_row_for_control(workflow, RUN_ID, control, clock())
    require(row["actions"]["retry"] is True, f"schema-1 failed control should be retryable: {row}")
    stale = row["runtime_version"] - 1
    with pytest.raises(WorkflowRuntimeConflict):
        store.resume(expected_version=stale, actor_user_id=USER, request_id="resume-stale")
    resumed = store.resume(expected_version=row["runtime_version"], actor_user_id=USER, request_id="resume-ok")
    require(resumed["state"] == "queued", "schema-1 resume should requeue the control")


def test_schema_two_status_runtime_version_is_resume_expected_version(monkeypatch):
    workflow, store, _container, clock = create_structured_runtime(definition(), monkeypatch)
    token = store.claim(owner_id="worker")
    control = store.transition(token, state="failed")
    row = status_row_for_control(workflow, "run", control, clock(), user_id="owner", conversation_id="conversation-schema-2")
    require(row["actions"]["retry"] is True, f"schema-2 failed control should be retryable: {row}")
    with pytest.raises(WorkflowRuntimeConflict):
        store.resume(expected_version=row["runtime_version"] - 1, actor_user_id="owner", request_id="resume-stale")
    resumed = store.resume(expected_version=row["runtime_version"], actor_user_id="owner", request_id="resume-ok")
    require(resumed["state"] == "queued", "schema-2 resume should requeue the control")


def test_workflow_run_chat_invocation_writer_sets_requested_at():
    tree = ast.parse(WORKFLOW_RUNS_PATH.read_text(encoding="utf-8"), filename=str(WORKFLOW_RUNS_PATH))
    candidates = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "chat_invocation":
                candidates.append(keyword.value)
    require(candidates, "expected a chat_invocation writer in functions_orchestration_workflow_runs.py")
    for candidate in candidates:
        require(isinstance(candidate, ast.Dict), "chat_invocation should be built as an explicit dict")
        keys = {key.value for key in candidate.keys if isinstance(key, ast.Constant)}
        require("requested_at" in keys, "chat_invocation writer must include requested_at")


def test_error_paths_are_fixed_and_non_leaking():
    for values in ((CONVERSATION_ID, "again"), (""), ("bad value!")):
        with pytest.raises(status.WorkflowRunStatusError) as captured:
            status.workflow_run_status_payload(USER, values if isinstance(values, tuple) else [values], services=services_for().services)
        body, code = captured.value.payload()
        require(code == 400 and body["code"] == status.INVALID_CONVERSATION_CODE, f"invalid conversation should be 400: {body}")

    harness = services_for([run_doc(RUN_ID)])
    harness.runs.fail("query_items", RuntimeError("secret-query-text"))
    with pytest.raises(status.WorkflowRunStatusError) as query_error:
        status.workflow_run_status_payload(USER, [CONVERSATION_ID], services=harness.services)
    body, code = query_error.value.payload()
    require(code == 503 and body["code"] == status.STATUS_UNAVAILABLE_CODE, "query failure should be unavailable")
    require("secret-query-text" not in json.dumps(body), "query exception text must not leak")

    gate_harness = services_for([run_doc(RUN_ID)], gate=lambda _settings: (_ for _ in ()).throw(RuntimeError("secret-gate-text")))
    with pytest.raises(status.WorkflowRunStatusError) as gate_error:
        status.workflow_run_status_payload(USER, [CONVERSATION_ID], services=gate_harness.services)
    require("secret-gate-text" not in json.dumps(gate_error.value.payload()[0]), "gate exception text must not leak")

    body, code = status.WorkflowRunStatusError("new-future-code").payload()
    require(code == 503 and body["code"] == status.STATUS_UNAVAILABLE_CODE, "unknown codes should map to unavailable")

    unavailable = services_for([run_doc(RUN_ID)], gate=lambda _settings: "disabled")
    payload = status.workflow_run_status_payload(USER, [CONVERSATION_ID], services=unavailable.services)
    require(payload["available"] is False and len(payload["runs"]) == 1, "settings gate reason should not hide rows")

    many = [run_doc(f"run-{index:02d}", requested_at=shift(REQUESTED_AT, minutes=index)) for index in range(status.CONVERSATION_LIMIT + 1)]
    payload, _harness = payload_for(many, conversation_values=[CONVERSATION_ID])
    require(payload["truncated"] is True and len(payload["runs"]) == status.CONVERSATION_LIMIT, "conversation rows should truncate")

    bad = run_doc("bad-run")
    bad["workflow_id"] = ""
    payload, _harness = payload_for([bad], conversation_values=[CONVERSATION_ID])
    require(payload["runs"] == [], "bad stored identifiers should skip the row")

    with pytest.raises(status.WorkflowRunStatusError) as user_error:
        status.workflow_run_status_payload("", [CONVERSATION_ID], services=services_for().services)
    require(user_error.value.payload()[1] == 503, "invalid user_id should be unavailable")


@pytest.mark.parametrize("optimized", [False, True])
def test_status_module_import_smoke_does_not_load_config_or_runtime(optimized):
    code = (
        "import sys; "
        "import functions_workflow_chat_delivery_status; "
        "print('config=' + str('config' in sys.modules)); "
        "print('runtime=' + str('functions_workflow_runtime' in sys.modules))"
    )
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend(["-c", code])
    environment = os.environ.copy()
    environment["PYTHONPATH"] = f"{ROOT / 'application' / 'single_app'}{os.pathsep}{ROOT / 'functional_tests'}"
    result = subprocess.run(command, text=True, capture_output=True, env=environment, check=False)
    require(result.returncode == 0, f"import smoke failed: {result.stderr}")
    require("config=False" in result.stdout, f"status import should not load config: {result.stdout}")
    require("runtime=False" in result.stdout, f"status import should not load runtime: {result.stdout}")


def _log_recorder(logs, source):
    def log_event(message, *args, **kwargs):
        logs.append({
            "source": source,
            "message": str(message),
            "extra": copy.deepcopy(kwargs.get("extra") or {}),
            "level": kwargs.get("level"),
        })
    return log_event


@pytest.fixture
def route_harness(modules, monkeypatch):
    status_module = importlib.import_module("functions_workflow_chat_delivery_status")
    settings_module = importlib.import_module("functions_settings")
    settings = copy.deepcopy(SETTINGS)
    route_logs = []

    def access_status(user_id):
        return True, None

    monkeypatch.setattr(modules.auth, "check_user_access_status", access_status)
    monkeypatch.setattr(modules.route, "get_settings", lambda: copy.deepcopy(settings))
    monkeypatch.setattr(settings_module, "get_settings", lambda: copy.deepcopy(settings))
    monkeypatch.setattr(modules.route, "log_event", _log_recorder(route_logs, "route_backend_orchestration"))
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="workflow-status-route-test")
    blueprint = Blueprint("backend_orchestration", __name__)
    blueprint.before_request(modules.auth.user_required_blueprint())
    modules.route.register_route_backend_orchestration(blueprint)
    app.register_blueprint(blueprint)
    return SimpleNamespace(
        modules=modules,
        status=status_module,
        settings=settings,
        logs=route_logs,
        app=app,
        client=Client(app, Response),
        monkeypatch=monkeypatch,
    )


def login(route_harness, *, user_id=USER, roles=("User",)):
    serializer = route_harness.app.session_interface.get_signing_serializer(route_harness.app)
    cookie = serializer.dumps({
        "user": {
            "oid": user_id,
            "roles": list(roles),
            "tid": "tenant-1",
            "preferred_username": "owner@example.com",
        },
    })
    route_harness.client.set_cookie(route_harness.app.config["SESSION_COOKIE_NAME"], cookie)


def status_get(route_harness, query=None):
    return route_harness.client.get("/api/v2/orchestration/workflow-runs/status", query_string=query or {})


def test_route_requires_a_signed_in_user(route_harness):
    response = status_get(route_harness)
    require(response.status_code in {302, 401}, f"unauthenticated API request should be rejected: {response.status_code}")


def test_route_preserves_workflow_feature_gates(route_harness):
    login(route_harness)
    route_harness.settings["allow_user_workflows"] = False
    disabled = status_get(route_harness)
    require(disabled.status_code == 400, f"allow_user_workflows false should return 400: {disabled.get_json()}")
    require(disabled.get_json()["error"] == "Allow User Workflows is disabled.", "enabled_required message changed")

    route_harness.settings["allow_user_workflows"] = True
    route_harness.settings["require_member_of_workflow_user"] = True
    forbidden = status_get(route_harness)
    require(forbidden.status_code == 403, f"missing WorkflowUser role should return 403: {forbidden.get_json()}")


def test_route_maps_status_errors_and_generic_errors_without_secret_text(route_harness, monkeypatch):
    login(route_harness)
    services = services_for([run_doc(RUN_ID)]).services
    monkeypatch.setattr(route_harness.status, "default_workflow_run_status_services", lambda: services)
    repeated = route_harness.client.get(
        "/api/v2/orchestration/workflow-runs/status?conversation_id=one&conversation_id=two"
    )
    require_codes(repeated, 400, status.INVALID_CONVERSATION_CODE)

    def boom(_user_id, _conversation_values):
        raise RuntimeError("secret-text")

    monkeypatch.setattr(route_harness.status, "workflow_run_status_payload", boom)
    failed = status_get(route_harness)
    body_text = failed.get_data(as_text=True)
    require_codes(failed, 503, status.STATUS_UNAVAILABLE_CODE)
    require("secret-text" not in body_text, "generic route error must not leak exception text")
    require(route_harness.logs, "generic route failure should be logged")
    extra = route_harness.logs[-1]["extra"]
    require(extra.get("stage") == "workflow_run_status", f"log stage mismatch: {extra}")
    require(extra.get("error_type") == "RuntimeError", f"log error_type mismatch: {extra}")
    require("secret-text" not in json.dumps(route_harness.logs, default=str), "logs must not contain exception text")


FEATURE_DOC = ROOT / "docs" / "explanation" / "features" / "CHAT_WORKFLOW_RESULT_DELIVERY.md"
ROW_KEYS = {
    "workflow_id", "workflow_scope", "run_id", "workflow_name", "conversation_id", "orchestration_run_id",
    "step_id", "requested_at", "status", "phase", "runtime_version", "step_index", "step_count", "step_label",
    "started_at", "completed_at", "elapsed_seconds", "waiting", "delivery", "error", "error_code",
    "retry_blocked", "actions", "live",
}
DELIVERY_KEYS = {"status", "generation", "message_id", "delivered_at", "reason"}
ACTION_KEYS = {"cancel", "retry", "approve", "open_run"}


def documented_response_example():
    text = FEATURE_DOC.read_text(encoding="utf-8")
    match = re.search(r"^### Response example\s*```json\n(.*?)\n```", text, re.S | re.M)
    require(match is not None, f"no JSON block under '### Response example' in {FEATURE_DOC.name}")
    return json.loads(match.group(1))


def test_route_returns_status_payload_body_shape(route_harness, monkeypatch):
    login(route_harness)
    services = services_for([run_doc(RUN_ID)]).services
    monkeypatch.setattr(route_harness.status, "default_workflow_run_status_services", lambda: services)
    response = status_get(route_harness, {"conversation_id": CONVERSATION_ID})
    body = response.get_json()
    require(response.status_code == 200, f"status route should succeed: {body}")
    require(set(body) == {"available", "runs", "checked_at", "truncated"}, f"top-level body shape changed: {body}")
    require(body["available"] is True and body["truncated"] is False, "body flags should be present")
    require(len(body["runs"]) == 1, f"expected one route row: {body}")
    row = body["runs"][0]
    require(set(row) == ROW_KEYS, f"row keys changed (6b-2 contract): {sorted(set(row) ^ ROW_KEYS)}")
    require(row["workflow_scope"] == "personal", f"workflow_scope must be personal: {row['workflow_scope']!r}")
    require(set(row["delivery"]) == DELIVERY_KEYS, f"delivery keys changed: {sorted(row['delivery'])}")
    require(set(row["actions"]) == ACTION_KEYS, f"action keys changed: {sorted(row['actions'])}")

    example = documented_response_example()
    documented = example["runs"][0]
    require(set(example) == set(body), f"doc example top-level keys drifted: {sorted(set(example) ^ set(body))}")
    require(set(documented) == ROW_KEYS, f"doc example row keys drifted: {sorted(set(documented) ^ ROW_KEYS)}")
    require(set(documented["delivery"]) == DELIVERY_KEYS, f"doc example delivery keys drifted: {documented['delivery']}")
    require(set(documented["actions"]) == ACTION_KEYS, f"doc example action keys drifted: {documented['actions']}")
    require(documented["workflow_scope"] == "personal", "doc example workflow_scope must be personal")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
