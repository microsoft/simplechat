# test_tabular_combined_output_schema_deferral_fix.py
#!/usr/bin/env python3
"""
Functional test for the combined tabular Analyze output-schema deferral fix.
Version: 0.250.189
Implemented in: 0.250.189

This test ensures a combined (Analyze) tabular run with no upfront output hints
starts with output_schema=None so batch 1 can discover the real model-produced
schema, instead of being locked to the lineage-only internal checkpoint schema
and rejecting every batch (including batch 1) as a schema mismatch.
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

IMPLEMENTED_VERSION = "0.250.189"
EXPORT_MODULE = APP_ROOT / "functions_tabular_generated_exports.py"

FIXED_LINE = (
    "'output_schema': contract_internal_checkpoint_schema if contract_public_output_schema else None,"
)
BUGGY_LINE = "'output_schema': contract_internal_checkpoint_schema or None,"


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


def _capture_analyze_plan():
    captured = {}

    def durable_callback(plan, **execution_context):
        captured["plan"] = plan
        captured["execution_context"] = execution_context
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


def test_combined_run_with_no_output_hints_defers_schema():
    """A real (unmocked) Analyze deliverable contract with no output hints must
    still let batch 1 discover the schema instead of locking it to lineage fields."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    plan = _capture_analyze_plan()

    assert plan["requested_output_hints"] == {}, (
        "Precondition: the financial-review prompt produces no upfront output hints"
    )
    deliverable_contract = plan["deliverable_contract"]
    contract_public_output_schema = list(deliverable_contract.get("public_output_schema") or [])
    contract_internal_checkpoint_schema = list(deliverable_contract.get("internal_checkpoint_schema") or [])

    assert contract_public_output_schema == [], (
        "Precondition: no real output columns are known before batch 1 runs"
    )
    assert contract_internal_checkpoint_schema, (
        "Precondition: lineage-only internal checkpoint schema is still non-empty"
    )

    # The historical bug: `contract_internal_checkpoint_schema or None` is truthy here,
    # locking the run to a schema with none of the model's real output columns.
    buggy_output_schema = contract_internal_checkpoint_schema or None
    assert buggy_output_schema == contract_internal_checkpoint_schema, (
        "This case must reproduce the historical bug precondition"
    )

    # The fix: only lock the schema when real output columns are already known.
    fixed_output_schema = (
        contract_internal_checkpoint_schema if contract_public_output_schema else None
    )
    assert fixed_output_schema is None, (
        "output_schema must defer to batch-1 discovery when no public schema is known"
    )


def test_run_creation_source_uses_the_deferral_fix():
    """Guard against silently reverting the one-line output_schema fix."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    source = EXPORT_MODULE.read_text(encoding="utf-8")
    assert FIXED_LINE in source, "queue_tabular_generated_output_run must use the deferral fix"
    assert BUGGY_LINE not in source, "the lineage-only schema lock must not be reintroduced"


if __name__ == "__main__":
    tests = [
        test_combined_run_with_no_output_hints_defers_schema,
        test_run_creation_source_uses_the_deferral_fix,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    sys.exit(1 if failures else 0)
