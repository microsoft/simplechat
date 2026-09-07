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
        "DOCUMENT_ACTION_TYPE_COMPARISON": "comparison",
        "WORKFLOW_TASK_CONTEXT_MAX_CHARS": 12000,
        "re": __import__("re"),
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
            "_get_workflow_active_task",
            "_document_run_item_id",
            "_resolve_workflow_task_document_action",
            "_build_workflow_task_execution_workflow",
            "_apply_file_sync_changed_documents_to_action",
            "_apply_file_sync_context_to_workflow",
        },
        namespace,
    )


def load_resume_helpers():
    return load_functions(
        APP_ROOT / "route_backend_workflows.py",
        {
            "_narrow_analyze_action_to_documents",
            "_force_group_document_action_scope",
            "_build_resume_failed_workflow",
        },
        {
            "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
            "DOCUMENT_ACTION_TYPE_NONE": "none",
            "FILE_SYNC_SCOPE_GROUP": "group",
            "FILE_SYNC_SCOPE_PUBLIC": "public",
            "build_analyze_config": lambda action: {"enabled": (action or {}).get("type") == "analyze"},
            "_normalize_identifier": lambda value: str(value or "").strip(),
        },
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


def test_document_run_items_are_task_scoped() -> None:
    """Two tasks targeting the same document must not overwrite each other's status."""
    print("Testing task-scoped document run item ids...")
    helpers = load_runner_helpers()
    document_run_item_id = helpers["_document_run_item_id"]

    first = document_run_item_id("run-1", "doc-a", task_id="task-1")
    second = document_run_item_id("run-1", "doc-a", task_id="task-2")
    legacy = document_run_item_id("run-1", "doc-a")

    assert first != second, "Per-task document run items must have distinct ids."
    assert legacy == "run-1:document:doc-a", legacy
    assert "task-1" in first and "task-2" in second

    runner_source = read_text(RUNNER_FILE)
    assert "'id': _document_run_item_id(run_id, document_id, task_id=task_id)," in runner_source
    assert "'task_id': task_id or None," in runner_source
    print("PASS: task-scoped document run item ids")


def test_task_document_action_failures_stay_inside_the_retry_loop() -> None:
    """An invalid task document action must fail that task, not abort the whole run."""
    print("Testing task document action failure containment...")
    runner_source = read_text(RUNNER_FILE)

    sequence_start = runner_source.index("def _execute_workflow_task_sequence(")
    sequence_body = runner_source[sequence_start:sequence_start + 6000]
    attempt_loop_index = sequence_body.index("for attempt_index in range(retry_count + 1):")
    build_index = sequence_body.index("prepared_workflow = _build_workflow_task_execution_workflow(")
    try_index = sequence_body.index("try:", attempt_loop_index)

    assert build_index > attempt_loop_index, (
        "The per-task workflow must be built inside the retry loop so document action "
        "normalization errors are retried and recorded per task."
    )
    assert build_index > try_index, "The per-task workflow build must be inside the attempt try block."
    print("PASS: task document action failure containment")


def test_resume_failed_narrows_task_document_actions() -> None:
    """Resuming failed documents must narrow task-level analyze actions, not just the workflow one."""
    print("Testing resume-failed per-task narrowing...")
    helpers = load_resume_helpers()
    build_resume = helpers["_build_resume_failed_workflow"]
    force_group_scope = helpers["_force_group_document_action_scope"]

    workflow = {
        "task_prompt": "Analyze everything.",
        "document_action": build_document_action("analyze", document_ids=["doc-a", "doc-b", "doc-c"]),
        "tasks": [
            {"id": "task-1", "document_action": build_document_action("analyze", document_ids=["doc-a", "doc-b"])},
            {"id": "task-2", "document_action": build_document_action("analyze", document_ids=["doc-c"])},
            {"id": "task-3", "document_action": build_document_action()},
        ],
    }
    failed_items = [
        {"document_id": "doc-b", "task_id": "task-1", "status": "failed"},
        {"document_id": "doc-c", "task_id": "task-2", "status": "failed"},
    ]

    resumed = build_resume(workflow, failed_items)
    assert resumed["document_action"]["document_ids"] == ["doc-b", "doc-c"]
    assert resumed["tasks"][0]["document_action"]["document_ids"] == ["doc-b"]
    assert resumed["tasks"][1]["document_action"]["document_ids"] == ["doc-c"]
    assert resumed["tasks"][2]["document_action"]["type"] == "none"
    assert resumed["file_sync"]["enabled"] is False

    # A task with an analyze action but no failed documents must not re-run its whole set.
    partial = build_resume(workflow, [{"document_id": "doc-b", "task_id": "task-1", "status": "failed"}])
    assert partial["tasks"][0]["document_action"]["document_ids"] == ["doc-b"]
    assert partial["tasks"][1]["document_action"]["type"] == "none"

    # Legacy run items without task attribution fall back to the full failed set.
    legacy = build_resume(workflow, [{"document_id": "doc-b", "status": "failed"}])
    assert legacy["tasks"][0]["document_action"]["document_ids"] == ["doc-b"]
    assert legacy["tasks"][1]["document_action"]["document_ids"] == ["doc-b"]

    # Group resumes stay inside the owning group workspace.
    scoped = force_group_scope(build_document_action("analyze", doc_scope="all", active_public_workspace_id=["p1"]), "group-9")
    assert scoped["doc_scope"] == "group"
    assert scoped["active_group_ids"] == ["group-9"]
    assert scoped["active_public_workspace_id"] == []
    assert force_group_scope(build_document_action(), "group-9")["type"] == "none"
    print("PASS: resume-failed per-task narrowing")


def test_retries_per_window_zero_survives_serialization() -> None:
    """A saved max_retries_per_window of 0 must not be silently rewritten to 1."""
    print("Testing zero retries-per-window preservation...")
    workflow_js = read_text(WORKFLOW_JS_FILE)

    assert "function normalizeWorkflowNumericField(" in workflow_js
    assert 'const rawRetries = normalizeWorkflowNumericField(source.max_retries_per_window, "1");' in workflow_js
    assert 'const rawRetries = normalizeText(source.max_retries_per_window) || "1";' not in workflow_js
    assert 'max_retries_per_window: normalizeWorkflowNumericField(workflowAnalysisRetriesInput?.value, "1"),' in workflow_js
    print("PASS: zero retries-per-window preservation")


def test_picker_load_token_guards_none_actions() -> None:
    """Switching to a task with no document action must invalidate an in-flight load."""
    print("Testing picker load token invalidation...")
    workflow_js = read_text(WORKFLOW_JS_FILE)

    picker_start = workflow_js.index("async function initializeWorkflowDocumentPicker(")
    picker_body = workflow_js[picker_start:picker_start + 1800]
    token_index = picker_body.index("workflowDocumentPickerLoadToken = requestToken;")
    none_return_index = picker_body.index("if (actionType === DOCUMENT_ACTION_NONE) {")

    assert token_index < none_return_index, (
        "The load token must be bumped before the no-document-action early return so a "
        "pending load for a previous task cannot apply its scopes or selection."
    )
    print("PASS: picker load token invalidation")


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
        test_document_run_items_are_task_scoped,
        test_task_document_action_failures_stay_inside_the_retry_loop,
        test_resume_failed_narrows_task_document_actions,
        test_retries_per_window_zero_survives_serialization,
        test_picker_load_token_guards_none_actions,
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
