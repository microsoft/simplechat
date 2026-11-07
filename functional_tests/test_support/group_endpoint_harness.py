# group_endpoint_harness.py
"""Shared, isolated harness for the native group model endpoint tests (M5C).

Version: 0.261.140
Implemented in: 0.261.140

The modules under test are loaded unchanged from their file paths: the group
document helpers (``functions_group``), the endpoint policy and access modules,
the scoped endpoint routes, the Key Vault helpers (``functions_keyvault``), the
settings helpers (``functions_settings``) and the discovery closures in
``route_backend_models``. Only services outside the application are replaced:

- Cosmos containers are the etag-enforcing ``FakeContainer`` from
  ``test_file_sync_concurrent_write_safety.py``: ``replace_item`` refuses a stale
  etag with 412 and a missing record with 404, and never creates;
- the Key Vault client is an in-memory vault that records every write, read and
  delete by exact secret name;
- governance, the active-group lookup, token credentials, HTTP calls and model
  clients are recording fakes;
- network access, including DNS, is refused.

Key Vault storage is enabled in the settings the helpers actually read
(``app_settings_cache.get_settings_cache``), so the secret assertions cannot pass
because a helper returned early.
"""

import ast
import copy
import importlib.util
import json
import logging
import re
import socket
import sys
import types
import typing
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from functools import wraps
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.cosmos import exceptions as cosmos_exceptions
from flask import Blueprint, Flask, jsonify, request, session

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub


GROUP_A = "group-a"
GROUP_B = "group-b"
VAULT_NAME = "test-only-vault"
ROLE_USERS = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "member"}
READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
WRITER_ROLES = ("Owner", "Admin")
NON_WRITER_ROLES = ("DocumentManager", "User")

BASE_SETTINGS = {
    "enable_group_workspaces": True,
    "enable_semantic_kernel": True,
    "per_user_semantic_kernel": True,
    "allow_group_custom_endpoints": True,
    "enable_multi_model_endpoints": True,
    "allow_user_custom_endpoints": True,
    "enable_key_vault_secret_storage": True,
    "key_vault_name": VAULT_NAME,
    "key_vault_identity": "",
}


def group_document(group_id, status="active", endpoints=(), **extra):
    """A group document shaped like the ones ``create_group`` writes, plus roles."""
    document = {
        "id": group_id,
        "name": f"Group {group_id}",
        "description": "Shared connections",
        "status": status,
        "owner": {"id": "owner", "email": "owner@example.test", "displayName": "Owner"},
        "admins": ["admin"],
        "documentManagers": ["manager"],
        "users": [
            {"userId": "owner", "email": "owner@example.test", "displayName": "Owner"},
            {"userId": "admin", "email": "admin@example.test", "displayName": "Admin"},
            {"userId": "manager", "email": "manager@example.test", "displayName": "Manager"},
            {"userId": "member", "email": "member@example.test", "displayName": "Member"},
        ],
        "pendingUsers": [],
        "model_endpoints": [copy.deepcopy(endpoint) for endpoint in endpoints],
        "createdDate": "2026-09-01T00:00:00",
        "modifiedDate": "2026-09-01T00:00:00",
    }
    document.update(extra)
    return document


def aoai_endpoint(endpoint_id, url="https://group-a.openai.azure.com", api_key="sk-plain", **extra):
    endpoint = {
        "id": endpoint_id,
        "name": f"Endpoint {endpoint_id}",
        "provider": "aoai",
        "enabled": True,
        "connection": {"endpoint": url, "openai_api_version": "2024-10-21"},
        "auth": {"type": "api_key", "api_key": api_key},
        "management": {},
        "models": [
            {"id": "chat", "deploymentName": "gpt-4o", "modelName": "gpt-4o", "enabled": True},
        ],
    }
    endpoint.update(extra)
    return endpoint


