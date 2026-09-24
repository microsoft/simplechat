# test_group_identity_apis.py
"""
Functional tests for the immutable-target group identity APIs.
Version: 0.261.139
Implemented in: 0.261.139

The real policy, access, projection, storage and route modules run against the
real Key Vault helpers, executed unchanged over an in-memory Cosmos stub that
honours ETag conditional writes and an in-memory Key Vault. The group is always
taken from the path, so a stale active group can never redirect or widen a
request. Group identities are a manager-only surface for both reads and writes.
Network access is prohibited.
"""

import importlib.util
import json
import socket
import sys
import uuid
from copy import deepcopy
from functools import wraps
from types import SimpleNamespace
from typing import Iterable
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify, request, session

from test_support.agent_delegation import (
    APP_ROOT,
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
    MatchConditions,
    execute_functions,
    module_stub,
)
from test_support.versioning import assert_app_version_at_least


LIST_PATH = "/api/groups/group-a/identities"
PLACEHOLDER = "Stored_In_KeyVault"


class CosmosAccessConditionFailedError(CosmosHttpResponseError):
    """The in-memory analogue of the Cosmos 412 precondition failure."""

    def __init__(self):
        super().__init__(412)


class IdentityContainer:
    """An in-memory Cosmos stub for a single scope that enforces ETags.

    ``before_replace`` lands a concurrent write or delete between a conditional
    write's read and its replace/delete, exactly the race the immutable-target
    routes must survive without ever recreating a deleted record.
    """

    def __init__(self):
        self.records = {}
        self._sequence = 0
        self.before_replace = None
        self.calls = []

    def _next_etag(self):
        self._sequence += 1
        return f'"etag-{self._sequence}"'

    def create_item(self, body):
        doc = deepcopy(body)
        doc["_etag"] = self._next_etag()
        key = (doc["group_id"], doc["id"])
        if key in self.records:
            raise CosmosHttpResponseError(409)
        self.records[key] = doc
        self.calls.append(("create", doc["id"]))
        return deepcopy(doc)

    def read_item(self, item, partition_key):
        doc = self.records.get((partition_key, item))
        if doc is None:
            raise CosmosResourceNotFoundError()
        return deepcopy(doc)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        values = {parameter["name"]: parameter["value"] for parameter in (parameters or [])}
        rows = [
            deepcopy(record) for (partition, _), record in self.records.items()
            if partition_key is None or partition == partition_key
        ]
        scope_id = values.get("@scope_id")
        if scope_id is not None:
            rows = [record for record in rows if record.get("group_id") == scope_id]
        rows.sort(key=lambda record: str(record.get("name") or ""))
        return rows

    def replace_item(self, item, body, etag=None, match_condition=None):
        assert match_condition is MatchConditions.IfNotModified
        key = (body.get("group_id"), item)
        if self.before_replace:
            callback, self.before_replace = self.before_replace, None
            callback(self.records, key)
        current = self.records.get(key)
        if current is None:
            raise CosmosResourceNotFoundError()
        if etag is not None and current.get("_etag") != etag:
            raise CosmosAccessConditionFailedError()
        doc = deepcopy(body)
        doc["_etag"] = self._next_etag()
        self.records[key] = doc
        self.calls.append(("replace", item))
        return deepcopy(doc)

    def delete_item(self, item, partition_key, etag=None, match_condition=None):
        assert match_condition is MatchConditions.IfNotModified
        key = (partition_key, item)
        if self.before_replace:
            callback, self.before_replace = self.before_replace, None
            callback(self.records, key)
        current = self.records.get(key)
        if current is None:
            raise CosmosResourceNotFoundError()
        if etag is not None and current.get("_etag") != etag:
            raise CosmosAccessConditionFailedError()
        del self.records[key]
        self.calls.append(("delete", item))


def group(group_id, status="active"):
    return {
        "id": group_id,
        "name": f"Group {group_id}",
        "status": status,
        "owner": {"id": "owner"},
        "admins": ["admin"],
        "documentManagers": ["manager"],
        "users": [{"userId": "member"}],
    }


