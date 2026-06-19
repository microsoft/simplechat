# functions_workspace_identities.py

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from config import (
    cosmos_global_workspace_identities_container,
    cosmos_group_workspace_identities_container,
    cosmos_personal_workspace_identities_container,
    cosmos_public_workspace_identities_container,
)
from functions_appinsights import log_event
from functions_keyvault import (
    SecretReturnType,
    retrieve_secret_from_key_vault_by_full_name,
    store_secret_in_key_vault,
    ui_trigger_word,
)
from functions_settings import get_settings


WORKSPACE_IDENTITY_SCOPE_PERSONAL = "personal"
WORKSPACE_IDENTITY_SCOPE_GROUP = "group"
WORKSPACE_IDENTITY_SCOPE_PUBLIC = "public"
WORKSPACE_IDENTITY_SCOPE_GLOBAL = "global"
WORKSPACE_IDENTITY_SCOPES = {
    WORKSPACE_IDENTITY_SCOPE_GLOBAL,
    WORKSPACE_IDENTITY_SCOPE_PERSONAL,
    WORKSPACE_IDENTITY_SCOPE_GROUP,
    WORKSPACE_IDENTITY_SCOPE_PUBLIC,
}
WORKSPACE_IDENTITY_AUTH_TYPES = {
    "anonymous",
    "api_key",
    "bearer_token",
    "client_secret",
    "connection_string",
    "managed_identity",
    "username_password",
}
WORKSPACE_IDENTITY_USAGE_CONTEXTS = {
    "file_sync",
    "action",
}
WORKSPACE_IDENTITY_USAGE_ALIASES = {
    "agent": "action",
    "plugin": "action",
    "general": "action",
}
WORKSPACE_IDENTITY_USAGE_SOURCE_TYPES = {
    "file_sync": ["smb", "azure_files", "onedrive", "google_drive", "google_shared_drive"],
    "action": ["action"],
}
WORKSPACE_IDENTITY_USAGE_AUTH_TYPES = {
    "file_sync": {"anonymous", "client_secret", "connection_string", "managed_identity", "username_password"},
    "action": {"api_key", "bearer_token", "client_secret", "connection_string", "managed_identity", "username_password"},
}
ACTION_IDENTITY_AUTH_TYPES = WORKSPACE_IDENTITY_USAGE_AUTH_TYPES["action"]
ACTION_IDENTITY_FIELD = "identity_id"
ACTION_IDENTITY_SQL_TYPES = {"sql_query", "sql_schema"}
ACTION_IDENTITY_SQL_AUTH_TYPES = {"connection_string", "managed_identity", "username_password"}
ACTION_IDENTITY_OPENAPI_TYPES = {"openapi"}
ACTION_IDENTITY_OPENAPI_AUTH_TYPES = {"api_key", "bearer_token", "username_password"}
ACTION_IDENTITY_DATABRICKS_TYPES = {"databricks", "databricks_table"}
ACTION_IDENTITY_DATABRICKS_AUTH_TYPES = {"api_key", "bearer_token", "managed_identity"}
ACTION_IDENTITY_SNOWFLAKE_TYPES = {"snowflake"}
ACTION_IDENTITY_SNOWFLAKE_AUTH_TYPES = {"api_key", "bearer_token", "username_password"}
ACTION_IDENTITY_TABLEAU_TYPES = {"tableau"}
ACTION_IDENTITY_TABLEAU_AUTH_TYPES = {"api_key", "username_password"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: Any, max_length: int = 255) -> str:
    return str(value or "").strip()[:max_length]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _validate_scope(scope_type: str) -> str:
    normalized_scope = _normalize_text(scope_type, 50).lower()
    if normalized_scope not in WORKSPACE_IDENTITY_SCOPES:
        raise ValueError("Unsupported identity scope")
    return normalized_scope


def _scope_field(scope_type: str) -> str:
    scope_type = _validate_scope(scope_type)
    if scope_type == WORKSPACE_IDENTITY_SCOPE_GLOBAL:
        return "global_id"
    if scope_type == WORKSPACE_IDENTITY_SCOPE_GROUP:
        return "group_id"
    if scope_type == WORKSPACE_IDENTITY_SCOPE_PUBLIC:
        return "public_workspace_id"
    return "user_id"


