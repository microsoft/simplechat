# test_document_analysis_observation_identity.py
"""
Evidence-bound observation identities and explicit Analyze semantics.
Version: 0.261.398
Implemented in: 0.261.398

Run the real source reader, window collector and finalizer with fictional
documents and deterministic model responses. Repeated subject labels must not
discard supported observations or weaken structured-record/evidence validation.
"""

from copy import deepcopy
import importlib
import json

import pytest

from test_document_analysis_final_results import run_analysis
from test_support.app_stubs import import_app_module
from test_support.document_analysis import (
    FixtureAnalysisClient,
    document_analysis_runtime,
    original_document,
)


OBSERVATIONS = {"version": "analysis-options-v2", "mode": "source_observations"}
RECORDS = {"version": "analysis-options-v2", "mode": "reconciled_records"}
PASSAGES = [
    "The handover lists item B-17.",
    "The log labels item B-17 closed at 13:30.",
    "The prior run finished at 12:20.",
    "Verification uses the preceding review period.",
    "The current schedule records a new shift.",
    "Verify the evidence and brief remaining questions.",
    "The supplied log is revision two.",
    "Retain uncertainty and keep review questions separate from formatting.",
]
FINDINGS = [
    (1, "subject", "The handover concerns B-17.", "The item is named in the handover."),
    (2, "status", "The log records closure.", "The recorded closure time is 13:30."),
    (3, "run", "The prior run is time-stamped.", "The prior run ended at 12:20."),
    (6, "closure_review", "The next shift must verify evidence.", "It must brief remaining questions."),
    (7, "revision", "The log has a revision.", "The supplied log is revision two."),
    (8, "closure_review", "The next shift must retain uncertainty.", "Review is separate from formatting."),
]


def response_builder(findings=FINDINGS, *, repeat=False, subject_suffix="", unsupported_page=None):
    def build(prompt):
        excerpt = prompt.split("<DocumentSlice>\n", 1)[1].rsplit("\n</DocumentSlice>", 1)[0]
        values = []
        for page, subject, finding, explanation in findings:
            if PASSAGES[page - 1] not in excerpt:
                continue
            values.append({
                "finding_key": subject + subject_suffix,
                "values": {"finding": finding, "explanation": explanation},
                "status": "unresolved" if page == unsupported_page else "supported",
                "issues": [],
                "evidence": [{"chunk_sequence": page, "quote": PASSAGES[page - 1]}],
            })
        return json.dumps({"findings": values * (2 if repeat else 1)})

    return build


@pytest.mark.parametrize("window_size", [1, 5, 8])
def test_repeated_subjects_preserve_all_supported_observations(window_size):
    documents = {"handover": original_document("handover", PASSAGES)}
    client = FixtureAnalysisClient(response_builder())
    with document_analysis_runtime(documents) as runtime:
        result, _ = run_analysis(
            runtime, documents, client, analysis_options=OBSERVATIONS, window_size=window_size,
        )
        records = result["authoritative_result"]["value"]
        validation = result["analysis_validation"]
        assert validation["status"] == "valid"
        assert validation["coverage"]["status"] == "complete"
        assert validation["unresolved_candidate_count"] == 0
        assert len(records) == 6
        assert len({record["record_id"] for record in records}) == 6
        assert validation["semantics"] == OBSERVATIONS
        assert {record["values"]["finding"] for record in records} == {item[2] for item in FINDINGS}
        passages = {item["evidence_id"]: item for item in result["analysis_evidence"]}
        assert {
            passages[ref]["location"]["page_number"]
            for record in records for ref in record["evidence_refs"]
        } == {1, 2, 3, 6, 7, 8}


@pytest.mark.parametrize("options", [None, RECORDS])
def test_record_semantics_keep_the_original_conflict_guard(options):
    documents = {"handover": original_document("handover", PASSAGES)}
    with document_analysis_runtime(documents) as runtime:
        result, _ = run_analysis(
            runtime, documents, FixtureAnalysisClient(response_builder()),
            analysis_options=options, window_size=5,
        )
        assert result["analysis_validation"]["status"] == "partial"
        assert result["analysis_validation"]["unresolved_candidate_count"] == 2
        assert len(result["authoritative_result"]["value"]) == 4
        assert result["analysis_validation"]["issues"][0]["code"] == "conflicting_values"


