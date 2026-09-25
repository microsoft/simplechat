# test_orchestration_harness_scheduler.py
"""Bounded scheduler queries, real claims, publication and headless loop integration.

Version: 0.261.139
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139
Production scheduler/continuation/runner/state machines run with external I/O doubled.
Owner modules are imported inside fixture-backed tests after offline initialization.
"""

import importlib
import json
import re
import subprocess
import sys
import threading
from copy import copy, deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from azure.core.exceptions import AzureError, ServiceRequestError


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"

# Scoped path bootstrap permits standalone execution without retaining global changes.
with patch.object(sys, "path", [str(APP), *sys.path]):
    import functions_orchestration_scheduler as scheduler
    from test_orchestration_continuation import (
        harness, initialized_continuation, replace_record, saved_composition,
    )


class DueQueryContainer:
    """External Cosmos query double; real point reads and CAS remain on the owner."""

    def __init__(self, container):
        self.container = container
        self.calls = []
        self.fail = set()
        self.override = None

    def query_items(self, query, parameters=None, **kwargs):
        parameters = parameters or []
        values = {value["name"]: value["value"] for value in parameters}
        is_output = values.get("@record_type") == "orchestration_output_v1"
        is_cleanup = "c.output_cleanup.state" in query
        kind = "outputs" if is_output else "cleanup_runs" if is_cleanup else "runs"
        self.calls.append((kind, query, deepcopy(parameters), kwargs))
        if kind in self.fail:
            raise AzureError("PRIVATE_PROVIDER_QUERY_FAILURE")
        if self.override is not None:
            return self.override(kind)
        now = None if is_cleanup else datetime.fromisoformat(values["@now"])
        rows = []
        for item in self.container.items.values():
            if is_output:
                if item.get("record_type") != "orchestration_output_v1":
                    continue
                state = item["state"]
                due = (
                    state in {"waiting", "retry_scheduled"} and (
                        item.get("next_retry_at") is None
                        or datetime.fromisoformat(item["next_retry_at"]) <= now
                    )
                ) or (
                    state == "rendering" and datetime.fromisoformat(item["lease"]["expires_at"]) <= now
                ) or (
                    state in {"completed", "failed", "cancelled"} and item.get("cleanup_pending")
                    and datetime.fromisoformat(item["cleanup_after"]) <= now
                )
            elif is_cleanup:
                cleanup = item.get("output_cleanup")
                due = (
                    item.get("record_type") in {"run", "orchestration_run"}
                    and (item.get("plan") or {}).get("planner_contract_version") == 2
                    and item.get("checkpoints_deleted") is True
                    and type(cleanup) is dict and type(cleanup.get("version")) is int
                    and cleanup["version"] == 1 and cleanup.get("state") == "pending"
                )
            else:
                if (
                    item.get("record_type") not in {"run", "orchestration_run"}
                    or item.get("planner_contract_version") != 2
                    or (item.get("plan") or {}).get("planner_contract_version") != 2
                    or not item.get("started_at") or item.get("checkpoints_deleted")
                    or item.get("outputs_deleted") or item.get("superseded_by_run_id")
                    or item.get("latest_attempt_run_id")
                ):
                    continue
                lease = item.get("execution_lease")
                if lease is not None and datetime.fromisoformat(lease["expires_at"]) > now:
                    continue
                due = item.get("status") in {"waiting", "running"} or (
                    item.get("status") in {"completed", "failed", "cancelled"}
                    and item.get("finalization_status") == "pending"
                )
            if due:
                rows.append(deepcopy(item))
        limit = int(re.search(r"SELECT TOP (\d+)", query).group(1))
        return sorted(rows, key=lambda row: row.get("updated_at", ""))[:limit]


def resources(harness, *, clock=None):
    queries = DueQueryContainer(harness.runs)
    logs = []
    value = scheduler.OrchestrationSchedulerResources(
        runs_container=queries, messages_container=harness.messages, settings=harness.settings,
        read_conversation=harness.bootstrap.read_owned_conversation,
        read_run=harness.revisions.read_revision_run,
        build_services=harness.bootstrap.build_orchestration_services,
        build_cleanup_service=harness.bootstrap.build_orchestration_cleanup_service,
        log=lambda message, **kwargs: logs.append((message, kwargs)),
        clock=clock or (lambda: datetime.now(timezone.utc)),
    )
    return value, queries, logs


def tick(harness, *, max_runs=4, max_outputs=8, clock=None):
    boundary, queries, logs = resources(harness, clock=clock)
    result = scheduler.check_due_orchestration_runs_once(
        max_runs=max_runs, max_outputs=max_outputs, resources=boundary,
    )
    return result, queries, logs


@pytest.mark.parametrize("limit", [1, 4, 17, 200])
def test_due_query_is_bounded_in_sql_and_iterator_consumption(limit):
    seen = []

    class Container:
        def query_items(self, **kwargs):
            self.call = kwargs

            def rows():
                for index in range(limit + 10):
                    seen.append(index)
                    yield {"id": f"run-{index}", "user_id": "owner", "conversation_id": "conversation-1"}

            return rows()

    container = Container()
    selected = scheduler.enumerate_due_runs(container, now=datetime(2030, 1, 1, tzinfo=timezone.utc), limit=limit)
    assert len(selected) == len(seen) == limit
    assert container.call["query"].startswith(f"SELECT TOP {limit} ")
    assert "c.planner_contract_version = 2" in container.call["query"]
    assert "c.plan.planner_contract_version = 2" in container.call["query"]
    assert 'c.finalization_status = "pending"' in container.call["query"]
    assert "c.latest_attempt_run_id = c.id" not in container.call["query"]
    assert container.call["max_item_count"] == limit
    assert container.call["enable_cross_partition_query"] is True
    assert all(set(value) == {"run_id", "user_id", "conversation_id"} for value in selected)


@pytest.mark.parametrize("limit", [1, 4, 32, 200])
def test_cleanup_enrollment_scan_bounds_the_actual_reader_and_returns_only_selectors(limit):
    consumed = []

    class Container:
        def query_items(self, **kwargs):
            self.call = kwargs

            def rows():
                for index in range(limit + 5):
                    consumed.append(index)
                    yield {
                        "id": f"deleted-run-{index}", "user_id": "owner",
                        "conversation_id": "conversation-1", "status": "untrusted",
                    }

            return rows()

    container = Container()
    selected = scheduler.enumerate_cleanup_enrollment_runs(container, limit=limit)
    assert len(selected) == len(consumed) == limit
    assert container.call["query"].startswith(f"SELECT TOP {limit} ")
    assert 'c.output_cleanup.state = "pending"' in container.call["query"]
    assert "c.checkpoints_deleted = true" in container.call["query"]
    assert container.call["max_item_count"] == limit
    assert all(set(value) == {"run_id", "user_id", "conversation_id"} for value in selected)


@pytest.mark.parametrize("limit", [None, True, False, -1, 201, 1.5, "4"])
def test_invalid_budgets_fail_before_discovering_application_resources(limit):
    with pytest.raises(ValueError):
        scheduler.check_due_orchestration_runs_once(max_runs=limit)
    with pytest.raises(ValueError):
        scheduler.check_due_orchestration_runs_once(max_outputs=limit)
    with pytest.raises(ValueError):
        scheduler.check_due_orchestration_runs_once(max_cleanup_runs=limit)


def test_naive_scheduler_time_is_rejected():
    with pytest.raises(ValueError):
        scheduler.enumerate_due_runs(None, now=datetime(2030, 1, 1))


def test_saved_run_publishes_without_model_replay(harness):
    original, _ = saved_composition(harness)
    services = harness.services()
    with harness.publication_only(services):
        result, queries, logs = tick(harness)
    current = harness.read()
    messages = harness.assistant_messages()
    assert result["ok"] is True and result["errors"] == []
    assert result["counts"]["runs_executed"] == 0
    assert result["counts"]["run_selectors"] == 1
    assert len(messages) == 1 and messages[0]["content"] == "The complete saved answer."
    assert current["status"] == "completed" and current["message_saved"] is True
    assert current["task_results"] == original["task_results"]
    assert current["started_at"] == original["started_at"]
    assert current["execution_deadline_at"] == original["execution_deadline_at"]
    assert len(harness.model_calls) == 1 and logs == []
    assert [value[0] for value in queries.calls] == ["cleanup_runs", "runs", "outputs"]
    assert [value[3]["max_item_count"] for value in queries.calls] == [4, 4, 8]


def test_pending_publication_keeps_the_same_assistant_id_and_timestamp(harness):
    saved_composition(harness)
    first, _, _ = tick(harness)
    initial = harness.read()
    replace_record(
        harness.runs, "run-1", "conversation-1", finalization_status="pending", message_saved=False,
    )
    services = harness.services()
    with harness.publication_only(services):
        second, _, _ = tick(harness)
    current = harness.read()
    messages = harness.assistant_messages()
    assert first["ok"] is True and second["ok"] is True
    assert current["assistant_message_id"] == initial["assistant_message_id"]
    assert current["assistant_message_created_at"] == initial["assistant_message_created_at"]
    assert current["attempt_index"] == initial["attempt_index"]
    assert len(messages) == 1 and len(harness.model_calls) == 1


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_terminal_pending_delivery_does_not_recompute_the_saved_outcome(harness, monkeypatch, status):
    original, _ = saved_composition(harness)
    failure = harness.schema.build_failure("context_unavailable") if status == "failed" else None
    replace_record(
        harness.runs, "run-1", "conversation-1", status=status, outcome=status,
        failure=failure, failures=[failure] if failure is not None else [],
        error=failure["message"] if failure is not None else None,
    )

    def forbidden_reconciliation(*args, **kwargs):
        raise AssertionError("A terminal publication retry must not recalculate its saved outcome.")

    monkeypatch.setattr(harness.continuation, "reconcile_run_outputs", forbidden_reconciliation)
    services = harness.services()
    with harness.publication_only(services):
        result, _, _ = tick(harness, max_outputs=0)
    current = harness.read()
    messages = harness.assistant_messages()
    assert result["ok"] is True, result
    assert current["status"] == status and current["failure"] == failure
    assert current["finalization_status"] == "saved" and len(messages) == 1
    assert current["task_results"] == original["task_results"] and len(harness.model_calls) == 1
    assert current["execution_steps"] == original["execution_steps"]
    assert current["started_at"] == original["started_at"]
    assert current["execution_deadline_at"] == original["execution_deadline_at"]


@pytest.mark.parametrize("latest", ["run-1", "newer-run"])
def test_truthy_attempt_successor_is_never_selected(harness, latest):
    saved_composition(harness)
    replace_record(harness.runs, "run-1", "conversation-1", latest_attempt_run_id=latest)
    original = deepcopy(harness.runs.items)
    result, queries, _ = tick(harness, max_outputs=0)
    assert result["counts"]["run_selectors"] == 0 and result["ok"] is True
    assert harness.runs.items == original and len(harness.model_calls) == 1
    run_queries = [value[1] for value in queries.calls if value[0] == "runs"]
    assert len(run_queries) == 1 and "c.latest_attempt_run_id = c.id" not in run_queries[0]


def test_v1_is_never_selected_or_reinterpreted(harness):
    saved_composition(harness)
    record = harness.read()
    old_plan = {**record["plan"], "planner_contract_version": 1}
    replace_record(harness.runs, "run-1", "conversation-1", planner_contract_version=1, plan=old_plan)
    before = deepcopy(harness.runs.items)
    result, _, _ = tick(harness)
    messages = harness.assistant_messages()
    assert result["counts"]["run_selectors"] == 0
    assert harness.runs.items == before
    assert messages == []


def test_live_parent_lease_and_duplicate_selectors_do_not_duplicate_work(harness):
    saved_composition(harness)
    boundary, queries, _ = resources(harness)
    selected = harness.continuation.claim_run_continuation(
        "run-1", "owner", "conversation-1", authorize=lambda: harness.bootstrap.read_owned_conversation(
            "owner", "conversation-1",
        ), message_container=harness.messages, mode="delivery",
    )
    record, lease = selected
    harness.continuation_leases.append(lease)
    try:
        result = scheduler.check_due_orchestration_runs_once(resources=boundary)
        assert result["counts"]["run_selectors"] == 0
    finally:
        lease.close(release=True)
    duplicate = {"id": "run-1", "user_id": "owner", "conversation_id": "conversation-1"}
    queries.override = lambda kind: [duplicate, duplicate] if kind == "runs" else []
    result = scheduler.check_due_orchestration_runs_once(resources=boundary)
    messages = harness.assistant_messages()
    assert result["ok"] is True and result["counts"]["run_selectors"] == 1
    assert len(messages) == 1 and len(harness.model_calls) == 1


