#!/usr/bin/env python3
# test_tabular_phase5_artifact_set_lifecycle.py
"""
Functional test for Phase 5 tabular artifact-set lifecycle publication.
Version: 0.250.180
Implemented in: 0.250.175; publication commit compatibility updated in 0.250.180

This test ensures durable tabular artifact sets hide staged members until the
whole required set is valid, publish Analyze Markdown as the primary member,
and fail closed when a required sibling is missing.
"""

import ast
import logging
import re
import sys
from collections import Counter
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
EXPORT_MODULE = APP_ROOT / "functions_tabular_generated_exports.py"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from functions_analysis_deliverables import (  # noqa: E402
    ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS,
    ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
    ANALYSIS_DELIVERABLE_MAX_ARTIFACT_ID_LENGTH,
    ANALYSIS_DELIVERABLE_MAX_ARTIFACTS,
    build_analysis_deliverable_contract,
    is_analysis_internal_lineage_field,
    validate_analysis_artifact_set,
)
from functions_tabular_transformations import normalize_tabular_transformation_spec  # noqa: E402


IMPLEMENTED_VERSION = "0.250.180"


def load_artifact_set_helpers():
    source = EXPORT_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_MODULE))
    helper_names = {
        "_safe_int",
        "_normalize_tabular_run_task_type",
        "_normalize_tabular_artifact_lifecycle_state",
        "_normalize_tabular_artifact_format",
        "_normalize_tabular_artifact_role",
        "_normalize_tabular_artifact_member_id",
        "_get_tabular_run_deliverable_contract",
        "_normalize_artifact_descriptor",
        "_default_artifact_descriptors_for_run",
        "_get_artifact_descriptors_for_run",
        "_get_primary_artifact_member_id",
        "_get_structured_artifact_member_id",
        "_get_structured_export_artifact_for_member",
        "_get_analysis_artifact_member_id",
        "_build_artifact_member_idempotency_key",
        "_build_artifact_set_member",
        "_artifact_lifecycle_for_existing_run_artifact",
        "_artifact_set_lifecycle_for_run",
        "_merge_artifact_metadata_into_member",
        "_build_or_update_artifact_set_manifest",
        "_set_artifact_set_member_state",
        "_publish_artifact_set_members",
        "_build_public_generated_artifact_from_member",
        "_build_public_generated_artifacts_from_manifest",
        "_build_public_artifact_projection",
        "_normalize_tabular_run_planner_metadata",
        "_build_planner_source_coverage_summary",
        "_normalize_tabular_run_rollout_assignment",
    }
    selected_functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    publication_commits = []
    logged_events = []

    def commit_publication(current_user_id, conversation_id, artifact_message_id, artifact_set_id, artifact_member_id, publication_generation):
        publication_commits.append({
            "current_user_id": current_user_id,
            "conversation_id": conversation_id,
            "artifact_message_id": artifact_message_id,
            "artifact_set_id": artifact_set_id,
            "artifact_member_id": artifact_member_id,
            "publication_generation": publication_generation,
        })

    def fake_log_event(message, extra=None, level=logging.INFO):
        logged_events.append({"message": message, "extra": extra or {}, "level": level})

    namespace = {
        "re": re,
        "logging": logging,
        "log_event": fake_log_event,
        "logged_events": logged_events,
        "Counter": Counter,
        "is_analysis_internal_lineage_field": is_analysis_internal_lineage_field,
        "ANALYSIS_DELIVERABLE_MAX_ARTIFACT_ID_LENGTH": ANALYSIS_DELIVERABLE_MAX_ARTIFACT_ID_LENGTH,
        "ANALYSIS_DELIVERABLE_MAX_ARTIFACTS": ANALYSIS_DELIVERABLE_MAX_ARTIFACTS,
        "normalize_tabular_transformation_spec": normalize_tabular_transformation_spec,
        "validate_analysis_artifact_set": validate_analysis_artifact_set,
        "commit_generated_chat_artifact_publication_for_user": commit_publication,
        "publication_commits": publication_commits,
        "ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS": ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS,
        "ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT": ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT,
        "ANALYSIS_ARTIFACT_ROLE_SUPPORTING_OUTPUT": "supporting_output",
        "TABULAR_RUN_TASK_STRUCTURED_EXPORT": "structured_export",
        "TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS": "hierarchical_analysis",
        "TABULAR_RUN_TASK_COMBINED": "combined",
        "TABULAR_RUN_TASK_TYPES": {"structured_export", "hierarchical_analysis", "combined"},
        "TABULAR_RUN_TASK_TYPES": {"structured_export", "hierarchical_analysis", "combined"},
        "TABULAR_EXPORT_STATUS_RUNNING": "running",
        "TABULAR_EXPORT_STATUS_COMPLETED": "completed",
        "TABULAR_EXPORT_STATUS_FAILED": "failed",
        "TABULAR_EXPORT_STATUS_CANCELED": "canceled",
        "TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_ROWS": 10,
        "TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_CHARS": 24000,
        "TABULAR_GENERATION_PLAN_MAX_FIELDS": 50,
        "TABULAR_ARTIFACT_SET_CONTRACT_VERSION": "tabular-artifact-set-v1",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_PLANNED": "planned",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_GENERATING": "generating",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_VALIDATING": "validating",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_READY_TO_PUBLISH": "ready_to_publish",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_PUBLISHING": "publishing",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_COMPLETED": "completed",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_FAILED": "failed",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_CANCELED": "canceled",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_ROLLBACK_REQUIRED": "rollback_required",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_ROLLED_BACK": "rolled_back",
        "TABULAR_ARTIFACT_SET_LIFECYCLE_STATES": {
            "planned",
            "generating",
            "validating",
            "ready_to_publish",
            "publishing",
            "completed",
            "failed",
            "canceled",
            "rollback_required",
            "rolled_back",
        },
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_PLANNED": "planned",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_GENERATING": "generating",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_STAGED": "staged",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_VALIDATED": "validated",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_PUBLISHING": "publishing",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_PUBLISHED": "published",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_FAILED": "failed",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_CANCELED": "canceled",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_ROLLED_BACK": "rolled_back",
        "TABULAR_ARTIFACT_MEMBER_LIFECYCLE_STATES": {
            "planned",
            "generating",
            "staged",
            "validated",
            "publishing",
            "published",
            "failed",
            "canceled",
            "rolled_back",
        },
        "TABULAR_ARTIFACT_MEMBER_PUBLIC_LIFECYCLE_STATES": {"published"},
    }
    module = ast.Module(body=selected_functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(EXPORT_MODULE), "exec"), namespace)
    return namespace


