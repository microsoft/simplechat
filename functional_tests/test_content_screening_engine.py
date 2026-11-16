# test_content_screening_engine.py
"""
Functional tests for fail-closed content-screening orchestration.
Version: 0.261.114
Implemented in: 0.261.106
Enabled-empty policy coverage implemented in: 0.261.114

Verify independent mandatory checks, injected model adapters, exact required unit
coverage, grounded Unicode evidence, and rejection of silent clean verdicts (#1476).
"""

import json
import sys
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1].joinpath("application", "single_app")))

# Resolve the pure application package after adding its standalone test import path.
from content_screening.contracts import ContentUnit, DetectorResult, Finding, Subject, content_fingerprint, hash_payload
from content_screening.deterministic import evaluate_deterministic_units
from content_screening.engine import inspect_content
from content_screening.policies import compose_policy, default_policy
from content_screening.service import _validate_result

import test_content_screening_model as model_fixtures


SUBJECT = Subject("personal", "owner", "document", "1")


def policy_with_checks(*, deterministic=True, model=True):
    policy = default_policy()
    policy["enabled"] = True
    if deterministic:
        policy["rules"] = [{
            "id": "literal", "name": "Private term", "type": "literal",
            "values": ["secret"], "category": "custom", "severity": "high",
        }]
    if model:
        policy["ai"].update(
            enabled=True, model_selection={"endpoint_id": "endpoint", "model_id": "model"},
            instructions="Identify source-ranking manipulation.",
        )
    return policy


def model_pass(units, check, **_kwargs):
    window_ids = model_fixtures.screening_model.model_window_ids(units, check)
    return DetectorResult(
        "pass", required_units=len(units), completed_units=len(units),
        required_windows=len(window_ids), completed_windows=len(window_ids),
        usage={"coverage": {
            "schema_version": 1, "content_fingerprint": content_fingerprint(units),
            "rule_ids": [check["id"]], "unit_ids": [unit.unit_id for unit in units],
            "window_ids": window_ids,
        }},
    )


def model_finding(units, check, **_kwargs):
    unit = units[-1]
    evidence = "manipulation"
    start = unit.text.index(evidence)
    result = model_pass(units, check)
    result.status = "findings"
    result.findings = [Finding(
        check["id"], unit.unit_id, check["category"], check["severity"], "Review these instructions.",
        start=start, end=start + len(evidence), evidence=evidence, source="model", confidence=0.8,
    )]
    return result


