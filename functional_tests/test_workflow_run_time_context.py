# test_workflow_run_time_context.py
#!/usr/bin/env python3
"""
Functional test for the calendar workflow run time prompt context.
Version: 0.261.197
Implemented in: 0.261.197

This test ensures that a workflow whose stored schedule is a calendar schedule tells the model
the run's current date and time in the schedule's time zone, on every run: scheduled, catch-up
and Run now. It also ensures that manual-only and interval workflows keep byte-identical
prompts.

The real ``_run_authorized_workflow_impl`` is compiled from the runner with its I/O doubled.
It runs up to the point where it hands the prepared workflow to the task sequence or the legacy
dispatcher. Each task's prompt is then built with the real
``_build_workflow_task_execution_workflow``, using the same arguments the task sequence passes.
The prompts recorded for manual-only and interval workflows are compared with
``fixtures/workflow_run_prompt_golden.json``. That golden was captured with ``--capture`` from
the runner before this change (the Phase 1 head, c5a375f06), so any difference in a model
prompt, a conversation message, a URL Access prompt or a document search query fails the test.
"""

import argparse
import ast
import copy
import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "workflow_run_prompt_golden.json"
MINIMUM_VERSION = "0.261.197"

RUNNER_FUNCTIONS = {
    "_truncate_workflow_file_sync_context",
    "_format_workflow_file_sync_context",
    "_apply_file_sync_changed_documents_to_action",
    "_apply_file_sync_context_to_workflow",
    "_resolve_workflow_task_document_action",
    "_build_workflow_task_execution_workflow",
    "_run_authorized_workflow_impl",
}
NEW_RUNNER_FUNCTIONS = {"_apply_workflow_run_time_context"}
RUNNER_CONSTANTS = {"WORKFLOW_FILE_SYNC_CONTEXT_MAX_CHARS"}


class PromptCaptured(BaseException):
    """Stops the run once the prepared workflow reaches the executor, like a cancellation would."""


def _dummy_exception(name, base=Exception):
    return type(name, (base,), {})


def _load_schedules_module():
    """The real schedule rules, loaded from their files; they import only the standard library."""
    loaded = {}
    saved = {name: sys.modules.get(name) for name in ("functions_workflow_definitions", "functions_workflow_schedules")}
    try:
        for name in ("functions_workflow_definitions", "functions_workflow_schedules"):
            spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            loaded[name] = module
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return loaded["functions_workflow_schedules"]


SCHEDULES = _load_schedules_module()


def _runner_source():
    return RUNNER_FILE.read_text(encoding="utf-8")


def _load_runner(namespace, *, require_new=True):
    source = _runner_source()
    tree = ast.parse(source, filename=str(RUNNER_FILE))
    available = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    wanted = set(RUNNER_FUNCTIONS)
    if require_new or NEW_RUNNER_FUNCTIONS <= available:
        wanted |= NEW_RUNNER_FUNCTIONS
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in RUNNER_CONSTANTS for target in node.targets
        ):
            nodes.append(node)
    found = {node.name for node in nodes if isinstance(node, ast.FunctionDef)}
    assert found == wanted, f"Missing runner functions: {sorted(wanted - found)}"
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER_FILE), "exec"), namespace)
    return namespace


