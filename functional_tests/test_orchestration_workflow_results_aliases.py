# test_orchestration_workflow_results_aliases.py
"""
Functional test for the workflow_results orchestration capability (saved-result alias exclusion and new-attempt re-reads).
Version: 0.261.217
Implemented in: 0.261.217

This test ensures a run that read a stored workflow result never offers a saved-result alias to a later plan and that a new attempt re-reads the result and re-runs everything computed from it.
"""

import sys
from copy import copy, deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

from functions_orchestration_result_contracts import ResultContractError, TaskResult  # noqa: E402
from test_orchestration_harness_routes import modules  # noqa: E402,F401
from test_orchestration_workflow_results_answer import (  # noqa: E402
    CONVERSATION_ID,
    EXCERPT_MARKER,
    LOCAL_ZONE,
    RESULTS_SETTINGS,
    USER_ID,
    _install_workflow_result_runtime,
    _planning,
    _result_payload,
    _workflow_results_step,
)
from test_support.orchestration_harness_execution import (  # noqa: E402
    HarnessEnvironment,
    compose_step,
    decoded_frames,
    input_binding,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402


NEW_EXCERPT_MARKER = "WORKFLOW_RESULT_EXCERPT_MARKER_NEW_5b92"


@pytest.fixture
def results_module(modules):
    import importlib

    return importlib.import_module("functions_orchestration_workflow_results")


def test_version_is_at_least_workflow_results_aliases_release():
    assert_app_version_at_least("0.261.217")


def _answer_step(step_id="answer", source_step="read_digest"):
    return compose_step(
        step_id,
        inputs={"workflow_notes": {"binding": input_binding(source_step, "result"), "allow_partial": False}},
    )


def _final_step():
    return compose_step(
        "final",
        inputs={"draft": {"binding": input_binding("answer", "answer"), "allow_partial": False}},
    )


def _results_harness_with_steps(monkeypatch, results_module, steps, *, final_response, replies=None, authorize=None):
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(RESULTS_SETTINGS)
    real_normalize = env.schema.normalize_plan

    def normalize(raw, *args, **kwargs):
        capability_ids = kwargs.get("available_capability_ids")
        if capability_ids is not None and "workflow_results" not in capability_ids:
            kwargs["available_capability_ids"] = [*capability_ids, "workflow_results"]
        kwargs.setdefault("workflow_planning", _planning())
        return real_normalize(raw, *args, **kwargs)

    monkeypatch.setattr(env.schema, "normalize_plan", normalize)
    calls = _install_workflow_result_runtime(results_module, monkeypatch, authorize=authorize)
    env.create(
        steps,
        replies=list(replies or ["Composed answer from workflow result."]),
        final_response=final_response,
        workflow_planning=_planning(),
        time_zone=LOCAL_ZONE,
    )
    return env, calls


def _results_harness(monkeypatch, results_module, *, replies=None):
    return _results_harness_with_steps(
        monkeypatch,
        results_module,
        [_answer_step(), _workflow_results_step()],
        final_response=input_binding("answer", "answer"),
        replies=replies,
    )


def _compose_harness(monkeypatch, *, replies=None):
    env = HarnessEnvironment(monkeypatch)
    env.create([compose_step("answer")], replies=list(replies or ["Compose-only answer."]))
    return env


def _execute_prepared(execution):
    emitted = []
    try:
        frames = decoded_frames(execution.execute(emit=emitted.append))
    finally:
        execution.close()
    return frames, emitted


def _run_harness(env):
    execution = env.prepare()
    _execute_prepared(execution)
    return env.read()


def _discover(env, records):
    return env.service_bindings.discover_result_aliases(records, env.services().results)


def _listed_records(env):
    return env.run_store.list_conversation_runs(CONVERSATION_ID, USER_ID, limit=10, strict=True)


def _route_equivalent_alias_dict(env):
    retained = _discover(env, _listed_records(env))
    return {alias: ref.to_dict() for alias, ref in retained["aliases"].items()}


def _assert_empty_discovery(result):
    _check_equal(result, {"aliases": {}, "unavailable_count": 0}, "workflow_results run should offer no aliases")


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def _check_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def _task(record, step_id):
    return TaskResult.from_dict(record["task_results"][step_id])


def _step(record, step_id):
    return next(step for step in record["plan"]["steps"] if step["step_id"] == step_id)


def _retry(env, execution, *, submission_id="explicit-user-retry"):
    parent = env.read()

    def authorize():
        return env.bootstrap.read_owned_conversation(USER_ID, CONVERSATION_ID)

    probe = copy(execution.context)
    probe.result_service = env.services().results
    request = {
        "conversation_id": CONVERSATION_ID,
        "submission_id": submission_id,
        "expected_version": parent["recovery_version"],
    }
    child = env.recovery.prepare_retry(
        parent["id"],
        USER_ID,
        request,
        authorize=authorize,
        message_container=env.messages,
        validate=lambda current: env.recovery.validate_resume(
            current,
            probe,
            env.settings,
            authorize,
            source_run_id=current["id"],
        ),
    )
    services = env.services()
    claimed = env.revisions.claim_plan_run(
        child["id"],
        USER_ID,
        CONVERSATION_ID,
        expected_version=child["edit_version"],
        result_alias_resolver=lambda current: env.service_bindings.admitted_result_aliases(
            current,
            services.results,
        ),
    )
    lease = env.recovery.ExecutionLease(claimed, authorize, message_container=env.messages)
    prepared = env.execution.prepare_harness_execution(claimed, settings=env.settings, lease=lease)
    return child, prepared


def _prepare_retry_child(env, execution):
    child, prepared = _retry(env, execution, submission_id="explicit-user-retry-child-only")
    prepared.close()
    return child


def _read_result_ref_from_completed_run(record):
    return _task(record, "read_digest").output("result")


def _superseded_record_from(record):
    superseded = deepcopy(record)
    superseded.update({
        "id": "run-superseded-predecessor",
        "run_id": "run-superseded-predecessor",
        "status": "superseded",
        "superseded_by_run_id": "run-superseding-revision",
        "superseded_at": "2026-10-01T00:00:00+00:00",
    })
    superseded["plan"] = deepcopy(record["plan"])
    superseded["plan"]["run_id"] = superseded["id"]
    return superseded


def test_completed_workflow_results_run_is_never_discovered_but_compose_only_run_is(monkeypatch, results_module):
    env, _calls = _results_harness(monkeypatch, results_module)
    completed = _run_harness(env)

    _check_equal(completed["status"], "completed", "workflow_results run should complete")
    _check_equal(set(completed["task_results"]), {"answer", "read_digest"}, "completed results should be stored")
    _check_equal(
        _task(completed, "read_digest").producer.capability_id,
        "workflow_results",
        "read task should identify workflow_results as producer",
    )
    _assert_empty_discovery(_discover(env, [completed]))

    listed = _listed_records(env)
    _check_equal([record["id"] for record in listed], ["run-1"], "listed runs should include run-1")
    _assert_empty_discovery(_discover(env, listed))
    _check_equal(_route_equivalent_alias_dict(env), {}, "route projection should not expose aliases")
    _check(
        "run-1" not in {ref["producer"]["run_id"] for ref in _route_equivalent_alias_dict(env).values()},
        "route projection should reference no results-bearing run",
    )

    compose_env = _compose_harness(monkeypatch)
    compose_completed = _run_harness(compose_env)
    _check_equal(compose_completed["status"], "completed", "compose-only run should complete")
    compose_found = _discover(compose_env, [compose_completed])
    _check_equal(compose_found["unavailable_count"], 0, "compose-only direct aliases should be available")
    _check(bool(compose_found["aliases"]), "compose-only direct aliases should be non-empty")
    route_found = _discover(compose_env, _listed_records(compose_env))
    _check_equal(route_found["unavailable_count"], 0, "compose-only route aliases should be available")
    _check(bool(route_found["aliases"]), "compose-only route aliases should be non-empty")


def test_plan_check_excludes_even_without_read_task_result_and_when_read_is_disabled(monkeypatch, results_module):
    env, _calls = _results_harness(monkeypatch, results_module)
    completed = _run_harness(env)

    no_read_task = deepcopy(completed)
    no_read_task["task_results"].pop("read_digest")
    _assert_empty_discovery(_discover(env, [no_read_task]))

    disabled_read = deepcopy(no_read_task)
    _step(disabled_read, "read_digest")["enabled"] = False
    _assert_empty_discovery(_discover(env, [disabled_read]))


def test_producer_check_excludes_workflow_results_task_even_if_plan_step_is_missing(monkeypatch, results_module):
    env, _calls = _results_harness(monkeypatch, results_module)
    completed = _run_harness(env)

    producer_only = deepcopy(completed)
    producer_only["plan"]["steps"] = [
        step for step in producer_only["plan"]["steps"] if step["step_id"] != "read_digest"
    ]
    _assert_empty_discovery(_discover(env, [producer_only]))


def test_partially_executed_workflow_results_run_is_not_discovered(monkeypatch, results_module):
    env, _calls = _results_harness(monkeypatch, results_module, replies=[RuntimeError("FIXTURE_FAILURE")])
    failed = _run_harness(env)

    _check_equal(failed["status"], "failed", "compose failure should fail the run")
    _check("read_digest" in failed["task_results"], "partial run should keep the completed read result")
    _check("answer" not in failed.get("task_results", {}), "partial run should not have answer result")
    _assert_empty_discovery(_discover(env, [failed]))
    _assert_empty_discovery(_discover(env, _listed_records(env)))


def test_superseded_revision_and_retry_attempts_are_excluded(monkeypatch, results_module):
    env, _calls = _results_harness(monkeypatch, results_module)
    completed = _run_harness(env)
    superseded = _superseded_record_from(completed)
    env.runs.create_item(superseded)

    listed_ids = {record["id"] for record in _listed_records(env)}
    _check("run-superseded-predecessor" not in listed_ids, "superseded predecessor should be excluded")
    _assert_empty_discovery(_discover(env, [superseded]))

    retry_env, _retry_calls = _results_harness_with_steps(
        monkeypatch,
        results_module,
        [_final_step(), _answer_step(), _workflow_results_step()],
        final_response=input_binding("final", "answer"),
        replies=["OLD_ANSWER_FOR_SUPERSEDED_RETRY", RuntimeError("FIXTURE_FAILURE")],
    )
    execution = retry_env.prepare()
    _execute_prepared(execution)
    parent = retry_env.read()
    _check_equal(parent["status"], "failed", "retry parent should fail before retry")
    child, prepared = _retry(retry_env, execution, submission_id="retry-for-superseded-test")
    retry_env.replies.extend(["NEW_ANSWER_FOR_SUPERSEDED_RETRY", "FINAL_FOR_SUPERSEDED_RETRY"])
    _execute_prepared(prepared)

    listed = _listed_records(retry_env)
    listed_ids = {record["id"] for record in listed}
    _check({"run-1", child["id"]} <= listed_ids, "retry parent and child should both be listed")
    _assert_empty_discovery(_discover(retry_env, listed))


def test_stored_aliases_refuse_workflow_results_refs_and_clean_aliases_resolve(monkeypatch, results_module):
    env, _calls = _results_harness(monkeypatch, results_module)
    completed = _run_harness(env)
    results = env.services().results
    read_ref = _read_result_ref_from_completed_run(completed)
    tainted_record = {
        "conversation_id": CONVERSATION_ID,
        "user_id": USER_ID,
        "result_aliases": {"saved_x": read_ref.to_dict()},
    }

    with pytest.raises(ResultContractError) as contract_error:
        env.service_bindings.admitted_result_aliases(tainted_record, results)
    _check_equal(
        contract_error.value.code,
        "result_reference_untrusted",
        "workflow_results stored alias should fail the result contract",
    )

    with pytest.raises(env.revisions.PlanRevisionError) as revision_error:
        env.revisions.resolve_revision_result_aliases(
            tainted_record,
            USER_ID,
            result_alias_resolver=lambda current: env.service_bindings.admitted_result_aliases(
                current,
                results,
            ),
        )
    _check_equal(revision_error.value.code, "source_changed", "tainted alias should fail revision resolution")

    compose_env = _compose_harness(monkeypatch)
    compose_completed = _run_harness(compose_env)
    compose_results = compose_env.services().results
    clean_aliases = _discover(compose_env, [compose_completed])["aliases"]
    clean_record = {
        "conversation_id": CONVERSATION_ID,
        "user_id": USER_ID,
        "result_aliases": {alias: ref.to_dict() for alias, ref in clean_aliases.items()},
    }
    resolved = compose_env.revisions.resolve_revision_result_aliases(
        clean_record,
        USER_ID,
        result_alias_resolver=lambda current: compose_env.service_bindings.admitted_result_aliases(
            current,
            compose_results,
        ),
    )
    _check_equal(resolved, clean_aliases, "clean compose-only aliases should resolve exactly")


def test_retry_new_attempt_rereads_workflow_result_and_reruns_computed_steps(monkeypatch, results_module):
    old_answer = "OLD_ANSWER_UNIQUE_2a08"
    new_answer = "NEW_ANSWER_UNIQUE_9e31"
    final_answer = "FINAL_UNIQUE_7c44"
    env, calls = _results_harness_with_steps(
        monkeypatch,
        results_module,
        [_final_step(), _answer_step(), _workflow_results_step()],
        final_response=input_binding("final", "answer"),
        replies=[old_answer, RuntimeError("FIXTURE_FAILURE")],
    )
    execution = env.prepare()
    _execute_prepared(execution)
    parent = env.read()
    _check_equal(parent["status"], "failed", "first attempt should fail at final step")
    _check_equal(set(parent["task_results"]), {"read_digest", "answer"}, "first attempt should store read and answer")

    projection = env.recovery.recovery_projection(parent)
    _check_equal(
        set(projection["retry_step_ids"]),
        {"read_digest", "answer", "final"},
        "new attempt should retry the read and all consumers",
    )
    _check_equal(projection["reused_step_ids"], [], "new attempt should not reuse workflow_results consumers")

    def read_new_result(user_id, workflow_id, run_id, **options):
        calls["reader"].append((user_id, workflow_id, run_id, deepcopy(options)))
        return _result_payload(marker=NEW_EXCERPT_MARKER)

    monkeypatch.setattr(results_module, "_read_result", read_new_result)
    env.replies.extend([new_answer, final_answer])
    child, prepared = _retry(env, execution)
    _execute_prepared(prepared)
    child_record = env.runs.read_item(child["id"], CONVERSATION_ID)

    step_reads = [call for call in calls["reader"] if "expected_sha256" not in call[3]]
    _check_equal(len(step_reads), 2, "workflow_results read step should execute once per attempt")
    _check_equal(child_record["status"], "completed", "retry child should complete")
    _check(final_answer in child_record["message"], "retry child message should contain the new final answer")
    for step_id in ("read_digest", "answer"):
        step = env.steps.read_item(f"{child['id']}:{step_id}", child["id"])
        _check_equal(step["status"], "completed", f"{step_id} should complete in the retry child")
        _check(step.get("reused_from_run_id") in (None, ""), f"{step_id} should not be reused from parent")
        _check_equal(_task(child_record, step_id).producer.run_id, child["id"], f"{step_id} result should be new")
    _check(NEW_EXCERPT_MARKER not in child_record["message"], "raw new excerpt should stay out of answer")
    _check(EXCERPT_MARKER not in child_record["message"], "raw old excerpt should stay out of answer")
    _check(old_answer not in child_record["message"], "old answer text should not carry into retry child")
    _check(final_answer in env.assistant_messages()[-1]["content"], "delivered retry answer should be the new final")


def test_disabled_workflow_results_read_invalidates_retained_consumers_only_for_new_attempt(monkeypatch, results_module):
    env, _calls = _results_harness_with_steps(
        monkeypatch,
        results_module,
        [_final_step(), _answer_step(), _workflow_results_step()],
        final_response=input_binding("final", "answer"),
        replies=["ANSWER_FOR_INVALIDATION", "FINAL_FOR_INVALIDATION"],
    )
    completed = _run_harness(env)
    retained = ["read_digest", "answer", "final"]

    disabled = deepcopy(completed)
    _step(disabled, "read_digest")["enabled"] = False
    invalidated_disabled = env.recovery._reuse_invalidated_by_rerun(disabled, retained)
    _check_equal(
        invalidated_disabled,
        {"read_digest", "answer", "final"},
        "disabled read should invalidate itself and retained consumers",
    )

    same_attempt = env.recovery._reuse_invalidated_by_rerun(disabled, retained, new_attempt=False)
    _check_equal(same_attempt, set(), "same-attempt restore should not invalidate the disabled read")

    enabled = deepcopy(completed)
    invalidated_enabled = env.recovery._reuse_invalidated_by_rerun(enabled, retained)
    _check_equal(
        invalidated_enabled,
        {"read_digest", "answer", "final"},
        "enabled read should invalidate itself and retained consumers",
    )


def test_retry_child_refuses_edits_inherited_parent_changes_and_completed_run_edits(monkeypatch, results_module):
    env, _calls = _results_harness_with_steps(
        monkeypatch,
        results_module,
        [_final_step(), _answer_step(), _workflow_results_step()],
        final_response=input_binding("final", "answer"),
        replies=["ANSWER_BEFORE_REFUSAL", RuntimeError("FIXTURE_FAILURE")],
    )
    execution = env.prepare()
    _execute_prepared(execution)
    child = _prepare_retry_child(env, execution)
    stored_child = env.runs.read_item(child["id"], CONVERSATION_ID)
    services = env.services()

    with pytest.raises(env.revisions.PlanRevisionError) as retry_edit_error:
        env.revisions.claim_plan_run(
            child["id"],
            USER_ID,
            CONVERSATION_ID,
            expected_version=stored_child["edit_version"],
            edits={"disabled_step_ids": ["read_digest"]},
            result_alias_resolver=lambda current: env.service_bindings.admitted_result_aliases(
                current,
                services.results,
            ),
        )
    _check_equal(retry_edit_error.value.code, "plan_changed", "retry child edits should be refused")
    _check(
        _step(env.runs.read_item(child["id"], CONVERSATION_ID), "read_digest").get("enabled", True) is True,
        "refused edit should leave read_digest enabled",
    )

    parent = env.runs.read_item("run-1", CONVERSATION_ID)
    env.recovery._validate_inherited_parent(stored_child, parent)

    disabled_child = deepcopy(stored_child)
    _step(disabled_child, "read_digest")["enabled"] = False
    with pytest.raises(env.recovery.CheckpointError) as disabled_error:
        env.recovery._validate_inherited_parent(disabled_child, parent)
    _check_equal(disabled_error.value.code, "recovery_changed", "disabled inherited read should be refused")

    removed_child = deepcopy(stored_child)
    removed_child["plan"]["steps"] = [
        step for step in removed_child["plan"]["steps"] if step["step_id"] != "read_digest"
    ]
    with pytest.raises(env.recovery.CheckpointError) as removed_error:
        env.recovery._validate_inherited_parent(removed_child, parent)
    _check_equal(removed_error.value.code, "recovery_changed", "removed inherited read should be refused")

    completed_env, _completed_calls = _results_harness(monkeypatch, results_module)
    completed = _run_harness(completed_env)
    with pytest.raises(completed_env.revisions.PlanRevisionError) as completed_error:
        completed_env.revisions._assert_editable(completed)
    _check_equal(completed_error.value.code, "plan_changed", "completed run should not be editable")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