def test_observation_identity_does_not_depend_on_subject_labels_or_window_size():
    documents = {"handover": original_document("handover", PASSAGES)}
    with document_analysis_runtime(documents) as runtime:
        first, _ = run_analysis(
            runtime, documents, FixtureAnalysisClient(response_builder()),
            analysis_options=OBSERVATIONS, window_size=1,
        )
        second, _ = run_analysis(
            runtime, documents, FixtureAnalysisClient(response_builder(subject_suffix="-renamed")),
            analysis_options=OBSERVATIONS, window_size=8,
        )
        assert first["authoritative_result"] == second["authoritative_result"]


def test_exact_duplicate_observations_and_work_unit_replays_are_idempotent():
    documents = {"handover": original_document("handover", PASSAGES)}
    with document_analysis_runtime(documents) as runtime:
        result, _ = run_analysis(
            runtime, documents, FixtureAnalysisClient(response_builder(repeat=True)),
            analysis_options=OBSERVATIONS, window_size=8,
        )
        assert len(result["authoritative_result"]["value"]) == 6
        replay = runtime.results.finalize_document_analysis_result(
            result["analysis_sources"],
            result["analysis_validation"]["coverage"]["work_units"] * 2,
            result["analysis_diagnostics"]["candidates"] * 2,
            result["analysis_evidence"] * 2,
            analysis_options=OBSERVATIONS,
        )
        assert replay["authoritative_result"] == result["authoritative_result"]
        assert replay["analysis_validation"]["status"] == "valid"


def test_observation_identity_changes_with_source_or_supported_content():
    documents = {"handover": original_document("handover", PASSAGES)}
    with document_analysis_runtime(documents) as runtime:
        first, _ = run_analysis(
            runtime, documents, FixtureAnalysisClient(response_builder()),
            analysis_options=OBSERVATIONS, window_size=8,
        )
        documents["handover"]["document"]["version"] = 2
        second, _ = run_analysis(
            runtime, documents, FixtureAnalysisClient(response_builder()),
            analysis_options=OBSERVATIONS, window_size=8,
        )
        assert {record["record_id"] for record in first["authoritative_result"]["value"]}.isdisjoint(
            record["record_id"] for record in second["authoritative_result"]["value"]
        )


def test_unsupported_observation_is_not_promoted_by_a_shared_subject():
    documents = {"handover": original_document("handover", PASSAGES)}
    with document_analysis_runtime(documents) as runtime:
        result, _ = run_analysis(
            runtime, documents, FixtureAnalysisClient(response_builder(unsupported_page=8)),
            analysis_options=OBSERVATIONS, window_size=8,
        )
        assert result["analysis_validation"]["status"] == "partial"
        assert result["analysis_validation"]["unresolved_candidate_count"] == 1
        records = result["authoritative_result"]["value"]
        assert len(records) == 5
        assert FINDINGS[3][2] in {record["values"]["finding"] for record in records}
        assert FINDINGS[5][2] not in {record["values"]["finding"] for record in records}


def test_invalid_evidence_remains_unresolved_in_observation_mode():
    documents = {"handover": original_document("handover", PASSAGES)}
    build = response_builder()

    def unmatched(prompt):
        payload = json.loads(build(prompt))
        payload["findings"][-1]["evidence"][0]["quote"] = "This passage is absent from the source."
        return json.dumps(payload)

    with document_analysis_runtime(documents) as runtime:
        result, _ = run_analysis(
            runtime, documents, FixtureAnalysisClient(unmatched),
            analysis_options=OBSERVATIONS, window_size=8,
        )
        assert result["analysis_validation"]["status"] == "partial"
        assert len(result["authoritative_result"]["value"]) == 5
        assert any(
            issue["code"] == "unmatched_evidence"
            for issue in result["analysis_validation"]["issues"]
        )


def test_contradictory_source_statements_remain_attributed_observations():
    documents = {"notice": original_document("notice", [
        "Required termination notice is 30 days.",
        "Required termination notice is 90 days.",
    ])}
    with document_analysis_runtime(documents) as runtime:
        result, _ = run_analysis(runtime, documents, analysis_options=OBSERVATIONS)
        assert result["analysis_validation"]["status"] == "valid"
        records = result["authoritative_result"]["value"]
        assert {record["values"]["notice_days"] for record in records} == {30, 90}
        assert all(record["evidence_refs"] for record in records)
        assert any(
            check["name"] == "factual_accuracy_and_entailment" and check["status"] == "not_performed"
            for check in result["analysis_validation"]["checks"]
        )