class ContentScreeningEngineTests(unittest.TestCase):
    def test_empty_enabled_configuration_never_produces_a_clean_inspection(self):
        raw = {**default_policy(), "enabled": True}
        for policy in (raw, compose_policy(raw)):
            with self.subTest(effective="ai_checks" in policy):
                with patch.dict(sys.modules, {"content_screening.model": None}):
                    result = inspect_content(SUBJECT, [ContentUnit("one", "Ordinary content")], policy)
                self.assertEqual(result.status, "error")
                self.assertEqual(result.error_code, "screening_policy_empty")
                self.assertEqual(result.detectors, [])

    def _model_harness(self):
        harness = model_fixtures.ModelScreeningTests()
        self.addCleanup(harness.doCleanups)
        harness.setUp()
        return harness

    def test_deterministic_only_inspection_never_requires_model_imports(self):
        units = [ContentUnit("one", "clean text")]
        with patch.dict(sys.modules, {"content_screening.model": None}):
            result = inspect_content(SUBJECT, units, policy_with_checks(model=False))
        self.assertEqual(result.status, "pass")
        self.assertEqual(len(result.detectors), 1)
        self.assertEqual(result.units_total, 1)

    def test_saved_scanner_and_workspace_permissions_do_not_execute_disabled_ai(self):
        baseline = policy_with_checks(model=False)
        baseline["ai"]["model_selection"] = {"endpoint_id": "endpoint", "model_id": "baseline-scanner"}
        baseline["allowed_models"] = [{"endpoint_id": "endpoint", "model_id": "workspace-scanner"}]
        workspace = policy_with_checks(model=False)
        workspace["ai"]["model_selection"] = baseline["allowed_models"][0].copy()
        for additions in (None, workspace):
            with self.subTest(workspace=additions is not None):
                effective = compose_policy(baseline, additions)
                self.assertEqual(effective["ai_checks"], [])
                with patch.dict(sys.modules, {"content_screening.model": None}):
                    result = inspect_content(SUBJECT, [ContentUnit("one", "secret")], effective)
                self.assertEqual(result.status, "findings")
                self.assertTrue(result.findings)
                self.assertTrue(all(finding.source == "deterministic" for finding in result.findings))

    def test_fingerprints_match_complete_content_and_persisted_policy_snapshot(self):
        units = [ContentUnit("one", "😀 clean text", {"page": 1})]
        policy = compose_policy(policy_with_checks(model=False))
        result = inspect_content(SUBJECT.to_dict(), units, policy)
        self.assertEqual(result.content_fingerprint, content_fingerprint(units))
        self.assertEqual(result.policy_fingerprint, hash_payload(policy))

    def test_service_validator_receives_the_exact_passed_policy_fingerprint(self):
        units = [ContentUnit("one", "clean text")]
        raw = policy_with_checks(model=False)
        for policy in (raw, compose_policy(raw)):
            with self.subTest(effective="ai_checks" in policy):
                snapshot = deepcopy(policy)
                result = inspect_content(SUBJECT, units, policy)
                self.assertEqual(result.status, "pass")
                self.assertEqual(result.policy_fingerprint, hash_payload(snapshot))
                self.assertEqual(policy, snapshot)
                self.assertIsNone(_validate_result(result, units, policy))

    def test_native_table_cells_and_source_metadata_keep_complete_service_coverage(self):
        units = [ContentUnit("schema", "Column: details", {"kind": "table_schema"})]
        units.extend(ContentUnit(
            f"cell-{row}", "" if row % 3 == 0 else f"value {row}",
            {"kind": "table_cell", "sheet_index": 1, "sheet": "Sheet 1", "row": row, "column": 1},
        ) for row in range(1, 21))
        units.extend([
            ContentUnit("last-cell", "😀 secret", {
                "kind": "table_cell", "sheet_index": 1, "sheet": "Sheet 1", "row": 21, "column": 1,
            }),
            ContentUnit("title", "secret report", {"kind": "source_metadata", "field": "title"}),
            ContentUnit("summary", "manipulation of source ranking", {
                "kind": "source_metadata", "field": "summary",
            }),
        ])
        received_units = []

        def evaluate(received, check):
            received_units.extend(unit.to_dict() for unit in received)
            return model_finding(received, check)

        policy = compose_policy(policy_with_checks())
        result = inspect_content(SUBJECT, units, policy, model_evaluator=evaluate)
        self.assertEqual(result.status, "findings")
        self.assertEqual(received_units, [unit.to_dict() for unit in units])
        self.assertEqual({finding.unit_id for finding in result.findings}, {"last-cell", "title", "summary"})
        self.assertEqual(result.content_fingerprint, content_fingerprint(units))
        self.assertNotEqual(result.content_fingerprint, content_fingerprint(units[:-2]))
        self.assertEqual(result.policy_fingerprint, hash_payload(policy))
        detector_fields = set(DetectorResult("pass").to_dict())
        for detector in result.detectors:
            self.assertTrue(detector_fields.issubset(detector))
            self.assertEqual(detector["required_units"], len(units))
            self.assertEqual(detector["completed_units"], len(units))
            self.assertEqual(detector["completed_windows"], detector["required_windows"])
            self.assertIsNone(detector["error_code"])
        self.assertIsNone(_validate_result(result, units, policy))

    def test_optional_model_adapter_receives_stable_check_and_all_units(self):
        units = [ContentUnit("one", "first"), ContentUnit("two", "tail")]
        calls = []

        def evaluate(received, check):
            calls.append(([unit.unit_id for unit in received], check["id"]))
            return model_pass(received, check)

        result = inspect_content(SUBJECT, units, policy_with_checks(), model_evaluator=evaluate)
        self.assertEqual(result.status, "pass")
        self.assertEqual(calls, [(["one", "two"], "global:ai")])

    def test_default_model_evaluator_is_imported_lazily(self):
        module = types.ModuleType("content_screening.model")
        module.evaluate_model_units = model_pass
        module.build_model_windows = model_fixtures.screening_model.build_model_windows
        with patch.dict(sys.modules, {"content_screening.model": module}):
            result = inspect_content(SUBJECT, [ContentUnit("one", "text")], policy_with_checks(deterministic=False))
        self.assertEqual(result.status, "pass")

    def test_real_model_adapter_preserves_service_contract_and_all_canonical_units(self):
        harness = self._model_harness()
        harness.route_client.responder = (
            lambda envelope, _number: model_fixtures.match_payload(envelope, marker="manipulation")
        )
        policy = policy_with_checks()
        policy["ai"].update(
            model_selection={"endpoint_id": "scanner-endpoint", "model_id": "scanner-model"},
            window_unit="chunks", window_size=2, max_characters=256, overlap_characters=16,
        )
        policy = compose_policy(policy)
        units = [
            ContentUnit("intro", "Ordinary introduction."),
            model_fixtures.table_unit("last-cell", "😀 secret " + "a" * 540 + " manipulation"),
            model_fixtures.table_unit("empty-cell", "", row=2),
            ContentUnit("title", "Ordinary report", {"kind": "source_metadata", "field": "title"}),
        ]
        result = inspect_content(SUBJECT, units, policy)
        self.assertEqual(result.status, "findings")
        self.assertEqual({item.source for item in result.findings}, {"deterministic", "model"})
        self.assertEqual({item.unit_id for item in result.findings}, {"last-cell"})
        model_finding_result = next(item for item in result.findings if item.source == "model")
        self.assertEqual(model_finding_result.evidence, "manipulation")
        self.assertEqual(model_finding_result.start, units[1].text.index("manipulation"))
        self.assertEqual({
            part["unit_id"] for envelope in harness.route_client.envelopes for part in envelope["units"]
        }, {unit.unit_id for unit in units})
        self.assertEqual(result.usage["requests"], len(harness.route_client.requests))
        self.assertEqual(result.usage["reported_requests"], result.usage["requests"])
        self.assertEqual(result.usage["input_tokens"], 7 * result.usage["requests"])
        self.assertEqual(result.usage["output_tokens"], 3 * result.usage["requests"])
        self.assertEqual(result.usage["budgeted_tokens"], result.usage["total_tokens"])
        self.assertTrue(harness.route_client.closed)
        self.assertIsNone(_validate_result(result, units, policy))

    def test_real_model_adapter_missing_usage_retains_explicit_budget_reservations(self):
        harness = self._model_harness()
        harness.route_client.responder = lambda envelope, _number: model_fixtures.completion(
            model_fixtures.clean_payload(envelope), usage=False,
        )
        policy = policy_with_checks(deterministic=False)
        policy["ai"]["model_selection"] = {"endpoint_id": "scanner-endpoint", "model_id": "scanner-model"}
        result = inspect_content(SUBJECT, [ContentUnit("one", "Ordinary text.")], compose_policy(policy))
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.usage["requests"], 1)
        self.assertEqual(result.usage["reported_requests"], 0)
        self.assertEqual(result.usage["total_tokens"], 0)
        self.assertGreater(result.usage["budgeted_tokens"], 0)
        self.assertGreater(result.usage["input_characters"], 0)
        self.assertGreater(result.usage["output_characters"], 0)

    def test_model_budget_usage_counters_reject_malformed_values(self):
        for field in ("reported_requests", "budgeted_tokens", "input_characters", "output_characters"):
            for value in (-1, True, float("nan")):
                def evaluate(units, check):
                    result = model_pass(units, check)
                    result.usage[field] = value
                    return result

                with self.subTest(field=field, value=value):
                    result = inspect_content(
                        SUBJECT, [ContentUnit("one", "text")], policy_with_checks(),
                        model_evaluator=evaluate,
                    )
                    self.assertEqual(result.status, "error")

    def test_clean_model_does_not_cancel_deterministic_findings(self):
        result = inspect_content(
            SUBJECT, [ContentUnit("one", "secret")], policy_with_checks(), model_evaluator=model_pass,
        )
        self.assertEqual(result.status, "findings")
        self.assertEqual({finding.source for finding in result.findings}, {"deterministic"})

    def test_clean_deterministic_result_does_not_cancel_model_findings(self):
        result = inspect_content(
            SUBJECT, [ContentUnit("one", "😀 manipulation")], policy_with_checks(), model_evaluator=model_finding,
        )
        self.assertEqual(result.status, "findings")
        self.assertEqual(result.findings[0].start, 2)
        self.assertEqual(result.findings[0].source, "model")

    def test_findings_from_both_detectors_are_unioned(self):
        result = inspect_content(
            SUBJECT, [ContentUnit("one", "secret manipulation")], policy_with_checks(), model_evaluator=model_finding,
        )
        self.assertEqual(result.status, "findings")
        self.assertEqual(len(result.findings), 2)
        self.assertEqual({finding.source for finding in result.findings}, {"deterministic", "model"})

    def test_baseline_and_workspace_models_are_both_required(self):
        baseline = policy_with_checks()
        workspace = policy_with_checks(deterministic=False)
        workspace["ai"]["instructions"] = "Identify credentials."
        calls = []

        def evaluate(units, check):
            calls.append(check["id"])
            return model_finding(units, check) if check["id"] == "global:ai" else model_pass(units, check)

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "manipulation")],
            compose_policy(baseline, workspace), model_evaluator=evaluate,
        )
        self.assertEqual(calls, ["global:ai", "workspace:ai"])
        self.assertEqual(result.status, "findings")
        self.assertEqual(len(result.detectors), 3)

    def test_missing_bad_and_partial_adapter_outputs_never_pass(self):
        units = [ContentUnit("one", "text"), ContentUnit("two", "tail")]
        values = [None, {}, "pass"]
        for field, value in (
            ("status", "unknown"), ("status", ["pass"]), ("required_units", 1), ("required_units", True),
            ("completed_units", 1), ("completed_units", 3), ("required_windows", 0),
            ("completed_windows", 0), ("required_windows", 3), ("error_code", ""),
            ("usage", None), ("findings", None),
        ):
            result = model_pass(units, compose_policy(policy_with_checks(deterministic=False))["ai_checks"][0])
            setattr(result, field, value)
            values.append(result)
        for value in values:
            with self.subTest(value=value):
                result = inspect_content(
                    SUBJECT, units, policy_with_checks(deterministic=False),
                    model_evaluator=lambda _units, _check: value,
                )
                self.assertIn(result.status, ("incomplete", "error"))

    def test_findings_status_without_findings_is_invalid(self):
        def evaluate(units, check):
            result = model_pass(units, check)
            result.status = "findings"
            return result

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "text")], policy_with_checks(), model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "error")

    def test_clean_status_with_findings_is_an_error_but_retains_evidence(self):
        def evaluate(units, check):
            result = model_finding(units, check)
            result.status = "pass"
            return result

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "manipulation")], policy_with_checks(), model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(len(result.findings), 1)

    def test_partial_model_failure_retains_deterministic_findings(self):
        def evaluate(units, _check):
            return DetectorResult("incomplete", required_units=len(units), error_code="provider timeout with secret")

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "secret")], policy_with_checks(), model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(len(result.findings), 1)
        self.assertNotIn("provider timeout", json.dumps(result.to_dict()))

    def test_stable_model_failure_codes_are_preserved_for_recovery(self):
        codes = (
            "model_check_disabled", "model_invalid_input", "model_configuration_unavailable",
            "model_protocol_unsupported", "model_input_limit", "model_time_limit",
            "model_token_limit", "model_response_limit", "model_finding_limit",
            "model_timeout", "model_capacity_exhausted", "model_provider_error",
            "model_refused", "model_invalid_response", "model_invalid_evidence",
            "model_invalid_usage", "model_incomplete_response", "model_incomplete_coverage",
            "model_cancelled", "model_progress_error", "model_evaluation_error",
        )
        for code in codes:
            def evaluate(units, _check):
                return DetectorResult("incomplete", required_units=len(units), error_code=code)

            with self.subTest(code=code):
                result = inspect_content(
                    SUBJECT, [ContentUnit("one", "text")], policy_with_checks(), model_evaluator=evaluate,
                )
                self.assertEqual(result.status, "incomplete")
                self.assertEqual(result.detectors[-1]["error_code"], code)

    def test_model_prefix_alone_does_not_allow_provider_diagnostics(self):
        def evaluate(units, _check):
            return DetectorResult(
                "error", required_units=len(units), error_code="model_provider_error_with_sensitive_detail",
            )

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "text")], policy_with_checks(), model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.detectors[-1]["error_code"], "screening_detector_failed")
        self.assertNotIn("sensitive_detail", json.dumps(result.to_dict()))

    def test_deterministic_cancellation_prevents_subsequent_model_calls(self):
        def evaluate(_units, _check):
            self.fail("A cancelled inspection must not initiate model evaluation.")

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "text")], policy_with_checks(),
            model_evaluator=evaluate, on_progress=lambda _event: False,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.error_code, "screening_cancelled")
        self.assertEqual(len(result.detectors), 2)
        self.assertTrue(all(detector["completed_units"] == 0 for detector in result.detectors))

    def test_model_cancellation_response_is_forwarded_and_stops_other_checks(self):
        calls = []

        def evaluate(units, check, *, on_progress):
            calls.append(check["id"])
            self.assertIs(on_progress({"required_units": len(units), "completed_units": 0}), False)
            return DetectorResult("incomplete", required_units=len(units), error_code="model_cancelled")

        policy = compose_policy(
            policy_with_checks(deterministic=False), policy_with_checks(deterministic=False),
        )
        result = inspect_content(
            SUBJECT, [ContentUnit("one", "text")], policy, model_evaluator=evaluate,
            on_progress=lambda _event: False,
        )
        self.assertEqual(calls, ["global:ai"])
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.error_code, "screening_cancelled")
        self.assertEqual(len(result.detectors), 2)
        self.assertEqual(result.detectors[0]["error_code"], "model_cancelled")
        self.assertEqual(result.detectors[1]["error_code"], "screening_cancelled")

    def test_required_model_still_runs_after_a_deterministic_timeout(self):
        policy = policy_with_checks()
        policy["rules"] = [{"id": "pathological", "type": "regex", "pattern": "(a+)+$"}]
        policy["limits"]["regex_timeout_seconds"] = 0.01
        result = inspect_content(
            SUBJECT, [ContentUnit("one", "a" * 30000 + "! manipulation")],
            policy, model_evaluator=model_finding,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(len(result.detectors), 2)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].source, "model")
        self.assertEqual(result.detectors[0]["error_code"], "screening_regex_timeout")

    def test_provider_exceptions_cannot_become_clean_or_leak_diagnostics(self):
        for exception in (RuntimeError("private-api-token"), TimeoutError("private-api-token")):
            def evaluate(_units, _check):
                raise exception

            with self.subTest(exception=type(exception).__name__):
                result = inspect_content(
                    SUBJECT, [ContentUnit("one", "text")], policy_with_checks(), model_evaluator=evaluate,
                )
                self.assertIn(result.status, ("error", "incomplete"))
                self.assertNotIn("private-api-token", json.dumps(result.to_dict()))

    def test_unknown_and_ungrounded_findings_are_rejected(self):
        changes = (
            {"rule_id": "unknown"}, {"unit_id": "unknown"}, {"category": "different"}, {"severity": "low"},
            {"evidence": "not in content"}, {"start": 1000, "end": 1012},
            {"start": 1, "end": 13}, {"source": "deterministic"},
        )
        for change in changes:
            def evaluate(units, check):
                result = model_finding(units, check)
                values = result.findings[0].to_dict()
                values.pop("finding_id")
                result.findings = [Finding(**{**values, **change})]
                return result

            with self.subTest(change=change):
                result = inspect_content(
                    SUBJECT, [ContentUnit("one", "manipulation")], policy_with_checks(), model_evaluator=evaluate,
                )
                self.assertEqual(result.status, "error")
                self.assertEqual(result.findings, [])

    def test_ambiguous_grounded_evidence_can_require_whole_unit_review(self):
        def evaluate(units, check):
            result = model_finding(units, check)
            values = result.findings[0].to_dict()
            values.pop("finding_id")
            result.findings = [Finding(**{**values, "start": None, "end": None})]
            return result

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "manipulation then manipulation")],
            policy_with_checks(), model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "findings")
        self.assertIsNone(result.findings[0].start)

    def test_duplicate_findings_are_suppressed_without_merging_distinct_checks(self):
        def evaluate(units, check):
            result = model_finding(units, check)
            result.findings *= 2
            return result

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "manipulation")],
            compose_policy(policy_with_checks(), policy_with_checks(deterministic=False)),
            model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "findings")
        self.assertEqual(len(result.findings), 2)
        self.assertEqual({finding.rule_id for finding in result.findings}, {"global:ai", "workspace:ai"})

    def test_malformed_or_absent_content_and_inactive_policies_never_pass(self):
        unit = ContentUnit("one", "text")
        for units in ([], [unit, unit], [ContentUnit("blank", "")], None):
            with self.subTest(units=units):
                self.assertEqual(inspect_content(SUBJECT, units, policy_with_checks(model=False)).status, "error")
        self.assertEqual(inspect_content({}, [unit], policy_with_checks(model=False)).status, "error")
        self.assertEqual(inspect_content(SUBJECT, [unit], {"enabled": "false"}).status, "error")
        self.assertEqual(inspect_content(SUBJECT, [unit], default_policy()).status, "incomplete")

    def test_effective_policy_tampering_and_absent_mandatory_rules_are_rejected(self):
        effective = compose_policy(policy_with_checks(model=False))
        effective["rules"] = []
        result = inspect_content(SUBJECT, [ContentUnit("one", "text")], effective)
        self.assertEqual(result.status, "error")

    def test_declared_input_budget_prevents_model_invocation(self):
        policy = policy_with_checks()
        policy["limits"]["max_total_characters"] = 5

        def evaluate(_units, _check):
            self.fail("Over-budget content must not be sent to the model.")

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "long content")], policy, model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "incomplete")

    def test_deterministic_coverage_cannot_claim_omitted_units(self):
        units = [ContentUnit("one", "text"), ContentUnit("two", "tail")]
        policy = compose_policy(policy_with_checks(model=False))
        detector = evaluate_deterministic_units(units, policy["rules"])
        detector.usage["coverage"]["unit_ids"] = ["one", "one"]
        with patch("content_screening.engine.evaluate_deterministic_units", return_value=detector):
            result = inspect_content(SUBJECT, units, policy)
        self.assertEqual(result.status, "incomplete")

    def test_explicit_model_coverage_must_match_input_revision_and_unit_ids(self):
        for change in (
            {"content_fingerprint": "different"},
            {"unit_ids": ["one", "one"]},
            {"window_ids": ["window-1", "window-1"]},
        ):
            def evaluate(units, check):
                result = model_pass(units, check)
                result.usage["coverage"].update(change)
                return result

            with self.subTest(change=change):
                result = inspect_content(
                    SUBJECT, [ContentUnit("one", "text"), ContentUnit("two", "tail")],
                    policy_with_checks(), model_evaluator=evaluate,
                )
                self.assertEqual(result.status, "incomplete")

    def test_explicit_null_coverage_is_invalid(self):
        def evaluate(units, check):
            result = model_pass(units, check)
            result.usage["coverage"] = None
            return result

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "text")], policy_with_checks(), model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "incomplete")

    def test_model_pass_without_an_explicit_coverage_manifest_is_incomplete(self):
        def evaluate(units, check):
            result = model_pass(units, check)
            result.usage.pop("coverage")
            return result

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "secret")], policy_with_checks(), model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.detectors[-1]["error_code"], "screening_coverage_incomplete")
        self.assertEqual(len(result.findings), 1)
        self.assertNotIn("coverage", result.detectors[-1]["usage"])

    def test_model_coverage_requires_exact_schema_rule_and_source_window_order(self):
        mutations = (
            lambda coverage: coverage.update(schema_version=True),
            lambda coverage: coverage.update(schema_version=2),
            lambda coverage: coverage.update(rule_ids=["another-rule"]),
            lambda coverage: coverage["unit_ids"].reverse(),
            lambda coverage: coverage["window_ids"].reverse(),
            lambda coverage: coverage.update(provider_detail="private-diagnostic"),
        )
        units = [
            ContentUnit("one", "first", {"page_number": 1}),
            ContentUnit("two", "tail", {"page_number": 2}),
        ]
        for index, mutate in enumerate(mutations):
            def evaluate(received, check):
                result = model_pass(received, check)
                mutate(result.usage["coverage"])
                return result

            with self.subTest(case=index):
                result = inspect_content(
                    SUBJECT, units, policy_with_checks(deterministic=False), model_evaluator=evaluate,
                )
                self.assertEqual(result.status, "incomplete")
                self.assertNotIn("coverage", result.detectors[0]["usage"])
                self.assertNotIn("private-diagnostic", json.dumps(result.to_dict()))

    def test_model_planner_must_cover_tails_gaps_and_empty_units_with_bounded_ranges(self):
        units = [ContentUnit("one", "x" * 600), ContentUnit("empty", "")]
        raw = policy_with_checks(deterministic=False)
        raw["ai"].update(max_characters=256, overlap_characters=0)
        policy = compose_policy(raw)
        check = policy["ai_checks"][0]
        prepared = model_pass(units, check)
        original_plan = model_fixtures.screening_model.build_model_windows(units, check)
        for failure in ("tail", "gap", "empty", "oversized", "boolean"):
            plan = deepcopy(original_plan)
            text_ranges = [
                part for window in plan for part in window["unit_ranges"] if part["unit_id"] == "one"
            ]
            if failure == "tail":
                text_ranges[-1]["end"] -= 1
            elif failure == "gap":
                text_ranges[1]["start"] += 1
            elif failure == "empty":
                for window in plan:
                    for part in window["unit_ranges"]:
                        if part["unit_id"] == "empty":
                            part.update(unit_id="one", start=0, end=1)
            elif failure == "oversized":
                text_ranges[0]["end"] += 1
            else:
                text_ranges[0]["start"] = False
            with (
                self.subTest(failure=failure),
                patch("content_screening.model.build_model_windows", return_value=plan),
            ):
                result = inspect_content(
                    SUBJECT, units, policy, model_evaluator=lambda _units, _check: deepcopy(prepared),
                )
                self.assertEqual(result.status, "incomplete")
                self.assertNotIn("coverage", result.detectors[0]["usage"])

    def test_partial_model_manifest_retains_only_independently_completed_units(self):
        units = [
            ContentUnit("one", "manipulation", {"page_number": 1}),
            ContentUnit("two", "tail", {"page_number": 2}),
        ]

        def evaluate(received, check):
            result = model_pass(received, check)
            result.status, result.error_code = "incomplete", "model_timeout"
            result.completed_units = result.completed_windows = 1
            result.usage["coverage"]["unit_ids"] = ["one"]
            result.usage["coverage"]["window_ids"] = result.usage["coverage"]["window_ids"][:1]
            result.findings = [Finding(
                check["id"], "one", check["category"], check["severity"], "Review the first page.",
                start=0, end=12, evidence="manipulation", source="model",
            )]
            return result

        policy = compose_policy(policy_with_checks(deterministic=False))
        result = inspect_content(SUBJECT, units, policy, model_evaluator=evaluate)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.detectors[0]["error_code"], "model_timeout")
        self.assertEqual(result.detectors[0]["usage"]["coverage"]["unit_ids"], ["one"])
        self.assertEqual(len(result.detectors[0]["usage"]["coverage"]["window_ids"]), 1)
        self.assertEqual(len(result.findings), 1)

    def test_progress_does_not_forward_evidence_or_provider_data(self):
        progress = []

        def evaluate(units, check, *, on_progress):
            on_progress({"status": "pass", "completed_units": 1, "evidence": "private-content"})
            result = model_pass(units, check)
            result.usage.update({"input_tokens": 10, "output_tokens": 5, "provider_body": "private-content"})
            return result

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "text")], policy_with_checks(),
            model_evaluator=evaluate, on_progress=progress.append,
        )
        self.assertEqual(result.status, "pass")
        self.assertNotIn("private-content", json.dumps(progress))
        self.assertNotIn("private-content", json.dumps(result.to_dict()))
        self.assertEqual(result.usage, {"input_tokens": 10, "output_tokens": 5})

    def test_injected_adapter_cannot_mutate_input_units_or_policy(self):
        units = [ContentUnit("one", "text", {"page": 1})]
        policy = policy_with_checks()
        original = deepcopy(policy)

        def evaluate(received, check):
            result = model_pass(received, check)
            received[0].locator["page"] = 999
            received.clear()
            check["model_selection"]["model_id"] = "different"
            return result

        result = inspect_content(SUBJECT, units, policy, model_evaluator=evaluate)
        self.assertEqual(result.status, "pass")
        self.assertEqual(units[0].locator["page"], 1)
        self.assertEqual(policy, original)

    def test_model_checks_receive_effective_limits_without_mutating_policy_snapshots(self):
        baseline = policy_with_checks()
        baseline["limits"].update(max_units=3, max_total_characters=1000)
        workspace = policy_with_checks(deterministic=False)
        workspace["limits"].update(max_units=2, max_findings=5)
        policy = compose_policy(baseline, workspace)
        snapshot = deepcopy(policy)
        received_limits = []

        def evaluate(units, check):
            received_limits.append(dict(check["limits"]))
            check["limits"]["max_units"] = 9999
            return model_pass(units, check)

        result = inspect_content(
            SUBJECT, [ContentUnit("one", "first"), ContentUnit("two", "tail")],
            policy, model_evaluator=evaluate,
        )
        self.assertEqual(result.status, "pass")
        self.assertEqual(len(received_limits), 2)
        for limits in received_limits:
            self.assertGreater(limits["max_runtime_seconds"], 0)
            self.assertLessEqual(limits["max_runtime_seconds"], snapshot["limits"]["max_runtime_seconds"])
            self.assertEqual(
                {key: value for key, value in limits.items() if key != "max_runtime_seconds"},
                {key: value for key, value in snapshot["limits"].items() if key != "max_runtime_seconds"},
            )
        self.assertLessEqual(received_limits[1]["max_runtime_seconds"], received_limits[0]["max_runtime_seconds"])
        self.assertEqual(received_limits[0]["max_units"], 2)
        self.assertEqual(received_limits[0]["max_total_characters"], 1000)
        self.assertEqual(received_limits[0]["max_findings"], 5)
        self.assertEqual(policy, snapshot)
        self.assertEqual(result.policy_fingerprint, hash_payload(snapshot))
        self.assertTrue(all("limits" not in check for check in policy["ai_checks"]))

    def test_ai_checks_share_the_remaining_inspection_deadline(self):
        clock = [100.0]
        baseline = policy_with_checks(deterministic=False)
        baseline["limits"]["max_runtime_seconds"] = 10.0
        policy = compose_policy(baseline, policy_with_checks(deterministic=False))
        budgets = []

        def evaluate(units, check):
            budgets.append((check["id"], check["limits"]["max_runtime_seconds"]))
            clock[0] += 4.0
            return model_pass(units, check)

        with patch("content_screening.engine.time.monotonic", side_effect=lambda: clock[0]):
            result = inspect_content(
                SUBJECT, [ContentUnit("one", "text")], policy, model_evaluator=evaluate,
            )
        self.assertEqual(result.status, "pass")
        self.assertEqual(budgets, [("global:ai", 10.0), ("workspace:ai", 6.0)])
        self.assertEqual(policy["limits"]["max_runtime_seconds"], 10.0)
        self.assertEqual(result.policy_fingerprint, hash_payload(policy))

    def test_an_exhausted_deadline_prevents_remaining_model_calls(self):
        clock = [100.0]
        baseline = policy_with_checks(deterministic=False)
        baseline["limits"]["max_runtime_seconds"] = 1.0
        policy = compose_policy(baseline, policy_with_checks(deterministic=False))
        calls = []

        def evaluate(units, check):
            calls.append(check["id"])
            clock[0] += 2.0
            return model_pass(units, check)

        with patch("content_screening.engine.time.monotonic", side_effect=lambda: clock[0]):
            result = inspect_content(
                SUBJECT, [ContentUnit("one", "text")], policy, model_evaluator=evaluate,
            )
        self.assertEqual(calls, ["global:ai"])
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.detectors[1]["error_code"], "screening_runtime_limit")
        self.assertEqual(result.detectors[1]["completed_units"], 0)

    def test_submillisecond_remaining_budgets_are_not_rounded_up(self):
        clock = [100.0]
        policy = policy_with_checks()
        policy["limits"]["max_runtime_seconds"] = 0.001

        def slow_composition(candidate):
            effective = compose_policy(candidate)
            clock[0] += 0.0006
            return effective

        with (
            patch("content_screening.engine.time.monotonic", side_effect=lambda: clock[0]),
            patch("content_screening.engine.compose_policy", side_effect=slow_composition),
            patch("content_screening.engine.evaluate_deterministic_units") as deterministic,
        ):
            model = unittest.mock.Mock()
            result = inspect_content(SUBJECT, [ContentUnit("one", "text")], policy, model_evaluator=model)
        deterministic.assert_not_called()
        model.assert_not_called()
        self.assertEqual(result.status, "incomplete")
        self.assertTrue(all(detector["error_code"] == "screening_runtime_limit" for detector in result.detectors))

    def test_overall_finding_budget_never_silently_drops_one_detector(self):
        policy = policy_with_checks()
        policy["limits"]["max_findings"] = 1
        result = inspect_content(
            SUBJECT, [ContentUnit("one", "secret manipulation")], policy, model_evaluator=model_finding,
        )
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(len(result.findings), 2)

    def test_bounded_deterministic_evidence_is_valid_for_long_exact_spans(self):
        policy = policy_with_checks(model=False)
        policy["rules"] = [{"id": "long", "type": "regex", "pattern": "q{600}"}]
        result = inspect_content(SUBJECT, [ContentUnit("one", "q" * 600)], policy)
        self.assertEqual(result.status, "findings")
        self.assertEqual(result.findings[0].end, 600)


if __name__ == "__main__":
    unittest.main()
