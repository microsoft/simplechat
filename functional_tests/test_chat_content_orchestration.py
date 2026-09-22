# test_chat_content_orchestration.py
"""
Functional tests for enabled chat checkpoints through real orchestration routes.
Version: 0.261.127
Implemented in: 0.261.127

Reuse the real planner, execution lease, message publication, and Flask/SSE
fixture with synthetic completions and an injected deterministic scanner.
"""

import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy

import test_orchestration_conversation_context_routes as route_fixture
from content_screening.policies import STARTER_RULE_TEMPLATES, default_policy
import functions_chat_content_checks as checks


class OrchestratedChatContentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = route_fixture.ConversationRouteTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.settings.update({
            "enable_content_screening": True,
            "enable_content_screening_chat_input": False,
            "enable_content_screening_chat_output": True,
        })
        self.policy = default_policy()
        self.policy["enabled"] = True
        self.policy["rules"] = [copy.deepcopy(STARTER_RULE_TEMPLATES["email"])]
        self.fixture.model.answer_response = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="alice@example.test"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
        self.audit = Mock()
        self.blocked_attempt = Mock()

        def evaluate(text, checkpoint, *, user_id, settings=None, required_scanners=None):
            result = checks.evaluate_chat_content(
                text, checkpoint, settings if settings is not None else self.fixture.settings,
                baseline_loader=lambda: self.policy, required_scanners=required_scanners,
            )
            if result.metadata:
                result.metadata["actor_user_id"] = user_id
            return result

        for patcher in (
            patch.object(self.fixture.route, "check_chat_content", side_effect=evaluate),
            patch.object(checks, "check_chat_content", side_effect=evaluate),
            patch.object(self.fixture.route, "record_chat_content_incident", self.audit),
            patch.object(self.fixture.route, "record_blocked_chat_attempt", self.blocked_attempt),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_flagged_output_is_published_as_safety_with_the_reserved_run_identity(self):
        plan = self.fixture.planned()
        response = self.fixture.run_plan(plan)
        events = route_fixture.frames(response)
        done = next(event for event in events if event.get("done"))
        saved = self.fixture.messages.read_item(done["message_id"], "conv1")
        self.assertTrue(done["blocked"])
        self.assertEqual(done["role"], "safety")
        self.assertNotIn("alice@example.test", done["full_content"])
        self.assertNotIn(checks.CHECK_METADATA, json.dumps(done))
        self.assertEqual(saved["role"], "safety")
        self.assertEqual(saved["metadata"]["orchestration"]["run_id"], plan["run_id"])
        self.assertEqual(saved["metadata"][checks.CHECK_METADATA]["status"], "findings")
        self.audit.assert_called_once()

    def test_checker_failure_is_private_and_keeps_the_reply_usable(self):
        self.policy = None
        plan = self.fixture.planned()
        response = self.fixture.run_plan(plan)
        done = next(event for event in route_fixture.frames(response) if event.get("done"))
        saved = self.fixture.messages.read_item(done["message_id"], "conv1")
        self.assertFalse(done["blocked"])
        self.assertEqual(done["full_content"], "alice@example.test")
        self.assertNotIn("not_checked", json.dumps(done))
        self.assertEqual(saved["metadata"][checks.CHECK_METADATA]["status"], "not_checked")
        self.assertEqual(saved["metadata"][checks.CHECK_METADATA]["decision"], "allow_unchecked")

    def test_input_finding_stops_the_planning_model(self):
        self.fixture.settings["enable_content_screening_chat_input"] = True
        response, events = self.fixture.plan(message="Please process alice@example.test")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(event.get("error") for event in events))
        self.assertEqual(self.fixture.model.calls, [])
        self.blocked_attempt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
