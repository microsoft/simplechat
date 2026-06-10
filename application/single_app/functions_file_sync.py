# functions_file_sync.py

import fnmatch
import hashlib
import json
import logging
import os
import re
import requests
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

from azure.core.exceptions import ResourceNotFoundError as AzureResourceNotFoundError
from azure.identity import ClientSecretCredential, DefaultAzureCredential
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import current_app, has_app_context
from msal import ConfidentialClientApplication

from config import (
    CLIENT_ID,
    CLIENT_SECRET,
    TENANT_ID,
    cosmos_group_file_sync_items_container,
    cosmos_group_file_sync_runs_container,
    cosmos_group_file_sync_sources_container,
    cosmos_personal_file_sync_items_container,
    cosmos_personal_file_sync_runs_container,
    cosmos_personal_file_sync_sources_container,
    cosmos_public_file_sync_items_container,
    cosmos_public_file_sync_runs_container,
    cosmos_public_file_sync_sources_container,
)
from functions_appinsights import log_event
from functions_authentication import get_graph_authority, get_graph_base_url, get_graph_endpoint
from functions_debug import debug_print
from functions_documents import (
    allowed_file,
    create_document,
    delete_document_revision,
    get_document_metadata,
    get_or_create_tag_definition,
    process_document_upload_background,
    update_document,
    validate_tags,
)
from functions_group import assert_group_role
from functions_keyvault import (
    retrieve_secret_from_key_vault_by_full_name,
    store_secret_in_key_vault,
    ui_trigger_word,
)
from functions_public_workspaces import find_public_workspace_by_id, get_user_role_in_public_workspace
from functions_settings import (
    get_settings,
    normalize_file_sync_allowed_group_ids,
    normalize_file_sync_allowed_public_workspace_ids,
)
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_GLOBAL,
    get_workspace_identity,
    get_workspace_identity_auth,
    identity_supports_usage,
    list_workspace_identities,
)
from utils_cache import (
    invalidate_group_search_cache,
    invalidate_personal_search_cache,
    invalidate_public_workspace_search_cache,
)


FILE_SYNC_SCOPE_PERSONAL = "personal"
FILE_SYNC_SCOPE_GROUP = "group"
FILE_SYNC_SCOPE_PUBLIC = "public"
FILE_SYNC_SCOPES = {FILE_SYNC_SCOPE_PERSONAL, FILE_SYNC_SCOPE_GROUP, FILE_SYNC_SCOPE_PUBLIC}
FILE_SYNC_SOURCE_TYPE_SMB = "smb"
FILE_SYNC_SOURCE_TYPE_AZURE_FILES = "azure_files"
FILE_SYNC_SOURCE_TYPE_ONEDRIVE = "onedrive"
FILE_SYNC_SOURCE_TYPE_SHAREPOINT_ON_PREM = "sharepoint_on_prem"
FILE_SYNC_SOURCE_TYPE_GOOGLE_WORKSPACE = "google_workspace"
FILE_SYNC_KNOWN_SOURCE_TYPES = {
    FILE_SYNC_SOURCE_TYPE_SMB,
    FILE_SYNC_SOURCE_TYPE_AZURE_FILES,
    FILE_SYNC_SOURCE_TYPE_ONEDRIVE,
    FILE_SYNC_SOURCE_TYPE_SHAREPOINT_ON_PREM,
    FILE_SYNC_SOURCE_TYPE_GOOGLE_WORKSPACE,
}
FILE_SYNC_IMPLEMENTED_SOURCE_TYPES = {
    FILE_SYNC_SOURCE_TYPE_SMB,
    FILE_SYNC_SOURCE_TYPE_AZURE_FILES,
    FILE_SYNC_SOURCE_TYPE_ONEDRIVE,
}
FILE_SYNC_ADMIN_VISIBLE_SOURCE_TYPES = {
    FILE_SYNC_SOURCE_TYPE_SMB,
    FILE_SYNC_SOURCE_TYPE_AZURE_FILES,
}
FILE_SYNC_SOURCE_TYPE_LABELS = {
    FILE_SYNC_SOURCE_TYPE_SMB: "SMB",
    FILE_SYNC_SOURCE_TYPE_AZURE_FILES: "Azure Files",
    FILE_SYNC_SOURCE_TYPE_ONEDRIVE: "OneDrive",
    FILE_SYNC_SOURCE_TYPE_SHAREPOINT_ON_PREM: "On-prem SharePoint",
    FILE_SYNC_SOURCE_TYPE_GOOGLE_WORKSPACE: "Google Workspace",
}
FILE_SYNC_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
FILE_SYNC_PERSONAL_APP_ROLE = "PersonalFileSyncUser"

FILE_SYNC_DEFAULTS = {
    "enable_file_sync": False,
    "enable_file_sync_personal": True,
    "enable_file_sync_group": True,
    "enable_file_sync_public": False,
    "file_sync_personal_require_app_role": False,
    "require_group_assignment_for_file_sync": False,
    "file_sync_allowed_group_ids": [],
    "require_public_workspace_assignment_for_file_sync": False,
    "file_sync_allowed_public_workspace_ids": [],
    "file_sync_personal_admin_only": False,
    "file_sync_group_admin_only": False,
    "file_sync_public_admin_only": False,
    "file_sync_visible_source_types": [FILE_SYNC_SOURCE_TYPE_SMB, FILE_SYNC_SOURCE_TYPE_AZURE_FILES],
    "file_sync_max_sources_per_scope": 10,
    "file_sync_min_schedule_interval_minutes": 15,
    "file_sync_max_files_per_run": 1000,
    "file_sync_max_bytes_per_run": 5368709120,
    "file_sync_max_concurrent_runs": 2,
    "file_sync_allow_recursive_sources": True,
    "file_sync_default_remote_delete_policy": "ignore",
    "file_sync_debug_logging": True,
}