class PromptHarness:
    """Runs the real run preparation and records every prompt a model or reader would see."""

    def __init__(self, *, require_new=True):
        self.started_at = "2026-09-28T13:00:00+00:00"
        self.prior_run = None
        self.file_sync_result = None
        self.captured = {}
        namespace = {
            "DOCUMENT_ACTION_TYPE_NONE": "none",
            "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
            "build_analyze_config": lambda action: {"enabled": (action or {}).get("type") == "analyze"},
            "_get_document_action_config": lambda source: dict((source or {}).get("document_action") or {"type": "none"}),
            "_get_workflow_file_sync_config": lambda workflow: (workflow or {}).get("file_sync") or {},
            "_get_workflow_group_id": lambda workflow: str(workflow.get("group_id") or ""),
            "_get_workflow_scope": lambda workflow: "group" if workflow.get("group_id") else "personal",
            "create_workflow_run_id": lambda: "run-1",
            "_utc_now_iso": lambda: self.started_at,
            "get_settings": lambda: {},
            "current_workflow_execution": lambda: None,
            "_get_workflow_run_record": lambda workflow, run_id: copy.deepcopy(self.prior_run),
            "_save_workflow_run_record": lambda workflow, run_record: None,
            "_raise_if_workflow_run_cancelled": lambda workflow, run_id: None,
            "_execute_cancelable_workflow_step": lambda workflow, run_id, operation: operation(),
            "workflow_unit": lambda name, operation, inputs=None, replay_safe=False: operation(),
            "_execute_workflow_file_sync": lambda workflow, run_id, trigger_source: copy.deepcopy(self.file_sync_result),
            "_ensure_workflow_conversation": lambda workflow: {"id": "conversation-1"},
            "cosmos_messages_container": None,
            "_create_user_message": self._create_user_message,
            "_initialize_workflow_assistant_tracking": lambda *args, **kwargs: ("assistant-1", None),
            "_add_workflow_activity_thought": lambda *args, **kwargs: None,
            "_prepare_workflow_url_access_context": self._prepare_url_access,
            "_workflow_url_access_enabled": lambda workflow: False,
            "_execute_workflow_task_sequence": self._task_sequence,
            "_execute_workflow_dispatch": self._dispatch,
            "M365ApprovalRequired": _dummy_exception("M365ApprovalRequired"),
            "M365SignInRequired": _dummy_exception("M365SignInRequired"),
            "WorkflowRunCancelledError": _dummy_exception("WorkflowRunCancelledError", BaseException),
            "AgentExecutionCancelled": _dummy_exception("AgentExecutionCancelled"),
            "workflow_run_time_context": getattr(SCHEDULES, "workflow_run_time_context", None),
            "WORKFLOW_SCHEDULED_TRIGGER_TYPES": SCHEDULES.WORKFLOW_SCHEDULED_TRIGGER_TYPES,
        }
        self.helpers = _load_runner(namespace, require_new=require_new)

    def _create_user_message(self, conversation_id, workflow, trigger_source, run_id):
        self.captured["user_message"] = workflow.get("task_prompt", "")
        return {"id": "message-1", "metadata": {}}

    def _prepare_url_access(self, workflow, settings, conversation_id, run_id, thought_tracker=None, user_roles=None):
        self.captured["url_access_prompt"] = workflow.get("task_prompt", "")
        return {}

    def _task_sequence(self, workflow, *args, **kwargs):
        self.captured["executor"] = "tasks"
        self.captured["execution_workflow"] = copy.deepcopy(workflow)
        raise PromptCaptured()

    def _dispatch(self, workflow, *args, **kwargs):
        self.captured["executor"] = "legacy"
        self.captured["execution_workflow"] = copy.deepcopy(workflow)
        raise PromptCaptured()

    def run(self, workflow, trigger_source="scheduled"):
        """Prepare one run and return the prompts it produces."""
        self.captured = {}
        stored = copy.deepcopy(workflow)
        with pytest.raises(PromptCaptured):
            self.helpers["_run_authorized_workflow_impl"](workflow, trigger_source=trigger_source)
        assert workflow == stored, "Preparing a run must never change the stored workflow definition."

        execution_workflow = self.captured["execution_workflow"]
        prompts = {
            "executor": self.captured["executor"],
            "user_message": self.captured["user_message"],
            "url_access_prompt": self.captured["url_access_prompt"],
        }
        if self.captured["executor"] == "legacy":
            prompts["legacy"] = {
                "task_prompt": execution_workflow.get("task_prompt"),
                "task_search_query": execution_workflow.get("task_search_query"),
            }
            return prompts

        structured = execution_workflow.get("definition_version") == 3
        build = self.helpers["_build_workflow_task_execution_workflow"]
        prompts["tasks"] = []
        for index, task in enumerate(execution_workflow.get("tasks") or []):
            # The same arguments _execute_workflow_task_sequence passes for each task.
            task_workflow = build(
                execution_workflow,
                task,
                previous_reply=f"Output of task {index}." if index else "",
                include_document_action=index == 0 and not structured,
                include_file_sync_context=index == 0 and not structured,
            )
            prompts["tasks"].append({
                "task_prompt": task_workflow["task_prompt"],
                "task_search_query": task_workflow["task_search_query"],
            })
        return prompts


