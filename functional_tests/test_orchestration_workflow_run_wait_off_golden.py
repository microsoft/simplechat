#!/usr/bin/env python3
# test_orchestration_workflow_run_wait_off_golden.py
"""
Functional test for the Wait For Quick Workflows In Chat setting-off golden.
Version: 0.261.309
Implemented in: 0.261.309

This test ensures that, with ``enable_chat_orchestration_workflow_run_wait`` off (the default),
starting a saved workflow from a chat plan is byte-identical to the release before waiting
existed. Run Workflows From Chat is on, Use Workflow Results In Chat is on or off, and the user's
"Weekly digest" is a quick workflow that the wait would accept. Against a committed golden fixture
it compares:

- the workflow planning context and the storage reads it makes: no waitable flags, no wait
  marker and no read of the saved definitions;
- the exact messages the planner model receives, its repair message, and the plan it returns when
  the model's compose step reads the run step: the run step is dropped, as before;
- ``drop_workflow_runs`` for a run step that a compose step reads, one that the final response
  reads, and one that nothing reads;
- the plan ``normalize_plan`` compiles when nothing reads the run step, and how it rejects a plan
  whose compose step or final response does;
- a plan executed end to end: the run step's record and retained result, what was queued, the
  run's chat invocation and post-back record, the plan's status and the reply's text.

Each way the wait can be off is compared: the key absent, ``False``, the string ``"true"``, ``1``,
and a real ``True`` without Use Workflow Results In Chat, which the wait requires.

The fixture was captured on the unmodified base, ``e1657efd9`` (before any wait change). Never
regenerate it to make this test pass. After merging an upstream change to these paths, regenerate
it from the upstream commit itself, without this feature:

    python functional_tests/test_orchestration_workflow_run_wait_off_golden.py --write-golden

Checks raise ``AssertionError`` explicitly, so they also run under ``python -O``.
"""

import importlib
import json
import os
import re
import sys
from copy import deepcopy
from difflib import unified_diff
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_orchestration_harness_routes import modules  # noqa: F401
from test_orchestration_workflow_run_adapter import RUN_ID, world  # noqa: F401
from test_orchestration_workflow_run_capability import ANSWER, WORKFLOW_RUN, _handle, _raw_plan, _run
from test_orchestration_workflow_run_planning_context import (  # noqa: F401
    DIGEST_ID,
    OWNER,
    RUN_SETTINGS,
    RUNS,
    _build,
    _workflows,
    wf,
)
from test_orchestration_workflow_setting_off_golden import (
    ACTIONS,
    AGENTS,
    BASE_SETTINGS,
    CANDIDATES,
    DEPLOYMENT,
    IDENTITY,
    PLANNER_JSON,
    _binding,
    _Completions,
    _FrozenDatetime,
)
from test_support.orchestration_harness_execution import HarnessEnvironment, compose_step, decoded_frames, input_binding
from test_support.versioning import assert_app_version_at_least


GOLDEN = Path(__file__).resolve().parent / "test_support" / "orchestration_workflow_run_wait_off_golden.json"
WRITE_ENV = "SIMPLECHAT_WRITE_RUN_WAIT_OFF_GOLDEN"
WAIT = "enable_chat_orchestration_workflow_run_wait"
RESULTS = "enable_chat_workflow_results"
MESSAGE = "Run my weekly digest, then compare its totals with last week."
PLANNER_SETTINGS = {**BASE_SETTINGS, RUNS: True}
AVAILABLE = ("compose", "web_search", WORKFLOW_RUN)
PROFILES = {"results_on": {RESULTS: True}, "results_off": {}}
# Each way the wait is off, per profile. The base ignores the key, so each must match the base.
WAIT_OFF = {
    "results_on": {"absent": None, "false": False, "string_true": "true", "one": 1},
    "results_off": {"absent": None, "true_without_results": True},
}
CASES = [(profile, name) for profile, values in WAIT_OFF.items() for name in values]
# Two plain tasks: with the wait on, the quick-run rule accepts the digest.
TASKS = [
    {"id": "task-1", "type": "instructions", "name": "Gather", "instructions": "Gather the week's totals.", "order": 1},
    {"id": "task-2", "type": "instructions", "name": "Summarize", "instructions": "Summarize the totals.", "order": 2},
]
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
# normalize_plan names a plan it was not given an id for with a random one.
_RANDOM_ID = re.compile(r"^(plan|run|turn)_[0-9a-f]{32}$")


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _with(base, profile, wait):
    settings = {**deepcopy(base), **deepcopy(PROFILES[profile])}
    if wait is None:
        settings.pop(WAIT, None)
    else:
        settings[WAIT] = wait
    return settings