FILE_SYNC_REMOTE_DELETE_POLICIES = {"ignore", "hard_delete"}
FILE_SYNC_FOLDER_TAG_MODES = {"none", "parent", "full_path"}
FILE_SYNC_DELETE_ACTIONS = {"delete_only", "ignore_remote"}
FILE_SYNC_IDENTITY_AUTH_TYPES_BY_SOURCE = {
    FILE_SYNC_SOURCE_TYPE_SMB: {"username_password", "anonymous"},
    FILE_SYNC_SOURCE_TYPE_AZURE_FILES: {"managed_identity", "client_secret", "connection_string"},
    FILE_SYNC_SOURCE_TYPE_ONEDRIVE: {"client_secret"},
}
FILE_SYNC_IDENTITY_AUTH_TYPES = set().union(*FILE_SYNC_IDENTITY_AUTH_TYPES_BY_SOURCE.values())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_int(value: Any, default_value: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        parsed_value = int(value)
    except Exception:
        parsed_value = default_value

    if minimum is not None:
        parsed_value = max(minimum, parsed_value)
    if maximum is not None:
        parsed_value = min(maximum, parsed_value)
    return parsed_value


def parse_file_sync_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = value
    elif isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed_value = json.loads(value.strip())
            values = parsed_value if isinstance(parsed_value, list) else re.split(r"[\n,;]+", value)
        except (TypeError, ValueError):
            values = re.split(r"[\n,;]+", value)
    else:
        values = re.split(r"[\n,;]+", str(value))

    normalized_values = []
    seen_values = set()
    for item in values:
        normalized_item = str(item).strip()
        if not normalized_item:
            continue
        normalized_key = normalized_item.lower()
        if normalized_key in seen_values:
            continue
        seen_values.add(normalized_key)
        normalized_values.append(normalized_item)
    return normalized_values


def _user_info_has_admin_role(user_info: Optional[Dict[str, Any]]) -> bool:
    return _user_info_has_app_role(user_info, "Admin")


def _user_info_has_app_role(user_info: Optional[Dict[str, Any]], role_name: str) -> bool:
    if not isinstance(user_info, dict):
        return False
    roles = user_info.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    normalized_role = str(role_name or "").strip().lower()
    return any(str(role).strip().lower() == normalized_role for role in roles)


def _normalize_source_type_list(value: Any, allowed_source_types: Optional[Iterable[str]] = None) -> List[str]:
    allowed_types = {str(source_type).strip().lower() for source_type in allowed_source_types} if allowed_source_types is not None else FILE_SYNC_KNOWN_SOURCE_TYPES
    source_types = []
    seen_source_types = set()
    for source_type in parse_file_sync_list(value):
        normalized_source_type = str(source_type or "").strip().lower()
        if normalized_source_type not in FILE_SYNC_KNOWN_SOURCE_TYPES:
            continue
        if normalized_source_type not in allowed_types:
            continue
        if normalized_source_type in seen_source_types:
            continue
        seen_source_types.add(normalized_source_type)
        source_types.append(normalized_source_type)
    return source_types


def _normalize_source_type(value: Any, default_value: str = FILE_SYNC_SOURCE_TYPE_SMB) -> str:
    normalized_source_type = _normalize_text(value or default_value, 50).lower()
    if normalized_source_type not in FILE_SYNC_KNOWN_SOURCE_TYPES:
        raise ValueError("Unsupported File Sync source type")
    if normalized_source_type not in FILE_SYNC_IMPLEMENTED_SOURCE_TYPES:
        source_label = FILE_SYNC_SOURCE_TYPE_LABELS.get(normalized_source_type, normalized_source_type)
        raise ValueError(f"{source_label} File Sync sources are not supported yet")
    return normalized_source_type


def _source_type_label(source_type: str) -> str:
    normalized_source_type = str(source_type or FILE_SYNC_SOURCE_TYPE_SMB).strip().lower()
    return FILE_SYNC_SOURCE_TYPE_LABELS.get(normalized_source_type, normalized_source_type.upper())


def _file_sync_auth_types_for_source_type(source_type: str) -> set:
    normalized_source_type = _normalize_source_type(source_type)
    return FILE_SYNC_IDENTITY_AUTH_TYPES_BY_SOURCE.get(normalized_source_type, {"username_password", "anonymous"})


def _default_auth_type_for_source_type(source_type: str) -> str:
    normalized_source_type = _normalize_source_type(source_type)
    if normalized_source_type == FILE_SYNC_SOURCE_TYPE_ONEDRIVE:
        return "global_identity"
    if normalized_source_type == FILE_SYNC_SOURCE_TYPE_AZURE_FILES:
        return "managed_identity"
    return "username_password"


def _is_redis_ready(settings: Dict[str, Any]) -> bool:
    if not _as_bool(settings.get("enable_redis_cache")):
        return False
    if not str(settings.get("redis_url") or "").strip():
        return False
    redis_auth_type = str(settings.get("redis_auth_type") or "").strip().lower()
    if redis_auth_type in {"key", "", "access_key"} and not str(settings.get("redis_key") or "").strip():
        return False
    return True


def get_file_sync_config(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    source_settings = settings or get_settings()
    config = {}
    for key, default_value in FILE_SYNC_DEFAULTS.items():
        raw_value = source_settings.get(key, default_value)
        if isinstance(default_value, bool):
            config[key] = _as_bool(raw_value)
        elif isinstance(default_value, int):
            config[key] = _safe_int(raw_value, default_value, minimum=1)
        elif isinstance(default_value, list):
            config[key] = parse_file_sync_list(raw_value)
        else:
            config[key] = raw_value if raw_value is not None else default_value

    config["file_sync_min_schedule_interval_minutes"] = _safe_int(
        config.get("file_sync_min_schedule_interval_minutes"),
        FILE_SYNC_DEFAULTS["file_sync_min_schedule_interval_minutes"],
        minimum=5,
        maximum=1440,
    )
    config["file_sync_max_sources_per_scope"] = _safe_int(
        config.get("file_sync_max_sources_per_scope"),
        FILE_SYNC_DEFAULTS["file_sync_max_sources_per_scope"],
        minimum=1,
        maximum=100,
    )
    config["file_sync_max_files_per_run"] = _safe_int(
        config.get("file_sync_max_files_per_run"),
        FILE_SYNC_DEFAULTS["file_sync_max_files_per_run"],
        minimum=1,
        maximum=100000,
    )
    config["file_sync_max_bytes_per_run"] = _safe_int(
        config.get("file_sync_max_bytes_per_run"),
        FILE_SYNC_DEFAULTS["file_sync_max_bytes_per_run"],
        minimum=1048576,
    )
    config["file_sync_max_concurrent_runs"] = _safe_int(
        config.get("file_sync_max_concurrent_runs"),
        FILE_SYNC_DEFAULTS["file_sync_max_concurrent_runs"],
        minimum=1,
        maximum=25,
    )

    remote_delete_policy = str(config.get("file_sync_default_remote_delete_policy") or "ignore").strip().lower()
    config["file_sync_default_remote_delete_policy"] = remote_delete_policy if remote_delete_policy in FILE_SYNC_REMOTE_DELETE_POLICIES else "ignore"
    config["file_sync_visible_source_types"] = _normalize_source_type_list(
        config.get("file_sync_visible_source_types"),
        FILE_SYNC_ADMIN_VISIBLE_SOURCE_TYPES,
    )
    config["file_sync_allowed_group_ids"] = normalize_file_sync_allowed_group_ids(
        config.get("file_sync_allowed_group_ids")
    )
    config["file_sync_allowed_public_workspace_ids"] = normalize_file_sync_allowed_public_workspace_ids(
        config.get("file_sync_allowed_public_workspace_ids")
    )

    config["requested_enable_file_sync"] = config["enable_file_sync"]
    config["redis_ready"] = _is_redis_ready(source_settings)
    config["enable_file_sync"] = bool(config["enable_file_sync"] and config["redis_ready"])
    return config


def is_file_sync_source_type_visible(settings: Dict[str, Any], source_type: str) -> bool:
    config = get_file_sync_config(settings)
    normalized_source_type = str(source_type or FILE_SYNC_SOURCE_TYPE_SMB).strip().lower()
    return normalized_source_type in config.get("file_sync_visible_source_types", [])


def is_file_sync_enabled_for_user(
    settings: Dict[str, Any],
    user_id: str,
    user_email: Optional[str] = None,
    user_info: Optional[Dict[str, Any]] = None,
    admin_management: bool = False,
) -> bool:
    config = get_file_sync_config(settings)
    if not config["enable_file_sync"] or not config["enable_file_sync_personal"]:
        return False

    if config.get("file_sync_personal_admin_only") and not admin_management and not _user_info_has_admin_role(user_info):
        return False
    if config.get("file_sync_personal_require_app_role") and not admin_management and not _user_info_has_app_role(user_info, FILE_SYNC_PERSONAL_APP_ROLE):
        return False
    return True


def is_file_sync_enabled_for_group(
    settings: Dict[str, Any],
    group_id: str,
    user_info: Optional[Dict[str, Any]] = None,
    admin_management: bool = False,
) -> bool:
    normalized_group_id = str(group_id or "").strip()
    config = get_file_sync_config(settings)
    if not config["enable_file_sync"] or not config["enable_file_sync_group"]:
        return False
    if not normalized_group_id:
        return False

    if config.get("file_sync_group_admin_only") and not admin_management and not _user_info_has_admin_role(user_info):
        return False
    if (
        config.get("require_group_assignment_for_file_sync")
        and not admin_management
        and normalized_group_id not in config.get("file_sync_allowed_group_ids", [])
    ):
        return False
    return True


def is_file_sync_enabled_for_public_workspace(
    settings: Dict[str, Any],
    public_workspace_id: str,
    user_info: Optional[Dict[str, Any]] = None,
    admin_management: bool = False,
) -> bool:
    normalized_workspace_id = str(public_workspace_id or "").strip()
    config = get_file_sync_config(settings)
    if not config["enable_file_sync"] or not config["enable_file_sync_public"]:
        return False
    if not normalized_workspace_id:
        return False

    if config.get("file_sync_public_admin_only") and not admin_management and not _user_info_has_admin_role(user_info):
        return False
    if (
        config.get("require_public_workspace_assignment_for_file_sync")
        and not admin_management
        and normalized_workspace_id not in config.get("file_sync_allowed_public_workspace_ids", [])
    ):
        return False
    return True


def _validate_scope(scope_type: str) -> str:
    normalized_scope = str(scope_type or "").strip().lower()
    if normalized_scope not in FILE_SYNC_SCOPES:
        raise ValueError("Unsupported file sync scope")
    return normalized_scope


def _scope_field(scope_type: str) -> str:
    scope_type = _validate_scope(scope_type)
    if scope_type == FILE_SYNC_SCOPE_GROUP:
        return "group_id"
    if scope_type == FILE_SYNC_SCOPE_PUBLIC:
        return "public_workspace_id"
    return "user_id"


def _keyvault_scope(scope_type: str) -> str:
    if scope_type == FILE_SYNC_SCOPE_PERSONAL:
        return "user"
    if scope_type == FILE_SYNC_SCOPE_GROUP:
        return "group"
    return "public"


def _source_scope_id(source: Dict[str, Any]) -> str:
    return str(source.get(_scope_field(source.get("scope_type"))) or "")


def _get_sources_container(scope_type: str):
    scope_type = _validate_scope(scope_type)
    if scope_type == FILE_SYNC_SCOPE_GROUP:
        return cosmos_group_file_sync_sources_container
    if scope_type == FILE_SYNC_SCOPE_PUBLIC:
        return cosmos_public_file_sync_sources_container
    return cosmos_personal_file_sync_sources_container


def _get_items_container(scope_type: str):
    scope_type = _validate_scope(scope_type)
    if scope_type == FILE_SYNC_SCOPE_GROUP:
        return cosmos_group_file_sync_items_container
    if scope_type == FILE_SYNC_SCOPE_PUBLIC:
        return cosmos_public_file_sync_items_container
    return cosmos_personal_file_sync_items_container


def _get_runs_container(scope_type: str):
    scope_type = _validate_scope(scope_type)
    if scope_type == FILE_SYNC_SCOPE_GROUP:
        return cosmos_group_file_sync_runs_container
    if scope_type == FILE_SYNC_SCOPE_PUBLIC:
        return cosmos_public_file_sync_runs_container
    return cosmos_personal_file_sync_runs_container


def assert_public_workspace_role(user_id: str, public_workspace_id: str, allowed_roles: Iterable[str] = FILE_SYNC_MANAGER_ROLES) -> str:
    workspace_doc = find_public_workspace_by_id(public_workspace_id)
    if not workspace_doc:
        raise LookupError("Public workspace not found")

    role = get_user_role_in_public_workspace(workspace_doc, user_id)
    allowed = {str(role_name).lower() for role_name in allowed_roles}
    if not role or role.lower() not in allowed:
        raise PermissionError("Insufficient permissions for this public workspace")
    return role


def get_authorized_sync_source(
    scope_type: str,
    source_id: str,
    user_id: str,
    scope_id: Optional[str] = None,
    allowed_roles: Iterable[str] = FILE_SYNC_MANAGER_ROLES,
) -> Dict[str, Any]:
    scope_type = _validate_scope(scope_type)
    source_id = str(source_id or "").strip()
    if not source_id:
        raise ValueError("source_id is required")

    source_partition_key = user_id if scope_type == FILE_SYNC_SCOPE_PERSONAL else scope_id
    if not source_partition_key:
        raise PermissionError("A workspace context is required")

    if scope_type == FILE_SYNC_SCOPE_GROUP:
        assert_group_role(user_id, source_partition_key, allowed_roles=allowed_roles)
    elif scope_type == FILE_SYNC_SCOPE_PUBLIC:
        assert_public_workspace_role(user_id, source_partition_key, allowed_roles=allowed_roles)

    container = _get_sources_container(scope_type)
    try:
        source = container.read_item(item=source_id, partition_key=source_partition_key)
    except CosmosResourceNotFoundError:
        raise LookupError("File sync source not found")

    scope_field = _scope_field(scope_type)
    if source.get("scope_type") != scope_type or source.get(scope_field) != source_partition_key:
        raise PermissionError("File sync source does not belong to this workspace")
    return source


def _get_file_sync_identity(
    scope_type: str,
    scope_id: str,
    identity_id: str,
    source_type: str = FILE_SYNC_SOURCE_TYPE_SMB,
) -> Dict[str, Any]:
    normalized_source_type = _normalize_source_type(source_type)
    identity = get_workspace_identity(scope_type, scope_id, identity_id)
    if not identity_supports_usage(
        identity,
        "file_sync",
        source_type=normalized_source_type,
        auth_types=_file_sync_auth_types_for_source_type(normalized_source_type),
    ):
        raise ValueError(f"Selected workspace identity cannot be used for {_source_type_label(normalized_source_type)} File Sync")
    return identity


def _get_identity_auth_for_source(source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    identity_id = str(source.get("identity_id") or "").strip()
    if not identity_id:
        return None
    _get_file_sync_identity(
        source.get("scope_type"),
        _source_scope_id(source),
        identity_id,
        source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB),
    )
    return get_workspace_identity_auth(source.get("scope_type"), _source_scope_id(source), identity_id)


def list_file_sync_sources(scope_type: str, scope_id: str) -> List[Dict[str, Any]]:
    scope_type = _validate_scope(scope_type)
    scope_field = _scope_field(scope_type)
    container = _get_sources_container(scope_type)
    query = f"SELECT * FROM c WHERE c.{scope_field} = @scope_id ORDER BY c.created_at DESC"
    return list(
        container.query_items(
            query=query,
            parameters=[{"name": "@scope_id", "value": scope_id}],
            partition_key=scope_id,
        )
    )


def sanitize_file_sync_source(source: Dict[str, Any]) -> Dict[str, Any]:
    sanitized_source = dict(source or {})
    auth = dict(sanitized_source.get("auth") or {})
    identity_id = str(sanitized_source.get("identity_id") or "").strip()
    if identity_id:
        try:
            identity = _get_file_sync_identity(
                sanitized_source.get("scope_type"),
                _source_scope_id(sanitized_source),
                identity_id,
                sanitized_source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB),
            )
            sanitized_source["identity_name"] = identity.get("name", "")
            auth = dict(identity.get("auth") or {})
        except Exception:
            sanitized_source["identity_name"] = "Unavailable identity"
            auth = {"auth_type": "identity_missing"}
    password_stored = bool(auth.get("password") or auth.get("password_secret_name"))
    secret_stored = bool(auth.get("secret") or auth.get("secret_secret_name"))
    sanitized_source["identity_id"] = identity_id
    sanitized_source["credentials"] = {
        "auth_type": auth.get("auth_type", _default_auth_type_for_source_type(sanitized_source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB))),
        "username": auth.get("username", ""),
        "domain": auth.get("domain", ""),
        "identity": auth.get("identity", ""),
        "password_stored": password_stored,
        "secret_stored": secret_stored,
        "password": ui_trigger_word if password_stored else "",
        "secret": ui_trigger_word if secret_stored else "",
    }
    sanitized_source.pop("auth", None)
    return sanitized_source


def sanitize_file_sync_run(run: Dict[str, Any]) -> Dict[str, Any]:
    sanitized_run = dict(run or {})
    if sanitized_run.get("error_message"):
        sanitized_run["error_message"] = str(sanitized_run["error_message"])[:1000]
    return sanitized_run


def _normalize_text(value: Any, max_length: int = 255) -> str:
    return str(value or "").strip()[:max_length]


def _normalize_unc_path(value: Any) -> str:
    unc_path = _normalize_text(value, max_length=2048).replace("/", "\\")
    if not unc_path.startswith("\\\\"):
        raise ValueError("SMB sources require a UNC path such as \\\\server\\share\\folder")
    parts = [part for part in unc_path.strip("\\").split("\\") if part]
    if len(parts) < 2:
        raise ValueError("SMB UNC path must include a server and share")
    return "\\\\" + "\\".join(parts)