def _keyvault_scope(scope_type: str) -> str:
    scope_type = _validate_scope(scope_type)
    if scope_type == WORKSPACE_IDENTITY_SCOPE_GLOBAL:
        return "global"
    if scope_type == WORKSPACE_IDENTITY_SCOPE_GROUP:
        return "group"
    if scope_type == WORKSPACE_IDENTITY_SCOPE_PUBLIC:
        return "public"
    return "user"


def _get_identities_container(scope_type: str):
    scope_type = _validate_scope(scope_type)
    if scope_type == WORKSPACE_IDENTITY_SCOPE_GLOBAL:
        return cosmos_global_workspace_identities_container
    if scope_type == WORKSPACE_IDENTITY_SCOPE_GROUP:
        return cosmos_group_workspace_identities_container
    if scope_type == WORKSPACE_IDENTITY_SCOPE_PUBLIC:
        return cosmos_public_workspace_identities_container
    return cosmos_personal_workspace_identities_container


def _normalize_list(
    values: Any,
    allowed_values: Optional[Set[str]] = None,
    default_values: Optional[List[str]] = None,
    aliases: Optional[Dict[str, str]] = None,
) -> List[str]:
    if isinstance(values, str):
        raw_values = [item.strip() for item in values.replace(";", ",").split(",")]
    elif isinstance(values, list):
        raw_values = [_normalize_text(item, 80).lower() for item in values]
    else:
        raw_values = []

    normalized_values = []
    for value in raw_values:
        normalized_value = _normalize_text(value, 80).lower()
        if aliases:
            normalized_value = aliases.get(normalized_value, normalized_value)
        if not normalized_value:
            continue
        if allowed_values and normalized_value not in allowed_values:
            continue
        if normalized_value not in normalized_values:
            normalized_values.append(normalized_value)
    return normalized_values or list(default_values or [])


def _get_usage_source_types(usage_contexts: List[str]) -> List[str]:
    source_types = []
    for usage_context in usage_contexts:
        for source_type in WORKSPACE_IDENTITY_USAGE_SOURCE_TYPES.get(usage_context, []):
            if source_type not in source_types:
                source_types.append(source_type)
    return source_types


def _get_usage_auth_types(usage_contexts: List[str]) -> Set[str]:
    auth_types: Set[str] = set()
    for usage_context in usage_contexts:
        auth_types.update(WORKSPACE_IDENTITY_USAGE_AUTH_TYPES.get(usage_context, set()))
    return auth_types or set(WORKSPACE_IDENTITY_AUTH_TYPES)


def _store_identity_secret(scope_type: str, scope_id: str, identity_id: str, field_name: str, secret_value: str) -> str:
    settings = get_settings()
    if not _as_bool(settings.get("enable_key_vault_secret_storage")) or not str(settings.get("key_vault_name") or "").strip():
        return secret_value

    secret_name = f"workspace-identity-{identity_id}-{field_name}"
    return store_secret_in_key_vault(
        secret_name=secret_name,
        secret_value=secret_value,
        scope_value=scope_id,
        source="identity",
        scope=_keyvault_scope(scope_type),
    )