@pytest.fixture
def environment(monkeypatch):
    settings = {
        "enable_group_workspaces": True,
        "enable_semantic_kernel": True,
        "enable_key_vault_secret_storage": False,
        "key_vault_name": "test-only-vault",
        "key_vault_identity": "",
    }
    state = SimpleNamespace(
        file_sync_enabled=True,
        file_sync_sources=[],
        group_actions=[],
        vault={},
        secret_writes=[],
        secret_deletes=[],
    )

    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in group identity tests."))
        scoped.setattr(socket, "create_connection", network)
        scoped.setattr(socket.socket, "connect", network)

        groups = {
            "group-a": group("group-a"),
            "group-b": group("group-b"),
            "locked-grp": group("locked-grp", status="locked"),
            "upload-disabled-grp": group("upload-disabled-grp", status="upload_disabled"),
            "inactive-grp": group("inactive-grp", status="inactive"),
            "haunted-grp": group("haunted-grp", status="haunted"),
        }

        group_container = IdentityContainer()

        # --- fake Key Vault client --------------------------------------
        class SecretClient:
            def __init__(self, **kwargs):
                pass

            def set_secret(self, name, value):
                state.secret_writes.append((name, value))
                state.vault[name] = value
                return SimpleNamespace(value=value, id=f"https://kv/secrets/{name}/v")

            def get_secret(self, name, version=None):
                return SimpleNamespace(value=state.vault[name], id=f"https://kv/secrets/{name}/v")

            def begin_delete_secret(self, name):
                state.secret_deletes.append(name)
                state.vault.pop(name, None)

        # --- config seam -------------------------------------------------
        config = module_stub("config")
        config.cosmos_group_workspace_identities_container = group_container
        config.cosmos_personal_workspace_identities_container = IdentityContainer()
        config.cosmos_public_workspace_identities_container = IdentityContainer()
        config.cosmos_global_workspace_identities_container = IdentityContainer()
        config.KEY_VAULT_DOMAIN = ".vault.azure.net"
        config.SECRET_KEY = "test-only-not-a-production-credential"
        scoped.setitem(sys.modules, "config", config)

        # --- appinsights seam --------------------------------------------
        scoped.setitem(sys.modules, "functions_appinsights", module_stub(
            "functions_appinsights", log_event=Mock(),
        ))

        # --- settings seam (real enabled_required) -----------------------
        settings_namespace = {"wraps": wraps, "get_settings": lambda: settings, "jsonify": jsonify}
        execute_functions("functions_settings.py", {"enabled_required"}, settings_namespace)
        scoped.setitem(sys.modules, "functions_settings", module_stub(
            "functions_settings",
            get_settings=lambda: settings,
            enabled_required=settings_namespace["enabled_required"],
            sanitize_settings_for_user=lambda data: data,
        ))

        # --- Key Vault dependency seams (real functions_keyvault) --------
        class KeyVaultSecretStorageError(Exception):
            def __init__(self, error):
                super().__init__(str(error))

        scoped.setitem(sys.modules, "functions_keyvault_errors", module_stub(
            "functions_keyvault_errors", KeyVaultSecretStorageError=KeyVaultSecretStorageError,
        ))
        scoped.setitem(sys.modules, "functions_mcp_operations", module_stub(
            "functions_mcp_operations", MCP_CUSTOM_HEADERS_FIELD="customHeaders", MCP_PLUGIN_TYPE="mcp",
        ))
        scoped.setitem(sys.modules, "functions_snowflake_operations", module_stub(
            "functions_snowflake_operations",
            SNOWFLAKE_PLUGIN_TYPE="snowflake", SNOWFLAKE_SENSITIVE_ADDITIONAL_FIELDS=set(),
        ))
        scoped.setitem(sys.modules, "functions_yamcs_operations", module_stub(
            "functions_yamcs_operations",
            YAMCS_PLUGIN_TYPE="yamcs", YAMCS_SENSITIVE_ADDITIONAL_FIELDS=set(),
        ))
        scoped.setitem(sys.modules, "app_settings_cache", module_stub(
            "app_settings_cache", get_settings_cache=lambda: deepcopy(settings),
        ))

        # --- azure seams -------------------------------------------------
        azure = module_stub("azure")
        azure_identity = module_stub("azure.identity", DefaultAzureCredential=Mock())
        azure_keyvault = module_stub("azure.keyvault")
        azure_keyvault_secrets = module_stub("azure.keyvault.secrets", SecretClient=SecretClient)
        azure_core = module_stub("azure.core", MatchConditions=MatchConditions)
        azure_cosmos = module_stub("azure.cosmos")
        azure_exceptions = module_stub(
            "azure.cosmos.exceptions",
            CosmosHttpResponseError=CosmosHttpResponseError,
            CosmosResourceNotFoundError=CosmosResourceNotFoundError,
            CosmosAccessConditionFailedError=CosmosAccessConditionFailedError,
        )
        azure.core, azure.cosmos, azure.identity, azure.keyvault = (
            azure_core, azure_cosmos, azure_identity, azure_keyvault,
        )
        azure_cosmos.exceptions = azure_exceptions
        azure_keyvault.secrets = azure_keyvault_secrets
        for name, module in {
            "azure": azure, "azure.core": azure_core, "azure.cosmos": azure_cosmos,
            "azure.cosmos.exceptions": azure_exceptions, "azure.identity": azure_identity,
            "azure.keyvault": azure_keyvault, "azure.keyvault.secrets": azure_keyvault_secrets,
        }.items():
            scoped.setitem(sys.modules, name, module)

        # --- group membership seam (real role/status logic) --------------
        group_namespace = {
            "Iterable": Iterable,
            "find_group_by_id": lambda group_id: deepcopy(groups.get(group_id)),
        }
        execute_functions("functions_group.py", {
            "get_user_role_in_group", "assert_group_role", "check_group_status_allows_operation",
        }, group_namespace)
        scoped.setitem(sys.modules, "functions_group", module_stub(
            "functions_group",
            find_group_by_id=group_namespace["find_group_by_id"],
            get_user_role_in_group=group_namespace["get_user_role_in_group"],
            assert_group_role=group_namespace["assert_group_role"],
            check_group_status_allows_operation=group_namespace["check_group_status_allows_operation"],
        ))

        # --- file sync and group action seams ----------------------------
        scoped.setitem(sys.modules, "functions_file_sync", module_stub(
            "functions_file_sync",
            list_file_sync_sources=lambda scope_type, scope_id: list(state.file_sync_sources),
            is_file_sync_enabled_for_group=lambda settings, group_id, user_info=None: state.file_sync_enabled,
        ))
        scoped.setitem(sys.modules, "functions_group_actions", module_stub(
            "functions_group_actions", get_group_actions=lambda group_id: list(state.group_actions),
        ))

        # --- authentication seam (real decorators) -----------------------
        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "debug_print": Mock(), "check_user_access_status": Mock(return_value=(True, None)),
        }
        execute_functions("functions_authentication.py", {
            "login_required", "user_required", "get_current_user_id", "get_current_user_info",
            "apply_blueprint_auth", "user_required_blueprint",
        }, auth_namespace)
        auth = module_stub("functions_authentication", **auth_namespace)
        scoped.setitem(sys.modules, "functions_authentication", auth)

        scoped.setitem(sys.modules, "swagger_wrapper", module_stub(
            "swagger_wrapper",
            swagger_route=lambda **_kwargs: (lambda function: function),
            get_auth_security=lambda: [{"sessionAuth": []}],
        ))

        def load_real(name):
            spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            scoped.setitem(sys.modules, name, module)
            spec.loader.exec_module(module)
            return module

        keyvault = load_real("functions_keyvault")
        identities = load_real("functions_workspace_identities")
        load_real("functions_group_identity_policy")
        access = load_real("functions_group_identity_access")

        # Spy on the audit-parity call without changing its behaviour.
        reference_block = Mock()
        access.log_workspace_identity_reference_block = reference_block

        # --- route module executed without importing the app -------------
        route_namespace = {
            "json": json, "wraps": wraps, "jsonify": jsonify, "request": request, "session": session,
            "get_current_user_id": auth.get_current_user_id,
            "get_current_user_info": auth.get_current_user_info,
            "login_required": auth.login_required, "user_required": auth.user_required,
            "enabled_required": settings_namespace["enabled_required"],
            "swagger_route": lambda **_kwargs: (lambda function: function),
            "get_auth_security": lambda: [{"sessionAuth": []}],
            "GroupIdentityError": access.GroupIdentityError,
            "create_group_identity": access.create_group_identity,
            "delete_group_identity": access.delete_group_identity,
            "get_group_identity": access.get_group_identity,
            "group_identity_error_response": access.group_identity_error_response,
            "list_group_identities": access.list_group_identities,
            "update_group_identity": access.update_group_identity,
        }
        execute_functions("route_backend_group_identities_scoped.py", {
            "register_route_backend_group_identities_scoped", "_group_identity_boundary",
            "_current_user_info", "_reject_query_parameters", "_reject_request_body", "_read_json_body",
        }, route_namespace)

        app = Flask("group_identity_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_group_identities_scoped", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route_namespace["register_route_backend_group_identities_scoped"](blueprint)
        app.register_blueprint(blueprint)

        env = SimpleNamespace(
            settings=settings, state=state, groups=groups, group_container=group_container,
            access=access, keyvault=keyvault, identities=identities, reference_block=reference_block,
            app=app, client=app.test_client(),
        )
        as_user(env, "owner")
        yield env
        network.assert_not_called()


def as_user(env, user_id, roles=("User",)):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": list(roles)}


ROLE_USER = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "member"}
MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
NON_MANAGER_ROLES = ("User",)