def _tasks(*instructions):
    return [
        {"id": f"task-{index + 1}", "name": f"Task {index + 1}", "instructions": text, "order": index,
         "runner": {"type": "inherit"}, "document_action": {"type": "none"}}
        for index, text in enumerate(instructions)
    ]


def _workflow(trigger_type="manual", schedule=None, tasks=None, **extra):
    workflow = {
        "id": "workflow-1",
        "user_id": "user-1",
        "name": "Weekly planning",
        "runner_type": "model",
        "trigger_type": trigger_type,
        "schedule": schedule if schedule is not None else {},
        "task_prompt": (tasks[0]["instructions"] if tasks else "Summarize this week's priorities."),
        "document_action": {"type": "none"},
        "file_sync": {"enabled": False},
        "definition_version": 2 if tasks else 1,
        "is_enabled": True,
        "run_count": 3,
    }
    if tasks is not None:
        workflow["tasks"] = tasks
    workflow.update(extra)
    return workflow


def _file_sync_result():
    return {
        "enabled": True,
        "should_continue": True,
        "counts": {"scanned": 4, "created": 1, "updated": 1, "unchanged": 2, "skipped": 0, "failed": 0},
        "changed_documents": [
            {"document_id": "doc-1", "relative_path": "contracts/acme.pdf", "action": "updated", "source_name": "Share"},
            {"document_id": "doc-2", "relative_path": "contracts/beta.pdf", "action": "created", "source_name": "Share"},
        ],
        "changed_document_ids": ["doc-1", "doc-2"],
    }


WEEKLY_NEW_YORK = {
    "kind": "calendar", "frequency": "weekly", "days_of_week": ["monday"], "day_of_month": None,
    "time_of_day": "09:00", "timezone": "America/New_York",
}
INTERVAL_HOURLY = {"unit": "hours", "value": 1}
FILE_SYNC_CONFIG = {
    "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": False,
    "sources": [{"scope_type": "personal", "scope_id": "user-1", "source_id": "share", "name": "Share"}],
}


def golden_cases():
    """Manual-only and interval workflows, whose prompts must not change."""
    two_tasks = _tasks("List this week's meetings.", "Summarize them for Monday.")
    return {
        "manual_tasks": (_workflow(tasks=copy.deepcopy(two_tasks)), None),
        "manual_legacy": (_workflow(), None),
        "interval_tasks": (_workflow("interval", INTERVAL_HOURLY, copy.deepcopy(two_tasks)), None),
        "interval_legacy": (_workflow("interval", INTERVAL_HOURLY), None),
        "interval_structured": (
            _workflow("interval", {"unit": "minutes", "value": 30}, copy.deepcopy(two_tasks), definition_version=3),
            None,
        ),
        "file_sync_interval_tasks": (
            _workflow("file_sync", INTERVAL_HOURLY, copy.deepcopy(two_tasks), file_sync=copy.deepcopy(FILE_SYNC_CONFIG)),
            _file_sync_result(),
        ),
        "file_sync_interval_legacy": (
            _workflow("file_sync", INTERVAL_HOURLY, file_sync=copy.deepcopy(FILE_SYNC_CONFIG)),
            _file_sync_result(),
        ),
        # Saving a manual workflow clears its schedule, but a stray stored schedule must not matter.
        "manual_with_stray_calendar_schedule": (_workflow(schedule=copy.deepcopy(WEEKLY_NEW_YORK)), None),
    }


def capture_prompts(harness):
    recorded = {}
    for name, (workflow, file_sync_result) in golden_cases().items():
        for trigger_source in ("manual", "scheduled"):
            harness.file_sync_result = copy.deepcopy(file_sync_result)
            recorded[f"{name}:{trigger_source}"] = harness.run(copy.deepcopy(workflow), trigger_source)
    return recorded


@pytest.fixture()
def harness():
    return PromptHarness()


def test_manual_and_interval_prompts_are_byte_identical_to_the_phase_1_head(harness):
    """No existing prompt, conversation message, URL Access prompt or search query changes."""
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    actual = capture_prompts(harness)
    assert sorted(actual) == sorted(golden)
    for key, prompts in actual.items():
        assert json.dumps(prompts, sort_keys=True) == json.dumps(golden[key], sort_keys=True), key
    # Anti-vacuity: the golden really holds task, legacy and File Sync prompts.
    assert golden["manual_tasks:manual"]["tasks"][1]["task_prompt"].startswith("Summarize them for Monday.")
    assert "[Workflow input context]" in golden["file_sync_interval_tasks:scheduled"]["tasks"][0]["task_prompt"]
    assert golden["interval_legacy:scheduled"]["legacy"]["task_prompt"] == "Summarize this week's priorities."
    assert not any("Current date and time" in json.dumps(prompts) for prompts in actual.values())


