#!/usr/bin/env python3
# test_orchestration_workflow_results_off_golden.py
"""
Functional test for the chat orchestration workflow results setting-off golden.
Version: 0.261.217
Implemented in: 0.261.217

This test ensures that, with ``enable_chat_workflow_results`` off (the default) and workflow
proposals and workflow runs on, orchestration planning is byte-identical to the release before
the ``workflow_results`` capability existed. It compares, against a committed golden fixture:

- the workflow planning context the ``/plan`` route stores, and the storage reads it makes, for
  a ready request, a user at the proposal cap, failed reads, a shared conversation, a missing
  WorkflowUser role, an allowlist without the workflow capabilities and proposals off;
- the exact messages the planner model receives for a ready request, at the cap, in a shared
  conversation and with only workflow runs on;
- a plan that starts a workflow, and the repair message and degraded plan when a proposal or a
  workflow run step cannot be repaired;
- the capability resolution and unavailable reasons for each of those requests;
- the capability list the V2 bootstrap sends the browser.

The fixture was captured on the unmodified base (0.261.215, before any workflow results change).

Never regenerate the fixture to make this test pass. After merging an upstream planner
change, regenerate it from the upstream commit itself (without this feature):

    python functional_tests/test_orchestration_workflow_results_off_golden.py --write-golden
"""

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_runs_off_golden import (
    ANSWER_STEP,
    CONTEXT_CASES,
    MESSAGE,
    OWNER,
    PLAIN_PLAN,
    PROPOSAL_PLAN,
    PROPOSALS,
    RUNS,
    SETTINGS,
    _build_context,
    _diff,
    _lines,
    _pretty,
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
from test_support.versioning import assert_app_version_at_least


GOLDEN = Path(__file__).resolve().parent / "test_support" / "orchestration_workflow_results_off_golden.json"
RESULTS = "enable_chat_workflow_results"
RESULTS_CAPABILITY = "workflow_results"
# The workflow results setting's values that must leave planning exactly as it was.
RESULTS_OFF = {"results_absent": {}, "results_false": {RESULTS: False}, "results_string": {RESULTS: "true"}}
# The requests the planner is shown: ready, at the cap, in a shared conversation and runs only.
PLANNER_CASES = ("ready", "quota_reached", "shared_conversation", "proposals_off")
RESOLUTION_CASES = ("ready", "quota_reached", "shared_conversation", "role_missing", "proposals_off")
# The settings the V2 bootstrap resolves the browser's capability list from.
CLIENT_CASES = {"deployment": {}, "proposals_off": {PROPOSALS: False}}


def _settings(variant, changes=None):
    return {**deepcopy(SETTINGS), RUNS: True, **deepcopy(variant), **deepcopy(changes or {})}


def _handle(context, name):
    return next(entry["handle"] for entry in context["catalog"]["workflows"] if entry["name"] == name)


def _with_run_step(handle):
    """The plain plan plus one step that starts the workflow ``handle`` names."""
    run_step = {
        "step_id": "run_workflow", "capability_id": "workflow_run", "arguments": {"workflow": handle},
        "inputs": {}, "outputs": [{"name": "run", "kind": "structured-v1"}],
    }
    return {**deepcopy(PLAIN_PLAN), "steps": [deepcopy(ANSWER_STEP), run_step]}


def _plan(patch, settings, workflow_planning, replies):
    """Plan the request through the real planner with scripted replies; the stable plan fields."""
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
    kind, document = planner.plan_request(
        MESSAGE, planner_context, "conversation", OWNER, settings=deepcopy(settings),
        authorized_document_ids=["document-record-1"], revision=0, allow_elicitation=True,
        turn_id="turn", seeds={}, document_labels={"document-record-1": "Weekly priorities.docx"},
        request_context=request_context, planner_model=None, existing_results={},
        composition_profiles=services.composition_profiles(), export_catalog=[],
    )
    return calls, {
        "kind": kind,
        "steps": [step["capability_id"] for step in document["steps"]],
        "deliverables": document.get("deliverables"),
        "validation": document.get("validation"),
        "approval": document.get("approval"),
        "status": document.get("status"),
        "inputs": document.get("inputs"),
        "workflow_run_notes": document.get("workflow_run_notes"),
    }


def _client_projection(settings):
    """The capability list ``route_backend_v2._build_orchestration`` sends the browser."""
    registry = importlib.import_module("functions_orchestration_registry")
    return registry.build_capability_client_projection(registry.resolve_available_capabilities(
        settings, allowed_ids=settings.get("chat_orchestration_enabled_capabilities"),
        include_runtime_bindings=False,
    ))


def _capture(patch, variant):
    """Everything the golden pins, for one value of the workflow results setting."""
    wf = importlib.import_module("functions_orchestration_workflow_context")
    runs = {RUNS: True, **variant}
    captured = {"contexts": {}, "planner": {}, "plans": {}, "resolution": {}, "client_projection": {}}
    contexts = {}
    for case_name in CONTEXT_CASES:
        context, reads = _build_context(wf, runs, case_name)
        contexts[case_name] = context
        captured["contexts"][case_name] = {"context": context, "reads": reads}
    for case_name in PLANNER_CASES:
        changes = CONTEXT_CASES[case_name][0]
        calls, result = _plan(patch, _settings(variant, changes), contexts[case_name], [PLAIN_PLAN])
        if len(calls) != 1:
            raise AssertionError(f"{case_name}: expected one planner call, got {len(calls)}")
        system, user = calls[0]
        captured["planner"][case_name] = {
            "system_prompt": system["content"], "planner_payload": user["content"], "result": result,
        }
    ready = contexts["ready"]
    replies = {
        "proposal_degrade": [PROPOSAL_PLAN, PROPOSAL_PLAN],
        "run": [_with_run_step(_handle(ready, "Manual one"))],
        # The newest workflow is not durable, so a step that starts it is repaired once, then dropped.
        "run_degrade": [_with_run_step(_handle(ready, "Contract watcher"))] * 2,
    }
    for name, scripted in replies.items():
        calls, result = _plan(patch, _settings(variant), ready, scripted)
        captured["plans"][name] = {"calls": calls, "result": result}
    for case_name in RESOLUTION_CASES:
        changes = CONTEXT_CASES[case_name][0]
        captured["resolution"][case_name] = _resolution(_settings(variant, changes), contexts[case_name])
    for name, changes in CLIENT_CASES.items():
        captured["client_projection"][name] = _client_projection(_settings(variant, changes))
    return captured


def _first_call(captured):
    ready = captured["planner"]["ready"]
    return [{"role": "system", "content": ready["system_prompt"]}, {"role": "user", "content": ready["planner_payload"]}]


def _check_repair_shape(calls, label):
    """Each repair call repeats the first call, then the reply it repairs and the repair message."""
    for call in calls[1:]:
        if call[:2] != calls[0]:
            raise AssertionError(f"{label}: a repair call does not start with the first call")
        roles = [message["role"] for message in call[2:]]
        if roles != ["assistant", "user"]:
            raise AssertionError(f"{label}: unexpected repair roles {roles}")


def _golden_from(captured):
    """The committed fixture shape: readable, diffable, and exact once re-serialized.

    System prompts are stored once each and named; every plan's first call is the ready request's
    call, so only the repair messages are stored for them.
    """
    prompts = {}

    def prompt_label(text):
        for label, lines in prompts.items():
            if "\n".join(lines) == text:
                return label
        label = f"prompt_{len(prompts) + 1}"
        prompts[label] = _lines(text)
        return label

    planner = {
        case_name: {
            "system_prompt": prompt_label(entry["system_prompt"]),
            "planner_payload": json.loads(entry["planner_payload"]),
            "result": entry["result"],
        }
        for case_name, entry in captured["planner"].items()
    }
    first = _first_call(captured)
    plans = {}
    for name, entry in captured["plans"].items():
        calls = entry["calls"]
        if calls[0] != first:
            raise AssertionError(f"{name}: the first planner call is not the ready request's call")
        _check_repair_shape(calls, name)
        plans[name] = {
            "first_call_as": "ready",
            "call_count": len(calls),
            "repair_messages": [_lines(call[3]["content"]) for call in calls[1:]],
            "result": entry["result"],
        }
    return {
        "captured_from": "0.261.215 (86f3f3629, before workflow results)",
        "contexts": captured["contexts"],
        "system_prompts": prompts,
        "planner": planner,
        "plans": plans,
        "resolution": captured["resolution"],
        "client_projection": captured["client_projection"],
    }


def _load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _assert_same(expected, actual, label):
    if _pretty(expected) != _pretty(actual):
        raise AssertionError(_diff(_pretty(expected), _pretty(actual), label))


def _assert_matches_golden(golden, captured):
    for case_name, expected in golden["contexts"].items():
        _assert_same(expected, captured["contexts"][case_name], f"{case_name} planning context")
    for case_name, expected in golden["planner"].items():
        actual = captured["planner"][case_name]
        prompt = "\n".join(golden["system_prompts"][expected["system_prompt"]])
        if actual["system_prompt"] != prompt:
            raise AssertionError(_diff(prompt, actual["system_prompt"], f"{case_name} system prompt"))
        content = json.dumps(expected["planner_payload"], **PLANNER_JSON)
        if actual["planner_payload"] != content:
            raise AssertionError(_diff(
                _pretty(expected["planner_payload"]), _pretty(json.loads(actual["planner_payload"])),
                f"{case_name} planner payload",
            ))
        _assert_same(expected["result"], actual["result"], f"{case_name} plan")
    first = _first_call(captured)
    for name, expected in golden["plans"].items():
        calls = captured["plans"][name]["calls"]
        if len(calls) != expected["call_count"]:
            raise AssertionError(f"{name}: {len(calls)} planner calls, golden has {expected['call_count']}")
        if calls[0] != first:
            raise AssertionError(f"{name}: the first planner call is not the ready request's call")
        _check_repair_shape(calls, name)
        for call, lines in zip(calls[1:], expected["repair_messages"]):
            repair = "\n".join(lines)
            if call[3]["content"] != repair:
                raise AssertionError(_diff(repair, call[3]["content"], f"{name} repair message"))
        _assert_same(expected["result"], captured["plans"][name]["result"], f"{name} plan")
    _assert_same(golden["resolution"], captured["resolution"], "capability resolution")
    _assert_same(golden["client_projection"], captured["client_projection"], "client capability projection")


def test_version_includes_the_workflow_results_off_golden():
    assert_app_version_at_least("0.261.217")


def test_the_fixture_covers_the_cases_that_matter():
    golden = _load_golden()
    contexts = golden["contexts"]
    ready = contexts["ready"]["context"]
    assert ready["workflow_runs"] == {"ready": True}
    # Ranking for runs puts the workflow the request names first.
    assert ready["catalog"]["workflows"][0]["name"] == "Manual one"
    assert contexts["quota_reached"]["context"]["workflow_runs"] == {"ready": True}
    assert "time_zone" not in contexts["quota_reached"]["context"]
    assert "time_zone" not in contexts["proposals_off"]["context"]
    for case_name in ("shared_conversation", "role_missing", "propose_not_allowlisted"):
        assert contexts[case_name]["reads"] == [], case_name
    planner = golden["planner"]
    ready_prompt = "\n".join(golden["system_prompts"][planner["ready"]["system_prompt"]])
    runs_only_prompt = "\n".join(golden["system_prompts"][planner["proposals_off"]["system_prompt"]])
    assert planner["ready"]["system_prompt"] != planner["proposals_off"]["system_prompt"]
    assert len(runs_only_prompt) < len(ready_prompt)
    for case_name in PLANNER_CASES:
        capabilities = [entry["id"] for entry in planner[case_name]["planner_payload"]["capabilities"]]
        assert RESULTS_CAPABILITY not in capabilities, case_name
    plans = golden["plans"]
    assert plans["run"]["call_count"] == 1
    assert plans["run"]["result"]["inputs"]["workflows"][0]["name"] == "Manual one"
    assert plans["run"]["result"]["approval"]["mode"] == "manual"
    assert plans["run_degrade"]["call_count"] == 2
    assert plans["run_degrade"]["result"]["workflow_run_notes"] == [
        {"reason": "workflow_not_durable", "name": "Contract watcher"},
    ]
    assert plans["proposal_degrade"]["result"]["steps"] == ["compose"]
    client_ids = [entry["id"] for entry in golden["client_projection"]["deployment"]]
    assert "workflow_run" in client_ids and RESULTS_CAPABILITY not in client_ids


@pytest.mark.parametrize("results_case", sorted(RESULTS_OFF))
def test_planning_with_results_off_is_byte_identical_to_the_base(modules, monkeypatch, results_case):
    golden = _load_golden()
    captured = _capture(monkeypatch, RESULTS_OFF[results_case])
    _assert_matches_golden(golden, captured)
    for case_name in RESOLUTION_CASES:
        resolution = captured["resolution"][case_name]
        assert RESULTS_CAPABILITY not in resolution["capability_ids"], case_name
        assert RESULTS_CAPABILITY not in resolution["unavailable"], case_name
    for name, projection in captured["client_projection"].items():
        assert RESULTS_CAPABILITY not in [entry["id"] for entry in projection], name


def _write_golden():
    from test_support.offline_bootstrap import offline_app_imports

    class _Patch:
        def __init__(self):
            self.undo = []

        def setattr(self, target, name, value):
            self.undo.append((target, name, getattr(target, name)))
            setattr(target, name, value)

        def restore(self):
            for target, name, value in reversed(self.undo):
                setattr(target, name, value)

    with offline_app_imports():
        # Same import order as the shared ``modules`` fixture, which avoids a settings cycle.
        importlib.import_module("route_backend_orchestration")
        patch = _Patch()
        try:
            captured = _capture(patch, RESULTS_OFF["results_absent"])
        finally:
            patch.restore()
    GOLDEN.write_text(_pretty(_golden_from(captured)) + "\n", encoding="utf-8")
    print(f"Wrote {GOLDEN}")


if __name__ == "__main__":
    if "--write-golden" in sys.argv:
        _write_golden()
        sys.exit(0)
    sys.exit(pytest.main([__file__, "-q"]))
