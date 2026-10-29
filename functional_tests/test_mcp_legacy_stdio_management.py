# test_mcp_legacy_stdio_management.py
#!/usr/bin/env python3
"""
Functional regression tests for safe retired MCP management and action migration.
Version: 0.261.030
Implemented in: 0.261.029
Global creation and lookup-failure regression coverage added in: 0.261.030

Uses real scoped persistence, manifest normalization, schema validation, locators,
and migration routes with in-memory storage and mocked credential/policy boundaries.
No cloud clients, network connections, or MCP subprocesses are used.
"""

from contextlib import contextmanager
from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
OWNER = "owner-user"
GROUP = "group-one"


class StoreError(Exception):
    def __init__(self, status_code=503):
        super().__init__("private-provider-detail")
        self.status_code = status_code


class NotFound(StoreError):
    def __init__(self):
        super().__init__(404)


class MemoryContainer:
    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.documents = {}
        self.writes = []
        self.deletes = []
        self.fail_ids = set()
        self.fail_after_create = set()
        self.after_create = None
        self.before_replace = None
        self.fail_replace = False
        self.false_replace = False
        self.read_count = 0
        self.revision = 0

    def seed(self, document, partition=None):
        stored = deepcopy(dict(document))
        self.revision += 1
        stored["_etag"] = str(self.revision)
        key = (partition or stored[self.partition_field], stored["id"])
        self.documents[key] = stored
        return deepcopy(stored)

    def read_item(self, item, partition_key):
        self.read_count += 1
        key = (partition_key, item)
        if key not in self.documents:
            raise NotFound()
        return deepcopy(self.documents[key])

    def query_items(self, query, parameters=None, partition_key=None, **_kwargs):
        params = {item["name"]: item["value"] for item in (parameters or [])}
        values = []
        for (partition, _item_id), document in self.documents.items():
            if partition_key is not None and partition != partition_key:
                continue
            if "@name" in params and document.get("name") != params["@name"]:
                continue
            names = [value for key, value in params.items() if key.startswith("@name") and key != "@name"]
            if names and document.get("name") not in names:
                continue
            if "@type" in params and document.get("type") != params["@type"]:
                continue
            if "c.is_enabled = true" in query and document.get("is_enabled", True) is not True:
                continue
            values.append(deepcopy(document))
        return values

    def upsert_item(self, body):
        if body["id"] in self.fail_ids:
            raise StoreError()
        self.writes.append(("upsert", deepcopy(dict(body))))
        return self.seed(body)

    def create_item(self, body):
        key = (body[self.partition_field], body["id"])
        if key in self.documents:
            raise StoreError(409)
        if body["id"] in self.fail_ids:
            raise StoreError()
        self.writes.append(("create", deepcopy(dict(body))))
        stored = self.seed(body)
        if self.after_create:
            self.after_create()
        if body["id"] in self.fail_after_create:
            raise StoreError()
        return stored

    def replace_item(self, item, body, etag, match_condition):
        if self.before_replace:
            callback = self.before_replace
            self.before_replace = None
            callback()
        current = self.documents[(body[self.partition_field], item)]
        if match_condition != "IfNotModified" or current["_etag"] != etag:
            raise StoreError(412)
        if self.fail_replace:
            raise StoreError()
        if self.false_replace:
            return False
        self.writes.append(("replace", deepcopy(dict(body))))
        return self.seed(body)

    def delete_item(self, item, partition_key):
        key = (partition_key, item)
        if key not in self.documents:
            raise NotFound()
        self.deletes.append(key)
        del self.documents[key]


def remote(action_id="remote-one", name="remote_action", endpoint="https://example.com/mcp"):
    manifest = {
        "name": name, "displayName": name, "description": "A remote action",
        "type": "mcp", "endpoint": endpoint, "auth": {"type": "NoAuth"},
        "metadata": {}, "additionalFields": {"transport": "sse"},
    }
    if action_id is not None:
        manifest["id"] = action_id
    return manifest


def retired(action_id="retired-one", name="retired_action"):
    manifest = remote(action_id, name)
    manifest["additionalFields"] = {
        "transport": " STDIO ", "command": "private-process-command",
        "args": ["private-process-argument"], "env": {"TOKEN": "private-environment-secret"},
        "custom_headers": {"Authorization": "private-header-secret"},
        "other__Secret": "private-additional-secret",
    }
    manifest["auth"] = {"type": "key", "key": "private-auth-secret"}
    manifest["endpoint"] = "stdio://private-endpoint-command"
    return manifest


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _decorator(function=None, **_kwargs):
    if callable(function):
        return function
    return lambda decorated: decorated


def _blocked(*_args, **_kwargs):
    raise AssertionError("External I/O is forbidden in this offline suite.")


