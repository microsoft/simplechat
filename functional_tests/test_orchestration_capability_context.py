# test_orchestration_capability_context.py
"""
Regression tests for truthful orchestration resources, requirements and reasoning notices.

Version: 0.261.104
Implemented in: 0.261.104

Executes production definitions with explicit offline storage boundaries. In particular,
the real agent label-map functions receive records resolved by the real membership helper.
"""

import json
import sys
import types
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Standalone execution needs the repository path before importing local test helpers.
from functional_tests.test_support.orchestration_research import _definitions, planner_runtime  # noqa: E402


class AgentDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("Unexpected network access.")))
        self.current_groups = [{"id": "allowed-group", "name": "Current group name"}]
        self.groups = types.SimpleNamespace(
            get_user_groups=Mock(side_effect=lambda _user: deepcopy(self.current_groups)),
            assert_group_role=Mock(),
        )
        identifier = _definitions("functions_agent_delegation.py", names={"_identifier"})["_identifier"]
        self.group_api = _definitions("functions_action_catalog.py", seed={
            "_identifier": identifier,
            "import_module": lambda name: {"functions_group": self.groups}[name],
        }, names={
            "_GROUP_ROLES", "_INVALID_REFERENCE", "_stored_identifier", "_require_actor",
            "_selected_group_ids", "_current_groups", "_assert_group_access", "resolve_current_user_groups",
        })
        self.model_reads = Mock(return_value=[])
        self.action_reads = Mock(return_value=[])
        self.agent_reads = Mock(return_value=[{"id": "agent-1", "name": "Group helper"}])
        self.catalog_api = _definitions("functions_agent_catalog.py", seed={
            "resolve_current_user_groups": self.group_api["resolve_current_user_groups"],
            "normalize_model_endpoints": lambda values: (values, False),
            "get_group_model_endpoints": self.model_reads,
            "get_global_actions": lambda **_kwargs: [],
            "filter_governed_global_actions_for_user": lambda _user, actions: actions,
            "SecretReturnType": types.SimpleNamespace(NAME="name"),
            "get_group_actions": self.action_reads,
            "filter_actions_by_action_type_access": lambda _user, actions, *_args: actions,
            "_should_include_global_agents": lambda _settings: False,
            "get_group_agents": self.agent_reads,
            "_serialize_catalog_agent": lambda agent, **scope: {**agent, **scope},
        }, names={
            "build_accessible_agent_catalog", "_build_model_label_map",
            "_add_model_labels_from_endpoints", "_build_action_label_map", "_add_action_labels",
            "build_agent_catalog_key",
        })
        self.settings = {
            "enable_group_workspaces": True, "allow_group_agents": True,
            "allow_group_custom_endpoints": True, "allow_group_plugins": True,
        }

    def catalog(self, selectors):
        return self.catalog_api["build_accessible_agent_catalog"](
            "user-1", settings=self.settings, user_groups=selectors,
        )

    def test_id_strings_are_resolved_before_real_model_and_action_label_maps(self):
        catalog = self.catalog(["allowed-group"])
        self.assertEqual(catalog[0]["scope_id"], "allowed-group")
        self.assertEqual(catalog[0]["scope_name"], "Current group name")
        self.model_reads.assert_called_once_with("allowed-group")
        self.action_reads.assert_called_once_with("allowed-group", return_type="name")
        self.groups.assert_group_role.assert_called_once_with(
            "user-1", "allowed-group", allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        )

    def test_client_group_records_only_narrow_current_membership(self):
        catalog = self.catalog([
            {"id": "allowed-group", "name": "FORGED LABEL", "role": "Owner"},
            {"id": "foreign-group", "name": "FORGED OTHER GROUP"},
        ])
        self.assertEqual([row["scope_id"] for row in catalog], ["allowed-group"])
        self.assertNotIn("FORGED", repr(catalog))
        self.agent_reads.assert_called_once_with("allowed-group")

    def test_nonmember_and_revoked_group_scopes_do_not_reach_resource_reads(self):
        self.assertEqual(self.catalog(["foreign-group"]), [])
        self.groups.assert_group_role.side_effect = PermissionError("Membership was revoked.")
        self.assertEqual(self.catalog(["allowed-group"]), [])
        self.model_reads.assert_not_called()
        self.action_reads.assert_not_called()
        self.agent_reads.assert_not_called()

    def context_resolver(self, builder):
        runtime = self.stack.enter_context(planner_runtime())
        module = types.ModuleType("functions_agent_catalog")
        module.build_accessible_agent_catalog = builder
        module.build_agent_catalog_key = self.catalog_api["build_agent_catalog_key"]
        self.stack.enter_context(patch.dict(sys.modules, {"functions_agent_catalog": module}))
        context = _definitions("functions_orchestration_context.py", seed=runtime.registry, names={
            "_text", "CatalogResolutionError", "resolve_agent_catalog",
        })
        descriptor = runtime.registry["get_capability"]("agent_invoke")
        settings = {
            key: True for key in (*descriptor["settings_gates"], *descriptor["settings_gates_any"])
        }
        return context, settings

    def test_selected_agent_is_resolved_from_current_authorized_records(self):
        agent = {
            "id": "agent-1", "name": "chosen", "display_name": "Current name",
            "scope_type": "personal", "scope_id": "user-1",
        }
        builder = Mock(return_value=[agent, {**agent, "id": "agent-2", "name": "alternative"}])
        context, settings = self.context_resolver(builder)
        result = context["resolve_agent_catalog"](
            "user-1", seeds={"agent": {"name": "chosen", "display_name": "FORGED"}},
            settings=settings,
        )
        self.assertEqual(result, [agent])
        builder.assert_called_once()
        builder.return_value = []
        with self.assertRaises(context["CatalogResolutionError"]):
            context["resolve_agent_catalog"](
                "user-1", seeds={"agent": {"name": "chosen"}}, settings=settings,
            )

    def test_catalog_failure_is_not_reported_as_an_empty_authorized_catalog(self):
        context, settings = self.context_resolver(Mock(side_effect=RuntimeError("Private storage error.")))
        with self.assertRaises(context["CatalogResolutionError"]) as raised:
            context["resolve_agent_catalog"]("user-1", settings=settings)
        self.assertNotIn("Private storage error", raised.exception.message)


