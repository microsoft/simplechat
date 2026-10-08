# test_workflow_plan_replay_off_golden.py
"""
Functional test for the plan replay setting-off golden.
Version: 0.261.307
Implemented in: 0.261.307

With enable_workflow_plan_replay off, which is the default, nothing a user can
already do changes. The golden was captured by running this file with
--write-golden in a clean checkout of the V2 commit this change started from,
fa3422deee5e6d8d65be370b387b28639425bf7f. It pins, for workflows without a
saved chat plan:

- a task sequence: what each task hands its runner, the run result and every
  saved run item, including a retry and a failure that continues;
- a personal workflow saved, renamed and put on a schedule;
- a group workflow build;
- run history redaction for a withheld and a verified task.

On this branch only, a saved chat plan must refuse with its fixed reason while
the setting is off: one failed task item, never a crash, a retry or a silent skip.

Regenerate the golden only from a clean checkout of the base commit (after
merging the base branch, from the new merge base):
    python functional_tests/test_workflow_plan_replay_off_golden.py --write-golden
"""

import importlib
import json
import re
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from difflib import unified_diff
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_support.offline_bootstrap import offline_app_imports
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
GOLDEN = TESTS / "test_support" / "workflow_plan_replay_off_golden.json"
SECTIONS = ("task_sequence", "personal_save", "group_build", "history_redaction")
OWNER = "owner-user"
GROUP = "group-1"
OFF = {"enable_workflow_plan_replay": False}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
NOW = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)?")
HARNESS_TIME = "2026-07-27T00:00:"
# Hashed over a fresh workflow id and save time, so it differs on every run of the same code.
VOLATILE_HASH_KEYS = frozenset({"m365_revision"})


def require(condition, message):
    if not condition:
        raise AssertionError(message)


@contextmanager
def _app():
    """Import the app and the runner harness once, offline, and forget both afterwards.

    One import generation matters: the harness's WorkflowInputError must be the class a
    refusal subclasses, or a refusal would look like an ordinary, retryable failure.
    """
    before = set(sys.modules)
    try:
        with offline_app_imports() as environment:
            sequence = importlib.import_module("test_workflow_task_sequence")
            yield SimpleNamespace(
                load_runner_helpers=sequence.load_runner_helpers,
                config=importlib.import_module("config"),
                settings=importlib.import_module("functions_settings"),
                personal=importlib.import_module("functions_personal_workflows"),
                groups=importlib.import_module("functions_group_workflows"),
                saved_analysis=importlib.import_module("functions_saved_analysis"),
            )
            require(not environment.network_attempts, environment.network_attempts)
    finally:
        for name in set(sys.modules) - before:
            path = getattr(sys.modules.get(name), "__file__", None)
            if path and (Path(path).resolve().is_relative_to(APP) or Path(path).resolve().is_relative_to(TESTS)):
                sys.modules.pop(name, None)


