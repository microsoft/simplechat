# test_m365_action_lifecycle.py
"""
Functional regressions for Microsoft 365 action lifecycle and capability ceilings.
Version: 0.261.036
Implemented in: 0.261.029

Real action persistence modules run against scoped in-memory Cosmos/Key Vault
adapters. No Azure credentials, application startup, or network calls are used.
The loader overlay probe executes its actual function with real capability
helpers, separately from unrelated model/bootstrap dependencies.
"""

import ast
import copy
import importlib.util
import sys
import types
from pathlib import Path

import pytest
from azure.cosmos import exceptions


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


class MemoryContainer:
    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.records = {}
        self.writes = []
        self.serial = 0
        self.before_replace = None

    def read_item(self, item, partition_key):
        key = (partition_key, item)
        if key not in self.records:
            raise exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found")
        return copy.deepcopy(self.records[key])

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        values = {entry["name"]: entry["value"] for entry in parameters or []}
        return [
            copy.deepcopy(record)
            for (partition, _item), record in self.records.items()
            if (partition_key is None or partition == partition_key)
            and ("@name" not in values or record.get("name") == values["@name"])
        ]

    def _store(self, body, operation):
        self.serial += 1
        stored = copy.deepcopy(body)
        stored["_etag"] = str(self.serial)
        self.records[(stored[self.partition_field], stored["id"])] = stored
        self.writes.append((operation, stored["id"]))
        return copy.deepcopy(stored)

    def create_item(self, body):
        if (body[self.partition_field], body["id"]) in self.records:
            raise exceptions.CosmosResourceExistsError(status_code=409, message="Exists")
        return self._store(body, "create")

    def upsert_item(self, body):
        return self._store(body, "upsert")

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if self.before_replace:
            callback, self.before_replace = self.before_replace, None
            callback(body[self.partition_field], item)
        existing = self.read_item(item, body[self.partition_field])
        if existing["_etag"] != etag:
            raise exceptions.CosmosHttpResponseError(status_code=412, message="Changed")
        return self._store(body, "replace")

    def delete_item(self, item, partition_key):
        self.read_item(item, partition_key)
        del self.records[(partition_key, item)]

    def execute_item_batch(self, batch_operations, partition_key):
        for operation, args in batch_operations:
            if operation != "create" or args[0][self.partition_field] != partition_key:
                raise AssertionError("Expected atomic scope-bound migration creates.")
            if (partition_key, args[0]["id"]) in self.records:
                raise exceptions.CosmosResourceExistsError(status_code=409, message="Exists")
        return [self.create_item(args[0]) for _operation, args in batch_operations]


def _module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


