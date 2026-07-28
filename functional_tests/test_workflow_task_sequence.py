# test_workflow_task_sequence.py
"""
Functional test for ordered workflow task sequences.
Version: 0.250.064
Implemented in: 0.250.064

This test ensures workflow tasks are normalized in order, execute with bounded
prior-task context, retry safely, and honor halt or continue error strategies.
"""

import ast
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
STORE_FILE = APP_ROOT / "functions_personal_workflows.py"
RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
EXPECTED_VERSION = "0.250.064"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_functions(path: Path, function_names: set[str], namespace: dict) -> dict:
    parsed = ast.parse(read_text(path), filename=str(path))
    selected_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert len(selected_nodes) == len(function_names), f"Expected functions {sorted(function_names)}"
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def load_store_helpers() -> dict:
    return load_functions(
        STORE_FILE,
        {
            "_normalize_text",
            "_normalize_workflow_tasks",
            "_normalize_workflow_error_handling",
        },
        {
            "uuid": uuid,
            "WORKFLOW_ERROR_STRATEGIES": {"halt", "continue"},
            "WORKFLOW_MAX_TASKS": 20,
            "WORKFLOW_TASK_INSTRUCTIONS_MAX_LENGTH": 12000,
            "WORKFLOW_TASK_NAME_MAX_LENGTH": 120,
        },
    )


def load_runner_helpers(dispatch):
    saved_items = []
    timestamps = iter(f"2026-07-27T00:00:{index:02d}+00:00" for index in range(60))
    namespace = {
        "DOCUMENT_ACTION_TYPE_NONE": "none",
        "WORKFLOW_TASK_CONTEXT_MAX_CHARS": 12000,
        "_add_workflow_activity_thought": lambda *args, **kwargs: None,
        "_build_response_preview": lambda value, max_length=220: str(value or "")[:max_length],
        "_execute_workflow_dispatch": dispatch,
        "_get_workflow_group_id": lambda workflow: str(workflow.get("group_id") or ""),
        "_merge_token_usage_summaries": lambda results: {
            "total_tokens": sum(int((result.get("token_usage") or {}).get("total_tokens") or 0) for result in results)
        },
        "_save_workflow_run_item_record": lambda workflow, item: saved_items.append(dict(item)) or item,
        "_utc_now_iso": lambda: next(timestamps),
        "build_analyze_config": lambda action: {"enabled": action.get("type") == "analyze"},
        "uuid": uuid,
    }
    helpers = load_functions(
        RUNNER_FILE,
        {
            "_truncate_workflow_task_context",
            "_build_workflow_task_execution_workflow",
            "_workflow_task_run_item_id",
            "_save_workflow_task_run_item",
            "_merge_workflow_task_execution_results",
            "_execute_workflow_task_sequence",
        },
        namespace,
    )
    return helpers, saved_items


def test_task_and_error_policy_normalization() -> None:
    """Normalize ordered instruction tasks and bounded error handling."""
    print("Testing workflow task normalization...")
    helpers = load_store_helpers()

    tasks = helpers["_normalize_workflow_tasks"]({
        "tasks": [
            {"id": "collect", "name": "Collect", "instructions": "Collect the source facts."},
            {"id": "summarize", "name": "Summarize", "instructions": "Summarize the facts."},
        ]
    })
    policy = helpers["_normalize_workflow_error_handling"]({
        "error_handling": {"strategy": "continue", "retry_count": 2}
    })

    assert [task["order"] for task in tasks] == [1, 2]
    assert [task["type"] for task in tasks] == ["instructions", "instructions"]
    assert policy == {"strategy": "continue", "retry_count": 2}

    try:
        helpers["_normalize_workflow_tasks"]({"tasks": []})
        raise AssertionError("Expected an empty task list to be rejected.")
    except ValueError as exc:
        assert "at least one" in str(exc)

    print("PASS: workflow task normalization")


