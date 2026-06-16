# functions_data_management.py
"""Data Management settings, schedules, and durable job records."""

import copy
import json
import logging
import os
import socket
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from cryptography.fernet import Fernet

import config as app_config
from config import (
    CLIENTS,
    VERSION,
    cosmos_data_management_job_items_container,
    cosmos_data_management_jobs_container,
    cosmos_settings_container,
)
from functions_appinsights import log_event


DATA_MANAGEMENT_SETTINGS_ID = "backup_settings"
DATA_MANAGEMENT_SETTINGS_TYPE = "data_management_settings"
DATA_MANAGEMENT_JOB_TYPE = "data_management_job"
DATA_MANAGEMENT_JOB_ITEM_TYPE = "data_management_job_item"

DATA_MANAGEMENT_OPERATION_BACKUP = "backup"
DATA_MANAGEMENT_OPERATION_RESTORE = "restore"
DATA_MANAGEMENT_OPERATION_MIGRATION = "migration"
DATA_MANAGEMENT_OPERATION_DRY_RUN = "dry_run"
DATA_MANAGEMENT_OPERATIONS = {
    DATA_MANAGEMENT_OPERATION_BACKUP,
    DATA_MANAGEMENT_OPERATION_RESTORE,
    DATA_MANAGEMENT_OPERATION_MIGRATION,
    DATA_MANAGEMENT_OPERATION_DRY_RUN,
}

DATA_MANAGEMENT_BACKUP_FULL = "full"
DATA_MANAGEMENT_BACKUP_PARTIAL = "partial"
DATA_MANAGEMENT_BACKUP_TYPES = {
    DATA_MANAGEMENT_BACKUP_FULL,
    DATA_MANAGEMENT_BACKUP_PARTIAL,
}

DATA_MANAGEMENT_STATUS_QUEUED = "queued"
DATA_MANAGEMENT_STATUS_RUNNING = "running"
DATA_MANAGEMENT_STATUS_COMPLETED = "completed"
DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS = "completed_with_warnings"
DATA_MANAGEMENT_STATUS_FAILED = "failed"
DATA_MANAGEMENT_STATUS_CANCELED = "canceled"
DATA_MANAGEMENT_TERMINAL_STATUSES = {
    DATA_MANAGEMENT_STATUS_COMPLETED,
    DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS,
    DATA_MANAGEMENT_STATUS_FAILED,
    DATA_MANAGEMENT_STATUS_CANCELED,
}

DATA_MANAGEMENT_DEFAULT_TIME_UTC = "03:00"
DATA_MANAGEMENT_FULL_FREQUENCIES = {
    "daily": 1,
    "weekly": 7,
    "14_days": 14,
    "30_days": 30,
}
DATA_MANAGEMENT_DEFAULT_LEASE_SECONDS = 900
DATA_MANAGEMENT_DEFAULT_STALE_SECONDS = 1200
DATA_MANAGEMENT_DEFAULT_JOB_LIMIT = 25
DATA_MANAGEMENT_KEY_VAULT_SCOPE_VALUE = "data-management"
DATA_MANAGEMENT_ENCRYPTION_SECRET_NAME = "backup-encryption-key"
DATA_MANAGEMENT_REDACTED_VALUE = "***REDACTED***"
DATA_MANAGEMENT_OPERATIONAL_WARNING = (
    "We suggest not running backups, restores, or migrations during your operational business hours. "
    "These jobs run inside the App Service environment and can affect application performance."
)

DATA_MANAGEMENT_DEFAULT_SETTINGS = {
    "enabled": False,
    "backup_storage_authentication_type": "managed_identity",
    "backup_storage_connection_string": "",
    "backup_storage_blob_endpoint": "",
    "backup_storage_container_name": "simplechat-backups",
    "backup_storage_path_prefix": "simplechat-backups",
    "target_cosmos_authentication_type": "managed_identity",
    "target_cosmos_endpoint": "",
    "target_cosmos_key": "",
    "target_cosmos_database_name": "SimpleChat",
    "encryption_enabled": True,
    "encryption_key_reference": "",
    "encryption_key_storage": "not_configured",
    "full_backup_frequency": "weekly",
    "scheduled_time_utc": DATA_MANAGEMENT_DEFAULT_TIME_UTC,
    "partial_backups_enabled": True,
    "retention_days": 30,
    "include_cosmos": True,
    "include_ai_search": True,
    "include_source_blobs": False,
    "low_impact_mode": True,
    "max_parallel_operations": 1,
    "next_full_backup_run_at": None,
    "next_partial_backup_run_at": None,
    "last_full_backup_completed_at": None,
    "last_partial_backup_completed_at": None,
    "last_settings_update_at": None,
}

DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS = {
    "backup_storage_connection_string",
    "encryption_key_reference",
    "target_cosmos_key",
}

