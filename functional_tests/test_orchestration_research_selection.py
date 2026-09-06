# test_orchestration_research_selection.py
"""
Functional contracts for balanced orchestration research selection and its opt-in evaluator.

Version: 0.261.096
Implemented in: 0.261.096

Runs actual planner, capability projection, request gates and plan normalization with
controlled completions. Azure-dependent imports are excluded through AST extraction.
Sockets are blocked and no production configuration or conversations are loaded.
These tests prove contracts, not semantic quality or improved real model selection.

Run: python -m unittest functional_tests.test_orchestration_research_selection
"""

import ast
import copy
import io
import json
import os
import sys
import types
import unittest
import uuid
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Standalone execution needs the repository path before these local test imports.
from functional_tests.test_support.orchestration_research import (  # noqa: E402
    APP_ROOT,
    capture_baseline,
    case_inputs,
    load_case_suite,
    planner_runtime,
)
from functional_tests.test_support.versioning import assert_app_version_at_least  # noqa: E402
from scripts import evaluate_orchestration_research_planning as evaluation  # noqa: E402


def model_plan(capability=None, rationale="Additional discovery and checked details justify the effort."):
    steps = []
    if capability:
        steps.append({
            "step_id": "gather",
            "capability_id": capability,
            "title": "Gather evidence",
            "rationale": rationale,
            "arguments": {"query": "A synthetic public evidence question"},
            "depends_on": [],
        })
    steps.append({
        "step_id": "answer",
        "capability_id": "respond",
        "title": "Answer",
        "rationale": "Use the available information to address the request.",
        "arguments": {},
        "depends_on": ["gather"] if capability else [],
    })
    return {
        "kind": "plan",
        "intent": {"summary": "Address the synthetic request.", "complexity": "simple", "confidence": 0.8},
        "steps": steps,
    }


class ScriptedClient:
    """An SDK-shaped completion seam, not an alternative planner."""

    max_retries = 0

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []
        self.closed = False
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        if not self.replies:
            raise AssertionError("The test did not authorize another completion.")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        content = json.dumps(reply) if isinstance(reply, dict) else reply
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
            usage=types.SimpleNamespace(prompt_tokens=101, completion_tokens=37, total_tokens=138),
            model="synthetic-model",
        )

    def close(self):
        self.closed = True


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("Network is forbidden in these tests.")))
        self.suite = load_case_suite()
        self.cases = {case["id"]: case for case in self.suite["cases"]}

    def artifact(self, payload=None):
        path = Path.cwd() / f".orchestration-research-test-{uuid.uuid4().hex}.json"
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        if payload is not None:
            path.write_text(json.dumps(payload), encoding="utf-8")
        return path


class ImplementationVersion(OfflineTestCase):
    def test_implementation_version(self):
        assert_app_version_at_least("0.261.096")


