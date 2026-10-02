# test_orchestration_workflow_results_reads.py
"""
Functional test for the workflow_results orchestration capability (access, selection, notes, compose, reuse, logging).
Version: 0.261.217
Implemented in: 0.261.217

This test ensures workflow_results reads are re-authorized, selected, fenced, summarized, reused, and logged without leaking stored run output or private identifiers.
"""

import json
import logging
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_orchestration_harness_routes import modules  # noqa: E402,F401
from test_support.versioning import assert_app_version_at_least  # noqa: E402


USER_ID = "user-owner-distinct-329"
OTHER_USER_ID = "user-foreign-distinct-913"
CONVERSATION_ID = "conversation-private-distinct-421"
WORKFLOW_ID = "workflow-secret-id-11111111-2222-4333-8444-555555555555"
OTHER_WORKFLOW_ID = "workflow-secret-id-99999999-2222-4333-8444-555555555555"
RUN_ID = "run-secret-id-aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_RUN_ID = "run-secret-id-ffffffff-bbbb-4ccc-8ddd-eeeeeeeeeeee"
HANDLE = "workflow_handle_secret_329"
WORKFLOW_NAME = "Weekly Digest Private Name"
EXCERPT_MARKER = "EXCERPT_MARKER_SECRET_4f61"
QUERY_SECRET = "QUERY_STORAGE_SECRET_6e21"
RESULT_SHA = "a" * 64
LOCAL_ZONE = "America/New_York"
SETTINGS = {
    "enable_chat_orchestration": True,
    "enable_chat_workflow_results": True,
    "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
    "chat_orchestration_enabled_capabilities": [],
}
DEFAULT = object()


class FakeWorkflowResultUnavailable(Exception):
    """Reader refusal test double with the same public shape as WorkflowResultUnavailable."""

    def __init__(self, code):
        self.code = code
        super().__init__(f"reader refusal {code}")


class Access:
    def __init__(self):
        self.authorized = []

    def authorize_producer(self, producer, for_write=False):
        self.authorized.append((producer.user_id, for_write))


class ResultService:
    def __init__(self, value=None):
        self.access = Access()
        self.persisted = []
        self.opened = []
        self.value = value

    def persist_task_result(
        self, *, producer, role, status, outputs, sources, origin, guard_token, upstream, input_fingerprint,
    ):
        self.persisted.append({
            "producer": producer,
            "role": role,
            "status": status,
            "outputs": [(output.name, output.kind, deepcopy(output.value)) for output in outputs],
            "sources": list(sources),
            "origin": origin,
            "guard_token": guard_token,
            "upstream": tuple(upstream),
            "input_fingerprint": input_fingerprint,
        })
        return None

    def open_result(self, reference, allow_partial=True):
        self.opened.append((reference, allow_partial))
        value = self.value

        class Opened:
            def read_value(self_inner):
                if isinstance(value, Exception):
                    raise value
                return deepcopy(value)

        return Opened()


def test_version_is_at_least_workflow_results_release():
    assert_app_version_at_least("0.261.217")


@pytest.fixture
def results(modules):
    import importlib

    return importlib.import_module("functions_orchestration_workflow_results")


@pytest.fixture(autouse=True)
def patch_result_runtime(results, monkeypatch):
    monkeypatch.setattr(results, "require_result_service", lambda context: context.result_service)
    monkeypatch.setattr(results, "_reader_unavailable_type", lambda: FakeWorkflowResultUnavailable)


def planning(handle=HANDLE, workflow_id=WORKFLOW_ID, *, private=True, ready=True, name=WORKFLOW_NAME):
    marker = {"ready": True} if ready else {"ready": False}
    return {
        "conversation_private": private,
        "workflow_results": marker,
        "catalog": {"workflows": [{"handle": handle, "name": name}]},
        "handles": {"workflows": {handle: {"id": workflow_id}}},
        "time_zone": LOCAL_ZONE,
        "request_local_time": "Monday, January 6, 2025, 9:00 AM EST",
    }


def step(handle=HANDLE, selector="latest", *, completed_on=None, status=None, step_id="read_saved_digest"):
    arguments = {"workflow": handle, "selector": selector}
    if completed_on is not None:
        arguments["completed_on"] = completed_on
    if status is not None:
        arguments["status"] = status
    return {
        "step_id": step_id,
        "capability_id": "workflow_results",
        "arguments": arguments,
        "inputs": {},
        "outputs": [{"name": "result", "kind": "structured-v1"}],
    }


