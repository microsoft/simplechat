# test_workflow_task_sequence.py
"""
Functional test for ordered workflow task sequences.
Version: 0.250.225
Implemented in: 0.250.064
Enhanced in: 0.250.065
Enhanced in: 0.250.129
Enhanced in: 0.250.225

This test ensures workflow tasks are normalized in order, execute with bounded
prior-task context, retry safely, and honor halt or continue error strategies.
"""

import ast
import os
import sys
import uuid
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
STORE_FILE = APP_ROOT / "functions_personal_workflows.py"
GROUP_STORE_FILE = APP_ROOT / "functions_group_workflows.py"
RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
MINIMUM_VERSION = "0.250.225"


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
            "normalize_workflow_max_tasks",
            "_normalize_workflow_tasks",
            "_normalize_workflow_error_handling",
        },
        {
            "uuid": uuid,
            "WORKFLOW_ERROR_STRATEGIES": {"halt", "continue"},
            "WORKFLOW_TASK_LIMIT_DEFAULT": 50,
            "WORKFLOW_TASK_LIMIT_MIN": 1,
            "WORKFLOW_TASK_LIMIT_MAX": 100,
            "WORKFLOW_MAX_TASKS": 50,
            "WORKFLOW_TASK_INSTRUCTIONS_MAX_LENGTH": 12000,
            "WORKFLOW_TASK_NAME_MAX_LENGTH": 120,
            "WORKFLOW_TASK_RUNNER_TYPES": {"inherit", "agent", "model"},
        },
    )


def load_runner_helpers(dispatch, personal_runner_normalizer=None, group_runner_normalizer=None):
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
        "normalize_group_workflow_task_runner": group_runner_normalizer or (
            lambda *_args, **_kwargs: {"type": "inherit"}
        ),
        "normalize_personal_workflow_task_runner": personal_runner_normalizer or (
            lambda *_args, **_kwargs: {"type": "inherit"}
        ),
        "_save_workflow_run_item_record": lambda workflow, item: saved_items.append(dict(item)) or item,
        "_utc_now_iso": lambda: next(timestamps),
        "build_analyze_config": lambda action: {"enabled": action.get("type") == "analyze"},
        "_get_document_action_config": lambda source: dict(
            (source or {}).get("document_action") or {"type": "none"}
        ),
        "WORKFLOW_FILE_SYNC_CONTEXT_MAX_CHARS": 8000,
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "_get_workflow_file_sync_config": lambda workflow: (workflow or {}).get("file_sync") or {},
        "uuid": uuid,
    }
    helpers = load_functions(
        RUNNER_FILE,
        {
            "_truncate_workflow_task_context",
            "_truncate_workflow_file_sync_context",
            "_format_workflow_file_sync_context",
            "_apply_file_sync_changed_documents_to_action",
            "_apply_file_sync_context_to_workflow",
            "_resolve_workflow_task_document_action",
            "_build_workflow_task_execution_workflow",
            "_get_workflow_task_requested_runner_mode",
            "_build_workflow_task_runner_audit",
            "_resolve_workflow_task_runner",
            "_workflow_task_run_item_id",
            "_save_workflow_task_run_item",
            "_merge_workflow_task_execution_results",
            "_execute_workflow_task_sequence",
        },
        namespace,
    )
    return helpers, saved_items


def load_personal_task_runner_helpers(personal_agents, global_agents, settings, personal_endpoints=None):
    return load_functions(
        STORE_FILE,
        {
            "_normalize_text",
            "_build_selectable_agents",
            "_find_matching_agent",
            "_normalize_selected_agent",
            "_build_model_endpoint_candidates",
            "_summarize_model_binding",
            "normalize_personal_workflow_task_runner",
        },
        {
            "WORKFLOW_TASK_RUNNER_TYPES": {"inherit", "agent", "model"},
            "get_global_agents": lambda: list(global_agents),
            "get_personal_agents": lambda _user_id: list(personal_agents),
            "get_settings": lambda: settings,
            "get_user_settings": lambda _user_id: {
                "settings": {"personal_model_endpoints": list(personal_endpoints or [])}
            },
            "normalize_model_endpoints": lambda endpoints: (list(endpoints), []),
        },
    )