@pytest.mark.parametrize("failed_scan", ["runs", "outputs", "cleanup_runs"])
def test_each_scan_gets_its_own_budget_despite_storage_outage(harness, failed_scan):
    saved_composition(harness)
    boundary, queries, logs = resources(harness)
    queries.fail.add(failed_scan)
    result = scheduler.check_due_orchestration_runs_once(max_runs=2, max_outputs=3, resources=boundary)
    assert [entry[0] for entry in queries.calls] == ["cleanup_runs", "runs", "outputs"]
    assert [entry[3]["max_item_count"] for entry in queries.calls] == [4, 2, 3]
    assert result["ok"] is False
    scope = "cleanup_enrollment_scan" if failed_scan == "cleanup_runs" else f"{failed_scan[:-1]}_scan"
    assert any(error["scope"] == scope and error["retryable"] for error in result["errors"])
    assert logs and "PRIVATE_PROVIDER_QUERY_FAILURE" not in json.dumps([result, logs])
    if failed_scan != "runs":
        saved = harness.read()
        assert saved["message_saved"] is True


def test_forged_selector_is_denied_but_an_independent_run_still_publishes(harness):
    saved_composition(harness)
    boundary, queries, logs = resources(harness)
    queries.override = lambda kind: [
        {"id": "run-1", "user_id": "another-owner", "conversation_id": "conversation-1"},
        {"id": "run-1", "user_id": "owner", "conversation_id": "conversation-1"},
    ] if kind == "runs" else []
    result = scheduler.check_due_orchestration_runs_once(resources=boundary)
    current = harness.read()
    messages = harness.assistant_messages()
    assert result["ok"] is False
    assert any(error["scope"] == "run" and error["code"] == "output_conversation_unavailable" for error in result["errors"])
    assert current["message_saved"] is True and len(messages) == 1
    assert len(harness.model_calls) == 1 and logs