def context(service, wf_planning=None, *, roles=("User",), user_id=USER_ID):
    producer = SimpleNamespace(user_id=user_id, run_id="orchestration-run-1", step_id="read_saved_digest")
    return SimpleNamespace(
        result_service=service,
        plan_contract_version=2,
        run_id="orchestration-run-1",
        attempt_root_run_id="orchestration-run-1",
        conversation_id=CONVERSATION_ID,
        workflow_planning=deepcopy(wf_planning if wf_planning is not None else planning()),
        user_roles=list(roles),
        settings=deepcopy(SETTINGS),
        time_zone=LOCAL_ZONE,
        result_producer=lambda current_step: producer,
        result_guard_token_for_step=lambda step_id: "guard-token-1",
        result_input_fingerprint_for_step=lambda step_id: "fingerprint-1",
    )


def completed_run(run_id=RUN_ID, *, workflow_id=WORKFLOW_ID, started_at="2025-01-06T14:00:00+00:00",
                  completed_at="2025-01-06T14:05:00+00:00", status="completed"):
    return {
        "id": run_id,
        "workflow_id": workflow_id,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
    }


def result_payload(run_id=RUN_ID, *, workflow_id=WORKFLOW_ID, completed_at="2025-01-06T14:05:00+00:00",
                   status="completed", marker=EXCERPT_MARKER, analysis_only=False, saved_inputs=None):
    return {
        "descriptor": {
            "version": "workflow-result-v1",
            "workflow_id": workflow_id,
            "run_id": run_id,
            "workflow_name": WORKFLOW_NAME,
            "status": status,
            "completed_at": completed_at,
            "result_sha256": RESULT_SHA,
            "available": True,
        },
        "excerpts": [{"label": "Summary", "kind": "text", "final": True, "text": marker, "truncated": False, "note": ""}],
        "saved_inputs": list(saved_inputs or []),
        "partial": False,
        "truncated": False,
        "analysis_only": analysis_only,
        "omitted_outputs": 0,
    }


def install_runtime_stubs(
    module,
    monkeypatch,
    *,
    wf_planning=None,
    conversation=DEFAULT,
    workflow=DEFAULT,
    latest_rows=None,
    in_progress_rows=None,
    completed_rows=None,
    read_result=DEFAULT,
    query_error=None,
    settings_reason=None,
    role_reason=None,
    refresh=None,
    calls=None,
):
    calls = calls if calls is not None else {
        "queries": [], "reads": [], "reader": [], "settings_gate": [], "role_gate": [], "refresh": [],
    }
    wf_planning = deepcopy(wf_planning if wf_planning is not None else planning())
    conversation = deepcopy(
        {"id": CONVERSATION_ID, "user_id": USER_ID} if conversation is DEFAULT else conversation
    )
    workflow = deepcopy(
        {"id": WORKFLOW_ID, "user_id": USER_ID, "name": WORKFLOW_NAME} if workflow is DEFAULT else workflow
    )
    latest_rows = list(latest_rows or [])
    in_progress_rows = list(in_progress_rows or [])
    completed_rows = list(completed_rows or [])
    read_result = deepcopy(result_payload() if read_result is DEFAULT else read_result)

    def settings_gate(settings):
        calls["settings_gate"].append(deepcopy(settings))
        return settings_reason

    def role_gate(settings, user_roles):
        calls["role_gate"].append((deepcopy(settings), list(user_roles or [])))
        return role_reason

    def refresh_privacy(current, current_conversation, user_id):
        calls["refresh"].append((deepcopy(current), deepcopy(current_conversation), user_id))
        if refresh is not None:
            return refresh(current, current_conversation, user_id)
        return deepcopy(wf_planning)

    def read_conversation(conversation_id):
        calls["reads"].append(("conversation", conversation_id))
        return deepcopy(conversation)

    def read_workflow(user_id, workflow_id):
        calls["reads"].append(("workflow", user_id, workflow_id))
        return deepcopy(workflow)

    def query_runs(user_id, query, parameters):
        calls["queries"].append((user_id, query, deepcopy(parameters)))
        if query_error is not None:
            raise query_error
        if query == module._LATEST_QUERY:
            return deepcopy(latest_rows)
        if query == module._IN_PROGRESS_QUERY:
            return deepcopy(in_progress_rows)
        if query == module._COMPLETED_ON_QUERY:
            by_name = {item["name"]: item["value"] for item in parameters}
            lo = datetime.fromisoformat(by_name["@lo"])
            hi = datetime.fromisoformat(by_name["@hi"])
            filtered = []
            for row in completed_rows:
                completed_at = module._parse_utc(row.get("completed_at"))
                if completed_at is not None and lo <= completed_at < hi:
                    filtered.append(deepcopy(row))
            return filtered
        raise AssertionError(f"unexpected query: {query}")

    def reader(user_id, workflow_id, run_id, **options):
        calls["reader"].append((user_id, workflow_id, run_id, deepcopy(options)))
        if isinstance(read_result, Exception):
            raise read_result
        return deepcopy(read_result)

    monkeypatch.setattr(module, "workflow_results_settings_gate", settings_gate)
    monkeypatch.setattr(module, "workflow_results_gate", role_gate)
    monkeypatch.setattr(module, "refresh_workflow_planning_privacy", refresh_privacy)
    monkeypatch.setattr(module, "_read_conversation", read_conversation)
    monkeypatch.setattr(module, "_read_workflow", read_workflow)
    monkeypatch.setattr(module, "_query_runs", query_runs)
    monkeypatch.setattr(module, "_read_result", reader)
    return calls


