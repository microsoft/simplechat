# functions_m365_connections.py
"""Explicit, encrypted, per-account delegated Microsoft 365 workflow connections.

Cloud/settings owners are imported only by runtime dependency factories. Importing
this module never creates a client, reads a secret, or performs network I/O.
"""

import base64
import binascii
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import msal
import requests
from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos import exceptions as cosmos_exceptions
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import has_request_context, session

from functions_m365_context import get_m365_execution_context
from functions_m365_operations import M365_ACTION_DEFINITIONS, get_m365_remote_function_names
from m365_interaction import M365_AUTH_INTERACTION_CODES, M365SignInRequired
from functions_m365_approvals import (
    M365ApprovalRequired,
    M365PolicyError,
    M365_SOURCES,
    _identifier,
    material_fingerprint,
    utc_datetime,
    utc_now,
)


KEY_SECRET_ENV = "M365_WORKFLOW_TOKEN_KEY_SECRET_NAME"
ENCRYPTION_VERSION = 1
MAX_CACHE_BYTES = 512 * 1024
AUTH_FLOW_SECONDS = 600
REFRESH_LEASE_SECONDS = 90
CONNECTION_CALLBACK_PATH = "/api/m365/connections/callback"
CHAT_CALLBACK_PATH = "/getAToken"
CHAT_AUTH_SESSION_KEY = "m365_chat_auth_flow"
CHAT_AUTH_STATE_PREFIX = "m365-chat-"
CHAT_CONNECTION_SESSION_KEY = "m365_chat_connection"
CHAT_RECONNECT_SESSION_KEY = "m365_chat_reconnect_required"
_SOURCE_SCOPE_NAMES = {
    "calendar": frozenset({"User.Read", "Calendars.Read", "MailboxSettings.Read"}),
    "email": frozenset({"User.Read", "Mail.Read"}),
    "onedrive": frozenset({"User.Read", "Files.Read.All", "Sites.Read.All"}),
    "spo": frozenset({"User.Read", "Files.Read.All", "Sites.Read.All"}),
}
_SOURCE_OPTIONAL_SCOPE_NAMES = {
    "calendar": frozenset({"Calendars.ReadWrite", "User.ReadBasic.All", "People.Read.All", "Group.Read.All"}),
    "email": frozenset({"Mail.ReadWrite", "Mail.Send", "User.ReadBasic.All", "People.Read.All", "Group.Read.All"}),
    "onedrive": frozenset({"Files.Read"}),
    "spo": frozenset(),
}
_SOURCE_CONNECT_SCOPE_NAMES = {
    "calendar": _SOURCE_SCOPE_NAMES["calendar"] | {"Calendars.ReadWrite", "User.ReadBasic.All"},
    "email": _SOURCE_SCOPE_NAMES["email"] | {"Mail.ReadWrite", "Mail.Send", "User.ReadBasic.All"},
    "onedrive": _SOURCE_SCOPE_NAMES["onedrive"],
    "spo": _SOURCE_SCOPE_NAMES["spo"],
}
_LEGACY_DIRECT_SCOPE_NAMES = frozenset({"SecurityEvents.Read.All"})
_ALLOWED_SCOPE_NAMES = {
    scope.lower(): scope
    for values in (
        *_SOURCE_SCOPE_NAMES.values(), *_SOURCE_OPTIONAL_SCOPE_NAMES.values(),
        _LEGACY_DIRECT_SCOPE_NAMES,
    )
    for scope in values
}
_BINDING_FIELDS = (
    "id", "kind", "connection_id", "user_id", "tenant_id", "client_id",
    "cloud", "authority", "graph_resource", "generation", "home_account_id",
    "cache_environment",
)


class M365ConnectionError(M365PolicyError):
    pass


def _auth_error(code, message, **safe_fields):
    return {
        "error": code, "message": message, "error_code": code,
        "error_description": message, **safe_fields,
    }


def _log_failure(code, exception=None):
    # This logger depends on config/settings and is needed only on a live error.
    from functions_appinsights import log_event
    log_event(
        "[AUTH] Microsoft 365 connection operation failed",
        extra={"code": code, "exception_type": type(exception).__name__ if exception else None},
    )


def _https_url(value):
    if not isinstance(value, str):
        raise M365ConnectionError("m365_configuration_invalid", "Microsoft 365 cloud configuration is invalid.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username
        or parsed.password or parsed.query or parsed.fragment
    ):
        raise M365ConnectionError("m365_configuration_invalid", "Microsoft 365 cloud configuration is invalid.")
    return value.rstrip("/")


@dataclass(frozen=True)
class M365IdentityConfig:
    client_id: str
    tenant_id: str
    authority: str
    graph_resource: str
    cloud: str

    def __post_init__(self):
        for value in (self.client_id, self.tenant_id, self.cloud):
            _identifier(value)
        object.__setattr__(self, "authority", _https_url(self.authority))
        object.__setattr__(self, "graph_resource", _https_url(self.graph_resource))
        if urlsplit(self.authority).path.rstrip("/").split("/")[-1].lower() != self.tenant_id.lower():
            raise M365ConnectionError(
                "m365_tenant_authority_required",
                "Workflow connections require the deployment's exact tenant authority.",
            )

    def binding(self):
        return {
            "client_id": self.client_id, "tenant_id": self.tenant_id,
            "authority": self.authority, "graph_resource": self.graph_resource, "cloud": self.cloud,
        }


@dataclass(frozen=True)
class M365EncryptionKey:
    key: bytes = field(repr=False)
    version: str
    name: str

    def __post_init__(self):
        if not isinstance(self.key, bytes) or len(self.key) != 32:
            raise M365ConnectionError("m365_key_invalid", "The workflow encryption key must be a 256-bit key.")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,127}", self.name or ""):
            raise M365ConnectionError("m365_key_invalid", "The workflow encryption-key reference is invalid.")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", self.version or ""):
            raise M365ConnectionError("m365_key_invalid", "The workflow encryption-key version is invalid.")


