# test_m365_execution_preflight.py
"""
Functional tests for the canonical Microsoft 365 manifest preflight.
Version: 0.261.029
Implemented in: 0.261.029

Exercises real type/capability intersections, batch subject consent, repeated
loader passes, retained-evidence exceptions, and scoped workflow binding hooks.
Cloud I/O is injected; approval and authorization modules are imported intact.
"""

import copy
from dataclasses import replace
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from azure.core.exceptions import ServiceRequestError
from flask import Flask, g


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

# Application imports follow the test-only source-path setup.
import functions_m365_approvals as approvals
import functions_m365_connections as connections
import functions_m365_execution as execution
from functions_m365_workflow_binding import workflow_execution_fingerprint
from test_support.m365 import Clock, CosmosContainer, Notifications, WORKFLOW_REVIEW


class ManifestPreflightTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.container = CosmosContainer()
        self.service = approvals.M365ApprovalService(
            container_factory=lambda: self.container, notification_sender=Notifications(),
            decision_validator=lambda approval: True, clock=self.clock,
        )
        self.saved = {}
        self.resolutions = []
        for target, name, value in (
            (approvals, "_service", self.service),
            (execution, "_action_config_resolver", self.resolve_action),
            (execution, "_workflow_validator", lambda ctx: True),
            (execution, "_workflow_binding_resolver", None),
            (execution, "_action_selection_resolver", None),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def context(self, **changes):
        values = {
            "actor_user_id": "user-a", "data_user_id": "user-a", "tenant_id": "tenant-a",
            "conversation_id": "conversation-a", "request_id": "request-a",
            "shared": True, "audience_version": "audience-a",
        }
        values.update(changes)
        return execution.M365ExecutionContext(**values)

    def resolve_action(self, context, action_id, source):
        self.resolutions.append((context.actor_user_id, action_id, source))
        action = self.saved.get(action_id)
        if action is None or source not in execution._action_sources(action):
            raise approvals.M365PolicyError("m365_action_not_authorized", "Action access denied.")
        return copy.deepcopy(action)

    def test_snapshot_capability_revalidation_does_not_require_a_remote_connection(self):
        manifest = {
            "id": "files", "type": "m365_sharepoint",
            "enabled_functions": ["read_file_chunk"],
        }
        context = self.context(
            workflow_id="workflow", run_id="run", actor_user_id="caller",
            action_configs={"files": manifest},
        )
        forbidden_remote = Mock(side_effect=AssertionError("Snapshot capability checks must not access OAuth or source grants."))
        with patch.object(execution, "_action_config_resolver", lambda *args: manifest), \
             patch.object(execution, "_action_selection_resolver", lambda ctx: ["files"]), \
             patch.object(execution, "_workflow_validator", forbidden_remote), \
             patch.object(execution, "get_m365_approval_service", forbidden_remote):
            with execution.m365_execution_context(context):
                authorized = execution.authorize_m365_capability(
                    "files", "read_file_chunk", "m365_sharepoint", context=context,
                )
        self.assertEqual(authorized.data_user_id, "user-a")
        self.assertEqual(authorized.actor_user_id, "caller")
        self.assertIsNone(authorized.connection_id)
        self.assertEqual(forbidden_remote.call_count, 0)

    def manifest(self, action_type, action_id, *, enabled=None, policy="always", capabilities=None):
        manifest = {
            "id": action_id, "name": action_id, "type": action_type,
            "additionalFields": {"maximum_sharing_acknowledgement": policy},
        }
        if enabled is not None:
            manifest["enabled_functions"] = enabled
        if capabilities is not None:
            field = "msgraph_capabilities" if action_type == "msgraph" else "m365_capabilities"
            manifest["additionalFields"][field] = capabilities
        self.saved[action_id] = copy.deepcopy(manifest)
        return manifest

    def test_bootstrap_without_context_does_not_resolve_or_fetch_anything(self):
        manifests = [self.manifest("m365_email", "email")]
        result = execution.preflight_m365_manifests(manifests)
        self.assertIs(result, manifests)
        self.assertEqual(self.resolutions, [])
        self.assertEqual(self.container.items, {})

    def test_global_catalog_only_prompts_for_authoritatively_selected_actions(self):
        calendar = self.manifest("m365_calendar", "calendar", enabled=["get_my_events"])
        email = self.manifest("m365_email", "unselected-email", enabled=["get_my_messages"])
        files = self.manifest("m365_onedrive", "unselected-files")
        native = {"type": "calculator", "id": "native"}
        with patch.object(execution, "_action_selection_resolver", lambda ctx: ["calendar"]):
            with execution.m365_execution_context(self.context()):
                with self.assertRaises(approvals.M365ApprovalRequired) as raised:
                    execution.preflight_m365_manifests([calendar, email, files, native])
                bound = execution.get_execution_context()
                self.service.decide(raised.exception.approval_id, "user-a", {
                    "decisions": {"calendar": {"duration": "request", "timezone": "UTC"}},
                })
                permitted = execution.preflight_m365_manifests([calendar, email, files, native])
                with self.assertRaises(approvals.M365PolicyError) as unselected:
                    execution.authorize_m365_operation("email", "unselected-email")
        self.assertEqual(set(raised.exception.payload["approval"]["sources"]), {"calendar"})
        self.assertEqual(set(bound.action_configs), {"calendar"})
        self.assertEqual([item["id"] for item in permitted], ["calendar", "native"])
        self.assertEqual(permitted[0]["enabled_functions"], ["get_my_events"])
        self.assertIs(permitted[1], native)
        self.assertTrue(all(item[1] == "calendar" for item in self.resolutions))
        self.assertEqual(unselected.exception.code, "m365_action_not_selected")

    def test_global_initialization_without_selected_actions_preserves_only_native_tools(self):
        calendar = self.manifest("m365_calendar", "calendar")
        retained_only = self.manifest("m365_sharepoint", "retained", enabled=["read_file_chunk"])
        native = {"type": "calculator", "id": "native"}
        with patch.object(execution, "_action_selection_resolver", lambda ctx: []):
            with execution.m365_execution_context(self.context()):
                permitted = execution.preflight_m365_manifests([calendar, retained_only, native])
        self.assertEqual(permitted, [native])
        self.assertEqual(self.resolutions, [])
        self.assertEqual(self.container.items, {})

    def test_bound_selection_without_resolver_ignores_unrelated_global_sources(self):
        calendar = self.manifest("m365_calendar", "calendar", enabled=["get_my_events"])
        email = self.manifest("m365_email", "email", enabled=["get_my_messages"])
        with patch.object(execution, "_action_config_resolver", None):
            with execution.m365_execution_context(self.context(action_configs={"calendar": calendar})):
                with self.assertRaises(approvals.M365ApprovalRequired) as raised:
                    execution.preflight_m365_manifests([email, calendar])
        self.assertEqual(set(raised.exception.payload["approval"]["sources"]), {"calendar"})

    def test_invalid_selection_does_not_fall_back_to_all_governed_actions(self):
        action = self.manifest("m365_email", "email")
        for invalid in (None, True, "email", {"selected": True}):
            with self.subTest(selection=invalid):
                with patch.object(execution, "_action_selection_resolver", lambda ctx: invalid):
                    with execution.m365_execution_context(self.context()):
                        with self.assertRaises(approvals.M365PolicyError) as raised:
                            execution.preflight_m365_manifests([action])
                self.assertEqual(raised.exception.code, "m365_action_selection_unavailable")
        self.assertEqual(self.resolutions, [])
        self.assertEqual(self.container.items, {})

    def test_authorization_dependency_failures_are_safe_fatal_policy_errors(self):
        action = self.manifest("m365_email", "email")
        private_detail = "private-storage-endpoint-and-credential-diagnostic"
        for hook in (
            "_action_config_resolver", "_action_selection_resolver",
            "_workflow_binding_resolver", "_workflow_validator",
        ):
            for error_type in (ImportError, OSError, TimeoutError, ServiceRequestError):
                with self.subTest(hook=hook, error_type=error_type):
                    ctx = self.context()
                    if hook in {"_workflow_binding_resolver", "_workflow_validator"}:
                        ctx = replace(
                            ctx, workflow_id="workflow-a", run_id="run-a",
                            workflow_fingerprint="revision", connection_id="connection-a",
                        )
                    with patch.object(execution, hook, Mock(side_effect=error_type(private_detail))):
                        with execution.m365_execution_context(ctx):
                            with self.assertRaises(approvals.M365PolicyError) as raised:
                                execution.preflight_m365_manifests([action])
                    self.assertEqual(raised.exception.code, "m365_authorization_unavailable")
                    self.assertNotIn(private_detail, str(raised.exception.payload))
        self.assertEqual(self.container.items, {})

    def test_cached_tool_dependency_failure_never_becomes_an_allowed_result(self):
        self.manifest("m365_email", "email")
        with patch.object(execution, "_action_config_resolver", Mock(side_effect=OSError("private diagnostic"))):
            with execution.m365_execution_context(self.context(shared=False)):
                with self.assertRaises(approvals.M365PolicyError) as raised:
                    execution.authorize_m365_operation("email", "email")
        self.assertEqual(raised.exception.code, "m365_authorization_unavailable")
        self.assertEqual(self.container.items, {})

    def test_pending_approval_exception_is_preserved_through_authorizer_callback(self):
        action = self.manifest("m365_email", "email")
        with execution.m365_execution_context(self.context()):
            with self.assertRaises(approvals.M365ApprovalRequired) as first:
                execution.preflight_m365_manifests([action])
            with patch.object(execution, "_action_config_resolver", Mock(side_effect=first.exception)):
                with self.assertRaises(approvals.M365ApprovalRequired) as repeated:
                    execution.preflight_m365_manifests([action])
        self.assertIs(repeated.exception, first.exception)

    def test_all_effective_sources_share_one_pending_record_with_strict_saved_ceiling(self):
        calendar = self.manifest("m365_calendar", "calendar", enabled=["get_my_events"], policy="request")
        email = self.manifest("m365_email", "email", enabled=["get_my_messages"], policy="today")
        attempted_override = {**calendar, "maximum_sharing_acknowledgement": "always"}
        with execution.m365_execution_context(self.context()):
            with self.assertRaises(approvals.M365ApprovalRequired) as raised:
                execution.preflight_m365_manifests([attempted_override, email])
            current = execution.get_execution_context()
        pending = raised.exception.payload["approval"]
        records = [item for item in self.container.items.values() if item.get("record_kind") == "m365_approval"]
        self.assertEqual(len(records), 1)
        self.assertEqual(set(pending["sources"]), {"calendar", "email"})
        self.assertEqual(pending["sources"]["calendar"]["allowed_durations"], ["request"])
        self.assertEqual(pending["sources"]["email"]["allowed_durations"], ["request", "today"])
        self.assertEqual(current.action_configs["calendar"]["maximum_sharing_acknowledgement"], "request")
        self.assertEqual(calendar["additionalFields"]["maximum_sharing_acknowledgement"], "request")

    def test_preflight_retains_frozen_saved_configuration_not_caller_overlays(self):
        saved = self.manifest(
            "m365_email", "email", enabled=["get_my_messages"],
            policy="today", capabilities={"get_my_messages": True, "send_mail": False},
        )
        overlay = {
            **saved,
            "maximum_sharing_acknowledgement": "always",
            "m365_capabilities": {"get_my_messages": True, "send_mail": True},
        }
        with execution.m365_execution_context(self.context(shared=False)):
            permitted = execution.preflight_m365_manifests([overlay])
            snapshot = execution.get_execution_context().action_configs["email"]
        self.assertEqual(snapshot["type"], "m365_email")
        self.assertEqual(snapshot["source"], "email")
        self.assertEqual(snapshot["additionalFields"], saved["additionalFields"])
        self.assertEqual(snapshot["maximum_sharing_acknowledgement"], "today")
        self.assertEqual(permitted[0]["enabled_functions"], ["get_my_messages"])
        self.saved["email"]["additionalFields"]["m365_capabilities"]["send_mail"] = True
        self.assertFalse(snapshot["additionalFields"]["m365_capabilities"]["send_mail"])
        with self.assertRaises(TypeError):
            snapshot["additionalFields"]["maximum_sharing_acknowledgement"] = "always"

    def test_manifest_cannot_retype_an_authorized_legacy_action(self):
        self.manifest("msgraph", "same-id", enabled=["get_my_messages"])
        retyped = {
            "id": "same-id", "type": "m365_email",
            "enabled_functions": ["get_my_messages"],
        }
        with execution.m365_execution_context(self.context()):
            with self.assertRaises(approvals.M365PolicyError) as raised:
                execution.preflight_m365_manifests([retyped])
        self.assertEqual(raised.exception.code, "m365_action_changed")
        self.assertEqual(self.container.items, {})

    def test_disabled_and_cross_type_functions_are_never_reenabled(self):
        saved = self.manifest(
            "m365_calendar", "calendar", enabled=["get_my_events"],
            capabilities={"get_my_events": False},
        )
        forged_overlay = {
            **saved, "m365_capabilities": {"get_my_events": True, "get_my_messages": True},
            "enabled_functions": ["get_my_events", "get_my_messages"],
        }
        with execution.m365_execution_context(self.context()):
            result = execution.preflight_m365_manifests([forged_overlay])
        self.assertEqual(result, [])
        self.assertEqual(self.container.items, {})

    def test_disabled_and_retained_evidence_only_file_actions_do_not_prompt(self):
        disabled = self.manifest("m365_email", "email", enabled=[])
        retained = self.manifest("m365_sharepoint", "spo", enabled=["read_file_chunk"])
        with execution.m365_execution_context(self.context()):
            permitted = execution.preflight_m365_manifests([disabled, retained])
        self.assertEqual(len(permitted), 1)
        self.assertEqual(permitted[0]["enabled_functions"], ["read_file_chunk"])
        self.assertEqual(self.container.items, {})

    def test_declining_typed_source_prunes_remote_tools_but_keeps_retained_snapshots(self):
        files = self.manifest("m365_onedrive", "files")
        unrelated = {"id": "calculator", "type": "calculator"}
        with execution.m365_execution_context(self.context()):
            with self.assertRaises(approvals.M365ApprovalRequired) as raised:
                execution.preflight_m365_manifests([files, unrelated])
            self.service.decide(raised.exception.approval_id, "user-a", {
                "decisions": {"onedrive": {"duration": "no"}},
            })
            permitted = execution.preflight_m365_manifests([files, unrelated])
            with self.assertRaises(approvals.M365SourceDenied):
                execution.authorize_m365_operation("onedrive", "files")
        self.assertEqual(permitted[0]["enabled_functions"], ["analyze_file", "read_file_chunk"])
        self.assertIs(permitted[1], unrelated)

    def test_legacy_decline_preserves_other_sources_and_survives_repeated_loader_pass(self):
        legacy = self.manifest("msgraph", "legacy")
        app = Flask(__name__)
        with app.test_request_context("/"):
            g.m365_execution_context = self.context()
            with self.assertRaises(approvals.M365ApprovalRequired) as raised:
                execution.preflight_m365_manifests([legacy])
            self.service.decide(raised.exception.approval_id, "user-a", {"decisions": {
                "calendar": {"duration": "request", "timezone": "UTC"},
                "email": {"duration": "no"},
                "onedrive": {"duration": "request", "timezone": "UTC"},
            }})
            first = execution.preflight_m365_manifests([legacy])
            first_scope = approvals.request_scope_fingerprint(execution.get_execution_context())
            repeated = execution.preflight_m365_manifests(first)
            repeated_scope = approvals.request_scope_fingerprint(execution.get_execution_context())
            declined = list(g.m365_declined_sources)
        enabled = repeated[0]["enabled_functions"]
        self.assertNotIn("get_my_messages", enabled)
        self.assertNotIn("send_mail", enabled)
        self.assertNotIn("mark_message_as_read", enabled)
        self.assertIn("get_my_events", enabled)
        self.assertIn("list_drive_items", enabled)
        self.assertIn("get_my_security_alerts", enabled)
        self.assertEqual(first_scope, repeated_scope)
        self.assertEqual(first[0]["enabled_functions"], enabled)
        self.assertIn("email", declined)

    def test_preflight_does_not_trust_an_unresolved_saved_action(self):
        manifest = {"id": "forged", "type": "m365_email", "enabled_functions": ["get_my_messages"]}
        with execution.m365_execution_context(self.context()):
            with self.assertRaises(approvals.M365PolicyError) as raised:
                execution.preflight_m365_manifests([manifest])
        self.assertEqual(raised.exception.code, "m365_action_not_authorized")
        self.assertEqual(self.container.items, {})

    def test_without_resolver_an_explicit_owner_authorized_action_snapshot_is_required(self):
        manifest = self.manifest("m365_email", "email")
        with patch.object(execution, "_action_config_resolver", None):
            with execution.m365_execution_context(self.context()):
                with self.assertRaises(approvals.M365PolicyError):
                    execution.preflight_m365_manifests([manifest])
            with execution.m365_execution_context(self.context(shared=False, action_configs={
                "email": {"type": "m365_email", "maximum_sharing_acknowledgement": "today"},
            })):
                allowed = execution.preflight_m365_manifests([manifest])
        self.assertEqual(allowed[0]["maximum_sharing_acknowledgement"], "today")

    def test_malformed_input_is_safe_policy_failure_not_unrestricted_fallback(self):
        valid = self.manifest("m365_email", "email")
        for manifests in (
            [valid, valid],
            [{**valid, "additionalFields": "invalid"}],
            [{**valid, "enabled_functions": "get_my_messages"}],
        ):
            with self.subTest(manifests=manifests):
                with execution.m365_execution_context(self.context()):
                    with self.assertRaises(approvals.M365PolicyError):
                        execution.preflight_m365_manifests(manifests)

    def test_workflow_resolver_prepares_binding_before_sharing_without_swapping_principal(self):
        manifest = self.manifest("m365_email", "email", enabled=["get_my_messages"])
        connection = {
            "id": "connection-a", "user_id": "user-a", "tenant_id": "tenant-a",
            "generation": 1, "status": "connected", "sources": ["email"],
        }
        def binding_resolver(context, manifests, policies):
            resolved = replace(context, connection_id="connection-a", workflow_fingerprint="revision-a")
            approval = self.service.ensure_workflow_binding(
                resolved, policies, connection, review=WORKFLOW_REVIEW,
            )
            return replace(resolved, binding_id=approval["id"])
        connection_service = types.SimpleNamespace(read_connection=lambda *args: copy.deepcopy(connection))
        with patch.object(execution, "_workflow_binding_resolver", binding_resolver), patch.object(
            connections, "_service", connection_service,
        ):
            with execution.m365_execution_context(self.context(
                actor_user_id="caller", workflow_id="workflow-a", run_id="run-a", shared=False,
            )):
                with self.assertRaises(approvals.M365ApprovalRequired) as raised:
                    execution.preflight_m365_manifests([manifest])
                self.assertEqual(raised.exception.request_type, approvals.TYPE_WORKFLOW_RUN_AS)
                self.service.decide(raised.exception.approval_id, "user-a", {"choice": "approve"})
                allowed = execution.preflight_m365_manifests([manifest])
                resolved_context = execution.get_execution_context()
        self.assertEqual(allowed[0]["id"], "email")
        self.assertEqual(resolved_context.actor_user_id, "caller")
        self.assertEqual(resolved_context.data_user_id, "user-a")
        self.assertEqual(resolved_context.binding_id, raised.exception.approval_id)

    def test_workflow_hook_cannot_replace_actor_data_user_audience_or_action_snapshot(self):
        manifest = self.manifest("m365_email", "email")
        for changes in (
            {"actor_user_id": "other"},
            {"data_user_id": "other"},
            {"conversation_id": "other"},
            {"audience_version": "other"},
            {"action_configs": {}},
        ):
            with self.subTest(changes=changes):
                with patch.object(execution, "_workflow_binding_resolver", lambda ctx, *_: replace(ctx, **changes)):
                    with execution.m365_execution_context(self.context(
                        workflow_id="workflow-a", run_id="run-a",
                    )):
                        with self.assertRaises(approvals.M365PolicyError) as raised:
                            execution.preflight_m365_manifests([manifest])
                self.assertEqual(raised.exception.code, "m365_principal_mismatch")

    def test_workflow_binding_uses_actual_effective_manifests_not_stored_revision(self):
        manifest = self.manifest("m365_calendar", "calendar", enabled=["get_my_events"])
        workflow = {
            "id": "workflow-a", "user_id": "owner", "task_prompt": "Summarize my calendar.",
            "m365_run_as_user_id": "user-a", "m365_revision": "stored-revision-is-not-authority",
        }
        connection = {
            "id": "connection-a", "user_id": "user-a", "tenant_id": "tenant-a",
            "generation": 1, "status": "connected", "sources": ["calendar"],
        }
        lookups = []
        def current_connection(user_id, tenant_id):
            lookups.append((user_id, tenant_id))
            return copy.deepcopy(connection)
        service = types.SimpleNamespace(current_connection=current_connection)
        ctx = self.context(actor_user_id="manual-caller", workflow_id="workflow-a", run_id="run-a")
        with patch.object(connections, "_service", service):
            prepared = execution.prepare_m365_workflow_binding(ctx, workflow, [manifest], review=WORKFLOW_REVIEW)
            self.service.decide(prepared.binding_id, "user-a", {"choice": "approve"})
            next_run = execution.prepare_m365_workflow_binding(
                replace(ctx, request_id="request-b", run_id="run-b"),
                workflow, [manifest], review=WORKFLOW_REVIEW,
            )
            changed_manifest = {**manifest, "enabled_functions": ["get_my_events", "get_my_timezone"]}
            changed = execution.prepare_m365_workflow_binding(
                ctx, workflow, [changed_manifest], review=WORKFLOW_REVIEW,
            )
        expected_fingerprint = workflow_execution_fingerprint(workflow, [manifest])
        changed_fingerprint = workflow_execution_fingerprint(workflow, [changed_manifest])
        self.assertEqual(prepared.workflow_fingerprint, expected_fingerprint)
        self.assertNotEqual(prepared.workflow_fingerprint, workflow["m365_revision"])
        self.assertEqual(prepared.binding_id, next_run.binding_id)
        self.assertEqual(changed.workflow_fingerprint, changed_fingerprint)
        self.assertNotEqual(changed.binding_id, prepared.binding_id)
        self.assertEqual(prepared.actor_user_id, "manual-caller")
        self.assertEqual(prepared.data_user_id, "user-a")
        self.assertEqual(lookups, [("user-a", "tenant-a")] * 3)

    def test_workflow_binding_never_infers_selected_account_from_owner_or_caller(self):
        manifest = self.manifest("m365_email", "email", enabled=["get_my_messages"])
        ctx = self.context(actor_user_id="caller", workflow_id="workflow-a", run_id="run-a")
        for workflow in (
            {"id": "workflow-a", "user_id": "owner"},
            {"id": "workflow-a", "user_id": "owner", "m365_run_as_user_id": "caller"},
            {"id": "workflow-b", "m365_run_as_user_id": "user-a"},
        ):
            with self.subTest(workflow=workflow):
                with patch.object(connections, "get_m365_connection_service") as lookup:
                    with self.assertRaises(approvals.M365PolicyError):
                        execution.prepare_m365_workflow_binding(ctx, workflow, [manifest], review=WORKFLOW_REVIEW)
                    lookup.assert_not_called()
        with patch.object(execution, "_workflow_validator", lambda ctx: False), patch.object(
            connections, "get_m365_connection_service",
        ) as lookup:
            with self.assertRaises(approvals.M365PolicyError):
                execution.prepare_m365_workflow_binding(
                    ctx, {"id": "workflow-a", "m365_run_as_user_id": "user-a"},
                    [manifest], review=WORKFLOW_REVIEW,
                )
            lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
