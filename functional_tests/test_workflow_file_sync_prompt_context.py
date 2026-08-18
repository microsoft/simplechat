#!/usr/bin/env python3
# test_workflow_file_sync_prompt_context.py
"""
Functional test for File Sync prompt context reaching the first workflow task.
Version: 0.250.226
Implemented in: 0.250.226

This test ensures that:
  1. _apply_file_sync_context_to_workflow() publishes file_sync_prompt_context, the producer
     that was lost in a merge and left the consumer reading a key nothing ever wrote.
  2. The first task's prompt carries the File Sync summary and the changed-document list, and
     later tasks do not.
  3. The legacy no-tasks path still carries the context on task_prompt.
  4. Document search queries use the task's own instructions, never the injected File Sync
     context or the previous task's output.
  5. The context block is bounded with a truncation notice.

Refs microsoft/simplechat#1285
"""

import ast
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
MINIMUM_VERSION = "0.250.226"
FILE_SYNC_CONTEXT_MAX_CHARS = 8000


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


def load_runner_helpers() -> dict:
    namespace = {
        "DOCUMENT_ACTION_TYPE_NONE": "none",
        "DOCUMENT_ACTION_TYPE_ANALYZE": "analyze",
        "WORKFLOW_TASK_CONTEXT_MAX_CHARS": 12000,
        "WORKFLOW_FILE_SYNC_CONTEXT_MAX_CHARS": FILE_SYNC_CONTEXT_MAX_CHARS,
        "build_analyze_config": lambda action: {"enabled": (action or {}).get("type") == "analyze"},
        "_get_document_action_config": lambda source: dict(
            (source or {}).get("document_action") or {"type": "none"}
        ),
        "_get_workflow_file_sync_config": lambda workflow: (workflow or {}).get("file_sync") or {},
    }
    return load_functions(
        RUNNER_FILE,
        {
            "_truncate_workflow_task_context",
            "_truncate_workflow_file_sync_context",
            "_format_workflow_file_sync_context",
            "_apply_file_sync_changed_documents_to_action",
            "_apply_file_sync_context_to_workflow",
            "_resolve_workflow_task_document_action",
            "_build_workflow_task_execution_workflow",
        },
        namespace,
    )


def build_file_sync_result(changed_documents=None, enabled=True):
    changed_documents = changed_documents if changed_documents is not None else [
        {
            "document_id": "doc-1",
            "relative_path": "contracts/acme-v3.pdf",
            "action": "updated",
            "source_name": "Contracts Share",
        },
        {
            "document_id": "doc-2",
            "relative_path": "contracts/beta-v1.pdf",
            "action": "created",
            "source_name": "Contracts Share",
        },
    ]
    return {
        "enabled": enabled,
        "counts": {
            "scanned": 12,
            "created": 1,
            "updated": 1,
            "unchanged": 10,
            "skipped": 0,
            "failed": 0,
        },
        "changed_documents": changed_documents,
        "changed_document_ids": [document["document_id"] for document in changed_documents],
    }


def build_workflow(tasks=None, document_action=None, use_changed_documents=False):
    workflow = {
        "id": "workflow-1",
        "name": "Sync watcher",
        "user_id": "user-1",
        "runner_type": "model",
        "task_prompt": "Summarize what changed.",
        "document_action": document_action or {"type": "none"},
        "file_sync": {
            "use_changed_documents": use_changed_documents,
            "sources": [{"scope_type": "group", "scope_id": "group-1"}],
        },
    }
    if tasks is not None:
        workflow["tasks"] = tasks
    return workflow


def test_producer_publishes_file_sync_prompt_context() -> None:
    """The producer lost in the merge must publish the key the task builder reads."""
    print("Testing File Sync prompt context producer...")
    helpers = load_runner_helpers()
    apply_context = helpers["_apply_file_sync_context_to_workflow"]

    prepared = apply_context(build_workflow(), build_file_sync_result())

    assert "file_sync_prompt_context" in prepared, (
        "_apply_file_sync_context_to_workflow must publish file_sync_prompt_context; "
        "_build_workflow_task_execution_workflow reads it and nothing else writes it."
    )
    context = prepared["file_sync_prompt_context"]
    assert "File Sync context for this workflow run" in context
    assert "contracts/acme-v3.pdf" in context
    assert "contracts/beta-v1.pdf" in context
    assert "Scanned: 12" in context

    # Disabled File Sync must not attach anything.
    untouched = apply_context(build_workflow(), {"enabled": False})
    assert "file_sync_prompt_context" not in untouched
    print("PASS: File Sync prompt context producer")


