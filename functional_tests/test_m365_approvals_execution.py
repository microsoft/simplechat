# test_m365_approvals_execution.py
"""
Functional tests for subject-owned Microsoft 365 approvals and scoped execution.
Version: 0.261.029
Implemented in: 0.261.029

Validates real policy modules against conditional, paginated Cosmos fakes:
sharing ceilings, DST, source/request/subject isolation, explicit expiration,
immutable audit, concurrent decisions, and unchanged legacy approval rights.
"""

import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask import Flask, g


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

# These imports follow the test-only source-path setup, not application bootstrap.
import functions_m365_approvals as approvals
import functions_m365_execution as execution
from test_support.m365 import Clock, CosmosContainer, Notifications, WORKFLOW_REVIEW


def context(**changes):
    values = {
        "actor_user_id": "user-a", "data_user_id": "user-a", "tenant_id": "tenant-a",
        "conversation_id": "conversation-a", "request_id": "request-a",
        "shared": True, "audience_version": "audience-1", "agent_id": "agent-a",
        "action_configs": {"action-a": {"source": "email", "maximum_sharing_acknowledgement": "always"}},
    }
    values.update(changes)
    return execution.M365ExecutionContext(**values)


def _module(name, **members):
    result = types.ModuleType(name)
    result.__dict__.update(members)
    return result


