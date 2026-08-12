# test_tabular_phase7b_production_correctness.py
#!/usr/bin/env python3
"""
Functional test for Phase 7B production tabular correctness planning.
Version: 0.250.179
Implemented in: 0.250.179

This test ensures real Search and Analyze shared-facade requests need no
injected output hints, persist the same reviewed deterministic contract, write
all 200 rows through durable checkpoints, and produce exact equivalent output.
"""

import ast
import hashlib
import logging
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from functions_analysis_deliverables import (  # noqa: E402
    build_analysis_deliverable_contract,
    project_structured_deliverable_rows,
    validate_structured_deliverable_rows,
)
from functions_tabular_orchestration import orchestrate_tabular_request  # noqa: E402
from functions_tabular_transformations import (  # noqa: E402
    evaluate_tabular_transformation_rows,
    get_tabular_transformation_model_fields,
)
from test_support.analyze_deliverable_contract_fixture import (  # noqa: E402
    FINANCIAL_REVIEW_OUTPUT_COLUMNS,
    FINANCIAL_REVIEW_PROMPT,
    build_expected_financial_review_output_rows,
    build_financial_review_source_rows,
    find_value_mismatches,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_tabular_row_orchestration_scale import _load_generation_plan_helpers  # noqa: E402
from test_tabular_transformations_phase4 import build_financial_review_transformation_spec  # noqa: E402


IMPLEMENTED_VERSION = "0.250.179"
EXPORT_MODULE = APP_ROOT / "functions_tabular_generated_exports.py"


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


def _capture_production_plan(action_mode):
    captured = {}

    def durable_callback(plan, **execution_context):
        captured["plan"] = plan
        captured["execution_context"] = execution_context
        return {
            "background_export": True,
            "export_run_id": f"run-{action_mode}",
            "status": "queued",
            "task_type": plan["durable_task_type"],
            "output_format": "csv",
        }

    result = orchestrate_tabular_request(
        f"{FINANCIAL_REVIEW_PROMPT}\nDownload the result as CSV.",
        [_build_context()],
        action_mode=action_mode,
        caller=action_mode,
        settings={
            "enable_tabular_hierarchical_analysis": True,
            "tabular_analyze_parity_rollout_percent": 100,
            "tabular_analyze_parity_rollout_state": "active",
        },
        planner_mode="active",
        durable_execution_callback=durable_callback,
        user_id="user-1",
        conversation_id="conversation-1",
        gpt_model="gpt-plan",
    )
    assert result["execution_state"] == "queued"
    assert result["reason_code"] == "active_execution_accepted"
    assert captured["plan"]["requested_output_hints"] == {}
    return captured["plan"]


def _build_reviewed_run(action_mode, shared_plan, source_rows):
    helpers, _, _ = _load_generation_plan_helpers()
    run = {
        "id": f"run-{action_mode}",
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "user_question": f"{FINANCIAL_REVIEW_PROMPT}\nDownload the result as CSV.",
        "output_format": "csv",
        "response_protocol_version": "object-v1",
        "task_type": shared_plan["durable_task_type"],
        "source_descriptor": {
            "blob_path": "user-1/financial_review.csv",
            "blob_etag": "etag-financial-review-v1",
        },
        "row_count": len(source_rows),
        "batch_count": 4,
        "batch_budget": {
            "max_rows": 50,
            "max_chars": 60000,
            "input_token_budget": 60000,
            "output_token_budget": 30000,
        },
        "plan_mode": "active",
        "plan_status": "pending",
        "output_schema": None,
        "public_output_schema": [],
        "internal_checkpoint_schema": [],
        "transformation_spec": {},
        "tabular_planner_metadata": shared_plan,
    }
    input_contract = helpers["_build_tabular_generation_plan_input_contract"](source_rows[:5])
    transformation_spec = build_financial_review_transformation_spec()
    planner_payload = {
        "output_fields": [
            {
                "name": field_name,
                "description": f"Deterministic requested field {field_name}.",
                "type": "string",
                "nullable": False,
                "source": "server",
            }
            for field_name in FINANCIAL_REVIEW_OUTPUT_COLUMNS
        ],
        "transformation_spec": transformation_spec,
    }
    plan = helpers["_build_tabular_generation_plan"](
        run,
        planner_payload,
        input_contract,
        {
            "endpoint_id": "endpoint-1",
            "model_id": "gpt-plan",
            "deployment": "gpt-plan",
        },
        created_at="2026-08-12T12:00:00+00:00",
    )
    reviewed_plan = helpers["_finalize_tabular_generation_plan_review"](
        plan,
        {
            "status": "passed",
            "represented_fields": FINANCIAL_REVIEW_OUTPUT_COLUMNS,
            "reason_codes": [],
        },
        {
            "endpoint_id": "endpoint-1",
            "model_id": "gpt-review",
            "deployment": "gpt-review",
        },
    )
    helpers["_apply_active_tabular_generation_plan"](run, reviewed_plan)
    return run, reviewed_plan


def _load_checkpoint_writer():
    source = EXPORT_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_MODULE))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_checkpoint_generated_batch_results"
    )
    blobs = {}

    def upload(path, payload, metadata=None, overwrite=True):
        del metadata
        if not overwrite and path in blobs:
            raise FileExistsError(path)
        blobs[path] = payload

    namespace = {
        "ResourceExistsError": FileExistsError,
        "logging": logging,
        "time": time,
        "_raise_if_tabular_export_canceled": lambda run: None,
        "_get_tabular_run_public_output_schema": lambda run: list(run["public_output_schema"]),
        "_get_tabular_run_internal_checkpoint_schema": lambda run: list(run["internal_checkpoint_schema"]),
        "_record_shadow_tabular_generation_plan_comparison": lambda run, schema: False,
        "_replace_claimed_run": lambda run: dict(run),
        "_output_blob_path": lambda user_id, conversation_id, run_id, batch_number: f"output/{batch_number}",
        "_output_summary_blob_path": lambda user_id, conversation_id, run_id, batch_number: f"summary/{batch_number}",
        "_upload_json_blob": upload,
        "_build_tabular_output_checkpoint_metadata": lambda run, metadata: metadata,
        "_validate_tabular_output_checkpoint_metadata": lambda run, path, batch_number: None,
        "_download_json_blob": lambda path: blobs[path],
        "_build_generated_batch_summary": lambda entries: {"row_count": len(entries)},
        "log_event": lambda *args, **kwargs: None,
    }
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(EXPORT_MODULE), "exec"), namespace)
    return namespace["_checkpoint_generated_batch_results"], blobs