DATA_MANAGEMENT_COSMOS_ARTIFACTS = [
    {"name": "settings", "container_attr": "cosmos_settings_container", "container_name_attr": "cosmos_settings_container_name", "partition_key_path": "/id", "category": "settings"},
    {"name": "groups", "container_attr": "cosmos_groups_container", "container_name_attr": "cosmos_groups_container_name", "partition_key_path": "/id", "category": "workspaces"},
    {"name": "public_workspaces", "container_attr": "cosmos_public_workspaces_container", "container_name_attr": "cosmos_public_workspaces_container_name", "partition_key_path": "/id", "category": "workspaces"},
    {"name": "personal_conversations", "container_attr": "cosmos_conversations_container", "container_name_attr": "cosmos_conversations_container_name", "partition_key_path": "/id", "category": "conversations"},
    {"name": "personal_messages", "container_attr": "cosmos_messages_container", "container_name_attr": "cosmos_messages_container_name", "partition_key_path": "/conversation_id", "category": "conversations"},
    {"name": "group_conversations", "container_attr": "cosmos_group_conversations_container", "container_name_attr": "cosmos_group_conversations_container_name", "partition_key_path": "/id", "category": "conversations"},
    {"name": "group_messages", "container_attr": "cosmos_group_messages_container", "container_name_attr": "cosmos_group_messages_container_name", "partition_key_path": "/conversation_id", "category": "conversations"},
    {"name": "collaboration_conversations", "container_attr": "cosmos_collaboration_conversations_container", "container_name_attr": "cosmos_collaboration_conversations_container_name", "partition_key_path": "/id", "category": "conversations"},
    {"name": "collaboration_messages", "container_attr": "cosmos_collaboration_messages_container", "container_name_attr": "cosmos_collaboration_messages_container_name", "partition_key_path": "/conversation_id", "category": "conversations"},
    {"name": "personal_documents", "container_attr": "cosmos_user_documents_container", "container_name_attr": "cosmos_user_documents_container_name", "partition_key_path": "/user_id", "category": "documents"},
    {"name": "group_documents", "container_attr": "cosmos_group_documents_container", "container_name_attr": "cosmos_group_documents_container_name", "partition_key_path": "/group_id", "category": "documents"},
    {"name": "public_documents", "container_attr": "cosmos_public_documents_container", "container_name_attr": "cosmos_public_documents_container_name", "partition_key_path": "/public_workspace_id", "category": "documents"},
    {"name": "personal_agents", "container_attr": "cosmos_personal_agents_container", "container_name_attr": "cosmos_personal_agents_container_name", "partition_key_path": "/user_id", "category": "agents"},
    {"name": "personal_actions", "container_attr": "cosmos_personal_actions_container", "container_name_attr": "cosmos_personal_actions_container_name", "partition_key_path": "/user_id", "category": "actions"},
    {"name": "group_agents", "container_attr": "cosmos_group_agents_container", "container_name_attr": "cosmos_group_agents_container_name", "partition_key_path": "/group_id", "category": "agents"},
    {"name": "group_actions", "container_attr": "cosmos_group_actions_container", "container_name_attr": "cosmos_group_actions_container_name", "partition_key_path": "/group_id", "category": "actions"},
    {"name": "global_agents", "container_attr": "cosmos_global_agents_container", "container_name_attr": "cosmos_global_agents_container_name", "partition_key_path": "/id", "category": "agents"},
    {"name": "global_actions", "container_attr": "cosmos_global_actions_container", "container_name_attr": "cosmos_global_actions_container_name", "partition_key_path": "/id", "category": "actions"},
    {"name": "agent_templates", "container_attr": "cosmos_agent_templates_container", "container_name_attr": "cosmos_agent_templates_container_name", "partition_key_path": "/id", "category": "agents"},
    {"name": "personal_prompts", "container_attr": "cosmos_user_prompts_container", "container_name_attr": "cosmos_user_prompts_container_name", "partition_key_path": "/user_id", "category": "prompts"},
    {"name": "group_prompts", "container_attr": "cosmos_group_prompts_container", "container_name_attr": "cosmos_group_prompts_container_name", "partition_key_path": "/group_id", "category": "prompts"},
    {"name": "public_prompts", "container_attr": "cosmos_public_prompts_container", "container_name_attr": "cosmos_public_prompts_container_name", "partition_key_path": "/public_workspace_id", "category": "prompts"},
    {"name": "personal_workspace_identities", "container_attr": "cosmos_personal_workspace_identities_container", "container_name_attr": "cosmos_personal_workspace_identities_container_name", "partition_key_path": "/user_id", "category": "identities"},
    {"name": "group_workspace_identities", "container_attr": "cosmos_group_workspace_identities_container", "container_name_attr": "cosmos_group_workspace_identities_container_name", "partition_key_path": "/group_id", "category": "identities"},
    {"name": "public_workspace_identities", "container_attr": "cosmos_public_workspace_identities_container", "container_name_attr": "cosmos_public_workspace_identities_container_name", "partition_key_path": "/public_workspace_id", "category": "identities"},
    {"name": "global_workspace_identities", "container_attr": "cosmos_global_workspace_identities_container", "container_name_attr": "cosmos_global_workspace_identities_container_name", "partition_key_path": "/id", "category": "identities"},
]

DATA_MANAGEMENT_SEARCH_ARTIFACTS = [
    {"name": "personal_ai_search", "client_key": "search_client_user", "index_name": "simplechat-user-index", "schema_file": "ai_search-index-user.json"},
    {"name": "group_ai_search", "client_key": "search_client_group", "index_name": "simplechat-group-index", "schema_file": "ai_search-index-group.json"},
    {"name": "public_ai_search", "client_key": "search_client_public", "index_name": "simplechat-public-index", "schema_file": "ai_search-index-public.json"},
]


def _now_utc():
    return datetime.now(timezone.utc)


def _now_iso():
    return _now_utc().isoformat()


def _parse_iso_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_bool(value, default=False):
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    if value is None:
        return default
    return bool(value)


