# public_file_source_harness.py
"""Shared, isolated harness for the native public file source endpoint tests (M10B).

Version: 0.261.182
Implemented in: 0.261.182

Mirrors ``group_file_source_harness.py`` for public scope: the real public file
source policy, access, projection, service and route modules run unchanged against
an in-memory Cosmos stub that honours ETag conditional writes and an in-memory Key
Vault, with the real ``functions_keyvault`` staging helpers and the real public
workspace role logic. The workspace is always taken from the path, so a stale
active workspace can never redirect or widen a request. Network access is
prohibited.

The scope differences from the group harness are: file sync records partition on
``public_workspace_id`` rather than ``group_id``; role and status resolve from the
public workspace document (via the real ``get_user_role_in_public_workspace`` and
the production ``assert_public_workspace_role`` in ``functions_file_sync``); and a
delete of a source with associated files routes through the public document
deletion path.

Exports: the ``environment`` pytest fixture (function-scoped, monkeypatch-based),
the ``FileSyncContainer`` etag-enforcing Cosmos stub, the role/status constants,
and the seed/build helpers the suites share.
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


LIST_PATH = "/api/public-workspaces/public-a/file-sources"
OPTIONS_PATH = "/api/public-workspaces/public-a/file-source-options"
PLACEHOLDER = "Stored_In_KeyVault"
UNC_PATH = "\\\\files\\contracts\\team"


class CosmosResourceExistsError(CosmosHttpResponseError):
    def __init__(self):
        super().__init__(409)


class CosmosAccessConditionFailedError(CosmosHttpResponseError):
    """The in-memory analogue of the Cosmos 412 precondition failure."""

    def __init__(self):
        super().__init__(412)


class FileSyncContainer:
    """An in-memory Cosmos stub that enforces ETag preconditions.

    ``replace_item`` and the conditional ``delete_item`` refuse a stale etag with
    412 and a missing record with 404; neither ever recreates. ``before_replace``
    and ``before_delete`` land a concurrent write between a guarded writer's read
    and its write, exactly the race the immutable-target routes must survive.
    ``query_items`` answers the ``COUNT`` used by the active-run checks and returns
    plain rows otherwise.
    """

    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.records = {}
        self.calls = []
        self.before_replace = []
        self.before_delete = []
        self.fail_create = False
        self._sequence = 0

    def _store(self, body):
        self._sequence += 1
        stored = deepcopy(dict(body))
        stored["_etag"] = f'"etag-{self._sequence}"'
        self.records[(stored[self.partition_field], stored["id"])] = stored
        return deepcopy(stored)

    def seed(self, body):
        return self._store(body)

    def get(self, partition_key, item_id):
        record = self.records.get((partition_key, item_id))
        return deepcopy(record) if record is not None else None

    def create_item(self, body, **kwargs):
        self.calls.append(("create_item", body["id"]))
        if self.fail_create:
            raise CosmosHttpResponseError(500, "create refused for test")
        if (body[self.partition_field], body["id"]) in self.records:
            raise CosmosResourceExistsError()
        return self._store(body)

    def read_item(self, item, partition_key, **kwargs):
        self.calls.append(("read_item", item))
        record = self.records.get((partition_key, item))
        if record is None:
            raise CosmosResourceNotFoundError()
        return deepcopy(record)

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        item_id = item if isinstance(item, str) else item["id"]
        self.calls.append(("replace_item", item_id))
        if self.before_replace:
            self.before_replace.pop(0)()
        key = (body[self.partition_field], item_id)
        record = self.records.get(key)
        if record is None:
            raise CosmosResourceNotFoundError()
        if match_condition == MatchConditions.IfNotModified and etag != record["_etag"]:
            raise CosmosAccessConditionFailedError()
        return self._store(body)

    def upsert_item(self, body, **kwargs):
        self.calls.append(("upsert_item", body["id"]))
        return self._store(body)

    def delete_item(self, item, partition_key, etag=None, match_condition=None, **kwargs):
        self.calls.append(("delete_item", item))
        if self.before_delete:
            self.before_delete.pop(0)()
        key = (partition_key, item)
        record = self.records.get(key)
        if record is None:
            raise CosmosResourceNotFoundError()
        if match_condition == MatchConditions.IfNotModified and etag != record["_etag"]:
            raise CosmosAccessConditionFailedError()
        del self.records[key]

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        self.calls.append(("query_items", partition_key))
        rows = [
            deepcopy(record)
            for (record_partition, _), record in self.records.items()
            if partition_key is None or record_partition == partition_key
        ]
        if "COUNT(1)" in query:
            if "status IN" in query:
                rows = [row for row in rows if row.get("status") in ("queued", "running")]
            return [len(rows)]
        return rows


class WorkspaceContainer:
    """A minimal public workspaces container: point reads only, by workspace id."""

    def __init__(self, workspaces):
        self.records = workspaces

    def read_item(self, item, partition_key, **kwargs):
        if item not in self.records:
            raise CosmosResourceNotFoundError()
        return deepcopy(self.records[item])


def public_workspace(workspace_id, status="active"):
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
        "enable_file_sync": True,
        "enable_file_sync_group": True,
        "enable_file_sync_personal": True,
        "enable_file_sync_public": True,
        "enable_redis_cache": True,
        "redis_url": "redis.invalid",
        "redis_auth_type": "managed_identity",
        "file_sync_public_admin_only": False,
        "require_public_workspace_assignment_for_file_sync": False,
        "file_sync_allowed_public_workspace_ids": [],
        "file_sync_visible_source_types": ["smb", "azure_files", "azure_blob", "sharepoint_on_prem", "google_workspace"],
        "file_sync_max_sources_per_scope": 10,
        "enable_key_vault_secret_storage": True,
        "key_vault_name": "test-only-vault",
        "key_vault_identity": "",
    }
    state = SimpleNamespace(vault={}, secret_writes=[], secret_deletes=[])

    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in public file source tests."))
        scoped.setattr(socket, "create_connection", network)
        scoped.setattr(socket.socket, "connect", network)

        workspaces = {
            "public-a": public_workspace("public-a"),
            "public-b": public_workspace("public-b"),
            "locked-ws": public_workspace("locked-ws", status="locked"),
            "upload-disabled-ws": public_workspace("upload-disabled-ws", status="upload_disabled"),
            "inactive-ws": public_workspace("inactive-ws", status="inactive"),
            "haunted-ws": public_workspace("haunted-ws", status="haunted"),
        }

        workspace_container = WorkspaceContainer(workspaces)
        sources_container = FileSyncContainer("public_workspace_id")
        items_container = FileSyncContainer("source_id")
        runs_container = FileSyncContainer("source_id")

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
        config.cosmos_public_file_sync_sources_container = sources_container
        config.cosmos_public_file_sync_items_container = items_container
        config.cosmos_public_file_sync_runs_container = runs_container
        config.cosmos_group_file_sync_sources_container = FileSyncContainer("group_id")
        config.cosmos_group_file_sync_items_container = FileSyncContainer("source_id")
        config.cosmos_group_file_sync_runs_container = FileSyncContainer("source_id")
        config.cosmos_personal_file_sync_sources_container = FileSyncContainer("user_id")
        config.cosmos_personal_file_sync_items_container = FileSyncContainer("source_id")
        config.cosmos_personal_file_sync_runs_container = FileSyncContainer("source_id")
        config.cosmos_public_workspaces_container = workspace_container
        config.cosmos_public_workspace_identities_container = FileSyncContainer("public_workspace_id")
        config.cosmos_group_workspace_identities_container = FileSyncContainer("group_id")
        config.cosmos_personal_workspace_identities_container = FileSyncContainer("user_id")
        config.cosmos_global_workspace_identities_container = FileSyncContainer("scope_id")
        config.CLIENT_ID = "test-client-id"
        config.CLIENT_SECRET = "test-client-secret"
        config.TENANT_ID = "test-tenant-id"
        config.KEY_VAULT_DOMAIN = ".vault.azure.net"
        config.SECRET_KEY = "test-only-not-a-production-credential"
        scoped.setitem(sys.modules, "config", config)

        scoped.setitem(sys.modules, "functions_appinsights", module_stub(
            "functions_appinsights", log_event=Mock(),
        ))
        scoped.setitem(sys.modules, "functions_debug", module_stub(
            "functions_debug", debug_print=Mock(),
        ))

        # --- settings seam (real enabled_required + normalizers) ---------
        settings_namespace = {
            "wraps": wraps, "get_settings": lambda: settings, "jsonify": jsonify,
            "re": __import__("re"),
        }
        execute_functions("functions_settings.py", {
            "enabled_required",
        }, settings_namespace)
        _normalize_id_list = lambda value: [str(v).strip() for v in value if str(v).strip()] if isinstance(value, (list, tuple, set)) else ([] if not value else [str(value).strip()])
        scoped.setitem(sys.modules, "functions_settings", module_stub(
            "functions_settings",
            get_settings=lambda: settings,
            enabled_required=settings_namespace["enabled_required"],
            sanitize_settings_for_user=lambda data: data,
            normalize_file_sync_allowed_group_ids=_normalize_id_list,
            normalize_file_sync_allowed_public_workspace_ids=_normalize_id_list,
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
        class AzureResourceNotFoundError(CosmosHttpResponseError):
            def __init__(self, *args, **kwargs):
                super().__init__(404)

        azure = module_stub("azure")
        azure.__path__ = []
        azure_identity = module_stub(
            "azure.identity", DefaultAzureCredential=Mock(), ClientSecretCredential=Mock(),
        )
        azure_keyvault = module_stub("azure.keyvault")
        azure_keyvault.__path__ = []
        azure_keyvault_secrets = module_stub("azure.keyvault.secrets", SecretClient=SecretClient)
        azure_core = module_stub("azure.core", MatchConditions=MatchConditions)
        azure_core.__path__ = []
        azure_core_exceptions = module_stub(
            "azure.core.exceptions", ResourceNotFoundError=AzureResourceNotFoundError,
        )
        azure_core.exceptions = azure_core_exceptions
        azure_cosmos = module_stub("azure.cosmos")
        azure_cosmos.__path__ = []
        azure_exceptions = module_stub(
            "azure.cosmos.exceptions",
            CosmosHttpResponseError=CosmosHttpResponseError,
            CosmosResourceNotFoundError=CosmosResourceNotFoundError,
            CosmosResourceExistsError=CosmosResourceExistsError,
            CosmosAccessConditionFailedError=CosmosAccessConditionFailedError,
        )
        azure_storage = module_stub("azure.storage")
        azure_storage.__path__ = []
        azure_storage_blob = module_stub(
            "azure.storage.blob", BlobServiceClient=Mock(), ContainerClient=Mock(),
        )
        azure_storage.blob = azure_storage_blob
        azure.core, azure.cosmos, azure.identity, azure.keyvault, azure.storage = (
            azure_core, azure_cosmos, azure_identity, azure_keyvault, azure_storage,
        )
        azure_cosmos.exceptions = azure_exceptions
        azure_keyvault.secrets = azure_keyvault_secrets
        for name, module in {
            "azure": azure, "azure.core": azure_core, "azure.core.exceptions": azure_core_exceptions,
            "azure.cosmos": azure_cosmos, "azure.cosmos.exceptions": azure_exceptions,
            "azure.identity": azure_identity,
            "azure.keyvault": azure_keyvault, "azure.keyvault.secrets": azure_keyvault_secrets,
            "azure.storage": azure_storage, "azure.storage.blob": azure_storage_blob,
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
        scoped.setitem(sys.modules, "functions_public_workspaces", module_stub(
            "functions_public_workspaces",
            find_public_workspace_by_id=public_ws_namespace["find_public_workspace_by_id"],
            get_user_role_in_public_workspace=public_ws_namespace["get_user_role_in_public_workspace"],
        ))

        # --- group membership seam ---------------------------------------
        # ``functions_file_sync`` imports ``assert_group_role`` for the group scope,
        # which the public tests never exercise; refuse it loudly if reached.
        scoped.setitem(sys.modules, "functions_group", module_stub(
            "functions_group",
            assert_group_role=Mock(side_effect=AssertionError("Group scope is not exercised in public file source tests.")),
        ))

        # --- functions_file_sync leaf-dependency seams -------------------
        # The real tag validator, so fixed tags are deduplicated and checked as the server does them.
        documents_namespace = {"re": __import__("re")}
        execute_functions("functions_documents.py", {"normalize_tag", "validate_tags"}, documents_namespace)
        scoped.setitem(sys.modules, "functions_documents", module_stub(
            "functions_documents",
            allowed_file=Mock(return_value=True),
            create_document=Mock(),
            delete_document_revision=Mock(),
            get_document_metadata=Mock(),
            get_or_create_tag_definition=Mock(),
            process_document_upload_background=Mock(),
            update_document=Mock(),
            validate_tags=documents_namespace["validate_tags"],
        ))
        # The real endpoint validator: it is pure, and a stub returning the wrong shape (a string for
        # its (account, suffix) pair) made every Azure Blob source fail to save in this harness.
        endpoint_spec = importlib.util.spec_from_file_location(
            "functions_azure_endpoint_validation", APP_ROOT / "functions_azure_endpoint_validation.py",
        )
        endpoint_validation = importlib.util.module_from_spec(endpoint_spec)
        scoped.setitem(sys.modules, "functions_azure_endpoint_validation", endpoint_validation)
        endpoint_spec.loader.exec_module(endpoint_validation)
        scoped.setitem(sys.modules, "utils_cache", module_stub(
            "utils_cache",
            invalidate_group_search_cache=Mock(),
            invalidate_personal_search_cache=Mock(),
            invalidate_public_workspace_search_cache=Mock(),
        ))
        content_screening = module_stub("content_screening")
        content_screening.__path__ = []
        content_screening_service = module_stub("content_screening.service", prepare_document_upload=Mock())
        content_screening.service = content_screening_service
        scoped.setitem(sys.modules, "content_screening", content_screening)
        scoped.setitem(sys.modules, "content_screening.service", content_screening_service)

        # --- authentication seam (real decorators + graph mocks) ---------
        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "debug_print": Mock(), "check_user_access_status": Mock(return_value=(True, None)),
        }
        execute_functions("functions_authentication.py", {
            "login_required", "user_required", "get_current_user_id", "get_current_user_info",
            "apply_blueprint_auth", "user_required_blueprint",
        }, auth_namespace)
        auth = module_stub(
            "functions_authentication",
            get_graph_authority=Mock(return_value="https://login.invalid"),
            get_graph_base_url=Mock(return_value="https://graph.invalid"),
            get_graph_endpoint=Mock(return_value="https://graph.invalid/v1.0"),
            **auth_namespace,
        )
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
        filesync = load_real("functions_file_sync")
        load_real("functions_public_file_source_policy")
        access = load_real("functions_public_file_source_access")

        # --- route module executed without importing the app -------------
        route_namespace = {
            "json": json, "wraps": wraps, "jsonify": jsonify, "request": request, "session": session,
            "get_current_user_id": auth.get_current_user_id,
            "get_current_user_info": auth.get_current_user_info,
            "login_required": auth.login_required, "user_required": auth.user_required,
            "enabled_required": settings_namespace["enabled_required"],
            "swagger_route": lambda **_kwargs: (lambda function: function),
            "get_auth_security": lambda: [{"sessionAuth": []}],
            "PublicFileSourceError": access.PublicFileSourceError,
            "browse_public_file_source": access.browse_public_file_source,
            "create_public_file_source": access.create_public_file_source,
            "delete_public_file_source": access.delete_public_file_source,
            "get_public_file_source": access.get_public_file_source,
            "get_public_file_source_options": access.get_public_file_source_options,
            "public_file_source_error_response": access.public_file_source_error_response,
            "ignore_public_file_source_path": access.ignore_public_file_source_path,
            "list_public_file_sources": access.list_public_file_sources,
            "list_public_file_source_runs": access.list_public_file_source_runs,
            "sync_public_file_source": access.sync_public_file_source,
            "test_public_file_source_connection": access.test_public_file_source_connection,
            "update_public_file_source": access.update_public_file_source,
        }
        execute_functions("route_backend_public_file_sources_scoped.py", {
            "register_route_backend_public_file_sources_scoped", "_public_file_source_boundary",
            "_current_user_info", "_reject_query_parameters", "_reject_request_body",
            "_unique_fields", "_read_json_body", "_read_optional_json_body",
        }, route_namespace)

        app = Flask("public_file_source_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_public_file_sources_scoped", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route_namespace["register_route_backend_public_file_sources_scoped"](blueprint)
        app.register_blueprint(blueprint)

        executor = SimpleNamespace(submit_stored=Mock(), submit=Mock())
        app.extensions["executor"] = executor

        env = SimpleNamespace(
            settings=settings, state=state, workspaces=workspaces,
            workspace_container=workspace_container,
            sources_container=sources_container, items_container=items_container,
            runs_container=runs_container, executor=executor,
            filesync=filesync, keyvault=keyvault, identities=identities, access=access,
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


def smb_payload(name="Contracts SMB", password="hunter2", unc_path=UNC_PATH):
    return {
        "name": name,
        "source_type": "smb",
        "connection": {"unc_path": unc_path},
        "credentials": {"auth_type": "username_password", "username": "svc", "password": password},
    }


def create_source(env, payload=None, workspace_id="public-a", as_role="owner"):
    """Create a source through the real route as a manager and return its projection."""
    as_user(env, as_role)
    response = env.client.post(f"/api/public-workspaces/{workspace_id}/file-sources", json=payload or smb_payload())
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["file_source"]


def full_secret_name(env, source_id, field="password"):
    return env.keyvault.build_full_secret_name(
        f"file-sync-{source_id}-{field}", "public-a", "file-sync", "public"
    )


def seed_identity(
    env,
    identity_id,
    *,
    workspace_id="public-a",
    usage_contexts=("file_sync",),
    supported_source_types=("smb",),
    auth_type="username_password",
    name=None,
):
    """Seed one native public workspace identity the file-source options and the
    save-time gate both read, so a test can pin their agreement over a matrix.

    ``usage_contexts``/``supported_source_types`` of ``None`` omit the field, so a
    stored shape can exercise the ``["action"]`` and ``[provider]`` defaults.
    """
    record = {
        "id": identity_id,
        "public_workspace_id": workspace_id,
        "scope_type": "public",
        "name": name or identity_id,
        "provider": "generic",
        "auth": {"auth_type": auth_type, "username": "svc", "password_secret_name": f"{identity_id}-p"},
    }
    if usage_contexts is not None:
        record["usage_contexts"] = list(usage_contexts)
    if supported_source_types is not None:
        record["supported_source_types"] = list(supported_source_types)
    env.identities._get_identities_container("public").seed(record)
    return identity_id


def seed_synced_document(env, source_id, document_id):
    """Seed one synced item so a delete-with-associated-files has documents to remove."""
    env.items_container.seed({
        "id": f"{source_id}-{document_id}",
        "type": "file_sync_item",
        "source_id": source_id,
        "scope_type": "public",
        "public_workspace_id": "public-a",
        "document_id": document_id,
        "remote_path": f"{UNC_PATH}\\{document_id}.txt",
        "status": "synced",
    })
    return document_id