def _load_fallback_contract_helper():
    source = EXPORT_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_MODULE))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_ensure_active_tabular_run_deliverable_contract"
    )
    namespace = {
        "hashlib": hashlib,
        "TABULAR_RUN_TASK_COMBINED": "combined",
        "_normalize_tabular_run_task_type": lambda value: value or "structured_export",
        "build_analysis_deliverable_contract": build_analysis_deliverable_contract,
    }
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(EXPORT_MODULE), "exec"), namespace)
    return namespace["_ensure_active_tabular_run_deliverable_contract"]


def _checkpoint_deterministic_rows(run, source_rows, transformed_rows):
    generated_results = []
    for batch_number, batch_start in enumerate(range(0, len(source_rows), 50), start=1):
        batch_rows = []
        for offset, public_row in enumerate(transformed_rows[batch_start:batch_start + 50], start=1):
            source_row_number = batch_start + offset
            batch_rows.append({
                "source_row_number": source_row_number,
                "source_row_identity": public_row["Item_ID"],
                **public_row,
            })
        generated_results.append({
            "batch_number": batch_number,
            "batch_entries": batch_rows,
            "batch_summary": {"row_count": len(batch_rows)},
            "batch_row_count": len(batch_rows),
            "elapsed_seconds": 0.01,
            "mismatch_count": 0,
            "output_schema": list(run["output_schema"]),
        })
    checkpoint_writer, blobs = _load_checkpoint_writer()
    checkpoint_writer(run, generated_results)
    checkpointed_rows = []
    for batch_number in range(1, 5):
        checkpointed_rows.extend(blobs[f"output/{batch_number}"])
    return project_structured_deliverable_rows(
        checkpointed_rows,
        run["public_output_schema"],
        require_all_fields=True,
    )