def _safe_int(value, default=0, minimum=None, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _safe_text(value, default=""):
    if value is None:
        return default
    return str(value).strip()


def normalize_data_management_time(value):
    normalized = _safe_text(value, DATA_MANAGEMENT_DEFAULT_TIME_UTC)
    parts = normalized.split(":")
    if len(parts) != 2:
        return DATA_MANAGEMENT_DEFAULT_TIME_UTC
    hour = _safe_int(parts[0], default=-1)
    minute = _safe_int(parts[1], default=-1)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return DATA_MANAGEMENT_DEFAULT_TIME_UTC
    return f"{hour:02d}:{minute:02d}"


def _candidate_run_for_date(date_value, schedule_time):
    hour, minute = [int(part) for part in schedule_time.split(":")]
    return datetime(
        date_value.year,
        date_value.month,
        date_value.day,
        hour,
        minute,
        tzinfo=timezone.utc,
    )


def calculate_next_data_management_run(settings, backup_type=DATA_MANAGEMENT_BACKUP_FULL, current_time=None):
    current_time = current_time or _now_utc()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)

    schedule_time = normalize_data_management_time((settings or {}).get("scheduled_time_utc"))
    candidate = _candidate_run_for_date(current_time.date(), schedule_time)
    if candidate <= current_time:
        candidate += timedelta(days=1)

    if backup_type == DATA_MANAGEMENT_BACKUP_PARTIAL:
        return candidate

    frequency = (settings or {}).get("full_backup_frequency")
    if frequency not in DATA_MANAGEMENT_FULL_FREQUENCIES:
        frequency = DATA_MANAGEMENT_DEFAULT_SETTINGS["full_backup_frequency"]
    interval_days = DATA_MANAGEMENT_FULL_FREQUENCIES[frequency]
    last_completed = _parse_iso_datetime((settings or {}).get("last_full_backup_completed_at"))
    if not last_completed:
        return candidate

    earliest = last_completed + timedelta(days=interval_days)
    scheduled_earliest = _candidate_run_for_date(earliest.date(), schedule_time)
    if scheduled_earliest < earliest:
        scheduled_earliest += timedelta(days=1)
    while scheduled_earliest <= current_time:
        scheduled_earliest += timedelta(days=interval_days)
    return scheduled_earliest


def normalize_data_management_settings(payload=None, existing_settings=None, current_time=None):
    source = copy.deepcopy(DATA_MANAGEMENT_DEFAULT_SETTINGS)
    if isinstance(existing_settings, dict):
        for key, value in existing_settings.items():
            if key not in {"_etag", "_rid", "_self", "_attachments", "_ts"}:
                source[key] = value
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key not in {"id", "type", "_etag", "_rid", "_self", "_attachments", "_ts"}:
                source[key] = value

    source["id"] = DATA_MANAGEMENT_SETTINGS_ID
    source["type"] = DATA_MANAGEMENT_SETTINGS_TYPE
    source["enabled"] = _safe_bool(source.get("enabled"), DATA_MANAGEMENT_DEFAULT_SETTINGS["enabled"])
    source["backup_storage_authentication_type"] = _safe_text(source.get("backup_storage_authentication_type"), "managed_identity")
    if source["backup_storage_authentication_type"] not in {"managed_identity", "connection_string"}:
        source["backup_storage_authentication_type"] = "managed_identity"
    source["backup_storage_connection_string"] = _safe_text(source.get("backup_storage_connection_string"))
    source["backup_storage_blob_endpoint"] = _safe_text(source.get("backup_storage_blob_endpoint"))
    source["backup_storage_container_name"] = _safe_text(source.get("backup_storage_container_name"), "simplechat-backups") or "simplechat-backups"
    source["backup_storage_path_prefix"] = _safe_text(source.get("backup_storage_path_prefix"), "simplechat-backups").strip("/") or "simplechat-backups"
    source["target_cosmos_authentication_type"] = _safe_text(source.get("target_cosmos_authentication_type"), "managed_identity")
    if source["target_cosmos_authentication_type"] not in {"managed_identity", "key"}:
        source["target_cosmos_authentication_type"] = "managed_identity"
    source["target_cosmos_endpoint"] = _safe_text(source.get("target_cosmos_endpoint"))
    source["target_cosmos_key"] = _safe_text(source.get("target_cosmos_key"))
    source["target_cosmos_database_name"] = _safe_text(source.get("target_cosmos_database_name"), "SimpleChat") or "SimpleChat"
    source["encryption_enabled"] = _safe_bool(source.get("encryption_enabled"), True)
    source["encryption_key_reference"] = _safe_text(source.get("encryption_key_reference"))
    source["encryption_key_storage"] = _safe_text(source.get("encryption_key_storage"), "not_configured") or "not_configured"
    if source.get("full_backup_frequency") not in DATA_MANAGEMENT_FULL_FREQUENCIES:
        source["full_backup_frequency"] = DATA_MANAGEMENT_DEFAULT_SETTINGS["full_backup_frequency"]
    source["scheduled_time_utc"] = normalize_data_management_time(source.get("scheduled_time_utc"))
    source["partial_backups_enabled"] = _safe_bool(source.get("partial_backups_enabled"), True)
    source["retention_days"] = _safe_int(source.get("retention_days"), default=30, minimum=1, maximum=3650)
    source["include_cosmos"] = _safe_bool(source.get("include_cosmos"), True)
    source["include_ai_search"] = _safe_bool(source.get("include_ai_search"), True)
    source["include_source_blobs"] = _safe_bool(source.get("include_source_blobs"), False)
    source["low_impact_mode"] = _safe_bool(source.get("low_impact_mode"), True)
    source["max_parallel_operations"] = _safe_int(source.get("max_parallel_operations"), default=1, minimum=1, maximum=5)

    for key in ("next_full_backup_run_at", "next_partial_backup_run_at", "last_full_backup_completed_at", "last_partial_backup_completed_at"):
        parsed = _parse_iso_datetime(source.get(key))
        source[key] = parsed.isoformat() if parsed else None

    if source["enabled"] and not source.get("next_full_backup_run_at"):
        source["next_full_backup_run_at"] = calculate_next_data_management_run(
            source,
            DATA_MANAGEMENT_BACKUP_FULL,
            current_time=current_time,
        ).isoformat()
    if source["enabled"] and source["partial_backups_enabled"] and not source.get("next_partial_backup_run_at"):
        source["next_partial_backup_run_at"] = calculate_next_data_management_run(
            source,
            DATA_MANAGEMENT_BACKUP_PARTIAL,
            current_time=current_time,
        ).isoformat()

    return source