class ResearchSelectionContracts(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.stack.enter_context(planner_runtime())

    def plan(self, case_id, replies, settings_overrides=None, request_overrides=None, **kwargs):
        case = self.cases[case_id]
        settings, request_context, context = case_inputs(self.runtime, self.suite, case)
        settings.update(settings_overrides or {})
        request_context.update(request_overrides or {})
        client = ScriptedClient(*replies)
        with patch.dict(self.runtime.planner, {
            "resolve_planner_client": lambda settings: (client, "synthetic-deployment"),
        }):
            kind, document = self.runtime.planner["plan_request"](
                case["message"], context, "synthetic-conversation", request_context["user_id"],
                settings=settings, request_context=request_context, authorized_document_ids=[],
                **kwargs,
            )
        return kind, document, client

    def test_balanced_fixture_has_evidence_based_review_not_a_research_quota(self):
        self.assertEqual(len(self.cases), len(self.suite["cases"]))
        self.assertEqual(len(self.cases), 11)
        self.assertEqual(
            set(self.cases["original-playlist"]["acceptable_choices"]),
            {"web_search", "deep_research"},
        )
        self.assertEqual(self.cases["quick-playlist"]["acceptable_choices"], ["respond"])
        self.assertEqual(self.cases["long-simple-drafting"]["acceptable_choices"], ["respond"])
        for case in self.cases.values():
            self.assertTrue(case["evidence_objectives"], case["id"])
            self.assertTrue(case["overuse_risk"], case["id"])
            self.assertTrue(case["underuse_risk"], case["id"])
        self.assertIn("Human semantic review", self.suite["rubric"]["review_method"])
        self.assertNotIn("target_research_rate", self.suite)

    def test_source_capture_is_the_actual_prompt_and_full_projection(self):
        snapshot = capture_baseline()
        tree = ast.parse((APP_ROOT / "functions_orchestration_planner.py").read_text(encoding="utf-8"))
        prompt_node = next(
            node for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "PLANNER_SYSTEM_PROMPT" for target in node.targets)
        )
        self.assertEqual(snapshot["planner_system_prompt"], ast.literal_eval(prompt_node.value))
        self.assertEqual(
            snapshot["capabilities"],
            self.runtime.registry["build_planner_capability_projection"](
                self.runtime.registry["CAPABILITY_REGISTRY"],
            ),
        )
        self.assertIn("PLANNER_SYSTEM_PROMPT =", snapshot["source_definitions"]["PLANNER_SYSTEM_PROMPT"])
        self.assertEqual(snapshot["parameters"]["temperature"], self.runtime.planner["PLANNER_TEMPERATURE"])
        self.assertEqual(snapshot["parameters"]["max_tokens"], self.runtime.planner["PLANNER_MAX_TOKENS"])

    def test_guidance_is_balanced_domain_neutral_and_cost_bounded(self):
        prompt = self.runtime.planner["PLANNER_SYSTEM_PROMPT"].lower()
        self.assertNotIn("web_search is the cheap default", prompt)
        self.assertNotIn("genuinely could not cover", prompt)
        self.assertIn("discover", prompt)
        self.assertRegex(prompt, r"\b(cost|effort)\b")
        for topic in ("playlist", "medford", "bluegrass", "crescent city"):
            self.assertNotIn(topic, prompt)
        research = self.runtime.registry["get_capability"]("deep_research")
        web = self.runtime.registry["get_capability"]("web_search")
        self.assertEqual(research["cost_class"], "high")
        self.assertEqual(research["max_per_plan"], 1)
        self.assertEqual(web["cost_class"], "low")
        self.assertRegex((research["summary"] + research["when_to_use"]).lower(), r"quer(?:y|ies)")

    def test_original_playlist_is_exact_and_nontrivial_without_selected_resources(self):
        message = self.cases["original-playlist"]["message"]
        self.assertEqual(message, (
            "Help me create a music playlist for 3 hrs of music while we drive from Medford Oregon "
            "to crescent city Ca. We will be driving to forests and redwoods and seeing the coast. "
            "I want a nastalgic vibe we were born in early 80s with bluegrass, country and more modern "
            "stuff from the 2000s to fun contemporary stuff playing now."
        ))
        self.assertGreater(len(message), self.runtime.planner["TRIVIAL_MAX_CHARACTERS"])
        self.assertEqual(self.runtime.planner["triage_request"](message, {}), "simple")
        self.assertEqual(
            self.runtime.planner["triage_request"](self.cases["stable-direct"]["message"], {}),
            "trivial",
        )

    def test_initial_and_replan_share_the_actual_prompt_and_projection(self):
        for hint in (None, "The earlier lookup covered one perspective; reconsider remaining evidence needs."):
            with self.subTest(replan_hint=hint):
                _, document, client = self.plan(
                    "original-playlist", [model_plan("web_search")], replan_hint=hint, revision=2,
                )
                messages = client.calls[0]["messages"]
                self.assertEqual(messages[0]["content"], self.runtime.planner["PLANNER_SYSTEM_PROMPT"])
                payload = json.JSONDecoder().raw_decode(messages[1]["content"])[0]
                settings, request_context, _ = case_inputs(
                    self.runtime, self.suite, self.cases["original-playlist"],
                )
                available = self.runtime.registry["resolve_available_capabilities"](
                    settings, allowed_ids=settings["chat_orchestration_enabled_capabilities"],
                    request_context=request_context,
                )
                self.assertEqual(
                    payload["capabilities"],
                    self.runtime.registry["build_planner_capability_projection"](available),
                )
                self.assertNotIn("acceptable_choices", payload)
                self.assertNotIn("evidence_objectives", payload)
                self.assertNotIn("user_roles", payload)
                self.assertEqual(document["revision"], 2)
                if hint:
                    self.assertIn(hint, messages[1]["content"])
                    self.assertIn("Do not repeat work", messages[1]["content"])

    def test_valid_model_depth_is_preserved_not_routed_by_topic_or_length(self):
        for case_id in ("stable-direct", "long-simple-drafting", "original-playlist", "independent-evidence-reconciliation"):
            for capability in ("web_search", "deep_research"):
                with self.subTest(case=case_id, capability=capability):
                    rationale = f"Synthetic contract completion chose {capability}; a human must assess quality."
                    kind, document, client = self.plan(case_id, [model_plan(capability, rationale)])
                    self.assertEqual(kind, "plan")
                    self.assertEqual([step["capability_id"] for step in document["steps"]], [capability, "respond"])
                    self.assertEqual(document["steps"][0]["rationale"], rationale)
                    self.assertNotIn("planner_fallback_reason", document)
                    self.assertEqual(document["validation"]["errors"], [])
                    self.assertEqual(len(client.calls), 1)
                    self.assertEqual(document["token_usage"]["total_tokens"], 138)

    def test_direct_choice_never_gets_automatic_research_inserted(self):
        for case_id in self.cases:
            with self.subTest(case=case_id):
                _, document, client = self.plan(case_id, [model_plan()])
                self.assertEqual([step["capability_id"] for step in document["steps"]], ["respond"])
                self.assertEqual(len(client.calls), 1)

    def test_prior_evidence_reaches_the_planner_without_redundant_gathering(self):
        _, document, client = self.plan("supported-follow-up", [model_plan()])
        payload = json.loads(client.calls[0]["messages"][1]["content"])
        self.assertEqual(payload["earlier_runs"], self.cases["supported-follow-up"]["earlier_runs"])
        self.assertEqual(payload["conversation"]["recent_turns"], self.cases["supported-follow-up"]["prior_messages"])
        self.assertEqual([step["capability_id"] for step in document["steps"]], ["respond"])

    def test_feature_role_and_allowlist_gates_apply_to_initial_plans_and_replans(self):
        for case_id in ("research-disabled", "research-role-missing", "research-allowlist-excluded"):
            for hint in (None, "Check whether additional discovery is justified."):
                with self.subTest(case=case_id, replan_hint=hint):
                    _, document, client = self.plan(case_id, [model_plan("deep_research")], replan_hint=hint)
                    payload = json.JSONDecoder().raw_decode(client.calls[0]["messages"][1]["content"])[0]
                    self.assertEqual(
                        [item["id"] for item in payload["capabilities"]],
                        ["web_search", "respond"],
                    )
                    self.assertEqual([step["capability_id"] for step in document["steps"]], ["respond"])
                    self.assertFalse(document["validation"]["ok"])

    def test_role_policy_is_actual_fail_closed_claim_normalization(self):
        for roles, allowed in (
            (None, False), ([], False), (["Admin"], False), (["User"], False),
            (["DeepResearchUser"], True), (["deepresearchuser"], True), ("DeepResearchUser", True),
        ):
            with self.subTest(roles=roles):
                _, document, _ = self.plan(
                    "original-playlist", [model_plan("deep_research")],
                    request_overrides={"user_roles": roles},
                )
                self.assertEqual(
                    "deep_research" in [step["capability_id"] for step in document["steps"]],
                    allowed,
                )

    def test_invalid_elicitation_retry_retains_request_role_gate(self):
        invalid_question = {
            "kind": "elicitation",
            "message": "A synthetic unrenderable question.",
            "requested_schema": {
                "type": "object", "properties": {"nested": {"type": "object"}},
            },
        }
        _, document, client = self.plan(
            "research-role-missing", [invalid_question, model_plan("deep_research")],
        )
        self.assertEqual(len(client.calls), 2)
        for call in client.calls:
            payload = json.loads(call["messages"][1]["content"])
            self.assertNotIn("deep_research", [item["id"] for item in payload["capabilities"]])
        self.assertEqual([step["capability_id"] for step in document["steps"]], ["respond"])

    def test_research_cap_is_one_and_does_not_require_a_preceding_web_step(self):
        raw = model_plan("deep_research")
        duplicate = copy.deepcopy(raw["steps"][0])
        duplicate["step_id"] = "extra_research"
        raw["steps"].insert(1, duplicate)
        _, document, _ = self.plan("broad-discovery-checking", [raw])
        self.assertEqual([step["capability_id"] for step in document["steps"]], ["deep_research", "respond"])
        self.assertTrue(document["validation"]["repairs"])

    def test_unparseable_completion_falls_back_without_inserting_research(self):
        _, document, client = self.plan("broad-discovery-checking", ["not a plan"])
        self.assertEqual([step["capability_id"] for step in document["steps"]], ["respond"])
        self.assertIn("planner_fallback_reason", document)
        self.assertEqual(len(client.calls), 1)