def load_real_legacy_approvals(container):
    dependencies = {
        "config": _module("config", cosmos_approvals_container=container, cosmos_groups_container=container),
        "functions_appinsights": _module("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_notifications": _module(
            "functions_notifications",
            create_notification=lambda **kwargs: None,
            delete_notifications_by_metadata=lambda **kwargs: None,
            create_m365_approval_notification=lambda approval: {"id": approval["id"]},
        ),
        "functions_group": _module("functions_group", find_group_by_id=lambda value: None),
        "functions_settings": _module("functions_settings", get_settings=lambda: {}),
        "functions_debug": _module("functions_debug", debug_print=lambda *args, **kwargs: None),
    }
    spec = importlib.util.spec_from_file_location(
        "m365_test_legacy_approvals", APP_DIR / "functions_approvals.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, dependencies):
        spec.loader.exec_module(module)
    return module


class M365ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.container = CosmosContainer()
        self.clock = Clock()
        self.notifications = Notifications()
        self.service = approvals.M365ApprovalService(
            container_factory=lambda: self.container,
            notification_sender=self.notifications, clock=self.clock,
            decision_validator=lambda approval: True,
        )
        self.service_patch = patch.object(approvals, "_service", self.service)
        self.service_patch.start()
        self.addCleanup(self.service_patch.stop)

    def pending(self, ctx=None, sources=None):
        with self.assertRaises(approvals.M365ApprovalRequired) as raised:
            self.service.authorize_sources(ctx or context(), sources or {"email": "always"})
        return raised.exception

    def decide(self, pending, duration="always", source="email", timezone_name="America/New_York"):
        return self.service.decide(pending.approval_id, "user-a", {
            "decisions": {source: {"duration": duration, "timezone": timezone_name}},
        })

    def test_defaults_and_explicit_publication_warning(self):
        preferences = self.service.get_preferences("user-a")
        pending = self.pending()
        record = self.service.get_approval(pending.approval_id, "user-a")
        self.assertEqual(set(preferences["sources"].values()), {"ask"})
        self.assertEqual(set(preferences["extended_analysis"].values()), {"ask"})
        self.assertIsNone(preferences["timezone"])
        self.assertEqual(record["sources"]["email"]["allowed_durations"], ["request", "today", "always"])
        self.assertEqual(record["ttl"], -1)
        self.assertIn("retained source evidence", pending.payload["approval"]["reason"])
        self.assertEqual(len(self.notifications.calls), 1)
        self.assertEqual(self.notifications.calls[0]["subject_user_id"], "user-a")

    def test_execution_status_and_cancellation_do_not_grant_access(self):
        pending = self.pending()
        canceled = self.service.record_execution_status(
            pending.approval_id, "user-a", "request-a", "cancelled",
        )
        self.assertEqual(canceled["status"], "cancelled")
        self.assertEqual(canceled["execution_status"], "cancelled")
        self.assertFalse(canceled["can_approve"])
        with self.assertRaises(approvals.M365PolicyError):
            self.service.record_execution_status(
                pending.approval_id, "user-a", "different-request", "completed",
            )
        new_request = self.pending(ctx=context(request_id="new-request"))
        self.decide(new_request)
        completed = self.service.record_execution_status(
            new_request.approval_id, "user-a", "new-request", "completed",
        )
        self.assertEqual(completed["status"], "approved")
        self.assertEqual(completed["execution_status"], "completed")

    def test_private_group_context_does_not_prompt(self):
        result = self.service.authorize_sources(context(shared=False), {"email": "always"})
        self.assertFalse(result["email"]["sharing_required"])
        self.assertEqual(self.container.items, {})

    def test_provider_alias_and_positive_guard_contract(self):
        ctx = context(shared=False)
        with execution.m365_execution_context(ctx):
            resolved = execution.get_execution_context()
            result = execution.authorize_m365_operation("email", "action-a")
        self.assertIs(resolved, ctx)
        self.assertTrue(result["allowed"])
        self.assertFalse(result["sharing_required"])
        self.assertEqual(result["source"], "email")

    def test_preference_is_not_a_grant(self):
        self.service.update_preferences("user-a", {"sources": {"email": "always"}})
        pending = self.pending()
        self.assertEqual(pending.payload["approval"]["status"], "pending")

    def test_confirmed_timezone_is_user_private_validated_and_audited(self):
        saved = self.service.update_preferences("user-a", {"timezone": "America/New_York"})
        other_user = self.service.get_preferences("user-b")
        audit = self.service.list_records("user-a", audit=True)
        self.assertEqual(saved["timezone"], "America/New_York")
        self.assertIsNone(other_user["timezone"])
        self.assertEqual(audit["items"][0]["preferences"], {"timezone": "America/New_York"})
        for invalid in ("", "Not/A_Timezone", "../UTC", 0, False, {"zone": "UTC"}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.service.update_preferences("user-a", {"timezone": invalid})
        retained = self.service.get_preferences("user-a")
        self.assertEqual(retained["timezone"], "America/New_York")
        pending = self.pending()
        self.assertEqual(pending.payload["approval"]["status"], "pending")
        with self.assertRaises(ValueError):
            self.service.decide(pending.approval_id, "user-a", {
                "decisions": {"email": {"duration": "today"}},
            })
        cleared = self.service.update_preferences("user-a", {"timezone": None})
        self.assertIsNone(cleared["timezone"])

    def test_timezone_change_never_rewrites_or_extends_a_previously_approved_day(self):
        self.service.update_preferences("user-a", {"timezone": "America/New_York"})
        pending = self.pending(sources={"email": "today"})
        self.decide(pending, "today", timezone_name="America/New_York")
        before = self.service.get_approval(pending.approval_id, "user-a")
        self.service.update_preferences("user-a", {"timezone": "Pacific/Honolulu"})
        self.service.authorize_sources(context(), {"email": "today"})
        self.clock.advance(hours=23)
        renewed = self.pending(sources={"email": "today"})
        after = self.service.get_approval(pending.approval_id, "user-a")
        self.assertEqual(after["decisions"], before["decisions"])
        self.assertEqual(after["decisions"]["email"]["expires_at"], "2026-03-09T04:00:00+00:00")
        self.assertEqual(after["decisions"]["email"]["timezone"], "America/New_York")
        self.assertNotEqual(renewed.approval_id, pending.approval_id)

    def test_legacy_preferences_without_timezone_remain_unconfirmed(self):
        self.service.get_preferences("user-a")
        state = self.container.read_item(approvals.POLICY_RECORD_ID, "user-a")
        state.pop("timezone")
        self.container.upsert_item(state)
        preferences = self.service.get_preferences("user-a")
        self.assertIsNone(preferences["timezone"])
        self.assertEqual(set(preferences["sources"].values()), {"ask"})

    def test_source_global_grant_and_actual_use_audit(self):
        pending = self.pending()
        decision = self.decide(pending)
        other_action = context(
            conversation_id="conversation-b", request_id="request-b",
            action_configs={"global-action": {"source": "email"}},
        )
        result = self.service.authorize_sources(other_action, {"email": "always"})
        record = self.container.read_item(result["email"]["audit_id"], "user-a")
        self.assertEqual(result["email"]["approval_id"], decision["id"])
        self.assertEqual(record["event_type"], "grant_used")
        self.assertEqual(record["context"]["conversation_id"], "conversation-b")
        with self.assertRaises(approvals.M365ApprovalRequired):
            self.service.authorize_sources(other_action, {"calendar": "always"})
        with self.assertRaises(approvals.M365ApprovalRequired):
            self.service.authorize_sources(context(actor_user_id="user-b", data_user_id="user-b"), {"email": "always"})

    def test_request_grant_binds_request_audience_and_action_snapshot(self):
        pending = self.pending(sources={"email": "request"})
        self.decide(pending, "request")
        result = self.service.authorize_sources(context(), {"email": "request"})
        self.assertEqual(result["email"]["effective_duration"], "request")
        for changed in (
            context(request_id="other-request"),
            context(audience_version="audience-2"),
            context(group_id="different-group"),
            context(action_configs={"action-a": {"source": "email", "capabilities": ["different"]}}),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(approvals.M365ApprovalRequired):
                    self.service.authorize_sources(changed, {"email": "request"})

    def test_today_ends_at_local_midnight_and_always_does_not_renew(self):
        pending = self.pending()
        self.decide(pending)
        next_request = context(request_id="day-limited")
        result = self.service.authorize_sources(next_request, {"email": "today"})
        self.assertEqual(result["email"]["expires_at"], "2026-03-09T04:00:00+00:00")
        self.clock.advance(hours=23)
        new_prompt = self.pending(next_request, {"email": "today"})
        self.assertNotEqual(new_prompt.approval_id, pending.approval_id)
        preferences = self.service.get_preferences("user-a")
        self.assertEqual(preferences["sources"]["email"], "always")

    def test_expired_positive_grant_can_prompt_once_more_within_same_logical_request(self):
        pending = self.pending(sources={"email": "today"})
        self.decide(pending, "today")
        self.clock.advance(hours=23)
        renewed = self.pending(sources={"email": "today"})
        repeated = self.pending(sources={"email": "today"})
        self.assertNotEqual(renewed.approval_id, pending.approval_id)
        self.assertEqual(renewed.approval_id, repeated.approval_id)
        self.assertEqual(renewed.payload["approval"]["status"], "pending")
        self.decide(renewed, "today")
        allowed = self.service.authorize_sources(context(), {"email": "today"})
        self.assertEqual(allowed["email"]["expires_at"], "2026-03-10T04:00:00+00:00")

    def test_dst_spring_fall_and_timezone_validation(self):
        for start, hours in (
            (datetime(2026, 3, 8, 5, tzinfo=timezone.utc), 23),
            (datetime(2026, 11, 1, 4, tzinfo=timezone.utc), 25),
        ):
            result = approvals.local_midnight_expiry(start, "America/New_York")
            self.assertEqual(result - start, timedelta(hours=hours))
        pending = self.pending()
        for zone in ("", "Not/A_Timezone", "America/../UTC", None):
            with self.subTest(zone=zone):
                with self.assertRaises(ValueError):
                    self.decide(pending, "today", timezone_name=zone)

    def test_action_ceiling_cannot_be_relaxed_and_short_grant_preserves_preference(self):
        self.service.update_preferences("user-a", {"sources": {"email": "always"}})
        pending = self.pending(sources={"email": "request"})
        with self.assertRaises(ValueError):
            self.decide(pending, "always")
        self.decide(pending, "request")
        preferences = self.service.get_preferences("user-a")
        self.assertEqual(preferences["sources"]["email"], "always")
        strict_context = context(action_configs={
            "action-a": {"source": "email", "maximum_sharing_acknowledgement": "always"},
            "action-b": {"source": "email", "maximum_sharing_acknowledgement": "request"},
        })
        with execution.m365_execution_context(strict_context):
            with self.assertRaises(approvals.M365ApprovalRequired) as raised:
                execution.authorize_m365_operation("email", "action-a", "always")
        self.assertEqual(raised.exception.payload["approval"]["sources"]["email"]["allowed_durations"], ["request"])

    def test_decline_is_source_specific_and_no_data_is_fetched(self):
        pending = self.pending(sources={"email": "always", "calendar": "today"})
        self.service.decide(pending.approval_id, "user-a", {"decisions": {
            "email": {"duration": "no"},
            "calendar": {"duration": "today", "timezone": "UTC"},
        }})
        with self.assertRaises(approvals.M365SourceDenied) as denied:
            self.service.authorize_sources(context(), {"email": "always"})
        result = self.service.authorize_sources(context(), {"calendar": "always"})
        self.assertEqual(denied.exception.payload["source"], "email")
        self.assertEqual(result["calendar"]["approval_id"], pending.approval_id)

    def test_decline_cannot_be_bypassed_by_a_looser_action_or_changed_audience(self):
        original = self.pending()
        self.decide(original, "always")
        self.clock.advance(days=1)
        limited_context = context(request_id="limited-request")
        pending = self.pending(limited_context, {"email": "today"})
        self.service.decide(pending.approval_id, "user-a", {"decisions": {"email": {"duration": "no"}}})
        changed = replace(
            limited_context, audience_version="new-audience",
            action_configs={"other-action": {"type": "m365_email"}},
        )
        with self.assertRaises(approvals.M365SourceDenied):
            self.service.authorize_sources(changed, {"email": "always"})

    def test_subject_only_decisions_and_generation_revocation(self):
        pending = self.pending()
        with self.assertRaises(LookupError):
            self.service.decide(pending.approval_id, "admin-user", {"decisions": {"email": {"duration": "no"}}})
        self.decide(pending)
        before = self.service.get_approval(pending.approval_id, "user-a")
        revoked = self.service.revoke_source("user-a", "email")
        after = self.service.get_approval(pending.approval_id, "user-a")
        new_prompt = self.pending(context(request_id="after-revoke"))
        self.assertTrue(revoked["published_snapshots_retained"])
        self.assertEqual(before["decisions"], after["decisions"])
        self.assertNotEqual(new_prompt.approval_id, pending.approval_id)

    def test_pending_expiration_is_a_durable_event_and_idempotent(self):
        pending = self.pending()
        self.clock.advance(days=3)
        expired = self.service.get_approval(pending.approval_id, "user-a")
        second = self.service.get_approval(pending.approval_id, "user-a")
        event = self.container.read_item(expired["decision_event_id"], "user-a")
        self.assertEqual(expired["status"], "expired")
        self.assertEqual(expired["ttl"], -1)
        self.assertEqual(expired["continuation_status"], "pending")
        self.assertEqual(second["decision_event_id"], event["id"])
        self.assertEqual(event["event_type"], "expired")

    def test_concurrent_decisions_have_one_winner_and_one_event(self):
        pending = self.pending()
        barrier = threading.Barrier(2)
        self.container.before_batch = lambda: barrier.wait(timeout=5)
        choices = [
            {"decisions": {"email": {"duration": "request", "timezone": "UTC"}}},
            {"decisions": {"email": {"duration": "no"}}},
        ]
        def decide(choice):
            try:
                return self.service.decide(pending.approval_id, "user-a", choice)
            except approvals.M365ApprovalConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(decide, choices))
        self.container.before_batch = None
        successful = [result for result in results if result is not None]
        events = [item for item in self.container.items.values() if item.get("record_kind") == "m365_audit"]
        self.assertEqual(len(successful), 1)
        self.assertEqual(len(events), 1)
        again = self.service.decide(
            pending.approval_id, "user-a",
            choices[0] if successful[0]["status"] == "approved" else choices[1],
        )
        self.assertFalse(again["transition_applied"])

    def test_stale_generation_cannot_be_approved(self):
        pending = self.pending()
        self.service.revoke_source("user-a", "email")
        with self.assertRaises(approvals.M365ApprovalConflict):
            self.decide(pending)
        invalidated = self.service.get_approval(pending.approval_id, "user-a")
        self.assertEqual(invalidated["status"], "invalidated")

    def test_continuation_has_one_claim_and_preserves_actual_approval_status(self):
        pending = self.pending()
        self.decide(pending)
        outbox = self.service.list_pending_continuations(page_size=1)
        self.assertEqual(outbox["items"][0]["id"], pending.approval_id)
        claim = self.service.claim_continuation(pending.approval_id, "user-a", "worker-a")
        with self.assertRaises(approvals.M365ApprovalConflict):
            self.service.claim_continuation(pending.approval_id, "user-a", "worker-b")
        completed = self.service.complete_continuation(
            pending.approval_id, "user-a", claim["claim_id"], "awaiting_sign_in",
        )
        self.assertEqual(completed["status"], "approved")
        self.assertEqual(completed["execution_status"], "awaiting_sign_in")
        self.assertEqual(completed["continuation_status"], "delivered")
        remaining = self.service.list_pending_continuations()
        self.assertEqual(remaining["items"], [])
        with self.assertRaises(approvals.M365ApprovalConflict):
            self.service.complete_continuation(pending.approval_id, "user-a", claim["claim_id"], "completed")

    def test_expired_continuation_claim_can_be_recovered_without_stale_worker_completion(self):
        pending = self.pending()
        self.decide(pending)
        first = self.service.claim_continuation(pending.approval_id, "user-a", "worker-a", lease_seconds=1)
        self.clock.advance(seconds=2)
        second = self.service.claim_continuation(pending.approval_id, "user-a", "worker-b")
        with self.assertRaises(approvals.M365ApprovalConflict):
            self.service.complete_continuation(pending.approval_id, "user-a", first["claim_id"], "resumed")
        completed = self.service.complete_continuation(
            pending.approval_id, "user-a", second["claim_id"], "resumed",
        )
        self.assertEqual(completed["execution_status"], "resumed")

    def test_saved_type_bounds_cannot_be_overridden_by_source_metadata(self):
        for config, requested_source in (
            ({"type": "m365_calendar", "source": "email"}, "email"),
            ({"type": "m365_calendar"}, "email"),
            ({"type": "msgraph"}, "spo"),
        ):
            with self.subTest(config=config):
                with execution.m365_execution_context(context(action_configs={"action-a": config})):
                    with self.assertRaises(approvals.M365PolicyError):
                        execution.authorize_m365_operation(requested_source, "action-a")

    def test_authorized_action_resolver_updates_snapshot_and_cannot_loosen_policy(self):
        resolver = lambda ctx, action_id, source: {"type": "m365_email"}
        with patch.object(execution, "_action_config_resolver", resolver):
            with execution.m365_execution_context(context(shared=False, action_configs={})):
                result = execution.authorize_m365_operation("email", "loaded-action")
                resolved_context = execution.get_m365_execution_context()
            cleared = execution.get_m365_execution_context()
        self.assertFalse(result["sharing_required"])
        self.assertEqual(resolved_context.action_configs["loaded-action"]["type"], "m365_email")
        self.assertIsNone(cleared)
        with patch.object(execution, "_action_config_resolver", lambda *args: {
            "source": "email", "maximum_sharing_acknowledgement": "always",
        }):
            with execution.m365_execution_context(context(action_configs={
                "action-a": {"type": "m365_email", "maximum_sharing_acknowledgement": "request"},
            })):
                with self.assertRaises(approvals.M365ApprovalRequired) as pending:
                    execution.authorize_m365_operation("email", "action-a")
        self.assertEqual(pending.exception.payload["approval"]["sources"]["email"]["allowed_durations"], ["request"])

    def test_cached_global_source_resolves_saved_policy_for_each_request(self):
        app = Flask(__name__)
        saved = {
            "type": "m365_email",
            "additionalFields": {"maximum_sharing_acknowledgement": "request"},
            "enabled_functions": ["get_my_messages"],
        }
        resolved_for = []
        def resolver(ctx, action_id, source):
            resolved_for.append((ctx.actor_user_id, ctx.request_id, action_id, source))
            return copy.deepcopy(saved)
        with patch.object(execution, "_action_config_resolver", resolver):
            for request_id in ("first-http-request", "second-http-request"):
                with app.test_request_context("/"):
                    g.m365_execution_context = context(request_id=request_id, action_configs={})
                    with self.assertRaises(approvals.M365ApprovalRequired) as pending:
                        execution.authorize_m365_operation("email", "cached-global", "always")
                    bound = execution.get_m365_execution_context()
                self.assertEqual(bound.action_configs["cached-global"]["enabled_functions"], ("get_my_messages",))
                self.assertEqual(pending.exception.payload["approval"]["sources"]["email"]["allowed_durations"], ["request"])
        self.assertEqual(resolved_for, [
            ("user-a", "first-http-request", "cached-global", "email"),
            ("user-a", "second-http-request", "cached-global", "email"),
        ])

    def test_cached_global_methods_respect_current_source_and_function_revocation(self):
        saved = {
            "type": "m365_email",
            "enabled_functions": ["get_my_messages", "send_mail"],
            "additionalFields": {"m365_capabilities": {"send_mail": True}},
        }
        cached_context = context(shared=False, action_configs={"cached-global": copy.deepcopy(saved)})
        with patch.object(execution, "_action_config_resolver", lambda *_: copy.deepcopy(saved)):
            with execution.m365_execution_context(cached_context):
                initially_allowed = execution.authorize_m365_operation(
                    "email", "cached-global", operation_name="send_mail",
                )
                saved["additionalFields"]["m365_capabilities"]["send_mail"] = False
                with self.assertRaises(approvals.M365PolicyError) as revoked_method:
                    execution.authorize_m365_operation("email", "cached-global", operation_name="send_mail")
                still_readable = execution.authorize_m365_operation(
                    "email", "cached-global", operation_name="get_my_messages",
                )
                saved["enabled_functions"] = []
                with self.assertRaises(approvals.M365PolicyError) as revoked_source:
                    execution.authorize_m365_operation("email", "cached-global")
        self.assertTrue(initially_allowed["allowed"])
        self.assertEqual(revoked_method.exception.code, "m365_function_not_authorized")
        self.assertTrue(still_readable["allowed"])
        self.assertEqual(revoked_source.exception.code, "m365_source_not_authorized")

    def test_cached_global_action_cannot_be_added_from_a_caller_policy(self):
        with patch.object(execution, "_action_config_resolver", lambda *_: None):
            with execution.m365_execution_context(context(shared=False, action_configs={})):
                with self.assertRaises(approvals.M365PolicyError) as raised:
                    execution.authorize_m365_operation("email", "not-a-saved-action", "always")
        self.assertEqual(raised.exception.code, "m365_action_not_authorized")
        self.assertEqual(self.container.items, {})

    def test_runtime_policy_mirror_cannot_relax_saved_additional_fields(self):
        saved = {
            "type": "m365_email", "source": "email",
            "maximum_sharing_acknowledgement": "always",
            "additionalFields": {"maximum_sharing_acknowledgement": "today"},
            "enabled_functions": ["get_my_messages"],
        }
        for resolver in (None, lambda *_: copy.deepcopy(saved)):
            with self.subTest(resolver=resolver):
                with patch.object(execution, "_action_config_resolver", resolver):
                    with execution.m365_execution_context(context(action_configs={"action-a": saved})):
                        with self.assertRaises(approvals.M365ApprovalRequired) as pending:
                            execution.authorize_m365_operation("email", "action-a", "always")
                self.assertEqual(
                    pending.exception.payload["approval"]["sources"]["email"]["allowed_durations"],
                    ["request", "today"],
                )

    def test_live_action_tightening_requires_new_request_acknowledgement(self):
        original = self.pending()
        self.decide(original, "always")
        with patch.object(execution, "_action_config_resolver", lambda *args: {
            "source": "email", "maximum_sharing_acknowledgement": "request",
        }):
            with execution.m365_execution_context(context()):
                with self.assertRaises(approvals.M365ApprovalRequired) as pending:
                    execution.authorize_m365_operation("email", "action-a")
        self.assertEqual(pending.exception.payload["approval"]["sources"]["email"]["allowed_durations"], ["request"])

    def test_flask_bridge_is_request_local_and_explicit_scope_takes_precedence(self):
        app = Flask(__name__)
        with app.test_request_context("/"):
            g.m365_execution_context = context()
            bridged = execution.get_m365_execution_context()
            with execution.m365_execution_context(context(request_id="explicit")):
                explicit = execution.get_m365_execution_context()
            restored = execution.get_m365_execution_context()
        with app.test_request_context("/"):
            unrelated_request = execution.get_m365_execution_context()
        self.assertEqual(bridged.request_id, "request-a")
        self.assertEqual(explicit.request_id, "explicit")
        self.assertIs(restored, bridged)
        self.assertIsNone(unrelated_request)

    def test_flask_request_never_inherits_an_unrelated_worker_context(self):
        app = Flask(__name__)
        worker = context(request_id="worker-request")
        current_request = context(request_id="http-request")
        with execution.m365_execution_context(worker):
            with app.test_request_context("/"):
                before_authorization = execution.get_m365_execution_context()
                g.m365_execution_context = current_request
                authorized = execution.get_m365_execution_context()
            restored_worker = execution.get_m365_execution_context()
        self.assertIsNone(before_authorization)
        self.assertIs(authorized, current_request)
        self.assertIs(restored_worker, worker)

    def test_request_scope_can_reset_after_an_async_context_boundary(self):
        app = Flask(__name__)
        original = context()
        changed = context(request_id="async-request")
        with app.test_request_context("/"):
            g.m365_execution_context = original
            token = copy_context().run(execution.set_m365_execution_context, changed)
            in_request = execution.get_m365_execution_context()
            execution.reset_m365_execution_context(token)
            restored = execution.get_m365_execution_context()
            with self.assertRaises(RuntimeError):
                execution.reset_m365_execution_context(token)
        self.assertIs(in_request, changed)
        self.assertIs(restored, original)

    def test_request_scope_reset_cannot_mutate_a_different_http_request(self):
        app = Flask(__name__)
        with app.test_request_context("/original"):
            token = execution.set_m365_execution_context(context())
            with app.test_request_context("/different"):
                with self.assertRaises(RuntimeError):
                    execution.reset_m365_execution_context(token)
            execution.reset_m365_execution_context(token)
            restored = execution.get_m365_execution_context()
        self.assertIsNone(restored)

    def test_live_action_resolution_updates_request_g_not_inherited_worker_scope(self):
        app = Flask(__name__)
        worker = context(request_id="worker-request")
        request_context = context(shared=False, request_id="http-request", action_configs={})
        with patch.object(execution, "_action_config_resolver", lambda *args: {"type": "m365_email"}):
            with execution.m365_execution_context(worker):
                with app.test_request_context("/"):
                    g.m365_execution_context = request_context
                    result = execution.authorize_m365_operation("email", "request-action")
                    updated_request = g.m365_execution_context
                unchanged_worker = execution.get_m365_execution_context()
        self.assertTrue(result["allowed"])
        self.assertIn("request-action", updated_request.action_configs)
        self.assertEqual(updated_request.request_id, "http-request")
        self.assertIs(unchanged_worker, worker)

    def test_extended_analysis_preferences_are_separate_and_audited(self):
        with self.assertRaises(approvals.M365ApprovalRequired) as raised:
            self.service.authorize_extended_analysis(context(), "onedrive", {"file_count": 4})
        self.service.decide(raised.exception.approval_id, "user-a", {"choice": "always"})
        result = self.service.authorize_extended_analysis(context(request_id="next"), "onedrive")
        preferences = self.service.get_preferences("user-a")
        self.assertEqual(result["mode"], "extended")
        self.assertEqual(preferences["extended_analysis"], {"onedrive": "always", "spo": "ask"})
        self.assertEqual(preferences["sources"]["onedrive"], "ask")
        with self.assertRaises(approvals.M365ApprovalRequired):
            self.service.authorize_extended_analysis(context(), "spo")
        self.service.update_preferences("user-a", {"extended_analysis": {"spo": "fast"}})
        fast = self.service.authorize_extended_analysis(context(), "spo")
        self.assertEqual(fast["mode"], "fast")

    def test_audit_is_paginated_and_conversation_view_omits_private_preferences(self):
        for index in range(3):
            self.service.update_preferences("user-a", {"sources": {"email": "always" if index % 2 == 0 else "ask"}})
        pending = self.pending()
        self.decide(pending)
        self.service.authorize_sources(context(), {"email": "always"})
        first = self.service.list_records("user-a", audit=True, page_size=2)
        second = self.service.list_records("user-a", audit=True, page_size=2, continuation_token=first["continuation_token"])
        safe = self.service.list_conversation_audit("conversation-a")
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(len(second["items"]), 2)
        self.assertTrue(set(item["id"] for item in first["items"]).isdisjoint(item["id"] for item in second["items"]))
        self.assertTrue(safe["items"])
        self.assertTrue(all("preferences" not in item for item in safe["items"]))
        self.assertTrue(all("connection_id" not in item["context"] for item in safe["items"]))

    def test_context_is_immutable_nested_and_restored(self):
        original = {"action-a": {"source": "email", "capabilities": ["read"]}}
        first = context(action_configs=original)
        original["action-a"]["capabilities"].append("write")
        before = execution.get_m365_execution_context()
        with execution.m365_execution_context(first):
            captured = execution.get_m365_execution_context()
            with execution.m365_execution_context(context(request_id="nested")):
                nested = execution.get_m365_execution_context()
            restored = execution.get_m365_execution_context()
        after = execution.get_m365_execution_context()
        self.assertEqual(captured.action_configs["action-a"]["capabilities"], ("read",))
        self.assertEqual(nested.request_id, "nested")
        self.assertIs(restored, first)
        self.assertIs(after, before)
        with self.assertRaises(approvals.M365PolicyError):
            context(data_user_id="different-user")

    def test_legacy_authorization_rules_remain_separate(self):
        legacy = load_real_legacy_approvals(self.container)
        pending = self.pending()
        new = self.service.get_approval(pending.approval_id, "user-a")
        old = {"request_type": "delete_group", "requester_id": "user-a", "group_owner_id": "owner"}
        self_new = legacy._can_user_approve(new, "user-a", ["User"])
        admin_new = legacy._can_user_approve(new, "other-admin", ["Admin", "ControlCenterAdmin"])
        owner_new = legacy._can_user_view(new, "owner", ["Admin"])
        self_old = legacy._can_user_approve(old, "user-a", ["Admin"])
        admin_old = legacy._can_user_approve(old, "other-admin", ["Admin"])
        self.assertTrue(self_new)
        self.assertFalse(admin_new)
        self.assertFalse(owner_new)
        self.assertFalse(self_old)
        self.assertTrue(admin_old)
        internal = legacy.get_approval_by_id(approvals.POLICY_RECORD_ID, "user-a")
        self.assertIsNone(internal)

    def test_denied_run_as_does_not_create_an_approval_loop_for_the_same_run(self):
        ctx = context(
            workflow_id="workflow", run_id="run-a", request_id="run-a",
            workflow_fingerprint="revision", connection_id="connection",
        )
        connection = {
            "id": "connection", "user_id": "user-a", "tenant_id": "tenant-a",
            "generation": 1, "status": "connected", "sources": ["email"],
        }
        pending = self.service.ensure_workflow_binding(ctx, ["email"], connection, review=WORKFLOW_REVIEW)
        self.service.decide(pending["id"], "user-a", {"choice": "deny"})
        before = len(self.container.items)
        with self.assertRaises(approvals.M365PolicyError) as raised:
            self.service.ensure_workflow_binding(ctx, ["email"], connection, review=WORKFLOW_REVIEW)
        self.assertEqual(raised.exception.code, "m365_workflow_declined")
        self.assertEqual(len(self.container.items), before)
        new_run = self.service.ensure_workflow_binding(
            replace(ctx, request_id="run-b", run_id="run-b"), ["email"], connection, review=WORKFLOW_REVIEW,
        )
        self.assertEqual(new_run["status"], "pending")

    def test_run_as_creation_has_one_stable_record_across_concurrent_request_ids(self):
        ctx = context(
            workflow_id="workflow", run_id="run-a", request_id="request-a",
            workflow_fingerprint="revision", connection_id="connection",
        )
        connection = {
            "id": "connection", "user_id": "user-a", "tenant_id": "tenant-a",
            "generation": 1, "status": "connected", "sources": ["email"],
        }
        contexts = [ctx, replace(ctx, request_id="request-b", run_id="run-b")]
        def create(current):
            return self.service.create_workflow_binding(
                current, ["email"], connection, review=WORKFLOW_REVIEW,
            )
        with ThreadPoolExecutor(max_workers=2) as pool:
            bindings = list(pool.map(create, contexts))
        stored_bindings = [
            item for item in self.container.items.values()
            if item.get("request_type") == approvals.TYPE_WORKFLOW_RUN_AS
        ]
        self.assertEqual(bindings[0]["id"], bindings[1]["id"])
        self.assertEqual(len(stored_bindings), 1)
        changed_account = self.service.create_workflow_binding(
            contexts[1], ["email"], {**connection, "generation": 2}, review=WORKFLOW_REVIEW,
        )
        self.assertNotEqual(changed_account["id"], bindings[0]["id"])

    def test_workflow_binding_requires_fresh_authorization_and_material_match(self):
        ctx = context(
            actor_user_id="workflow-owner", data_user_id="user-a", workflow_id="workflow-a",
            workflow_fingerprint="revision-a", connection_id="connection-a", run_id="run-a",
        )
        connection = {
            "id": "connection-a", "user_id": "user-a", "tenant_id": "tenant-a",
            "generation": 3, "status": "connected", "sources": ["email"],
        }
        with self.assertRaises(ValueError):
            self.service.create_workflow_binding(ctx, ["email"], connection)
        binding = self.service.create_workflow_binding(ctx, ["email"], connection, review=WORKFLOW_REVIEW)
        self.assertEqual(binding["binding"]["review"], WORKFLOW_REVIEW)
        self.service.decision_validator = None
        with self.assertRaises(approvals.M365PolicyError):
            self.service.decide(binding["id"], "user-a", {"choice": "approve"})
        self.service.decision_validator = lambda approval: True
        self.service.decide(binding["id"], "user-a", {"choice": "approve"})
        authorized_context = replace(ctx, binding_id=binding["id"])
        allowed = self.service.validate_workflow_binding(authorized_context, connection, "email")
        self.assertEqual(allowed["status"], "approved")
        reused = self.service.ensure_workflow_binding(
            replace(authorized_context, run_id="next-run", request_id="next-request"),
            ["email"], connection,
        )
        self.assertEqual(reused["id"], binding["id"])
        for changed_context, changed_connection in (
            (replace(authorized_context, workflow_fingerprint="changed"), connection),
            (replace(authorized_context, audience_version="changed-audience"), connection),
            (replace(authorized_context, conversation_id="different-conversation"), connection),
            (authorized_context, {**connection, "generation": 4}),
            (authorized_context, {**connection, "status": "disconnected"}),
        ):
            with self.assertRaises(approvals.M365PolicyError):
                self.service.validate_workflow_binding(changed_context, changed_connection, "email")
        self.service.revoke_workflow_binding(binding["id"], "user-a")
        with self.assertRaises(approvals.M365PolicyError):
            self.service.validate_workflow_binding(authorized_context, connection, "email")

    def test_real_policy_and_connection_cold_imports_never_initialize_cloud(self):
        probe = (
            "import socket,sys; "
            "from unittest.mock import patch; "
            f"sys.path.insert(0, {str(APP_DIR)!r}); "
            "block=patch.object(socket.socket,'connect',side_effect=RuntimeError('network forbidden')); "
            "block.start(); "
            "import functions_m365_execution, functions_m365_connections; "
            "bad=set(sys.modules)&{'config','functions_settings','functions_keyvault'}; "
            "sys.exit(1 if bad else 0)"
        )
        for optimization in ([], ["-O"]):
            result = subprocess.run(
                [sys.executable, *optimization, "-c", probe],
                capture_output=True, text=True, timeout=30, check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
