# functions_file_sync.py

import fnmatch
import hashlib
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import current_app, has_app_context

from config import (
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
from functions_settings import get_settings
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
FILE_SYNC_SOURCE_TYPE_SHAREPOINT_ON_PREM = "sharepoint_on_prem"
FILE_SYNC_SOURCE_TYPE_GOOGLE_WORKSPACE = "google_workspace"
FILE_SYNC_KNOWN_SOURCE_TYPES = {
    FILE_SYNC_SOURCE_TYPE_SMB,
    FILE_SYNC_SOURCE_TYPE_SHAREPOINT_ON_PREM,
    FILE_SYNC_SOURCE_TYPE_GOOGLE_WORKSPACE,
}
FILE_SYNC_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
FILE_SYNC_PERSONAL_APP_ROLE = "PersonalFileSyncUser"
FILE_SYNC_GROUP_APP_ROLE = "GroupFileSyncUser"
FILE_SYNC_PUBLIC_APP_ROLE = "PublicWorkspaceFileSyncUser"

FILE_SYNC_DEFAULTS = {
    "enable_file_sync": False,
    "enable_file_sync_personal": True,
    "enable_file_sync_group": True,
    "enable_file_sync_public": False,
    "file_sync_personal_require_app_role": False,
    "file_sync_group_require_app_role": False,
    "file_sync_public_require_app_role": False,
    "file_sync_personal_admin_only": False,
    "file_sync_group_admin_only": False,
    "file_sync_public_admin_only": False,
    "file_sync_visible_source_types": [FILE_SYNC_SOURCE_TYPE_SMB],
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


def _normalize_source_type_list(value: Any) -> List[str]:
    source_types = []
    seen_source_types = set()
    for source_type in parse_file_sync_list(value):
        normalized_source_type = str(source_type or "").strip().lower()
        if normalized_source_type not in FILE_SYNC_KNOWN_SOURCE_TYPES:
            continue
        if normalized_source_type in seen_source_types:
            continue
        seen_source_types.add(normalized_source_type)
        source_types.append(normalized_source_type)
    return source_types


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
    config["file_sync_visible_source_types"] = _normalize_source_type_list(config.get("file_sync_visible_source_types"))

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
    config = get_file_sync_config(settings)
    if not config["enable_file_sync"] or not config["enable_file_sync_group"]:
        return False

    if config.get("file_sync_group_admin_only") and not admin_management and not _user_info_has_admin_role(user_info):
        return False
    if config.get("file_sync_group_require_app_role") and not admin_management and not _user_info_has_app_role(user_info, FILE_SYNC_GROUP_APP_ROLE):
        return False
    return True


def is_file_sync_enabled_for_public_workspace(
    settings: Dict[str, Any],
    public_workspace_id: str,
    user_info: Optional[Dict[str, Any]] = None,
    admin_management: bool = False,
) -> bool:
    config = get_file_sync_config(settings)
    if not config["enable_file_sync"] or not config["enable_file_sync_public"]:
        return False

    if config.get("file_sync_public_admin_only") and not admin_management and not _user_info_has_admin_role(user_info):
        return False
    if config.get("file_sync_public_require_app_role") and not admin_management and not _user_info_has_app_role(user_info, FILE_SYNC_PUBLIC_APP_ROLE):
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
    password_stored = bool(auth.get("password") or auth.get("password_secret_name"))
    sanitized_source["credentials"] = {
        "auth_type": auth.get("auth_type", "username_password"),
        "username": auth.get("username", ""),
        "domain": auth.get("domain", ""),
        "password_stored": password_stored,
        "password": ui_trigger_word if password_stored else "",
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
    raw_credentials: Dict[str, Any],
    existing_auth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw_credentials = raw_credentials or {}
    existing_auth = existing_auth or {}
    auth_type = _normalize_text(raw_credentials.get("auth_type", existing_auth.get("auth_type", "username_password")), 50)
    if auth_type not in {"username_password", "anonymous"}:
        raise ValueError("SMB file sync currently supports username_password or anonymous authentication")

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

    settings = get_settings()
    if _as_bool(settings.get("enable_key_vault_secret_storage")) and str(settings.get("key_vault_name") or "").strip():
        secret_name = f"file-sync-{source_id}-password"
        full_secret_name = store_secret_in_key_vault(
            secret_name=secret_name,
            secret_value=str(password),
            scope_value=scope_id,
            source="file-sync",
            scope=_keyvault_scope(scope_type),
        )
        prepared_auth["password_secret_name"] = full_secret_name
    else:
        prepared_auth["password"] = str(password)
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
    source_type = _normalize_text(payload.get("source_type", existing_source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB)), 50).lower()
    if source_type != FILE_SYNC_SOURCE_TYPE_SMB:
        raise ValueError("Only SMB file sync sources are supported")

    connection = payload.get("connection") or {}
    existing_connection = existing_source.get("connection") or {}
    filters = payload.get("filters") or {}
    existing_filters = existing_source.get("filters") or {}
    schedule = payload.get("schedule") or {}
    existing_schedule = existing_source.get("schedule") or {}
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
        "name": _normalize_text(payload.get("name", existing_source.get("name", "SMB File Sync Source")), 120),
        "source_type": source_type,
        "enabled": _as_bool(payload.get("enabled", existing_source.get("enabled", True))),
        "recursive": _as_bool(payload.get("recursive", existing_source.get("recursive", True))) and config["file_sync_allow_recursive_sources"],
        "connection": {
            "unc_path": _normalize_unc_path(connection.get("unc_path", existing_connection.get("unc_path", ""))),
        },
        "filters": {
            "include_patterns": _normalize_patterns(filters.get("include_patterns", existing_filters.get("include_patterns", []))),
            "exclude_patterns": _normalize_patterns(filters.get("exclude_patterns", existing_filters.get("exclude_patterns", []))),
            "allowed_extensions": _normalize_extensions(filters.get("allowed_extensions", existing_filters.get("allowed_extensions", []))),
            "fixed_tags": _normalize_tags(filters.get("fixed_tags", existing_filters.get("fixed_tags", []))),
            "folder_tag_mode": folder_tag_mode,
        },
        "schedule": _normalize_schedule(schedule, config, existing_schedule),
        "remote_delete_policy": raw_delete_policy if raw_delete_policy in FILE_SYNC_REMOTE_DELETE_POLICIES else "ignore",
    }
    normalized_source["auth"] = _prepare_auth_payload(
        scope_type=scope_type,
        scope_id=scope_id,
        source_id=source_id,
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


def _prepare_connection_test_auth(raw_credentials: Dict[str, Any], existing_auth: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw_credentials = raw_credentials or {}
    existing_auth = existing_auth or {}
    auth_type = _normalize_text(raw_credentials.get("auth_type", existing_auth.get("auth_type", "username_password")), 50)
    if auth_type not in {"username_password", "anonymous"}:
        raise ValueError("SMB file sync currently supports username_password or anonymous authentication")

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
    source_type = _normalize_text(payload.get("source_type", existing_source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB)), 50).lower()
    if source_type != FILE_SYNC_SOURCE_TYPE_SMB:
        raise ValueError("Only SMB file sync sources are supported")

    connection = payload.get("connection") or {}
    existing_connection = existing_source.get("connection") or {}
    config = get_file_sync_config()
    test_source_id = source_id or "connection-test"
    return {
        "id": test_source_id,
        "source_id": test_source_id,
        "scope_type": _validate_scope(scope_type),
        _scope_field(scope_type): scope_id,
        "source_type": source_type,
        "name": _normalize_text(payload.get("name", existing_source.get("name", "SMB File Sync Source")), 120),
        "recursive": _as_bool(payload.get("recursive", existing_source.get("recursive", True))) and config["file_sync_allow_recursive_sources"],
        "connection": {
            "unc_path": _normalize_unc_path(connection.get("unc_path", existing_connection.get("unc_path", ""))),
        },
        "auth": _prepare_connection_test_auth(
            payload.get("credentials") or payload.get("auth") or {},
            existing_source.get("auth") or {},
        ),
    }


def test_file_sync_source_connection(
    scope_type: str,
    scope_id: str,
    payload: Dict[str, Any],
    tested_by: str,
    source_id: Optional[str] = None,
) -> Dict[str, Any]:
    source = _build_connection_test_source(scope_type, scope_id, payload or {}, tested_by, source_id=source_id)
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
            "unchanged": 0,
            "skipped": 0,
            "deleted": 0,
            "failed": 0,
            "bytes_queued": 0,
        },
    }
    _get_runs_container(source["scope_type"]).create_item(body=run)
    return run