def _normalize_azure_file_url(value: Any) -> Tuple[str, List[str]]:
    raw_url = _normalize_text(value, max_length=2048)
    if not raw_url:
        return "", []
    if "://" not in raw_url:
        raw_url = f"https://{raw_url}"

    parsed_url = urlparse(raw_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise ValueError("Azure Files sources require an HTTPS file service or share URL")

    path_parts = [unquote(path_part) for path_part in parsed_url.path.split("/") if path_part]
    return f"{parsed_url.scheme}://{parsed_url.netloc}".rstrip("/"), path_parts


def _normalize_azure_share_name(value: Any) -> str:
    share_name = _normalize_text(value, 255).lower()
    if not re.match(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$", share_name):
        raise ValueError("Azure Files share name must be 3-63 lowercase letters, numbers, or hyphens")
    return share_name


def _normalize_azure_directory_path(value: Any) -> str:
    directory_path = _normalize_text(value, 2048).replace("\\", "/").strip("/")
    if not directory_path:
        return ""
    parts = []
    for part in directory_path.split("/"):
        cleaned_part = part.strip()
        if not cleaned_part or cleaned_part in {".", ".."}:
            raise ValueError("Azure Files directory path contains an invalid segment")
        parts.append(cleaned_part)
    return "/".join(parts)


def _normalize_selected_path(value: Any) -> str:
    selected_path = _normalize_text(value, 2048).replace("\\", "/").strip("/")
    if not selected_path:
        return ""
    parts = []
    for part in selected_path.split("/"):
        cleaned_part = part.strip()
        if not cleaned_part or cleaned_part in {".", ".."}:
            raise ValueError("Selected sync paths must stay inside the configured source root")
        parts.append(cleaned_part)
    return "/".join(parts)


def _normalize_selected_paths(value: Any) -> List[str]:
    selected_paths = []
    seen_paths = set()
    for raw_path in parse_file_sync_list(value):
        selected_path = _normalize_selected_path(raw_path)
        if not selected_path:
            continue
        selected_key = selected_path.lower()
        if selected_key in seen_paths:
            continue
        seen_paths.add(selected_key)
        selected_paths.append(selected_path)
    return selected_paths


def _build_azure_files_url(account_url: str, share_name: str, file_path: str = "") -> str:
    path_segments = [share_name]
    if file_path:
        path_segments.extend(part for part in file_path.replace("\\", "/").split("/") if part)
    encoded_path = "/".join(quote(segment, safe="") for segment in path_segments)
    return f"{account_url.rstrip('/')}/{encoded_path}"


def _normalize_azure_files_connection(
    connection: Dict[str, Any],
    existing_connection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    connection = connection or {}
    existing_connection = existing_connection or {}
    raw_url = (
        connection.get("share_url")
        or connection.get("account_url")
        or connection.get("file_endpoint")
        or existing_connection.get("share_url")
        or existing_connection.get("account_url")
        or existing_connection.get("file_endpoint")
        or ""
    )
    account_url, url_path_parts = _normalize_azure_file_url(raw_url)
    if not account_url:
        raise ValueError("Azure Files sources require a file service URL such as https://account.file.core.windows.net")

    share_name = _normalize_text(connection.get("share_name", existing_connection.get("share_name", "")), 255)
    if not share_name and url_path_parts:
        share_name = url_path_parts[0]
    share_name = _normalize_azure_share_name(share_name)

    raw_directory_path = connection.get("directory_path", existing_connection.get("directory_path", ""))
    if not raw_directory_path and len(url_path_parts) > 1:
        raw_directory_path = "/".join(url_path_parts[1:])
    directory_path = _normalize_azure_directory_path(raw_directory_path)
    return {
        "account_url": account_url,
        "share_name": share_name,
        "directory_path": directory_path,
        "share_url": _build_azure_files_url(account_url, share_name, directory_path),
        "selected_paths": _normalize_selected_paths(connection.get("selected_paths", existing_connection.get("selected_paths", []))),
    }


def _normalize_onedrive_connection(
    connection: Dict[str, Any],
    existing_connection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    connection = connection or {}
    existing_connection = existing_connection or {}
    return {
        "selected_paths": _normalize_selected_paths(connection.get("selected_paths", existing_connection.get("selected_paths", []))),
    }


def _normalize_connection_payload(source_type: str, connection: Dict[str, Any], existing_connection: Dict[str, Any]) -> Dict[str, Any]:
    normalized_source_type = _normalize_source_type(source_type)
    if normalized_source_type == FILE_SYNC_SOURCE_TYPE_AZURE_FILES:
        return _normalize_azure_files_connection(connection, existing_connection)
    if normalized_source_type == FILE_SYNC_SOURCE_TYPE_ONEDRIVE:
        return _normalize_onedrive_connection(connection, existing_connection)
    return {
        "unc_path": _normalize_unc_path(connection.get("unc_path", existing_connection.get("unc_path", ""))),
        "selected_paths": _normalize_selected_paths(connection.get("selected_paths", existing_connection.get("selected_paths", []))),
    }


def _normalize_patterns(value: Any) -> List[str]:
    return parse_file_sync_list(value)


def _normalize_extensions(value: Any) -> List[str]:
    extensions = []
    for raw_extension in parse_file_sync_list(value):
        extension = raw_extension.strip().lower()
        if extension.startswith("*."):
            extension = extension[2:]
        if extension.startswith("."):
            extension = extension[1:]
        if re.match(r"^[a-z0-9]+$", extension):
            extensions.append(extension)
    return sorted(set(extensions))


def _safe_tag_from_text(value: Any) -> str:
    normalized_value = str(value or "").strip().lower()
    normalized_value = re.sub(r"[^a-z0-9_-]+", "-", normalized_value).strip("-")
    return normalized_value[:50]


def _normalize_tags(value: Any) -> List[str]:
    tag_candidates = [_safe_tag_from_text(tag) for tag in parse_file_sync_list(value)]
    tag_candidates = [tag for tag in tag_candidates if tag]
    is_valid, error_message, normalized_tags = validate_tags(tag_candidates)
    if not is_valid:
        raise ValueError(error_message or "Invalid sync tags")
    return normalized_tags


def _normalize_schedule(raw_schedule: Dict[str, Any], config: Dict[str, Any], existing_schedule: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw_schedule = raw_schedule or {}
    existing_schedule = existing_schedule or {}
    enabled = _as_bool(raw_schedule.get("enabled", existing_schedule.get("enabled", False)))
    interval_minutes = _safe_int(
        raw_schedule.get("interval_minutes", existing_schedule.get("interval_minutes")),
        config["file_sync_min_schedule_interval_minutes"],
        minimum=config["file_sync_min_schedule_interval_minutes"],
        maximum=10080,
    )
    next_run_at = existing_schedule.get("next_run_at")
    if enabled and not next_run_at:
        next_run_at = (_now() + timedelta(minutes=interval_minutes)).isoformat()
    if not enabled:
        next_run_at = None
    return {
        "enabled": enabled,
        "interval_minutes": interval_minutes,
        "next_run_at": next_run_at,
    }


def _prepare_auth_payload(
    scope_type: str,
    scope_id: str,
    source_id: str,
    source_type: str,
    raw_credentials: Dict[str, Any],
    existing_auth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw_credentials = raw_credentials or {}
    existing_auth = existing_auth or {}
    normalized_source_type = _normalize_source_type(source_type)
    if normalized_source_type == FILE_SYNC_SOURCE_TYPE_ONEDRIVE:
        return {"auth_type": "global_identity"}

    default_auth_type = _default_auth_type_for_source_type(normalized_source_type)
    auth_type = _normalize_text(raw_credentials.get("auth_type", existing_auth.get("auth_type", default_auth_type)), 50).lower()
    allowed_auth_types = _file_sync_auth_types_for_source_type(normalized_source_type)
    if auth_type not in allowed_auth_types:
        raise ValueError(f"{_source_type_label(normalized_source_type)} File Sync supports {', '.join(sorted(allowed_auth_types))} authentication")

    if normalized_source_type == FILE_SYNC_SOURCE_TYPE_AZURE_FILES:
        return _prepare_azure_files_auth_payload(scope_type, scope_id, source_id, raw_credentials, existing_auth, auth_type)

    username = _normalize_text(raw_credentials.get("username", existing_auth.get("username", "")), 255)
    domain = _normalize_text(raw_credentials.get("domain", existing_auth.get("domain", "")), 255)
    password = raw_credentials.get("password")
    prepared_auth = {
        "auth_type": auth_type,
        "username": username,
        "domain": domain,
    }

    if auth_type == "anonymous":
        return prepared_auth

    if password in [None, "", ui_trigger_word]:
        if existing_auth.get("password_secret_name"):
            prepared_auth["password_secret_name"] = existing_auth["password_secret_name"]
        elif existing_auth.get("password"):
            prepared_auth["password"] = existing_auth["password"]
        else:
            raise ValueError("SMB username/password sources require a password")
        return prepared_auth

    stored_password = _store_file_sync_secret(scope_type, scope_id, source_id, "password", str(password))
    if stored_password == str(password):
        prepared_auth["password"] = stored_password
    else:
        prepared_auth["password_secret_name"] = stored_password
    return prepared_auth


def _store_file_sync_secret(scope_type: str, scope_id: str, source_id: str, field_name: str, secret_value: str) -> str:
    settings = get_settings()
    if not _as_bool(settings.get("enable_key_vault_secret_storage")) or not str(settings.get("key_vault_name") or "").strip():
        return secret_value

    secret_name = f"file-sync-{source_id}-{field_name}"
    return store_secret_in_key_vault(
        secret_name=secret_name,
        secret_value=secret_value,
        scope_value=scope_id,
        source="file-sync",
        scope=_keyvault_scope(scope_type),
    )


def _get_file_sync_secret_value(raw_credentials: Dict[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        value = raw_credentials.get(field_name)
        if value not in [None, "", ui_trigger_word]:
            return value
    return None


def _prepare_azure_files_auth_payload(
    scope_type: str,
    scope_id: str,
    source_id: str,
    raw_credentials: Dict[str, Any],
    existing_auth: Dict[str, Any],
    auth_type: str,
) -> Dict[str, Any]:
    prepared_auth = {"auth_type": auth_type}
    if auth_type == "managed_identity":
        managed_identity_client_id = _normalize_text(
            raw_credentials.get("managed_identity_client_id", raw_credentials.get("client_id", existing_auth.get("managed_identity_client_id", ""))),
            255,
        )
        if managed_identity_client_id:
            prepared_auth["managed_identity_client_id"] = managed_identity_client_id
        return prepared_auth

    if auth_type == "client_secret":
        client_id = _normalize_text(raw_credentials.get("client_id", raw_credentials.get("identity", existing_auth.get("identity", ""))), 255)
        if not client_id:
            raise ValueError("Azure Files service principal identities require a client ID")
        prepared_auth["identity"] = client_id
        tenant_id = _normalize_text(raw_credentials.get("tenant_id", existing_auth.get("tenant_id", "")), 255)
        if tenant_id:
            prepared_auth["tenant_id"] = tenant_id
        secret_value = _get_file_sync_secret_value(raw_credentials, "secret", "client_secret", "password", "key")
        if secret_value in [None, "", ui_trigger_word]:
            if existing_auth.get("secret_secret_name"):
                prepared_auth["secret_secret_name"] = existing_auth["secret_secret_name"]
            elif existing_auth.get("secret"):
                prepared_auth["secret"] = existing_auth["secret"]
            else:
                raise ValueError("Azure Files service principal identities require a client secret")
            return prepared_auth
        return _store_prepared_secret(scope_type, scope_id, source_id, prepared_auth, "secret", str(secret_value))

    secret_value = _get_file_sync_secret_value(raw_credentials, "connection_string", "secret", "key")
    if secret_value in [None, "", ui_trigger_word]:
        if existing_auth.get("secret_secret_name"):
            prepared_auth["secret_secret_name"] = existing_auth["secret_secret_name"]
        elif existing_auth.get("secret"):
            prepared_auth["secret"] = existing_auth["secret"]
        else:
            raise ValueError("Azure Files connection string identities require a connection string")
        return prepared_auth
    return _store_prepared_secret(scope_type, scope_id, source_id, prepared_auth, "secret", str(secret_value))


def _store_prepared_secret(
    scope_type: str,
    scope_id: str,
    source_id: str,
    prepared_auth: Dict[str, Any],
    field_name: str,
    secret_value: str,
) -> Dict[str, Any]:
    stored_secret = _store_file_sync_secret(scope_type, scope_id, source_id, field_name, secret_value)
    if stored_secret == secret_value:
        prepared_auth[field_name] = stored_secret
    else:
        prepared_auth[f"{field_name}_secret_name"] = stored_secret
    return prepared_auth


def _normalize_source_payload(
    scope_type: str,
    scope_id: str,
    payload: Dict[str, Any],
    source_id: str,
    existing_source: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    existing_source = existing_source or {}
    config = get_file_sync_config()
    source_type = _normalize_source_type(payload.get("source_type", existing_source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB)))
    if source_type == FILE_SYNC_SOURCE_TYPE_ONEDRIVE and _validate_scope(scope_type) != FILE_SYNC_SCOPE_PERSONAL:
        raise ValueError("OneDrive File Sync sources can only be added to personal workspaces")

    connection = payload.get("connection") or {}
    existing_connection = existing_source.get("connection") or {}
    filters = payload.get("filters") or {}
    existing_filters = existing_source.get("filters") or {}
    schedule = payload.get("schedule") or {}
    existing_schedule = existing_source.get("schedule") or {}
    identity_id = _normalize_text(payload.get("identity_id", existing_source.get("identity_id", "")), 255)
    raw_delete_policy = _normalize_text(
        payload.get("remote_delete_policy", existing_source.get("remote_delete_policy", config["file_sync_default_remote_delete_policy"])),
        50,
    ).lower()

    folder_tag_mode = _normalize_text(
        filters.get("folder_tag_mode", existing_filters.get("folder_tag_mode", "parent")),
        50,
    ).lower()
    if folder_tag_mode not in FILE_SYNC_FOLDER_TAG_MODES:
        folder_tag_mode = "parent"

    normalized_source = {
        "name": _normalize_text(payload.get("name", existing_source.get("name", f"{_source_type_label(source_type)} File Sync Source")), 120),
        "source_type": source_type,
        "enabled": _as_bool(payload.get("enabled", existing_source.get("enabled", True))),
        "recursive": _as_bool(payload.get("recursive", existing_source.get("recursive", True))) and config["file_sync_allow_recursive_sources"],
        "connection": _normalize_connection_payload(source_type, connection, existing_connection),
        "filters": {
            "include_patterns": _normalize_patterns(filters.get("include_patterns", existing_filters.get("include_patterns", []))),
            "exclude_patterns": _normalize_patterns(filters.get("exclude_patterns", existing_filters.get("exclude_patterns", []))),
            "allowed_extensions": _normalize_extensions(filters.get("allowed_extensions", existing_filters.get("allowed_extensions", []))),
            "fixed_tags": _normalize_tags(filters.get("fixed_tags", existing_filters.get("fixed_tags", []))),
            "folder_tag_mode": folder_tag_mode,
        },
        "schedule": _normalize_schedule(schedule, config, existing_schedule),
        "remote_delete_policy": raw_delete_policy if raw_delete_policy in FILE_SYNC_REMOTE_DELETE_POLICIES else "ignore",
        "identity_id": identity_id,
    }
    if identity_id:
        _get_file_sync_identity(scope_type, scope_id, identity_id, source_type)
        normalized_source["auth"] = {}
    else:
        normalized_source["auth"] = _prepare_auth_payload(
            scope_type=scope_type,
            scope_id=scope_id,
            source_id=source_id,
            source_type=source_type,
            raw_credentials=payload.get("credentials") or payload.get("auth") or {},
            existing_auth=existing_source.get("auth") or {},
        )
    return normalized_source


def create_file_sync_source(scope_type: str, scope_id: str, payload: Dict[str, Any], created_by: str) -> Dict[str, Any]:
    scope_type = _validate_scope(scope_type)
    existing_sources = list_file_sync_sources(scope_type, scope_id)
    config = get_file_sync_config()
    if len(existing_sources) >= config["file_sync_max_sources_per_scope"]:
        raise ValueError("This workspace has reached the configured file sync source limit")

    source_id = str(uuid.uuid4())
    normalized_payload = _normalize_source_payload(scope_type, scope_id, payload or {}, source_id)
    scope_field = _scope_field(scope_type)
    now_iso = _now_iso()
    source = {
        "id": source_id,
        "source_id": source_id,
        "type": "file_sync_source",
        "scope_type": scope_type,
        scope_field: scope_id,
        "created_by": created_by,
        "updated_by": created_by,
        "created_at": now_iso,
        "updated_at": now_iso,
        "last_run_status": None,
        "last_run_at": None,
        **normalized_payload,
    }
    _get_sources_container(scope_type).create_item(body=source)
    _log_file_sync_activity(source, created_by, "source_created", {"source_name": source["name"]})
    return source


def update_file_sync_source(scope_type: str, scope_id: str, source_id: str, payload: Dict[str, Any], updated_by: str) -> Dict[str, Any]:
    source = get_authorized_sync_source(scope_type, source_id, updated_by, scope_id=scope_id)
    normalized_payload = _normalize_source_payload(scope_type, scope_id, payload or {}, source_id, existing_source=source)
    source.update(normalized_payload)
    source["updated_by"] = updated_by
    source["updated_at"] = _now_iso()
    _get_sources_container(scope_type).upsert_item(source)
    _log_file_sync_activity(source, updated_by, "source_updated", {"source_name": source["name"]})
    return source


def _prepare_connection_test_auth(
    source_type: str,
    raw_credentials: Dict[str, Any],
    existing_auth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw_credentials = raw_credentials or {}
    existing_auth = existing_auth or {}
    normalized_source_type = _normalize_source_type(source_type)
    if normalized_source_type == FILE_SYNC_SOURCE_TYPE_ONEDRIVE:
        return {"auth_type": "global_identity"}

    auth_type = _normalize_text(
        raw_credentials.get("auth_type", existing_auth.get("auth_type", _default_auth_type_for_source_type(normalized_source_type))),
        50,
    ).lower()
    allowed_auth_types = _file_sync_auth_types_for_source_type(normalized_source_type)
    if auth_type not in allowed_auth_types:
        raise ValueError(f"{_source_type_label(normalized_source_type)} File Sync supports {', '.join(sorted(allowed_auth_types))} authentication")

    if normalized_source_type == FILE_SYNC_SOURCE_TYPE_AZURE_FILES:
        return _prepare_connection_test_azure_files_auth(raw_credentials, existing_auth, auth_type)

    prepared_auth = {
        "auth_type": auth_type,
        "username": _normalize_text(raw_credentials.get("username", existing_auth.get("username", "")), 255),
        "domain": _normalize_text(raw_credentials.get("domain", existing_auth.get("domain", "")), 255),
    }
    if auth_type == "anonymous":
        return prepared_auth

    password = raw_credentials.get("password")
    if password in [None, "", ui_trigger_word]:
        if existing_auth.get("password_secret_name"):
            prepared_auth["password_secret_name"] = existing_auth["password_secret_name"]
        elif existing_auth.get("password"):
            prepared_auth["password"] = existing_auth["password"]
        else:
            raise ValueError("SMB username/password sources require a password")
    else:
        prepared_auth["password"] = str(password)
    return prepared_auth


def _prepare_connection_test_azure_files_auth(
    raw_credentials: Dict[str, Any],
    existing_auth: Dict[str, Any],
    auth_type: str,
) -> Dict[str, Any]:
    prepared_auth = {"auth_type": auth_type}
    if auth_type == "managed_identity":
        managed_identity_client_id = _normalize_text(
            raw_credentials.get("managed_identity_client_id", raw_credentials.get("client_id", existing_auth.get("managed_identity_client_id", ""))),
            255,
        )
        if managed_identity_client_id:
            prepared_auth["managed_identity_client_id"] = managed_identity_client_id
        return prepared_auth

    if auth_type == "client_secret":
        client_id = _normalize_text(raw_credentials.get("client_id", raw_credentials.get("identity", existing_auth.get("identity", ""))), 255)
        if not client_id:
            raise ValueError("Azure Files service principal identities require a client ID")
        prepared_auth["identity"] = client_id
        tenant_id = _normalize_text(raw_credentials.get("tenant_id", existing_auth.get("tenant_id", "")), 255)
        if tenant_id:
            prepared_auth["tenant_id"] = tenant_id
        secret_value = _get_file_sync_secret_value(raw_credentials, "secret", "client_secret", "password", "key")
        if secret_value in [None, "", ui_trigger_word]:
            if existing_auth.get("secret_secret_name"):
                prepared_auth["secret_secret_name"] = existing_auth["secret_secret_name"]
            elif existing_auth.get("secret"):
                prepared_auth["secret"] = existing_auth["secret"]
            else:
                raise ValueError("Azure Files service principal identities require a client secret")
        else:
            prepared_auth["secret"] = str(secret_value)
        return prepared_auth

    secret_value = _get_file_sync_secret_value(raw_credentials, "connection_string", "secret", "key")
    if secret_value in [None, "", ui_trigger_word]:
        if existing_auth.get("secret_secret_name"):
            prepared_auth["secret_secret_name"] = existing_auth["secret_secret_name"]
        elif existing_auth.get("secret"):
            prepared_auth["secret"] = existing_auth["secret"]
        else:
            raise ValueError("Azure Files connection string identities require a connection string")
    else:
        prepared_auth["secret"] = str(secret_value)
    return prepared_auth


def _build_connection_test_source(
    scope_type: str,
    scope_id: str,
    payload: Dict[str, Any],
    tested_by: str,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    existing_source = None
    if source_id:
        existing_source = get_authorized_sync_source(scope_type, source_id, tested_by, scope_id=scope_id)

    existing_source = existing_source or {}
    source_type = _normalize_source_type(payload.get("source_type", existing_source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB)))
    if source_type == FILE_SYNC_SOURCE_TYPE_ONEDRIVE and _validate_scope(scope_type) != FILE_SYNC_SCOPE_PERSONAL:
        raise ValueError("OneDrive File Sync sources can only be used with personal workspaces")

    connection = payload.get("connection") or {}
    existing_connection = existing_source.get("connection") or {}
    config = get_file_sync_config()
    test_source_id = source_id or "connection-test"
    identity_id = _normalize_text(payload.get("identity_id", existing_source.get("identity_id", "")), 255)
    auth = {}
    if identity_id:
        _get_file_sync_identity(scope_type, scope_id, identity_id, source_type)
        auth = get_workspace_identity_auth(scope_type, scope_id, identity_id)
    else:
        auth = _prepare_connection_test_auth(
            source_type,
            payload.get("credentials") or payload.get("auth") or {},
            existing_source.get("auth") or {},
        )
    return {
        "id": test_source_id,
        "source_id": test_source_id,
        "scope_type": _validate_scope(scope_type),
        _scope_field(scope_type): scope_id,
        "source_type": source_type,
        "name": _normalize_text(payload.get("name", existing_source.get("name", f"{_source_type_label(source_type)} File Sync Source")), 120),
        "identity_id": identity_id,
        "recursive": _as_bool(payload.get("recursive", existing_source.get("recursive", True))) and config["file_sync_allow_recursive_sources"],
        "connection": _normalize_connection_payload(source_type, connection, existing_connection),
        "auth": auth,
    }


def test_file_sync_source_connection(
    scope_type: str,
    scope_id: str,
    payload: Dict[str, Any],
    tested_by: str,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    source = _build_connection_test_source(scope_type, scope_id, payload or {}, tested_by, source_id=source_id)
    if source.get("source_type") == FILE_SYNC_SOURCE_TYPE_ONEDRIVE:
        return _test_onedrive_connection(source)
    if source.get("source_type") == FILE_SYNC_SOURCE_TYPE_AZURE_FILES:
        return _test_azure_files_connection(source)

    try:
        smbclient = _register_smb_session(source)
        root_path = source.get("connection", {}).get("unc_path", "")
        entries_checked = 0
        files_seen = 0
        folders_seen = 0
        for entry in smbclient.scandir(root_path):
            entries_checked += 1
            if entry.is_dir():
                folders_seen += 1
            elif entry.is_file():
                files_seen += 1
            if entries_checked >= 25:
                break
        return {
            "success": True,
            "source_type": source["source_type"],
            "recursive": source.get("recursive", True),
            "entries_checked": entries_checked,
            "files_seen": files_seen,
            "folders_seen": folders_seen,
        }
    except RuntimeError as error:
        if "smbprotocol" in str(error):
            raise
        raise ValueError("SMB connection test failed. Verify the UNC path and credentials.") from error
    except Exception as error:
        raise ValueError("SMB connection test failed. Verify the UNC path and credentials.") from error


def browse_file_sync_source_path(
    scope_type: str,
    scope_id: str,
    payload: Dict[str, Any],
    browsed_by: str,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    source = _build_connection_test_source(scope_type, scope_id, payload or {}, browsed_by, source_id=source_id)
    browse_path = _normalize_selected_path((payload or {}).get("browse_path") or (payload or {}).get("path") or "")
    if source.get("source_type") == FILE_SYNC_SOURCE_TYPE_ONEDRIVE:
        entries = _browse_onedrive_path(source, browse_path)
    elif source.get("source_type") == FILE_SYNC_SOURCE_TYPE_AZURE_FILES:
        entries = _browse_azure_files_path(source, browse_path)
    else:
        entries = _browse_smb_path(source, browse_path)
    return {
        "success": True,
        "source_type": source.get("source_type"),
        "path": browse_path,
        "entries": entries,
    }


def _test_azure_files_connection(source: Dict[str, Any]) -> Dict[str, Any]:
    try:
        share_client = _get_azure_files_share_client(source)
        directory_path = source.get("connection", {}).get("directory_path") or None
        entries_checked = 0
        files_seen = 0
        folders_seen = 0
        for entry in share_client.list_directories_and_files(directory_name=directory_path):
            entries_checked += 1
            if _azure_files_item_is_directory(entry):
                folders_seen += 1
            else:
                files_seen += 1
            if entries_checked >= 25:
                break
        return {
            "success": True,
            "source_type": source["source_type"],
            "recursive": source.get("recursive", True),
            "entries_checked": entries_checked,
            "files_seen": files_seen,
            "folders_seen": folders_seen,
        }
    except RuntimeError as error:
        if "azure-storage-file-share" in str(error):
            raise
        raise ValueError("Azure Files connection test failed. Verify the file endpoint, share, and identity permissions.") from error
    except Exception as error:
        raise ValueError("Azure Files connection test failed. Verify the file endpoint, share, and identity permissions.") from error


def delete_file_sync_source(scope_type: str, scope_id: str, source_id: str, deleted_by: str, delete_associated_files: bool = False) -> Dict[str, Any]:
    source = get_authorized_sync_source(scope_type, source_id, deleted_by, scope_id=scope_id)
    delete_result = {
        "associated_files_requested": bool(delete_associated_files),
        "documents_deleted": 0,
        "documents_skipped": 0,
        "documents_failed": 0,
    }
    if delete_associated_files:
        delete_result = _delete_associated_synced_documents(source)
    _get_sources_container(scope_type).delete_item(item=source_id, partition_key=scope_id)
    _log_file_sync_activity(
        source,
        deleted_by,
        "source_deleted",
        {
            "source_name": source.get("name"),
            "delete_associated_files": bool(delete_associated_files),
            **delete_result,
        },
    )
    return delete_result


def _delete_associated_synced_documents(source: Dict[str, Any]) -> Dict[str, Any]:
    delete_result = {
        "associated_files_requested": True,
        "documents_deleted": 0,
        "documents_skipped": 0,
        "documents_failed": 0,
    }
    document_ids = []
    seen_document_ids = set()
    for item in _load_existing_items(source).values():
        document_id = str(item.get("document_id") or "").strip()
        if not document_id or document_id in seen_document_ids:
            continue
        seen_document_ids.add(document_id)
        document_ids.append(document_id)

    failed_document_ids = []
    for document_id in document_ids:
        try:
            _delete_synced_document(source, document_id)
            delete_result["documents_deleted"] += 1
        except CosmosResourceNotFoundError:
            delete_result["documents_skipped"] += 1
        except Exception as error:
            if "Document not found" in str(error):
                delete_result["documents_skipped"] += 1
                continue
            failed_document_ids.append(document_id)
            delete_result["documents_failed"] += 1
            log_event(
                f"[FileSync] Failed to delete synced document during source deletion: {error}",
                level=logging.WARNING,
            )

    if failed_document_ids:
        raise ValueError(
            "Could not delete all associated synced files. "
            f"Deleted {delete_result['documents_deleted']}, failed {delete_result['documents_failed']}. "
            "The File Sync source was not deleted."
        )
    return delete_result


def _item_id_for_path(source_id: str, remote_path: str) -> str:
    path_hash = hashlib.sha256(_normalize_remote_path(remote_path).lower().encode("utf-8")).hexdigest()
    return f"{source_id}-{path_hash}"


def _normalize_remote_path(path_value: Any) -> str:
    return str(path_value or "").replace("/", "\\").strip()


def set_file_sync_path_ignored(source: Dict[str, Any], remote_path: str, ignored: bool, updated_by: str) -> Dict[str, Any]:
    source_id = source["id"]
    normalized_remote_path = _normalize_remote_path(remote_path)
    if not normalized_remote_path:
        raise ValueError("remote_path is required")

    container = _get_items_container(source["scope_type"])
    item_id = _item_id_for_path(source_id, normalized_remote_path)
    try:
        item = container.read_item(item=item_id, partition_key=source_id)
    except CosmosResourceNotFoundError:
        item = {
            "id": item_id,
            "type": "file_sync_item",
            "source_id": source_id,
            "scope_type": source["scope_type"],
            _scope_field(source["scope_type"]): _source_scope_id(source),
            "remote_path": normalized_remote_path,
            "status": "ignored" if ignored else "pending",
            "created_at": _now_iso(),
        }

    item["ignored"] = bool(ignored)
    item["status"] = "ignored" if ignored else item.get("status", "pending")
    item["updated_by"] = updated_by
    item["updated_at"] = _now_iso()
    container.upsert_item(item)
    return item


def list_file_sync_runs(scope_type: str, source_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    scope_type = _validate_scope(scope_type)
    limit = _safe_int(limit, 20, minimum=1, maximum=100)
    query = f"SELECT TOP {limit} * FROM c WHERE c.source_id = @source_id ORDER BY c.started_at DESC"
    return list(
        _get_runs_container(scope_type).query_items(
            query=query,
            parameters=[
                {"name": "@source_id", "value": source_id},
            ],
            partition_key=source_id,
        )
    )


def _create_run(source: Dict[str, Any], triggered_by: Optional[str], trigger: str) -> Dict[str, Any]:
    run_id = str(uuid.uuid4())
    run = {
        "id": run_id,
        "run_id": run_id,
        "type": "file_sync_run",
        "source_id": source["id"],
        "source_name": source.get("name"),
        "scope_type": source["scope_type"],
        _scope_field(source["scope_type"]): _source_scope_id(source),
        "trigger": trigger,
        "triggered_by": triggered_by,
        "status": "queued",
        "started_at": _now_iso(),
        "completed_at": None,
        "counts": {
            "scanned": 0,
            "queued": 0,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped": 0,
            "deleted": 0,
            "failed": 0,
            "bytes_queued": 0,
        },
        "changed_documents": [],
        "changed_document_ids": [],
    }
    _get_runs_container(source["scope_type"]).create_item(body=run)
    return run


def _update_run(run: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    run.update(fields)
    _get_runs_container(run["scope_type"]).upsert_item(run)
    return run


def queue_file_sync_source_run(source: Dict[str, Any], triggered_by: Optional[str], trigger: str = "manual", run_inline: bool = False) -> Dict[str, Any]:
    config = get_file_sync_config()
    if _count_active_runs() >= config["file_sync_max_concurrent_runs"]:
        raise ValueError("The configured File Sync concurrent run limit has been reached")
    if _source_has_active_run(source):
        raise ValueError("This File Sync source already has a queued or running sync")

    run = _create_run(source, triggered_by, trigger)
    if run_inline:
        return process_file_sync_run_by_id(source["scope_type"], _source_scope_id(source), source["id"], run["id"], triggered_by, trigger)

    if has_app_context():
        executor = current_app.extensions.get("executor")
        if executor and hasattr(executor, "submit_stored"):
            executor.submit_stored(
                run["id"],
                process_file_sync_run_by_id,
                scope_type=source["scope_type"],
                scope_id=_source_scope_id(source),
                source_id=source["id"],
                run_id=run["id"],
                triggered_by=triggered_by,
                trigger=trigger,
            )
            return run
        if executor and hasattr(executor, "submit"):
            executor.submit(
                process_file_sync_run_by_id,
                source["scope_type"],
                _source_scope_id(source),
                source["id"],
                run["id"],
                triggered_by,
                trigger,
            )
            return run

    process_file_sync_run_by_id(source["scope_type"], _source_scope_id(source), source["id"], run["id"], triggered_by, trigger)
    return run


def process_file_sync_run_by_id(
    scope_type: str,
    scope_id: str,
    source_id: str,
    run_id: str,
    triggered_by: Optional[str] = None,
    trigger: str = "manual",
) -> Dict[str, Any]:
    source = _get_sources_container(scope_type).read_item(item=source_id, partition_key=scope_id)
    run = _get_runs_container(scope_type).read_item(item=run_id, partition_key=source_id)
    return _process_file_sync_source(source, run, triggered_by=triggered_by, trigger=trigger)


def _load_existing_items(source: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    source_id = source["id"]
    query = "SELECT * FROM c WHERE c.source_id = @source_id"
    items = list(
        _get_items_container(source["scope_type"]).query_items(
            query=query,
            parameters=[{"name": "@source_id", "value": source_id}],
            partition_key=source_id,
        )
    )
    return {item.get("id"): item for item in items}


def _process_file_sync_source(
    source: Dict[str, Any],
    run: Dict[str, Any],
    triggered_by: Optional[str],
    trigger: str,
) -> Dict[str, Any]:
    debug_file_sync(f"Starting file sync run {run['id']} for source {source.get('name')}")
    run = _update_run(run, {"status": "running", "started_at": _now_iso()})
    counts = dict(run.get("counts") or {})
    config = get_file_sync_config()

    try:
        if not config["enable_file_sync"]:
            raise RuntimeError("File sync is disabled or Redis is not configured")
        if not source.get("enabled", True):
            raise RuntimeError("File sync source is disabled")

        existing_items = _load_existing_items(source)
        remote_files = _list_remote_files(source, config)
        remote_item_ids = set()
        bytes_queued = 0
        changed_documents = []

        for remote_file in remote_files:
            counts["scanned"] = counts.get("scanned", 0) + 1
            item_id = _item_id_for_path(source["id"], remote_file["remote_path"])
            remote_item_ids.add(item_id)
            existing_item = existing_items.get(item_id)
            if existing_item and existing_item.get("ignored"):
                counts["skipped"] = counts.get("skipped", 0) + 1
                continue

            if not _file_matches_filters(remote_file, source.get("filters") or {}):
                counts["skipped"] = counts.get("skipped", 0) + 1
                continue

            if counts.get("queued", 0) >= config["file_sync_max_files_per_run"]:
                counts["skipped"] = counts.get("skipped", 0) + 1
                continue
            if bytes_queued + remote_file.get("size", 0) > config["file_sync_max_bytes_per_run"]:
                counts["skipped"] = counts.get("skipped", 0) + 1
                continue

            if _remote_file_unchanged(existing_item, remote_file):
                counts["unchanged"] = counts.get("unchanged", 0) + 1
                _apply_sync_tags_to_existing_document(source, existing_item, remote_file)
                _touch_item(source, existing_item, remote_file, "unchanged")
                continue

            try:
                temp_file_path, content_hash = _stage_remote_file(source, remote_file)
                if existing_item and existing_item.get("content_hash") == content_hash:
                    counts["unchanged"] = counts.get("unchanged", 0) + 1
                    remote_file["content_hash"] = content_hash
                    _apply_sync_tags_to_existing_document(source, existing_item, remote_file)
                    _touch_item(source, existing_item, remote_file, "unchanged")
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                    continue

                remote_file["content_hash"] = content_hash
                sync_action = "updated" if existing_item and existing_item.get("document_id") else "created"
                document_id = _create_document_from_remote_file(source, remote_file, temp_file_path)
                _upsert_synced_item(
                    source,
                    existing_item,
                    remote_file,
                    document_id,
                    status="synced",
                    run_id=run["id"],
                    sync_action=sync_action,
                )
                counts["queued"] = counts.get("queued", 0) + 1
                counts[sync_action] = counts.get(sync_action, 0) + 1
                bytes_queued += remote_file.get("size", 0)
                counts["bytes_queued"] = bytes_queued
                changed_documents.append({
                    "document_id": document_id,
                    "action": sync_action,
                    "file_name": remote_file.get("file_name"),
                    "relative_path": remote_file.get("relative_path"),
                    "remote_path": remote_file.get("remote_path"),
                    "remote_modified_at": remote_file.get("modified_at"),
                    "remote_size": remote_file.get("size"),
                })
            except Exception as item_error:
                counts["failed"] = counts.get("failed", 0) + 1
                _upsert_failed_item(source, existing_item, remote_file, item_error, run_id=run["id"])
                log_event(
                    f"[FileSync] Error syncing {remote_file.get('remote_path')}: {item_error}",
                    level=logging.ERROR,
                    exceptionTraceback=True,
                )

        _handle_remote_deletes(source, existing_items, remote_item_ids, counts)
        _invalidate_scope_search_cache(source)

        completed_at = _now_iso()
        run = _update_run(
            run,
            {
                "status": "completed" if counts.get("failed", 0) == 0 else "completed_with_errors",
                "counts": counts,
                "changed_documents": changed_documents,
                "changed_document_ids": [item.get("document_id") for item in changed_documents if item.get("document_id")],
                "completed_at": completed_at,
            },
        )
        _update_source_after_run(source, run)
        _log_file_sync_activity(source, triggered_by, "run_completed", {"run_id": run["id"], "counts": counts})
        return run
    except Exception as error:
        error_message = str(error)
        run = _update_run(
            run,
            {
                "status": "failed",
                "counts": counts,
                "completed_at": _now_iso(),
                "error_message": error_message,
            },
        )
        _update_source_after_run(source, run)
        _log_file_sync_activity(source, triggered_by, "run_failed", {"run_id": run["id"], "error": error_message})
        log_event(f"[FileSync] Run failed for source {source.get('id')}: {error_message}", level=logging.ERROR, exceptionTraceback=True)
        return run


def _parse_unc_server(unc_path: str) -> str:
    parts = [part for part in unc_path.strip("\\").split("\\") if part]
    if len(parts) < 2:
        raise ValueError("SMB UNC path must include a server and share")
    return parts[0]


def _join_smb_path(parent_path: str, child_name: str) -> str:
    return parent_path.rstrip("\\") + "\\" + child_name.strip("\\")


def _relative_remote_path(root_path: str, remote_path: str) -> str:
    root = root_path.rstrip("\\") + "\\"
    if remote_path.lower().startswith(root.lower()):
        return remote_path[len(root):]
    return remote_path.strip("\\").split("\\")[-1]


def _count_active_runs() -> int:
    total_runs = 0
    query = "SELECT VALUE COUNT(1) FROM c WHERE c.status IN ('queued', 'running')"
    for scope_type in FILE_SYNC_SCOPES:
        try:
            result = list(
                _get_runs_container(scope_type).query_items(
                    query=query,
                    enable_cross_partition_query=True,
                )
            )
            total_runs += int(result[0] if result else 0)
        except Exception as error:
            log_event(f"[FileSync] Unable to count active runs: {error}", level=logging.WARNING)
    return total_runs


def _source_has_active_run(source: Dict[str, Any]) -> bool:
    query = "SELECT VALUE COUNT(1) FROM c WHERE c.source_id = @source_id AND c.status IN ('queued', 'running')"
    try:
        result = list(
            _get_runs_container(source["scope_type"]).query_items(
                query=query,
                parameters=[{"name": "@source_id", "value": source["id"]}],
                partition_key=source["id"],
            )
        )
        return int(result[0] if result else 0) > 0
    except Exception as error:
        log_event(f"[FileSync] Unable to count source active runs: {error}", level=logging.WARNING)
        return False


def _get_smb_credentials(source: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    auth = _get_identity_auth_for_source(source) or source.get("auth") or {}
    if auth.get("auth_type") == "anonymous":
        return None, None

    username = auth.get("username") or None
    domain = auth.get("domain") or ""
    if username and domain and "\\" not in username and "@" not in username:
        username = f"{domain}\\{username}"

    if auth.get("password_secret_name"):
        password = retrieve_secret_from_key_vault_by_full_name(auth["password_secret_name"])
    else:
        password = auth.get("password")
    return username, password


def _register_smb_session(source: Dict[str, Any]):
    try:
        import smbclient
    except ImportError as import_error:
        raise RuntimeError("SMB file sync requires the smbprotocol package to be installed") from import_error

    unc_path = source.get("connection", {}).get("unc_path", "")
    server = _parse_unc_server(unc_path)
    username, password = _get_smb_credentials(source)
    if username or password:
        smbclient.register_session(server, username=username, password=password)
    else:
        smbclient.register_session(server)
    return smbclient


def _list_remote_files(source: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    source_type = source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB)
    if source_type == FILE_SYNC_SOURCE_TYPE_ONEDRIVE:
        return _list_onedrive_files(source, config)
    if source_type == FILE_SYNC_SOURCE_TYPE_AZURE_FILES:
        return _list_azure_files(source, config)
    return _list_smb_files(source, config)


def _stage_remote_file(source: Dict[str, Any], remote_file: Dict[str, Any]) -> Tuple[str, str]:
    if source.get("source_type") == FILE_SYNC_SOURCE_TYPE_ONEDRIVE:
        return _stage_onedrive_file(source, remote_file)
    if source.get("source_type") == FILE_SYNC_SOURCE_TYPE_AZURE_FILES:
        return _stage_azure_files_file(source, remote_file)
    return _stage_smb_file(source, remote_file["remote_path"], remote_file["file_name"])


def _graph_app_scope() -> str:
    graph_base = get_graph_base_url().rstrip("/")
    if graph_base.lower().endswith("/v1.0"):
        graph_base = graph_base[:-5]
    return f"{graph_base}/.default"


def _get_global_file_sync_identity_auth(source_type: str) -> Dict[str, Any]:
    normalized_source_type = _normalize_source_type(source_type)
    try:
        identities = list_workspace_identities(WORKSPACE_IDENTITY_SCOPE_GLOBAL, WORKSPACE_IDENTITY_SCOPE_GLOBAL)
    except Exception as error:
        log_event(f"[FileSync] Unable to list global connector identities: {error}", level=logging.WARNING)
        return {}

    for identity in identities:
        if identity_supports_usage(
            identity,
            "file_sync",
            source_type=normalized_source_type,
            auth_types={"client_secret"},
        ):
            return get_workspace_identity_auth(
                WORKSPACE_IDENTITY_SCOPE_GLOBAL,
                WORKSPACE_IDENTITY_SCOPE_GLOBAL,
                identity["id"],
            )
    return {}


def _resolve_graph_app_credentials(source_type: str) -> Dict[str, str]:
    identity_auth = _get_global_file_sync_identity_auth(source_type)
    if identity_auth:
        client_id = str(identity_auth.get("identity") or "").strip()
        client_secret = _resolved_auth_secret(identity_auth)
        tenant_id = str(identity_auth.get("tenant_id") or TENANT_ID or "").strip()
        if client_id and client_secret and tenant_id:
            return {
                "client_id": client_id,
                "client_secret": client_secret,
                "tenant_id": tenant_id,
                "source": "global_identity",
            }

    if CLIENT_ID and CLIENT_SECRET:
        return {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "tenant_id": TENANT_ID,
            "source": "application_config",
        }

    raise ValueError(
        "OneDrive File Sync requires an admin-managed global File Sync identity "
        "with client-secret Microsoft Graph application permissions."
    )


def _authority_for_tenant(tenant_id: str) -> str:
    configured_authority = get_graph_authority().rstrip("/")
    if configured_authority.endswith(f"/{TENANT_ID}"):
        return configured_authority[: -(len(str(TENANT_ID)) + 1)] + f"/{tenant_id}"
    return configured_authority


def _get_graph_app_token(source_type: str = FILE_SYNC_SOURCE_TYPE_ONEDRIVE) -> str:
    credentials = _resolve_graph_app_credentials(source_type)
    msal_app = ConfidentialClientApplication(
        credentials["client_id"],
        authority=_authority_for_tenant(credentials["tenant_id"]),
        client_credential=credentials["client_secret"],
    )
    token_result = msal_app.acquire_token_for_client(scopes=[_graph_app_scope()])
    access_token = token_result.get("access_token") if isinstance(token_result, dict) else None
    if not access_token:
        error_description = token_result.get("error_description") if isinstance(token_result, dict) else "Unknown token error"
        raise ValueError(f"Unable to acquire Microsoft Graph application token for OneDrive File Sync: {error_description}")
    return access_token


def _onedrive_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_graph_app_token()}",
        "Accept": "application/json",
    }


def _graph_get_json(path_or_url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = path_or_url if str(path_or_url or "").startswith("http") else get_graph_endpoint(path_or_url)
    response = requests.get(url, headers=_onedrive_headers(), params=params, timeout=30)
    if response.status_code >= 400:
        try:
            error_body = response.json()
        except ValueError:
            error_body = {}
        graph_error = error_body.get("error", {}) if isinstance(error_body, dict) else {}
        graph_message = graph_error.get("message") or response.text or "Microsoft Graph request failed"
        if response.status_code in {401, 403}:
            raise PermissionError(
                "OneDrive File Sync needs Microsoft Graph application permissions such as Files.Read.All. "
                f"Graph returned {response.status_code}: {graph_message}"
            )
        raise ValueError(f"Microsoft Graph request failed with {response.status_code}: {graph_message}")
    return response.json()


def _quote_graph_path(path_value: str) -> str:
    return "/".join(quote(part, safe="") for part in str(path_value or "").split("/") if part)


def _onedrive_user_path(source: Dict[str, Any], suffix: str) -> str:
    user_id = quote(_source_scope_id(source), safe="")
    return f"/users/{user_id}{suffix}"


def _onedrive_item_path(source: Dict[str, Any], selected_path: str = "") -> str:
    if not selected_path:
        return _onedrive_user_path(source, "/drive/root")
    return _onedrive_user_path(source, f"/drive/root:/{_quote_graph_path(selected_path)}")


def _onedrive_children_path(source: Dict[str, Any], item_id: Optional[str] = None, selected_path: str = "") -> str:
    if item_id:
        return _onedrive_user_path(source, f"/drive/items/{quote(item_id, safe='')}/children")
    if not selected_path:
        return _onedrive_user_path(source, "/drive/root/children")
    return _onedrive_user_path(source, f"/drive/root:/{_quote_graph_path(selected_path)}:/children")


def _onedrive_relative_path(item: Dict[str, Any], fallback_path: str = "") -> str:
    item_name = str(item.get("name") or "")
    parent_reference = item.get("parentReference") or {}
    parent_path = str(parent_reference.get("path") or "")
    relative_parent = ""
    marker = "/drive/root:"
    if marker in parent_path:
        relative_parent = parent_path.split(marker, 1)[1].strip("/")
    if relative_parent and item_name:
        return f"{relative_parent}/{item_name}".strip("/")
    if fallback_path and item_name and fallback_path.split("/")[-1] != item_name:
        return f"{fallback_path.strip('/')}/{item_name}".strip("/")
    return fallback_path.strip("/") or item_name


def _onedrive_remote_file_from_item(item: Dict[str, Any], fallback_path: str = "") -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict) or not item.get("file"):
        return None
    item_id = str(item.get("id") or "").strip()
    item_name = str(item.get("name") or "").strip()
    parent_reference = item.get("parentReference") or {}
    drive_id = str(parent_reference.get("driveId") or "").strip()
    if not item_id or not item_name:
        return None
    change_token = item.get("eTag") or item.get("cTag") or item.get("lastModifiedDateTime")
    return {
        "remote_path": f"onedrive://{drive_id or 'drive'}/{item_id}",
        "relative_path": _onedrive_relative_path(item, fallback_path),
        "file_name": item_name,
        "size": int(item.get("size") or 0),
        "modified_at": item.get("lastModifiedDateTime"),
        "remote_change_token": change_token,
        "onedrive_item_id": item_id,
        "onedrive_drive_id": drive_id,
        "web_url": item.get("webUrl"),
    }


def _iter_onedrive_children(source: Dict[str, Any], item_id: Optional[str] = None, selected_path: str = "", max_items: int = 1000) -> List[Dict[str, Any]]:
    params = {
        "$top": 200,
        "$select": "id,name,size,lastModifiedDateTime,eTag,cTag,file,folder,parentReference,webUrl",
        "$orderby": "name",
    }
    next_url = _onedrive_children_path(source, item_id=item_id, selected_path=selected_path)
    items = []
    while next_url and len(items) < max_items:
        payload = _graph_get_json(next_url, params=params if not str(next_url).startswith("http") else None)
        items.extend(payload.get("value") or [])
        next_url = payload.get("@odata.nextLink")
    return items[:max_items]


def _browse_onedrive_path(source: Dict[str, Any], browse_path: str) -> List[Dict[str, Any]]:
    entries = []
    for item in _iter_onedrive_children(source, selected_path=browse_path, max_items=100):
        item_name = str(item.get("name") or "")
        if not item_name:
            continue
        relative_path = _onedrive_relative_path(item, browse_path)
        entries.append(
            {
                "name": item_name,
                "path": relative_path,
                "type": "folder" if item.get("folder") else "file",
                "size": int(item.get("size") or 0),
                "modified_at": item.get("lastModifiedDateTime"),
            }
        )
    return entries


def _test_onedrive_connection(source: Dict[str, Any]) -> Dict[str, Any]:
    try:
        entries = _browse_onedrive_path(source, "")
        return {
            "success": True,
            "source_type": source["source_type"],
            "recursive": source.get("recursive", True),
            "entries_checked": len(entries),
            "files_seen": len([entry for entry in entries if entry.get("type") == "file"]),
            "folders_seen": len([entry for entry in entries if entry.get("type") == "folder"]),
        }
    except PermissionError:
        raise
    except Exception as error:
        raise ValueError("OneDrive connection test failed. Verify Microsoft Graph application permissions and user drive access.") from error


def _list_onedrive_files(source: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    selected_paths = source.get("connection", {}).get("selected_paths") or [""]
    recursive_enabled = bool(source.get("recursive", True) and config.get("file_sync_allow_recursive_sources", True))
    max_items = config["file_sync_max_files_per_run"] * 2
    remote_files = []
    seen_item_ids = set()

    def add_file(item: Dict[str, Any], fallback_path: str = "") -> None:
        if len(remote_files) >= max_items:
            return
        remote_file = _onedrive_remote_file_from_item(item, fallback_path)
        if not remote_file:
            return
        item_id = remote_file.get("onedrive_item_id")
        if item_id in seen_item_ids:
            return
        seen_item_ids.add(item_id)
        remote_files.append(remote_file)

    def walk_folder(item_id: Optional[str] = None, selected_path: str = "") -> None:
        if len(remote_files) >= max_items:
            return
        for child in _iter_onedrive_children(source, item_id=item_id, selected_path=selected_path, max_items=max_items):
            if child.get("folder"):
                if recursive_enabled:
                    walk_folder(item_id=child.get("id"), selected_path=_onedrive_relative_path(child, selected_path))
                continue
            add_file(child, selected_path)

    for selected_path in selected_paths:
        if len(remote_files) >= max_items:
            break
        if not selected_path:
            walk_folder(selected_path="")
            continue
        item = _graph_get_json(
            _onedrive_item_path(source, selected_path),
            params={"$select": "id,name,size,lastModifiedDateTime,eTag,cTag,file,folder,parentReference,webUrl"},
        )
        if item.get("folder"):
            walk_folder(item_id=item.get("id"), selected_path=selected_path)
        else:
            add_file(item, selected_path)
    return remote_files


def _stage_onedrive_file(source: Dict[str, Any], remote_file: Dict[str, Any]) -> Tuple[str, str]:
    item_id = str(remote_file.get("onedrive_item_id") or "").strip()
    if not item_id:
        raise ValueError("OneDrive file is missing its drive item ID")
    suffix = os.path.splitext(remote_file.get("file_name") or "")[1] or ".bin"
    temp_dir = "/sc-temp-files" if os.path.exists("/sc-temp-files") else None
    sha256_hash = hashlib.sha256()
    download_url = get_graph_endpoint(_onedrive_user_path(source, f"/drive/items/{quote(item_id, safe='')}/content"))
    response = requests.get(download_url, headers={"Authorization": f"Bearer {_get_graph_app_token()}"}, stream=True, timeout=120, allow_redirects=True)
    if response.status_code >= 400:
        raise ValueError(f"OneDrive file download failed with {response.status_code}")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir) as temp_file:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            temp_file.write(chunk)
            sha256_hash.update(chunk)
        return temp_file.name, sha256_hash.hexdigest()


def _get_azure_files_service_client(source: Dict[str, Any]):
    try:
        from azure.storage.fileshare import ShareServiceClient
    except ImportError as import_error:
        raise RuntimeError("Azure Files sync requires the azure-storage-file-share package to be installed") from import_error

    connection = source.get("connection") or {}
    auth = _get_identity_auth_for_source(source) or source.get("auth") or {}
    auth_type = _normalize_text(auth.get("auth_type"), 50).lower() or "managed_identity"
    if auth_type == "connection_string":
        connection_string = _resolved_auth_secret(auth)
        if not connection_string:
            raise ValueError("Azure Files connection string authentication requires a connection string")
        return ShareServiceClient.from_connection_string(connection_string)

    account_url = connection.get("account_url") or ""
    if not account_url:
        raise ValueError("Azure Files source is missing an account URL")
    if auth_type == "client_secret":
        client_id = auth.get("identity") or ""
        client_secret = _resolved_auth_secret(auth)
        tenant_id = auth.get("tenant_id") or TENANT_ID
        if not tenant_id or not client_id or not client_secret:
            raise ValueError("Azure Files service principal authentication requires tenant ID, client ID, and client secret")
        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
    elif auth_type == "managed_identity":
        credential = DefaultAzureCredential(managed_identity_client_id=auth.get("managed_identity_client_id") or None)
    else:
        raise ValueError("Azure Files sources require managed identity, service principal, or connection string authentication")
    return ShareServiceClient(account_url=account_url, credential=credential)


def _get_azure_files_share_client(source: Dict[str, Any]):
    connection = source.get("connection") or {}
    share_name = connection.get("share_name") or ""
    if not share_name:
        raise ValueError("Azure Files source is missing a share name")
    return _get_azure_files_service_client(source).get_share_client(share_name)


def _resolved_auth_secret(auth: Dict[str, Any]) -> str:
    if auth.get("secret_secret_name"):
        return retrieve_secret_from_key_vault_by_full_name(auth["secret_secret_name"])
    return str(auth.get("secret") or "")


def _azure_files_item_is_directory(item: Any) -> bool:
    return bool(item.get("is_directory") if hasattr(item, "get") else getattr(item, "is_directory", False))


def _azure_files_item_name(item: Any) -> str:
    name_value = item.get("name") if hasattr(item, "get") else getattr(item, "name", "")
    return str(name_value or "")


def _azure_files_item_size(item: Any) -> int:
    if hasattr(item, "get"):
        size_value = item.get("size") or item.get("content_length") or 0
    else:
        size_value = getattr(item, "size", None) or getattr(item, "content_length", 0) or 0
    try:
        return int(size_value or 0)
    except Exception:
        return 0


def _azure_files_item_modified_at(item: Any) -> Optional[str]:
    modified_value = None
    if hasattr(item, "get"):
        modified_value = item.get("last_modified") or item.get("last_write_time") or item.get("change_time")
    else:
        modified_value = getattr(item, "last_modified", None) or getattr(item, "last_write_time", None) or getattr(item, "change_time", None)
    return _format_smb_modified_at(modified_value)


def _azure_files_item_change_token(item: Any) -> Optional[str]:
    if hasattr(item, "get"):
        return item.get("etag") or item.get("ETag")
    return getattr(item, "etag", None) or getattr(item, "ETag", None)


def _join_azure_file_path(parent_path: str, child_name: str) -> str:
    parent = str(parent_path or "").strip("/")
    child = str(child_name or "").strip("/")
    if not parent:
        return child
    return f"{parent}/{child}"


def _relative_azure_file_path(root_directory_path: str, file_path: str) -> str:
    root = str(root_directory_path or "").strip("/")
    normalized_file_path = str(file_path or "").strip("/")
    if root and normalized_file_path.lower().startswith(f"{root.lower()}/"):
        return normalized_file_path[len(root) + 1:]
    return normalized_file_path


def _join_selected_azure_file_path(root_directory_path: str, selected_path: str) -> str:
    root = str(root_directory_path or "").strip("/")
    selected = str(selected_path or "").strip("/")
    if not selected:
        return root
    return _join_azure_file_path(root, selected) if root else selected


def _browse_azure_files_path(source: Dict[str, Any], browse_path: str) -> List[Dict[str, Any]]:
    share_client = _get_azure_files_share_client(source)
    root_directory_path = source.get("connection", {}).get("directory_path", "")
    directory_path = _join_selected_azure_file_path(root_directory_path, browse_path)
    entries = []
    for entry in share_client.list_directories_and_files(directory_name=directory_path or None):
        entry_name = _azure_files_item_name(entry)
        if not entry_name:
            continue
        entry_path = _join_azure_file_path(directory_path, entry_name)
        entries.append(
            {
                "name": entry_name,
                "path": _relative_azure_file_path(root_directory_path, entry_path),
                "type": "folder" if _azure_files_item_is_directory(entry) else "file",
                "size": _azure_files_item_size(entry),
                "modified_at": _azure_files_item_modified_at(entry),
            }
        )
        if len(entries) >= 100:
            break
    return entries


def _list_azure_files(source: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    share_client = _get_azure_files_share_client(source)
    connection = source.get("connection") or {}
    account_url = connection.get("account_url", "")
    share_name = connection.get("share_name", "")
    root_directory_path = connection.get("directory_path", "")
    selected_paths = connection.get("selected_paths") or [""]
    recursive_enabled = bool(source.get("recursive", True) and config.get("file_sync_allow_recursive_sources", True))
    remote_files = []

    def add_file(file_path: str, entry: Any) -> None:
        file_name = file_path.strip("/").split("/")[-1]
        remote_files.append(
            {
                "remote_path": _build_azure_files_url(account_url, share_name, file_path),
                "relative_path": _relative_azure_file_path(root_directory_path, file_path),
                "file_name": file_name,
                "size": _azure_files_item_size(entry),
                "modified_at": _azure_files_item_modified_at(entry),
                "remote_change_token": _azure_files_item_change_token(entry),
                "azure_file_path": file_path,
            }
        )

    def walk_directory(directory_path: str) -> None:
        if len(remote_files) >= config["file_sync_max_files_per_run"] * 2:
            return
        for entry in share_client.list_directories_and_files(directory_name=directory_path or None):
            entry_name = _azure_files_item_name(entry)
            if not entry_name:
                continue
            entry_path = _join_azure_file_path(directory_path, entry_name)
            if _azure_files_item_is_directory(entry):
                if recursive_enabled:
                    walk_directory(entry_path)
                continue

            file_properties = share_client.get_file_client(entry_path).get_file_properties()
            add_file(entry_path, file_properties or entry)

    for selected_path in selected_paths:
        selected_file_path = _join_selected_azure_file_path(root_directory_path, selected_path)
        if selected_path:
            try:
                file_properties = share_client.get_file_client(selected_file_path).get_file_properties()
                add_file(selected_file_path, file_properties)
                continue
            except AzureResourceNotFoundError:
                pass
        walk_directory(selected_file_path)
    return remote_files


def _list_smb_files(source: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    smbclient = _register_smb_session(source)
    connection = source.get("connection", {})
    root_path = connection.get("unc_path", "")
    selected_paths = connection.get("selected_paths") or [""]
    recursive_enabled = bool(source.get("recursive", True) and config.get("file_sync_allow_recursive_sources", True))
    remote_files = []

    def add_file(entry_path: str, file_name: str, stat_result: Any) -> None:
        remote_files.append(
            {
                "remote_path": entry_path,
                "relative_path": _relative_remote_path(root_path, entry_path),
                "file_name": file_name,
                "size": int(getattr(stat_result, "st_size", 0) or 0),
                "modified_at": _format_smb_modified_at(getattr(stat_result, "st_mtime", None)),
            }
        )

    def walk_directory(directory_path: str) -> None:
        if len(remote_files) >= config["file_sync_max_files_per_run"] * 2:
            return
        for entry in smbclient.scandir(directory_path):
            entry_path = _join_smb_path(directory_path, entry.name)
            if entry.is_dir():
                if recursive_enabled:
                    walk_directory(entry_path)
                continue
            if not entry.is_file():
                continue
            stat_result = entry.stat()
            add_file(entry_path, entry.name, stat_result)

    for selected_path in selected_paths:
        selected_remote_path = _resolve_selected_smb_path(root_path, selected_path)
        if _smb_path_is_file(smbclient, selected_remote_path):
            stat_result = smbclient.stat(selected_remote_path)
            add_file(selected_remote_path, selected_remote_path.strip("\\").split("\\")[-1], stat_result)
            continue
        walk_directory(selected_remote_path)
    return remote_files


def _resolve_selected_smb_path(root_path: str, selected_path: str) -> str:
    selected = str(selected_path or "").replace("/", "\\").strip("\\")
    return _join_smb_path(root_path, selected) if selected else root_path


def _smb_path_is_file(smbclient: Any, path_value: str) -> bool:
    try:
        return bool(smbclient.path.isfile(path_value))
    except Exception:
        return False


def _browse_smb_path(source: Dict[str, Any], browse_path: str) -> List[Dict[str, Any]]:
    smbclient = _register_smb_session(source)
    root_path = source.get("connection", {}).get("unc_path", "")
    directory_path = _resolve_selected_smb_path(root_path, browse_path)
    entries = []
    for entry in smbclient.scandir(directory_path):
        entry_path = _join_smb_path(directory_path, entry.name)
        stat_result = entry.stat()
        entries.append(
            {
                "name": entry.name,
                "path": _relative_remote_path(root_path, entry_path).replace("\\", "/"),
                "type": "folder" if entry.is_dir() else "file",
                "size": int(getattr(stat_result, "st_size", 0) or 0),
                "modified_at": _format_smb_modified_at(getattr(stat_result, "st_mtime", None)),
            }
        )
        if len(entries) >= 100:
            break
    return entries


def _format_smb_modified_at(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except Exception:
        return str(value)


def _file_matches_filters(remote_file: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    file_name = remote_file.get("file_name", "")
    relative_path = remote_file.get("relative_path", file_name).replace("\\", "/")
    if not allowed_file(file_name):
        return False

    extension = os.path.splitext(file_name)[1].lower().lstrip(".")
    allowed_extensions = filters.get("allowed_extensions") or []
    if allowed_extensions and extension not in allowed_extensions:
        return False

    include_patterns = filters.get("include_patterns") or []
    if include_patterns and not any(fnmatch.fnmatch(relative_path.lower(), pattern.lower()) for pattern in include_patterns):
        return False

    exclude_patterns = filters.get("exclude_patterns") or []
    if exclude_patterns and any(fnmatch.fnmatch(relative_path.lower(), pattern.lower()) for pattern in exclude_patterns):
        return False
    return True


def _remote_file_unchanged(existing_item: Optional[Dict[str, Any]], remote_file: Dict[str, Any]) -> bool:
    if not existing_item or existing_item.get("status") not in {"synced", "unchanged"}:
        return False
    existing_change_token = existing_item.get("remote_change_token")
    remote_change_token = remote_file.get("remote_change_token")
    if existing_change_token or remote_change_token:
        return (
            existing_change_token == remote_change_token
            and int(existing_item.get("remote_size") or 0) == int(remote_file.get("size") or 0)
            and existing_item.get("document_id")
        )
    return (
        existing_item.get("remote_modified_at") == remote_file.get("modified_at")
        and int(existing_item.get("remote_size") or 0) == int(remote_file.get("size") or 0)
        and existing_item.get("document_id")
    )


def _stage_smb_file(source: Dict[str, Any], remote_path: str, file_name: str) -> Tuple[str, str]:
    smbclient = _register_smb_session(source)
    suffix = os.path.splitext(file_name)[1] or ".bin"
    temp_dir = "/sc-temp-files" if os.path.exists("/sc-temp-files") else None
    sha256_hash = hashlib.sha256()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir) as temp_file:
        with smbclient.open_file(remote_path, mode="rb") as remote_file:
            while True:
                chunk = remote_file.read(1024 * 1024)
                if not chunk:
                    break
                temp_file.write(chunk)
                sha256_hash.update(chunk)
        return temp_file.name, sha256_hash.hexdigest()


def _stage_azure_files_file(source: Dict[str, Any], remote_file: Dict[str, Any]) -> Tuple[str, str]:
    share_client = _get_azure_files_share_client(source)
    file_path = remote_file.get("azure_file_path") or remote_file.get("relative_path") or remote_file.get("file_name")
    file_client = share_client.get_file_client(file_path)
    suffix = os.path.splitext(remote_file.get("file_name") or "")[1] or ".bin"
    temp_dir = "/sc-temp-files" if os.path.exists("/sc-temp-files") else None
    sha256_hash = hashlib.sha256()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir) as temp_file:
        downloader = file_client.download_file()
        for chunk in downloader.chunks():
            if not chunk:
                continue
            temp_file.write(chunk)
            sha256_hash.update(chunk)
        return temp_file.name, sha256_hash.hexdigest()


def _derive_tags_for_remote_file(source: Dict[str, Any], remote_file: Dict[str, Any]) -> List[str]:
    filters = source.get("filters") or {}
    tags = list(filters.get("fixed_tags") or [])
    folder_tag_mode = filters.get("folder_tag_mode", "parent")
    relative_path = remote_file.get("relative_path", "").replace("\\", "/")
    folder_parts = [part for part in relative_path.split("/")[:-1] if part]

    if folder_tag_mode == "parent" and folder_parts:
        tags.append(_safe_tag_from_text(folder_parts[-1]))
    elif folder_tag_mode == "full_path":
        tags.extend(_safe_tag_from_text(part) for part in folder_parts)

    is_valid, error_message, normalized_tags = validate_tags([tag for tag in tags if tag])
    if not is_valid:
        raise ValueError(error_message or "Invalid sync tags")
    return normalized_tags


def _document_context_for_source(source: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    scope_type = source["scope_type"]
    scope_id = _source_scope_id(source)
    user_id = source.get("user_id") or source.get("created_by") or "file-sync"
    group_id = scope_id if scope_type == FILE_SYNC_SCOPE_GROUP else None
    public_workspace_id = scope_id if scope_type == FILE_SYNC_SCOPE_PUBLIC else None
    return user_id, group_id, public_workspace_id


def _tag_definition_workspace_type(scope_type: str) -> str:
    return FILE_SYNC_SCOPE_PUBLIC if scope_type == FILE_SYNC_SCOPE_PUBLIC else scope_type


def _ensure_sync_tag_definitions(
    user_id: str,
    scope_type: str,
    group_id: Optional[str],
    public_workspace_id: Optional[str],
    tags: List[str],
) -> None:
    for tag in tags:
        get_or_create_tag_definition(
            user_id=user_id,
            tag_name=tag,
            workspace_type=_tag_definition_workspace_type(scope_type),
            group_id=group_id,
            public_workspace_id=public_workspace_id,
        )


def _apply_sync_tags_to_existing_document(
    source: Dict[str, Any],
    existing_item: Optional[Dict[str, Any]],
    remote_file: Dict[str, Any],
) -> bool:
    document_id = str((existing_item or {}).get("document_id") or "").strip()
    if not document_id:
        return False

    try:
        scope_type = source["scope_type"]
        tags = _derive_tags_for_remote_file(source, remote_file)
        user_id, group_id, public_workspace_id = _document_context_for_source(source)
        _ensure_sync_tag_definitions(user_id, scope_type, group_id, public_workspace_id, tags)
        document_metadata = get_document_metadata(
            document_id=document_id,
            user_id=user_id,
            group_id=group_id,
            public_workspace_id=public_workspace_id,
        )
        if not document_metadata:
            return False

        current_tags = document_metadata.get("tags") or []
        if current_tags == tags:
            return False

        update_document(
            document_id=document_id,
            user_id=user_id,
            group_id=group_id,
            public_workspace_id=public_workspace_id,
            tags=tags,
        )
        return True
    except Exception as error:
        log_event(
            f"[FileSync] Unable to apply sync tags to existing document {document_id}: {error}",
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return False


def _create_document_from_remote_file(source: Dict[str, Any], remote_file: Dict[str, Any], temp_file_path: str) -> str:
    scope_type = source["scope_type"]
    document_id = str(uuid.uuid4())
    user_id, group_id, public_workspace_id = _document_context_for_source(source)
    tags = _derive_tags_for_remote_file(source, remote_file)

    create_document(
        file_name=remote_file["file_name"],
        user_id=user_id,
        document_id=document_id,
        num_file_chunks=0,
        status="Queued from file sync",
        group_id=group_id,
        public_workspace_id=public_workspace_id,
    )
    _ensure_sync_tag_definitions(user_id, scope_type, group_id, public_workspace_id, tags)

    update_document(
        document_id=document_id,
        user_id=user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
        tags=tags,
        file_sync={
            "source_id": source["id"],
            "source_name": source.get("name"),
            "source_type": source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB),
            "scope_type": scope_type,
            "remote_path": remote_file.get("remote_path"),
            "relative_path": remote_file.get("relative_path"),
            "remote_modified_at": remote_file.get("modified_at"),
            "remote_size": remote_file.get("size"),
            "remote_change_token": remote_file.get("remote_change_token"),
            "remote_web_url": remote_file.get("web_url"),
            "content_hash": remote_file.get("content_hash"),
            "synced_at": _now_iso(),
            "remote_delete_policy": source.get("remote_delete_policy", "ignore"),
        },
    )
    _queue_document_processing(document_id, user_id, temp_file_path, remote_file["file_name"], group_id, public_workspace_id)
    return document_id


def _queue_document_processing(
    document_id: str,
    user_id: str,
    temp_file_path: str,
    file_name: str,
    group_id: Optional[str],
    public_workspace_id: Optional[str],
) -> None:
    task_kwargs = {
        "document_id": document_id,
        "user_id": user_id,
        "temp_file_path": temp_file_path,
        "original_filename": file_name,
    }
    if group_id:
        task_kwargs["group_id"] = group_id
    if public_workspace_id:
        task_kwargs["public_workspace_id"] = public_workspace_id

    if has_app_context():
        executor = current_app.extensions.get("executor")
        if executor and hasattr(executor, "submit_stored"):
            executor.submit_stored(document_id, process_document_upload_background, **task_kwargs)
            return
        if executor and hasattr(executor, "submit"):
            executor.submit(process_document_upload_background, **task_kwargs)
            return

    process_document_upload_background(**task_kwargs)


def _touch_item(source: Dict[str, Any], existing_item: Dict[str, Any], remote_file: Dict[str, Any], status: str) -> None:
    existing_item["status"] = status
    existing_item["remote_modified_at"] = remote_file.get("modified_at")
    existing_item["remote_size"] = remote_file.get("size")
    existing_item["remote_change_token"] = remote_file.get("remote_change_token")
    existing_item["remote_web_url"] = remote_file.get("web_url")
    existing_item["last_seen_at"] = _now_iso()
    existing_item["updated_at"] = _now_iso()
    _get_items_container(source["scope_type"]).upsert_item(existing_item)


def _upsert_synced_item(
    source: Dict[str, Any],
    existing_item: Optional[Dict[str, Any]],
    remote_file: Dict[str, Any],
    document_id: str,
    status: str,
    run_id: Optional[str] = None,
    sync_action: str = "synced",
) -> None:
    source_id = source["id"]
    now_iso = _now_iso()
    item = existing_item or {
        "id": _item_id_for_path(source_id, remote_file["remote_path"]),
        "type": "file_sync_item",
        "source_id": source_id,
        "scope_type": source["scope_type"],
        _scope_field(source["scope_type"]): _source_scope_id(source),
        "created_at": now_iso,
    }
    item.update(
        {
            "remote_path": remote_file.get("remote_path"),
            "relative_path": remote_file.get("relative_path"),
            "file_name": remote_file.get("file_name"),
            "remote_modified_at": remote_file.get("modified_at"),
            "remote_size": remote_file.get("size"),
            "remote_change_token": remote_file.get("remote_change_token"),
            "remote_web_url": remote_file.get("web_url"),
            "content_hash": remote_file.get("content_hash"),
            "document_id": document_id,
            "status": status,
            "ignored": False,
            "last_synced_at": now_iso,
            "last_sync_run_id": run_id,
            "last_sync_action": sync_action,
            "last_seen_at": now_iso,
            "updated_at": now_iso,
        }
    )
    _get_items_container(source["scope_type"]).upsert_item(item)


def _upsert_failed_item(
    source: Dict[str, Any],
    existing_item: Optional[Dict[str, Any]],
    remote_file: Dict[str, Any],
    error: Exception,
    run_id: Optional[str] = None,
) -> None:
    source_id = source["id"]
    now_iso = _now_iso()
    item = existing_item or {
        "id": _item_id_for_path(source_id, remote_file["remote_path"]),
        "type": "file_sync_item",
        "source_id": source_id,
        "scope_type": source["scope_type"],
        _scope_field(source["scope_type"]): _source_scope_id(source),
        "created_at": now_iso,
    }
    item.update(
        {
            "remote_path": remote_file.get("remote_path"),
            "relative_path": remote_file.get("relative_path"),
            "file_name": remote_file.get("file_name"),
            "remote_modified_at": remote_file.get("modified_at"),
            "remote_size": remote_file.get("size"),
            "remote_change_token": remote_file.get("remote_change_token"),
            "remote_web_url": remote_file.get("web_url"),
            "status": "failed",
            "error_message": str(error)[:1000],
            "last_sync_run_id": run_id,
            "last_sync_action": "failed",
            "last_seen_at": now_iso,
            "updated_at": now_iso,
        }
    )
    _get_items_container(source["scope_type"]).upsert_item(item)


def _handle_remote_deletes(source: Dict[str, Any], existing_items: Dict[str, Dict[str, Any]], remote_item_ids: set, counts: Dict[str, int]) -> None:
    if source.get("remote_delete_policy", "ignore") not in FILE_SYNC_REMOTE_DELETE_POLICIES:
        return
    now_iso = _now_iso()
    for item_id, item in existing_items.items():
        if item_id in remote_item_ids or item.get("ignored") or item.get("status") in {"remote_deleted", "ignored"}:
            continue
        item["last_missing_at"] = now_iso
        if source.get("remote_delete_policy") == "hard_delete" and item.get("document_id"):
            try:
                _delete_synced_document(source, item["document_id"])
                item["status"] = "remote_deleted"
                counts["deleted"] = counts.get("deleted", 0) + 1
            except Exception as delete_error:
                item["status"] = "delete_failed"
                item["error_message"] = str(delete_error)[:1000]
                counts["failed"] = counts.get("failed", 0) + 1
        else:
            item["status"] = "remote_missing"
        item["updated_at"] = now_iso
        _get_items_container(source["scope_type"]).upsert_item(item)


def _delete_synced_document(source: Dict[str, Any], document_id: str) -> None:
    scope_type = source["scope_type"]
    scope_id = _source_scope_id(source)
    user_id = source.get("user_id") or source.get("created_by") or "file-sync"
    delete_document_revision(
        user_id=user_id,
        document_id=document_id,
        delete_mode="all_versions",
        group_id=scope_id if scope_type == FILE_SYNC_SCOPE_GROUP else None,
        public_workspace_id=scope_id if scope_type == FILE_SYNC_SCOPE_PUBLIC else None,
    )


def _update_source_after_run(source: Dict[str, Any], run: Dict[str, Any]) -> None:
    now_iso = _now_iso()
    source["last_run_at"] = run.get("completed_at") or now_iso
    source["last_run_id"] = run.get("id")
    source["last_run_status"] = run.get("status")
    source["last_run_counts"] = run.get("counts", {})
    source["updated_at"] = now_iso
    schedule = source.get("schedule") or {}
    if schedule.get("enabled"):
        interval_minutes = _safe_int(schedule.get("interval_minutes"), 15, minimum=5, maximum=10080)
        schedule["next_run_at"] = (_now() + timedelta(minutes=interval_minutes)).isoformat()
        source["schedule"] = schedule
    _get_sources_container(source["scope_type"]).upsert_item(source)


def _invalidate_scope_search_cache(source: Dict[str, Any]) -> None:
    scope_type = source["scope_type"]
    scope_id = _source_scope_id(source)
    if scope_type == FILE_SYNC_SCOPE_GROUP:
        invalidate_group_search_cache(scope_id)
    elif scope_type == FILE_SYNC_SCOPE_PUBLIC:
        invalidate_public_workspace_search_cache(scope_id)
    else:
        invalidate_personal_search_cache(scope_id)


def check_due_file_sync_sources_once() -> List[Dict[str, Any]]:
    settings = get_settings()
    config = get_file_sync_config(settings)
    if not config["enable_file_sync"]:
        return []

    due_sources = []
    for scope_type in FILE_SYNC_SCOPES:
        if scope_type == FILE_SYNC_SCOPE_PERSONAL and not config["enable_file_sync_personal"]:
            continue
        if scope_type == FILE_SYNC_SCOPE_GROUP and not config["enable_file_sync_group"]:
            continue
        if scope_type == FILE_SYNC_SCOPE_PUBLIC and not config["enable_file_sync_public"]:
            continue
        due_sources.extend(_get_due_sources_for_scope(scope_type))

    due_sources = [
        source for source in due_sources
        if _is_scheduled_source_allowed(source, settings)
    ]

    runs = []
    for source in due_sources:
        try:
            runs.append(queue_file_sync_source_run(source, triggered_by=None, trigger="scheduled"))
        except Exception as error:
            log_event(f"[FileSync] Error queueing scheduled sync for {source.get('id')}: {error}", level=logging.ERROR, exceptionTraceback=True)
    return runs


def _is_scheduled_source_allowed(source: Dict[str, Any], settings: Dict[str, Any]) -> bool:
    config = get_file_sync_config(settings)
    scope_type = source.get("scope_type")
    if scope_type == FILE_SYNC_SCOPE_GROUP:
        group_id = _source_scope_id(source)
        if not config.get("require_group_assignment_for_file_sync"):
            return True
        return group_id in config.get("file_sync_allowed_group_ids", [])
    if scope_type == FILE_SYNC_SCOPE_PUBLIC:
        public_workspace_id = _source_scope_id(source)
        if not config.get("require_public_workspace_assignment_for_file_sync"):
            return True
        return public_workspace_id in config.get("file_sync_allowed_public_workspace_ids", [])
    if scope_type == FILE_SYNC_SCOPE_PERSONAL:
        return True
    return False


def _get_due_sources_for_scope(scope_type: str) -> List[Dict[str, Any]]:
    now_iso = _now_iso()
    query = """
        SELECT * FROM c
        WHERE c.enabled = true
            AND IS_DEFINED(c.schedule)
            AND c.schedule.enabled = true
            AND IS_DEFINED(c.schedule.next_run_at)
            AND c.schedule.next_run_at <= @now
    """
    return list(
        _get_sources_container(scope_type).query_items(
            query=query,
            parameters=[{"name": "@now", "value": now_iso}],
            enable_cross_partition_query=True,
        )
    )


def build_synced_document_delete_guard(
    scope_type: str,
    document_id: str,
    user_id: str,
    group_id: Optional[str] = None,
    public_workspace_id: Optional[str] = None,
    requested_action: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if requested_action in FILE_SYNC_DELETE_ACTIONS:
        return None

    document_metadata = get_document_metadata(
        document_id=document_id,
        user_id=user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
    )
    file_sync_metadata = (document_metadata or {}).get("file_sync")
    if not file_sync_metadata:
        return None
    source_id = file_sync_metadata.get("source_id")
    source = _read_file_sync_source_for_document_action(
        scope_type,
        source_id,
        group_id or public_workspace_id or user_id,
    )
    if not source:
        return None
    return {
        "error": "synced_document_delete_requires_action",
        "message": "This document was created by File Sync. Choose whether to ignore the remote file so it is not re-synced after deletion.",
        "file_sync": {
            "source_id": file_sync_metadata.get("source_id"),
            "source_name": file_sync_metadata.get("source_name"),
            "remote_path": file_sync_metadata.get("remote_path"),
            "relative_path": file_sync_metadata.get("relative_path"),
        },
        "options": [
            {"action": "delete_only", "label": "Delete this copy only"},
            {"action": "ignore_remote", "label": "Delete and ignore the remote file"},
        ],
    }


def _read_file_sync_source_for_document_action(
    scope_type: str,
    source_id: Optional[str],
    partition_key: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not source_id or not partition_key:
        return None

    try:
        return _get_sources_container(scope_type).read_item(item=source_id, partition_key=partition_key)
    except CosmosResourceNotFoundError:
        return None


def apply_synced_document_delete_action(
    scope_type: str,
    document_id: str,
    user_id: str,
    action: Optional[str],
    group_id: Optional[str] = None,
    public_workspace_id: Optional[str] = None,
) -> None:
    if action != "ignore_remote":
        return

    document_metadata = get_document_metadata(
        document_id=document_id,
        user_id=user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
    )
    file_sync_metadata = (document_metadata or {}).get("file_sync") or {}
    source_id = file_sync_metadata.get("source_id")
    remote_path = file_sync_metadata.get("remote_path")
    if not source_id or not remote_path:
        return

    source = _read_file_sync_source_for_document_action(
        scope_type,
        source_id,
        group_id or public_workspace_id or user_id,
    )
    if not source:
        return
    set_file_sync_path_ignored(source, remote_path, True, user_id)


def debug_file_sync(message: str) -> None:
    settings = get_settings()
    if _as_bool(settings.get("file_sync_debug_logging", True)):
        debug_print(f"[FileSync] {message}")


def _log_file_sync_activity(source: Dict[str, Any], user_id: Optional[str], action: str, additional_context: Optional[Dict[str, Any]] = None) -> None:
    try:
        from functions_activity_logging import log_file_sync_activity

        log_file_sync_activity(
            user_id=user_id or source.get("created_by") or source.get("user_id") or _source_scope_id(source),
            action=action,
            scope_type=source.get("scope_type"),
            source_id=source.get("id"),
            source_name=source.get("name"),
            group_id=source.get("group_id"),
            public_workspace_id=source.get("public_workspace_id"),
            additional_context=additional_context or {},
        )
    except Exception as error:
        log_event(f"[FileSync] Failed to log activity: {error}", level=logging.WARNING)