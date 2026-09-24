# test_group_file_source_apis.py
"""
Functional tests for the immutable-target group file source APIs.
Version: 0.261.142
Implemented in: 0.261.142

The real policy, access, projection, service and route modules run unchanged
against an in-memory Cosmos stub that honours ETag conditional writes and an
in-memory Key Vault, with the real ``functions_keyvault`` staging helpers and the
real group role/status logic. The group is always taken from the path, so a stale
active group can never redirect or widen a request. Group file sources are a
manager-only surface for both reads and writes. Network access is prohibited.

Coverage: the role/status/availability matrix for every route; the list envelope
and single-resource shape with a fresh ``config_revision`` and ``source_actions``;
``expected_config_revision`` conflict detection checked inside the etag-guarded
apply (and an engine run finishing causing no false 409); the busy 409 on delete;
the DELETE body contract; the fresh-name secret staging that keeps a refused
write from rotating the live credential and cleans up superseded names on commit;
create-failure cleanup; the sync 202 and runs read; the server-decided options;
and audit parity.
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


LIST_PATH = "/api/groups/group-a/file-sources"
OPTIONS_PATH = "/api/groups/group-a/file-source-options"
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
        "enable_file_sync": True,
        "enable_file_sync_group": True,
        "enable_file_sync_personal": True,
        "enable_file_sync_public": True,
        "enable_redis_cache": True,
        "redis_url": "redis.invalid",
        "redis_auth_type": "managed_identity",
        "file_sync_group_admin_only": False,
        "require_group_assignment_for_file_sync": False,
        "file_sync_visible_source_types": ["smb", "azure_files", "azure_blob", "sharepoint_on_prem", "google_workspace"],
        "file_sync_max_sources_per_scope": 10,
        "enable_key_vault_secret_storage": True,
        "key_vault_name": "test-only-vault",
        "key_vault_identity": "",
    }
    state = SimpleNamespace(vault={}, secret_writes=[], secret_deletes=[])

    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in group file source tests."))
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

        sources_container = FileSyncContainer("group_id")
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
        config.cosmos_group_file_sync_sources_container = sources_container
        config.cosmos_group_file_sync_items_container = items_container
        config.cosmos_group_file_sync_runs_container = runs_container
        config.cosmos_personal_file_sync_sources_container = FileSyncContainer("user_id")
        config.cosmos_personal_file_sync_items_container = FileSyncContainer("source_id")
        config.cosmos_personal_file_sync_runs_container = FileSyncContainer("source_id")
        config.cosmos_public_file_sync_sources_container = FileSyncContainer("public_workspace_id")
        config.cosmos_public_file_sync_items_container = FileSyncContainer("source_id")
        config.cosmos_public_file_sync_runs_container = FileSyncContainer("source_id")
        config.cosmos_group_workspace_identities_container = FileSyncContainer("group_id")
        config.cosmos_personal_workspace_identities_container = FileSyncContainer("user_id")
        config.cosmos_public_workspace_identities_container = FileSyncContainer("public_workspace_id")
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

        # --- functions_file_sync leaf-dependency seams -------------------
        scoped.setitem(sys.modules, "functions_documents", module_stub(
            "functions_documents",
            allowed_file=Mock(return_value=True),
            create_document=Mock(),
            delete_document_revision=Mock(),
            get_document_metadata=Mock(),
            get_or_create_tag_definition=Mock(),
            process_document_upload_background=Mock(),
            update_document=Mock(),
            validate_tags=Mock(side_effect=lambda tags, *a, **k: (True, "", list(tags or []))),
        ))
        scoped.setitem(sys.modules, "functions_public_workspaces", module_stub(
            "functions_public_workspaces",
            find_public_workspace_by_id=Mock(return_value=None),
            get_user_role_in_public_workspace=Mock(return_value=None),
        ))
        scoped.setitem(sys.modules, "functions_azure_endpoint_validation", module_stub(
            "functions_azure_endpoint_validation",
            AZURE_STORAGE_ENDPOINT_SUFFIXES=("core.windows.net",),
            azure_storage_endpoint_suffix_for_hostname=Mock(return_value="core.windows.net"),
        ))
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
        load_real("functions_group_file_source_policy")
        access = load_real("functions_group_file_source_access")

        # --- route module executed without importing the app -------------
        route_namespace = {
            "json": json, "wraps": wraps, "jsonify": jsonify, "request": request, "session": session,
            "get_current_user_id": auth.get_current_user_id,
            "get_current_user_info": auth.get_current_user_info,
            "login_required": auth.login_required, "user_required": auth.user_required,
            "enabled_required": settings_namespace["enabled_required"],
            "swagger_route": lambda **_kwargs: (lambda function: function),
            "get_auth_security": lambda: [{"sessionAuth": []}],
            "GroupFileSourceError": access.GroupFileSourceError,
            "browse_group_file_source": access.browse_group_file_source,
            "create_group_file_source": access.create_group_file_source,
            "delete_group_file_source": access.delete_group_file_source,
            "get_group_file_source": access.get_group_file_source,
            "get_group_file_source_options": access.get_group_file_source_options,
            "group_file_source_error_response": access.group_file_source_error_response,
            "ignore_group_file_source_path": access.ignore_group_file_source_path,
            "list_group_file_sources": access.list_group_file_sources,
            "list_group_file_source_runs": access.list_group_file_source_runs,
            "sync_group_file_source": access.sync_group_file_source,
            "test_group_file_source_connection": access.test_group_file_source_connection,
            "update_group_file_source": access.update_group_file_source,
        }
        execute_functions("route_backend_group_file_sources_scoped.py", {
            "register_route_backend_group_file_sources_scoped", "_group_file_source_boundary",
            "_current_user_info", "_reject_query_parameters", "_reject_request_body",
            "_unique_fields", "_read_json_body", "_read_optional_json_body",
        }, route_namespace)

        app = Flask("group_file_source_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_group_file_sources_scoped", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route_namespace["register_route_backend_group_file_sources_scoped"](blueprint)
        app.register_blueprint(blueprint)

        executor = SimpleNamespace(submit_stored=Mock(), submit=Mock())
        app.extensions["executor"] = executor

        env = SimpleNamespace(
            settings=settings, state=state, groups=groups,
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


ROLE_USER = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "member"}
MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
NON_MANAGER_ROLES = ("User",)


def smb_payload(name="Contracts SMB", password="s3cr3t", unc_path=UNC_PATH):
    return {
        "name": name,
        "source_type": "smb",
        "connection": {"unc_path": unc_path},
        "credentials": {"auth_type": "username_password", "username": "svc", "password": password},
    }


def create_source(env, payload=None, group_id="group-a", as_role="owner"):
    """Create a source through the real route as a manager and return its projection."""
    as_user(env, as_role)
    response = env.client.post(f"/api/groups/{group_id}/file-sources", json=payload or smb_payload())
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()["file_source"]


def full_secret_name(env, source_id, field="password"):
    return env.keyvault.build_full_secret_name(
        f"file-sync-{source_id}-{field}", "group-a", "file-sync", "group"
    )


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
    source = create_source(environment)
    as_user(environment, ROLE_USER[role])
    listing = environment.client.get(LIST_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert [item["id"] for item in body["file_sources"]] == [source["id"]]
    single = environment.client.get(f"{LIST_PATH}/{source['id']}")
    assert single.status_code == 200
    assert single.get_json()["file_source"]["id"] == source["id"]


@pytest.mark.parametrize("role", NON_MANAGER_ROLES)
def test_non_manager_roles_cannot_read(environment, role):
    create_source(environment)
    as_user(environment, ROLE_USER[role])
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/whatever").status_code == 403


def test_non_member_is_forbidden(environment):
    create_source(environment)
    as_user(environment, "stranger")
    assert environment.client.get(LIST_PATH).status_code == 403


def test_unknown_group_is_404(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/no-such-group/file-sources").status_code == 404


def test_list_envelope_and_single_resource_shape(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"file_sources", "file_source_management"}
    assert body["file_source_management"] == {
        "schema_version": 1, "operations": ["create", "edit", "delete", "sync", "test"],
    }
    item = body["file_sources"][0]
    assert item["id"] == source["id"] and item["group_id"] == "group-a"
    assert item["config_revision"] and item["source_actions"] == ["edit", "delete", "sync", "test"]
    assert "auth" not in item and "_etag" not in item
    single = environment.client.get(f"{LIST_PATH}/{source['id']}").get_json()
    assert set(single) == {"file_source"}
    assert single["file_source"]["id"] == source["id"]


@pytest.mark.parametrize("group_id,readable", [
    ("group-a", True),
    ("locked-grp", True),
    ("upload-disabled-grp", True),
    ("inactive-grp", False),
    ("haunted-grp", False),
])
def test_read_status_matrix(environment, group_id, readable):
    as_user(environment, "owner")
    response = environment.client.get(f"/api/groups/{group_id}/file-sources")
    assert response.status_code == (200 if readable else 403)


@pytest.mark.parametrize("group_id,manageable", [
    ("group-a", True),
    ("locked-grp", False),
    ("upload-disabled-grp", False),
])
def test_management_only_when_active(environment, group_id, manageable):
    """A browsable but non-active group is read-only: management operations are empty
    and a create is refused even though the reader can list."""
    as_user(environment, "owner")
    listing = environment.client.get(f"/api/groups/{group_id}/file-sources")
    assert listing.status_code == 200
    operations = listing.get_json()["file_source_management"]["operations"]
    create = environment.client.post(f"/api/groups/{group_id}/file-sources", json=smb_payload())
    if manageable:
        assert operations == ["create", "edit", "delete", "sync", "test"]
        assert create.status_code == 201
    else:
        assert operations == []
        assert create.status_code == 403


def test_surface_unavailable_when_file_sync_off(environment):
    environment.settings["enable_file_sync_group"] = False
    as_user(environment, "owner")
    response = environment.client.get(LIST_PATH)
    assert response.status_code == 403
    assert response.get_json()["error"] == "File sources require File Sync."


# --------------------------------------------------------------------------
# Create, staging and cleanup
# --------------------------------------------------------------------------

def test_create_stages_secret_under_deterministic_name(environment):
    source = create_source(environment)
    stored = environment.sources_container.get("group-a", source["id"])
    expected_name = full_secret_name(environment, source["id"])
    # The write reference and the vault agree on the conventional name, and the
    # plaintext never lands inline on the stored source.
    assert stored["auth"]["password_secret_name"] == expected_name
    assert environment.state.vault[expected_name] == "s3cr3t"
    assert [name for name, _ in environment.state.secret_writes] == [expected_name]
    assert "password" not in stored["auth"]
    # The sanitized projection never carries the secret.
    assert "auth" not in source


def test_create_failure_discards_staged_secret(environment):
    environment.sources_container.fail_create = True
    as_user(environment, "owner")
    response = environment.client.post(LIST_PATH, json=smb_payload())
    assert response.status_code == 500
    # The staged secret was minted then discarded: no orphan remains in the vault.
    assert environment.state.vault == {}
    assert len(environment.state.secret_writes) == 1
    assert len(environment.state.secret_deletes) == 1
    assert environment.state.secret_writes[0][0] == environment.state.secret_deletes[0]


# --------------------------------------------------------------------------
# Update: config_revision, fresh-name staging, engine-safety
# --------------------------------------------------------------------------

def test_update_password_change_supersedes_old_secret(environment):
    source = create_source(environment)
    old_name = full_secret_name(environment, source["id"])
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={
            "expected_config_revision": source["config_revision"],
            "credentials": {"auth_type": "username_password", "username": "svc", "password": "rotated"},
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    stored = environment.sources_container.get("group-a", source["id"])
    new_name = stored["auth"]["password_secret_name"]
    # The rotated secret lives under a fresh name; the superseded one is removed
    # only after the write commits.
    assert new_name != old_name and new_name.startswith("group-a--file-sync--group--file-sync-")
    assert environment.state.vault.get(new_name) == "rotated"
    assert old_name in environment.state.secret_deletes and old_name not in environment.state.vault


def test_update_conflict_keeps_live_credential_and_leaves_no_orphan(environment):
    source = create_source(environment)
    old_name = full_secret_name(environment, source["id"])
    writes_before = len(environment.state.secret_writes)
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={
            "expected_config_revision": "stale-revision-value",
            "credentials": {"auth_type": "username_password", "username": "svc", "password": "rotated"},
        },
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "config_conflict"
    # The stored reference still points at the original secret, whose current value
    # is unchanged; the fresh staged secret was discarded, leaving no orphan.
    stored = environment.sources_container.get("group-a", source["id"])
    assert stored["auth"]["password_secret_name"] == old_name
    assert environment.state.vault[old_name] == "s3cr3t"
    staged = [name for name, _ in environment.state.secret_writes[writes_before:]]
    assert len(staged) == 1 and staged[0] not in environment.state.vault
    assert staged[0] in environment.state.secret_deletes


def test_update_missing_expected_config_revision_is_400(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}", json={"name": "Renamed"},
    )
    assert response.status_code == 400


def test_engine_run_finishing_is_not_a_false_conflict(environment):
    """An engine writing last_run_* between the read and the conditional write does
    not change the editable projection, so a correct expected_config_revision still
    commits after the etag guard re-reads."""
    source = create_source(environment)
    key = ("group-a", source["id"])

    def land_engine_write():
        record = environment.sources_container.records[key]
        record["last_run_status"] = "success"
        record["_etag"] = '"etag-engine"'

    environment.sources_container.before_replace.append(land_engine_write)
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "name": "Renamed Source"},
    )
    assert response.status_code == 200
    stored = environment.sources_container.get("group-a", source["id"])
    assert stored["name"] == "Renamed Source"
    assert stored["last_run_status"] == "success"


def test_update_deleted_source_is_404(environment):
    source = create_source(environment)
    key = ("group-a", source["id"])

    def delete_underneath():
        environment.sources_container.records.pop(key, None)

    environment.sources_container.before_replace.append(delete_underneath)
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "name": "Renamed"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Delete: body contract, busy, associated files, conflict
# --------------------------------------------------------------------------

def test_delete_requires_body_fields(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    # Missing expected_config_revision.
    assert environment.client.delete(
        f"{LIST_PATH}/{source['id']}", json={"delete_associated_files": False},
    ).status_code == 400
    # Missing delete_associated_files.
    assert environment.client.delete(
        f"{LIST_PATH}/{source['id']}", json={"expected_config_revision": source["config_revision"]},
    ).status_code == 400
    # Unknown field.
    assert environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False, "surprise": 1},
    ).status_code == 400


def test_delete_refused_while_run_active(environment):
    source = create_source(environment)
    environment.runs_container.seed({
        "id": str(uuid.uuid4()), "source_id": source["id"], "scope_type": "group",
        "group_id": "group-a", "status": "running",
    })
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "source_busy"
    assert environment.sources_container.get("group-a", source["id"]) is not None


def test_delete_config_conflict_leaves_source(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": "stale", "delete_associated_files": False},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "config_conflict"
    assert environment.sources_container.get("group-a", source["id"]) is not None


def test_delete_success_without_associated_files(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["delete_result"]["associated_files_requested"] is False
    assert environment.sources_container.get("group-a", source["id"]) is None


def test_delete_mid_flight_write_is_conflict(environment):
    source = create_source(environment)
    key = ("group-a", source["id"])

    def bump_etag():
        environment.sources_container.records[key]["_etag"] = '"etag-raced"'

    environment.sources_container.before_delete.append(bump_etag)
    as_user(environment, "owner")
    response = environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "delete_associated_files": False},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "config_conflict"
    assert environment.sources_container.get("group-a", source["id"]) is not None


# --------------------------------------------------------------------------
# Sync, runs, ignore-path
# --------------------------------------------------------------------------

def test_sync_queues_a_run_without_inline_processing(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.post(f"{LIST_PATH}/{source['id']}/sync")
    assert response.status_code == 202
    run = response.get_json()["run"]
    assert run["source_id"] == source["id"] and run["status"] == "queued"
    environment.executor.submit_stored.assert_called_once()


def test_runs_list_is_readable(environment):
    source = create_source(environment)
    environment.runs_container.seed({
        "id": "run-1", "source_id": source["id"], "scope_type": "group", "group_id": "group-a",
        "status": "success", "error_message": "raw internal detail",
    })
    as_user(environment, "owner")
    response = environment.client.get(f"{LIST_PATH}/{source['id']}/runs")
    assert response.status_code == 200
    runs = response.get_json()["runs"]
    assert [run["id"] for run in runs] == ["run-1"]
    # The raw provider error is replaced by the public run error message.
    assert runs[0]["error_message"] != "raw internal detail"


def test_ignore_path_marks_item_ignored(environment):
    source = create_source(environment)
    as_user(environment, "owner")
    response = environment.client.post(
        f"{LIST_PATH}/{source['id']}/ignore-path",
        json={"remote_path": f"{UNC_PATH}\\old.txt", "ignored": True},
    )
    assert response.status_code == 200
    assert response.get_json()["item"]["status"] == "ignored"


def test_sync_rejects_non_manager(environment):
    source = create_source(environment)
    as_user(environment, "member")
    assert environment.client.post(f"{LIST_PATH}/{source['id']}/sync").status_code == 403


# --------------------------------------------------------------------------
# Test / browse gating (manager-only, no network on the refused path)
# --------------------------------------------------------------------------

def test_saved_test_connection_is_manager_only(environment):
    source = create_source(environment)
    as_user(environment, "member")
    # Refused before any connector runs, so no network is attempted.
    assert environment.client.post(f"{LIST_PATH}/{source['id']}/test-connection").status_code == 403


def test_saved_test_connection_reaches_service_for_manager(environment):
    source = create_source(environment)
    environment.access.test_file_sync_source_connection = Mock(return_value={"ok": True})
    as_user(environment, "owner")
    response = environment.client.post(f"{LIST_PATH}/{source['id']}/test-connection")
    assert response.status_code == 200
    assert response.get_json()["connection"] == {"ok": True}
    scope, group_id, _payload, user_id = environment.access.test_file_sync_source_connection.call_args.args
    assert scope == "group" and group_id == "group-a" and user_id == "owner"
    assert environment.access.test_file_sync_source_connection.call_args.kwargs["source_id"] == source["id"]


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------

def test_options_offers_scope_valid_types_only(environment):
    as_user(environment, "owner")
    response = environment.client.get(OPTIONS_PATH)
    assert response.status_code == 200
    body = response.get_json()
    values = {entry["value"] for entry in body["source_types"]}
    assert "smb" in values
    # OneDrive is personal-only and must never be offered for a group scope.
    assert "onedrive" not in values
    assert body["eligible_identity_ids"] == {value: [] for value in values}
    assert body["limits"]["max_sources"] == 10


def test_options_requires_manager(environment):
    as_user(environment, "member")
    assert environment.client.get(OPTIONS_PATH).status_code == 403


# --------------------------------------------------------------------------
# Query-parameter and body rejection
# --------------------------------------------------------------------------

def test_read_routes_reject_query_parameters(environment):
    create_source(environment)
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}?unexpected=1").status_code == 400
    assert environment.client.get(f"{OPTIONS_PATH}?x=1").status_code == 400


def test_duplicate_json_keys_are_rejected(environment):
    as_user(environment, "owner")
    response = environment.client.post(
        LIST_PATH,
        data='{"name": "a", "name": "b", "source_type": "smb"}',
        content_type="application/json",
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Audit parity
# --------------------------------------------------------------------------

def test_committed_writes_log_activity(environment):
    environment.filesync._log_file_sync_activity = Mock()
    source = create_source(environment)
    assert environment.filesync._log_file_sync_activity.call_args.args[2] == "source_created"

    as_user(environment, "owner")
    environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": source["config_revision"], "name": "Renamed"},
    )
    assert environment.filesync._log_file_sync_activity.call_args.args[2] == "source_updated"

    updated = environment.sources_container.get("group-a", source["id"])
    revision = environment.filesync.compute_file_sync_config_revision(updated)
    environment.client.delete(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": revision, "delete_associated_files": False},
    )
    assert environment.filesync._log_file_sync_activity.call_args.args[2] == "source_deleted"


def test_refused_write_logs_no_activity(environment):
    source = create_source(environment)
    environment.filesync._log_file_sync_activity = Mock()
    as_user(environment, "owner")
    environment.client.patch(
        f"{LIST_PATH}/{source['id']}",
        json={"expected_config_revision": "stale", "name": "Renamed"},
    )
    environment.filesync._log_file_sync_activity.assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