def foundry_endpoint(endpoint_id, url="https://group-a.services.ai.azure.com/api/projects/proj", secret="sp-plain", provider="aifoundry", **extra):
    endpoint = {
        "id": endpoint_id,
        "name": f"Foundry {endpoint_id}",
        "provider": provider,
        "enabled": True,
        "connection": {"endpoint": url, "project_api_version": "v1", "openai_api_version": "2025-03-01-preview"},
        "auth": {
            "type": "service_principal",
            "tenant_id": "tenant-1",
            "client_id": "client-1",
            "client_secret": secret,
            "management_cloud": "public",
        },
        "management": {},
        "models": [
            {"id": "chat", "deploymentName": "gpt-4o", "modelName": "gpt-4o", "enabled": True},
        ],
    }
    endpoint.update(extra)
    return endpoint


class FakeVault:
    """An in-memory Key Vault that records every operation by exact secret name."""

    def __init__(self):
        self.secrets = {}
        self.writes = []
        self.reads = []
        self.deletes = []

    def reset(self):
        self.secrets.clear()
        self.writes.clear()
        self.reads.clear()
        self.deletes.clear()

    def written_names(self):
        return [name for name, _value in self.writes]

    def client_class(self):
        vault = self

        class SecretClient:
            def __init__(self, vault_url=None, credential=None, **kwargs):
                assert vault_url == f"https://{VAULT_NAME}.vault.azure.net"

            def set_secret(self, name, value):
                vault.writes.append((name, value))
                vault.secrets[name] = value
                return SimpleNamespace(name=name, value=value, id=f"https://{VAULT_NAME}.vault.azure.net/secrets/{name}/v1")

            def get_secret(self, name, version=None):
                vault.reads.append(name)
                if name not in vault.secrets:
                    raise LookupError("secret not found")
                return SimpleNamespace(value=vault.secrets[name], id=f"https://{VAULT_NAME}.vault.azure.net/secrets/{name}/v1")

            def begin_delete_secret(self, name):
                vault.deletes.append(name)
                vault.secrets.pop(name, None)
                return SimpleNamespace(result=lambda: None)

        return SecretClient


class ActivityRecorder(types.ModuleType):
    """A ``functions_activity_logging`` stand-in that records any call made to it."""

    def __init__(self):
        super().__init__("functions_activity_logging")
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def _load(stack, name, filename=None):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / (filename or f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    stack.enter_context(patch.dict(sys.modules, {name: module}))
    spec.loader.exec_module(module)
    return module


def _extract(filename, names, namespace):
    """Execute top-level classes, constants and functions named in ``names`` from an app file."""
    tree = ast.parse((APP_ROOT / filename).read_text(encoding="utf-8"))
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names for target in node.targets
        ):
            selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)
    return namespace


