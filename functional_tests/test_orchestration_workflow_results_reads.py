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

HARNESS_MODULES_FIXTURE = modules


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
            def read_value(self):
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


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def require_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def require_is(actual, expected, message):
    if actual is not expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


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
    refresh_callback = None

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
        def refresh_after_share(current, current_conversation, user_id):
            refreshed = deepcopy(current)
            refreshed["conversation_private"] = False
            return refreshed
        refresh_callback = refresh_after_share
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
        refresh=refresh_callback,
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
    missing_started.pop("started_at")
    invalid_completed = completed_run("invalid-completed", completed_at="not-a-date")
    # Cosmos DB orders an undefined sort property lowest, so a row without started_at comes last under DESC.
    install_runtime_stubs(results, monkeypatch, latest_rows=[invalid_completed, valid, missing_started])
    selected = results._select_latest(USER_ID, WORKFLOW_ID, None)
    in_progress = {"id": "running", "status": "running", "started_at": "2025-01-06T18:00:00+00:00"}
    install_runtime_stubs(
        results, monkeypatch, latest_rows=[invalid_completed, missing_started], in_progress_rows=[in_progress],
    )
    lone_missing_started = results._select_latest(USER_ID, WORKFLOW_ID, None)
    bad_rows = [completed_run(f"bad-{index}", completed_at="not-a-date") for index in range(5)]
    install_runtime_stubs(results, monkeypatch, latest_rows=bad_rows)
    full_bad_page = results._select_latest(USER_ID, WORKFLOW_ID, None)

    assert "started_at" not in missing_started
    assert selected[0]["id"] == "newer-valid"
    assert lone_missing_started[0]["id"] == "missing-started"
    assert lone_missing_started[1] is False
    assert lone_missing_started[2] is None
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


def test_completed_on_rejects_dates_outside_runtime_window_without_query(results, monkeypatch):
    calls = []
    today = results._local_today(LOCAL_ZONE)
    future_day = (today + results.timedelta(days=1)).isoformat()
    expired_day = (today - results.timedelta(days=367)).isoformat()

    def query_runs(user_id, query, parameters):
        calls.append((user_id, query, deepcopy(parameters)))
        return []

    monkeypatch.setattr(results, "_query_runs", query_runs)
    future = results._select_completed_on(USER_ID, WORKFLOW_ID, None, future_day, LOCAL_ZONE)
    expired = results._select_completed_on(USER_ID, WORKFLOW_ID, None, expired_day, LOCAL_ZONE)

    require_equal(future, (None, False, results.WORKFLOW_RESULTS_OUTCOME_NO_MATCH), "future date outcome")
    require_equal(expired, (None, False, results.WORKFLOW_RESULTS_OUTCOME_NO_MATCH), "expired date outcome")
    require_equal(calls, [], "out-of-window completed_on must not query")


def test_point_reads_raise_retryable_failure_for_cosmos_errors_and_not_found_is_none(results, monkeypatch):
    import config
    from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

    class FailingContainer:
        def __init__(self, error):
            self.error = error

        def read_item(self, item, partition_key):
            raise self.error

    transient_error = CosmosHttpResponseError(status_code=503, message=QUERY_SECRET)
    not_found = CosmosResourceNotFoundError(status_code=404, message="missing")

    monkeypatch.setattr(config, "cosmos_conversations_container", FailingContainer(transient_error), raising=False)
    with pytest.raises(results._StepFailure) as conversation_failure:
        results._read_conversation(CONVERSATION_ID)

    monkeypatch.setattr(config, "cosmos_personal_workflows_container", FailingContainer(transient_error), raising=False)
    with pytest.raises(results._StepFailure) as workflow_failure:
        results._read_workflow(USER_ID, WORKFLOW_ID)

    monkeypatch.setattr(config, "cosmos_conversations_container", FailingContainer(not_found), raising=False)
    missing_conversation = results._read_conversation(CONVERSATION_ID)
    monkeypatch.setattr(config, "cosmos_personal_workflows_container", FailingContainer(not_found), raising=False)
    missing_workflow = results._read_workflow(USER_ID, WORKFLOW_ID)

    require_equal(conversation_failure.value.code, "workflow_results_unavailable", "conversation failure code")
    require_equal(workflow_failure.value.code, "workflow_results_unavailable", "workflow failure code")
    require_is(missing_conversation, None, "missing conversation")
    require_is(missing_workflow, None, "missing workflow")