def get_data_management_settings():
    try:
        settings = cosmos_settings_container.read_item(
            item=DATA_MANAGEMENT_SETTINGS_ID,
            partition_key=DATA_MANAGEMENT_SETTINGS_ID,
        )
    except CosmosResourceNotFoundError:
        settings = normalize_data_management_settings()
        cosmos_settings_container.create_item(body=settings)
        return settings

    return normalize_data_management_settings(existing_settings=settings)


def sanitize_data_management_settings_for_admin(settings):
    sanitized = copy.deepcopy(settings or {})
    for field_name in DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS:
        if sanitized.get(field_name):
            sanitized[field_name] = DATA_MANAGEMENT_REDACTED_VALUE
    sanitized["operational_business_hours_warning"] = DATA_MANAGEMENT_OPERATIONAL_WARNING
    sanitized["default_scheduled_time_utc"] = DATA_MANAGEMENT_DEFAULT_TIME_UTC
    sanitized["partial_backup_frequency_label"] = "Daily"
    return sanitized


def update_data_management_settings(payload):
    existing = get_data_management_settings()
    payload = dict(payload or {})
    for secret_field in DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS:
        if payload.get(secret_field) == DATA_MANAGEMENT_REDACTED_VALUE:
            payload[secret_field] = existing.get(secret_field, "")

    updated = normalize_data_management_settings(payload=payload, existing_settings=existing)
    updated["last_settings_update_at"] = _now_iso()
    return cosmos_settings_container.upsert_item(updated)


def generate_data_management_encryption_key():
    generated_key = Fernet.generate_key().decode("utf-8")
    storage_mode = "settings"
    key_reference = generated_key

    try:
        from functions_keyvault import store_secret_in_key_vault

        stored_reference = store_secret_in_key_vault(
            DATA_MANAGEMENT_ENCRYPTION_SECRET_NAME,
            generated_key,
            DATA_MANAGEMENT_KEY_VAULT_SCOPE_VALUE,
            source="backup",
            scope="global",
        )
        if stored_reference != generated_key:
            storage_mode = "key_vault"
            key_reference = stored_reference
    except Exception as exc:
        log_event(
            "[DataManagement] Backup encryption key could not be stored in Key Vault; storing in settings document.",
            {"error": str(exc)},
            level=logging.WARNING,
        )

    settings = get_data_management_settings()
    settings.update({
        "encryption_enabled": True,
        "encryption_key_reference": key_reference,
        "encryption_key_storage": storage_mode,
        "last_settings_update_at": _now_iso(),
    })
    stored = cosmos_settings_container.upsert_item(normalize_data_management_settings(existing_settings=settings))
    return sanitize_data_management_settings_for_admin(stored)


def build_backup_storage_client(settings):
    auth_type = _safe_text((settings or {}).get("backup_storage_authentication_type"), "managed_identity")
    if auth_type == "connection_string":
        connection_string = _safe_text((settings or {}).get("backup_storage_connection_string"))
        if not connection_string:
            raise ValueError("Backup storage connection string is required for connection string authentication.")
        return BlobServiceClient.from_connection_string(connection_string)

    blob_endpoint = _safe_text((settings or {}).get("backup_storage_blob_endpoint"))
    if not blob_endpoint:
        raise ValueError("Backup storage blob endpoint is required for managed identity authentication.")
    return BlobServiceClient(account_url=blob_endpoint, credential=DefaultAzureCredential())


def test_backup_storage_connection(settings=None, create_container=False):
    existing_settings = get_data_management_settings()
    if isinstance(settings, dict):
        settings_payload = dict(settings)
        for secret_field in DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS:
            if settings_payload.get(secret_field) == DATA_MANAGEMENT_REDACTED_VALUE:
                settings_payload[secret_field] = existing_settings.get(secret_field, "")
        settings = normalize_data_management_settings(payload=settings_payload, existing_settings=existing_settings)
    else:
        settings = normalize_data_management_settings(existing_settings=existing_settings)
    container_name = settings.get("backup_storage_container_name")
    blob_service_client = build_backup_storage_client(settings)
    container_client = blob_service_client.get_container_client(container_name)
    exists = container_client.exists()
    created = False
    if not exists and create_container:
        container_client.create_container()
        exists = True
        created = True
    return {
        "success": True,
        "container_name": container_name,
        "container_exists": exists,
        "container_created": created,
        "authentication_type": settings.get("backup_storage_authentication_type"),
    }


def _job_lease_holder_id():
    return f"{socket.gethostname()}:{uuid.uuid4().hex}"


def _is_stale_job(job, stale_seconds=DATA_MANAGEMENT_DEFAULT_STALE_SECONDS):
    last_heartbeat = _parse_iso_datetime((job or {}).get("last_heartbeat_at") or (job or {}).get("updated_at"))
    if not last_heartbeat:
        return True
    return last_heartbeat <= _now_utc() - timedelta(seconds=stale_seconds)


def _read_job(job_id):
    return cosmos_data_management_jobs_container.read_item(item=job_id, partition_key=job_id)


def _replace_job(job):
    return cosmos_data_management_jobs_container.replace_item(
        item=job.get("id"),
        body=job,
        etag=job.get("_etag"),
        match_condition=MatchConditions.IfNotModified,
    )