def run_step(module, monkeypatch, *, service=None, wf_planning=None, current_step=None, **stubs):
    service = service or ResultService()
    wf_planning = wf_planning if wf_planning is not None else planning()
    calls = install_runtime_stubs(module, monkeypatch, wf_planning=wf_planning, **stubs)
    outcome = module.run_workflow_results(
        current_step or step(),
        context(service, wf_planning),
        settings=deepcopy(SETTINGS),
        user_id=USER_ID,
    )
    return outcome, service, calls


def retained_value(outcome="read", *, run_id=RUN_ID, workflow_id=WORKFLOW_ID, name=WORKFLOW_NAME,
                   completed_at="2025-01-06T14:05:00+00:00", status="completed", context_value="default"):
    if context_value == "default" and outcome == "read":
        context_value = {"workflow_id": workflow_id, "run_id": run_id, "result_sha256": RESULT_SHA}
    return {
        "version": 1,
        "outcome": outcome,
        "reason": None if outcome == "read" else f"workflow_result_{outcome}",
        "workflow_name": name,
        "status": status,
        "completed_at": completed_at,
        "partial": False,
        "truncated": False,
        "newer_in_progress": False,
        "context": context_value if outcome == "read" else None,
    }


def assert_no_public_leak(value, forbidden):
    exposed = json.dumps(value, default=str)
    for secret in forbidden:
        assert secret not in exposed