def seed_identity(env, name="Shared SMB", group_id="group-a", credentials=None, provider="generic",
                  usage_contexts=None):
    """Create an identity straight through the storage layer for read/edit fixtures."""
    payload = {
        "name": name,
        "provider": provider,
        "credentials": credentials or {"auth_type": "username_password", "username": "svc", "password": "p@ss"},
    }
    if usage_contexts is not None:
        payload["usage_contexts"] = usage_contexts
    created = env.identities.create_workspace_identity("group", group_id, payload, "owner")
    return env.identities.get_workspace_identity("group", group_id, created["identity_id"])


def read_etag(env, identity_id, group_id="group-a"):
    stored = env.identities.get_workspace_identity("group", group_id, identity_id)
    return stored["_etag"]


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.139")


# --------------------------------------------------------------------------
# Reads: role, status, availability
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", MANAGER_ROLES)
def test_manager_roles_can_list_and_read(environment, role):
    identity = seed_identity(environment)
    as_user(environment, ROLE_USER[role])
    listing = environment.client.get(LIST_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert [item["id"] for item in body["identities"]] == [identity["id"]]
    single = environment.client.get(f"{LIST_PATH}/{identity['id']}")
    assert single.status_code == 200
    assert single.get_json()["identity"]["id"] == identity["id"]


@pytest.mark.parametrize("role", NON_MANAGER_ROLES)
def test_non_manager_roles_cannot_read(environment, role):
    seed_identity(environment)
    as_user(environment, ROLE_USER[role])
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/whatever").status_code == 403


def test_non_member_is_forbidden(environment):
    seed_identity(environment)
    as_user(environment, "stranger")
    assert environment.client.get(LIST_PATH).status_code == 403


def test_unknown_group_is_404(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/no-such-group/identities").status_code == 404


def test_list_envelope_and_single_resource_shape(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"identities", "identity_management"}
    assert body["identity_management"] == {
        "schema_version": 1, "operations": ["create", "edit", "delete"],
    }
    item = body["identities"][0]
    assert item["id"] == identity["id"] and item["group_id"] == "group-a"
    assert item["etag"] and item["identity_actions"] == ["edit", "delete"]
    assert "auth" not in item and "_etag" not in item and "_rid" not in item
    assert "credentials" in item
    single = environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json()
    assert set(single) == {"identity"}
    assert single["identity"]["id"] == identity["id"]


@pytest.mark.parametrize("group_id,status,readable", [
    ("group-a", "active", True),
    ("locked-grp", "locked", True),
    ("upload-disabled-grp", "upload_disabled", True),
    ("inactive-grp", "inactive", False),
    ("haunted-grp", "haunted", False),
])
def test_read_status_matrix(environment, group_id, status, readable):
    seed_identity(environment, group_id=group_id)
    as_user(environment, "owner")
    response = environment.client.get(f"/api/groups/{group_id}/identities")
    assert response.status_code == (200 if readable else 403)


def test_surface_unavailable_when_semantic_kernel_and_file_sync_off(environment):
    environment.settings["enable_semantic_kernel"] = False
    environment.state.file_sync_enabled = False
    as_user(environment, "owner")
    response = environment.client.get(LIST_PATH)
    assert response.status_code == 403
    assert "File Sync or Semantic Kernel" in response.get_json()["error"]


def test_surface_available_via_file_sync_when_semantic_kernel_off(environment):
    environment.settings["enable_semantic_kernel"] = False
    environment.state.file_sync_enabled = True
    seed_identity(environment)
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 200


# --------------------------------------------------------------------------
# Writes: role and status
# --------------------------------------------------------------------------

def _create_body(name="New identity"):
    return {
        "name": name,
        "provider": "generic",
        "credentials": {"auth_type": "username_password", "username": "svc", "password": "p@ss"},
    }


@pytest.mark.parametrize("role", NON_MANAGER_ROLES)
def test_non_manager_cannot_create(environment, role):
    as_user(environment, ROLE_USER[role])
    assert environment.client.post(LIST_PATH, json=_create_body()).status_code == 403


def test_create_returns_201_with_etag_and_actions(environment):
    as_user(environment, "owner")
    response = environment.client.post(LIST_PATH, json=_create_body())
    assert response.status_code == 201
    identity = response.get_json()["identity"]
    assert identity["name"] == "New identity"
    assert identity["etag"] and identity["identity_actions"] == ["edit", "delete"]
    assert "auth" not in identity


@pytest.mark.parametrize("group_id", ["locked-grp", "upload-disabled-grp"])
def test_writes_refused_on_readable_but_non_active_status(environment, group_id):
    as_user(environment, "owner")
    response = environment.client.post(f"/api/groups/{group_id}/identities", json=_create_body())
    assert response.status_code == 403


# --------------------------------------------------------------------------
# Conditional writes
# --------------------------------------------------------------------------

def test_update_requires_expected_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed"})
    assert response.status_code == 400


def test_update_succeeds_with_current_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": etag},
    )
    assert response.status_code == 200
    assert response.get_json()["identity"]["name"] == "Renamed"


def test_update_stale_etag_conflicts_without_writing(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    writes_before = list(environment.group_container.calls)
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": '"stale"'},
    )
    assert response.status_code == 409
    assert environment.group_container.calls == writes_before


def test_update_race_with_delete_is_404_and_never_recreates(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])

    def land_delete(records, key):
        records.pop(key, None)

    environment.group_container.before_replace = land_delete
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": etag},
    )
    assert response.status_code == 404
    assert (("group-a", identity["id"])) not in environment.group_container.records


