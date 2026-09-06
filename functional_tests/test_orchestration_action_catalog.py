# test_orchestration_action_catalog.py
#!/usr/bin/env python3
"""Functional coverage for governed orchestration action discovery and resolution.

Version: 0.261.098
Implemented in: 0.261.098

Exercises the real catalog and governance decisions with isolated storage,
membership, and Key Vault seams. No Azure calls or plugin initialization occur.
"""

import base64
import importlib
import json
import sys
import unittest
from contextlib import ExitStack
from copy import deepcopy
from enum import Enum
from types import ModuleType
from unittest.mock import Mock, patch

from test_support.app_stubs import stubbed_app_imports, stubbed_config


class _MissingAction(Exception):
    pass


class _SecretReturnType(Enum):
    VALUE = "value"
    TRIGGER = "trigger"
    NAME = "name"


def _module(name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    return module


def _reference(scope, scope_id, action_id):
    def encode(value):
        return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")

    return f"action:v1:{scope}:{encode(scope_id)}:{encode(action_id)}"


class _ActionContainer:
    def __init__(self, scope):
        self.scope = scope
        self.records = {}
        self.query_items = Mock(side_effect=self._query)
        self.read_item = Mock(side_effect=self._read)

    def _query(self, **options):
        partition = options.get("partition_key")
        return [
            deepcopy(record)
            for (record_partition, _), record in self.records.items()
            if self.scope == "global" or record_partition == partition
        ]

    def _read(self, *, item, partition_key):
        try:
            return deepcopy(self.records[(partition_key, item)])
        except KeyError:
            raise _MissingAction("PRIVATE_STORAGE_DETAIL") from None


class ActionCatalogTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.settings = {
            "enable_semantic_kernel": True,
            "enable_user_workspace": True,
            "enable_group_workspaces": True,
            "allow_user_plugins": True,
            "allow_group_plugins": True,
            "per_user_semantic_kernel": True,
            "merge_global_semantic_kernel_with_workspace": True,
            "allow_user_agents": False,
            "allow_group_agents": False,
            "governance_user_actions": True,
            "governance_group_actions": True,
            "governance_global_actions_usage": True,
        }
        self.containers = {
            scope: _ActionContainer(scope) for scope in ("personal", "group", "global")
        }
        self.groups = [
            {"id": "group-one", "name": "Engineering"},
            {"id": "group-two", "name": "Operations"},
        ]
        self.roles = {"group-one": "User", "group-two": "User"}
        self.group_module = _module(
            "functions_group",
            get_user_groups=Mock(side_effect=lambda user_id: deepcopy(self.groups)),
            assert_group_role=Mock(side_effect=self._assert_group_role),
        )
        self.keyvault = _module(
            "functions_keyvault",
            SecretReturnType=_SecretReturnType,
            keyvault_plugin_get_helper=Mock(side_effect=lambda manifest, **kwargs: deepcopy(manifest)),
            retrieve_secret_from_key_vault_by_full_name=Mock(
                side_effect=AssertionError("Secret resolution is forbidden during discovery.")
            ),
        )
        self.identities = _module(
            "functions_workspace_identities",
            hydrate_action_identity_reference=Mock(
                side_effect=AssertionError("Workspace identity hydration belongs to execution.")
            ),
            get_workspace_identity_auth=Mock(
                side_effect=AssertionError("Workspace identity credentials must not be read.")
            ),
        )
        self.stack.enter_context(stubbed_config(
            **{f"cosmos_{scope}_actions_container": container for scope, container in self.containers.items()},
            cosmos_governance_item_policies_container=Mock(),
            cosmos_governance_policies_container=Mock(),
        ))
        self.stack.enter_context(patch.dict(sys.modules, {
            "functions_group": self.group_module,
            "functions_public_workspaces": _module(
                "functions_public_workspaces", get_user_public_workspaces=lambda user_id: [],
            ),
            "functions_keyvault": self.keyvault,
            "functions_workspace_identities": self.identities,
            "app_settings_cache": _module("app_settings_cache", get_governance_cache_version=lambda: 0),
            "azure.cosmos.exceptions": _module(
                "azure.cosmos.exceptions", CosmosResourceNotFoundError=_MissingAction,
            ),
            "functions_personal_actions": None,
            "functions_group_actions": None,
            "functions_global_actions": None,
            "semantic_kernel": None,
            "semantic_kernel_loader": None,
            "semantic_kernel_plugins.logged_plugin_loader": None,
        }))
        sys.modules.pop("functions_action_catalog", None)
        sys.modules.pop("functions_governance", None)
        self.catalog = importlib.import_module("functions_action_catalog")
        self.governance = importlib.import_module("functions_governance")
        self.get_settings = Mock(side_effect=lambda: deepcopy(self.settings))
        self.stack.enter_context(patch.object(
            sys.modules["functions_settings"], "get_settings", self.get_settings,
        ))
        self.stack.enter_context(patch.object(self.governance, "get_settings", self.get_settings))
        self.feature_policies = {}
        self.type_policies = {}
        self.item_policies = {}
        self.stack.enter_context(patch.object(
            self.governance, "get_feature_policy",
            side_effect=lambda feature: self.feature_policies.get(feature, {"allow_all": True}),
        ))
        self.stack.enter_context(patch.object(
            self.governance, "get_explicit_item_policies",
            side_effect=lambda entity, item: self.type_policies.get((entity, item), []),
        ))
        self.stack.enter_context(patch.object(
            self.governance, "get_item_policies",
            side_effect=lambda entity, item: self.item_policies.get((entity, item), [{"allow_all": True}]),
        ))
        self.stack.enter_context(patch.object(
            self.governance, "get_user_governance_group_ids",
            side_effect=lambda user_id: set(self.roles),
        ))

    def _assert_group_role(self, user_id, group_id, allowed_roles):
        self.assertEqual(user_id, "actor")
        role = self.roles.get(group_id)
        if role not in allowed_roles:
            raise PermissionError("PRIVATE_MEMBERSHIP_DETAIL")
        return role

    def store(self, scope, action_id="shared-id", scope_id=None, **fields):
        scope_id = scope_id or {"personal": "actor", "group": "group-one", "global": "global"}[scope]
        action = {
            "id": action_id,
            "name": "same-name",
            "displayName": "Ticket lookup",
            "description": "Find ticket details.",
            "type": "openapi",
            "metadata": {},
            "additionalFields": {},
        }
        if scope == "personal":
            action["user_id"] = scope_id
        elif scope == "group":
            action["group_id"] = scope_id
        else:
            action["is_global"] = True
        action.update(fields)
        partition = action_id if scope == "global" else scope_id
        self.containers[scope].records[(partition, action_id)] = action
        return action

    def discover(self, **kwargs):
        kwargs.setdefault("settings", self.settings)
        return self.catalog.build_accessible_action_catalog("actor", **kwargs)

    def resolve(self, scope="personal", action_id="shared-id", scope_id=None, **kwargs):
        scope_id = scope_id or {"personal": "actor", "group": "group-one", "global": "global"}[scope]
        kwargs.setdefault("settings", self.settings)
        return self.catalog.resolve_action_manifest(
            "actor", _reference(scope, scope_id, action_id), **kwargs,
        )

    def assert_no_action_reads(self):
        for container in self.containers.values():
            container.query_items.assert_not_called()
            container.read_item.assert_not_called()

    def test_scope_collisions_remain_distinct_without_configured_agents(self):
        for scope in self.containers:
            self.store(scope)
        self.store("group", scope_id="group-two")
        actions = self.discover()
        self.assertEqual(len(actions), 4)
        self.assertEqual(len({action["action_ref"] for action in actions}), 4)
        self.assertEqual({action["name"] for action in actions}, {"same-name"})
        self.assertEqual({action["id"] for action in actions}, {"shared-id"})
        self.assertEqual(
            {(action["scope_type"], action["scope_id"]) for action in actions},
            {("personal", "actor"), ("global", "global"), ("group", "group-one"), ("group", "group-two")},
        )
        for action in actions:
            manifest = self.catalog.resolve_action_manifest(
                "actor", action["action_ref"], settings=self.settings,
            )
            self.assertEqual(manifest["scope_type"], action["scope_type"])
            self.assertEqual(manifest["scope_id"], action["scope_id"])

    def test_reference_is_stable_when_display_name_and_name_change(self):
        stored = self.store("personal")
        reference = self.discover()[0]["action_ref"]
        stored.update(name="renamed", displayName="New display name")
        self.assertEqual(self.discover()[0]["action_ref"], reference)
        self.assertEqual(self.resolve()["name"], "renamed")

    def test_reference_handles_unicode_and_delimiter_collisions(self):
        action_id = "tickets:west:é"
        self.store("personal", action_id=action_id)
        action = self.discover()[0]
        self.assertEqual(action["action_ref"], _reference("personal", "actor", action_id))
        self.assertEqual(self.resolve(action_id=action_id)["id"], action_id)
        self.assertNotEqual(
            _reference("personal", "actor:a", "b"), _reference("personal", "actor", "a:b"),
        )

    def test_personal_reads_are_partitioned_and_match_exact_ownership(self):
        self.store("personal")
        self.store("personal", action_id="foreign", user_id="another-user")
        actions = self.discover()
        self.assertEqual([action["id"] for action in actions], ["shared-id"])
        self.containers["personal"].query_items.assert_called_once_with(
            query="SELECT * FROM c WHERE c.user_id = @scope_id",
            parameters=[{"name": "@scope_id", "value": "actor"}],
            partition_key="actor",
        )
        self.resolve()
        self.containers["personal"].read_item.assert_called_once_with(
            item="shared-id", partition_key="actor",
        )
        with self.assertRaises(PermissionError):
            self.resolve(action_id="foreign")

    def test_foreign_personal_reference_is_rejected_before_storage(self):
        self.store("personal", scope_id="another-user")
        with self.assertRaises(PermissionError):
            self.resolve(scope_id="another-user")
        self.assert_no_action_reads()

    def test_missing_record_never_falls_back_to_an_action_name(self):
        self.store("personal", action_id="replacement", name="shared-id")
        with self.assertRaisesRegex(LookupError, "^The action is unavailable"):
            self.resolve()
        self.containers["personal"].query_items.assert_not_called()
        self.keyvault.keyvault_plugin_get_helper.assert_not_called()

    def test_missing_id_is_not_replaced_with_a_name(self):
        self.store("personal", id=None)
        self.assertEqual(self.discover(), [])
        with self.assertRaises(LookupError):
            self.resolve()

    def test_point_read_result_must_match_original_id(self):
        self.containers["personal"].read_item.side_effect = None
        self.containers["personal"].read_item.return_value = {
            "id": "different", "user_id": "actor", "name": "shared-id", "type": "openapi",
        }
        with self.assertRaises(LookupError):
            self.resolve()
        self.keyvault.keyvault_plugin_get_helper.assert_not_called()

    def test_groups_use_current_memberships_and_authoritative_labels(self):
        self.store("group")
        self.store("group", scope_id="group-two")
        actions = self.discover(user_groups=[{
            "id": "group-one", "name": "FORGED_LABEL", "userRole": "Owner",
        }])
        self.assertEqual([action["scope_id"] for action in actions], ["group-one"])
        self.assertEqual(actions[0]["scope_label"], "Engineering")
        self.group_module.get_user_groups.assert_called_once_with("actor")
        self.group_module.assert_group_role.assert_called_once_with(
            "actor", "group-one", allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        )
        self.containers["group"].query_items.assert_called_once_with(
            query="SELECT * FROM c WHERE c.group_id = @scope_id",
            parameters=[{"name": "@scope_id", "value": "group-one"}],
            partition_key="group-one",
        )

    def test_group_selection_supports_runtime_group_ids_without_expanding_access(self):
        self.store("group")
        self.store("group", scope_id="group-two")
        actions = self.discover(user_groups=["group-two"])
        self.assertEqual([action["scope_id"] for action in actions], ["group-two"])
        self.assertEqual(self.resolve("group", scope_id="group-two", user_groups=["group-two"])["scope_id"], "group-two")
        with self.assertRaises(PermissionError):
            self.resolve("group", user_groups=["group-two"])

    def test_missing_group_selection_follows_all_live_memberships_not_active_scope(self):
        self.settings["activeGroupOid"] = "unrelated-group"
        self.store("group")
        self.store("group", scope_id="group-two")
        self.assertEqual({action["scope_id"] for action in self.discover()}, {"group-one", "group-two"})

    def test_tampered_group_selection_cannot_authorize_membership(self):
        self.store("group", scope_id="forbidden-group")
        selection = [{"id": "forbidden-group", "users": [{"userId": "actor", "role": "Owner"}]}]
        self.assertEqual(self.discover(user_groups=selection), [])
        with self.assertRaises(PermissionError):
            self.resolve("group", scope_id="forbidden-group", user_groups=selection)
        self.containers["group"].query_items.assert_not_called()
        self.containers["group"].read_item.assert_not_called()

    def test_stale_membership_listing_is_rechecked_before_group_read(self):
        self.store("group")
        self.roles.pop("group-one")
        self.assertEqual(self.discover(user_groups=["group-one"]), [])
        with self.assertRaisesRegex(PermissionError, "^The action is unavailable"):
            self.resolve("group", user_groups=["group-one"])
        self.containers["group"].query_items.assert_not_called()
        self.containers["group"].read_item.assert_not_called()

    def test_group_role_revocation_after_planning_is_enforced(self):
        self.store("group")
        reference = self.discover(user_groups=["group-one"])[0]["action_ref"]
        self.roles["group-one"] = "Reader"
        with self.assertRaises(PermissionError):
            self.catalog.resolve_action_manifest(
                "actor", reference, settings=self.settings, user_groups=["group-one"],
            )
        self.containers["group"].read_item.assert_not_called()

    def test_group_membership_removal_after_planning_is_enforced(self):
        self.store("group")
        selection = deepcopy(self.groups)
        reference = self.discover(user_groups=selection)[0]["action_ref"]
        self.groups = []
        with self.assertRaises(PermissionError):
            self.catalog.resolve_action_manifest(
                "actor", reference, settings=self.settings, user_groups=selection,
            )
        self.containers["group"].read_item.assert_not_called()

    def test_all_existing_group_usage_roles_are_supported(self):
        self.store("group")
        for role in ("Owner", "Admin", "DocumentManager", "User"):
            with self.subTest(role=role):
                self.roles["group-one"] = role
                self.assertEqual(len(self.discover(user_groups=["group-one"])), 1)
                self.assertEqual(self.resolve("group")["group_id"], "group-one")

    def test_group_record_cannot_escape_its_partition(self):
        self.store("group", group_id="different-group")
        self.assertEqual(self.discover(), [])
        with self.assertRaises(PermissionError):
            self.resolve("group")

    def test_empty_group_selection_disables_group_discovery_and_resolution(self):
        self.store("group")
        self.assertEqual(self.discover(user_groups=[]), [])
        with self.assertRaises(PermissionError):
            self.resolve("group", user_groups=[])
        self.group_module.get_user_groups.assert_not_called()

    def test_invalid_group_selection_never_falls_back_to_all_groups(self):
        self.store("group")
        self.assertEqual(self.discover(user_groups=[None, {}, {"id": "bad/id"}]), [])
        for selection in (False, 123, "group-one", {"id": "group-one"}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.discover(user_groups=selection)
        self.containers["group"].query_items.assert_not_called()

    def test_semantic_kernel_disable_skips_every_storage_source(self):
        self.settings["enable_semantic_kernel"] = False
        self.assertEqual(self.discover(), [])
        with self.assertRaises(PermissionError):
            self.resolve("global")
        self.assert_no_action_reads()
        self.group_module.get_user_groups.assert_not_called()

    def test_explicit_empty_settings_do_not_fall_back_to_enabled_settings(self):
        self.assertEqual(self.catalog.build_accessible_action_catalog("actor", settings={}), [])
        self.get_settings.assert_not_called()
        self.assert_no_action_reads()

    def test_personal_and_group_scope_flags_block_planned_actions(self):
        for scope in ("personal", "group"):
            self.store(scope)
        for flag, scope in (
            ("allow_user_plugins", "personal"),
            ("enable_user_workspace", "personal"),
            ("allow_group_plugins", "group"),
            ("enable_group_workspaces", "group"),
        ):
            with self.subTest(flag=flag):
                settings = {**self.settings, flag: False}
                self.assertNotIn(scope, {item["scope_type"] for item in self.discover(settings=settings)})
                with self.assertRaises(PermissionError):
                    self.resolve(scope, settings=settings)

    def test_global_visibility_honors_workspace_merge_without_retagging(self):
        self.store("global")
        for workspace_mode, merge, visible in (
            (False, False, True),
            (False, True, True),
            (True, False, False),
            (True, True, True),
        ):
            with self.subTest(workspace_mode=workspace_mode, merge=merge):
                settings = {
                    **self.settings,
                    "per_user_semantic_kernel": workspace_mode,
                    "merge_global_semantic_kernel_with_workspace": merge,
                }
                actions = self.discover(settings=settings)
                self.assertEqual(len(actions), int(visible))
                if visible:
                    self.assertEqual(actions[0]["scope_type"], "global")
                    self.assertEqual(actions[0]["scope_id"], "global")
                    self.assertEqual(self.resolve("global", settings=settings)["scope"], "global")
                else:
                    with self.assertRaises(PermissionError):
                        self.resolve("global", settings=settings)

    def test_global_resolution_uses_id_partition(self):
        self.store("global")
        self.resolve("global")
        self.containers["global"].read_item.assert_called_once_with(
            item="shared-id", partition_key="shared-id",
        )

    def test_global_item_governance_is_not_replaced_by_type_governance(self):
        self.store("global")
        self.item_policies[("global_action", "shared-id")] = [{
            "allow_all": False, "allowed_users": ["another-user"],
        }]
        self.assertEqual(self.discover(), [])
        with self.assertRaisesRegex(PermissionError, "^The action is unavailable"):
            self.resolve("global")

    def test_global_explicit_item_deny_wins_over_allow(self):
        self.store("global")
        self.item_policies[("global_action", "shared-id")] = [
            {"allow_all": True}, {"allow_all": True, "denied_users": ["actor"]},
        ]
        self.assertEqual(self.discover(), [])
        with self.assertRaises(PermissionError):
            self.resolve("global")

    def test_type_governance_applies_to_every_scope_and_normalizes_aliases(self):
        for scope in self.containers:
            self.store(scope, type="sql_query")
            self.type_policies[(f"{scope}_action_type", "sql")] = [{
                "allow_all": True, "denied_users": ["actor"],
            }]
        self.assertEqual(self.discover(), [])
        for scope in self.containers:
            with self.subTest(scope=scope):
                with self.assertRaises(PermissionError):
                    self.resolve(scope)

    def test_feature_policy_and_explicit_type_allow_use_existing_governance(self):
        self.store("personal", type="mcp")
        self.feature_policies["governance_user_actions"] = {"allow_all": False}
        self.assertEqual(self.discover(), [])
        self.type_policies[("personal_action_type", "mcp")] = [{
            "allow_all": False, "allowed_users": ["actor"],
        }]
        self.assertEqual(len(self.discover()), 1)
        self.feature_policies["governance_user_actions"]["denied_users"] = ["actor"]
        self.assertEqual(self.discover(), [])

    def test_governance_disabled_does_not_add_an_action_type_allowlist(self):
        self.store("personal", type="future_custom_action")
        self.store("global", type="future_custom_action")
        self.settings["governance_user_actions"] = False
        self.settings["governance_global_actions_usage"] = False
        self.feature_policies["governance_user_actions"] = {"allow_all": False}
        self.item_policies[("global_action", "shared-id")] = [{"allow_all": False}]
        self.assertEqual(len(self.discover()), 2)
        self.assertEqual(self.resolve()["type"], "future_custom_action")
        self.assertEqual(self.resolve("global")["type"], "future_custom_action")

    def test_disabled_records_are_rejected_even_with_governance_off(self):
        for scope in self.containers:
            self.store(scope, is_enabled=False)
        for flag in ("governance_user_actions", "governance_group_actions", "governance_global_actions_usage"):
            self.settings[flag] = False
        self.assertEqual(self.discover(), [])
        for scope in self.containers:
            with self.subTest(scope=scope):
                with self.assertRaises(PermissionError):
                    self.resolve(scope)

    def test_non_boolean_enabled_values_fail_closed(self):
        for enabled in (None, "false", "true", 0, 1):
            with self.subTest(enabled=enabled):
                self.store("personal", is_enabled=enabled)
                self.assertEqual(self.discover(), [])
                with self.assertRaises(PermissionError):
                    self.resolve()

    def test_disabled_record_is_refreshed_after_planning(self):
        stored = self.store("global")
        reference = self.discover()[0]["action_ref"]
        stored["is_enabled"] = False
        with self.assertRaises(PermissionError):
            self.catalog.resolve_action_manifest("actor", reference, settings=self.settings)

    def test_governance_revocation_is_refreshed_after_planning(self):
        for scope in self.containers:
            self.store(scope)
        actions = self.discover()
        self.feature_policies["governance_user_actions"] = {"allow_all": False}
        self.feature_policies["governance_group_actions"] = {"allow_all": False}
        self.item_policies[("global_action", "shared-id")] = [{"allow_all": False}]
        for action in actions:
            with self.subTest(scope=action["scope_type"]):
                with self.assertRaises(PermissionError):
                    self.catalog.resolve_action_manifest("actor", action["action_ref"], settings=self.settings)

    def test_settings_are_refetched_when_not_supplied(self):
        self.store("personal")
        reference = self.catalog.build_accessible_action_catalog("actor")[0]["action_ref"]
        self.settings["allow_user_plugins"] = False
        with self.assertRaises(PermissionError):
            self.catalog.resolve_action_manifest("actor", reference)
        self.assertGreaterEqual(self.get_settings.call_count, 2)

    def test_deletion_after_planning_does_not_substitute_a_same_name_action(self):
        self.store("personal")
        reference = self.discover()[0]["action_ref"]
        self.containers["personal"].records.clear()
        self.store("personal", action_id="new-id")
        with self.assertRaises(LookupError):
            self.catalog.resolve_action_manifest("actor", reference, settings=self.settings)

    def test_call_agent_is_excluded_and_forged_references_are_rejected(self):
        for action_type in ("agent", "AGENT", " Agent "):
            for scope in self.containers:
                self.store(scope, type=action_type)
            with self.subTest(action_type=action_type):
                self.assertEqual(self.discover(), [])
                for scope in self.containers:
                    with self.assertRaises(PermissionError):
                        self.resolve(scope)
        self.keyvault.keyvault_plugin_get_helper.assert_not_called()

    def test_type_changed_to_call_agent_after_planning_is_rejected(self):
        stored = self.store("personal")
        reference = self.discover()[0]["action_ref"]
        stored["type"] = "agent"
        with self.assertRaises(PermissionError):
            self.catalog.resolve_action_manifest("actor", reference, settings=self.settings)

    def test_actor_is_required_even_when_governance_is_disabled(self):
        for user_id in (None, "", " ", "system", " SYSTEM ", {}, True, "bad/user", " actor "):
            with self.subTest(user_id=user_id):
                with self.assertRaises(PermissionError):
                    self.catalog.build_accessible_action_catalog(user_id, settings=self.settings)
                with self.assertRaises(PermissionError):
                    self.catalog.resolve_action_manifest(
                        user_id, _reference("global", "global", "shared-id"), settings=self.settings,
                    )
        self.assert_no_action_reads()

    def test_malformed_noncanonical_and_tampered_references_fail_safely(self):
        valid = _reference("personal", "actor", "shared-id")
        references = (
            None, {}, "", "same-name", "personal:actor:shared-id",
            valid + "=", valid + ":extra", valid.replace("v1", "v2"),
            valid.replace("personal", "user"), valid.replace("personal", "PERSONAL"),
            "action:v1:personal:!:!", "action:v1:personal:YQ:YQ==",
            _reference("global", "actor", "shared-id"),
            _reference("personal", "actor", "../shared-id"),
            _reference("personal", "actor", " shared-id "),
            _reference("personal", "actor", ""), "a" * 4096,
        )
        for reference in references:
            with self.subTest(reference=reference):
                with self.assertRaises(ValueError) as raised:
                    self.catalog.resolve_action_manifest("actor", reference, settings=self.settings)
                self.assertEqual(str(raised.exception), "Select an action using its catalog reference.")
        self.assert_no_action_reads()

    def test_metadata_only_projection_excludes_inline_secrets_connections_and_schemas(self):
        self.store(
            "personal",
            auth={"type": "key", "key": "PRIVATE_API_KEY"},
            endpoint="https://PRIVATE_HOST/api",
            identity_id="PRIVATE_IDENTITY",
            metadata={
                "description": "Fallback description.",
                "schema": {"password": "PRIVATE_SCHEMA_PASSWORD", "functions": ["PRIVATE_FUNCTION"]},
            },
            additionalFields={
                "connection_string": "PRIVATE_CONNECTION",
                "token__Secret": "PRIVATE_SECRET_REF",
                "custom_headers": {"Authorization": "PRIVATE_HEADER"},
            },
        )
        actions = self.discover()
        self.assertEqual(set(actions[0]), {
            "action_ref", "id", "name", "display_name", "description",
            "type", "scope_type", "scope_id", "scope_label",
        })
        projection = self.catalog.build_action_planner_projection(actions)
        self.assertEqual(set(projection[0]), {
            "action_ref", "display_name", "description", "type", "scope_label",
        })
        self.assertNotIn("PRIVATE_", json.dumps(actions))
        self.assertNotIn("PRIVATE_", json.dumps(projection))
        self.keyvault.keyvault_plugin_get_helper.assert_not_called()
        self.identities.hydrate_action_identity_reference.assert_not_called()
        self.identities.get_workspace_identity_auth.assert_not_called()

    def test_metadata_description_fallback_and_no_stringification_of_objects(self):
        self.store(
            "personal",
            description={"password": "PRIVATE_DESCRIPTION"},
            displayName={"password": "PRIVATE_DISPLAY"},
            metadata={"description": "Find records using the stored integration."},
        )
        action = self.discover()[0]
        self.assertEqual(action["description"], "Find records using the stored integration.")
        self.assertEqual(action["display_name"], "same-name")
        self.assertNotIn("PRIVATE_", json.dumps(action))
        self.containers["personal"].records[("actor", "shared-id")]["metadata"] = {
            "description": {"secret": "PRIVATE_NESTED"},
        }
        self.assertEqual(self.discover()[0]["description"], "")

    def test_descriptive_text_cannot_echo_known_credentials_or_raw_endpoints(self):
        self.store(
            "personal",
            description="Use PRIVATE_PASSWORD at https://intranet.example.local/api or PRIVATE_DB_HOST.",
            auth={"type": "basic", "password": "PRIVATE_PASSWORD"},
            endpoint="PRIVATE_DB_HOST",
        )
        action = self.discover()[0]
        self.assertNotIn("PRIVATE_", json.dumps(action))
        self.assertNotIn("intranet.example.local", json.dumps(action))
        self.assertIn("[redacted]", action["description"])
        self.assertIn("[endpoint]", action["description"])

    def test_planner_projection_is_allowlisted_even_with_extra_manifest_fields(self):
        action = {
            "action_ref": _reference("personal", "actor", "shared-id"),
            "display_name": "Tickets",
            "description": "Read https://private.example.local/config",
            "type": "mcp",
            "scope_label": "Personal",
            "auth": {"api_key": "PRIVATE_KEY"},
            "metadata": {"functions": ["PRIVATE_FUNCTION"]},
            "endpoint": "PRIVATE_CONNECTION",
        }
        projected = self.catalog.build_action_planner_projection([action])
        self.assertEqual(projected[0]["description"], "Read [endpoint]")
        self.assertNotIn("PRIVATE_", json.dumps(projected))
        self.assertEqual(len(projected[0]), 5)

    def test_planner_projection_omits_invalid_entries_and_agent_actions(self):
        action = {
            "action_ref": "an-opaque-reference", "display_name": "Tickets", "type": "openapi",
        }
        projected = self.catalog.build_action_planner_projection([
            None, [], {**action, "type": "agent"}, {**action, "type": {}},
            {**action, "action_ref": {}}, {**action, "action_ref": ""}, action,
        ])
        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["action_ref"], action["action_ref"])

    def test_planner_projection_truncates_text_without_truncating_identity(self):
        action = {
            "action_ref": _reference("personal", "actor", "a" * 1023),
            "display_name": "x" * 500,
            "description": "é" * 2000,
            "type": "openapi",
            "scope_label": "s" * 500,
        }
        projected = self.catalog.build_action_planner_projection([action])[0]
        self.assertEqual(projected["action_ref"], action["action_ref"])
        self.assertEqual(len(projected["display_name"]), 200)
        self.assertEqual(len(projected["description"]), 1000)
        self.assertEqual(len(projected["scope_label"]), 200)

    def test_manifest_resolution_preserves_secret_references_without_identity_hydration(self):
        for scope in self.containers:
            self.store(
                scope,
                auth={"type": "key", "key": "stored-secret-reference"},
                identity_id="workspace-identity-reference",
                additionalFields={"enabled_functions": ["lookup"], "token__Secret": "stored-token-reference"},
            )
            with self.subTest(scope=scope):
                manifest = self.resolve(scope)
                self.assertEqual(manifest["auth"]["key"], "stored-secret-reference")
                self.assertEqual(manifest["identity_id"], "workspace-identity-reference")
                self.assertEqual(manifest["additionalFields"]["enabled_functions"], ["lookup"])
                _, call = self.keyvault.keyvault_plugin_get_helper.call_args
                self.assertIs(call["return_type"], _SecretReturnType.NAME)
                self.assertEqual(call["scope"], "user" if scope == "personal" else scope)
                self.assertEqual(call["scope_value"], {
                    "personal": "actor", "group": "group-one", "global": "shared-id",
                }[scope])
        self.identities.hydrate_action_identity_reference.assert_not_called()
        self.identities.get_workspace_identity_auth.assert_not_called()
        self.keyvault.retrieve_secret_from_key_vault_by_full_name.assert_not_called()

    def test_manifest_scope_fields_are_authoritative_and_source_is_not_mutated(self):
        stored = self.store(
            "personal", is_global=True, is_group=True, group_id="foreign",
            _etag="PRIVATE_ETAG",
            additionalFields={"nested": {"value": "original"}},
        )
        stored.update(scope_type="group", scope_id="foreign", scope="group")
        original = deepcopy(stored)
        self.discover()
        manifest = self.resolve()
        self.assertEqual(manifest["scope_type"], "personal")
        self.assertEqual(manifest["scope_id"], "actor")
        self.assertEqual(manifest["user_id"], "actor")
        self.assertIsNone(manifest["group_id"])
        self.assertIs(manifest["is_global"], False)
        self.assertIs(manifest["is_group"], False)
        self.assertNotIn("_etag", manifest)
        manifest["additionalFields"]["nested"]["value"] = "changed"
        self.assertEqual(stored, original)

    def test_resolution_returns_fresh_manifest_not_the_planner_snapshot(self):
        stored = self.store("personal", endpoint="old-connection")
        reference = self.discover()[0]["action_ref"]
        stored["endpoint"] = "new-connection"
        manifest = self.catalog.resolve_action_manifest("actor", reference, settings=self.settings)
        self.assertEqual(manifest["endpoint"], "new-connection")

    def test_successive_manifest_reads_are_deterministic_and_detect_definition_changes(self):
        for scope in self.containers:
            stored = self.store(
                scope,
                auth={"type": "key", "key": "stored-secret-reference"},
                identity_id="workspace-identity-reference",
                additionalFields={"enabled_functions": ["lookup"]},
            )
            with self.subTest(scope=scope):
                first = self.resolve(scope)
                stored.update(_etag="refreshed-storage-tag", _ts=123)
                second = self.resolve(scope)
                self.assertEqual(first, second)
                self.assertIsNot(first, second)
                second["auth"]["key"] = "local-mutation"
                self.assertEqual(first, self.resolve(scope))
                stored["additionalFields"]["enabled_functions"] = ["different_function"]
                self.assertNotEqual(first, self.resolve(scope))
        self.identities.get_workspace_identity_auth.assert_not_called()

    def test_discovery_never_imports_keyvault_or_plugin_runtime(self):
        for scope in self.containers:
            self.store(scope, type="mcp", identity_id="workspace-identity")
        with patch.dict(sys.modules, {"functions_keyvault": None}):
            self.assertEqual(len(self.discover()), 3)
        self.keyvault.keyvault_plugin_get_helper.assert_not_called()
        self.identities.get_workspace_identity_auth.assert_not_called()

    def test_storage_failure_is_not_silently_replaced_with_an_empty_catalog(self):
        self.containers["personal"].query_items.side_effect = RuntimeError("storage unavailable")
        with self.assertRaises(RuntimeError):
            self.discover()

    def test_group_listing_failure_never_uses_supplied_membership_as_fallback(self):
        self.group_module.get_user_groups.side_effect = RuntimeError("membership unavailable")
        with self.assertRaises(RuntimeError):
            self.discover(user_groups=[{"id": "group-one", "userRole": "Owner"}])
        with self.assertRaises(RuntimeError):
            self.resolve("group", user_groups=["group-one"])
        self.containers["group"].query_items.assert_not_called()
        self.containers["group"].read_item.assert_not_called()


class ActionCatalogImportTests(unittest.TestCase):
    def test_module_and_planner_projection_import_without_azure_or_application_storage(self):
        blocked = {
            name: None for name in (
                "azure", "config", "functions_settings", "functions_group",
                "functions_governance", "functions_keyvault", "functions_workspace_identities",
                "functions_personal_actions", "functions_group_actions", "functions_global_actions",
                "semantic_kernel", "semantic_kernel_loader", "semantic_kernel_plugins.logged_plugin_loader",
            )
        }
        with stubbed_app_imports(), patch.dict(sys.modules, blocked):
            sys.modules.pop("functions_action_catalog", None)
            sys.modules.pop("functions_agent_delegation", None)
            catalog = importlib.import_module("functions_action_catalog")
            self.assertEqual(catalog.build_action_planner_projection([{
                "action_ref": "opaque-reference",
                "display_name": "Tickets",
                "description": "Find ticket information.",
                "type": "openapi",
                "scope_label": "Personal",
            }]), [{
                "action_ref": "opaque-reference",
                "display_name": "Tickets",
                "description": "Find ticket information.",
                "type": "openapi",
                "scope_label": "Personal",
            }])


if __name__ == "__main__":
    unittest.main()
