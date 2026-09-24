# group_identity_harness.py
"""Shared, isolated harness for the native group identity endpoint tests (M5A).

Version: 0.261.157
Implemented in: 0.261.139

Extracted verbatim from ``test_group_identity_apis.py`` so the API suite and the
per-route fixture shape parity test (``test_group_identity_fixture_parity.py``)
drive the same real backend. The real policy, access, projection, storage and
route modules run unchanged against an in-memory Cosmos stub that honours ETag
conditional writes and an in-memory Key Vault, with the real ``functions_keyvault``
staging helpers and the real group role/status logic. The group is always taken
from the path, so a stale active group can never redirect or widen a request.
Network access is prohibited.

Exports: the ``environment`` pytest fixture (function-scoped, monkeypatch-based),
the ``IdentityContainer`` etag-enforcing Cosmos stub, the role/status constants,
and the seed/build helpers the suites share.
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