def test_uncertain_publication_is_retried_without_relabeling_it_access_denial(harness):
    original, _ = saved_composition(harness)
    harness.messages.before_batch = lambda: setattr(harness.messages, "fail_writes", True)
    result, _, logs = tick(harness)
    current = harness.read()
    assert result["ok"] is False and any(error["retryable"] for error in result["errors"])
    assert current["status"] == "completed" and current["finalization_status"] == "pending"
    assert current["task_results"] == original["task_results"]
    assert (current.get("failure") or {}).get("code") != "context_unavailable"
    assert logs
    harness.messages.fail_writes = False
    second, _, _ = tick(harness)
    current = harness.read()
    assert second["ok"] is True and current["message_saved"] is True
    messages = harness.assistant_messages()
    assert len(harness.model_calls) == 1 and len(messages) == 1


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("code,retryable", [
    ("external_identity_service_unavailable", True),
    ("external_identity_response_invalid", False),
])
def test_scheduler_preserves_classified_directory_publication_failures(harness, monkeypatch, wrapped, code, retryable):
    from functions_orchestration_external_identity import ExternalIdentityServiceError
    from functions_orchestration_results import ResultUnavailableError

    original, _ = saved_composition(harness)

    def unavailable_identity(*args, **kwargs):
        if wrapped:
            try:
                raise ExternalIdentityServiceError(code)
            except ExternalIdentityServiceError as exc:
                raise ResultUnavailableError("result_external_identity_unavailable") from exc
        raise ExternalIdentityServiceError(code)

    with monkeypatch.context() as scoped:
        scoped.setattr(harness.bootstrap, "current_execution_identity", unavailable_identity)
        result, _, logs = tick(harness, max_outputs=0)
    current = harness.read()
    messages = harness.assistant_messages()
    assert result["ok"] is False and result["counts"]["runs_executed"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["code"] == "message_not_saved"
    assert result["errors"][0]["retryable"] is retryable
    assert current["status"] == "completed" and current["finalization_status"] == "pending"
    assert current["task_results"] == original["task_results"] and current["failure"] is None
    assert current["execution_lease"] is None and not messages
    assert len(harness.model_calls) == 1 and logs
    recovered, _, _ = tick(harness, max_outputs=0)
    messages = harness.assistant_messages()
    assert recovered["ok"] is True and len(messages) == 1
    assert len(harness.model_calls) == 1


@pytest.mark.parametrize("authority", ["identity", "configuration", "invocation"])
@pytest.mark.parametrize("wrapper", ["direct", "result", "checkpoint", "harness", "nested"])
def test_scheduler_preserves_typed_delivery_cancellation(harness, monkeypatch, authority, wrapper):
    from functions_orchestration_checkpoints import CheckpointError
    from functions_orchestration_external_configuration import ExternalConfigurationCancelledError
    from functions_orchestration_external_identity import ExternalIdentityCancelledError
    from functions_orchestration_invocation_capture import OrchestrationInvocationCancelledError
    from functions_orchestration_results import ResultUnavailableError

    original, _ = saved_composition(harness)
    services = harness.services()
    cancellation_type = {
        "identity": ExternalIdentityCancelledError,
        "configuration": ExternalConfigurationCancelledError,
        "invocation": OrchestrationInvocationCancelledError,
    }[authority]
    refresh = harness.execution.refresh_harness_delivery
    failures = []

    def cancelled_identity(*args, **kwargs):
        error = cancellation_type()
        if wrapper == "result":
            raise ResultUnavailableError("result_source_unavailable") from error
        if wrapper == "checkpoint":
            raise CheckpointError("context_unavailable") from error
        if wrapper == "harness":
            raise harness.execution.HarnessExecutionError("context_unavailable") from error
        if wrapper == "nested":
            try:
                raise ResultUnavailableError("result_source_unavailable") from error
            except ResultUnavailableError as unavailable:
                raise CheckpointError("context_unavailable") from unavailable
        raise error

    def observe_refresh(*args, **kwargs):
        try:
            return refresh(*args, **kwargs)
        except harness.execution.HarnessExecutionError as error:
            failures.append(error)
            raise

    with harness.publication_only(services), monkeypatch.context() as scoped:
        scoped.setattr(harness.bootstrap, "current_execution_identity", cancelled_identity)
        scoped.setattr(harness.execution, "refresh_harness_delivery", observe_refresh)
        result, _, logs = tick(harness, max_outputs=0)
    current = harness.read()
    messages = harness.assistant_messages()
    assert len(failures) == 1
    assert failures[0].code == "user_cancelled" and failures[0].retryable is False
    assert failures[0].final_frames == [] and failures[0].durable_status is None
    assert result["ok"] is False and result["runs"] == [] and len(result["errors"]) == 1
    assert result["errors"][0]["code"] == "user_cancelled"
    assert result["errors"][0]["retryable"] is False
    assert result["errors"][0]["error_type"] == "HarnessExecutionError"
    for field in (
        "status", "outcome", "failure", "task_results", "pending_results", "execution_steps",
        "started_at", "execution_deadline_at", "harness_step_token_usage", "harness_prompt_token_usage",
    ):
        assert current.get(field) == original.get(field)
    assert current["execution_lease"] is None and current["finalization_status"] == "pending"
    assert not current.get("cancellation_requested_at") and not current.get("message_saved") and messages == []
    assert result["counts"]["runs_executed"] == 0 and len(harness.model_calls) == 1
    assert all(client.closed for client in harness.clients) and harness.blobs.file_uploads == 0 and logs
    recovered, _, _ = tick(harness, max_outputs=0)
    messages = harness.assistant_messages()
    assert recovered["ok"] is True and len(messages) == 1 and len(harness.model_calls) == 1


@pytest.mark.parametrize("error_type,nested_cancel", [
    (InterruptedError, False), (RuntimeError, False), (RuntimeError, True),
])
def test_scheduler_does_not_guess_delivery_cancellation_from_untyped_errors(
    harness, monkeypatch, error_type, nested_cancel,
):
    from functions_orchestration_external_configuration import ExternalConfigurationCancelledError

    original, _ = saved_composition(harness)
    services = harness.services()

    def interrupted_identity(*args, **kwargs):
        error = error_type("PRIVATE_CANCELLATION_DIAGNOSTIC")
        error.code = "user_cancelled"
        if nested_cancel:
            raise error from ExternalConfigurationCancelledError()
        raise error

    with harness.publication_only(services), monkeypatch.context() as scoped:
        scoped.setattr(harness.bootstrap, "current_execution_identity", interrupted_identity)
        result, _, logs = tick(harness, max_outputs=0)
    current = harness.read()
    messages = harness.assistant_messages()
    assert result["ok"] is False and len(result["errors"]) == 1
    assert result["errors"][0]["code"] != "user_cancelled"
    assert current["status"] == original["status"] and current["task_results"] == original["task_results"]
    assert not current.get("failure") and not current.get("cancellation_requested_at") and messages == []
    assert current["execution_lease"] is None and len(harness.model_calls) == 1
    assert "PRIVATE_CANCELLATION_DIAGNOSTIC" not in json.dumps([result, logs])


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("unavailable", [False, True])
@pytest.mark.parametrize("authority", ["source", "directory", "screening", "configuration"])
def test_scheduler_keeps_authority_outages_distinct_from_denial(harness, wrapped, unavailable, authority):
    from content_screening.access import strict_source_authority_enabled
    from content_screening.contracts import (
        ScreeningConfigurationError, ScreeningError,
        SourceAuthorityUnavailableError, SourceAuthorityUnverifiedError,
    )
    from functions_orchestration_external_configuration import ExternalConfigurationServiceError
    from functions_orchestration_external_identity import ExternalIdentityServiceError
    from functions_orchestration_results import ResultUnavailableError

    original, _ = saved_composition(harness)
    boundary, _, logs = resources(harness)
    cause = SourceAuthorityUnavailableError() if unavailable else SourceAuthorityUnverifiedError()
    if authority == "directory":
        cause = ExternalIdentityServiceError(
            "external_identity_service_unavailable" if unavailable else "external_identity_response_invalid",
        )
    elif authority == "screening":
        error_type = ScreeningError if unavailable else ScreeningConfigurationError
        cause = error_type("PRIVATE_AUTHORITY_DIAGNOSTIC")
    elif authority == "configuration":
        cause = ExternalConfigurationServiceError(
            "external_configuration_service_unavailable" if unavailable else "external_configuration_metadata_invalid",
        )
    scopes = []

    def unavailable_run(*args, **kwargs):
        scopes.append(strict_source_authority_enabled())
        if wrapped:
            try:
                raise cause
            except (ScreeningError, ExternalIdentityServiceError, ExternalConfigurationServiceError) as error:
                raise ResultUnavailableError("result_source_unavailable") from error
        raise cause

    failed = replace(boundary, read_run=unavailable_run)
    outcome = scheduler.check_due_orchestration_runs_once(max_outputs=0, resources=failed)
    current = harness.read()
    messages = harness.assistant_messages()
    outside_scope = strict_source_authority_enabled()
    assert scopes == [True] and outside_scope is False
    assert outcome["ok"] is False and len(outcome["errors"]) == 1
    assert outcome["errors"][0]["code"] == cause.code
    assert outcome["errors"][0]["retryable"] is unavailable
    assert "PRIVATE_AUTHORITY_DIAGNOSTIC" not in json.dumps([outcome, logs])
    assert current == original and not messages and len(harness.model_calls) == 1 and logs
    recovered = scheduler.check_due_orchestration_runs_once(max_outputs=0, resources=boundary)
    messages = harness.assistant_messages()
    assert recovered["ok"] is True and len(messages) == 1 and len(harness.model_calls) == 1


@pytest.mark.parametrize("wrapped", [False, True])
def test_scheduler_keeps_a_genuine_screening_hold_nonretryable(harness, wrapped):
    from content_screening.contracts import DocumentHeldError
    from functions_orchestration_results import ResultUnavailableError

    original, _ = saved_composition(harness)
    boundary, _, logs = resources(harness)

    def held_run(*args, **kwargs):
        held = DocumentHeldError("PRIVATE_HOLD_DIAGNOSTIC")
        if wrapped:
            raise ResultUnavailableError("result_source_unavailable") from held
        raise held

    outcome = scheduler.check_due_orchestration_runs_once(
        max_outputs=0, resources=replace(boundary, read_run=held_run),
    )
    current = harness.read()
    messages = harness.assistant_messages()
    assert outcome["ok"] is False and len(outcome["errors"]) == 1
    assert outcome["errors"][0]["code"] == "context_unavailable"
    assert outcome["errors"][0]["retryable"] is False
    assert current == original and not messages and len(harness.model_calls) == 1
    assert "PRIVATE_HOLD_DIAGNOSTIC" not in json.dumps([outcome, logs])


@pytest.mark.parametrize("stage", ["prepare", "publication"])
@pytest.mark.parametrize("wrapper", ["direct", "result", "checkpoint", "nested"])
@pytest.mark.parametrize("authority,retryable", [
    ("directory_service", True), ("directory_response", False),
    ("screening_service", True), ("screening_configuration", False),
    ("configuration_service", True), ("configuration_metadata", False),
])
def test_scheduler_preserves_real_headless_authority_uncertainty(
    harness, monkeypatch, stage, wrapper, authority, retryable,
):
    from content_screening.contracts import ScreeningConfigurationError, ScreeningError
    from functions_orchestration_checkpoints import CheckpointError
    from functions_orchestration_external_configuration import ExternalConfigurationServiceError
    from functions_orchestration_external_identity import ExternalIdentityServiceError
    from functions_orchestration_results import ResultUnavailableError

    original = interrupted_composition(harness)

    def uncertain_authority(*args, **kwargs):
        if authority == "directory_service":
            error = ExternalIdentityServiceError()
        elif authority == "directory_response":
            error = ExternalIdentityServiceError("external_identity_response_invalid")
        elif authority == "configuration_service":
            error = ExternalConfigurationServiceError()
        elif authority == "configuration_metadata":
            error = ExternalConfigurationServiceError("external_configuration_metadata_invalid")
        elif authority == "screening_service":
            error = ScreeningError("PRIVATE_AUTHORITY_DIAGNOSTIC")
        else:
            error = ScreeningConfigurationError("PRIVATE_AUTHORITY_DIAGNOSTIC")
        if wrapper == "result":
            raise ResultUnavailableError("result_source_unavailable") from error
        if wrapper == "checkpoint":
            raise CheckpointError("context_unavailable") from error
        if wrapper == "nested":
            try:
                raise ResultUnavailableError("result_source_unavailable") from error
            except ResultUnavailableError as unavailable:
                raise CheckpointError("context_unavailable") from unavailable
        raise error

    with monkeypatch.context() as blocked:
        if stage == "prepare":
            blocked.setattr(harness.bootstrap, "get_settings", uncertain_authority)
        else:
            blocked.setattr(harness.messages, "execute_item_batch", uncertain_authority)
        outcome, _, logs = tick(harness, max_outputs=0)
    current = harness.read()
    messages = harness.assistant_messages()
    assert outcome["ok"] is False and len(outcome["errors"]) == 1, outcome
    assert outcome["errors"][0]["code"] == "message_not_saved", outcome
    assert outcome["errors"][0]["retryable"] is retryable
    assert outcome["runs"] == [] and messages == [] and current.get("failure") is None
    assert current["execution_lease"] is None and not current.get("message_saved")
    assert current["status"] == ("running" if stage == "prepare" else "completed")
    assert current["started_at"] == original["started_at"]
    assert current["execution_deadline_at"] == original["execution_deadline_at"]
    assert current["attempt_index"] == original["attempt_index"]
    assert len(harness.model_calls) == (1 if stage == "prepare" else 2)
    assert all(client.closed for client in harness.clients) and harness.blobs.file_uploads == 0
    assert "PRIVATE_AUTHORITY_DIAGNOSTIC" not in json.dumps([outcome, logs])
    if stage == "prepare":
        assert current.get("task_results") == original.get("task_results")
    else:
        assert current["finalization_status"] == "pending"

    recovered, _, _ = tick(harness, max_outputs=0)
    saved = harness.read()
    messages = harness.assistant_messages()
    assert recovered["ok"] is True and saved["message_saved"] is True, recovered
    assert len(messages) == 1 and len(harness.model_calls) == 2
    if stage == "publication":
        assert saved["task_results"] == current["task_results"]
        assert saved["harness_prompt_token_usage"] == current["harness_prompt_token_usage"]
        assert saved["harness_step_token_usage"] == current["harness_step_token_usage"]


def test_run_scan_revalidates_record_contract_after_selection(harness):
    saved_composition(harness)
    boundary, queries, _ = resources(harness)
    selector = {"id": "run-1", "user_id": "owner", "conversation_id": "conversation-1"}
    queries.override = lambda kind: [selector] if kind == "runs" else []
    replace_record(harness.runs, "run-1", "conversation-1", planner_contract_version="2")
    result = scheduler.check_due_orchestration_runs_once(resources=boundary)
    current = harness.read()
    messages = harness.assistant_messages()
    assert result["ok"] is False and result["counts"]["runs_executed"] == 0
    assert current["execution_lease"] is None
    assert messages == []


def test_deadline_terminalizes_unfinished_work_without_another_model_call(harness, monkeypatch):
    class LostProcess(BaseException):
        pass

    def lose_process():
        raise LostProcess()

    harness.create(
        steps=[
            harness.helpers.compose_step(),
            harness.helpers.compose_step("unfinished", inputs={
                "prepared": {"binding": harness.helpers.input_binding("prepare"), "allow_partial": False},
            }),
        ],
        replies=["Already retained.", lose_process],
    )
    execution = harness.prepare()
    try:
        with pytest.raises(LostProcess):
            harness.run_engine(execution)
    finally:
        execution.close()
    original = harness.read()
    late = datetime.fromisoformat(original["execution_deadline_at"]) + timedelta(seconds=1)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return late.astimezone(tz) if tz is not None else late.replace(tzinfo=None)

    monkeypatch.setattr(harness.recovery, "_now", lambda: late)
    monkeypatch.setattr(harness.continuation, "_now", lambda: late)
    monkeypatch.setattr(harness.execution, "datetime", Clock)
    before_calls = len(harness.model_calls)
    result, _, _ = tick(harness, clock=lambda: late)
    current = harness.read()
    assert result["ok"] is True
    assert current["status"] == "failed" and current["failure"]["code"] == "run_timeout"
    assert current["execution_deadline_at"] == original["execution_deadline_at"]
    assert current["started_at"] == original["started_at"]
    assert current["message_saved"] is True
    assert len(harness.model_calls) == before_calls


def test_cancelled_run_is_finalized_without_replaying_retained_content(harness):
    original, _ = saved_composition(harness)
    replace_record(
        harness.runs, "run-1", "conversation-1", status="waiting",
        cancellation_requested_at=datetime.now(timezone.utc).isoformat(),
    )
    result, _, _ = tick(harness)
    current = harness.read()
    assert result["ok"] is True
    assert current["status"] == "cancelled" and current["failure"]["code"] == "user_cancelled"
    assert current["task_results"] == original["task_results"]
    assert current["attempt_index"] == original["attempt_index"]
    assert len(harness.model_calls) == 1


def test_stale_completed_step_manifest_is_not_timed_out_or_recomputed(harness, monkeypatch):
    original, _ = saved_composition(harness)
    stale = [{**original["execution_steps"][0], "status": "running", "checkpoint_available": False}]
    replace_record(
        harness.runs, "run-1", "conversation-1", status="running", execution_steps=stale, task_results={},
    )
    late = datetime.fromisoformat(original["execution_deadline_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(harness.recovery, "_now", lambda: late)
    monkeypatch.setattr(harness.continuation, "_now", lambda: late)
    result, _, _ = tick(harness, clock=lambda: late)
    current = harness.read()
    assert result["ok"] is True
    assert current["status"] == "completed" and current["failure"] is None
    assert current["task_results"] == original["task_results"]
    assert current["execution_steps"][0]["status"] == "completed"
    assert len(harness.model_calls) == 1


def interrupted_composition(harness):
    """Retain a completed producer and stop before its dependent producer starts."""
    class LostProcess(BaseException):
        pass

    harness.create(
        steps=[
            harness.helpers.compose_step(),
            harness.helpers.compose_step("finish", inputs={
                "prepared": {"binding": harness.helpers.input_binding("prepare"), "allow_partial": False},
            }),
        ],
        replies=["Keep this original prepared value.", "Complete answer after restart."],
        final_response=harness.helpers.input_binding("finish"),
    )
    execution = harness.prepare()

    def interrupt_before_next_step():
        completed = harness.steps.items.get(("run-1", "run-1:prepare"))
        if completed is not None and completed.get("status") == "completed":
            raise LostProcess()
        harness.steps.before_batch = interrupt_before_next_step

    harness.steps.before_batch = interrupt_before_next_step
    try:
        with pytest.raises(LostProcess):
            harness.run_engine(execution)
    finally:
        execution.close()
        harness.steps.before_batch = None
    return harness.read()


def test_scheduler_executes_only_never_started_work_after_completed_checkpoint(harness, monkeypatch):
    original = interrupted_composition(harness)
    factories, handed_off, closed = [], [], []
    prepare = harness.execution.prepare_harness_execution

    def prepare_continuation(*args, **kwargs):
        factories.append(kwargs.get("checkpoint_factory"))
        execution = prepare(*args, **kwargs)
        bound_store = execution.services.results.store
        execute = execution.execute
        close = execution.close

        def execute_handoff(*args, **kwargs):
            handed_off.append((bound_store, execution.services.results.store))
            return execute(*args, **kwargs)

        def close_execution():
            closed.append(execution)
            return close()

        monkeypatch.setattr(execution, "execute", execute_handoff)
        monkeypatch.setattr(execution, "close", close_execution)
        return execution

    monkeypatch.setattr(harness.execution, "prepare_harness_execution", prepare_continuation)
    before_calls = len(harness.model_calls)
    result, _, _ = tick(harness)
    current = harness.read()
    assert result["ok"] is True, result
    assert factories == [harness.continuation.ContinuationCheckpoints]
    assert len(handed_off) == len(closed) == 1
    assert handed_off[0][0] is handed_off[0][1]
    assert result["counts"]["runs_executed"] == 1
    assert before_calls == 1 and len(harness.model_calls) == 2
    assert current["status"] == "completed" and current["message_saved"] is True
    assert current["attempt_index"] == original["attempt_index"]
    assert current["execution_deadline_at"] == original["execution_deadline_at"]
    assert current["execution_steps"][0]["reused"] is True


@pytest.mark.parametrize("finisher", ["scheduler", "existing_headless_api"])
def test_scheduler_reopens_native_once_per_tick_with_new_result_epochs(harness, monkeypatch, finisher):
    harness.settings.update({
        "enable_tabular_generation_plan": False,
        "enable_tabular_completion_driven_checkpointing": False,
        "tabular_generated_output_inline_max_rows": 1,
    })
    with harness.native_io() as native:
        harness.create(
            [
                harness.helpers.native_step(),
                harness.helpers.compose_step(inputs={"rows": {
                    "binding": harness.helpers.input_binding("compute", "records"), "allow_partial": False,
                }}),
            ],
            replies=["All 37 rows were prepared."], final_response=harness.helpers.input_binding("prepare"),
            seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
            original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        )
        initial = harness.prepare()
        frames = initial.execute()
        done = harness.helpers.decoded_frames(frames)[-1]
        assert done["status"] == "waiting", done
        original = harness.read()
        message = harness.assistant_messages()[0]
        wait = deepcopy(original["pending_results"]["compute"])
        store_module = importlib.import_module("functions_workflow_result_store")
        identity = store_module._orchestration_identity("owner", "conversation-1", "run-1", "compute")
        store = harness.services().results.store
        first_guard = store._analysis_guard(identity)
        bridge_module = importlib.import_module("functions_orchestration_native_results")
        opens = []
        open_result = native.results.open_native_tabular_result

        def forbidden(*args, **kwargs):
            raise AssertionError("Scheduler continuation resubmitted a native producer.")

        def read_once(**kwargs):
            opens.append(deepcopy(kwargs))
            return open_result(**kwargs)

        monkeypatch.setattr(bridge_module, "build_native_orchestration_request", forbidden)
        monkeypatch.setattr(native.native, "build_native_tabular_compute_callback", forbidden)
        monkeypatch.setattr(native.results, "open_native_tabular_result", read_once)
        pending, _, _ = tick(harness, max_outputs=0)
        pending_record = harness.read()
        pending_guard = store._analysis_guard(identity)
        assert pending["ok"] is True, pending
        assert pending_record["status"] == "waiting" and len(opens) == 1
        assert pending_record["task_results"]["compute"] == original["task_results"]["compute"]
        assert pending_record["pending_results"]["compute"] == wait
        assert pending_guard["token"] == first_guard["token"]
        assert pending_guard["execution_claim_id"] != first_guard.get("execution_claim_id")
        assert native.jobs.created == 1 and not harness.model_calls

        native.engine.process_tabular_generated_output_run(wait["handle"]["job_id"], "owner")
        if finisher == "scheduler":
            completed, _, _ = tick(harness, max_outputs=0)
            assert completed["ok"] is True, completed
        else:
            resumed = harness.continue_waiting("existing-headless-native-refresh")
            frames = resumed.execute()
            completed = harness.helpers.decoded_frames(frames)[-1]
            assert completed["status"] == "completed", completed
        current = harness.read()
        last_guard = store._analysis_guard(identity)
        messages = harness.assistant_messages()
        contracts = importlib.import_module("functions_orchestration_result_contracts")
        task = contracts.TaskResult.from_dict(current["task_results"]["compute"])
        reader = harness.services().results.open_result(task.output("records"))
        rows = list(reader.iter_records())
        assert current["status"] == "completed" and current["pending_results"] == {}
        assert last_guard["token"] == pending_guard["token"]
        assert last_guard["execution_claim_id"] != pending_guard["execution_claim_id"]
        assert current["task_results"]["compute"]["producer"] == original["task_results"]["compute"]["producer"]
        assert current["attempt_index"] == original["attempt_index"] == 1
        assert current["started_at"] == original["started_at"]
        assert current["execution_deadline_at"] == original["execution_deadline_at"]
        assert current["execution_binding"] == original["execution_binding"]
        assert len(opens) == 2 and all(value["handle"] == wait["handle"] for value in opens)
        assert native.jobs.created == 1 and len(harness.model_calls) == 1
        assert len(rows) == 37 and rows[-1] == {"Item_ID": "item-000037", "doubled": 74}
        assert len(messages) == 1 and messages[0]["id"] == message["id"]
        assert messages[0]["timestamp"] == message["timestamp"]
        assert messages[0]["content"] == "All 37 rows were prepared."
        assert harness.blobs.file_uploads == 0


@pytest.mark.parametrize("role", ["gather", "reason"])
@pytest.mark.parametrize("wait_change", ["unchanged", "fingerprint", "kind", "extra_field"])
def test_scheduler_reopens_a_generic_result_wait_without_replaying_its_producer(harness, role, wait_change):
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    producer_calls = []
    step = {
        "step_id": "lookup", "capability_id": "document_search",
        "arguments": {"query": "Find the requested documents."},
    } if role == "gather" else harness.helpers.compose_step("lookup")
    harness.create([step])
    execution = harness.prepare()

    def pending_producer(step, context, **kwargs):
        producer_calls.append(step["step_id"])
        wait = {
            "kind": "orchestration_result",
            "input_fingerprint": context.result_input_fingerprint_for_step(step["step_id"]),
        }
        if wait_change == "fingerprint":
            wait["input_fingerprint"] = "0" * 64
        elif wait_change == "kind":
            wait["kind"] = "unknown_result"
        elif wait_change == "extra_field":
            wait["unexpected"] = True
        return harness.schema.build_step_result(
            status="waiting",
            task_result=contracts.TaskResult(context.result_producer(step), role, "pending", ()),
            wait=wait,
        )

    try:
        result = harness.execution.execute_plan(
            execution.record["plan"], execution.context, settings=execution.settings,
            user_id="owner", cancel_requested=execution.lease.cancel_requested,
            persist=execution._persist, get_adapter=lambda capability_id: pending_producer,
            checkpoints=lambda context: harness.recovery.ExecutionCheckpoints(
                execution.record, context, execution.settings, execution.lease,
            ),
        )
    finally:
        execution.close()
    original = harness.read()
    assert result["status"] == original["status"] == "waiting", result
    outcome, _, _ = tick(harness, max_outputs=0)
    current = harness.read()
    assert outcome["ok"] is True, outcome
    if wait_change == "unchanged":
        assert current["status"] == "waiting", current.get("failure")
        assert current["pending_results"] == original["pending_results"]
        assert current["task_results"] == original["task_results"]
    else:
        assert current["status"] == "failed"
        assert current["execution_steps"][0]["failure"]["code"] == "result_unavailable"
    assert current["execution_deadline_at"] == original["execution_deadline_at"]
    assert current["attempt_index"] == original["attempt_index"]
    assert producer_calls == ["lookup"] and harness.model_calls == []
    assert harness.blobs.file_uploads == 0


@pytest.mark.parametrize("boundary", ["lease_read", "lease_start", "checkpoint_restore"])
@pytest.mark.parametrize("wrapper", ["checkpoint", "permission"])
@pytest.mark.parametrize("outage", [ServiceRequestError, ConnectionError, TimeoutError])
def test_scheduler_continuation_io_retains_native_work_without_denial_or_replay(
    harness, monkeypatch, boundary, wrapper, outage,
):
    harness.settings.update({
        "enable_tabular_generation_plan": False,
        "enable_tabular_completion_driven_checkpointing": False,
        "tabular_generated_output_inline_max_rows": 1,
    })
    with harness.native_io(row_count=3) as native:
        harness.create(
            [harness.helpers.native_step()],
            seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
            original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        )
        first = harness.prepare()
        frames = first.execute()
        first_done = harness.helpers.decoded_frames(frames)[-1]
        original = harness.read()
        messages = deepcopy(harness.assistant_messages())
        assert first_done["status"] == original["status"] == "waiting"
        claims, faults = [], []
        original_claim = scheduler._Tick.claim
        checkpoints = harness.continuation.ContinuationCheckpoints

        def unavailable():
            faults.append(boundary)
            failure = outage("PRIVATE_STORAGE_DIAGNOSTIC")
            if wrapper == "checkpoint":
                raise harness.continuation.CheckpointError("checkpoint_unavailable") from failure
            raise PermissionError("PRIVATE_AUTHORIZATION_WRAPPER") from failure

        def claim_then_interrupt(self, selector, mode):
            claimed = original_claim(self, selector, mode)
            if claimed is None:
                return None
            record, lease = claimed
            claims.append((record, lease))
            if boundary == "lease_read":
                read = lease.read

                def interrupted_read():
                    if not faults:
                        unavailable()
                    return read()

                monkeypatch.setattr(lease, "read", interrupted_read)
            elif boundary == "lease_start":
                monkeypatch.setattr(lease, "start", unavailable)
            else:
                def interrupted_restore(_self, *args, **kwargs):
                    unavailable()

                monkeypatch.setattr(checkpoints, "__init__", interrupted_restore)
            return claimed

        def forbidden(*args, **kwargs):
            raise AssertionError("Uncertain continuation polled or resubmitted native work.")

        bridge = importlib.import_module("functions_orchestration_native_results")
        monkeypatch.setattr(scheduler._Tick, "claim", claim_then_interrupt)
        monkeypatch.setattr(bridge, "build_native_orchestration_request", forbidden)
        monkeypatch.setattr(native.native, "build_native_tabular_compute_callback", forbidden)
        monkeypatch.setattr(native.results, "open_native_tabular_result", forbidden)
        outcome, _, logs = tick(harness, max_outputs=0)
        current = harness.read()
        after_messages = harness.assistant_messages()
        assert faults == [boundary] and len(claims) == 1
        claimed, lease = claims[0]
        heartbeat_alive = lease.thread is not None and lease.thread.is_alive()
        assert outcome["ok"] is False and len(outcome["errors"]) == 1, outcome
        assert outcome["errors"][0]["code"] == "message_not_saved", outcome
        assert outcome["errors"][0]["retryable"] is True
        assert outcome["runs"] == [] and not current.get("failure")
        assert current["status"] == claimed["status"] == "running"
        assert current["task_results"] == original["task_results"]
        assert current["pending_results"] == original["pending_results"]
        assert current["execution_binding"] == original["execution_binding"]
        assert current["execution_deadline_at"] == original["execution_deadline_at"]
        assert current["started_at"] == original["started_at"]
        assert current["attempt_index"] == original["attempt_index"]
        assert current["continuation_submission"] == claimed["continuation_submission"]
        assert current["execution_lease"] is None and lease.stopped.is_set()
        assert heartbeat_alive is False
        assert after_messages == messages and native.jobs.created == 1
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0
        assert all(client.closed for client in harness.clients)
        assert "PRIVATE_" not in json.dumps([outcome, logs])


@pytest.mark.parametrize("stop", ["deadline", "cancellation"])
def test_native_claim_stopping_during_admission_is_finalized_without_execution(harness, monkeypatch, stop):
    harness.settings["tabular_generated_output_inline_max_rows"] = 1
    with harness.native_io() as native:
        harness.create(
            [harness.helpers.native_step()],
            seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
            original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        )
        first = harness.prepare()
        frames = first.execute()
        done = harness.helpers.decoded_frames(frames)[-1]
        original = harness.read()
        assert done["status"] == "waiting", done
        clock = {"now": datetime.now(timezone.utc), "advanced": False}
        late = datetime.fromisoformat(original["execution_deadline_at"]) + timedelta(seconds=1)
        owned = harness.recovery._owned

        def owned_after_latency(*args, **kwargs):
            record = owned(*args, **kwargs)
            if not clock["advanced"]:
                clock.update(now=late, advanced=True)
            return record

        def cancel_after_claim():
            harness.recovery.request_cancellation(
                "run-1", "owner", "conversation-1",
                lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1"),
            )
            clock["advanced"] = True

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock["now"].astimezone(tz) if tz is not None else clock["now"].replace(tzinfo=None)

        if stop == "deadline":
            monkeypatch.setattr(harness.recovery, "_owned", owned_after_latency)
        else:
            monkeypatch.setattr(harness.steps, "before_replace", cancel_after_claim)
        monkeypatch.setattr(harness.recovery, "_now", lambda: clock["now"])
        monkeypatch.setattr(harness.continuation, "_now", lambda: clock["now"])
        monkeypatch.setattr(harness.execution, "datetime", Clock)
        boundary, _, _ = resources(harness, clock=lambda: clock["now"])
        services = harness.services()
        with harness.publication_only(services):
            outcome = scheduler.check_due_orchestration_runs_once(max_outputs=0, resources=boundary)
        current = harness.read()
        assert outcome["ok"] is True and clock["advanced"] is True, outcome
        expected_status, expected_code = (
            ("failed", "run_timeout") if stop == "deadline" else ("cancelled", "user_cancelled")
        )
        assert current["status"] == expected_status and current["failure"]["code"] == expected_code
        assert current["message_saved"] is True and current["attempt_index"] == original["attempt_index"]
        assert current["started_at"] == original["started_at"]
        assert current["execution_deadline_at"] == original["execution_deadline_at"]
        assert native.jobs.created == 1 and not harness.model_calls and not harness.blobs.file_uploads


@pytest.fixture
def file_lifecycle(harness, monkeypatch):
    # Reuse the output owner's full retained-result/transport fixture, not a renderer mock.
    from test_orchestration_output_lifecycle import Lifecycle
    from functions_orchestration_services import OrchestrationServices

    seed, execution = saved_composition(harness)
    modules = SimpleNamespace(
        operations=harness.operations,
        sources=importlib.import_module("functions_generated_artifact_sources"),
        routes=importlib.import_module("route_enhanced_citations"),
        config=harness.config,
        schema=harness.schema,
    )
    lifecycle = Lifecycle(modules, monkeypatch)
    lifecycle.cleanup_guards = harness.steps
    lifecycle.now = datetime.now(timezone.utc)
    lifecycle.deadline = datetime.fromisoformat(seed["execution_deadline_at"])
    for message in harness.messages.items.values():
        lifecycle.messages.create_item(deepcopy(message))
    plan = deepcopy(seed["plan"])
    plan["steps"] = [{
        "step_id": "analyze", "capability_id": "document_analyze", "role": "reason",
        "enabled": True, "optional": False, "depends_on": [], "inputs": {},
        "arguments": {"document_ids": ["document-1"]},
        "outputs": [{"name": value.output_name, "kind": value.kind} for value in lifecycle.saved.outputs],
    }]
    plan["final_response"] = None
    seed.update({
        "plan": plan, "status": "waiting", "outcome": "waiting", "final_response": None,
        "execution_binding": harness.continuation.context_binding(execution.context, plan, harness.settings),
        "task_results": {"analyze": lifecycle.saved.to_dict()}, "pending_results": {},
        "execution_steps": [{
            "step_id": "analyze", "capability_id": "document_analyze", "role": "reason",
            "status": "completed", "step_index": 0, "checkpoint_available": False,
        }],
    })
    lifecycle.runs.upsert_item(seed)
    harness.runs, harness.messages, harness.conversations = (
        lifecycle.runs, lifecycle.messages, lifecycle.conversations,
    )
    monkeypatch.setattr(harness.run_store, "cosmos_orchestration_runs_container", lifecycle.runs)
    monkeypatch.setattr(harness.config, "cosmos_orchestration_runs_container", lifecycle.runs)
    monkeypatch.setattr(harness.recovery, "_now", lambda: lifecycle.now)
    monkeypatch.setattr(harness.continuation, "_now", lambda: lifecycle.now)
    monkeypatch.setattr(harness.config, "storage_account_personal_chat_container_name", "chat")
    actual_output_store = harness.bootstrap.OrchestrationOutputStore

    def timed_output_store(*args, **kwargs):
        return actual_output_store(*args, **kwargs, clock=lambda: lifecycle.now, lease_seconds=10)

    monkeypatch.setattr(harness.bootstrap, "OrchestrationOutputStore", timed_output_store)
    services = OrchestrationServices(
        user_id="owner", conversation_id="conversation-1",
        result_store=lifecycle.service.results.store, run_container=lifecycle.runs,
        read_conversation=lifecycle.service.results.access.read_conversation,
        read_run=lifecycle.service.results.access.read_run,
        source_resolver=lifecycle.results.resolve, source_metadata_reader=lifecycle.results.metadata,
        transport=lifecycle.service.transport, authorize_execution=lifecycle.authorize,
        max_output_bytes=1024 * 1024,
    )
    services.results, services.outputs, services.rendering = (
        lifecycle.service.results, lifecycle.service.store, lifecycle.service,
    )
    original_add = lifecycle.add_render_step

    def add_step(name):
        producer = original_add(name)
        record = lifecycle.runs.read_item("run-1", "conversation-1")
        for step in record["plan"]["steps"]:
            step.setdefault("optional", False)
        lifecycle.change_run(plan=record["plan"])
        return producer

    monkeypatch.setattr(lifecycle, "add_render_step", add_step)

    def forbidden(*args, **kwargs):
        raise AssertionError("A file-only tick attempted model, producer, memory or native execution.")

    for name in ("prepare_harness_execution", "execute_plan", "resolve_orchestration_model", "load_orchestration_memory"):
        monkeypatch.setattr(harness.execution, name, forbidden)
    monkeypatch.setattr(harness.planner, "AzureOpenAI", forbidden)

    def fresh_services(user_id, conversation_id, **kwargs):
        current = copy(services)
        current.results = copy(services.results)
        current.rendering = copy(services.rendering)
        current.rendering.results = current.results
        return current

    queries, logs = DueQueryContainer(lifecycle.runs), []
    boundary = scheduler.OrchestrationSchedulerResources(
        runs_container=queries, messages_container=lifecycle.messages,
        settings=harness.settings, read_conversation=harness.bootstrap.read_owned_conversation,
        read_run=harness.revisions.read_revision_run,
        build_services=fresh_services,
        build_cleanup_service=harness.bootstrap.build_orchestration_cleanup_service,
        log=lambda message, **kwargs: logs.append((message, kwargs)),
        clock=lambda: lifecycle.now,
    )
    yield SimpleNamespace(
        life=lifecycle, services=services, resources=boundary, queries=queries, logs=logs,
    )
    if any(not stream.closed for stream in lifecycle.output_streams):
        raise AssertionError("A scheduler renderer leaked a private stream.")


def test_file_ticks_bound_automatic_attempts_and_manual_retry_never_replays_producers(file_lifecycle, harness):
    case, life = file_lifecycle, file_lifecycle.life
    failing = life.prepare("json")
    successful = life.prepare("csv")
    life.failures["json"] = [ConnectionError("PRIVATE_RENDER_FAILURE") for _ in range(3)]
    source_payloads = {
        key: deepcopy(row) for key, row in life.results.container.items.items()
        if row.get("record_kind") != "lifecycle"
    }
    original = harness.read()
    outcomes = []
    for attempt in range(1, 4):
        outcome = scheduler.check_due_orchestration_runs_once(resources=case.resources)
        outcomes.append(outcome)
        current = life.raw(failing)
        assert current["automatic_attempts"] == current["attempt_count"] == min(attempt + 1, 3)
        assert life.render_calls.count(("json", "exact_records_v1")) == attempt
        assert outcome["ok"] is True, outcome
        if attempt < 3:
            assert current["state"] == "retry_scheduled"
            before_calls = len(life.render_calls)
            not_due = scheduler.check_due_orchestration_runs_once(resources=case.resources)
            assert not_due["counts"]["output_selectors"] == 0
            assert len(life.render_calls) == before_calls
            life.advance_due(failing)
    exhausted = life.raw(failing)
    sibling = life.raw(successful)
    failed_run = harness.read()
    messages = harness.assistant_messages()
    assert exhausted["state"] == "failed" and exhausted["can_retry"] is True
    assert sibling["state"] == "completed" and sibling["automatic_attempts"] == 1
    assert failed_run["status"] == "failed" and failed_run["outcome"] == "partial"
    assert len(messages) == 1
    identity = (messages[0]["id"], messages[0]["timestamp"])
    queued = life.service.manual_retry(failing["output_id"], "manual-request-1")
    queued_run = harness.read()
    assert queued["state"] == "waiting"
    assert queued_run["status"] == "failed" and queued_run["execution_steps"] == failed_run["execution_steps"]
    final_tick = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    completed = life.raw(failing)
    completed_run = harness.read()
    messages = harness.assistant_messages()
    assert final_tick["ok"] is True, final_tick
    assert completed["state"] == "completed"
    assert completed["automatic_attempts"] == 3 and completed["attempt_count"] == 4
    assert life.render_calls.count(("csv", "tabular_records_v1")) == 1
    current_payloads = {
        key: row for key, row in life.results.container.items.items()
        if row.get("record_kind") != "lifecycle"
    }
    assert current_payloads == source_payloads
    assert completed_run["status"] == "completed" and completed_run["message_saved"] is True
    assert completed_run["task_results"] == original["task_results"]
    assert completed_run["attempt_index"] == original["attempt_index"]
    assert completed_run["started_at"] == original["started_at"]
    assert completed_run["execution_deadline_at"] == original["execution_deadline_at"]
    assert len(messages) == 1 and (messages[0]["id"], messages[0]["timestamp"]) == identity
    assert len(harness.model_calls) == 1
    assert "PRIVATE_RENDER_FAILURE" not in json.dumps([*outcomes, final_tick, case.logs])
    calls = list(life.render_calls)
    duplicate = life.service.manual_retry(failing["output_id"], "manual-request-1")
    repeated_tick = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    after_duplicate = life.raw(failing)
    assert duplicate["state"] == "completed" and after_duplicate == completed
    assert repeated_tick["counts"]["outputs_processed"] == 0 and life.render_calls == calls


@pytest.mark.parametrize("status", ["completed", "waiting", "failed"])
def test_real_refresh_is_read_only_after_render_and_reconciliation(file_lifecycle, harness, monkeypatch, status):
    case, life = file_lifecycle, file_lifecycle.life
    life.prepare("json")
    life.prepare("csv")
    if status != "completed":
        life.failures["json"] = [
            ConnectionError("PRIVATE_REFRESH_FIXTURE") if status == "waiting"
            else ValueError("PRIVATE_REFRESH_FIXTURE"),
        ]
    refresh = harness.execution.refresh_harness_delivery
    observed = []

    def forbidden_write(*args, **kwargs):
        raise AssertionError("Delivery refresh attempted a producer or result-fence write.")

    def guarded_refresh(record, *, services=None, settings=None, lease=None):
        owned = lease.read()
        assert owned["status"] == record["status"] == status
        assert isinstance(lease, harness.recovery.ExecutionLease)
        before_rows = deepcopy(life.results.container.items)
        before_calls = (len(life.render_calls), life.blobs.uploads, len(harness.model_calls))
        retained = {
            key: deepcopy(owned.get(key)) for key in (
                "id", "run_id", "attempt_index", "started_at", "execution_deadline_at",
                "task_results", "pending_results", "execution_steps", "planning_token_usage",
                "harness_prompt_token_usage", "harness_step_token_usage",
            )
        }
        with harness.publication_only(services), monkeypatch.context() as reads_only:
            for name in (
                "save_orchestration", "prepare_orchestration_result",
                "commit_orchestration_result", "rollover_orchestration_result_guard",
            ):
                reads_only.setattr(type(services.results.store), name, forbidden_write)
            frames = refresh(record, services=services, settings=settings, lease=lease)
        current = harness.read()
        after_calls = (len(life.render_calls), life.blobs.uploads, len(harness.model_calls))
        after_retained = {key: current.get(key) for key in retained}
        assert after_retained == retained
        assert life.results.container.items == before_rows and after_calls == before_calls
        for key in ("assistant_message_id", "assistant_message_created_at"):
            if owned.get(key) is not None:
                assert current[key] == owned[key]
        observed.append(current["finalization_status"])
        return frames

    monkeypatch.setattr(harness.execution, "refresh_harness_delivery", guarded_refresh)
    outcome = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    current = harness.read()
    messages = harness.assistant_messages()
    assert outcome["ok"] is True and observed == ["saved"], outcome
    assert current["status"] == status and current["message_saved"] is True
    assert len(messages) == 1 and len(life.render_calls) == 2 and len(harness.model_calls) == 1
    assert "PRIVATE_REFRESH_FIXTURE" not in json.dumps([outcome, case.logs, messages])


@pytest.mark.parametrize("status", ["completed", "waiting"])
@pytest.mark.parametrize("error_name", [
    "storage", "reader_configuration", "external_reader_configuration", "raw_storage_permission",
])
def test_scheduler_preserves_saved_render_read_uncertainty(
    file_lifecycle, harness, monkeypatch, status, error_name,
):
    from test_orchestration_render_read_failures import _read_failure

    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare("json")
    if status == "waiting":
        life.failures["json"] = [TimeoutError("PRIVATE_INITIAL_RENDER_FAILURE")]
    refresh = harness.execution.refresh_harness_delivery
    before, failures, reads = {}, [], []
    error, _ = _read_failure(error_name)

    def guarded_refresh(record, *, services=None, settings=None, lease=None):
        owned = lease.read()
        before["record"] = deepcopy(owned)
        before["output"] = deepcopy(life.raw(output))
        before["results"] = deepcopy(life.results.container.items)
        target, method = (
            (services.outputs, "get") if error_name == "raw_storage_permission"
            else (services.rendering, "_authorize_read_record")
        )
        read = getattr(target, method)

        def uncertain_read(value):
            reads.append(value)
            if len(reads) == 1:
                raise error
            return read(value)

        with harness.publication_only(services), monkeypatch.context() as scoped:
            scoped.setattr(target, method, uncertain_read)
            try:
                return refresh(record, services=services, settings=settings, lease=lease)
            except harness.execution.HarnessExecutionError as failure:
                failures.append(failure)
                raise

    monkeypatch.setattr(harness.execution, "refresh_harness_delivery", guarded_refresh)
    outcome = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    current = harness.read()
    current_output = life.raw(output)
    messages = harness.assistant_messages()
    assert before["record"]["status"] == status
    for field in (
        "status", "outcome", "failure", "task_results", "pending_results", "execution_steps",
        "started_at", "execution_deadline_at", "harness_step_token_usage", "harness_prompt_token_usage",
        "message_saved", "finalization_status",
    ):
        assert current.get(field) == before["record"].get(field), (field, current.get(field))
    assert outcome["ok"] is False and len(outcome["errors"]) == len(failures) == 1, outcome
    assert outcome["errors"][0]["code"] == failures[0].code == "message_not_saved"
    assert failures[0].final_frames == [] and failures[0].durable_status is None
    assert len(reads) == 1 and messages == []
    assert current_output == before["output"] and life.results.container.items == before["results"]
    assert current["execution_lease"] is None and not current.get("message_saved")
    assert len(harness.model_calls) == len(life.render_calls) == 1
    assert life.blobs.uploads == (1 if status == "completed" else 0)
    assert "PRIVATE_INITIAL_RENDER_FAILURE" not in json.dumps([outcome, case.logs, messages])


def test_output_claim_captures_current_parent_lease_with_running_heartbeat(file_lifecycle, harness, monkeypatch):
    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare("json")
    renderer = life.service.renderer
    observed = []

    def guarded_renderer(**kwargs):
        run = harness.read()
        current = life.raw(output)
        threads = [thread for thread in threading.enumerate() if thread.name == "orchestration-lease-run-1"]
        if len(threads) != 1:
            raise AssertionError("Rendering requires exactly one live owning parent heartbeat.")
        alive = threads[0].is_alive()
        observed.append((run, current, threads[0], alive))
        return renderer(**kwargs)

    monkeypatch.setattr(life.service, "renderer", guarded_renderer)
    result = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    assert result["ok"] is True and len(observed) == 1, result
    run, current, thread, was_alive = observed[0]
    alive_after = thread.is_alive()
    assert was_alive is True and alive_after is False
    assert run["status"] == "running"
    assert current["lease"]["run_token"] == run["execution_lease"]["token"]
    assert current["lease"]["run_token"]
    assert datetime.fromisoformat(run["execution_lease"]["expires_at"]) > life.now
    assert current["state"] == "rendering" and current["attempt_count"] == 1


@pytest.mark.parametrize("operation", ["owned", "renew"])
def test_output_claim_cannot_survive_same_token_parent_claim_takeover(file_lifecycle, harness, operation):
    from functions_orchestration_output_store import OutputConflictError

    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare("json")
    authorize = lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1")
    record, old = harness.continuation.claim_run_continuation(
        "run-1", "owner", "conversation-1", authorize=authorize,
        message_container=life.messages, mode="outputs",
    )
    harness.continuation_leases.append(old)
    old.start()
    claim = life.service.store.claim_due(output["output_id"], worker_id="old-output-worker")
    previous = life.raw(output)
    old.close()
    record = harness.read()
    replace_record(
        life.runs, "run-1", "conversation-1",
        execution_lease={
            **record["execution_lease"], "expires_at": (life.now - timedelta(seconds=1)).isoformat(),
        },
    )
    record, current = harness.continuation.claim_run_continuation(
        "run-1", "owner", "conversation-1", authorize=authorize,
        message_container=life.messages, mode="outputs",
    )
    harness.continuation_leases.append(current)
    current.start()
    assert current.token == old.token and current.claim_id != old.claim_id
    with pytest.raises(OutputConflictError):
        getattr(life.service.store, operation)(claim)
    after = life.raw(output)
    assert after == previous and not life.render_calls
    current.close(release=True)


def test_uncertain_admitted_output_preserves_minimal_step_wait_without_a_task(file_lifecycle, harness, monkeypatch):
    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare("json")
    saved = life.raw(output)
    step_id = saved["producer"]["step_id"]
    wait = {
        "kind": "orchestration_output", "output_id": output["output_id"],
        "error_code": "output_storage_unavailable",
    }
    pending_step = harness.schema.build_step_result(status="waiting", wait=wait)
    pending_step.update({
        "step_id": step_id, "capability_id": "render_file", "role": "render",
        "step_index": 1, "outputs": [deepcopy(output)],
    })
    original = harness.read()
    life.change_run(
        execution_steps=[*original["execution_steps"], pending_step],
        pending_results={step_id: wait},
    )
    read_item = life.runs.read_item

    def uncertain_output_read(item, partition_key, **kwargs):
        if item == output["output_id"]:
            raise AzureError("PRIVATE_UNCERTAIN_OUTPUT_READ")
        return read_item(item=item, partition_key=partition_key, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(life.runs, "read_item", uncertain_output_read)
        uncertain = scheduler.check_due_orchestration_runs_once(max_outputs=0, resources=case.resources)
    current = harness.read()
    assert uncertain["ok"] is False and uncertain["errors"][0]["retryable"] is True, uncertain
    assert current["status"] == "waiting" and not current.get("failure")
    assert current["pending_results"][step_id] == wait
    assert current["execution_steps"][-1] == pending_step
    assert step_id not in current["task_results"] and not life.render_calls
    assert len(harness.model_calls) == 1
    recovered = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    completed = harness.read()
    assert recovered["ok"] is True, recovered
    assert completed["status"] == "completed" and not completed["pending_results"]
    assert step_id not in completed["task_results"]
    assert life.render_calls == [("json", "exact_records_v1")] and len(harness.model_calls) == 1


def test_completed_file_does_not_finish_unresolved_native_work(file_lifecycle, harness):
    from functions_native_tabular_compute import NATIVE_TABULAR_COMPUTE_VERSION, native_compute_job_id
    from functions_orchestration_native_results import NATIVE_WAIT_KIND
    from functions_orchestration_result_contracts import ProducerIdentity, TaskResult

    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare("json")
    record = harness.read()
    producer = ProducerIdentity(
        "owner", "conversation-1", "run-1", 1, "native", "tabular_analyze", "native-tabular-result-v1",
    )
    pending = TaskResult(producer, "reason", "pending", ())
    wait = {"kind": NATIVE_WAIT_KIND, "handle": {
        "version": NATIVE_TABULAR_COMPUTE_VERSION, "job_id": native_compute_job_id(producer.to_dict()),
        "request_fingerprint": "1" * 64,
    }}
    record["plan"]["steps"].append({
        "step_id": "native", "capability_id": "tabular_analyze", "role": "reason",
        "enabled": True, "optional": False, "depends_on": [],
    })
    record["execution_steps"].append({
        "step_id": "native", "capability_id": "tabular_analyze", "role": "reason", "status": "waiting",
    })
    record["task_results"]["native"] = pending.to_dict()
    life.change_run(
        plan=record["plan"], execution_steps=record["execution_steps"],
        task_results=record["task_results"], pending_results={"native": wait},
    )
    result = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    current = harness.read()
    file_record = life.raw(output)
    assert result["ok"] is True, result
    assert file_record["state"] == "completed"
    assert current["status"] == "waiting" and current["completed_at"] is None
    assert current["pending_results"]["native"] == wait
    assert current["task_results"]["native"] == pending.to_dict()
    assert current["execution_steps"][-1]["status"] == "waiting"
    assert result["counts"]["runs_executed"] == 0


def test_cancelled_file_tick_does_not_reopen_result_write_fences(file_lifecycle, harness):
    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare("json")
    original = harness.read()
    life.change_run(cancellation_requested_at=life.now.isoformat())
    before = deepcopy(life.results.container.items)
    outcome = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    current = harness.read()
    stored = life.raw(output)
    assert outcome["ok"] is True, outcome
    assert current["status"] == "cancelled" and current["failure"]["code"] == "user_cancelled"
    assert current["attempt_index"] == original["attempt_index"]
    assert stored["state"] == "cancelled" and stored["attempt_count"] == 1
    assert life.results.container.items == before and not life.render_calls
    assert len(harness.model_calls) == 1


def test_one_output_storage_failure_does_not_replay_or_hide_successful_siblings(file_lifecycle, monkeypatch):
    case, life = file_lifecycle, file_lifecycle.life
    broken = life.prepare("json")
    sibling = life.prepare("csv")
    original = life.service.render_attempt

    def unavailable(output_id, **kwargs):
        if output_id == broken["output_id"]:
            raise AzureError("PRIVATE_OUTPUT_STORAGE_FAILURE")
        return original(output_id, **kwargs)

    monkeypatch.setattr(life.service, "render_attempt", unavailable)
    result = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    completed = life.raw(sibling)
    unfinished = life.raw(broken)
    assert result["ok"] is False
    assert completed["state"] == "completed"
    assert unfinished["state"] == "waiting" and unfinished["attempt_count"] == 1
    assert result["counts"]["outputs_processed"] == 1
    assert any(error["scope"] == "output_attempt" and error["retryable"] for error in result["errors"])
    assert "PRIVATE_OUTPUT_STORAGE_FAILURE" not in json.dumps([result, case.logs])


@pytest.mark.parametrize("boundary", ["before_blob", "blob", "message"])
def test_expired_renderer_only_reconciles_once_then_obeys_saved_backoff(file_lifecycle, harness, boundary, monkeypatch):
    from test_orchestration_output_cleanup import interrupted_output

    case, life = file_lifecycle, file_lifecycle.life
    output = interrupted_output(life, boundary)
    original_run = harness.read()
    original = life.raw(output)
    real_reconcile = life.service.reconcile
    observed = []

    def reconcile(output_id, **kwargs):
        run = life.runs.read_item("run-1", "conversation-1")
        observed.append((output_id, deepcopy(run["execution_lease"])))
        return real_reconcile(output_id, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("An expired rendering output was rendered in its reconciliation tick.")

    monkeypatch.setattr(life.service, "reconcile", reconcile)
    life.now += timedelta(seconds=11)
    with monkeypatch.context() as scoped:
        scoped.setattr(life.service, "render_attempt", forbidden)
        outcome = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    waiting = life.raw(output)
    run = harness.read()
    assert outcome["ok"] is True, outcome
    assert outcome["counts"]["outputs_processed"] == 1
    assert outcome["outputs"][0]["action"] == "reconcile"
    assert len(observed) == 1 and observed[0][0] == output["output_id"]
    assert observed[0][1]["token"]
    assert waiting["state"] == "retry_scheduled" and waiting["next_retry_at"]
    assert waiting["automatic_attempts"] == waiting["attempt_count"] == 2
    assert original["attempt_count"] == 1 and len(life.render_calls) == 1
    assert run["attempt_index"] == original_run["attempt_index"]
    assert run["started_at"] == original_run["started_at"]
    assert run["execution_deadline_at"] == original_run["execution_deadline_at"]
    deferred = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    assert deferred["ok"] is True and deferred["counts"]["output_selectors"] == 0
    assert len(observed) == 1 and len(life.render_calls) == 1
    life.advance_due(output)
    life.blobs.before_upload = None
    life.blobs.after_upload = None
    life.messages.after_create = None
    resumed = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    completed = life.raw(output)
    assert resumed["ok"] is True and resumed["outputs"][0]["action"] == "attempt", resumed
    assert completed["state"] == "completed" and completed["attempt_count"] == 2
    assert len(observed) == 1
    assert len(life.render_calls) == (2 if boundary == "before_blob" else 1)


def cleanup_only_resources(case):
    def forbidden(*args, **kwargs):
        raise AssertionError("Deletion-only cleanup requested live execution or conversation access.")

    return replace(
        case.resources, build_services=forbidden, read_run=forbidden, read_conversation=forbidden,
    )


def admit_output_cleanup(case, *, mode="missing", retain_committed=False):
    from functions_orchestration_output_store import build_output_cleanup_intent
    from test_orchestration_output_cleanup import delete_conversation, retain_run_deletion_tombstone

    life = case.life
    delete_conversation(life, "orchestration_deleted" if mode == "missing" else mode)
    run = life.runs.read_item("run-1", "conversation-1")
    intent = build_output_cleanup_intent(run, retain_committed=retain_committed)
    replace_record(
        life.runs, "run-1", "conversation-1", checkpoints_deleted=True, output_cleanup=intent,
    )
    retain_run_deletion_tombstone(life)
    if mode == "missing":
        conversation = life.conversations.read_item("conversation-1", "conversation-1")
        life.conversations.delete_item(
            "conversation-1", partition_key="conversation-1", etag=conversation["_etag"],
        )
    return intent


@pytest.mark.parametrize("mode", ["missing", "deleted", "orchestration_deleted"])
def test_deleted_run_enrollment_discovers_committed_outputs_without_cleanup_pending(file_lifecycle, mode):
    case, life = file_lifecycle, file_lifecycle.life
    baseline = deepcopy(life.messages.items)
    outputs = [life.prepare(step_id=f"file-{index}") for index in range(2)]
    delivered = [life.run(output) for output in outputs]
    before = [life.raw(output) for output in outputs]
    assert all(value["state"] == "completed" and not value["cleanup_pending"] for value in before)
    assert all(value["state"] == "completed" for value in delivered)
    intent = admit_output_cleanup(case, mode=mode)
    run_before = life.runs.read_item("run-1", "conversation-1")
    life.results.sources.clear()
    life.results.container.fail_reads = True
    life.now += timedelta(seconds=11)
    outcome = scheduler.check_due_orchestration_runs_once(
        max_runs=0, resources=cleanup_only_resources(case),
    )
    stored = [life.runs.read_item(output["output_id"], "conversation-1") for output in outputs]
    run = life.runs.read_item("run-1", "conversation-1")
    guard = life.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
    assert outcome["ok"] is True, outcome
    assert outcome["counts"]["cleanup_run_selectors"] == outcome["counts"]["cleanup_runs_enrolled"] == 1
    assert outcome["counts"]["cleanup_outputs_enrolled"] == outcome["counts"]["outputs_processed"] == 2
    assert run["output_cleanup"] == {**intent, "state": "completed"}
    assert run["render_output_ids"] == run_before["render_output_ids"]
    assert run["task_results"] == run_before["task_results"] and run["status"] == run_before["status"]
    assert all(value["state"] == "cancelled" and value["deleted_at"] for value in stored)
    assert all(not value["cleanup_pending"] and value["attempt_count"] == 1 for value in stored)
    assert guard["deleted"] is True and guard["token"] is None
    assert life.messages.items == baseline and not life.blobs.data
    assert len(life.render_calls) == life.blobs.uploads == life.blobs.deletes == 2


def test_enrollment_preserves_the_frozen_archive_policy_and_committed_sibling(file_lifecycle):
    from test_orchestration_output_cleanup import interrupted_output

    case, life = file_lifecycle, file_lifecycle.life
    completed = life.prepare(step_id="retained-file")
    success = life.run(completed)
    retained = life.raw(completed)
    staged = interrupted_output(life, "blob")
    intent = admit_output_cleanup(case, retain_committed=True)
    life.now += timedelta(seconds=11)
    outcome = scheduler.check_due_orchestration_runs_once(
        max_runs=0, resources=cleanup_only_resources(case),
    )
    saved = life.runs.read_item(completed["output_id"], "conversation-1")
    discarded = life.runs.read_item(staged["output_id"], "conversation-1")
    run = life.runs.read_item("run-1", "conversation-1")
    artifact = life.messages.read_item(success["artifact_message_id"], "conversation-1")
    assert outcome["ok"] is True, outcome
    assert outcome["cleanup_enrollments"][0]["retain_committed"] is True
    assert run["output_cleanup"] == {**intent, "state": "completed"}
    assert saved["state"] == "completed" and not saved["deleted_at"] and not saved["cleanup_pending"]
    assert saved["committed_intent"] == retained["committed_intent"]
    assert saved["attempt_count"] == retained["attempt_count"] == 1
    assert discarded["state"] == "cancelled" and discarded["deleted_at"] and not discarded["cleanup_pending"]
    assert artifact["id"] == success["artifact_message_id"] and len(life.blobs.data) == 1
    assert len(life.render_calls) == life.blobs.uploads == 2 and life.blobs.deletes == 1


def test_enrollment_restarts_after_a_process_dies_between_exact_output_tombstones(file_lifecycle, monkeypatch):
    from test_orchestration_output_lifecycle import Crash

    case, life = file_lifecycle, file_lifecycle.life
    outputs = [life.prepare(step_id=f"file-{index}") for index in range(2)]
    for output in outputs:
        result = life.run(output)
        assert result["state"] == "completed"
    intent = admit_output_cleanup(case)
    batch = life.runs.execute_item_batch

    def crash_after_first_tombstone(*args, **kwargs):
        result = batch(*args, **kwargs)
        first = life.runs.read_item(outputs[0]["output_id"], "conversation-1")
        if first.get("deleted_at"):
            raise Crash("The process died after the first output tombstone.")
        return result

    with monkeypatch.context() as stopped:
        stopped.setattr(life.runs, "execute_item_batch", crash_after_first_tombstone)
        with pytest.raises(Crash):
            scheduler.check_due_orchestration_runs_once(
                max_runs=0, max_outputs=0, resources=cleanup_only_resources(case),
            )
    interrupted = life.runs.read_item("run-1", "conversation-1")
    first = life.runs.read_item(outputs[0]["output_id"], "conversation-1")
    second = life.runs.read_item(outputs[1]["output_id"], "conversation-1")
    assert interrupted["output_cleanup"] == intent and intent["state"] == "pending"
    assert first["deleted_at"] and second["state"] == "completed" and not second["cleanup_pending"]
    life.now += timedelta(seconds=11)
    resumed = scheduler.check_due_orchestration_runs_once(
        max_runs=0, resources=cleanup_only_resources(case),
    )
    repeated = scheduler.check_due_orchestration_runs_once(
        max_runs=0, resources=cleanup_only_resources(case),
    )
    run = life.runs.read_item("run-1", "conversation-1")
    assert resumed["ok"] is True and repeated["ok"] is True, (resumed, repeated)
    assert resumed["counts"]["cleanup_outputs_enrolled"] == resumed["counts"]["outputs_processed"] == 2
    assert repeated["counts"]["cleanup_run_selectors"] == repeated["counts"]["output_selectors"] == 0
    assert run["output_cleanup"] == {**intent, "state": "completed"} and not life.blobs.data
    assert len(life.render_calls) == life.blobs.uploads == life.blobs.deletes == 2


def test_due_cleanup_survives_process_death_after_completed_enrollment(file_lifecycle, monkeypatch):
    from test_orchestration_output_lifecycle import Crash

    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare()
    success = life.run(output)
    assert success["state"] == "completed"
    intent = admit_output_cleanup(case)
    query = case.queries.query_items

    def crash_before_output_discovery(*args, **kwargs):
        parameters = kwargs.get("parameters") or []
        if any(item == {"name": "@record_type", "value": "orchestration_output_v1"} for item in parameters):
            raise Crash("The process died before due-output discovery.")
        return query(*args, **kwargs)

    with monkeypatch.context() as stopped:
        stopped.setattr(case.queries, "query_items", crash_before_output_discovery)
        with pytest.raises(Crash):
            scheduler.check_due_orchestration_runs_once(
                max_runs=0, resources=cleanup_only_resources(case),
            )
    run = life.runs.read_item("run-1", "conversation-1")
    withdrawn = life.runs.read_item(output["output_id"], "conversation-1")
    assert run["output_cleanup"] == {**intent, "state": "completed"}
    assert withdrawn["deleted_at"] and withdrawn["cleanup_pending"] and life.blobs.deletes == 0
    life.now += timedelta(seconds=11)
    recovered = scheduler.check_due_orchestration_runs_once(
        max_runs=0, resources=cleanup_only_resources(case),
    )
    after = life.runs.read_item(output["output_id"], "conversation-1")
    assert recovered["ok"] is True and recovered["counts"]["cleanup_run_selectors"] == 0, recovered
    assert recovered["counts"]["output_selectors"] == recovered["counts"]["outputs_processed"] == 1
    assert not after["cleanup_pending"] and not life.blobs.data
    assert after["attempt_count"] == 1 and life.blobs.uploads == life.blobs.deletes == 1


def test_cleanup_enrollment_budget_can_be_disabled_without_consuming_its_reader(file_lifecycle):
    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare()
    success = life.run(output)
    assert success["state"] == "completed"
    admit_output_cleanup(case)
    before = deepcopy(life.runs.items)
    outcome = scheduler.check_due_orchestration_runs_once(
        max_runs=0, max_outputs=0, max_cleanup_runs=0, resources=cleanup_only_resources(case),
    )
    assert outcome["ok"] is True and case.queries.calls == []
    assert outcome["counts"]["cleanup_run_selectors"] == outcome["counts"]["outputs_processed"] == 0
    assert life.runs.items == before and life.blobs.deletes == 0


def test_enrollment_handles_the_full_bounded_admission_index_without_rendering(file_lifecycle):
    from functions_orchestration_output_store import MAX_OUTPUTS_PER_RUN

    case, life = file_lifecycle, file_lifecycle.life
    outputs = [life.prepare(step_id=f"delete-{index}") for index in range(MAX_OUTPUTS_PER_RUN)]
    admitted = [life.raw(output) for output in outputs]
    intent = admit_output_cleanup(case)
    life.results.sources.clear()
    life.results.container.fail_reads = True
    outcome = scheduler.check_due_orchestration_runs_once(
        max_runs=0, max_outputs=0, max_cleanup_runs=1, resources=cleanup_only_resources(case),
    )
    stored = [life.runs.read_item(output["output_id"], "conversation-1") for output in outputs]
    run = life.runs.read_item("run-1", "conversation-1")
    assert outcome["ok"] is True, outcome
    assert outcome["counts"]["cleanup_outputs_enrolled"] == MAX_OUTPUTS_PER_RUN
    assert outcome["counts"]["cleanup_run_selectors"] == outcome["counts"]["cleanup_runs_enrolled"] == 1
    assert run["render_output_ids"] == intent["output_ids"]
    assert run["output_cleanup"] == {**intent, "state": "completed"}
    assert all(value["state"] == "cancelled" and value["deleted_at"] for value in stored)
    assert all(
        (after["attempt_count"], after["automatic_attempts"], after["manual_requests"])
        == (before["attempt_count"], before["automatic_attempts"], before["manual_requests"])
        for before, after in zip(admitted, stored)
    )
    assert not life.render_calls and life.blobs.uploads == life.blobs.deletes == 0


def test_cleanup_enrollment_deduplicates_run_selectors_before_any_mutation(file_lifecycle):
    case, life = file_lifecycle, file_lifecycle.life
    life.prepare()
    admit_output_cleanup(case)
    selector = {"id": "run-1", "user_id": "owner", "conversation_id": "conversation-1"}
    case.queries.override = lambda kind: [selector, selector] if kind == "cleanup_runs" else []
    outcome = scheduler.check_due_orchestration_runs_once(
        max_runs=0, max_outputs=0, resources=cleanup_only_resources(case),
    )
    assert outcome["ok"] is True, outcome
    assert outcome["counts"]["cleanup_run_selectors"] == outcome["counts"]["cleanup_runs_enrolled"] == 1
    assert outcome["counts"]["cleanup_outputs_enrolled"] == 1
    assert len(outcome["cleanup_enrollments"]) == 1 and not life.render_calls


@pytest.mark.parametrize("failure", ["missing_guard", "guard_outage", "changed_index"])
def test_failed_enrollment_preserves_authority_and_never_falls_back_to_live_execution(
    file_lifecycle, failure, monkeypatch,
):
    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare()
    result = life.run(output)
    assert result["state"] == "completed"
    intent = admit_output_cleanup(case)
    before = deepcopy(life.runs.items)
    blobs, messages = deepcopy(life.blobs.data), deepcopy(life.messages.items)
    if failure == "missing_guard":
        guard = life.cleanup_guards.read_item("checkpoint:lifecycle", "run-1")
        life.cleanup_guards.delete_item("checkpoint:lifecycle", "run-1", etag=guard["_etag"])
    elif failure == "guard_outage":
        monkeypatch.setattr(life.cleanup_guards, "fail_reads", True)
    else:
        replace_record(life.runs, "run-1", "conversation-1", render_output_ids=[])
        before = deepcopy(life.runs.items)
    outcome = scheduler.check_due_orchestration_runs_once(resources=cleanup_only_resources(case))
    run = life.runs.read_item("run-1", "conversation-1")
    assert outcome["ok"] is False and outcome["counts"]["cleanup_runs_enrolled"] == 0
    assert outcome["counts"]["runs_executed"] == outcome["counts"]["outputs_processed"] == 0
    assert len(outcome["errors"]) == 1 and outcome["errors"][0]["scope"] == "cleanup_enrollment"
    assert outcome["errors"][0]["retryable"] is (failure == "guard_outage")
    assert run["output_cleanup"] == intent and life.runs.items == before
    assert life.blobs.data == blobs and life.messages.items == messages and life.blobs.deletes == 0


def test_deletion_enrollment_is_not_inferred_without_an_explicit_durable_policy(file_lifecycle):
    from test_orchestration_output_cleanup import delete_conversation

    case, life = file_lifecycle, file_lifecycle.life
    output = life.prepare()
    result = life.run(output)
    assert result["state"] == "completed"
    delete_conversation(life, "missing")
    before = deepcopy(life.runs.items)
    outcome = scheduler.check_due_orchestration_runs_once(resources=cleanup_only_resources(case))
    assert outcome["ok"] is True and outcome["counts"]["cleanup_run_selectors"] == 0
    assert outcome["counts"]["outputs_processed"] == outcome["counts"]["runs_executed"] == 0
    assert life.runs.items == before and life.blobs.data and life.blobs.deletes == 0


@pytest.mark.parametrize("mode", ["missing", "deleted", "orchestration_deleted"])
@pytest.mark.parametrize("boundary", ["blob", "message"])
@pytest.mark.parametrize("max_runs", [0, 4])
def test_scheduler_cleanup_survives_real_conversation_deletion(file_lifecycle, mode, boundary, max_runs, monkeypatch):
    from test_orchestration_output_cleanup import delete_conversation, interrupted_output

    case, life = file_lifecycle, file_lifecycle.life
    baseline_messages = deepcopy(life.messages.items)
    output = interrupted_output(life, boundary)
    original = life.raw(output)
    delete_conversation(life, mode)
    life.results.sources.clear()
    life.results.container.fail_reads = True
    life.now += timedelta(seconds=11)

    def forbidden(*args, **kwargs):
        raise AssertionError("Deletion-only cleanup invoked a renderer or native reconciliation.")

    monkeypatch.setattr(life.service, "render_attempt", forbidden)
    monkeypatch.setattr(life.service, "reconcile", forbidden)
    resources = cleanup_only_resources(case)
    first = scheduler.check_due_orchestration_runs_once(max_runs=max_runs, resources=resources)
    life.now += timedelta(seconds=11)
    second = scheduler.check_due_orchestration_runs_once(max_runs=0, resources=resources)
    stored = life.runs.read_item(output["output_id"], "conversation-1")
    assert first["ok"] is True, first
    assert second["ok"] is True, second
    assert first["counts"]["output_selectors"] == 1
    assert first["counts"]["runs_executed"] == second["counts"]["runs_executed"] == 0
    assert stored["state"] == "cancelled" and stored["deleted_at"]
    assert stored["cleanup_pending"] is False and stored["lease"] is None
    assert stored["attempt_count"] == original["attempt_count"] == 1
    assert stored["automatic_attempts"] == original["automatic_attempts"] == 1
    assert life.messages.items == baseline_messages and not life.blobs.data
    assert len(life.render_calls) == life.blobs.uploads == life.blobs.deletes == 1
    assert not any(item.get("id") == "conversation-1" for item in life.messages.items.values())
    if mode == "missing":
        assert ("conversation-1", "conversation-1") not in life.conversations.items


def test_scheduler_does_not_infer_deletion_authority_from_a_bare_404(file_lifecycle):
    from test_orchestration_output_cleanup import delete_conversation, interrupted_output

    case, life = file_lifecycle, file_lifecycle.life
    output = interrupted_output(life)
    before = life.runs.read_item(output["output_id"], "conversation-1")
    messages = deepcopy(life.messages.items)
    blobs = deepcopy(life.blobs.data)
    delete_conversation(life, "missing", retain_guard=False)
    life.now += timedelta(seconds=11)
    outcome = scheduler.check_due_orchestration_runs_once(max_runs=0, resources=cleanup_only_resources(case))
    current = life.runs.read_item(output["output_id"], "conversation-1")
    assert outcome["ok"] is False and outcome["counts"]["outputs_processed"] == 0
    assert len(outcome["errors"]) == 1
    assert outcome["errors"][0]["code"] == "output_cleanup_tombstone_required"
    assert outcome["errors"][0]["retryable"] is False
    assert current == before and current["attempt_count"] == 1
    assert life.blobs.data == blobs and life.messages.items == messages and life.blobs.deletes == 0
    assert len(life.render_calls) == 1


@pytest.mark.parametrize("authority", ["run_owner", "run_missing", "admission_missing", "conversation_owner"])
def test_scheduler_cleanup_never_grants_execution_to_invalid_authority(file_lifecycle, authority, monkeypatch):
    from test_orchestration_output_cleanup import interrupted_output

    case, life = file_lifecycle, file_lifecycle.life
    output = interrupted_output(life)
    run = life.runs.read_item("run-1", "conversation-1")
    if authority == "run_missing":
        life.runs.delete_item("run-1", "conversation-1", etag=run["_etag"])
    elif authority == "conversation_owner":
        conversation = life.conversations.read_item("conversation-1", "conversation-1")
        conversation["user_id"] = "someone-else"
        life.conversations.upsert_item(conversation)
    else:
        run.update({"user_id": "someone-else"} if authority == "run_owner" else {"render_output_ids": []})
        life.runs.upsert_item(run)
    before_blobs = deepcopy(life.blobs.data)
    before_messages = deepcopy(life.messages.items)
    life.now += timedelta(seconds=11)

    def forbidden(*args, **kwargs):
        raise AssertionError("Cleanup denial was incorrectly treated as permission to render.")

    monkeypatch.setattr(life.service, "render_attempt", forbidden)
    outcome = scheduler.check_due_orchestration_runs_once(max_runs=0, resources=case.resources)
    stored = life.runs.read_item(output["output_id"], "conversation-1")
    assert outcome["ok"] is False and outcome["counts"]["outputs_processed"] == 0
    assert all(error["error_type"] != "AssertionError" for error in outcome["errors"])
    assert stored["attempt_count"] == 1 and not stored["deleted_at"]
    assert life.blobs.data == before_blobs and life.messages.items == before_messages
    assert len(life.render_calls) == 1 and life.blobs.deletes == 0


@pytest.mark.parametrize("store", ["conversations", "runs", "messages"])
def test_scheduler_cleanup_outage_retains_uncertain_state_without_retrying_work(file_lifecycle, store, monkeypatch):
    from test_orchestration_output_cleanup import interrupted_output

    case, life = file_lifecycle, file_lifecycle.life
    output = interrupted_output(life)
    life.service.store.cancel(output["output_id"])
    life.now += timedelta(seconds=11)
    before = life.raw(output)
    messages = deepcopy(life.messages.items)
    blobs = deepcopy(life.blobs.data)
    with monkeypatch.context() as scoped:
        scoped.setattr(getattr(life, store), "fail_reads", True)
        outcome = scheduler.check_due_orchestration_runs_once(
            max_runs=0, resources=cleanup_only_resources(case),
        )
    stored = life.raw(output)
    assert outcome["ok"] is False and outcome["counts"]["outputs_processed"] == 0
    assert len(outcome["errors"]) == 1 and outcome["errors"][0]["retryable"] is True
    assert outcome["errors"][0]["code"] == "storage_unavailable"
    assert outcome["errors"][0]["scope"] == "output_cleanup"
    assert stored == before and stored["cleanup_pending"] is True
    assert life.messages.items == messages and life.blobs.data == blobs and life.blobs.deletes == 0
    assert stored["attempt_count"] == 1 and len(life.render_calls) == 1


def test_scheduler_cleanup_keeps_current_success_and_removes_only_obsolete_intents(file_lifecycle, monkeypatch):
    from test_orchestration_output_cleanup import interrupted_output

    case, life = file_lifecycle, file_lifecycle.life
    output = interrupted_output(life, "before_blob")
    life.now += timedelta(seconds=11)
    life.service.reconcile(output["output_id"])
    life.advance_due(output)
    completed = life.run(output)
    before = life.raw(completed)
    before_messages = deepcopy(life.messages.items)
    life.results.sources.clear()
    life.results.container.fail_reads = True
    life.now += timedelta(seconds=11)
    outcome = scheduler.check_due_orchestration_runs_once(max_runs=0, resources=cleanup_only_resources(case))
    current = life.raw(completed)
    assert outcome["ok"] is True and outcome["counts"]["outputs_processed"] == 1
    assert outcome["outputs"][0]["cleanup_status"] == "complete"
    assert current["state"] == "completed" and current["committed_intent"] == before["committed_intent"]
    assert current["cleanup_pending"] is False and len(life.blobs.data) == 1
    assert life.messages.items == before_messages and life.blobs.deletes == 0
    assert len(life.render_calls) == 2 and current["automatic_attempts"] == before["automatic_attempts"]


def test_live_pending_delivery_follows_cleanup_on_a_separate_tick(file_lifecycle, harness):
    from test_orchestration_output_cleanup import interrupted_output

    case, life = file_lifecycle, file_lifecycle.life
    output = interrupted_output(life, "before_blob")
    life.now += timedelta(seconds=11)
    life.service.reconcile(output["output_id"])
    life.advance_due(output)
    completed = life.run(output)
    life.now += timedelta(seconds=11)
    cleanup = scheduler.check_due_orchestration_runs_once(resources=cleanup_only_resources(case))
    current_output = life.raw(completed)
    after_cleanup = harness.read()
    assert cleanup["ok"] is True and cleanup["counts"]["run_selectors"] == 1, cleanup
    assert cleanup["counts"]["outputs_processed"] == 1 and not current_output["cleanup_pending"]
    assert after_cleanup["finalization_status"] == "pending"
    delivery = scheduler.check_due_orchestration_runs_once(resources=case.resources)
    current = harness.read()
    messages = harness.assistant_messages()
    assert delivery["ok"] is True and delivery["counts"]["output_selectors"] == 0, delivery
    assert current["status"] == "completed" and current["finalization_status"] == "saved"
    assert len(messages) == 1 and len(life.render_calls) == 2 and len(harness.model_calls) == 1


_COLD_LOOP = r'''
import importlib
import pathlib
import socket
import sys
from unittest.mock import patch

root = pathlib.Path.cwd()
app = root / "application" / "single_app"
sys.path[:0] = [str(app), str(root / "functional_tests")]

def blocked(*args, **kwargs):
    raise AssertionError("Unexpected network access.")

with patch.object(socket.socket, "connect", blocked), patch.object(socket, "create_connection", blocked):
    scheduler = importlib.import_module("functions_orchestration_scheduler")
    if "config" in sys.modules or "functions_orchestration_bootstrap" in sys.modules:
        raise AssertionError("Importing the scheduler initialized application owners.")

import pytest
from flask import Flask
from test_support import offline_bootstrap
from test_support.orchestration_harness_execution import HarnessEnvironment, project_session_cache

class StopLoop(BaseException):
    pass

with patch.object(offline_bootstrap, "TemporaryDirectory", project_session_cache):
    with offline_bootstrap.offline_app_imports() as offline, pytest.MonkeyPatch.context() as monkeypatch:
        environment = HarnessEnvironment(monkeypatch)
        background = importlib.import_module("background_tasks")
        settings = importlib.import_module("functions_settings")
        monkeypatch.setattr(settings, "get_settings", lambda: environment.settings)
        calls, releases, sleeps, ticks = [], [], [], []
        lock = {"id": "owned-scan-lock"}
        def acquire(name, *, lease_seconds):
            calls.append((name, lease_seconds))
            return lock
        def sleep(seconds):
            sleeps.append(seconds)
            raise StopLoop()
        original_tick = scheduler.check_due_orchestration_runs_once
        def run_tick(**kwargs):
            ticks.append((kwargs, original_tick(**kwargs)))
        monkeypatch.setattr(background, "acquire_distributed_task_lock", acquire)
        monkeypatch.setattr(background, "release_distributed_task_lock", releases.append)
        monkeypatch.setattr(background.time, "sleep", sleep)
        monkeypatch.setattr(scheduler, "check_due_orchestration_runs_once", run_tick)
        flask_app = Flask("real-scheduler-loop") if sys.argv[1] == "app" else None
        try:
            background.run_orchestration_scheduler_loop(flask_app)
        except StopLoop:
            pass
        else:
            raise AssertionError("The loop did not reach its bounded slice.")
        if calls != [("orchestration_harness_scheduler_scan", 120)] or releases != [lock] or sleeps != [30]:
            raise AssertionError("The real distributed scan lock was not released.")
        if len(ticks) != 1 or ticks[0][0] != {"max_runs": 4, "max_outputs": 8}:
            raise AssertionError("The real loop did not invoke the bounded scheduler.")
        if not ticks[0][1]["ok"] or ticks[0][1]["counts"]["errors"]:
            raise AssertionError(ticks)
        if environment.model_calls or environment.clients or offline.network_attempts:
            raise AssertionError("The headless scheduler called a provider.")
        if pathlib.Path(background.__file__).resolve().parent != app:
            raise AssertionError("A fake background module was imported.")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("with_app", [False, True])
def test_real_cold_scheduler_and_background_loop_normal_and_optimized(optimized, with_app):
    command = [sys.executable, *(["-O"] if optimized else []), "-c", _COLD_LOOP, "app" if with_app else "headless"]
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=150)
    assert process.returncode == 0, process.stdout + process.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