@pytest.fixture
def lifecycle(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_ROOT))
    containers = {
        "personal": MemoryContainer("user_id"),
        "group": MemoryContainer("group_id"),
        "global": MemoryContainer("id"),
        "settings": MemoryContainer("id"),
    }
    containers["settings"].create_item({"id": "owner", "settings": {"plugins": []}})
    secret_writes = []

    def save_secret(payload, **kwargs):
        secret_writes.append(payload["name"])
        return copy.deepcopy(payload)

    def unchanged(payload, *args, **kwargs):
        return copy.deepcopy(payload)

    stubs = {
        "config": _module("config",
            cosmos_personal_actions_container=containers["personal"],
            cosmos_group_actions_container=containers["group"],
            cosmos_global_actions_container=containers["global"],
            cosmos_user_settings_container=containers["settings"]),
        "functions_authentication": _module("functions_authentication", get_current_user_id=lambda: "owner"),
        "functions_keyvault": _module("functions_keyvault",
            SecretReturnType=types.SimpleNamespace(TRIGGER="trigger", NAME="name", VALUE="value"),
            clean_name_for_keyvault=lambda value: value,
            redact_plugin_secret_values=unchanged,
            keyvault_plugin_save_helper=save_secret,
            keyvault_plugin_get_helper=unchanged,
            keyvault_plugin_delete_helper=lambda *args, **kwargs: None),
        "functions_settings": _module("functions_settings",
            get_settings=lambda: {},
            get_user_settings=lambda user_id: containers["settings"].read_item(user_id, user_id),
            _authorize_user_settings_access=lambda *args: None,
            update_user_settings=lambda *args, **kwargs: True,
            _set_request_cached_user_settings=lambda *args: None,
            _delete_user_ui_settings_cache=lambda *args: None),
        "functions_workspace_identities": _module("functions_workspace_identities",
            WORKSPACE_IDENTITY_SCOPE_PERSONAL="personal",
            WORKSPACE_IDENTITY_SCOPE_GROUP="group",
            WORKSPACE_IDENTITY_SCOPE_GLOBAL="global",
            hydrate_action_identity_reference=unchanged,
            validate_action_identity_reference=lambda *args, **kwargs: None),
        "functions_governance": _module("functions_governance",
            ensure_action_type_access=lambda *args: None,
            filter_actions_by_action_type_access=lambda user_id, actions, *args: actions),
        "functions_appinsights": _module("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_debug": _module("functions_debug", debug_print=lambda *args, **kwargs: None),
        "functions_chat_bootstrap_cache": _module("functions_chat_bootstrap_cache",
            bump_chat_bootstrap_user_cache_version=lambda *args, **kwargs: None,
            bump_chat_bootstrap_global_cache_version=lambda *args, **kwargs: None),
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    modules = {}
    for scope in ("personal", "group", "global"):
        name = f"functions_{scope}_actions"
        spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules[scope] = module

    def save(scope, payload):
        if scope == "personal":
            return modules[scope].save_personal_action("owner", payload)
        if scope == "group":
            return modules[scope].save_group_action("group", payload, user_id="owner")
        return modules[scope].save_global_action(payload, user_id="owner")

    return types.SimpleNamespace(containers=containers, modules=modules, save=save, secret_writes=secret_writes)


def manifest(action_type="msgraph", action_id=None):
    result = {
        "name": "mail_tools", "displayName": "Mail tools", "description": "Test action",
        "type": action_type, "endpoint": "", "auth": {"type": "user"},
        "metadata": {}, "additionalFields": {},
    }
    if action_id:
        result["id"] = action_id
    return result


def seed(lifecycle, scope, payload):
    payload = copy.deepcopy(payload)
    if scope == "personal":
        payload["user_id"] = "owner"
    elif scope == "group":
        payload["group_id"] = "group"
    else:
        payload["is_global"] = True
    return lifecycle.containers[scope].create_item(payload)


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
@pytest.mark.parametrize("alias", ["msgraph", "microsoft_graph", "Microsoft-Graph", "MSGraphPlugin", "microsoft.graph.plugin"])
def test_new_legacy_aliases_are_rejected_before_secrets(lifecycle, scope, alias):
    with pytest.raises(ValueError, match="cannot be created"):
        lifecycle.save(scope, manifest(alias, "invented"))
    assert not lifecycle.secret_writes
    assert not lifecycle.containers[scope].records


@pytest.mark.parametrize("scope", ["personal", "global"])
@pytest.mark.parametrize("status", [403, 429, 500])
def test_exact_id_lookup_never_treats_storage_failure_as_absence(lifecycle, monkeypatch, scope, status):
    failure = exceptions.CosmosHttpResponseError(status_code=status, message="Storage unavailable")

    def unavailable(*args, **kwargs):
        raise failure

    monkeypatch.setattr(lifecycle.containers[scope], "read_item", unavailable)
    with pytest.raises(exceptions.CosmosHttpResponseError) as raised:
        lifecycle.save(scope, manifest("m365_email", "action-id"))
    assert raised.value is failure
    assert lifecycle.secret_writes == []
    assert lifecycle.containers[scope].writes == []


@pytest.mark.parametrize("status", [403, 429, 500])
def test_migration_receipt_lookup_never_treats_storage_failure_as_absence(lifecycle, monkeypatch, status):
    failure = exceptions.CosmosHttpResponseError(status_code=status, message="Storage unavailable")

    def unavailable(*args, **kwargs):
        raise failure

    monkeypatch.setattr(lifecycle.containers["personal"], "read_item", unavailable)
    with pytest.raises(exceptions.CosmosHttpResponseError) as raised:
        lifecycle.modules["personal"]._migrate_historical_msgraph_action("owner", manifest())
    assert raised.value is failure
    assert lifecycle.secret_writes == []
    assert lifecycle.containers["personal"].writes == []


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
def test_legacy_edits_require_exact_live_id_and_type(lifecycle, scope):
    existing = seed(lifecycle, scope, manifest(action_id="original"))
    name_only = manifest()
    with pytest.raises(ValueError, match="cannot be created"):
        lifecycle.save(scope, name_only)
    clone = manifest(action_id="clone")
    with pytest.raises(ValueError, match="cannot be created"):
        lifecycle.save(scope, clone)
    changed = manifest(action_id="original")
    changed["description"] = "Edited existing action"
    saved = lifecycle.save(scope, changed)
    assert saved["id"] == existing["id"]
    assert saved["description"] == "Edited existing action"
    assert lifecycle.containers[scope].writes[-1][0] == "replace"

    seed(lifecycle, scope, manifest("m365_email", "typed"))
    with pytest.raises(ValueError, match="cannot be created"):
        lifecycle.save(scope, manifest(action_id="typed"))


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
def test_delete_and_concurrent_delete_cannot_be_undone(lifecycle, scope):
    existing = seed(lifecycle, scope, manifest(action_id="original"))
    container = lifecycle.containers[scope]
    container.before_replace = lambda partition, item: container.delete_item(item, partition)
    with pytest.raises(exceptions.CosmosResourceNotFoundError):
        lifecycle.save(scope, manifest(action_id="original"))
    assert not container.records
    with pytest.raises(ValueError, match="cannot be created"):
        lifecycle.save(scope, manifest(action_id=existing["id"]))
    assert not container.records


@pytest.mark.parametrize("scope,field", [("personal", "user_id"), ("group", "group_id")])
def test_other_scope_is_not_proof_of_legacy_existence(lifecycle, scope, field):
    payload = manifest(action_id="original")
    payload[field] = "someone-else"
    lifecycle.containers[scope].create_item(payload)
    with pytest.raises(ValueError, match="cannot be created"):
        lifecycle.save(scope, manifest(action_id="original"))
    assert not lifecycle.secret_writes


def test_safe_historical_migration_and_stale_array_replay(lifecycle):
    settings = lifecycle.containers["settings"]
    historical = {"id": "owner", "settings": {"plugins": [manifest()]}}
    settings.upsert_item(historical)
    migrated = lifecycle.modules["personal"].ensure_migration_complete("owner")
    actions = lifecycle.modules["personal"].get_personal_actions("owner")
    assert migrated["migrated_count"] == 1
    assert migrated["complete"] is True
    assert len(actions) == 1
    assert actions[0]["type"] == "msgraph"
    assert not actions[0].get("_action_migration")
    removed = lifecycle.modules["personal"].delete_personal_action("owner", actions[0]["id"])
    assert removed
    settings.upsert_item(historical)
    replayed = lifecycle.modules["personal"].ensure_migration_complete("owner")
    after = lifecycle.modules["personal"].get_personal_actions("owner")
    assert replayed["migrated_count"] == 0
    assert replayed["complete"] is True
    assert after == []
    receipts = list(lifecycle.containers["personal"].records.values())
    assert len(receipts) == 1
    assert receipts[0]["_action_migration"] is True


def test_graph_migration_retains_stdio_management_and_prevents_replay(lifecycle):
    personal = lifecycle.modules["personal"]
    settings = lifecycle.containers["settings"]
    retired = {
        **manifest("mcp", "retired-mcp"), "name": "retired_mcp",
        "endpoint": "stdio://python", "auth": {"type": "NoAuth"},
        "additionalFields": {"transport": "stdio", "command": "must-not-run"},
    }
    settings.upsert_item({"id": "owner", "settings": {"plugins": [manifest(), retired]}})
    result = personal.ensure_migration_complete("owner")
    persisted = settings.read_item("owner", "owner")
    actions = personal.get_personal_actions("owner")
    status = personal.get_action_migration_status("owner")
    assert result["migrated_count"] == result["retained_count"] == 1
    assert result["failed_count"] == 0
    assert persisted["settings"]["plugins"] == [retired]
    assert len(actions) == 1 and actions[0]["type"] == "msgraph"
    assert status["retired_count"] == 1 and status["pending_count"] == 0
    assert lifecycle.secret_writes == ["mail_tools"]
    deleted = personal.delete_personal_action("owner", actions[0]["id"])
    settings.upsert_item({"id": "owner", "settings": {"plugins": [manifest(), retired]}})
    repeated = personal.ensure_migration_complete("owner")
    remaining_actions = personal.get_personal_actions("owner")
    remaining_sources = settings.read_item("owner", "owner")["settings"]["plugins"]
    assert deleted is True
    assert repeated["migrated_count"] == 0
    assert remaining_actions == []
    assert remaining_sources == [retired]


def test_global_enable_keeps_the_original_etag_after_scope_preparation(lifecycle):
    seed(lifecycle, "global", manifest(action_id="global-graph"))
    result = lifecycle.modules["global"].update_global_action_enabled("global-graph", False, user_id="owner")
    saved = lifecycle.containers["global"].read_item("global-graph", "global-graph")
    assert result is not None
    assert saved["is_enabled"] is False
    assert lifecycle.containers["global"].writes[-1] == ("replace", "global-graph")


def test_action_api_cannot_remove_receipt_to_recreate_deleted_legacy(lifecycle):
    personal = lifecycle.modules["personal"]
    settings = lifecycle.containers["settings"]
    historical = {"id": "owner", "settings": {"plugins": [manifest()]}}
    settings.upsert_item(historical)
    migrated = personal.ensure_migration_complete("owner")
    actions = personal.get_personal_actions("owner")
    receipt = next(
        item for item in lifecycle.containers["personal"].records.values()
        if item.get("_action_migration")
    )
    hidden = personal.get_personal_action("owner", receipt["id"])
    deleted = personal.delete_personal_action("owner", actions[0]["id"])
    settings.upsert_item(historical)
    receipt_deleted = personal.delete_personal_action("owner", receipt["id"])
    replayed = personal.ensure_migration_complete("owner")
    after = personal.get_personal_actions("owner")
    retained_receipt = lifecycle.containers["personal"].read_item(receipt["id"], "owner")
    assert migrated["migrated_count"] == 1
    assert hidden is None
    assert deleted is True
    assert receipt_deleted is False
    assert replayed["migrated_count"] == 0
    assert after == []
    assert retained_receipt["_action_migration"] is True


@pytest.mark.parametrize("prefix,marker", [(True, False), (False, True)])
def test_internal_receipts_are_excluded_from_every_action_lookup(lifecycle, prefix, marker):
    import json_schema_validation as validation

    action_id = f"{validation.ACTION_MIGRATION_ID_PREFIX}test" if prefix else "internal-receipt"
    receipt = {
        **manifest(action_id=action_id), "user_id": "owner",
        "_action_migration": marker,
    }
    lifecycle.containers["personal"].create_item(receipt)
    personal = lifecycle.modules["personal"]
    listed = personal.get_personal_actions("owner")
    direct = personal.get_personal_action("owner", action_id)
    by_name = personal.get_personal_action("owner", receipt["name"])
    by_names = personal.get_actions_by_names("owner", [receipt["name"]])
    by_type = personal.get_actions_by_type("owner", "msgraph")
    assert listed == by_names == by_type == []
    assert direct is None
    assert by_name is None
    with pytest.raises(ValueError, match="server managed"):
        lifecycle.save("personal", manifest("m365_email", action_id))


def test_regular_action_name_is_not_treated_as_a_reserved_record_id(lifecycle):
    import json_schema_validation as validation

    payload = manifest("m365_email")
    payload["name"] = f"{validation.ACTION_MIGRATION_ID_PREFIX}named_action"
    saved = lifecycle.save("personal", payload)
    deleted = lifecycle.modules["personal"].delete_personal_action("owner", payload["name"])
    assert not saved["id"].startswith(validation.ACTION_MIGRATION_ID_PREFIX)
    assert deleted is True


def test_independent_migration_retains_invalid_sources_and_successful_receipts(lifecycle):
    historical = [manifest(), {"name": ""}]
    lifecycle.containers["settings"].upsert_item({"id": "owner", "settings": {"plugins": historical}})
    result = lifecycle.modules["personal"].ensure_migration_complete("owner")
    preserved = lifecycle.containers["settings"].read_item("owner", "owner")
    actions = lifecycle.modules["personal"].get_personal_actions("owner")
    assert preserved["settings"]["plugins"] == [historical[1]]
    assert result["migrated_count"] == 1
    assert result["retained_count"] == 1
    assert result["failed_count"] == 0
    assert len(actions) == 1


def test_migration_does_not_overwrite_a_concurrent_settings_edit(lifecycle):
    settings = lifecycle.containers["settings"]
    settings.upsert_item({"id": "owner", "settings": {"plugins": [manifest()]}})

    def concurrent_edit(partition, item):
        document = settings.read_item(item, partition)
        document["settings"]["other_preference"] = True
        settings.upsert_item(document)

    settings.before_replace = concurrent_edit
    conflicted = lifecycle.modules["personal"].ensure_migration_complete("owner")
    preserved = settings.read_item("owner", "owner")
    assert preserved["settings"]["other_preference"] is True
    assert len(preserved["settings"]["plugins"]) == 1
    assert conflicted["retained_count"] == 1
    assert conflicted["complete"] is False
    migrated = lifecycle.modules["personal"].ensure_migration_complete("owner")
    after = settings.read_item("owner", "owner")
    assert migrated["migrated_count"] == 0
    assert migrated["complete"] is True
    assert after["settings"]["other_preference"] is True
    assert after["settings"]["plugins"] == []


def test_settings_ingress_cannot_introduce_legacy_or_forge_receipts(lifecycle):
    import json_schema_validation as validation

    existing = manifest(action_id="original")
    validation.validate_legacy_plugin_settings_update({"plugins": [existing]}, {"plugins": [copy.deepcopy(existing)]})
    for candidate in (manifest(action_id="new"), manifest(), manifest("microsoft_graph", "new")):
        with pytest.raises(ValueError, match="cannot be created"):
            validation.validate_legacy_plugin_settings_update({"plugins": [existing]}, {"plugins": [candidate]})
    with pytest.raises(ValueError, match="cannot be created"):
        validation.validate_legacy_plugin_settings_update({}, {"semantic_kernel_plugins": [existing]})
    forged = manifest("m365_email", f"{validation.ACTION_MIGRATION_ID_PREFIX}forged")
    with pytest.raises(ValueError, match="server managed"):
        lifecycle.save("personal", forged)


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
@pytest.mark.parametrize("action_type", ["m365_calendar", "m365_email", "m365_onedrive", "m365_sharepoint"])
def test_typed_actions_save_with_inherited_endpoint_and_bounded_defaults(lifecycle, scope, action_type):
    from functions_m365_operations import get_m365_default_capabilities

    saved = lifecycle.save(scope, manifest(action_type))
    expected = get_m365_default_capabilities(action_type)
    assert saved["auth"] == {"type": "user"}
    assert saved["endpoint"] == ""
    assert saved["additionalFields"]["m365_capabilities"] == expected
    assert saved["additionalFields"]["maximum_sharing_acknowledgement"] == "always"
    for write in ("send_mail", "mark_message_as_read", "create_calendar_invite"):
        assert saved["additionalFields"]["m365_capabilities"].get(write, False) is False


@pytest.mark.parametrize("scope", ["personal", "group", "global"])
@pytest.mark.parametrize("alias", [
    "M365_CALENDAR", "m365-calendar", " m365_calendar ", "m365calendar",
    "M365CalendarPlugin", "m365_email_plugin", "Microsoft 365 Email",
    "m365-oneDrive", "m365_sharepoint ", "M365SharePointPlugin",
])
def test_new_m365_type_aliases_are_not_canonicalized_at_save(lifecycle, scope, alias):
    import json_schema_validation as validation

    payload = manifest(alias)
    with pytest.raises(ValueError, match="exact source-specific type"):
        lifecycle.save(scope, payload)
    schema_error = validation.validate_plugin(payload)
    assert schema_error == "Invalid Microsoft 365 source configuration."
    assert not lifecycle.secret_writes
    assert not lifecycle.containers[scope].records


@pytest.mark.parametrize("change", [
    {"auth": {"type": "identity", "identity": "managed_identity"}},
    {"auth": {"type": "user", "key": "not-a-real-key"}},
    {"identity_id": "another-workspace-identity"},
    {"endpoint": "https://graph.microsoft.com"},
    {"additionalFields": {"m365_capabilities": {"send_mail": True}}},
    {"additionalFields": {"site_allowlist": ["site"]}},
    {"additionalFields": {"maximum_sharing_acknowledgement": "forever"}},
    {"m365_capabilities": {"send_mail": True}},
])
def test_typed_actions_reject_auth_scope_and_capability_bypasses(lifecycle, change):
    payload = manifest("m365_calendar")
    payload.update(change)
    with pytest.raises(ValueError):
        lifecycle.save("personal", payload)
    assert not lifecycle.secret_writes


def test_loader_intersects_saved_type_and_agent_limits(lifecycle):
    from functions_action_manifest import copy_action_manifest
    import functions_m365_execution as execution
    import functions_m365_operations as m365
    import functions_msgraph_operations as legacy

    tree = ast.parse((APP_ROOT / "semantic_kernel_loader.py").read_text(encoding="utf-8"))
    nodes = [
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name in {
            "_apply_agent_plugin_runtime_overlays", "_preflight_m365_plugin_manifests",
        }
    ]
    namespace = {
        **vars(m365), **vars(legacy),
        "SIMPLECHAT_PLUGIN_TYPE": "simplechat", "CHART_PLUGIN_TYPE": "chart",
        "BLOB_STORAGE_PLUGIN_TYPE": "blob_storage",
        "m365_execution": execution,
        "copy_action_manifest": copy_action_manifest,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "semantic_kernel_loader.py", "exec"), namespace)
    original = manifest("m365_calendar", "calendar")
    original["additionalFields"]["m365_capabilities"] = {"get_my_events": False, "get_my_timezone": True}
    original["m365_capabilities"] = {"get_my_events": True}
    result = namespace["_apply_agent_plugin_runtime_overlays"](
        [original],
        {"action_capabilities": {"calendar": {"get_my_events": True, "send_mail": True, "get_my_timezone": False}}},
    )
    assert result[0]["enabled_functions"] == []
    assert original["additionalFields"]["m365_capabilities"]["get_my_events"] is False

    old = manifest("msgraph", "old")
    old["additionalFields"]["msgraph_capabilities"] = {"send_mail": False}
    old["msgraph_capabilities"] = {"send_mail": True}
    result = namespace["_apply_agent_plugin_runtime_overlays"](
        [old], {"action_capabilities": {"old": {"send_mail": True}}},
    )
    assert "send_mail" not in result[0]["enabled_functions"]