def _expected_line(text):
    return f"[Workflow run time]\nCurrent date and time: {text}"


@pytest.mark.parametrize(("started_at", "expected"), [
    # 1 November 2026 ends daylight saving time in New York: 09:00 is 13:00 UTC before and 14:00 UTC after.
    ("2026-10-26T13:00:00+00:00", "Monday, 26 October 2026, 09:00 (America/New_York)"),
    ("2026-11-02T14:00:00+00:00", "Monday, 2 November 2026, 09:00 (America/New_York)"),
    # 8 March 2026 starts daylight saving time: 09:00 is 14:00 UTC before and 13:00 UTC after.
    ("2026-03-02T14:00:00+00:00", "Monday, 2 March 2026, 09:00 (America/New_York)"),
    ("2026-03-09T13:00:00+00:00", "Monday, 9 March 2026, 09:00 (America/New_York)"),
])
def test_calendar_runs_carry_local_time_on_both_sides_of_a_dst_change(harness, started_at, expected):
    harness.started_at = started_at
    workflow = _workflow("interval", copy.deepcopy(WEEKLY_NEW_YORK),
                         _tasks("Read my email.", "List this week's to-dos."))
    prompts = harness.run(workflow, "scheduled")

    first, second = prompts["tasks"]
    assert first["task_prompt"] == f"Read my email.\n\n{_expected_line(expected)}"
    assert second["task_prompt"].startswith(f"List this week's to-dos.\n\n{_expected_line(expected)}\n\n")
    assert "[Previous workflow task output]\nOutput of task 1." in second["task_prompt"]
    # Document search stays scoped to what each task asks for.
    assert [task["task_search_query"] for task in prompts["tasks"]] == ["Read my email.", "List this week's to-dos."]
    assert prompts["user_message"] == f"Read my email.\n\n{_expected_line(expected)}"


def test_run_now_of_a_calendar_workflow_uses_the_actual_start_time(harness):
    """Scope follows the stored schedule, not how the run started."""
    harness.started_at = "2026-10-28T19:45:00+00:00"
    workflow = _workflow("interval", copy.deepcopy(WEEKLY_NEW_YORK), _tasks("List this week's to-dos."))
    for trigger_source in ("manual", "scheduled", "catch_up"):
        prompts = harness.run(copy.deepcopy(workflow), trigger_source)
        assert prompts["tasks"][0]["task_prompt"] == (
            "List this week's to-dos.\n\n"
            + _expected_line("Wednesday, 28 October 2026, 15:45 (America/New_York)")
        ), trigger_source


def test_resumed_run_keeps_its_original_start_time(harness):
    """A resumed run repeats the prompt its first attempt used, so replays stay identical."""
    harness.prior_run = {"id": "run-1", "started_at": "2026-10-26T13:00:00+00:00"}
    harness.started_at = "2026-10-26T18:30:00+00:00"
    prompts = harness.run(_workflow("interval", copy.deepcopy(WEEKLY_NEW_YORK), _tasks("Plan the week.")))
    assert prompts["tasks"][0]["task_prompt"].endswith("Monday, 26 October 2026, 09:00 (America/New_York)")


