# test_tabular_durable_artifact_lifecycle_recovery.py
#!/usr/bin/env python3
"""
Functional tests for durable tabular artifact completion and failure preservation.
Version: 0.250.199
Implemented in: 0.250.199

This test ensures hierarchical analysis records its uploaded Markdown artifact
before publication validation, only marks the run completed after the artifact
set commits, repairs empty legacy durable contracts from task semantics, and
preserves the original combined-generation exception when no batch succeeds.
"""

import ast
import asyncio
import logging
import sys
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT_DIR / "application" / "single_app"
EXPORT_FILE = APP_ROOT / "functions_tabular_generated_exports.py"
IMPLEMENTED_VERSION = "0.250.199"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from functions_analysis_deliverables import build_analysis_deliverable_contract  # noqa: E402
from test_tabular_phase5_artifact_set_lifecycle import (  # noqa: E402
    build_artifact,
    load_artifact_set_helpers,
)


def _extract_function(function_name):
    source = EXPORT_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_FILE))
    function_node = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    )
    return ast.Module(body=[function_node], type_ignores=[])


def _load_complete_analysis_run(artifact_set_lifecycle="completed"):
    calls = []

    def publish_analysis_artifact(run, final_summary):
        calls.append("upload")
        return run, {"id": "md-message", "file_name": "analysis.md"}, final_summary, "analysis.md"

    def build_artifact_metadata(uploaded_message, file_name, output_format, **kwargs):
        return {
            "artifact_message_id": uploaded_message["id"],
            "file_name": file_name,
            "output_format": output_format,
            "capability": "tabular",
            "preview_text": kwargs.get("preview_text", ""),
            "suppress_assistant_text": kwargs.get("suppress_assistant_text", False),
        }

    def set_member_state(run, member_id, artifact=None, **kwargs):
        calls.append("stage")
        assert run["status"] == "running"
        assert member_id == "analysis"
        assert artifact["artifact_message_id"] == "md-message"

    def publish_members(run, member_ids):
        calls.append("publish")
        assert run["status"] == "running"
        assert run["analysis_phase"] == "publishing"
        assert run["analysis_artifact"]["artifact_message_id"] == "md-message"
        assert member_ids == ["analysis"]
        return {"lifecycle_state": artifact_set_lifecycle}

    def replace_claimed_run(run):
        calls.append("persist")
        assert run["status"] == "completed"
        assert run["analysis_phase"] == "completed"
        return dict(run)

    namespace = {
        "logging": logging,
        "log_event": lambda *args, **kwargs: None,
        "_publish_analysis_artifact": publish_analysis_artifact,
        "_build_analysis_summary_markdown": lambda run, summary: "# Analysis",
        "_build_artifact_metadata": build_artifact_metadata,
        "_set_artifact_set_member_state": set_member_state,
        "_get_analysis_artifact_member_id": lambda run: "analysis",
        "_now_iso": lambda: "2026-08-14T17:00:00+00:00",
        "_safe_int": lambda value, default=0, minimum=None: int(value if value is not None else default),
        "_publish_artifact_set_members": publish_members,
        "_build_generation_progress_contract_fields": lambda run, batches, rows: {},
        "_build_tabular_generation_performance_summary": lambda run, completed_at=None: {},
        "_replace_claimed_run": replace_claimed_run,
        "TABULAR_EXPORT_STATUS_COMPLETED": "completed",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_STAGED": "staged",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_COMPLETED": "completed",
    }
    module = _extract_function("_complete_analysis_run")
    exec(compile(module, str(EXPORT_FILE), "exec"), namespace)
    return namespace["_complete_analysis_run"], calls


def test_hierarchical_completion_publishes_before_marking_run_completed():
    """The uploaded Markdown member must validate and commit before terminal status."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    complete_analysis_run, calls = _load_complete_analysis_run()
    run = {
        "id": "run-1",
        "status": "running",
        "row_count": 200,
        "batch_count": 1,
    }

    completed_run = complete_analysis_run(run, {"summary": "Done", "row_count": 200})

    assert calls == ["upload", "stage", "publish", "persist"]
    assert completed_run["status"] == "completed"
    assert completed_run["analysis_artifact"]["artifact_message_id"] == "md-message"


def test_hierarchical_completion_fails_before_terminal_status_when_publication_is_invalid():
    """An invalid artifact set must not create a completed run with no downloadable file."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    complete_analysis_run, calls = _load_complete_analysis_run("rollback_required")
    run = {
        "id": "run-2",
        "status": "running",
        "row_count": 200,
        "batch_count": 1,
    }

    try:
        complete_analysis_run(run, {"summary": "Done", "row_count": 200})
    except ValueError as exc:
        assert str(exc) == "Generated analysis artifact failed publication validation"
    else:
        raise AssertionError("Invalid publication must raise before terminal completion")

    assert calls == ["upload", "stage", "publish"]
    assert run["status"] == "running"