class GroupEndpointEnvironment:
    """Everything a test needs: live state, the loaded modules and a Flask client."""

    def __init__(self):
        self.settings = dict(BASE_SETTINGS)
        self.groups = FakeContainer("cosmos_groups_container", "id")
        self.agents = FakeContainer("cosmos_group_agents_container", "group_id")
        self.workflows = FakeContainer("cosmos_group_workflows_container", "group_id")
        self.vault = FakeVault()
        self.logs = []
        self.bumps = []
        self.activity = ActivityRecorder()
        self.active_group = GROUP_A
        self.require_active_group = Mock(side_effect=self._require_active_group)
        self.user_settings = {}
        self.denied_features = set()
        self.denied_items = set()
        self.recheck_denials = set()
        self.governance_calls = []
        self.http_calls = []
        self.credentials = []
        self.chat_clients = []
        self.foundry_calls = []
        self.foundry_failure = None

    # --- seams ------------------------------------------------------------

    def _require_active_group(self, user_id, allowed_roles=("Owner", "Admin", "DocumentManager", "User")):
        self.modules.group.assert_group_role(user_id, self.active_group, allowed_roles=allowed_roles)
        return self.active_group

    def _ensure_governance_access(self, feature_key, user_id, item_entity_type=None, item_id=None):
        self.governance_calls.append((feature_key, user_id, item_entity_type, item_id))
        if feature_key in self.denied_features:
            raise PermissionError(f"Governance policy blocks access for feature '{feature_key}'.")
        if item_id and item_id in self.denied_items:
            raise PermissionError(f"Governance policy blocks access to {item_entity_type} '{item_id}'.")
        if item_id and item_id in self.recheck_denials:
            seen = sum(1 for call in self.governance_calls if call[3] == item_id)
            if seen >= 2:
                raise PermissionError(f"Governance policy blocks access to {item_entity_type} '{item_id}'.")

    def _is_governance_access_allowed(self, feature_key, user_id, item_entity_type=None, item_id=None):
        try:
            self._ensure_governance_access(feature_key, user_id, item_entity_type, item_id)
        except PermissionError:
            return False
        return True

    def _log_event(self, message, *args, **kwargs):
        self.logs.append((message, kwargs.get("level"), dict(kwargs.get("extra") or {})))

    def _build_project_credential(self, auth_settings):
        environment = self
        snapshot = copy.deepcopy(auth_settings)

        class Credential:
            def get_token(self, scope):
                environment.credentials.append({"auth": snapshot, "scope": scope})
                return SimpleNamespace(token="fixture-only-access-token")

        return Credential()

    def _http_get(self, url, headers=None, params=None, timeout=None):
        self.http_calls.append({"url": url, "headers": dict(headers or {}), "params": dict(params or {})})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"value": [{"name": "gpt-4o", "modelName": "gpt-4o", "modelVersion": "2024-08-06"}]},
        )

    def _build_chat_client(self, auth_settings, provider, endpoint, api_version, **kwargs):
        environment = self
        record = {
            "auth": copy.deepcopy(auth_settings), "provider": provider, "endpoint": endpoint,
            "api_version": api_version, "deployment_name": kwargs.get("deployment_name"),
        }
        environment.chat_clients.append(record)

        class Completions:
            def create(self, model, messages):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

        client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()), close=lambda: None)
        return client, "azure_openai"

    def _list_foundry(self, kind):
        def list_resources(foundry_settings, settings):
            self.foundry_calls.append({"kind": kind, "settings": copy.deepcopy(foundry_settings)})
            if self.foundry_failure is not None:
                raise self.foundry_failure
            return [{"id": f"{kind}-1", "name": f"{kind} one"}]
        return list_resources

    # --- state ------------------------------------------------------------

    def reset(self):
        self.settings.clear()
        self.settings.update(BASE_SETTINGS)
        for container in (self.groups, self.agents, self.workflows):
            container.records.clear()
            container.calls.clear()
            container.before_replace.clear()
        self.vault.reset()
        self.logs.clear()
        self.bumps.clear()
        self.activity.calls.clear()
        self.active_group = GROUP_A
        self.require_active_group.reset_mock()
        self.user_settings.clear()
        self.denied_features.clear()
        self.denied_items.clear()
        self.recheck_denials.clear()
        self.governance_calls.clear()
        self.http_calls.clear()
        self.credentials.clear()
        self.chat_clients.clear()
        self.foundry_calls.clear()
        self.foundry_failure = None
        self.as_user("owner")

    def as_user(self, user_id, roles=("User",)):
        with self.client.session_transaction() as state:
            state["user"] = {"oid": user_id, "roles": list(roles)}

    def seed_group(self, group_id, status="active", endpoints=(), **extra):
        return self.groups.seed(group_document(group_id, status=status, endpoints=endpoints, **extra))

    def legacy_stored_endpoints(self, group_id, endpoints, scope="group"):
        """Store endpoints as the legacy collection save stored them before the
        endpoint-keyed hardening: normalized, with each credential under the
        deterministic ``{id}--model-endpoint--{scope}--model-endpoint-<field>`` name.

        Built from the Key Vault primitives the old helper used, so the V1-created
        records these tests edit do not depend on how the current helper names a new
        secret. With Key Vault storage off the old helper left the endpoint as it was.
        """
        keyvault = self.modules.keyvault
        normalized, _ = self.modules.settings.normalize_model_endpoints([copy.deepcopy(item) for item in endpoints])
        if not (self.settings.get("enable_key_vault_secret_storage") and self.settings.get("key_vault_name")):
            return normalized
        for endpoint in normalized:
            auth = endpoint.get("auth")
            if not isinstance(auth, dict):
                continue
            auth_type = str(auth.get("type") or "managed_identity").lower()
            for field, auth_types in keyvault.MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS.items():
                if auth_type not in auth_types:
                    auth.pop(field, None)
                elif auth.get(field):
                    auth[field] = keyvault.store_secret_in_key_vault(
                        keyvault._build_model_endpoint_secret_name(field), auth[field], endpoint["id"],
                        source="model-endpoint", scope=scope,
                    )
        return normalized

    def seed_group_with_legacy_endpoints(self, group_id, endpoints, status="active", **extra):
        return self.seed_group(group_id, status=status, endpoints=self.legacy_stored_endpoints(group_id, endpoints), **extra)

    def seed_personal_endpoints(self, user_id, endpoints):
        """Store V1-created personal endpoints (deterministic ``--user--`` names)."""
        stored = self.legacy_stored_endpoints(None, endpoints, scope="user")
        self.user_settings[user_id] = {"id": user_id, "settings": {"personal_model_endpoints": stored}}
        return stored

    def personal_endpoint(self, user_id, endpoint_id):
        for endpoint in self.user_settings.get(user_id, {}).get("settings", {}).get("personal_model_endpoints", []):
            if endpoint.get("id") == endpoint_id:
                return endpoint
        return None

    def stored_group(self, group_id):
        return self.groups.get(group_id, group_id)

    def stored_endpoint(self, group_id, endpoint_id):
        for endpoint in (self.stored_group(group_id) or {}).get("model_endpoints") or []:
            if endpoint.get("id") == endpoint_id:
                return endpoint
        return None

    def write_calls(self, container=None):
        container = container or self.groups
        return [call for call in container.calls if call[0] in ("replace_item", "create_item", "upsert_item", "delete_item")]

    def model_logs(self, fragment):
        return [entry for entry in self.logs if entry[0].startswith("[MODELS]") and fragment in entry[0]]

    # --- requests ---------------------------------------------------------

    def call(self, method, path, body=None, *, raw=None, content_type="application/json", query_string=None):
        kwargs = {}
        if raw is not None:
            kwargs["data"] = raw
            kwargs["content_type"] = content_type
        elif body is not None:
            kwargs["data"] = json.dumps(body)
            kwargs["content_type"] = content_type
        if query_string:
            kwargs["query_string"] = query_string
        return getattr(self.client, method.lower())(path, **kwargs)

    def revision_of(self, group_id, endpoint_id):
        response = self.client.get(f"/api/groups/{group_id}/model-endpoints/{endpoint_id}")
        assert response.status_code == 200, response.get_json()
        return response.get_json()["endpoint"]["revision"]


