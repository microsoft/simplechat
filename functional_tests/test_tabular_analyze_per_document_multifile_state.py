# test_tabular_analyze_per_document_multifile_state.py
"""
Functional test for Phase 6 per-document tabular Analyze state preservation.
Version: 0.250.167
Implemented in: 0.250.162; all-canceled aggregate coverage in 0.250.167

This test ensures recursive per-document Analyze preserves pending tabular
generated-output handoffs and coverage state instead of replacing them with a
generic missing-response message.
"""

import ast
from pathlib import Path
import sys

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
WORKFLOW_RUNNER = APP_ROOT / "functions_workflow_runner.py"
IMPLEMENTED_VERSION = "0.250.162"
sys.path.insert(0, str(APP_ROOT))


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"Expected truthy value for {label}")


def load_per_document_namespace():
    source = WORKFLOW_RUNNER.read_text(encoding="utf-8")
    module_tree = ast.parse(source, filename=str(WORKFLOW_RUNNER))
    function_names = {
        "_resolve_document_action_reply",
        "_merge_token_usage_summaries",
        "_get_per_document_analysis_coverage",
        "_get_per_document_coverage_entries",
        "_get_per_document_execution_state",
        "_get_per_document_status_label",
        "_get_per_document_fallback_reply",
        "_combine_per_document_analysis_results",
    }
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert_equal({node.name for node in selected_nodes}, function_names, "loaded function set")

    def create_token_usage_aggregate():
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "request_count": 0,
        }

    def finalize_token_usage(token_usage):
        return dict(token_usage or {})

    def get_output_status(output):
        return str((output or {}).get("status") or "").strip().lower()

    def is_nonterminal_output(output):
        return get_output_status(output) in {"queued", "running", "retrying", "finalizing"}

    def deduplicate_artifacts(references, reference_type="citation"):
        if reference_type != "artifact":
            return list(references or [])
        deduplicated = []
        seen_keys = set()
        for reference in list(references or []):
            if not isinstance(reference, dict):
                continue
            dedupe_key = reference.get("artifact_message_id") or reference.get("document_id") or reference.get("export_run_id")
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            deduplicated.append(reference)
        return deduplicated

    namespace = {
        "EVIDENCE_STATUS_CANCELED": "canceled",
        "EVIDENCE_STATUS_COMPLETED": "completed",
        "EVIDENCE_STATUS_FAILED": "failed",
        "EVIDENCE_STATUS_PENDING": "pending",
        "deduplicate_mixed_source_references": deduplicate_artifacts,
        "_create_token_usage_aggregate": create_token_usage_aggregate,
        "_finalize_token_usage": finalize_token_usage,
        "_get_tabular_generated_output_status": get_output_status,
        "_is_nonterminal_tabular_generated_output": is_nonterminal_output,
        "_select_preferred_workflow_alert_targets": lambda alert_targets: list(alert_targets or []),
    }
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(WORKFLOW_RUNNER), "exec"), namespace)
    return namespace


def test_per_document_pending_tabular_state_is_preserved():
    print("Testing per-document pending tabular state preservation...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    namespace = load_per_document_namespace()
    combine_results = namespace["_combine_per_document_analysis_results"]

    pending_output = {
        "export_run_id": "run-table-1",
        "status": "queued",
        "task_type": "combined",
        "output_format": "csv",
    }
    result = combine_results([
        {
            "document_id": "table-1",
            "result": {
                "reply": "The full-source tabular work has been accepted for background processing.",
                "coverage": {
                    "sources": [{
                        "source": "survey.csv",
                        "source_kind": "tabular",
                        "status": "pending",
                        "reason": None,
                    }],
                    "pending_source_count": 1,
                    "progress_meta": {
                        "status": "pending",
                    },
                },
                "generated_tabular_outputs": [pending_output, dict(pending_output)],
                "tabular_execution_contract": "combined",
                "deferred_composition": {
                    "status": "pending",
                    "enabled": True,
                },
            },
        },
        {
            "document_id": "narrative-1",
            "result": {
                "analysis_reply": "Narrative analysis complete.",
                "analysis_coverage": {
                    "documents": [{
                        "document_id": "narrative-1",
                        "document_name": "report.pdf",
                        "status": "completed",
                    }],
                    "processed_windows": 2,
                    "failed_windows": 0,
                },
                "token_usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 5,
                    "total_tokens": 8,
                    "request_count": 1,
                },
            },
        },
    ])

    analysis_result = result["analysis_result"]
    combined_reply = result["reply"]
    coverage = result["analysis_coverage"]

    assert_true("## 1. survey.csv" in combined_reply, "tabular source label")
    assert_true("Status: background analysis in progress" in combined_reply, "pending status label")
    assert_true("No response was generated for this document." not in combined_reply, "pending fallback omission")
    assert_equal(coverage["status_counts"]["pending"], 1, "pending status count")
    assert_equal(coverage["status_counts"]["completed"], 1, "completed status count")
    assert_equal(coverage["progress_meta"]["status"], "pending", "aggregate progress status")
    assert_equal(analysis_result["document_results"][0]["execution_state"], "pending", "child execution state")
    assert_equal(
        analysis_result["document_results"][0]["generated_tabular_outputs"][0]["export_run_id"],
        "run-table-1",
        "child generated output metadata",
    )
    assert_equal(len(result["generated_tabular_outputs"]), 1, "aggregate output dedupe")
    assert_equal(result["generated_tabular_outputs"][0]["export_run_id"], "run-table-1", "aggregate output metadata")
    assert_equal(result["token_usage"]["total_tokens"], 8, "token usage merge")

    print("Per-document pending tabular state checks passed")


def test_all_canceled_per_document_state_is_preserved():
    print("Testing all-canceled per-document state preservation...")
    namespace = load_per_document_namespace()
    combine_results = namespace["_combine_per_document_analysis_results"]
    result = combine_results([
        {
            "document_id": "table-1",
            "result": {
                "coverage": {"progress_meta": {"status": "canceled"}},
                "generated_tabular_outputs": [{"export_run_id": "run-1", "status": "canceled"}],
            },
        },
        {
            "document_id": "table-2",
            "result": {
                "coverage": {"progress_meta": {"status": "cancelled"}},
                "generated_tabular_outputs": [{"export_run_id": "run-2", "status": "cancelled"}],
            },
        },
    ])

    coverage = result["analysis_coverage"]
    assert_equal(coverage["status_counts"]["canceled"], 2, "canceled status count")
    assert_equal(coverage["progress_meta"]["status"], "canceled", "aggregate canceled status")
    assert_equal(coverage["progress_meta"]["phase_label"], "Canceled", "aggregate canceled label")
    assert_true("Status: canceled" in result["reply"], "canceled reply status")
    print("All-canceled per-document state checks passed")


if __name__ == "__main__":
    test_per_document_pending_tabular_state_is_preserved()
    test_all_canceled_per_document_state_is_preserved()
