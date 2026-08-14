# test_tabular_search_analyze_artifact_matrix.py
#!/usr/bin/env python3
"""
Functional matrix for Search and Analyze durable tabular artifact ownership.
Version: 0.250.199
Implemented in: 0.250.199

This test drives the real shared planner, persisted-metadata sanitizer,
artifact-set manifest, validation, and public projection for four customer
scenarios over the deterministic 200-row financial-review fixture.
"""

import sys
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT_DIR / "application" / "single_app"
TEST_ROOT = Path(__file__).resolve().parent
IMPLEMENTED_VERSION = "0.250.199"

for import_path in (APP_ROOT, TEST_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from functions_tabular_orchestration import plan_tabular_request  # noqa: E402
from test_support.analyze_deliverable_contract_fixture import (  # noqa: E402
    FINANCIAL_REVIEW_PROMPT,
    build_financial_review_source_rows,
)
from test_tabular_phase5_artifact_set_lifecycle import (  # noqa: E402
    build_artifact,
    load_artifact_set_helpers,
)


LINE_BY_LINE_PROMPT = (
    "For each line in this document, answer all eight questions individually. "
    "Go line by line and do not consolidate or omit any line."
)

SETTINGS = {
    "enable_tabular_hierarchical_analysis": True,
    "tabular_request_planner_mode": "active",
    "tabular_analyze_parity_rollout_percent": 100,
    "tabular_analyze_parity_rollout_state": "active",
}

FILE_CONTEXT = {
    "file_name": "financial_review.csv",
    "document_id": "financial-review-doc",
    "source_version": "etag-financial-review-v1",
    "source_hint": "workspace",
}


def _publish_planned_artifacts(plan, expected_formats):
    helpers = load_artifact_set_helpers()
    sanitized_metadata = helpers["_normalize_tabular_run_planner_metadata"](plan)
    run = {
        "id": f"run-{plan['action_mode']}-{plan['durable_task_type']}",
        "conversation_id": "conversation-1",
        "user_id": "user-1",
        "task_type": plan["durable_task_type"],
        "status": "running",
        "output_format": plan["output_format"] or "md",
        "source_file_name": "financial_review.csv",
        "row_count": 200,
        "processed_rows": 200,
        "tabular_planner_metadata": sanitized_metadata,
    }
    descriptors = helpers["_get_artifact_descriptors_for_run"](run)
    structured_artifacts = []
    published_member_ids = []

    for descriptor in descriptors:
        artifact = build_artifact(
            f"message-{descriptor['member_id']}",
            f"financial_review.{descriptor['format']}",
            descriptor["format"],
        )
        artifact["artifact_id"] = descriptor["member_id"]
        artifact["member_id"] = descriptor["member_id"]
        if descriptor["role"] == "primary_analysis":
            run["analysis_artifact"] = artifact
        else:
            structured_artifacts.append(artifact)
        helpers["_set_artifact_set_member_state"](
            run,
            descriptor["member_id"],
            artifact=artifact,
            lifecycle_state="staged",
            validation_state="validated",
        )
        published_member_ids.append(descriptor["member_id"])

    if structured_artifacts:
        run["structured_export_artifacts"] = structured_artifacts
        run["structured_export_artifact"] = structured_artifacts[0]
    run["status"] = "completed"

    manifest = helpers["_publish_artifact_set_members"](run, published_member_ids)
    public_artifacts = helpers["_build_public_generated_artifacts_from_manifest"](run, manifest)

    assert manifest["lifecycle_state"] == "completed", manifest
    assert manifest["validation_report"]["valid"] is True
    assert [artifact["output_format"] for artifact in public_artifacts] == expected_formats
    assert [artifact["row_count"] for artifact in public_artifacts] == [200] * len(expected_formats)
    assert len(public_artifacts) == len(expected_formats)


def test_search_analyze_artifact_matrix():
    """Each mode and prompt shape must own exactly its contract-defined artifacts."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    assert len(build_financial_review_source_rows()) == 200

    scenarios = [
        {
            "name": "search_explicit_csv",
            "action_mode": "search",
            "prompt": f"{FINANCIAL_REVIEW_PROMPT}\nCreate one complete downloadable CSV.",
            "task_type": "structured_export",
            "formats": ["csv"],
        },
        {
            "name": "analyze_explicit_csv",
            "action_mode": "analyze",
            "prompt": f"{FINANCIAL_REVIEW_PROMPT}\nCreate one complete downloadable CSV.",
            "task_type": "combined",
            "formats": ["md", "csv"],
        },
        {
            "name": "search_implicit_markdown",
            "action_mode": "search",
            "prompt": LINE_BY_LINE_PROMPT,
            "task_type": "hierarchical_analysis",
            "formats": ["md"],
        },
        {
            "name": "analyze_implicit_markdown",
            "action_mode": "analyze",
            "prompt": LINE_BY_LINE_PROMPT,
            "task_type": "hierarchical_analysis",
            "formats": ["md"],
        },
    ]

    for scenario in scenarios:
        plan = plan_tabular_request(
            scenario["prompt"],
            [FILE_CONTEXT],
            action_mode=scenario["action_mode"],
            settings=SETTINGS,
        )
        assert plan["durable_task_type"] == scenario["task_type"], scenario["name"]
        contract_formats = [
            artifact["format"]
            for artifact in plan["deliverable_contract"]["requested_artifacts"]
        ]
        assert contract_formats == scenario["formats"], scenario["name"]
        assert plan["deliverable_contract"]["analysis_required"] is (
            scenario["task_type"] != "structured_export"
        )
        _publish_planned_artifacts(plan, scenario["formats"])


if __name__ == "__main__":
    try:
        test_search_analyze_artifact_matrix()
        print("PASS: test_search_analyze_artifact_matrix")
    except Exception as exc:
        print(f"FAIL: test_search_analyze_artifact_matrix: {exc}")
        raise
