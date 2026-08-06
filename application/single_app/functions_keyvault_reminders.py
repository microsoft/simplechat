# functions_keyvault_reminders.py

"""Key Vault secret expiration reminder inventory and notification helpers."""

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from config import cosmos_key_vault_secret_reminders_container
from functions_appinsights import log_event, log_external_event
from functions_notifications import (
    create_group_notification,
    create_notification,
    create_public_workspace_notification,
)
from functions_settings import get_settings


KEY_VAULT_SECRET_REMINDERS_METADATA_FIELD = "key_vault_secret_reminders"
KEY_VAULT_SECRET_REMINDER_ALL_FIELDS = "__all__"
KEY_VAULT_SECRET_REMINDER_NOTIFICATION_TYPE = "key_vault_secret_expiring"
KEY_VAULT_SECRET_REMINDER_ACTIVE_STATUS = "active"
KEY_VAULT_SECRET_REMINDER_DISABLED_STATUS = "disabled"
KEY_VAULT_SECRET_REMINDER_SYNC_FAILED_STATUS = "sync_failed"
KEY_VAULT_SECRET_REMINDER_SYNCED_STATUS = "synced"
KEY_VAULT_SECRET_REMINDER_DEFAULT_LEAD_DAYS = 30
KEY_VAULT_SECRET_REMINDER_DEFAULT_SCAN_INTERVAL_SECONDS = 21600
KEY_VAULT_SECRET_REMINDER_LOCK_NAME = "key_vault_secret_expiration_reminders"
KEY_VAULT_REMINDER_EXTERNAL_EVENT_NAME = "key_vault_expiration_reminder_triggered"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_int(value: Any, default_value: int, minimum: int, maximum: int) -> int:
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default_value
    return min(max(parsed_value, minimum), maximum)