@contextmanager
def action_services(plugins=None):
    state = types.SimpleNamespace(
        actor=OWNER, denied_types=set(), settings={}, secret_saves=[], secret_gets=[],
        secret_deletes=[], identity_hydrations=[], identity_validations=[], policy_calls=[],
        governance_calls=[], cache={}, settings_updates=[], logs=[],
        credential_authorizations=[], read_events=[], denied_endpoints=set(),
    )
    state.personal = MemoryContainer("user_id")
    state.group = MemoryContainer("group_id")
    state.global_actions = MemoryContainer("id")
    state.source = MemoryContainer("id")
    state.source.seed({
        "id": OWNER,
        "settings": {
            "plugins": deepcopy(plugins or []), "agents": [], "prompts": ["keep-this-prompt"],
            "unrelated_setting": "preserved",
        },
    })

    def authorize_user_settings(user_id, operation, allow_cross_user=False):
        if user_id != state.actor:
            raise PermissionError("Not the settings owner.")
        return state.actor

    def get_user_settings(user_id):
        authorize_user_settings(user_id, "read")
        if user_id not in state.cache:
            state.cache[user_id] = state.source.read_item(user_id, user_id)
        return deepcopy(state.cache[user_id])

    def update_user_settings(user_id, updates):
        get_user_settings(user_id)
        state.settings_updates.append(deepcopy(updates))
        document = state.source.read_item(user_id, user_id)
        document["settings"].update(deepcopy(updates))
        stored = state.source.upsert_item(document)
        state.cache[user_id] = stored
        return True

    def ensure_access(feature, user_id, action_type, scope):
        state.governance_calls.append((feature, user_id, action_type, scope))
        if action_type in state.denied_types:
            raise PermissionError("Action use is denied.")

    def filter_actions(user_id, actions, feature, scope):
        allowed = []
        for action in actions:
            try:
                ensure_access(feature, user_id, action.get("type"), scope)
            except PermissionError:
                continue
            allowed.append(action)
        return allowed

    def save_secrets(manifest, scope_value, scope, existing_plugin=None):
        state.secret_saves.append((deepcopy(manifest), scope_value, scope))
        saved = deepcopy(dict(manifest))
        if saved.get("auth", {}).get("key"):
            saved["auth"]["key"] = f"kv-reference-{scope}-{scope_value}-{manifest.get('id')}"
        return saved

    def get_secrets(manifest, scope_value, scope, return_type):
        state.secret_gets.append((scope_value, scope, return_type))
        state.read_events.append(("secret", manifest.get("id"), return_type))
        view = deepcopy(dict(manifest))
        if view.get("auth", {}).get("key") and return_type == "trigger":
            view["auth"]["key"] = "Stored_In_KeyVault"
        view["runtime_user_id"] = "untrusted-hydration-principal"
        view["scope"] = "untrusted-hydration-scope"
        return view

    def redact_secrets(manifest, redaction_value="Stored_In_KeyVault"):
        view = deepcopy(dict(manifest))
        if view.get("auth", {}).get("key"):
            view["auth"]["key"] = redaction_value
        return view

    def hydrate_identity(manifest, scope, scope_id, return_type):
        state.identity_hydrations.append((scope, scope_id, return_type))
        state.read_events.append(("identity", manifest.get("id"), return_type))
        view = deepcopy(dict(manifest))
        view["is_global"] = True
        view["is_group"] = True
        return view

    def assert_destination(manifest, **kwargs):
        state.policy_calls.append((deepcopy(manifest), deepcopy(kwargs)))
        if kwargs["policy_config"].get("deny_destination"):
            raise PermissionError("Destination is denied.")
        return {"allowed": True}

    def assert_preconfiguration(_manifest, **kwargs):
        if kwargs["settings"].get("deny_preconfiguration"):
            raise PermissionError("Preconfiguration is denied.")

    def authorize_mcp_action(manifest, *, settings, operation, origin=None):
        action_origin = origin or state.manifest.get_action_origin(manifest)
        state.credential_authorizations.append((action_origin, state.actor, deepcopy(settings), operation))
        state.read_events.append(("authorize", manifest.get("id"), state.actor))
        if action_origin is None or not state.actor:
            raise PermissionError("Current principal and authoritative origin are required.")
        if action_origin.scope_type == "personal" and action_origin.scope_id != state.actor:
            raise PermissionError("This personal action does not belong to the current principal.")
        if (
            settings.get("deny_destination") or settings.get("deny_preconfiguration")
            or manifest.get("endpoint") in state.denied_endpoints
        ):
            raise PermissionError("MCP usage is denied.")
        return action_origin

    class SecretReturnType:
        NAME = "name"
        TRIGGER = "trigger"
        VALUE = "value"

    class HealthChecker:
        @staticmethod
        def validate_plugin_manifest(manifest, plugin_type):
            return True, []

    azure = _module("azure")
    azure.__path__ = []
    azure_core = _module("azure.core", MatchConditions=types.SimpleNamespace(IfNotModified="IfNotModified"))
    azure_cosmos = _module("azure.cosmos", exceptions=types.SimpleNamespace(
        CosmosResourceNotFoundError=NotFound, CosmosHttpResponseError=StoreError,
    ))
    azure.core = azure_core
    azure.cosmos = azure_cosmos
    replacements = {
        "azure": azure,
        "azure.core": azure_core,
        "azure.cosmos": azure_cosmos,
        "config": _module(
            "config", cosmos_personal_actions_container=state.personal,
            cosmos_group_actions_container=state.group,
            cosmos_global_actions_container=state.global_actions,
            cosmos_user_settings_container=state.source,
        ),
        "functions_settings": _module(
            "functions_settings", get_settings=lambda: deepcopy(state.settings),
            get_user_settings=get_user_settings, update_user_settings=update_user_settings,
            _authorize_user_settings_access=authorize_user_settings,
            _set_request_cached_user_settings=lambda user_id, doc: state.cache.__setitem__(user_id, deepcopy(doc)),
            _delete_user_ui_settings_cache=lambda user_id: None,
        ),
        "functions_keyvault": _module(
            "functions_keyvault", SecretReturnType=SecretReturnType,
            keyvault_plugin_save_helper=save_secrets, keyvault_plugin_get_helper=get_secrets,
            redact_plugin_secret_values=redact_secrets,
            clean_name_for_keyvault=lambda value: re.sub(r"[^a-zA-Z0-9-]", "-", value)[:127],
            keyvault_plugin_delete_helper=lambda manifest, **kwargs: state.secret_deletes.append(
                (deepcopy(manifest), kwargs)
            ),
        ),
        "functions_workspace_identities": _module(
            "functions_workspace_identities",
            WORKSPACE_IDENTITY_SCOPE_PERSONAL="personal", WORKSPACE_IDENTITY_SCOPE_GROUP="group",
            WORKSPACE_IDENTITY_SCOPE_GLOBAL="global", hydrate_action_identity_reference=hydrate_identity,
            validate_action_identity_reference=lambda *args: state.identity_validations.append(deepcopy(args)),
        ),
        "functions_governance": _module(
            "functions_governance", ensure_action_type_access=ensure_access,
            filter_actions_by_action_type_access=filter_actions,
        ),
        "functions_authentication": _module(
            "functions_authentication", get_current_user_id=lambda: state.actor,
            login_required=_decorator, user_required=_decorator,
            user_required_blueprint=lambda: lambda: None,
        ),
        "functions_appinsights": _module(
            "functions_appinsights",
            log_event=lambda *args, **kwargs: state.logs.append((args, kwargs)),
        ),
        "functions_chat_bootstrap_cache": _module(
            "functions_chat_bootstrap_cache",
            bump_chat_bootstrap_user_cache_version=lambda *_args, **_kwargs: None,
            bump_chat_bootstrap_global_cache_version=lambda *_args, **_kwargs: None,
        ),
        "functions_mcp_destinations": _module(
            "functions_mcp_destinations",
            get_mcp_destination_policy_config=lambda settings, user_id: deepcopy(settings),
            assert_mcp_destination_allowed=assert_destination,
        ),
        "functions_mcp_preconfigurations": _module(
            "functions_mcp_preconfigurations",
            assert_mcp_preconfiguration_manifest_allowed=assert_preconfiguration,
            authorize_mcp_action=authorize_mcp_action,
        ),
        "semantic_kernel_plugins.plugin_health_checker": _module(
            "semantic_kernel_plugins.plugin_health_checker", PluginHealthChecker=HealthChecker,
        ),
        "functions_personal_agents": _module(
            "functions_personal_agents", migrate_agents_from_user_settings=lambda user_id: 0,
            get_personal_agents=lambda user_id: [],
        ),
        "swagger_wrapper": _module(
            "swagger_wrapper", swagger_route=_decorator, get_auth_security=lambda: [],
        ),
    }
    original_path = list(sys.path)
    try:
        sys.path.insert(0, str(APP))
        with patch.dict(sys.modules, replacements), patch.object(socket.socket, "connect", _blocked), \
                patch.object(socket, "create_connection", _blocked), patch.object(subprocess, "Popen", _blocked):
            for module_name in (
                "functions_action_manifest", "functions_legacy_action_management",
                "functions_personal_actions", "functions_group_actions", "functions_global_actions",
                "functions_mcp_operations", "json_schema_validation", "route_migration",
            ):
                sys.modules.pop(module_name, None)
            state.manifest = importlib.import_module("functions_action_manifest")
            state.management = importlib.import_module("functions_legacy_action_management")
            state.operations = importlib.import_module("functions_mcp_operations")
            with patch.object(state.operations, "normalize_mcp_server_profile", lambda value: "generic"):
                state.personal_service = importlib.import_module("functions_personal_actions")
                state.group_service = importlib.import_module("functions_group_actions")
                state.global_service = importlib.import_module("functions_global_actions")
                state.routes = importlib.import_module("route_migration")
                state.flask_app = Flask(__name__)
                state.flask_app.register_blueprint(state.routes.bp_migration)
                yield state
    finally:
        sys.path[:] = original_path


def source_plugins(state):
    document = state.source.read_item(OWNER, OWNER)
    return document["settings"]["plugins"]


