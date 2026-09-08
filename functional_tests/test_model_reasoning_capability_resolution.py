# test_model_reasoning_capability_resolution.py
"""
Functional tests for canonical reasoning policies and bounded provider recovery.
Version: 0.261.104
Implemented in: 0.261.104

Exercises real catalog matching and SDK errors without Azure clients or network
calls. Covers stale preferences, explicit None, unknown support, safe metadata,
unchanged vision decisions, immutable request arguments and streaming boundaries.
"""

import importlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from openai import APIConnectionError, AuthenticationError, BadRequestError, RateLimitError

from test_support.app_stubs import stubbed_config


LUNA = "gpt-5.6-luna"
LUNA_EFFORTS = ["none", "low", "medium", "high", "xhigh"]
MODEL_UUID = "f8c476df-c951-499c-b87d-98fd02597780"


def sdk_error(error_type=BadRequestError, *, status=400, param="reasoning_effort",
              code="unsupported_value", nested=False):
    """Construct the actual SDK exception shape without making a request."""
    detail = {
        "message": "Unsupported value: reasoning_effort minimal; private-provider-detail",
        "type": "invalid_request_error", "param": param, "code": code,
    }
    return error_type(
        detail["message"],
        response=httpx.Response(
            status, request=httpx.Request("POST", "https://provider.example.test/chat/completions")
        ),
        body={"error": detail} if nested else detail,
    )


class ReasoningPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with stubbed_config():
            cls.capabilities = importlib.import_module("functions_model_capabilities")
            cls.clients = importlib.import_module("model_endpoint_clients")
        cls.capabilities.load_model_capability_catalog(force_refresh=True)

    def policy(self, model=LUNA):
        return self.capabilities.resolve_model_reasoning_policy(model)

    def resolve(self, effort, model=LUNA):
        return self.capabilities.resolve_model_reasoning_effort(model, effort)

    def test_luna_contract_and_normalized_aliases(self):
        for name in (LUNA, "GPT 5.6 LUNA", "gpt_5_6_luna", "gpt-5.6-luna-2026-06-25",
                     "gpt-5.6-luna-eastus", "gpt-5.6"):
            with self.subTest(name=name):
                self.assertEqual(self.policy(name), {
                    "status": "supported", "efforts": LUNA_EFFORTS, "default_effort": "low",
                })

    def test_authorized_canonical_identity_not_configuration_id_or_display_label(self):
        record = {
            "id": MODEL_UUID, "model_id": MODEL_UUID, "modelName": LUNA,
            "deploymentName": "production-answer", "displayName": "GPT-5 Minimal",
        }
        self.assertEqual(self.policy(record)["efforts"], LUNA_EFFORTS)
        self.assertEqual(self.policy({"behavior_name": LUNA, "deployment": "custom"})["efforts"],
                         LUNA_EFFORTS)
        for value in (
            MODEL_UUID, {"id": MODEL_UUID}, {"displayName": LUNA}, {"name": LUNA},
            {"modelName": "acme-private-model", "deploymentName": LUNA, "displayName": LUNA},
        ):
            with self.subTest(value=value):
                self.assertEqual(self.policy(value)["status"], "unknown")
        second_endpoint = {**record, "modelName": "gpt-5-mini"}
        self.assertIn("minimal", self.policy(second_endpoint)["efforts"])
        self.assertNotIn("minimal", self.policy(record)["efforts"])

    def test_longest_prefix_does_not_invent_new_version_or_chat_variant_support(self):
        for name in ("gpt-5.99", "gpt-5.99-custom", "gpt-5.6.1", "gpt-5.3-chat-eastus",
                     "gpt-5-chat", "gpt-5.1-chat", "acme-model", "gpt-6", None, {}):
            with self.subTest(name=name):
                self.assertEqual(self.policy(name), {
                    "status": "unknown", "efforts": [], "default_effort": None,
                })
        self.assertEqual(self.policy("gpt-5-pro-prod")["efforts"], ["high"])
        self.assertEqual(self.policy("o1-mini-2024-09-12")["status"], "unsupported")

    def test_supported_values_preserved_and_luna_minimal_corrected_to_low(self):
        for value in LUNA_EFFORTS:
            with self.subTest(value=value):
                self.assertEqual(self.resolve(value), {
                    "requested_effort": value, "effective_effort": value,
                    "mode": "explicit", "adjustment_reason": None,
                })
        self.assertEqual(self.resolve("minimal"), {
            "requested_effort": "minimal", "effective_effort": "low",
            "mode": "explicit", "adjustment_reason": "reasoning_effort_unsupported",
        })
        self.assertEqual(self.resolve(" HIGH ")["effective_effort"], "high")
        self.assertEqual(self.resolve("max")["effective_effort"], "low")

    def test_legitimate_minimal_and_model_specific_fallbacks(self):
        for model in ("gpt-5", "gpt-5-mini", "gpt-5-nano"):
            self.assertEqual(self.resolve("minimal", model)["effective_effort"], "minimal")
            self.assertIsNone(self.resolve("minimal", model)["adjustment_reason"])
        self.assertEqual(self.resolve("minimal", "gpt-5-pro")["effective_effort"], "high")
        self.assertEqual(self.resolve("low", "gpt-5.4-pro")["effective_effort"], "medium")
        self.assertEqual(self.policy("gpt-5.1")["efforts"], ["none", "low", "medium", "high"])
        self.assertEqual(self.policy("gpt-5.2")["efforts"], LUNA_EFFORTS)
        self.assertEqual(self.policy("gpt-5.3-codex")["efforts"], ["low", "medium", "high", "xhigh"])
        for model in ("o1", "o3", "o3-mini", "o4-mini"):
            self.assertEqual(self.policy(model)["efforts"], ["low", "medium", "high"])

    def test_absent_effort_never_injects_application_fallback(self):
        for value in (None, "", "  "):
            for model in (LUNA, "gpt-5-pro", "gpt-4o", "unknown"):
                with self.subTest(value=value, model=model):
                    self.assertEqual(self.resolve(value, model), {
                        "requested_effort": None, "effective_effort": None,
                        "mode": "model_default", "adjustment_reason": None,
                    })
        self.assertEqual(self.resolve("none")["mode"], "explicit")
        self.assertEqual(self.resolve("none", "gpt-5")["effective_effort"], "low")

    def test_unknown_and_unsupported_efforts_use_honest_default_metadata(self):
        for model, reason in (
            ("gpt-4o", "reasoning_parameter_unsupported"),
            ("o1-mini", "reasoning_parameter_unsupported"),
            ("unknown", "reasoning_capability_unknown"),
        ):
            for effort in ("none", "high"):
                self.assertEqual(self.resolve(effort, model), {
                    "requested_effort": effort, "effective_effort": None,
                    "mode": "model_default", "adjustment_reason": reason,
                })

    def test_policy_sources_and_original_boolean_catalog_fields(self):
        catalog_path = Path(self.capabilities.__file__).parent / self.capabilities.CATALOG_FILENAME
        document = json.loads(catalog_path.read_text(encoding="utf-8"))
        sources = {source["id"] for source in document["sources"]}
        for model in document["models"]:
            for value in model.get("capabilities", {}).values():
                self.assertIsInstance(value, bool)
            if policy := model.get("reasoningPolicy"):
                self.assertTrue(policy["sourceIds"])
                self.assertTrue(set(policy["sourceIds"]) <= sources)
                self.assertEqual(self.policy(model["id"])["status"], policy["status"])
        public = self.policy()
        public["efforts"].clear()
        self.assertEqual(self.policy()["efforts"], LUNA_EFFORTS)

    def test_reasoning_only_legacy_records_do_not_change_vision(self):
        resolve_vision = self.capabilities.resolve_model_vision_support
        self.assertEqual(resolve_vision("gpt-4o"), (True, "inferred"))
        self.assertEqual(resolve_vision("o3-mini"), (True, "inferred"))
        self.assertEqual(resolve_vision("gpt-5.3-chat"), (False, "catalog"))
        self.assertEqual(resolve_vision(LUNA), (True, "catalog"))
        self.assertEqual(resolve_vision({"modelName": LUNA, "supportsVision": False}),
                         (False, "declared"))

    def test_missing_or_malformed_reasoning_metadata_is_unknown(self):
        for policy in (None, {}, [], {"status": "supported", "efforts": ["imaginary"]},
                       {"status": "supported", "efforts": ["low"], "default_effort": "high"}):
            with self.subTest(policy=policy):
                with patch.object(self.capabilities, "_CATALOG_CACHE", {
                    "test-model": {"reasoningPolicy": policy}
                }):
                    self.assertEqual(self.policy("test-model")["status"], "unknown")
        with patch.object(self.capabilities, "_CATALOG_CACHE", {}):
            self.assertEqual(self.policy()["status"], "unknown")
            self.assertEqual(self.resolve("minimal")["mode"], "model_default")

    def test_endpoint_behavior_uses_the_shared_policy(self):
        behavior = self.clients.ModelEndpointBehavior("aoai", LUNA)
        self.assertEqual(behavior.resolve_reasoning_effort("minimal"), "low")
        self.assertEqual(behavior.resolve_reasoning_effort("none"), "none")
        self.assertEqual(behavior.resolve_reasoning_effort(None), "")
        self.assertEqual(
            self.clients.ModelEndpointBehavior("aoai", "gpt-5").resolve_reasoning_effort("minimal"),
            "minimal",
        )
        self.assertEqual(
            self.clients.ModelEndpointBehavior("aoai", "gpt-5.99").resolve_reasoning_effort("high"),
            "",
        )

    def test_completion_applies_policy_without_mutating_parameters(self):
        for effort, effective in (("minimal", "low"), ("none", "none"), ("xhigh", "xhigh"),
                                  (None, None)):
            with self.subTest(effort=effort):
                params = {
                    "model": "production-answer", "messages": [{"role": "user", "content": "hello"}],
                    "reasoning_effort": effort, "max_completion_tokens": 8192, "stream": True,
                }
                create = Mock(return_value=iter(["token"]))
                result, resolution = self.clients.create_completion_with_reasoning(create, params, LUNA)
                self.assertIs(result, create.return_value)
                self.assertEqual(params["reasoning_effort"], effort)
                self.assertEqual(create.call_args.kwargs.get("reasoning_effort"), effective)
                self.assertEqual(resolution["effective_effort"], effective)
                self.assertIs(create.call_args.kwargs["messages"], params["messages"])
                create.assert_called_once()

    def test_exact_parameter_rejection_retries_once_and_only_omits_effort(self):
        for nested in (False, True):
            for code in ("unsupported_value", "unsupported_parameter"):
                with self.subTest(nested=nested, code=code):
                    params = {
                        "model": "production-answer", "messages": [{"role": "user", "content": "hello"}],
                        "reasoning_effort": "high", "max_completion_tokens": 8192,
                        "response_format": {"type": "json_object"}, "stream": True,
                    }
                    create = Mock(side_effect=[sdk_error(code=code, nested=nested), "completion"])
                    with patch.object(self.clients, "log_event") as log:
                        result, resolution = self.clients.create_completion_with_reasoning(
                            create, params, LUNA
                        )
                    self.assertEqual(result, "completion")
                    self.assertEqual(create.call_count, 2)
                    self.assertEqual(create.call_args_list[0].kwargs, params)
                    self.assertEqual(create.call_args_list[1].kwargs, {
                        key: value for key, value in params.items() if key != "reasoning_effort"
                    })
                    self.assertEqual(resolution, {
                        "requested_effort": "high", "effective_effort": None,
                        "mode": "model_default", "adjustment_reason": "reasoning_parameter_rejected",
                    })
                    self.assertNotIn("private-provider-detail", str(log.call_args_list))
                    self.assertNotIn("private-provider-detail", json.dumps(resolution))

    def test_second_rejection_propagates_and_no_effort_means_no_retry(self):
        error = sdk_error()
        for model, effort, calls in ((LUNA, "high", 2), (LUNA, None, 1), ("unknown", "high", 1)):
            with self.subTest(model=model, effort=effort):
                create = Mock(side_effect=error)
                with self.assertRaises(BadRequestError) as raised:
                    self.clients.create_completion_with_reasoning(
                        create, {"model": model, "messages": [], "reasoning_effort": effort}, model
                    )
                self.assertIs(raised.exception, error)
                self.assertEqual(create.call_count, calls)

    def test_resolution_callback_records_recovery_before_a_failing_retry(self):
        observations = []
        retry_error = sdk_error(param="response_format", code="unsupported_parameter")

        def create(**parameters):
            self.assertEqual(observations[-1]["effective_effort"],
                             parameters.get("reasoning_effort"))
            if "reasoning_effort" in parameters:
                raise sdk_error()
            raise retry_error

        with self.assertRaises(BadRequestError) as raised:
            self.clients.create_completion_with_reasoning(
                create,
                {"model": LUNA, "messages": [], "reasoning_effort": "minimal",
                 "response_format": {"type": "json_object"}},
                LUNA, on_resolution=observations.append,
            )
        self.assertIs(raised.exception, retry_error)
        self.assertEqual(observations, [
            {"requested_effort": "minimal", "effective_effort": "low", "mode": "explicit",
             "adjustment_reason": "reasoning_effort_unsupported"},
            {"requested_effort": "minimal", "effective_effort": None, "mode": "model_default",
             "adjustment_reason": "reasoning_parameter_rejected"},
        ])

    def test_resolution_callback_cannot_mutate_request_or_returned_metadata(self):
        observations = []

        def observe(resolution):
            observations.append(dict(resolution))
            resolution.update(requested_effort="changed", effective_effort="high")

        create = Mock(return_value="completion")
        result, resolution = self.clients.create_completion_with_reasoning(
            create, {"model": LUNA, "messages": [], "reasoning_effort": "none"},
            LUNA, on_resolution=observe,
        )
        self.assertEqual(result, "completion")
        self.assertEqual(create.call_args.kwargs["reasoning_effort"], "none")
        self.assertEqual(resolution, {
            "requested_effort": "none", "effective_effort": "none", "mode": "explicit",
            "adjustment_reason": None,
        })
        self.assertEqual(observations, [resolution])

    def test_unrelated_errors_never_trigger_compatibility_recovery(self):
        errors = [
            sdk_error(param="response_format"), sdk_error(param="messages"),
            sdk_error(code="context_length_exceeded"), sdk_error(code="content_filter"),
            sdk_error(param=None), sdk_error(code="invalid_request_error"),
            sdk_error(AuthenticationError, status=401), sdk_error(RateLimitError, status=429),
            APIConnectionError(request=httpx.Request("POST", "https://provider.example.test")),
            ValueError("reasoning_effort is unsupported"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__, code=getattr(error, "code", None)):
                create = Mock(side_effect=error)
                self.assertFalse(self.clients.is_reasoning_parameter_rejection(error))
                with self.assertRaises(type(error)) as raised:
                    self.clients.create_completion_with_reasoning(
                        create, {"model": LUNA, "messages": [], "reasoning_effort": "high"}, LUNA
                    )
                self.assertIs(raised.exception, error)
                create.assert_called_once()

    def test_stream_iteration_errors_are_not_replayed(self):
        error = sdk_error()

        def stream():
            yield "already delivered"
            raise error

        create = Mock(return_value=stream())
        result, resolution = self.clients.create_completion_with_reasoning(
            create, {"model": LUNA, "messages": [], "reasoning_effort": "low", "stream": True}, LUNA
        )
        self.assertEqual(next(result), "already delivered")
        with self.assertRaises(BadRequestError):
            next(result)
        self.assertEqual(resolution["effective_effort"], "low")
        create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