def _update_run(run: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    run.update(fields)
    _get_runs_container(run["scope_type"]).upsert_item(run)
    return run


def queue_file_sync_source_run(source: Dict[str, Any], triggered_by: Optional[str], trigger: str = "manual") -> Dict[str, Any]:
    config = get_file_sync_config()
    if _count_active_runs() >= config["file_sync_max_concurrent_runs"]:
        raise ValueError("The configured File Sync concurrent run limit has been reached")
    if _source_has_active_run(source):
        raise ValueError("This File Sync source already has a queued or running sync")

    run = _create_run(source, triggered_by, trigger)
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
        remote_files = _list_smb_files(source, config)
        remote_item_ids = set()
        bytes_queued = 0

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
                _touch_item(source, existing_item, remote_file, "unchanged")
                continue

            try:
                temp_file_path, content_hash = _stage_smb_file(source, remote_file["remote_path"], remote_file["file_name"])
                if existing_item and existing_item.get("content_hash") == content_hash:
                    counts["unchanged"] = counts.get("unchanged", 0) + 1
                    remote_file["content_hash"] = content_hash
                    _touch_item(source, existing_item, remote_file, "unchanged")
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                    continue

                remote_file["content_hash"] = content_hash
                document_id = _create_document_from_remote_file(source, remote_file, temp_file_path)
                _upsert_synced_item(source, existing_item, remote_file, document_id, status="synced")
                counts["queued"] = counts.get("queued", 0) + 1
                bytes_queued += remote_file.get("size", 0)
                counts["bytes_queued"] = bytes_queued
            except Exception as item_error:
                counts["failed"] = counts.get("failed", 0) + 1
                _upsert_failed_item(source, existing_item, remote_file, item_error)
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
    auth = source.get("auth") or {}
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


def _list_smb_files(source: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    smbclient = _register_smb_session(source)
    root_path = source.get("connection", {}).get("unc_path", "")
    recursive_enabled = bool(source.get("recursive", True) and config.get("file_sync_allow_recursive_sources", True))
    remote_files = []

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
            modified_at = _format_smb_modified_at(getattr(stat_result, "st_mtime", None))
            remote_files.append(
                {
                    "remote_path": entry_path,
                    "relative_path": _relative_remote_path(root_path, entry_path),
                    "file_name": entry.name,
                    "size": int(getattr(stat_result, "st_size", 0) or 0),
                    "modified_at": modified_at,
                }
            )

    walk_directory(root_path)
    return remote_files


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


def _create_document_from_remote_file(source: Dict[str, Any], remote_file: Dict[str, Any], temp_file_path: str) -> str:
    scope_type = source["scope_type"]
    scope_id = _source_scope_id(source)
    user_id = source.get("user_id") or source.get("created_by") or "file-sync"
    document_id = str(uuid.uuid4())
    group_id = scope_id if scope_type == FILE_SYNC_SCOPE_GROUP else None
    public_workspace_id = scope_id if scope_type == FILE_SYNC_SCOPE_PUBLIC else None
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
    for tag in tags:
        get_or_create_tag_definition(
            user_id=user_id,
            tag_name=tag,
            workspace_type=scope_type,
            group_id=group_id,
            public_workspace_id=public_workspace_id,
        )

    update_document(
        document_id=document_id,
        user_id=user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
        tags=tags,
        file_sync={
            "source_id": source["id"],
            "source_name": source.get("name"),
            "scope_type": scope_type,
            "remote_path": remote_file.get("remote_path"),
            "relative_path": remote_file.get("relative_path"),
            "remote_modified_at": remote_file.get("modified_at"),
            "remote_size": remote_file.get("size"),
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
    existing_item["last_seen_at"] = _now_iso()
    existing_item["updated_at"] = _now_iso()
    _get_items_container(source["scope_type"]).upsert_item(existing_item)


def _upsert_synced_item(
    source: Dict[str, Any],
    existing_item: Optional[Dict[str, Any]],
    remote_file: Dict[str, Any],
    document_id: str,
    status: str,
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
            "content_hash": remote_file.get("content_hash"),
            "document_id": document_id,
            "status": status,
            "ignored": False,
            "last_synced_at": now_iso,
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
            "status": "failed",
            "error_message": str(error)[:1000],
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

    runs = []
    for source in due_sources:
        try:
            runs.append(queue_file_sync_source_run(source, triggered_by=None, trigger="scheduled"))
        except Exception as error:
            log_event(f"[FileSync] Error queueing scheduled sync for {source.get('id')}: {error}", level=logging.ERROR, exceptionTraceback=True)
    return runs


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