def load_group_task_runner_helpers(group_agents, global_agents, settings, group_endpoints=None):
    role_checks = []

    def normalize_text(value, field_name, required=False):
        normalized = str(value or "").strip()
        if required and not normalized:
            raise ValueError(f"{field_name} is required.")
        return normalized

    helpers = load_functions(
        GROUP_STORE_FILE,
        {
            "_build_selectable_agents",
            "_find_matching_agent",
            "_normalize_selected_agent",
            "_build_model_endpoint_candidates",
            "_summarize_model_binding",
            "normalize_group_workflow_task_runner",
        },
        {
            "GROUP_WORKFLOW_MEMBER_ROLES": ("Owner", "Admin", "DocumentManager", "User"),
            "WORKFLOW_TASK_RUNNER_TYPES": {"inherit", "agent", "model"},
            "_normalize_text": normalize_text,
            "assert_group_role": lambda user_id, group_id, allowed_roles: role_checks.append(
                (user_id, group_id, allowed_roles)
            ),
            "get_global_agents": lambda: list(global_agents),
            "get_group_agents": lambda _group_id: list(group_agents),
            "get_group_model_endpoints": lambda _group_id: list(group_endpoints or []),
            "get_settings": lambda: settings,
            "normalize_model_endpoints": lambda endpoints: (list(endpoints), []),
        },
    )
    return helpers, role_checks


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
    assert [task["runner"] for task in tasks] == [{"type": "inherit"}, {"type": "inherit"}]
    assert policy == {"strategy": "continue", "retry_count": 2}

    existing_tasks = helpers["_normalize_workflow_tasks"](
        {},
        existing_workflow={
            "tasks": [
                {"id": "legacy", "name": "Legacy", "instructions": "Keep working."}
            ]
        },
    )
    assert existing_tasks[0]["runner"] == {"type": "inherit"}

    try:
        helpers["_normalize_workflow_tasks"]({"tasks": []})
        raise AssertionError("Expected an empty task list to be rejected.")
    except ValueError as exc:
        assert "at least one" in str(exc)

    print("PASS: workflow task normalization")


def test_configurable_task_limit_normalization() -> None:
    """Clamp admin-configured task limits and enforce the effective limit."""
    print("Testing configurable workflow task limit normalization...")
    helpers = load_store_helpers()

    assert helpers["normalize_workflow_max_tasks"](None) == 50
    assert helpers["normalize_workflow_max_tasks"](0) == 1
    assert helpers["normalize_workflow_max_tasks"](150) == 100

    fifty_tasks = [
        {
            "id": f"task-{index}",
            "name": f"Task {index}",
            "instructions": f"Complete task {index}.",
        }
        for index in range(1, 51)
    ]
    assert len(helpers["_normalize_workflow_tasks"]({"tasks": fifty_tasks}, max_tasks=50)) == 50

    try:
        helpers["_normalize_workflow_tasks"](
            {
                "tasks": [
                    {
                        "id": f"task-{index}",
                        "name": f"Task {index}",
                        "instructions": f"Complete task {index}.",
                    }
                    for index in range(1, 52)
                ]
            },
            max_tasks=50,
        )
        raise AssertionError("Expected the configured 50-task limit to be enforced.")
    except ValueError as exc:
        assert "up to 50 tasks" in str(exc)

    try:
        helpers["_normalize_workflow_tasks"](
            {
                "tasks": [
                    {
                        "id": f"task-{index}",
                        "name": f"Task {index}",
                        "instructions": f"Complete task {index}.",
                    }
                    for index in range(1, 102)
                ]
            },
            max_tasks=150,
        )
        raise AssertionError("Expected the hard 100-task limit to be enforced.")
    except ValueError as exc:
        assert "up to 100 tasks" in str(exc)

    print("PASS: configurable workflow task limit normalization")