class RequirementAndNoticeTests(unittest.TestCase):
    def setUp(self):
        self.runtime_scope = planner_runtime()
        self.runtime = self.runtime_scope.__enter__()
        self.addCleanup(self.runtime_scope.__exit__, None, None, None)

    def test_normalization_cannot_silently_lose_selected_work(self):
        plan = {"steps": [{"capability_id": "respond", "arguments": {}}]}
        check = self.runtime.schema["validate_plan_requirements"]
        with self.assertRaises(self.runtime.schema["PlanValidationError"]):
            check(deepcopy(plan), {"required_capabilities": ["deep_research"]})
        with self.assertRaises(self.runtime.schema["PlanValidationError"]):
            check(deepcopy(plan), {"agent": {"name": "chosen"}})
        self.assertEqual(check(deepcopy(plan), {"web_search": False}), plan)

    def test_explicit_later_narrowing_stays_possible_but_visible(self):
        plan = {"steps": [{"capability_id": "respond", "arguments": {}}]}
        checked = self.runtime.schema["validate_plan_requirements"](
            plan, {"web_search": True}, allow_changes=True,
        )
        self.assertTrue(checked["validation"]["repairs"])
        self.assertIn("Review this change", checked["validation"]["repairs"][0])
        self.runtime.schema["validate_plan_requirements"](
            checked, {"web_search": True}, allow_changes=True,
        )
        self.assertEqual(len(checked["validation"]["repairs"]), 1)

    def test_selected_documents_must_be_in_the_effective_search_or_read_scope(self):
        check = self.runtime.schema["validate_plan_requirements"]
        seeds = {"document_ids": ["document-a", "document-b"]}
        plan = {"steps": [{
            "capability_id": "document_search", "arguments": {"document_ids": ["document-a"]},
        }]}
        with self.assertRaises(self.runtime.schema["PlanValidationError"]):
            check(deepcopy(plan), seeds)
        plan["steps"][0]["arguments"] = {"query": "Search the selected documents."}
        check(plan, seeds)

    def test_runtime_notices_report_effective_default_and_keep_model_roles_separate(self):
        events = _definitions("functions_orchestration_events.py")
        binding = types.SimpleNamespace(
            behavior_name="gpt-5.6-luna", deployment="custom-deployment",
            reasoning_resolution={
                "requested_effort": "minimal", "effective_effort": "low",
                "mode": "explicit", "adjustment_reason": "unsupported_value",
            },
        )
        planner = events["build_model_reasoning_metadata"](binding, "planner")
        binding.reasoning_resolution.update(
            effective_effort=None, mode="model_default", adjustment_reason="provider_rejected",
        )
        answer = events["build_model_reasoning_metadata"](binding, "answer")
        self.assertIsNone(answer["reasoning_effort"])
        self.assertEqual(answer["reasoning_mode"], "model_default")
        adjustments = events["merge_reasoning_adjustments"](
            planner["reasoning_adjustments"], answer["reasoning_adjustments"],
        )
        self.assertEqual(len(adjustments), 2)
        frame = events["build_reasoning_adjustment_event"](adjustments)
        payload = json.loads(frame.removeprefix("data:").strip())
        self.assertEqual(payload["type"], "thought")
        self.assertIn("Model default", payload["content"])
        done = json.loads(events["build_run_done_event"](
            "conversation", **answer,
        ).removeprefix("data:").strip())
        self.assertEqual(done["reasoning_mode"], "model_default")
        self.assertEqual(done["reasoning_adjustments"], answer["reasoning_adjustments"])
        self.assertEqual(events["merge_reasoning_adjustments"](
            {"malformed": "not an array"}, "not an array", [None, {"stage": []}],
        ), [])


if __name__ == "__main__":
    unittest.main()
