#!/usr/bin/env python3
# test_orchestration_server_continuation.py
"""
Functional test for the server-side next attempt after a failed orchestration run.
Version: 0.261.478
Implemented in: 0.261.462

This test ensures that a failed attempt is followed by its next one on the server, after the
browser's response has ended and without any request from a page, and that nothing is started
when the setting is off.
"""

import importlib
import json
import os
import sys
import time
import types

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_harness_routes import modules, real_http_harness  # noqa: E402,F401 (fixtures)
from test_support.orchestration_harness_execution import compose_step, input_binding  # noqa: E402


def _answer_report(status):
    return json.dumps({"requirements": [{
        "id": "details", "requirement": "Include status, proposal deadline and response days.",
        "status": status, "reason": "Requested facts omitted." if status == "missing" else "",
        "evidence_refs": [], "answer_quote": "Evaluation" if status == "satisfied" else "",
    }]})


def _wait_for_attempts(harness, count, *, seconds=60):
    """The next attempt runs on the server after the response has ended."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        attempts = [
            item for item in harness.runs.items.values()
            if isinstance(item, dict) and isinstance(item.get("plan"), dict) and item.get("turn_id")
        ]
        if len(attempts) >= count and all(
            item.get("status") in ("completed", "failed", "cancelled") and not item.get("execution_lease")
            for item in attempts
        ):
            return sorted(attempts, key=lambda item: item.get("attempt_index") or 1)
        time.sleep(0.2)
    raise AssertionError("The server did not finish the expected attempts in time: " + json.dumps([
        {key: item.get(key) for key in ("id", "status", "attempt_index", "retry_of_run_id", "latest_attempt_run_id")}
        | {"lease": bool(item.get("execution_lease")), "failure": (item.get("failure") or {}).get("code")}
        for item in attempts
    ]))


def test_the_server_runs_the_next_attempt_after_the_response_has_ended(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings.update(
        enable_chat_orchestration_completeness_check=True,
        enable_chat_orchestration_reactive_loop=True,
        # No recovery inside the run, so the failed attempt itself is what gets followed.
        chat_orchestration_max_recovery_rounds=1,
    )
    record = harness.create(
        steps=[compose_step()],
        replies=[
            "Evaluation", _answer_report("missing"), "Evaluation first", _answer_report("missing"),
            "Evaluation final", _answer_report("missing"),
            # One round inside the run: checked again, corrected twice, still incomplete.
            _answer_report("missing"), "Evaluation third", _answer_report("missing"),
            "Evaluation fourth", _answer_report("missing"),
            # The attempt the server starts by itself checks the retained answer again.
            _answer_report("satisfied"),
        ],
        final_response=input_binding("prepare"),
    )
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    frames = [
        json.loads(frame.partition("data:")[2].strip())
        for frame in response.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]
    # The browser's response ends with the failed attempt; nothing else is asked of it.
    assert response.status_code == 200 and frames[-1]["status"] == "failed"
    first, second = _wait_for_attempts(harness, 2)
    assert first["id"] == record["id"] and first["status"] == "failed"
    assert first["latest_attempt_run_id"] == second["id"]
    assert second["retry_of_run_id"] == record["id"] and second["attempt_index"] == 2
    assert second["status"] == "completed", second.get("failure")
    assert len(harness.model_calls) == 12


def test_the_server_starts_nothing_when_the_setting_is_off(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings.update(enable_chat_orchestration_completeness_check=True)
    record = harness.create(
        steps=[compose_step()],
        replies=[
            "Evaluation", _answer_report("missing"), "Evaluation first", _answer_report("missing"),
            "Evaluation final", _answer_report("missing"),
        ],
        final_response=input_binding("prepare"),
    )
    runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    attempts = _wait_for_attempts(harness, 1)
    time.sleep(1.5)
    assert len(_wait_for_attempts(harness, 1)) == len(attempts) == 1
    assert len(harness.model_calls) == 6


def test_reading_unchanged_memory_again_does_not_change_the_binding(modules, monkeypatch):
    """A next attempt reads saved memory again; only a change in the memory may refuse it."""
    import types

    import functions_fact_memory_context as fact_memory
    from functions_orchestration_checkpoints import context_binding, fingerprint

    def read_memory(value, similarity, moment):
        # The real citation builders, so the fields a real read varies are the ones tested.
        class Clock:
            @staticmethod
            def utcnow():
                return moment

        monkeypatch.setattr(fact_memory, "datetime", Clock)
        fact = {"id": "fact-1", "value": value, "memory_type": "fact", "updated_at": "2026-11-01T00:00:00"}
        return {
            "audience": {"kind": "personal"}, "status": "available", "scope_type": "user",
            "scope": {"type": "user", "id": "user-1"}, "notices": [],
            "context_messages": [{"role": "system", "content": f"- {value}"}],
            "instruction_messages": [{"role": "system", "content": "Answer briefly."}],
            "citations": [
                fact_memory.build_instruction_memory_citation([{**fact, "memory_type": "instruction"}]),
                fact_memory.build_fact_memory_citation("vendor terms", [{**fact, "similarity": similarity}], "embedding"),
            ],
        }

    from datetime import datetime as real_datetime

    plan = {"steps": [], "final_response": None}
    binding = lambda memory: context_binding(types.SimpleNamespace(memory_context=memory), plan, {})
    first = read_memory("Net 30 terms.", 0.812345, real_datetime(2026, 11, 20, 0, 23, 53))
    again = read_memory("Net 30 terms.", 0.812344, real_datetime(2026, 11, 20, 0, 25, 14))
    assert first["citations"] != again["citations"], "the two reads must differ as real reads do"
    assert binding(first) == binding(again)
    changed = read_memory("Net 45 terms.", 0.812345, real_datetime(2026, 11, 20, 0, 23, 53))
    assert binding(first) != binding(changed)
    # Runs saved before this change keep their binding when memory recalled nothing.
    empty = {"audience": {"kind": "personal"}, "status": "empty", "citations": [], "context_messages": []}
    from functions_orchestration_checkpoints import _memory_fingerprint
    assert _memory_fingerprint(empty) == fingerprint(empty) and _memory_fingerprint(None) == fingerprint({})


def test_a_changed_binding_can_name_the_part_that_changed(modules):
    """The binding is one hash; its parts are logged so a mismatch says which part differs."""
    import types

    from functions_orchestration_checkpoints import INPUT_FIELDS, context_binding, context_binding_parts

    plan = {"steps": [], "final_response": None}
    saved = types.SimpleNamespace(
        user_message="Private request text.", model_context={"model_id": "m1"},
        action_catalog=[{"id": "a1"}], allowed_user_urls=["https://example.test/private"],
    )
    resumed = types.SimpleNamespace(**{**vars(saved), "action_catalog": []})
    before, after = (context_binding_parts(item, plan, {}) for item in (saved, resumed))
    assert context_binding(saved, plan, {}) != context_binding(resumed, plan, {})
    assert {name for name in before if before[name] != after[name]} == {"binding_part_action_catalog_digest"}
    # Every part of the binding is covered, each request input separately, and none is content.
    assert set(before) == {
        "binding_part_plan", "binding_part_model", "binding_part_memory_digest",
        "binding_part_agent_catalog_digest", "binding_part_action_catalog_digest",
        "binding_part_settings_digest", "binding_part_final_response",
        *(f"binding_input_{name}" for name in INPUT_FIELDS),
    }
    assert all(len(value) == 12 and int(value, 16) >= 0 for value in before.values())
    assert "Private" not in json.dumps(before) and "example.test" not in json.dumps(before)
    changed = types.SimpleNamespace(**{**vars(saved), "user_message": "Another request."})
    after = context_binding_parts(changed, plan, {})
    assert {name for name in before if before[name] != after[name]} == {"binding_input_user_message"}
    # The parts must survive the log sanitizer, which keeps only allowlisted text: on 0.261.472
    # every part reached the log as a length, so a changed binding still could not name its part.
    telemetry = importlib.import_module("functions_appinsights")
    logged = telemetry._build_logger_extra("[ORCHESTRATION_RUNS] Execution binding parts.", {
        **before, "stage": "execution_binding", "binding_outcome": "changed",
    })
    assert logged["sc_binding_outcome"] == "changed"
    assert {name: logged[f"sc_{name}"] for name in before} == before
    dropped = telemetry._build_logger_extra("Parts.", {
        "binding_part_plan": "Private text", "binding_input_user_message": "0123456789abcdef",
        "binding_outcome": "Private text",
    })
    assert not {"sc_binding_part_plan", "sc_binding_input_user_message", "sc_binding_outcome"} & set(dropped)


def test_a_role_gated_action_is_outside_the_binding_and_still_gated(modules):
    """A run that waits is resumed by a worker with no role claims; that must not refuse it.

    On 0.261.473 both refused resumes named the action catalog as the only changed part. The
    request's catalog lists a role-gated action for a caller who holds the role and the
    worker's never does, so the binding differed whatever the plan used.
    """
    from functions_action_catalog import _is_control_center_action
    from functions_orchestration_checkpoints import (
        bound_action_catalog, context_binding, context_binding_parts, role_gated_action,
    )

    plan = {"steps": [], "final_response": None}
    ordinary = {"action_ref": "global:a1", "id": "a1", "type": "openapi"}
    gated = {"action_ref": "global:cc", "id": "cc", "type": "control_center"}
    assert role_gated_action(gated) and not role_gated_action(ordinary)
    # The binding and the catalog must agree on which actions are role-gated.
    for action in (ordinary, gated, {"type": " Control_Center "}, {"type": None}, {}, None):
        assert role_gated_action(action) == _is_control_center_action(action)
    request = types.SimpleNamespace(user_message="Request.", action_catalog=[ordinary, gated])
    worker = types.SimpleNamespace(user_message="Request.", action_catalog=[ordinary])
    assert context_binding(request, plan, {}) == context_binding(worker, plan, {})
    assert context_binding_parts(request, plan, {}) == context_binding_parts(worker, plan, {})
    # The gate is not the binding: the worker's context still does not list the action, and
    # execution validates every action step against that list.
    assert bound_action_catalog(request) == [ordinary] and gated not in worker.action_catalog
    # Any other action added, removed or changed is still a changed binding.
    for changed in ([], [ordinary, {**ordinary, "action_ref": "global:a2", "id": "a2"}],
                    [{**ordinary, "description": "Changed."}]):
        other = types.SimpleNamespace(user_message="Request.", action_catalog=changed)
        assert context_binding(request, plan, {}) != context_binding(other, plan, {})
    telemetry = importlib.import_module("functions_appinsights")
    logged = telemetry._build_logger_extra("[ORCHESTRATION_RUNS] Execution binding parts.", {
        "action_count": 2, "role_gated_action_count": 1, "agent_count": 0,
    })
    assert (logged["sc_action_count"], logged["sc_role_gated_action_count"]) == (2, 1)


def test_a_partial_analysis_logs_why_as_codes_only(monkeypatch):
    """A partial analysis is the first cause of several downstream failures; say why."""
    results = importlib.import_module("functions_orchestration_analysis_results")
    telemetry = importlib.import_module("functions_appinsights")
    logged = []
    monkeypatch.setattr(
        results, "log_event",
        lambda message, extra=None, **_kwargs: logged.append(telemetry._build_logger_extra(message, extra)),
    )
    producer = types.SimpleNamespace(
        run_id="PRIVATE_RUN", conversation_id="PRIVATE_CONVERSATION", step_id="PRIVATE_STEP",
        capability_id="document_analyze",
    )
    results._log_partial_analysis(producer, {
        "execution": {"status": "succeeded"},
        "validation": {
            "status": "partial", "presentation_status": "ready",
            "coverage": {"status": "complete", "assigned_work_units": 3, "completed_work_units": 3,
                         "failed_work_units": 0, "pending_work_units": 0},
            "issues": [{"code": "requirement_unresolved", "message": "PRIVATE issue text"},
                       {"code": "requirement_unresolved"}, {"code": "evidence_missing"}, "PRIVATE"],
            "finalized_record_count": 12, "unresolved_candidate_count": 2,
            "checks": [{"name": "evidence_matching", "status": "passed"},
                       {"name": "requirement_coverage", "status": "partial"}],
            "limitations": ["PRIVATE limitation"] * 5,
        },
    }, 12, False)
    detail = logged[0]
    assert detail["sc_validation_status"] == "partial" and detail["sc_execution_status"] == "succeeded"
    assert detail["sc_coverage_status"] == "complete" and detail["sc_presentation_status"] == "ready"
    assert detail["sc_validation_issue_codes"] == "evidence_missing,requirement_unresolved"
    assert detail["sc_validation_checks_not_passed"] == "requirement_coverage"
    assert (detail["sc_validation_issue_count"], detail["sc_limitation_count"]) == (3, 5)
    assert (detail["sc_record_count"], detail["sc_completed_work_units"]) == (12, 3)
    assert detail["sc_public_records_available"] is False
    assert (detail["sc_finalized_record_count"], detail["sc_unresolved_candidate_count"]) == (12, 2)
    assert detail["sc_model_stated_issue_count"] == 0
    assert "PRIVATE" not in json.dumps(detail)
    logged.clear()
    results._log_partial_analysis(producer, {"validation": {"status": "partial", "issues": [
        {"code": "unresolved_finding"}, {"code": "window_requirement_unresolved"}, {"code": "unmatched_evidence"},
    ]}}, 0, False)
    assert logged[0]["sc_model_stated_issue_count"] == 2 and logged[0]["sc_validation_issue_count"] == 3


def test_a_complete_analysis_logs_how_many_gaps_it_stated(monkeypatch):
    """0.261.478: a complete analysis with stated gaps is visible in telemetry, as counts."""
    results = importlib.import_module("functions_orchestration_analysis_results")
    telemetry = importlib.import_module("functions_appinsights")
    logged = []
    monkeypatch.setattr(
        results, "log_event",
        lambda message, extra=None, **_kwargs: logged.append(telemetry._build_logger_extra(message, extra)),
    )
    producer = types.SimpleNamespace(
        run_id="PRIVATE_RUN", conversation_id="PRIVATE_CONVERSATION", step_id="PRIVATE_STEP",
        capability_id="document_analyze",
    )
    results._log_stated_gaps(producer, {"validation": {"status": "valid", "finalized_record_count": 4, "stated_gaps": [
        {"scope": "source", "file_name": "PRIVATE.pdf", "statement": "PRIVATE statement"},
        {"scope": "record", "statement": "PRIVATE"}, {"scope": "record", "statement": "PRIVATE"},
        {"scope": "finding", "statement": "PRIVATE"}, "PRIVATE",
    ]}}, 4)
    [detail] = logged
    assert detail["sc_stated_gap_count"] == 4 and detail["sc_record_count"] == 4
    assert (
        detail["sc_stated_gap_source_count"], detail["sc_stated_gap_finding_count"],
        detail["sc_stated_gap_record_count"],
    ) == (1, 1, 2)
    assert detail["sc_finalized_record_count"] == 4
    assert "PRIVATE" not in json.dumps(detail)
    # An analysis that states no gap logs nothing.
    logged.clear()
    results._log_stated_gaps(producer, {"validation": {"status": "valid"}}, 4)
    assert logged == []


def test_stated_gaps_reach_every_reading_step_as_bounded_limitations():
    """0.261.477: each stated gap is a limitation of the result, in the model's words."""
    results = importlib.import_module("functions_orchestration_analysis_results")
    lines = results._stated_gap_limitations({"stated_gaps": [
        {"scope": "source", "file_name": "a.pdf", "statement": "Two renewal\n dates are given."},
        {"scope": "record", "file_name": "a.pdf", "finding_key": "supplier", "statement": "The value is unclear."},
        {"scope": "source", "statement": "x" * 5000},
        {"scope": "source", "statement": "  "}, "not a gap", {"statement": 3},
    ]})
    assert lines[0] == "Not settled by the sources (a.pdf): Two renewal dates are given."
    assert lines[1] == "Not settled by the sources (a.pdf, supplier): The value is unclear."
    assert len(lines) == 3 and all(len(line.encode("utf-8")) <= 1024 and line == line.strip() for line in lines)
    many = results._stated_gap_limitations({"stated_gaps": [
        {"scope": "source", "file_name": "a.pdf", "statement": f"gap {index}"} for index in range(20)
    ]})
    assert len(many) == results.STATED_GAP_LIMITATION_LIMIT + 1
    assert many[-1] == "12 more stated gaps are listed in the analysis report."
    assert results._stated_gap_limitations({}) == []