def test_personal_task_runner_normalization_and_authorization() -> None:
    """Normalize server-authorized personal agents and model bindings without secrets."""
    print("Testing personal task runner authorization...")
    settings = {
        "enable_semantic_kernel": True,
        "allow_user_agents": True,
        "per_user_semantic_kernel": True,
        "merge_global_semantic_kernel_with_workspace": False,
        "allow_user_custom_endpoints": False,
        "model_endpoints": [
            {
                "id": "global-endpoint",
                "name": "Server endpoint",
                "provider": "aoai",
                "enabled": True,
                "connection": {"api_key": "must-not-persist"},
                "models": [
                    {"id": "fast-model", "displayName": "Fast", "enabled": True},
                    {"id": "disabled-model", "displayName": "Disabled", "enabled": False},
                ],
            }
        ],
    }
    helpers = load_personal_task_runner_helpers(
        personal_agents=[
            {"id": "personal-agent", "name": "server_name", "display_name": "Server Name"},
            {"id": "disabled-agent", "name": "disabled", "is_enabled": False},
        ],
        global_agents=[{"id": "global-agent", "name": "global_name", "is_global": True}],
        settings=settings,
    )

    agent_runner = helpers["normalize_personal_workflow_task_runner"](
        "user-1",
        {
            "type": "agent",
            "selected_agent": {
                "id": "personal-agent",
                "name": "browser_tampered_name",
                "is_global": False,
            },
        },
        settings=settings,
    )
    assert agent_runner["selected_agent"]["name"] == "server_name"
    assert agent_runner["selected_agent"]["is_global"] is False

    model_runner = helpers["normalize_personal_workflow_task_runner"](
        "user-1",
        {
            "type": "model",
            "model_endpoint_id": "global-endpoint",
            "model_id": "fast-model",
            "model_provider": "browser-value",
        },
        settings=settings,
    )
    assert model_runner["model_provider"] == "aoai"
    assert model_runner["model_binding_summary"]["label"] == "Global: Server endpoint / Fast"
    assert "connection" not in model_runner["model_binding_summary"]

    for invalid_runner in (
        {"type": "agent", "selected_agent": {"id": "cross-user", "is_global": False}},
        {"type": "agent", "selected_agent": {"id": "disabled-agent", "is_global": False}},
        {"type": "agent", "selected_agent": {"id": "global-agent", "is_global": True}},
        {"type": "model", "model_endpoint_id": "missing", "model_id": "fast-model"},
        {"type": "model", "model_endpoint_id": "global-endpoint", "model_id": "disabled-model"},
    ):
        try:
            helpers["normalize_personal_workflow_task_runner"](
                "user-1",
                invalid_runner,
                settings=settings,
            )
            raise AssertionError(f"Expected task runner rejection: {invalid_runner}")
        except ValueError:
            pass

    task_helpers = load_store_helpers()
    normalized_tasks = task_helpers["_normalize_workflow_tasks"](
        {
            "tasks": [
                {
                    "id": "extract",
                    "name": "Extract",
                    "instructions": "Extract facts.",
                    "runner": {
                        "type": "model",
                        "model_endpoint_id": "global-endpoint",
                        "model_id": "fast-model",
                    },
                }
            ]
        },
        task_runner_normalizer=lambda runner: helpers["normalize_personal_workflow_task_runner"](
            "user-1",
            runner,
            settings=settings,
        ),
    )
    assert normalized_tasks[0]["runner"] == model_runner
    assert "'tasks': tasks" in read_text(STORE_FILE)
    print("PASS: personal task runner authorization")


