# test_analysis_calculations.py
"""
Functional tests for applying declared calculations to accepted Analyze records.
Version: 0.261.109
Implemented in: 0.261.109

Verify pure calculation application, correction provenance, rejected-record
isolation, untouched model judgments, and unchanged narrative-only analysis.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Standalone functional tests must establish the application import path first.
import functions_analysis_deliverables as deliverables  # noqa: E402


def _record(record_id, values):
    return {
        "record_id": record_id,
        "document_id": f"doc-{record_id}",
        "source": {"document_id": f"doc-{record_id}", "title": "Source document"},
        "values": values,
        "evidence_refs": [{"evidence_id": f"evidence-{record_id}", "locations": [1, 2]}],
        "metadata": {"retained": ["unchanged"]},
    }


def _field(name, expression, field_type="number", **options):
    return {
        "name": name,
        "mode": "deterministic",
        "type": field_type,
        "expression": expression,
        **options,
    }


def _round(value):
    return {"op": "round", "value": value, "scale": 2, "mode": "half_up"}


def _round_spec():
    return {
        "version": "tabular-transform-v2",
        "fields": [_field("total", _round({"source": "amount"}))],
    }


def _unexpected_call(*args, **kwargs):
    raise AssertionError("Narrative-only analysis must not execute calculations or telemetry")


@pytest.mark.parametrize("spec", [None, {}, False, []])
def test_no_spec_is_an_independent_narrative_passthrough_without_calls(monkeypatch, spec):
    records = [
        _record("narrative", {"finding": "A model judgment", "details": {"risks": ["delivery"]}}),
        {"record_id": "unstructured", "text": "Existing narrative remains unchanged"},
    ]
    original = deepcopy(records)
    monkeypatch.setattr(deliverables, "normalize_tabular_transformation_spec", _unexpected_call)
    monkeypatch.setattr(deliverables, "evaluate_tabular_transformation_row", _unexpected_call)
    monkeypatch.setattr(deliverables, "log_event", _unexpected_call)
    result = deliverables.apply_analysis_calculations(records, spec)
    assert result == {"accepted_records": records, "rejected_records": [], "issues": []}
    result["accepted_records"][0]["values"]["details"]["risks"].append("new")
    result["accepted_records"][0]["evidence_refs"][0]["locations"].append(3)
    assert records == original


def test_omitted_spec_and_empty_input_preserve_narrative_defaults():
    records = [_record("narrative", {"finding": "No scoring requested"})]
    assert deliverables.apply_analysis_calculations(records)["accepted_records"] == records
    assert deliverables.apply_analysis_calculations(None) == {
        "accepted_records": [], "rejected_records": [], "issues": [],
    }
    assert deliverables.apply_analysis_calculations([], _round_spec()) == {
        "accepted_records": [], "rejected_records": [], "issues": [],
    }


def test_model_only_spec_does_not_run_calculations_or_rewrite_fields(monkeypatch):
    records = [_record("model", {"judgment": {"risk": "high"}, "review": ["uncertain"]})]
    spec = {
        "version": "tabular-transform-v2",
        "fields": [
            {"name": "judgment", "mode": "semantic", "type": "object"},
            {"name": "review", "mode": "hybrid", "type": "array"},
        ],
    }
    monkeypatch.setattr(deliverables, "evaluate_tabular_transformation_row", _unexpected_call)
    result = deliverables.apply_analysis_calculations(records, spec)
    assert result == {"accepted_records": records, "rejected_records": [], "issues": []}


def test_weighted_totals_correct_only_declared_fields_with_bound_provenance(monkeypatch):
    spec = {
        "version": "tabular-transform-v2",
        "fields": [
            _field("meets_threshold", {
                "op": "gte", "left": {"field": "total"}, "right": "85.99", "value_type": "number",
            }, "boolean"),
            _field("total", _round({
                "op": "add",
                "values": [
                    {"op": "multiply", "values": [{"source": "first_score"}, "0.6"]},
                    {"op": "multiply", "values": [{"source": "second_score"}, "0.4"]},
                ],
            })),
            {"name": "judgment", "mode": "semantic", "type": "object"},
            {"name": "review", "mode": "hybrid", "type": "string"},
        ],
    }
    records = [_record("weighted", {
        "first_score": "89.95", "second_score": "80.05",
        "total": 0, "meets_threshold": False,
        "judgment": {"risk": "model judgment", "evidence": ["passage"]},
        "review": "Factual review remains unperformed",
        "undeclared": {"nested": ["keep"]},
    })]
    original_records = deepcopy(records)
    original_spec = deepcopy(spec)
    monkeypatch.setattr(deliverables, "log_event", _unexpected_call)
    result = deliverables.apply_analysis_calculations(records, spec)
    assert result["rejected_records"] == []
    accepted = result["accepted_records"][0]
    assert accepted["values"]["total"] == 85.99
    assert accepted["values"]["meets_threshold"] is True
    for field_name in ("first_score", "second_score", "judgment", "review", "undeclared"):
        assert accepted["values"][field_name] == records[0]["values"][field_name]
    for metadata_name in ("record_id", "document_id", "source", "evidence_refs", "metadata"):
        assert accepted[metadata_name] == records[0][metadata_name]
    corrections = {issue["field"]: issue for issue in result["issues"]}
    assert set(corrections) == {"total", "meets_threshold"}
    normalized = deliverables.normalize_tabular_transformation_spec(spec)
    fingerprint_input = {"version": normalized["version"], "fields": normalized["fields"]}
    expected_digest = hashlib.sha256(
        json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    for field_name, issue in corrections.items():
        assert issue == {
            "code": "analysis_calculation_value_corrected",
            "record_index": 0,
            "record_id": "weighted",
            "document_id": "doc-weighted",
            "spec_version": "tabular-transform-v2",
            "spec_fingerprint": expected_digest,
            "field": field_name,
            "reported_value": records[0]["values"][field_name],
            "calculated_value": accepted["values"][field_name],
        }
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    accepted["values"]["judgment"]["evidence"].append("new")
    accepted["metadata"]["retained"].append("new")
    assert records == original_records
    assert spec == original_spec


@pytest.mark.parametrize("reported", [False, None, "0", 0.0])
def test_correction_provenance_distinguishes_null_boolean_and_number_representations(reported):
    record = _record("zero", {"amount": "0", "total": reported})
    result = deliverables.apply_analysis_calculations([record], _round_spec())
    assert result["accepted_records"][0]["values"]["total"] == 0
    assert len(result["issues"]) == 1
    assert result["issues"][0]["reported_value"] == reported
    assert type(result["issues"][0]["reported_value"]) is type(reported)
    assert result["issues"][0]["calculated_value"] == 0


def test_missing_or_matching_values_do_not_create_spurious_correction_issues():
    records = [
        _record("missing", {"amount": "2.675"}),
        _record("matching", {"amount": "2.675", "total": 2.68}),
    ]
    result = deliverables.apply_analysis_calculations(records, _round_spec())
    assert [record["values"]["total"] for record in result["accepted_records"]] == [2.68, 2.68]
    assert result["issues"] == []
    assert result["rejected_records"] == []
    assert "total" not in records[0]["values"]
    repeated = deliverables.apply_analysis_calculations(result["accepted_records"], _round_spec())
    assert repeated == result


@pytest.mark.parametrize("invalid_amount", [None, "NaN", True])
def test_failed_calculations_reject_records_without_reusing_reported_values(invalid_amount):
    records = [
        _record("first", {"amount": "2.675", "total": 1, "judgment": "retained"}),
        _record("rejected", {"amount": invalid_amount, "total": 999, "judgment": "still provisional"}),
        _record("last", {"amount": "-2.675", "total": -2.68}),
    ]
    original = deepcopy(records)
    result = deliverables.apply_analysis_calculations(records, _round_spec())
    assert [record["record_id"] for record in result["accepted_records"]] == ["first", "last"]
    assert [record["values"]["total"] for record in result["accepted_records"]] == [2.68, -2.68]
    assert result["rejected_records"] == [{
        "record_index": 1,
        "record_id": "rejected",
        "document_id": "doc-rejected",
        "source": records[1]["source"],
        "evidence_refs": records[1]["evidence_refs"],
        "issue_codes": ["analysis_calculation_failed"],
    }]
    assert [issue["code"] for issue in result["issues"]] == [
        "analysis_calculation_value_corrected", "analysis_calculation_failed",
    ]
    assert "values" not in result["rejected_records"][0]
    result["rejected_records"][0]["evidence_refs"][0]["locations"].append(3)
    assert records == original


def test_required_calculation_failure_is_atomic_for_the_entire_record():
    spec = {
        "version": "tabular-transform-v2",
        "fields": [
            _field("good", {"op": "add", "values": [1, 2]}),
            _field("bad", _round({"op": "divide", "values": [1, 0]})),
        ],
    }
    record = _record("atomic", {"good": 999, "bad": 888, "narrative": "Do not alter"})
    result = deliverables.apply_analysis_calculations([record], spec)
    assert result["accepted_records"] == []
    assert len(result["rejected_records"]) == 1
    assert [issue["code"] for issue in result["issues"]] == ["analysis_calculation_failed"]
    assert record["values"] == {"good": 999, "bad": 888, "narrative": "Do not alter"}


@pytest.mark.parametrize(
    "spec",
    [
        {"version": "tabular-transform-v2", "fields": [_field("total", {"op": "eval", "value": "1"})]},
        {"version": "tabular-transform-v3", "fields": [_field("total", 1)]},
        {"version": "tabular-transform-v2", "fields": [_field("total", {"field": "total"})]},
        {"version": "tabular-transform-v2", "fields": []},
    ],
)
def test_invalid_required_specs_reject_all_records_and_stay_explicit_when_empty(monkeypatch, spec):
    records = [_record("first", {"total": 999}), _record("second", {"total": 888})]
    monkeypatch.setattr(deliverables, "evaluate_tabular_transformation_row", _unexpected_call)
    result = deliverables.apply_analysis_calculations(records, spec)
    assert result["accepted_records"] == []
    assert [record["record_index"] for record in result["rejected_records"]] == [0, 1]
    assert all("values" not in record for record in result["rejected_records"])
    assert all(issue["code"] == "analysis_calculation_spec_invalid" for issue in result["issues"])
    assert deliverables.apply_analysis_calculations([], spec) == {
        "accepted_records": [], "rejected_records": [],
        "issues": [{"code": "analysis_calculation_spec_invalid"}],
    }


@pytest.mark.parametrize("record", [None, {}, {"values": None}, {"values": []}, {"values": "narrative"}])
def test_required_calculations_reject_invalid_record_shapes_without_execution(monkeypatch, record):
    monkeypatch.setattr(deliverables, "evaluate_tabular_transformation_row", _unexpected_call)
    result = deliverables.apply_analysis_calculations([record], _round_spec())
    assert result["accepted_records"] == []
    assert result["rejected_records"][0]["record_index"] == 0
    assert result["issues"][0]["code"] == "analysis_calculation_record_invalid"


@pytest.mark.parametrize("reported", [float("nan"), float("inf"), object()])
def test_nonserializable_reported_values_are_record_issues_not_arithmetic_failures(reported):
    record = _record("invalid-reported", {"amount": "2.675", "total": reported})
    result = deliverables.apply_analysis_calculations([record], _round_spec())
    assert result["accepted_records"] == []
    assert result["rejected_records"][0]["issue_codes"] == ["analysis_calculation_record_invalid"]
    assert result["issues"][0]["code"] == "analysis_calculation_record_invalid"
    assert "reported_value" not in result["issues"][0]
    json.dumps(result, allow_nan=False)


def test_helper_preserves_exact_dependent_rounding_and_thresholds():
    spec = {
        "version": "tabular-transform-v2",
        "fields": [
            _field("total", _round({"field": "raw"})),
            _field("above", {
                "op": "gte", "left": {"field": "raw"}, "right": "1.005", "value_type": "number",
            }, "boolean"),
            _field("raw", {
                "op": "add", "values": [{"source": "amount"}, "0.000000000000000001"],
            }, "string"),
        ],
    }
    record = _record("precise", {
        "amount": "1.004999999999999998", "raw": 1.005, "total": 1.01, "above": True,
        "judgment": "This remains a model assessment",
    })
    result = deliverables.apply_analysis_calculations([record], spec)
    values = result["accepted_records"][0]["values"]
    assert values["raw"] == "1.004999999999999999"
    assert values["total"] == 1
    assert values["above"] is False
    assert values["judgment"] == record["values"]["judgment"]
    assert {issue["field"] for issue in result["issues"]} == {"raw", "total", "above"}


@pytest.mark.parametrize(("version", "expected"), [("tabular-transform-v1", 0), ("tabular-transform-v2", 0.1)])
def test_helper_honors_saved_version_semantics(version, expected):
    spec = {
        "version": version,
        "fields": [_field("total", {
            "op": "subtract",
            "left": {"op": "add", "values": ["10000000000000000", "0.1"]},
            "right": "10000000000000000",
        })],
    }
    result = deliverables.apply_analysis_calculations([_record("versioned", {"total": 999})], spec)
    assert result["accepted_records"][0]["values"]["total"] == expected
    assert result["issues"][0]["spec_version"] == version


def test_unrepresentable_results_cannot_fall_back_to_model_rounded_values():
    spec = {
        "version": "tabular-transform-v2",
        "fields": [_field("total", {"op": "add", "values": ["0.100000000000000005", 0]})],
    }
    record = _record("lossy", {"total": 0.1})
    result = deliverables.apply_analysis_calculations([record], spec)
    assert result["accepted_records"] == []
    assert result["issues"][0]["code"] == "analysis_calculation_failed"
    spec["fields"][0]["type"] = "string"
    result = deliverables.apply_analysis_calculations([record], spec)
    assert result["accepted_records"][0]["values"]["total"] == "0.100000000000000005"


def test_calculations_use_values_not_source_metadata_and_do_not_expose_exception_text(monkeypatch):
    record = _record("source", {"amount": "2.675", "total": 2.68})
    record["source"]["amount"] = "100"
    result = deliverables.apply_analysis_calculations([record], _round_spec())
    assert result["accepted_records"][0]["values"]["total"] == 2.68
    assert result["issues"] == []

    def fail_evaluation(*args, **kwargs):
        raise ValueError("private-provider-error-not-for-reports")

    monkeypatch.setattr(deliverables, "evaluate_tabular_transformation_row", fail_evaluation)
    result = deliverables.apply_analysis_calculations([record], _round_spec())
    assert result["accepted_records"] == []
    assert "private-provider-error-not-for-reports" not in json.dumps(result)


def test_nested_correction_snapshots_do_not_alias_accepted_judgments():
    reported = [True]
    record = _record("nested", {"derived": reported, "judgment": reported})
    spec = {
        "version": "tabular-transform-v2",
        "fields": [_field("derived", {"value": [1]}, "array")],
    }
    result = deliverables.apply_analysis_calculations([record], spec)
    assert result["accepted_records"][0]["values"] == {"derived": [1], "judgment": [True]}
    assert len(result["issues"]) == 1
    result["issues"][0]["reported_value"][0] = False
    assert result["accepted_records"][0]["values"]["judgment"] == [True]
    assert record["values"] == {"derived": [True], "judgment": [True]}
