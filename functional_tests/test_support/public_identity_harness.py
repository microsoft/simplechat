# public_identity_harness.py
"""Shared, isolated harness for the native public identity endpoint tests (M10B).

Version: 0.261.179
Implemented in: 0.261.179

Mirrors ``group_identity_harness.py`` for public scope: the real public identity
policy, access, projection, storage and route modules run unchanged against an
in-memory Cosmos stub that honours ETag conditional writes and an in-memory Key
Vault, with the real ``functions_keyvault`` staging helpers and the real public
workspace role logic. The workspace is always taken from the path, so a stale
active workspace can never redirect or widen a request. Network access is
prohibited.

The scope differences from the group harness are: identity records partition on
``public_workspace_id`` rather than ``group_id``; role and status resolve from the
public workspace document (via the real ``get_user_role_in_public_workspace`` and
a harness ``assert_public_workspace_role`` that mirrors the production one); and a
public workspace has no Semantic Kernel actions, so the only reference that can
block a delete is a File Sync source and the availability predicate rests solely
on File Sync being enabled for the workspace.

Exports: the ``environment`` pytest fixture, the role/status constants, and the
seed/build helpers the API suite and the fixture-shape parity pin share.
"""

import importlib.util
import json
import socket
import sys
from copy import deepcopy
from functools import wraps
from types import SimpleNamespace
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


LIST_PATH = "/api/public-workspaces/public-a/identities"
PLACEHOLDER = "Stored_In_KeyVault"


class CosmosAccessConditionFailedError(CosmosHttpResponseError):
    """The in-memory analogue of the Cosmos 412 precondition failure."""

    def __init__(self):
        super().__init__(412)


class IdentityContainer:
    """An in-memory Cosmos stub for a single scope that enforces ETags.

    Public identity records partition on ``public_workspace_id``; the container
    keys on that field so a read, list, replace or delete lands on the same
    workspace the write named.
    """

    def __init__(self, partition_field="public_workspace_id"):
        self.records = {}
        self._sequence = 0
        self.before_replace = None
        self.calls = []
        self._partition_field = partition_field

    def _next_etag(self):
        self._sequence += 1
        return f'"etag-{self._sequence}"'

    def create_item(self, body):
        doc = deepcopy(body)
        doc["_etag"] = self._next_etag()
        key = (doc[self._partition_field], doc["id"])
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
            rows = [record for record in rows if record.get(self._partition_field) == scope_id]
        rows.sort(key=lambda record: str(record.get("name") or ""))
        return rows

    def replace_item(self, item, body, etag=None, match_condition=None):
        assert match_condition is MatchConditions.IfNotModified
        key = (body.get(self._partition_field), item)
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


class WorkspaceContainer:
    """A minimal public workspaces container: point reads only, by workspace id."""

    def __init__(self, workspaces):
        self.records = workspaces

    def read_item(self, item, partition_key):
        if item not in self.records:
            raise CosmosResourceNotFoundError()
        return deepcopy(self.records[item])


def workspace(workspace_id, status="active"):
    """A public workspace document with the three managing roles seeded."""
    return {
        "id": workspace_id,
        "name": f"Public {workspace_id}",
        "status": status,
        "owner": {"userId": "owner"},
        "admins": ["admin"],
        "documentManagers": [{"userId": "manager"}],
    }


