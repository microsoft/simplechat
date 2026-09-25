# test_orchestration_route_recovery.py
"""Functional route regressions for current orchestration recovery.

Version: 0.261.139
Implemented in: 0.261.105
Single orchestration contract updated in: 0.261.139

The legacy checkpoint route fixture was removed with the v1 plan contract. These
checks keep route-level recovery behavior that still matters for Gather / Reason /
Render: failed attempts can be retried without replaying completed producers, and
ownership/legacy fencing happens before recovery or execution services mutate state.
"""

import json

import pytest

from test_orchestration_harness_routes import RETRY_ID, login, modules, real_http_harness, runtime  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.versioning import assert_app_version_at_least


LEGACY_MESSAGE = (
    "This plan was created by an earlier orchestration version and can't be opened or "
    "rerun. Start a new request."
)


def frames(response):
    return [
        json.loads(line[5:].strip())
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data:") and line[5:].strip() != "[DONE]"
    ]


def _dependent_plan_steps():
    retained = compose_step("retained")
    failed = compose_step("failed")
    answer = compose_step("answer", inputs={
        "retained": {"binding": input_binding("retained"), "allow_partial": False},
        "failed": {"binding": input_binding("failed"), "allow_partial": False},
    })
    return [retained, failed, answer]


def _run(runtime, run_id="run-1", **body):
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": run_id,
        **body,
    }, buffered=True)
    return response, frames(response)


def _detail(runtime, run_id="run-1"):
    response = runtime.client.get(f"/api/v2/orchestration/runs/{run_id}", query_string={
        "conversation_id": "conversation-1",
    })
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["run"]


def test_application_version_includes_single_contract_recovery():
    assert_app_version_at_least("0.261.139")


def test_route_retry_reuses_completed_producer_without_recalling_it(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.create(
        _dependent_plan_steps(), replies=["Exact retained draft.", RuntimeError("private failed compose")],
        final_response=input_binding("answer"),
    )

    response, events = _run(runtime)
    terminal = next(event for event in events if event.get("type") == "orchestration_done")
    assert response.status_code == 200
    assert terminal["status"] == "failed"
    assert _detail(runtime)["recovery"]["eligible"] is True
    assert len(harness.model_calls) == 2

    retry = runtime.client.post("/api/v2/orchestration/runs/run-1/retry", json={
        "conversation_id": "conversation-1", "submission_id": RETRY_ID,
        "expected_version": _detail(runtime)["recovery"]["expected_version"],
        "confirm_external_effects": True,
    })
    assert retry.status_code == 200, retry.get_data(as_text=True)
    child = retry.get_json()["run"]
    assert child["recovery"]["reused_step_ids"] == ["retained"]

    assert len(harness.model_calls) == 2
    steps = runtime.client.get(
        f"/api/v2/orchestration/runs/{child['run_id']}/steps",
        query_string={"conversation_id": "conversation-1"},
    ).get_json()["steps"]
    retained = next(step for step in steps if step["step_id"] == "retained")
    assert retained["reused"] is True
    assert retained["reused_from_run_id"] == "run-1"


def test_retry_rechecks_conversation_owner_before_mutating_recovery(runtime):
    login(runtime, user_id="owner")
    runtime.runs.create_item({
        "id": "saved-run", "run_id": "saved-run", "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "owner", "turn_id": "turn-1",
        "status": "failed", "recovery_version": "version-1",
        "plan": {"planner_contract_version": 2, "steps": []},
    })
    login(runtime, user_id="intruder")

    response = runtime.client.post("/api/v2/orchestration/runs/saved-run/retry", json={
        "conversation_id": "conversation", "submission_id": RETRY_ID,
        "expected_version": "version-1", "confirm_external_effects": True,
    })

    assert response.status_code == 404
    assert runtime.runs.read_item("saved-run", "conversation").get("latest_attempt_run_id") is None


def test_legacy_run_retry_and_execution_fail_closed_without_service_binding(runtime, monkeypatch):
    login(runtime)
    runtime.runs.create_item({
        "id": "legacy-run", "run_id": "legacy-run", "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "owner", "turn_id": "turn-1",
        "status": "failed", "recovery_version": "legacy-version",
        "user_message": "legacy question", "checkpoint_version": 1,
        "execution_binding": "legacy-binding", "started_at": "2026-01-01T00:00:00+00:00",
        "plan": {
            "kind": "plan", "plan_id": "legacy-plan", "run_id": "legacy-run",
            "conversation_id": "conversation", "user_id": "owner", "turn_id": "turn-1",
            "intent": {"summary": "legacy question"},
            "steps": [{"step_id": "answer", "capability_id": "respond"}],
        },
    })
    monkeypatch.setattr(
        runtime.modules.route, "_orchestration_services",
        lambda *args, **kwargs: pytest.fail("legacy runs must not bind execution services"),
    )

    retry = runtime.client.post("/api/v2/orchestration/runs/legacy-run/retry", json={
        "conversation_id": "conversation", "submission_id": RETRY_ID,
        "expected_version": "legacy-version", "confirm_external_effects": True,
    })
    run = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation", "run_id": "legacy-run",
    })

    for response in (retry, run):
        assert response.status_code == 409
        assert response.get_json() == {"error": LEGACY_MESSAGE, "code": "legacy_plan"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