def test_new_diagnostic_fields_reach_the_log_and_only_as_codes():
    """A field the sanitizer does not know is logged as a length, which diagnoses nothing."""
    telemetry = importlib.import_module("functions_appinsights")
    logged = telemetry._build_logger_extra("[ORCHESTRATION_NATIVE] Calculation program returned to its author.", {
        "correction_category": "numeric_value_is_empty_or_boolean", "correction_origin": "evaluation",
        "correction_check": "step_evaluation", "calls_used": 1, "calls_limit": 3,
    })
    assert logged["sc_correction_check"] == "step_evaluation"
    assert logged["sc_correction_category"] == "numeric_value_is_empty_or_boolean"
    assert logged["sc_correction_origin"] == "evaluation" and logged["sc_calls_used"] == 1
    logged = telemetry._build_logger_extra("[ORCHESTRATION_EXECUTOR] Step outputs do not match the plan.", {
        "task_status": "partial", "declared_outputs": "findings,records,report",
        "produced_outputs": "findings", "outputs_not_produced": "records,report",
        "outputs_of_another_kind": "", "outputs_not_allowed": "",
    })
    assert logged["sc_task_status"] == "partial" and logged["sc_declared_outputs"] == "findings,records,report"
    assert logged["sc_outputs_not_produced"] == "records,report" and logged["sc_outputs_of_another_kind"] == ""
    dropped = telemetry._build_logger_extra("Outputs.", {
        "declared_outputs": "Private text, more", "outputs_not_produced": "a;b",
        "correction_category": "Private text", "task_status": "Private text",
    })
    assert not [name for name in dropped if not name.endswith("_length") and name not in ("sc_message",)]


