#!/usr/bin/env python3
# test_workflow_task_document_actions.py
"""
Functional test for per-task workflow workspace documents and the document picker fix.
Version: 0.250.225
Implemented in: 0.250.225

This test ensures that:
  1. The workflow builder loads the workspace document picker whenever the document
     action or document target changes, so the Tags control resolves instead of
     staying stuck on "Loading tags...".
  2. The "Refresh documents" button reloads the picker before applying a selection.
  3. Each workflow task owns its own document action, with legacy workflow-level
     configuration inherited by task 1 only.
  4. The runner executes every task with that task's own document action.

Refs microsoft/simplechat#1282
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
WORKFLOW_JS_FILE = APP_ROOT / "static" / "js" / "workspace" / "workspace_workflows.js"
CHAT_DOCUMENTS_JS_FILE = APP_ROOT / "static" / "js" / "chat" / "chat-documents.js"
WORKSPACE_TEMPLATE = APP_ROOT / "templates" / "workspace.html"
GROUP_TEMPLATE = APP_ROOT / "templates" / "group_workspaces.html"
MINIMUM_VERSION = "0.250.225"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_functions(path: Path, function_names: set, namespace: dict) -> dict:
    parsed = ast.parse(read_text(path), filename=str(path))
    selected_nodes = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert len(selected_nodes) == len(function_names), (
        f"Expected functions {sorted(function_names)} in {path.name}"
    )
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def build_document_action(action_type="none", **overrides):
    """Build a normalized-looking document action config for test fixtures."""
    action = {
        "type": action_type,
        "doc_scope": "all",
        "active_group_ids": [],
        "active_public_workspace_id": [],
        "window_unit": "pages",
        "window_size": None,
        "window_percent": None,
        "max_retries_per_window": 1,
        "document_ids": [],
        "left_document_id": "",
        "right_document_ids": [],
        "analysis_mode": "combined",
        "target_mode": "selected",
        "recent_window_minutes": 10,
    }
    action.update(overrides)
    return action


def load_store_helpers(document_action_error_types=()):
    """Load task normalization helpers with an injectable document action normalizer."""

    def fake_normalize_document_action_config(action_payload=None, **_kwargs):
        payload = action_payload if isinstance(action_payload, dict) else {}
        action_type = str(payload.get("type") or "none").strip().lower()
        if action_type in document_action_error_types:
            raise ValueError(f"{action_type} is currently disabled by an administrator.")
        if action_type == "none":
            return build_document_action()
        return build_document_action(
            action_type,
            document_ids=list(payload.get("document_ids") or []),
            left_document_id=str(payload.get("left_document_id") or ""),
            right_document_ids=list(payload.get("right_document_ids") or []),
        )

    return load_functions(
        STORE_FILE,
        {
            "_normalize_text",
            "normalize_workflow_max_tasks",
            "_normalize_workflow_tasks",
            "_normalize_task_document_action_config",
        },
        {
            "uuid": uuid,
            "WORKFLOW_TASK_LIMIT_DEFAULT": 50,
            "WORKFLOW_TASK_LIMIT_MIN": 1,
            "WORKFLOW_TASK_LIMIT_MAX": 100,
            "WORKFLOW_MAX_TASKS": 50,
            "WORKFLOW_TASK_INSTRUCTIONS_MAX_LENGTH": 12000,
            "WORKFLOW_TASK_NAME_MAX_LENGTH": 120,
            "WORKFLOW_TASK_RUNNER_TYPES": {"inherit", "agent", "model"},
            "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
            "DOCUMENT_ACTION_CONTEXT_WORKFLOW": "workflow",
            "get_settings": lambda: {},
            "get_document_action_max_documents_by_type": lambda *_args, **_kwargs: {},
            "get_enabled_document_action_types": lambda **_kwargs: ["analyze", "comparison"],
            "normalize_document_action_config": fake_normalize_document_action_config,
        },
    )


def load_group_scope_helper():
    return load_functions(
        GROUP_STORE_FILE,
        {"_apply_group_document_action_scope"},
        {},
    )


def load_runner_helpers():
    namespace = {
        "DOCUMENT_ACTION_TYPE_NONE": "none",
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "WORKFLOW_TASK_CONTEXT_MAX_CHARS": 12000,
        "build_analyze_config": lambda action: {"enabled": (action or {}).get("type") == "analyze"},
        "_get_document_action_config": lambda source: dict(
            (source or {}).get("document_action") or {"type": "none"}
        ),
        "_format_workflow_file_sync_context": lambda _result: "sync context",
        "_get_workflow_file_sync_config": lambda workflow: (workflow or {}).get("file_sync") or {},
    }
    return load_functions(
        RUNNER_FILE,
        {
            "_truncate_workflow_task_context",
            "_resolve_workflow_task_document_action",
            "_build_workflow_task_execution_workflow",
            "_apply_file_sync_changed_documents_to_action",
            "_apply_file_sync_context_to_workflow",
        },
        namespace,
    )


def test_document_picker_loads_on_action_change() -> None:
    """The picker must load whenever the document action or target mode changes."""
    print("Testing workflow document picker load wiring...")
    workflow_js = read_text(WORKFLOW_JS_FILE)
    chat_documents_js = read_text(CHAT_DOCUMENTS_JS_FILE)

    assert "function handleWorkflowDocumentActionSelectionChanged()" in workflow_js
    assert "function ensureWorkflowDocumentPickerLoaded(" in workflow_js
    assert 'workflowDocumentActionTypeSelect?.addEventListener("change", handleWorkflowDocumentActionSelectionChanged)' in workflow_js
    assert 'workflowAnalysisTargetModeSelect?.addEventListener("change", handleWorkflowDocumentActionSelectionChanged)' in workflow_js
    assert 'workflowDocumentActionTypeSelect?.addEventListener("change", updateDocumentActionFields)' not in workflow_js

    # The stale change handler was the only reason the picker never initialized.
    assert "ensureWorkflowDocumentPickerLoaded()" in workflow_js
    assert "workflowDocumentPickerLoadToken" in workflow_js

    # The tags dropdown must never be left in its initial loading markup state.
    assert "hideTagsDropdown();\n    return;" in chat_documents_js
    print("PASS: workflow document picker load wiring")


def test_refresh_documents_button_reloads_picker() -> None:
    """Refresh reloads the picker before applying the current picker selection."""
    print("Testing refresh documents button behavior...")
    workflow_js = read_text(WORKFLOW_JS_FILE)
    workspace_html = read_text(WORKSPACE_TEMPLATE)
    group_html = read_text(GROUP_TEMPLATE)

    refresh_start = workflow_js.index("async function applySelectedWorkspaceDocumentsToWorkflow()")
    refresh_body = workflow_js[refresh_start:refresh_start + 1600]
    assert "await ensureWorkflowDocumentPickerLoaded({ preserveSelection: true })" in refresh_body
    assert "Select one or more ${selectedLabel} documents in the picker first." not in workflow_js
    assert "Document list refreshed." in refresh_body
    assert "getWorkflowPickerAvailableDocumentCount()" in refresh_body

    for template in (workspace_html, group_html):
        assert 'id="workflow-use-selected-documents-btn">Refresh documents<' in template
        assert "Refresh selected documents" not in template
        assert "saved with the selected task" in template
    print("PASS: refresh documents button behavior")


def test_task_document_action_frontend_model() -> None:
    """Each task carries its own document action through the builder and payload."""
    print("Testing per-task document action frontend model...")
    workflow_js = read_text(WORKFLOW_JS_FILE)

    for expected_symbol in (
        "function createDefaultWorkflowTaskDocumentAction()",
        "function normalizeWorkflowTaskDocumentAction(",
        "function readWorkflowDocumentActionFromForm()",
        "function applyWorkflowDocumentActionToForm(",
        "function serializeWorkflowDocumentAction(",
        "function validateWorkflowTaskDocumentAction(",
    ):
        assert expected_symbol in workflow_js, f"Missing {expected_symbol}"

    # The editor writes to and reads from the active task.
    assert "activeTask.document_action = readWorkflowDocumentActionFromForm();" in workflow_js
    assert "applyWorkflowDocumentActionToForm(activeTask?.document_action);" in workflow_js
    # New tasks reset the workspace document fields.
    assert "document_action: createDefaultWorkflowTaskDocumentAction()," in workflow_js
    # Payload carries per-task actions plus a mirrored workflow-level action.
    assert "document_action: serializeWorkflowDocumentAction(task.document_action)," in workflow_js
    assert "const primaryDocumentAction = tasks.find((task) => task.document_action.type !== DOCUMENT_ACTION_NONE)?.document_action" in workflow_js
    assert "document_action: primaryDocumentAction," in workflow_js
    assert "analyze: buildWorkflowAnalyzeConfig(primaryDocumentAction)," in workflow_js
    # Legacy workflow-level config hydrates task 1 only.
    assert "if (index === 0 && !(task?.document_action && typeof task.document_action === \"object\") && workflowDocumentAction)" in workflow_js
    print("PASS: per-task document action frontend model")


def test_task_normalization_persists_document_actions() -> None:
    """Task normalization stores a document action per task."""
    print("Testing per-task document action normalization...")
    helpers = load_store_helpers()
    normalize_tasks = helpers["_normalize_workflow_tasks"]
    normalize_task_action = helpers["_normalize_task_document_action_config"]

    tasks = normalize_tasks(
        {
            "tasks": [
                {
                    "id": "analyze",
                    "name": "Analyze",
                    "instructions": "Analyze the contracts.",
                    "document_action": {"type": "analyze", "document_ids": ["doc-a"]},
                },
                {
                    "id": "compare",
                    "name": "Compare",
                    "instructions": "Compare the amendments.",
                    "document_action": {
                        "type": "comparison",
                        "left_document_id": "doc-v1",
                        "right_document_ids": ["doc-v2"],
                        "document_ids": ["doc-v1", "doc-v2"],
                    },
                },
                {
                    "id": "report",
                    "name": "Report",
                    "instructions": "Write the summary.",
                    "document_action": {"type": "none"},
                },
            ]
        },
        task_document_action_normalizer=normalize_task_action,
    )

    assert [task["document_action"]["type"] for task in tasks] == ["analyze", "comparison", "none"]
    assert tasks[0]["document_action"]["document_ids"] == ["doc-a"]
    assert tasks[1]["document_action"]["left_document_id"] == "doc-v1"
    assert tasks[1]["document_action"]["right_document_ids"] == ["doc-v2"]
    assert tasks[2]["document_action"]["document_ids"] == []
    print("PASS: per-task document action normalization")


def test_legacy_workflow_action_inherits_first_task_only() -> None:
    """Pre-migration workflows apply their single action to task 1 only."""
    print("Testing legacy document action inheritance...")
    helpers = load_store_helpers()
    normalize_tasks = helpers["_normalize_workflow_tasks"]
    normalize_task_action = helpers["_normalize_task_document_action_config"]
    legacy_action = build_document_action("analyze", document_ids=["legacy-doc"])

    tasks = normalize_tasks(
        {
            "tasks": [
                {"id": "one", "name": "One", "instructions": "First task."},
                {"id": "two", "name": "Two", "instructions": "Second task."},
            ]
        },
        task_document_action_normalizer=normalize_task_action,
        default_document_action=legacy_action,
    )

    assert tasks[0]["document_action"]["type"] == "analyze"
    assert tasks[0]["document_action"]["document_ids"] == ["legacy-doc"]
    assert tasks[1]["document_action"]["type"] == "none"

    # Without a normalizer the tasks stay untouched, preserving stored records.
    untouched = normalize_tasks(
        {"tasks": [{"id": "one", "name": "One", "instructions": "First task."}]}
    )
    assert "document_action" not in untouched[0]
    print("PASS: legacy document action inheritance")


def test_invalid_task_document_action_reports_task_number() -> None:
    """Per-task document action failures identify the offending task."""
    print("Testing per-task document action validation errors...")
    helpers = load_store_helpers(document_action_error_types={"comparison"})
    normalize_tasks = helpers["_normalize_workflow_tasks"]
    normalize_task_action = helpers["_normalize_task_document_action_config"]

    try:
        normalize_tasks(
            {
                "tasks": [
                    {"id": "one", "name": "Collect", "instructions": "First task."},
                    {
                        "id": "two",
                        "name": "Compare",
                        "instructions": "Second task.",
                        "document_action": {"type": "comparison"},
                    },
                ]
            },
            task_document_action_normalizer=normalize_task_action,
        )
    except ValueError as exc:
        assert "Workflow task 2 (Compare)" in str(exc), str(exc)
    else:
        raise AssertionError("Expected an invalid per-task document action to raise.")
    print("PASS: per-task document action validation errors")


def test_group_task_document_actions_stay_in_group_scope() -> None:
    """Group workflows force every task action into the owning group workspace."""
    print("Testing group task document action scoping...")
    helpers = load_group_scope_helper()
    apply_scope = helpers["_apply_group_document_action_scope"]

    scoped = apply_scope(
        "group-123",
        build_document_action(
            "analyze",
            doc_scope="all",
            active_group_ids=["other-group"],
            active_public_workspace_id=["public-1"],
        ),
    )
    assert scoped["doc_scope"] == "group"
    assert scoped["active_group_ids"] == ["group-123"]
    assert scoped["active_public_workspace_id"] == []

    untouched = apply_scope("group-123", build_document_action())
    assert untouched["type"] == "none"
    assert untouched["active_group_ids"] == []

    group_source = read_text(GROUP_STORE_FILE)
    assert "task_document_action_normalizer=lambda action_payload: _apply_group_document_action_scope(" in group_source
    print("PASS: group task document action scoping")


def test_runner_executes_each_task_with_its_own_action() -> None:
    """Every task runs with its own document action, not just task 1."""
    print("Testing runner per-task document action execution...")
    helpers = load_runner_helpers()
    build_execution_workflow = helpers["_build_workflow_task_execution_workflow"]

    workflow = {
        "document_action": build_document_action("analyze", document_ids=["workflow-doc"]),
        "tasks": [],
    }
    first_task = {
        "id": "one",
        "name": "One",
        "order": 1,
        "instructions": "Analyze the intake set.",
        "document_action": build_document_action("analyze", document_ids=["task-one-doc"]),
    }
    second_task = {
        "id": "two",
        "name": "Two",
        "order": 2,
        "instructions": "Compare the amendments.",
        "document_action": build_document_action(
            "comparison",
            document_ids=["doc-v1", "doc-v2"],
            left_document_id="doc-v1",
            right_document_ids=["doc-v2"],
        ),
    }

    first_execution = build_execution_workflow(workflow, first_task, include_document_action=True)
    second_execution = build_execution_workflow(
        workflow,
        second_task,
        previous_reply="prior output",
        include_document_action=False,
    )

    assert first_execution["document_action"]["document_ids"] == ["task-one-doc"]
    assert first_execution["analyze"]["enabled"] is True
    assert second_execution["document_action"]["type"] == "comparison"
    assert second_execution["document_action"]["left_document_id"] == "doc-v1"
    assert second_execution["analyze"]["enabled"] is False
    assert "[Previous workflow task output]" in second_execution["task_prompt"]
    print("PASS: runner per-task document action execution")


def test_runner_legacy_tasks_keep_first_task_only_behavior() -> None:
    """Tasks stored without a document action fall back to the legacy contract."""
    print("Testing runner legacy document action fallback...")
    helpers = load_runner_helpers()
    build_execution_workflow = helpers["_build_workflow_task_execution_workflow"]
    workflow = {"document_action": build_document_action("analyze", document_ids=["legacy-doc"])}

    first_execution = build_execution_workflow(
        workflow,
        {"id": "one", "name": "One", "order": 1, "instructions": "First."},
        include_document_action=True,
    )
    second_execution = build_execution_workflow(
        workflow,
        {"id": "two", "name": "Two", "order": 2, "instructions": "Second."},
        include_document_action=False,
    )

    assert first_execution["document_action"]["document_ids"] == ["legacy-doc"]
    assert second_execution["document_action"] == {"type": "none"}
    assert second_execution["analyze"] == {"enabled": False}
    print("PASS: runner legacy document action fallback")


def test_file_sync_changed_documents_reach_task_actions() -> None:
    """File Sync changed documents update task-level analyze actions."""
    print("Testing File Sync changed document propagation...")
    helpers = load_runner_helpers()
    apply_file_sync = helpers["_apply_file_sync_context_to_workflow"]

    workflow = {
        "task_prompt": "Run the workflow.",
        "file_sync": {
            "use_changed_documents": True,
            "sources": [{"scope_type": "group", "scope_id": "group-1"}],
        },
        "document_action": build_document_action("analyze"),
        "tasks": [
            {"id": "one", "document_action": build_document_action("analyze")},
            {"id": "two", "document_action": build_document_action("none")},
        ],
    }

    prepared = apply_file_sync(
        workflow,
        {"enabled": True, "changed_document_ids": ["changed-1", "changed-2"]},
    )

    assert prepared["document_action"]["document_ids"] == ["changed-1", "changed-2"]
    assert prepared["tasks"][0]["document_action"]["document_ids"] == ["changed-1", "changed-2"]
    assert prepared["tasks"][0]["document_action"]["active_group_ids"] == ["group-1"]
    assert prepared["tasks"][1]["document_action"]["type"] == "none"

    no_changes = apply_file_sync(workflow, {"enabled": True, "changed_document_ids": []})
    assert no_changes["document_action"] == {"type": "none"}
    assert no_changes["tasks"][0]["document_action"] == {"type": "none"}
    print("PASS: File Sync changed document propagation")


def test_version_contract() -> None:
    """The fix ships at or after its implementation version."""
    print("Testing version contract...")
    assert_app_version_at_least(MINIMUM_VERSION)
    print("PASS: version contract")


def run_tests() -> bool:
    tests = [
        test_document_picker_loads_on_action_change,
        test_refresh_documents_button_reloads_picker,
        test_task_document_action_frontend_model,
        test_task_normalization_persists_document_actions,
        test_legacy_workflow_action_inherits_first_task_only,
        test_invalid_task_document_action_reports_task_number,
        test_group_task_document_actions_stay_in_group_scope,
        test_runner_executes_each_task_with_its_own_action,
        test_runner_legacy_tasks_keep_first_task_only_behavior,
        test_file_sync_changed_documents_reach_task_actions,
        test_version_contract,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)