def _digest_definition():
    """The Weekly digest's full saved definition, as the wait would read it."""
    listed = next(workflow for workflow in _workflows() if workflow["id"] == DIGEST_ID)
    return {**deepcopy(listed), "user_id": OWNER, "tasks": deepcopy(TASKS)}


def _definitions(user_id, workflow_ids):
    return [_digest_definition()] if user_id == OWNER and DIGEST_ID in workflow_ids else []


def _reader_answer():
    return {
        "step_id": "answer", "capability_id": "compose",
        "arguments": {"instruction": "Compare the digest's totals with last week.", "knowledge_basis": "general_knowledge"},
        "inputs": {"digest": {"binding": input_binding("run_digest", "run")}},
        "outputs": [{"name": "answer", "kind": "markdown-v1"}],
    }


def _canonical(value):
    return json.loads(json.dumps(value, default=str))


def _stable(value):
    """A JSON copy of ``value`` without storage metadata, and with wall-clock times and random ids replaced."""
    def walk(node):
        if isinstance(node, dict):
            return {key: walk(item) for key, item in node.items() if not str(key).startswith("_")}
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, str) and _TIMESTAMP.match(node):
            return "<timestamp>"
        if isinstance(node, str) and _RANDOM_ID.match(node):
            return f"<{node.split('_', 1)[0]} id>"
        return node
    return walk(_canonical(value))


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def _plan(patch, settings, planning, replies):
    """Plan MESSAGE through the real planner with scripted replies. Returns ``(calls, kind, document)``."""
    context_module = importlib.import_module("functions_orchestration_context")
    planner = importlib.import_module("functions_orchestration_planner")
    services = importlib.import_module("functions_orchestration_services")
    patch.setattr(context_module, "datetime", _FrozenDatetime)
    request_context = context_module.build_capability_request_context(
        OWNER, deepcopy(IDENTITY), MESSAGE, deepcopy(AGENTS), deepcopy(ACTIONS), allowed_user_urls=[],
        native_bridge_for_step=_binding, external_source_admission=_binding,
        external_source_authorizer=_binding, external_source_preflight=_binding,
        capture_external_source_configuration=_binding,
    )
    request_context["workflow_planning"] = deepcopy(planning)
    planner_context = context_module.build_planner_context(
        MESSAGE, candidates=deepcopy(CANDIDATES), seeds={}, ledger=None,
        signals=context_module.build_conversation_signals([], MESSAGE), agents=deepcopy(AGENTS),
        original_message=MESSAGE, request_resolution={"relationship": "new_topic", "resolved_message": MESSAGE},
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
    return calls, kind, document


def _planner_capture(calls, kind, document):
    _require(calls, "The planner model should have been called.")
    first = calls[0]
    later = []
    for call in calls[1:]:
        _require(call[:2] == first, "A later planner call must repeat the first call's messages.")
        later.append([{"role": message["role"], "content": message["content"].split("\n")} for message in call[2:]])
    return {
        "system_prompt": first[0]["content"].split("\n"),
        "planner_payload": json.loads(first[1]["content"]),
        "planner_payload_text": first[1]["content"],
        "later_calls": later,
        "kind": kind,
        "plan": _stable(document),
    }


def _normalize(schema, settings, planning, steps, final="answer"):
    return schema.normalize_plan(
        _raw_plan(steps, final), "conversation-1", OWNER, settings=deepcopy(settings), contract_version=2,
        available_capability_ids=list(AVAILABLE), workflow_planning=deepcopy(planning),
    )


def _normalized(schema, settings, planning, steps, final="answer"):
    try:
        plan = _normalize(schema, settings, planning, steps, final)
    except schema.PlanValidationError as exc:
        return {"rejected": {"error": type(exc).__name__, "rule": getattr(exc, "rule", None), "message": str(exc)}}
    return {"plan": _stable(plan)}


def _execute(monkeypatch, world, planning, settings):
    """Run a plan that starts the Weekly digest and answers without reading the run."""
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    world.definitions.patch(OWNER, DIGEST_ID, tasks=deepcopy(TASKS))
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(deepcopy(settings))
    if WAIT not in settings:
        env.settings.pop(WAIT, None)
    real_normalize = env.schema.normalize_plan

    def normalize(raw, *args, **kwargs):
        # The harness offers only its own capabilities and plans without a workflow context.
        capability_ids = kwargs.get("available_capability_ids")
        if capability_ids is not None and WORKFLOW_RUN not in capability_ids:
            kwargs["available_capability_ids"] = [*capability_ids, WORKFLOW_RUN]
        kwargs.setdefault("workflow_planning", planning)
        return real_normalize(raw, *args, **kwargs)

    monkeypatch.setattr(env.schema, "normalize_plan", normalize)
    env.create(
        [_run(_handle(planning, "Weekly digest")), compose_step("answer")], replies=["Your priorities."],
        final_response=input_binding("answer"), workflow_planning=planning,
    )
    execution = env.prepare()
    # The harness prepares a run outside a request, so it has no signed-in session of its own.
    execution.context.signed_in_session = True
    decoded_frames(execution.execute(emit=lambda frame: None))
    record = env.read()
    step = env.steps.read_item("run-1:run_digest", "run-1")
    retained = None
    if isinstance(step.get("task_result"), dict):
        task = contracts.TaskResult.from_dict(step["task_result"])
        retained = env.services().results.open_result(task.output("run"), allow_partial=False).read_value()
    started = world.runs.get(OWNER, RUN_ID) or {}
    return _stable({
        "plan": record["plan"],
        "status": record["status"],
        "task_results": sorted(record.get("task_results") or {}),
        "step": {"status": step["status"], "workflow_run": step.get("workflow_run")},
        "retained": retained,
        "queued": world.queued,
        "run": {key: started.get(key) for key in ("trigger_source", "chat_invocation", "chat_delivery", "status")},
        "replies": [message.get("content") for message in env.assistant_messages()],
    })


def _capture(monkeypatch, world, wf, profile, wait):
    """Everything the golden pins, for one settings profile and one way the wait is off."""
    runs = importlib.import_module("functions_orchestration_workflow_runs")
    schema = importlib.import_module("functions_orchestration_schema")
    planner_settings = _with(PLANNER_SETTINGS, profile, wait)
    reads = []
    planning = _build(wf, reads, _with(RUN_SETTINGS, profile, wait), wait_workflows=_definitions)
    handle = _handle(planning, "Weekly digest")
    reading = _raw_plan([_run(handle), _reader_answer()])
    # Scoped, so the stand-in planner model and frozen clock are gone before the plan executes.
    with monkeypatch.context() as patch:
        calls, kind, document = _plan(patch, planner_settings, planning, [reading, reading])
    raws = {
        "compose_reads_run": reading,
        "final_reads_run": _raw_plan([_run(handle), deepcopy(ANSWER)], final=input_binding("run_digest", "run")),
        "nothing_reads_run": _raw_plan([_run(handle), deepcopy(ANSWER)]),
    }
    dropped = {}
    for name, raw in raws.items():
        plan, notes, remaining = runs.drop_workflow_runs(deepcopy(raw), workflow_planning=deepcopy(planning))
        dropped[name] = {"plan": plan, "notes": notes, "remaining": remaining}
    normalized = {
        "compose_reads_run": _normalized(schema, planner_settings, planning, [_run(handle), _reader_answer()]),
        "final_reads_run": _normalized(
            schema, planner_settings, planning, [_run(handle), deepcopy(ANSWER)],
            final=input_binding("run_digest", "run"),
        ),
        "nothing_reads_run": _normalized(schema, planner_settings, planning, [_run(handle), deepcopy(ANSWER)]),
    }
    return {
        "context": {"context": _canonical(planning), "reads": reads},
        "planner": _planner_capture(calls, kind, document),
        "drop": _stable(dropped),
        "normalize": normalized,
        "execution": _execute(monkeypatch, world, planning, _with(RUN_SETTINGS, profile, wait)),
    }


def _golden_from(captured):
    golden = deepcopy(captured)
    golden["planner"].pop("planner_payload_text")
    return golden


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _load_golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _pretty(value):
    return json.dumps(value, indent=1, ensure_ascii=False, default=str)


def _diff(expected, actual, label):
    return "\n".join(list(unified_diff(
        expected.split("\n"), actual.split("\n"), fromfile=f"golden {label}", tofile=f"actual {label}", lineterm="",
    ))[:80])


def _assert_same(expected, actual, label):
    if _pretty(expected) != _pretty(actual):
        raise AssertionError(_diff(_pretty(expected), _pretty(actual), label))


def _assert_matches(golden, captured, label):
    _assert_same(golden["context"], captured["context"], f"{label} planning context")
    expected, actual = golden["planner"], captured["planner"]
    _assert_same(expected["system_prompt"], actual["system_prompt"], f"{label} system prompt")
    payload = json.dumps(expected["planner_payload"], **PLANNER_JSON)
    if actual["planner_payload_text"] != payload:
        raise AssertionError(_diff(
            _pretty(expected["planner_payload"]), _pretty(json.loads(actual["planner_payload_text"])),
            f"{label} planner payload",
        ))
    for key in ("later_calls", "kind", "plan"):
        _assert_same(expected[key], actual[key], f"{label} planner {key}")
    for key in ("drop", "normalize", "execution"):
        _assert_same(golden[key], captured[key], f"{label} {key}")


def test_version_includes_the_wait_off_golden():
    """Waiting for quick workflows ships in 0.261.309."""
    assert_app_version_at_least("0.261.309")


def test_the_fixture_covers_the_cases_that_matter():
    """The golden pins a dropped consumed run step, a rejection, a plain run and its post-back."""
    golden = _load_golden()
    _require(sorted(golden["profiles"]) == sorted(PROFILES), "Both settings profiles should be captured.")
    for profile, captured in golden["profiles"].items():
        _require("wait_workflows" not in captured["context"]["reads"], f"{profile}: the base never reads definitions.")
        entries = captured["context"]["context"]["catalog"]["workflows"]
        _require("Weekly digest" in [entry["name"] for entry in entries], f"{profile}: the digest is offered.")
        _require(len(captured["planner"]["later_calls"]) == 1, f"{profile}: a read run step is repaired once.")
        _require(WORKFLOW_RUN not in json.dumps(captured["planner"]["plan"].get("steps")),
                 f"{profile}: a run step that a compose step reads is dropped.")
        _require(captured["drop"]["compose_reads_run"]["remaining"] == 0, f"{profile}: a read run step is dropped.")
        _require(captured["drop"]["compose_reads_run"]["notes"] == [{"reason": "workflow_run_invalid", "name": "Weekly digest"}],
                 f"{profile}: a read run step is dropped as invalid.")
        # When no single run step fails its own check, the fallback drops every run step.
        _require(captured["drop"]["nothing_reads_run"]["remaining"] == 0, f"{profile}: the fallback drops all.")
        _require(captured["normalize"]["compose_reads_run"]["rejected"]["rule"] == "workflow_run_consumed",
                 f"{profile}: a read run step is rejected by the consumer rule.")
        _require("workflow_run_waits" not in captured["normalize"]["nothing_reads_run"]["plan"],
                 f"{profile}: the base plan has no wait marker.")
        execution = captured["execution"]
        _require(execution["status"] == "completed", f"{profile}: the plan completed.")
        _require(execution["step"]["workflow_run"]["status"] == "queued", f"{profile}: the plan started the run.")
        _require(execution["retained"] is not None and "wait" not in execution["retained"],
                 f"{profile}: the retained run result has no wait.")
    on = golden["profiles"]["results_on"]["execution"]["run"]["chat_delivery"]
    _require(isinstance(on, dict) and "plan_wait" not in on, "With results on the run's post-back is seeded, unheld.")
    _require(golden["profiles"]["results_off"]["execution"]["run"]["chat_delivery"] is None,
             "With results off nothing is posted back.")


def test_the_golden_would_see_a_wait(modules, wf):
    """With the wait on, the same request is no longer the golden's: the digest is quick."""
    wait_module = importlib.import_module("functions_orchestration_workflow_run_wait")
    on = _with(RUN_SETTINGS, "results_on", True)
    eligible, reason = wait_module.quick_run_eligibility(_digest_definition(), on)
    _require(eligible is True, f"The digest should be a quick run, got {reason!r}.")
    reads = []
    planning = _build(wf, reads, on, wait_workflows=_definitions)
    entry = next(entry for entry in planning["catalog"]["workflows"] if entry["name"] == "Weekly digest")
    _require("wait_workflows" in reads and entry.get("waitable") is True, "With the wait on the digest is waitable.")
    golden = _load_golden()["profiles"]["results_on"]["context"]["context"]
    _require(_canonical(planning) != golden, "With the wait on the planning context must differ from the golden.")


@pytest.mark.parametrize("profile,wait_name", CASES)
def test_with_the_wait_off_planning_and_running_match_the_base(modules, monkeypatch, world, wf, profile, wait_name):
    """Every way the wait is off plans and runs exactly as the base did."""
    golden = _load_golden()["profiles"][profile]
    captured = _capture(monkeypatch, world, wf, profile, WAIT_OFF[profile][wait_name])
    _assert_matches(golden, captured, f"{profile}/{wait_name}")
    run = captured["execution"]["run"]
    _require(not isinstance(run.get("chat_delivery"), dict) or "plan_wait" not in run["chat_delivery"],
             "With the wait off the run's post-back is never held.")


if os.environ.get(WRITE_ENV) == "1":
    @pytest.mark.parametrize("profile", sorted(PROFILES))
    def test_write_the_golden(modules, monkeypatch, world, wf, profile):
        """Capture one profile, with the wait key absent, into the golden fixture."""
        captured = _capture(monkeypatch, world, wf, profile, None)
        version = importlib.import_module("config").VERSION
        golden = _load_golden() if GOLDEN.exists() else {"captured_from": f"{version} (before waiting)", "profiles": {}}
        golden["profiles"][profile] = _golden_from(captured)
        GOLDEN.write_text(_pretty(golden) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if "--write-golden" in sys.argv:
        os.environ[WRITE_ENV] = "1"
        if GOLDEN.exists():
            GOLDEN.unlink()
        raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider", "-k", "write_the_golden"]))
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
