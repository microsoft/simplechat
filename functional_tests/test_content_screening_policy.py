# test_content_screening_policy.py
"""
Functional tests for mandatory content-screening policy composition.
Version: 0.261.106
Implemented in: 0.261.106

Validate explicit opt-in, strict configuration bounds, approved model selection,
stable policy fingerprints, and non-sensitive baseline summaries for issue #1476.
"""

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].joinpath("application", "single_app")))

# Resolve the pure application package after adding its standalone test import path.
from content_screening.contracts import ScreeningValidationError
from content_screening.policies import (
    AI_STARTER_CRITERIA,
    AI_STARTER_TEMPLATES,
    DEFAULT_LIMITS,
    MAX_LITERAL_CHARACTERS,
    MAX_PATTERN_CHARACTERS,
    STARTER_RULE_TEMPLATES,
    compose_policy,
    default_policy,
    normalize_effective_policy,
    normalize_policy,
    policy_is_active,
    safe_baseline_summary,
    starter_templates,
)


def literal_rule(rule_id="secret"):
    return {
        "id": rule_id, "name": "Private value", "type": "literal", "enabled": True,
        "severity": "high", "category": "custom", "values": ["private-value"],
        "case_sensitive": False, "whole_word": False,
    }


def enabled_policy():
    result = default_policy()
    result.update(enabled=True, rules=[literal_rule()])
    return result


def add_ai(policy, model="scanner"):
    policy["ai"].update(
        enabled=True, model_selection={"endpoint_id": "endpoint", "model_id": model},
        instructions="Look for source-ranking manipulation.",
    )
    return policy