def _normalize_text(value: Any, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _hash_external_telemetry_value(value: Any) -> str:
    normalized_value = str(value or "").strip()
    if not normalized_value:
        return ""
    return hashlib.sha256(normalized_value.encode("utf-8")).hexdigest()[:16]


def _parse_expiration_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    raw_value = str(value).strip()
    if not raw_value:
        return None
    if raw_value.endswith("Z"):
        raw_value = f"{raw_value[:-1]}+00:00"

    try:
        return datetime.fromisoformat(raw_value).date()
    except ValueError:
        return date.fromisoformat(raw_value[:10])


def _format_scope_key(scope: str, scope_value: str) -> str:
    return f"{scope}:{scope_value}"


def build_key_vault_secret_reminder_id(secret_name: str) -> str:
    """Return a stable inventory id for a Key Vault secret name."""
    digest = hashlib.sha256(str(secret_name or "").encode("utf-8")).hexdigest()[:32]
    return f"key-vault-secret-reminder-{digest}"


def normalize_key_vault_reminder_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize reminder-related app settings in-place and return the same dict."""
    settings["enable_key_vault_secret_expiration_reminders"] = _as_bool(
        settings.get("enable_key_vault_secret_expiration_reminders", False)
    )
    settings["key_vault_secret_expiration_default_lead_days"] = _safe_int(
        settings.get("key_vault_secret_expiration_default_lead_days"),
        KEY_VAULT_SECRET_REMINDER_DEFAULT_LEAD_DAYS,
        1,
        3650,
    )
    settings["key_vault_secret_expiration_default_contact_email"] = _normalize_text(
        settings.get("key_vault_secret_expiration_default_contact_email"),
        254,
    )
    settings["key_vault_secret_expiration_require_expiration"] = _as_bool(
        settings.get("key_vault_secret_expiration_require_expiration", False)
    )
    settings["key_vault_secret_expiration_emit_contact_email_in_telemetry"] = _as_bool(
        settings.get("key_vault_secret_expiration_emit_contact_email_in_telemetry", False)
    )
    settings["key_vault_secret_expiration_admin_roles"] = normalize_admin_role_list(
        settings.get("key_vault_secret_expiration_admin_roles")
    )
    settings["key_vault_secret_expiration_scan_interval_seconds"] = _safe_int(
        settings.get("key_vault_secret_expiration_scan_interval_seconds"),
        KEY_VAULT_SECRET_REMINDER_DEFAULT_SCAN_INTERVAL_SECONDS,
        900,
        86400,
    )
    return settings


def normalize_admin_role_list(value: Any) -> List[str]:
    """Return distinct admin notification role names."""
    if isinstance(value, list):
        raw_roles = value
    elif isinstance(value, str):
        raw_roles = value.replace(";", ",").split(",")
    else:
        raw_roles = []

    roles = []
    for role in raw_roles:
        normalized_role = _normalize_text(role, 80)
        if normalized_role and normalized_role not in roles:
            roles.append(normalized_role)
    return roles or ["Admin"]


def normalize_key_vault_secret_reminder_config(
    reminder_config: Dict[str, Any],
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate and normalize a single per-secret reminder configuration."""
    settings = normalize_key_vault_reminder_settings(dict(settings or get_settings() or {}))
    raw_config = reminder_config if isinstance(reminder_config, dict) else {}
    enabled = _as_bool(raw_config.get("enabled"))
    if not enabled:
        return {"enabled": False}

    expiration_date = _parse_expiration_date(
        raw_config.get("expires_on") or raw_config.get("expiration_date")
    )
    if expiration_date is None:
        raise ValueError("Expiration date is required when Key Vault expiration reminders are enabled.")

    contact_email = _normalize_text(
        raw_config.get("contact_email")
        or raw_config.get("reminder_email")
        or settings.get("key_vault_secret_expiration_default_contact_email"),
        254,
    )
    if not contact_email or "@" not in contact_email:
        raise ValueError("A valid reminder email is required when Key Vault expiration reminders are enabled.")

    lead_days = _safe_int(
        raw_config.get("lead_days"),
        settings.get("key_vault_secret_expiration_default_lead_days", KEY_VAULT_SECRET_REMINDER_DEFAULT_LEAD_DAYS),
        1,
        3650,
    )

    return {
        "enabled": True,
        "expires_on": expiration_date.isoformat(),
        "lead_days": lead_days,
        "contact_email": contact_email,
        "label": _normalize_text(raw_config.get("label") or raw_config.get("friendly_label"), 160),
        "notes": _normalize_text(raw_config.get("notes") or raw_config.get("rotation_notes"), 1000),
    }


def resolve_key_vault_secret_reminder_config(
    owner_document: Dict[str, Any],
    field_path: Tuple[str, ...],
    settings: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Return the normalized reminder config for a secret field, if configured."""
    if not isinstance(owner_document, dict):
        return None

    metadata = owner_document.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    raw_reminders = metadata.get(KEY_VAULT_SECRET_REMINDERS_METADATA_FIELD)
    if not isinstance(raw_reminders, dict):
        return None

    field_key = ".".join(str(part) for part in field_path)
    if field_key in raw_reminders:
        raw_config = raw_reminders.get(field_key)
    elif KEY_VAULT_SECRET_REMINDER_ALL_FIELDS in raw_reminders:
        raw_config = raw_reminders.get(KEY_VAULT_SECRET_REMINDER_ALL_FIELDS)
    else:
        return None

    if isinstance(raw_config, bool):
        raw_config = {"enabled": raw_config}
    if not isinstance(raw_config, dict):
        return None

    return normalize_key_vault_secret_reminder_config(raw_config, settings=settings)


def upsert_key_vault_secret_reminder(
    secret_name: str,
    reminder_config: Dict[str, Any],
    context: Dict[str, Any],
    key_vault_sync_status: str = KEY_VAULT_SECRET_REMINDER_SYNCED_STATUS,
    key_vault_sync_error: str = "",
) -> Dict[str, Any]:
    """Create or update the SimpleChat inventory document for a tracked secret."""
    if not reminder_config.get("enabled"):
        return mark_key_vault_secret_reminder_disabled(secret_name, context=context)

    normalized_secret_name = _normalize_text(secret_name, 127)
    if not normalized_secret_name:
        raise ValueError("Secret name is required for a Key Vault reminder inventory entry.")

    scope = _normalize_text(context.get("scope"), 50)
    scope_value = _normalize_text(context.get("scope_value"), 255)
    if not scope or not scope_value:
        raise ValueError("Reminder inventory context requires a scope and scope value.")

    reminder_id = build_key_vault_secret_reminder_id(normalized_secret_name)
    scope_key = _format_scope_key(scope, scope_value)
    existing = None
    try:
        existing = cosmos_key_vault_secret_reminders_container.read_item(
            item=reminder_id,
            partition_key=scope_key,
        )
    except CosmosResourceNotFoundError:
        existing = None

    expires_on = reminder_config["expires_on"]
    notify_on = (
        _parse_expiration_date(expires_on)
        - timedelta(days=int(reminder_config.get("lead_days") or KEY_VAULT_SECRET_REMINDER_DEFAULT_LEAD_DAYS))
    ).isoformat()

    now = _now_iso()
    status = (
        KEY_VAULT_SECRET_REMINDER_SYNC_FAILED_STATUS
        if key_vault_sync_status == KEY_VAULT_SECRET_REMINDER_SYNC_FAILED_STATUS
        else KEY_VAULT_SECRET_REMINDER_ACTIVE_STATUS
    )
    document = {
        "id": reminder_id,
        "type": "key_vault_secret_reminder",
        "enabled": True,
        "status": status,
        "secret_name": normalized_secret_name,
        "key_vault_name": _normalize_text(context.get("key_vault_name"), 120),
        "scope": scope,
        "scope_value": scope_value,
        "scope_key": scope_key,
        "source": _normalize_text(context.get("source"), 80),
        "source_type": _normalize_text(context.get("source_type"), 80),
        "source_id": _normalize_text(context.get("source_id"), 255),
        "source_name": _normalize_text(context.get("source_name"), 255),
        "source_display_name": _normalize_text(context.get("source_display_name"), 255),
        "field_path": _normalize_text(context.get("field_path"), 255),
        "field_label": _normalize_text(context.get("field_label"), 255),
        "owner_user_id": _normalize_text(context.get("owner_user_id"), 255),
        "group_id": _normalize_text(context.get("group_id"), 255),
        "public_workspace_id": _normalize_text(context.get("public_workspace_id"), 255),
        "configured_by": _normalize_text(context.get("configured_by"), 255),
        "contact_email": reminder_config["contact_email"],
        "label": reminder_config.get("label") or _normalize_text(context.get("field_label"), 160),
        "notes": reminder_config.get("notes", ""),
        "expires_on": expires_on,
        "lead_days": int(reminder_config.get("lead_days") or KEY_VAULT_SECRET_REMINDER_DEFAULT_LEAD_DAYS),
        "notify_on": notify_on,
        "remediation_url": _normalize_text(context.get("remediation_url"), 500),
        "key_vault_sync_status": key_vault_sync_status,
        "key_vault_sync_error": _normalize_text(key_vault_sync_error, 1000),
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
        "last_notified_at": (existing or {}).get("last_notified_at"),
        "last_notification_window_key": (existing or {}).get("last_notification_window_key"),
    }
    cosmos_key_vault_secret_reminders_container.upsert_item(document)
    return document


def mark_key_vault_secret_reminder_disabled(
    secret_name: str,
    context: Optional[Dict[str, Any]] = None,
    reason: str = "disabled",
) -> Dict[str, Any]:
    """Disable an inventory entry when a user turns off tracking for a secret."""
    normalized_secret_name = _normalize_text(secret_name, 127)
    if not normalized_secret_name:
        return {}

    reminder_id = build_key_vault_secret_reminder_id(normalized_secret_name)
    context = context or {}
    scope = _normalize_text(context.get("scope"), 50)
    scope_value = _normalize_text(context.get("scope_value"), 255)
    scope_key = _format_scope_key(scope, scope_value) if scope and scope_value else None
    candidates = []

    if scope_key:
        try:
            candidates.append(
                cosmos_key_vault_secret_reminders_container.read_item(
                    item=reminder_id,
                    partition_key=scope_key,
                )
            )
        except CosmosResourceNotFoundError:
            candidates = []
    else:
        candidates = list(
            cosmos_key_vault_secret_reminders_container.query_items(
                query="SELECT * FROM c WHERE c.id = @id",
                parameters=[{"name": "@id", "value": reminder_id}],
                enable_cross_partition_query=True,
            )
        )

    if not candidates:
        return {}

    updated_document = {}
    for document in candidates:
        document["enabled"] = False
        document["status"] = KEY_VAULT_SECRET_REMINDER_DISABLED_STATUS
        document["disabled_reason"] = _normalize_text(reason, 200)
        document["updated_at"] = _now_iso()
        cosmos_key_vault_secret_reminders_container.upsert_item(document)
        updated_document = document
    return updated_document


def sanitize_key_vault_secret_reminder(document: Dict[str, Any]) -> Dict[str, Any]:
    """Return the admin-safe inventory projection for a reminder document."""
    sanitized = {
        key: value
        for key, value in (document or {}).items()
        if not str(key).startswith("_")
    }
    expires_on = _parse_expiration_date(sanitized.get("expires_on"))
    sanitized["days_until_expiry"] = (
        (expires_on - datetime.now(timezone.utc).date()).days
        if expires_on
        else None
    )
    return sanitized


def list_key_vault_secret_reminders(
    status: str = "",
    scope: str = "",
    source_type: str = "",
    search: str = "",
    limit: int = 250,
) -> List[Dict[str, Any]]:
    """List Key Vault reminder inventory entries for the admin dashboard."""
    limit = _safe_int(limit, 250, 1, 1000)
    query_parts = ["SELECT * FROM c WHERE c.type = @type"]
    parameters = [{"name": "@type", "value": "key_vault_secret_reminder"}]

    if status:
        query_parts.append("AND c.status = @status")
        parameters.append({"name": "@status", "value": status})
    if scope:
        query_parts.append("AND c.scope = @scope")
        parameters.append({"name": "@scope", "value": scope})
    if source_type:
        query_parts.append("AND c.source_type = @source_type")
        parameters.append({"name": "@source_type", "value": source_type})

    query_parts.append("ORDER BY c.expires_on ASC")
    reminders = list(
        cosmos_key_vault_secret_reminders_container.query_items(
            query=" ".join(query_parts),
            parameters=parameters,
            enable_cross_partition_query=True,
        )
    )

    normalized_search = str(search or "").strip().lower()
    if normalized_search:
        searchable_fields = (
            "id",
            "secret_name",
            "source_name",
            "source_display_name",
            "field_path",
            "field_label",
            "contact_email",
            "label",
            "scope_value",
        )
        reminders = [
            reminder
            for reminder in reminders
            if any(normalized_search in str(reminder.get(field) or "").lower() for field in searchable_fields)
        ]

    return [sanitize_key_vault_secret_reminder(reminder) for reminder in reminders[:limit]]


def _build_notification_message(reminder: Dict[str, Any], days_until_expiry: int) -> str:
    display_name = (
        reminder.get("label")
        or reminder.get("source_display_name")
        or reminder.get("source_name")
        or reminder.get("secret_name")
    )
    if days_until_expiry < 0:
        return f"Key Vault secret '{display_name}' expired on {reminder.get('expires_on')}."
    if days_until_expiry == 0:
        return f"Key Vault secret '{display_name}' expires today."
    return f"Key Vault secret '{display_name}' expires in {days_until_expiry} days."


def _create_expiration_notification(reminder: Dict[str, Any], settings: Dict[str, Any], days_until_expiry: int) -> Optional[Dict[str, Any]]:
    title = "Key Vault secret expiration reminder"
    message = _build_notification_message(reminder, days_until_expiry)
    link_url = reminder.get("remediation_url") or "/admin/settings?tab=security#keyvault-section"
    metadata = {
        "reminder_id": reminder.get("id"),
        "secret_name": reminder.get("secret_name"),
        "expires_on": reminder.get("expires_on"),
        "days_until_expiry": days_until_expiry,
        "scope": reminder.get("scope"),
        "scope_value": reminder.get("scope_value"),
        "source_type": reminder.get("source_type"),
        "source_id": reminder.get("source_id"),
        "field_path": reminder.get("field_path"),
    }

    scope = reminder.get("scope")
    if scope == "user":
        user_id = reminder.get("owner_user_id") or reminder.get("scope_value")
        return create_notification(
            user_id=user_id,
            notification_type=KEY_VAULT_SECRET_REMINDER_NOTIFICATION_TYPE,
            title=title,
            message=message,
            link_url=link_url,
            metadata=metadata,
        )
    if scope == "group":
        return create_group_notification(
            reminder.get("group_id") or reminder.get("scope_value"),
            KEY_VAULT_SECRET_REMINDER_NOTIFICATION_TYPE,
            title,
            message,
            link_url=link_url,
            metadata=metadata,
        )
    if scope == "public":
        return create_public_workspace_notification(
            reminder.get("public_workspace_id") or reminder.get("scope_value"),
            KEY_VAULT_SECRET_REMINDER_NOTIFICATION_TYPE,
            title,
            message,
            link_url=link_url,
            metadata=metadata,
        )

    return create_notification(
        notification_type=KEY_VAULT_SECRET_REMINDER_NOTIFICATION_TYPE,
        title=title,
        message=message,
        link_url=link_url,
        metadata=metadata,
        assignment={
            "roles": normalize_admin_role_list(settings.get("key_vault_secret_expiration_admin_roles")),
        },
    )


def _emit_external_expiration_notification_event(
    reminder: Dict[str, Any],
    notification: Dict[str, Any],
    days_until_expiry: int,
    settings: Dict[str, Any],
) -> None:
    """Emit a safe Azure Monitor event for external alert rules and automation."""
    event_extra = {
        "reminder_id": reminder.get("id"),
        "reminder_status": reminder.get("status"),
        "scope": reminder.get("scope"),
        "source": reminder.get("source"),
        "source_type": reminder.get("source_type"),
        "field_path": reminder.get("field_path"),
        "key_vault_sync_status": reminder.get("key_vault_sync_status"),
        "notification_id": notification.get("id"),
        "notification_scope": notification.get("scope"),
        "days_until_expiry": days_until_expiry,
        "lead_days": reminder.get("lead_days"),
        "expires_on": reminder.get("expires_on"),
        "notify_on": reminder.get("notify_on"),
        "scope_value_hash": _hash_external_telemetry_value(reminder.get("scope_value")),
        "source_id_hash": _hash_external_telemetry_value(reminder.get("source_id")),
        "owner_user_id_hash": _hash_external_telemetry_value(reminder.get("owner_user_id")),
        "group_id_hash": _hash_external_telemetry_value(reminder.get("group_id")),
        "public_workspace_id_hash": _hash_external_telemetry_value(reminder.get("public_workspace_id")),
        "contact_email_hash": _hash_external_telemetry_value(reminder.get("contact_email")),
    }
    allowed_sensitive_dimensions = ()
    if settings.get("key_vault_secret_expiration_emit_contact_email_in_telemetry"):
        event_extra["contact_email"] = reminder.get("contact_email")
        allowed_sensitive_dimensions = ("contact_email",)

    log_external_event(
        KEY_VAULT_REMINDER_EXTERNAL_EVENT_NAME,
        extra=event_extra,
        allowed_sensitive_dimensions=allowed_sensitive_dimensions,
    )


def check_due_key_vault_secret_reminders_once(
    settings: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    limit: int = 1000,
) -> Dict[str, Any]:
    """Send in-app notifications for active reminders that are in their lead window."""
    settings = normalize_key_vault_reminder_settings(dict(settings or get_settings() or {}))
    if not settings.get("enable_key_vault_secret_expiration_reminders"):
        return {"enabled": False, "checked": 0, "notifications_created": 0}

    current_date = (now or datetime.now(timezone.utc)).date()
    active_reminders = list_key_vault_secret_reminders(limit=limit)

    checked = 0
    notifications_created = 0
    for reminder in active_reminders:
        if reminder.get("status") not in {
            KEY_VAULT_SECRET_REMINDER_ACTIVE_STATUS,
            KEY_VAULT_SECRET_REMINDER_SYNC_FAILED_STATUS,
        }:
            continue
        checked += 1
        expires_on = _parse_expiration_date(reminder.get("expires_on"))
        if not expires_on:
            continue

        lead_days = _safe_int(
            reminder.get("lead_days"),
            settings.get("key_vault_secret_expiration_default_lead_days", KEY_VAULT_SECRET_REMINDER_DEFAULT_LEAD_DAYS),
            1,
            3650,
        )
        notify_on = expires_on - timedelta(days=lead_days)
        if current_date < notify_on:
            continue

        window_key = f"{expires_on.isoformat()}:{lead_days}"
        if reminder.get("last_notification_window_key") == window_key:
            continue

        days_until_expiry = (expires_on - current_date).days
        notification = _create_expiration_notification(reminder, settings, days_until_expiry)
        if not notification:
            continue

        _emit_external_expiration_notification_event(reminder, notification, days_until_expiry, settings)
        reminder["last_notified_at"] = _now_iso()
        reminder["last_notification_window_key"] = window_key
        reminder["updated_at"] = _now_iso()
        cosmos_key_vault_secret_reminders_container.upsert_item(reminder)
        notifications_created += 1

    log_event(
        "[KeyVaultReminders] Reminder sweep completed.",
        extra={"checked": checked, "notifications_created": notifications_created},
        level=logging.INFO,
    )
    return {
        "enabled": True,
        "checked": checked,
        "notifications_created": notifications_created,
    }