def _associated_data(binding, key):
    return json.dumps({
        "encryption_version": ENCRYPTION_VERSION,
        "key_name": key.name, "key_version": key.version,
        "binding": {field_name: binding.get(field_name) for field_name in _BINDING_FIELDS},
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")


def encrypt_m365_cache(serialized_cache, binding, key):
    if not isinstance(serialized_cache, str):
        raise M365ConnectionError("m365_cache_invalid", "The Microsoft 365 connection cache is invalid.")
    plaintext = serialized_cache.encode("utf-8")
    if len(plaintext) > MAX_CACHE_BYTES:
        raise M365ConnectionError("m365_cache_limit", "The Microsoft 365 connection cache exceeds its safe limit.")
    nonce = os.urandom(12)
    ciphertext = AESGCM(key.key).encrypt(nonce, plaintext, _associated_data(binding, key))
    return {
        "version": ENCRYPTION_VERSION, "key_name": key.name, "key_version": key.version,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_m365_cache(envelope, binding, key):
    try:
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"version", "key_name", "key_version", "nonce", "ciphertext"}
            or envelope["version"] != ENCRYPTION_VERSION
            or envelope["key_name"] != key.name or envelope["key_version"] != key.version
            or len(envelope["ciphertext"]) > (MAX_CACHE_BYTES + 16) * 2
        ):
            raise ValueError("Invalid encryption envelope.")
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        if len(nonce) != 12:
            raise ValueError("Invalid nonce.")
        return AESGCM(key.key).decrypt(
            nonce, ciphertext, _associated_data(binding, key),
        ).decode("utf-8")
    except (InvalidTag, ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as exc:
        raise M365ConnectionError(
            "m365_cache_unavailable",
            "The Microsoft 365 connection could not be verified. Reconnect your account.",
        ) from exc


def deserialize_m365_cache(serialized):
    try:
        if not isinstance(serialized, str) or len(serialized.encode("utf-8")) > MAX_CACHE_BYTES:
            raise ValueError("Invalid cache length.")
        document = json.loads(serialized)
        if not isinstance(document, dict) or any(
            not isinstance(entries, dict)
            or any(not isinstance(entry, dict) for entry in entries.values())
            for entries in document.values()
        ):
            raise ValueError("Invalid cache shape.")
        cache = msal.SerializableTokenCache()
        cache.deserialize(serialized)
        return cache
    except (ValueError, TypeError, UnicodeError) as exc:
        raise M365ConnectionError(
            "m365_cache_unavailable",
            "The Microsoft 365 connection cache is invalid. Sign in again.",
        ) from exc


def select_m365_account(accounts, user_id, tenant_id, *, environment=None):
    expected_home = f"{user_id}.{tenant_id}".lower()
    matches = [
        account for account in accounts
        if str(account.get("home_account_id") or "").lower() == expected_home
        and str(account.get("local_account_id") or "").lower() == user_id.lower()
        and str(account.get("realm") or "").lower() == tenant_id.lower()
        and account.get("environment")
        and (environment is None or account.get("environment") == environment)
    ]
    if len(matches) != 1:
        raise M365ConnectionError(
            "m365_account_mismatch",
            "Sign in with your own account in this deployment's tenant. Guest or different accounts cannot be used.",
        )
    return matches[0]


def normalize_m365_scopes(scopes, config):
    if not isinstance(scopes, (list, tuple, set, frozenset)) or not scopes or len(scopes) > 30:
        raise M365ConnectionError("m365_scopes_invalid", "Specify the required delegated Microsoft 365 permissions.")
    normalized = []
    for value in scopes:
        if not isinstance(value, str):
            raise M365ConnectionError("m365_scopes_invalid", "An unsupported Microsoft 365 permission was requested.")
        scope = value.strip()
        if "://" in scope:
            prefix = f"{config.graph_resource}/"
            if not scope.lower().startswith(prefix.lower()):
                raise M365ConnectionError("m365_scope_cloud_mismatch", "The requested permission belongs to a different cloud.")
            scope = scope[len(prefix):]
        canonical = _ALLOWED_SCOPE_NAMES.get(scope.lower())
        if canonical is None:
            raise M365ConnectionError("m365_scopes_invalid", "An unsupported Microsoft 365 permission was requested.")
        qualified = f"{config.graph_resource}/{canonical}"
        if qualified not in normalized:
            normalized.append(qualified)
    return normalized


def _scope_names(scopes, config):
    return {
        scope.rsplit("/", 1)[-1].lower()
        for scope in normalize_m365_scopes(scopes, config)
    }


def _source_connection_scopes(sources):
    if (
        not isinstance(sources, list) or not sources or len(sources) > len(M365_SOURCES)
        or any(not isinstance(source, str) or source not in M365_SOURCES for source in sources)
    ):
        raise M365ConnectionError("m365_sources_invalid", "Select at least one supported Microsoft 365 source.")
    return sorted(set().union(*(_SOURCE_CONNECT_SCOPE_NAMES[source] for source in sources)))


def mark_m365_chat_reconnect_required(context):
    """Fence rejected interactive credentials without revoking workflow connections."""
    if not has_request_context() or context is None or context.workflow_id:
        return
    user = session.get("user") or {}
    if user.get("oid") == context.data_user_id == context.actor_user_id and user.get("tid") == context.tenant_id:
        session[CHAT_RECONNECT_SESSION_KEY] = {"user_id": context.data_user_id, "tenant_id": context.tenant_id}


def _chat_reconnect_required(user_id, tenant_id):
    return session.get(CHAT_RECONNECT_SESSION_KEY) == {"user_id": user_id, "tenant_id": tenant_id}


def _require_granted_scopes(requested_scopes, granted_scope, config):
    """Verify requested grants without treating prior consent as a new scope request."""
    required = _scope_names(requested_scopes, config)
    prefix = f"{config.graph_resource}/".lower()
    granted = {
        scope.lower().removeprefix(prefix)
        for scope in granted_scope.split()
    } if isinstance(granted_scope, str) else set()
    if not required.issubset(granted):
        raise M365ConnectionError(
            "m365_consent_required", "Not all selected Microsoft 365 permissions were authorized.",
        )


def _validate_callback_uri(redirect_uri, *, interactive=False):
    redirect = urlsplit(redirect_uri)
    if (
        redirect.path != (CHAT_CALLBACK_PATH if interactive else CONNECTION_CALLBACK_PATH)
        or redirect.query or redirect.fragment or redirect.username or redirect.password
        or not redirect.hostname
        or (redirect.scheme != "https" and not (
            redirect.scheme == "http" and redirect.hostname in {"localhost", "127.0.0.1"}
        ))
    ):
        raise M365ConnectionError(
            "m365_callback_invalid",
            "Microsoft 365 needs a valid HTTPS callback for this site. Contact an administrator.",
        )


def _validate_auth_flow(flow, config):
    parsed_auth = urlsplit(flow.get("auth_uri", ""))
    query = parse_qs(parsed_auth.query)
    if (
        not flow.get("state") or not flow.get("nonce") or not flow.get("code_verifier")
        or parsed_auth.scheme != "https"
        or parsed_auth.netloc.lower() != urlsplit(config.authority).netloc.lower()
        or query.get("code_challenge_method") != ["S256"]
        or not query.get("code_challenge")
    ):
        raise M365ConnectionError("m365_auth_flow_invalid", "A protected Microsoft 365 sign-in flow could not be created.")


def _default_config():
    # These owners are fully initialized before any connection operation.
    import config as app_config
    from functions_authentication import get_graph_authority, get_graph_base_url
    return M365IdentityConfig(
        client_id=app_config.CLIENT_ID, tenant_id=app_config.TENANT_ID,
        authority=get_graph_authority(),
        graph_resource=get_graph_base_url().removesuffix("/v1.0"),
        cloud=app_config.AZURE_ENVIRONMENT,
    )


def _default_container():
    # The app/scheduler owner registers this dedicated /user_id container.
    import config as app_config
    return app_config.cosmos_m365_connections_container


def _default_msal_factory(cache, config):
    # Credentials remain owned by initialized config. The Graph authority is
    # already pinned by that owner; discovery must not probe a different cloud.
    import config as app_config
    return msal.ConfidentialClientApplication(
        config.client_id, authority=config.authority, client_credential=app_config.CLIENT_SECRET,
        token_cache=cache, instance_discovery=False,
    )


def _default_key_provider(version=None, name=None):
    # Key Vault is mandatory; there is deliberately no Flask-secret/plaintext fallback.
    from azure.keyvault.secrets import SecretClient
    import config as app_config
    from functions_keyvault import get_keyvault_credential
    from functions_settings import get_settings

    configured_name = os.environ.get(KEY_SECRET_ENV, "")
    settings = get_settings()
    vault_name = settings.get("key_vault_name")
    if (
        not settings.get("enable_key_vault_secret_storage")
        or not isinstance(vault_name, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{1,22}[A-Za-z0-9]", vault_name.strip())
        or not re.fullmatch(r"[A-Za-z0-9-]{1,127}", configured_name)
        or (name is not None and name != configured_name)
    ):
        raise M365ConnectionError(
            "m365_key_vault_required",
            "Configure Key Vault and a dedicated workflow encryption-key secret before connecting Microsoft 365.",
        )
    client = SecretClient(
        vault_url=f"https://{vault_name.strip()}{app_config.KEY_VAULT_DOMAIN}",
        credential=get_keyvault_credential(settings=settings),
    )
    try:
        secret = client.get_secret(configured_name, version=version)
    except AzureError as exc:
        _log_failure("m365_key_unavailable", exc)
        raise M365ConnectionError("m365_key_unavailable", "The workflow encryption key is unavailable.") from exc
    properties = secret.properties
    if (
        properties.enabled is False
        or (properties.expires_on is not None and utc_datetime(properties.expires_on) <= utc_now())
        or (properties.not_before is not None and utc_datetime(properties.not_before) > utc_now())
        or (version is not None and properties.version != version)
    ):
        raise M365ConnectionError("m365_key_unavailable", "The workflow encryption-key version is unavailable.")
    try:
        raw_key = base64.b64decode(secret.value, validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise M365ConnectionError("m365_key_invalid", "The workflow encryption key must contain a base64-encoded 256-bit key.") from exc
    return M365EncryptionKey(key=raw_key, version=properties.version, name=configured_name)


def sanitize_m365_connection(connection):
    result = {
        key: copy.deepcopy(connection[key])
        for key in (
            "id", "user_id", "tenant_id", "cloud", "status", "generation",
            "account_username", "sources", "authorized_scopes", "connected_at",
            "disconnected_at", "last_refreshed_at",
        )
        if key in connection
    }
    if "authorized_scopes" in result:
        result["authorized_scopes"] = [
            scope.rsplit("/", 1)[-1] for scope in result["authorized_scopes"]
        ]
    return result


class M365ConnectionService:
    def __init__(
        self, container_factory=_default_container, key_provider=_default_key_provider,
        config_provider=_default_config, msal_factory=_default_msal_factory, clock=utc_now,
        workflow_authorizer=None,
    ):
        self.container_factory = container_factory
        self.key_provider = key_provider
        self.config_provider = config_provider
        self.msal_factory = msal_factory
        self.clock = clock
        self.workflow_authorizer = workflow_authorizer

    @property
    def container(self):
        return self.container_factory()

    def connection_id(self, user_id, config):
        return f"m365-connection-{material_fingerprint([user_id, config.binding()])}"

    def _read(self, item_id, user_id):
        try:
            return self.container.read_item(item=item_id, partition_key=user_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return None

    def _replace(self, previous, updated):
        try:
            return self.container.replace_item(
                item=previous["id"], body=updated,
                etag=previous["_etag"], match_condition=MatchConditions.IfNotModified,
            )
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            if exc.status_code in (409, 412):
                raise M365ConnectionError("m365_connection_busy", "The connection changed. Retry this operation.") from exc
            raise

    def _own_connection(self, connection_id, user_id, tenant_id):
        config = self.config_provider()
        if tenant_id != config.tenant_id:
            raise M365ConnectionError("m365_account_mismatch", "The Microsoft 365 tenant does not match this deployment.")
        expected_id = self.connection_id(_identifier(user_id), config)
        if connection_id != expected_id:
            raise M365ConnectionError("m365_connection_not_found", "Microsoft 365 connection not found.")
        connection = self._read(connection_id, user_id)
        if connection is None or connection.get("kind") != "connection":
            raise M365ConnectionError("m365_connection_required", "Connect your Microsoft 365 account in Profile.")
        if any(connection.get(key) != value for key, value in config.binding().items()):
            raise M365ConnectionError("m365_connection_binding_changed", "The Microsoft 365 deployment changed. Reconnect your account.")
        if connection.get("user_id") != user_id:
            raise M365ConnectionError("m365_account_mismatch", "Microsoft 365 connection account mismatch.")
        return connection, config

    def read_connection(self, connection_id, user_id, tenant_id):
        connection, _config = self._own_connection(connection_id, user_id, tenant_id)
        return sanitize_m365_connection(connection)

    def current_connection(self, user_id, tenant_id):
        config = self.config_provider()
        if tenant_id != config.tenant_id:
            raise M365ConnectionError("m365_account_mismatch", "The Microsoft 365 tenant does not match this deployment.")
        connection = self._read(self.connection_id(_identifier(user_id), config), user_id)
        if connection is None:
            return None
        return self.read_connection(connection["id"], user_id, tenant_id)

    def _ensure_connection(self, user_id, config):
        connection_id = self.connection_id(user_id, config)
        connection = self._read(connection_id, user_id)
        if connection is not None:
            return connection
        body = {
            "id": connection_id, "kind": "connection", "user_id": user_id,
            **config.binding(), "generation": 0, "status": "disconnected",
            "sources": [], "authorized_scopes": [], "encrypted_cache": None,
            "home_account_id": f"{user_id}.{config.tenant_id}",
            "ttl": -1,
        }
        try:
            return self.container.create_item(body=body)
        except cosmos_exceptions.CosmosResourceExistsError:
            return self._read(connection_id, user_id)

    def start_connection(self, user_id, tenant_id, sources, redirect_uri, session_binding, scopes=None):
        config = self.config_provider()
        _identifier(user_id)
        _identifier(session_binding)
        if tenant_id != config.tenant_id:
            raise M365ConnectionError("m365_account_mismatch", "Connect only your account in this deployment's tenant.")
        if (
            not isinstance(sources, list) or not sources or len(sources) > len(M365_SOURCES)
            or any(source not in M365_SOURCES for source in sources)
        ):
            raise ValueError("Select at least one supported Microsoft 365 source.")
        _validate_callback_uri(redirect_uri)
        required = set().union(*(_SOURCE_SCOPE_NAMES[source] for source in sources))
        if scopes is None:
            required = set().union(*(_SOURCE_CONNECT_SCOPE_NAMES[source] for source in sources))
        else:
            allowed = required | set().union(*(_SOURCE_OPTIONAL_SCOPE_NAMES[source] for source in sources))
            normalized_optional = normalize_m365_scopes(scopes, config)
            if not _scope_names(normalized_optional, config).issubset({name.lower() for name in allowed}):
                raise ValueError("The permissions do not belong to the selected Microsoft 365 sources.")
            required.update(scope.rsplit("/", 1)[-1] for scope in normalized_optional)
        required = normalize_m365_scopes(sorted(required), config)
        key = self.key_provider()
        connection = self._ensure_connection(user_id, config)
        cache = msal.SerializableTokenCache()
        client = self.msal_factory(cache, config)
        flow = client.initiate_auth_code_flow(
            scopes=required, redirect_uri=redirect_uri,
            state=secrets.token_urlsafe(32), prompt="select_account",
        )
        _validate_auth_flow(flow, config)
        expires_at = self.clock() + timedelta(seconds=AUTH_FLOW_SECONDS)
        record = {
            "id": f"m365-oauth-{hashlib.sha256(flow['state'].encode('utf-8')).hexdigest()}",
            "kind": "oauth_flow", "purpose": "m365_workflow_connection",
            "user_id": user_id, **config.binding(),
            "connection_id": connection["id"], "generation": connection["generation"],
            "home_account_id": f"{user_id}.{tenant_id}",
            "session_binding": hashlib.sha256(session_binding.encode("utf-8")).hexdigest(),
            "status": "pending", "sources": sorted(set(sources)),
            "requested_scopes": required, "expires_at": expires_at.isoformat(),
            "ttl": AUTH_FLOW_SECONDS * 2,
        }
        record["encrypted_flow"] = encrypt_m365_cache(
            json.dumps(flow, separators=(",", ":")), record, key,
        )
        self.container.create_item(body=record)
        return {
            "authorization_url": flow["auth_uri"], "connection_id": connection["id"],
            "expires_at": expires_at.isoformat(),
        }

    def complete_connection(self, user_id, tenant_id, auth_response, session_binding, *, cache_writer=None):
        config = self.config_provider()
        state = auth_response.get("state") if isinstance(auth_response, dict) else None
        if not isinstance(state, str) or not 20 <= len(state) <= 256:
            raise M365ConnectionError("m365_auth_state_invalid", "This Microsoft 365 sign-in request is invalid or expired.")
        flow_id = f"m365-oauth-{hashlib.sha256(state.encode('utf-8')).hexdigest()}"
        record = self._read(flow_id, user_id)
        if (
            record is None or record.get("purpose") != "m365_workflow_connection"
            or record.get("status") != "pending" or record.get("user_id") != user_id
            or tenant_id != config.tenant_id
            or any(record.get(key) != value for key, value in config.binding().items())
            or utc_datetime(record["expires_at"]) <= self.clock()
            or not isinstance(session_binding, str)
            or not hmac.compare_digest(
                record["session_binding"], hashlib.sha256(session_binding.encode("utf-8")).hexdigest(),
            )
        ):
            raise M365ConnectionError("m365_auth_state_invalid", "This Microsoft 365 sign-in request is invalid or expired.")
        connection, _config = self._own_connection(record["connection_id"], user_id, tenant_id)
        if connection["generation"] != record["generation"]:
            raise M365ConnectionError("m365_auth_state_invalid", "The connection changed during sign-in. Start Connect again.")
        envelope = record["encrypted_flow"]
        key = self.key_provider(envelope["key_version"], envelope["key_name"])
        flow = json.loads(decrypt_m365_cache(envelope, record, key))
        if not hmac.compare_digest(flow["state"], state):
            raise M365ConnectionError("m365_auth_state_invalid", "This Microsoft 365 sign-in request is invalid.")
        self._replace(record, {
            **record, "status": "consumed", "encrypted_flow": None,
            "consumed_at": self.clock().isoformat(),
        })
        cache = msal.SerializableTokenCache()
        client = self.msal_factory(cache, config)
        try:
            result = client.acquire_token_by_auth_code_flow(flow, auth_response)
        except (ValueError, RuntimeError) as exc:
            # MSAL reports nonce validation failures as RuntimeError.
            raise M365ConnectionError("m365_auth_validation_failed", "Microsoft 365 sign-in validation failed. Start Connect again.") from exc
        if not result or result.get("error") or not result.get("access_token"):
            raise M365ConnectionError("m365_consent_required", "Microsoft 365 sign-in or delegated consent was not completed.")
        claims = result.get("id_token_claims") or {}
        if (
            claims.get("oid") != user_id or claims.get("tid") != tenant_id
            or claims.get("acct") in (1, "1")
        ):
            raise M365ConnectionError("m365_account_mismatch", "You must connect your own non-guest account in this tenant.")
        accounts = client.get_accounts()
        account = select_m365_account(accounts, user_id, tenant_id)
        if len(accounts) != 1:
            raise M365ConnectionError("m365_account_mismatch", "The workflow connection must contain exactly your own account.")
        refresh_tokens = list(cache.search(msal.TokenCache.CredentialType.REFRESH_TOKEN))
        if not any(
            token.get("home_account_id") == account["home_account_id"]
            and token.get("client_id") == config.client_id
            and token.get("environment") == account["environment"]
            for token in refresh_tokens
        ):
            raise M365ConnectionError("m365_offline_consent_required", "Offline delegated consent is required for workflow connections.")
        _require_granted_scopes(record["requested_scopes"], result.get("scope"), config)
        current, _config = self._own_connection(connection["id"], user_id, tenant_id)
        if current["generation"] != record["generation"]:
            raise M365ConnectionError("m365_connection_changed", "The connection changed during sign-in. Start Connect again.")
        updated = {
            **current, "generation": current["generation"] + 1, "status": "connected",
            "home_account_id": account["home_account_id"], "cache_environment": account["environment"],
            "account_username": account.get("username", ""),
            "sources": record["sources"], "authorized_scopes": record["requested_scopes"],
            "connected_at": self.clock().isoformat(), "refresh_lease": None,
        }
        updated["encrypted_cache"] = encrypt_m365_cache(cache.serialize(), updated, self.key_provider())
        saved = self._replace(current, updated)
        if cache_writer is not None:
            cache_writer(cache.serialize())
        return sanitize_m365_connection(saved)

    def start_chat_connection(self, user_id, tenant_id, request_id, conversation_id, scopes, redirect_uri):
        """Store a short-lived PKCE flow in the existing server-side login session."""
        _identifier(request_id)
        _identifier(conversation_id)
        return self._start_interactive_connection(
            user_id, tenant_id, scopes, redirect_uri,
            request_id=request_id, conversation_id=conversation_id, purpose="chat_request",
        )

    def _interactive_config(self, user_id, tenant_id):
        config = self.config_provider()
        user = session.get("user") or {}
        if (
            user.get("oid") != user_id or user.get("tid") != tenant_id
            or tenant_id != config.tenant_id or user.get("acct") in (1, "1")
        ):
            raise M365ConnectionError("m365_account_mismatch", "Connect the same tenant account that is signed in to SimpleChat.")
        return config

    def read_chat_connection(self, user_id, tenant_id):
        """Report local session state without probing Graph or exposing credential material."""
        config = self._interactive_config(user_id, tenant_id)
        metadata = session.get(CHAT_CONNECTION_SESSION_KEY)
        if not isinstance(metadata, dict) or (
            metadata.get("user_id") != user_id or metadata.get("tenant_id") != tenant_id
            or metadata.get("configuration") != config.binding()
        ):
            metadata = {}
        sources = [
            source for source in metadata.get("sources", [])
            if isinstance(source, str) and source in M365_SOURCES
        ]
        result = {"status": "not_connected", "sources": sources}
        if _chat_reconnect_required(user_id, tenant_id):
            result["status"] = "reconnect_required"
        elif session.get("token_cache"):
            try:
                cache = deserialize_m365_cache(session["token_cache"])
                accounts = list(cache.search(msal.TokenCache.CredentialType.ACCOUNT))
                select_m365_account(accounts, user_id, tenant_id)
                result["status"] = "available"
            except M365ConnectionError:
                result["status"] = "reconnect_required"
        if metadata.get("connected_at"):
            result["connected_at"] = metadata["connected_at"]
        return result

    def start_profile_chat_connection(self, user_id, tenant_id, sources, redirect_uri):
        scopes = _source_connection_scopes(sources)
        return self._start_interactive_connection(
            user_id, tenant_id, scopes, redirect_uri,
            purpose="profile_reconnect", sources=sorted(set(sources)),
        )

    def _start_interactive_connection(
        self, user_id, tenant_id, scopes, redirect_uri, *,
        purpose, request_id=None, conversation_id=None, sources=None,
    ):
        config = self._interactive_config(user_id, tenant_id)
        _validate_callback_uri(redirect_uri, interactive=True)
        required = normalize_m365_scopes(scopes, config)
        if sources is None:
            names = _scope_names(required, config)
            sources = [
                source for source in M365_SOURCES
                if {name.lower() for name in _SOURCE_CONNECT_SCOPE_NAMES[source]}.issubset(names)
            ]
        client = self.msal_factory(msal.SerializableTokenCache(), config)
        flow = client.initiate_auth_code_flow(
            scopes=required, redirect_uri=redirect_uri,
            state=f"{CHAT_AUTH_STATE_PREFIX}{secrets.token_urlsafe(32)}",
            prompt="select_account",
        )
        _validate_auth_flow(flow, config)
        expires_at = self.clock() + timedelta(seconds=AUTH_FLOW_SECONDS)
        session[CHAT_AUTH_SESSION_KEY] = {
            "flow": flow, "user_id": user_id, "tenant_id": tenant_id,
            "request_id": request_id, "conversation_id": conversation_id,
            "configuration": config.binding(), "required_scopes": required,
            "purpose": purpose, "sources": sources,
            "expires_at": expires_at.isoformat(),
        }
        return {"authorization_url": flow["auth_uri"], "expires_at": expires_at.isoformat()}

    def complete_chat_connection(self, user_id, tenant_id, auth_response):
        config = self.config_provider()
        record = session.get(CHAT_AUTH_SESSION_KEY)
        state = auth_response.get("state")
        user = session.get("user") or {}
        if (
            not isinstance(record, dict) or not isinstance(state, str)
            or re.fullmatch(r"m365-chat-[A-Za-z0-9_-]{32,128}", state) is None
            or not hmac.compare_digest((record.get("flow") or {}).get("state", ""), state)
            or record.get("user_id") != user_id or record.get("tenant_id") != tenant_id
            or user.get("oid") != user_id or user.get("tid") != tenant_id
            or record.get("configuration") != config.binding()
            or utc_datetime(record["expires_at"]) <= self.clock()
        ):
            raise M365ConnectionError("m365_auth_state_invalid", "This sign-in request expired or changed. Connect again from chat.")
        session.pop(CHAT_AUTH_SESSION_KEY)
        cache = msal.SerializableTokenCache()
        client = self.msal_factory(cache, config)
        try:
            result = client.acquire_token_by_auth_code_flow(record["flow"], auth_response)
        except (ValueError, RuntimeError) as exc:
            raise M365ConnectionError("m365_auth_validation_failed", "Microsoft 365 sign-in validation failed. Connect again from chat.") from exc
        if not result or result.get("error") or not result.get("access_token"):
            raise M365ConnectionError("m365_consent_required", "Microsoft 365 sign-in or consent was not completed.")
        claims = result.get("id_token_claims") or {}
        if (
            claims.get("oid") != user_id or claims.get("tid") != tenant_id
            or claims.get("acct") in (1, "1")
        ):
            raise M365ConnectionError("m365_account_mismatch", "Use the same tenant account that started this conversation.")
        accounts = client.get_accounts()
        select_m365_account(accounts, user_id, tenant_id)
        if len(accounts) != 1:
            raise M365ConnectionError("m365_account_mismatch", "The sign-in result must contain only your own account.")
        _require_granted_scopes(record["required_scopes"], result.get("scope"), config)
        serialized = cache.serialize()
        deserialize_m365_cache(serialized)
        session["token_cache"] = serialized
        session[CHAT_CONNECTION_SESSION_KEY] = {
            "user_id": user_id, "tenant_id": tenant_id, "configuration": config.binding(),
            "sources": record.get("sources") or [], "connected_at": self.clock().isoformat(),
        }
        session.pop(CHAT_RECONNECT_SESSION_KEY, None)
        if record.get("purpose") == "profile_reconnect":
            return {"return_to": "profile"}
        return {
            "request_id": record["request_id"], "conversation_id": record["conversation_id"],
        }

    def disconnect(self, connection_id, user_id, tenant_id):
        for _attempt in range(3):
            current, _config = self._own_connection(connection_id, user_id, tenant_id)
            updated = {
                **current, "status": "disconnected", "generation": current["generation"] + 1,
                "encrypted_cache": None, "refresh_lease": None,
                "disconnected_at": self.clock().isoformat(), "authorized_scopes": [],
            }
            try:
                return sanitize_m365_connection(self._replace(current, updated))
            except M365ConnectionError as exc:
                if exc.code != "m365_connection_busy":
                    raise
        raise M365ConnectionError("m365_connection_busy", "The connection is busy. Retry Disconnect.")

    def _claim_refresh(self, connection):
        now = self.clock()
        lease = connection.get("refresh_lease")
        if lease and utc_datetime(lease["expires_at"]) > now:
            raise M365ConnectionError("m365_connection_busy", "This account is refreshing. Retry shortly.")
        if connection["status"] != "connected" or not connection.get("encrypted_cache"):
            raise M365ConnectionError("m365_reconnect_required", "Reconnect Microsoft 365 in Profile before continuing the workflow.")
        lease = {"id": str(uuid.uuid4()), "expires_at": (now + timedelta(seconds=REFRESH_LEASE_SECONDS)).isoformat()}
        return self._replace(connection, {**connection, "refresh_lease": lease})

    def _finish_refresh(self, claimed, serialized=None, reconnect=False):
        current, _config = self._own_connection(claimed["id"], claimed["user_id"], claimed["tenant_id"])
        if (
            current["generation"] != claimed["generation"] or current["status"] != "connected"
            or (current.get("refresh_lease") or {}).get("id") != claimed["refresh_lease"]["id"]
            or utc_datetime(claimed["refresh_lease"]["expires_at"]) <= self.clock()
        ):
            raise M365ConnectionError("m365_connection_changed", "The Microsoft 365 connection changed while refreshing.")
        updated = {**current, "refresh_lease": None}
        if reconnect:
            updated["status"] = "reconnect_required"
        if serialized is not None:
            updated["encrypted_cache"] = encrypt_m365_cache(serialized, updated, self.key_provider())
            updated["last_refreshed_at"] = self.clock().isoformat()
        return self._replace(current, updated)

    def acquire_workflow_token(self, scopes, context):
        # A storage adapter must not become an alternate path around Run as.
        binding_approval = self._authorize_workflow(context)
        connection, config = self._own_connection(
            context.connection_id, context.data_user_id, context.tenant_id,
        )
        required = normalize_m365_scopes(scopes, config)
        allowed = set().union(*(
            _SOURCE_SCOPE_NAMES[source] | _SOURCE_OPTIONAL_SCOPE_NAMES[source]
            for source in binding_approval["binding"]["sources"]
        ))
        if not _scope_names(required, config).issubset({scope.lower() for scope in allowed}):
            raise M365ConnectionError(
                "m365_binding_scope_mismatch",
                "These Microsoft 365 permissions were not authorized for the workflow.",
            )
        if not _scope_names(required, config).issubset(_scope_names(connection["authorized_scopes"], config)):
            raise M365ConnectionError(
                "m365_consent_required",
                "Reconnect Microsoft 365 with this workflow's required permissions.",
                scopes=[scope.rsplit("/", 1)[-1] for scope in required],
                profile_url="/profile",
            )
        claimed = self._claim_refresh(connection)
        envelope = claimed["encrypted_cache"]
        try:
            key = self.key_provider(envelope["key_version"], envelope["key_name"])
            cache = deserialize_m365_cache(decrypt_m365_cache(envelope, claimed, key))
            client = self.msal_factory(cache, config)
            account = select_m365_account(
                client.get_accounts(), context.data_user_id, context.tenant_id,
                environment=claimed["cache_environment"],
            )
            result = client.acquire_token_silent_with_error(required, account=account)
        except (ValueError, requests.RequestException, M365ConnectionError) as exc:
            self._finish_refresh(claimed)
            if isinstance(exc, M365ConnectionError):
                raise
            _log_failure("m365_token_acquisition_failed", exc)
            raise M365ConnectionError("m365_token_acquisition_failed", "Microsoft 365 authentication could not be refreshed.") from exc
        if not result or not result.get("access_token"):
            self._finish_refresh(claimed, cache.serialize(), reconnect=True)
            raise M365ConnectionError("m365_reconnect_required", "Reconnect Microsoft 365 in Profile to continue this workflow.")
        claims = result.get("id_token_claims")
        if claims and (claims.get("oid") != context.data_user_id or claims.get("tid") != context.tenant_id):
            self._finish_refresh(claimed, reconnect=True)
            raise M365ConnectionError("m365_account_mismatch", "The refreshed Microsoft 365 account did not match the approved user.")
        saved = self._finish_refresh(claimed, cache.serialize())
        latest, _config = self._own_connection(saved["id"], context.data_user_id, context.tenant_id)
        if latest["generation"] != saved["generation"] or latest["status"] != "connected":
            raise M365ConnectionError("m365_connection_changed", "The Microsoft 365 connection was disconnected.")
        self._authorize_workflow(context)
        return {"access_token": result["access_token"]}

    def _authorize_workflow(self, context):
        if not callable(self.workflow_authorizer):
            raise M365ConnectionError(
                "m365_authorization_unavailable",
                "Workflow authorization has not been configured. No Microsoft 365 access has been allowed.",
            )
        approval = self.workflow_authorizer(context)
        binding = approval.get("binding") if isinstance(approval, dict) else None
        sources = binding.get("sources") if isinstance(binding, dict) else None
        if (
            not isinstance(sources, list) or not sources
            or any(not isinstance(source, str) or source not in M365_SOURCES for source in sources)
        ):
            raise M365ConnectionError("m365_authorization_unavailable", "The workflow authorization result is invalid.")
        return approval

    def rotate_connection_key(self, connection_id, user_id, tenant_id):
        connection, _config = self._own_connection(connection_id, user_id, tenant_id)
        claimed = self._claim_refresh(connection)
        envelope = claimed["encrypted_cache"]
        try:
            old_key = self.key_provider(envelope["key_version"], envelope["key_name"])
            serialized = decrypt_m365_cache(envelope, claimed, old_key)
        except M365ConnectionError:
            self._finish_refresh(claimed)
            raise
        return sanitize_m365_connection(self._finish_refresh(claimed, serialized))


_service = M365ConnectionService()


def configure_m365_connections(**dependencies):
    global _service
    _service = M365ConnectionService(**dependencies)
    return _service


def configure_m365_connection_authorization(workflow_authorizer):
    """The web/scheduler owner supplies the live binding-validation boundary."""
    if not callable(workflow_authorizer):
        raise TypeError("A workflow authorization callback is required.")
    _service.workflow_authorizer = workflow_authorizer


def get_m365_connection_service():
    return _service


def _direct_access_token(scopes, context, *, include_auth_url=True):
    if not has_request_context() or not isinstance(session.get("user"), dict):
        return _auth_error("not_logged_in", "Sign in to SimpleChat to access Microsoft 365.")
    user = session["user"]
    user_id, tenant_id = user.get("oid"), user.get("tid")
    if not user_id or not tenant_id or user.get("acct") in (1, "1"):
        return _auth_error("m365_account_mismatch", "A matching tenant member account is required.")
    config = _service.config_provider()
    if tenant_id != config.tenant_id or (
        context is not None and (
            context.actor_user_id != user_id or context.data_user_id != user_id
            or context.tenant_id != tenant_id or context.workflow_id
        )
    ):
        return _auth_error("m365_principal_mismatch", "Sign in as the original Microsoft 365 data user to continue.")
    required = normalize_m365_scopes(scopes, config)
    if _chat_reconnect_required(user_id, tenant_id):
        return _auth_error(
            "m365_reconnect_required",
            "Microsoft 365 rejected this saved sign-in. Reconnect your account before trying again.",
            scopes=required,
        )
    serialized = session.get("token_cache")
    if not isinstance(serialized, str) or not serialized:
        return _auth_error("interactive_auth_required", "Sign in again to access Microsoft 365.", scopes=required)
    try:
        cache = deserialize_m365_cache(serialized)
        client = _service.msal_factory(cache, config)
        try:
            account = select_m365_account(client.get_accounts(), user_id, tenant_id)
        except M365ConnectionError as exc:
            if include_auth_url or exc.code != "m365_account_mismatch":
                raise
            return _auth_error(
                "interactive_auth_required", "Connect your own Microsoft 365 account for this agent.",
                scopes=required,
            )
        result = client.acquire_token_silent_with_error(required, account=account)
    except (ValueError, requests.RequestException) as exc:
        _log_failure("m365_token_acquisition_failed", exc)
        return _auth_error("token_acquisition_failed", "Microsoft 365 authentication could not be refreshed.")
    if cache.has_state_changed:
        session["token_cache"] = cache.serialize()
    if result and result.get("access_token"):
        claims = result.get("id_token_claims")
        if claims and (claims.get("oid") != user_id or claims.get("tid") != tenant_id):
            return _auth_error("m365_account_mismatch", "Microsoft 365 returned a different account.")
        return {"access_token": result["access_token"]}
    if not include_auth_url:
        return _auth_error(
            "interactive_auth_required", "Connect Microsoft 365 to authorize this agent's sources.",
            scopes=required,
        )
    # Reuse only the existing consent URL builder, never its first-account fallback.
    from functions_authentication import _build_plugin_auth_response
    needs_consent = bool(
        result and (
            result.get("error") == "consent_required"
            or "AADSTS65001" in str(result.get("error_description", ""))
        )
    )
    code = "consent_required" if needs_consent else "interactive_auth_required"
    message = "Microsoft 365 delegated consent is required." if needs_consent else "Sign in again to access Microsoft 365."
    return _build_plugin_auth_response(
        client, user, required, error=code, message=message,
        error_code=code, error_description=message, prompt="consent" if needs_consent else None,
    )


def get_m365_access_token(scopes, context=None, *, include_auth_url=True):
    """Never fall back from a workflow binding to a caller, owner, or app token."""
    context = context or get_m365_execution_context()
    try:
        if context is not None and context.workflow_id:
            return _service.acquire_workflow_token(scopes, context)
        return _direct_access_token(scopes, context, include_auth_url=include_auth_url)
    except M365ApprovalRequired:
        raise
    except M365PolicyError as exc:
        return _auth_error(
            exc.code, exc.payload["message"],
            **{key: exc.payload[key] for key in ("scopes", "profile_url") if key in exc.payload},
        )
    except (AzureError, requests.RequestException) as exc:
        _log_failure("m365_connection_unavailable", exc)
        return _auth_error("m365_connection_unavailable", "The Microsoft 365 connection is temporarily unavailable.")


def preflight_m365_chat_authentication(manifests, context):
    """Check selected remote sources before model execution, not only after a tool call."""
    if context.workflow_id:
        return
    sources = set()
    for manifest in manifests:
        action_type = manifest.get("type")
        if action_type in M365_ACTION_DEFINITIONS and get_m365_remote_function_names(action_type, manifest):
            sources.add(M365_ACTION_DEFINITIONS[action_type]["source"])
    if not sources:
        return
    scopes = sorted(set().union(*(_SOURCE_CONNECT_SCOPE_NAMES[source] for source in sources)))
    result = get_m365_access_token(scopes, context=context, include_auth_url=False)
    if result.get("access_token"):
        return
    code = result.get("error") or "m365_authorization_unavailable"
    if code in M365_AUTH_INTERACTION_CODES:
        raise M365SignInRequired(code, {"scopes": scopes, "sources": sorted(sources)})
    raise M365PolicyError(
        code, result.get("message") or "Microsoft 365 access could not be verified. No source access has been allowed.",
    )