def test_a_refused_next_attempt_logs_which_check_refused_it(modules):
    """Most refusals share one public code; the log must name the check behind it."""
    from functions_orchestration_checkpoints import CheckpointError
    from functions_orchestration_recovery import RecoveryError

    try:
        try:
            raise CheckpointError(
                "recovery_changed", rule="execution_binding_changed", stage="resume_binding",
                producer_capability_id="tabular_analyze",
            )
        except CheckpointError as inner:
            raise RecoveryError("Saved progress changed.", recovery={"reason_code": "recovery_changed"}) from inner
    except RecoveryError as refused:
        detail = modules.route._refusal_detail(refused)
        assert refused.code == "recovery_unavailable"
    assert detail["cause_type"] == "CheckpointError" and detail["cause_code"] == "recovery_changed"
    assert detail["validation_rule"] == "execution_binding_changed" and detail["refusal_stage"] == "resume_binding"
    assert detail["reason_code"] == "recovery_changed" and detail["producer_capability_id"] == "tabular_analyze"
    assert detail["error_site"].startswith("test_orchestration_server_continuation.py:")
    # A plain error from rebuilding the context has no rule; its type and raise site still show.
    try:
        try:
            raise ValueError("private detail that must not be logged")
        except ValueError as inner:
            raise RecoveryError() from inner
    except RecoveryError as refused:
        detail = modules.route._refusal_detail(refused)
    assert detail["cause_type"] == "ValueError" and "private" not in json.dumps(detail)
    assert set(detail) == {"cause_type", "error_site"}
