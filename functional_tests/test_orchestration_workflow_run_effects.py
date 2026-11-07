#!/usr/bin/env python3
# test_orchestration_workflow_run_effects.py
"""
Functional test for registry-driven external effects in chat orchestration.
Version: 0.261.212
Implemented in: 0.261.212

This test ensures that the capabilities whose steps may already have acted outside a plan when
they fail, stop or are interrupted come from the capability registry's ``external_effects`` flag,
and that they are exactly agent_invoke, action_invoke and workflow_run. The executor marks a
failed, stopped or interrupted step of one of them effects_uncertain, and a retry of its plan asks
the user to confirm first. No orchestration module keeps its own list of them.
"""

import ast
import importlib
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_run_adapter import (  # noqa: F401
    SECRET,
    _harness,
    _retry,
    _run_to_end,
    _signed_in,
    adapter,
    chat,
    world,
    wr,
)
from test_orchestration_workflow_run_capability import _handle, _run, planning  # noqa: F401
from test_orchestration_workflow_run_planning_context import wf  # noqa: F401
from test_support.orchestration_harness_execution import compose_step
from test_support.versioning import assert_app_version_at_least


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
EFFECTS = frozenset({"agent_invoke", "action_invoke", "workflow_run"})


def test_the_version_includes_registry_driven_effects():
    assert_app_version_at_least("0.261.212")


def test_the_capabilities_that_act_outside_a_plan_are_read_from_the_registry(modules):
    registry = importlib.import_module("functions_orchestration_registry")
    recovery = importlib.import_module("functions_orchestration_recovery")
    flagged = registry.external_effect_capability_ids()
    assert flagged == EFFECTS
    assert recovery.EFFECT_CAPABILITIES == EFFECTS
    for descriptor in registry.CAPABILITY_REGISTRY:
        # Only a real True counts, so a truthy string or 1 never marks a capability.
        assert descriptor.get("external_effects", False) is (descriptor["id"] in EFFECTS), descriptor["id"]
    assert EFFECTS <= set(registry.all_capability_ids())


def test_no_orchestration_module_keeps_its_own_list_of_them():
    for name in ("functions_orchestration_executor.py", "functions_orchestration_recovery.py"):
        tree = ast.parse((APP_ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
                values = {item.value for item in node.elts if isinstance(item, ast.Constant)}
                assert not values & EFFECTS, (name, node.lineno, sorted(values & EFFECTS))


@pytest.mark.parametrize("status", ["running", "completed", "failed", "cancelled", "waiting"])
def test_a_step_record_is_uncertain_only_while_an_effect_step_is_running(modules, status):
    registry = importlib.import_module("functions_orchestration_registry")
    executor = importlib.import_module("functions_orchestration_executor")
    context = type("Context", (), {"run_id": "run-1"})()
    for capability_id in registry.all_capability_ids():
        step = {"step_id": "s1", "capability_id": capability_id, "role": "gather", "arguments": {}}
        record = executor._step_record(context, step, 0, status, {}, None, None, 0)
        expected = status == "running" and capability_id in EFFECTS
        assert record["effects_uncertain"] is expected, (capability_id, status)


def test_a_failed_run_step_is_uncertain_and_its_retry_asks_the_user_to_confirm(world, wr, planning, monkeypatch):
    env = _harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest")), compose_step("answer")],
                   ["Your priorities."])

    def lost_reply():
        raise AzureError(SECRET)

    # The run is queued, but the step never hears back, so it may have started the workflow.
    world.after_queue = lost_reply
    execution = _signed_in(env.prepare())
    assert _run_to_end(env, execution)["status"] == "failed"
    first = env.steps.read_item("run-1:run_digest", "run-1")
    assert first["status"] == "failed" and first["effects_uncertain"] is True
    recovery = env.recovery.recovery_projection(env.read())
    assert recovery["eligible"] is True and recovery["requires_confirmation"] is True

    with pytest.raises(env.recovery.RecoveryError) as refused:
        _retry(env, execution)
    assert refused.value.code == "confirmation_required"
    assert len(world.queued) == 1

    # Confirmed, the retry links the run the first attempt started instead of starting another.
    child, second = _retry(env, execution, confirm=True)
    assert _run_to_end(env, second)["status"] == "completed"
    assert child["retry_confirmed_external_effects"] is True
    assert len(world.queued) == 1


def test_a_run_step_that_finished_leaves_nothing_uncertain(world, wr, planning, monkeypatch):
    env = _harness(monkeypatch, planning, [_run(_handle(planning, "Weekly digest")), compose_step("answer")],
                   [RuntimeError("FIXTURE_FAILURE")])
    execution = _signed_in(env.prepare())
    assert _run_to_end(env, execution)["status"] == "failed"
    first = env.steps.read_item("run-1:run_digest", "run-1")
    assert first["status"] == "completed" and first["effects_uncertain"] is False
    assert env.recovery.recovery_projection(env.read())["requires_confirmation"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