def test_update_race_with_concurrent_edit_is_409(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])

    def land_edit(records, key):
        records[key]["_etag"] = '"moved-on"'

    environment.group_container.before_replace = land_edit
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}", json={"name": "Renamed", "expected_etag": etag},
    )
    assert response.status_code == 409


def test_delete_requires_expected_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    assert environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={}).status_code == 400


def test_delete_stale_etag_conflicts(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{identity['id']}", json={"expected_etag": '"stale"'},
    )
    assert response.status_code == 409
    assert ("group-a", identity["id"]) in environment.group_container.records


def test_delete_succeeds_with_current_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 200
    assert ("group-a", identity["id"]) not in environment.group_container.records


# --------------------------------------------------------------------------
# Strict request handling
# --------------------------------------------------------------------------

def test_query_parameters_are_rejected(environment):
    seed_identity(environment)
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}?page=2").status_code == 400


def test_unknown_top_level_field_is_rejected(environment):
    as_user(environment, "owner")
    body = _create_body()
    body["auth"] = {"auth_type": "api_key", "secret": "smuggled"}
    assert environment.client.post(LIST_PATH, json=body).status_code == 400


def test_duplicate_json_keys_are_rejected(environment):
    as_user(environment, "owner")
    raw = '{"name": "a", "name": "b"}'
    response = environment.client.post(LIST_PATH, data=raw, content_type="application/json")
    assert response.status_code == 400