@pytest.mark.parametrize("extra", [
    {"required_fields": ["amount"]},
    {"transformation_spec": {"computed_columns": [{"name": "amount", "expression": "1 + 2"}]}},
])
def test_observation_mode_rejects_reconciled_field_and_calculation_requirements(extra):
    with document_analysis_runtime({}) as runtime:
        with pytest.raises(ValueError):
            runtime.results.normalize_analysis_options({**OBSERVATIONS, **extra})


def test_semantics_are_explicit_and_legacy_normalization_stays_unchanged():
    with document_analysis_runtime({}) as runtime:
        legacy = runtime.results.normalize_analysis_options()
        assert legacy["version"] == "analysis-options-v1"
        assert legacy["mode"] == "narrative_findings"
        explicit = runtime.results.normalize_analysis_options(RECORDS)
        assert explicit["version"] == "analysis-options-v2"
        assert explicit["mode"] == "reconciled_records"
        for invalid in (
            {"version": "analysis-options-v1", "mode": "source_observations"},
            {"version": "analysis-options-v2", "mode": "narrative_findings"},
            {"version": "analysis-options-v2", "mode": "guess_from_prompt"},
        ):
            with pytest.raises(ValueError):
                runtime.results.normalize_analysis_options(invalid)


def test_observation_plans_cannot_declare_a_reconciled_records_output():
    with document_analysis_runtime({}):
        registry = importlib.import_module("functions_orchestration_registry")
        schema = importlib.import_module("functions_orchestration_schema")
        capability = registry.get_capability("document_analyze")
        required, optional = registry.get_capability_result_outputs(
            capability, {"analysis_options": OBSERVATIONS},
        )
        assert "records" not in required and "records" not in optional
        with pytest.raises(schema.PlanValidationError):
            schema._dependency_outputs(
                {"outputs": [
                    {"name": "findings", "kind": "records-v1"},
                    {"name": "coverage", "kind": "structured-v1"},
                    {"name": "records", "kind": "records-v1"},
                ]}, capability, {}, {"analysis_options": OBSERVATIONS},
            )


@pytest.mark.parametrize("prior_options", [None, OBSERVATIONS, RECORDS])
def test_draft_edits_preserve_existing_analysis_semantics_when_the_model_omits_them(prior_options):
    with document_analysis_runtime({}):
        planner = import_app_module("functions_orchestration_planner")
        prior = {"step_id": "analyze", "capability_id": "document_analyze", "arguments": {}}
        if prior_options is not None:
            prior["arguments"]["analysis_options"] = deepcopy(prior_options)
        raw = {"steps": [{
            "step_id": "analyze", "capability_id": "document_analyze",
            "arguments": {"analysis_prompt": "Describe the source."},
        }]}
        before = deepcopy(raw)
        result = planner._with_analysis_semantics(raw, {"current_plan": {"steps": [prior]}})
        assert result["steps"][0]["arguments"].get("analysis_options") == prior_options
        assert raw == before


def test_new_analysis_work_in_a_draft_uses_observations_without_overwriting_explicit_options():
    with document_analysis_runtime({}):
        planner = import_app_module("functions_orchestration_planner")
        raw = {"steps": [
            {"step_id": "new-analysis", "capability_id": "document_analyze", "arguments": {}},
            {"step_id": "explicit-records", "capability_id": "document_analyze",
             "arguments": {"analysis_options": deepcopy(RECORDS)}},
        ]}
        result = planner._with_analysis_semantics(raw, {"current_plan": {"steps": []}})
        assert result["steps"][0]["arguments"]["analysis_options"]["mode"] == "source_observations"
        assert result["steps"][1]["arguments"]["analysis_options"] == RECORDS


def test_observation_caveats_are_preserved_without_merging_distinct_qualifications():
    documents = {"handover": original_document("handover", PASSAGES)}
    build = response_builder(findings=[FINDINGS[3]])

    def qualified(prompt):
        payload = json.loads(build(prompt))
        first = payload["findings"][0]
        first["caveats"] = ["An owner is not named."]
        second = deepcopy(first)
        second["caveats"] = ["A completion time is not named."]
        payload["findings"].append(second)
        return json.dumps(payload)

    with document_analysis_runtime(documents) as runtime:
        result, _ = run_analysis(
            runtime, documents, FixtureAnalysisClient(qualified),
            analysis_options=OBSERVATIONS, window_size=8,
        )
        assert result["analysis_validation"]["status"] == "valid"
        records = result["authoritative_result"]["value"]
        assert len(records) == 2
        assert {tuple(record["caveats"]) for record in records} == {
            ("An owner is not named.",), ("A completion time is not named.",),
        }