class LegacyMcpManagementTests(unittest.TestCase):
    def assert_origin(self, state, manifest, scope, scope_id):
        origin = state.manifest.get_action_origin(manifest)
        self.assertIsNotNone(origin)
        self.assertEqual((origin.scope_type, origin.scope_id, origin.action_id), (
            scope, scope_id, manifest["id"],
        ))
        self.assertEqual(manifest["is_global"], scope == "global")
        self.assertEqual(manifest["is_group"], scope == "group")
        self.assertEqual(manifest["scope_id"], scope_id)
        self.assertNotIn("runtime_user_id", manifest)
        self.assertNotIn("_action_origin", json.loads(json.dumps(manifest)))

    def test_retired_projection_never_hydrates_process_data_or_credentials(self):
        with action_services() as state:
            original = retired()
            original.update({"scope": "global", "scope_id": "forged", "runtime_user_id": "admin"})
            saved_copy = deepcopy(original)
            for scope, scope_id in (("personal", OWNER), ("group", GROUP), ("global", "global")):
                view = state.management.retired_action_management_view(original, scope, scope_id)
                self.assert_origin(state, view, scope, scope_id)
                self.assertEqual(view["execution_status"]["code"], "mcp_stdio_removed")
                self.assertEqual(view["additionalFields"], {"transport": "stdio"})
                self.assertNotIn("private-", json.dumps(view))
            self.assertEqual(original, saved_copy)
            self.assertEqual(state.secret_gets, [])

    def test_every_scoped_getter_preserves_authoritative_origin(self):
        with action_services() as state:
            for manifest in (retired(), remote()):
                forged = dict(manifest, scope="global", scope_id="forged", runtime_user_id="forged")
                state.personal.seed(dict(forged, user_id=OWNER))
                state.group.seed(dict(forged, group_id=GROUP))
                state.global_actions.seed(forged)
            personal_results = [
                *state.personal_service.get_personal_actions(OWNER),
                state.personal_service.get_personal_action(OWNER, "retired-one"),
                state.personal_service.get_personal_action(OWNER, "remote_action"),
                *state.personal_service.get_actions_by_names(OWNER, ["retired_action", "remote_action"]),
                *state.personal_service.get_actions_by_type(OWNER, "mcp"),
                *state.personal_service.get_governed_personal_actions(OWNER),
            ]
            group_results = [
                *state.group_service.get_group_actions(GROUP),
                state.group_service.get_group_action(GROUP, "retired-one"),
                state.group_service.get_group_action(GROUP, "remote_action"),
                *state.group_service.get_governed_group_actions(GROUP, OWNER),
            ]
            global_results = [
                *state.global_service.get_global_actions(),
                *state.global_service.get_global_actions(include_disabled=True),
                state.global_service.get_global_action("retired-one"),
                state.global_service.get_global_action("remote-one"),
            ]
            for scope, scope_id, results in (
                ("personal", OWNER, personal_results), ("group", GROUP, group_results),
                ("global", "global", global_results),
            ):
                for manifest in results:
                    self.assert_origin(state, manifest, scope, scope_id)
                    if manifest["id"] == "retired-one":
                        self.assertNotIn("private-", json.dumps(manifest))
            global_secret_scopes = [scope_id for scope_id, scope, _return_type in state.secret_gets if scope == "global"]
            self.assertTrue(global_secret_scopes)
            self.assertEqual(set(global_secret_scopes), {"remote-one"})

    def test_retired_getters_skip_secret_and_identity_hydration_for_every_return_type(self):
        with action_services() as state:
            state.personal.seed(dict(retired(), user_id=OWNER))
            state.group.seed(dict(retired(), group_id=GROUP))
            state.global_actions.seed(retired())
            for return_type in ("name", "trigger", "value"):
                personal = state.personal_service.get_personal_action(OWNER, "retired-one", return_type)
                group = state.group_service.get_group_action(GROUP, "retired-one", return_type)
                global_action = state.global_service.get_global_action("retired-one", return_type)
                self.assertIsNotNone(personal)
                self.assertIsNotNone(group)
                self.assertIsNotNone(global_action)
            self.assertEqual(state.secret_gets, [])
            self.assertEqual(state.identity_hydrations, [])

    def test_personal_name_reads_are_authoritative_but_ui_reads_stay_projected(self):
        with action_services() as state:
            original = dict(retired(), user_id=OWNER, scope="global", runtime_user_id="forged")
            state.personal.seed(original)
            internal = state.personal_service.get_personal_actions(OWNER, "name")
            ui_actions = state.personal_service.get_personal_actions(OWNER, "trigger")
            self.assertEqual(internal[0]["additionalFields"]["command"], "private-process-command")
            self.assertEqual(internal[0]["auth"]["key"], "private-auth-secret")
            self.assertNotIn("execution_status", internal[0])
            self.assert_origin(state, internal[0], "personal", OWNER)
            expected = state.management.retired_action_management_view(internal[0], "personal", OWNER)
            self.assertEqual(ui_actions[0], expected)
            self.assertNotIn("private-", json.dumps(ui_actions))
            self.assertEqual(state.secret_gets, [])
            self.assertEqual(state.identity_hydrations, [])

    def test_effective_type_selector_includes_metadata_only_and_aliased_legacy_records(self):
        with action_services() as state:
            alias = retired("alias")
            alias["type"] = "McpPlugin"
            metadata_only = retired("metadata")
            metadata_only.pop("type")
            metadata_only["metadata"]["type"] = "model_context_protocol"
            state.personal.seed(dict(alias, user_id=OWNER))
            state.personal.seed(dict(metadata_only, user_id=OWNER))
            actions = state.personal_service.get_actions_by_type(OWNER, "mcp")
            self.assertEqual({action["id"] for action in actions}, {"alias", "metadata"})
            for action in actions:
                self.assert_origin(state, action, "personal", OWNER)
            self.assertEqual(state.secret_gets, [])

    def test_active_value_getters_authorize_before_secret_and_identity_hydration(self):
        with action_services() as state:
            manifest = remote()
            manifest["type"] = "Model_Context_Protocol"
            manifest.update({"scope": "forged", "runtime_user_id": "forged-user"})
            state.personal.seed(dict(manifest, user_id=OWNER))
            state.group.seed(dict(manifest, group_id=GROUP))
            state.global_actions.seed(manifest)
            selectors = [
                ("personal", OWNER, lambda: state.personal_service.get_personal_action(OWNER, "remote-one", "value")),
                ("personal", OWNER, lambda: state.personal_service.get_personal_actions(OWNER, "value")),
                ("personal", OWNER, lambda: state.personal_service.get_actions_by_names(OWNER, ["remote_action"], "value")),
                ("personal", OWNER, lambda: state.personal_service.get_actions_by_type(OWNER, "mcp", "value")),
                ("personal", OWNER, lambda: state.personal_service.get_governed_personal_actions(OWNER, "value")),
                ("group", GROUP, lambda: state.group_service.get_group_action(GROUP, "remote-one", "value")),
                ("group", GROUP, lambda: state.group_service.get_group_actions(GROUP, "value")),
                ("group", GROUP, lambda: state.group_service.get_governed_group_actions(GROUP, OWNER, "value")),
                ("global", "global", lambda: state.global_service.get_global_action("remote-one", "value")),
                ("global", "global", lambda: state.global_service.get_global_actions("value")),
            ]
            for scope, scope_id, selector in selectors:
                result = selector()
                action = result[0] if isinstance(result, list) else result
                self.assert_origin(state, action, scope, scope_id)
            self.assertEqual(len(state.credential_authorizations), len(selectors))
            self.assertEqual(len(state.read_events), len(selectors) * 3)
            for offset in range(0, len(state.read_events), 3):
                self.assertEqual(
                    [event[0] for event in state.read_events[offset:offset + 3]],
                    ["authorize", "secret", "identity"],
                )

    def test_authoritative_value_lists_raise_instead_of_returning_partial_results(self):
        with action_services() as state:
            blocked = remote("blocked", "blocked", "https://blocked.example/mcp")
            allowed = remote("allowed", "allowed")
            for manifest in (blocked, allowed, retired()):
                state.personal.seed(dict(manifest, user_id=OWNER))
                state.group.seed(dict(manifest, group_id=GROUP))
                state.global_actions.seed(manifest)
            state.denied_endpoints.add(blocked["endpoint"])
            selectors = [
                lambda: state.personal_service.get_personal_actions(OWNER, "value"),
                lambda: state.personal_service.get_actions_by_names(
                    OWNER, ["blocked", "allowed", "retired_action"], "value"
                ),
                lambda: state.personal_service.get_actions_by_type(OWNER, "mcp", "value"),
                lambda: state.group_service.get_group_actions(GROUP, "value"),
                lambda: state.global_service.get_global_actions("value"),
            ]
            for selector in selectors:
                with self.assertRaises(PermissionError):
                    selector()
            self.assertEqual(state.secret_gets, [])
            self.assertEqual(state.identity_hydrations, [])
            for selector in (
                lambda: state.personal_service.get_personal_action(OWNER, "blocked", "value"),
                lambda: state.group_service.get_group_action(GROUP, "blocked", "value"),
                lambda: state.global_service.get_global_action("blocked", "value"),
            ):
                with self.assertRaises(PermissionError):
                    selector()
            state.denied_endpoints.clear()
            for selector in selectors:
                actions = selector()
                self.assertEqual({action["id"] for action in actions}, {"blocked", "allowed", "retired-one"})

    def test_scoped_list_storage_failures_are_not_success_shaped_empty_results(self):
        with action_services() as state:
            selectors = [
                (state.personal, lambda: state.personal_service.get_personal_actions(OWNER, "name")),
                (state.personal, lambda: state.personal_service.get_actions_by_names(OWNER, ["name"], "name")),
                (state.personal, lambda: state.personal_service.get_actions_by_type(OWNER, "mcp", "name")),
                (state.personal, lambda: state.personal_service.get_governed_personal_actions(OWNER, "name")),
                (state.group, lambda: state.group_service.get_group_actions(GROUP, "name")),
                (state.group, lambda: state.group_service.get_governed_group_actions(GROUP, OWNER, "name")),
                (state.global_actions, lambda: state.global_service.get_global_actions("name")),
            ]
            for container, selector in selectors:
                with patch.object(container, "query_items", side_effect=StoreError()):
                    with self.assertRaises(StoreError):
                        selector()
                with patch.object(container, "query_items", side_effect=NotFound()):
                    result = selector()
                self.assertEqual(result, [])
            self.assertEqual(state.personal.writes + state.group.writes + state.global_actions.writes, [])

    def test_scoped_lists_propagate_unexpected_record_validation_failures(self):
        with action_services() as state:
            malformed = remote("malformed", "malformed")
            malformed["type"] = []
            for manifest in (remote(), malformed):
                state.personal.seed(dict(manifest, user_id=OWNER))
                state.group.seed(dict(manifest, group_id=GROUP))
                state.global_actions.seed(manifest)
            selectors = [
                lambda: state.personal_service.get_personal_actions(OWNER, "name"),
                lambda: state.personal_service.get_actions_by_names(
                    OWNER, ["remote_action", "malformed"], "name"
                ),
                lambda: state.personal_service.get_actions_by_type(OWNER, "mcp", "name"),
                lambda: state.group_service.get_group_actions(GROUP, "name"),
                lambda: state.global_service.get_global_actions("name"),
            ]
            for selector in selectors:
                with self.assertRaises(ValueError):
                    selector()

    def test_missing_credentials_do_not_masquerade_as_missing_action_collections(self):
        with action_services() as state:
            state.personal.seed(dict(remote(), user_id=OWNER))
            state.group.seed(dict(remote(), group_id=GROUP))
            state.global_actions.seed(remote())
            selectors = [
                (state.personal_service, lambda: state.personal_service.get_personal_actions(OWNER)),
                (state.group_service, lambda: state.group_service.get_group_actions(GROUP)),
                (state.global_service, lambda: state.global_service.get_global_actions()),
            ]
            for service, selector in selectors:
                with patch.object(service, "keyvault_plugin_get_helper", side_effect=NotFound()):
                    with self.assertRaises(NotFound):
                        selector()

    def test_single_action_lookup_storage_errors_are_not_reported_as_absent_actions(self):
        with action_services() as state:
            selectors = [
                (state.personal, lambda: state.personal_service.get_personal_action(OWNER, "id", "name")),
                (state.group, lambda: state.group_service.get_group_action(GROUP, "id", "name")),
                (state.global_actions, lambda: state.global_service.get_global_action("id", "name")),
            ]
            for container, selector in selectors:
                with patch.object(container, "read_item", side_effect=StoreError()):
                    with self.assertRaises(StoreError):
                        selector()
                missing = selector()
                self.assertIsNone(missing)
            with patch.object(state.group, "query_items", side_effect=StoreError()):
                with self.assertRaises(StoreError):
                    state.group_service.get_group_action(GROUP, "missing-id", "name")

    def test_legacy_list_read_and_validation_failures_remain_visible(self):
        with action_services([retired()]) as state:
            views = state.personal_service.list_legacy_personal_actions(OWNER)
            self.assertEqual(len(views), 1)
            with patch.object(state.source, "read_item", side_effect=StoreError()):
                with self.assertRaises(StoreError):
                    state.personal_service.list_legacy_personal_actions(OWNER)
            with patch.object(
                state.personal_service, "_ensure_legacy_management_access", side_effect=ValueError("invalid")
            ):
                with self.assertRaises(ValueError):
                    state.personal_service.list_legacy_personal_actions(OWNER)
            with patch.object(state.source, "read_item", side_effect=NotFound()):
                missing = state.personal_service.list_legacy_personal_actions(OWNER)
            self.assertEqual(missing, [])

    def test_personal_name_reads_do_not_hydrate_even_active_identity_references(self):
        with action_services() as state:
            original = dict(remote(), user_id=OWNER, identity_id="stored-identity")
            original["auth"] = {"type": "key", "key": "private-stored-reference"}
            original["additionalFields"]["basic_auth_identity_id"] = "proxy-identity"
            state.personal.seed(original)
            with patch.object(state.personal_service, "keyvault_plugin_get_helper", side_effect=_blocked), \
                    patch.object(state.personal_service, "hydrate_action_identity_reference", side_effect=_blocked):
                named = state.personal_service.get_personal_actions(OWNER, "name")
                selected = state.personal_service.get_personal_action(OWNER, original["id"], "name")
            for action in (named[0], selected):
                self.assertEqual(action["identity_id"], "stored-identity")
                self.assertEqual(action["additionalFields"]["basic_auth_identity_id"], "proxy-identity")
                self.assertEqual(action["auth"], original["auth"])
                self.assert_origin(state, action, "personal", OWNER)
            self.assertEqual(state.secret_gets, [])
            self.assertEqual(state.identity_hydrations, [])

    def test_group_and_global_mcp_name_reads_never_hydrate_identity_credentials(self):
        for declared_type in ("mcp", "McpPlugin", None):
            with self.subTest(declared_type=declared_type), action_services() as state:
                manifest = dict(remote(), identity_id="primary-identity")
                manifest["additionalFields"]["basic_auth_identity_id"] = "proxy-identity"
                if declared_type is None:
                    manifest.pop("type")
                    manifest["metadata"]["type"] = "Model_Context_Protocol"
                else:
                    manifest["type"] = declared_type
                state.group.seed(dict(manifest, group_id=GROUP))
                state.global_actions.seed(manifest)
                state.actor = None
                state.settings["deny_destination"] = True
                selectors = [
                    (state.group_service, "group", GROUP, lambda: state.group_service.get_group_actions(GROUP, "name")),
                    (state.group_service, "group", GROUP, lambda: state.group_service.get_group_action(
                        GROUP, "remote-one", "name"
                    )),
                    (state.global_service, "global", "global", lambda: state.global_service.get_global_actions("name")),
                    (state.global_service, "global", "global", lambda: state.global_service.get_global_action(
                        "remote-one", "name"
                    )),
                ]
                for service, scope, scope_id, selector in selectors:
                    with patch.object(service, "keyvault_plugin_get_helper", side_effect=_blocked), \
                            patch.object(service, "hydrate_action_identity_reference", side_effect=_blocked):
                        result = selector()
                    action = result[0] if isinstance(result, list) else result
                    self.assertEqual(action["identity_id"], "primary-identity")
                    self.assertEqual(action["additionalFields"]["basic_auth_identity_id"], "proxy-identity")
                    self.assertEqual(action["type"], "mcp")
                    self.assert_origin(state, action, scope, scope_id)
                self.assertEqual(state.secret_gets, [])
                self.assertEqual(state.identity_hydrations, [])
                self.assertEqual(state.credential_authorizations, [])

    def test_mcp_name_identity_bypass_preserves_other_action_type_behavior(self):
        with action_services() as state:
            non_mcp = dict(remote(), type="sql_query", identity_id="sql-identity")
            state.group.seed(dict(non_mcp, group_id=GROUP))
            state.global_actions.seed(non_mcp)
            group = state.group_service.get_group_action(GROUP, "remote-one", "name")
            global_action = state.global_service.get_global_action("remote-one", "name")
            self.assertEqual(group["type"], "sql_query")
            self.assertEqual(global_action["type"], "sql_query")
            self.assertEqual(len(state.identity_hydrations), 2)
            self.assertEqual(state.credential_authorizations, [])

    def test_global_value_reads_recheck_live_actor_and_policy_but_name_reads_do_not(self):
        with action_services() as state:
            state.global_actions.seed(dict(remote(), created_by="admin", runtime_user_id="admin"))
            state.actor = "first-user"
            first = state.global_service.get_global_action("remote-one", "value")
            state.actor = "second-user"
            second = state.global_service.get_global_action("remote-one", "value")
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            state.settings["deny_destination"] = True
            with self.assertRaises(PermissionError):
                state.global_service.get_global_action("remote-one", "value")
            state.settings.clear()
            state.actor = None
            with self.assertRaises(PermissionError):
                state.global_service.get_global_action("remote-one", "value")
            self.assertEqual(len(state.secret_gets), 2)
            actors = [entry[1] for entry in state.credential_authorizations]
            self.assertEqual(actors, ["first-user", "second-user", "second-user", None])
            named = state.global_service.get_global_action("remote-one", "name")
            self.assertIsNotNone(named)
            self.assertEqual(len(state.credential_authorizations), 4)

    def test_usage_governance_precedes_personal_and_group_value_hydration(self):
        with action_services() as state:
            state.personal.seed(dict(remote(), user_id=OWNER))
            state.group.seed(dict(remote(), group_id=GROUP))
            state.denied_types.add("mcp")
            with self.assertRaises(PermissionError):
                state.personal_service.get_personal_action(OWNER, "remote-one", "value")
            with self.assertRaises(PermissionError):
                state.group_service.get_group_action(GROUP, "remote-one", "value")
            self.assertEqual(state.secret_gets, [])
            self.assertEqual(state.identity_hydrations, [])

    def test_retired_owners_can_inspect_and_delete_when_usage_is_denied(self):
        with action_services([retired("legacy")]) as state:
            state.denied_types.add("mcp")
            state.personal.seed(dict(retired(), user_id=OWNER))
            state.personal.seed(dict(remote(), user_id=OWNER))
            state.group.seed(dict(retired(), group_id=GROUP))
            personal = state.personal_service.get_governed_personal_actions(OWNER)
            group = state.group_service.get_governed_group_actions(GROUP, OWNER)
            legacy = state.personal_service.list_legacy_personal_actions(OWNER)
            self.assertEqual([item["id"] for item in personal], ["retired-one"])
            self.assertEqual([item["id"] for item in group], ["retired-one"])
            self.assertEqual(len(legacy), 1)
            deleted = state.personal_service.delete_personal_action(OWNER, "retired-one")
            legacy_deleted = state.personal_service.delete_legacy_personal_action(OWNER, legacy[0]["id"])
            self.assertTrue(deleted)
            self.assertTrue(legacy_deleted)
            with self.assertRaises(PermissionError):
                state.personal_service.delete_personal_action(OWNER, "remote-one")
            self.assertIn((OWNER, "remote-one"), state.personal.documents)

    def test_all_save_boundaries_reject_retired_and_invalid_mcp_without_mutation(self):
        variants = []
        for action_type in ("mcp", "McpPlugin", " MODEL_CONTEXT_PROTOCOL ", "MCP-Plugin"):
            action = retired()
            action["type"] = action_type
            variants.append(action)
        metadata_only = retired()
        metadata_only.pop("type")
        metadata_only["metadata"]["type"] = "McpPlugin"
        variants.append(metadata_only)
        endpoint_only = remote()
        endpoint_only["endpoint"] = " STDIO://private-command"
        variants.append(endpoint_only)
        invalid_transport = remote()
        invalid_transport["additionalFields"]["transport"] = "unknown"
        variants.append(invalid_transport)
        invalid_endpoint = remote(endpoint="not-a-remote-endpoint")
        variants.append(invalid_endpoint)
        invalid_auth = remote()
        invalid_auth["auth"] = {"type": "unsupported"}
        variants.append(invalid_auth)
        for manifest in variants:
            with self.subTest(manifest_type=manifest.get("type"), endpoint=manifest["endpoint"]):
                with action_services() as state:
                    original = deepcopy(manifest)
                    for save in (
                        lambda: state.personal_service.save_personal_action(OWNER, manifest, enforce_governance=False),
                        lambda: state.group_service.save_group_action(GROUP, manifest, OWNER),
                        lambda: state.global_service.save_global_action(manifest, OWNER),
                    ):
                        with self.assertRaises(ValueError):
                            save()
                    self.assertEqual(manifest, original)
                    self.assertEqual(state.secret_saves, [])
                    self.assertEqual(state.personal.writes + state.group.writes + state.global_actions.writes, [])

    def test_valid_saves_resolve_type_and_bind_before_policy_and_after_storage(self):
        with action_services() as state:
            payload = remote()
            payload.pop("type")
            payload["metadata"]["type"] = "Model_Context_Protocol"
            payload.update({"scope": "global", "scope_id": "forged", "runtime_user_id": "forged"})
            payload["additionalFields"].update({
                "command": "inert", "env": {"OLD": "inert"},
                "provider": {"command": "legitimate-provider-value"},
            })
            personal = state.personal_service.save_personal_action(OWNER, payload)
            group = state.group_service.save_group_action(GROUP, payload, OWNER)
            global_action = state.global_service.save_global_action(payload, OWNER)
            for scope, scope_id, result in (
                ("personal", OWNER, personal), ("group", GROUP, group), ("global", "global", global_action),
            ):
                self.assert_origin(state, result, scope, scope_id)
                self.assertEqual(result["type"], "mcp")
                self.assertNotIn("command", result["additionalFields"])
                self.assertEqual(result["additionalFields"]["provider"]["command"], "legitimate-provider-value")
            self.assertEqual(len(state.policy_calls), 3)
            for manifest, kwargs in state.policy_calls:
                self.assert_origin(state, manifest, kwargs["scope_type"], kwargs["scope_id"])
                self.assertEqual(kwargs["user_id"], OWNER)
            self.assertEqual(state.secret_saves[-1][1:], ("remote-one", "global"))
            enabled = state.global_service.update_global_action_enabled("remote-one", False, OWNER)
            self.assert_origin(state, enabled, "global", "global")

    def test_global_save_creates_a_missing_action_with_default_metadata(self):
        with action_services() as state:
            created = state.global_service.save_global_action(remote(), OWNER)
            self.assertEqual(created["created_by"], OWNER)
            self.assertEqual(created["modified_by"], OWNER)
            self.assertEqual(created["created_at"], created["modified_at"])
            self.assertTrue(created["is_enabled"])
            self.assertEqual(len(state.global_actions.writes), 1)
            self.assert_origin(state, created, "global", "global")

    def test_global_save_preserves_existing_creation_metadata_and_disabled_state(self):
        with action_services() as state:
            state.global_actions.seed(dict(
                remote(), created_by="original-admin", created_at="2026-01-01T00:00:00",
                is_enabled=False,
            ))
            updated = state.global_service.save_global_action(remote(), OWNER)
            self.assertEqual(updated["created_by"], "original-admin")
            self.assertEqual(updated["created_at"], "2026-01-01T00:00:00")
            self.assertEqual(updated["modified_by"], OWNER)
            self.assertFalse(updated["is_enabled"])
            self.assertEqual(len(state.global_actions.writes), 1)

    def test_global_save_propagates_lookup_failures_without_writes(self):
        for status_code in (403, 429, 503):
            with self.subTest(status_code=status_code), action_services() as state:
                with patch.object(state.global_actions, "read_item", side_effect=StoreError(status_code)):
                    with self.assertRaises(StoreError):
                        state.global_service.save_global_action(remote(), OWNER)
                self.assertEqual(state.global_actions.writes, [])
                self.assertEqual(state.secret_saves, [])

    def test_destination_and_preconfiguration_denials_happen_before_secret_writes(self):
        for flag in ("deny_destination", "deny_preconfiguration"):
            with self.subTest(flag=flag), action_services() as state:
                state.settings[flag] = True
                for save in (
                    lambda: state.personal_service.save_personal_action(OWNER, remote(), enforce_governance=False),
                    lambda: state.group_service.save_group_action(GROUP, remote(), OWNER),
                    lambda: state.global_service.save_global_action(remote(), OWNER),
                ):
                    with self.assertRaises(PermissionError):
                        save()
                self.assertEqual(state.secret_saves, [])

    def test_retired_global_enabled_update_is_not_an_executable_save_bypass(self):
        with action_services() as state:
            state.global_actions.seed(retired())
            with self.assertRaises(state.manifest.McpStdioRemovedError):
                state.global_service.update_global_action_enabled("retired-one", True, OWNER)
            self.assertEqual(state.global_actions.writes, [])
            self.assertEqual(state.secret_saves, [])

    def test_mcp_save_requires_an_actual_actor_not_a_manifest_principal(self):
        with action_services() as state:
            state.actor = None
            manifest = dict(remote(), runtime_user_id="forged-user", user_id="forged-user")
            with self.assertRaises(PermissionError):
                state.group_service.save_group_action(GROUP, manifest)
            with self.assertRaises(PermissionError):
                state.global_service.save_global_action(manifest)
            self.assertEqual(state.secret_saves, [])

    def test_count_and_name_collisions_never_prove_source_migration(self):
        original = retired("old-id", "same_name")
        with action_services([original]) as state:
            state.personal.seed(dict(remote("different-id", "same_name"), user_id=OWNER))
            state.personal.seed(dict(remote("another-id", "another"), user_id=OWNER))
            result = state.personal_service.ensure_migration_complete(OWNER)
            remaining = source_plugins(state)
            self.assertEqual(remaining, [original])
            self.assertEqual(result["migrated_count"], 0)
            self.assertEqual(result["retained_count"], 1)
            self.assertTrue(result["complete"])
            self.assertEqual(state.source.writes, [])

    def test_remote_name_collision_migrates_by_exact_id_without_overwrite(self):
        original = remote("source-id", "same_name")
        with action_services([original]) as state:
            existing = dict(remote("unrelated-id", "same_name", "https://other.example/mcp"), user_id=OWNER)
            state.personal.seed(existing)
            result = state.personal_service.migrate_actions_from_user_settings(OWNER)
            remaining = source_plugins(state)
            unchanged = state.personal.read_item("unrelated-id", OWNER)
            self.assertEqual(result["migrated_count"], 1)
            self.assertEqual(remaining, [])
            self.assertEqual(unchanged["endpoint"], existing["endpoint"])
            self.assertEqual(len(state.personal.documents), 2)

    def test_idless_duplicate_names_have_distinct_stable_source_identities(self):
        originals = [
            remote(None, "same_name", "https://one.example/mcp"),
            remote(None, "same_name", "https://two.example/mcp"),
        ]
        with action_services(originals) as state:
            first = state.personal_service.list_legacy_personal_actions(OWNER)
            second = state.personal_service.list_legacy_personal_actions(OWNER)
            self.assertEqual([item["id"] for item in first], [item["id"] for item in second])
            self.assertNotEqual(first[0]["id"], first[1]["id"])
            result = state.personal_service.migrate_actions_from_user_settings(OWNER)
            again = state.personal_service.migrate_actions_from_user_settings(OWNER)
            self.assertEqual(result["migrated_count"], 2)
            self.assertEqual(again["migrated_count"], 0)
            self.assertEqual(len(state.personal.documents), 2)
            self.assertEqual(len(state.secret_saves), 2)

    def test_name_collisions_cannot_overwrite_another_actions_credentials(self):
        original = remote("new-id", "same_name")
        original["auth"] = {"type": "key", "key": "new-private-secret"}
        with action_services([original]) as state:
            existing = dict(remote("existing-id", "same-name"), user_id=OWNER)
            existing["auth"] = {"type": "key", "key": "existing-private-secret"}
            state.personal.seed(existing)
            result = state.personal_service.migrate_actions_from_user_settings(OWNER)
            remaining = source_plugins(state)
            self.assertEqual(result["retained_count"], 1)
            self.assertEqual(result["retained"][0]["code"], "legacy_secret_name_conflict")
            self.assertEqual(remaining, [original])
            self.assertEqual(state.secret_saves, [])
            views = state.personal_service.list_legacy_personal_actions(OWNER)
            replacement = deepcopy(original)
            replacement["name"] = "unique_name"
            converted = state.personal_service.reconfigure_legacy_personal_action(
                OWNER, views[0]["id"], replacement
            )
            self.assertEqual(converted["id"], "new-id")
            self.assertEqual(len(state.secret_saves), 1)

    def test_ambiguous_duplicate_records_are_retained_and_stale_delete_cannot_replay(self):
        original = retired(None, "duplicate")
        with action_services([original, original]) as state:
            views = state.personal_service.list_legacy_personal_actions(OWNER)
            self.assertNotEqual(views[0]["id"], views[1]["id"])
            deleted = state.personal_service.delete_legacy_personal_action(OWNER, views[0]["id"])
            self.assertTrue(deleted)
            with self.assertRaises(state.management.LegacyActionConflictError):
                state.personal_service.delete_legacy_personal_action(OWNER, views[0]["id"])
            with self.assertRaises(state.management.LegacyActionConflictError):
                state.personal_service.delete_legacy_personal_action(OWNER, views[1]["id"])
            remaining = source_plugins(state)
            self.assertEqual(remaining, [original])
        duplicate_remote = remote(None)
        with action_services([duplicate_remote, duplicate_remote]) as state:
            result = state.personal_service.migrate_actions_from_user_settings(OWNER)
            self.assertEqual(result["retained_count"], 2)
            self.assertEqual({item["code"] for item in result["retained"]}, {"legacy_identity_conflict"})
            self.assertEqual(state.secret_saves, [])

    def test_partial_migration_retains_unsupported_invalid_and_failed_sources(self):
        invalid = remote("invalid")
        invalid["additionalFields"]["transport"] = "not-supported"
        originals = [remote("valid"), retired("retired"), invalid, remote("fails")]
        with action_services(originals) as state:
            state.personal.fail_ids.add("fails")
            result = state.personal_service.migrate_actions_from_user_settings(OWNER)
            remaining = source_plugins(state)
            self.assertEqual(result["migrated_count"], 1)
            self.assertEqual(result["retained_count"], 2)
            self.assertEqual(result["failed_count"], 1)
            self.assertFalse(result["complete"])
            self.assertEqual(remaining, originals[1:])
            self.assertEqual({item[0]["id"] for item in state.secret_saves}, {"valid", "fails"})

    def test_source_update_failure_is_reported_and_retry_reuses_verified_destination(self):
        for failure_mode in ("fail_replace", "false_replace"):
            original = remote(None)
            original["auth"] = {"type": "key", "key": "private-input-secret"}
            with self.subTest(failure_mode=failure_mode), action_services([original]) as state:
                setattr(state.source, failure_mode, True)
                result = state.personal_service.migrate_actions_from_user_settings(OWNER)
                remaining = source_plugins(state)
                self.assertEqual(result["migrated_count"], 0)
                self.assertEqual(result["failed_count"], 1)
                self.assertFalse(result["complete"])
                self.assertEqual(remaining, [original])
                self.assertEqual(len(state.personal.documents), 1)
                setattr(state.source, failure_mode, False)
                retried = state.personal_service.migrate_actions_from_user_settings(OWNER)
                final_source = state.source.read_item(OWNER, OWNER)
                self.assertEqual(retried["migrated_count"], 1)
                self.assertTrue(retried["complete"])
                self.assertEqual(len(state.secret_saves), 1)
                self.assertEqual(final_source["settings"]["plugins"], [])
                self.assertEqual(final_source["settings"]["prompts"], ["keep-this-prompt"])
                self.assertEqual(final_source["settings"]["unrelated_setting"], "preserved")

    def test_uncertain_destination_write_is_idempotent_without_a_second_secret_write(self):
        original = remote("uncertain")
        with action_services([original]) as state:
            state.personal.fail_after_create.add("uncertain")
            result = state.personal_service.migrate_actions_from_user_settings(OWNER)
            remaining = source_plugins(state)
            self.assertEqual(result["failed_count"], 1)
            self.assertEqual(remaining, [original])
            state.personal.fail_after_create.clear()
            retry = state.personal_service.migrate_actions_from_user_settings(OWNER)
            self.assertEqual(retry["migrated_count"], 1)
            self.assertEqual(len(state.secret_saves), 1)
            self.assertEqual(len(state.personal.documents), 1)

    def test_cache_failure_does_not_misreport_a_verified_source_update(self):
        with action_services([remote()]) as state:
            def fail_cache(*_args):
                raise RuntimeError("cache failure")

            with patch.object(
                state.personal_service.user_settings_service, "_set_request_cached_user_settings", fail_cache
            ):
                result = state.personal_service.migrate_actions_from_user_settings(OWNER)
            remaining = source_plugins(state)
            self.assertEqual(result["migrated_count"], 1)
            self.assertEqual(result["failed_count"], 0)
            self.assertTrue(result["complete"])
            self.assertEqual(remaining, [])

    def test_existing_id_without_a_verified_receipt_is_retained_even_when_content_matches(self):
        original = remote("same-id")
        with action_services([original]) as state:
            state.personal.seed(dict(original, user_id=OWNER))
            result = state.personal_service.migrate_actions_from_user_settings(OWNER)
            remaining = source_plugins(state)
            self.assertEqual(result["migrated_count"], 0)
            self.assertEqual(result["retained_count"], 1)
            self.assertEqual(remaining, [original])
            self.assertEqual(state.secret_saves, [])

    def test_changed_destination_does_not_authorize_source_cleanup(self):
        original = remote("source")
        with action_services([original]) as state:
            state.source.fail_replace = True
            first = state.personal_service.migrate_actions_from_user_settings(OWNER)
            self.assertEqual(first["failed_count"], 1)
            destination = state.personal.read_item("source", OWNER)
            destination["endpoint"] = "https://changed.example/mcp"
            state.personal.seed(destination)
            state.source.fail_replace = False
            retry = state.personal_service.migrate_actions_from_user_settings(OWNER)
            remaining = source_plugins(state)
            self.assertEqual(retry["retained_count"], 1)
            self.assertEqual(retry["retained"][0]["code"], "legacy_action_conflict")
            self.assertEqual(remaining, [original])

    def test_source_replacement_conflict_preserves_concurrent_settings(self):
        original = retired("source")
        with action_services([original]) as state:
            views = state.personal_service.list_legacy_personal_actions(OWNER)

            def concurrent_edit():
                document = state.source.read_item(OWNER, OWNER)
                document["settings"]["plugins"][0]["description"] = "Changed concurrently"
                document["settings"]["unrelated_setting"] = "concurrent-value"
                state.source.seed(document)

            state.source.before_replace = concurrent_edit
            with self.assertRaises(state.management.LegacyActionConflictError):
                state.personal_service.delete_legacy_personal_action(OWNER, views[0]["id"])
            stored = state.source.read_item(OWNER, OWNER)
            self.assertEqual(stored["settings"]["plugins"][0]["description"], "Changed concurrently")
            self.assertEqual(stored["settings"]["unrelated_setting"], "concurrent-value")

    def test_changed_source_after_destination_save_is_never_removed(self):
        original = remote("source")
        with action_services([original]) as state:
            def source_changed():
                document = state.source.read_item(OWNER, OWNER)
                document["settings"]["plugins"][0]["endpoint"] = "https://new.example/mcp"
                state.source.seed(document)

            state.personal.after_create = source_changed
            result = state.personal_service.migrate_actions_from_user_settings(OWNER)
            remaining = source_plugins(state)
            self.assertEqual(result["migrated_count"], 0)
            self.assertEqual(result["retained_count"], 1)
            self.assertEqual(remaining[0]["endpoint"], "https://new.example/mcp")

    def test_locators_are_owner_bound_and_exact_snapshot_bound(self):
        original = retired(None)
        with action_services([original]) as state:
            views = state.personal_service.list_legacy_personal_actions(OWNER)
            state.source.seed({"id": "other-user", "settings": {"plugins": [original]}})
            reads_before = state.source.read_count
            with self.assertRaises(PermissionError):
                state.personal_service.get_legacy_personal_action("other-user", views[0]["id"])
            self.assertEqual(state.source.read_count, reads_before)
            state.actor = "other-user"
            with self.assertRaises(state.management.LegacyActionConflictError):
                state.personal_service.delete_legacy_personal_action("other-user", views[0]["id"])
            state.actor = OWNER
            document = state.source.read_item(OWNER, OWNER)
            document["settings"]["plugins"][0]["additionalFields"]["env"]["TOKEN"] = "changed-secret"
            state.source.seed(document)
            with self.assertRaises(state.management.LegacyActionConflictError):
                state.personal_service.get_legacy_personal_action(OWNER, views[0]["id"])

    def test_pass_through_requires_the_exact_authoritative_management_view(self):
        with action_services([retired()]) as state:
            views = state.personal_service.list_legacy_personal_actions(OWNER)
            unchanged = state.personal_service.is_unchanged_legacy_personal_action(OWNER, views[0])
            self.assertTrue(unchanged)
            for mutate in (
                lambda view: view["additionalFields"].update({"command": "new-process"}),
                lambda view: view.update({"id": "forged-id"}),
                lambda view: view["execution_status"].update({"code": "forged-status"}),
                lambda view: view.update({"is_legacy": False}),
            ):
                modified = deepcopy(views[0])
                mutate(modified)
                unchanged = state.personal_service.is_unchanged_legacy_personal_action(OWNER, modified)
                self.assertFalse(unchanged)
            original = retired()
            expected = state.management.retired_action_management_view(original, "personal", OWNER)
            unchanged = state.management.is_unchanged_retired_action(expected, original, "personal", OWNER)
            self.assertTrue(unchanged)
            expected["description"] = "changed"
            unchanged = state.management.is_unchanged_retired_action(expected, original, "personal", OWNER)
            self.assertFalse(unchanged)

    def test_reconfiguration_preserves_id_and_checks_governance_before_secrets(self):
        original = retired("original-id")
        with action_services([original]) as state:
            views = state.personal_service.list_legacy_personal_actions(OWNER)
            replacement = remote("forged-id")
            state.denied_types.add("mcp")
            with self.assertRaises(PermissionError):
                state.personal_service.reconfigure_legacy_personal_action(OWNER, views[0]["id"], replacement)
            self.assertEqual(state.secret_saves, [])
            self.assertEqual(state.personal.writes, [])
            state.denied_types.clear()
            converted = state.personal_service.reconfigure_legacy_personal_action(
                OWNER, views[0]["id"], replacement
            )
            remaining = source_plugins(state)
            self.assertEqual(converted["id"], "original-id")
            self.assertEqual(remaining, [])
            self.assert_origin(state, converted, "personal", OWNER)

    def test_unchanged_nonretired_legacy_views_do_not_receive_the_governance_exception(self):
        with action_services([remote()]) as state:
            views = state.personal_service.list_legacy_personal_actions(OWNER)
            unchanged = state.personal_service.is_unchanged_legacy_personal_action(OWNER, views[0])
            self.assertTrue(unchanged)
            state.denied_types.add("mcp")
            with self.assertRaises(PermissionError):
                state.personal_service.is_unchanged_legacy_personal_action(OWNER, views[0])
            self.assertEqual(state.personal.writes, [])
            self.assertEqual(state.secret_saves, [])

    def test_settings_preflight_preserves_retired_omissions_without_any_writes(self):
        originals = [retired("one"), retired(None), retired(None)]
        with action_services(originals) as state:
            state.denied_types.add("mcp")
            with patch.object(state.personal_service.user_settings_service, "get_user_settings", side_effect=_blocked):
                prepared = state.personal_service.prepare_legacy_personal_actions_update(OWNER, [])
            self.assertEqual(prepared["plugins"], originals)
            self.assertFalse(prepared["has_imports"])
            self.assertFalse(prepared["changed"])
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves + state.secret_gets, [])

    def test_route_settings_preflight_entry_point_preserves_sources_and_propagates_failures(self):
        original = retired()
        with action_services([original]) as state:
            state.denied_types.add("mcp")
            with patch.object(state.personal_service.user_settings_service, "get_user_settings", side_effect=_blocked):
                prepared = state.personal_service.prepare_legacy_action_settings_update(
                    user_id=OWNER, incoming_plugins=[]
                )
            self.assertEqual(prepared["plugins"], [original])
            self.assertFalse(prepared["has_imports"])
            self.assertFalse(prepared["changed"])
            self.assertIn("source_etag", prepared)
            with self.assertRaises(state.manifest.McpStdioRemovedError):
                state.personal_service.prepare_legacy_action_settings_update(
                    user_id=OWNER, incoming_plugins=[retired("new-retired")]
                )
            with patch.object(state.source, "read_item", side_effect=RuntimeError("unavailable")):
                with self.assertRaises(RuntimeError):
                    state.personal_service.prepare_legacy_action_settings_update(
                        user_id=OWNER, incoming_plugins=[]
                    )
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves + state.secret_gets, [])

    def test_settings_preflight_accepts_only_exact_authoritative_retired_views(self):
        originals = [retired(None, "duplicate"), retired(None, "duplicate")]
        with action_services(originals) as state:
            snapshots = state.management.legacy_action_snapshots(OWNER, originals)
            views = [state.management.legacy_action_management_view(snapshot) for snapshot in snapshots]
            state.denied_types.add("mcp")
            prepared = state.personal_service.prepare_legacy_personal_actions_update(OWNER, list(reversed(views)))
            self.assertEqual(prepared["plugins"], originals)
            self.assertFalse(prepared["has_imports"])
            self.assertFalse(prepared["changed"])
            forged = deepcopy(views[0])
            forged["additionalFields"]["command"] = "new-command"
            with self.assertRaises(state.manifest.McpStdioRemovedError):
                state.personal_service.prepare_legacy_personal_actions_update(OWNER, [forged])
            with self.assertRaises(ValueError):
                state.personal_service.prepare_legacy_personal_actions_update(OWNER, [views[0], views[0]])
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves, [])

    def test_settings_preflight_normalizes_and_authorizes_remote_imports_before_writes(self):
        original = retired()
        with action_services([original]) as state:
            incoming = remote("new-remote")
            incoming.pop("type")
            incoming["metadata"]["type"] = "Model_Context_Protocol"
            incoming.update({"is_global": True, "scope_id": "forged", "runtime_user_id": "admin"})
            incoming["additionalFields"]["command"] = "ignored-remote-process-field"
            unchanged_input = deepcopy(incoming)
            with patch.object(state.personal_service.user_settings_service, "get_user_settings", side_effect=_blocked):
                prepared = state.personal_service.prepare_legacy_personal_actions_update(OWNER, [incoming])
            self.assertTrue(prepared["has_imports"])
            self.assertTrue(prepared["changed"])
            self.assertEqual(prepared["plugins"][0], original)
            imported = prepared["plugins"][1]
            self.assertEqual(imported["type"], "mcp")
            self.assertNotIn("command", imported["additionalFields"])
            self.assert_origin(state, imported, "personal", OWNER)
            self.assertEqual(incoming, unchanged_input)
            self.assertEqual(len(state.policy_calls), 1)
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves + state.secret_gets, [])
            self.assertEqual(state.identity_hydrations, [])

    def test_settings_preflight_rejects_an_entire_batch_when_later_record_is_retired(self):
        invalids = [
            retired("new-retired"),
            dict(retired("metadata-only"), type="", metadata={"type": "McpPlugin"}),
            dict(retired("forged-retired"), is_legacy=True, legacy_source="settings.plugins"),
        ]
        for invalid in invalids:
            with self.subTest(action_id=invalid["id"]), action_services() as state:
                with self.assertRaises(ValueError):
                    state.personal_service.prepare_legacy_personal_actions_update(
                        OWNER, [remote("first-valid"), invalid]
                    )
                self.assertEqual(state.personal.writes + state.source.writes, [])
                self.assertEqual(state.secret_saves + state.secret_gets, [])
                self.assertEqual(state.settings_updates, [])

    def test_settings_preflight_checks_current_policy_and_type_governance(self):
        for mode in ("type", "destination", "preconfiguration"):
            with self.subTest(mode=mode), action_services() as state:
                if mode == "type":
                    state.denied_types.add("mcp")
                else:
                    state.settings[f"deny_{mode}"] = True
                with self.assertRaises(PermissionError):
                    state.personal_service.prepare_legacy_personal_actions_update(OWNER, [remote()])
                self.assertEqual(state.personal.writes + state.source.writes, [])
                self.assertEqual(state.secret_saves, [])

    def test_settings_preflight_cannot_convert_or_drop_retired_sources_by_import(self):
        original = retired("same-id")
        with action_services([original]) as state:
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            view = state.management.legacy_action_management_view(snapshot)
            replacement = remote(view["id"])
            for incoming in (replacement, remote("same-id"), original):
                with self.subTest(incoming_id=incoming["id"]):
                    with self.assertRaises(ValueError):
                        state.personal_service.prepare_legacy_personal_actions_update(OWNER, [incoming])
            remaining = source_plugins(state)
            self.assertEqual(remaining, [original])
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves, [])

    def test_settings_preflight_rejects_stale_locators_and_cross_owner_access(self):
        original = retired()
        with action_services([original]) as state:
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            view = state.management.legacy_action_management_view(snapshot)
            document = state.source.read_item(OWNER, OWNER)
            document["settings"]["plugins"][0]["description"] = "Changed source"
            state.source.seed(document)
            with self.assertRaises(state.management.LegacyActionConflictError):
                state.personal_service.prepare_legacy_personal_actions_update(OWNER, [view])
            reads_before = state.source.read_count
            with self.assertRaises(PermissionError):
                state.personal_service.prepare_legacy_personal_actions_update("different-owner", [])
            self.assertEqual(state.source.read_count, reads_before)
            self.assertEqual(state.personal.writes + state.source.writes, [])

    def test_settings_preflight_handles_nonretired_round_trip_and_removal_with_governance(self):
        original = remote()
        with action_services([original]) as state:
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            view = state.management.legacy_action_management_view(snapshot)
            prepared = state.personal_service.prepare_legacy_personal_actions_update(OWNER, [view])
            self.assertEqual(prepared["plugins"], [original])
            self.assertFalse(prepared["changed"])
            self.assertFalse(prepared["has_imports"])
            removed = state.personal_service.prepare_legacy_personal_actions_update(OWNER, [])
            self.assertEqual(removed["plugins"], [])
            self.assertTrue(removed["changed"])
            self.assertFalse(removed["has_imports"])
            state.denied_types.add("mcp")
            for incoming in ([view], []):
                with self.assertRaises(PermissionError):
                    state.personal_service.prepare_legacy_personal_actions_update(OWNER, incoming)
            self.assertEqual(state.personal.writes + state.source.writes, [])

    def test_settings_preflight_rejects_cross_record_secret_name_collisions(self):
        first = remote("first", "same_name")
        second = remote("second", "same-name")
        first["auth"] = {"type": "key", "key": "private-first-secret"}
        second["auth"] = {"type": "key", "key": "private-second-secret"}
        with action_services() as state:
            with patch.object(state.personal_service.user_settings_service, "get_user_settings", side_effect=_blocked):
                with self.assertRaises(state.management.LegacyActionSecretConflictError):
                    state.personal_service.prepare_legacy_personal_actions_update(OWNER, [first, second])
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves + state.secret_gets, [])

    def test_legacy_conversion_preflight_preserves_identity_without_source_or_secret_writes(self):
        original = retired("original-id")
        with action_services([original]) as state:
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            replacement = remote("forged-id", "new_name")
            replacement["auth"] = {"type": "key", "key": "private-replacement-secret"}
            replacement["additionalFields"]["auth_method"] = "bearer"
            with patch.object(state.personal_service.user_settings_service, "get_user_settings", side_effect=_blocked):
                prepared = state.personal_service.prepare_legacy_personal_action_reconfiguration(
                    OWNER, snapshot.locator, replacement
                )
            self.assertEqual(prepared["id"], "original-id")
            self.assert_origin(state, prepared, "personal", OWNER)
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves + state.secret_gets, [])
            remaining = source_plugins(state)
            self.assertEqual(remaining, [original])

    def test_route_conversion_preflight_entry_point_preserves_identity_and_error_contracts(self):
        original = retired("original-id")
        with action_services([original]) as state:
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            with patch.object(state.personal_service.user_settings_service, "get_user_settings", side_effect=_blocked):
                prepared = state.personal_service.validate_legacy_personal_action_reconfiguration(
                    user_id=OWNER, locator=snapshot.locator, replacement=remote("ignored-id")
                )
            self.assertEqual(prepared["id"], "original-id")
            self.assert_origin(state, prepared, "personal", OWNER)
            with self.assertRaises(state.management.LegacyActionConflictError) as conflict:
                state.personal_service.validate_legacy_personal_action_reconfiguration(
                    user_id=OWNER, locator=f"{snapshot.locator}-stale", replacement=remote()
                )
            self.assertEqual(conflict.exception.code, "legacy_action_conflict")
            with self.assertRaises(state.manifest.McpStdioRemovedError):
                state.personal_service.validate_legacy_personal_action_reconfiguration(
                    user_id=OWNER, locator=snapshot.locator, replacement=original
                )
            state.denied_types.add("mcp")
            with self.assertRaises(PermissionError):
                state.personal_service.validate_legacy_personal_action_reconfiguration(
                    user_id=OWNER, locator=snapshot.locator, replacement=remote()
                )
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves + state.secret_gets, [])

    def test_legacy_conversion_preflight_detects_conflicts_before_any_batch_mutation(self):
        original = retired("original-id")
        with action_services([original]) as state:
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            replacement = remote("ignored-id", "same_name")
            replacement["auth"] = {"type": "key", "key": "private-new-secret"}
            state.personal.seed(dict(remote("other-id", "same-name"), user_id=OWNER))
            with patch.object(state.personal_service.user_settings_service, "get_user_settings", side_effect=_blocked):
                with self.assertRaises(state.management.LegacyActionSecretConflictError):
                    state.personal_service.prepare_legacy_personal_action_reconfiguration(
                        OWNER, snapshot.locator, replacement
                    )
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves, [])

    def test_legacy_conversion_preflight_rejects_unverified_destination_id_collisions(self):
        original = retired("existing-id")
        with action_services([original]) as state:
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            state.personal.seed(dict(remote("existing-id", "unrelated"), user_id=OWNER))
            with self.assertRaises(state.management.LegacyActionConflictError):
                state.personal_service.prepare_legacy_personal_action_reconfiguration(
                    OWNER, snapshot.locator, remote("ignored-id")
                )
            self.assertEqual(state.personal.writes + state.source.writes, [])
            self.assertEqual(state.secret_saves, [])

    def test_legacy_conversion_preflight_accepts_only_a_verified_retry_destination(self):
        original = retired("existing-id")
        with action_services([original]) as state:
            snapshot = state.management.legacy_action_snapshots(OWNER, [original])[0]
            replacement = remote("ignored-id", "replacement")
            state.source.fail_replace = True
            with self.assertRaises(state.management.LegacyActionSourceUpdateError):
                state.personal_service.reconfigure_legacy_personal_action(OWNER, snapshot.locator, replacement)
            writes_before = len(state.personal.writes)
            secrets_before = len(state.secret_saves)
            prepared = state.personal_service.prepare_legacy_personal_action_reconfiguration(
                OWNER, snapshot.locator, replacement
            )
            self.assertEqual(prepared["id"], "existing-id")
            self.assertEqual(len(state.personal.writes), writes_before)
            self.assertEqual(len(state.secret_saves), secrets_before)
            changed_replacement = dict(replacement, endpoint="https://changed.example/mcp")
            with self.assertRaises(state.management.LegacyActionConflictError):
                state.personal_service.prepare_legacy_personal_action_reconfiguration(
                    OWNER, snapshot.locator, changed_replacement
                )

    def test_failed_reconfiguration_keeps_source_and_supports_retry(self):
        original = retired("original-id")
        with action_services([original]) as state:
            views = state.personal_service.list_legacy_personal_actions(OWNER)
            with self.assertRaises(state.manifest.McpStdioRemovedError):
                state.personal_service.reconfigure_legacy_personal_action(OWNER, views[0]["id"], original)
            state.source.fail_replace = True
            with self.assertRaises(state.management.LegacyActionSourceUpdateError):
                state.personal_service.reconfigure_legacy_personal_action(OWNER, views[0]["id"], remote())
            remaining = source_plugins(state)
            self.assertEqual(remaining, [original])
            state.source.fail_replace = False
            saved = state.personal_service.reconfigure_legacy_personal_action(OWNER, views[0]["id"], remote())
            self.assertEqual(saved["id"], "original-id")
            self.assertEqual(len(state.secret_saves), 1)

    def test_reconfiguration_rejects_a_stale_source_before_any_destination_mutation(self):
        with action_services([retired()]) as state:
            views = state.personal_service.list_legacy_personal_actions(OWNER)
            document = state.source.read_item(OWNER, OWNER)
            document["settings"]["plugins"][0]["description"] = "source has changed"
            state.source.seed(document)
            with self.assertRaises(state.management.LegacyActionConflictError):
                state.personal_service.reconfigure_legacy_personal_action(OWNER, views[0]["id"], remote())
            self.assertEqual(state.personal.writes, [])
            self.assertEqual(state.secret_saves, [])

    def test_routes_never_blanket_clear_legacy_plugins_or_claim_partial_success(self):
        originals = [retired("keep"), remote("fails")]
        with action_services(originals) as state:
            state.personal.fail_ids.add("fails")
            document = state.source.read_item(OWNER, OWNER)
            document["settings"]["agents"] = [{"name": "old_agent"}]
            state.source.seed(document)
            with state.flask_app.test_request_context("/api/migrate/all", method="POST"):
                response = state.routes.migrate_all_user_data()
            body = response.get_json()
            remaining = source_plugins(state)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(body["success"])
            self.assertEqual(body["actions_migrated"], 0)
            self.assertEqual(body["actions_retained"], 1)
            self.assertEqual(body["actions_failed"], 1)
            self.assertEqual(remaining, originals)
            self.assertEqual(state.settings_updates, [{"agents": []}])
            self.assertNotIn("private-", json.dumps(body))

    def test_retired_only_status_has_safe_management_views_and_no_migration_prompt(self):
        with action_services([retired()]) as state:
            with state.flask_app.test_request_context("/api/migrate/status"):
                response = state.routes.get_migration_status()
            body = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertFalse(body["migration_needed"])
            self.assertEqual(body["legacy_data"]["actions_unsupported_count"], 1)
            self.assertEqual(body["legacy_data"]["actions_pending_count"], 0)
            self.assertNotIn("private-", json.dumps(body))
            with state.flask_app.test_request_context("/api/migrate/actions", method="POST"):
                migrated_response = state.routes.migrate_user_actions()
            migrated = migrated_response.get_json()
            self.assertEqual(migrated["retained_count"], 1)
            self.assertEqual(migrated["migrated_count"], 0)
            self.assertEqual(state.secret_saves, [])

    def test_management_module_cold_import_does_not_load_settings_or_runtime(self):
        script = """
import socket
import sys
sys.path.insert(0, sys.argv[1])
def blocked(*args, **kwargs):
    raise RuntimeError("External I/O is forbidden.")
socket.socket.connect = blocked
socket.create_connection = blocked
import functions_legacy_action_management
for forbidden in ("config", "functions_settings", "functions_governance", "semantic_kernel"):
    if forbidden in sys.modules:
        raise RuntimeError("Management inspection loaded a bootstrap owner or runtime.")
"""
        completed = subprocess.run(
            [sys.executable, "-c", script, str(APP)], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_migration_ui_distinguishes_retained_and_retryable_outcomes(self):
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8')
    .replace(/^import .*;\r?$/gm, '').replace(/\bexport /g, '');
function node() {
    const classes = new Set(['d-none']);
    return {
        textContent: '', disabled: false, className: '',
        style: { width: '', removeProperty() {} },
        classList: { add: value => classes.add(value), remove: value => classes.delete(value),
            contains: value => classes.has(value) },
        setAttribute() {}, replaceChildren() {}, addEventListener() {},
        querySelector() { return this.child; }
    };
}
const nodes = Object.fromEntries(['migration-banner', 'migrate-all-btn', 'migration-progress',
    'migration-status-text'].map(id => [id, node()]));
nodes['migration-banner'].child = node();
nodes['migration-progress'].child = node();
const toasts = [];
const responses = [];
const context = vm.createContext({
    document: {
        getElementById: id => nodes[id], querySelector: () => null, addEventListener() {},
        createElement: node, createTextNode: value => ({ textContent: value })
    },
    window: {}, console: { error() {} },
    showToast: (message, kind) => toasts.push({ message, kind }),
    fetch: async () => ({ ok: true, json: async () => responses.shift() })
});
vm.runInContext(source, context);
const retiredOnly = { migration_needed: false, legacy_data: { agents_count: 0,
    actions_pending_count: 0, actions_failed_count: 0, actions_retained_count: 1 } };
const pending = { migration_needed: true, legacy_data: { agents_count: 0,
    actions_pending_count: 1, actions_failed_count: 0, actions_retained_count: 1 } };
(async () => {
    responses.push(retiredOnly);
    await context.checkMigrationStatus();
    assert.equal(nodes['migration-banner'].classList.contains('d-none'), true);
    responses.push(pending);
    await context.checkMigrationStatus();
    assert.equal(nodes['migration-banner'].classList.contains('d-none'), false);
    assert.match(nodes['migration-banner'].child.textContent, /manual reconfiguration/);
    responses.push({ action_migration: { migrated_count: 1, retained_count: 1,
        failed_count: 0, complete: true } }, retiredOnly);
    await context.performMigration();
    assert.equal(toasts.at(-1).kind, 'warning');
    assert.match(toasts.at(-1).message, /Stdio actions cannot run/);
    assert.equal(nodes['migration-banner'].classList.contains('d-none'), true);
    responses.push({ action_migration: { migrated_count: 0, retained_count: 1,
        failed_count: 1, complete: false } }, pending);
    await context.performMigration();
    assert.equal(toasts.at(-1).kind, 'warning');
    assert.match(toasts.at(-1).message, /incomplete/);
    assert.equal(nodes['migration-banner'].classList.contains('d-none'), false);
    assert.equal(nodes['migrate-all-btn'].disabled, false);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        completed = subprocess.run(
            ["node", "-e", script, str(APP / "static" / "js" / "workspace" / "workspace-migration.js")],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