class ContentScreeningPolicyTests(unittest.TestCase):
    def test_defaults_require_explicit_admin_selection(self):
        first = default_policy()
        self.assertFalse(first["enabled"])
        self.assertEqual(first["rules"], [])
        self.assertFalse(first["ai"]["enabled"])
        self.assertFalse(policy_is_active(compose_policy(first)))
        first["limits"]["max_units"] = 1
        self.assertEqual(default_policy()["limits"], DEFAULT_LIMITS)
        first["enabled"] = True
        with self.assertRaises(ScreeningValidationError):
            normalize_policy(first)

    def test_disabling_all_checks_cannot_enable_an_empty_gate(self):
        policy = enabled_policy()
        policy["rules"][0]["enabled"] = False
        with self.assertRaises(ScreeningValidationError):
            normalize_policy(policy)

    def test_malformed_objects_never_become_disabled_defaults(self):
        for value in (None, False, "", [], {"rules": None}, {"ai": None}, {"limits": None}, {"unknown": True}):
            with self.subTest(value=value), self.assertRaises(ScreeningValidationError):
                normalize_policy(value)

    def test_boolean_switches_are_not_coerced(self):
        for value in ("false", "true", 0, 1, None, [], {}):
            for target in ("policy", "ai", "rule", "case_sensitive", "whole_word"):
                policy = enabled_policy()
                if target == "policy":
                    policy["enabled"] = value
                elif target == "ai":
                    policy["ai"]["enabled"] = value
                elif target == "rule":
                    policy["rules"][0]["enabled"] = value
                else:
                    policy["rules"][0][target] = value
                with self.subTest(value=value, target=target), self.assertRaises(ScreeningValidationError):
                    normalize_policy(policy)

    def test_schema_rule_types_and_duplicate_ids_are_strict(self):
        values = []
        for schema in (True, "1", 0, 2):
            values.append({**enabled_policy(), "schema_version": schema})
        for rule_change in (
            {"type": "unknown"}, {"type": []}, {"severity": "urgent"}, {"category": "<script>"},
            {"id": "global:secret"}, {"values": "private-value"}, {"values": []}, {"values": [123]},
            {"name": "x" * 121}, {"values": ["x" * (MAX_LITERAL_CHARACTERS + 1)]},
            {"required": False},
        ):
            policy = enabled_policy()
            policy["rules"][0].update(rule_change)
            values.append(policy)
        duplicate = enabled_policy()
        duplicate["rules"].append(deepcopy(duplicate["rules"][0]))
        values.append(duplicate)
        for policy in values:
            with self.subTest(policy=policy), self.assertRaises(ScreeningValidationError):
                normalize_policy(policy)

    def test_unicode_literals_are_not_stripped_or_normalized(self):
        policy = enabled_policy()
        policy["rules"][0]["values"] = [" 😀 café ", "e\u0301", "é", "e\u0301"]
        normalized = normalize_policy(policy)
        self.assertEqual(normalized["rules"][0]["values"], sorted({" 😀 café ", "e\u0301", "é"}))
        self.assertEqual(normalized, normalize_policy(normalized))

    def test_regex_syntax_empty_matches_flags_and_size_are_validated(self):
        for pattern in (
            "[", "", "a*", "^", "(?r)needle", "(?V0)needle", "(?a)needle",
            "x{1000000}", "x" * (MAX_PATTERN_CHARACTERS + 1),
        ):
            policy = enabled_policy()
            policy["rules"] = [{
                "id": "pattern", "name": "Pattern", "type": "regex", "pattern": pattern,
            }]
            with self.subTest(pattern=pattern), self.assertRaises(ScreeningValidationError):
                normalize_policy(policy)

    def test_disabled_rules_are_still_validated(self):
        policy = default_policy()
        policy["rules"] = [{"id": "invalid", "type": "regex", "enabled": False, "pattern": "["}]
        with self.assertRaises(ScreeningValidationError):
            normalize_policy(policy)

    def test_execution_caps_reject_boolean_nan_and_out_of_range_values(self):
        for key, value in (
            ("max_units", True), ("max_units", 0), ("max_units", 100001),
            ("max_findings", 1001), ("max_windows", -1), ("max_total_characters", 20000001),
            ("regex_timeout_seconds", float("nan")), ("regex_timeout_seconds", 0),
            ("regex_timeout_seconds", "0.1"), ("max_runtime_seconds", float("inf")),
        ):
            policy = enabled_policy()
            policy["limits"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ScreeningValidationError):
                normalize_policy(policy)

    def test_ai_selection_and_windowing_bounds_are_strict(self):
        for change in (
            {"model_selection": {}}, {"model_selection": {"endpoint_id": "endpoint"}},
            {"model_selection": {"endpoint_id": "endpoint", "model_id": False}},
            {"instructions": ""}, {"instructions": "x" * 12001},
            {"window_unit": "documents"}, {"window_size": True}, {"window_size": 0},
            {"window_size": 21}, {"max_characters": 255}, {"max_characters": 64001},
            {"max_characters": 256, "overlap_characters": 256}, {"overlap_characters": -1},
            {"provider_url": "not-an-approved-reference"},
        ):
            policy = add_ai(enabled_policy())
            policy["ai"].update(change)
            with self.subTest(change=change), self.assertRaises(ScreeningValidationError):
                normalize_policy(policy)

    def test_all_starter_rules_are_selectable_but_not_automatically_required(self):
        policy = default_policy()
        policy.update(enabled=True, rules=list(deepcopy(STARTER_RULE_TEMPLATES).values()))
        self.assertEqual(len(normalize_policy(policy)["rules"]), len(STARTER_RULE_TEMPLATES))
        self.assertEqual(default_policy()["rules"], [])

    def test_disabled_ai_uses_empty_model_references_not_null(self):
        policy = default_policy()
        self.assertEqual(normalize_policy(policy)["ai"]["model_selection"], {"endpoint_id": "", "model_id": ""})
        policy["ai"]["model_selection"] = None
        with self.assertRaises(ScreeningValidationError):
            normalize_policy(policy)

    def test_template_envelope_has_all_rule_types_and_named_ai_criteria(self):
        templates = starter_templates()
        self.assertEqual(set(templates), {"rules", "packs", "ai"})
        self.assertEqual({rule["type"] for rule in templates["rules"].values()}, {"pii", "regex", "literal"})
        self.assertEqual(set(templates["ai"]), set(AI_STARTER_CRITERIA))
        for name, template in templates["ai"].items():
            self.assertEqual(set(template), {"name", "instructions"})
            self.assertTrue(template["name"].strip())
            self.assertEqual(template["instructions"], AI_STARTER_CRITERIA[name])
        for rule_ids in templates["packs"].values():
            self.assertIsInstance(rule_ids, list)
            self.assertTrue(all(rule_id in templates["rules"] for rule_id in rule_ids))

    def test_template_edits_and_generated_rule_ids_do_not_change_backend_defaults(self):
        templates = starter_templates()
        literal = templates["rules"]["confidentiality_markers"]
        literal["id"] = "550e8400-e29b-41d4-a716-446655440000"
        literal["values"] = ["workspace-specific value"]
        policy = default_policy()
        policy.update(enabled=True, rules=[literal])
        self.assertEqual(normalize_policy(policy)["rules"][0]["id"], literal["id"])
        templates["ai"]["prompt_manipulation_v1"]["instructions"] = "Edited criteria."
        templates["packs"]["structured_pii_v1"].clear()
        fresh = starter_templates()
        self.assertEqual(fresh["rules"], STARTER_RULE_TEMPLATES)
        self.assertEqual(fresh["ai"], AI_STARTER_TEMPLATES)
        self.assertTrue(fresh["packs"]["structured_pii_v1"])
        self.assertNotIn("workspace-specific value", json.dumps(fresh))

    def test_workspace_cannot_disable_or_replace_baseline_rules(self):
        baseline = enabled_policy()
        workspace = enabled_policy()
        workspace["rules"][0]["values"] = ["workspace-value"]
        effective = compose_policy(baseline, workspace)
        self.assertEqual([rule["id"] for rule in effective["rules"]], ["global:secret", "workspace:secret"])
        self.assertEqual(effective["rules"][0]["values"], ["private-value"])
        self.assertTrue(all(rule["required"] for rule in effective["rules"]))
        workspace["enabled"] = False
        effective = compose_policy(baseline, workspace)
        self.assertEqual([rule["id"] for rule in effective["rules"]], ["global:secret"])
        self.assertTrue(policy_is_active(effective))

    def test_global_off_cannot_be_activated_by_a_workspace(self):
        baseline = default_policy()
        effective = compose_policy(baseline, enabled_policy())
        self.assertFalse(effective["enabled"])
        self.assertEqual(effective["rules"], [])
        self.assertFalse(policy_is_active(effective))

    def test_baseline_and_workspace_ai_checks_are_independently_required(self):
        baseline = add_ai(enabled_policy())
        baseline["allowed_models"] = [{"endpoint_id": "endpoint", "model_id": "workspace-scanner"}]
        workspace = add_ai(enabled_policy(), "workspace-scanner")
        workspace["ai"]["instructions"] = "Identify secrets."
        effective = compose_policy(baseline, workspace)
        self.assertEqual([check["id"] for check in effective["ai_checks"]], ["global:ai", "workspace:ai"])
        self.assertEqual(effective["ai_checks"][0]["instructions"], baseline["ai"]["instructions"])
        self.assertEqual(effective["ai_checks"][1]["instructions"], "Identify secrets.")
        self.assertEqual(normalize_effective_policy(effective), effective)

    def test_implicit_baseline_model_is_allowed_but_workspace_cannot_add_choices(self):
        baseline = add_ai(enabled_policy())
        workspace = add_ai(enabled_policy())
        self.assertEqual(len(compose_policy(baseline, workspace)["ai_checks"]), 2)
        workspace["ai"]["model_selection"]["model_id"] = "unapproved"
        with self.assertRaises(ScreeningValidationError):
            compose_policy(baseline, workspace)
        workspace["ai"]["enabled"] = False
        with self.assertRaises(ScreeningValidationError):
            compose_policy(baseline, workspace)
        workspace["allowed_models"] = [{"endpoint_id": "endpoint", "model_id": "unapproved"}]
        with self.assertRaises(ScreeningValidationError):
            normalize_policy(workspace, scope_type="group")

    def test_workspace_cannot_relax_execution_caps(self):
        baseline, workspace = enabled_policy(), enabled_policy()
        baseline["limits"]["max_units"] = 50
        workspace["limits"]["max_units"] = 100
        workspace["limits"]["max_findings"] = 5
        result = compose_policy(baseline, workspace)
        self.assertEqual(result["limits"]["max_units"], 50)
        self.assertEqual(result["limits"]["max_findings"], 5)

    def test_maximum_explicit_model_choices_can_include_an_implicit_baseline_choice(self):
        policy = add_ai(enabled_policy(), "baseline-scanner")
        policy["allowed_models"] = [
            {"endpoint_id": "endpoint", "model_id": f"model-{index}"} for index in range(100)
        ]
        effective = compose_policy(policy)
        self.assertEqual(len(effective["allowed_models"]), 101)
        self.assertEqual(normalize_effective_policy(effective), effective)

    def test_fingerprints_are_stable_and_effective_snapshots_detect_tampering(self):
        policy = enabled_policy()
        policy["rules"].append(literal_rule("another"))
        first = normalize_policy(policy)
        policy["rules"].reverse()
        self.assertEqual(first["fingerprint"], normalize_policy(policy)["fingerprint"])
        effective = compose_policy(policy)
        original = deepcopy(effective)
        effective["rules"][0]["values"] = ["different"]
        with self.assertRaises(ScreeningValidationError):
            normalize_effective_policy(effective)
        original["rules"][0]["required"] = False
        with self.assertRaises(ScreeningValidationError):
            policy_is_active(original)

    def test_summary_does_not_disclose_values_names_patterns_or_model_routes(self):
        policy = add_ai(enabled_policy())
        policy["rules"][0]["name"] = "sensitive-rule-name"
        policy["rules"][0]["category"] = "sensitive_category"
        policy["ai"]["instructions"] = "sensitive-instructions"
        summary = safe_baseline_summary(policy)
        self.assertEqual(set(summary), {
            "schema_version", "enabled", "rule_count", "ai_check_count",
            "rule_types", "pii_types", "severities", "fingerprint",
        })
        encoded = json.dumps(summary)
        for secret in (
            "private-value", "sensitive-rule-name", "sensitive_category",
            "sensitive-instructions", "endpoint", "scanner",
        ):
            self.assertNotIn(secret, encoded)
        self.assertEqual(summary["rule_count"], 1)
        self.assertEqual(summary["ai_check_count"], 1)
        self.assertEqual(summary, safe_baseline_summary(compose_policy(policy)))


if __name__ == "__main__":
    unittest.main()