@pytest.mark.parametrize("scenario", [
    "settings_gate",
    "role_gate",
    "missing_conversation",
    "foreign_conversation",
    "deleted_conversation",
    "shared_after_refresh",
    "not_ready",
    "unknown_handle",
    "workflow_id_mismatch",
    "workflow_user_mismatch",
    "workflow_deleting",
    "workflow_group",
])
def test_runtime_access_chain_fails_closed_before_query_or_result_read(results, monkeypatch, scenario):
    wf_plan = planning()
    conversation = {"id": CONVERSATION_ID, "user_id": USER_ID}
    workflow = {"id": WORKFLOW_ID, "user_id": USER_ID, "name": WORKFLOW_NAME}
    settings_reason = None
    role_reason = None
    current_step = step()
    refresh = None

    if scenario == "settings_gate":
        settings_reason = "workflow_results_disabled"
    elif scenario == "role_gate":
        role_reason = "workflow_role_required"
    elif scenario == "missing_conversation":
        conversation = None
    elif scenario == "foreign_conversation":
        conversation = {"id": CONVERSATION_ID, "user_id": OTHER_USER_ID}
    elif scenario == "deleted_conversation":
        conversation = {"id": CONVERSATION_ID, "user_id": USER_ID, "orchestration_deleted": True}
    elif scenario == "shared_after_refresh":
        def refresh(current, current_conversation, user_id):
            refreshed = deepcopy(current)
            refreshed["conversation_private"] = False
            return refreshed
    elif scenario == "not_ready":
        wf_plan = planning(ready=False)
    elif scenario == "unknown_handle":
        current_step = step("workflow_unknown_handle")
    elif scenario == "workflow_id_mismatch":
        workflow = {"id": OTHER_WORKFLOW_ID, "user_id": USER_ID, "name": WORKFLOW_NAME}
    elif scenario == "workflow_user_mismatch":
        workflow = {"id": WORKFLOW_ID, "user_id": OTHER_USER_ID, "name": WORKFLOW_NAME}
    elif scenario == "workflow_deleting":
        workflow = {"id": WORKFLOW_ID, "user_id": USER_ID, "name": WORKFLOW_NAME, "deleting": True}
    elif scenario == "workflow_group":
        workflow = {"id": WORKFLOW_ID, "user_id": USER_ID, "name": WORKFLOW_NAME, "group_id": "group-secret"}
    calls = install_runtime_stubs(
        results,
        monkeypatch,
        wf_planning=wf_plan,
        conversation=conversation,
        workflow=workflow,
        settings_reason=settings_reason,
        role_reason=role_reason,
        refresh=refresh,
    )
    service = ResultService()

    outcome = results.run_workflow_results(current_step, context(service, wf_plan), settings=SETTINGS, user_id=USER_ID)

    assert outcome["status"] == "completed"
    assert outcome["summary"] == results.NO_WORKFLOW_RESULT_READ
    assert outcome["workflow_results"]["outcome"] == results.WORKFLOW_RESULTS_OUTCOME_UNAVAILABLE
    assert calls["queries"] == []
    assert calls["reader"] == []
    if scenario == "role_gate":
        assert calls["role_gate"] == [(SETTINGS, ["User"])]
    if scenario == "shared_after_refresh":
        assert calls["refresh"] and outcome["workflow_results"]["reason"] == "workflow_shared_conversation"


