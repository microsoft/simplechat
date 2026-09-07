#!/usr/bin/env python3
# test_tabular_combined_artifact_set_download_visibility.py
"""
Functional test for the combined Analyze+CSV artifact-set download visibility.
Version: 0.250.191
Implemented in: 0.250.191 (root cause fixed); diagnostics added in 0.250.190

A customer reported that a combined (Analyze) tabular run reached "Complete"
100% progress in the chat UI but never showed the Download/View/Add-to-Workspace
buttons. Production logs captured after shipping the 0.250.190 diagnostics
pinpointed the root cause: `_normalize_tabular_run_planner_metadata()` (which
sanitizes shared planner metadata before persisting it onto a durable run)
rebuilt the `deliverable_contract` dict from an explicit field whitelist that
omitted `requested_artifacts` entirely. Every run that went through this
sanitizer therefore persisted a `deliverable_contract` with zero expected
artifacts, so `validate_analysis_artifact_set()` always rejected both the
published Markdown analysis artifact and the CSV sibling as `extra_artifact`,
permanently freezing `artifact_set.lifecycle_state` below `"completed"` (the
frontend never shows Download/View controls unless it is exactly
`"completed"`, and it also stops polling once `run.status == "completed"`, so
the freeze had no way to self-heal).

This test:
1. Reproduces the real (unmocked) Analyze+CSV deliverable contract used in
   production (no upfront output hints, so `public_output_schema == []`),
   routes it through the real `_normalize_tabular_run_planner_metadata()`
   sanitizer exactly like `queue_tabular_generated_output_run()` does, and
   asserts `requested_artifacts` survives sanitization intact.
2. Drives the actual `_complete_combined_analysis_run`-style dynamic
   `published_member_ids` resolution (`artifact.get('artifact_id') or
   artifact.get('member_id')`) through the real `_publish_artifact_set_members`
   function using the *sanitized* metadata, asserting both the Markdown
   primary artifact and the CSV sibling end up published and visible.
3. Verifies the diagnostic log_events added in 0.250.190 fire with the
   expected payloads in both the healthy and stuck cases.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from functions_tabular_orchestration import orchestrate_tabular_request  # noqa: E402
from test_support.analyze_deliverable_contract_fixture import (  # noqa: E402
    FINANCIAL_REVIEW_PROMPT,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_tabular_phase5_artifact_set_lifecycle import (  # noqa: E402
    build_artifact,
    load_artifact_set_helpers,
)

IMPLEMENTED_VERSION = "0.250.191"


def _build_context():
    return {
        "document_id": "financial-review-doc",
        "file_name": "financial_review.csv",
        "source_hint": "workspace",
        "source_version": "etag-financial-review-v1",
        "storage_locator": {
            "container": "user-documents",
            "blob_path": "user-1/financial_review.csv",
        },
    }


def _capture_real_planner_metadata():
    """Return the real, unsanitized planner_metadata dict a combined
    Analyze+CSV request produces, exactly as queue_tabular_generated_output_run
    receives it before persisting."""
    captured = {}

    def durable_callback(plan, **execution_context):
        captured["plan"] = plan
        return {
            "background_export": True,
            "export_run_id": "run-analyze",
            "status": "queued",
            "task_type": plan["durable_task_type"],
            "output_format": "csv",
        }

    result = orchestrate_tabular_request(
        f"{FINANCIAL_REVIEW_PROMPT}\nDownload the result as CSV.",
        [_build_context()],
        action_mode="analyze",
        caller="analyze",
        settings={
            "enable_tabular_analyze_durable_preflight": True,
            "tabular_request_planner_mode": "active",
            "tabular_analyze_parity_rollout_percent": 100,
            "tabular_analyze_parity_rollout_state": "active",
        },
        planner_mode="active",
        durable_execution_callback=durable_callback,
        user_id="user-1",
        conversation_id="conversation-1",
        gpt_model="gpt-plan",
    )
    assert result["execution_state"] == "queued", result
    return captured["plan"]


def test_planner_metadata_sanitization_preserves_requested_artifacts():
    """Regression guard for the root cause: sanitizing planner metadata for
    persistence must not drop the deliverable contract's requested_artifacts,
    or artifact-set publication validation will reject every real artifact
    as 'extra_artifact' forever."""
    print("Testing planner metadata sanitization preserves requested_artifacts...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = load_artifact_set_helpers()
    raw_planner_metadata = _capture_real_planner_metadata()
    raw_requested_artifacts = raw_planner_metadata["deliverable_contract"]["requested_artifacts"]
    assert raw_requested_artifacts, "Precondition: the real contract must have requested artifacts"

    sanitized = helpers["_normalize_tabular_run_planner_metadata"](raw_planner_metadata)
    sanitized_requested_artifacts = sanitized.get("deliverable_contract", {}).get("requested_artifacts")

    assert sanitized_requested_artifacts, (
        "_normalize_tabular_run_planner_metadata dropped requested_artifacts "
        f"during sanitization: {sanitized.get('deliverable_contract')}"
    )
    assert [a["artifact_id"] for a in sanitized_requested_artifacts] == [
        a["artifact_id"] for a in raw_requested_artifacts
    ]
    assert [a["role"] for a in sanitized_requested_artifacts] == [
        a["role"] for a in raw_requested_artifacts
    ]
    assert [a["format"] for a in sanitized_requested_artifacts] == [
        a["format"] for a in raw_requested_artifacts
    ]


def test_completed_combined_run_publishes_both_artifacts_for_download():
    """A completed combined run using the real Analyze+CSV contract (no
    upfront output hints), persisted through the real sanitizer exactly like
    production, must resolve both the Markdown analysis artifact and the CSV
    sibling via the same dynamic member-id lookup the real
    _complete_combined_analysis_run uses, ending with both visible for
    download."""
    print("Testing completed combined run publishes both artifacts for download...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = load_artifact_set_helpers()
    raw_planner_metadata = _capture_real_planner_metadata()
    assert raw_planner_metadata["deliverable_contract"].get("public_output_schema") == [], (
        "Precondition: the financial-review prompt produces no upfront output schema"
    )
    sanitized_planner_metadata = helpers["_normalize_tabular_run_planner_metadata"](raw_planner_metadata)

    run = {
        "id": "run-real-1",
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "task_type": "combined",
        "status": "running",
        "output_format": "csv",
        "source_file_name": "financial_review.csv",
        "row_count": 200,
        "processed_rows": 200,
        "post_run_summary": "Analysis completed.",
        "post_run_export_summary": "CSV export completed.",
        "tabular_planner_metadata": sanitized_planner_metadata,
    }

    # Mirror _publish_structured_export_artifact tagging the structured
    # artifact with the descriptor's real member_id/artifact_id.
    descriptors = helpers["_get_artifact_descriptors_for_run"](run)
    structured_descriptor = next(d for d in descriptors if d["role"] == "requested_output")
    structured_artifact = build_artifact("csv-message", "financial_review.csv", "csv")
    structured_artifact["artifact_id"] = structured_descriptor["member_id"]
    structured_artifact["member_id"] = structured_descriptor["member_id"]
    analysis_artifact = build_artifact("md-message", "financial_review.md", "md")

    run["structured_export_artifacts"] = [structured_artifact]
    run["structured_export_artifact"] = structured_artifact
    run["analysis_artifact"] = analysis_artifact
    run["status"] = "completed"

    # Mirror _complete_combined_analysis_run's exact published_member_ids
    # construction: dynamic resolution, not hardcoded literals.
    published_member_ids = [
        helpers["_get_analysis_artifact_member_id"](run),
        *[
            artifact.get("artifact_id") or artifact.get("member_id")
            for artifact in [structured_artifact]
        ],
    ]

    manifest = helpers["_publish_artifact_set_members"](run, published_member_ids)
    assert manifest["lifecycle_state"] == "completed", manifest
    assert manifest["validation_state"] == "validated", manifest
    assert manifest["validation_report"]["valid"] is True

    public_artifacts = helpers["_build_public_generated_artifacts_from_manifest"](run, manifest)
    assert [artifact["artifact_id"] for artifact in public_artifacts] == ["analysis", "requested-csv"]
    assert [artifact["output_format"] for artifact in public_artifacts] == ["md", "csv"]

    validation_logs = [
        event for event in helpers["logged_events"]
        if event["message"] == "[TABULAR_GENERATED_OUTPUT] Artifact set publication validation"
    ]
    assert len(validation_logs) == 1
    assert validation_logs[0]["extra"]["artifact_set_valid"] is True
    assert validation_logs[0]["extra"]["reason_codes"] == []

    stuck_logs = [
        event for event in helpers["logged_events"]
        if event["message"] == "[TABULAR_GENERATED_OUTPUT] Artifact set stuck below completed lifecycle on a completed run"
    ]
    assert stuck_logs == [], "A healthy completed run must not emit the stuck-lifecycle diagnostic"


def test_stuck_artifact_set_emits_diagnostic_log_on_every_read():
    """When a completed run's artifact set is invalid/rollback_required, the
    manifest rebuild must emit a diagnostic log carrying the persisted
    validation_report and per-member state, instead of failing silently
    forever."""
    print("Testing stuck artifact-set lifecycle emits a diagnostic log...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = load_artifact_set_helpers()
    raw_planner_metadata = _capture_real_planner_metadata()
    sanitized_planner_metadata = helpers["_normalize_tabular_run_planner_metadata"](raw_planner_metadata)
    run = {
        "id": "run-stuck-1",
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "task_type": "combined",
        "status": "completed",
        "output_format": "csv",
        "source_file_name": "financial_review.csv",
        "row_count": 200,
        "processed_rows": 200,
        "tabular_planner_metadata": sanitized_planner_metadata,
    }
    # Only the structured artifact is present; the required Markdown primary
    # artifact never got attached, so publication must fail closed.
    run["structured_export_artifact"] = build_artifact("csv-message", "financial_review.csv", "csv")

    manifest = helpers["_publish_artifact_set_members"](run, ["requested-csv"])
    assert manifest["lifecycle_state"] == "rollback_required", manifest

    # Re-read the manifest exactly like a status poll would; this must
    # re-emit the stuck-lifecycle diagnostic every time it is observed.
    helpers["logged_events"].clear()
    rebuilt_manifest = helpers["_build_or_update_artifact_set_manifest"](run)
    assert rebuilt_manifest["lifecycle_state"] == "rollback_required"

    stuck_logs = [
        event for event in helpers["logged_events"]
        if event["message"] == "[TABULAR_GENERATED_OUTPUT] Artifact set stuck below completed lifecycle on a completed run"
    ]
    assert len(stuck_logs) == 1
    assert stuck_logs[0]["extra"]["run_id"] == "run-stuck-1"
    assert stuck_logs[0]["extra"]["persisted_lifecycle_state"] == "rollback_required"
    assert stuck_logs[0]["extra"]["validation_state"] == "invalid"


if __name__ == "__main__":
    tests = [
        test_planner_metadata_sanitization_preserves_requested_artifacts,
        test_completed_combined_run_publishes_both_artifacts_for_download,
        test_stuck_artifact_set_emits_diagnostic_log_on_every_read,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
            print(f"PASS {test.__name__}")
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)
    passed_count = sum(1 for result in results if result)
    print(f"\nResults: {passed_count}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