def test_first_task_receives_context_and_later_tasks_do_not() -> None:
    """Only the first task gets the File Sync block; later tasks inherit it via task one's reply."""
    print("Testing first-task-only File Sync injection...")
    helpers = load_runner_helpers()
    apply_context = helpers["_apply_file_sync_context_to_workflow"]
    build_task_workflow = helpers["_build_workflow_task_execution_workflow"]

    tasks = [
        {"id": "one", "name": "One", "order": 1, "instructions": "List what changed."},
        {"id": "two", "name": "Two", "order": 2, "instructions": "Draft the summary."},
    ]
    prepared = apply_context(build_workflow(tasks=tasks), build_file_sync_result())

    first = build_task_workflow(prepared, tasks[0], include_file_sync_context=True)
    second = build_task_workflow(
        prepared,
        tasks[1],
        previous_reply="Task one output",
        include_file_sync_context=False,
    )

    assert "[Workflow input context]" in first["task_prompt"]
    assert "contracts/acme-v3.pdf" in first["task_prompt"]
    assert first["task_prompt"].startswith("List what changed.")

    assert "[Workflow input context]" not in second["task_prompt"]
    assert "contracts/acme-v3.pdf" not in second["task_prompt"]
    assert "[Previous workflow task output]" in second["task_prompt"]

    runner_source = read_text(RUNNER_FILE)
    assert "include_file_sync_context=task_index == 0," in runner_source, (
        "The sequence must gate File Sync context on the first task explicitly."
    )
    assert "if include_document_action and file_sync_context:" not in runner_source, (
        "File Sync context must no longer piggyback on the document action fallback flag."
    )
    print("PASS: first-task-only File Sync injection")


def test_search_query_ignores_injected_context() -> None:
    """Document search must query the task's instructions, not the injected context."""
    print("Testing search query isolation...")
    helpers = load_runner_helpers()
    apply_context = helpers["_apply_file_sync_context_to_workflow"]
    build_task_workflow = helpers["_build_workflow_task_execution_workflow"]

    tasks = [
        {"id": "one", "name": "One", "order": 1, "instructions": "Find the renewal clause."},
        {"id": "two", "name": "Two", "order": 2, "instructions": "Find the termination clause."},
    ]
    prepared = apply_context(build_workflow(tasks=tasks), build_file_sync_result())

    first = build_task_workflow(prepared, tasks[0], include_file_sync_context=True)
    second = build_task_workflow(
        prepared,
        tasks[1],
        previous_reply="A very long prior answer that would otherwise dilute the query.",
        include_file_sync_context=False,
    )

    assert first["task_search_query"] == "Find the renewal clause."
    assert "contracts/acme-v3.pdf" not in first["task_search_query"]
    assert "[Workflow input context]" not in first["task_search_query"]

    assert second["task_search_query"] == "Find the termination clause."
    assert "[Previous workflow task output]" not in second["task_search_query"]
    assert "dilute the query" not in second["task_search_query"]

    # The legacy no-tasks path keeps an un-augmented query source too.
    legacy = apply_context(build_workflow(), build_file_sync_result())
    assert legacy["task_search_query"] == "Summarize what changed."
    assert "contracts/acme-v3.pdf" in legacy["task_prompt"]

    runner_source = read_text(RUNNER_FILE)
    assert (
        "query = str(workflow.get('task_search_query') or workflow.get('task_prompt') or '').strip()"
        in runner_source
    ), "The workflow search query must prefer task_search_query and fall back to task_prompt."
    print("PASS: search query isolation")


def test_legacy_no_task_workflows_keep_context_in_task_prompt() -> None:
    """Workflows without tasks still dispatch with the context appended to task_prompt."""
    print("Testing legacy no-tasks context path...")
    helpers = load_runner_helpers()
    apply_context = helpers["_apply_file_sync_context_to_workflow"]

    prepared = apply_context(build_workflow(), build_file_sync_result())

    assert prepared["task_prompt"].startswith("Summarize what changed.")
    assert "File Sync context for this workflow run" in prepared["task_prompt"]
    assert "contracts/beta-v1.pdf" in prepared["task_prompt"]
    print("PASS: legacy no-tasks context path")