def build_combined_contract():
    return build_analysis_deliverable_contract(
        action_mode="analyze",
        requested_output_format="csv",
        source_fingerprint="source-fingerprint",
        request_fingerprint="request-fingerprint",
    ).to_dict()


def build_multi_format_combined_contract():
    return build_analysis_deliverable_contract(
        action_mode="analyze",
        requested_output_formats=["json", "xml"],
        source_fingerprint="source-fingerprint",
        request_fingerprint="request-fingerprint",
    ).to_dict()


def build_run(status="running"):
    return {
        "id": "run-1",
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "task_type": "combined",
        "status": status,
        "output_format": "csv",
        "source_file_name": "financial_review.csv",
        "row_count": 200,
        "processed_rows": 200,
        "post_run_summary": "Analysis completed.",
        "post_run_export_summary": "CSV export completed.",
        "tabular_planner_metadata": {
            "deliverable_contract": build_combined_contract(),
        },
    }


def build_artifact(message_id, file_name, output_format):
    return {
        "artifact_message_id": message_id,
        "file_name": file_name,
        "capability": "tabular",
        "output_format": output_format,
        "preview_rows": [{"Column": "Value"}],
        "preview_columns": ["Column"],
        "preview_text": "# Preview" if output_format == "md" else "",
        "suppress_assistant_text": True,
    }