@pytest.fixture
def environment(monkeypatch):
    settings = {
        "enable_public_workspaces": True,
        "enable_key_vault_secret_storage": False,
        "key_vault_name": "test-only-vault",
        "key_vault_identity": "",
    }
    state = SimpleNamespace(
        file_sync_enabled=True,
        file_sync_sources=[],
        vault={},
        secret_writes=[],
        secret_deletes=[],
    )

    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in public identity tests."))
        scoped.setattr(socket, "create_connection", network)
        scoped.setattr(socket.socket, "connect", network)

        workspaces = {
            "public-a": workspace("public-a"),
            "public-b": workspace("public-b"),
            "locked-ws": workspace("locked-ws", status="locked"),
            "upload-disabled-ws": workspace("upload-disabled-ws", status="upload_disabled"),
            "inactive-ws": workspace("inactive-ws", status="inactive"),
            "haunted-ws": workspace("haunted-ws", status="haunted"),
        }

        workspace_container = WorkspaceContainer(workspaces)
        public_container = IdentityContainer()

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
        config.cosmos_public_workspace_identities_container = public_container
        config.cosmos_personal_workspace_identities_container = IdentityContainer(partition_field="user_id")
        config.cosmos_group_workspace_identities_container = IdentityContainer(partition_field="group_id")
        config.cosmos_global_workspace_identities_container = IdentityContainer(partition_field="scope_id")
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

        # --- public workspace membership seam (real role/lookup logic) ---
        public_ws_namespace = {
            "cosmos_public_workspaces_container": workspace_container,
            "exceptions": SimpleNamespace(CosmosResourceNotFoundError=CosmosResourceNotFoundError),
        }
        execute_functions("functions_public_workspaces.py", {
            "find_public_workspace_by_id", "get_user_role_in_public_workspace",
        }, public_ws_namespace)
        find_public_workspace_by_id = public_ws_namespace["find_public_workspace_by_id"]
        get_user_role_in_public_workspace = public_ws_namespace["get_user_role_in_public_workspace"]
        scoped.setitem(sys.modules, "functions_public_workspaces", module_stub(
            "functions_public_workspaces",
            find_public_workspace_by_id=find_public_workspace_by_id,
            get_user_role_in_public_workspace=get_user_role_in_public_workspace,
        ))

        # --- file sync seam ----------------------------------------------
        # ``assert_public_workspace_role`` mirrors the production helper in
        # functions_file_sync: resolve the workspace, resolve the role, and refuse
        # a caller whose role is outside the allowed set. File Sync availability
        # and the source list are the two other things the identity surface reads.
        FILE_SYNC_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")

        def assert_public_workspace_role(user_id, public_workspace_id, allowed_roles=FILE_SYNC_MANAGER_ROLES):
            workspace_doc = find_public_workspace_by_id(public_workspace_id)
            if not workspace_doc:
                raise LookupError("Public workspace not found")
            role = get_user_role_in_public_workspace(workspace_doc, user_id)
            allowed = {str(role_name).lower() for role_name in allowed_roles}
            if not role or role.lower() not in allowed:
                raise PermissionError("Insufficient permissions for this public workspace")
            return role

        scoped.setitem(sys.modules, "functions_file_sync", module_stub(
            "functions_file_sync",
            FILE_SYNC_MANAGER_ROLES=FILE_SYNC_MANAGER_ROLES,
            assert_public_workspace_role=assert_public_workspace_role,
            list_file_sync_sources=lambda scope_type, scope_id: list(state.file_sync_sources),
            is_file_sync_enabled_for_public_workspace=(
                lambda settings, workspace_id, user_info=None: state.file_sync_enabled
            ),
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
        load_real("functions_public_identity_policy")
        access = load_real("functions_public_identity_access")

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
            "PublicIdentityError": access.PublicIdentityError,
            "create_public_identity": access.create_public_identity,
            "delete_public_identity": access.delete_public_identity,
            "get_public_identity": access.get_public_identity,
            "public_identity_error_response": access.public_identity_error_response,
            "list_public_identities": access.list_public_identities,
            "update_public_identity": access.update_public_identity,
        }
        execute_functions("route_backend_public_identities_scoped.py", {
            "register_route_backend_public_identities_scoped", "_public_identity_boundary",
            "_current_user_info", "_reject_query_parameters", "_reject_request_body", "_read_json_body",
        }, route_namespace)

        app = Flask("public_identity_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_public_identities_scoped", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route_namespace["register_route_backend_public_identities_scoped"](blueprint)
        app.register_blueprint(blueprint)

        env = SimpleNamespace(
            settings=settings, state=state, workspaces=workspaces,
            workspace_container=workspace_container, public_container=public_container,
            access=access, keyvault=keyvault, identities=identities, reference_block=reference_block,
            app=app, client=app.test_client(),
        )
        as_user(env, "owner")
        yield env
        network.assert_not_called()


def as_user(env, user_id, roles=("User",)):
    with env.client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": list(roles)}


ROLE_USER = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "stranger"}
MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
NON_MANAGER_ROLES = ("User",)


def seed_identity(env, name="Shared SMB", workspace_id="public-a", credentials=None, provider="generic",
                  usage_contexts=None):
    """Create an identity straight through the storage layer for read/edit fixtures."""
    payload = {
        "name": name,
        "provider": provider,
        "credentials": credentials or {"auth_type": "username_password", "username": "svc", "password": "p@ss"},
    }
    if usage_contexts is not None:
        payload["usage_contexts"] = usage_contexts
    created = env.identities.create_workspace_identity("public", workspace_id, payload, "owner")
    return env.identities.get_workspace_identity("public", workspace_id, created["identity_id"])


def read_etag(env, identity_id, workspace_id="public-a"):
    stored = env.identities.get_workspace_identity("public", workspace_id, identity_id)
    return stored["_etag"]