def _hide_volatile(value):
    if isinstance(value, dict):
        return {key: "<revision>" if key in VOLATILE_HASH_KEYS else _hide_volatile(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_hide_volatile(item) for item in value]
    return value


def _mask(value):
    """Name each generated id by first appearance and hide wall-clock times."""
    text = json.dumps(
        _hide_volatile(value), sort_keys=True, default=lambda item: f"<{type(item).__name__}>", ensure_ascii=False,
    )
    names = {}
    text = UUID.sub(lambda match: names.setdefault(match.group(0), f"<id-{len(names) + 1}>"), text)
    text = NOW.sub(lambda match: match.group(0) if match.group(0).startswith(HARNESS_TIME) else "<now>", text)
    return json.loads(text)


def _outcome(action):
    try:
        return {"ok": _mask(action())}
    except Exception as exc:  # The golden pins refusals as well as results.
        return {"error": type(exc).__name__, "message": str(exc)}


def _sequence_workflow(name, tasks, strategy, retries):
    return {
        "id": f"workflow-{name}", "name": "Weekly <b>summary</b>", "user_id": OWNER, "runner_type": "model",
        "document_action": {"type": "none"}, "tasks": tasks,
        "error_handling": {"strategy": strategy, "retry_count": retries},
    }


FILE_SYNC_RESULT = {
    "enabled": True,
    "counts": {"scanned": 3, "created": 1, "updated": 1, "unchanged": 1, "skipped": 0, "failed": 0},
    "changed_documents": [
        {"document_id": "doc-1", "relative_path": "reports/q3.pdf", "action": "created", "source_name": "Reports"},
    ],
    "changed_document_ids": ["doc-1"],
}
SEARCH_WORKFLOW = {
    **_sequence_workflow("search", [
        {"id": "collect", "name": "Collect", "instructions": "Collect facts."},
        {"id": "summarize", "name": "Summarize", "instructions": "Write a summary."},
    ], "halt", 0),
    "task_prompt": "Run the sequence.",
    "document_action": {"type": "search", "document_ids": ["doc-1"]},
    "file_sync": {"use_changed_documents": False, "sources": []},
}
# Each case: the workflow, which runner calls fail, and the File Sync result applied first.
SEQUENCE_CASES = {
    "two_tasks_succeed": (
        _sequence_workflow("two", [
            {"id": "gather", "name": "Gather", "instructions": "Gather this week's notes."},
            {"id": "summarize", "name": "Summarize", "instructions": "Summarize the notes."},
        ], "halt", 0),
        set(), None,
    ),
    "first_attempt_fails_then_retry_succeeds": (
        _sequence_workflow("retry", [
            {"id": "gather", "name": "Gather", "instructions": "Gather this week's notes."},
        ], "halt", 1),
        {1}, None,
    ),
    "failed_task_continues": (
        _sequence_workflow("continue", [
            {"id": "gather", "name": "Gather", "instructions": "Gather this week's notes."},
            {"id": "summarize", "name": "Summarize", "instructions": "Summarize the notes."},
        ], "continue", 1),
        {1, 2}, None,
    ),
    "search_with_file_sync_context": (SEARCH_WORKFLOW, set(), FILE_SYNC_RESULT),
    "unresolved_task_input_fails": (
        _sequence_workflow("unresolved", [
            {"id": "analyze", "name": "Analyze", "instructions": "Find the risks.",
             "document_action": {"type": "analyze", "document_ids": ["doc-1"]}},
        ], "halt", 1),
        set(), None,
    ),
}


def _call_shape(args, kwargs):
    return {
        "execution_workflow": deepcopy(args[0]) if args else None,
        "positional": [type(value).__name__ for value in args[1:]],
        "keywords": {name: type(value).__name__ for name, value in sorted(kwargs.items())},
    }


def _capture_sequence(app, name):
    workflow, failing_calls, file_sync_result = SEQUENCE_CASES[name]
    calls = []

    def dispatch(*args, **kwargs):
        calls.append(_call_shape(args, kwargs))
        if len(calls) in failing_calls:
            raise RuntimeError(f"Runner call {len(calls)} failed.")
        return {"reply": f"Reply {len(calls)}", "token_usage": {"total_tokens": 7}}

    helpers, saved_items = app.load_runner_helpers(dispatch)
    workflow = deepcopy(workflow)
    if file_sync_result:
        workflow = helpers["_apply_file_sync_context_to_workflow"](workflow, deepcopy(file_sync_result))
    result = _outcome(lambda: helpers["_execute_workflow_task_sequence"](
        workflow, dict(OFF), "conversation-1", "run-1", None, {}, actor_user_id=OWNER,
    ))
    return {"result": result, "dispatch_calls": _mask(calls), "saved_items": _mask(saved_items)}


def _settings(app):
    return {**deepcopy(app.settings.get_settings() or {}), "allow_user_workflows": True, **OFF}


def _capture_personal(app, patch):
    workflows = AtomicMemoryContainer("user_id")
    settings = _settings(app)
    patch.setattr(app.config, "cosmos_personal_workflows_container", workflows)
    patch.setattr(app.personal, "cosmos_personal_workflows_container", workflows)
    for module in (app.settings, app.personal):
        patch.setattr(module, "get_settings", lambda *args, **kwargs: deepcopy(settings))

    def latest():
        return deepcopy(next(iter(workflows.items.values())))

    def save(payload):
        return _outcome(lambda: app.personal.save_personal_workflow(OWNER, deepcopy(payload), actor_user_id=OWNER))

    # The editor resends the same form with the workflow's id, as these updates do.
    payload = {
        "name": "Weekly <script>summary</script>", "description": "Plain workflow",
        "runner_type": "model", "trigger_type": "manual", "task_prompt": "Summarize the week.",
    }
    created = save(payload)
    if not workflows.items:
        return {"created": created}
    payload = {**payload, "id": latest()["id"], "name": "Renamed"}
    renamed = save(payload)
    rescheduled = save({**payload, "trigger_type": "interval", "schedule": {"unit": "hours", "value": 24}})
    return {"created": created, "renamed": renamed, "rescheduled": rescheduled, "stored": _mask(latest())}


def _capture_group(app):
    workflow = {
        "name": "Team digest", "runner_type": "model", "trigger_type": "manual",
        "task_prompt": "Summarize the team's week.",
    }
    return _outcome(lambda: app.groups.build_group_workflow_document(
        GROUP, deepcopy(workflow), OWNER, {"userId": OWNER}, settings=_settings(app),
    ))


def _capture_history(app):
    workflow = {"id": "workflow-1", "user_id": OWNER}
    summary = {
        "contract_version": "workflow-result-v2",
        "producer": {"workflow_id": "workflow-1", "run_id": "run-1", "task_id": "summarize"},
        "result_ref": {"sha256": "c" * 64},
    }
    item = {"task_id": "summarize", "workflow_result": summary, "reply": "The summary.",
            "response_preview": "The summary.", "output_summary": "1 answer", "error": ""}
    run_record = {"id": "run-1", "task_results": [deepcopy(item)], "reply": "The summary."}
    captured = {}
    for name, readable in (("verified", True), ("withheld", False)):
        def reader(*_args, readable=readable, **_kwargs):
            if not readable:
                raise PermissionError("source access lost")
        captured[name] = _outcome(lambda reader=reader: app.saved_analysis.sanitize_workflow_analysis_history(
            workflow, deepcopy(run_record), OWNER, items=[deepcopy(item)], result_reader=reader,
        ))
    return captured


def _capture(app):
    captured = {"task_sequence": {name: _capture_sequence(app, name) for name in SEQUENCE_CASES}}
    with pytest.MonkeyPatch.context() as patch:
        captured["personal_save"] = _capture_personal(app, patch)
    captured["group_build"] = _capture_group(app)
    captured["history_redaction"] = _capture_history(app)
    return captured


def _pretty(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@pytest.fixture(scope="module")
def app():
    with _app() as imported:
        yield imported


@pytest.fixture(scope="module")
def captured(app):
    return _capture(app)


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_the_golden_comes_from_the_base_commit(golden):
    require(re.fullmatch(r"[0-9a-f]{40}", golden.get("captured_from") or ""), golden.get("captured_from"))
    require(tuple(sorted(golden["captured"])) == tuple(sorted(SECTIONS)), sorted(golden["captured"]))
    require(set(golden["captured"]["task_sequence"]) == set(SEQUENCE_CASES), "Every sequence case is pinned.")
    for name, outcome in golden["captured"]["personal_save"].items():
        if name != "stored":
            require("ok" in outcome, f"The base refused the plain personal {name} save: {outcome}")
    require("ok" in golden["captured"]["group_build"], golden["captured"]["group_build"])


@pytest.mark.parametrize("section", SECTIONS)
def test_workflows_without_a_saved_plan_match_the_base(captured, golden, section):
    expected = _pretty(golden["captured"][section])
    actual = _pretty(captured[section])
    require(actual == expected, "".join(unified_diff(
        expected.splitlines(True), actual.splitlines(True), "base", "branch", n=2,
    )))


@pytest.mark.parametrize("strategy", ("halt", "continue"))
def test_a_saved_plan_refuses_with_its_fixed_reason_while_off(app, strategy):
    replay = importlib.import_module("functions_workflow_plan_replay")
    calls = []

    def dispatch(*args, **kwargs):
        calls.append(args)
        return {"reply": "A runner must never answer for a saved chat plan."}

    helpers, saved_items = app.load_runner_helpers(dispatch)
    helpers.update({
        "workflow_unit": lambda _key, action, **_kwargs: action(),
        "_raise_if_workflow_run_cancelled": lambda *_args, **_kwargs: None,
    })
    workflow = {
        "id": "workflow-replay", "name": "Repeat", "user_id": OWNER, "created_by": OWNER,
        "runner_type": "model", "document_action": {"type": "none"},
        "tasks": [{"id": "replay", "name": replay.PLAN_REPLAY_TASK_NAME, "type": replay.PLAN_REPLAY_TASK_TYPE,
                   "instructions": "Replay the saved chat plan.", "plan_replay": {"plan_sha256": "a" * 64}}],
        "error_handling": {"strategy": strategy, "retry_count": 2},
    }
    settings = {"enable_chat_orchestration": True, "allow_user_workflows": True, **OFF}
    expected = replay.REFUSAL_MESSAGES["replay_disabled"]
    outcome = _outcome(lambda: helpers["_execute_workflow_task_sequence"](
        workflow, settings, "conversation-1", "run-1", None, {}, actor_user_id=OWNER,
    ))
    require(not calls, "No runner answers for a saved chat plan.")
    if strategy == "halt":
        # The run stops, and its failure carries the fixed reason the alert and inspector show.
        require(outcome.get("error") == "RuntimeError", outcome)
        require(expected in outcome.get("message", ""), outcome)
    else:
        result = outcome.get("ok") or {}
        require(result.get("task_error_count") == 1, outcome)
        require([task["status"] for task in result["task_results"]] == ["failed"], result)
    final = [item for item in saved_items if item.get("status") == "failed"]
    require(len(final) == 1, f"A refusal is recorded once and never retried: {saved_items}")
    require(expected in str(final[0].get("error")), final[0].get("error"))
    require("plan_replay" not in final[0], "A refused replay has no typed result.")


def test_the_setting_is_off_by_default_and_saves_only_a_real_true(app):
    require(app.settings.get_settings().get("enable_workflow_plan_replay") is False,
            "Plan replay is off until an admin turns it on.")
    try:
        for value, expected in (("true", False), (1, False), (None, False), (True, True)):
            saved = app.settings.update_settings({"enable_workflow_plan_replay": value})
            require(saved, f"The setting wasn't saved for {value!r}.")
            stored = app.settings.get_settings().get("enable_workflow_plan_replay")
            require(stored is expected, f"{value!r} saved as {stored!r}.")
    finally:
        restored = app.settings.update_settings({"enable_workflow_plan_replay": False})
    require(restored, "The setting wasn't turned back off.")


def test_version_includes_plan_replay():
    assert_app_version_at_least("0.261.307")


def _write_golden():
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()
    with _app() as imported:
        captured = _capture(imported)
    GOLDEN.write_text(_pretty({"captured_from": commit, "captured": captured}), encoding="utf-8")
    print(f"Wrote {GOLDEN} from {commit}.")


if __name__ == "__main__":
    if "--write-golden" in sys.argv:
        _write_golden()
        sys.exit(0)
    sys.exit(pytest.main([__file__, "-q", "-p", "no:langsmith_plugin", "-p", "no:cacheprovider"]))