def test_empty_search_hierarchical_contract_defaults_to_required_markdown():
    """Legacy Search runs with an empty contract must not reject their Markdown as extra."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = load_artifact_set_helpers()
    empty_contract = build_analysis_deliverable_contract(
        action_mode="search",
        requested_artifacts=[],
    ).to_dict()
    run = {
        "id": "run-search-md",
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "task_type": "hierarchical_analysis",
        "status": "running",
        "output_format": "md",
        "source_file_name": "financial_review.csv",
        "row_count": 200,
        "tabular_planner_metadata": {"deliverable_contract": empty_contract},
        "final_artifact": build_artifact("md-message", "financial_review.md", "md"),
    }

    manifest = helpers["_publish_artifact_set_members"](run, ["analysis"])

    assert manifest["lifecycle_state"] == "completed", manifest
    assert manifest["validation_report"]["valid"] is True
    assert manifest["validation_report"]["reason_codes"] == []


def _load_process_combined_run(original_error, checkpoint_calls):
    async def generate_combined_results(*args, **kwargs):
        return [], original_error

    def checkpoint_results(run, generated_results):
        checkpoint_calls.append(list(generated_results))
        raise AssertionError("Empty generated results must not reach schema checkpointing")

    namespace = {
        "asyncio": asyncio,
        "logging": logging,
        "log_event": lambda *args, **kwargs: None,
        "_safe_int": lambda value, default=0, minimum=None: int(value if value is not None else default),
        "_raise_if_tabular_export_canceled": lambda run: None,
        "_build_combined_batch_window": lambda *args, **kwargs: (
            {},
            [{"batch_number": 1, "rows": [{"Item_ID": "FRI-001"}]}],
        ),
        "_generate_combined_chunk_result_window": generate_combined_results,
        "_checkpoint_combined_batch_results": checkpoint_results,
        "_get_tabular_run_transformation_spec": lambda run: None,
        "_load_ready_active_tabular_generation_plan": lambda run: None,
        "_get_tabular_semantic_validation_options": lambda run: {},
        "_advance_analysis_map_progress_for_window": lambda *args, **kwargs: args[0:1] + (0, 0),
        "_log_progress_if_due": lambda run, last_logged_at: last_logged_at,
        "_publish_combined_structured_export_phase": lambda run: run,
        "_run_analysis_reduce_tree": lambda *args, **kwargs: {},
        "_complete_combined_analysis_run": lambda run, summary: run,
    }
    module = _extract_function("_process_combined_run")
    exec(compile(module, str(EXPORT_FILE), "exec"), namespace)
    return namespace["_process_combined_run"]


def test_combined_zero_success_window_preserves_original_generation_error():
    """A provider failure must not be replaced by an empty-schema checkpoint error."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    class DeploymentNotFoundError(Exception):
        pass

    original_error = DeploymentNotFoundError("selected model deployment was not found")
    checkpoint_calls = []
    process_combined_run = _load_process_combined_run(original_error, checkpoint_calls)
    run = {
        "id": "run-combined",
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "status": "running",
        "batch_count": 1,
        "completed_batches": 0,
        "processed_rows": 0,
        "output_schema": None,
    }

    try:
        process_combined_run(
            run,
            object(),
            [],
            retry_attempts=1,
            batch_concurrency=1,
            batch_timeout_seconds=30,
            settings={},
        )
    except DeploymentNotFoundError as exc:
        assert exc is original_error
    else:
        raise AssertionError("The original generation error must be re-raised")

    assert checkpoint_calls == []


def test_completed_legacy_run_reconciles_uploaded_markdown_publication():
    """Status reconciliation must commit an uploaded legacy artifact exactly once."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    source = EXPORT_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_FILE))
    function_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_reconcile_completed_tabular_artifact_set"
    )
    published_member_ids = []
    persisted_runs = []
    logged_events = []

    def publish_members(run, member_ids):
        published_member_ids.extend(member_ids)
        manifest = {
            "lifecycle_state": "completed",
            "members": [{"member_id": "analysis", "artifact_message_id": "md-message"}],
        }
        run["artifact_set_manifest"] = manifest
        return manifest

    def replace_run(run):
        persisted_runs.append(dict(run))
        return dict(run)

    namespace = {
        "logging": logging,
        "log_event": lambda message, extra=None, level=logging.INFO: logged_events.append((message, extra)),
        "_build_or_update_artifact_set_manifest": lambda run: {
            "lifecycle_state": "rollback_required",
            "members": [{"member_id": "analysis", "artifact_message_id": "md-message"}],
        },
        "_publish_artifact_set_members": publish_members,
        "_replace_run": replace_run,
        "_read_run": lambda user_id, run_id: None,
        "TABULAR_EXPORT_STATUS_COMPLETED": "completed",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_COMPLETED": "completed",
    }
    exec(
        compile(ast.Module(body=[function_node], type_ignores=[]), str(EXPORT_FILE), "exec"),
        namespace,
    )
    run = {
        "id": "run-legacy",
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "status": "completed",
        "artifact_set_manifest": {"lifecycle_state": "rollback_required"},
    }

    repaired_run = namespace["_reconcile_completed_tabular_artifact_set"](run)

    assert published_member_ids == ["analysis"]
    assert len(persisted_runs) == 1
    assert repaired_run["artifact_set_manifest"]["lifecycle_state"] == "completed"
    assert logged_events[0][0] == "[TABULAR_GENERATED_OUTPUT] Reconciled completed artifact-set publication"


if __name__ == "__main__":
    tests = [
        test_hierarchical_completion_publishes_before_marking_run_completed,
        test_hierarchical_completion_fails_before_terminal_status_when_publication_is_invalid,
        test_empty_search_hierarchical_contract_defaults_to_required_markdown,
        test_combined_zero_success_window_preserves_original_generation_error,
        test_completed_legacy_run_reconciles_uploaded_markdown_publication,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
        except Exception as exc:
            failures += 1
            print(f"FAIL: {test.__name__}: {exc}")

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(0 if failures == 0 else 1)