def queue_data_management_job(operation, backup_type=None, requested_by=None, requested_by_email=None, options=None, scheduled=False, occurrence_id=None):
    normalized_operation = _safe_text(operation)
    if normalized_operation not in DATA_MANAGEMENT_OPERATIONS:
        raise ValueError("Unsupported data management operation.")

    normalized_backup_type = _safe_text(backup_type)
    if normalized_operation == DATA_MANAGEMENT_OPERATION_BACKUP and normalized_backup_type not in DATA_MANAGEMENT_BACKUP_TYPES:
        raise ValueError("Backup jobs must be full or partial.")
    if normalized_operation != DATA_MANAGEMENT_OPERATION_BACKUP and normalized_backup_type not in DATA_MANAGEMENT_BACKUP_TYPES:
        normalized_backup_type = None

    now = _now_iso()
    job_id = occurrence_id or str(uuid.uuid4())
    job = {
        "id": job_id,
        "type": DATA_MANAGEMENT_JOB_TYPE,
        "operation": normalized_operation,
        "backup_type": normalized_backup_type,
        "status": DATA_MANAGEMENT_STATUS_QUEUED,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "last_heartbeat_at": None,
        "last_message": "Queued data management job",
        "last_error": None,
        "requested_by": _safe_text(requested_by),
        "requested_by_email": _safe_text(requested_by_email),
        "scheduled": bool(scheduled),
        "occurrence_id": occurrence_id,
        "options": options if isinstance(options, dict) else {},
        "progress": {
            "total_steps": 0,
            "completed_steps": 0,
            "current_step": None,
            "percent_complete": 0,
        },
        "lease_holder_id": None,
        "lease_expires_at": None,
        "warnings": [],
    }

    try:
        return cosmos_data_management_jobs_container.create_item(body=job)
    except Exception as exc:
        if occurrence_id and getattr(exc, "status_code", None) == 409:
            return _read_job(job_id)
        raise


def get_data_management_jobs(limit=DATA_MANAGEMENT_DEFAULT_JOB_LIMIT):
    safe_limit = _safe_int(limit, default=DATA_MANAGEMENT_DEFAULT_JOB_LIMIT, minimum=1, maximum=100)
    query = "SELECT * FROM c WHERE c.type = @type ORDER BY c.created_at DESC"
    parameters = [{"name": "@type", "value": DATA_MANAGEMENT_JOB_TYPE}]
    return list(cosmos_data_management_jobs_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
        max_item_count=safe_limit,
    ))[:safe_limit]