def test_ordered_tasks_chain_context_and_apply_documents_once() -> None:
    """Execute tasks in order and apply configured document input only to task one."""
    print("Testing ordered task context chaining...")
    dispatched_workflows = []

    def dispatch(workflow, *_args, **_kwargs):
        dispatched_workflows.append(dict(workflow))
        return {
            "reply": f"Result {len(dispatched_workflows)}",
            "token_usage": {"total_tokens": 5},
            "agent_citations": [{"task": len(dispatched_workflows)}],
        }

    helpers, saved_items = load_runner_helpers(dispatch)
    result = helpers["_execute_workflow_task_sequence"](
        {
            "id": "workflow-1",
            "name": "Sequence",
            "user_id": "user-1",
            "runner_type": "model",
            "document_action": {"type": "search", "document_ids": ["doc-1"]},
            "file_sync_prompt_context": "File Sync context for this workflow run.",
            "tasks": [
                {"id": "collect", "name": "Collect", "instructions": "Collect facts."},
                {"id": "summarize", "name": "Summarize", "instructions": "Write a summary."},
            ],
            "error_handling": {"strategy": "halt", "retry_count": 0},
        },
        {},
        "conversation-1",
        "run-1",
        None,
        {},
    )

    assert [workflow["active_task"]["id"] for workflow in dispatched_workflows] == ["collect", "summarize"]
    assert dispatched_workflows[0]["document_action"]["type"] == "search"
    assert "[Workflow input context]" in dispatched_workflows[0]["task_prompt"]
    assert "File Sync context for this workflow run." in dispatched_workflows[0]["task_prompt"]
    assert dispatched_workflows[1]["document_action"]["type"] == "none"
    assert "[Previous workflow task output]" in dispatched_workflows[1]["task_prompt"]
    assert "Result 1" in dispatched_workflows[1]["task_prompt"]
    assert result["task_error_count"] == 0
    assert result["token_usage"]["total_tokens"] == 10
    assert [item["status"] for item in saved_items if item["item_type"] == "task"][-2:] == ["running", "succeeded"]

    print("PASS: ordered task context chaining")


def test_continue_strategy_retries_and_runs_later_tasks() -> None:
    """Retry failed tasks, record the failure, and continue when configured."""
    print("Testing workflow task retry and continue strategy...")
    attempts = {"first": 0, "second": 0}

    def dispatch(workflow, *_args, **_kwargs):
        task_id = workflow["active_task"]["id"]
        attempts[task_id] += 1
        if task_id == "first":
            raise ValueError("first task failed")
        return {"reply": "second task succeeded"}

    helpers, saved_items = load_runner_helpers(dispatch)
    result = helpers["_execute_workflow_task_sequence"](
        {
            "id": "workflow-2",
            "name": "Continue",
            "user_id": "user-1",
            "runner_type": "model",
            "document_action": {"type": "none"},
            "tasks": [
                {"id": "first", "name": "First", "instructions": "Fail."},
                {"id": "second", "name": "Second", "instructions": "Continue."},
            ],
            "error_handling": {"strategy": "continue", "retry_count": 1},
        },
        {},
        "conversation-2",
        "run-2",
        None,
        {},
    )

    assert attempts == {"first": 2, "second": 1}
    assert result["task_error_count"] == 1
    assert [task["status"] for task in result["task_results"]] == ["failed", "succeeded"]
    assert any(item["task_id"] == "first" and item["status"] == "failed" for item in saved_items)

    print("PASS: workflow task retry and continue strategy")


def test_version_and_legacy_dispatch_contract() -> None:
    """Keep the version and legacy no-task dispatch branch explicit."""
    config_content = read_text(APP_ROOT / "config.py")
    runner_content = read_text(RUNNER_FILE)
    assert f'VERSION = "{EXPECTED_VERSION}"' in config_content
    assert "if execution_workflow.get('tasks'):" in runner_content
    assert "execution_result = _execute_workflow_dispatch(" in runner_content


def run_tests() -> bool:
    tests = [
        test_task_and_error_policy_normalization,
        test_ordered_tasks_chain_context_and_apply_documents_once,
        test_continue_strategy_retries_and_runs_later_tasks,
        test_version_and_legacy_dispatch_contract,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)