def test_group_task_agent_authorization() -> None:
    """Normalize only agents belonging to the currently authorized group."""
    print("Testing group task runner authorization...")
    settings = {
        "enable_semantic_kernel": True,
        "allow_group_agents": True,
        "per_user_semantic_kernel": True,
        "merge_global_semantic_kernel_with_workspace": False,
        "allow_group_custom_endpoints": True,
        "model_endpoints": [],
    }
    helpers, role_checks = load_group_task_runner_helpers(
        group_agents=[{"id": "group-agent", "name": "group_server_name", "group_id": "group-1"}],
        global_agents=[{"id": "global-agent", "name": "global_name", "is_global": True}],
        settings=settings,
        group_endpoints=[
            {
                "id": "group-endpoint",
                "name": "Group endpoint",
                "provider": "openai",
                "models": [{"id": "group-model", "displayName": "Group Model"}],
            }
        ],
    )
    agent_runner = helpers["normalize_group_workflow_task_runner"](
        "member-1",
        "group-1",
        {
            "type": "agent",
            "selected_agent": {
                "id": "group-agent",
                "name": "tampered",
                "is_global": False,
                "is_group": True,
                "group_id": "other-group",
            },
        },
        settings=settings,
    )
    assert agent_runner["selected_agent"]["name"] == "group_server_name"
    assert agent_runner["selected_agent"]["group_id"] == "group-1"
    assert role_checks[-1][0:2] == ("member-1", "group-1")

    model_runner = helpers["normalize_group_workflow_task_runner"](
        "member-1",
        "group-1",
        {"type": "model", "model_endpoint_id": "group-endpoint", "model_id": "group-model"},
        settings=settings,
    )
    assert model_runner["model_binding_summary"]["scope"] == "group"

    for invalid_agent in (
        {"id": "cross-group-agent", "is_global": False, "is_group": True, "group_id": "other-group"},
        {"id": "global-agent", "is_global": True},
    ):
        try:
            helpers["normalize_group_workflow_task_runner"](
                "member-1",
                "group-1",
                {"type": "agent", "selected_agent": invalid_agent},
                settings=settings,
            )
            raise AssertionError(f"Expected group task agent rejection: {invalid_agent}")
        except ValueError:
            pass
    print("PASS: group task runner authorization")


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
    # Build the File Sync context through the real producer instead of injecting
    # file_sync_prompt_context by hand, so a missing producer cannot pass this test again.
    execution_workflow = helpers["_apply_file_sync_context_to_workflow"](
        {
            "id": "workflow-1",
            "name": "Sequence",
            "user_id": "user-1",
            "runner_type": "model",
            "task_prompt": "Run the sequence.",
            "document_action": {"type": "search", "document_ids": ["doc-1"]},
            "file_sync": {"use_changed_documents": False, "sources": []},
            "tasks": [
                {"id": "collect", "name": "Collect", "instructions": "Collect facts."},
                {"id": "summarize", "name": "Summarize", "instructions": "Write a summary."},
            ],
            "error_handling": {"strategy": "halt", "retry_count": 0},
        },
        {
            "enabled": True,
            "counts": {"scanned": 3, "created": 1, "updated": 1, "unchanged": 1, "skipped": 0, "failed": 0},
            "changed_documents": [
                {"document_id": "doc-1", "relative_path": "reports/q3.pdf", "action": "created", "source_name": "Reports"},
            ],
            "changed_document_ids": ["doc-1"],
        },
    )
    assert execution_workflow["file_sync_prompt_context"], (
        "_apply_file_sync_context_to_workflow must publish file_sync_prompt_context for tasks."
    )

    result = helpers["_execute_workflow_task_sequence"](
        execution_workflow,
        {},
        "conversation-1",
        "run-1",
        None,
        {},
    )

    assert [workflow["active_task"]["id"] for workflow in dispatched_workflows] == ["collect", "summarize"]
    assert [workflow["runner_type"] for workflow in dispatched_workflows] == ["model", "model"]
    assert dispatched_workflows[0]["document_action"]["type"] == "search"
    assert "[Workflow input context]" in dispatched_workflows[0]["task_prompt"]
    assert "File Sync context for this workflow run" in dispatched_workflows[0]["task_prompt"]
    assert "reports/q3.pdf" in dispatched_workflows[0]["task_prompt"]
    assert "[Workflow input context]" not in dispatched_workflows[1]["task_prompt"]
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