def test_storage_backed_query_uses_user_partition_key(results, monkeypatch):
    import config

    captured = []

    class CapturingRuns:
        def query_items(self, query, parameters, partition_key):
            captured.append((query, deepcopy(parameters), partition_key))
            return []

    monkeypatch.setattr(config, "cosmos_personal_workflow_runs_container", CapturingRuns(), raising=False)

    rows = results._query_runs(USER_ID, results._LATEST_QUERY, [])

    require_equal(rows, [], "query rows")
    require_equal(len(captured), 1, "query call count")
    require_equal(captured[0][2], USER_ID, "query partition key")


def test_completed_on_skips_margin_rows_from_the_wrong_local_day(results, monkeypatch):
    monkeypatch.setattr(results, "_utc_now", lambda: datetime(2025, 1, 8, 12, 0, tzinfo=timezone.utc))
    margin_row = completed_run("margin-next-day", completed_at="2025-01-07T05:00:30Z")
    in_day_row = completed_run("in-day", completed_at="2025-01-06T20:00:00Z")
    install_runtime_stubs(results, monkeypatch, completed_rows=[margin_row, in_day_row])
    selected = results._select_completed_on(USER_ID, WORKFLOW_ID, None, "2025-01-06", LOCAL_ZONE)
    install_runtime_stubs(results, monkeypatch, completed_rows=[margin_row])
    margin_only = results._select_completed_on(USER_ID, WORKFLOW_ID, None, "2025-01-06", LOCAL_ZONE)

    require_equal(selected[0]["id"], "in-day", "completed_on selected row")
    require_is(selected[2], None, "completed_on selected reason")
    require_equal(margin_only, (None, False, results.WORKFLOW_RESULTS_OUTCOME_NO_MATCH), "margin-only outcome")


def test_completed_on_full_bad_page_fails_closed_but_short_bad_page_is_no_match(results, monkeypatch):
    monkeypatch.setattr(results, "_utc_now", lambda: datetime(2025, 1, 8, 12, 0, tzinfo=timezone.utc))
    wrong_day_rows = [
        completed_run(f"margin-next-day-{index}", completed_at="2025-01-07T05:00:30Z")
        for index in range(20)
    ]
    install_runtime_stubs(results, monkeypatch, completed_rows=wrong_day_rows)
    full_bad_page = results._select_completed_on(USER_ID, WORKFLOW_ID, None, "2025-01-06", LOCAL_ZONE)
    install_runtime_stubs(results, monkeypatch, completed_rows=wrong_day_rows[:19])
    short_bad_page = results._select_completed_on(USER_ID, WORKFLOW_ID, None, "2025-01-06", LOCAL_ZONE)

    require_equal(
        full_bad_page, (None, False, results.WORKFLOW_RESULTS_OUTCOME_UNAVAILABLE), "full bad page outcome",
    )
    require_equal(
        short_bad_page, (None, False, results.WORKFLOW_RESULTS_OUTCOME_NO_MATCH), "short bad page outcome",
    )


def test_latest_marks_only_later_in_progress_runs_as_newer(results, monkeypatch):
    chosen = completed_run("chosen", started_at="2025-01-06T14:00:00+00:00")
    later_probe = {"id": "later", "status": "running", "started_at": "2025-01-06T15:00:00+00:00"}
    earlier_probe = {"id": "earlier", "status": "running", "started_at": "2025-01-06T13:00:00+00:00"}
    install_runtime_stubs(results, monkeypatch, latest_rows=[chosen], in_progress_rows=[later_probe])
    later = results._select_latest(USER_ID, WORKFLOW_ID, None)
    install_runtime_stubs(results, monkeypatch, latest_rows=[chosen], in_progress_rows=[earlier_probe])
    earlier = results._select_latest(USER_ID, WORKFLOW_ID, None)

    require_equal(later[0]["id"], "chosen", "later selected row")
    require_is(later[1], True, "later probe newer flag")
    require_equal(earlier[0]["id"], "chosen", "earlier selected row")
    require_is(earlier[1], False, "earlier probe newer flag")


