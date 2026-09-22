# test_chat_content_checks.py
"""
Functional regressions for shared chat content checkpoints.
Version: 0.261.127
Implemented in: 0.261.127

Exercise master/child switches, real deterministic rules, bounded Azure text
coverage, quiet allow-unchecked metadata, and authoritative reply replacement.
Only synthetic content and injected scanner clients are used.
"""

import copy
import builtins
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from content_screening.policies import STARTER_RULE_TEMPLATES, default_policy
from functions_chat_content_checks import (
    CHECK_METADATA,
    REMOVED_REPLY_MESSAGE,
    attach_chat_check,
    chat_content_form_updates,
    check_chat_content,
    blocked_chat_payload,
    enabled_chat_scanners,
    evaluate_chat_content,
    prepare_checked_reply,
    public_chat_payload,
    retract_message_content,
    should_withhold_chat_event,
    strip_private_chat_checks,
)
from functions_content_safety import (
    CONTENT_SAFETY_MAX_CHARACTERS,
    CONTENT_SAFETY_MAX_WINDOWS,
    analyze_content_safety_text,
)


def policy():
    value = default_policy()
    value["enabled"] = True
    value["rules"] = [copy.deepcopy(STARTER_RULE_TEMPLATES["email"])]
    return value


def safety_response(severity=0):
    return SimpleNamespace(
        categories_analysis=[
            SimpleNamespace(category=name, severity=severity if name == "Hate" else 0)
            for name in ("Hate", "SelfHarm", "Sexual", "Violence")
        ],
        blocklists_match=[],
    )


class ChatContentChecksTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "enable_content_screening": True,
            "enable_content_screening_chat_input": True,
            "enable_content_screening_chat_output": True,
        }

    def evaluate(self, text, checkpoint="chat_output", **kwargs):
        return evaluate_chat_content(
            text, checkpoint, self.settings, baseline_loader=policy, **kwargs,
        )

    def test_child_switches_never_enable_a_disabled_master(self):
        inactive = enabled_chat_scanners(
            {"enable_content_screening_chat_output": True, "enable_content_safety_chat_output": True},
            "chat_output",
        )
        legacy_input = enabled_chat_scanners({"enable_content_safety": True}, "chat_input")
        legacy_output = enabled_chat_scanners({"enable_content_safety": True}, "chat_output")
        self.assertEqual(inactive, [])
        self.assertEqual(legacy_input, ["content_safety"])
        self.assertEqual(legacy_output, [])

    def test_disabled_checkpoint_is_not_an_unchecked_incident(self):
        result = evaluate_chat_content("alice@example.test", "chat_output", {})
        self.assertEqual(result.status, "not_required")
        self.assertEqual(result.metadata, {})
        self.assertFalse(result.blocked)

    def test_supplied_settings_do_not_import_the_settings_owner_for_disabled_checks(self):
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name in ("config", "functions_settings"):
                raise AssertionError("A supplied settings snapshot must not bootstrap its owner.")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded_import):
            result = check_chat_content("ordinary", "chat_output", user_id="owner", settings={})
        self.assertEqual(result.status, "not_required")

    def test_legacy_forms_preserve_new_controls_and_new_forms_can_clear_switches(self):
        current = {
            "enable_content_safety_chat_output": True,
            "chat_content_output_mode": "check_before_display",
        }
        preserved = chat_content_form_updates({}, current)
        submitted = chat_content_form_updates({
            "chat_content_settings_present": "1",
            "enable_content_screening_chat_input": "on",
        }, current)
        self.assertTrue(preserved["enable_content_safety_chat_output"])
        self.assertEqual(preserved["chat_content_output_mode"], "check_before_display")
        self.assertTrue(submitted["enable_content_screening_chat_input"])
        self.assertFalse(submitted["enable_content_safety_chat_output"])

    def test_public_projection_removes_private_metadata_not_business_field_names(self):
        public = strip_private_chat_checks({
            "data": {CHECK_METADATA: "An ordinary business column"},
            "metadata": {CHECK_METADATA: {"status": "not_checked"}, "thread_info": {"thread_id": "thread"}},
        })
        self.assertEqual(public["data"][CHECK_METADATA], "An ordinary business column")
        self.assertNotIn(CHECK_METADATA, public["metadata"])

    def test_same_real_baseline_blocks_input_and_output(self):
        for checkpoint in ("chat_input", "chat_output"):
            with self.subTest(checkpoint=checkpoint):
                result = self.evaluate("Contact alice@example.test", checkpoint)
                self.assertTrue(result.blocked)
                self.assertEqual(result.status, "findings")
                self.assertTrue(result.metadata["complete"])
                self.assertNotIn("alice@example.test", json.dumps(result.metadata))
                self.assertNotIn("alice@example.test", result.notice)

    def test_clean_complete_content_passes_without_rewriting(self):
        result = self.evaluate("An ordinary answer without sensitive identifiers.")
        message = {"role": "assistant", "content": "Original text"}
        attach_chat_check(message, result)
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.decision, "allow")
        self.assertEqual(message["content"], "Original text")
        self.assertTrue(message["metadata"][CHECK_METADATA]["complete"])

    def test_empty_policy_is_not_fabricated_as_a_pass(self):
        empty = default_policy()
        empty["enabled"] = True
        log = Mock()
        result = evaluate_chat_content(
            "Ordinary text", "chat_input", self.settings, baseline_loader=lambda: empty, log=log,
        )
        self.assertEqual(result.status, "not_checked")
        self.assertEqual(result.decision, "allow_unchecked")
        self.assertIsNone(result.notice)
        self.assertEqual(result.metadata["scanners"][0]["error_code"], "screening_policy_empty")
        log.assert_called()

    def test_administrator_can_block_on_checker_failure(self):
        self.settings["chat_content_scan_failure_action"] = "block"
        result = evaluate_chat_content("Ordinary text", "chat_input", self.settings)
        self.assertTrue(result.blocked)
        self.assertEqual(result.status, "not_checked")
        self.assertIn("could not finish", result.notice)
        self.assertNotIn("policy violation", result.notice)

    def test_confirmed_finding_overrides_allow_on_error_from_another_scanner(self):
        self.settings.update({"enable_content_safety": True, "enable_content_safety_chat_output": True})
        result = self.evaluate("alice@example.test", safety_client=None)
        self.assertTrue(result.blocked)
        self.assertEqual(result.status, "findings")
        self.assertFalse(result.metadata["complete"])
        self.assertEqual(result.metadata["scanners"][1]["status"], "not_checked")

    def test_recheck_cannot_mark_a_disabled_scanner_as_passed(self):
        result = evaluate_chat_content(
            "Ordinary text", "chat_output", {}, required_scanners=["content_screening"],
        )
        self.assertEqual(result.status, "not_checked")
        self.assertEqual(result.metadata["scanners"][0]["error_code"], "chat_scanner_disabled")

    def test_complete_assembled_reply_catches_a_pattern_across_stream_chunks(self):
        chunks = ["Contact alice@", "example.", "test"]
        result = self.evaluate("".join(chunks))
        self.assertTrue(result.blocked)

    def test_retraction_removes_answer_and_derived_projections(self):
        result = self.evaluate("alice@example.test")
        original = {
            "id": "reply", "conversation_id": "conversation", "role": "assistant",
            "content": "alice@example.test", "hybrid_citations": [{"text": "alice@example.test"}],
            "metadata": {
                "thread_info": {"thread_id": "thread"},
                "block_revisions": {"old_source": "alice@example.test"},
                "generated_analysis_artifacts": [{"artifact_message_id": "artifact"}],
            },
        }
        replacement = retract_message_content(original, result)
        public = strip_private_chat_checks(replacement)
        self.assertEqual(public["role"], "safety")
        self.assertEqual(public["content"], REMOVED_REPLY_MESSAGE)
        self.assertEqual(public["metadata"]["thread_info"]["thread_id"], "thread")
        self.assertNotIn("alice@example.test", json.dumps(public))
        self.assertNotIn(CHECK_METADATA, json.dumps(public))
        self.assertEqual(original["content"], "alice@example.test")

    def test_terminal_replacement_beats_stale_caller_content_and_cancel_flags(self):
        app = Flask(__name__)
        result = self.evaluate("alice@example.test")
        message = {"id": "reply", "conversation_id": "conversation", "role": "assistant", "content": "alice@example.test"}
        with app.test_request_context(), patch(
            "functions_chat_content_checks.check_chat_content", return_value=result,
        ):
            prepare_checked_reply(message, user_id="owner")
            payload = public_chat_payload({
                "done": True, "message_id": "reply", "cancelled": True,
                "full_content": "alice@example.test", "partial_content": "alice@example.test",
                "agent_citations": [{"text": "alice@example.test"}],
                "source": "alice@example.test",
                "block_revisions": {"old": "alice@example.test"},
            })
        self.assertTrue(payload["replace_content"])
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["full_content"], REMOVED_REPLY_MESSAGE)
        self.assertNotIn("cancelled", payload)
        self.assertNotIn("alice@example.test", json.dumps(payload))
        self.assertNotIn(CHECK_METADATA, json.dumps(payload))

    def test_allow_unchecked_is_private_and_has_no_end_user_warning(self):
        app = Flask(__name__)
        result = evaluate_chat_content("Ordinary answer", "chat_output", self.settings)
        message = {"id": "reply", "role": "assistant", "content": "Ordinary answer"}
        with app.test_request_context(), patch(
            "functions_chat_content_checks.check_chat_content", return_value=result,
        ):
            prepare_checked_reply(message, user_id="owner")
            payload = public_chat_payload({"message_id": "reply", "done": True, "content": "Ordinary answer"})
        self.assertEqual(message["metadata"][CHECK_METADATA]["status"], "not_checked")
        self.assertEqual(payload["content"], "Ordinary answer")
        self.assertNotIn("warning", payload)
        self.assertNotIn("error", payload)
        self.assertNotIn("not_checked", json.dumps(payload))
        self.assertNotIn(CHECK_METADATA, json.dumps(payload))

    def test_held_mode_suppresses_answer_and_thought_deltas_not_terminal_decisions(self):
        settings = {**self.settings, "chat_content_output_mode": "check_before_display"}
        answer = should_withhold_chat_event({"content": "provisional"}, settings)
        thought = should_withhold_chat_event({"type": "thought", "content": "private excerpt"}, settings)
        final = should_withhold_chat_event({"done": True, "full_content": "approved"}, settings)
        legacy = should_withhold_chat_event({"content": "normal"}, self.settings)
        self.assertTrue(answer)
        self.assertTrue(thought)
        self.assertFalse(final)
        self.assertFalse(legacy)

    def test_held_mode_does_not_hide_required_authentication_or_approval_handoffs(self):
        settings = {**self.settings, "chat_content_output_mode": "check_before_display"}
        for payload in (
            {"auth_required": True},
            {"type": "m365_pending_action", "pending_action": {"id": "action"}},
            {"type": "m365_approval_required"},
            {"type": "m365_sign_in_required"},
        ):
            with self.subTest(payload=payload):
                hidden = should_withhold_chat_event(payload, settings)
                self.assertFalse(hidden)