def test_alternating_task_runners_and_audit_metadata() -> None:
    """Dispatch model, agent, and model overrides with per-task audit metadata."""
    print("Testing alternating task runners and audit metadata...")
    dispatched_workflows = []

    def normalize_runner(_user_id, requested_runner, settings=None):
        runner_type = requested_runner.get("type") or "inherit"
        if runner_type == "inherit":
            return {"type": "inherit"}
        if runner_type == "agent":
            return {
                "type": "agent",
                "selected_agent": {
                    "id": "research-agent",
                    "name": "server_research",
                    "is_global": False,
                    "is_group": False,
                },
            }
        return {
            "type": "model",
            "model_endpoint_id": requested_runner["model_endpoint_id"],
            "model_id": requested_runner["model_id"],
            "model_provider": "aoai",
            "model_binding_summary": {
                "endpoint_id": requested_runner["model_endpoint_id"],
                "model_id": requested_runner["model_id"],
                "provider": "aoai",
            },
        }

    def dispatch(workflow, *_args, **_kwargs):
        dispatched_workflows.append(dict(workflow))
        task_order = workflow["active_task"]["order"]
        return {
            "reply": f"Task {task_order} result",
            "model_deployment_name": f"deployment-{task_order}",
            "provider": "agent" if workflow["runner_type"] == "agent" else "aoai",
            "token_usage": {
                "prompt_tokens": task_order,
                "completion_tokens": task_order + 1,
                "total_tokens": (task_order * 2) + 1,
            },
        }

    helpers, saved_items = load_runner_helpers(
        dispatch,
        personal_runner_normalizer=normalize_runner,
    )
    result = helpers["_execute_workflow_task_sequence"](
        {
            "id": "workflow-alternating",
            "name": "Alternating",
            "user_id": "user-1",
            "runner_type": "model",
            "model_endpoint_id": "default-endpoint",
            "model_id": "default-model",
            "document_action": {"type": "none"},
            "tasks": [
                {
                    "id": "extract",
                    "name": "Extract",
                    "instructions": "Extract.",
                    "runner": {"type": "model", "model_endpoint_id": "fast-endpoint", "model_id": "fast-model"},
                },
                {
                    "id": "research",
                    "name": "Research",
                    "instructions": "Research.",
                    "runner": {"type": "agent", "selected_agent": {"id": "browser-agent"}},
                },
                {
                    "id": "evaluate",
                    "name": "Evaluate",
                    "instructions": "Evaluate.",
                    "runner": {"type": "model", "model_endpoint_id": "reason-endpoint", "model_id": "reason-model"},
                },
            ],
            "error_handling": {"strategy": "halt", "retry_count": 0},
        },
        {},
        "conversation-alternating",
        "run-alternating",
        None,
        {},
    )

    assert [workflow["runner_type"] for workflow in dispatched_workflows] == ["model", "agent", "model"]
    assert dispatched_workflows[0]["model_id"] == "fast-model"
    assert dispatched_workflows[1]["selected_agent"]["name"] == "server_research"
    assert dispatched_workflows[2]["model_id"] == "reason-model"
    succeeded_items = [item for item in saved_items if item["status"] == "succeeded"]
    assert [item["runner"]["requested_mode"] for item in succeeded_items] == ["model", "agent", "model"]
    assert [item["runner"]["resolved_type"] for item in succeeded_items] == ["model", "agent", "model"]
    assert succeeded_items[1]["runner"]["agent_id"] == "research-agent"
    assert succeeded_items[1]["runner"]["model_deployment_name"] == "deployment-2"
    assert succeeded_items[2]["token_usage"]["total_tokens"] == 7
    assert result["token_usage"]["total_tokens"] == 15
    print("PASS: alternating task runners and audit metadata")


def test_unavailable_task_runner_retries_and_continues() -> None:
    """Treat execution-time runner loss as a retryable task failure."""
    print("Testing unavailable task runner retry and continue behavior...")
    resolution_attempts = {"missing": 0, "inherit": 0}
    dispatched_task_ids = []

    def normalize_runner(_user_id, requested_runner, settings=None):
        runner_type = requested_runner.get("type") or "inherit"
        resolution_attempts[runner_type] += 1
        if runner_type == "missing":
            raise ValueError("The selected model endpoint is no longer available.")
        return {"type": "inherit"}

    def dispatch(workflow, *_args, **_kwargs):
        dispatched_task_ids.append(workflow["active_task"]["id"])
        return {"reply": "continued"}

    helpers, saved_items = load_runner_helpers(
        dispatch,
        personal_runner_normalizer=normalize_runner,
    )
    result = helpers["_execute_workflow_task_sequence"](
        {
            "id": "workflow-unavailable",
            "name": "Unavailable",
            "user_id": "user-1",
            "runner_type": "model",
            "document_action": {"type": "none"},
            "tasks": [
                {
                    "id": "missing",
                    "name": "Missing runner",
                    "instructions": "Fail runner resolution.",
                    "runner": {"type": "missing"},
                },
                {
                    "id": "later",
                    "name": "Later task",
                    "instructions": "Continue.",
                },
            ],
            "error_handling": {"strategy": "continue", "retry_count": 1},
        },
        {},
        "conversation-unavailable",
        "run-unavailable",
        None,
        {},
    )

    assert resolution_attempts == {"missing": 2, "inherit": 1}
    assert dispatched_task_ids == ["later"]
    assert [item["status"] for item in result["task_results"]] == ["failed", "succeeded"]
    failed_item = next(item for item in saved_items if item["task_id"] == "missing" and item["status"] == "failed")
    assert failed_item["attempt_count"] == 2
    assert failed_item["runner"]["requested_mode"] == "missing"
    print("PASS: unavailable task runner retry and continue behavior")