def test_no_changes_still_reaches_the_first_task() -> None:
    """A run with nothing changed must still tell the first task that nothing changed."""
    print("Testing no-changes File Sync context...")
    helpers = load_runner_helpers()
    apply_context = helpers["_apply_file_sync_context_to_workflow"]
    build_task_workflow = helpers["_build_workflow_task_execution_workflow"]

    tasks = [{"id": "one", "name": "One", "order": 1, "instructions": "Report on the sync."}]
    prepared = apply_context(
        build_workflow(tasks=tasks),
        build_file_sync_result(changed_documents=[]),
    )
    first = build_task_workflow(prepared, tasks[0], include_file_sync_context=True)

    assert "No new or changed synced documents were detected." in first["task_prompt"]
    assert "[Workflow input context]" in first["task_prompt"]
    print("PASS: no-changes File Sync context")


def test_context_is_bounded_with_a_truncation_notice() -> None:
    """A very large sync must not let the context dominate the prompt."""
    print("Testing File Sync context truncation...")
    helpers = load_runner_helpers()
    format_context = helpers["_format_workflow_file_sync_context"]
    truncate_context = helpers["_truncate_workflow_file_sync_context"]

    short_value = "a" * 100
    assert truncate_context(short_value) == short_value
    assert "[File Sync context truncated]" not in truncate_context(short_value)

    long_value = "b" * (FILE_SYNC_CONTEXT_MAX_CHARS + 500)
    truncated = truncate_context(long_value)
    assert "[File Sync context truncated]" in truncated
    assert len(truncated) < len(long_value)

    # A realistic oversized sync: 50 documents with very long relative paths.
    oversized_documents = [
        {
            "document_id": f"doc-{index}",
            "relative_path": f"{'nested/' * 30}document-{index}.pdf",
            "action": "updated",
            "source_name": "Deep Share",
        }
        for index in range(50)
    ]
    context = format_context(build_file_sync_result(changed_documents=oversized_documents))
    assert "[File Sync context truncated]" in context
    assert len(context) <= FILE_SYNC_CONTEXT_MAX_CHARS + len("\n\n[File Sync context truncated]\n\n")
    print("PASS: File Sync context truncation")


def test_use_changed_documents_still_targets_analyze_tasks() -> None:
    """Restoring the prompt context must not disturb the changed-document targeting."""
    print("Testing changed-document targeting is unaffected...")
    helpers = load_runner_helpers()
    apply_context = helpers["_apply_file_sync_context_to_workflow"]

    tasks = [
        {
            "id": "one",
            "name": "One",
            "order": 1,
            "instructions": "Analyze the changes.",
            "document_action": {"type": "analyze", "document_ids": ["stale-doc"]},
        },
    ]
    prepared = apply_context(
        build_workflow(
            tasks=tasks,
            document_action={"type": "analyze", "document_ids": ["stale-doc"]},
            use_changed_documents=True,
        ),
        build_file_sync_result(),
    )

    assert prepared["document_action"]["document_ids"] == ["doc-1", "doc-2"]
    assert prepared["tasks"][0]["document_action"]["document_ids"] == ["doc-1", "doc-2"]
    assert prepared["tasks"][0]["document_action"]["active_group_ids"] == ["group-1"]
    assert "file_sync_prompt_context" in prepared
    print("PASS: changed-document targeting is unaffected")


def test_version_contract() -> None:
    """The fix ships at or after its implementation version."""
    print("Testing version contract...")
    assert_app_version_at_least(MINIMUM_VERSION)
    print("PASS: version contract")


def run_tests() -> bool:
    tests = [
        test_producer_publishes_file_sync_prompt_context,
        test_first_task_receives_context_and_later_tasks_do_not,
        test_search_query_ignores_injected_context,
        test_legacy_no_task_workflows_keep_context_in_task_prompt,
        test_no_changes_still_reaches_the_first_task,
        test_context_is_bounded_with_a_truncation_notice,
        test_use_changed_documents_still_targets_analyze_tasks,
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