def _prepare_auth_payload(
    scope_type: str,
    scope_id: str,
    identity_id: str,
    raw_credentials: Dict[str, Any],
    existing_auth: Optional[Dict[str, Any]] = None,
    allowed_auth_types: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    raw_credentials = raw_credentials or {}
    existing_auth = existing_auth or {}
    auth_type = _normalize_text(raw_credentials.get("auth_type", existing_auth.get("auth_type", "username_password")), 50).lower()
    if auth_type not in WORKSPACE_IDENTITY_AUTH_TYPES:
        raise ValueError("Unsupported workspace identity authentication type")
    if allowed_auth_types and auth_type not in allowed_auth_types:
        raise ValueError("Selected authentication type is not available for the selected identity uses")

    prepared_auth = {"auth_type": auth_type}
    if auth_type == "anonymous":
        return prepared_auth
    if auth_type == "managed_identity":
        managed_identity_client_id = _normalize_text(
            raw_credentials.get("managed_identity_client_id", raw_credentials.get("client_id", existing_auth.get("managed_identity_client_id", ""))),
            255,
        )
        if managed_identity_client_id:
            prepared_auth["managed_identity_client_id"] = managed_identity_client_id
        return prepared_auth
    if auth_type == "client_secret":
        client_id = raw_credentials.get("client_id", raw_credentials.get("identity", existing_auth.get("identity", "")))
        prepared_auth["identity"] = _normalize_text(client_id, 255)
        tenant_id = _normalize_text(raw_credentials.get("tenant_id", existing_auth.get("tenant_id", "")), 255)
        if tenant_id:
            prepared_auth["tenant_id"] = tenant_id

    if auth_type == "username_password":
        prepared_auth["username"] = _normalize_text(raw_credentials.get("username", existing_auth.get("username", "")), 255)
        prepared_auth["domain"] = _normalize_text(raw_credentials.get("domain", existing_auth.get("domain", "")), 255)
        password = raw_credentials.get("password")
        if password in [None, "", ui_trigger_word]:
            if existing_auth.get("password_secret_name"):
                prepared_auth["password_secret_name"] = existing_auth["password_secret_name"]
            elif existing_auth.get("password"):
                prepared_auth["password"] = existing_auth["password"]
            else:
                raise ValueError("Username/password identities require a password")
            return prepared_auth

        stored_password = _store_identity_secret(scope_type, scope_id, identity_id, "password", str(password))
        if stored_password == str(password):
            prepared_auth["password"] = stored_password
        else:
            prepared_auth["password_secret_name"] = stored_password
        return prepared_auth

    secret_value = raw_credentials.get("secret") or raw_credentials.get("key") or raw_credentials.get("token") or raw_credentials.get("connection_string")
    if secret_value in [None, "", ui_trigger_word]:
        if existing_auth.get("secret_secret_name"):
            prepared_auth["secret_secret_name"] = existing_auth["secret_secret_name"]
        elif existing_auth.get("secret"):
            prepared_auth["secret"] = existing_auth["secret"]
        else:
            raise ValueError("This identity type requires a secret value")
        return prepared_auth

    stored_secret = _store_identity_secret(scope_type, scope_id, identity_id, "secret", str(secret_value))
    if stored_secret == str(secret_value):
        prepared_auth["secret"] = stored_secret
    else:
        prepared_auth["secret_secret_name"] = stored_secret
    return prepared_auth


def _normalize_identity_payload(
    scope_type: str,
    scope_id: str,
    payload: Dict[str, Any],
    identity_id: str,
    existing_identity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    existing_identity = existing_identity or {}
    scope_type = _validate_scope(scope_type)
    fallback_provider = existing_identity.get("provider", existing_identity.get("source_type", "generic"))
    provider = _normalize_text(
        payload.get("provider", payload.get("source_type", fallback_provider)),
        80,
    ).lower() or "generic"
    allowed_usage_contexts = {"file_sync", "action"}
    default_usage_contexts = ["file_sync"] if provider == "smb" else ["action"]
    if scope_type == WORKSPACE_IDENTITY_SCOPE_PUBLIC:
        allowed_usage_contexts = {"file_sync"}
        default_usage_contexts = ["file_sync"]
    elif scope_type == WORKSPACE_IDENTITY_SCOPE_GLOBAL:
        allowed_usage_contexts = {"file_sync", "action"}
        default_usage_contexts = ["action"]

    usage_contexts = _normalize_list(
        payload.get("usage_contexts", existing_identity.get("usage_contexts")),
        allowed_values=allowed_usage_contexts,
        default_values=default_usage_contexts,
        aliases=WORKSPACE_IDENTITY_USAGE_ALIASES,
    )
    supported_source_types = _normalize_list(
        payload.get("supported_source_types", existing_identity.get("supported_source_types", [provider])),
        allowed_values=set(_get_usage_source_types(list(allowed_usage_contexts))),
        default_values=_get_usage_source_types(usage_contexts) or [provider],
    )
    if provider not in supported_source_types and supported_source_types:
        provider = supported_source_types[0]
    allowed_auth_types = _get_usage_auth_types(usage_contexts)

    return {
        "name": _normalize_text(payload.get("name", existing_identity.get("name", "Workspace Identity")), 120) or "Workspace Identity",
        "description": _normalize_text(payload.get("description", existing_identity.get("description", "")), 500),
        "provider": provider,
        "source_type": provider,
        "usage_contexts": usage_contexts,
        "supported_source_types": supported_source_types,
        "metadata": payload.get("metadata", existing_identity.get("metadata", {})) if isinstance(payload.get("metadata", existing_identity.get("metadata", {})), dict) else {},
        "auth": _prepare_auth_payload(
            scope_type=scope_type,
            scope_id=scope_id,
            identity_id=identity_id,
            raw_credentials=payload.get("credentials") or payload.get("auth") or {},
            existing_auth=existing_identity.get("auth") or {},
            allowed_auth_types=allowed_auth_types,
        ),
    }


def list_workspace_identities(scope_type: str, scope_id: str) -> List[Dict[str, Any]]:
    scope_type = _validate_scope(scope_type)
    scope_field = _scope_field(scope_type)
    query = f"SELECT * FROM c WHERE c.{scope_field} = @scope_id ORDER BY c.name ASC"
    return list(
        _get_identities_container(scope_type).query_items(
            query=query,
            parameters=[{"name": "@scope_id", "value": scope_id}],
            partition_key=scope_id,
        )
    )


def get_workspace_identity(scope_type: str, scope_id: str, identity_id: str) -> Dict[str, Any]:
    scope_type = _validate_scope(scope_type)
    identity_id = _normalize_text(identity_id, 255)
    if not identity_id:
        raise ValueError("identity_id is required")
    try:
        identity = _get_identities_container(scope_type).read_item(item=identity_id, partition_key=scope_id)
    except CosmosResourceNotFoundError:
        raise LookupError("Workspace identity not found")

    scope_field = _scope_field(scope_type)
    if identity.get("scope_type") != scope_type or identity.get(scope_field) != scope_id:
        raise PermissionError("Workspace identity does not belong to this workspace")
    return identity


def sanitize_workspace_identity(identity: Dict[str, Any]) -> Dict[str, Any]:
    sanitized_identity = {key: value for key, value in (identity or {}).items() if not str(key).startswith("_")}
    auth = dict(sanitized_identity.get("auth") or {})
    auth_type = auth.get("auth_type", "username_password")
    secret_stored = bool(auth.get("secret") or auth.get("secret_secret_name"))
    password_stored = bool(auth.get("password") or auth.get("password_secret_name"))
    sanitized_identity["credentials"] = {
        "auth_type": auth_type,
        "username": auth.get("username", ""),
        "domain": auth.get("domain", ""),
        "identity": auth.get("identity", ""),
        "password_stored": password_stored,
        "secret_stored": secret_stored,
        "password": ui_trigger_word if password_stored else "",
        "secret": ui_trigger_word if secret_stored else "",
    }
    sanitized_identity.pop("auth", None)
    return sanitized_identity


def create_workspace_identity(scope_type: str, scope_id: str, payload: Dict[str, Any], created_by: str) -> Dict[str, Any]:
    scope_type = _validate_scope(scope_type)
    identity_id = str(uuid.uuid4())
    normalized_payload = _normalize_identity_payload(scope_type, scope_id, payload or {}, identity_id)
    scope_field = _scope_field(scope_type)
    now_iso = _now_iso()
    identity = {
        "id": identity_id,
        "identity_id": identity_id,
        "type": "workspace_identity",
        "scope_type": scope_type,
        scope_field: scope_id,
        "created_by": created_by,
        "updated_by": created_by,
        "created_at": now_iso,
        "updated_at": now_iso,
        **normalized_payload,
    }
    _get_identities_container(scope_type).create_item(body=identity)
    return identity


def update_workspace_identity(scope_type: str, scope_id: str, identity_id: str, payload: Dict[str, Any], updated_by: str) -> Dict[str, Any]:
    identity = get_workspace_identity(scope_type, scope_id, identity_id)
    normalized_payload = _normalize_identity_payload(scope_type, scope_id, payload or {}, identity_id, existing_identity=identity)
    identity.update(normalized_payload)
    identity["updated_by"] = updated_by
    identity["updated_at"] = _now_iso()
    _get_identities_container(scope_type).upsert_item(identity)
    return identity


def delete_workspace_identity(scope_type: str, scope_id: str, identity_id: str, deleted_by: str) -> Dict[str, Any]:
    identity = get_workspace_identity(scope_type, scope_id, identity_id)
    _get_identities_container(scope_type).delete_item(item=identity["id"], partition_key=scope_id)
    return {"identity_id": identity_id, "deleted_by": deleted_by}


def get_workspace_identity_auth(scope_type: str, scope_id: str, identity_id: str) -> Dict[str, Any]:
    identity = get_workspace_identity(scope_type, scope_id, identity_id)
    auth = dict(identity.get("auth") or {})
    if auth.get("password_secret_name"):
        auth["password"] = retrieve_secret_from_key_vault_by_full_name(auth["password_secret_name"])
    if auth.get("secret_secret_name"):
        auth["secret"] = retrieve_secret_from_key_vault_by_full_name(auth["secret_secret_name"])
    return auth


def get_action_identity_reference_id(action_data: Dict[str, Any]) -> str:
    """Return the workspace identity reference on an action manifest, if present."""
    if not isinstance(action_data, dict):
        return ""

    identity_id = _normalize_text(action_data.get(ACTION_IDENTITY_FIELD), 255)
    if identity_id:
        return identity_id

    additional_fields = action_data.get("additionalFields")
    if isinstance(additional_fields, dict):
        identity_id = _normalize_text(additional_fields.get(ACTION_IDENTITY_FIELD), 255)
        if identity_id:
            return identity_id

    return ""


def validate_action_identity_reference(
    action_data: Dict[str, Any],
    scope_type: str,
    scope_id: str,
) -> Optional[Dict[str, Any]]:
    """Validate that an action references an action-capable identity in its own scope."""
    identity_id = get_action_identity_reference_id(action_data)
    if not identity_id:
        return None

    scope_type = _validate_scope(scope_type)
    if scope_type == WORKSPACE_IDENTITY_SCOPE_PUBLIC:
        raise ValueError("Public workspace identities cannot be used by actions")

    identity = get_workspace_identity(scope_type, scope_id, identity_id)
    allowed_auth_types = _get_action_identity_auth_types_for_plugin(action_data)
    if not identity_supports_usage(
        identity,
        "action",
        source_type="action",
        auth_types=allowed_auth_types,
    ):
        raise ValueError("Selected workspace identity is not configured for action use")

    return identity


def _get_action_identity_auth_types_for_plugin(action_data: Dict[str, Any]) -> Set[str]:
    plugin_type = _normalize_text((action_data or {}).get("type"), 80).lower()
    if plugin_type in ACTION_IDENTITY_SQL_TYPES:
        return ACTION_IDENTITY_SQL_AUTH_TYPES
    if plugin_type in ACTION_IDENTITY_OPENAPI_TYPES:
        return ACTION_IDENTITY_OPENAPI_AUTH_TYPES
    if plugin_type in ACTION_IDENTITY_DATABRICKS_TYPES:
        return ACTION_IDENTITY_DATABRICKS_AUTH_TYPES
    if plugin_type in ACTION_IDENTITY_SNOWFLAKE_TYPES:
        return ACTION_IDENTITY_SNOWFLAKE_AUTH_TYPES
    if plugin_type in ACTION_IDENTITY_TABLEAU_TYPES:
        return ACTION_IDENTITY_TABLEAU_AUTH_TYPES
    return ACTION_IDENTITY_AUTH_TYPES


def hydrate_action_identity_reference(
    action_data: Dict[str, Any],
    scope_type: str,
    scope_id: str,
    return_type: SecretReturnType = SecretReturnType.TRIGGER,
) -> Dict[str, Any]:
    """Apply a referenced workspace identity to an action manifest for UI or runtime use."""
    if not isinstance(action_data, dict):
        return action_data

    identity_id = get_action_identity_reference_id(action_data)
    if not identity_id:
        return action_data

    identity = validate_action_identity_reference(action_data, scope_type, scope_id)
    hydrated_action = dict(action_data)
    hydrated_action[ACTION_IDENTITY_FIELD] = identity_id

    auth = dict(identity.get("auth") or {})
    auth_type = _normalize_text(auth.get("auth_type"), 50).lower()
    additional_fields = dict(hydrated_action.get("additionalFields") or {})
    additional_fields["identity_auth_type"] = auth_type
    hydrated_action["additionalFields"] = additional_fields

    if return_type == SecretReturnType.TRIGGER:
        hydrated_auth = dict(hydrated_action.get("auth") or {})
        hydrated_auth["type"] = "identity"
        hydrated_auth["identity"] = identity_id
        hydrated_action["auth"] = hydrated_auth
        return hydrated_action

    resolved_auth = get_workspace_identity_auth(scope_type, scope_id, identity_id)
    return _apply_action_identity_auth(hydrated_action, resolved_auth)


def _apply_action_identity_auth(action_data: Dict[str, Any], identity_auth: Dict[str, Any]) -> Dict[str, Any]:
    """Return a transient action manifest with identity credentials resolved for runtime use."""
    action = dict(action_data)
    plugin_type = _normalize_text(action.get("type"), 80).lower()
    auth_type = _normalize_text(identity_auth.get("auth_type"), 50).lower()
    additional_fields = dict(action.get("additionalFields") or {})
    action_auth = dict(action.get("auth") or {})

    additional_fields["identity_auth_type"] = auth_type
    action["additionalFields"] = additional_fields

    if plugin_type in ACTION_IDENTITY_SQL_TYPES:
        _apply_sql_action_identity_auth(action_auth, additional_fields, identity_auth)
    elif plugin_type in ACTION_IDENTITY_OPENAPI_TYPES:
        _apply_openapi_action_identity_auth(action_auth, additional_fields, identity_auth)
    elif plugin_type in ACTION_IDENTITY_SNOWFLAKE_TYPES:
        _apply_snowflake_action_identity_auth(action_auth, additional_fields, identity_auth)
    elif plugin_type in ACTION_IDENTITY_TABLEAU_TYPES:
        _apply_tableau_action_identity_auth(action_auth, additional_fields, identity_auth)
    else:
        _apply_generic_action_identity_auth(action_auth, identity_auth)

    action["auth"] = action_auth
    return action


def _identity_secret(identity_auth: Dict[str, Any]) -> str:
    return str(identity_auth.get("secret") or "")


def _apply_sql_action_identity_auth(
    action_auth: Dict[str, Any],
    additional_fields: Dict[str, Any],
    identity_auth: Dict[str, Any],
) -> None:
    auth_type = _normalize_text(identity_auth.get("auth_type"), 50).lower()
    if auth_type == "username_password":
        action_auth["type"] = "user"
        additional_fields["username"] = identity_auth.get("username", "")
        additional_fields["password"] = identity_auth.get("password", "")
    elif auth_type == "connection_string":
        action_auth["type"] = "connection_string"
        action_auth["key"] = _identity_secret(identity_auth)
        additional_fields["connection_string"] = _identity_secret(identity_auth)
    elif auth_type == "managed_identity":
        action_auth["type"] = "identity"
        action_auth["identity"] = "managed_identity"
        additional_fields["auth_type"] = "managed_identity"
    elif auth_type == "client_secret":
        action_auth["type"] = "servicePrincipal"
        action_auth["identity"] = identity_auth.get("identity", "")
        action_auth["key"] = _identity_secret(identity_auth)
    elif auth_type == "api_key":
        action_auth["type"] = "key"
        action_auth["key"] = _identity_secret(identity_auth)
    elif auth_type == "bearer_token":
        action_auth["type"] = "key"
        action_auth["key"] = _identity_secret(identity_auth)


def _apply_openapi_action_identity_auth(
    action_auth: Dict[str, Any],
    additional_fields: Dict[str, Any],
    identity_auth: Dict[str, Any],
) -> None:
    auth_type = _normalize_text(identity_auth.get("auth_type"), 50).lower()
    if auth_type == "api_key":
        action_auth["type"] = "key"
        action_auth["key"] = _identity_secret(identity_auth)
    elif auth_type == "bearer_token":
        action_auth["type"] = "key"
        action_auth["key"] = _identity_secret(identity_auth)
        additional_fields["auth_method"] = "bearer"
    elif auth_type == "username_password":
        action_auth["type"] = "key"
        action_auth["key"] = f"{identity_auth.get('username', '')}:{identity_auth.get('password', '')}"
        additional_fields["auth_method"] = "basic"
    elif auth_type == "managed_identity":
        action_auth["type"] = "identity"
        action_auth["identity"] = "managed_identity"
    elif auth_type == "client_secret":
        action_auth["type"] = "servicePrincipal"
        action_auth["identity"] = identity_auth.get("identity", "")
        action_auth["key"] = _identity_secret(identity_auth)
    elif auth_type == "connection_string":
        action_auth["type"] = "connection_string"
        action_auth["key"] = _identity_secret(identity_auth)


def _apply_tableau_action_identity_auth(
    action_auth: Dict[str, Any],
    additional_fields: Dict[str, Any],
    identity_auth: Dict[str, Any],
) -> None:
    auth_type = _normalize_text(identity_auth.get("auth_type"), 50).lower()
    if auth_type == "api_key":
        action_auth["type"] = "key"
        action_auth["key"] = _identity_secret(identity_auth)
        action_auth["identity"] = additional_fields.get("pat_name", "")
        additional_fields["auth_method"] = "personal_access_token"
    elif auth_type == "username_password":
        action_auth["type"] = "username_password"
        action_auth["identity"] = identity_auth.get("username", "")
        action_auth["key"] = identity_auth.get("password", "")
        additional_fields["auth_method"] = "username_password"


def _apply_snowflake_action_identity_auth(
    action_auth: Dict[str, Any],
    additional_fields: Dict[str, Any],
    identity_auth: Dict[str, Any],
) -> None:
    auth_type = _normalize_text(identity_auth.get("auth_type"), 50).lower()
    if auth_type == "username_password":
        action_auth["type"] = "username_password"
        action_auth["identity"] = identity_auth.get("username", "")
        action_auth["key"] = identity_auth.get("password", "")
        additional_fields["auth_method"] = "password"
        additional_fields["user"] = identity_auth.get("username", "")
    elif auth_type == "api_key":
        action_auth["type"] = "key"
        action_auth["key"] = _identity_secret(identity_auth)
        additional_fields["auth_method"] = "key_pair"
    elif auth_type == "bearer_token":
        action_auth["type"] = "key"
        action_auth["key"] = _identity_secret(identity_auth)
        additional_fields["auth_method"] = "oauth"


def _apply_generic_action_identity_auth(action_auth: Dict[str, Any], identity_auth: Dict[str, Any]) -> None:
    auth_type = _normalize_text(identity_auth.get("auth_type"), 50).lower()
    if auth_type == "api_key":
        action_auth["type"] = "key"
        action_auth["key"] = _identity_secret(identity_auth)
    elif auth_type == "bearer_token":
        action_auth["type"] = "key"
        action_auth["key"] = _identity_secret(identity_auth)
    elif auth_type == "username_password":
        action_auth["type"] = "username_password"
        action_auth["identity"] = identity_auth.get("username", "")
        action_auth["key"] = identity_auth.get("password", "")
    elif auth_type == "connection_string":
        action_auth["type"] = "connection_string"
        action_auth["key"] = _identity_secret(identity_auth)
    elif auth_type == "managed_identity":
        action_auth["type"] = "identity"
        action_auth["identity"] = "managed_identity"
    elif auth_type == "client_secret":
        action_auth["type"] = "servicePrincipal"
        action_auth["identity"] = identity_auth.get("identity", "")
        action_auth["key"] = _identity_secret(identity_auth)


def identity_supports_usage(
    identity: Dict[str, Any],
    usage_context: str,
    source_type: Optional[str] = None,
    auth_types: Optional[Set[str]] = None,
) -> bool:
    normalized_usage_context = WORKSPACE_IDENTITY_USAGE_ALIASES.get(
        _normalize_text(usage_context, 80).lower(),
        _normalize_text(usage_context, 80).lower(),
    )
    usage_contexts = set(
        _normalize_list(
            identity.get("usage_contexts"),
            allowed_values=WORKSPACE_IDENTITY_USAGE_CONTEXTS,
            default_values=["action"],
            aliases=WORKSPACE_IDENTITY_USAGE_ALIASES,
        )
    )
    if normalized_usage_context not in usage_contexts:
        return False
    if source_type:
        normalized_source_type = _normalize_text(source_type, 80).lower()
        supported_source_types = set(_normalize_list(identity.get("supported_source_types"), default_values=[identity.get("provider", "generic")]))
        if normalized_source_type not in supported_source_types and "generic" not in supported_source_types:
            return False
    if auth_types:
        auth_type = _normalize_text((identity.get("auth") or {}).get("auth_type"), 50).lower()
        if auth_type not in auth_types:
            return False
    return True


def log_workspace_identity_reference_block(scope_type: str, scope_id: str, identity_id: str, reference_count: int) -> None:
    log_event(
        "[WorkspaceIdentity] Delete blocked because identity is still referenced.",
        extra={
            "scope_type": scope_type,
            "scope_id": scope_id,
            "identity_id": identity_id,
            "reference_count": reference_count,
        },
        level=logging.INFO,
    )