def test_calendar_legacy_and_file_sync_paths(harness):
    harness.started_at = "2026-10-26T13:00:00+00:00"
    line = _expected_line("Monday, 26 October 2026, 09:00 (America/New_York)")

    legacy = harness.run(_workflow("interval", copy.deepcopy(WEEKLY_NEW_YORK)))
    assert legacy["legacy"] == {
        "task_prompt": f"Summarize this week's priorities.\n\n{line}",
        "task_search_query": "Summarize this week's priorities.",
    }

    harness.file_sync_result = _file_sync_result()
    watched = harness.run(_workflow(
        "file_sync", copy.deepcopy(WEEKLY_NEW_YORK), _tasks("Review each changed contract.", "Summarize the review."),
        file_sync=copy.deepcopy(FILE_SYNC_CONFIG),
    ))
    first, second = watched["tasks"]
    # The first task reads the changed files, then the run time; later tasks get only the run time.
    assert first["task_prompt"].startswith("Review each changed contract.\n\n[Workflow input context]\n")
    assert first["task_prompt"].endswith(f"\n\n{line}")
    assert "[Workflow input context]" not in second["task_prompt"]
    assert second["task_prompt"].startswith(f"Summarize the review.\n\n{line}\n\n[Previous workflow task output]")
    assert first["task_search_query"] == "Review each changed contract."

    legacy_watch = harness.run(_workflow("file_sync", copy.deepcopy(WEEKLY_NEW_YORK), file_sync=copy.deepcopy(FILE_SYNC_CONFIG)))
    assert legacy_watch["legacy"]["task_prompt"].startswith("Summarize this week's priorities.\n\nFile Sync")
    assert legacy_watch["legacy"]["task_prompt"].endswith(f"\n\n{line}")
    assert legacy_watch["legacy"]["task_search_query"] == "Summarize this week's priorities."


def test_structured_calendar_workflow_gets_the_line_on_every_task(harness):
    harness.started_at = "2026-10-26T13:00:00+00:00"
    prompts = harness.run(_workflow(
        "interval", copy.deepcopy(WEEKLY_NEW_YORK), _tasks("Gather.", "Report."), definition_version=3,
    ))
    assert all("Current date and time: Monday, 26 October 2026, 09:00" in task["task_prompt"] for task in prompts["tasks"])


def test_helper_formats_and_refuses_consistently():
    context = SCHEDULES.workflow_run_time_context
    assert context(WEEKLY_NEW_YORK, "2026-09-28T13:00:00+00:00") == (
        "Current date and time: Monday, 28 September 2026, 09:00 (America/New_York)"
    )
    kolkata = {**WEEKLY_NEW_YORK, "timezone": "Asia/Kolkata"}
    assert context(kolkata, datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)) == (
        "Current date and time: Thursday, 1 January 2026, 05:30 (Asia/Kolkata)"
    )
    # A naive time is UTC, as everywhere else in the workflow store.
    assert context(kolkata, datetime(2026, 1, 1, 0, 0)) == context(kolkata, "2026-01-01T00:00:00+00:00")
    # Only a valid calendar schedule gets a line; nothing else ever raises.
    for schedule in ({}, INTERVAL_HOURLY, None, "weekly", {**WEEKLY_NEW_YORK, "timezone": "Mars/Olympus"},
                     {**WEEKLY_NEW_YORK, "kind": "cron"}):
        assert context(schedule, "2026-09-28T13:00:00+00:00") == ""
    for started_at in ("not a time", 12, object()):
        assert context(WEEKLY_NEW_YORK, started_at) == ""


def test_helper_names_do_not_depend_on_the_process_locale():
    source = (APP_ROOT / "functions_workflow_schedules.py").read_text(encoding="utf-8")
    body = source.split("def workflow_run_time_context", 1)[1].split("\ndef ", 1)[0]
    assert "strftime" not in body and "%A" not in body and "%B" not in body


def test_runner_wires_the_context_after_file_sync_and_before_the_conversation():
    source = _runner_source()
    body = source.split("def _run_authorized_workflow_impl(", 1)[1].split("\ndef ", 1)[0]
    file_sync_index = body.index("execution_workflow = _apply_file_sync_context_to_workflow(workflow, file_sync_result)")
    context_index = body.index("execution_workflow = _apply_workflow_run_time_context(execution_workflow, started_at)")
    conversation_index = body.index("_ensure_workflow_conversation(execution_workflow)")
    assert file_sync_index < context_index < conversation_index
    assert "run_time_prompt_context" not in (APP_ROOT / "functions_workflow_definitions.py").read_text(encoding="utf-8")


def test_version_contract():
    assert_app_version_at_least(MINIMUM_VERSION)


def capture():
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    recorded = capture_prompts(PromptHarness(require_new=False))
    GOLDEN_PATH.write_text(json.dumps(recorded, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Captured {len(recorded)} prompt sets into {GOLDEN_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Record the golden from the runner in this worktree.")
    arguments = parser.parse_args()
    if arguments.capture:
        capture()
        sys.exit(0)
    sys.exit(pytest.main([__file__, "-q"]))