@contextmanager
def group_endpoint_environment():
    """Load every real module once and yield a resettable environment."""
    env = GroupEndpointEnvironment()
    with ExitStack() as stack:
        stack.enter_context(patch.object(sys, "path", [str(APP_ROOT), *sys.path]))

        def refuse(*args, **kwargs):
            raise AssertionError("The test attempted a network connection")

        def refuse_dns(*args, **kwargs):
            raise socket.gaierror("DNS is disabled in this test")

        stack.enter_context(patch.object(socket.socket, "connect", refuse))
        stack.enter_context(patch.object(socket, "create_connection", refuse))
        stack.enter_context(patch.object(socket, "getaddrinfo", refuse_dns))

        config = module_stub(
            "config",
            json=json, re=re, uuid=uuid, logging=logging,
            datetime=datetime, timezone=timezone,
            exceptions=cosmos_exceptions,
            request=request, session=session, jsonify=jsonify,
            AZURE_ENVIRONMENT="public",
            KEY_VAULT_DOMAIN=".vault.azure.net",
            cosmos_groups_container=env.groups,
            cosmos_group_agents_container=env.agents,
            cosmos_group_workflows_container=env.workflows,
        )
        appinsights = module_stub(
            "functions_appinsights",
            log_event=env._log_event,
            debug_print=lambda *args, **kwargs: None,
            is_debug_enabled=lambda *args, **kwargs: False,
        )
        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "debug_print": lambda *args, **kwargs: None,
            "check_user_access_status": lambda user_id: (True, None),
        }
        execute_functions("functions_authentication.py", {
            "login_required", "user_required", "admin_required", "get_current_user_id",
            "apply_blueprint_auth", "user_required_blueprint",
        }, auth_namespace)
        authentication = module_stub("functions_authentication", **{
            name: value for name, value in auth_namespace.items() if not name.startswith("__")
        })
        governance = module_stub(
            "functions_governance",
            ensure_governance_access=env._ensure_governance_access,
            is_governance_access_allowed=env._is_governance_access_allowed,
        )
        foundry_namespace = _extract("foundry_agent_runtime.py", {
            "FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE", "FoundryAgentInvocationError",
            "FoundryAgentUserAuthenticationRequired", "_get_delegated_foundry_user_token",
            "resolve_foundry_project_base", "resolve_foundry_project_api_version", "resolve_authority",
        }, {"Any": typing.Any, "Dict": typing.Dict, "Optional": typing.Optional})
        foundry_namespace["get_valid_access_token_for_plugins"] = lambda scopes: {
            "scopes": list(scopes), "consent_url": "https://login.example.test/consent",
        }
        foundry = module_stub(
            "foundry_agent_runtime",
            FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE=foundry_namespace["FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE"],
            FoundryAgentUserAuthenticationRequired=foundry_namespace["FoundryAgentUserAuthenticationRequired"],
            list_foundry_agents_from_endpoint=env._list_foundry("agents"),
            list_new_foundry_agents_from_endpoint=env._list_foundry("new_agents"),
            list_foundry_workflows_from_endpoint=env._list_foundry("workflows"),
            resolve_foundry_project_base=foundry_namespace["resolve_foundry_project_base"],
            resolve_foundry_project_api_version=foundry_namespace["resolve_foundry_project_api_version"],
            build_project_credential=env._build_project_credential,
            resolve_authority=foundry_namespace["resolve_authority"],
        )
        env.raise_delegated_auth_required = foundry_namespace["_get_delegated_foundry_user_token"]
        env.FoundryAgentUserAuthenticationRequired = foundry_namespace["FoundryAgentUserAuthenticationRequired"]
        env.FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE = foundry_namespace["FOUNDRY_DELEGATED_AUTH_REQUIRED_MESSAGE"]

        stubs = {
            "config": config,
            "functions_appinsights": appinsights,
            "functions_authentication": authentication,
            "functions_governance": governance,
            "functions_activity_logging": env.activity,
            "functions_chat_bootstrap_cache": module_stub(
                "functions_chat_bootstrap_cache",
                bump_chat_bootstrap_global_cache_version=lambda reason=None, **kwargs: env.bumps.append(reason),
                bump_chat_bootstrap_user_cache_version=lambda *args, **kwargs: None,
            ),
            "functions_workspace_branding": module_stub(
                "functions_workspace_branding", DEFAULT_WORKSPACE_HERO_COLOR="#0078d4",
            ),
            "app_settings_cache": module_stub(
                "app_settings_cache",
                get_settings_cache=lambda: copy.deepcopy(env.settings),
                update_settings_cache=lambda settings: None,
            ),
            "azure.identity": module_stub(
                "azure.identity",
                DefaultAzureCredential=lambda **kwargs: SimpleNamespace(kind="default", options=kwargs),
                ClientSecretCredential=lambda **kwargs: SimpleNamespace(kind="client-secret", options=kwargs),
                get_bearer_token_provider=lambda credential, scope: (lambda: "fixture-only-token"),
            ),
            "azure.keyvault": module_stub("azure.keyvault"),
            "azure.keyvault.secrets": module_stub("azure.keyvault.secrets", SecretClient=env.vault.client_class()),
            "swagger_wrapper": module_stub(
                "swagger_wrapper",
                swagger_route=lambda **kwargs: (lambda function: function),
                get_auth_security=lambda: [{"sessionAuth": []}],
            ),
            "foundry_agent_runtime": foundry,
            "functions_model_endpoint_runtime": module_stub(
                "functions_model_endpoint_runtime", build_model_endpoint_sync_chat_client=env._build_chat_client,
            ),
            # Stand-ins for settings-module dependencies with no bearing on endpoints,
            # the same set the model endpoint normalization suite uses.
            "functions_content_safety": module_stub(
                "functions_content_safety", CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT="Content safety policy violation.",
            ),
            "functions_cosmos_throughput": module_stub(
                "functions_cosmos_throughput", get_default_cosmos_throughput_settings=lambda: {},
            ),
            "functions_document_actions": module_stub(
                "functions_document_actions", get_default_document_action_capabilities=lambda: {},
            ),
            "functions_icon_utils": module_stub(
                "functions_icon_utils",
                normalize_icon_payload=lambda value, field_name="": value if isinstance(value, dict) else {},
            ),
            "functions_latest_features_nav": module_stub(
                "functions_latest_features_nav", LATEST_FEATURES_HIDDEN_VERSION_SETTING="latest_features_hidden_version",
            ),
            "functions_mcp_server_config": module_stub(
                "functions_mcp_server_config",
                INBOUND_MCP_SETTINGS_DEFAULTS={}, normalize_inbound_mcp_settings=lambda settings: None,
            ),
            "functions_service_health": module_stub(
                "functions_service_health", get_default_service_health=lambda: {},
            ),
            "support_menu_config": module_stub(
                "support_menu_config",
                get_default_support_latest_features_visibility=lambda: {},
                has_visible_support_latest_features=lambda *args, **kwargs: False,
                normalize_support_latest_features_visibility=lambda settings: None,
            ),
        }
        stack.enter_context(patch.dict(sys.modules, stubs))

        settings_module = _load(stack, "functions_settings")
        settings_module.get_settings = lambda *args, **kwargs: env.settings
        settings_module.get_user_settings = lambda user_id, *args, **kwargs: copy.deepcopy(
            env.user_settings.get(user_id, {"id": user_id, "settings": {}})
        )

        def update_user_settings(user_id, updates):
            document = env.user_settings.setdefault(user_id, {"id": user_id, "settings": {}})
            document["settings"].update(copy.deepcopy(updates))
            return True

        settings_module.update_user_settings = update_user_settings
        providers = importlib.import_module("functions_model_endpoint_providers")
        stack.enter_context(patch.dict(sys.modules, {
            "model_endpoint_clients": module_stub(
                "model_endpoint_clients",
                MODEL_ENDPOINT_PROTOCOL_ANTHROPIC=providers.MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
                MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI=providers.MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
                MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE=providers.MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
                build_anthropic_chat_client=Mock(side_effect=AssertionError("Unexpected Anthropic client")),
                build_openai_style_chat_client=Mock(side_effect=AssertionError("Unexpected OpenAI-style client")),
                infer_model_endpoint_protocol=lambda *args, **kwargs: providers.MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
                normalize_anthropic_messages_url=lambda endpoint, **kwargs: str(endpoint or ""),
                normalize_openai_style_base_url=lambda endpoint: str(endpoint or ""),
                resolve_custom_openai_base_url=lambda endpoint, api_type, url_mode: str(endpoint or ""),
            ),
        }))
        keyvault = _load(stack, "functions_keyvault")
        group = _load(stack, "functions_group")
        policy = _load(stack, "functions_group_endpoint_policy")
        access = _load(stack, "functions_group_endpoint_access")
        routes = _load(stack, "route_backend_group_endpoints_scoped")
        models = _load(stack, "route_backend_models")
        models.require_active_group = env.require_active_group
        models.requests = SimpleNamespace(get=env._http_get)

        env.modules = SimpleNamespace(
            settings=settings_module, keyvault=keyvault, group=group, policy=policy,
            access=access, routes=routes, models=models, authentication=authentication,
        )

        app = Flask("group_endpoint_contract", root_path=str(APP_ROOT))
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        models_bp = Blueprint("backend_models", __name__)
        models_bp.before_request(authentication.user_required_blueprint())
        models.register_route_backend_models(models_bp)
        endpoints_bp = Blueprint("backend_group_endpoints_scoped", __name__)
        endpoints_bp.before_request(authentication.user_required_blueprint())
        routes.register_route_backend_group_endpoints_scoped(endpoints_bp)
        app.register_blueprint(models_bp)
        app.register_blueprint(endpoints_bp)
        env.app = app
        env.client = app.test_client()
        env.reset()
        yield env
