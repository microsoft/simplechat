#!/usr/bin/env python3
# test_tabular_transformations_phase4.py
"""
Functional test for Phase 4 tabular transformation correctness.
Version: 0.250.174
Implemented in: 0.250.174

This test ensures deterministic tabular transformation specs are bounded,
server-evaluable, persisted in deliverable contracts, and sufficient to
produce the 200-row financial review oracle without model-generated fields.
"""

from pathlib import Path
import sys
import traceback


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from test_support.analyze_deliverable_contract_fixture import (  # noqa: E402
    FINANCIAL_REVIEW_OUTPUT_COLUMNS,
    FINANCIAL_REVIEW_SOURCE_COLUMNS,
    build_expected_financial_review_output_rows,
    build_financial_review_source_rows,
    find_value_mismatches,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402

from functions_analysis_deliverables import (  # noqa: E402
    ANALYSIS_ORDERING_SOURCE_ORDER,
    ANALYSIS_ROW_CARDINALITY_ONE_PER_SOURCE_ROW,
    ANALYSIS_TRANSFORMATION_MODE_DETERMINISTIC,
    ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA_AND_RULES,
    build_analysis_deliverable_contract,
    coerce_analysis_deliverable_contract,
)
from functions_tabular_orchestration import plan_tabular_request  # noqa: E402
from functions_tabular_transformations import (  # noqa: E402
    TABULAR_TRANSFORMATION_SPEC_VERSION,
    TabularTransformationSpecError,
    evaluate_tabular_transformation_rows,
    get_tabular_transformation_model_fields,
    is_tabular_transformation_deterministic_only,
    normalize_tabular_transformation_spec,
)


IMPLEMENTED_VERSION = "0.250.174"


def _source(name):
    return {"source": name}


def _field(name):
    return {"field": name}


def _eq(left, right, value_type="", case_sensitive=True):
    expression = {"op": "eq", "left": left, "right": right, "case_sensitive": case_sensitive}
    if value_type:
        expression["value_type"] = value_type
    return expression


def _ne(left, right):
    return {"op": "ne", "left": left, "right": right}


def _gte(left, right, value_type="number"):
    return {"op": "gte", "left": left, "right": right, "value_type": value_type}


def _lt_date(left, right):
    return {"op": "lt", "left": left, "right": right, "value_type": "date"}


def _lte_date(left, right):
    return {"op": "lte", "left": left, "right": right, "value_type": "date"}


def _any(*values):
    return {"op": "any", "values": list(values)}


def _all(*values):
    return {"op": "all", "values": list(values)}


def _case(branches, else_value):
    return {"op": "case", "branches": branches, "else": else_value}


def _branch(when, then):
    return {"when": when, "then": then}


def build_financial_review_transformation_spec():
    return {
        "version": TABULAR_TRANSFORMATION_SPEC_VERSION,
        "fields": [
            {
                "name": "Item_ID",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "expression": {"op": "copy", "source": "Item_ID"},
            },
            {
                "name": "Timeline_Status",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "allowed_values": ["Overdue", "Due Soon", "On Track"],
                "expression": _case(
                    [
                        _branch(_lt_date(_source("Due_Date"), "2026-08-12"), "Overdue"),
                        _branch(_lte_date(_source("Due_Date"), "2026-09-11"), "Due Soon"),
                    ],
                    "On Track",
                ),
            },
            {
                "name": "Spend_Risk",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "allowed_values": ["High Spend Risk", "Moderate Spend Risk", "Low Spend Risk"],
                "expression": _case(
                    [
                        _branch(
                            _any(
                                _gte(_source("Invoice_Amount"), 75000),
                                _eq(_source("Vendor_Risk"), "High"),
                            ),
                            "High Spend Risk",
                        ),
                        _branch(
                            _any(
                                _gte(_source("Invoice_Amount"), 25000),
                                _eq(_source("Vendor_Risk"), "Medium"),
                            ),
                            "Moderate Spend Risk",
                        ),
                    ],
                    "Low Spend Risk",
                ),
            },
            {
                "name": "Control_Concern",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "allowed_values": ["Control Concern", "No Control Concern"],
                "expression": _case(
                    [
                        _branch(
                            _any(
                                {
                                    "op": "in",
                                    "value": _source("Control_Status"),
                                    "values": ["Missing Approval", "Policy Exception"],
                                },
                                _gte(_source("Exception_Count"), 2),
                            ),
                            "Control Concern",
                        ),
                    ],
                    "No Control Concern",
                ),
            },
            {
                "name": "Owner_Response_Status",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "allowed_values": ["Responded", "Needs Response"],
                "expression": _case(
                    [_branch(_eq(_source("Owner_Response"), "Received"), "Responded")],
                    "Needs Response",
                ),
            },
            {
                "name": "Escalation_Required",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "allowed_values": ["Yes", "No"],
                "expression": _case(
                    [
                        _branch(
                            _any(
                                _eq(_source("Escalation_Flag"), "Y"),
                                _all(
                                    _eq(_field("Timeline_Status"), "Overdue"),
                                    _eq(_field("Owner_Response_Status"), "Needs Response"),
                                ),
                            ),
                            "Yes",
                        ),
                    ],
                    "No",
                ),
            },
            {
                "name": "Overall_Attention",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "allowed_values": ["High Attention", "Monitor", "Low Attention"],
                "expression": _case(
                    [
                        _branch(
                            _any(
                                _eq(_field("Escalation_Required"), "Yes"),
                                _all(
                                    _eq(_field("Control_Concern"), "Control Concern"),
                                    _eq(_field("Owner_Response_Status"), "Needs Response"),
                                ),
                                _eq(_field("Spend_Risk"), "High Spend Risk"),
                            ),
                            "High Attention",
                        ),
                        _branch(
                            _any(
                                _ne(_field("Timeline_Status"), "On Track"),
                                _eq(_field("Spend_Risk"), "Moderate Spend Risk"),
                                _eq(_field("Control_Concern"), "Control Concern"),
                            ),
                            "Monitor",
                        ),
                    ],
                    "Low Attention",
                ),
            },
            {
                "name": "Review_Window",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "allowed_values": ["Past Due", "Due Today", "Within 30 Days", "Beyond 30 Days"],
                "expression": _case(
                    [
                        _branch(_lt_date(_source("Due_Date"), "2026-08-12"), "Past Due"),
                        _branch(_eq(_source("Due_Date"), "2026-08-12", value_type="date"), "Due Today"),
                        _branch(_lte_date(_source("Due_Date"), "2026-09-11"), "Within 30 Days"),
                    ],
                    "Beyond 30 Days",
                ),
            },
            {
                "name": "Recommended_Action",
                "mode": "deterministic",
                "type": "string",
                "nullable": False,
                "allowed_values": [
                    "Escalate review",
                    "Review overdue item",
                    "Schedule follow-up",
                    "Routine monitoring",
                ],
                "expression": _case(
                    [
                        _branch(_eq(_field("Overall_Attention"), "High Attention"), "Escalate review"),
                        _branch(_eq(_field("Timeline_Status"), "Overdue"), "Review overdue item"),
                        _branch(_eq(_field("Timeline_Status"), "Due Soon"), "Schedule follow-up"),
                    ],
                    "Routine monitoring",
                ),
            },
        ],
    }


def test_financial_review_transformation_matches_oracle():
    print("Testing deterministic transformation against the 200-row financial review oracle...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    source_rows = build_financial_review_source_rows()
    expected_rows = build_expected_financial_review_output_rows(source_rows)
    transformation_spec = build_financial_review_transformation_spec()
    normalized_spec = normalize_tabular_transformation_spec(
        transformation_spec,
        public_output_schema=FINANCIAL_REVIEW_OUTPUT_COLUMNS,
        source_schema=FINANCIAL_REVIEW_SOURCE_COLUMNS,
    )
    actual_rows = evaluate_tabular_transformation_rows(normalized_spec, source_rows)

    assert len(actual_rows) == 200
    assert list(actual_rows[0].keys()) == FINANCIAL_REVIEW_OUTPUT_COLUMNS
    assert find_value_mismatches(expected_rows, actual_rows, FINANCIAL_REVIEW_OUTPUT_COLUMNS) == []
    assert normalized_spec["field_mode_counts"]["deterministic"] == 9
    assert is_tabular_transformation_deterministic_only(
        normalized_spec,
        public_output_schema=FINANCIAL_REVIEW_OUTPUT_COLUMNS,
    )


def test_transformation_spec_rejects_unsafe_and_ambiguous_contracts():
    print("Testing transformation spec safety checks...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    unsafe_spec = {
        "version": TABULAR_TRANSFORMATION_SPEC_VERSION,
        "fields": [{"name": "X", "mode": "deterministic", "expression": {"op": "eval", "value": "1"}}],
    }
    try:
        normalize_tabular_transformation_spec(unsafe_spec, public_output_schema=["X"])
    except TabularTransformationSpecError:
        pass
    else:
        raise AssertionError("Unsupported operation was not rejected")

    reserved_spec = {
        "version": TABULAR_TRANSFORMATION_SPEC_VERSION,
        "fields": [{"name": "__simplechat_secret", "mode": "deterministic", "expression": "x"}],
    }
    try:
        normalize_tabular_transformation_spec(reserved_spec)
    except TabularTransformationSpecError:
        pass
    else:
        raise AssertionError("Reserved output field was not rejected")

    cycle_spec = {
        "version": TABULAR_TRANSFORMATION_SPEC_VERSION,
        "fields": [
            {"name": "A", "mode": "deterministic", "expression": {"field": "B"}},
            {"name": "B", "mode": "deterministic", "expression": {"field": "A"}},
        ],
    }
    try:
        normalize_tabular_transformation_spec(cycle_spec, public_output_schema=["A", "B"])
    except TabularTransformationSpecError:
        pass
    else:
        raise AssertionError("Derived-field cycle was not rejected")

    missing_source_spec = {
        "version": TABULAR_TRANSFORMATION_SPEC_VERSION,
        "fields": [{"name": "A", "mode": "deterministic", "expression": {"source": "Missing"}}],
    }
    try:
        normalize_tabular_transformation_spec(
            missing_source_spec,
            public_output_schema=["A"],
            source_schema=["Known"],
        )
    except TabularTransformationSpecError:
        pass
    else:
        raise AssertionError("Unknown source field was not rejected")


def test_contract_and_planner_persist_transformation_spec():
    print("Testing deliverable contract and planner transformation-spec persistence...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    transformation_spec = build_financial_review_transformation_spec()
    contract = build_analysis_deliverable_contract(
        action_mode="analyze",
        requested_output_format="csv",
        public_output_schema=FINANCIAL_REVIEW_OUTPUT_COLUMNS,
        row_cardinality=ANALYSIS_ROW_CARDINALITY_ONE_PER_SOURCE_ROW,
        ordering=ANALYSIS_ORDERING_SOURCE_ORDER,
        transformation_mode=ANALYSIS_TRANSFORMATION_MODE_DETERMINISTIC,
        transformation_spec=transformation_spec,
        validation_profile=ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA_AND_RULES,
        source_fingerprint="source-fixture",
        request_fingerprint="request-fixture",
    )
    payload = contract.to_dict()
    assert payload["contract_version"] == "analysis-deliverables-v3"
    assert payload["transformation_spec"]["version"] == TABULAR_TRANSFORMATION_SPEC_VERSION
    assert payload["transformation_spec"]["field_mode_counts"]["deterministic"] == 9
    assert coerce_analysis_deliverable_contract(payload).to_dict() == payload

    plan = plan_tabular_request(
        "Analyze every row and download the result as CSV.",
        [{"file_name": "financial_review.csv", "document_id": "doc-1", "source_version": "v1"}],
        action_mode="analyze",
        settings={"enable_tabular_hierarchical_analysis": True},
        requested_output_hints={
            "public_output_schema": FINANCIAL_REVIEW_OUTPUT_COLUMNS,
            "transformation_spec": transformation_spec,
        },
    )
    planned_contract = plan["deliverable_contract"]
    assert planned_contract["transformation_mode"] == ANALYSIS_TRANSFORMATION_MODE_DETERMINISTIC
    assert planned_contract["validation_profile"] == ANALYSIS_VALIDATION_PROFILE_EXACT_ROWS_SCHEMA_AND_RULES
    assert planned_contract["transformation_spec"]["version"] == TABULAR_TRANSFORMATION_SPEC_VERSION
    assert plan["durable_task_type"] == "combined"


def test_model_field_selection_excludes_deterministic_fields():
    print("Testing model-owned field selection for deterministic and hybrid specs...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    deterministic_spec = normalize_tabular_transformation_spec(
        build_financial_review_transformation_spec(),
        public_output_schema=FINANCIAL_REVIEW_OUTPUT_COLUMNS,
    )
    assert get_tabular_transformation_model_fields(
        deterministic_spec,
        public_output_schema=FINANCIAL_REVIEW_OUTPUT_COLUMNS,
    ) == []

    hybrid_spec = {
        "version": TABULAR_TRANSFORMATION_SPEC_VERSION,
        "fields": [
            {"name": "Item_ID", "mode": "deterministic", "expression": {"op": "copy", "source": "Item_ID"}},
            {"name": "Narrative", "mode": "semantic"},
        ],
    }
    assert get_tabular_transformation_model_fields(
        hybrid_spec,
        public_output_schema=["Item_ID", "Narrative"],
    ) == ["Narrative"]


def run_tests():
    tests = [
        test_financial_review_transformation_matches_oracle,
        test_transformation_spec_rejects_unsafe_and_ambiguous_contracts,
        test_contract_and_planner_persist_transformation_spec,
        test_model_field_selection_excludes_deterministic_fields,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