class AzureSafetyCoverageTests(unittest.TestCase):
    def test_exact_service_boundaries_and_unicode_tail_are_covered(self):
        for length in (9999, 10000, 10001, 25123):
            with self.subTest(length=length):
                text = "\U0001f600" * (length - 4) + "TAIL"
                client = Mock()
                client.analyze_text.return_value = safety_response()
                result = analyze_content_safety_text(text, client)
                windows = [call.args[0].text for call in client.analyze_text.call_args_list]
                self.assertTrue(result.complete)
                self.assertEqual(result.status, "passed")
                self.assertTrue(all(len(window) <= CONTENT_SAFETY_MAX_CHARACTERS for window in windows))
                self.assertTrue(windows[-1].endswith("TAIL"))
                self.assertEqual(len(windows), result.required_windows)
                self.assertEqual(len(windows), 1 if length <= 10000 else 2 if length == 10001 else 3)

    def test_a_tail_finding_blocks_even_when_earlier_windows_pass(self):
        client = Mock()
        client.analyze_text.side_effect = [safety_response(), safety_response(6)]
        result = analyze_content_safety_text("a" * 10001, client)
        self.assertEqual(result.status, "findings")
        self.assertTrue(result.complete)

    def test_missing_client_and_missing_categories_are_not_passes(self):
        unavailable = analyze_content_safety_text("ordinary", None)
        client = Mock()
        client.analyze_text.return_value = SimpleNamespace(categories_analysis=[], blocklists_match=[])
        incomplete = analyze_content_safety_text("ordinary", client)
        self.assertEqual(unavailable.status, "not_checked")
        self.assertFalse(incomplete.complete)
        self.assertEqual(incomplete.error_code, "content_safety_invalid_response")

    def test_valid_finding_survives_an_incomplete_provider_response(self):
        client = Mock()
        client.analyze_text.return_value = SimpleNamespace(
            categories_analysis=[SimpleNamespace(category="Hate", severity=6)], blocklists_match=[],
        )
        result = analyze_content_safety_text("synthetic", client)
        self.assertEqual(result.status, "findings")
        self.assertFalse(result.complete)

    def test_exceptions_and_window_limit_do_not_silently_truncate(self):
        client = Mock()
        client.analyze_text.side_effect = TimeoutError("private provider response")
        timeout = analyze_content_safety_text("ordinary", client)
        oversized = analyze_content_safety_text("a" * (10000 * CONTENT_SAFETY_MAX_WINDOWS), client)
        self.assertEqual(timeout.status, "not_checked")
        self.assertEqual(timeout.error_code, "content_safety_timeout")
        self.assertEqual(oversized.error_code, "content_safety_window_limit")
        self.assertEqual(client.analyze_text.call_count, 1)


if __name__ == "__main__":
    unittest.main()