class EvaluationContracts(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.baseline = capture_baseline()

    def compare(self, client, call_cap=2, **kwargs):
        return evaluation.run_comparison(
            self.baseline, client=client, deployment="synthetic-deployment", call_cap=call_cap,
            case_ids=["original-playlist"], **kwargs,
        )

    def test_paired_calls_share_context_capabilities_parameters_and_client(self):
        self.baseline["planner_system_prompt"] += "\nSynthetic baseline comparison marker."
        self.baseline["capabilities"][4]["when_to_use"] += " Synthetic baseline descriptor marker."
        client = ScriptedClient(model_plan("web_search"), model_plan("deep_research"))
        report = self.compare(client)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["requests_made"], 2)
        self.assertEqual(report["review_status"], "not_reviewed")
        self.assertTrue(report["guidance_changed"])
        first, second = client.calls
        self.assertEqual(first["model"], second["model"])
        self.assertEqual(first["temperature"], second["temperature"])
        self.assertEqual(first["max_tokens"], second["max_tokens"])
        self.assertNotEqual(first["messages"][0], second["messages"][0])
        first_context = json.loads(first["messages"][1]["content"])
        second_context = json.loads(second["messages"][1]["content"])
        self.assertEqual(
            [item["id"] for item in first_context["capabilities"]],
            [item["id"] for item in second_context["capabilities"]],
        )
        first_context.pop("capabilities")
        second_context.pop("capabilities")
        self.assertEqual(first_context, second_context)
        self.assertNotIn("rubric", first_context)
        self.assertNotIn("acceptable_choices", first_context)
        self.assertEqual(
            [result["selected_steps"][0]["capability_id"] for result in report["results"]],
            ["web_search", "deep_research"],
        )
        for request in report["requests"]:
            self.assertEqual(request["usage"]["total_tokens"], 138)
            self.assertGreaterEqual(request["duration_ms"], 0)
            self.assertEqual(request["observed_model"], "synthetic-model")

    def test_all_synthetic_cases_share_gates_without_exposing_review_annotations(self):
        client = ScriptedClient(*[model_plan() for _ in range(2 * len(self.cases))])
        report = evaluation.run_comparison(
            self.baseline, client=client, deployment="synthetic-deployment",
            call_cap=2 * len(self.cases),
        )
        self.assertEqual(report["requests_made"], 2 * len(self.cases))
        for result in report["results"]:
            expected = ["web_search", "respond"] if result["case_id"].startswith("research-") else [
                "web_search", "deep_research", "respond",
            ]
            self.assertEqual(result["available_capabilities"], expected)
        for call in client.calls:
            payload = json.loads(call["messages"][1]["content"])
            self.assertNotIn("evidence_objectives", payload)
            self.assertNotIn("overuse_risk", payload)

    def test_sdk_automatic_retries_and_invalid_budgets_are_rejected_before_calls(self):
        client = ScriptedClient(model_plan(), model_plan())
        for cap in (None, 0, 1, True):
            with self.subTest(cap=cap):
                with self.assertRaises(evaluation.EvaluationConfigurationError):
                    self.compare(client, call_cap=cap)
        client.max_retries = 2
        with self.assertRaises(evaluation.EvaluationConfigurationError):
            self.compare(client)
        self.assertEqual(client.calls, [])

    def test_changed_capability_contract_or_parameters_fail_preflight(self):
        for mutate in (
            lambda snapshot: snapshot["parameters"].update({"temperature": 0.9}),
            lambda snapshot: snapshot["capabilities"][0].update({"cost": "high"}),
        ):
            with self.subTest(mutation=mutate):
                baseline = copy.deepcopy(self.baseline)
                mutate(baseline)
                client = ScriptedClient()
                with self.assertRaises(evaluation.EvaluationConfigurationError):
                    evaluation.run_comparison(
                        baseline, client=client, deployment="synthetic-deployment",
                        call_cap=2, case_ids=["original-playlist"],
                    )
                self.assertEqual(client.calls, [])

    def test_successful_response_format_retry_is_counted_and_classified(self):
        client = ScriptedClient(RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL"), model_plan(), model_plan())
        report = self.compare(client, call_cap=3)
        self.assertEqual(report["status"], "completed_with_recoveries")
        self.assertEqual(report["requests_made"], len(client.calls))
        self.assertEqual(report["requests_made"], 3)
        self.assertEqual(report["results"][0]["recoveries"], ["retry_without_response_format"])
        self.assertIn("response_format", client.calls[0])
        self.assertNotIn("response_format", client.calls[1])
        self.assertIsNone(report["requests"][0]["usage"])
        self.assertNotIn("SYNTHETIC_PRIVATE_PROVIDER_DETAIL", json.dumps(report))

    def test_cap_counts_fallback_retry_and_stops_before_any_extra_provider_request(self):
        client = ScriptedClient(RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL"), model_plan())
        report = self.compare(client, call_cap=2)
        self.assertEqual(report["status"], "budget_exhausted")
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(report["requests_made"], 2)
        self.assertGreater(report["blocked_requests"], 0)
        self.assertEqual(report["results"][-1]["fallback_classification"], "budget_exhausted")
        self.assertFalse(report["results"][-1]["semantic_review_eligible"])
        self.assertNotIn(report["status"], evaluation.SUCCESS_STATUSES)

    def test_invalid_elicitation_replanning_also_consumes_the_request_cap(self):
        invalid_question = {
            "kind": "elicitation",
            "message": "A synthetic unrenderable question.",
            "requested_schema": {"type": "object", "properties": {}},
        }
        client = ScriptedClient(invalid_question, model_plan("web_search"))
        report = self.compare(client, call_cap=2)
        self.assertEqual(report["status"], "budget_exhausted")
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(report["results"][0]["recoveries"], ["invalid_elicitation_replanned"])
        self.assertFalse(report["results"][-1]["semantic_review_eligible"])

    def test_provider_failure_is_not_scored_as_a_successful_direct_answer(self):
        client = ScriptedClient(
            RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL"),
            RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL"),
        )
        report = self.compare(client, call_cap=4)
        self.assertEqual(report["status"], "provider_failure")
        self.assertEqual(report["requests_made"], 2)
        self.assertEqual(len(report["results"]), 1)
        result = report["results"][0]
        self.assertFalse(result["semantic_review_eligible"])
        self.assertEqual([step["capability_id"] for step in result["selected_steps"]], ["respond"])
        self.assertNotIn("planner_fallback_reason", result)
        self.assertNotIn("SYNTHETIC_PRIVATE_PROVIDER_DETAIL", json.dumps(report))

    def test_loaded_sdk_error_base_is_handled_without_importing_sdk_offline(self):
        sdk = types.ModuleType("openai")
        sdk.OpenAIError = type("OpenAIError", (Exception,), {})
        client = ScriptedClient(
            sdk.OpenAIError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL"),
            sdk.OpenAIError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL"),
        )

        with patch.dict(sys.modules, {"openai": sdk}):
            report = self.compare(client, call_cap=4)

        self.assertEqual(report["status"], "provider_failure")
        self.assertEqual(report["requests_made"], 2)
        self.assertNotIn("SYNTHETIC_PRIVATE_PROVIDER_DETAIL", json.dumps(report))

    def test_unparseable_reply_and_normalization_repairs_are_reported_honestly(self):
        report = self.compare(ScriptedClient("not parseable", model_plan()))
        self.assertEqual(report["status"], "completed_with_planner_fallbacks")
        self.assertEqual(report["results"][0]["fallback_classification"], "unparseable_reply")
        self.assertFalse(report["results"][0]["semantic_review_eligible"])
        raw = model_plan("deep_research")
        raw["steps"].insert(1, {**copy.deepcopy(raw["steps"][0]), "step_id": "duplicate"})
        repaired = self.compare(ScriptedClient(raw, raw))
        self.assertEqual(repaired["status"], "completed_with_repairs")
        self.assertEqual(len(repaired["results"][0]["proposals"][0]["steps"]), 3)
        self.assertEqual(len(repaired["results"][0]["selected_steps"]), 2)
        self.assertTrue(repaired["results"][0]["validation"]["repairs"])

    def test_normalization_exception_keeps_request_accounting_without_raw_errors(self):
        invalid = model_plan()
        invalid["revision"] = "SYNTHETIC_PRIVATE_INVALID_VALUE"
        client = ScriptedClient(invalid)
        report = self.compare(client)
        self.assertEqual(report["status"], "planner_processing_error")
        self.assertEqual(report["requests_made"], 1)
        self.assertEqual(len(client.calls), 1)
        self.assertFalse(report["results"][0]["semantic_review_eligible"])
        self.assertEqual(report["results"][0]["selected_steps"], [])
        self.assertNotIn("SYNTHETIC_PRIVATE_INVALID_VALUE", json.dumps(report))

    def test_repetitions_alternate_pair_order_without_changing_parameters(self):
        client = ScriptedClient(*[model_plan() for _ in range(4)])
        report = self.compare(client, call_cap=4, repetitions=2)
        self.assertEqual(
            [item["variant"] for item in report["results"]],
            ["baseline", "candidate", "candidate", "baseline"],
        )
        self.assertEqual(report["requests_made"], 4)
        self.assertEqual(report["expected_planner_runs"], 4)

    def test_default_capture_and_import_modes_do_not_construct_a_live_client(self):
        path = self.artifact()
        before_config = sys.modules.get("config")
        with patch.object(evaluation, "_explicit_client", side_effect=AssertionError("No live client")), redirect_stdout(io.StringIO()):
            self.assertEqual(evaluation.main([]), 0)
            self.assertEqual(evaluation.main(["--mode", "capture", "--output", str(path)]), 0)
        self.assertIs(sys.modules.get("config"), before_config)
        captured = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(captured["planner_system_prompt"], self.baseline["planner_system_prompt"])
        self.assertEqual(captured["capabilities"], self.baseline["capabilities"])
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(evaluation.main(["--mode", "capture", "--output", str(path)]), 2)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), captured)

    def test_live_cli_requires_explicit_budget_before_constructing_client(self):
        baseline_path = self.artifact(self.baseline)
        output = self.artifact()
        with patch.object(evaluation, "_explicit_client") as configured, redirect_stderr(io.StringIO()):
            self.assertEqual(evaluation.main([
                "--mode", "live", "--baseline", str(baseline_path), "--output", str(output),
            ]), 2)
        configured.assert_not_called()
        self.assertFalse(output.exists())

    def test_live_auth_is_explicit_and_cannot_pick_up_the_other_ambient_auth_type(self):
        for token_auth in (False, True):
            with self.subTest(token_auth=token_auth):
                args = types.SimpleNamespace(
                    endpoint="https://synthetic-evaluation.openai.azure.com",
                    deployment="synthetic-deployment", api_version="2024-10-21",
                    api_key_env=None if token_auth else "SYNTHETIC_EVAL_AUTH",
                    entra_token_env="SYNTHETIC_EVAL_AUTH" if token_auth else None,
                    timeout=20,
                )
                seen = {}

                def constructor(**kwargs):
                    seen.update(kwargs)
                    self.assertNotIn("AZURE_OPENAI_API_KEY", os.environ)
                    self.assertNotIn("AZURE_OPENAI_AD_TOKEN", os.environ)
                    return ScriptedClient()

                sdk = types.ModuleType("openai")
                sdk.AzureOpenAI = constructor
                with patch.dict(sys.modules, {"openai": sdk}), patch.dict(os.environ, {
                    "SYNTHETIC_EVAL_AUTH": "synthetic-explicit-value",
                    "AZURE_OPENAI_API_KEY": "synthetic-ambient-key",
                    "AZURE_OPENAI_AD_TOKEN": "synthetic-ambient-token",
                }):
                    evaluation._explicit_client(args)
                    self.assertEqual(os.environ["AZURE_OPENAI_API_KEY"], "synthetic-ambient-key")
                    self.assertEqual(os.environ["AZURE_OPENAI_AD_TOKEN"], "synthetic-ambient-token")
                self.assertEqual(seen["max_retries"], 0)
                self.assertEqual(seen["azure_ad_token"], "synthetic-explicit-value" if token_auth else None)
                self.assertEqual(seen["api_key"], None if token_auth else "synthetic-explicit-value")

    def test_live_cli_scrubs_client_construction_errors(self):
        baseline_path = self.artifact(self.baseline)
        output = self.artifact()
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(
            evaluation, "_explicit_client",
            side_effect=RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL"),
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            status = evaluation.main([
                "--mode", "live", "--baseline", str(baseline_path), "--output", str(output),
                "--deployment", "synthetic-deployment", "--case", "original-playlist", "--call-cap", "2",
            ])
        self.assertEqual(status, 2)
        artifact = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(artifact["status"], "evaluation_error")
        self.assertNotIn("SYNTHETIC_PRIVATE_PROVIDER_DETAIL", json.dumps(artifact) + stdout.getvalue() + stderr.getvalue())

    def test_live_cli_returns_nonzero_and_writes_safe_provider_failure_artifact(self):
        baseline_path = self.artifact(self.baseline)
        output = self.artifact()
        client = ScriptedClient(
            RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL"),
            RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_DETAIL"),
        )
        with patch.object(evaluation, "_explicit_client", return_value=client), redirect_stdout(io.StringIO()):
            status = evaluation.main([
                "--mode", "live", "--baseline", str(baseline_path), "--output", str(output),
                "--deployment", "synthetic-deployment", "--case", "original-playlist", "--call-cap", "2",
            ])
        self.assertEqual(status, 2)
        self.assertTrue(client.closed)
        artifact = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(artifact["status"], "provider_failure")
        self.assertNotIn("SYNTHETIC_PRIVATE_PROVIDER_DETAIL", json.dumps(artifact))


if __name__ == "__main__":
    unittest.main()