@pytest.mark.parametrize("sidecar", [
    retained_value(outcome="no_match"),
    retained_value(outcome="status_only", status="failed"),
    retained_value(),
])
@pytest.mark.parametrize("closed_reason", [
    "workflow_deleting",
    "shared_after_refresh",
    "settings_gate",
    "role_gate",
])
def test_rebuild_returns_none_when_access_has_closed_since_original_read(
    results, monkeypatch, sidecar, closed_reason,
):
    wf_plan = planning()
    workflow = {"id": WORKFLOW_ID, "user_id": USER_ID, "name": WORKFLOW_NAME}
    settings_reason = None
    role_reason = None
    refresh_callback = None
    authorized = []

    if closed_reason == "workflow_deleting":
        workflow["deleting"] = True
    elif closed_reason == "shared_after_refresh":
        def refresh_after_share(current, current_conversation, user_id):
            refreshed = deepcopy(current)
            refreshed["conversation_private"] = False
            return refreshed
        refresh_callback = refresh_after_share
    elif closed_reason == "settings_gate":
        settings_reason = "workflow_results_disabled"
    elif closed_reason == "role_gate":
        role_reason = "workflow_role_required"

    install_runtime_stubs(
        results,
        monkeypatch,
        wf_planning=wf_plan,
        workflow=workflow,
        settings_reason=settings_reason,
        role_reason=role_reason,
        refresh=refresh_callback,
    )
    monkeypatch.setattr(results, "_authorize_result_context", lambda user_id, ctx, **options: authorized.append(ctx))
    service = ResultService(value=sidecar)
    task = SimpleNamespace(output=lambda name: f"reference:{name}")

    rebuilt = results.rebuild_workflow_results(step(), context(service, wf_plan), user_id=USER_ID, task=task)

    require_is(rebuilt, None, "rebuild result after closed access")
    require_equal(authorized, [], "authorization calls after closed access")


def test_reader_storage_unavailable_fails_step_retryably(results, monkeypatch):
    output, _service, _calls = run_step(
        results,
        monkeypatch,
        latest_rows=[completed_run()],
        read_result=FakeWorkflowResultUnavailable("workflow_result_storage_unavailable"),
    )

    require_equal(output["status"], "failed", "storage-unavailable step status")
    require_equal(output["failure"]["code"], "workflow_results_unavailable", "storage-unavailable failure code")


def test_saved_inputs_force_analysis_only_without_retained_context_or_excerpt(results, monkeypatch):
    payload = result_payload(analysis_only=False, saved_inputs=[{"name": "private input"}])
    output, service, _calls = run_step(results, monkeypatch, latest_rows=[completed_run()], read_result=payload)
    persisted = service.persisted[0]["outputs"][0][2]
    exposed = json.dumps({"output": output, "persisted": persisted}, default=str)

    require_equal(output["status"], "completed", "saved-inputs step status")
    require_equal(
        output["workflow_results"]["outcome"],
        results.WORKFLOW_RESULTS_OUTCOME_ANALYSIS_ONLY,
        "saved-inputs public outcome",
    )
    require_is(output["workflow_results"]["context"], None, "saved-inputs public context")
    require_equal(persisted["outcome"], results.WORKFLOW_RESULTS_OUTCOME_ANALYSIS_ONLY, "saved-inputs retained outcome")
    require_is(persisted["context"], None, "saved-inputs retained context")
    require(EXCERPT_MARKER not in exposed, "saved-inputs outcome leaked excerpt text")


def test_workflow_results_step_rechecks_cancellation_after_read_before_persisting(results, monkeypatch):
    service = ResultService()
    wf_plan = planning()
    ctx = context(service, wf_plan)
    cancelled = {"value": False}

    def read_step(current_step, current_context, *, settings, user_id):
        cancelled["value"] = True
        return retained_value(outcome="no_match")

    monkeypatch.setattr(results, "_read_workflow_result_step", read_step)

    with pytest.raises(results.MixedSourceCancellationError):
        results.run_workflow_results(
            step(),
            ctx,
            settings=deepcopy(SETTINGS),
            user_id=USER_ID,
            cancel_requested=lambda: cancelled["value"],
        )

    require_equal(service.persisted, [], "cancelled attempt must not persist")


if __name__ == "__main__":
    sys.exit(pytest.main(["-q", __file__]))