def test_read_does_not_accept_a_body(environment):
    seed_identity(environment)
    as_user(environment, "owner")
    response = environment.client.get(LIST_PATH, data=b"{}", content_type="application/json")
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Exact response and request shapes (addendum §10)
# --------------------------------------------------------------------------

_STRICT_WRITE_FIELDS = {
    "name", "description", "provider", "source_type",
    "usage_contexts", "supported_source_types", "metadata", "credentials",
}


def test_every_strict_write_field_is_accepted(environment):
    as_user(environment, "owner")
    body = {
        "name": "Full", "description": "d", "provider": "generic", "source_type": "generic",
        "usage_contexts": ["action"], "supported_source_types": ["generic"], "metadata": {"k": "v"},
        "credentials": {"auth_type": "username_password", "username": "svc", "password": "p@ss"},
    }
    assert set(body) == _STRICT_WRITE_FIELDS
    assert environment.client.post(LIST_PATH, json=body).status_code == 201


@pytest.mark.parametrize("field", ["auth", "auth_type", "scope_id", "group_id", "id", "etag"])
def test_forbidden_top_level_write_fields_are_rejected(environment, field):
    as_user(environment, "owner")
    body = _create_body()
    body[field] = {"auth_type": "api_key"} if field == "auth" else "x"
    assert environment.client.post(LIST_PATH, json=body).status_code == 400