def sanitize_data_management_job_for_admin(job):
    if not isinstance(job, dict):
        return None
    return {
        "id": job.get("id"),
        "operation": job.get("operation"),
        "backup_type": job.get("backup_type"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "last_heartbeat_at": job.get("last_heartbeat_at"),
        "last_message": job.get("last_message"),
        "last_error": job.get("last_error"),
        "requested_by_email": job.get("requested_by_email"),
        "scheduled": bool(job.get("scheduled")),
        "progress": job.get("progress") if isinstance(job.get("progress"), dict) else {},
        "warnings": job.get("warnings") if isinstance(job.get("warnings"), list) else [],
        "result": job.get("result") if isinstance(job.get("result"), dict) else {},
    }


def _try_claim_data_management_job(job_id, settings=None):
    try:
        job = _read_job(job_id)
    except CosmosResourceNotFoundError:
        return None

    status = _safe_text(job.get("status"))
    if status in DATA_MANAGEMENT_TERMINAL_STATUSES:
        return None
    if status == DATA_MANAGEMENT_STATUS_RUNNING and not _is_stale_job(job):
        return None

    lease_seconds = _safe_int(
        (settings or {}).get("data_management_job_lease_seconds"),
        default=DATA_MANAGEMENT_DEFAULT_LEASE_SECONDS,
        minimum=60,
        maximum=7200,
    )
    now = _now_utc()
    job.update({
        "status": DATA_MANAGEMENT_STATUS_RUNNING,
        "started_at": job.get("started_at") or now.isoformat(),
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "lease_holder_id": _job_lease_holder_id(),
        "lease_expires_at": (now + timedelta(seconds=lease_seconds)).isoformat(),
        "last_message": "Data management job claimed by a worker",
    })
    try:
        return _replace_job(job)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code not in (409, 412):
            log_event(
                "[DataManagement] Job claim failed.",
                {"job_id": job_id, "status_code": status_code, "error": str(exc)},
                level=logging.WARNING,
            )
        return None


def create_data_management_job_item(job_id, step_name, status=DATA_MANAGEMENT_STATUS_QUEUED, details=None):
    now = _now_iso()
    item = {
        "id": f"{job_id}:{step_name}",
        "job_id": job_id,
        "type": DATA_MANAGEMENT_JOB_ITEM_TYPE,
        "step_name": step_name,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "details": details if isinstance(details, dict) else {},
    }
    return cosmos_data_management_job_items_container.upsert_item(item)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _strip_cosmos_system_fields(document):
    if not isinstance(document, dict):
        return document
    return {
        key: value
        for key, value in document.items()
        if not key.startswith("_")
    }


def _save_data_management_job(job):
    body = _strip_cosmos_system_fields(job)
    saved = cosmos_data_management_jobs_container.upsert_item(body)
    job.clear()
    job.update(saved)
    return job


def _set_job_progress(job, message, completed_steps, total_steps, current_step=None, status=DATA_MANAGEMENT_STATUS_RUNNING):
    total_steps = max(1, total_steps)
    completed_steps = max(0, min(completed_steps, total_steps))
    percent_complete = int((completed_steps / total_steps) * 100)
    job.update({
        "status": status,
        "updated_at": _now_iso(),
        "last_heartbeat_at": _now_iso(),
        "last_message": message,
        "progress": {
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "current_step": current_step,
            "percent_complete": percent_complete,
        },
    })
    return _save_data_management_job(job)


def _get_backup_fernet(settings):
    if not settings.get("encryption_enabled"):
        return None
    key_reference = _safe_text(settings.get("encryption_key_reference"))
    if not key_reference:
        raise ValueError("Backup encryption is enabled but no backup encryption key has been configured.")

    try:
        from functions_keyvault import retrieve_secret_from_key_vault_by_full_name

        key_value = retrieve_secret_from_key_vault_by_full_name(key_reference)
    except Exception as exc:
        log_event(
            "[DataManagement] Backup encryption key retrieval failed.",
            {"error": str(exc)},
            level=logging.ERROR,
        )
        raise ValueError("Backup encryption key could not be retrieved.") from exc

    try:
        return Fernet(key_value.encode("utf-8"))
    except Exception as exc:
        raise ValueError("Backup encryption key is not a valid 256-bit Fernet key.") from exc


def _encrypted_blob_name(blob_name, fernet):
    if not fernet:
        return blob_name
    return f"{blob_name}.fernet"


def _upload_json_artifact(container_client, blob_name, payload, fernet=None):
    data = json.dumps(payload, default=_json_default, ensure_ascii=False, indent=2).encode("utf-8")
    content_type = "application/json"
    final_blob_name = _encrypted_blob_name(blob_name, fernet)
    if fernet:
        data = fernet.encrypt(data)
        content_type = "application/octet-stream"
    container_client.upload_blob(
        name=final_blob_name,
        data=data,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )
    return {
        "path": final_blob_name,
        "bytes": len(data),
        "encrypted": bool(fernet),
    }


def _write_jsonl_artifact(container_client, blob_name, records, fernet=None):
    temp_path = None
    item_count = 0
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False) as temp_file:
            temp_path = temp_file.name
            for record in records:
                line = json.dumps(record, default=_json_default, ensure_ascii=False, separators=(",", ":"))
                if fernet:
                    line = fernet.encrypt(line.encode("utf-8")).decode("utf-8")
                temp_file.write(line)
                temp_file.write("\n")
                item_count += 1

        final_blob_name = _encrypted_blob_name(blob_name, fernet)
        content_type = "application/octet-stream" if fernet else "application/x-jsonlines"
        with open(temp_path, "rb") as upload_file:
            container_client.upload_blob(
                name=final_blob_name,
                data=upload_file,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
        return {
            "path": final_blob_name,
            "item_count": item_count,
            "bytes": os.path.getsize(temp_path),
            "encrypted": bool(fernet),
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _get_backup_container_client(settings):
    blob_service_client = build_backup_storage_client(settings)
    container_client = blob_service_client.get_container_client(settings.get("backup_storage_container_name"))
    if not container_client.exists():
        container_client.create_container()
    return container_client


def _get_backup_base_prefix(settings, job):
    started_at = _parse_iso_datetime(job.get("started_at")) or _now_utc()
    backup_type = job.get("backup_type") or "manual"
    safe_job_id = str(job.get("id") or uuid.uuid4()).replace("/", "-")
    prefix = _safe_text(settings.get("backup_storage_path_prefix"), "simplechat-backups").strip("/")
    return f"{prefix}/{backup_type}/{started_at.strftime('%Y/%m/%d/%H%M%S')}-{safe_job_id}"


def _get_partial_since_epoch(settings, job):
    if job.get("backup_type") != DATA_MANAGEMENT_BACKUP_PARTIAL:
        return None
    since_datetime = _parse_iso_datetime(settings.get("last_partial_backup_completed_at"))
    if not since_datetime:
        since_datetime = _parse_iso_datetime(settings.get("last_full_backup_completed_at"))
    if not since_datetime:
        return None
    return int(since_datetime.timestamp())


def _iter_cosmos_container_items(container, since_epoch=None):
    if since_epoch:
        query = "SELECT * FROM c WHERE c._ts >= @since_epoch"
        parameters = [{"name": "@since_epoch", "value": since_epoch}]
    else:
        query = "SELECT * FROM c"
        parameters = []
    for item in container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
    ):
        yield _strip_cosmos_system_fields(item)


def _export_cosmos_artifacts(container_client, base_prefix, settings, job, fernet=None):
    artifacts = []
    since_epoch = _get_partial_since_epoch(settings, job)
    for artifact in DATA_MANAGEMENT_COSMOS_ARTIFACTS:
        container = getattr(app_config, artifact["container_attr"], None)
        if not container:
            artifacts.append({
                "name": artifact["name"],
                "type": "cosmos_container",
                "status": "skipped",
                "warning": "Container client was not initialized.",
            })
            continue

        blob_name = f"{base_prefix}/cosmos/{artifact['name']}.jsonl"
        upload = _write_jsonl_artifact(
            container_client,
            blob_name,
            _iter_cosmos_container_items(container, since_epoch=since_epoch),
            fernet=fernet,
        )
        upload.update({
            "name": artifact["name"],
            "type": "cosmos_container",
            "category": artifact["category"],
            "container_name": getattr(app_config, artifact["container_name_attr"], artifact["name"]),
            "partition_key_path": artifact["partition_key_path"],
            "partial_since_epoch": since_epoch,
        })
        artifacts.append(upload)
    return artifacts


def _get_search_schema(schema_file):
    schema_path = os.path.join(os.path.dirname(__file__), "static", "json", schema_file)
    with open(schema_path, "r", encoding="utf-8") as schema_handle:
        return json.load(schema_handle)


def _search_filter_for_partial(settings, job):
    since_epoch = _get_partial_since_epoch(settings, job)
    if not since_epoch:
        return None
    since_datetime = datetime.fromtimestamp(since_epoch, tz=timezone.utc)
    return f"upload_date ge {since_datetime.strftime('%Y-%m-%dT%H:%M:%SZ')}"


def _iter_search_documents(search_client, settings, job):
    search_filter = _search_filter_for_partial(settings, job)
    results = search_client.search(
        search_text="*",
        filter=search_filter,
        include_total_count=True,
    )
    for result in results:
        document = dict(result)
        yield {
            key: value
            for key, value in document.items()
            if not key.startswith("@search.")
        }


def _export_search_artifacts(container_client, base_prefix, settings, job, fernet=None):
    artifacts = []
    for artifact in DATA_MANAGEMENT_SEARCH_ARTIFACTS:
        search_client = CLIENTS.get(artifact["client_key"])
        if not search_client:
            artifacts.append({
                "name": artifact["name"],
                "type": "ai_search_index",
                "status": "skipped",
                "warning": "Search client was not initialized.",
            })
            continue

        schema_blob_name = f"{base_prefix}/ai_search/{artifact['index_name']}.schema.json"
        schema_upload = _upload_json_artifact(
            container_client,
            schema_blob_name,
            _get_search_schema(artifact["schema_file"]),
            fernet=fernet,
        )
        schema_upload.update({
            "name": f"{artifact['name']}_schema",
            "type": "ai_search_schema",
            "index_name": artifact["index_name"],
        })
        artifacts.append(schema_upload)

        documents_blob_name = f"{base_prefix}/ai_search/{artifact['index_name']}.documents.jsonl"
        documents_upload = _write_jsonl_artifact(
            container_client,
            documents_blob_name,
            _iter_search_documents(search_client, settings, job),
            fernet=fernet,
        )
        documents_upload.update({
            "name": artifact["name"],
            "type": "ai_search_documents",
            "index_name": artifact["index_name"],
            "partial_filter": _search_filter_for_partial(settings, job),
        })
        artifacts.append(documents_upload)
    return artifacts


def _get_source_blob_service_client():
    source_client = CLIENTS.get("storage_account_office_docs_client")
    if source_client:
        return source_client

    from functions_settings import get_settings

    app_settings = get_settings()
    auth_type = app_settings.get("office_docs_authentication_type")
    if auth_type == "key":
        connection_string = app_settings.get("office_docs_storage_account_url")
        if connection_string:
            return BlobServiceClient.from_connection_string(connection_string)
    if auth_type == "managed_identity":
        blob_endpoint = app_settings.get("office_docs_storage_account_blob_endpoint")
        if blob_endpoint:
            return BlobServiceClient(account_url=blob_endpoint, credential=DefaultAzureCredential())
    return None


def _source_blob_container_names():
    return [
        app_config.storage_account_user_documents_container_name,
        app_config.storage_account_group_documents_container_name,
        app_config.storage_account_public_documents_container_name,
        app_config.storage_account_personal_chat_container_name,
        app_config.storage_account_group_chat_container_name,
    ]


def _copy_source_blob(target_container_client, source_blob_client, target_blob_name, fernet=None):
    blob_bytes = source_blob_client.download_blob().readall()
    final_blob_name = _encrypted_blob_name(target_blob_name, fernet)
    if fernet:
        blob_bytes = fernet.encrypt(blob_bytes)
    target_container_client.upload_blob(
        name=final_blob_name,
        data=blob_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type="application/octet-stream"),
    )
    return final_blob_name, len(blob_bytes)