def test_financial_review_real_search_and_analyze_contracts_are_exact():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    source_rows = build_financial_review_source_rows()
    expected_rows = build_expected_financial_review_output_rows(source_rows)
    actual_by_action = {}
    contracts_by_action = {}

    for action_mode in ("search", "analyze"):
        shared_plan = _capture_production_plan(action_mode)
        run, reviewed_plan = _build_reviewed_run(action_mode, shared_plan, source_rows)
        transformation_spec = reviewed_plan["transformation_spec"]
        assert get_tabular_transformation_model_fields(
            transformation_spec,
            public_output_schema=FINANCIAL_REVIEW_OUTPUT_COLUMNS,
        ) == []
        transformed_rows = evaluate_tabular_transformation_rows(transformation_spec, source_rows)
        actual_rows = _checkpoint_deterministic_rows(run, source_rows, transformed_rows)
        contract = run["tabular_planner_metadata"]["deliverable_contract"]
        report = validate_structured_deliverable_rows(
            contract,
            output_rows=actual_rows,
            source_rows=source_rows,
            expected_rows=expected_rows,
            identity_field="Item_ID",
        )
        assert report.valid, report.to_dict()
        assert find_value_mismatches(expected_rows, actual_rows) == []
        assert contract["validation_profile"] == "exact_rows_schema_and_rules"
        assert contract["transformation_mode"] == "deterministic"
        actual_by_action[action_mode] = actual_rows
        contracts_by_action[action_mode] = contract

    assert actual_by_action["search"] == actual_by_action["analyze"]
    assert contracts_by_action["search"]["public_output_schema"] == FINANCIAL_REVIEW_OUTPUT_COLUMNS
    assert contracts_by_action["analyze"]["public_output_schema"] == FINANCIAL_REVIEW_OUTPUT_COLUMNS
    assert [
        artifact["format"]
        for artifact in contracts_by_action["analyze"]["requested_artifacts"]
    ] == ["md", "csv"]


def test_active_legacy_direct_preflight_gets_server_owned_contract():
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    ensure_contract = _load_fallback_contract_helper()
    fallback_metadata = ensure_contract(
        {},
        "active",
        "combined",
        "csv",
        "Analyze every row and create a CSV.",
    )
    contract = fallback_metadata["deliverable_contract"]
    assert contract["action_mode"] == "analyze"
    assert contract["analysis_required"] is True
    assert [artifact["format"] for artifact in contract["requested_artifacts"]] == ["md", "csv"]
    assert fallback_metadata["reason_code"] == "legacy_direct_preflight"

    existing_metadata = {"deliverable_contract": {"contract_version": "existing"}}
    assert ensure_contract(
        existing_metadata,
        "active",
        "structured_export",
        "csv",
        "Export rows.",
    ) == existing_metadata
    assert ensure_contract(
        {},
        "shadow",
        "structured_export",
        "csv",
        "Export rows.",
    ) == {}


if __name__ == "__main__":
    test_financial_review_real_search_and_analyze_contracts_are_exact()
    test_active_legacy_direct_preflight_gets_server_owned_contract()
    print("PASS test_financial_review_real_search_and_analyze_contracts_are_exact")
    print("PASS test_active_legacy_direct_preflight_gets_server_owned_contract")