def test_execution_revalidation_rejects_deleted_agent_and_disabled_model() -> None:
    """Recheck stored task runners against current options before each dispatch."""
    print("Testing execution-time task runner revalidation...")
    personal_agents = [
        {"id": "agent-before-delete", "name": "agent_before_delete", "display_name": "Agent"}
    ]
    settings = {
        "enable_semantic_kernel": True,
        "allow_user_agents": True,
        "per_user_semantic_kernel": True,
        "merge_global_semantic_kernel_with_workspace": False,
        "allow_user_custom_endpoints": False,
        "model_endpoints": [
            {
                "id": "endpoint-before-disable",
                "name": "Endpoint",
                "provider": "aoai",
                "enabled": True,
                "models": [{"id": "model-before-disable", "displayName": "Model", "enabled": True}],
            }
        ],
    }
    authorization_helpers = load_personal_task_runner_helpers(
        personal_agents=personal_agents,
        global_agents=[],
        settings=settings,
    )
    saved_agent_runner = authorization_helpers["normalize_personal_workflow_task_runner"](
        "user-1",
        {
            "type": "agent",
            "selected_agent": {"id": "agent-before-delete", "is_global": False},
        },
        settings=settings,
    )
    saved_model_runner = authorization_helpers["normalize_personal_workflow_task_runner"](
        "user-1",
        {
            "type": "model",
            "model_endpoint_id": "endpoint-before-disable",
            "model_id": "model-before-disable",
        },
        settings=settings,
    )

    personal_agents.clear()
    settings["model_endpoints"][0]["enabled"] = False
    dispatched_task_ids = []

    def revalidate_runner(user_id, requested_runner, settings=None):
        return authorization_helpers["normalize_personal_workflow_task_runner"](
            user_id,
            requested_runner,
            settings=execution_settings,
        )

    execution_settings = settings

    def dispatch(workflow, *_args, **_kwargs):
        dispatched_task_ids.append(workflow["active_task"]["id"])
        return {"reply": "inherited task completed"}

    helpers, _saved_items = load_runner_helpers(
        dispatch,
        personal_runner_normalizer=revalidate_runner,
    )
    result = helpers["_execute_workflow_task_sequence"](
        {
            "id": "workflow-stale-runners",
            "name": "Stale runners",
            "user_id": "user-1",
            "runner_type": "model",
            "document_action": {"type": "none"},
            "tasks": [
                {
                    "id": "deleted-agent",
                    "name": "Deleted agent",
                    "instructions": "Use the deleted agent.",
                    "runner": saved_agent_runner,
                },
                {
                    "id": "disabled-model",
                    "name": "Disabled model",
                    "instructions": "Use the disabled model.",
                    "runner": saved_model_runner,
                },
                {
                    "id": "inherit",
                    "name": "Inherited runner",
                    "instructions": "Continue with the workflow default.",
                    "runner": {"type": "inherit"},
                },
            ],
            "error_handling": {"strategy": "continue", "retry_count": 0},
        },
        execution_settings,
        "conversation-stale-runners",
        "run-stale-runners",
        None,
        {},
    )

    assert [item["status"] for item in result["task_results"]] == ["failed", "failed", "succeeded"]
    assert "valid personal" in result["task_results"][0]["error"]
    assert "disabled" in result["task_results"][1]["error"]
    assert dispatched_task_ids == ["inherit"]
    print("PASS: execution-time task runner revalidation")


def test_version_and_legacy_dispatch_contract() -> None:
    """Keep the version and legacy no-task dispatch branch explicit."""
    runner_content = read_text(RUNNER_FILE)
    assert_app_version_at_least(MINIMUM_VERSION)
    assert "if execution_workflow.get('tasks'):" in runner_content
    assert "execution_result = _execute_workflow_dispatch(" in runner_content


def run_tests() -> bool:
    tests = [
        test_task_and_error_policy_normalization,
        test_configurable_task_limit_normalization,
        test_personal_task_runner_normalization_and_authorization,
        test_group_task_agent_authorization,
        test_ordered_tasks_chain_context_and_apply_documents_once,
        test_continue_strategy_retries_and_runs_later_tasks,
        test_alternating_task_runners_and_audit_metadata,
        test_unavailable_task_runner_retries_and_continues,
        test_execution_revalidation_rejects_deleted_agent_and_disabled_model,
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