def test_patch_rejects_auth_alias(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    body = {"name": "Renamed", "auth": {"auth_type": "api_key"}, "expected_etag": etag}
    assert environment.client.patch(f"{LIST_PATH}/{identity['id']}", json=body).status_code == 400


def test_delete_body_must_be_exactly_expected_etag(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(
        f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag, "force": True},
    )
    assert response.status_code == 400
    assert ("group-a", identity["id"]) in environment.group_container.records


def test_response_row_carries_the_native_additions_without_leaks(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    for row in (
        environment.client.get(LIST_PATH).get_json()["identities"][0],
        environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json()["identity"],
    ):
        assert isinstance(row["etag"], str) and row["etag"]
        assert set(row["identity_actions"]) <= {"edit", "delete"}
        assert row["usage_contexts"] == ["action"]
        assert "auth" not in row and "auth_type" not in row
        assert "scope_id" not in row and "_etag" not in row


# --------------------------------------------------------------------------
# Placeholder round trip and secret handling (Key Vault off)
# --------------------------------------------------------------------------

def test_placeholder_keeps_the_stored_secret(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    etag = read_etag(environment, identity["id"])
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}",
        json={
            "name": "Renamed",
            "credentials": {"auth_type": "username_password", "username": "svc", "password": PLACEHOLDER},
            "expected_etag": etag,
        },
    )
    assert response.status_code == 200
    credentials = response.get_json()["identity"]["credentials"]
    assert credentials["password_stored"] is True and credentials["password"] == PLACEHOLDER
    stored = environment.identities.get_workspace_identity("group", "group-a", identity["id"])
    assert stored["auth"].get("password") == "p@ss"


def test_storage_off_response_never_returns_the_inline_value(environment):
    as_user(environment, "owner")
    body = environment.client.post(LIST_PATH, json=_create_body()).get_json()
    dumped = json.dumps(body)
    assert "p@ss" not in dumped
    assert "auth" not in body["identity"]
    assert body["identity"]["credentials"]["password"] == PLACEHOLDER


# --------------------------------------------------------------------------
# Key Vault positive controls (storage enabled)
# --------------------------------------------------------------------------

def _enable_key_vault(env):
    env.settings["enable_key_vault_secret_storage"] = True
    env.settings["key_vault_name"] = "test-only-vault"


def test_create_stores_secret_under_the_exact_full_name(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    expected = f"group-a--identity--group--workspace-identity-{identity['id']}-password"
    assert (expected, "p@ss") in environment.state.secret_writes
    stored = environment.identities.get_workspace_identity("group", "group-a", identity["id"])
    assert stored["auth"].get("password_secret_name") == expected
    assert "p@ss" not in json.dumps(environment.client.get(f"{LIST_PATH}/{identity['id']}").get_json())


def test_auth_type_change_removes_the_superseded_secret(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    password_name = f"group-a--identity--group--workspace-identity-{identity['id']}-password"
    assert password_name in environment.state.vault

    etag = read_etag(environment, identity["id"])
    response = environment.client.patch(
        f"{LIST_PATH}/{identity['id']}",
        json={
            "credentials": {"auth_type": "connection_string", "connection_string": "Server=x;"},
            "expected_etag": etag,
        },
    )
    assert response.status_code == 200
    assert password_name in environment.state.secret_deletes
    assert password_name not in environment.state.vault
    secret_name = f"group-a--identity--group--workspace-identity-{identity['id']}-secret"
    assert secret_name in environment.state.vault


def test_delete_removes_the_identity_secrets(environment):
    _enable_key_vault(environment)
    as_user(environment, "owner")
    identity = environment.client.post(LIST_PATH, json=_create_body()).get_json()["identity"]
    password_name = f"group-a--identity--group--workspace-identity-{identity['id']}-password"
    assert password_name in environment.state.vault

    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 200
    assert password_name in environment.state.secret_deletes
    assert password_name not in environment.state.vault


# --------------------------------------------------------------------------
# Delete while in use
# --------------------------------------------------------------------------

def test_delete_refused_when_a_file_source_references_the_identity(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    environment.state.file_sync_sources = [
        {"id": "src-1", "name": "Nightly sync", "identity_id": identity["id"]},
        {"id": "src-2", "name": "Other", "identity_id": "someone-else"},
    ]
    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 409
    body = response.get_json()
    assert body["error_code"] == "identity_in_use"
    assert body["references"] == [{"kind": "file_source", "id": "src-1", "name": "Nightly sync"}]
    assert ("group-a", identity["id"]) in environment.group_container.records
    environment.reference_block.assert_called_once()


def test_delete_refused_when_an_action_references_the_identity(environment):
    identity = seed_identity(environment)
    as_user(environment, "owner")
    environment.state.group_actions = [
        {"id": "act-1", "displayName": "SQL report", "identity_id": identity["id"]},
    ]
    etag = read_etag(environment, identity["id"])
    response = environment.client.delete(f"{LIST_PATH}/{identity['id']}", json={"expected_etag": etag})
    assert response.status_code == 409
    body = response.get_json()
    assert body["error_code"] == "identity_in_use"
    assert body["references"] == [{"kind": "action", "id": "act-1", "name": "SQL report"}]
    assert ("group-a", identity["id"]) in environment.group_container.records


# --------------------------------------------------------------------------
# identity_actions seam
# --------------------------------------------------------------------------

def test_identity_actions_are_empty_on_a_read_only_group(environment):
    identity = seed_identity(environment, group_id="locked-grp")
    as_user(environment, "owner")
    single = environment.client.get(f"/api/groups/locked-grp/identities/{identity['id']}").get_json()
    assert single["identity"]["identity_actions"] == []


# --------------------------------------------------------------------------
# Normalized usage_contexts in every response (addendum §9)
# --------------------------------------------------------------------------

_MISSING = object()


def seed_raw(env, identity_id, usage_contexts, group_id="group-a"):
    """Insert a stored record directly, bypassing write-time normalization, so a
    response can be checked against an older or aliased ``usage_contexts`` shape."""
    record = {
        "id": identity_id, "identity_id": identity_id, "type": "workspace_identity",
        "scope_type": "group", "group_id": group_id,
        "name": f"Identity {identity_id}", "provider": "generic", "source_type": "generic",
        "supported_source_types": ["action"], "metadata": {},
        "auth": {"auth_type": "api_key", "secret_secret_name": "x"},
    }
    if usage_contexts is not _MISSING:
        record["usage_contexts"] = usage_contexts
    env.group_container.create_item(record)
    return record


@pytest.mark.parametrize("stored_usage,expected", [
    (_MISSING, ["action"]),
    (["agent"], ["action"]),
    (["plugin"], ["action"]),
    (["general"], ["action"]),
    (["file_sync"], ["file_sync"]),
    (["file_sync", "action"], ["file_sync", "action"]),
])
def test_response_usage_contexts_are_normalized_like_supports_usage(environment, stored_usage, expected):
    seed_raw(environment, "raw-1", stored_usage)
    as_user(environment, "owner")
    single = environment.client.get(f"{LIST_PATH}/raw-1").get_json()["identity"]
    assert single["usage_contexts"] == expected
    listed = environment.client.get(LIST_PATH).get_json()["identities"][0]
    assert listed["usage_contexts"] == expected
    # The equivalence the frontend action filter relies on.
    stored = environment.identities.get_workspace_identity("group", "group-a", "raw-1")
    supports_action = environment.identities.identity_supports_usage(stored, "action")
    assert ("action" in single["usage_contexts"]) == supports_action


def test_projection_and_supports_usage_share_one_normalizer():
    access_source = (APP_ROOT / "functions_group_identity_access.py").read_text(encoding="utf-8")
    identities_source = (APP_ROOT / "functions_workspace_identities.py").read_text(encoding="utf-8")
    assert "normalize_identity_usage_contexts" in access_source
    # identity_supports_usage must delegate to the shared helper, not re-inline it.
    gate = identities_source.split("def identity_supports_usage", 1)[1].split("\ndef ", 1)[0]
    assert "normalize_identity_usage_contexts(identity)" in gate


# --------------------------------------------------------------------------
# One availability predicate, shared by the context and the routes
# --------------------------------------------------------------------------

def test_context_and_access_share_the_availability_predicate():
    context_source = (APP_ROOT / "functions_workspace_context.py").read_text(encoding="utf-8")
    access_source = (APP_ROOT / "functions_group_identity_access.py").read_text(encoding="utf-8")
    assert "group_identities_available" in context_source
    assert "group_identities_available" in access_source


def test_availability_predicate_behaviour():
    spec = importlib.util.spec_from_file_location(
        "_identity_policy_probe", APP_ROOT / "functions_group_identity_policy.py",
    )
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)

    assert policy.group_identities_available({"enable_semantic_kernel": True}, "group-a") == (True, None)
    assert policy.group_identities_available(
        {"enable_semantic_kernel": False}, "group-a", file_sync_enabled=True,
    ) == (True, None)
    available, reason = policy.group_identities_available(
        {"enable_semantic_kernel": False}, "group-a", file_sync_enabled=False,
    )
    assert available is False and "File Sync or Semantic Kernel" in reason


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
