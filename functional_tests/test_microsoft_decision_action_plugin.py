#!/usr/bin/env python3
# test_microsoft_decision_action_plugin.py
"""
Functional test for the Microsoft Decision-1 action plugin.
Version: 0.261.062
Implemented in: 0.261.062

This test verifies endpoint safety, manifest validation, typed Decision-1 request
construction, normalized responses, and safe provider failures without live I/O.
"""

import sys
import types
import unittest
import json
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))


def plugin_function_logger(_plugin_name):
    def decorator(function):
        return function

    return decorator


plugin_invocation_logger_stub = types.ModuleType("semantic_kernel_plugins.plugin_invocation_logger")
plugin_invocation_logger_stub.plugin_function_logger = plugin_function_logger
sys.modules.setdefault("semantic_kernel_plugins.plugin_invocation_logger", plugin_invocation_logger_stub)

appinsights_stub = types.ModuleType("functions_appinsights")
appinsights_stub.log_event = lambda *args, **kwargs: None
sys.modules.setdefault("functions_appinsights", appinsights_stub)

from functions_microsoft_decision_operations import (  # noqa: E402
    MICROSOFT_DECISION_PATH,
    normalize_microsoft_decision_endpoint,
    validate_microsoft_decision_manifest,
)
from semantic_kernel_plugins.microsoft_decision_plugin import MicrosoftDecisionPlugin  # noqa: E402
from semantic_kernel_plugins.microsoft_decision_plugin_factory import MicrosoftDecisionPluginFactory  # noqa: E402


class FakeResponse:
    """Minimal HTTP response with a JSON body."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class MicrosoftDecisionActionPluginTests(unittest.TestCase):
    """Validate the Decision-1 action's safe request and response contract."""

    def setUp(self):
        self.manifest = {
            "name": "decision_action",
            "type": "microsoft_decision",
            "endpoint": "https://contoso.services.ai.azure.com",
            "auth": {"type": "key", "key": "test-key"},
            "additionalFields": {
                "deployment_name": "decision-1",
                "minimum_confidence": 0.75,
            },
        }

    def test_endpoint_normalization_preserves_exact_apim_revision_path(self):
        self.assertEqual(
            normalize_microsoft_decision_endpoint(
                "https://gateway.azure-api.net/shared-foundry;rev=2/providers/microsoft/v1/systemone",
                "exact",
            ),
            "https://gateway.azure-api.net/shared-foundry;rev=2/providers/microsoft/v1/systemone",
        )
        self.assertEqual(
            normalize_microsoft_decision_endpoint("https://contoso.services.ai.azure.com/", "foundry"),
            f"https://contoso.services.ai.azure.com{MICROSOFT_DECISION_PATH}",
        )

    def test_manifest_rejects_untrusted_identity_endpoint_and_invalid_exact_path(self):
        identity_manifest = {
            **self.manifest,
            "endpoint": "https://gateway.example.test/providers/microsoft/v1/systemone",
            "auth": {"type": "identity", "identity": "managed_identity"},
            "additionalFields": {"url_mode": "exact", "deployment_name": "decision-1"},
        }
        self.assertTrue(any("trusted Azure" in error for error in validate_microsoft_decision_manifest(identity_manifest)))

        invalid_path_manifest = {
            **self.manifest,
            "endpoint": "https://gateway.azure-api.net/decision",
            "additionalFields": {"url_mode": "exact", "deployment_name": "decision-1"},
        }
        self.assertTrue(any("must end with" in error for error in validate_microsoft_decision_manifest(invalid_path_manifest)))

    def test_condition_request_uses_configured_api_key_header_and_review_threshold(self):
        plugin = MicrosoftDecisionPluginFactory.create_from_config(
            {
                **self.manifest,
                "additionalFields": {
                    **self.manifest["additionalFields"],
                    "api_key_header": "Ocp-Apim-Subscription-Key",
                },
            }
        )
        captured = {}
        original_post = __import__("semantic_kernel_plugins.microsoft_decision_plugin", fromlist=["requests"]).requests.post

        def fake_post(*args, **kwargs):
            captured["url"] = args[0]
            captured.update(kwargs)
            return FakeResponse(
                200,
                {
                    "model": "decision-1",
                    "output_text": json.dumps({"answer": False, "probabilities": {"true": 0.6, "false": 0.4}}),
                },
            )

        module = __import__("semantic_kernel_plugins.microsoft_decision_plugin", fromlist=["requests"])
        module.requests.post = fake_post
        try:
            result = plugin.check_condition(
                '{"priority":"high"}',
                "Does this request require immediate review?",
                "A high-priority item requires review.",
                "All other items do not.",
            )
        finally:
            module.requests.post = original_post

        self.assertTrue(result["success"])
        self.assertTrue(result["requires_review"])
        self.assertEqual(captured["headers"]["Ocp-Apim-Subscription-Key"], "test-key")
        self.assertEqual(captured["json"]["model"], "decision-1")
        self.assertIn('State: {"priority": "high"}', captured["json"]["input"])
        self.assertIn('"type": "noul"', captured["json"]["input"])

    def test_choice_and_score_requests_are_typed_and_invalid_input_is_safe(self):
        plugin = MicrosoftDecisionPlugin(self.manifest)
        module = __import__("semantic_kernel_plugins.microsoft_decision_plugin", fromlist=["requests"])
        original_post = module.requests.post
        questions = []

        def fake_post(*args, **kwargs):
            input_text = kwargs["json"]["input"]
            question_type = next(
                question_type
                for question_type in ("choice", "score")
                if f'"type": "{question_type}"' in input_text
            )
            questions.append((question_type, {"type": question_type}))
            return FakeResponse(
                200,
                {
                    "output_text": json.dumps(
                        {"answer": question_type, "probabilities": {"one": 0.9, "two": 0.1}}
                    )
                },
            )

        module.requests.post = fake_post
        try:
            choice_result = plugin.choose_option("state", "Choose the best route.", '{"one":"First route","two":"Second route"}')
            score_result = plugin.score_state("state", "Score the risk.", '["low","high"]')
        finally:
            module.requests.post = original_post

        self.assertTrue(choice_result["success"])
        self.assertTrue(score_result["success"])
        self.assertEqual([question[1]["type"] for question in questions], ["choice", "score"])
        invalid_result = plugin.choose_option("state", "", '{"one":"First route","two":"Second route"}')
        self.assertFalse(invalid_result["success"])
        self.assertEqual(invalid_result["error_type"], "validation")

    def test_provider_failure_does_not_expose_provider_error_body(self):
        plugin = MicrosoftDecisionPlugin(self.manifest)
        module = __import__("semantic_kernel_plugins.microsoft_decision_plugin", fromlist=["requests"])
        original_post = module.requests.post
        module.requests.post = lambda *args, **kwargs: FakeResponse(401, {"error": {"message": "sensitive provider detail"}})
        try:
            result = plugin.check_condition("state", "Is state valid?")
        finally:
            module.requests.post = original_post

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "authentication")
        self.assertNotIn("sensitive provider detail", result["error"])


if __name__ == "__main__":
    assert_app_version_at_least("0.261.062")
    unittest.main()