def _export_source_blob_artifacts(container_client, base_prefix, settings, fernet=None):
    if not settings.get("include_source_blobs"):
        return [{
            "name": "source_blobs",
            "type": "source_blobs",
            "status": "skipped",
            "warning": "Source blob backup is disabled. Document restore will require the original source storage account.",
        }]

    source_blob_service_client = _get_source_blob_service_client()
    if not source_blob_service_client:
        return [{
            "name": "source_blobs",
            "type": "source_blobs",
            "status": "skipped",
            "warning": "Source document Blob Storage client is not configured.",
        }]

    artifacts = []
    for source_container_name in _source_blob_container_names():
        source_container_client = source_blob_service_client.get_container_client(source_container_name)
        artifact = {
            "name": source_container_name,
            "type": "source_blob_container",
            "container_name": source_container_name,
            "blob_count": 0,
            "bytes": 0,
            "encrypted": bool(fernet),
            "prefix": f"{base_prefix}/source_blobs/{source_container_name}/",
        }
        try:
            for blob_properties in source_container_client.list_blobs():
                source_blob_client = source_container_client.get_blob_client(blob_properties.name)
                target_blob_name = f"{artifact['prefix']}{blob_properties.name}"
                _, uploaded_bytes = _copy_source_blob(
                    container_client,
                    source_blob_client,
                    target_blob_name,
                    fernet=fernet,
                )
                artifact["blob_count"] += 1
                artifact["bytes"] += uploaded_bytes
        except Exception as exc:
            artifact["status"] = "warning"
            artifact["warning"] = str(exc)
        artifacts.append(artifact)
    return artifacts


def execute_backup_job(job, settings):
    if settings.get("encryption_enabled") and not settings.get("encryption_key_reference"):
        generate_data_management_encryption_key()
        settings = get_data_management_settings()

    container_client = _get_backup_container_client(settings)
    fernet = _get_backup_fernet(settings)
    base_prefix = _get_backup_base_prefix(settings, job)
    artifacts = []
    warnings = []
    total_steps = 4

    manifest = {
        "schema_version": 1,
        "app": "SimpleChat",
        "app_version": VERSION,
        "job_id": job.get("id"),
        "backup_type": job.get("backup_type"),
        "created_at": _now_iso(),
        "base_prefix": base_prefix,
        "encryption_enabled": bool(fernet),
        "encryption_key_storage": settings.get("encryption_key_storage"),
        "include_cosmos": bool(settings.get("include_cosmos")),
        "include_ai_search": bool(settings.get("include_ai_search")),
        "include_source_blobs": bool(settings.get("include_source_blobs")),
        "artifacts": artifacts,
        "warnings": warnings,
    }

    _set_job_progress(job, "Starting backup export", 0, total_steps, current_step="start")

    if settings.get("include_cosmos"):
        artifacts.extend(_export_cosmos_artifacts(container_client, base_prefix, settings, job, fernet=fernet))
    else:
        warnings.append("Cosmos DB export is disabled for this backup.")
    _set_job_progress(job, "Cosmos DB export step completed", 1, total_steps, current_step="cosmos")

    if settings.get("include_ai_search"):
        artifacts.extend(_export_search_artifacts(container_client, base_prefix, settings, job, fernet=fernet))
    else:
        warnings.append("AI Search export is disabled for this backup.")
    _set_job_progress(job, "AI Search export step completed", 2, total_steps, current_step="ai_search")

    source_blob_artifacts = _export_source_blob_artifacts(container_client, base_prefix, settings, fernet=fernet)
    artifacts.extend(source_blob_artifacts)
    for artifact in source_blob_artifacts:
        if artifact.get("warning"):
            warnings.append(artifact.get("warning"))
    _set_job_progress(job, "Source blob export step completed", 3, total_steps, current_step="source_blobs")

    manifest_upload = _upload_json_artifact(
        container_client,
        f"{base_prefix}/manifest.json",
        manifest,
        fernet=fernet,
    )
    manifest_upload.update({"name": "manifest", "type": "manifest"})
    artifacts.append(manifest_upload)

    create_data_management_job_item(
        job.get("id"),
        "backup-export",
        status=DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS if warnings else DATA_MANAGEMENT_STATUS_COMPLETED,
        details={"manifest_path": manifest_upload.get("path"), "artifact_count": len(artifacts), "warnings": warnings},
    )

    settings_key = "last_partial_backup_completed_at" if job.get("backup_type") == DATA_MANAGEMENT_BACKUP_PARTIAL else "last_full_backup_completed_at"
    settings[settings_key] = _now_iso()
    settings["last_settings_update_at"] = _now_iso()
    cosmos_settings_container.upsert_item(normalize_data_management_settings(existing_settings=settings))

    return {
        "manifest_path": manifest_upload.get("path"),
        "artifact_count": len(artifacts),
        "warnings": warnings,
    }