def test_staged_structured_member_is_not_public_until_set_completion():
    print("Testing staged structured member visibility...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = load_artifact_set_helpers()
    run = build_run(status="running")
    run["structured_export_artifact"] = build_artifact("csv-message", "financial_review.csv", "csv")

    manifest = helpers["_build_or_update_artifact_set_manifest"](run)
    members_by_id = {member["member_id"]: member for member in manifest["members"]}
    assert manifest["lifecycle_state"] == "validating"
    assert members_by_id["analysis"]["lifecycle_state"] == "planned"
    assert members_by_id["requested-csv"]["lifecycle_state"] == "staged"
    assert helpers["_build_public_generated_artifacts_from_manifest"](run, manifest) == []


def test_completed_combined_set_publishes_markdown_primary_then_sibling():
    print("Testing completed combined artifact-set publication order...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = load_artifact_set_helpers()
    run = build_run(status="running")
    structured_artifact = build_artifact("csv-message", "financial_review.csv", "csv")
    analysis_artifact = build_artifact("md-message", "financial_review.md", "md")

    helpers["_set_artifact_set_member_state"](
        run,
        "requested-csv",
        artifact=structured_artifact,
        lifecycle_state="staged",
        validation_state="validated",
    )
    run["structured_export_artifact"] = structured_artifact
    helpers["_set_artifact_set_member_state"](
        run,
        "analysis",
        artifact=analysis_artifact,
        lifecycle_state="staged",
        validation_state="validated",
    )
    run["analysis_artifact"] = analysis_artifact
    run["status"] = "completed"

    manifest = helpers["_publish_artifact_set_members"](run, ["analysis", "requested-csv"])
    assert manifest["lifecycle_state"] == "completed"
    assert manifest["validation_state"] == "validated"
    assert manifest["primary_artifact_id"] == "analysis"
    assert manifest["publication_generation"] == 1
    assert helpers["publication_commits"] == [
        {
            "current_user_id": "user-1",
            "conversation_id": "conversation-1",
            "artifact_message_id": "md-message",
            "artifact_set_id": "tabular-artifact-set:run-1",
            "artifact_member_id": "analysis",
            "publication_generation": 1,
        },
        {
            "current_user_id": "user-1",
            "conversation_id": "conversation-1",
            "artifact_message_id": "csv-message",
            "artifact_set_id": "tabular-artifact-set:run-1",
            "artifact_member_id": "requested-csv",
            "publication_generation": 1,
        },
    ]

    public_artifacts = helpers["_build_public_generated_artifacts_from_manifest"](run, manifest)
    assert [artifact["artifact_id"] for artifact in public_artifacts] == ["analysis", "requested-csv"]
    assert public_artifacts[0]["role"] == ANALYSIS_ARTIFACT_ROLE_PRIMARY_ANALYSIS
    assert public_artifacts[0]["output_format"] == "md"
    assert public_artifacts[1]["role"] == ANALYSIS_ARTIFACT_ROLE_REQUESTED_OUTPUT
    assert public_artifacts[1]["output_format"] == "csv"


def test_completed_combined_set_publishes_multiple_requested_siblings():
    print("Testing completed multi-sibling artifact-set publication order...")
    assert_app_version_at_least("0.250.180")
    helpers = load_artifact_set_helpers()
    run = build_run(status="running")
    run["output_format"] = "json"
    run["tabular_planner_metadata"]["deliverable_contract"] = build_multi_format_combined_contract()
    json_artifact = build_artifact("json-message", "financial_review.json", "json")
    json_artifact["artifact_id"] = "requested-json"
    xml_artifact = build_artifact("xml-message", "financial_review.xml", "xml")
    xml_artifact["artifact_id"] = "requested-xml"
    analysis_artifact = build_artifact("md-message", "financial_review.md", "md")

    run["structured_export_artifacts"] = [json_artifact, xml_artifact]
    run["structured_export_artifact"] = json_artifact
    run["analysis_artifact"] = analysis_artifact
    run["status"] = "completed"

    manifest = helpers["_publish_artifact_set_members"](run, ["analysis", "requested-json", "requested-xml"])
    assert manifest["lifecycle_state"] == "completed"
    assert manifest["validation_state"] == "validated"
    assert manifest["publication_generation"] == 1
    assert [commit["artifact_member_id"] for commit in helpers["publication_commits"]] == [
        "analysis",
        "requested-json",
        "requested-xml",
    ]

    public_artifacts = helpers["_build_public_generated_artifacts_from_manifest"](run, manifest)
    assert [artifact["artifact_id"] for artifact in public_artifacts] == [
        "analysis",
        "requested-json",
        "requested-xml",
    ]
    assert [artifact["output_format"] for artifact in public_artifacts] == ["md", "json", "xml"]


def test_invalid_required_set_fails_closed_without_public_artifacts():
    print("Testing invalid artifact-set fail-closed behavior...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    helpers = load_artifact_set_helpers()
    run = build_run(status="completed")
    run["structured_export_artifact"] = build_artifact("csv-message", "financial_review.csv", "csv")

    manifest = helpers["_publish_artifact_set_members"](run, ["requested-csv"])
    assert manifest["lifecycle_state"] == "rollback_required"
    assert manifest["validation_state"] == "invalid"
    assert "required_artifact_not_valid" in manifest["validation_report"]["reason_codes"]
    assert helpers["publication_commits"] == []
    assert helpers["_build_public_generated_artifacts_from_manifest"](run, manifest) == []


if __name__ == "__main__":
    tests = [
        test_staged_structured_member_is_not_public_until_set_completion,
        test_completed_combined_set_publishes_markdown_primary_then_sibling,
        test_completed_combined_set_publishes_multiple_requested_siblings,
        test_invalid_required_set_fails_closed_without_public_artifacts,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)
    passed_count = sum(1 for result in results if result)
    print(f"\nResults: {passed_count}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