def test_completed_run_reads_notes_context_and_uses_budget_without_evidence(results, monkeypatch):
    service = ResultService()
    completed_at = "2025-01-06T14:05:00+00:00"
    row = completed_run(completed_at=completed_at)
    output, service, calls = run_step(results, monkeypatch, service=service, latest_rows=[row])

    sidecar = output["workflow_results"]
    persisted = service.persisted[0]
    retained = persisted["outputs"][0][2]
    public_output = {key: value for key, value in output.items() if key not in {"workflow_results", "task_result"}}
    note = results.workflow_results_note(
        {"steps": [step()]}, [{**output, "step_id": step()["step_id"], "capability_id": "workflow_results"}],
        time_zone=LOCAL_ZONE,
    )

    assert output["status"] == "completed"
    assert output["summary"] == "Read a saved workflow result."
    assert sidecar["outcome"] == results.WORKFLOW_RESULTS_OUTCOME_READ
    assert sidecar["context"] == {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": RESULT_SHA}
    assert calls["reader"] == [(USER_ID, WORKFLOW_ID, RUN_ID, {
        "include_excerpts": True,
        "excerpt_budget_bytes": results.WORKFLOW_RESULTS_EXCERPT_BUDGET_BYTES,
    })]
    assert results.WORKFLOW_RESULTS_EXCERPT_BUDGET_BYTES == 24 * 1024
    assert persisted["sources"] == [] and persisted["origin"] == "generated"
    assert output["evidence"] == [] and output["citations"] == []
    assert "grounded" not in output and "origin" not in output
    assert note is not None and WORKFLOW_NAME in note and "Jan" in note
    assert_no_public_leak(public_output, [WORKFLOW_ID, RUN_ID, USER_ID, HANDLE, EXCERPT_MARKER])
    assert_no_public_leak(note, [WORKFLOW_ID, RUN_ID, USER_ID, HANDLE, EXCERPT_MARKER])
    assert EXCERPT_MARKER not in json.dumps(retained, default=str)


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_or_cancelled_run_is_status_only_and_never_reads_text(results, monkeypatch, status):
    row = completed_run(status=status, completed_at="2025-01-06T15:05:00+00:00")
    output, _service, calls = run_step(results, monkeypatch, latest_rows=[row])
    note = results.workflow_results_note(
        {"steps": [step()]}, [{**output, "step_id": step()["step_id"], "capability_id": "workflow_results"}],
        time_zone=LOCAL_ZONE,
    )

    assert output["workflow_results"]["outcome"] == results.WORKFLOW_RESULTS_OUTCOME_STATUS_ONLY
    assert output["workflow_results"]["status"] == status
    assert calls["reader"] == []
    assert note is not None and WORKFLOW_NAME in note and status in note and EXCERPT_MARKER not in note
    assert_no_public_leak(note, [WORKFLOW_ID, RUN_ID, USER_ID, HANDLE, EXCERPT_MARKER])


@pytest.mark.parametrize("reader_error,outcome", [
    (FakeWorkflowResultUnavailable("workflow_result_unsupported"), "unsupported"),
    (FakeWorkflowResultUnavailable("workflow_result_in_progress"), "in_progress"),
    (FakeWorkflowResultUnavailable("workflow_result_not_found"), "unavailable"),
])
def test_reader_closed_reasons_map_to_completed_step_explanations(results, monkeypatch, reader_error, outcome):
    row = completed_run()
    output, _service, _calls = run_step(results, monkeypatch, latest_rows=[row], read_result=reader_error)

    assert output["status"] == "completed"
    assert output["workflow_results"]["outcome"] == outcome
    assert output["summary"] == results.NO_WORKFLOW_RESULT_READ
    assert output["failure"] is None


def test_analysis_run_and_in_progress_and_no_match_outcomes(results, monkeypatch):
    analysis_output, _service, _calls = run_step(
        results,
        monkeypatch,
        latest_rows=[completed_run()],
        read_result=result_payload(analysis_only=True),
    )
    in_progress_output, _service, _calls = run_step(
        results,
        monkeypatch,
        latest_rows=[],
        in_progress_rows=[{"id": OTHER_RUN_ID, "status": "running", "started_at": "2025-01-06T16:00:00+00:00"}],
    )
    no_match_output, _service, _calls = run_step(results, monkeypatch, latest_rows=[], in_progress_rows=[])

    assert analysis_output["workflow_results"]["outcome"] == results.WORKFLOW_RESULTS_OUTCOME_ANALYSIS_ONLY
    # The reply points at a surface that exists without Phase 6b: Ask in chat on the run history.
    assert "Ask in chat" in results.WORKFLOW_RESULTS_REASON_TEXT["workflow_result_analysis_only"]
    assert in_progress_output["workflow_results"]["outcome"] == results.WORKFLOW_RESULTS_OUTCOME_IN_PROGRESS
    assert no_match_output["workflow_results"]["outcome"] == results.WORKFLOW_RESULTS_OUTCOME_NO_MATCH


@pytest.mark.parametrize("query_error,expected_code", [
    (RuntimeError("workflow_results_unavailable"), "workflow_results_unavailable"),
    (RuntimeError(QUERY_SECRET), "step_failed"),
])
def test_query_storage_errors_fail_retryably_or_safely_not_as_no_runs(results, monkeypatch, query_error, expected_code):
    if str(query_error) == "workflow_results_unavailable":
        query_error = results._StepFailure("workflow_results_unavailable")
    output, _service, _calls = run_step(results, monkeypatch, query_error=query_error)
    exposed = json.dumps(output, default=str)

    assert output["status"] == "failed"
    assert output["failure"]["code"] == expected_code
    assert results.WORKFLOW_RESULTS_OUTCOME_NO_MATCH not in exposed
    assert QUERY_SECRET not in exposed


def test_query_shapes_are_bounded_projected_partitioned_and_errors_raise(results, monkeypatch):
    captured = []

    def query(user_id, query_text, parameters):
        captured.append((user_id, query_text, deepcopy(parameters)))
        return []

    monkeypatch.setattr(results, "_query_runs", query)
    latest = results._select_latest(USER_ID, WORKFLOW_ID, None)
    monkeypatch.setattr(results, "_utc_now", lambda: datetime(2025, 1, 8, 12, 0, tzinfo=timezone.utc))
    completed = results._select_completed_on(USER_ID, WORKFLOW_ID, None, "2025-01-06", LOCAL_ZONE)
    monkeypatch.setattr(results, "_query_runs", lambda user_id, query_text, parameters: (_ for _ in ()).throw(RuntimeError(QUERY_SECRET)))

    with pytest.raises(RuntimeError):
        results._select_latest(USER_ID, WORKFLOW_ID, None)

    assert latest[2] == results.WORKFLOW_RESULTS_OUTCOME_NO_MATCH
    assert completed[2] == results.WORKFLOW_RESULTS_OUTCOME_NO_MATCH
    assert len(captured) >= 3
    latest_query = captured[0]
    completed_query = next(item for item in captured if item[1] == results._COMPLETED_ON_QUERY)
    for user_id, query_text, params in (latest_query, completed_query):
        assert user_id == USER_ID
        assert "SELECT TOP" in query_text
        assert "c.id, c.workflow_id, c.status, c.started_at, c.completed_at" in query_text
        assert "c.user_id = @user_id" in query_text
        assert {param["name"]: param["value"] for param in params}["@user_id"] == USER_ID
    assert "ORDER BY c.started_at DESC" in latest_query[1]
    assert "@lo" in completed_query[1] and "@hi" in completed_query[1]
    assert "c.completed_at >= @lo" in completed_query[1]
    assert "c.completed_at < @hi" in completed_query[1]


def test_storage_backed_query_run_errors_raise_instead_of_looking_empty(results, monkeypatch):
    import config
    from azure.cosmos.exceptions import CosmosHttpResponseError

    class FailingRuns:
        def query_items(self, query, parameters, partition_key):
            raise CosmosHttpResponseError(status_code=503, message=QUERY_SECRET)

    monkeypatch.setattr(config, "cosmos_personal_workflow_runs_container", FailingRuns(), raising=False)

    with pytest.raises(results._StepFailure) as caught:
        results._query_runs(USER_ID, results._LATEST_QUERY, [])

    assert caught.value.code == "workflow_results_unavailable"


def test_timestamp_parsing_day_windows_and_local_date_selection(results, monkeypatch):
    zulu = results._parse_utc("2025-01-06T05:00:00Z")
    offset = results._parse_utc("2025-01-06T05:00:00+00:00")
    naive = results._parse_utc("2025-01-06T05:00:00")
    monkeypatch.setattr(results, "_utc_now", lambda: datetime(2025, 1, 8, 12, 0, tzinfo=timezone.utc))
    lo, hi, _zone = results._day_bounds(datetime(2025, 1, 6).date(), LOCAL_ZONE)
    rows = [
        completed_run("bad-row", completed_at="not-a-date"),
        completed_run("midnight", completed_at="2025-01-06T05:00:00Z"),
        completed_run("evening", completed_at="2025-01-07T02:30:00Z"),
    ]
    calls = install_runtime_stubs(results, monkeypatch, completed_rows=rows)
    selected_6 = results._select_completed_on(USER_ID, WORKFLOW_ID, None, "2025-01-06", LOCAL_ZONE)
    selected_7 = results._select_completed_on(USER_ID, WORKFLOW_ID, None, "2025-01-07", LOCAL_ZONE)

    assert zulu == offset == naive == datetime(2025, 1, 6, 5, 0, tzinfo=timezone.utc)
    assert lo == "2025-01-06T04:59:00+00:00" and hi == "2025-01-07T05:01:00+00:00"
    assert selected_6[0]["id"] == "midnight"
    assert selected_6[2] is None
    assert selected_7[0] is None and selected_7[2] == results.WORKFLOW_RESULTS_OUTCOME_NO_MATCH
    assert any(param["name"] == "@lo" and param["value"] == lo for param in calls["queries"][0][2])


def test_latest_skips_unparseable_rows_missing_started_at_sorts_last_and_full_bad_page_fails_closed(results, monkeypatch):
    valid = completed_run("newer-valid", started_at="2025-01-06T16:00:00+00:00")
    missing_started = completed_run("missing-started")
    invalid_completed = completed_run("invalid-completed", completed_at="not-a-date")
    install_runtime_stubs(results, monkeypatch, latest_rows=[invalid_completed, valid, missing_started])
    selected = results._select_latest(USER_ID, WORKFLOW_ID, None)
    bad_rows = [completed_run(f"bad-{index}", completed_at="not-a-date") for index in range(5)]
    install_runtime_stubs(results, monkeypatch, latest_rows=bad_rows)
    full_bad_page = results._select_latest(USER_ID, WORKFLOW_ID, None)

    assert selected[0]["id"] == "newer-valid"
    assert full_bad_page[0] is None
    assert full_bad_page[2] == results.WORKFLOW_RESULTS_OUTCOME_UNAVAILABLE


def test_step_summary_and_events_never_include_excerpt_text(results, monkeypatch):
    emitted = []
    current_step = step()
    output, service, _calls = run_step(
        results,
        monkeypatch,
        service=ResultService(),
        latest_rows=[completed_run()],
        current_step=current_step,
    )
    emitted.append({"summary": output.get("summary"), "message": output.get("message"), "error": output.get("error")})
    persisted = service.persisted[0]["outputs"][0][2]
    public_output = {key: value for key, value in output.items() if key not in {"workflow_results", "task_result"}}

    assert EXCERPT_MARKER not in json.dumps(public_output, default=str)
    assert EXCERPT_MARKER not in json.dumps(emitted, default=str)
    assert EXCERPT_MARKER not in json.dumps(persisted, default=str)
    assert output["summary"] == "Read a saved workflow result."


class ComposeReader:
    def __init__(self, value, capability_id="workflow_results"):
        self.value = deepcopy(value)
        self.reference = SimpleNamespace(producer=SimpleNamespace(capability_id=capability_id))

    def read_value(self):
        return deepcopy(self.value)


def test_compose_inputs_refence_each_read_with_fresh_nonces_and_no_marker_outside_fences(results, monkeypatch):
    nonce_values = iter(["0000000000000001", "0000000000000002", "0000000000000003", "0000000000000004"])
    monkeypatch.setattr(results, "_new_nonce", lambda: next(nonce_values))
    calls = []

    def read_result(user_id, workflow_id, run_id, **options):
        calls.append((user_id, workflow_id, run_id, deepcopy(options)))
        return result_payload(run_id=run_id, marker=f"{EXCERPT_MARKER}_{run_id}")

    monkeypatch.setattr(results, "_read_result", read_result)
    value_1 = retained_value(run_id=RUN_ID)
    value_2 = retained_value(run_id=OTHER_RUN_ID)
    readers = {"first": ComposeReader(value_1), "second": ComposeReader(value_2)}
    inputs, system_message = results.workflow_results_compose_inputs(readers, {}, user_id=USER_ID, time_zone=LOCAL_ZONE)
    inputs_again, system_message_again = results.workflow_results_compose_inputs({"first": ComposeReader(value_1)}, {}, user_id=USER_ID, time_zone=LOCAL_ZONE)

    first_text = inputs["first"]["value"]
    second_text = inputs["second"]["value"]
    assert "0000000000000001" in first_text and "0000000000000002" in second_text
    assert "0000000000000001" != "0000000000000002"
    assert "0000000000000003" in inputs_again["first"]["value"]
    assert "0000000000000001" in system_message and "0000000000000002" in system_message
    assert "0000000000000003" in system_message_again
    assert EXCERPT_MARKER not in system_message
    assert first_text.count(f"{EXCERPT_MARKER}_{RUN_ID}") == 1
    assert second_text.count(f"{EXCERPT_MARKER}_{OTHER_RUN_ID}") == 1
    assert calls[0][3]["expected_sha256"] == RESULT_SHA
    assert calls[0][3]["excerpt_budget_bytes"] == results.WORKFLOW_RESULTS_EXCERPT_BUDGET_BYTES


def test_compose_rejects_changed_or_unauthorized_result_without_exposing_excerpt(results, monkeypatch):
    monkeypatch.setattr(results, "_new_nonce", lambda: "0000000000000001")
    monkeypatch.setattr(results, "_read_result", lambda *args, **kwargs: (_ for _ in ()).throw(
        FakeWorkflowResultUnavailable("workflow_result_changed")
    ))
    readers = {"notes": ComposeReader(retained_value())}

    with pytest.raises(results.WorkflowResultsComposeError) as caught:
        results.workflow_results_compose_inputs(readers, {"notes": {"value": "original"}}, user_id=USER_ID, time_zone=LOCAL_ZONE)

    assert caught.value.code == "workflow_result_changed"
    assert EXCERPT_MARKER not in str(caught.value)


def test_compose_defends_against_nonce_reuse_by_requesting_another_nonce(results, monkeypatch):
    nonce_values = iter(["0000000000000001", "0000000000000001", "0000000000000002"])
    monkeypatch.setattr(results, "_new_nonce", lambda: next(nonce_values))
    monkeypatch.setattr(results, "_read_result", lambda user_id, workflow_id, run_id, **options: result_payload(run_id=run_id))
    readers = {"first": ComposeReader(retained_value(run_id=RUN_ID)), "second": ComposeReader(retained_value(run_id=OTHER_RUN_ID))}

    inputs, _system_message = results.workflow_results_compose_inputs(readers, {}, user_id=USER_ID, time_zone=LOCAL_ZONE)

    assert "0000000000000001" in inputs["first"]["value"]
    assert "0000000000000002" in inputs["second"]["value"]


def test_rebuild_reauthorizes_context_and_fails_closed_for_changed_or_malformed_sidecar(results, monkeypatch):
    wf_plan = planning()
    calls = install_runtime_stubs(results, monkeypatch, wf_planning=wf_plan)
    authorized = []
    monkeypatch.setattr(results, "_authorize_result_context", lambda user_id, ctx, **options: authorized.append((user_id, deepcopy(ctx))))
    monkeypatch.setattr(
        results,
        "build_step_result",
        lambda status, summary, task_result=None, **kwargs: {
            "status": status,
            "summary": summary,
            "task_result": task_result,
            "evidence": [],
            "citations": [],
            "artifacts": [],
            "notes": [],
            "error": None,
            "failure": None,
        },
    )
    service = ResultService(value=retained_value())
    ctx = context(service, wf_plan)
    task = SimpleNamespace(output=lambda name: f"reference:{name}")
    rebuilt = results.rebuild_workflow_results(step(), ctx, user_id=USER_ID, task=task)

    monkeypatch.setattr(results, "_authorize_result_context", lambda user_id, ctx, **options: (_ for _ in ()).throw(
        FakeWorkflowResultUnavailable("workflow_result_changed")
    ))
    changed_service = ResultService(value=retained_value())
    changed = results.rebuild_workflow_results(step(), context(changed_service, wf_plan), user_id=USER_ID, task=task)
    malformed_service = ResultService(value=retained_value(context_value=None))
    malformed = results.rebuild_workflow_results(step(), context(malformed_service, wf_plan), user_id=USER_ID, task=task)

    assert rebuilt is not None and rebuilt["workflow_results"]["outcome"] == "read"
    assert authorized == [(USER_ID, {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": RESULT_SHA})]
    assert service.opened == [("reference:result", False)]
    assert calls["queries"] == []
    assert changed is None
    assert malformed is None


def test_logs_and_user_visible_failures_are_sanitized(results, monkeypatch, caplog):
    log_calls = []
    appinsights_calls = []
    original_log = results._log

    def captured_log(message, level=logging.INFO, **fields):
        log_calls.append((message, level, deepcopy(fields)))
        return original_log(message, level, **fields)

    monkeypatch.setattr(results, "_log", captured_log)
    monkeypatch.setattr(results, "log_event", lambda message, **kwargs: appinsights_calls.append((message, deepcopy(kwargs))))
    caplog.set_level(logging.INFO)
    output, _service, _calls = run_step(results, monkeypatch, latest_rows=[completed_run()])
    failure, _service, _calls = run_step(results, monkeypatch, query_error=RuntimeError(QUERY_SECRET))
    all_logged = json.dumps({"log": log_calls, "appinsights": appinsights_calls, "records": [r.getMessage() for r in caplog.records]}, default=str)
    user_visible = json.dumps({
        "success": {key: value for key, value in output.items() if key != "workflow_results"},
        "failure": failure,
    }, default=str)

    for forbidden in (EXCERPT_MARKER, WORKFLOW_NAME, HANDLE, results._LATEST_QUERY, QUERY_SECRET):
        assert forbidden not in all_logged
    for forbidden in (EXCERPT_MARKER, QUERY_SECRET):
        assert forbidden not in user_visible
    assert failure["failure"]["message"] == "This operation could not complete."


if __name__ == "__main__":
    sys.exit(pytest.main(["-q", __file__]))