def process_data_management_job(job_id):
    settings = get_data_management_settings()
    job = _try_claim_data_management_job(job_id, settings=settings)
    if not job:
        return None

    try:
        if job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP:
            result = execute_backup_job(job, settings)
            warnings = list(job.get("warnings") or []) + result.get("warnings", [])
            status = DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS if warnings else DATA_MANAGEMENT_STATUS_COMPLETED
            message = "Backup completed with warnings" if warnings else "Backup completed successfully"
        else:
            warnings = list(job.get("warnings") or [])
            warnings.append(
                "Restore and migration apply logic has not run in this job. The durable job record, settings, and admin workflow are ready for the restore and migration implementation layer."
            )
            result = {"warnings": warnings}
            create_data_management_job_item(
                job.get("id"),
                "orchestration-foundation",
                status=DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS,
                details={"message": warnings[-1]},
            )
            status = DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS
            message = "Data Management job foundation completed with implementation warnings"

        now = _now_iso()
        job.update({
            "status": status,
            "updated_at": now,
            "completed_at": now,
            "last_heartbeat_at": now,
            "last_message": message,
            "last_error": None,
            "lease_holder_id": None,
            "lease_expires_at": None,
            "warnings": warnings,
            "result": result,
            "progress": {
                "total_steps": 1,
                "completed_steps": 1,
                "current_step": "complete",
                "percent_complete": 100,
            },
        })
        return _save_data_management_job(job)
    except Exception as exc:
        now = _now_iso()
        job.update({
            "status": DATA_MANAGEMENT_STATUS_FAILED,
            "updated_at": now,
            "completed_at": now,
            "last_heartbeat_at": now,
            "last_message": "Data Management job failed",
            "last_error": str(exc),
            "lease_holder_id": None,
            "lease_expires_at": None,
        })
        log_event(
            "[DataManagement] Job processing failed.",
            {"job_id": job_id, "operation": job.get("operation"), "error": str(exc)},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return _save_data_management_job(job)


def submit_data_management_job(app, job_id):
    if not app:
        return False
    executor = app.extensions.get("executor")
    if executor and hasattr(executor, "submit_stored"):
        executor.submit_stored(
            f"data_management_{job_id}",
            process_data_management_job,
            job_id=job_id,
        )
        return True
    if executor and hasattr(executor, "submit"):
        executor.submit(process_data_management_job, job_id)
        return True
    return False


def build_scheduled_occurrence_id(backup_type, run_at):
    normalized_backup_type = backup_type if backup_type in DATA_MANAGEMENT_BACKUP_TYPES else DATA_MANAGEMENT_BACKUP_FULL
    scheduled_time = _parse_iso_datetime(run_at) or _now_utc()
    return f"data_management_{normalized_backup_type}_{scheduled_time.strftime('%Y%m%dT%H%MZ')}"


def check_due_data_management_jobs_once(app=None):
    settings = get_data_management_settings()
    if not settings.get("enabled"):
        return []

    current_time = _now_utc()
    queued_jobs = []
    for backup_type, next_key in (
        (DATA_MANAGEMENT_BACKUP_FULL, "next_full_backup_run_at"),
        (DATA_MANAGEMENT_BACKUP_PARTIAL, "next_partial_backup_run_at"),
    ):
        if backup_type == DATA_MANAGEMENT_BACKUP_PARTIAL and not settings.get("partial_backups_enabled"):
            continue
        next_run_at = _parse_iso_datetime(settings.get(next_key))
        if not next_run_at or current_time < next_run_at:
            continue
        occurrence_id = build_scheduled_occurrence_id(backup_type, next_run_at)
        job = queue_data_management_job(
            DATA_MANAGEMENT_OPERATION_BACKUP,
            backup_type=backup_type,
            requested_by="system",
            requested_by_email="system",
            scheduled=True,
            occurrence_id=occurrence_id,
        )
        queued_jobs.append(job)
        settings[next_key] = calculate_next_data_management_run(
            settings,
            backup_type=backup_type,
            current_time=current_time,
        ).isoformat()

    if queued_jobs:
        settings["last_settings_update_at"] = _now_iso()
        cosmos_settings_container.upsert_item(normalize_data_management_settings(existing_settings=settings))
        for job in queued_jobs:
            submitted = submit_data_management_job(app, job.get("id"))
            if not submitted:
                process_data_management_job(job.get("id"))

    return queued_jobs