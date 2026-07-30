# functions_data_management.py
"""Data Management settings, schedules, and durable job records."""

import copy
import base64
from email.utils import parsedate_to_datetime
import hashlib
import json
import logging
import os
import random
import re
import socket
import time
import tempfile
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from urllib.parse import urlparse

from azure.core import MatchConditions
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
import azure.cosmos as azure_cosmos
from azure.cosmos import PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchField, SearchFieldDataType, SearchIndex
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
from functions_cosmos_throughput import (
    CosmosThroughputError,
    get_container_throughput,
    get_database_throughput,
    set_database_throughput,
)
from functions_data_management_migration_state import (
    MIGRATION_RESOURCE_STATUS_COMPLETED,
    MIGRATION_RESOURCE_STATUS_FAILED,
    build_transfer_metrics,
    complete_migration_resource,
    fail_migration_resource,
    initialize_migration_state,
    is_migration_resource_completed,
    start_migration_resource,
    update_migration_resource,
)
from functions_data_management_backup_state import (
    BACKUP_RESOURCE_STATUS_CANCELED,
    BACKUP_RESOURCE_STATUS_COMPLETED,
    BACKUP_RESOURCE_STATUS_FAILED,
    BACKUP_RESOURCE_STATUS_SKIPPED,
    build_backup_configuration_fingerprint,
    complete_backup_attempt,
    complete_backup_resource,
    fail_backup_resource,
    get_backup_resource,
    initialize_backup_state,
    is_backup_resource_completed,
    skip_backup_resource,
    start_backup_attempt,
    start_backup_resource,
    update_backup_resource,
)
from functions_data_management_search_write_fence import (
    acquire_data_management_search_write_fence,
    acquire_data_management_target_migration_coordinator,
    release_data_management_search_write_fence,
    release_data_management_target_migration_coordinator,
    renew_data_management_search_write_fence,
    renew_data_management_target_migration_coordinator,
)
from functions_migration_provenance import (
    BLOB_MIGRATION_STATUS_METADATA_KEY,
    COSMOS_MIGRATION_PROVENANCE_FIELD,
    SEARCH_MIGRATED_AT_FIELD,
    SEARCH_MIGRATION_ID_FIELD,
    SEARCH_MIGRATION_SOURCE_HASH_FIELD,
    SEARCH_MIGRATION_SOURCE_VERSION_FIELD,
    SEARCH_MIGRATION_STATUS_FIELD,
    add_cosmos_migration_provenance,
    add_search_migration_provenance,
    create_migration_provenance_context,
    get_blob_migration_provenance,
    get_cosmos_migration_provenance,
    get_search_migration_provenance,
    is_successful_migration_record,
    merge_blob_migration_metadata,
    migration_record_matches_source,
    should_skip_migration_record,
)


DATA_MANAGEMENT_SETTINGS_ID = "backup_settings"
DATA_MANAGEMENT_SETTINGS_TYPE = "data_management_settings"
DATA_MANAGEMENT_JOB_TYPE = "data_management_job"
DATA_MANAGEMENT_JOB_ITEM_TYPE = "data_management_job_item"
DATA_MANAGEMENT_MIGRATION_MANIFEST_BATCH_TYPE = "data_management_migration_manifest_batch"
DATA_MANAGEMENT_MIRROR_DELETION_BATCH_TYPE = "data_management_mirror_deletion_batch"
DATA_MANAGEMENT_MIGRATION_LOCK_TYPE = "data_management_migration_lock"
DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_TYPE = "data_management_backup_manifest_batch"
DATA_MANAGEMENT_BACKUP_LATEST_ITEM_STATE_TYPE = "data_management_backup_latest_item_state"
DATA_MANAGEMENT_BACKUP_LOCK_TYPE = "data_management_backup_lock"

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
DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME = "SimpleChat"
DATA_MANAGEMENT_FULL_FREQUENCIES = {
    "daily": 1,
    "weekly": 7,
    "14_days": 14,
    "30_days": 30,
}
DATA_MANAGEMENT_DEFAULT_LEASE_SECONDS = 900
DATA_MANAGEMENT_DEFAULT_STALE_SECONDS = 1200
DATA_MANAGEMENT_DEFAULT_JOB_LIMIT = 25
DATA_MANAGEMENT_DEFAULT_RECOVERY_JOB_LIMIT = 25
DATA_MANAGEMENT_RECOVERY_QUEUE_DELAY_SECONDS = 60
DATA_MANAGEMENT_RECOVERY_RESUBMIT_DELAY_SECONDS = 120
DATA_MANAGEMENT_MIGRATION_LOCK_PREFIX = "data_management_migration_lock"
DATA_MANAGEMENT_BACKUP_LOCK_PREFIX = "data_management_backup_lock"
DATA_MANAGEMENT_BACKUP_SOURCE_SCOPE = "simplechat-primary"
DATA_MANAGEMENT_MIGRATION_CATALOG_LIMIT = 50
DATA_MANAGEMENT_MIGRATION_BATCH_SIZE = 500
DATA_MANAGEMENT_MIGRATION_MANIFEST_BATCH_SIZE = 100
DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE = 100
DATA_MANAGEMENT_BACKUP_MAX_PUBLIC_ITEM_SUMMARIES = 50
DATA_MANAGEMENT_BACKUP_MAX_RECENT_CHECKPOINTS = 20
DATA_MANAGEMENT_BACKUP_DEFAULT_PARALLEL_OPERATIONS = 4
DATA_MANAGEMENT_BACKUP_MAX_PARALLEL_OPERATIONS = 16
DATA_MANAGEMENT_BACKUP_DEFAULT_RETRY_COUNT = 5
DATA_MANAGEMENT_BACKUP_MAX_RETRY_COUNT = 10
DATA_MANAGEMENT_BACKUP_DEFAULT_SOURCE_RU = 10000
DATA_MANAGEMENT_BACKUP_MAX_SOURCE_RU = 10000
DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_FAIL = "fail"
DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE = "continue_without_boost"
DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICIES = {
    DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_FAIL,
    DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE,
}
DATA_MANAGEMENT_SEARCH_KEYSET_PAGE_SIZE = 1000
DATA_MANAGEMENT_SEARCH_SCOPE_FILTER_BATCH_SIZE = 100
DATA_MANAGEMENT_BLOB_SERVICE_TIMEOUT_SECONDS = 120
DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS = 30
DATA_MANAGEMENT_MIGRATION_HEARTBEAT_INTERVAL_SECONDS = 2.0
DATA_MANAGEMENT_MIGRATION_HEARTBEAT_POLL_SECONDS = 1.0
DATA_MANAGEMENT_BACKUP_HEARTBEAT_INTERVAL_SECONDS = 30.0
DATA_MANAGEMENT_BACKUP_HEARTBEAT_POLL_SECONDS = 1.0
DATA_MANAGEMENT_BACKUP_MAX_RETRY_DELAY_SECONDS = 60.0
DATA_MANAGEMENT_MIGRATION_LOCK_RECOVERY_GRACE_SECONDS = 120
DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY = "new_only"
DATA_MANAGEMENT_MIGRATION_MODE_DELTA_UPSERT = "delta_upsert"
DATA_MANAGEMENT_MIGRATION_MODE_MIRROR = "mirror_with_deletions"
DATA_MANAGEMENT_MIGRATION_MODES = {
    DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
    DATA_MANAGEMENT_MIGRATION_MODE_DELTA_UPSERT,
    DATA_MANAGEMENT_MIGRATION_MODE_MIRROR,
}
DATA_MANAGEMENT_MIRROR_CONFIRMATION = "MIRROR WITH DELETIONS"
DATA_MANAGEMENT_SEARCH_WRITE_FREEZE_CONFIRMATION_ERROR = (
    "Confirm that external destination AI Search writers are frozen before migrating AI Search documents."
)
DATA_MANAGEMENT_MIGRATION_DEFAULT_PARALLEL_OPERATIONS = 8
DATA_MANAGEMENT_MIGRATION_MAX_PARALLEL_OPERATIONS = 32
DATA_MANAGEMENT_MIGRATION_DEFAULT_RETRY_COUNT = 5
DATA_MANAGEMENT_MIGRATION_MAX_RETRY_COUNT = 10
DATA_MANAGEMENT_MIGRATION_DEFAULT_SKIP_WITHIN_HOURS = 0
DATA_MANAGEMENT_MIGRATION_MAX_SKIP_WITHIN_HOURS = 8760
DATA_MANAGEMENT_MIGRATION_DEFAULT_DESTINATION_RU = 10000
DATA_MANAGEMENT_MIGRATION_MAX_DESTINATION_RU = 10000
DATA_MANAGEMENT_KEY_VAULT_SCOPE_VALUE = "data-management"
DATA_MANAGEMENT_ENCRYPTION_SECRET_NAME = "backup-encryption-key"
DATA_MANAGEMENT_REDACTED_VALUE = "***REDACTED***"
DATA_MANAGEMENT_OPERATIONAL_WARNING = (
    "We suggest not running backups, restores, or migrations during your operational business hours. "
    "These jobs run inside the App Service environment and can affect application performance."
)
DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_RUNTIME = {}
DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_RUNTIME_LOCK = Lock()

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
    "target_cosmos_database_name": DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME,
    "target_cosmos_subscription_id": "",
    "target_cosmos_resource_group": "",
    "target_ai_search_authentication_type": "managed_identity",
    "target_ai_search_endpoint": "",
    "target_ai_search_key": "",
    "target_enhanced_citations_storage_authentication_type": "managed_identity",
    "target_enhanced_citations_storage_connection_string": "",
    "target_enhanced_citations_storage_blob_endpoint": "",
    "encryption_enabled": True,
    "encryption_key_reference": "",
    "encryption_key_storage": "not_configured",
    "full_backup_frequency": "weekly",
    "scheduled_time_utc": DATA_MANAGEMENT_DEFAULT_TIME_UTC,
    "partial_backups_enabled": True,
    "retention_days": 30,
    "include_cosmos": True,
    "include_ai_search": True,
    "include_source_blobs": True,
    "low_impact_mode": True,
    "max_parallel_operations": 1,
    "backup_max_parallel_operations": DATA_MANAGEMENT_BACKUP_DEFAULT_PARALLEL_OPERATIONS,
    "backup_retry_count": DATA_MANAGEMENT_BACKUP_DEFAULT_RETRY_COUNT,
    "backup_temporary_source_ru_enabled": False,
    "backup_temporary_source_ru": DATA_MANAGEMENT_BACKUP_DEFAULT_SOURCE_RU,
    "backup_capacity_failure_policy": DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE,
    "migration_max_parallel_operations": DATA_MANAGEMENT_MIGRATION_DEFAULT_PARALLEL_OPERATIONS,
    "migration_retry_count": DATA_MANAGEMENT_MIGRATION_DEFAULT_RETRY_COUNT,
    "migration_skip_recent_within_hours": DATA_MANAGEMENT_MIGRATION_DEFAULT_SKIP_WITHIN_HOURS,
    "migration_temporary_destination_ru_enabled": False,
    "migration_temporary_destination_ru": DATA_MANAGEMENT_MIGRATION_DEFAULT_DESTINATION_RU,
    "next_full_backup_run_at": None,
    "next_partial_backup_run_at": None,
    "last_full_backup_completed_at": None,
    "last_partial_backup_completed_at": None,
    "last_settings_update_at": None,
}


class DataManagementSettingsValidationError(ValueError):
    """Raised when Data Management settings fail admin-safe validation."""


class DataManagementCosmosEditorError(ValueError):
    """Raised when Cosmos editor input is unsafe or incomplete."""


class DataManagementMigrationLeaseLostError(RuntimeError):
    """Raised when a stale migration worker no longer owns its job lease."""


class DataManagementMigrationCanceledError(RuntimeError):
    """Raised when an administrator requests cooperative migration cancellation."""


class DataManagementBackupLeaseLostError(RuntimeError):
    """Raised when a stale backup worker no longer owns its job lease."""


class DataManagementBackupCanceledError(RuntimeError):
    """Raised when an administrator requests cooperative backup cancellation."""


class DataManagementBackupOverlapError(RuntimeError):
    """Raised when another backup owns the same source scope."""

DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS = {
    "backup_storage_connection_string",
    "encryption_key_reference",
    "target_ai_search_key",
    "target_cosmos_key",
    "target_enhanced_citations_storage_connection_string",
}

DATA_MANAGEMENT_MIGRATION_TARGET_TYPES = {"users", "groups", "public_workspaces"}
DATA_MANAGEMENT_MIGRATION_TARGET_TYPE_ORDER = ("users", "groups", "public_workspaces")

DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
    "users": [
        {"name": "user_settings", "container_attr": "cosmos_user_settings_container", "container_name_attr": "cosmos_user_settings_container_name", "partition_key_path": "/id", "id_field": "id"},
        {"name": "personal_documents", "container_attr": "cosmos_user_documents_container", "container_name_attr": "cosmos_user_documents_container_name", "partition_key_path": "/id", "filter_field": "user_id", "documents": True},
        {"name": "personal_workspace_identities", "container_attr": "cosmos_personal_workspace_identities_container", "container_name_attr": "cosmos_personal_workspace_identities_container_name", "partition_key_path": "/user_id", "filter_field": "user_id"},
        {"name": "personal_agents", "container_attr": "cosmos_personal_agents_container", "container_name_attr": "cosmos_personal_agents_container_name", "partition_key_path": "/user_id", "filter_field": "user_id"},
        {"name": "personal_actions", "container_attr": "cosmos_personal_actions_container", "container_name_attr": "cosmos_personal_actions_container_name", "partition_key_path": "/user_id", "filter_field": "user_id"},
        {"name": "personal_prompts", "container_attr": "cosmos_user_prompts_container", "container_name_attr": "cosmos_user_prompts_container_name", "partition_key_path": "/id", "filter_field": "user_id"},
    ],
    "groups": [
        {"name": "groups", "container_attr": "cosmos_groups_container", "container_name_attr": "cosmos_groups_container_name", "partition_key_path": "/id", "id_field": "id"},
        {"name": "group_documents", "container_attr": "cosmos_group_documents_container", "container_name_attr": "cosmos_group_documents_container_name", "partition_key_path": "/id", "filter_field": "group_id", "documents": True},
        {"name": "group_workspace_identities", "container_attr": "cosmos_group_workspace_identities_container", "container_name_attr": "cosmos_group_workspace_identities_container_name", "partition_key_path": "/group_id", "filter_field": "group_id"},
        {"name": "group_agents", "container_attr": "cosmos_group_agents_container", "container_name_attr": "cosmos_group_agents_container_name", "partition_key_path": "/group_id", "filter_field": "group_id"},
        {"name": "group_actions", "container_attr": "cosmos_group_actions_container", "container_name_attr": "cosmos_group_actions_container_name", "partition_key_path": "/group_id", "filter_field": "group_id"},
        {"name": "group_prompts", "container_attr": "cosmos_group_prompts_container", "container_name_attr": "cosmos_group_prompts_container_name", "partition_key_path": "/id", "filter_field": "group_id"},
    ],
    "public_workspaces": [
        {"name": "public_workspaces", "container_attr": "cosmos_public_workspaces_container", "container_name_attr": "cosmos_public_workspaces_container_name", "partition_key_path": "/id", "id_field": "id"},
        {"name": "public_documents", "container_attr": "cosmos_public_documents_container", "container_name_attr": "cosmos_public_documents_container_name", "partition_key_path": "/id", "filter_field": "public_workspace_id", "documents": True},
        {"name": "public_workspace_identities", "container_attr": "cosmos_public_workspace_identities_container", "container_name_attr": "cosmos_public_workspace_identities_container_name", "partition_key_path": "/public_workspace_id", "filter_field": "public_workspace_id"},
        {"name": "public_prompts", "container_attr": "cosmos_public_prompts_container", "container_name_attr": "cosmos_public_prompts_container_name", "partition_key_path": "/id", "filter_fields": ["public_id", "public_workspace_id"]},
    ],
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

DATA_MANAGEMENT_COSMOS_EDITOR_EMPTY_QUERY = "SELECT * FROM c"
DATA_MANAGEMENT_COSMOS_EDITOR_EMPTY_QUERY_LIMIT = 100
DATA_MANAGEMENT_COSMOS_EDITOR_MAX_PAGE_SIZE = 100
DATA_MANAGEMENT_COSMOS_EDITOR_MAX_QUERY_LENGTH = 4000
DATA_MANAGEMENT_COSMOS_EDITOR_CONFIRMATION_PHRASE = "I understand this can damage system data"
DATA_MANAGEMENT_COSMOS_EDITOR_CONTAINER_DEFINITIONS = [
    ("conversations", "cosmos_conversations_container", "cosmos_conversations_container_name", "/id", "conversations"),
    ("messages", "cosmos_messages_container", "cosmos_messages_container_name", "/conversation_id", "conversations"),
    ("tabular_export_runs", "cosmos_tabular_export_runs_container", "cosmos_tabular_export_runs_container_name", "/user_id", "exports"),
    ("data_management_jobs", "cosmos_data_management_jobs_container", "cosmos_data_management_jobs_container_name", "/id", "data_management"),
    ("data_management_job_items", "cosmos_data_management_job_items_container", "cosmos_data_management_job_items_container_name", "/job_id", "data_management"),
    ("personal_workflows", "cosmos_personal_workflows_container", "cosmos_personal_workflows_container_name", "/user_id", "workflows"),
    ("personal_workflow_runs", "cosmos_personal_workflow_runs_container", "cosmos_personal_workflow_runs_container_name", "/user_id", "workflows"),
    ("personal_workflow_run_items", "cosmos_personal_workflow_run_items_container", "cosmos_personal_workflow_run_items_container_name", "/run_id", "workflows"),
    ("group_workflows", "cosmos_group_workflows_container", "cosmos_group_workflows_container_name", "/group_id", "workflows"),
    ("group_workflow_runs", "cosmos_group_workflow_runs_container", "cosmos_group_workflow_runs_container_name", "/group_id", "workflows"),
    ("group_workflow_run_items", "cosmos_group_workflow_run_items_container", "cosmos_group_workflow_run_items_container_name", "/run_id", "workflows"),
    ("group_conversations", "cosmos_group_conversations_container", "cosmos_group_conversations_container_name", "/id", "conversations"),
    ("group_messages", "cosmos_group_messages_container", "cosmos_group_messages_container_name", "/conversation_id", "conversations"),
    ("collaboration_conversations", "cosmos_collaboration_conversations_container", "cosmos_collaboration_conversations_container_name", "/id", "collaboration"),
    ("collaboration_messages", "cosmos_collaboration_messages_container", "cosmos_collaboration_messages_container_name", "/conversation_id", "collaboration"),
    ("collaboration_user_state", "cosmos_collaboration_user_state_container", "cosmos_collaboration_user_state_container_name", "/user_id", "collaboration"),
    ("settings", "cosmos_settings_container", "cosmos_settings_container_name", "/id", "settings"),
    ("custom_pages", "cosmos_custom_pages_container", "cosmos_custom_pages_container_name", "/id", "settings"),
    ("groups", "cosmos_groups_container", "cosmos_groups_container_name", "/id", "workspaces"),
    ("public_workspaces", "cosmos_public_workspaces_container", "cosmos_public_workspaces_container_name", "/id", "workspaces"),
    ("documents", "cosmos_user_documents_container", "cosmos_user_documents_container_name", "/id", "documents"),
    ("group_documents", "cosmos_group_documents_container", "cosmos_group_documents_container_name", "/id", "documents"),
    ("public_documents", "cosmos_public_documents_container", "cosmos_public_documents_container_name", "/id", "documents"),
    ("document_access_index", "cosmos_document_access_index_container", "cosmos_document_access_index_container_name", "/scope_key", "documents"),
    ("personal_file_sync_sources", "cosmos_personal_file_sync_sources_container", "cosmos_personal_file_sync_sources_container_name", "/user_id", "file_sync"),
    ("group_file_sync_sources", "cosmos_group_file_sync_sources_container", "cosmos_group_file_sync_sources_container_name", "/group_id", "file_sync"),
    ("public_file_sync_sources", "cosmos_public_file_sync_sources_container", "cosmos_public_file_sync_sources_container_name", "/public_workspace_id", "file_sync"),
    ("personal_workspace_identities", "cosmos_personal_workspace_identities_container", "cosmos_personal_workspace_identities_container_name", "/user_id", "identities"),
    ("group_workspace_identities", "cosmos_group_workspace_identities_container", "cosmos_group_workspace_identities_container_name", "/group_id", "identities"),
    ("public_workspace_identities", "cosmos_public_workspace_identities_container", "cosmos_public_workspace_identities_container_name", "/public_workspace_id", "identities"),
    ("global_workspace_identities", "cosmos_global_workspace_identities_container", "cosmos_global_workspace_identities_container_name", "/global_id", "identities"),
    ("personal_file_sync_items", "cosmos_personal_file_sync_items_container", "cosmos_personal_file_sync_items_container_name", "/source_id", "file_sync"),
    ("group_file_sync_items", "cosmos_group_file_sync_items_container", "cosmos_group_file_sync_items_container_name", "/source_id", "file_sync"),
    ("public_file_sync_items", "cosmos_public_file_sync_items_container", "cosmos_public_file_sync_items_container_name", "/source_id", "file_sync"),
    ("personal_file_sync_runs", "cosmos_personal_file_sync_runs_container", "cosmos_personal_file_sync_runs_container_name", "/source_id", "file_sync"),
    ("group_file_sync_runs", "cosmos_group_file_sync_runs_container", "cosmos_group_file_sync_runs_container_name", "/source_id", "file_sync"),
    ("public_file_sync_runs", "cosmos_public_file_sync_runs_container", "cosmos_public_file_sync_runs_container_name", "/source_id", "file_sync"),
    ("user_settings", "cosmos_user_settings_container", "cosmos_user_settings_container_name", "/id", "settings"),
    ("safety", "cosmos_safety_container", "cosmos_safety_container_name", "/id", "safety"),
    ("feedback", "cosmos_feedback_container", "cosmos_feedback_container_name", "/id", "feedback"),
    ("archived_conversations", "cosmos_archived_conversations_container", "cosmos_archived_conversations_container_name", "/id", "archive"),
    ("archived_messages", "cosmos_archived_messages_container", "cosmos_archived_messages_container_name", "/conversation_id", "archive"),
    ("prompts", "cosmos_user_prompts_container", "cosmos_user_prompts_container_name", "/id", "prompts"),
    ("group_prompts", "cosmos_group_prompts_container", "cosmos_group_prompts_container_name", "/id", "prompts"),
    ("public_prompts", "cosmos_public_prompts_container", "cosmos_public_prompts_container_name", "/id", "prompts"),
    ("file_processing", "cosmos_file_processing_container", "cosmos_file_processing_container_name", "/document_id", "documents"),
    ("personal_agents", "cosmos_personal_agents_container", "cosmos_personal_agents_container_name", "/user_id", "agents"),
    ("personal_actions", "cosmos_personal_actions_container", "cosmos_personal_actions_container_name", "/user_id", "actions"),
    ("group_agents", "cosmos_group_agents_container", "cosmos_group_agents_container_name", "/group_id", "agents"),
    ("group_actions", "cosmos_group_actions_container", "cosmos_group_actions_container_name", "/group_id", "actions"),
    ("global_agents", "cosmos_global_agents_container", "cosmos_global_agents_container_name", "/id", "agents"),
    ("global_actions", "cosmos_global_actions_container", "cosmos_global_actions_container_name", "/id", "actions"),
    ("governance_policies", "cosmos_governance_policies_container", "cosmos_governance_policies_container_name", "/id", "governance"),
    ("governance_item_policies", "cosmos_governance_item_policies_container", "cosmos_governance_item_policies_container_name", "/id", "governance"),
    ("agent_templates", "cosmos_agent_templates_container", "cosmos_agent_templates_container_name", "/id", "agents"),
    ("agent_facts", "cosmos_agent_facts_container", "cosmos_agent_facts_container_name", "/scope_id", "agents"),
    ("search_cache", "cosmos_search_cache_container", "cosmos_search_cache_container_name", "/user_id", "cache"),
    ("activity_logs", "cosmos_activity_logs_container", "cosmos_activity_logs_container_name", "/user_id", "activity"),
    ("notifications", "cosmos_notifications_container", "cosmos_notifications_container_name", "/user_id", "notifications"),
    ("approvals", "cosmos_approvals_container", "cosmos_approvals_container_name", "/group_id", "approvals"),
    ("msgraph_pending_actions", "cosmos_msgraph_pending_actions_container", "cosmos_msgraph_pending_actions_container_name", "/user_id", "actions"),
    ("thoughts", "cosmos_thoughts_container", "cosmos_thoughts_container_name", "/user_id", "thoughts"),
    ("archive_thoughts", "cosmos_archived_thoughts_container", "cosmos_archived_thoughts_container_name", "/user_id", "archive"),
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


def _get_application_settings_for_data_management():
    try:
        from functions_settings import get_settings

        return get_settings() or {}
    except Exception as exc:
        log_event(
            "[DataManagement] Application settings could not be loaded for Data Management validation.",
            {"error": str(exc)},
            level=logging.WARNING,
        )
        return {}


def _get_data_management_feature_context(application_settings=None):
    settings = application_settings if isinstance(application_settings, dict) else _get_application_settings_for_data_management()
    key_vault_enabled = _safe_bool(settings.get("enable_key_vault_secret_storage"), False)
    key_vault_name = _safe_text(settings.get("key_vault_name"))
    return {
        "enhanced_citations_enabled": _safe_bool(settings.get("enable_enhanced_citations"), False),
        "key_vault_secret_storage_enabled": key_vault_enabled,
        "key_vault_name_configured": bool(key_vault_name),
    }


def _normalize_storage_endpoint(endpoint):
    normalized = _safe_text(endpoint).rstrip("/").lower()
    if normalized.startswith("https://") or normalized.startswith("http://"):
        return normalized
    return normalized


def _derive_storage_blob_endpoint_from_connection_string(connection_string):
    if not _safe_text(connection_string):
        return ""
    try:
        from functions_blob_storage_operations import derive_blob_endpoint_from_connection_string

        return _normalize_storage_endpoint(derive_blob_endpoint_from_connection_string(connection_string))
    except Exception as exc:
        log_event(
            "[DataManagement] Could not derive a Blob endpoint from a storage connection string.",
            {"error": str(exc)},
            level=logging.WARNING,
        )
        return ""


def _storage_endpoint_candidates(connection_string="", blob_endpoint=""):
    candidates = set()
    normalized_endpoint = _normalize_storage_endpoint(blob_endpoint)
    if normalized_endpoint:
        candidates.add(normalized_endpoint)
    derived_endpoint = _derive_storage_blob_endpoint_from_connection_string(connection_string)
    if derived_endpoint:
        candidates.add(derived_endpoint)
    return candidates


def validate_data_management_storage_is_dedicated(settings, application_settings=None):
    app_settings = application_settings if isinstance(application_settings, dict) else _get_application_settings_for_data_management()
    if not _safe_bool(app_settings.get("enable_enhanced_citations"), False):
        return

    backup_connection_string = _safe_text((settings or {}).get("backup_storage_connection_string"))
    backup_blob_endpoint = _safe_text((settings or {}).get("backup_storage_blob_endpoint"))
    enhanced_connection_string = _safe_text(app_settings.get("office_docs_storage_account_url"))
    enhanced_blob_endpoint = _safe_text(app_settings.get("office_docs_storage_account_blob_endpoint"))

    if backup_connection_string and enhanced_connection_string and backup_connection_string == enhanced_connection_string:
        raise DataManagementSettingsValidationError(
            "Backup storage must use a dedicated Azure Storage account. It cannot use the same connection string configured for Enhanced Citations."
        )

    backup_endpoints = _storage_endpoint_candidates(backup_connection_string, backup_blob_endpoint)
    enhanced_endpoints = _storage_endpoint_candidates(enhanced_connection_string, enhanced_blob_endpoint)
    if backup_endpoints and enhanced_endpoints and backup_endpoints.intersection(enhanced_endpoints):
        raise DataManagementSettingsValidationError(
            "Backup storage must use a dedicated Azure Storage account. It cannot use the same Blob endpoint configured for Enhanced Citations."
        )


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


def normalize_data_management_settings(payload=None, existing_settings=None, current_time=None, application_settings=None):
    feature_context = _get_data_management_feature_context(application_settings)
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
    if source["backup_storage_authentication_type"] == "connection_string":
        source["backup_storage_blob_endpoint"] = ""
    else:
        source["backup_storage_connection_string"] = ""
    source["backup_storage_container_name"] = _safe_text(source.get("backup_storage_container_name"), "simplechat-backups") or "simplechat-backups"
    source["backup_storage_path_prefix"] = _safe_text(source.get("backup_storage_path_prefix"), "simplechat-backups").strip("/") or "simplechat-backups"
    source["target_cosmos_authentication_type"] = _safe_text(source.get("target_cosmos_authentication_type"), "managed_identity")
    if source["target_cosmos_authentication_type"] not in {"managed_identity", "key"}:
        source["target_cosmos_authentication_type"] = "managed_identity"
    source["target_cosmos_endpoint"] = _safe_text(source.get("target_cosmos_endpoint"))
    source["target_cosmos_key"] = _safe_text(source.get("target_cosmos_key"))
    source["target_cosmos_subscription_id"] = _safe_text(source.get("target_cosmos_subscription_id"))
    source["target_cosmos_resource_group"] = _safe_text(source.get("target_cosmos_resource_group"))
    if source["target_cosmos_authentication_type"] == "managed_identity":
        source["target_cosmos_key"] = ""
    source["target_cosmos_database_name"] = DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME
    source["target_ai_search_authentication_type"] = _safe_text(source.get("target_ai_search_authentication_type"), "managed_identity")
    if source["target_ai_search_authentication_type"] not in {"managed_identity", "key"}:
        source["target_ai_search_authentication_type"] = "managed_identity"
    source["target_ai_search_endpoint"] = _safe_text(source.get("target_ai_search_endpoint"))
    source["target_ai_search_key"] = _safe_text(source.get("target_ai_search_key"))
    if source["target_ai_search_authentication_type"] == "managed_identity":
        source["target_ai_search_key"] = ""
    source["target_enhanced_citations_storage_authentication_type"] = _safe_text(source.get("target_enhanced_citations_storage_authentication_type"), "managed_identity")
    if source["target_enhanced_citations_storage_authentication_type"] not in {"managed_identity", "connection_string"}:
        source["target_enhanced_citations_storage_authentication_type"] = "managed_identity"
    source["target_enhanced_citations_storage_connection_string"] = _safe_text(source.get("target_enhanced_citations_storage_connection_string"))
    source["target_enhanced_citations_storage_blob_endpoint"] = _safe_text(source.get("target_enhanced_citations_storage_blob_endpoint"))
    if source["target_enhanced_citations_storage_authentication_type"] == "connection_string":
        source["target_enhanced_citations_storage_blob_endpoint"] = ""
    else:
        source["target_enhanced_citations_storage_connection_string"] = ""
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
    source["include_source_blobs"] = _safe_bool(source.get("include_source_blobs"), feature_context["enhanced_citations_enabled"])
    if feature_context["enhanced_citations_enabled"] and not source.get("last_settings_update_at") and not isinstance(payload, dict):
        source["include_source_blobs"] = True
    if not feature_context["enhanced_citations_enabled"]:
        source["include_source_blobs"] = False
    source["low_impact_mode"] = _safe_bool(source.get("low_impact_mode"), True)
    source["max_parallel_operations"] = _safe_int(source.get("max_parallel_operations"), default=1, minimum=1, maximum=5)
    source["backup_max_parallel_operations"] = _safe_int(
        source.get("backup_max_parallel_operations"),
        default=DATA_MANAGEMENT_BACKUP_DEFAULT_PARALLEL_OPERATIONS,
        minimum=1,
        maximum=DATA_MANAGEMENT_BACKUP_MAX_PARALLEL_OPERATIONS,
    )
    source["backup_retry_count"] = _safe_int(
        source.get("backup_retry_count"),
        default=DATA_MANAGEMENT_BACKUP_DEFAULT_RETRY_COUNT,
        minimum=1,
        maximum=DATA_MANAGEMENT_BACKUP_MAX_RETRY_COUNT,
    )
    source["backup_temporary_source_ru_enabled"] = _safe_bool(
        source.get("backup_temporary_source_ru_enabled"),
        False,
    )
    source["backup_temporary_source_ru"] = _safe_int(
        source.get("backup_temporary_source_ru"),
        default=DATA_MANAGEMENT_BACKUP_DEFAULT_SOURCE_RU,
        minimum=1000,
        maximum=DATA_MANAGEMENT_BACKUP_MAX_SOURCE_RU,
    )
    source["backup_capacity_failure_policy"] = _safe_text(
        source.get("backup_capacity_failure_policy"),
        DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE,
    )
    if source["backup_capacity_failure_policy"] not in DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICIES:
        source["backup_capacity_failure_policy"] = DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE
    source["migration_max_parallel_operations"] = _safe_int(
        source.get("migration_max_parallel_operations"),
        default=DATA_MANAGEMENT_MIGRATION_DEFAULT_PARALLEL_OPERATIONS,
        minimum=1,
        maximum=DATA_MANAGEMENT_MIGRATION_MAX_PARALLEL_OPERATIONS,
    )
    source["migration_retry_count"] = _safe_int(
        source.get("migration_retry_count"),
        default=DATA_MANAGEMENT_MIGRATION_DEFAULT_RETRY_COUNT,
        minimum=1,
        maximum=DATA_MANAGEMENT_MIGRATION_MAX_RETRY_COUNT,
    )
    source["migration_skip_recent_within_hours"] = _safe_int(
        source.get("migration_skip_recent_within_hours"),
        default=DATA_MANAGEMENT_MIGRATION_DEFAULT_SKIP_WITHIN_HOURS,
        minimum=0,
        maximum=DATA_MANAGEMENT_MIGRATION_MAX_SKIP_WITHIN_HOURS,
    )
    source["migration_temporary_destination_ru_enabled"] = _safe_bool(
        source.get("migration_temporary_destination_ru_enabled"),
        False,
    )
    source["migration_temporary_destination_ru"] = _safe_int(
        source.get("migration_temporary_destination_ru"),
        default=DATA_MANAGEMENT_MIGRATION_DEFAULT_DESTINATION_RU,
        minimum=1000,
        maximum=DATA_MANAGEMENT_MIGRATION_MAX_DESTINATION_RU,
    )

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
    feature_context = _get_data_management_feature_context()
    for field_name in DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS:
        if sanitized.get(field_name):
            sanitized[field_name] = DATA_MANAGEMENT_REDACTED_VALUE
    if not feature_context["enhanced_citations_enabled"]:
        sanitized["include_source_blobs"] = False
    sanitized.update(feature_context)
    sanitized["include_source_blobs_manageable"] = feature_context["enhanced_citations_enabled"]
    sanitized["operational_business_hours_warning"] = DATA_MANAGEMENT_OPERATIONAL_WARNING
    sanitized["default_scheduled_time_utc"] = DATA_MANAGEMENT_DEFAULT_TIME_UTC
    sanitized["partial_backup_frequency_label"] = "Daily"
    return sanitized


def update_data_management_settings(payload):
    existing = get_data_management_settings()
    application_settings = _get_application_settings_for_data_management()
    payload = dict(payload or {})
    for secret_field in DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS:
        if payload.get(secret_field) == DATA_MANAGEMENT_REDACTED_VALUE:
            payload[secret_field] = existing.get(secret_field, "")

    updated = normalize_data_management_settings(payload=payload, existing_settings=existing, application_settings=application_settings)
    validate_data_management_storage_is_dedicated(updated, application_settings=application_settings)
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
    validate_data_management_storage_is_dedicated(settings)
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
        application_settings = _get_application_settings_for_data_management()
        settings = normalize_data_management_settings(payload=settings_payload, existing_settings=existing_settings, application_settings=application_settings)
    else:
        application_settings = _get_application_settings_for_data_management()
        settings = normalize_data_management_settings(existing_settings=existing_settings, application_settings=application_settings)
    validate_data_management_storage_is_dedicated(settings, application_settings=application_settings)
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


def _normalize_data_management_settings_from_payload(settings=None):
    existing_settings = get_data_management_settings()
    if isinstance(settings, dict):
        settings_payload = dict(settings)
        for secret_field in DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS:
            if settings_payload.get(secret_field) == DATA_MANAGEMENT_REDACTED_VALUE:
                settings_payload[secret_field] = existing_settings.get(secret_field, "")
        application_settings = _get_application_settings_for_data_management()
        return normalize_data_management_settings(
            payload=settings_payload,
            existing_settings=existing_settings,
            application_settings=application_settings,
        )
    application_settings = _get_application_settings_for_data_management()
    return normalize_data_management_settings(existing_settings=existing_settings, application_settings=application_settings)


def test_target_cosmos_connection(settings=None, migration_plan=None):
    normalized_settings = _normalize_data_management_settings_from_payload(settings)
    target_database = _get_target_cosmos_database(normalized_settings)
    properties = target_database.read()
    normalized_plan = normalize_data_management_migration_plan({
        "migration_plan": migration_plan if isinstance(migration_plan, dict) else {},
    })
    selected_total = sum(
        len((normalized_plan.get(target_type) or {}).get("ids") or [])
        if (normalized_plan.get(target_type) or {}).get("mode") == "selected"
        else 1 if (normalized_plan.get(target_type) or {}).get("mode") == "all"
        else 0
        for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPE_ORDER
    )
    migration_access = None
    if selected_total:
        migration_access = _preflight_target_cosmos_migration_access(
            normalized_settings,
            normalized_plan,
        )
    capacity = None
    if normalized_settings.get("migration_temporary_destination_ru_enabled"):
        inspected_capacity = _inspect_target_cosmos_migration_capacity(
            normalized_settings,
            normalized_plan,
        )
        capacity = {
            "target_ru": inspected_capacity.get("target_ru"),
            "database_mode": inspected_capacity.get("database_mode"),
            "database_current_ru": inspected_capacity.get("database_current_ru"),
            "targets": inspected_capacity.get("targets"),
        }
    result = {
        "success": True,
        "target": "cosmos",
        "database_name": properties.get("id") or DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME,
        "authentication_type": normalized_settings.get("target_cosmos_authentication_type"),
        "migration_access": migration_access,
        "capacity": capacity,
    }
    return result


def test_target_search_connection(settings=None):
    normalized_settings = _normalize_data_management_settings_from_payload(settings)
    endpoint = _safe_text(normalized_settings.get("target_ai_search_endpoint"))
    if not endpoint:
        raise ValueError("Target Search endpoint is required.")
    index_client = SearchIndexClient(
        endpoint=endpoint,
        credential=_get_target_ai_search_credential(normalized_settings),
        connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        retry_total=0,
    )
    existing_indexes = set(index_client.list_index_names())
    expected_indexes = [artifact["index_name"] for artifact in DATA_MANAGEMENT_SEARCH_ARTIFACTS]
    return {
        "success": True,
        "target": "search",
        "authentication_type": normalized_settings.get("target_ai_search_authentication_type"),
        "expected_indexes": expected_indexes,
        "existing_indexes": sorted(existing_indexes.intersection(expected_indexes)),
        "missing_indexes": [index_name for index_name in expected_indexes if index_name not in existing_indexes],
    }


def test_target_enhanced_citation_storage_connection(settings=None, create_containers=False):
    normalized_settings = _normalize_data_management_settings_from_payload(settings)
    blob_service_client = _get_target_enhanced_citations_blob_client(normalized_settings)
    container_results = []
    for container_name in _source_blob_container_names():
        container_client = blob_service_client.get_container_client(container_name)
        exists = container_client.exists()
        created = False
        if not exists and create_containers:
            container_client.create_container()
            exists = True
            created = True
        container_results.append({
            "container_name": container_name,
            "container_exists": exists,
            "container_created": created,
        })
    return {
        "success": True,
        "target": "enhanced_citation_storage",
        "authentication_type": normalized_settings.get("target_enhanced_citations_storage_authentication_type"),
        "containers": container_results,
    }


def _safe_list(value, limit=1000):
    if not isinstance(value, list):
        return []
    results = []
    seen = set()
    for item in value:
        normalized = _safe_text(item)
        if not normalized or normalized in seen:
            continue
        results.append(normalized)
        seen.add(normalized)
        if len(results) >= limit:
            break
    return results


def _normalize_migration_selection(selection=None):
    selection = selection if isinstance(selection, dict) else {}
    mode = _safe_text(selection.get("mode"), "none")
    if mode not in {"none", "all", "selected"}:
        mode = "none"
    ids = _safe_list(selection.get("ids"), limit=2000)
    if mode == "selected" and not ids:
        mode = "none"
    return {
        "mode": mode,
        "ids": ids if mode == "selected" else [],
        "include_documents": _safe_bool(selection.get("include_documents"), False),
    }


def _get_target_cosmos_client(settings):
    endpoint = _safe_text((settings or {}).get("target_cosmos_endpoint"))
    if not endpoint:
        raise ValueError("Target Cosmos endpoint is required before running migration.")
    if (settings or {}).get("target_cosmos_authentication_type") == "key":
        key = _safe_text((settings or {}).get("target_cosmos_key"))
        if not key:
            raise ValueError("Target Cosmos account key is required when account key authentication is selected.")
        return azure_cosmos.CosmosClient(
            endpoint,
            credential=key,
            consistency_level="Session",
            connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
            timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        )
    return azure_cosmos.CosmosClient(
        endpoint,
        credential=DefaultAzureCredential(),
        consistency_level="Session",
        connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
    )


def _get_target_cosmos_database(settings):
    return _get_target_cosmos_client(settings).create_database_if_not_exists(
        DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME
    )


def _get_existing_target_cosmos_database(settings):
    """Open the destination database without creating resources during preview."""
    database = _get_target_cosmos_client(settings).get_database_client(
        DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME
    )
    database.read()
    return database


def _get_target_cosmos_container(target_database, container_name, partition_key_path):
    target_container = target_database.create_container_if_not_exists(
        id=container_name,
        partition_key=PartitionKey(path=partition_key_path),
    )
    _validate_target_cosmos_container_partition_key(
        target_container,
        container_name,
        partition_key_path,
    )
    return target_container


def _get_target_data_management_search_write_gate_container(target_database):
    """Open the target SimpleChat job container used to coordinate Search writers."""
    return _get_target_cosmos_container(
        target_database,
        getattr(
            app_config,
            "cosmos_data_management_jobs_container_name",
            "data_management_jobs",
        ),
        "/id",
    )


def _get_target_search_write_fence_lease_seconds(settings):
    """Keep uncertain target Search writes quarantined beyond their bounded request lifetime."""
    return min(
        _get_migration_lock_lease_seconds(settings),
        DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS +
        DATA_MANAGEMENT_MIGRATION_LOCK_RECOVERY_GRACE_SECONDS,
    )


def _set_target_migration_coordinator_runtime(job_id, container, coordinator):
    """Keep non-serializable target SDK state out of durable migration job records."""
    with DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_RUNTIME_LOCK:
        DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_RUNTIME[_safe_text(job_id)] = {
            "container": container,
            "coordinator": coordinator,
        }


def _get_target_migration_coordinator_runtime(job_id):
    with DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_RUNTIME_LOCK:
        return DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_RUNTIME.get(_safe_text(job_id))


def _clear_target_migration_coordinator_runtime(job_id):
    with DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_RUNTIME_LOCK:
        return DATA_MANAGEMENT_TARGET_MIGRATION_COORDINATOR_RUNTIME.pop(
            _safe_text(job_id),
            None,
        )


def _acquire_target_migration_coordinator(job, target_database, settings):
    """Acquire a destination-wide lease before this source performs any migration work."""
    target_container = _get_target_data_management_search_write_gate_container(
        target_database
    )
    coordinator = acquire_data_management_target_migration_coordinator(
        target_container,
        job.get("id"),
        _get_migration_lock_lease_seconds(settings),
        existing_lock=(
            job.get("target_migration_coordinator")
            if isinstance(job.get("target_migration_coordinator"), dict)
            else None
        ),
    )
    job["target_migration_coordinator"] = copy.deepcopy(coordinator)
    _set_target_migration_coordinator_runtime(
        job.get("id"),
        target_container,
        coordinator,
    )
    return coordinator


def _renew_target_migration_coordinator(job, settings):
    """Renew the destination-wide coordinator that protects independent source deployments."""
    runtime = _get_target_migration_coordinator_runtime(job.get("id"))
    if not isinstance(runtime, dict):
        return
    coordinator = runtime.get("coordinator")
    target_container = runtime.get("container")
    if not isinstance(coordinator, dict) or target_container is None:
        return
    try:
        renewed_coordinator = renew_data_management_target_migration_coordinator(
            target_container,
            coordinator,
            _get_migration_lock_lease_seconds({
                "data_management_job_lease_seconds": (
                    (settings or {}).get("data_management_job_lease_seconds") or
                    coordinator.get("lease_seconds")
                ),
            }),
        )
    except Exception as exc:
        raise DataManagementMigrationLeaseLostError(
            "The target migration coordinator was lost or could not be renewed."
        ) from exc
    job["target_migration_coordinator"] = copy.deepcopy(renewed_coordinator)


def _release_target_migration_coordinator(job):
    """Release a cleanly completed or drained-canceled destination coordinator lease."""
    runtime = _clear_target_migration_coordinator_runtime(job.get("id"))
    if not isinstance(runtime, dict):
        return False
    try:
        return release_data_management_target_migration_coordinator(
            runtime.get("container"),
            runtime.get("coordinator"),
        )
    except Exception:
        return False


def _validate_target_cosmos_container_partition_key(target_container, container_name, expected_path):
    """Reject existing target containers whose partition key differs from SimpleChat's contract."""
    container_read = getattr(target_container, "read", None)
    if not callable(container_read):
        return
    properties = container_read()
    partition_key = properties.get("partitionKey") if isinstance(properties, dict) else None
    actual_paths = partition_key.get("paths") if isinstance(partition_key, dict) else None
    if not isinstance(actual_paths, list) or actual_paths != [expected_path]:
        raise DataManagementSettingsValidationError(
            f"Destination Cosmos container '{container_name}' has partition key paths "
            f"{actual_paths!r}; expected [{expected_path!r}]."
        )


def _iter_migration_cosmos_container_definitions(migration_plan):
    """Yield only destination containers that the selected migration can write."""
    for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPE_ORDER:
        selection = (migration_plan or {}).get(target_type) or {}
        if selection.get("mode") == "none":
            continue
        for container_definition in DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS[target_type]:
            if container_definition.get("documents") and not selection.get("include_documents"):
                continue
            yield target_type, container_definition


def _target_cosmos_container_name(container_definition):
    return getattr(
        app_config,
        container_definition["container_name_attr"],
        container_definition["name"],
    )


def _get_migration_parallel_operations(settings):
    return _safe_int(
        (settings or {}).get("migration_max_parallel_operations"),
        default=DATA_MANAGEMENT_MIGRATION_DEFAULT_PARALLEL_OPERATIONS,
        minimum=1,
        maximum=DATA_MANAGEMENT_MIGRATION_MAX_PARALLEL_OPERATIONS,
    )


def _get_backup_parallel_operations(settings, backup_plan=None):
    execution = (backup_plan or {}).get("cosmos_execution") if isinstance(backup_plan, dict) else {}
    configured_value = (
        (execution or {}).get("max_parallel_operations")
        if isinstance(execution, dict) and "max_parallel_operations" in execution else
        (settings or {}).get("backup_max_parallel_operations")
        if backup_plan is None else
        DATA_MANAGEMENT_BACKUP_DEFAULT_PARALLEL_OPERATIONS
    )
    return _safe_int(
        configured_value,
        default=DATA_MANAGEMENT_BACKUP_DEFAULT_PARALLEL_OPERATIONS,
        minimum=1,
        maximum=DATA_MANAGEMENT_BACKUP_MAX_PARALLEL_OPERATIONS,
    )


def _get_backup_retry_count(settings, backup_plan=None):
    execution = (backup_plan or {}).get("cosmos_execution") if isinstance(backup_plan, dict) else {}
    configured_value = (
        (execution or {}).get("retry_count")
        if isinstance(execution, dict) and "retry_count" in execution else
        (settings or {}).get("backup_retry_count")
        if backup_plan is None else
        DATA_MANAGEMENT_BACKUP_DEFAULT_RETRY_COUNT
    )
    return _safe_int(
        configured_value,
        default=DATA_MANAGEMENT_BACKUP_DEFAULT_RETRY_COUNT,
        minimum=1,
        maximum=DATA_MANAGEMENT_BACKUP_MAX_RETRY_COUNT,
    )


def _get_backup_capacity_failure_policy(settings, backup_plan=None):
    execution = (backup_plan or {}).get("cosmos_execution") if isinstance(backup_plan, dict) else {}
    configured_value = (
        (execution or {}).get("capacity_failure_policy")
        if isinstance(execution, dict) and "capacity_failure_policy" in execution else
        (settings or {}).get("backup_capacity_failure_policy")
        if backup_plan is None else
        DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE
    )
    policy = _safe_text(
        configured_value,
        DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE,
    )
    if policy not in DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICIES:
        return DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE
    return policy


def _get_backup_temporary_source_ru(settings, backup_plan=None):
    execution = (backup_plan or {}).get("cosmos_execution") if isinstance(backup_plan, dict) else {}
    configured_value = (
        (execution or {}).get("temporary_source_ru")
        if isinstance(execution, dict) and "temporary_source_ru" in execution else
        (settings or {}).get("backup_temporary_source_ru")
        if backup_plan is None else
        DATA_MANAGEMENT_BACKUP_DEFAULT_SOURCE_RU
    )
    return _safe_int(
        configured_value,
        default=DATA_MANAGEMENT_BACKUP_DEFAULT_SOURCE_RU,
        minimum=1000,
        maximum=DATA_MANAGEMENT_BACKUP_MAX_SOURCE_RU,
    )


def _get_migration_retry_count(settings):
    return _safe_int(
        (settings or {}).get("migration_retry_count"),
        default=DATA_MANAGEMENT_MIGRATION_DEFAULT_RETRY_COUNT,
        minimum=1,
        maximum=DATA_MANAGEMENT_MIGRATION_MAX_RETRY_COUNT,
    )


def _get_target_cosmos_account_name(endpoint):
    normalized_endpoint = _safe_text(endpoint)
    if not normalized_endpoint:
        return ""
    parsed_endpoint = urlparse(
        normalized_endpoint if "://" in normalized_endpoint else f"https://{normalized_endpoint}"
    )
    hostname = parsed_endpoint.hostname or ""
    return hostname.split(".")[0].strip()


def _get_target_cosmos_management_settings(settings):
    account_name = _get_target_cosmos_account_name((settings or {}).get("target_cosmos_endpoint"))
    management_settings = {
        "cosmos_throughput_subscription_id": _safe_text(
            (settings or {}).get("target_cosmos_subscription_id")
        ),
        "cosmos_throughput_resource_group": _safe_text(
            (settings or {}).get("target_cosmos_resource_group")
        ),
        "cosmos_throughput_account_name": account_name,
        "cosmos_throughput_database_name": DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME,
    }
    missing_values = [
        field_name
        for field_name, value in management_settings.items()
        if not value
    ]
    if missing_values:
        raise DataManagementSettingsValidationError(
            "Destination Cosmos capacity management requires "
            f"{', '.join(missing_values)}."
        )
    return management_settings


def _get_source_cosmos_management_settings():
    """Resolve local Cosmos ARM routing without exposing it to backup progress APIs."""
    application_settings = _get_application_settings_for_data_management()
    return {
        "cosmos_throughput_subscription_id": _safe_text(
            application_settings.get("cosmos_throughput_subscription_id")
        ),
        "cosmos_throughput_resource_group": _safe_text(
            application_settings.get("cosmos_throughput_resource_group")
        ),
        "cosmos_throughput_account_name": _safe_text(
            application_settings.get("cosmos_throughput_account_name")
        ),
        "cosmos_throughput_database_name": _safe_text(
            application_settings.get("cosmos_throughput_database_name"),
            DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME,
        ),
    }


def _build_migration_configuration_snapshot(settings, migration_plan):
    """Build a durable state fingerprint without copying credential material."""
    return {
        "migration_plan": copy.deepcopy(migration_plan),
        "parallel_operations": _get_migration_parallel_operations(settings),
        "retry_count": _get_migration_retry_count(settings),
        "skip_recent_within_hours": _safe_int(
            (settings or {}).get("migration_skip_recent_within_hours"),
            default=DATA_MANAGEMENT_MIGRATION_DEFAULT_SKIP_WITHIN_HOURS,
            minimum=0,
            maximum=DATA_MANAGEMENT_MIGRATION_MAX_SKIP_WITHIN_HOURS,
        ),
        "temporary_destination_ru_enabled": _safe_bool(
            (settings or {}).get("migration_temporary_destination_ru_enabled"),
            False,
        ),
        "temporary_destination_ru": _safe_int(
            (settings or {}).get("migration_temporary_destination_ru"),
            default=DATA_MANAGEMENT_MIGRATION_DEFAULT_DESTINATION_RU,
            minimum=1000,
            maximum=DATA_MANAGEMENT_MIGRATION_MAX_DESTINATION_RU,
        ),
        "target_cosmos_endpoint": _safe_text((settings or {}).get("target_cosmos_endpoint")),
        "target_cosmos_authentication_type": _safe_text(
            (settings or {}).get("target_cosmos_authentication_type")
        ),
        "target_cosmos_subscription_id": _safe_text(
            (settings or {}).get("target_cosmos_subscription_id")
        ),
        "target_cosmos_resource_group": _safe_text(
            (settings or {}).get("target_cosmos_resource_group")
        ),
        "target_ai_search_endpoint": _safe_text((settings or {}).get("target_ai_search_endpoint")),
        "target_ai_search_authentication_type": _safe_text(
            (settings or {}).get("target_ai_search_authentication_type")
        ),
        "target_enhanced_citations_storage_endpoint": _safe_text(
            (settings or {}).get("target_enhanced_citations_storage_blob_endpoint")
        ),
        "target_enhanced_citations_storage_authentication_type": _safe_text(
            (settings or {}).get("target_enhanced_citations_storage_authentication_type")
        ),
    }


def _migration_plan_scope_signature(migration_plan):
    """Return the source scope fields that must match an incremental baseline."""
    signature = {
        "include_ai_search": bool((migration_plan or {}).get("include_ai_search")),
        "include_source_blobs": bool((migration_plan or {}).get("include_source_blobs")),
    }
    for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPE_ORDER:
        selection = (migration_plan or {}).get(target_type) or {}
        signature[target_type] = {
            "mode": _safe_text(selection.get("mode"), "none"),
            "ids": sorted(_dedupe_limited_strings(selection.get("ids"), limit=2000)),
            "include_documents": bool(selection.get("include_documents")),
        }
    return signature


def _migration_destination_signature(configuration, migration_plan):
    """Return normalized destination identities without credential material."""
    return {
        "cosmos": _safe_text((configuration or {}).get("target_cosmos_endpoint")).lower(),
        "ai_search": (
            _safe_text((configuration or {}).get("target_ai_search_endpoint")).lower()
            if (migration_plan or {}).get("include_ai_search") else ""
        ),
        "source_blobs": (
            _safe_text(
                (configuration or {}).get("target_enhanced_citations_storage_endpoint")
            ).lower()
            if (migration_plan or {}).get("include_source_blobs") else ""
        ),
    }


def _validate_incremental_baseline_job(candidate_job, current_job, current_configuration, migration_plan):
    """Return a compatible completed cutoff or reject an unsafe baseline."""
    candidate_state = candidate_job.get("migration_state") if isinstance(candidate_job, dict) else None
    candidate_configuration = (
        candidate_state.get("configuration")
        if isinstance(candidate_state, dict) and isinstance(candidate_state.get("configuration"), dict)
        else {}
    )
    candidate_plan = candidate_configuration.get("migration_plan")
    candidate_plan = candidate_plan if isinstance(candidate_plan, dict) else {}
    candidate_result = candidate_job.get("result") if isinstance(candidate_job, dict) else {}
    reconciliation_resource = (
        (candidate_state.get("resources") or {}).get("reconciliation:cutover")
        if isinstance(candidate_state, dict) else None
    )
    reconciliation_result = (
        reconciliation_resource.get("result")
        if isinstance(reconciliation_resource, dict) and
        isinstance(reconciliation_resource.get("result"), dict)
        else {}
    )
    if (
        not isinstance(candidate_job, dict) or
        candidate_job.get("id") == (current_job or {}).get("id") or
        candidate_job.get("operation") != DATA_MANAGEMENT_OPERATION_MIGRATION or
        candidate_job.get("status") not in {
            DATA_MANAGEMENT_STATUS_COMPLETED,
            DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS,
        } or
        not isinstance(candidate_state, dict) or
        candidate_state.get("status") != MIGRATION_RESOURCE_STATUS_COMPLETED or
        (isinstance(candidate_result, dict) and candidate_result.get("dry_run")) or
        reconciliation_result.get("readiness") not in {"ready", "ready_with_warnings"}
    ):
        raise DataManagementSettingsValidationError(
            "Incremental migration baseline must be a completed, reconciled, non-dry-run migration."
        )
    if _migration_plan_scope_signature(candidate_plan) != _migration_plan_scope_signature(migration_plan):
        raise DataManagementSettingsValidationError(
            "Incremental migration baseline uses a different source scope."
        )
    if (
        _migration_destination_signature(candidate_configuration, candidate_plan) !=
        _migration_destination_signature(current_configuration, migration_plan)
    ):
        raise DataManagementSettingsValidationError(
            "Incremental migration baseline targets a different destination."
        )
    source_cutoff_at = _safe_text(candidate_state.get("source_cutoff_at"))
    if _parse_iso_datetime(source_cutoff_at) is None:
        raise DataManagementSettingsValidationError(
            "Incremental migration baseline does not contain a valid source watermark."
        )
    return source_cutoff_at


def _get_completed_migration_baseline_candidates(limit=100):
    query = (
        "SELECT * FROM c WHERE c.type = @type AND c.operation = @operation "
        "AND (c.status = @completed OR c.status = @completed_with_warnings) "
        "ORDER BY c.completed_at DESC"
    )
    parameters = [
        {"name": "@type", "value": DATA_MANAGEMENT_JOB_TYPE},
        {"name": "@operation", "value": DATA_MANAGEMENT_OPERATION_MIGRATION},
        {"name": "@completed", "value": DATA_MANAGEMENT_STATUS_COMPLETED},
        {
            "name": "@completed_with_warnings",
            "value": DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS,
        },
    ]
    return list(cosmos_data_management_jobs_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
        max_item_count=limit,
    ))[:limit]


def _resolve_data_management_migration_baseline(job, settings, migration_plan):
    """Resolve one immutable prior cutoff for delta and mirror migration modes."""
    resolved_plan = copy.deepcopy(migration_plan)
    migration_mode = resolved_plan.get("migration_mode", DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY)
    if migration_mode == DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY:
        resolved_plan["baseline_job_id"] = ""
        resolved_plan["baseline_source_cutoff_at"] = ""
        return resolved_plan

    existing_state = job.get("migration_state") if isinstance(job, dict) else None
    existing_configuration = (
        existing_state.get("configuration")
        if isinstance(existing_state, dict) and isinstance(existing_state.get("configuration"), dict)
        else {}
    )
    existing_plan = existing_configuration.get("migration_plan")
    if isinstance(existing_plan, dict) and existing_plan.get("baseline_source_cutoff_at"):
        resolved_plan["baseline_job_id"] = _safe_text(existing_plan.get("baseline_job_id"))
        resolved_plan["baseline_source_cutoff_at"] = _safe_text(
            existing_plan.get("baseline_source_cutoff_at")
        )
        return resolved_plan

    current_configuration = _build_migration_configuration_snapshot(settings, resolved_plan)
    requested_baseline_job_id = _safe_text(resolved_plan.get("baseline_job_id"))
    if requested_baseline_job_id:
        candidate_jobs = [_read_job(requested_baseline_job_id)]
    else:
        candidate_jobs = _get_completed_migration_baseline_candidates()

    incompatibility_messages = []
    for candidate_job in candidate_jobs:
        try:
            source_cutoff_at = _validate_incremental_baseline_job(
                candidate_job,
                job,
                current_configuration,
                resolved_plan,
            )
        except DataManagementSettingsValidationError as exc:
            incompatibility_messages.append(str(exc))
            if requested_baseline_job_id:
                raise
            continue
        resolved_plan["baseline_job_id"] = _safe_text(candidate_job.get("id"))
        resolved_plan["baseline_source_cutoff_at"] = source_cutoff_at
        return resolved_plan

    detail = incompatibility_messages[0] if incompatibility_messages else "No completed migration was found."
    raise DataManagementSettingsValidationError(
        f"Incremental migration requires a compatible completed baseline. {detail}"
    )


def _initialize_data_management_migration_state(job, settings, migration_plan):
    """Persist the job's stable migration identity before target writes begin."""
    configuration = _build_migration_configuration_snapshot(settings, migration_plan)
    state = initialize_migration_state(
        job.get("migration_state"),
        str(job.get("id")),
        configuration,
    )
    job["migration_state"] = state
    context = create_migration_provenance_context(
        migration_id=state["migration_id"],
        migrated_at_utc=state["source_cutoff_at"],
        skip_within_hours=configuration["skip_recent_within_hours"],
    )
    migration_mode = migration_plan.get(
        "migration_mode",
        DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
    )
    baseline_source_cutoff_at = _safe_text(migration_plan.get("baseline_source_cutoff_at"))
    state["incremental"] = {
        "mode": migration_mode,
        "baseline_job_id": _safe_text(migration_plan.get("baseline_job_id")),
        "baseline_source_cutoff_at": baseline_source_cutoff_at,
        "source_cutoff_at": state["source_cutoff_at"],
        "deletion_policy": (
            "confirmed_migration_owned_only"
            if migration_mode == DATA_MANAGEMENT_MIGRATION_MODE_MIRROR else
            "disabled"
        ),
    }
    state["watermarks"] = {
        "baseline": baseline_source_cutoff_at,
        "current_cutoff": state["source_cutoff_at"],
        "cosmos": {"strategy": "_ts_content_hash_with_identity", "through": state["source_cutoff_at"]},
        "ai_search": {"strategy": "id_keyset_with_observed_source_hash", "through": None},
        "source_blobs": {"strategy": "stable_etag_with_path", "through": None},
    }
    context.update({
        "migration_mode": migration_mode,
        "baseline_job_id": state["incremental"]["baseline_job_id"],
        "baseline_source_cutoff_at": baseline_source_cutoff_at,
    })
    return state, context


def _set_document_path_value(document, partition_key_path, value):
    """Set a simple or nested Cosmos partition-key value in a probe document."""
    path_parts = [part for part in _safe_text(partition_key_path).strip("/").split("/") if part]
    if not path_parts:
        raise DataManagementSettingsValidationError("Destination Cosmos container has an invalid partition key path.")
    current = document
    for path_part in path_parts[:-1]:
        nested = current.get(path_part)
        if not isinstance(nested, dict):
            nested = {}
            current[path_part] = nested
        current = nested
    current[path_parts[-1]] = value
    return value


def _verify_target_cosmos_container_access(target_container, partition_key_path):
    """Prove the destination has create, read, and delete data-plane access."""
    probe_id = f"simplechat-migration-preflight-{uuid.uuid4().hex}"
    probe_document = {
        "id": probe_id,
        "type": "simplechat_migration_preflight",
        "created_at": _now_iso(),
    }
    partition_key_value = _set_document_path_value(probe_document, partition_key_path, probe_id)
    target_container.create_item(body=probe_document)
    try:
        target_container.read_item(item=probe_id, partition_key=partition_key_value)
    finally:
        target_container.delete_item(item=probe_id, partition_key=partition_key_value)


def _preflight_target_cosmos_migration_access(settings, migration_plan):
    """Create planned containers and verify their destination data-plane permissions."""
    target_database = _get_target_cosmos_database(settings)
    container_results = []
    for target_type, container_definition in _iter_migration_cosmos_container_definitions(migration_plan):
        source_container = getattr(app_config, container_definition["container_attr"], None)
        if source_container is None:
            raise DataManagementSettingsValidationError(
                f"Source Cosmos container '{container_definition['name']}' is not initialized."
            )
        source_probe = source_container.query_items(
            query="SELECT TOP 1 * FROM c",
            enable_cross_partition_query=True,
        )
        next(iter(source_probe), None)
        target_container_name = _target_cosmos_container_name(container_definition)
        target_container = _get_target_cosmos_container(
            target_database,
            target_container_name,
            container_definition["partition_key_path"],
        )
        _verify_target_cosmos_container_access(
            target_container,
            container_definition["partition_key_path"],
        )
        container_results.append({
            "target_type": target_type,
            "container_name": target_container_name,
            "partition_key_path": container_definition["partition_key_path"],
            "source_read_verified": True,
            "destination_write_verified": True,
        })
    return {
        "database_name": DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME,
        "container_count": len(container_results),
        "containers": container_results,
    }


def _inspect_target_cosmos_migration_capacity(settings, migration_plan):
    """Read destination capacity targets before an optional temporary RU boost."""
    management_settings = _get_target_cosmos_management_settings(settings)
    database_throughput = get_database_throughput(management_settings)
    targets = []
    if database_throughput.get("is_scalable"):
        targets.append({
            "scope": "database",
            "container_name": "",
            "mode": database_throughput.get("mode"),
            "current_ru": database_throughput.get("current_ru"),
        })
    else:
        seen_container_names = set()
        for _, container_definition in _iter_migration_cosmos_container_definitions(migration_plan):
            container_name = _target_cosmos_container_name(container_definition)
            if container_name in seen_container_names:
                continue
            seen_container_names.add(container_name)
            container_throughput = get_container_throughput(management_settings, container_name)
            if container_throughput.get("is_scalable"):
                targets.append({
                    "scope": "container",
                    "container_name": container_name,
                    "mode": container_throughput.get("mode"),
                    "current_ru": container_throughput.get("current_ru"),
                })
    if not targets:
        raise CosmosThroughputError(
            "Destination Cosmos throughput is not scalable at the database or selected container level."
        )
    return {
        "target_ru": _safe_int(
            (settings or {}).get("migration_temporary_destination_ru"),
            default=DATA_MANAGEMENT_MIGRATION_DEFAULT_DESTINATION_RU,
            minimum=1000,
            maximum=DATA_MANAGEMENT_MIGRATION_MAX_DESTINATION_RU,
        ),
        "management_settings": management_settings,
        "database_mode": database_throughput.get("mode"),
        "database_current_ru": database_throughput.get("current_ru"),
        "targets": targets,
    }


def _get_data_management_job_lease_seconds(settings):
    return _safe_int(
        (settings or {}).get("data_management_job_lease_seconds"),
        default=DATA_MANAGEMENT_DEFAULT_LEASE_SECONDS,
        minimum=60,
        maximum=7200,
    )


def _migration_resource_metrics(resource):
    if not isinstance(resource, dict):
        return {}
    result = resource.get("result")
    if isinstance(result, dict) and result:
        return result
    progress = resource.get("progress")
    return progress if isinstance(progress, dict) else {}


def _update_migration_state_totals(state):
    totals = {
        "copied_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "collision_count": 0,
        "processed_count": 0,
        "bytes": 0,
        "request_units": 0.0,
    }
    for resource in (state.get("resources") or {}).values():
        metrics = _migration_resource_metrics(resource)
        for field_name in (
            "copied_count",
            "skipped_count",
            "failed_count",
            "collision_count",
            "processed_count",
            "bytes",
        ):
            totals[field_name] += _safe_int(metrics.get(field_name), default=0, minimum=0)
        try:
            totals["request_units"] += max(0.0, float(metrics.get("request_units") or 0.0))
        except (TypeError, ValueError):
            continue
    totals["request_units"] = round(totals["request_units"], 3)
    state["totals"] = totals
    return totals


def _migration_progress_marker(progress):
    marker_fields = (
        "copied_count",
        "created_count",
        "updated_count",
        "unchanged_count",
        "skipped_count",
        "failed_count",
        "collision_count",
        "missing_count",
        "not_applicable_count",
        "processed_count",
        "bytes",
        "observed_bytes",
        "request_units",
        "source_read_count",
        "destination_accepted_count",
        "destination_failed_count",
        "completed_count",
        "services_completed",
    )
    return tuple((field_name, (progress or {}).get(field_name)) for field_name in marker_fields)


def _persist_migration_checkpoint(
    job,
    state,
    settings,
    resource_name,
    progress,
    message,
    allow_cancel_requested=False,
):
    """Save a batch checkpoint and renew the worker lease without timeline noise."""
    _assert_migration_job_lease(
        job,
        allow_cancel_requested=allow_cancel_requested,
    )
    previous_resource = (state.get("resources") or {}).get(resource_name) or {}
    previous_progress = (
        previous_resource.get("progress")
        if isinstance(previous_resource.get("progress"), dict)
        else {}
    )
    now = _now_utc()
    if _migration_progress_marker(progress) != _migration_progress_marker(previous_progress):
        progress["last_progress_at"] = now.isoformat()
        state["last_progress_at"] = now.isoformat()
        job["last_progress_at"] = now.isoformat()
    else:
        progress["last_progress_at"] = (
            previous_progress.get("last_progress_at") or
            state.get("last_progress_at") or
            job.get("last_progress_at")
        )
    update_migration_resource(state, resource_name, progress)
    _update_migration_state_totals(state)
    job.update({
        "migration_state": state,
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": message,
    })
    _save_data_management_job(job)
    return job.get("migration_state") if isinstance(job.get("migration_state"), dict) else state


def _persist_migration_heartbeat(job, settings, message):
    """Renew worker and coordinator leases without advancing resource progress."""
    _assert_migration_job_lease(job)
    now = _now_utc()
    job.update({
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": message,
    })
    return _save_data_management_job(job)


def _complete_migration_resource_checkpoint(job, state, settings, resource_name, result, message):
    """Complete a resource after its final durable checkpoint is written."""
    _assert_migration_job_lease(job)
    complete_migration_resource(state, resource_name, result=result)
    _update_migration_state_totals(state)
    now = _now_utc()
    result["last_progress_at"] = now.isoformat()
    state["last_progress_at"] = now.isoformat()
    job.update({
        "migration_state": state,
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "last_progress_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": message,
    })
    _save_data_management_job(job)
    return job.get("migration_state") if isinstance(job.get("migration_state"), dict) else state


def _fail_migration_resource_checkpoint(job, state, settings, resource_name, error_message):
    """Persist a failed resource before allowing the job to be retried."""
    _assert_migration_job_lease(job)
    fail_migration_resource(state, resource_name, error_message)
    _update_migration_state_totals(state)
    now = _now_utc()
    job.update({
        "migration_state": state,
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": f"Migration resource failed: {resource_name}",
    })
    _save_data_management_job(job)
    return job.get("migration_state") if isinstance(job.get("migration_state"), dict) else state


def _persist_migration_state(
    job,
    state,
    settings,
    message,
    allow_cancel_requested=False,
):
    """Persist non-resource migration state changes and renew the worker lease."""
    _assert_migration_job_lease(
        job,
        allow_cancel_requested=allow_cancel_requested,
    )
    now = _now_utc()
    job.update({
        "migration_state": state,
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": message,
    })
    _save_data_management_job(job)
    return job.get("migration_state") if isinstance(job.get("migration_state"), dict) else state


def _preflight_target_ai_search_migration_access(settings, migration_plan):
    """Ensure target indexes are writable and have provenance fields before copying."""
    _validate_target_ai_search_migration_write_safety(settings, migration_plan)
    target_database = None
    target_search_write_gate_verified = False
    results = []
    search_mappings = [
        ("users", DATA_MANAGEMENT_SEARCH_ARTIFACTS[0]),
        ("groups", DATA_MANAGEMENT_SEARCH_ARTIFACTS[1]),
        ("public_workspaces", DATA_MANAGEMENT_SEARCH_ARTIFACTS[2]),
    ]
    for target_type, artifact in search_mappings:
        selection = (migration_plan or {}).get(target_type) or {}
        if selection.get("mode") == "none" or not selection.get("include_documents"):
            continue
        if target_database is None:
            target_database = _get_target_cosmos_database(settings)
            target_search_write_gate_container = _get_target_data_management_search_write_gate_container(
                target_database
            )
            _verify_target_cosmos_container_access(
                target_search_write_gate_container,
                "/id",
            )
            target_search_write_gate_verified = True
        source_client = CLIENTS.get(artifact["client_key"])
        if not source_client:
            raise DataManagementSettingsValidationError(
                f"Source AI Search client '{artifact['name']}' is not initialized."
            )
        next(iter(source_client.search(
            search_text="*",
            top=1,
            connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
            read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
            retry_total=0,
        )), None)
        index_status = _ensure_target_search_index(
            settings,
            artifact["index_name"],
            artifact["schema_file"],
        )
        target_client = _get_target_search_client(settings, artifact["index_name"])
        probe_id = f"simplechat-migration-preflight-{uuid.uuid4().hex}"
        probe_document = {
            "id": probe_id,
            SEARCH_MIGRATION_ID_FIELD: probe_id,
            SEARCH_MIGRATED_AT_FIELD: _now_iso(),
            SEARCH_MIGRATION_STATUS_FIELD: "preflight",
        }
        probe_written = False
        probe_succeeded = False
        try:
            upload_results = list(target_client.upload_documents(
                documents=[probe_document],
                connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                retry_total=0,
            ))
            if not upload_results or not _get_search_result_succeeded(upload_results[0]):
                raise DataManagementSettingsValidationError(
                    f"Destination AI Search index '{artifact['index_name']}' rejected a write probe."
                )
            probe_written = True
            read_results = list(target_client.search(
                search_text="*",
                filter=f"id eq '{_escape_search_filter_value(probe_id)}'",
                select=["id"],
                top=1,
                connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                retry_total=0,
            ))
            if not any(_safe_text(dict(item).get("id")) == probe_id for item in read_results):
                raise DataManagementSettingsValidationError(
                    f"Destination AI Search index '{artifact['index_name']}' did not return its write probe."
                )
            probe_succeeded = True
        finally:
            if probe_written:
                try:
                    delete_results = list(target_client.delete_documents(
                        documents=[{"id": probe_id}],
                        connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                        read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                        retry_total=0,
                    ))
                    if delete_results and not _get_search_result_succeeded(delete_results[0]):
                        raise DataManagementSettingsValidationError(
                            f"Destination AI Search index '{artifact['index_name']}' rejected write-probe cleanup."
                        )
                except Exception:
                    if probe_succeeded:
                        raise
        results.append({
            "target_type": target_type,
            "index_name": artifact["index_name"],
            "source_read_verified": True,
            "destination_write_verified": True,
            "index_status": index_status,
        })
    return {
        "index_count": len(results),
        "indexes": results,
        "target_search_write_gate_verified": target_search_write_gate_verified,
    }


def _preflight_target_blob_migration_access(settings, migration_plan):
    """Verify source and target Blob clients before the long-running copy phase."""
    if not (migration_plan or {}).get("include_source_blobs"):
        return {"enabled": False, "container_count": 0, "containers": []}
    source_client = _get_source_blob_service_client()
    if not source_client:
        raise DataManagementSettingsValidationError(
            "Source Enhanced Citations storage is not configured for blob migration."
        )
    target_client = _get_target_enhanced_citations_blob_client(settings)
    container_names = []
    for target_type, selection in (migration_plan or {}).items():
        if target_type not in DATA_MANAGEMENT_MIGRATION_TARGET_TYPES:
            continue
        if not isinstance(selection, dict) or selection.get("mode") == "none" or not selection.get("include_documents"):
            continue
        if target_type == "users":
            container_names.append(app_config.storage_account_user_documents_container_name)
        elif target_type == "groups":
            container_names.append(app_config.storage_account_group_documents_container_name)
        elif target_type == "public_workspaces":
            container_names.append(app_config.storage_account_public_documents_container_name)
    results = []
    for container_name in sorted(set(container_names)):
        source_container = source_client.get_container_client(container_name)
        next(iter(source_container.list_blobs()), None)
        try:
            target_client.create_container(container_name)
        except ResourceExistsError:
            target_client.get_container_client(container_name).get_container_properties()
        probe_blob_name = f"simplechat-migration-preflight/{uuid.uuid4().hex}"
        target_blob = target_client.get_blob_client(
            container=container_name,
            blob=probe_blob_name,
        )
        probe_written = False
        probe_succeeded = False
        try:
            target_blob.upload_blob(
                data=b"",
                overwrite=False,
                metadata={"simplechatMigrationPreflight": "true"},
            )
            probe_written = True
            target_blob.get_blob_properties()
            probe_succeeded = True
        finally:
            if probe_written:
                try:
                    target_blob.delete_blob()
                except Exception:
                    if probe_succeeded:
                        raise
        results.append({
            "container_name": container_name,
            "source_read_verified": True,
            "destination_write_verified": True,
        })
    return {"enabled": True, "container_count": len(results), "containers": results}


def _run_data_management_migration_preflight(job, migration_state, settings, migration_plan):
    """Persist preflight evidence before any selected user data is written."""
    migration_state["preflight"] = {
        "status": "in_progress",
        "started_at": _now_iso(),
    }
    migration_state = _persist_migration_state(
        job,
        migration_state,
        settings,
        "Validating source and destination migration access",
    )
    _assert_migration_job_lease(job)
    cosmos_result = _preflight_target_cosmos_migration_access(settings, migration_plan)
    _assert_migration_job_lease(job)
    search_result = _preflight_target_ai_search_migration_access(settings, migration_plan)
    _assert_migration_job_lease(job)
    blob_result = _preflight_target_blob_migration_access(settings, migration_plan)
    capacity_result = None
    if _safe_bool((settings or {}).get("migration_temporary_destination_ru_enabled"), False):
        capacity_result = _inspect_target_cosmos_migration_capacity(settings, migration_plan)
    migration_state["preflight"] = {
        "status": "completed",
        "completed_at": _now_iso(),
        "cosmos": cosmos_result,
        "ai_search": search_result,
        "source_blobs": blob_result,
        "destination_capacity": capacity_result,
    }
    return _persist_migration_state(
        job,
        migration_state,
        settings,
        "Migration source and destination preflight completed",
    )


def _get_destination_capacity_current(management_settings, capacity_target):
    if capacity_target.get("scope") == "container":
        return get_container_throughput(
            management_settings,
            capacity_target.get("container_name"),
        )
    return get_database_throughput(management_settings)


def _get_backup_source_capacity_current(management_settings, capacity_target):
    if capacity_target.get("scope") == "container":
        return get_container_throughput(
            management_settings,
            capacity_target.get("container_name"),
        )
    return get_database_throughput(management_settings)


def _inspect_backup_source_capacity(backup_plan):
    """Discover whether source throughput is database-shared or container-dedicated."""
    management_settings = _get_source_cosmos_management_settings()
    database_throughput = get_database_throughput(management_settings)
    targets = []
    if database_throughput.get("is_scalable"):
        targets.append({
            "scope": "database",
            "container_name": "",
            "mode": database_throughput.get("mode"),
            "current_ru": database_throughput.get("current_ru"),
        })
    else:
        seen_container_names = set()
        for artifact in DATA_MANAGEMENT_COSMOS_ARTIFACTS:
            container_name = _safe_text(
                getattr(app_config, artifact["container_name_attr"], artifact["name"])
            )
            if not container_name or container_name in seen_container_names:
                continue
            seen_container_names.add(container_name)
            container_throughput = get_container_throughput(
                management_settings,
                container_name,
            )
            if container_throughput.get("is_scalable"):
                targets.append({
                    "scope": "container",
                    "container_name": container_name,
                    "mode": container_throughput.get("mode"),
                    "current_ru": container_throughput.get("current_ru"),
                })
    if not targets:
        raise CosmosThroughputError(
            "Source Cosmos throughput is not scalable at the database or dedicated-container level."
        )
    return {
        "target_ru": _get_backup_temporary_source_ru({}, backup_plan),
        "management_settings": management_settings,
        "database_mode": database_throughput.get("mode"),
        "database_current_ru": database_throughput.get("current_ru"),
        "targets": targets,
    }


def _apply_temporary_backup_source_capacity(job, backup_state, settings, backup_plan):
    """Boost only local source capacity that this fenced backup can later restore."""
    _assert_backup_job_lease(job)
    execution = backup_plan.get("cosmos_execution") if isinstance(backup_plan, dict) else {}
    if not _safe_bool((execution or {}).get("temporary_source_ru_enabled"), False):
        backup_state["source_capacity"] = {
            "status": "not_requested",
            "restore_pending": False,
        }
        return _persist_backup_state(
            job,
            backup_state,
            settings,
            "Temporary source Cosmos capacity boost is disabled",
        )

    capacity = (
        backup_state.get("source_capacity")
        if isinstance(backup_state.get("source_capacity"), dict) else {}
    )
    if capacity.get("restore_pending") and capacity.get("targets"):
        return _recover_pending_temporary_backup_source_capacity(
            job,
            backup_state,
            settings,
        )

    policy = _get_backup_capacity_failure_policy(settings, backup_plan)
    try:
        inspection = _inspect_backup_source_capacity(backup_plan)
    except Exception as exc:
        log_event(
            "[DataManagement] Source Cosmos capacity inspection failed.",
            {"job_id": job.get("id"), "error": str(exc)},
            level=logging.WARNING,
        )
        if policy == DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE:
            backup_state["source_capacity"] = {
                "status": "unavailable_continued",
                "restore_pending": False,
                "failure_policy": policy,
                "warning": "Source Cosmos capacity inspection was unavailable.",
            }
            _append_backup_warning(
                backup_state,
                "Source Cosmos capacity boost was unavailable; continuing without a boost.",
            )
            return _persist_backup_state(
                job,
                backup_state,
                settings,
                "Source Cosmos capacity boost unavailable; continuing without boost",
            )
        raise

    target_ru = inspection["target_ru"]
    capacity = {
        "status": "applying",
        "restore_pending": True,
        "failure_policy": policy,
        "target_ru": target_ru,
        "management_settings": inspection["management_settings"],
        "topology": {
            "database_mode": inspection.get("database_mode"),
            "database_current_ru": inspection.get("database_current_ru"),
            "scope": "shared_database" if inspection["targets"][0].get("scope") == "database" else "dedicated_containers",
        },
        "attempt_id": _safe_text(job.get("backup_attempt_id")),
        "lease_generation": _safe_int(job.get("lease_generation"), default=0),
        "targets": [],
        "started_at": _now_iso(),
    }
    backup_state["source_capacity"] = capacity
    _persist_backup_state(
        job,
        backup_state,
        settings,
        f"Preparing temporary source Cosmos capacity up to {target_ru} RU/s",
    )
    capacity = backup_state.setdefault("source_capacity", capacity)

    for target in inspection["targets"]:
        _assert_backup_job_lease(job)
        original_ru = _safe_int(target.get("current_ru"), default=0, minimum=0)
        target_snapshot = {
            "scope": target.get("scope"),
            "container_name": target.get("container_name") or "",
            "mode": target.get("mode"),
            "original_ru": original_ru,
            "target_ru": target_ru,
            "changed": False,
            "boost_attempted": False,
            "restore_status": "not_required",
        }
        capacity["targets"].append(target_snapshot)
        if original_ru and original_ru < target_ru:
            target_snapshot["boost_attempted"] = True
            target_snapshot["restore_status"] = "pending"
            _persist_backup_state(
                job,
                backup_state,
                settings,
                f"Recorded source Cosmos capacity recovery snapshot for {target_snapshot['scope']}",
            )
            capacity = backup_state.setdefault("source_capacity", capacity)
            target_snapshot = capacity["targets"][-1]
            _assert_backup_job_lease(job)
            try:
                scale_result = set_database_throughput(
                    inspection["management_settings"],
                    target_ru,
                    initiated_by=f"data_management_backup:{job.get('id')}",
                    reason="temporary_backup_source_capacity_boost",
                    decision={
                        "scope": target_snapshot["scope"],
                        "container_name": target_snapshot["container_name"],
                        "target_mode": target_snapshot["mode"],
                    },
                )
            except Exception as exc:
                target_snapshot["boost_error"] = "Source Cosmos capacity boost operation failed."
                log_event(
                    "[DataManagement] Source Cosmos capacity boost failed.",
                    {"job_id": job.get("id"), "scope": target_snapshot["scope"], "error": str(exc)},
                    level=logging.WARNING,
                )
                if policy == DATA_MANAGEMENT_BACKUP_CAPACITY_FAILURE_POLICY_CONTINUE:
                    _persist_backup_state(
                        job,
                        backup_state,
                        settings,
                        f"Source Cosmos capacity boost failed for {target_snapshot['scope']}",
                    )
                    restore_warnings, _ = _restore_temporary_backup_source_capacity(
                        job,
                        backup_state,
                        settings,
                    )
                    capacity = backup_state.setdefault("source_capacity", capacity)
                    if capacity.get("restore_pending"):
                        raise DataManagementSettingsValidationError(
                            "Source Cosmos capacity boost could not be safely rolled back. Retry the backup to restore the recorded capacity snapshot."
                        ) from exc
                    capacity.update({
                        "status": "unavailable_continued",
                        "completed_at": _now_iso(),
                        "warning": "Source Cosmos capacity boost could not be applied.",
                    })
                    for restore_warning in restore_warnings:
                        _append_backup_warning(backup_state, restore_warning)
                    _append_backup_warning(
                        backup_state,
                        "Source Cosmos capacity boost failed; continuing without a boost.",
                    )
                    return _persist_backup_state(
                        job,
                        backup_state,
                        settings,
                        "Source Cosmos capacity boost unavailable; continuing without boost",
                    )
                _persist_backup_state(
                    job,
                    backup_state,
                    settings,
                    f"Source Cosmos capacity boost failed for {target_snapshot['scope']}",
                )
                raise DataManagementSettingsValidationError(
                    "Source Cosmos capacity boost could not be applied. Review source topology and managed identity ARM permissions."
                ) from exc
            target_snapshot["changed"] = True
            target_snapshot["boosted_to_ru"] = scale_result.get("to_ru", target_ru)
            target_snapshot["restore_status"] = "pending"
        _persist_backup_state(
            job,
            backup_state,
            settings,
            f"Updated temporary source Cosmos capacity for {target_snapshot['scope']}",
        )
        capacity = backup_state.setdefault("source_capacity", capacity)

    capacity["status"] = "boosted"
    capacity["completed_at"] = _now_iso()
    return _persist_backup_state(
        job,
        backup_state,
        settings,
        f"Temporary source Cosmos capacity is ready up to {target_ru} RU/s",
    )


def _recover_pending_temporary_backup_source_capacity(job, backup_state, settings):
    """Claim and restore a prior fenced attempt's source capacity before more work."""
    capacity = (
        backup_state.get("source_capacity")
        if isinstance(backup_state.get("source_capacity"), dict) else {}
    )
    if not (capacity.get("restore_pending") and capacity.get("targets")):
        return backup_state
    _assert_backup_job_lease(job)
    # The new job lease fences the prior worker before recovery transfers
    # restoration ownership, preventing a stale finally block from acting.
    capacity.update({
        "attempt_id": _safe_text(job.get("backup_attempt_id")),
        "lease_generation": _safe_int(job.get("lease_generation"), default=0),
        "recovery_attempt_id": _safe_text(job.get("backup_attempt_id")),
        "recovery_lease_generation": _safe_int(job.get("lease_generation"), default=0),
        "recovery_started_at": _now_iso(),
    })
    backup_state["source_capacity"] = capacity
    _persist_backup_state(
        job,
        backup_state,
        settings,
        "Claimed pending source Cosmos capacity restoration for recovery",
    )
    _restore_temporary_backup_source_capacity(job, backup_state, settings)
    capacity = backup_state.get("source_capacity") or {}
    if capacity.get("restore_pending"):
        raise DataManagementSettingsValidationError(
            "Source Cosmos capacity restoration is still pending. Retry the backup after the recorded restore state is resolved."
        )
    return _persist_backup_state(
        job,
        backup_state,
        settings,
        "Recovered pending source Cosmos capacity without reapplying a boost",
    )


def _restore_temporary_backup_source_capacity(
    job,
    backup_state,
    settings,
    allow_cancel_requested=False,
):
    """Restore only capacity still owned by this fenced backup attempt."""
    _assert_backup_job_lease(
        job,
        allow_cancel_requested=allow_cancel_requested,
    )
    capacity = (
        backup_state.get("source_capacity")
        if isinstance(backup_state.get("source_capacity"), dict) else {}
    )
    if not capacity.get("restore_pending"):
        return [], backup_state
    if (
        _safe_text(capacity.get("attempt_id")) != _safe_text(job.get("backup_attempt_id")) or
        _safe_int(capacity.get("lease_generation"), default=0) !=
        _safe_int(job.get("lease_generation"), default=0)
    ):
        raise DataManagementBackupLeaseLostError(
            "A stale backup attempt cannot restore source Cosmos capacity."
        )

    management_settings = capacity.get("management_settings") or {}
    restore_warnings = []
    for target in reversed(capacity.get("targets") or []):
        _assert_backup_job_lease(
            job,
            allow_cancel_requested=allow_cancel_requested,
        )
        if not (target.get("changed") or target.get("boost_attempted")):
            continue
        try:
            current = _get_backup_source_capacity_current(management_settings, target)
            current_ru = _safe_int(current.get("current_ru"), default=0, minimum=0)
            boosted_to_ru = _safe_int(
                target.get("boosted_to_ru"),
                default=target.get("target_ru"),
                minimum=0,
            )
            original_ru = _safe_int(target.get("original_ru"), default=0, minimum=0)
            if current_ru == original_ru:
                target["restore_status"] = "not_changed"
                continue
            if current_ru != boosted_to_ru:
                target["restore_status"] = "skipped_external_change"
                restore_warnings.append(
                    f"Did not restore source {target.get('scope')} capacity because it changed after this backup boost."
                )
                continue
            scale_result = set_database_throughput(
                management_settings,
                original_ru,
                initiated_by=f"data_management_backup:{job.get('id')}",
                reason="restore_temporary_backup_source_capacity",
                decision={
                    "scope": target.get("scope"),
                    "container_name": target.get("container_name") or "",
                    "target_mode": target.get("mode"),
                },
            )
            target["restore_status"] = "restored"
            target["restored_to_ru"] = scale_result.get("to_ru", original_ru)
        except Exception as exc:
            target["restore_status"] = "restore_failed"
            log_event(
                "[DataManagement] Source Cosmos capacity restoration failed.",
                {"job_id": job.get("id"), "scope": target.get("scope"), "error": str(exc)},
                level=logging.WARNING,
            )
            restore_warnings.append(
                f"Failed to restore source {target.get('scope')} capacity."
            )

    capacity["restore_pending"] = any(
        target.get("restore_status") in {"pending", "restore_failed"}
        for target in capacity.get("targets") or []
    )
    capacity["restored_at"] = _now_iso()
    capacity["status"] = (
        "restore_pending" if capacity["restore_pending"] else
        "restored_with_warnings" if restore_warnings else
        "restored"
    )
    capacity["restore_warnings"] = restore_warnings
    backup_state["source_capacity"] = capacity
    _persist_backup_state(
        job,
        backup_state,
        settings,
        "Restored temporary source Cosmos capacity",
        allow_cancel_requested=allow_cancel_requested,
    )
    return restore_warnings, backup_state


def _apply_temporary_destination_capacity(job, migration_state, settings, migration_plan):
    """Temporarily increase only migration-targeted destination throughput to <=10,000 RU/s."""
    _assert_migration_job_lease(job)
    if not _safe_bool((settings or {}).get("migration_temporary_destination_ru_enabled"), False):
        migration_state["capacity"] = {"status": "not_requested", "restore_pending": False}
        return _persist_migration_state(
            job,
            migration_state,
            settings,
            "Temporary destination Cosmos capacity boost is disabled",
        )

    capacity = migration_state.get("capacity") if isinstance(migration_state.get("capacity"), dict) else {}
    if capacity.get("restore_pending") and capacity.get("targets"):
        if capacity.get("status") in {"applying", "restore_pending"}:
            _restore_temporary_destination_capacity(job, migration_state, settings)
            capacity = migration_state.get("capacity") if isinstance(migration_state.get("capacity"), dict) else {}
            if capacity.get("restore_pending"):
                raise DataManagementSettingsValidationError(
                    "Destination Cosmos capacity restoration is still pending. Resolve the recorded restore error before retrying migration."
                )
            return _persist_migration_state(
                job,
                migration_state,
                settings,
                "Recovered pending destination Cosmos capacity without reapplying a boost",
            )
        else:
            return migration_state

    inspection = _inspect_target_cosmos_migration_capacity(settings, migration_plan)
    target_ru = inspection["target_ru"]
    capacity = {
        "status": "applying",
        "restore_pending": True,
        "target_ru": target_ru,
        "management_settings": inspection["management_settings"],
        "targets": [],
        "started_at": _now_iso(),
    }
    migration_state["capacity"] = capacity
    migration_state = _persist_migration_state(
        job,
        migration_state,
        settings,
        f"Preparing temporary destination Cosmos capacity up to {target_ru} RU/s",
    )
    capacity = migration_state.setdefault("capacity", capacity)

    for target in inspection["targets"]:
        _assert_migration_job_lease(job)
        original_ru = _safe_int(target.get("current_ru"), default=0, minimum=0)
        target_snapshot = {
            "scope": target.get("scope"),
            "container_name": target.get("container_name") or "",
            "mode": target.get("mode"),
            "original_ru": original_ru,
            "target_ru": target_ru,
            "changed": False,
            "boost_attempted": False,
            "restore_status": "not_required",
        }
        capacity["targets"].append(target_snapshot)
        if original_ru and original_ru < target_ru:
            target_snapshot["boost_attempted"] = True
            target_snapshot["restore_status"] = "pending"
            migration_state = _persist_migration_state(
                job,
                migration_state,
                settings,
                f"Recorded destination Cosmos capacity recovery snapshot for {target_snapshot['scope']}",
            )
            capacity = migration_state.setdefault("capacity", capacity)
            target_snapshot = capacity["targets"][-1]
            _assert_migration_job_lease(job)
            try:
                scale_result = set_database_throughput(
                    inspection["management_settings"],
                    target_ru,
                    initiated_by=f"data_management_migration:{job.get('id')}",
                    reason="temporary_migration_capacity_boost",
                    decision={
                        "scope": target_snapshot["scope"],
                        "container_name": target_snapshot["container_name"],
                        "target_mode": target_snapshot["mode"],
                    },
                )
            except Exception as exc:
                target_snapshot["boost_error"] = str(exc)[:300]
                migration_state["capacity"] = capacity
                _persist_migration_state(
                    job,
                    migration_state,
                    settings,
                    f"Destination Cosmos capacity boost failed for {target_snapshot['scope']}",
                )
                raise
            target_snapshot["changed"] = True
            target_snapshot["boosted_to_ru"] = scale_result.get("to_ru", target_ru)
            target_snapshot["restore_status"] = "pending"
        else:
            target_snapshot["restore_status"] = "not_required"
        migration_state = _persist_migration_state(
            job,
            migration_state,
            settings,
            f"Updated temporary destination Cosmos capacity for {target_snapshot['scope']}",
        )
        capacity = migration_state.setdefault("capacity", capacity)

    capacity["status"] = "boosted"
    capacity["completed_at"] = _now_iso()
    return _persist_migration_state(
        job,
        migration_state,
        settings,
        f"Temporary destination Cosmos capacity is ready up to {target_ru} RU/s",
    )


def _restore_temporary_destination_capacity(
    job,
    migration_state,
    settings,
    allow_cancel_requested=False,
):
    """Restore only the capacity values this migration changed, without clobbering outside updates."""
    _assert_migration_job_lease(
        job,
        allow_cancel_requested=allow_cancel_requested,
    )
    capacity = migration_state.get("capacity") if isinstance(migration_state.get("capacity"), dict) else {}
    if not capacity.get("restore_pending"):
        return [], migration_state
    management_settings = capacity.get("management_settings") or {}
    restore_warnings = []
    for target in reversed(capacity.get("targets") or []):
        _assert_migration_job_lease(
            job,
            allow_cancel_requested=allow_cancel_requested,
        )
        if not (target.get("changed") or target.get("boost_attempted")):
            continue
        try:
            current = _get_destination_capacity_current(management_settings, target)
            current_ru = _safe_int(current.get("current_ru"), default=0, minimum=0)
            boosted_to_ru = _safe_int(target.get("boosted_to_ru"), default=target.get("target_ru"), minimum=0)
            original_ru = _safe_int(target.get("original_ru"), default=0, minimum=0)
            if current_ru == original_ru:
                target["restore_status"] = "not_changed"
                continue
            if current_ru != boosted_to_ru:
                target["restore_status"] = "skipped_external_change"
                restore_warnings.append(
                    f"Did not restore destination {target.get('scope')} capacity because it changed after the migration boost."
                )
                continue
            scale_result = set_database_throughput(
                management_settings,
                original_ru,
                initiated_by=f"data_management_migration:{job.get('id')}",
                reason="restore_temporary_migration_capacity",
                decision={
                    "scope": target.get("scope"),
                    "container_name": target.get("container_name") or "",
                    "target_mode": target.get("mode"),
                },
            )
            target["restore_status"] = "restored"
            target["restored_to_ru"] = scale_result.get("to_ru", original_ru)
        except Exception as exc:
            target["restore_status"] = "restore_failed"
            restore_warnings.append(
                f"Failed to restore destination {target.get('scope')} capacity: {str(exc)[:300]}"
            )

    unresolved_restore_statuses = {"pending", "restore_failed"}
    capacity["restore_pending"] = any(
        target.get("restore_status") in unresolved_restore_statuses
        for target in capacity.get("targets") or []
    )
    capacity["restored_at"] = _now_iso()
    if capacity["restore_pending"]:
        capacity["status"] = "restore_pending"
    else:
        capacity["status"] = "restored_with_warnings" if restore_warnings else "restored"
    capacity["restore_warnings"] = restore_warnings
    migration_state["capacity"] = capacity
    migration_state = _persist_migration_state(
        job,
        migration_state,
        settings,
        "Restored temporary destination Cosmos capacity",
        allow_cancel_requested=allow_cancel_requested,
    )
    return restore_warnings, migration_state


def _get_selected_scope_filter_fields(container_definition):
    """Return the trusted ownership fields used for selected-scope Cosmos reads."""
    configured_fields = container_definition.get("filter_fields")
    if configured_fields is None:
        configured_fields = [container_definition.get("filter_field")]
    elif isinstance(configured_fields, str):
        configured_fields = [configured_fields]
    elif not isinstance(configured_fields, (list, tuple)):
        raise DataManagementSettingsValidationError(
            "Migration container filter fields must be a string, list, or tuple."
        )

    filter_fields = []
    for field_name in configured_fields:
        if not field_name:
            continue
        if not isinstance(field_name, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*",
            field_name,
        ):
            raise DataManagementSettingsValidationError(
                "Migration container filter fields must be valid Cosmos property names."
            )
        filter_fields.append(field_name)
    return filter_fields


def _build_selected_scope_filter_clause(filter_fields):
    """Build the static Cosmos ownership predicate for one selected scope ID."""
    filter_clauses = [
        f"c.{field_name} = @selected_id"
        for field_name in filter_fields
    ]
    if len(filter_clauses) == 1:
        return filter_clauses[0]
    return f"({' OR '.join(filter_clauses)})"


def _iter_selected_cosmos_records(
    container_definition,
    selection,
    source_cutoff_epoch=None,
    source_start_epoch=None,
    include_source_version=False,
):
    source_container = getattr(app_config, container_definition["container_attr"], None)
    if not source_container:
        return
    if container_definition.get("documents") and not selection.get("include_documents"):
        return
    mode = selection.get("mode")

    def prepare_item(item):
        cleaned_item = _strip_cosmos_system_fields(item)
        if include_source_version:
            return cleaned_item, _safe_text(item.get("_ts"))
        return cleaned_item

    if mode == "all":
        query = "SELECT * FROM c"
        parameters = []
        conditions = []
        if source_start_epoch is not None:
            conditions.append("c._ts >= @source_start_epoch")
            parameters.append({"name": "@source_start_epoch", "value": source_start_epoch})
        if source_cutoff_epoch is not None:
            conditions.append("c._ts <= @source_cutoff_epoch")
            parameters = [{"name": "@source_cutoff_epoch", "value": source_cutoff_epoch}]
            if source_start_epoch is not None:
                parameters.insert(0, {"name": "@source_start_epoch", "value": source_start_epoch})
        if conditions:
            query = f"SELECT * FROM c WHERE {' AND '.join(conditions)}"
        for item in source_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        ):
            yield prepare_item(item)
        return
    if mode != "selected":
        return

    ids = selection.get("ids") or []
    if container_definition.get("id_field") == "id":
        for item_id in ids:
            try:
                item = source_container.read_item(item=item_id, partition_key=item_id)
            except CosmosResourceNotFoundError:
                continue
            if (
                source_cutoff_epoch is not None and
                item.get("_ts") is not None and
                _safe_int(item.get("_ts"), default=0, minimum=0) > source_cutoff_epoch
            ):
                continue
            if (
                source_start_epoch is not None and
                item.get("_ts") is not None and
                _safe_int(item.get("_ts"), default=0, minimum=0) < source_start_epoch
            ):
                continue
            yield prepare_item(item)
        return

    filter_fields = _get_selected_scope_filter_fields(container_definition)
    if not filter_fields:
        return
    filter_clause = _build_selected_scope_filter_clause(filter_fields)
    seen_identities = set() if len(filter_fields) > 1 else None
    for selected_id in ids:
        query = f"SELECT * FROM c WHERE {filter_clause}"
        parameters = [{"name": "@selected_id", "value": selected_id}]
        if source_start_epoch is not None:
            query += " AND c._ts >= @source_start_epoch"
            parameters.append({"name": "@source_start_epoch", "value": source_start_epoch})
        if source_cutoff_epoch is not None:
            query += " AND c._ts <= @source_cutoff_epoch"
            parameters.append({"name": "@source_cutoff_epoch", "value": source_cutoff_epoch})
        for item in source_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        ):
            if seen_identities is not None:
                item_identity = _get_cosmos_document_identity(
                    item,
                    container_definition["partition_key_path"],
                )
                if item_identity and item_identity in seen_identities:
                    continue
                if item_identity:
                    seen_identities.add(item_identity)
            yield prepare_item(item)


def _build_cosmos_document_identity(document_id, partition_key_value):
    if document_id is None or partition_key_value is None:
        return ""
    return json.dumps(
        {"id": str(document_id), "partition_key": partition_key_value},
        ensure_ascii=True,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


def _get_cosmos_document_identity(document, partition_key_path):
    if not isinstance(document, dict):
        return ""
    return _build_cosmos_document_identity(
        document.get("id"),
        _get_document_path_value(document, partition_key_path),
    )


def _build_cosmos_source_hash(document):
    """Hash source content without service fields or migration provenance."""
    canonical_document = {
        key: value
        for key, value in (document or {}).items()
        if key not in {
            COSMOS_MIGRATION_PROVENANCE_FIELD,
            "_etag",
            "_rid",
            "_self",
            "_attachments",
            "_ts",
        }
    }
    encoded = json.dumps(
        canonical_document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _get_cosmos_partition_key_select_expression(partition_key_path):
    path_parts = [part for part in _safe_text(partition_key_path).strip("/").split("/") if part]
    if not path_parts or any(not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", part) for part in path_parts):
        raise DataManagementSettingsValidationError("Destination Cosmos container has an unsupported partition key path.")
    return "c." + ".".join(path_parts)


def _get_target_cosmos_document(target_container, document, partition_key_path):
    """Read one exact destination item without allocating an account-wide key set."""
    document_id = _safe_text((document or {}).get("id"))
    partition_key_value = _get_document_path_value(document, partition_key_path)
    if not document_id or partition_key_value is None:
        raise DataManagementSettingsValidationError(
            "Migration source record is missing a required ID or partition key value."
        )
    try:
        return target_container.read_item(
            item=document_id,
            partition_key=partition_key_value,
        )
    except (CosmosResourceNotFoundError, ResourceNotFoundError):
        return None


def _classify_target_cosmos_document(
    target_document,
    provenance_context,
    container_name,
    migration_mode=DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
    source_hash="",
    source_version="",
):
    """Allow only empty or migration-owned target identities to be written."""
    if target_document is None:
        return "create"
    target_provenance = get_cosmos_migration_provenance(target_document)
    if is_successful_migration_record(target_provenance):
        if (
            _safe_text(target_provenance.get("migrationId")) ==
            _safe_text((provenance_context or {}).get("migration_id"))
        ):
            if migration_record_matches_source(
                target_provenance,
                source_hash=source_hash,
                source_version=source_version,
            ):
                return "resume_verified"
            return "update"
        if migration_mode == DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY:
            return "unchanged"
        if migration_record_matches_source(
            target_provenance,
            source_hash=source_hash,
            source_version=source_version,
        ):
            return "unchanged"
        return "update"
    raise DataManagementSettingsValidationError(
        f"Destination Cosmos container '{container_name}' contains an unowned record that conflicts with this migration."
    )


def _get_cosmos_response_request_units(headers):
    for header_name, header_value in (headers or {}).items():
        if str(header_name).lower() != "x-ms-request-charge":
            continue
        try:
            return max(0.0, float(header_value))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _drain_migration_futures_with_heartbeat(
    pending_futures,
    consume_result,
    persist_heartbeat,
    cancel_event,
    persist_stopped_results=None,
):
    pending_by_future = (
        dict(pending_futures)
        if isinstance(pending_futures, (dict, list, tuple))
        else {future: None for future in pending_futures}
    )
    last_heartbeat = time.monotonic()
    stop_error = None
    while pending_by_future:
        completed_futures, _pending_futures = wait(
            set(pending_by_future),
            timeout=DATA_MANAGEMENT_MIGRATION_HEARTBEAT_POLL_SECONDS,
            return_when=FIRST_COMPLETED,
        )
        for future in completed_futures:
            context = pending_by_future.pop(future)
            if future.cancelled():
                continue
            try:
                consume_result(future.result(), context)
            except Exception as exc:
                if stop_error is None:
                    stop_error = exc
                    cancel_event.set()
                    for pending_future in pending_by_future:
                        pending_future.cancel()
        now = time.monotonic()
        if (
            pending_by_future and
            stop_error is None and
            now - last_heartbeat >= DATA_MANAGEMENT_MIGRATION_HEARTBEAT_INTERVAL_SECONDS
        ):
            try:
                persist_heartbeat()
            except Exception as exc:
                stop_error = exc
                cancel_event.set()
                for future in pending_by_future:
                    future.cancel()
            last_heartbeat = now
    if stop_error is not None:
        if callable(persist_stopped_results):
            try:
                persist_stopped_results()
            except Exception:
                pass
        raise stop_error


def _write_cosmos_migration_record(
    target_container,
    document,
    partition_key_path,
    provenance_context,
    retry_count,
    disposition="create",
    target_document=None,
    source_hash="",
    source_version="",
    cancel_event=None,
):
    """Write one provenance-tagged Cosmos record with bounded transient retries."""
    writable_document = copy.deepcopy(document)
    add_cosmos_migration_provenance(
        writable_document,
        provenance_context,
        source_hash=source_hash,
        source_version=source_version,
    )
    payload_bytes = len(json.dumps(writable_document, default=_json_default).encode("utf-8"))
    request_units = 0.0
    request_unit_lock = Lock()

    def response_hook(headers, _response):
        nonlocal request_units
        with request_unit_lock:
            request_units += _get_cosmos_response_request_units(headers)

    started_at = time.perf_counter()
    last_error = None
    for attempt in range(1, retry_count + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise DataManagementMigrationCanceledError(
                "Cosmos migration stopped after cancellation or lease loss."
            )
        try:
            if disposition == "update":
                target_container.replace_item(
                    item=target_document,
                    body=writable_document,
                    etag=(target_document or {}).get("_etag"),
                    match_condition=MatchConditions.IfNotModified,
                    response_hook=response_hook,
                    connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                    timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                )
            else:
                target_container.create_item(
                    writable_document,
                    response_hook=response_hook,
                    retry_write=1,
                    connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                    timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                )
            return {
                "copied": True,
                "created": disposition == "create",
                "updated": disposition == "update",
                "bytes": payload_bytes,
                "request_units": request_units,
                "attempt": attempt,
                "elapsed_seconds": time.perf_counter() - started_at,
            }
        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None)
            if status_code in {409, 412}:
                target_document = _get_target_cosmos_document(
                    target_container,
                    document,
                    partition_key_path,
                )
                try:
                    disposition = _classify_target_cosmos_document(
                        target_document,
                        provenance_context,
                        "migration target",
                        migration_mode=(provenance_context or {}).get(
                            "migration_mode",
                            DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
                        ),
                        source_hash=source_hash,
                        source_version=source_version,
                    )
                except DataManagementSettingsValidationError as collision_error:
                    return {
                        "copied": False,
                        "skipped": False,
                        "collision": True,
                        "bytes": 0,
                        "request_units": request_units,
                        "attempt": attempt,
                        "elapsed_seconds": time.perf_counter() - started_at,
                        "error": str(collision_error),
                    }
                if disposition in {"unchanged", "resume_verified"}:
                    return {
                        "copied": False,
                        "skipped": True,
                        "resume_verified": disposition == "resume_verified",
                        "bytes": 0,
                        "request_units": request_units,
                        "attempt": attempt,
                        "elapsed_seconds": time.perf_counter() - started_at,
                    }
                if disposition == "update":
                    continue
            retryable = status_code in {408, 429, 449, 500, 503} or status_code is None
            if not retryable or attempt >= retry_count:
                break
            retry_delay = min(30, 2 ** (attempt - 1))
            if cancel_event is not None:
                if cancel_event.wait(retry_delay):
                    raise DataManagementMigrationCanceledError(
                        "Cosmos migration stopped during retry backoff."
                    )
            else:
                time.sleep(retry_delay)

    return {
        "copied": False,
        "skipped": False,
        "collision": False,
        "bytes": 0,
        "request_units": request_units,
        "attempt": retry_count,
        "elapsed_seconds": time.perf_counter() - started_at,
        "error": str(last_error or "Cosmos document write failed.")[:500],
    }


def _copy_cosmos_records_to_target(
    target_database,
    target_type,
    selection,
    job,
    migration_state,
    provenance_context,
    settings,
):
    copied = []
    source_cutoff = _parse_iso_datetime(migration_state.get("source_cutoff_at"))
    source_cutoff_epoch = int(source_cutoff.timestamp()) if source_cutoff else None
    migration_mode = _safe_text(
        (provenance_context or {}).get("migration_mode"),
        DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
    )
    baseline_cutoff = _parse_iso_datetime(
        (provenance_context or {}).get("baseline_source_cutoff_at")
    )
    source_start_epoch = (
        int(baseline_cutoff.timestamp())
        if baseline_cutoff and migration_mode != DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY
        else None
    )
    parallel_operations = _get_migration_parallel_operations(settings)
    retry_count = _get_migration_retry_count(settings)
    for container_definition in DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS[target_type]:
        if container_definition.get("documents") and not selection.get("include_documents"):
            continue
        target_container_name = _target_cosmos_container_name(container_definition)
        resource_name = f"cosmos:{target_type}:{container_definition['name']}"
        completed_resource = migration_state.get("resources", {}).get(resource_name)
        if is_migration_resource_completed(migration_state, resource_name):
            previous_result = completed_resource.get("result") if isinstance(completed_resource, dict) else {}
            copied.append({
                "name": container_definition["name"],
                "type": "cosmos_container",
                "target_type": target_type,
                "container_name": target_container_name,
                "partition_key_path": container_definition["partition_key_path"],
                "status": "checkpoint_completed",
                **(previous_result if isinstance(previous_result, dict) else {}),
            })
            continue

        target_container = _get_target_cosmos_container(
            target_database,
            target_container_name,
            container_definition["partition_key_path"],
        )
        resource = start_migration_resource(migration_state, resource_name)
        resource_started_at = resource.get("attempt_started_at") or resource.get("started_at")
        previous_progress = resource.get("progress") if isinstance(resource.get("progress"), dict) else {}
        copied_count = _safe_int(previous_progress.get("copied_count"), default=0, minimum=0)
        skipped_count = _safe_int(previous_progress.get("skipped_count"), default=0, minimum=0)
        prior_failed_count = _safe_int(previous_progress.get("failed_count"), default=0, minimum=0)
        failed_count = 0
        collision_count = _safe_int(previous_progress.get("collision_count"), default=0, minimum=0)
        destination_provenance_skip_count = _safe_int(
            previous_progress.get("destination_provenance_skip_count"),
            default=0,
            minimum=0,
        )
        created_count = _safe_int(previous_progress.get("created_count"), default=0, minimum=0)
        updated_count = _safe_int(previous_progress.get("updated_count"), default=0, minimum=0)
        unchanged_count = _safe_int(previous_progress.get("unchanged_count"), default=0, minimum=0)
        source_read_count = _safe_int(previous_progress.get("source_read_count"), default=0, minimum=0)
        retry_attempt_count = _safe_int(previous_progress.get("retry_attempt_count"), default=0, minimum=0)
        byte_count = _safe_int(previous_progress.get("bytes"), default=0, minimum=0)
        request_units = float(previous_progress.get("request_units") or 0.0)
        errors = []
        append_manifest, flush_manifest = _create_migration_manifest_writer(
            job.get("id"),
            resource_name,
        )
        transfer_cancel_event = Event()

        def persist_progress(allow_cancel_requested=False):
            flush_manifest()
            progress = build_transfer_metrics(
                resource_started_at,
                copied_count=copied_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
                byte_count=byte_count,
                request_units=request_units,
            )
            progress.update({
                "parallel_operations": parallel_operations,
                "retry_count": retry_count,
                "destination_provenance_skip_count": destination_provenance_skip_count,
                "collision_count": collision_count,
                "migration_mode": migration_mode,
                "baseline_source_cutoff_at": _safe_text(
                    (provenance_context or {}).get("baseline_source_cutoff_at")
                ),
                "source_read_count": source_read_count,
                "created_count": created_count,
                "updated_count": updated_count,
                "unchanged_count": unchanged_count,
                "retry_attempt_count": retry_attempt_count,
                "prior_failed_count": prior_failed_count,
            })
            return _persist_migration_checkpoint(
                job,
                migration_state,
                settings,
                resource_name,
                progress,
                f"Migrating Cosmos container {target_container_name}",
                allow_cancel_requested=allow_cancel_requested,
            )

        def persist_heartbeat():
            return _persist_migration_heartbeat(
                job,
                settings,
                f"Waiting for Cosmos writes to {target_container_name}",
            )

        def persist_stopped_results():
            return persist_progress(allow_cancel_requested=True)

        def consume_write_result(write_result, manifest_context):
            nonlocal copied_count, skipped_count, failed_count
            nonlocal collision_count, destination_provenance_skip_count
            nonlocal created_count, updated_count, unchanged_count
            nonlocal byte_count, request_units, retry_attempt_count
            request_units += write_result.get("request_units", 0.0)
            retry_attempt_count += max(0, _safe_int(write_result.get("attempt"), default=1) - 1)
            if write_result.get("copied"):
                copied_count += 1
                if write_result.get("updated"):
                    updated_count += 1
                else:
                    created_count += 1
                byte_count += write_result.get("bytes", 0)
            elif write_result.get("skipped"):
                if not write_result.get("resume_verified"):
                    skipped_count += 1
                    unchanged_count += 1
                destination_provenance_skip_count += 1
            else:
                failed_count += 1
                if write_result.get("collision"):
                    collision_count += 1
                errors.append(write_result.get("error", "Cosmos write failed."))
            status = (
                "updated"
                if write_result.get("updated") else
                "created"
                if write_result.get("copied") else
                "resume_verified"
                if write_result.get("resume_verified") else
                "unchanged"
                if write_result.get("skipped") else
                "collision"
                if write_result.get("collision") else
                "failed"
            )
            append_manifest({
                **manifest_context,
                "status": status,
                "attempt": write_result.get("attempt"),
                "bytes": write_result.get("bytes", 0),
                "error": write_result.get("error"),
            })

        try:
            pending_writes = []
            with ThreadPoolExecutor(max_workers=parallel_operations) as executor:
                for item, source_version in _iter_selected_cosmos_records(
                    container_definition,
                    selection,
                    source_cutoff_epoch=source_cutoff_epoch,
                    source_start_epoch=source_start_epoch,
                    include_source_version=True,
                ) or []:
                    source_read_count += 1
                    source_hash = _build_cosmos_source_hash(item)
                    manifest_context = {
                        "service": "cosmos",
                        "resource_name": resource_name,
                        "target_type": target_type,
                        "source_identity": _hash_migration_manifest_identity(
                            target_type,
                            container_definition["name"],
                            item.get("id"),
                            _get_document_path_value(
                                item,
                                container_definition["partition_key_path"],
                            ),
                        ),
                        "destination_identity": _hash_migration_manifest_identity(
                            target_container_name,
                            item.get("id"),
                            _get_document_path_value(
                                item,
                                container_definition["partition_key_path"],
                            ),
                        ),
                        "source_version": source_version,
                        "source_hash": source_hash,
                        "_locator": {
                            "service": "cosmos",
                            "resource_name": resource_name,
                            "target_type": target_type,
                            "document_id": item.get("id"),
                            "partition_key": _get_document_path_value(
                                item,
                                container_definition["partition_key_path"],
                            ),
                            "container_name": target_container_name,
                        },
                    }
                    target_document = _get_target_cosmos_document(
                        target_container,
                        item,
                        container_definition["partition_key_path"],
                    )
                    disposition = _classify_target_cosmos_document(
                        target_document,
                        provenance_context,
                        target_container_name,
                        migration_mode=migration_mode,
                        source_hash=source_hash,
                        source_version=source_version,
                    )
                    if disposition in {"unchanged", "resume_verified"}:
                        if disposition == "unchanged":
                            skipped_count += 1
                            unchanged_count += 1
                        destination_provenance_skip_count += 1
                        append_manifest({**manifest_context, "status": disposition})
                        if (copied_count + skipped_count + failed_count) % max(100, parallel_operations * 4) == 0:
                            migration_state = persist_progress()
                        continue

                    if not pending_writes:
                        _assert_migration_job_lease(job)
                    pending_writes.append((
                        executor.submit(
                            _write_cosmos_migration_record,
                            target_container,
                            item,
                            container_definition["partition_key_path"],
                            provenance_context,
                            retry_count,
                            disposition=disposition,
                            target_document=target_document,
                            source_hash=source_hash,
                            source_version=source_version,
                            cancel_event=transfer_cancel_event,
                        ),
                        manifest_context,
                    ))
                    if len(pending_writes) < parallel_operations:
                        continue

                    _drain_migration_futures_with_heartbeat(
                        pending_writes,
                        consume_write_result,
                        persist_heartbeat,
                        transfer_cancel_event,
                        persist_stopped_results=persist_stopped_results,
                    )
                    pending_writes = []
                    migration_state = persist_progress()

                _drain_migration_futures_with_heartbeat(
                    pending_writes,
                    consume_write_result,
                    persist_heartbeat,
                    transfer_cancel_event,
                    persist_stopped_results=persist_stopped_results,
                )

            flush_manifest()

            result = build_transfer_metrics(
                resource_started_at,
                copied_count=copied_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
                byte_count=byte_count,
                request_units=request_units,
            )
            result.update({
                "name": container_definition["name"],
                "type": "cosmos_container",
                "target_type": target_type,
                "container_name": target_container_name,
                "partition_key_path": container_definition["partition_key_path"],
                "parallel_operations": parallel_operations,
                "retry_count": retry_count,
                "destination_provenance_skip_count": destination_provenance_skip_count,
                "collision_count": collision_count,
                "migration_mode": migration_mode,
                "baseline_source_cutoff_at": _safe_text(
                    (provenance_context or {}).get("baseline_source_cutoff_at")
                ),
                "source_read_count": source_read_count,
                "created_count": created_count,
                "updated_count": updated_count,
                "unchanged_count": unchanged_count,
                "retry_attempt_count": retry_attempt_count,
                "prior_failed_count": prior_failed_count,
            })
            if failed_count:
                error_summary = "; ".join(errors[:3])
                migration_state = _fail_migration_resource_checkpoint(
                    job,
                    migration_state,
                    settings,
                    resource_name,
                    error_summary,
                )
                raise RuntimeError(
                    f"Cosmos migration failed for container '{target_container_name}' after {failed_count} item write failure(s)."
                )
            migration_state = _complete_migration_resource_checkpoint(
                job,
                migration_state,
                settings,
                resource_name,
                result,
                f"Completed Cosmos container {target_container_name}",
            )
            copied.append(result)
        except (DataManagementMigrationCanceledError, DataManagementMigrationLeaseLostError):
            flush_manifest()
            raise
        except Exception as exc:
            flush_manifest()
            if not failed_count:
                migration_state = _fail_migration_resource_checkpoint(
                    job,
                    migration_state,
                    settings,
                    resource_name,
                    str(exc),
                )
            raise
    return copied


def _escape_search_filter_value(value):
    return _safe_text(value).replace("'", "''")


def _build_search_filter(field_name, selection):
    if selection.get("mode") == "all":
        return None
    if selection.get("mode") != "selected":
        return "id eq '__no_migration_selection__'"
    conditions = [f"{field_name} eq '{_escape_search_filter_value(item_id)}'" for item_id in selection.get("ids") or []]
    if not conditions:
        return "id eq '__no_migration_selection__'"
    return " or ".join(conditions)


def _combine_search_filters(*search_filters):
    normalized_filters = [
        _safe_text(search_filter)
        for search_filter in search_filters
        if _safe_text(search_filter)
    ]
    if not normalized_filters:
        return None
    return " and ".join(f"({search_filter})" for search_filter in normalized_filters)


def _build_search_scope_filter_batches(field_name, selection):
    """Bound selected-scope filters so large migrations stay within Search limits."""
    if selection.get("mode") == "all":
        return [None]
    selected_ids = sorted({
        _safe_text(item_id)
        for item_id in (selection.get("ids") or [])
        if _safe_text(item_id)
    })
    if selection.get("mode") != "selected" or not selected_ids:
        return ["id eq '__no_migration_selection__'"]
    return [
        _build_search_filter(field_name, {
            "mode": "selected",
            "ids": selected_ids[offset:offset + DATA_MANAGEMENT_SEARCH_SCOPE_FILTER_BATCH_SIZE],
        })
        for offset in range(0, len(selected_ids), DATA_MANAGEMENT_SEARCH_SCOPE_FILTER_BATCH_SIZE)
    ]


def _iter_search_document_pages(
    search_client,
    search_filter=None,
    page_size=None,
    last_id="",
    select=None,
):
    """Yield stable keyset pages without allowing the SDK to fall back to deep skip."""
    safe_page_size = _safe_int(
        page_size,
        default=DATA_MANAGEMENT_SEARCH_KEYSET_PAGE_SIZE,
        minimum=1,
        maximum=DATA_MANAGEMENT_SEARCH_KEYSET_PAGE_SIZE,
    )
    cursor_id = _safe_text(last_id)
    while True:
        cursor_filter = (
            f"id gt '{_escape_search_filter_value(cursor_id)}'"
            if cursor_id
            else None
        )
        search_kwargs = {
            "search_text": "*",
            "filter": _combine_search_filters(search_filter, cursor_filter),
            "order_by": ["id asc"],
            "top": safe_page_size,
            "include_total_count": False,
        }
        if select:
            search_kwargs["select"] = select
        results = search_client.search(
            connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
            read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
            retry_total=0,
            **search_kwargs,
        )
        page = []
        previous_id = cursor_id
        for result in results:
            document = {
                key: value
                for key, value in dict(result).items()
                if not key.startswith("@search.")
            }
            document_id = _safe_text(document.get("id"))
            if not document_id:
                raise DataManagementSettingsValidationError(
                    "Source AI Search returned a document without an ID during keyset pagination."
                )
            if previous_id and document_id <= previous_id:
                raise DataManagementSettingsValidationError(
                    "Source AI Search did not honor the required strictly increasing ID order."
                )
            previous_id = document_id
            page.append(document)
        if not page:
            break
        cursor_id = _safe_text(page[-1].get("id"))
        yield page, cursor_id
        if len(page) < safe_page_size:
            break


def _get_target_ai_search_credential(settings):
    if (settings or {}).get("target_ai_search_authentication_type") == "key":
        key = _safe_text((settings or {}).get("target_ai_search_key"))
        if not key:
            raise ValueError("Target AI Search key is required when key authentication is selected.")
        return AzureKeyCredential(key)
    return DefaultAzureCredential()


def _get_target_search_client(settings, index_name):
    endpoint = _safe_text((settings or {}).get("target_ai_search_endpoint"))
    if not endpoint:
        raise ValueError("Target AI Search endpoint is required before running AI Search migration.")
    return SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=_get_target_ai_search_credential(settings),
        connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        retry_total=0,
    )


def _normalize_search_service_endpoint(endpoint):
    """Compare Search service endpoints without credentials or request paths."""
    normalized_endpoint = _safe_text(endpoint).strip().rstrip("/").lower()
    parsed_endpoint = urlparse(
        normalized_endpoint if "://" in normalized_endpoint else f"https://{normalized_endpoint}"
    )
    return _safe_text(parsed_endpoint.netloc or normalized_endpoint).rstrip("/").lower()


def _get_search_client_service_endpoint(search_client):
    """Read the SDK endpoint when the source client exposes one."""
    return _normalize_search_service_endpoint(
        getattr(search_client, "_endpoint", None) or
        getattr(search_client, "endpoint", None)
    )


def _migration_plan_includes_ai_search_documents(migration_plan):
    """Return whether this plan will write selected document chunks to AI Search."""
    if not (migration_plan or {}).get("include_ai_search"):
        return False
    return any(
        (migration_plan.get(target_type) or {}).get("mode") != "none" and
        bool((migration_plan.get(target_type) or {}).get("include_documents"))
        for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPES
    )


def _validate_target_ai_search_migration_write_safety(settings, migration_plan):
    """Require a frozen, distinct target before non-conditional Search document writes."""
    if not _migration_plan_includes_ai_search_documents(migration_plan):
        return
    if not bool((migration_plan or {}).get("target_ai_search_writes_frozen")):
        raise DataManagementSettingsValidationError(
            DATA_MANAGEMENT_SEARCH_WRITE_FREEZE_CONFIRMATION_ERROR
        )
    target_endpoint = _normalize_search_service_endpoint(
        (settings or {}).get("target_ai_search_endpoint")
    )
    if not target_endpoint:
        return
    for artifact in DATA_MANAGEMENT_SEARCH_ARTIFACTS:
        source_client = CLIENTS.get(artifact["client_key"])
        source_endpoint = _get_search_client_service_endpoint(source_client)
        if source_endpoint and source_endpoint == target_endpoint:
            raise DataManagementSettingsValidationError(
                "Target AI Search endpoint must differ from the selected source Search service."
            )


def _get_migration_search_provenance_fields():
    return [
        SearchField(
            name=SEARCH_MIGRATION_ID_FIELD,
            type=SearchFieldDataType.String,
            searchable=False,
            filterable=True,
            sortable=True,
            facetable=False,
            retrievable=True,
        ),
        SearchField(
            name=SEARCH_MIGRATED_AT_FIELD,
            type=SearchFieldDataType.DateTimeOffset,
            filterable=True,
            sortable=True,
            facetable=False,
            retrievable=True,
        ),
        SearchField(
            name=SEARCH_MIGRATION_STATUS_FIELD,
            type=SearchFieldDataType.String,
            searchable=False,
            filterable=True,
            sortable=True,
            facetable=False,
            retrievable=True,
        ),
        SearchField(
            name=SEARCH_MIGRATION_SOURCE_HASH_FIELD,
            type=SearchFieldDataType.String,
            searchable=False,
            filterable=True,
            sortable=False,
            facetable=False,
            retrievable=True,
        ),
        SearchField(
            name=SEARCH_MIGRATION_SOURCE_VERSION_FIELD,
            type=SearchFieldDataType.String,
            searchable=False,
            filterable=True,
            sortable=False,
            facetable=False,
            retrievable=True,
        ),
    ]


def _ensure_target_search_migration_provenance_fields(index):
    """Add compatible queryable provenance fields without rebuilding an index."""
    existing_fields = {
        field.name: field
        for field in (getattr(index, "fields", None) or [])
        if getattr(field, "name", None)
    }
    fields = list(getattr(index, "fields", None) or [])
    added_fields = 0
    for required_field in _get_migration_search_provenance_fields():
        existing_field = existing_fields.get(required_field.name)
        if existing_field is None:
            fields.append(required_field)
            added_fields += 1
            continue
        if (
            str(getattr(existing_field, "type", "")) != str(required_field.type) or
            getattr(existing_field, "filterable", False) is not True or
            getattr(existing_field, "retrievable", False) is not True
        ):
            raise DataManagementSettingsValidationError(
                f"Target AI Search index '{getattr(index, 'name', '')}' has incompatible "
                f"migration provenance field '{required_field.name}'."
            )
    if added_fields:
        index.fields = fields
    return added_fields


def _ensure_target_search_index(settings, index_name, schema_file):
    endpoint = _safe_text((settings or {}).get("target_ai_search_endpoint"))
    if not endpoint:
        raise ValueError("Target AI Search endpoint is required before running AI Search migration.")
    index_client = SearchIndexClient(
        endpoint=endpoint,
        credential=_get_target_ai_search_credential(settings),
        connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        retry_total=0,
    )
    try:
        index = index_client.get_index(index_name)
        added_fields = _ensure_target_search_migration_provenance_fields(index)
        if added_fields:
            index_client.create_or_update_index(index)
            return "updated_with_migration_provenance"
        return "exists_with_migration_provenance"
    except ResourceNotFoundError:
        schema = _get_search_schema(schema_file)
        schema = {key: value for key, value in schema.items() if not key.startswith("@odata.")}
        try:
            index = SearchIndex.from_dict(schema)
            _ensure_target_search_migration_provenance_fields(index)
            index_client.create_or_update_index(index)
            return "created_with_migration_provenance"
        except Exception as exc:
            raise ValueError(f"Target AI Search index {index_name} is missing and could not be created: {exc}") from exc


def _get_target_search_documents_by_ids(search_client, document_ids):
    """Read only the current bounded upload batch from the target index."""
    normalized_ids = [
        _safe_text(document_id)
        for document_id in document_ids
        if _safe_text(document_id)
    ]
    if not normalized_ids:
        return {}
    conditions = [
        f"id eq '{_escape_search_filter_value(document_id)}'"
        for document_id in normalized_ids
    ]
    results = search_client.search(
        search_text="*",
        filter=" or ".join(conditions),
        select=[
            "id",
            SEARCH_MIGRATION_ID_FIELD,
            SEARCH_MIGRATED_AT_FIELD,
            SEARCH_MIGRATION_STATUS_FIELD,
            SEARCH_MIGRATION_SOURCE_HASH_FIELD,
            SEARCH_MIGRATION_SOURCE_VERSION_FIELD,
        ],
        connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        retry_total=0,
    )
    documents_by_id = {}
    for result in results:
        document = dict(result)
        document_id = _safe_text(document.get("id"))
        if document_id:
            documents_by_id[document_id] = document
    return documents_by_id


def _build_search_source_hash(document):
    """Hash canonical source fields while excluding destination migration metadata."""
    excluded_fields = {
        SEARCH_MIGRATION_ID_FIELD,
        SEARCH_MIGRATED_AT_FIELD,
        SEARCH_MIGRATION_STATUS_FIELD,
        SEARCH_MIGRATION_SOURCE_HASH_FIELD,
        SEARCH_MIGRATION_SOURCE_VERSION_FIELD,
    }
    canonical_document = {
        key: value
        for key, value in (document or {}).items()
        if key not in excluded_fields and not key.startswith("@search.")
    }
    encoded = json.dumps(
        canonical_document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _classify_target_search_document(
    target_document,
    provenance_context,
    index_name,
    migration_mode=DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
    source_hash="",
):
    """Allow only empty or migration-owned target keys to be uploaded."""
    if target_document is None:
        return "create"
    target_provenance = get_search_migration_provenance(target_document)
    if is_successful_migration_record(target_provenance):
        if (
            _safe_text(target_provenance.get("migrationId")) ==
            _safe_text((provenance_context or {}).get("migration_id"))
        ):
            if migration_record_matches_source(
                target_provenance,
                source_hash=source_hash,
            ):
                return "resume_verified"
            return "update"
        if migration_mode == DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY:
            return "unchanged"
        if migration_record_matches_source(target_provenance, source_hash=source_hash):
            return "unchanged"
        return "update"
    raise DataManagementSettingsValidationError(
        f"Destination AI Search index '{index_name}' contains an unowned document that conflicts with this migration."
    )


def _get_search_result_succeeded(result):
    if isinstance(result, dict):
        return bool(result.get("succeeded", result.get("status", False)))
    return bool(getattr(result, "succeeded", getattr(result, "status", False)))


def _reclassify_pending_search_migration_entries(
    search_client,
    pending_entries,
    provenance_context,
    index_name,
    migration_mode,
):
    """Allow only verified response-lost writes to leave an ambiguous Search retry."""
    document_ids = [
        _safe_text((entry.get("document") or {}).get("id"))
        for entry in pending_entries
    ]
    target_documents = _get_target_search_documents_by_ids(search_client, document_ids)
    verified_entries = []
    retry_entries = []
    for entry in pending_entries:
        document = entry.get("document") if isinstance(entry, dict) else {}
        document_id = _safe_text((document or {}).get("id"))
        target_document = target_documents.get(document_id)
        if target_document is None:
            retry_entries.append(entry)
            continue
        source_hash = _safe_text((document or {}).get(SEARCH_MIGRATION_SOURCE_HASH_FIELD))
        disposition = _classify_target_search_document(
            target_document,
            provenance_context,
            index_name,
            migration_mode=migration_mode,
            source_hash=source_hash,
        )
        if disposition != "resume_verified":
            raise DataManagementSettingsValidationError(
                f"Destination AI Search index '{index_name}' changed after an ambiguous "
                f"migration write for document '{document_id}'. The migration stopped before retrying it."
            )
        verified_entries.append(entry)
    return verified_entries, retry_entries


def _upload_search_migration_batch(
    search_client,
    documents,
    retry_count,
    dispositions=None,
    manifest_contexts=None,
    cancel_event=None,
    provenance_context=None,
    index_name="",
    migration_mode=DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
):
    """Upload one idempotent batch and surface partial indexing failures."""
    pending_entries = [
        {
            "document": document,
            "disposition": (
                dispositions[index]
                if isinstance(dispositions, list) and index < len(dispositions)
                else "create"
            ),
            "bytes": len(json.dumps(document, default=_json_default).encode("utf-8")),
            "manifest_context": (
                manifest_contexts[index]
                if isinstance(manifest_contexts, list) and index < len(manifest_contexts)
                else {}
            ),
        }
        for index, document in enumerate(documents)
    ]
    started_at = time.perf_counter()
    last_error = ""
    copied_count = 0
    created_count = 0
    updated_count = 0
    accepted_bytes = 0
    manifest_entries = []

    def record_accepted_entry(entry, attempt):
        nonlocal copied_count, created_count, updated_count, accepted_bytes
        copied_count += 1
        accepted_bytes += entry["bytes"]
        if entry["disposition"] == "update":
            updated_count += 1
        else:
            created_count += 1
        manifest_entries.append({
            **entry["manifest_context"],
            "status": entry["disposition"] + "d",
            "attempt": attempt,
            "bytes": entry["bytes"],
        })

    for attempt in range(1, retry_count + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise DataManagementMigrationCanceledError(
                "AI Search migration stopped after cancellation or lease loss."
            )
        try:
            results = list(search_client.upload_documents(
                documents=[entry["document"] for entry in pending_entries],
                connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
                retry_total=0,
            ))
            if len(results) != len(pending_entries):
                last_error = "AI Search returned an incomplete document result set."
            else:
                failed_entries = []
                for entry, result in zip(pending_entries, results):
                    if not _get_search_result_succeeded(result):
                        failed_entries.append(entry)
                        continue
                    record_accepted_entry(entry, attempt)
                pending_entries = failed_entries
            if not pending_entries:
                return {
                    "copied": copied_count,
                    "created": created_count,
                    "updated": updated_count,
                    "failed": 0,
                    "bytes": accepted_bytes,
                    "attempt": attempt,
                    "manifest_entries": manifest_entries,
                    "elapsed_seconds": time.perf_counter() - started_at,
                }
            if not last_error:
                last_error = f"AI Search returned {len(pending_entries)} failed document result(s)."
        except DataManagementSettingsValidationError:
            raise
        except Exception as exc:
            last_error = str(exc)[:500]

        if attempt < retry_count:
            if provenance_context and index_name:
                try:
                    verified_entries, pending_entries = _reclassify_pending_search_migration_entries(
                        search_client,
                        pending_entries,
                        provenance_context,
                        index_name,
                        migration_mode,
                    )
                except DataManagementSettingsValidationError:
                    raise
                except Exception as exc:
                    last_error = (
                        "AI Search migration could not verify unresolved documents after an "
                        f"ambiguous write: {str(exc)[:400]}"
                    )
                    break
                for entry in verified_entries:
                    record_accepted_entry(entry, attempt)
                if not pending_entries:
                    return {
                        "copied": copied_count,
                        "created": created_count,
                        "updated": updated_count,
                        "failed": 0,
                        "bytes": accepted_bytes,
                        "attempt": attempt,
                        "manifest_entries": manifest_entries,
                        "elapsed_seconds": time.perf_counter() - started_at,
                    }
            retry_delay = min(30, 2 ** (attempt - 1))
            if cancel_event is not None:
                if cancel_event.wait(retry_delay):
                    return {
                        "copied": copied_count,
                        "created": created_count,
                        "updated": updated_count,
                        "failed": 0,
                        "bytes": accepted_bytes,
                        "attempt": attempt,
                        "manifest_entries": manifest_entries,
                        "interrupted": True,
                        "elapsed_seconds": time.perf_counter() - started_at,
                    }
            else:
                time.sleep(retry_delay)

    manifest_entries.extend({
        **entry["manifest_context"],
        "status": "failed",
        "attempt": retry_count,
        "bytes": 0,
        "error": last_error or "AI Search document indexing failed.",
    } for entry in pending_entries)
    return {
        "copied": copied_count,
        "created": created_count,
        "updated": updated_count,
        "failed": len(pending_entries),
        "bytes": accepted_bytes,
        "attempt": retry_count,
        "manifest_entries": manifest_entries,
        "elapsed_seconds": time.perf_counter() - started_at,
        "error": last_error or "AI Search document indexing failed.",
    }


def _copy_ai_search_to_target(
    settings,
    migration_plan,
    job,
    migration_state,
    provenance_context,
    target_search_write_fence=None,
):
    copied = []
    if not migration_plan.get("include_ai_search"):
        return copied
    search_mappings = [
        ("users", "user_id", DATA_MANAGEMENT_SEARCH_ARTIFACTS[0]),
        ("groups", "group_id", DATA_MANAGEMENT_SEARCH_ARTIFACTS[1]),
        ("public_workspaces", "public_workspace_id", DATA_MANAGEMENT_SEARCH_ARTIFACTS[2]),
    ]
    parallel_operations = _get_migration_parallel_operations(settings)
    retry_count = _get_migration_retry_count(settings)
    migration_mode = _safe_text(
        (provenance_context or {}).get("migration_mode"),
        DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
    )
    batch_size = min(50, DATA_MANAGEMENT_MIGRATION_BATCH_SIZE)
    search_page_size = min(
        DATA_MANAGEMENT_SEARCH_KEYSET_PAGE_SIZE,
        max(batch_size, batch_size * parallel_operations),
    )
    gate_container = None
    gate_fence = None
    if isinstance(target_search_write_fence, tuple) and len(target_search_write_fence) == 2:
        gate_container, gate_fence = target_search_write_fence

    def renew_target_search_write_fence():
        if gate_container is None or gate_fence is None:
            return
        renew_data_management_search_write_fence(
            gate_container,
            gate_fence,
            _get_target_search_write_fence_lease_seconds(settings),
        )

    for target_type, field_name, artifact in search_mappings:
        selection = migration_plan.get(target_type) or {}
        if selection.get("mode") == "none" or not selection.get("include_documents"):
            continue
        source_client = CLIENTS.get(artifact["client_key"])
        if not source_client:
            copied.append({"name": artifact["name"], "type": "ai_search_documents", "status": "skipped", "warning": "Source AI Search client is not initialized."})
            continue
        resource_name = f"ai_search:{target_type}:{artifact['index_name']}"
        completed_resource = migration_state.get("resources", {}).get(resource_name)
        if is_migration_resource_completed(migration_state, resource_name):
            previous_result = completed_resource.get("result") if isinstance(completed_resource, dict) else {}
            copied.append({
                "name": artifact["name"],
                "type": "ai_search_documents",
                "target_type": target_type,
                "index_name": artifact["index_name"],
                "status": "checkpoint_completed",
                **(previous_result if isinstance(previous_result, dict) else {}),
            })
            continue

        index_status = _ensure_target_search_index(settings, artifact["index_name"], artifact["schema_file"])
        target_client = _get_target_search_client(settings, artifact["index_name"])
        search_filters = _build_search_scope_filter_batches(field_name, selection)
        resource = start_migration_resource(migration_state, resource_name)
        resource_started_at = resource.get("attempt_started_at") or resource.get("started_at")
        previous_progress = resource.get("progress") if isinstance(resource.get("progress"), dict) else {}
        previous_cursor = previous_progress.get("keyset_cursor")
        previous_cursor = previous_cursor if isinstance(previous_cursor, dict) else {}
        copied_count = _safe_int(previous_progress.get("copied_count"), default=0, minimum=0)
        skipped_count = _safe_int(previous_progress.get("skipped_count"), default=0, minimum=0)
        prior_failed_count = _safe_int(previous_progress.get("failed_count"), default=0, minimum=0)
        failed_count = 0
        collision_count = _safe_int(previous_progress.get("collision_count"), default=0, minimum=0)
        destination_provenance_skip_count = _safe_int(
            previous_progress.get("destination_provenance_skip_count"),
            default=0,
            minimum=0,
        )
        byte_count = _safe_int(previous_progress.get("bytes"), default=0, minimum=0)
        source_read_count = _safe_int(previous_progress.get("source_read_count"), default=0, minimum=0)
        created_count = _safe_int(previous_progress.get("created_count"), default=0, minimum=0)
        updated_count = _safe_int(previous_progress.get("updated_count"), default=0, minimum=0)
        unchanged_count = _safe_int(previous_progress.get("unchanged_count"), default=0, minimum=0)
        retry_attempt_count = _safe_int(previous_progress.get("retry_attempt_count"), default=0, minimum=0)
        checkpoint_count = _safe_int(previous_progress.get("checkpoint_count"), default=0, minimum=0)
        cursor_scope_batch_index = _safe_int(
            previous_cursor.get("scope_batch_index"),
            default=0,
            minimum=0,
            maximum=len(search_filters),
        )
        cursor_last_id = _safe_text(previous_cursor.get("last_id"))
        errors = []
        append_manifest, flush_manifest = _create_migration_manifest_writer(
            job.get("id"),
            resource_name,
        )
        transfer_cancel_event = Event()

        def persist_progress(allow_cancel_requested=False):
            renew_target_search_write_fence()
            flush_manifest()
            progress = build_transfer_metrics(
                resource_started_at,
                copied_count=copied_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
                byte_count=byte_count,
            )
            progress.update({
                "parallel_operations": parallel_operations,
                "batch_size": batch_size,
                "retry_count": retry_count,
                "destination_provenance_skip_count": destination_provenance_skip_count,
                "collision_count": collision_count,
                "source_read_count": source_read_count,
                "destination_accepted_count": copied_count,
                "destination_failed_count": failed_count,
                "prior_failed_count": prior_failed_count,
                "retry_attempt_count": retry_attempt_count,
                "checkpoint_count": checkpoint_count,
                "migration_mode": migration_mode,
                "baseline_source_cutoff_at": _safe_text(
                    (provenance_context or {}).get("baseline_source_cutoff_at")
                ),
                "created_count": created_count,
                "updated_count": updated_count,
                "unchanged_count": unchanged_count,
                "keyset_cursor": {
                    "scope_batch_index": cursor_scope_batch_index,
                    "scope_batch_count": len(search_filters),
                    "last_id": cursor_last_id,
                },
            })
            return _persist_migration_checkpoint(
                job,
                migration_state,
                settings,
                resource_name,
                progress,
                f"Migrating AI Search index {artifact['index_name']}",
                allow_cancel_requested=allow_cancel_requested,
            )

        def persist_heartbeat():
            result = _persist_migration_heartbeat(
                job,
                settings,
                f"Waiting for AI Search uploads to {artifact['index_name']}",
            )
            renew_target_search_write_fence()
            return result

        def persist_stopped_results():
            return persist_progress(allow_cancel_requested=True)

        def prepare_upload_batch(source_batch):
            nonlocal collision_count
            source_ids = [_safe_text(document.get("id")) for document in source_batch]
            if any(not document_id for document_id in source_ids):
                raise DataManagementSettingsValidationError(
                    f"Source AI Search index '{artifact['index_name']}' contains a document without an ID."
                )
            _assert_migration_job_lease(job)
            renew_target_search_write_fence()
            target_documents = _get_target_search_documents_by_ids(
                target_client,
                source_ids,
            )
            upload_documents = []
            upload_dispositions = []
            upload_manifest_contexts = []
            deferred_outcomes = {
                "skipped_count": 0,
                "unchanged_count": 0,
                "destination_provenance_skip_count": 0,
                "manifest_entries": [],
            }
            for source_document, source_document_id in zip(source_batch, source_ids):
                source_hash = _build_search_source_hash(source_document)
                manifest_context = {
                    "service": "ai_search",
                    "resource_name": resource_name,
                    "target_type": target_type,
                    "source_identity": _hash_migration_manifest_identity(
                        artifact["index_name"],
                        source_document_id,
                    ),
                    "destination_identity": _hash_migration_manifest_identity(
                        "destination",
                        artifact["index_name"],
                        source_document_id,
                    ),
                    "source_hash": source_hash,
                    "_locator": {
                        "service": "ai_search",
                        "resource_name": resource_name,
                        "target_type": target_type,
                        "document_id": source_document_id,
                        "index_name": artifact["index_name"],
                    },
                }
                try:
                    disposition = _classify_target_search_document(
                        target_documents.get(source_document_id),
                        provenance_context,
                        artifact["index_name"],
                        migration_mode=migration_mode,
                        source_hash=source_hash,
                    )
                except DataManagementSettingsValidationError:
                    collision_count += 1
                    raise
                if disposition in {"unchanged", "resume_verified"}:
                    if disposition == "unchanged":
                        deferred_outcomes["skipped_count"] += 1
                        deferred_outcomes["unchanged_count"] += 1
                    deferred_outcomes["destination_provenance_skip_count"] += 1
                    deferred_outcomes["manifest_entries"].append({
                        **manifest_context,
                        "status": disposition,
                    })
                    continue
                upload_documents.append(add_search_migration_provenance(
                    copy.deepcopy(source_document),
                    provenance_context,
                    source_hash=source_hash,
                ))
                upload_dispositions.append(disposition)
                upload_manifest_contexts.append(manifest_context)
            return (
                upload_documents,
                upload_dispositions,
                upload_manifest_contexts,
                deferred_outcomes,
            )

        def consume_batch_result(batch_result):
            nonlocal copied_count, failed_count, byte_count, retry_attempt_count
            nonlocal created_count, updated_count
            copied_count += batch_result.get("copied", 0)
            created_count += batch_result.get("created", 0)
            updated_count += batch_result.get("updated", 0)
            failed_count += batch_result.get("failed", 0)
            byte_count += batch_result.get("bytes", 0)
            retry_attempt_count += max(0, _safe_int(batch_result.get("attempt"), default=1) - 1)
            if batch_result.get("error"):
                errors.append(batch_result["error"])
            for manifest_entry in batch_result.get("manifest_entries") or []:
                append_manifest(manifest_entry)

        def consume_batch_future(batch_result, _context):
            consume_batch_result(batch_result)

        try:
            with ThreadPoolExecutor(max_workers=parallel_operations) as executor:
                for scope_batch_index, search_filter in enumerate(search_filters):
                    if scope_batch_index < cursor_scope_batch_index:
                        continue
                    last_id = cursor_last_id if scope_batch_index == cursor_scope_batch_index else ""
                    for source_page, page_last_id in _iter_search_document_pages(
                        source_client,
                        search_filter=search_filter,
                        page_size=search_page_size,
                        last_id=last_id,
                    ):
                        page_failed_count = failed_count
                        pending_batches = []
                        page_outcomes = {
                            "skipped_count": 0,
                            "unchanged_count": 0,
                            "destination_provenance_skip_count": 0,
                            "manifest_entries": [],
                        }
                        for offset in range(0, len(source_page), batch_size):
                            source_batch = []
                            source_batch.extend(source_page[offset:offset + batch_size])
                            if not source_batch:
                                continue
                            (
                                upload_documents,
                                upload_dispositions,
                                upload_manifest_contexts,
                                deferred_outcomes,
                            ) = prepare_upload_batch(source_batch)
                            for field_name in (
                                "skipped_count",
                                "unchanged_count",
                                "destination_provenance_skip_count",
                            ):
                                page_outcomes[field_name] += deferred_outcomes[field_name]
                            page_outcomes["manifest_entries"].extend(
                                deferred_outcomes["manifest_entries"]
                            )
                            if upload_documents:
                                pending_batches.append(executor.submit(
                                    _upload_search_migration_batch,
                                    target_client,
                                    upload_documents,
                                    retry_count,
                                    upload_dispositions,
                                    upload_manifest_contexts,
                                    transfer_cancel_event,
                                    provenance_context=provenance_context,
                                    index_name=artifact["index_name"],
                                    migration_mode=migration_mode,
                                ))
                            if len(pending_batches) < parallel_operations:
                                continue
                            _drain_migration_futures_with_heartbeat(
                                {future: None for future in pending_batches},
                                consume_batch_future,
                                persist_heartbeat,
                                transfer_cancel_event,
                                persist_stopped_results=persist_stopped_results,
                            )
                            pending_batches = []
                        _drain_migration_futures_with_heartbeat(
                            {future: None for future in pending_batches},
                            consume_batch_future,
                            persist_heartbeat,
                            transfer_cancel_event,
                            persist_stopped_results=persist_stopped_results,
                        )

                        if failed_count > page_failed_count:
                            migration_state = persist_progress()
                            migration_state = _fail_migration_resource_checkpoint(
                                job,
                                migration_state,
                                settings,
                                resource_name,
                                "; ".join(errors[:3]) or "AI Search document indexing failed.",
                            )
                            raise RuntimeError(
                                f"AI Search migration failed for index '{artifact['index_name']}' "
                                "before its keyset cursor could advance."
                            )

                        source_read_count += len(source_page)
                        skipped_count += page_outcomes["skipped_count"]
                        unchanged_count += page_outcomes["unchanged_count"]
                        destination_provenance_skip_count += page_outcomes[
                            "destination_provenance_skip_count"
                        ]
                        for manifest_entry in page_outcomes["manifest_entries"]:
                            append_manifest(manifest_entry)
                        cursor_scope_batch_index = scope_batch_index
                        cursor_last_id = page_last_id
                        checkpoint_count += 1
                        migration_state = persist_progress()

                    cursor_scope_batch_index = scope_batch_index + 1
                    cursor_last_id = ""
                    checkpoint_count += 1
                    migration_state = persist_progress()

            result = build_transfer_metrics(
                resource_started_at,
                copied_count=copied_count,
                skipped_count=skipped_count,
                failed_count=failed_count,
                byte_count=byte_count,
            )
            flush_manifest()
            result.update({
                "name": artifact["name"],
                "type": "ai_search_documents",
                "target_type": target_type,
                "index_name": artifact["index_name"],
                "scope_filter_batch_count": len(search_filters),
                "index_status": index_status,
                "parallel_operations": parallel_operations,
                "batch_size": batch_size,
                "search_page_size": search_page_size,
                "retry_count": retry_count,
                "destination_provenance_skip_count": destination_provenance_skip_count,
                "collision_count": collision_count,
                "source_read_count": source_read_count,
                "destination_accepted_count": copied_count,
                "destination_failed_count": failed_count,
                "prior_failed_count": prior_failed_count,
                "retry_attempt_count": retry_attempt_count,
                "checkpoint_count": checkpoint_count,
                "migration_mode": migration_mode,
                "baseline_source_cutoff_at": _safe_text(
                    (provenance_context or {}).get("baseline_source_cutoff_at")
                ),
                "created_count": created_count,
                "updated_count": updated_count,
                "unchanged_count": unchanged_count,
                "keyset_cursor": {
                    "scope_batch_index": len(search_filters),
                    "scope_batch_count": len(search_filters),
                    "last_id": "",
                    "completed": True,
                },
            })
            if failed_count:
                migration_state = _fail_migration_resource_checkpoint(
                    job,
                    migration_state,
                    settings,
                    resource_name,
                    "; ".join(errors[:3]) or "AI Search document indexing failed.",
                )
                raise RuntimeError(
                    f"AI Search migration failed for index '{artifact['index_name']}' after {failed_count} document failure(s)."
                )
            migration_state = _complete_migration_resource_checkpoint(
                job,
                migration_state,
                settings,
                resource_name,
                result,
                f"Completed AI Search index {artifact['index_name']}",
            )
            copied.append(result)
        except (DataManagementMigrationCanceledError, DataManagementMigrationLeaseLostError):
            flush_manifest()
            raise
        except Exception as exc:
            flush_manifest()
            if not failed_count:
                migration_state = _fail_migration_resource_checkpoint(
                    job,
                    migration_state,
                    settings,
                    resource_name,
                    str(exc),
                )
            raise
    return copied


def _get_target_enhanced_citations_blob_client(settings):
    auth_type = _safe_text((settings or {}).get("target_enhanced_citations_storage_authentication_type"), "managed_identity")
    if auth_type == "connection_string":
        connection_string = _safe_text((settings or {}).get("target_enhanced_citations_storage_connection_string"))
        if not connection_string:
            raise ValueError("Destination Enhanced Citations storage connection string is required when migrating source document blobs.")
        return BlobServiceClient.from_connection_string(connection_string)
    blob_endpoint = _safe_text((settings or {}).get("target_enhanced_citations_storage_blob_endpoint"))
    if not blob_endpoint:
        raise ValueError("Destination Enhanced Citations Blob endpoint is required when migrating source document blobs.")
    return BlobServiceClient(account_url=blob_endpoint, credential=DefaultAzureCredential())


def _document_blob_reference(document_item):
    if not isinstance(document_item, dict):
        return None
    container_name = document_item.get("blob_container") or _blob_container_for_document(document_item)
    blob_path = document_item.get("blob_path") or document_item.get("archived_blob_path")
    if not container_name or not blob_path:
        return None
    return container_name, blob_path


def _document_migration_scope_hash(document_item):
    if not isinstance(document_item, dict):
        return ""
    for scope_type, field_name in (
        ("public_workspaces", "public_workspace_id"),
        ("groups", "group_id"),
        ("users", "user_id"),
    ):
        scope_id = _safe_text(document_item.get(field_name))
        if scope_id:
            encoded = f"{scope_type}:{scope_id}".encode("utf-8")
            return hashlib.sha256(encoded).hexdigest()
    return ""


def _blob_container_for_document(document_item):
    if document_item.get("public_workspace_id"):
        return app_config.storage_account_public_documents_container_name
    if document_item.get("group_id"):
        return app_config.storage_account_group_documents_container_name
    return app_config.storage_account_user_documents_container_name


def _iter_selected_document_records_for_blob_migration(migration_plan, source_cutoff_epoch=None):
    for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPE_ORDER:
        selection = migration_plan.get(target_type) or {}
        if selection.get("mode") == "none" or not selection.get("include_documents"):
            continue
        container_definition = next(
            (
                definition
                for definition in DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS[target_type]
                if definition.get("documents")
            ),
            None,
        )
        if not container_definition:
            continue
        yield from _iter_selected_cosmos_records(
            container_definition,
            selection,
            source_cutoff_epoch=source_cutoff_epoch,
        ) or []


def _get_blob_properties_or_none(blob_client):
    try:
        return blob_client.get_blob_properties()
    except ResourceNotFoundError:
        return None


def _get_blob_content_md5(blob_properties):
    content_settings = getattr(blob_properties, "content_settings", None)
    content_md5 = getattr(content_settings, "content_md5", None)
    if isinstance(content_md5, (bytes, bytearray)):
        return base64.b64encode(bytes(content_md5)).decode("ascii")
    return _safe_text(content_md5)


def _build_blob_source_fingerprint(blob_properties):
    """Build stable source content and version markers from service properties."""
    content_md5 = _get_blob_content_md5(blob_properties)
    last_modified = getattr(blob_properties, "last_modified", None)
    if isinstance(last_modified, datetime):
        last_modified = last_modified.astimezone(timezone.utc).isoformat()
    version_payload = {
        "etag": _safe_text(getattr(blob_properties, "etag", None)),
        "last_modified": _safe_text(last_modified),
        "size": _safe_int(getattr(blob_properties, "size", 0), default=0, minimum=0),
        "blob_type": _safe_text(getattr(blob_properties, "blob_type", None)),
    }
    encoded = json.dumps(
        version_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    source_hash = f"md5:{content_md5}" if content_md5 else ""
    source_version = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    return source_hash, source_version


def _get_source_blob_tags(source_blob_client, source_properties):
    source_tags = getattr(source_properties, "tags", None)
    if isinstance(source_tags, dict):
        return source_tags
    if _safe_int(getattr(source_properties, "tag_count", 0), default=0, minimum=0) <= 0:
        return None
    get_blob_tags = getattr(source_blob_client, "get_blob_tags", None)
    if not callable(get_blob_tags):
        return None
    tags = get_blob_tags()
    return tags if isinstance(tags, dict) else None


def _classify_target_blob(
    target_properties,
    provenance_context,
    migration_mode,
    source_hash,
    source_version,
):
    if target_properties is None:
        return "create"
    target_provenance = get_blob_migration_provenance(
        getattr(target_properties, "metadata", None)
    )
    if (
        _safe_text(target_provenance.get("migrationId")) ==
        _safe_text((provenance_context or {}).get("migration_id")) and
        _safe_text(target_provenance.get("status")).lower() == "pending"
    ):
        return "update"
    if is_successful_migration_record(target_provenance):
        if (
            _safe_text(target_provenance.get("migrationId")) ==
            _safe_text((provenance_context or {}).get("migration_id"))
        ):
            if migration_record_matches_source(
                target_provenance,
                source_hash=source_hash,
                source_version=source_version,
            ):
                return "resume_verified"
            return "update"
        if migration_mode == DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY:
            return "unchanged"
        if migration_record_matches_source(
            target_provenance,
            source_hash=source_hash,
            source_version=source_version,
        ):
            return "unchanged"
        return "update"
    return "collision"


def _build_pending_blob_migration_metadata(
    source_metadata,
    provenance_context,
    source_hash,
    source_version,
    scope_hash,
):
    metadata = merge_blob_migration_metadata(
        source_metadata,
        provenance_context,
        source_hash=source_hash,
        source_version=source_version,
        scope_hash=scope_hash,
    )
    metadata[BLOB_MIGRATION_STATUS_METADATA_KEY] = "pending"
    return metadata


def _iter_migration_blob_chunks(
    source_download,
    progress_callback=None,
    cancel_event=None,
):
    for chunk in source_download.chunks():
        if cancel_event is not None and cancel_event.is_set():
            raise DataManagementMigrationCanceledError(
                "Blob transfer stopped after migration cancellation or lease loss."
            )
        if progress_callback:
            progress_callback(len(chunk))
        yield chunk
    if cancel_event is not None and cancel_event.is_set():
        raise DataManagementMigrationCanceledError(
            "Blob transfer stopped after migration cancellation or lease loss."
        )


def _copy_source_blob_migration_record(
    source_blob_client,
    target_blob_client,
    provenance_context,
    retry_count,
    scope_hash="",
    progress_callback=None,
    cancel_event=None,
):
    """Stream one blob to the target and stamp metadata only on success."""
    try:
        source_properties = source_blob_client.get_blob_properties()
    except ResourceNotFoundError:
        return {"status": "missing", "bytes": 0}

    migration_mode = _safe_text(
        (provenance_context or {}).get("migration_mode"),
        DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
    )
    source_hash, source_version = _build_blob_source_fingerprint(source_properties)
    existing_target_properties = _get_blob_properties_or_none(target_blob_client)
    disposition = _classify_target_blob(
        existing_target_properties,
        provenance_context,
        migration_mode,
        source_hash,
        source_version,
    )
    if disposition in {"unchanged", "resume_verified"}:
        return {
            "status": disposition,
            "bytes": 0,
            "source_hash": source_hash,
            "source_version": source_version,
        }
    if disposition == "collision":
        return {
            "status": "collision",
            "bytes": 0,
            "error": "Destination blob exists without successful migration provenance.",
        }

    source_metadata = getattr(source_properties, "metadata", None) or {}
    pending_metadata = _build_pending_blob_migration_metadata(
        source_metadata,
        provenance_context,
        source_hash,
        source_version,
        scope_hash,
    )
    destination_metadata = merge_blob_migration_metadata(
        source_metadata,
        provenance_context,
        source_hash=source_hash,
        source_version=source_version,
        scope_hash=scope_hash,
    )
    source_size = _safe_int(getattr(source_properties, "size", 0), default=0, minimum=0)
    content_settings = getattr(source_properties, "content_settings", None)
    source_tags = _get_source_blob_tags(source_blob_client, source_properties)
    source_blob_tier = getattr(source_properties, "blob_tier", None)
    source_blob_type = getattr(source_properties, "blob_type", None)
    source_etag = _safe_text(getattr(source_properties, "etag", None))
    started_at = time.perf_counter()
    last_error = ""

    for attempt in range(1, retry_count + 1):
        try:
            if progress_callback:
                progress_callback(0, reset=True)
            if cancel_event is not None and cancel_event.is_set():
                raise DataManagementMigrationCanceledError(
                    "Blob transfer stopped after migration cancellation or lease loss."
                )
            download_kwargs = {
                "max_concurrency": 1,
                "timeout": DATA_MANAGEMENT_BLOB_SERVICE_TIMEOUT_SECONDS,
            }
            if source_etag:
                download_kwargs.update({
                    "etag": source_etag,
                    "match_condition": MatchConditions.IfNotModified,
                })
            source_download = source_blob_client.download_blob(**download_kwargs)
            upload_kwargs = {
                "data": _iter_migration_blob_chunks(
                    source_download,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                ),
                "length": source_size,
                "overwrite": disposition == "update",
                "metadata": pending_metadata,
                "content_settings": content_settings,
                "max_concurrency": 1,
                "timeout": DATA_MANAGEMENT_BLOB_SERVICE_TIMEOUT_SECONDS,
            }
            if source_tags is not None:
                upload_kwargs["tags"] = source_tags
            if source_blob_tier is not None:
                upload_kwargs["standard_blob_tier"] = source_blob_tier
            if source_blob_type is not None:
                upload_kwargs["blob_type"] = source_blob_type
            if disposition == "update" and existing_target_properties is not None:
                target_etag = getattr(existing_target_properties, "etag", None)
                if target_etag:
                    upload_kwargs["etag"] = target_etag
                    upload_kwargs["match_condition"] = MatchConditions.IfNotModified
            target_blob_client.upload_blob(**upload_kwargs)
            destination_properties = _get_blob_properties_or_none(target_blob_client)
            destination_size = _safe_int(
                getattr(destination_properties, "size", source_size),
                default=source_size,
                minimum=0,
            )
            destination_md5 = _get_blob_content_md5(destination_properties)
            if destination_size != source_size or (
                source_hash and destination_md5 and source_hash != f"md5:{destination_md5}"
            ):
                raise RuntimeError(
                    "Destination blob verification did not match the source content properties."
                )
            current_source_properties = source_blob_client.get_blob_properties()
            current_source_etag = _safe_text(getattr(current_source_properties, "etag", None))
            if source_etag and current_source_etag != source_etag:
                raise RuntimeError("Source blob changed while it was being transferred.")
            destination_etag = _safe_text(getattr(destination_properties, "etag", None))
            set_metadata_kwargs = {"metadata": destination_metadata}
            if destination_etag:
                set_metadata_kwargs.update({
                    "etag": destination_etag,
                    "match_condition": MatchConditions.IfNotModified,
                })
            target_blob_client.set_blob_metadata(**set_metadata_kwargs)
            return {
                "status": "updated" if disposition == "update" else "copied",
                "bytes": source_size,
                "attempt": attempt,
                "source_size": source_size,
                "destination_size": destination_size,
                "source_hash": source_hash,
                "source_version": source_version,
                "elapsed_seconds": time.perf_counter() - started_at,
            }
        except Exception as exc:
            if isinstance(exc, (DataManagementMigrationCanceledError, DataManagementMigrationLeaseLostError)):
                raise
            last_error = str(exc)[:500]
            status_code = getattr(exc, "status_code", None)
            if isinstance(exc, ResourceExistsError) or status_code in {409, 412}:
                concurrent_target_properties = _get_blob_properties_or_none(target_blob_client)
                concurrent_disposition = _classify_target_blob(
                    concurrent_target_properties,
                    provenance_context,
                    migration_mode,
                    source_hash,
                    source_version,
                )
                if concurrent_disposition in {"unchanged", "resume_verified"}:
                    return {"status": concurrent_disposition, "bytes": 0}
                if concurrent_disposition == "update":
                    disposition = "update"
                    existing_target_properties = concurrent_target_properties
                    continue
                if concurrent_disposition == "collision":
                    return {
                        "status": "collision",
                        "bytes": 0,
                        "error": "Destination blob changed without migration ownership during this migration.",
                    }
            retryable = status_code in {408, 429, 500, 503} or status_code is None
            if not retryable or attempt >= retry_count:
                break
            time.sleep(min(30, 2 ** (attempt - 1)))

    if disposition == "create":
        failed_target_properties = _get_blob_properties_or_none(target_blob_client)
        failed_provenance = get_blob_migration_provenance(
            getattr(failed_target_properties, "metadata", None)
        ) if failed_target_properties else {}
        if (
            _safe_text(failed_provenance.get("migrationId")) ==
            _safe_text((provenance_context or {}).get("migration_id")) and
            _safe_text(failed_provenance.get("status")).lower() == "pending"
        ):
            delete_kwargs = {}
            failed_etag = _safe_text(getattr(failed_target_properties, "etag", None))
            if failed_etag:
                delete_kwargs.update({
                    "etag": failed_etag,
                    "match_condition": MatchConditions.IfNotModified,
                })
            try:
                target_blob_client.delete_blob(**delete_kwargs)
            except Exception:
                pass

    return {
        "status": "failed",
        "bytes": 0,
        "attempt": retry_count,
        "elapsed_seconds": time.perf_counter() - started_at,
        "error": last_error or "Source blob copy failed.",
    }


def _copy_source_blobs_to_target(settings, migration_plan, job, migration_state, provenance_context):
    if not migration_plan.get("include_source_blobs"):
        return []
    source_client = _get_source_blob_service_client()
    if not source_client:
        return [{"name": "source_blobs", "type": "source_blobs", "status": "skipped", "warning": "Source Enhanced Citations storage is not configured."}]

    resource_name = "source_blobs:selected_documents"
    completed_resource = migration_state.get("resources", {}).get(resource_name)
    if is_migration_resource_completed(migration_state, resource_name):
        previous_result = completed_resource.get("result") if isinstance(completed_resource, dict) else {}
        return [{
            "name": "source_blobs",
            "type": "source_blobs",
            "status": "checkpoint_completed",
            **(previous_result if isinstance(previous_result, dict) else {}),
        }]

    target_client = _get_target_enhanced_citations_blob_client(settings)
    resource = start_migration_resource(migration_state, resource_name)
    resource_started_at = resource.get("attempt_started_at") or resource.get("started_at")
    source_cutoff = _parse_iso_datetime(migration_state.get("source_cutoff_at"))
    source_cutoff_epoch = int(source_cutoff.timestamp()) if source_cutoff else None
    parallel_operations = _get_migration_parallel_operations(settings)
    retry_count = _get_migration_retry_count(settings)
    migration_mode = _safe_text(
        (provenance_context or {}).get("migration_mode"),
        DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
    )
    previous_progress = resource.get("progress") if isinstance(resource.get("progress"), dict) else {}
    copied_count = _safe_int(previous_progress.get("copied_count"), default=0, minimum=0)
    skipped_count = _safe_int(previous_progress.get("skipped_count"), default=0, minimum=0)
    prior_failed_count = _safe_int(previous_progress.get("failed_count"), default=0, minimum=0)
    prior_collision_count = _safe_int(previous_progress.get("collision_count"), default=0, minimum=0)
    prior_missing_count = _safe_int(previous_progress.get("missing_count"), default=0, minimum=0)
    failed_count = 0
    collision_count = 0
    missing_count = 0
    not_applicable_count = _safe_int(previous_progress.get("not_applicable_count"), default=0, minimum=0)
    created_count = _safe_int(previous_progress.get("created_count"), default=0, minimum=0)
    updated_count = _safe_int(previous_progress.get("updated_count"), default=0, minimum=0)
    unchanged_count = _safe_int(previous_progress.get("unchanged_count"), default=0, minimum=0)
    retry_attempt_count = _safe_int(previous_progress.get("retry_attempt_count"), default=0, minimum=0)
    byte_count = _safe_int(previous_progress.get("bytes"), default=0, minimum=0)
    container_stats = {}
    errors = []
    append_manifest, flush_manifest = _create_migration_manifest_writer(
        job.get("id"),
        resource_name,
    )
    transfer_progress = {}
    transfer_progress_lock = Lock()
    transfer_cancel_event = Event()

    def persist_progress(message="Migrating selected source document blobs"):
        nonlocal migration_state
        flush_manifest()
        with transfer_progress_lock:
            in_flight_bytes = sum(transfer_progress.values())
        progress = build_transfer_metrics(
            resource_started_at,
            copied_count=copied_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            byte_count=byte_count,
        )
        progress.update({
            "missing_count": missing_count,
            "not_applicable_count": not_applicable_count,
            "parallel_operations": parallel_operations,
            "retry_count": retry_count,
            "collision_count": collision_count,
            "migration_mode": migration_mode,
            "baseline_source_cutoff_at": _safe_text(
                (provenance_context or {}).get("baseline_source_cutoff_at")
            ),
            "created_count": created_count,
            "updated_count": updated_count,
            "unchanged_count": unchanged_count,
            "retry_attempt_count": retry_attempt_count,
            "prior_failed_count": prior_failed_count,
            "prior_collision_count": prior_collision_count,
            "prior_missing_count": prior_missing_count,
            "in_flight_bytes": in_flight_bytes,
            "observed_bytes": byte_count + in_flight_bytes,
            "observed_bytes_per_second": round(
                (byte_count + in_flight_bytes) /
                max(0.001, float(progress.get("elapsed_seconds") or 0.001)),
                3,
            ),
            "active_transfer_count": len(transfer_progress),
        })
        migration_state = _persist_migration_checkpoint(
            job,
            migration_state,
            settings,
            resource_name,
            progress,
            message,
        )
        return migration_state

    def make_transfer_progress_callback(reference_key):
        def report_progress(byte_delta, reset=False):
            with transfer_progress_lock:
                if reset:
                    transfer_progress[reference_key] = 0
                else:
                    transfer_progress[reference_key] = (
                        transfer_progress.get(reference_key, 0) +
                        _safe_int(byte_delta, default=0, minimum=0)
                    )
        return report_progress

    def consume_copy_future(result_container_name, reference_key, future):
        nonlocal copied_count, skipped_count, failed_count, collision_count, missing_count, byte_count
        nonlocal created_count, updated_count, unchanged_count, retry_attempt_count
        with transfer_progress_lock:
            transfer_progress.pop(reference_key, None)
        copy_result = future.result()
        artifact = container_stats[result_container_name]
        artifact["blob_count"] += 1
        status = copy_result.get("status")
        retry_attempt_count += max(0, _safe_int(copy_result.get("attempt"), default=1) - 1)
        if status in {"copied", "updated"}:
            copied_count += 1
            if status == "updated":
                updated_count += 1
                artifact["updated_count"] += 1
            else:
                created_count += 1
                artifact["created_count"] += 1
            byte_count += copy_result.get("bytes", 0)
            artifact["copied_count"] += 1
            artifact["bytes"] += copy_result.get("bytes", 0)
        elif status in {"unchanged", "resume_verified"}:
            if status == "unchanged":
                skipped_count += 1
                unchanged_count += 1
            artifact["skipped_count"] += 1
            if status == "unchanged":
                artifact["unchanged_count"] += 1
        elif status == "missing":
            missing_count += 1
            artifact["missing_count"] += 1
        else:
            failed_count += 1
            if status == "collision":
                collision_count += 1
                artifact["collision_count"] += 1
            artifact["failed_count"] += 1
            errors.append(copy_result.get("error", "Source blob copy failed."))
        append_manifest({
            "service": "source_blobs",
            "resource_name": resource_name,
            "source_identity": _hash_migration_manifest_identity(
                "source",
                result_container_name,
                reference_key.split("\n", 1)[-1],
            ),
            "destination_identity": _hash_migration_manifest_identity(
                "destination",
                result_container_name,
                reference_key.split("\n", 1)[-1],
            ),
            "status": status,
            "attempt": copy_result.get("attempt"),
            "bytes": copy_result.get("bytes", 0),
            "source_version": copy_result.get("source_version"),
            "source_hash": copy_result.get("source_hash"),
            "error": copy_result.get("error"),
            "_locator": {
                "service": "source_blobs",
                "resource_name": resource_name,
                "container_name": result_container_name,
                "blob_name": reference_key.split("\n", 1)[-1],
            },
        })

    def process_pending_copies(pending_copies):
        pending_by_future = {
            future: (result_container_name, reference_key)
            for result_container_name, reference_key, future in pending_copies
        }
        last_heartbeat = 0.0
        while pending_by_future:
            completed_futures, _pending_futures = wait(
                set(pending_by_future),
                timeout=1.0,
                return_when=FIRST_COMPLETED,
            )
            for future in completed_futures:
                result_container_name, reference_key = pending_by_future.pop(future)
                consume_copy_future(result_container_name, reference_key, future)
            now = time.monotonic()
            if pending_by_future and now - last_heartbeat >= 2.0:
                try:
                    persist_progress("Migrating source blobs; worker heartbeat renewed")
                except (DataManagementMigrationCanceledError, DataManagementMigrationLeaseLostError):
                    transfer_cancel_event.set()
                    for future in pending_by_future:
                        future.cancel()
                    raise
                last_heartbeat = now

    try:
        pending_copies = []
        pending_reference_keys = set()
        with ThreadPoolExecutor(max_workers=parallel_operations) as executor:
            for document in _iter_selected_document_records_for_blob_migration(
                migration_plan,
                source_cutoff_epoch=source_cutoff_epoch,
            ):
                reference = _document_blob_reference(document)
                if not reference:
                    not_applicable_count += 1
                    append_manifest({
                        "service": "source_blobs",
                        "resource_name": resource_name,
                        "source_identity": _hash_migration_manifest_identity(
                            "no-source-blob",
                            document.get("id"),
                        ),
                        "status": "not_applicable",
                        "_locator": {
                            "service": "source_blobs",
                            "resource_name": resource_name,
                            "document_id": document.get("id"),
                        },
                    })
                    continue
                container_name, blob_path = reference
                reference_key = f"{container_name}\n{blob_path}"
                if reference_key in pending_reference_keys:
                    continue
                artifact = container_stats.setdefault(container_name, {
                    "name": container_name,
                    "type": "source_blob_container",
                    "container_name": container_name,
                    "blob_count": 0,
                    "copied_count": 0,
                    "created_count": 0,
                    "updated_count": 0,
                    "unchanged_count": 0,
                    "skipped_count": 0,
                    "missing_count": 0,
                    "collision_count": 0,
                    "failed_count": 0,
                    "bytes": 0,
                })
                try:
                    target_client.create_container(container_name)
                except ResourceExistsError:
                    pass
                source_blob_client = source_client.get_blob_client(
                    container=container_name,
                    blob=blob_path,
                )
                target_blob_client = target_client.get_blob_client(
                    container=container_name,
                    blob=blob_path,
                )
                if not pending_copies:
                    _assert_migration_job_lease(job)
                pending_reference_keys.add(reference_key)
                progress_callback = make_transfer_progress_callback(reference_key)
                pending_copies.append((container_name, reference_key, executor.submit(
                    _copy_source_blob_migration_record,
                    source_blob_client,
                    target_blob_client,
                    provenance_context,
                    retry_count,
                    _document_migration_scope_hash(document),
                    progress_callback,
                    transfer_cancel_event,
                )))
                if len(pending_copies) < parallel_operations:
                    continue
                process_pending_copies(pending_copies)
                pending_copies = []
                pending_reference_keys.clear()
                persist_progress()

            process_pending_copies(pending_copies)

        flush_manifest()

        result = build_transfer_metrics(
            resource_started_at,
            copied_count=copied_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            byte_count=byte_count,
        )
        result.update({
            "name": "source_blobs",
            "type": "source_blobs",
            "missing_count": missing_count,
            "not_applicable_count": not_applicable_count,
            "parallel_operations": parallel_operations,
            "retry_count": retry_count,
            "collision_count": collision_count,
            "container_count": len(container_stats),
            "migration_mode": migration_mode,
            "baseline_source_cutoff_at": _safe_text(
                (provenance_context or {}).get("baseline_source_cutoff_at")
            ),
            "created_count": created_count,
            "updated_count": updated_count,
            "unchanged_count": unchanged_count,
            "retry_attempt_count": retry_attempt_count,
        })
        if failed_count or missing_count:
            failure_message = (
                f"{missing_count} persisted source blob reference(s) could not be resolved."
                if missing_count else
                "; ".join(errors[:3]) or "Source blob copy failed."
            )
            persist_progress("Source blob migration requires remediation before retry")
            migration_state = _fail_migration_resource_checkpoint(
                job,
                migration_state,
                settings,
                resource_name,
                failure_message,
            )
            raise RuntimeError(
                "Source blob migration requires remediation before retry: "
                f"{failed_count} failed and {missing_count} unexpectedly missing blob(s)."
            )
        migration_state = _complete_migration_resource_checkpoint(
            job,
            migration_state,
            settings,
            resource_name,
            result,
            "Completed selected source document blob migration",
        )
        artifacts = list(container_stats.values())
        artifacts.append(result)
        return artifacts
    except Exception as exc:
        flush_manifest()
        if not failed_count:
            _fail_migration_resource_checkpoint(
                job,
                migration_state,
                settings,
                resource_name,
                str(exc),
            )
        raise


def _iter_target_cosmos_records(target_container, container_definition, selection):
    """Enumerate the exact destination scope used by the migration plan."""
    mode = selection.get("mode")
    if mode == "all":
        yield from target_container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True,
        )
        return
    if mode != "selected":
        return
    if container_definition.get("id_field") == "id":
        for item_id in selection.get("ids") or []:
            try:
                yield target_container.read_item(item=item_id, partition_key=item_id)
            except (CosmosResourceNotFoundError, ResourceNotFoundError):
                continue
        return
    filter_fields = _get_selected_scope_filter_fields(container_definition)
    if not filter_fields:
        return
    filter_clause = _build_selected_scope_filter_clause(filter_fields)
    seen_identities = set() if len(filter_fields) > 1 else None
    for selected_id in selection.get("ids") or []:
        for item in target_container.query_items(
            query=f"SELECT * FROM c WHERE {filter_clause}",
            parameters=[{"name": "@selected_id", "value": selected_id}],
            enable_cross_partition_query=True,
        ):
            if seen_identities is not None:
                item_identity = _get_cosmos_document_identity(
                    item,
                    container_definition["partition_key_path"],
                )
                if item_identity and item_identity in seen_identities:
                    continue
                if item_identity:
                    seen_identities.add(item_identity)
            yield item


def _delete_target_cosmos_record(target_container, document, partition_key_path):
    delete_kwargs = {
        "item": document.get("id"),
        "partition_key": _get_document_path_value(document, partition_key_path),
    }
    if document.get("_etag"):
        delete_kwargs.update({
            "etag": document.get("_etag"),
            "match_condition": MatchConditions.IfNotModified,
        })
    target_container.delete_item(**delete_kwargs)


def _get_reconciliation_target_cosmos_container(
    target_database,
    container_name,
    partition_key_path,
    read_only,
):
    if not read_only:
        return _get_target_cosmos_container(
            target_database,
            container_name,
            partition_key_path,
        )
    get_container_client = getattr(target_database, "get_container_client", None)
    if not callable(get_container_client):
        return _get_target_cosmos_container(
            target_database,
            container_name,
            partition_key_path,
        )
    target_container = get_container_client(container_name)
    try:
        _validate_target_cosmos_container_partition_key(
            target_container,
            container_name,
            partition_key_path,
        )
    except (CosmosResourceNotFoundError, ResourceNotFoundError):
        return None
    return target_container


def _migration_blob_container_target_type(container_name):
    container_mappings = {
        getattr(app_config, "storage_account_user_documents_container_name", ""): "users",
        getattr(app_config, "storage_account_group_documents_container_name", ""): "groups",
        getattr(app_config, "storage_account_public_documents_container_name", ""): "public_workspaces",
    }
    return container_mappings.get(container_name)


def _selected_scope_hashes(target_type, selection):
    if selection.get("mode") == "all":
        return None
    return {
        hashlib.sha256(f"{target_type}:{scope_id}".encode("utf-8")).hexdigest()
        for scope_id in _dedupe_limited_strings(selection.get("ids"), limit=2000)
    }


def _new_reconciliation_report(service, include_blob_fields=False):
    report = {
        "service": service,
        "matched_count": 0,
        "missing_count": 0,
        "destination_only_owned_count": 0,
        "remaining_destination_only_owned_count": 0,
        "destination_only_unowned_count": 0,
        "conflict_count": 0,
        "deleted_count": 0,
        "create_count": 0,
        "update_count": 0,
        "unchanged_count": 0,
        "stale_count": 0,
        "delete_candidate_count": 0,
        "resources": [],
    }
    if include_blob_fields:
        report.update({
            "unresolved_scope_count": 0,
            "not_applicable_count": 0,
            "source_missing_count": 0,
        })
    return report


def _start_reconciliation_heartbeat_thread(
    job,
    settings,
    state_holder,
    stop_event,
    failure_holder,
    persistence_lock,
):
    def run_heartbeat():
        while not stop_event.wait(2.0):
            try:
                with persistence_lock:
                    state = state_holder["state"]
                    state_holder["state"] = _persist_migration_state(
                        job,
                        state,
                        settings,
                        "Reconciliation worker heartbeat renewed",
                    )
            except Exception as exc:
                failure_holder["error"] = exc
                stop_event.set()
                return

    heartbeat_thread = Thread(target=run_heartbeat, daemon=True)
    heartbeat_thread.start()
    return heartbeat_thread


def _raise_reconciliation_heartbeat_failure(stop_event, failure_holder):
    if not stop_event.is_set():
        return
    error = failure_holder.get("error")
    if error:
        raise error
    raise DataManagementMigrationCanceledError("Reconciliation was canceled.")


def _append_reconciliation_resource(report, resource_report):
    report["resources"].append(resource_report)
    for field_name in report:
        if field_name in {"service", "resources"} or str(field_name).startswith("_"):
            continue
        report[field_name] += _safe_int(resource_report.get(field_name), default=0, minimum=0)


def _emit_reconciliation_candidate(report, candidate, deletion_candidate_callback):
    if callable(deletion_candidate_callback):
        deletion_candidate_callback(_sanitize_mirror_deletion_candidate(candidate))


def _reconcile_cosmos_migration(
    target_database,
    migration_plan,
    migration_state,
    provenance_context,
    apply_deletions=False,
    heartbeat_callback=None,
    deletion_candidate_callback=None,
    stop_event=None,
    failure_holder=None,
):
    """Reconcile Cosmos with bounded point reads and one destination scan."""
    report = _new_reconciliation_report("cosmos")
    for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPE_ORDER:
        selection = migration_plan.get(target_type) or {}
        if selection.get("mode") == "none":
            continue
        for container_definition in DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS[target_type]:
            if container_definition.get("documents") and not selection.get("include_documents"):
                continue
            container_name = _target_cosmos_container_name(container_definition)
            target_container = _get_reconciliation_target_cosmos_container(
                target_database,
                container_name,
                container_definition["partition_key_path"],
                read_only=True,
            )
            source_container = getattr(app_config, container_definition["container_attr"], None)
            resource_report = {
                "target_type": target_type,
                "container_name": container_name,
                "source_count": 0,
                "target_count": 0,
                "matched_count": 0,
                "missing_count": 0,
                "destination_only_owned_count": 0,
                "remaining_destination_only_owned_count": 0,
                "destination_only_unowned_count": 0,
                "conflict_count": 0,
                "deleted_count": 0,
                "create_count": 0,
                "update_count": 0,
                "unchanged_count": 0,
                "stale_count": 0,
                "delete_candidate_count": 0,
            }
            for item, source_version in _iter_selected_cosmos_records(
                container_definition,
                selection,
                include_source_version=True,
            ) or []:
                if stop_event is not None:
                    _raise_reconciliation_heartbeat_failure(stop_event, failure_holder or {})
                resource_report["source_count"] += 1
                if heartbeat_callback and resource_report["source_count"] % 250 == 0:
                    heartbeat_callback(
                        f"Reconciling source Cosmos container {container_name}",
                        resource_report["source_count"],
                    )
                target_document = (
                    _get_target_cosmos_document(
                        target_container,
                        item,
                        container_definition["partition_key_path"],
                    )
                    if target_container is not None else None
                )
                if target_document is None:
                    resource_report["missing_count"] += 1
                    resource_report["create_count"] += 1
                    continue
                target_provenance = get_cosmos_migration_provenance(target_document)
                if not is_successful_migration_record(target_provenance):
                    resource_report["conflict_count"] += 1
                    continue
                resource_report["matched_count"] += 1
                source_hash = _build_cosmos_source_hash(item)
                if migration_record_matches_source(
                    target_provenance,
                    source_hash=source_hash,
                    source_version=source_version,
                ):
                    resource_report["unchanged_count"] += 1
                else:
                    resource_report["stale_count"] += 1
                    if migration_plan.get("migration_mode") != DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY:
                        resource_report["update_count"] += 1

            target_records = (
                _iter_target_cosmos_records(target_container, container_definition, selection)
                if target_container is not None else []
            )
            for target_document in target_records or []:
                if stop_event is not None:
                    _raise_reconciliation_heartbeat_failure(stop_event, failure_holder or {})
                resource_report["target_count"] += 1
                if heartbeat_callback and resource_report["target_count"] % 250 == 0:
                    heartbeat_callback(
                        f"Reconciling destination Cosmos container {container_name}",
                        resource_report["target_count"],
                    )
                target_provenance = get_cosmos_migration_provenance(target_document)
                if _source_cosmos_document_exists(
                    source_container,
                    target_document,
                    container_definition["partition_key_path"],
                ):
                    continue
                if is_successful_migration_record(target_provenance):
                    resource_report["destination_only_owned_count"] += 1
                    resource_report["remaining_destination_only_owned_count"] += 1
                    if migration_plan.get("migration_mode") == DATA_MANAGEMENT_MIGRATION_MODE_MIRROR:
                        resource_report["delete_candidate_count"] += 1
                        _emit_reconciliation_candidate(report, {
                            "service": "cosmos",
                            "target_type": target_type,
                            "container_name": container_name,
                            "document_id": target_document.get("id"),
                            "partition_key": _get_document_path_value(
                                target_document,
                                container_definition["partition_key_path"],
                            ),
                            "target_etag": target_document.get("_etag"),
                        }, deletion_candidate_callback)
                else:
                    resource_report["destination_only_unowned_count"] += 1
            _append_reconciliation_resource(report, resource_report)
    return report


def _source_cosmos_document_exists(source_container, target_document, partition_key_path):
    if source_container is None:
        return True
    try:
        source_container.read_item(
            item=target_document.get("id"),
            partition_key=_get_document_path_value(target_document, partition_key_path),
        )
        return True
    except (CosmosResourceNotFoundError, ResourceNotFoundError):
        return False


def _iter_search_documents_keyset(search_client, search_filter=None, select=None):
    for page, _last_id in _iter_search_document_pages(
        search_client,
        search_filter=search_filter,
        select=select,
    ):
        yield from page


def _next_or_none(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return None


def _reconcile_ai_search_migration(
    settings,
    migration_plan,
    apply_deletions=False,
    heartbeat_callback=None,
    deletion_candidate_callback=None,
    stop_event=None,
    failure_holder=None,
):
    """Reconcile Search by merging two ordered keyset streams."""
    report = _new_reconciliation_report("ai_search")
    if not migration_plan.get("include_ai_search"):
        return report
    search_mappings = [
        ("users", "user_id", DATA_MANAGEMENT_SEARCH_ARTIFACTS[0]),
        ("groups", "group_id", DATA_MANAGEMENT_SEARCH_ARTIFACTS[1]),
        ("public_workspaces", "public_workspace_id", DATA_MANAGEMENT_SEARCH_ARTIFACTS[2]),
    ]
    provenance_select = [
        "id",
        SEARCH_MIGRATION_ID_FIELD,
        SEARCH_MIGRATED_AT_FIELD,
        SEARCH_MIGRATION_STATUS_FIELD,
        SEARCH_MIGRATION_SOURCE_HASH_FIELD,
        SEARCH_MIGRATION_SOURCE_VERSION_FIELD,
    ]
    for target_type, field_name, artifact in search_mappings:
        selection = migration_plan.get(target_type) or {}
        if selection.get("mode") == "none" or not selection.get("include_documents"):
            continue
        source_client = CLIENTS.get(artifact["client_key"])
        if not source_client:
            continue
        target_client = _get_target_search_client(settings, artifact["index_name"])
        resource_report = {
            "target_type": target_type,
            "index_name": artifact["index_name"],
            "source_count": 0,
            "target_count": 0,
            "matched_count": 0,
            "missing_count": 0,
            "destination_only_owned_count": 0,
            "remaining_destination_only_owned_count": 0,
            "destination_only_unowned_count": 0,
            "conflict_count": 0,
            "deleted_count": 0,
            "create_count": 0,
            "update_count": 0,
            "unchanged_count": 0,
            "stale_count": 0,
            "delete_candidate_count": 0,
        }
        for search_filter in _build_search_scope_filter_batches(field_name, selection):
            source_iterator = iter(_iter_search_documents_keyset(
                source_client,
                search_filter=search_filter,
            ))
            try:
                target_iterator = iter(_iter_search_documents_keyset(
                    target_client,
                    search_filter=search_filter,
                    select=provenance_select,
                ))
                source_document = _next_or_none(source_iterator)
                target_document = _next_or_none(target_iterator)
            except ResourceNotFoundError:
                source_document = _next_or_none(source_iterator)
                target_document = None
                target_iterator = iter(())
            while source_document is not None or target_document is not None:
                if stop_event is not None:
                    _raise_reconciliation_heartbeat_failure(stop_event, failure_holder or {})
                source_id = _safe_text((source_document or {}).get("id"))
                target_id = _safe_text((target_document or {}).get("id"))
                if target_document is None or (source_document is not None and source_id < target_id):
                    resource_report["source_count"] += 1
                    resource_report["missing_count"] += 1
                    resource_report["create_count"] += 1
                    source_document = _next_or_none(source_iterator)
                elif source_document is None or target_id < source_id:
                    resource_report["target_count"] += 1
                    target_provenance = get_search_migration_provenance(target_document)
                    if is_successful_migration_record(target_provenance):
                        resource_report["destination_only_owned_count"] += 1
                        resource_report["remaining_destination_only_owned_count"] += 1
                        if migration_plan.get("migration_mode") == DATA_MANAGEMENT_MIGRATION_MODE_MIRROR:
                            resource_report["delete_candidate_count"] += 1
                            _emit_reconciliation_candidate(report, {
                                "service": "ai_search",
                                "target_type": target_type,
                                "index_name": artifact["index_name"],
                                "document_id": target_id,
                            }, deletion_candidate_callback)
                    else:
                        resource_report["destination_only_unowned_count"] += 1
                    target_document = _next_or_none(target_iterator)
                else:
                    resource_report["source_count"] += 1
                    resource_report["target_count"] += 1
                    target_provenance = get_search_migration_provenance(target_document)
                    if not is_successful_migration_record(target_provenance):
                        resource_report["conflict_count"] += 1
                    else:
                        resource_report["matched_count"] += 1
                        if migration_record_matches_source(
                            target_provenance,
                            source_hash=_build_search_source_hash(source_document),
                        ):
                            resource_report["unchanged_count"] += 1
                        else:
                            resource_report["stale_count"] += 1
                            if migration_plan.get("migration_mode") != DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY:
                                resource_report["update_count"] += 1
                    source_document = _next_or_none(source_iterator)
                    target_document = _next_or_none(target_iterator)
                processed_count = resource_report["source_count"] + resource_report["target_count"]
                if heartbeat_callback and processed_count % 1000 == 0:
                    heartbeat_callback(
                        f"Reconciling AI Search index {artifact['index_name']}",
                        processed_count,
                    )
        _append_reconciliation_resource(report, resource_report)
    return report


def _source_blob_reference_exists_in_plan(
    migration_plan,
    container_name,
    blob_name,
    scope_hash,
):
    target_type = _migration_blob_container_target_type(container_name)
    selection = migration_plan.get(target_type) or {}
    allowed_scope_hashes = _selected_scope_hashes(target_type, selection)
    if allowed_scope_hashes is not None and scope_hash not in allowed_scope_hashes:
        return False
    container_definition = next((
        definition
        for definition in DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS.get(target_type, [])
        if definition.get("documents")
    ), None)
    source_container = (
        getattr(app_config, container_definition["container_attr"], None)
        if container_definition else None
    )
    if source_container is None:
        return True
    query = (
        "SELECT * FROM c WHERE c.blob_path = @blob_path "
        "OR c.archived_blob_path = @blob_path"
    )
    for document in source_container.query_items(
        query=query,
        parameters=[{"name": "@blob_path", "value": blob_name}],
        enable_cross_partition_query=True,
    ):
        if allowed_scope_hashes is None or _document_migration_scope_hash(document) == scope_hash:
            return True
    return False


def _reconcile_blob_migration(
    settings,
    migration_plan,
    apply_deletions=False,
    heartbeat_callback=None,
    deletion_candidate_callback=None,
    stop_event=None,
    failure_holder=None,
):
    """Reconcile Blob paths with bounded point reads and a destination scan."""
    report = _new_reconciliation_report("source_blobs", include_blob_fields=True)
    if not migration_plan.get("include_source_blobs"):
        return report
    target_service = _get_target_enhanced_citations_blob_client(settings)
    source_service = _get_source_blob_service_client()
    resource_reports = {}
    for document_count, document in enumerate(
        _iter_selected_document_records_for_blob_migration(migration_plan),
        start=1,
    ):
        if stop_event is not None:
            _raise_reconciliation_heartbeat_failure(stop_event, failure_holder or {})
        reference = _document_blob_reference(document)
        if not reference:
            report["not_applicable_count"] += 1
            continue
        container_name, blob_name = reference
        target_type = _migration_blob_container_target_type(container_name)
        resource_report = resource_reports.setdefault(container_name, {
            "target_type": target_type,
            "container_name": container_name,
            "source_count": 0,
            "target_count": 0,
            "matched_count": 0,
            "missing_count": 0,
            "destination_only_owned_count": 0,
            "remaining_destination_only_owned_count": 0,
            "destination_only_unowned_count": 0,
            "conflict_count": 0,
            "deleted_count": 0,
            "unresolved_scope_count": 0,
            "not_applicable_count": 0,
            "source_missing_count": 0,
            "create_count": 0,
            "update_count": 0,
            "unchanged_count": 0,
            "stale_count": 0,
            "delete_candidate_count": 0,
        })
        resource_report["source_count"] += 1
        source_blob = source_service.get_blob_client(container=container_name, blob=blob_name)
        try:
            source_properties = source_blob.get_blob_properties()
        except ResourceNotFoundError:
            resource_report["source_missing_count"] += 1
            continue
        target_blob = target_service.get_blob_client(container=container_name, blob=blob_name)
        target_properties = _get_blob_properties_or_none(target_blob)
        if target_properties is None:
            resource_report["missing_count"] += 1
            resource_report["create_count"] += 1
            continue
        target_provenance = get_blob_migration_provenance(
            getattr(target_properties, "metadata", None)
        )
        if not is_successful_migration_record(target_provenance):
            resource_report["conflict_count"] += 1
            continue
        resource_report["matched_count"] += 1
        source_hash, source_version = _build_blob_source_fingerprint(source_properties)
        if migration_record_matches_source(
            target_provenance,
            source_hash=source_hash,
            source_version=source_version,
        ):
            resource_report["unchanged_count"] += 1
        else:
            resource_report["stale_count"] += 1
            if migration_plan.get("migration_mode") != DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY:
                resource_report["update_count"] += 1
        if heartbeat_callback and document_count % 250 == 0:
            heartbeat_callback("Reconciling source Blob references", document_count)

    for container_name, resource_report in resource_reports.items():
        target_type = resource_report["target_type"]
        selection = migration_plan.get(target_type) or {}
        allowed_scope_hashes = _selected_scope_hashes(target_type, selection)
        container_client = target_service.get_container_client(container_name)
        try:
            target_blob_items = container_client.list_blobs(include=["metadata"])
        except ResourceNotFoundError:
            target_blob_items = []
        for target_count, blob_item in enumerate(target_blob_items, start=1):
            if stop_event is not None:
                _raise_reconciliation_heartbeat_failure(stop_event, failure_holder or {})
            metadata = (
                blob_item.get("metadata")
                if isinstance(blob_item, dict) else getattr(blob_item, "metadata", None)
            ) or {}
            provenance = get_blob_migration_provenance(metadata)
            blob_name = _safe_text(
                blob_item.get("name") if isinstance(blob_item, dict) else getattr(blob_item, "name", None)
            )
            if not blob_name:
                continue
            scope_hash = _safe_text(provenance.get("scopeHash"))
            source_reference_exists = _source_blob_reference_exists_in_plan(
                migration_plan,
                container_name,
                blob_name,
                scope_hash,
            )
            if is_successful_migration_record(provenance):
                if allowed_scope_hashes is not None and not scope_hash:
                    resource_report["unresolved_scope_count"] += 1
                    continue
                if allowed_scope_hashes is not None and scope_hash not in allowed_scope_hashes:
                    continue
            elif allowed_scope_hashes is not None and not source_reference_exists:
                continue
            resource_report["target_count"] += 1
            if source_reference_exists:
                continue
            if is_successful_migration_record(provenance):
                resource_report["destination_only_owned_count"] += 1
                resource_report["remaining_destination_only_owned_count"] += 1
                if migration_plan.get("migration_mode") == DATA_MANAGEMENT_MIGRATION_MODE_MIRROR:
                    resource_report["delete_candidate_count"] += 1
                    _emit_reconciliation_candidate(report, {
                        "service": "source_blobs",
                        "target_type": target_type,
                        "container_name": container_name,
                        "blob_name": blob_name,
                        "target_etag": (
                            blob_item.get("etag")
                            if isinstance(blob_item, dict) else getattr(blob_item, "etag", None)
                        ),
                    }, deletion_candidate_callback)
            else:
                resource_report["destination_only_unowned_count"] += 1
            if heartbeat_callback and target_count % 250 == 0:
                heartbeat_callback(f"Reconciling Blob container {container_name}", target_count)
        _append_reconciliation_resource(report, resource_report)
    return report


def _source_cosmos_identity_exists(candidate):
    container_definition = _get_migration_cosmos_container_definition(
        candidate.get("target_type"),
        candidate.get("container_name"),
    )
    source_container = (
        getattr(app_config, container_definition["container_attr"], None)
        if container_definition else None
    )
    if source_container is None:
        return True
    try:
        source_container.read_item(
            item=candidate.get("document_id"),
            partition_key=candidate.get("partition_key"),
        )
        return True
    except (CosmosResourceNotFoundError, ResourceNotFoundError):
        return False


def _source_search_identity_exists(candidate):
    artifact = _get_migration_search_artifact(candidate.get("target_type"))
    source_client = CLIENTS.get(artifact["client_key"]) if artifact else None
    document_id = _safe_text(candidate.get("document_id"))
    if source_client is None or not document_id:
        return True
    results = source_client.search(
        search_text="*",
        filter=f"id eq '{_escape_search_filter_value(document_id)}'",
        select=["id"],
        top=1,
        connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
        retry_total=0,
    )
    return any(_safe_text(dict(result).get("id")) == document_id for result in results)


def _source_blob_identity_exists(candidate):
    source_service = _get_source_blob_service_client()
    if source_service is None:
        return True
    source_blob = source_service.get_blob_client(
        container=candidate.get("container_name"),
        blob=candidate.get("blob_name"),
    )
    try:
        source_blob.get_blob_properties()
        return True
    except ResourceNotFoundError:
        return False


def _get_migration_cosmos_container_definition(target_type, container_name):
    for container_definition in DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS.get(
        _safe_text(target_type),
        [],
    ):
        if _target_cosmos_container_name(container_definition) == _safe_text(container_name):
            return container_definition
    return None


def _get_migration_search_artifact(target_type):
    artifacts_by_type = {
        "users": DATA_MANAGEMENT_SEARCH_ARTIFACTS[0],
        "groups": DATA_MANAGEMENT_SEARCH_ARTIFACTS[1],
        "public_workspaces": DATA_MANAGEMENT_SEARCH_ARTIFACTS[2],
    }
    return artifacts_by_type.get(_safe_text(target_type))


def _validate_mirror_deletion_candidate(candidate, settings=None, target_database=None):
    """Revalidate current source absence and destination ownership before any delete."""
    service = candidate.get("service")
    if service == "cosmos":
        if _source_cosmos_identity_exists(candidate):
            return False, "A Cosmos deletion candidate currently exists in the source."
        container_definition = _get_migration_cosmos_container_definition(
            candidate.get("target_type"),
            candidate.get("container_name"),
        )
        if not container_definition or target_database is None:
            return False, "A Cosmos deletion candidate could not resolve its resource definition."
        target_container = _get_reconciliation_target_cosmos_container(
            target_database,
            candidate.get("container_name"),
            container_definition["partition_key_path"],
            read_only=True,
        )
        try:
            current_target = target_container.read_item(
                item=candidate.get("document_id"),
                partition_key=candidate.get("partition_key"),
            )
        except (CosmosResourceNotFoundError, ResourceNotFoundError):
            current_target = None
        if not current_target or not is_successful_migration_record(
            get_cosmos_migration_provenance(current_target)
        ):
            return False, "A Cosmos deletion candidate lost migration ownership."
        if not candidate.get("target_etag") or current_target.get("_etag") != candidate.get("target_etag"):
            return False, "A Cosmos deletion candidate changed after reconciliation."
        candidate["target_container"] = target_container
        candidate["container_definition"] = container_definition
        candidate["target_document"] = current_target
        return True, ""
    if service == "ai_search":
        if _source_search_identity_exists(candidate):
            return False, "An AI Search deletion candidate currently exists in the source."
        artifact = _get_migration_search_artifact(candidate.get("target_type"))
        if not artifact:
            return False, "An AI Search deletion candidate could not resolve its index definition."
        target_client = _get_target_search_client(settings, artifact["index_name"])
        target_documents = _get_target_search_documents_by_ids(
            target_client,
            [candidate.get("document_id")],
        )
        current_target = target_documents.get(_safe_text(candidate.get("document_id")))
        if not current_target or not is_successful_migration_record(
            get_search_migration_provenance(current_target)
        ):
            return False, "An AI Search deletion candidate lost migration ownership."
        candidate["target_client"] = target_client
        candidate["index_name"] = artifact["index_name"]
        return True, ""
    if service == "source_blobs":
        if _source_blob_identity_exists(candidate):
            return False, "A Blob deletion candidate currently exists in the source."
        target_service = _get_target_enhanced_citations_blob_client(settings)
        target_blob = target_service.get_blob_client(
            container=candidate.get("container_name"),
            blob=candidate.get("blob_name"),
        )
        target_properties = _get_blob_properties_or_none(target_blob)
        if not target_properties or not is_successful_migration_record(
            get_blob_migration_provenance(getattr(target_properties, "metadata", None))
        ):
            return False, "A Blob deletion candidate lost migration ownership."
        current_etag = _safe_text(getattr(target_properties, "etag", None))
        if not candidate.get("target_etag") or current_etag != _safe_text(candidate.get("target_etag")):
            return False, "A Blob deletion candidate changed after reconciliation."
        candidate["target_blob"] = target_blob
        candidate["target_etag"] = current_etag
        return True, ""
    return False, "An unsupported mirror deletion candidate was produced."


def _validate_mirror_deletion_candidates(
    candidates,
    heartbeat_callback=None,
    settings=None,
    target_database=None,
):
    validated_count = 0
    blockers = set()
    last_heartbeat_at = 0.0
    for index, candidate in enumerate(candidates, start=1):
        now = time.monotonic()
        if heartbeat_callback and (
            index == 1 or
            index % 100 == 0 or
            now - last_heartbeat_at >= DATA_MANAGEMENT_MIGRATION_HEARTBEAT_INTERVAL_SECONDS
        ):
            heartbeat_callback("Revalidating mirror deletion candidates", index)
            last_heartbeat_at = now
        is_valid, blocker = _validate_mirror_deletion_candidate(
            candidate,
            settings=settings,
            target_database=target_database,
        )
        if is_valid:
            validated_count += 1
        elif len(blockers) < 20:
            blockers.add(blocker)
    return validated_count, sorted(blockers)


def _apply_mirror_deletion_candidates(
    candidates,
    heartbeat_callback=None,
    settings=None,
    target_database=None,
    manifest_append=None,
    manifest_flush=None,
):
    deleted_counts = {"cosmos": 0, "ai_search": 0, "source_blobs": 0}
    search_batch = []
    search_batch_key = None

    def record_deleted(candidate):
        if not callable(manifest_append):
            return
        manifest_append({
            "service": candidate.get("service"),
            "resource_name": "reconciliation:cutover",
            "target_type": candidate.get("target_type"),
            "source_identity": _hash_migration_manifest_identity(
                "deleted-source",
                candidate.get("service"),
                candidate.get("container_name") or candidate.get("index_name"),
                candidate.get("document_id") or candidate.get("blob_name"),
            ),
            "destination_identity": _hash_migration_manifest_identity(
                "deleted-destination",
                candidate.get("service"),
                candidate.get("container_name") or candidate.get("index_name"),
                candidate.get("document_id") or candidate.get("blob_name"),
            ),
            "status": "deleted",
            "_locator": {
                "service": candidate.get("service"),
                "resource_name": "reconciliation:cutover",
                "target_type": candidate.get("target_type"),
                "document_id": candidate.get("document_id"),
                "partition_key": candidate.get("partition_key"),
                "container_name": candidate.get("container_name"),
                "blob_name": candidate.get("blob_name"),
                "index_name": candidate.get("index_name"),
            },
        })
        if callable(manifest_flush):
            manifest_flush()

    def flush_search_batch():
        nonlocal search_batch, search_batch_key
        if not search_batch:
            return
        target_client = search_batch[0].get("target_client")
        last_heartbeat_at = 0.0
        for index, candidate in enumerate(search_batch, start=1):
            now = time.monotonic()
            if heartbeat_callback and (
                index == 1 or
                index % 100 == 0 or
                now - last_heartbeat_at >=
                DATA_MANAGEMENT_MIGRATION_HEARTBEAT_INTERVAL_SECONDS
            ):
                heartbeat_callback(
                    "Revalidating mirror AI Search deletions",
                    sum(deleted_counts.values()),
                )
                last_heartbeat_at = now
            is_valid, blocker = _validate_mirror_deletion_candidate(
                candidate,
                settings=settings,
                target_database=target_database,
            )
            if not is_valid:
                raise DataManagementSettingsValidationError(blocker)
        if heartbeat_callback:
            heartbeat_callback(
                "Applying mirror AI Search deletions",
                sum(deleted_counts.values()),
            )
        results = list(target_client.delete_documents(
            documents=[{"id": candidate.get("document_id")} for candidate in search_batch],
            connection_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
            read_timeout=DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS,
            retry_total=0,
        ))
        successful_count = 0
        failure_count = 0
        for candidate, delete_result in zip(search_batch, results):
            if _get_search_result_succeeded(delete_result):
                successful_count += 1
                record_deleted(candidate)
            else:
                failure_count += 1
        failure_count += max(0, len(search_batch) - len(results))
        deleted_counts["ai_search"] += successful_count
        if failure_count:
            raise RuntimeError(
                f"AI Search mirror reconciliation failed to delete {failure_count} document(s)."
            )
        search_batch = []
        search_batch_key = None

    for candidate in candidates:
        is_valid, blocker = _validate_mirror_deletion_candidate(
            candidate,
            settings=settings,
            target_database=target_database,
        )
        if not is_valid:
            raise DataManagementSettingsValidationError(blocker)
        if heartbeat_callback:
            heartbeat_callback(
                "Applying mirror deletions",
                sum(deleted_counts.values()),
            )
        if candidate.get("service") == "ai_search":
            candidate_key = candidate.get("index_name")
            if search_batch and (
                candidate_key != search_batch_key or
                len(search_batch) >= DATA_MANAGEMENT_MIGRATION_BATCH_SIZE
            ):
                flush_search_batch()
            search_batch_key = candidate_key
            search_batch.append(candidate)
            continue
        flush_search_batch()
        if candidate.get("service") == "cosmos":
            _delete_target_cosmos_record(
                candidate.get("target_container"),
                candidate.get("target_document"),
                (candidate.get("container_definition") or {}).get("partition_key_path"),
            )
            deleted_counts["cosmos"] += 1
            record_deleted(candidate)
        elif candidate.get("service") == "source_blobs":
            candidate.get("target_blob").delete_blob(
                etag=candidate.get("target_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
            deleted_counts["source_blobs"] += 1
            record_deleted(candidate)
    flush_search_batch()
    return deleted_counts


def _public_reconciliation_report(report):
    return {
        key: value
        for key, value in (report or {}).items()
        if not str(key).startswith("_")
    }


def _run_data_management_migration_reconciliation(
    settings,
    migration_plan,
    job,
    migration_state,
    provenance_context,
    target_database,
    preview_snapshot=None,
    migration_artifacts=None,
):
    """Persist final source/destination reconciliation and mirror deletion outcomes."""
    resource_name = "reconciliation:cutover"
    completed_resource = migration_state.get("resources", {}).get(resource_name)
    if is_migration_resource_completed(migration_state, resource_name):
        return completed_resource.get("result") if isinstance(completed_resource, dict) else {}
    start_migration_resource(migration_state, resource_name)
    deletion_plan_id = str(uuid.uuid4())
    append_deletion_candidate, flush_deletion_candidates = (
        _create_mirror_deletion_candidate_writer(job.get("id"), deletion_plan_id)
    )
    append_reconciliation_manifest, flush_reconciliation_manifest = (
        _create_migration_manifest_writer(job.get("id"), resource_name)
    )
    reconciliation_stop_event = Event()
    reconciliation_failure_holder = {}
    reconciliation_state_holder = {"state": migration_state}
    reconciliation_persistence_lock = Lock()
    reconciliation_heartbeat_thread = _start_reconciliation_heartbeat_thread(
        job,
        settings,
        reconciliation_state_holder,
        reconciliation_stop_event,
        reconciliation_failure_holder,
        reconciliation_persistence_lock,
    )
    last_heartbeat_at = 0.0
    heartbeat_count = 0
    aggregate_fields = (
        "matched_count",
        "missing_count",
        "destination_only_owned_count",
        "remaining_destination_only_owned_count",
        "destination_only_unowned_count",
        "conflict_count",
        "deleted_count",
        "unresolved_scope_count",
        "create_count",
        "update_count",
        "unchanged_count",
        "stale_count",
        "delete_candidate_count",
        "not_applicable_count",
        "source_missing_count",
    )
    service_reports = []

    def stop_reconciliation_heartbeat():
        reconciliation_stop_event.set()
        reconciliation_heartbeat_thread.join(timeout=5.0)

    def build_partial_result(error=None):
        partial_result = {
            field_name: sum(
                _safe_int(report.get(field_name), default=0, minimum=0)
                for report in service_reports
            )
            for field_name in aggregate_fields
        }
        partial_result.update({
            "name": "migration_reconciliation",
            "type": "migration_reconciliation",
            "migration_mode": migration_plan.get("migration_mode"),
            "readiness": "not_ready",
            "services_completed": len(service_reports),
            "services_total": 3,
            "services": [
                _public_reconciliation_report(report)
                for report in service_reports
            ],
        })
        if error:
            partial_result["error"] = str(error)[:1000]
        return partial_result

    def fail_reconciliation(error, failure_result=None):
        nonlocal migration_state
        stop_reconciliation_heartbeat()
        migration_state = reconciliation_state_holder["state"]
        persisted_result = copy.deepcopy(
            failure_result if isinstance(failure_result, dict) else build_partial_result(error)
        )
        resource = (migration_state.get("resources") or {}).get(resource_name)
        if isinstance(resource, dict):
            resource["result"] = persisted_result
        fail_migration_resource(
            migration_state,
            resource_name,
            str(error)[:1000],
        )
        job["migration_state"] = migration_state
        cleanup_errors = []
        for cleanup_name, cleanup in (
            ("deletion_plan", flush_deletion_candidates),
            ("manifest", flush_reconciliation_manifest),
        ):
            try:
                cleanup()
            except Exception as cleanup_exc:
                cleanup_errors.append(f"{cleanup_name}: {str(cleanup_exc)[:300]}")
        if cleanup_errors:
            persisted_result["persistence_warnings"] = cleanup_errors
            resource = (migration_state.get("resources") or {}).get(resource_name)
            if isinstance(resource, dict):
                resource["result"] = persisted_result
        try:
            _fail_migration_resource_checkpoint(
                job,
                migration_state,
                settings,
                resource_name,
                str(error)[:1000],
            )
        except Exception as checkpoint_exc:
            persisted_result.setdefault("persistence_warnings", []).append(
                f"checkpoint: {str(checkpoint_exc)[:300]}"
            )
            resource = (migration_state.get("resources") or {}).get(resource_name)
            if isinstance(resource, dict):
                resource["result"] = persisted_result
                resource["status"] = MIGRATION_RESOURCE_STATUS_FAILED
                resource["last_error"] = str(error)[:1000]
            job["migration_state"] = migration_state

    def persist_reconciliation_checkpoint(progress, message):
        nonlocal migration_state
        with reconciliation_persistence_lock:
            migration_state = reconciliation_state_holder["state"]
            migration_state = _persist_migration_checkpoint(
                job,
                migration_state,
                settings,
                resource_name,
                progress,
                message,
            )
            reconciliation_state_holder["state"] = migration_state
        return migration_state

    def heartbeat(message, completed_count=0, force=False):
        nonlocal migration_state, last_heartbeat_at, heartbeat_count
        _assert_migration_job_lease(job)
        heartbeat_count += 1
        now = time.monotonic()
        if not force and now - last_heartbeat_at < 2.0:
            return
        _raise_reconciliation_heartbeat_failure(
            reconciliation_stop_event,
            reconciliation_failure_holder,
        )
        with reconciliation_persistence_lock:
            migration_state = reconciliation_state_holder["state"]
            migration_state = _persist_migration_checkpoint(
                job,
                migration_state,
                settings,
                resource_name,
                {
                    "state": "reconciling",
                    "heartbeat_count": heartbeat_count,
                    "completed_count": completed_count,
                },
                message,
            )
            reconciliation_state_holder["state"] = migration_state
        last_heartbeat_at = now

    try:
        service_reports.append(_reconcile_cosmos_migration(
            target_database,
            migration_plan,
            migration_state,
            provenance_context,
            apply_deletions=False,
            heartbeat_callback=heartbeat,
            deletion_candidate_callback=append_deletion_candidate,
            stop_event=reconciliation_stop_event,
            failure_holder=reconciliation_failure_holder,
        ))
    except Exception as exc:
        fail_reconciliation(exc)
        raise
    try:
        flush_deletion_candidates()
        persist_reconciliation_checkpoint(
            {"services_completed": 1, "services_total": 3},
            "Reconciling migrated Cosmos records",
        )
    except Exception as exc:
        fail_reconciliation(exc)
        raise
    try:
        service_reports.append(_reconcile_ai_search_migration(
            settings,
            migration_plan,
            apply_deletions=False,
            heartbeat_callback=heartbeat,
            deletion_candidate_callback=append_deletion_candidate,
            stop_event=reconciliation_stop_event,
            failure_holder=reconciliation_failure_holder,
        ))
    except Exception as exc:
        fail_reconciliation(exc)
        raise
    try:
        flush_deletion_candidates()
        persist_reconciliation_checkpoint(
            {"services_completed": 2, "services_total": 3},
            "Reconciling migrated AI Search documents",
        )
    except Exception as exc:
        fail_reconciliation(exc)
        raise
    try:
        service_reports.append(_reconcile_blob_migration(
            settings,
            migration_plan,
            apply_deletions=False,
            heartbeat_callback=heartbeat,
            deletion_candidate_callback=append_deletion_candidate,
            stop_event=reconciliation_stop_event,
            failure_holder=reconciliation_failure_holder,
        ))
    except Exception as exc:
        fail_reconciliation(exc)
        raise
    try:
        flush_deletion_candidates()
        heartbeat("Completed read-only migration reconciliation", 3, force=True)
    except Exception as exc:
        fail_reconciliation(exc)
        raise
    result = {
        field_name: sum(_safe_int(report.get(field_name), default=0, minimum=0) for report in service_reports)
        for field_name in aggregate_fields
    }
    result.update({
        "name": "migration_reconciliation",
        "type": "migration_reconciliation",
        "migration_mode": migration_plan.get("migration_mode"),
        "deletion_policy": (
            "migration_owned_only"
            if migration_plan.get("migration_mode") == DATA_MANAGEMENT_MIGRATION_MODE_MIRROR else
            "retain_destination_only"
        ),
        "services": [_public_reconciliation_report(report) for report in service_reports],
    })
    actual_outcomes = {
        "create_count": 0,
        "update_count": 0,
        "unchanged_count": 0,
        "delete_count": result.get("delete_candidate_count", 0),
        "not_applicable_count": 0,
        "missing_count": 0,
        "conflict_count": 0,
        "failed_count": 0,
    }
    for artifact in migration_artifacts or []:
        if artifact.get("type") not in {
            "cosmos_container",
            "ai_search_documents",
            "source_blobs",
        }:
            continue
        actual_outcomes["create_count"] += _safe_int(
            artifact.get("created_count"),
            default=0,
            minimum=0,
        )
        actual_outcomes["update_count"] += _safe_int(
            artifact.get("updated_count"),
            default=0,
            minimum=0,
        )
        actual_outcomes["unchanged_count"] += _safe_int(
            artifact.get("unchanged_count"),
            default=0,
            minimum=0,
        )
        actual_outcomes["not_applicable_count"] += _safe_int(
            artifact.get("not_applicable_count"),
            default=0,
            minimum=0,
        )
        actual_outcomes["missing_count"] += _safe_int(
            artifact.get("missing_count"),
            default=0,
            minimum=0,
        )
        actual_outcomes["conflict_count"] += _safe_int(
            artifact.get("collision_count"),
            default=0,
            minimum=0,
        )
        actual_outcomes["failed_count"] += _safe_int(
            artifact.get("failed_count"),
            default=0,
            minimum=0,
        )
    preview_counts = (
        preview_snapshot.get("estimated_outcomes")
        if isinstance(preview_snapshot, dict) and
        isinstance(preview_snapshot.get("estimated_outcomes"), dict)
        else {}
    )
    result["preview_snapshot"] = _sanitize_activity_value(
        preview_snapshot if isinstance(preview_snapshot, dict) else {}
    )
    result["actual_outcomes"] = actual_outcomes
    result["preview_actual_divergence"] = {
        field_name: actual_outcomes.get(field_name, 0) - _safe_int(
            preview_counts.get(field_name),
            default=0,
        )
        for field_name in actual_outcomes
    }
    critical_mismatch_count = sum((
        result["missing_count"],
        result["conflict_count"],
        result["stale_count"],
        result["source_missing_count"],
        result["unresolved_scope_count"],
        actual_outcomes["failed_count"],
    ))
    if critical_mismatch_count:
        result["readiness"] = "not_ready"
    elif (
        result["remaining_destination_only_owned_count"] or
        result["destination_only_unowned_count"] or
        result["unresolved_scope_count"]
    ):
        result["readiness"] = "ready_with_warnings"
    else:
        result["readiness"] = "ready"

    is_mirror = (
        migration_plan.get("migration_mode") == DATA_MANAGEMENT_MIGRATION_MODE_MIRROR and
        migration_plan.get("mirror_deletions_confirmed") is True
    )
    if is_mirror:
        preview_divergence = result["preview_actual_divergence"]
        deletion_blockers = []
        if not preview_counts:
            deletion_blockers.append("Mirror deletion requires a server-owned inventory preview.")
        if any(value != 0 for value in preview_divergence.values()):
            deletion_blockers.append("Migration outcomes diverged from the queued preview.")
        if critical_mismatch_count:
            deletion_blockers.append("Reconciliation found missing, stale, failed, or conflicting items.")
        if result["destination_only_unowned_count"]:
            deletion_blockers.append("Unowned destination-only items prevent an exact mirror.")
        candidate_iterator = _iter_mirror_deletion_candidates(
            job.get("id"),
            deletion_plan_id,
        )
        try:
            validated_candidate_count, candidate_blockers = _validate_mirror_deletion_candidates(
                candidate_iterator,
                heartbeat_callback=heartbeat,
                settings=settings,
                target_database=target_database,
            )
        except Exception as exc:
            failure_result = copy.deepcopy(result)
            failure_result.update({
                "readiness": "not_ready",
                "error": str(exc)[:1000],
            })
            fail_reconciliation(exc, failure_result=failure_result)
            raise
        deletion_blockers.extend(candidate_blockers)
        if validated_candidate_count != result["delete_candidate_count"]:
            deletion_blockers.append("Mirror deletion candidate count changed during validation.")
        if deletion_blockers:
            result["readiness"] = "not_ready"
            result["deletion_status"] = "blocked"
            result["deletion_blockers"] = sorted(set(deletion_blockers))[:20]
        else:
            target_search_write_gate_container = None
            target_search_write_fence = None
            requires_search_write_fence = any(
                report.get("service") == "ai_search" and
                _safe_int(report.get("delete_candidate_count"), default=0) > 0
                for report in service_reports
            )

            last_target_search_fence_renewal = 0.0

            def mirror_deletion_heartbeat(message, completed_count=0):
                nonlocal last_target_search_fence_renewal
                heartbeat(message, completed_count)
                if (
                    target_search_write_gate_container is not None and
                    target_search_write_fence is not None and
                    time.monotonic() - last_target_search_fence_renewal >=
                    DATA_MANAGEMENT_MIGRATION_HEARTBEAT_INTERVAL_SECONDS
                ):
                    renew_data_management_search_write_fence(
                        target_search_write_gate_container,
                        target_search_write_fence,
                        _get_target_search_write_fence_lease_seconds(settings),
                    )
                    last_target_search_fence_renewal = time.monotonic()

            try:
                if requires_search_write_fence:
                    target_search_write_gate_container = _get_target_data_management_search_write_gate_container(
                        target_database
                    )
                    target_search_write_fence = acquire_data_management_search_write_fence(
                        target_search_write_gate_container,
                        job.get("id"),
                        _get_target_search_write_fence_lease_seconds(settings),
                        heartbeat_callback=lambda: heartbeat(
                            "Waiting for target AI Search writers to drain before mirror deletion",
                            result.get("deleted_count", 0),
                        ),
                    )
                deletion_counts = _apply_mirror_deletion_candidates(
                    _iter_mirror_deletion_candidates(job.get("id"), deletion_plan_id),
                    heartbeat_callback=mirror_deletion_heartbeat,
                    settings=settings,
                    target_database=target_database,
                    manifest_append=append_reconciliation_manifest,
                    manifest_flush=flush_reconciliation_manifest,
                )
                if target_search_write_gate_container is not None:
                    release_data_management_search_write_fence(
                        target_search_write_gate_container,
                        target_search_write_fence,
                    )
            except DataManagementMigrationCanceledError:
                if target_search_write_gate_container is not None:
                    release_data_management_search_write_fence(
                        target_search_write_gate_container,
                        target_search_write_fence,
                    )
                raise
            except Exception as exc:
                failure_result = copy.deepcopy(result)
                failure_result.update({
                    "readiness": "not_ready",
                    "error": str(exc)[:1000],
                })
                fail_reconciliation(exc, failure_result=failure_result)
                raise
            flush_reconciliation_manifest()
            result["deleted_count"] = sum(deletion_counts.values())
            result["remaining_destination_only_owned_count"] = max(
                0,
                result["destination_only_owned_count"] - result["deleted_count"],
            )
            result["actual_outcomes"]["delete_count"] = result["deleted_count"]
            result["preview_actual_divergence"]["delete_count"] = (
                result["deleted_count"] - _safe_int(preview_counts.get("delete_count"), default=0)
            )
            result["deletion_status"] = "completed"
            result["deletion_counts"] = deletion_counts
            result["readiness"] = (
                "ready"
                if not result["preview_actual_divergence"]["delete_count"] else
                "not_ready"
            )
            heartbeat("Completed guarded mirror deletions", result["deleted_count"], force=True)
    else:
        result["actual_outcomes"]["delete_count"] = 0
        result["preview_actual_divergence"]["delete_count"] = (
            0 - _safe_int(preview_counts.get("delete_count"), default=0)
        )
    if result["readiness"] == "not_ready":
        stop_reconciliation_heartbeat()
        flush_reconciliation_manifest()
        migration_state = reconciliation_state_holder["state"]
        resource = (migration_state.get("resources") or {}).get(resource_name)
        if isinstance(resource, dict):
            resource["result"] = copy.deepcopy(result)
        _fail_migration_resource_checkpoint(
            job,
            migration_state,
            settings,
            resource_name,
            "Migration reconciliation is not ready for cutover.",
        )
        raise RuntimeError("Migration reconciliation is not ready for cutover.")
    stop_reconciliation_heartbeat()
    migration_state = reconciliation_state_holder["state"]
    _complete_migration_resource_checkpoint(
        job,
        migration_state,
        settings,
        resource_name,
        result,
        "Completed migration source/destination reconciliation",
    )
    return result


def _migration_selection_summary(migration_plan):
    return {
        target_type: {
            "mode": (migration_plan.get(target_type) or {}).get("mode"),
            "selected_count": len((migration_plan.get(target_type) or {}).get("ids") or []),
            "include_documents": bool((migration_plan.get(target_type) or {}).get("include_documents")),
        }
        for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPES
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


def _get_migration_destination_lock_id(settings, migration_plan):
    """Use one global coordinator so partially overlapping migrations cannot race."""
    return f"{DATA_MANAGEMENT_MIGRATION_LOCK_PREFIX}_global"


def _get_migration_lock_lease_seconds(settings):
    configured_lease_seconds = _safe_int(
        (settings or {}).get("data_management_job_lease_seconds"),
        default=DATA_MANAGEMENT_DEFAULT_LEASE_SECONDS,
        minimum=60,
        maximum=7200,
    )
    minimum_quarantine_seconds = (
        DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS +
        DATA_MANAGEMENT_MIGRATION_LOCK_RECOVERY_GRACE_SECONDS
    )
    maximum_recovery_safe_seconds = (
        DATA_MANAGEMENT_DEFAULT_STALE_SECONDS -
        DATA_MANAGEMENT_RECOVERY_RESUBMIT_DELAY_SECONDS
    )
    return min(
        max(configured_lease_seconds, minimum_quarantine_seconds),
        maximum_recovery_safe_seconds,
    )


def _has_active_migration_destination_lock(job):
    """Return whether a coordinator lock remains active and clear only conclusively stale metadata."""
    lock = job.get("migration_coordinator_lock") if isinstance(job, dict) else None
    if not isinstance(lock, dict) or not lock.get("id") or not lock.get("lock_token"):
        if isinstance(job, dict):
            job.pop("migration_coordinator_lock", None)
        return False
    try:
        current_lock = _read_job(lock["id"])
    except (CosmosResourceNotFoundError, ResourceNotFoundError, KeyError):
        job.pop("migration_coordinator_lock", None)
        return False
    except Exception as exc:
        raise DataManagementMigrationLeaseLostError(
            "Migration destination coordinator lease could not be read while claiming a retry."
        ) from exc
    expires_at = _parse_iso_datetime(current_lock.get("expires_at"))
    lock_is_active = bool(
        current_lock.get("type") == DATA_MANAGEMENT_MIGRATION_LOCK_TYPE and
        expires_at and
        expires_at > _now_utc()
    )
    if not lock_is_active:
        job.pop("migration_coordinator_lock", None)
    return lock_is_active


def _acquire_migration_destination_lock(job, settings, migration_plan):
    """Acquire a destination-scoped lease so independent migration jobs cannot overlap."""
    if not isinstance(job, dict) or job.get("operation") != DATA_MANAGEMENT_OPERATION_MIGRATION:
        return None
    lock_id = _get_migration_destination_lock_id(settings, migration_plan)
    now = _now_utc()
    lease_seconds = _get_migration_lock_lease_seconds(settings)
    lock_document = {
        "id": lock_id,
        "type": DATA_MANAGEMENT_MIGRATION_LOCK_TYPE,
        "migration_job_id": job.get("id"),
        "lock_token": str(uuid.uuid4()),
        "acquired_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "lease_seconds": lease_seconds,
        "expires_at": (now + timedelta(seconds=lease_seconds)).isoformat(),
    }
    try:
        cosmos_data_management_jobs_container.create_item(body=lock_document)
    except Exception as exc:
        if getattr(exc, "status_code", None) != 409:
            raise
        existing_lock = _read_job(lock_id)
        expires_at = _parse_iso_datetime(existing_lock.get("expires_at"))
        if expires_at and expires_at > now:
            raise DataManagementSettingsValidationError(
                "Another Data Management migration is active for this destination. Wait for it to complete or expire before retrying."
            )
        replacement_lock = dict(existing_lock)
        replacement_lock.update(lock_document)
        try:
            cosmos_data_management_jobs_container.replace_item(
                item=lock_id,
                body=replacement_lock,
                etag=existing_lock.get("_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as replace_exc:
            if getattr(replace_exc, "status_code", None) in {409, 412}:
                raise DataManagementSettingsValidationError(
                    "Another Data Management migration acquired this destination before the retry could start."
                ) from replace_exc
            raise

    job["migration_coordinator_lock"] = {
        "id": lock_id,
        "lock_token": lock_document["lock_token"],
        "lease_seconds": lease_seconds,
        "expires_at": lock_document["expires_at"],
    }
    return job["migration_coordinator_lock"]


def _renew_migration_destination_lock(job, settings=None):
    """Renew and verify the exclusive destination lease held by this worker."""
    lock = job.get("migration_coordinator_lock") if isinstance(job, dict) else None
    if not isinstance(lock, dict) or not lock.get("id"):
        return
    now = _now_utc()
    try:
        current_lock = _read_job(lock["id"])
    except Exception as exc:
        raise DataManagementMigrationLeaseLostError(
            "Migration destination coordinator lease could not be read."
        ) from exc
    if (
        current_lock.get("type") != DATA_MANAGEMENT_MIGRATION_LOCK_TYPE or
        current_lock.get("migration_job_id") != job.get("id") or
        current_lock.get("lock_token") != lock.get("lock_token")
    ):
        raise DataManagementMigrationLeaseLostError(
            "Migration destination coordinator lease was superseded."
        )
    expires_at = _parse_iso_datetime(current_lock.get("expires_at"))
    if expires_at is None or expires_at <= now:
        raise DataManagementMigrationLeaseLostError(
            "Migration destination coordinator lease expired."
        )
    lease_seconds = _get_migration_lock_lease_seconds({
        "data_management_job_lease_seconds": (
            (settings or {}).get("data_management_job_lease_seconds") or
            lock.get("lease_seconds")
        ),
    })
    current_lock["updated_at"] = now.isoformat()
    current_lock["expires_at"] = (
        now + timedelta(seconds=lease_seconds)
    ).isoformat()
    try:
        renewed_lock = cosmos_data_management_jobs_container.replace_item(
            item=current_lock.get("id"),
            body=current_lock,
            etag=current_lock.get("_etag"),
            match_condition=MatchConditions.IfNotModified,
        )
    except Exception as exc:
        if getattr(exc, "status_code", None) in {409, 412}:
            raise DataManagementMigrationLeaseLostError(
                "Migration destination coordinator lease changed during renewal."
            ) from exc
        raise
    lock["expires_at"] = renewed_lock.get("expires_at", current_lock["expires_at"])
    lock["lease_seconds"] = lease_seconds


def _release_migration_destination_lock(job):
    """Release only the destination coordinator lease token owned by this job."""
    lock = job.get("migration_coordinator_lock") if isinstance(job, dict) else None
    if not isinstance(lock, dict) or not lock.get("id"):
        return
    try:
        current_lock = _read_job(lock["id"])
    except Exception:
        return
    if (
        current_lock.get("type") != DATA_MANAGEMENT_MIGRATION_LOCK_TYPE or
        current_lock.get("migration_job_id") != job.get("id") or
        current_lock.get("lock_token") != lock.get("lock_token")
    ):
        return
    try:
        cosmos_data_management_jobs_container.delete_item(
            item=current_lock.get("id"),
            partition_key=current_lock.get("id"),
            etag=current_lock.get("_etag"),
            match_condition=MatchConditions.IfNotModified,
        )
    except Exception:
        return


def _get_backup_source_scope(job=None):
    """Return the source identity shared by full and partial primary-app backups."""
    state = (job or {}).get("backup_state") if isinstance(job, dict) else None
    if isinstance(state, dict) and _safe_text(state.get("source_scope")):
        return _safe_text(state.get("source_scope"))
    return _safe_text((job or {}).get("source_scope"), DATA_MANAGEMENT_BACKUP_SOURCE_SCOPE)


def _get_backup_source_lock_id(source_scope):
    """Create a stable lock id without exposing a source locator in the job id."""
    source_hash = hashlib.sha256(
        _safe_text(source_scope, DATA_MANAGEMENT_BACKUP_SOURCE_SCOPE).encode("utf-8")
    ).hexdigest()[:24]
    return f"{DATA_MANAGEMENT_BACKUP_LOCK_PREFIX}_{source_hash}"


def _get_backup_lock_lease_seconds(settings):
    return _get_data_management_job_lease_seconds(settings)


def _read_active_backup_source_lock(source_scope):
    """Return the active source lock, clearing no state when it is absent or expired."""
    lock_id = _get_backup_source_lock_id(source_scope)
    try:
        lock = _read_job(lock_id)
    except (CosmosResourceNotFoundError, ResourceNotFoundError, KeyError):
        return None
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            return None
        raise
    expires_at = _parse_iso_datetime(lock.get("expires_at"))
    if (
        lock.get("type") != DATA_MANAGEMENT_BACKUP_LOCK_TYPE or
        expires_at is None or
        expires_at <= _now_utc()
    ):
        return None
    return lock


def _has_active_backup_source_lock(job):
    """Return whether any worker still owns the backup source scope."""
    source_scope = _get_backup_source_scope(job)
    try:
        return _read_active_backup_source_lock(source_scope) is not None
    except Exception as exc:
        raise DataManagementBackupLeaseLostError(
            "Backup source lock could not be verified while claiming the job."
        ) from exc


def _acquire_backup_source_lock(job, settings):
    """Acquire the primary source lease before a backup reads or writes artifacts."""
    if not isinstance(job, dict) or job.get("operation") != DATA_MANAGEMENT_OPERATION_BACKUP:
        return None
    source_scope = _get_backup_source_scope(job)
    lock_id = _get_backup_source_lock_id(source_scope)
    now = _now_utc()
    lease_seconds = _get_backup_lock_lease_seconds(settings)
    lock_document = {
        "id": lock_id,
        "type": DATA_MANAGEMENT_BACKUP_LOCK_TYPE,
        "source_scope": source_scope,
        "backup_job_id": job.get("id"),
        "lease_generation": _safe_int(job.get("lease_generation"), default=0, minimum=1),
        "lock_token": str(uuid.uuid4()),
        "acquired_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "lease_seconds": lease_seconds,
        "expires_at": (now + timedelta(seconds=lease_seconds)).isoformat(),
    }
    try:
        cosmos_data_management_jobs_container.create_item(body=lock_document)
    except Exception as exc:
        if getattr(exc, "status_code", None) != 409:
            raise
        existing_lock = _read_job(lock_id)
        expires_at = _parse_iso_datetime(existing_lock.get("expires_at"))
        if (
            existing_lock.get("type") == DATA_MANAGEMENT_BACKUP_LOCK_TYPE and
            expires_at and expires_at > now
        ):
            raise DataManagementBackupOverlapError(
                "Another full or partial backup is active for this source."
            ) from exc
        replacement_lock = dict(existing_lock)
        replacement_lock.update(lock_document)
        try:
            cosmos_data_management_jobs_container.replace_item(
                item=lock_id,
                body=replacement_lock,
                etag=existing_lock.get("_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as replace_exc:
            if getattr(replace_exc, "status_code", None) in {409, 412}:
                raise DataManagementBackupOverlapError(
                    "Another backup acquired this source before the worker could start."
                ) from replace_exc
            raise

    job["backup_source_lock"] = {
        "id": lock_id,
        "source_scope": source_scope,
        "lock_token": lock_document["lock_token"],
        "lease_generation": lock_document["lease_generation"],
        "lease_seconds": lease_seconds,
        "expires_at": lock_document["expires_at"],
    }
    return job["backup_source_lock"]


def _renew_backup_source_lock(job, settings=None):
    """Renew the source lock only when this exact fenced job attempt owns it."""
    lock = job.get("backup_source_lock") if isinstance(job, dict) else None
    if not isinstance(lock, dict) or not lock.get("id"):
        raise DataManagementBackupLeaseLostError("Backup worker has no source lock to renew.")
    now = _now_utc()
    try:
        current_lock = _read_job(lock["id"])
    except Exception as exc:
        raise DataManagementBackupLeaseLostError(
            "Backup source lock could not be read."
        ) from exc
    if (
        current_lock.get("type") != DATA_MANAGEMENT_BACKUP_LOCK_TYPE or
        current_lock.get("backup_job_id") != job.get("id") or
        current_lock.get("lock_token") != lock.get("lock_token") or
        _safe_int(current_lock.get("lease_generation"), default=0) !=
        _safe_int(job.get("lease_generation"), default=0)
    ):
        raise DataManagementBackupLeaseLostError(
            "Backup source lock was superseded by another worker."
        )
    expires_at = _parse_iso_datetime(current_lock.get("expires_at"))
    if expires_at is None or expires_at <= now:
        raise DataManagementBackupLeaseLostError("Backup source lock expired.")
    lease_seconds = _get_backup_lock_lease_seconds({
        "data_management_job_lease_seconds": (
            (settings or {}).get("data_management_job_lease_seconds") or
            lock.get("lease_seconds")
        ),
    })
    current_lock["updated_at"] = now.isoformat()
    current_lock["expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat()
    try:
        renewed_lock = cosmos_data_management_jobs_container.replace_item(
            item=current_lock.get("id"),
            body=current_lock,
            etag=current_lock.get("_etag"),
            match_condition=MatchConditions.IfNotModified,
        )
    except Exception as exc:
        if getattr(exc, "status_code", None) in {409, 412}:
            raise DataManagementBackupLeaseLostError(
                "Backup source lock changed during renewal."
            ) from exc
        raise
    lock["expires_at"] = renewed_lock.get("expires_at", current_lock["expires_at"])
    lock["lease_seconds"] = lease_seconds


def _release_backup_source_lock(job):
    """Release only the source lock token owned by this backup attempt."""
    lock = job.get("backup_source_lock") if isinstance(job, dict) else None
    if not isinstance(lock, dict) or not lock.get("id"):
        return
    try:
        current_lock = _read_job(lock["id"])
    except Exception:
        return
    if (
        current_lock.get("type") != DATA_MANAGEMENT_BACKUP_LOCK_TYPE or
        current_lock.get("backup_job_id") != job.get("id") or
        current_lock.get("lock_token") != lock.get("lock_token")
    ):
        return
    try:
        cosmos_data_management_jobs_container.delete_item(
            item=current_lock.get("id"),
            partition_key=current_lock.get("id"),
            etag=current_lock.get("_etag"),
            match_condition=MatchConditions.IfNotModified,
        )
    except Exception:
        return


def _assert_backup_job_lease(job, allow_cancel_requested=False):
    """Fence a stale or canceled backup worker before its next durable boundary."""
    if not isinstance(job, dict) or job.get("operation") != DATA_MANAGEMENT_OPERATION_BACKUP:
        return
    lease_holder_id = _safe_text(job.get("lease_holder_id"))
    if not lease_holder_id:
        raise DataManagementBackupLeaseLostError("Backup worker has no durable job lease.")
    try:
        persisted_job = _read_job(job.get("id"))
    except Exception as exc:
        raise DataManagementBackupLeaseLostError(
            "Backup worker could not verify its durable job lease."
        ) from exc
    if persisted_job.get("cancel_requested_at") and not allow_cancel_requested:
        raise DataManagementBackupCanceledError(
            "Backup cancellation was requested by an administrator."
        )
    persisted_expiry = _parse_iso_datetime(persisted_job.get("lease_expires_at"))
    if (
        persisted_job.get("status") != DATA_MANAGEMENT_STATUS_RUNNING or
        _safe_text(persisted_job.get("lease_holder_id")) != lease_holder_id or
        _safe_int(persisted_job.get("lease_generation"), default=0) !=
        _safe_int(job.get("lease_generation"), default=0) or
        persisted_expiry is None or
        persisted_expiry <= _now_utc()
    ):
        raise DataManagementBackupLeaseLostError(
            "Backup worker lease was superseded or expired."
        )
    if persisted_job.get("_etag"):
        job["_etag"] = persisted_job.get("_etag")
    _renew_backup_source_lock(job)


def _assert_data_management_job_lease(job, allow_cancel_requested=False):
    """Dispatch durable lease checks to the owning Data Management operation."""
    if not isinstance(job, dict):
        return
    if job.get("operation") == DATA_MANAGEMENT_OPERATION_MIGRATION:
        _assert_migration_job_lease(job, allow_cancel_requested=allow_cancel_requested)
    elif job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP:
        _assert_backup_job_lease(job, allow_cancel_requested=allow_cancel_requested)


def _run_backup_transfer_with_heartbeat(job, settings, message, transfer):
    """Renew the fenced backup lease while one blocking storage call is in flight."""
    stop_event = Event()
    failure_holder = {}

    def renew():
        while not stop_event.wait(DATA_MANAGEMENT_BACKUP_HEARTBEAT_INTERVAL_SECONDS):
            try:
                _persist_backup_heartbeat(job, settings, message)
            except Exception as exc:
                failure_holder["error"] = exc
                stop_event.set()
                return

    heartbeat_thread = Thread(target=renew, daemon=True)
    heartbeat_thread.start()
    try:
        result = transfer()
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=5.0)
    if failure_holder.get("error"):
        raise failure_holder["error"]
    _assert_backup_job_lease(job)
    return result


def _assert_migration_job_lease(job, allow_cancel_requested=False):
    """Stop a stale migration worker before it schedules another remote action."""
    if not isinstance(job, dict) or job.get("operation") != DATA_MANAGEMENT_OPERATION_MIGRATION:
        return
    lease_holder_id = _safe_text(job.get("lease_holder_id"))
    if not lease_holder_id:
        return
    try:
        persisted_job = _read_job(job.get("id"))
    except Exception as exc:
        raise DataManagementMigrationLeaseLostError(
            "Migration worker could not verify its durable job lease."
        ) from exc

    persisted_expiry = _parse_iso_datetime(persisted_job.get("lease_expires_at"))
    if (
        persisted_job.get("status") != DATA_MANAGEMENT_STATUS_RUNNING or
        _safe_text(persisted_job.get("lease_holder_id")) != lease_holder_id or
        persisted_expiry is None or
        persisted_expiry <= _now_utc()
    ):
        raise DataManagementMigrationLeaseLostError(
            "Migration worker lease was superseded or expired."
        )
    if persisted_job.get("cancel_requested_at") and not allow_cancel_requested:
        raise DataManagementMigrationCanceledError(
            "Migration cancellation was requested by an administrator."
        )
    if persisted_job.get("_etag"):
        job["_etag"] = persisted_job.get("_etag")
    _renew_migration_destination_lock(job)
    _renew_target_migration_coordinator(job, None)


def _replace_job(job):
    return cosmos_data_management_jobs_container.replace_item(
        item=job.get("id"),
        body=job,
        etag=job.get("_etag"),
        match_condition=MatchConditions.IfNotModified,
    )


def _sanitize_activity_value(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        sanitized = {}
        for key, nested_value in value.items():
            normalized_key = str(key)
            normalized_key_lower = normalized_key.lower()
            safe_key_metadata_fields = {"partition_key_path", "encryption_key_storage"}
            is_sensitive_field = (
                normalized_key_lower not in safe_key_metadata_fields
                and (
                    any(secret_marker in normalized_key_lower for secret_marker in ("secret", "password", "connection_string", "credential", "token"))
                    or normalized_key_lower.endswith("_key")
                    or normalized_key_lower in {"key", "account_key", "target_cosmos_key"}
                )
            )
            if is_sensitive_field:
                sanitized[normalized_key] = DATA_MANAGEMENT_REDACTED_VALUE
            else:
                sanitized[normalized_key] = _sanitize_activity_value(nested_value)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_activity_value(item) for item in value]
    return str(value)


def _log_data_management_activity(job, action, status, message, details=None):
    if not isinstance(job, dict):
        return

    now = _now_iso()
    job_id = _safe_text(job.get("id"))
    activity_record = {
        "id": str(uuid.uuid4()),
        "user_id": _safe_text(job.get("requested_by"), "system") or "system",
        "activity_type": "data_management",
        "timestamp": now,
        "created_at": now,
        "action": _safe_text(action),
        "description": _safe_text(message),
        "workspace_type": "admin",
        "workspace_context": {
            "action": _safe_text(action),
            "job_id": job_id,
            "operation": _safe_text(job.get("operation")),
            "backup_type": _safe_text(job.get("backup_type")),
        },
        "additional_context": {
            "job_id": job_id,
            "operation": _safe_text(job.get("operation")),
            "backup_type": _safe_text(job.get("backup_type")),
            "status": _safe_text(status),
            "scheduled": bool(job.get("scheduled")),
            "progress": _sanitize_activity_value(job.get("progress") if isinstance(job.get("progress"), dict) else {}),
            "details": _sanitize_activity_value(details if isinstance(details, dict) else {}),
        },
    }
    if job.get("requested_by_email"):
        activity_record["admin_email"] = _safe_text(job.get("requested_by_email"))
        activity_record["admin"] = {
            "user_id": activity_record["user_id"],
            "email": _safe_text(job.get("requested_by_email")),
        }

    try:
        app_config.cosmos_activity_logs_container.create_item(body=activity_record)
    except Exception as exc:
        log_event(
            "[DataManagement] Failed to write job activity record.",
            {"job_id": job_id, "action": action, "error": str(exc)},
            level=logging.WARNING,
        )


def _normalize_data_management_backup_plan(settings, backup_type, options=None, source_cutoff_at=None):
    """Build the secret-free immutable plan used by one full or partial backup."""
    normalized_backup_type = _safe_text(backup_type)
    if normalized_backup_type not in DATA_MANAGEMENT_BACKUP_TYPES:
        raise DataManagementSettingsValidationError("Backup jobs must be full or partial.")
    source_options = options if isinstance(options, dict) else {}
    source_cutoff = _safe_text(source_cutoff_at) or _now_iso()
    parsed_cutoff = _parse_iso_datetime(source_cutoff) or _now_utc()
    cosmos_cutoff_epoch = int(parsed_cutoff.timestamp()) - 1
    last_successful_cutoff = (
        _safe_text((settings or {}).get("last_partial_backup_completed_at")) or
        _safe_text((settings or {}).get("last_full_backup_completed_at"))
    )
    inclusion_defaults = {
        "include_cosmos": _safe_bool((settings or {}).get("include_cosmos"), True),
        "include_ai_search": _safe_bool((settings or {}).get("include_ai_search"), True),
        "include_source_blobs": _safe_bool((settings or {}).get("include_source_blobs"), True),
    }
    inclusions = {
        field_name: _safe_bool(source_options.get(field_name), default_value)
        if field_name in source_options else default_value
        for field_name, default_value in inclusion_defaults.items()
    }
    partial_backup = normalized_backup_type == DATA_MANAGEMENT_BACKUP_PARTIAL
    encryption_key_storage = _safe_text((settings or {}).get("encryption_key_storage"))
    encryption_reference = (
        _resolve_backup_encryption_reference(settings)
        if encryption_key_storage == "key_vault" else
        ""
    )
    return {
        "backup_type": normalized_backup_type,
        "source_scope": DATA_MANAGEMENT_BACKUP_SOURCE_SCOPE,
        "source_cutoff_at": source_cutoff,
        "cosmos_source_cutoff_epoch": cosmos_cutoff_epoch,
        "source_lower_bound_at": last_successful_cutoff if partial_backup else None,
        "differential_mode": "latest_item_state" if partial_backup else "full_snapshot",
        "source_cutoff_semantics": {
            "upper_bound": "inclusive",
            "cosmos_upper_bound": "strictly_before_captured_second",
            "lower_bound": "inclusive" if partial_backup and last_successful_cutoff else "not_applicable",
            "deletion_policy": "none",
            "deleted_source_behavior": "non_destructive_not_recorded_as_delete",
        },
        "include_cosmos": inclusions["include_cosmos"],
        "include_ai_search": inclusions["include_ai_search"],
        "include_source_blobs": inclusions["include_source_blobs"],
        "backup_storage_container_name": _safe_text(
            (settings or {}).get("backup_storage_container_name"),
            "simplechat-backups",
        ),
        "backup_storage_path_prefix": _safe_text(
            (settings or {}).get("backup_storage_path_prefix"),
            "simplechat-backups",
        ).strip("/"),
        "storage_identity": _build_backup_storage_identity(settings),
        "encryption_enabled": _safe_bool((settings or {}).get("encryption_enabled"), True),
        "encryption_key_storage": encryption_key_storage,
        "encryption_key_reference": encryption_reference,
        "encryption_key_fingerprint": _build_backup_encryption_key_fingerprint(
            settings,
            key_reference=(
                encryption_reference or
                _safe_text((settings or {}).get("encryption_key_reference"))
            ),
        ),
        "cosmos_execution": {
            "max_parallel_operations": _get_backup_parallel_operations(settings),
            "retry_count": _get_backup_retry_count(settings),
            "temporary_source_ru_enabled": _safe_bool(
                (settings or {}).get("backup_temporary_source_ru_enabled"),
                False,
            ),
            "temporary_source_ru": _get_backup_temporary_source_ru(settings),
            "capacity_failure_policy": _get_backup_capacity_failure_policy(settings),
        },
        "resource_contract": ["cosmos", "ai_search", "source_blobs"],
    }


def _build_backup_storage_identity(settings):
    """Hash storage routing without persisting a connection string or credential."""
    auth_type = _safe_text(
        (settings or {}).get("backup_storage_authentication_type"),
        "managed_identity",
    )
    connection_string = _safe_text((settings or {}).get("backup_storage_connection_string"))
    endpoint = _safe_text((settings or {}).get("backup_storage_blob_endpoint")).rstrip("/")
    identity_source = connection_string if auth_type == "connection_string" else endpoint
    return build_backup_configuration_fingerprint({
        "authentication_type": auth_type,
        "identity_hash": hashlib.sha256(identity_source.encode("utf-8")).hexdigest(),
    })


def _build_backup_encryption_key_fingerprint(settings, key_reference=None):
    """Retain encryption-key continuity without retaining a key reference in the plan."""
    return hashlib.sha256(
        _safe_text(
            key_reference if key_reference is not None else
            (settings or {}).get("encryption_key_reference")
        ).encode("utf-8")
    ).hexdigest()


def _resolve_backup_encryption_reference(settings):
    """Pin Key Vault-backed backups to one secret version for all retry attempts."""
    key_reference = _safe_text((settings or {}).get("encryption_key_reference"))
    if not key_reference or _safe_text((settings or {}).get("encryption_key_storage")) != "key_vault":
        return key_reference
    try:
        from functions_keyvault import resolve_secret_reference_version

        resolved_reference = _safe_text(resolve_secret_reference_version(key_reference))
        reference_parts = [
            part for part in resolved_reference.split("/")
            if part
        ]
        if (
            not resolved_reference.lower().startswith("https://") or
            len(reference_parts) < 4 or
            "secrets" not in reference_parts
        ):
            raise ValueError("Key Vault did not return a version-pinned secret reference.")
        return resolved_reference
    except Exception as exc:
        log_event(
            "[DataManagement] Backup encryption version could not be resolved.",
            {"error": str(exc)},
            level=logging.ERROR,
        )
        raise DataManagementSettingsValidationError(
            "Backup encryption key version could not be resolved. Queue the backup after Key Vault access is restored."
        ) from exc


def _build_backup_lineage_id(backup_plan):
    """Keep latest-only state isolated when backup artifacts change destination or key."""
    plan = backup_plan if isinstance(backup_plan, dict) else {}
    return build_backup_configuration_fingerprint({
        "storage_identity": _safe_text(plan.get("storage_identity")),
        "backup_storage_container_name": _safe_text(plan.get("backup_storage_container_name")),
        "backup_storage_path_prefix": _safe_text(plan.get("backup_storage_path_prefix")).strip("/"),
        "encryption_enabled": _safe_bool(plan.get("encryption_enabled")),
        "encryption_key_fingerprint": _safe_text(plan.get("encryption_key_fingerprint")),
    })


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
    backup_plan = None
    backup_state = None
    source_scope = None
    source_cutoff_at = None
    normalized_options = options if isinstance(options, dict) else {}
    if normalized_operation == DATA_MANAGEMENT_OPERATION_BACKUP:
        settings = get_data_management_settings()
        if settings.get("encryption_enabled") and not settings.get("encryption_key_reference"):
            generate_data_management_encryption_key()
            settings = get_data_management_settings()
        backup_plan = _normalize_data_management_backup_plan(
            settings,
            normalized_backup_type,
            normalized_options,
            source_cutoff_at=now,
        )
        source_scope = backup_plan["source_scope"]
        source_cutoff_at = backup_plan["source_cutoff_at"]
        backup_state = initialize_backup_state(
            None,
            job_id,
            backup_plan,
            source_scope,
            source_cutoff_at,
        )
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
        "cancel_requested_at": None,
        "cancel_requested_by": None,
        "cancel_requested_by_email": None,
        "cancel_reason": None,
        "requested_by": _safe_text(requested_by),
        "requested_by_email": _safe_text(requested_by_email),
        "scheduled": bool(scheduled),
        "occurrence_id": occurrence_id,
        "options": normalized_options,
        "progress": {
            "total_steps": 0,
            "completed_steps": 0,
            "current_step": None,
            "percent_complete": 0,
        },
        "lease_holder_id": None,
        "lease_expires_at": None,
        "lease_generation": 0,
        "warnings": [],
        "source_scope": source_scope,
        "source_cutoff_at": source_cutoff_at,
        "backup_plan": backup_plan,
        "backup_state": backup_state,
    }

    try:
        saved_job = cosmos_data_management_jobs_container.create_item(body=job)
        _record_data_management_job_event(
            saved_job.get("id"),
            "queued",
            saved_job,
            status=DATA_MANAGEMENT_STATUS_QUEUED,
            message="Queued data management job",
            details={"operation": normalized_operation, "backup_type": normalized_backup_type, "scheduled": bool(scheduled)},
        )
        return saved_job
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


def get_recoverable_data_management_jobs(
    current_time=None,
    limit=DATA_MANAGEMENT_DEFAULT_RECOVERY_JOB_LIMIT,
    operations=None,
):
    """Return queued or stale backup and migration jobs that can be resubmitted."""
    safe_limit = _safe_int(
        limit,
        default=DATA_MANAGEMENT_DEFAULT_RECOVERY_JOB_LIMIT,
        minimum=1,
        maximum=100,
    )
    now = current_time if isinstance(current_time, datetime) else _now_utc()
    query = (
        "SELECT * FROM c WHERE c.type = @type "
        "AND (c.status = @queued OR c.status = @running) ORDER BY c.updated_at ASC"
    )
    parameters = [
        {"name": "@type", "value": DATA_MANAGEMENT_JOB_TYPE},
        {"name": "@queued", "value": DATA_MANAGEMENT_STATUS_QUEUED},
        {"name": "@running", "value": DATA_MANAGEMENT_STATUS_RUNNING},
    ]
    candidates = list(cosmos_data_management_jobs_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
        max_item_count=safe_limit,
    ))[:safe_limit]
    recoverable_jobs = []
    allowed_operations = {
        _safe_text(operation)
        for operation in (operations or {
            DATA_MANAGEMENT_OPERATION_BACKUP,
            DATA_MANAGEMENT_OPERATION_MIGRATION,
        })
    }
    for job in candidates:
        operation = _safe_text(job.get("operation"))
        if operation not in allowed_operations:
            continue
        if job.get("status") == DATA_MANAGEMENT_STATUS_QUEUED and job.get("cancel_requested_at"):
            continue
        status = job.get("status")
        queued_since = _parse_iso_datetime(job.get("updated_at") or job.get("created_at"))
        last_recovery = _parse_iso_datetime(job.get("last_recovery_submitted_at"))
        resubmit_due = (
            last_recovery is None or
            last_recovery <= now - timedelta(seconds=DATA_MANAGEMENT_RECOVERY_RESUBMIT_DELAY_SECONDS)
        )
        if status == DATA_MANAGEMENT_STATUS_QUEUED:
            is_queued_long_enough = (
                queued_since is None or
                queued_since <= now - timedelta(seconds=DATA_MANAGEMENT_RECOVERY_QUEUE_DELAY_SECONDS)
            )
            if is_queued_long_enough and resubmit_due:
                recoverable_jobs.append({"job": job, "reason": "queued_recovery"})
        elif status == DATA_MANAGEMENT_STATUS_RUNNING and _is_stale_job(job) and resubmit_due:
            recoverable_jobs.append({"job": job, "reason": "stale_recovery"})
    return recoverable_jobs


def get_recoverable_data_management_migration_jobs(
    current_time=None,
    limit=DATA_MANAGEMENT_DEFAULT_RECOVERY_JOB_LIMIT,
):
    """Retain migration-only recovery discovery for existing callers and tests."""
    return [
        recovery
        for recovery in get_recoverable_data_management_jobs(
            current_time=current_time,
            limit=limit,
            operations={DATA_MANAGEMENT_OPERATION_MIGRATION},
        )
    ]


def recover_data_management_jobs(app=None, settings=None, current_time=None, operations=None):
    """Resubmit recoverable backup and migration jobs through the executor, never inline."""
    now = current_time if isinstance(current_time, datetime) else _now_utc()
    recovery_results = []
    for recovery in get_recoverable_data_management_jobs(
        current_time=now,
        operations=operations,
    ):
        job = recovery["job"]
        reason = recovery["reason"]
        operation = _safe_text(job.get("operation"))
        operation_label = "backup" if operation == DATA_MANAGEMENT_OPERATION_BACKUP else "migration"
        job.update({
            "last_recovery_submitted_at": now.isoformat(),
            "recovery_attempt_count": _safe_int(job.get("recovery_attempt_count"), default=0, minimum=0) + 1,
            "updated_at": now.isoformat(),
            "last_message": (
                f"Detected a stale {operation_label} worker; scheduling durable recovery."
                if reason == "stale_recovery" else
                f"Detected a delayed queued {operation_label}; scheduling executor recovery."
            ),
        })
        saved_job = _save_data_management_job(job)
        _record_data_management_job_event(
            saved_job.get("id"),
            f"{operation_label}-stall-detected" if reason == "stale_recovery" else f"{operation_label}-queued-recovery",
            saved_job,
            status=saved_job.get("status"),
            message=saved_job.get("last_message"),
            details={
                "recovery_attempt_count": saved_job.get("recovery_attempt_count"),
                "cancel_requested": bool(saved_job.get("cancel_requested_at")),
            },
        )
        submitted = submit_data_management_job(app, saved_job.get("id"))
        if submitted:
            _record_data_management_job_event(
                saved_job.get("id"),
                f"{operation_label}-recovery-submitted",
                saved_job,
                status=saved_job.get("status"),
                message=f"Submitted {operation_label} recovery to the executor.",
                details={"reason": reason},
            )
        else:
            log_event(
                "[DataManagement] Durable job recovery could not submit to the executor.",
                {"job_id": saved_job.get("id"), "reason": reason, "operation": operation},
                level=logging.WARNING,
            )
        recovery_results.append({
            "job_id": saved_job.get("id"),
            "operation": operation,
            "reason": reason,
            "submitted": submitted,
        })
    return recovery_results


def recover_data_management_migration_jobs(app=None, settings=None, current_time=None):
    """Retain the migration-only public helper while using the shared recovery path."""
    results = recover_data_management_jobs(
        app=app,
        settings=settings,
        current_time=current_time,
        operations={DATA_MANAGEMENT_OPERATION_MIGRATION},
    )
    return results


def _sanitize_data_management_migration_state_for_admin(state):
    if not isinstance(state, dict):
        return {}
    resources = {}
    for resource_name, resource in (state.get("resources") or {}).items():
        if not isinstance(resource, dict):
            continue
        resources[_safe_text(resource_name)] = {
            "status": resource.get("status"),
            "attempts": resource.get("attempts"),
            "started_at": resource.get("started_at"),
            "attempt_started_at": resource.get("attempt_started_at"),
            "updated_at": resource.get("updated_at"),
            "completed_at": resource.get("completed_at"),
            "last_error": _safe_text(resource.get("last_error"))[:500],
            "progress": _sanitize_activity_value(resource.get("progress") if isinstance(resource.get("progress"), dict) else {}),
            "result": _sanitize_activity_value(resource.get("result") if isinstance(resource.get("result"), dict) else {}),
        }
    capacity = state.get("capacity") if isinstance(state.get("capacity"), dict) else {}
    return {
        "schema_version": state.get("schema_version"),
        "migration_id": state.get("migration_id"),
        "status": state.get("status"),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "completed_at": state.get("completed_at"),
        "source_cutoff_at": state.get("source_cutoff_at"),
        "last_progress_at": state.get("last_progress_at"),
        "resume_count": state.get("resume_count"),
        "last_error": _safe_text(state.get("last_error"))[:500],
        "totals": _sanitize_activity_value(state.get("totals") if isinstance(state.get("totals"), dict) else {}),
        "preflight": _sanitize_activity_value(state.get("preflight") if isinstance(state.get("preflight"), dict) else {}),
        "capacity": {
            "status": capacity.get("status"),
            "restore_pending": bool(capacity.get("restore_pending")),
            "target_ru": capacity.get("target_ru"),
            "started_at": capacity.get("started_at"),
            "completed_at": capacity.get("completed_at"),
            "restored_at": capacity.get("restored_at"),
            "restore_warnings": _sanitize_activity_value(
                capacity.get("restore_warnings") if isinstance(capacity.get("restore_warnings"), list) else []
            ),
            "targets": _sanitize_activity_value(capacity.get("targets") if isinstance(capacity.get("targets"), list) else []),
        },
        "resources": resources,
    }


def _sanitize_data_management_backup_text(value):
    """Bound operational text and remove URI query strings that could contain SAS tokens."""
    text = _safe_text(value)[:500]
    if "?" in text and ("sig=" in text.lower() or "se=" in text.lower()):
        text = text.split("?", 1)[0] + "?[redacted]"
    secret_markers = (
        "accountkey=",
        "sharedaccesssignature=",
        "connectionstring=",
        "password=",
        "secret=",
        "token=",
        "apikey=",
    )
    if any(marker in text.lower() for marker in secret_markers):
        return "[redacted operational detail]"
    return text


def _sanitize_data_management_backup_state_for_admin(state):
    """Expose durable backup progress without source content, locators, or credentials."""
    if not isinstance(state, dict):
        return {}

    def sanitize_metric_number(value):
        try:
            return round(max(0.0, float(value)), 3)
        except (TypeError, ValueError):
            return 0.0

    resources = {}
    for resource_name, resource in (state.get("resources") or {}).items():
        if not isinstance(resource, dict):
            continue
        progress = resource.get("progress") if isinstance(resource.get("progress"), dict) else {}
        checkpoint = resource.get("checkpoint") if isinstance(resource.get("checkpoint"), dict) else {}
        result = resource.get("result") if isinstance(resource.get("result"), dict) else {}
        resources[_safe_text(resource_name)] = {
            "status": resource.get("status"),
            "phase": resource.get("phase"),
            "attempts": _safe_int(resource.get("attempts"), default=0, minimum=0),
            "started_at": resource.get("started_at"),
            "attempt_started_at": resource.get("attempt_started_at"),
            "updated_at": resource.get("updated_at"),
            "completed_at": resource.get("completed_at"),
            "last_error": _sanitize_data_management_backup_text(resource.get("last_error")),
            "progress": {
                field_name: _safe_int(progress.get(field_name), default=0, minimum=0)
                for field_name in (
                    "source_read_count",
                    "processed_count",
                    "item_count",
                    "blob_count",
                    "skipped_count",
                    "failed_count",
                    "bytes",
                    "checkpoint_count",
                    "retry_attempt_count",
                    "throttle_count",
                    "parallel_operations",
                    "active_parallel_operations",
                    "source_page_count",
                )
                if field_name in progress
            },
            "telemetry": {
                field_name: sanitize_metric_number(progress.get(field_name))
                for field_name in (
                    "request_units",
                    "elapsed_seconds",
                    "records_per_second",
                    "bytes_per_second",
                    "request_units_per_second",
                )
                if field_name in progress
            },
            "current_container": _safe_text(progress.get("current_container")),
            "checkpoint": {
                "next_batch_number": _safe_int(checkpoint.get("next_batch_number"), default=0, minimum=0),
                "completed_batch_count": _safe_int(checkpoint.get("completed_batch_count"), default=0, minimum=0),
            },
            "result": _summarize_backup_artifact(result) or {},
        }
    attempt_history = []
    for attempt in (state.get("attempt_history") or [])[-DATA_MANAGEMENT_BACKUP_MAX_RECENT_CHECKPOINTS:]:
        if not isinstance(attempt, dict):
            continue
        attempt_history.append({
            "attempt_id": _safe_text(attempt.get("attempt_id")),
            "lease_generation": _safe_int(attempt.get("lease_generation"), default=0, minimum=0),
            "started_at": attempt.get("started_at"),
            "completed_at": attempt.get("completed_at"),
            "outcome": _safe_text(attempt.get("outcome")),
        })

    def sanitize_item_summary(summary):
        safe_summary = _sanitize_activity_value(summary if isinstance(summary, dict) else {})
        for field_name in ("failure_summary", "skip_summary", "warning", "error"):
            if field_name in safe_summary:
                safe_summary[field_name] = _sanitize_data_management_backup_text(
                    safe_summary[field_name]
                )
        return safe_summary

    source_capacity = (
        state.get("source_capacity")
        if isinstance(state.get("source_capacity"), dict) else {}
    )
    public_source_capacity = {
        "status": _safe_text(source_capacity.get("status")),
        "restore_pending": bool(source_capacity.get("restore_pending")),
        "failure_policy": _safe_text(source_capacity.get("failure_policy")),
        "target_ru": _safe_int(source_capacity.get("target_ru"), default=0, minimum=0),
        "started_at": source_capacity.get("started_at"),
        "completed_at": source_capacity.get("completed_at"),
        "restored_at": source_capacity.get("restored_at"),
        "restore_warnings": [
            _sanitize_data_management_backup_text(warning)
            for warning in (source_capacity.get("restore_warnings") or [])
        ][-DATA_MANAGEMENT_BACKUP_MAX_PUBLIC_ITEM_SUMMARIES:],
        "topology": _sanitize_activity_value(
            source_capacity.get("topology")
            if isinstance(source_capacity.get("topology"), dict) else {}
        ),
        "targets": [
            {
                "scope": _safe_text(target.get("scope")),
                "container_name": _safe_text(target.get("container_name")),
                "mode": _safe_text(target.get("mode")),
                "original_ru": _safe_int(target.get("original_ru"), default=0, minimum=0),
                "target_ru": _safe_int(target.get("target_ru"), default=0, minimum=0),
                "boosted_to_ru": _safe_int(target.get("boosted_to_ru"), default=0, minimum=0),
                "changed": bool(target.get("changed")),
                "restore_status": _safe_text(target.get("restore_status")),
            }
            for target in (source_capacity.get("targets") or [])
            if isinstance(target, dict)
        ],
    }
    totals = state.get("totals") if isinstance(state.get("totals"), dict) else {}
    telemetry = state.get("telemetry") if isinstance(state.get("telemetry"), dict) else {}

    return {
        "schema_version": state.get("schema_version"),
        "backup_id": state.get("backup_id"),
        "status": state.get("status"),
        "phase": _sanitize_data_management_backup_text(state.get("phase")),
        "source_scope": _safe_text(state.get("source_scope")),
        "source_cutoff_at": state.get("source_cutoff_at"),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "completed_at": state.get("completed_at"),
        "last_progress_at": state.get("last_progress_at"),
        "resume_count": _safe_int(state.get("resume_count"), default=0, minimum=0),
        "totals": {
            field_name: _safe_int(totals.get(field_name), default=0, minimum=0)
            for field_name in (
                "processed_count",
                "exported_count",
                "skipped_count",
                "failed_count",
                "bytes",
                "checkpoint_count",
                "retry_attempt_count",
                "throttle_count",
            )
        } | {
            field_name: sanitize_metric_number(totals.get(field_name))
            for field_name in (
                "request_units",
                "elapsed_seconds",
                "records_per_second",
                "request_units_per_second",
            )
        },
        "telemetry": {
            "current_container": _safe_text(telemetry.get("current_container")),
            "checkpoint_position": _safe_int(telemetry.get("checkpoint_position"), default=0, minimum=0),
            "records_processed": _safe_int(telemetry.get("records_processed"), default=0, minimum=0),
            "bytes": _safe_int(telemetry.get("bytes"), default=0, minimum=0),
            "request_units": sanitize_metric_number(telemetry.get("request_units")),
            "retries": _safe_int(telemetry.get("retries"), default=0, minimum=0),
            "throttles": _safe_int(telemetry.get("throttles"), default=0, minimum=0),
            "elapsed_seconds": sanitize_metric_number(telemetry.get("elapsed_seconds")),
            "records_per_second": sanitize_metric_number(telemetry.get("records_per_second")),
            "request_units_per_second": sanitize_metric_number(telemetry.get("request_units_per_second")),
        },
        "source_capacity": public_source_capacity,
        "warnings": [
            _sanitize_data_management_backup_text(warning)
            for warning in (state.get("warnings") or [])[-DATA_MANAGEMENT_BACKUP_MAX_PUBLIC_ITEM_SUMMARIES:]
        ],
        "failed_items": [
            sanitize_item_summary(summary)
            for summary in (state.get("failed_items") or [])[-DATA_MANAGEMENT_BACKUP_MAX_PUBLIC_ITEM_SUMMARIES:]
            if isinstance(summary, dict)
        ],
        "skipped_items": [
            sanitize_item_summary(summary)
            for summary in (state.get("skipped_items") or [])[-DATA_MANAGEMENT_BACKUP_MAX_PUBLIC_ITEM_SUMMARIES:]
            if isinstance(summary, dict)
        ],
        "attempt_history": attempt_history,
        "resources": resources,
    }


def sanitize_data_management_job_for_admin(job):
    if not isinstance(job, dict):
        return None
    result = _sanitize_activity_value(job.get("result") if isinstance(job.get("result"), dict) else {})
    if isinstance(result, dict) and "migration_state" in result:
        result["migration_state"] = _sanitize_data_management_migration_state_for_admin(
            job.get("migration_state")
        )
    if isinstance(result, dict) and job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP:
        if isinstance(result.get("artifacts"), list):
            result["artifacts"] = summarize_backup_artifacts(result.get("artifacts"))
        if isinstance(result.get("warnings"), list):
            result["warnings"] = [
                _sanitize_data_management_backup_text(warning)
                for warning in result.get("warnings", [])[-DATA_MANAGEMENT_BACKUP_MAX_PUBLIC_ITEM_SUMMARIES:]
            ]
        if "backup_state" in result:
            result["backup_state"] = _sanitize_data_management_backup_state_for_admin(
                job.get("backup_state")
            )
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
        "last_progress_at": job.get("last_progress_at"),
        "last_message": _sanitize_data_management_backup_text(job.get("last_message")),
        "last_error": _sanitize_data_management_backup_text(job.get("last_error")),
        "cancel_requested_at": job.get("cancel_requested_at"),
        "requested_by_email": job.get("requested_by_email"),
        "scheduled": bool(job.get("scheduled")),
        "progress": job.get("progress") if isinstance(job.get("progress"), dict) else {},
        "warnings": [
            _sanitize_data_management_backup_text(warning)
            for warning in (job.get("warnings") or [])[-DATA_MANAGEMENT_BACKUP_MAX_PUBLIC_ITEM_SUMMARIES:]
        ],
        "result": result,
        "migration_state": _sanitize_data_management_migration_state_for_admin(job.get("migration_state")),
        "backup_state": _sanitize_data_management_backup_state_for_admin(job.get("backup_state")),
        "can_retry": bool(
            job.get("operation") in {
                DATA_MANAGEMENT_OPERATION_MIGRATION,
                DATA_MANAGEMENT_OPERATION_BACKUP,
            } and
            (
                job.get("status") in {DATA_MANAGEMENT_STATUS_FAILED, DATA_MANAGEMENT_STATUS_CANCELED} or
                (job.get("status") == DATA_MANAGEMENT_STATUS_RUNNING and _is_stale_job(job)) or
                (
                    job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP and
                    job.get("status") == DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS and
                    any(
                        isinstance(resource, dict) and
                        resource.get("status") == BACKUP_RESOURCE_STATUS_FAILED
                        for resource in ((job.get("backup_state") or {}).get("resources") or {}).values()
                    )
                )
            )
        ),
        "can_cancel": bool(
            job.get("operation") in {
                DATA_MANAGEMENT_OPERATION_MIGRATION,
                DATA_MANAGEMENT_OPERATION_BACKUP,
            } and
            job.get("status") in {DATA_MANAGEMENT_STATUS_QUEUED, DATA_MANAGEMENT_STATUS_RUNNING} and
            not job.get("cancel_requested_at")
        ),
    }


def sanitize_data_management_job_item_for_admin(item):
    if not isinstance(item, dict):
        return None
    return {
        "id": item.get("id"),
        "job_id": item.get("job_id"),
        "step_name": item.get("step_name"),
        "status": item.get("status"),
        "message": _sanitize_data_management_job_item_text(item.get("message")),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "details": _sanitize_data_management_job_item_details(item.get("details")),
    }


def get_data_management_job(job_id):
    safe_job_id = _safe_text(job_id)
    if not safe_job_id:
        return None
    try:
        job = _read_job(safe_job_id)
    except CosmosResourceNotFoundError:
        return None
    return job if job.get("type") == DATA_MANAGEMENT_JOB_TYPE else None


def request_data_management_job_cancellation(
    job_id,
    requested_by=None,
    requested_by_email=None,
    reason="",
):
    """Request cooperative cancellation without invalidating durable checkpoints."""
    job = get_data_management_job(job_id)
    if not job:
        raise DataManagementSettingsValidationError("Data Management job was not found.")
    operation = _safe_text(job.get("operation"))
    if operation not in {DATA_MANAGEMENT_OPERATION_MIGRATION, DATA_MANAGEMENT_OPERATION_BACKUP}:
        raise DataManagementSettingsValidationError("Only queued or running backup and migration jobs can be canceled.")
    if job.get("status") == DATA_MANAGEMENT_STATUS_CANCELED:
        return job
    if job.get("status") in DATA_MANAGEMENT_TERMINAL_STATUSES:
        raise DataManagementSettingsValidationError("Only queued or running backup and migration jobs can be canceled.")

    now = _now_iso()
    safe_reason = _safe_text(reason)[:500]
    migration_state = job.get("migration_state")
    if isinstance(migration_state, dict):
        migration_state.update({
            "cancel_requested_at": now,
            "cancel_requested_by": _safe_text(requested_by),
            "cancel_reason": safe_reason,
            "updated_at": now,
        })
    backup_state = job.get("backup_state")
    if isinstance(backup_state, dict):
        backup_state.update({
            "cancel_requested_at": now,
            "cancel_requested_by": _safe_text(requested_by),
            "cancel_reason": safe_reason,
            "updated_at": now,
        })

    job.update({
        "cancel_requested_at": now,
        "cancel_requested_by": _safe_text(requested_by),
        "cancel_requested_by_email": _safe_text(requested_by_email),
        "cancel_reason": safe_reason,
        "updated_at": now,
        "last_message": "Migration cancellation requested. The worker will stop at its next durable checkpoint.",
        "migration_state": migration_state,
        "backup_state": backup_state,
    })
    noun = "Backup" if operation == DATA_MANAGEMENT_OPERATION_BACKUP else "Migration"
    if job.get("status") == DATA_MANAGEMENT_STATUS_QUEUED:
        job.update({
            "status": DATA_MANAGEMENT_STATUS_CANCELED,
            "completed_at": now,
            "last_heartbeat_at": now,
            "last_message": "Queued migration canceled before execution started.",
            "lease_holder_id": None,
            "lease_expires_at": None,
        })
        if isinstance(migration_state, dict):
            migration_state.update({
                "status": DATA_MANAGEMENT_STATUS_CANCELED,
                "completed_at": now,
                "updated_at": now,
            })
        if isinstance(backup_state, dict):
            backup_state.update({
                "status": BACKUP_RESOURCE_STATUS_CANCELED,
                "phase": "canceled",
                "completed_at": now,
                "updated_at": now,
            })
            complete_backup_attempt(backup_state, "canceled")
        event_name = f"{operation}-canceled"
        event_message = f"Queued {operation} canceled before execution started."
    else:
        event_name = f"{operation}-cancel-requested"
        event_message = f"{noun} cancellation requested; worker will stop at the next durable checkpoint."

    if operation == DATA_MANAGEMENT_OPERATION_BACKUP:
        job["last_message"] = (
            "Queued backup canceled before execution started."
            if job.get("status") == DATA_MANAGEMENT_STATUS_CANCELED else
            "Backup cancellation requested. The worker will stop at its next durable checkpoint."
        )

    saved_job = _save_data_management_job(job)
    _record_data_management_job_event(
        saved_job.get("id"),
        event_name,
        saved_job,
        status=saved_job.get("status"),
        message=event_message,
        details={
            "cancel_requested_at": now,
            "has_reason": bool(safe_reason),
        },
    )
    return saved_job


def request_data_management_migration_cancellation(
    job_id,
    requested_by=None,
    requested_by_email=None,
    reason="",
):
    """Retain the migration-specific API while delegating to the shared job control."""
    job = get_data_management_job(job_id)
    if not job or job.get("operation") != DATA_MANAGEMENT_OPERATION_MIGRATION:
        raise DataManagementSettingsValidationError("Data Management migration job was not found.")
    return request_data_management_job_cancellation(
        job_id,
        requested_by=requested_by,
        requested_by_email=requested_by_email,
        reason=reason,
    )


def retry_data_management_migration_job(job_id):
    """Requeue a failed migration without changing its provenance identity or checkpoints."""
    job = get_data_management_job(job_id)
    if not job:
        raise DataManagementSettingsValidationError("Data Management job was not found.")
    if job.get("operation") != DATA_MANAGEMENT_OPERATION_MIGRATION:
        raise DataManagementSettingsValidationError("Only migration jobs can be retried from migration checkpoints.")
    retryable_statuses = {DATA_MANAGEMENT_STATUS_FAILED, DATA_MANAGEMENT_STATUS_CANCELED}
    if job.get("status") == DATA_MANAGEMENT_STATUS_RUNNING and _is_stale_job(job):
        retryable_statuses.add(DATA_MANAGEMENT_STATUS_RUNNING)
    if job.get("status") not in retryable_statuses:
        raise DataManagementSettingsValidationError(
            "Only failed, canceled, or stale migration jobs can be retried."
        )
    migration_state = job.get("migration_state")
    canceled_before_start = (
        job.get("status") == DATA_MANAGEMENT_STATUS_CANCELED and
        not isinstance(migration_state, dict)
    )
    if not canceled_before_start and (
        not isinstance(migration_state, dict) or not migration_state.get("migration_id")
    ):
        raise DataManagementSettingsValidationError("This migration does not have durable checkpoint state to retry.")
    if (
        not canceled_before_start and
        _safe_text(migration_state.get("migration_id")) != _safe_text(job.get("id"))
    ):
        raise DataManagementSettingsValidationError("Migration checkpoint identity does not match the job identity.")

    now = _now_iso()
    if isinstance(migration_state, dict):
        migration_state["last_cancellation"] = {
            "requested_at": migration_state.get("cancel_requested_at"),
            "requested_by": migration_state.get("cancel_requested_by"),
            "reason": migration_state.get("cancel_reason"),
        }
        migration_state.update({
            "status": DATA_MANAGEMENT_STATUS_QUEUED,
            "updated_at": now,
            "last_error": None,
            "retry_requested_at": now,
            "cancel_requested_at": None,
            "cancel_requested_by": None,
            "cancel_reason": None,
        })
    job.update({
        "status": DATA_MANAGEMENT_STATUS_QUEUED,
        "updated_at": now,
        "completed_at": None,
        "last_heartbeat_at": None,
        "last_message": "Migration retry queued from durable checkpoints",
        "last_error": None,
        "last_cancellation": {
            "requested_at": job.get("cancel_requested_at"),
            "requested_by": job.get("cancel_requested_by"),
            "requested_by_email": job.get("cancel_requested_by_email"),
            "reason": job.get("cancel_reason"),
        },
        "cancel_requested_at": None,
        "cancel_requested_by": None,
        "cancel_requested_by_email": None,
        "cancel_reason": None,
        "lease_holder_id": None,
        "lease_expires_at": None,
        "migration_state": migration_state,
        "result": {},
    })
    saved_job = _save_data_management_job(job)
    _record_data_management_job_event(
        saved_job.get("id"),
        "migration-retry-queued",
        saved_job,
        status=DATA_MANAGEMENT_STATUS_QUEUED,
        message="Migration retry queued from durable checkpoints",
        details={
            "migration_id": (
                migration_state.get("migration_id")
                if isinstance(migration_state, dict) else
                job.get("id")
            ),
            "resume_count": (
                migration_state.get("resume_count")
                if isinstance(migration_state, dict) else
                0
            ),
        },
    )
    return saved_job


def retry_data_management_backup_job(job_id):
    """Requeue a backup from durable checkpoints without changing its immutable plan."""
    job = get_data_management_job(job_id)
    if not job or job.get("operation") != DATA_MANAGEMENT_OPERATION_BACKUP:
        raise DataManagementSettingsValidationError("Data Management backup job was not found.")
    retryable_statuses = {DATA_MANAGEMENT_STATUS_FAILED, DATA_MANAGEMENT_STATUS_CANCELED}
    backup_state = job.get("backup_state")
    has_retryable_resource_failures = any(
        isinstance(resource, dict) and
        resource.get("status") == BACKUP_RESOURCE_STATUS_FAILED
        for resource in ((backup_state or {}).get("resources") or {}).values()
    )
    if (
        job.get("status") == DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS and
        has_retryable_resource_failures
    ):
        retryable_statuses.add(DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS)
    if job.get("status") == DATA_MANAGEMENT_STATUS_RUNNING and _is_stale_job(job):
        retryable_statuses.add(DATA_MANAGEMENT_STATUS_RUNNING)
    if job.get("status") not in retryable_statuses:
        raise DataManagementSettingsValidationError(
            "Only failed, canceled, or stale backup jobs can be retried."
        )
    backup_plan = job.get("backup_plan")
    canceled_before_start = (
        job.get("status") == DATA_MANAGEMENT_STATUS_CANCELED and
        not isinstance(backup_state, dict)
    )
    if not canceled_before_start and (
        not isinstance(backup_plan, dict) or
        not isinstance(backup_state, dict) or
        _safe_text(backup_state.get("backup_id")) != _safe_text(job.get("id"))
    ):
        raise DataManagementSettingsValidationError(
            "This backup does not have durable checkpoint state to retry."
        )

    now = _now_iso()
    if isinstance(backup_state, dict):
        backup_state["last_cancellation"] = {
            "requested_at": backup_state.get("cancel_requested_at"),
            "requested_by": backup_state.get("cancel_requested_by"),
            "reason": backup_state.get("cancel_reason"),
        }
        backup_state.update({
            "status": BACKUP_RESOURCE_STATUS_PENDING,
            "phase": "queued",
            "updated_at": now,
            "completed_at": None,
            "cancel_requested_at": None,
            "cancel_requested_by": None,
            "cancel_reason": None,
        })
    job.update({
        "status": DATA_MANAGEMENT_STATUS_QUEUED,
        "updated_at": now,
        "completed_at": None,
        "last_heartbeat_at": None,
        "last_message": "Backup retry queued from durable checkpoints",
        "last_error": None,
        "last_cancellation": {
            "requested_at": job.get("cancel_requested_at"),
            "requested_by": job.get("cancel_requested_by"),
            "requested_by_email": job.get("cancel_requested_by_email"),
            "reason": job.get("cancel_reason"),
        },
        "cancel_requested_at": None,
        "cancel_requested_by": None,
        "cancel_requested_by_email": None,
        "cancel_reason": None,
        "lease_holder_id": None,
        "lease_expires_at": None,
        "backup_source_lock": None,
        "backup_state": backup_state,
        "result": {},
    })
    saved_job = _save_data_management_job(job)
    _record_data_management_job_event(
        saved_job.get("id"),
        "backup-retry-queued",
        saved_job,
        status=DATA_MANAGEMENT_STATUS_QUEUED,
        message="Backup retry queued from durable checkpoints",
        details={
            "source_cutoff_at": (backup_plan or {}).get("source_cutoff_at"),
            "resume_count": (backup_state or {}).get("resume_count", 0),
        },
    )
    return saved_job


def get_data_management_job_items(job_id, limit=200):
    safe_job_id = _safe_text(job_id)
    if not safe_job_id:
        return []
    safe_limit = _safe_int(limit, default=200, minimum=1, maximum=500)
    query = "SELECT * FROM c WHERE c.job_id = @job_id AND c.type = @type ORDER BY c.created_at ASC"
    parameters = [
        {"name": "@job_id", "value": safe_job_id},
        {"name": "@type", "value": DATA_MANAGEMENT_JOB_ITEM_TYPE},
    ]
    return list(cosmos_data_management_job_items_container.query_items(
        query=query,
        parameters=parameters,
        partition_key=safe_job_id,
        max_item_count=safe_limit,
    ))[:safe_limit]


def get_data_management_job_detail(job_id):
    job = get_data_management_job(job_id)
    if not job:
        return None
    sanitized_job = sanitize_data_management_job_for_admin(job)
    reconciliation_resource = (
        ((job.get("migration_state") or {}).get("resources") or {}).get(
            "reconciliation:cutover"
        )
        if isinstance(job.get("migration_state"), dict) else None
    )
    reconciliation_result = (
        reconciliation_resource.get("result")
        if isinstance(reconciliation_resource, dict) and
        isinstance(reconciliation_resource.get("result"), dict)
        else None
    )
    if reconciliation_result and isinstance(sanitized_job, dict):
        sanitized_result = (
            sanitized_job.get("result")
            if isinstance(sanitized_job.get("result"), dict)
            else {}
        )
        artifacts = (
            list(sanitized_result.get("artifacts"))
            if isinstance(sanitized_result.get("artifacts"), list)
            else []
        )
        if not any(
            isinstance(artifact, dict) and artifact.get("type") == "migration_reconciliation"
            for artifact in artifacts
        ):
            reconciliation_artifact = _summarize_backup_artifact(reconciliation_result)
            if reconciliation_artifact:
                artifacts.append(reconciliation_artifact)
        sanitized_result["artifacts"] = artifacts
        sanitized_result["artifact_count"] = len(artifacts)
        sanitized_job["result"] = sanitized_result
    return {
        "job": sanitized_job,
        "items": [
            sanitized_item
            for sanitized_item in (
                sanitize_data_management_job_item_for_admin(item)
                for item in get_data_management_job_items(job.get("id"))
            )
            if sanitized_item
        ],
    }


def get_data_management_job_progress(job_id):
    job = get_data_management_job(job_id)
    if not job:
        return None
    public_job = sanitize_data_management_job_for_admin(job)
    return {
        "id": public_job.get("id"),
        "operation": public_job.get("operation"),
        "status": public_job.get("status"),
        "updated_at": public_job.get("updated_at"),
        "last_heartbeat_at": public_job.get("last_heartbeat_at"),
        "last_progress_at": public_job.get("last_progress_at"),
        "last_message": public_job.get("last_message"),
        "last_error": public_job.get("last_error"),
        "progress": public_job.get("progress"),
        "migration_state": public_job.get("migration_state"),
        "backup_state": public_job.get("backup_state"),
        "can_retry": public_job.get("can_retry"),
        "can_cancel": public_job.get("can_cancel"),
    }


def _summarize_backup_artifact(artifact):
    if not isinstance(artifact, dict):
        return None
    allowed_fields = [
        "name",
        "type",
        "category",
        "status",
        "path",
        "bytes",
        "item_count",
        "copied_count",
        "created_count",
        "updated_count",
        "unchanged_count",
        "skipped_count",
        "failed_count",
        "collision_count",
        "missing_count",
        "not_applicable_count",
        "processed_count",
        "request_units",
        "elapsed_seconds",
        "items_per_second",
        "bytes_per_second",
        "request_units_per_second",
        "parallel_operations",
        "active_parallel_operations",
        "batch_size",
        "retry_count",
        "retry_attempt_count",
        "throttle_count",
        "source_page_count",
        "prior_failed_count",
        "checkpoint_count",
        "source_read_count",
        "destination_accepted_count",
        "destination_failed_count",
        "destination_provenance_skip_count",
        "blob_count",
        "encrypted",
        "container_name",
        "partition_key_path",
        "index_name",
        "partial_since_epoch",
        "partial_filter",
        "prefix",
        "migration_mode",
        "readiness",
        "deletion_policy",
        "deletion_status",
        "deletion_blockers",
        "deleted_count",
        "delete_candidate_count",
        "remaining_destination_only_owned_count",
        "destination_only_unowned_count",
        "unresolved_scope_count",
        "stale_count",
        "keyset_cursor",
        "actual_outcomes",
        "preview_actual_divergence",
        "services",
        "warning",
    ]
    summary = {
        field_name: _sanitize_activity_value(artifact.get(field_name))
        for field_name in allowed_fields
        if artifact.get(field_name) is not None
    }
    for text_field in ("path", "prefix", "warning", "partial_filter"):
        if text_field in summary:
            summary[text_field] = _sanitize_data_management_backup_text(summary[text_field])
    return summary


def summarize_backup_artifacts(artifacts):
    if not isinstance(artifacts, list):
        return []
    return [summary for summary in (_summarize_backup_artifact(artifact) for artifact in artifacts) if summary]


def _backup_artifact_totals(artifacts):
    totals = {
        "artifact_count": 0,
        "bytes": 0,
        "record_count": 0,
        "blob_count": 0,
        "warning_count": 0,
    }
    artifact_list = artifacts if isinstance(artifacts, list) else []
    for artifact in artifact_list:
        if not isinstance(artifact, dict):
            continue
        totals["artifact_count"] += 1
        totals["bytes"] += _safe_int(artifact.get("bytes"), default=0, minimum=0)
        totals["record_count"] += _safe_int(
            artifact.get("item_count", artifact.get("copied_count")),
            default=0,
            minimum=0,
        )
        totals["blob_count"] += _safe_int(artifact.get("blob_count"), default=0, minimum=0)
        if artifact.get("warning") or artifact.get("status") == "warning":
            totals["warning_count"] += 1
    return totals


def sanitize_data_management_backup_for_admin(job):
    public_job = sanitize_data_management_job_for_admin(job)
    if not public_job:
        return None
    result = public_job.get("result") if isinstance(public_job.get("result"), dict) else {}
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    totals = _backup_artifact_totals(artifacts)
    return {
        "id": public_job.get("id"),
        "backup_type": public_job.get("backup_type"),
        "status": public_job.get("status"),
        "created_at": public_job.get("created_at"),
        "completed_at": public_job.get("completed_at"),
        "scheduled": public_job.get("scheduled"),
        "manifest_path": result.get("manifest_path"),
        "base_prefix": result.get("base_prefix"),
        "artifact_count": totals.get("artifact_count") or result.get("artifact_count") or 0,
        "bytes": totals.get("bytes", 0),
        "record_count": totals.get("record_count", 0),
        "blob_count": totals.get("blob_count", 0),
        "warning_count": len(public_job.get("warnings") or []) + totals.get("warning_count", 0),
        "encrypted": any(bool(artifact.get("encrypted")) for artifact in artifacts if isinstance(artifact, dict)),
        "last_message": public_job.get("last_message"),
    }


def get_data_management_backup_inventory(limit=100):
    safe_limit = _safe_int(limit, default=100, minimum=1, maximum=500)
    query = "SELECT * FROM c WHERE c.type = @type AND c.operation = @operation ORDER BY c.created_at DESC"
    parameters = [
        {"name": "@type", "value": DATA_MANAGEMENT_JOB_TYPE},
        {"name": "@operation", "value": DATA_MANAGEMENT_OPERATION_BACKUP},
    ]
    jobs = list(cosmos_data_management_jobs_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
        max_item_count=safe_limit,
    ))[:safe_limit]
    return [backup for backup in (sanitize_data_management_backup_for_admin(job) for job in jobs) if backup]


def get_data_management_backup_summary(limit=100):
    backups = get_data_management_backup_inventory(limit=limit)
    summary = {
        "full": 0,
        "partial": 0,
        "available": 0,
        "running": 0,
        "failed": 0,
        "total": len(backups),
        "latest_full": None,
        "latest_partial": None,
    }
    for backup in backups:
        status = backup.get("status")
        backup_type = backup.get("backup_type")
        if status in {DATA_MANAGEMENT_STATUS_COMPLETED, DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS}:
            summary["available"] += 1
            if backup_type == DATA_MANAGEMENT_BACKUP_FULL:
                summary["full"] += 1
                summary["latest_full"] = summary["latest_full"] or backup
            elif backup_type == DATA_MANAGEMENT_BACKUP_PARTIAL:
                summary["partial"] += 1
                summary["latest_partial"] = summary["latest_partial"] or backup
        elif status == DATA_MANAGEMENT_STATUS_RUNNING:
            summary["running"] += 1
        elif status == DATA_MANAGEMENT_STATUS_FAILED:
            summary["failed"] += 1
    return {"summary": summary, "backups": backups}


def _search_text_matches(document, fields, search_text):
    normalized_search = _safe_text(search_text).lower()
    if not normalized_search:
        return True
    return any(normalized_search in _safe_text(document.get(field_name)).lower() for field_name in fields)


def _query_catalog_items(container, search_text, search_fields, order_field, limit=DATA_MANAGEMENT_MIGRATION_CATALOG_LIMIT):
    safe_limit = _safe_int(limit, default=DATA_MANAGEMENT_MIGRATION_CATALOG_LIMIT, minimum=1, maximum=250)
    results = []
    query = "SELECT * FROM c"
    for item in container.query_items(query=query, enable_cross_partition_query=True):
        if _search_text_matches(item, search_fields, search_text):
            results.append(_strip_cosmos_system_fields(item))
    results.sort(key=lambda item: _safe_text(item.get(order_field) or item.get("name") or item.get("display_name") or item.get("email") or item.get("id")).lower())
    return results[:safe_limit]


def _count_documents_for_scope(container, field_name, scope_id):
    query = f"SELECT VALUE COUNT(1) FROM c WHERE c.{field_name} = @scope_id"
    parameters = [{"name": "@scope_id", "value": scope_id}]
    results = list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))
    return results[0] if results and isinstance(results[0], int) else 0


def get_data_management_migration_catalog(target_type, search_text="", limit=DATA_MANAGEMENT_MIGRATION_CATALOG_LIMIT):
    normalized_target_type = _safe_text(target_type)
    if normalized_target_type == "users":
        users = _query_catalog_items(
            app_config.cosmos_user_settings_container,
            search_text,
            ["email", "display_name", "id"],
            "display_name",
            limit=limit,
        )
        return {
            "type": "users",
            "items": [
                {
                    "id": user.get("id"),
                    "label": user.get("display_name") or user.get("email") or user.get("id"),
                    "description": user.get("email") or "No email recorded",
                    "document_count": _count_documents_for_scope(app_config.cosmos_user_documents_container, "user_id", user.get("id")),
                }
                for user in users
                if user.get("id")
            ],
        }
    if normalized_target_type == "groups":
        groups = _query_catalog_items(
            app_config.cosmos_groups_container,
            search_text,
            ["name", "description", "id"],
            "name",
            limit=limit,
        )
        return {
            "type": "groups",
            "items": [
                {
                    "id": group.get("id"),
                    "label": group.get("name") or group.get("id"),
                    "description": group.get("description") or "No description recorded",
                    "document_count": _count_documents_for_scope(app_config.cosmos_group_documents_container, "group_id", group.get("id")),
                }
                for group in groups
                if group.get("id")
            ],
        }
    if normalized_target_type == "public_workspaces":
        workspaces = _query_catalog_items(
            app_config.cosmos_public_workspaces_container,
            search_text,
            ["name", "description", "id"],
            "name",
            limit=limit,
        )
        return {
            "type": "public_workspaces",
            "items": [
                {
                    "id": workspace.get("id"),
                    "label": workspace.get("name") or workspace.get("id"),
                    "description": workspace.get("description") or "No description recorded",
                    "document_count": _count_documents_for_scope(app_config.cosmos_public_documents_container, "public_workspace_id", workspace.get("id")),
                }
                for workspace in workspaces
                if workspace.get("id")
            ],
        }
    raise DataManagementSettingsValidationError("Unsupported migration catalog type.")


def _dedupe_limited_strings(values, limit=500):
    ordered_values = []
    seen = set()
    if not isinstance(values, list):
        return ordered_values
    for value in values:
        normalized = _safe_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered_values.append(normalized)
        if len(ordered_values) >= limit:
            break
    return ordered_values


def normalize_data_management_migration_plan(options):
    raw_plan = options.get("migration_plan") if isinstance(options, dict) else {}
    if not isinstance(raw_plan, dict):
        raw_plan = {}
    migration_mode = _safe_text(
        raw_plan.get("migration_mode"),
        DATA_MANAGEMENT_MIGRATION_MODE_NEW_ONLY,
    ).lower()
    if migration_mode not in DATA_MANAGEMENT_MIGRATION_MODES:
        raise DataManagementSettingsValidationError(
            "Migration mode must be new_only, delta_upsert, or mirror_with_deletions."
        )
    baseline_job_id = _safe_text(raw_plan.get("baseline_job_id"))
    if baseline_job_id:
        try:
            baseline_job_id = str(uuid.UUID(baseline_job_id))
        except (AttributeError, TypeError, ValueError) as exc:
            raise DataManagementSettingsValidationError(
                "Migration baseline job ID must be a valid GUID."
            ) from exc
    mirror_confirmation = _safe_text(raw_plan.get("mirror_confirmation"))
    mirror_deletions_confirmed = (
        migration_mode == DATA_MANAGEMENT_MIGRATION_MODE_MIRROR and
        mirror_confirmation == DATA_MANAGEMENT_MIRROR_CONFIRMATION
    )
    if (
        migration_mode == DATA_MANAGEMENT_MIGRATION_MODE_MIRROR and
        not mirror_deletions_confirmed
    ):
        raise DataManagementSettingsValidationError(
            f"Mirror migration requires the exact confirmation phrase: {DATA_MANAGEMENT_MIRROR_CONFIRMATION}"
        )
    plan = {
        "users": _normalize_migration_selection(raw_plan.get("users")),
        "groups": _normalize_migration_selection(raw_plan.get("groups")),
        "public_workspaces": _normalize_migration_selection(raw_plan.get("public_workspaces")),
        "include_ai_search": raw_plan.get("include_ai_search") is not False,
        "include_source_blobs": bool(raw_plan.get("include_source_blobs")),
        "target_ai_search_writes_frozen": (
            raw_plan.get("target_ai_search_writes_frozen") is True
        ),
        "migration_mode": migration_mode,
        "baseline_job_id": baseline_job_id,
        "mirror_deletions_confirmed": mirror_deletions_confirmed,
    }
    for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPES:
        if plan[target_type].get("mode") == "none":
            plan[target_type]["include_documents"] = False
    return plan


def _resolve_plan_scope_ids(target_type, plan_entry):
    if plan_entry.get("mode") == "all":
        catalog = get_data_management_migration_catalog(target_type, limit=1000)
        return [item.get("id") for item in catalog.get("items", []) if item.get("id")]
    return _dedupe_limited_strings(plan_entry.get("ids"))


def summarize_data_management_migration_plan(options):
    plan = normalize_data_management_migration_plan(options or {})
    summary = {}
    for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPES:
        ids = _resolve_plan_scope_ids(target_type, plan[target_type])
        summary[target_type] = {
            "mode": plan[target_type].get("mode"),
            "count": len(ids),
            "include_documents": bool(plan[target_type].get("include_documents")),
            "ids": ids[:50],
        }
    summary["include_ai_search"] = bool(plan.get("include_ai_search"))
    summary["include_source_blobs"] = bool(plan.get("include_source_blobs"))
    summary["target_ai_search_writes_frozen"] = bool(
        plan.get("target_ai_search_writes_frozen")
    )
    summary["migration_mode"] = plan.get("migration_mode")
    summary["baseline_job_id"] = plan.get("baseline_job_id")
    summary["mirror_deletions_confirmed"] = bool(plan.get("mirror_deletions_confirmed"))
    return summary


def _count_preview_source_cosmos_records(migration_plan, source_cutoff_at):
    source_cutoff = _parse_iso_datetime(source_cutoff_at)
    source_cutoff_epoch = int(source_cutoff.timestamp()) if source_cutoff else None
    record_count = 0
    for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPE_ORDER:
        selection = migration_plan.get(target_type) or {}
        if selection.get("mode") == "none":
            continue
        for container_definition in DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS[target_type]:
            if container_definition.get("documents") and not selection.get("include_documents"):
                continue
            record_count += sum(
                1
                for _item in _iter_selected_cosmos_records(
                    container_definition,
                    selection,
                    source_cutoff_epoch=source_cutoff_epoch,
                ) or []
            )
    return record_count


def preview_data_management_migration_plan(
    settings,
    options,
    resolved_migration_plan=None,
    source_cutoff_at=None,
    migration_id=None,
    heartbeat_callback=None,
):
    """Build a read-only server-owned inventory preview for one migration plan."""
    if isinstance(resolved_migration_plan, dict):
        migration_plan = copy.deepcopy(resolved_migration_plan)
    else:
        migration_plan = normalize_data_management_migration_plan(options or {})
        preview_job = {"id": str(uuid.uuid4())}
        migration_plan = _resolve_data_management_migration_baseline(
            preview_job,
            settings,
            migration_plan,
        )
    source_cutoff_at = _safe_text(source_cutoff_at) or _now_iso()
    preview_migration_id = _safe_text(migration_id) or str(uuid.uuid4())
    migration_state = {"source_cutoff_at": source_cutoff_at}
    provenance_context = create_migration_provenance_context(
        migration_id=preview_migration_id,
        migrated_at_utc=source_cutoff_at,
    )
    provenance_context.update({
        "migration_mode": migration_plan.get("migration_mode"),
        "baseline_job_id": migration_plan.get("baseline_job_id"),
        "baseline_source_cutoff_at": migration_plan.get("baseline_source_cutoff_at"),
    })
    try:
        target_database = _get_existing_target_cosmos_database(settings)
        cosmos_report = _reconcile_cosmos_migration(
            target_database,
            migration_plan,
            migration_state,
            provenance_context,
            apply_deletions=False,
            heartbeat_callback=heartbeat_callback,
        )
    except (CosmosResourceNotFoundError, ResourceNotFoundError):
        source_record_count = _count_preview_source_cosmos_records(
            migration_plan,
            source_cutoff_at,
        )
        cosmos_report = {
            "service": "cosmos",
            "create_count": source_record_count,
            "update_count": 0,
            "unchanged_count": 0,
            "delete_candidate_count": 0,
            "conflict_count": 0,
            "missing_count": 0,
            "warning": "Destination Cosmos database does not exist; selected source records are new.",
        }
    search_report = _reconcile_ai_search_migration(
        settings,
        migration_plan,
        apply_deletions=False,
        heartbeat_callback=heartbeat_callback,
    )
    blob_report = _reconcile_blob_migration(
        settings,
        migration_plan,
        apply_deletions=False,
        heartbeat_callback=heartbeat_callback,
    )
    service_reports = [cosmos_report, search_report, blob_report]
    estimated_outcomes = {
        "create_count": sum(_safe_int(report.get("create_count"), default=0) for report in service_reports),
        "update_count": sum(_safe_int(report.get("update_count"), default=0) for report in service_reports),
        "unchanged_count": sum(_safe_int(report.get("unchanged_count"), default=0) for report in service_reports),
        "delete_count": sum(_safe_int(report.get("delete_candidate_count"), default=0) for report in service_reports),
        "not_applicable_count": sum(_safe_int(report.get("not_applicable_count"), default=0) for report in service_reports),
        "missing_count": sum(
            _safe_int(report.get("source_missing_count"), default=0)
            for report in service_reports
        ),
        "conflict_count": sum(_safe_int(report.get("conflict_count"), default=0) for report in service_reports),
        "failed_count": 0,
    }
    normalized_preview_plan = copy.deepcopy(migration_plan)
    normalized_preview_plan.pop("mirror_confirmation", None)
    return {
        "captured_at": source_cutoff_at,
        "migration_mode": migration_plan.get("migration_mode"),
        "baseline_job_id": migration_plan.get("baseline_job_id"),
        "baseline_source_cutoff_at": migration_plan.get("baseline_source_cutoff_at"),
        "plan_fingerprint": hashlib.sha256(json.dumps(
            normalized_preview_plan,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")).hexdigest(),
        "estimated_outcomes": estimated_outcomes,
        "services": service_reports,
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
    if job.get("operation") == DATA_MANAGEMENT_OPERATION_MIGRATION:
        try:
            if _has_active_migration_destination_lock(job):
                return None
        except DataManagementMigrationLeaseLostError as exc:
            log_event(
                "[DataManagement] Migration retry claim deferred because its coordinator lock could not be verified.",
                {"job_id": job_id, "error": str(exc)},
                level=logging.WARNING,
            )
            return None
    if job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP:
        try:
            if _has_active_backup_source_lock(job):
                _defer_data_management_backup_job(
                    job,
                    "Backup claim deferred because another full or partial backup owns this source.",
                )
                return None
        except DataManagementBackupLeaseLostError as exc:
            log_event(
                "[DataManagement] Backup claim deferred because its source lock could not be verified.",
                {"job_id": job_id, "error": str(exc)},
                level=logging.WARNING,
            )
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
        "lease_generation": _safe_int(job.get("lease_generation"), default=0, minimum=0) + 1,
        "last_message": "Data management job claimed by a worker",
    })
    if job.get("operation") == DATA_MANAGEMENT_OPERATION_MIGRATION:
        job["migration_attempt_id"] = str(uuid.uuid4())
    elif job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP:
        job["backup_attempt_id"] = str(uuid.uuid4())
    try:
        claimed_job = _replace_job(job)
        if claimed_job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP:
            try:
                _acquire_backup_source_lock(claimed_job, settings or {})
                _save_data_management_job(claimed_job)
            except DataManagementBackupOverlapError:
                _defer_data_management_backup_job(
                    claimed_job,
                    "Backup claim deferred because another full or partial backup acquired this source.",
                )
                return None
            except Exception:
                _release_backup_source_lock(claimed_job)
                raise
        _record_data_management_job_event(
            claimed_job.get("id"),
            "claimed",
            claimed_job,
            status=DATA_MANAGEMENT_STATUS_RUNNING,
            message="Data management job claimed by a worker",
            details={"lease_expires_at": claimed_job.get("lease_expires_at")},
        )
        return claimed_job
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code not in (409, 412):
            log_event(
                "[DataManagement] Job claim failed.",
                {"job_id": job_id, "status_code": status_code, "error": str(exc)},
                level=logging.WARNING,
            )
        return None


def _safe_job_item_id_part(value):
    normalized = _safe_text(value, "event")
    safe_value = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in normalized)
    return (safe_value.strip("-") or "event")[:80]


def _sanitize_migration_manifest_entry(entry):
    allowed_fields = {
        "service",
        "resource_name",
        "target_type",
        "source_identity",
        "destination_identity",
        "item_ref",
        "status",
        "attempt",
        "bytes",
        "source_version",
        "source_hash",
        "error",
        "recorded_at",
    }
    sanitized = {
        field_name: _sanitize_activity_value((entry or {}).get(field_name))
        for field_name in allowed_fields
        if (entry or {}).get(field_name) is not None
    }
    sanitized["error"] = _safe_text(sanitized.get("error"))[:500]
    sanitized["recorded_at"] = _safe_text(sanitized.get("recorded_at")) or _now_iso()
    return sanitized


def _hash_migration_manifest_identity(*identity_parts):
    encoded = json.dumps(
        [str(part) for part in identity_parts],
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _build_migration_manifest_item_ref(
    job_id,
    service="",
    resource_name="",
    target_type="",
    document_id="",
    partition_key=None,
    container_name="",
    blob_name="",
    index_name="",
):
    return str(uuid.uuid4())


def resolve_data_management_migration_manifest_item(job_id, item_ref):
    safe_job_id = _safe_text(job_id)
    safe_item_ref = _safe_text(item_ref)
    if not safe_job_id or not safe_item_ref:
        raise DataManagementSettingsValidationError("Migration manifest item reference is required.")
    job = get_data_management_job(safe_job_id)
    if not job or job.get("operation") != DATA_MANAGEMENT_OPERATION_MIGRATION:
        raise DataManagementSettingsValidationError("Data Management migration job was not found.")
    query = (
        "SELECT * FROM c WHERE c.job_id = @job_id AND c.type = @type "
        "ORDER BY c.created_at ASC"
    )
    parameters = [
        {"name": "@job_id", "value": safe_job_id},
        {"name": "@type", "value": DATA_MANAGEMENT_MIGRATION_MANIFEST_BATCH_TYPE},
    ]
    batches = cosmos_data_management_job_items_container.query_items(
        query=query,
        parameters=parameters,
        partition_key=safe_job_id,
        max_item_count=100,
    )
    for batch in batches:
        for locator in batch.get("private_locators") or []:
            if _safe_text(locator.get("item_ref")) != safe_item_ref:
                continue
            return {
                "service": _safe_text(locator.get("service")),
                "resource_name": _safe_text(locator.get("resource_name")),
                "target_type": _safe_text(locator.get("target_type")),
                "document_id": _safe_text(locator.get("document_id")),
                "partition_key": locator.get("partition_key"),
                "container_name": _safe_text(locator.get("container_name")),
                "blob_name": _safe_text(locator.get("blob_name")),
                "index_name": _safe_text(locator.get("index_name")),
            }
    raise DataManagementSettingsValidationError(
        "Migration manifest item reference was not found."
    )


def _write_migration_manifest_batch(job_id, resource_name, entries):
    normalized_entries = []
    private_locators = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        locator = entry.get("_locator") if isinstance(entry.get("_locator"), dict) else None
        item_ref = _safe_text(entry.get("item_ref"))
        if locator and not item_ref:
            item_ref = _build_migration_manifest_item_ref(job_id, **locator)
        public_entry = dict(entry)
        public_entry.pop("_locator", None)
        if item_ref:
            public_entry["item_ref"] = item_ref
        normalized_entries.append(_sanitize_migration_manifest_entry(public_entry))
        if locator and item_ref:
            private_locators.append({
                "item_ref": item_ref,
                "service": _safe_text(locator.get("service")),
                "resource_name": _safe_text(locator.get("resource_name")),
                "target_type": _safe_text(locator.get("target_type")),
                "document_id": _safe_text(locator.get("document_id")),
                "partition_key": copy.deepcopy(locator.get("partition_key")),
                "container_name": _safe_text(locator.get("container_name")),
                "blob_name": _safe_text(locator.get("blob_name")),
                "index_name": _safe_text(locator.get("index_name")),
            })
    if not normalized_entries:
        return None
    create_item = getattr(cosmos_data_management_job_items_container, "create_item", None)
    if not callable(create_item):
        raise RuntimeError("Migration manifest storage is not available.")
    now = _now_iso()
    body = {
        "id": (
            f"{_safe_job_item_id_part(job_id)}:manifest:"
            f"{_safe_job_item_id_part(resource_name)}:{uuid.uuid4().hex}"
        ),
        "job_id": _safe_text(job_id),
        "type": DATA_MANAGEMENT_MIGRATION_MANIFEST_BATCH_TYPE,
        "resource_name": _safe_text(resource_name),
        "created_at": now,
        "updated_at": now,
        "entry_count": len(normalized_entries),
        "entries": normalized_entries,
        "private_locators": private_locators,
    }
    return create_item(body=body)


def _create_migration_manifest_writer(job_id, resource_name):
    buffer = []

    def append(entry):
        buffer.append(entry)
        if len(buffer) >= DATA_MANAGEMENT_MIGRATION_MANIFEST_BATCH_SIZE:
            flush()

    def flush():
        if not buffer:
            return
        pending_entries = list(buffer)
        _write_migration_manifest_batch(job_id, resource_name, pending_entries)
        del buffer[:len(pending_entries)]

    return append, flush


def iter_data_management_migration_manifest_entries(job_id, statuses=None):
    safe_job_id = _safe_text(job_id)
    if not safe_job_id:
        return
    normalized_statuses = {
        _safe_text(status).lower()
        for status in (statuses or [])
        if _safe_text(status)
    }
    query = (
        "SELECT * FROM c WHERE c.job_id = @job_id AND c.type = @type "
        "ORDER BY c.created_at ASC"
    )
    parameters = [
        {"name": "@job_id", "value": safe_job_id},
        {"name": "@type", "value": DATA_MANAGEMENT_MIGRATION_MANIFEST_BATCH_TYPE},
    ]
    batches = cosmos_data_management_job_items_container.query_items(
        query=query,
        parameters=parameters,
        partition_key=safe_job_id,
        max_item_count=100,
    )
    for batch in batches:
        for entry in batch.get("entries") or []:
            sanitized = _sanitize_migration_manifest_entry(entry)
            if normalized_statuses and _safe_text(sanitized.get("status")).lower() not in normalized_statuses:
                continue
            yield sanitized


def export_data_management_migration_manifest(job_id, statuses=None):
    job = get_data_management_job(job_id)
    if not job or job.get("operation") != DATA_MANAGEMENT_OPERATION_MIGRATION:
        raise DataManagementSettingsValidationError("Data Management migration job was not found.")
    entries = list(iter_data_management_migration_manifest_entries(job_id, statuses=statuses))
    lines = [
        json.dumps(entry, ensure_ascii=True, separators=(",", ":"), default=str)
        for entry in entries
    ]
    return {
        "content": "\n".join(lines) + ("\n" if lines else ""),
        "entry_count": len(entries),
        "statuses": sorted({
            _safe_text(status).lower()
            for status in (statuses or [])
            if _safe_text(status)
        }),
    }


def _sanitize_mirror_deletion_candidate(candidate):
    allowed_fields = {
        "service",
        "target_type",
        "container_name",
        "document_id",
        "partition_key",
        "target_etag",
        "index_name",
        "blob_name",
    }
    return {
        field_name: copy.deepcopy((candidate or {}).get(field_name))
        for field_name in allowed_fields
        if (candidate or {}).get(field_name) is not None
    }


def _write_mirror_deletion_candidate_batch(job_id, plan_id, candidates):
    normalized_candidates = [
        _sanitize_mirror_deletion_candidate(candidate)
        for candidate in (candidates or [])
        if isinstance(candidate, dict)
    ]
    if not normalized_candidates:
        return None
    now = _now_iso()
    return cosmos_data_management_job_items_container.create_item(body={
        "id": (
            f"{_safe_job_item_id_part(job_id)}:mirror-plan:"
            f"{_safe_job_item_id_part(plan_id)}:{uuid.uuid4().hex}"
        ),
        "job_id": _safe_text(job_id),
        "type": DATA_MANAGEMENT_MIRROR_DELETION_BATCH_TYPE,
        "plan_id": _safe_text(plan_id),
        "created_at": now,
        "updated_at": now,
        "candidate_count": len(normalized_candidates),
        "candidates": normalized_candidates,
    })


def _create_mirror_deletion_candidate_writer(job_id, plan_id):
    buffer = []

    def append(candidate):
        buffer.append(candidate)
        if len(buffer) >= DATA_MANAGEMENT_MIGRATION_MANIFEST_BATCH_SIZE:
            flush()

    def flush():
        if not buffer:
            return
        pending_candidates = list(buffer)
        _write_mirror_deletion_candidate_batch(job_id, plan_id, pending_candidates)
        del buffer[:len(pending_candidates)]

    return append, flush


def _iter_mirror_deletion_candidates(job_id, plan_id):
    query = (
        "SELECT * FROM c WHERE c.job_id = @job_id AND c.type = @type "
        "AND c.plan_id = @plan_id ORDER BY c.created_at ASC"
    )
    parameters = [
        {"name": "@job_id", "value": _safe_text(job_id)},
        {"name": "@type", "value": DATA_MANAGEMENT_MIRROR_DELETION_BATCH_TYPE},
        {"name": "@plan_id", "value": _safe_text(plan_id)},
    ]
    batches = cosmos_data_management_job_items_container.query_items(
        query=query,
        parameters=parameters,
        partition_key=_safe_text(job_id),
        max_item_count=100,
    )
    for batch in batches:
        for candidate in batch.get("candidates") or []:
            yield _sanitize_mirror_deletion_candidate(candidate)


def create_data_management_job_item(job_id, step_name, status=DATA_MANAGEMENT_STATUS_QUEUED, message=None, details=None):
    now = _now_iso()
    safe_job_id = _safe_job_item_id_part(job_id)
    safe_step_name = _safe_job_item_id_part(step_name)
    safe_timestamp = _safe_job_item_id_part(now.replace(":", "").replace(".", ""))
    item = {
        "id": f"{safe_job_id}:{safe_timestamp}:{safe_step_name}:{uuid.uuid4().hex[:8]}",
        "job_id": job_id,
        "type": DATA_MANAGEMENT_JOB_ITEM_TYPE,
        "step_name": step_name,
        "status": status,
        "message": _sanitize_data_management_job_item_text(message),
        "created_at": now,
        "updated_at": now,
        "details": _sanitize_data_management_job_item_details(details),
    }
    return cosmos_data_management_job_items_container.create_item(item)


def _record_data_management_job_event(job_id, step_name, job, status=DATA_MANAGEMENT_STATUS_QUEUED, message=None, details=None):
    safe_message = _sanitize_data_management_job_item_text(message)
    safe_details = _sanitize_data_management_job_item_details(details)
    try:
        create_data_management_job_item(
            job_id,
            step_name,
            status=status,
            message=safe_message,
            details=safe_details,
        )
    except Exception as exc:
        log_event(
            "[DataManagement] Failed to write job timeline event.",
            {"job_id": job_id, "step_name": step_name, "status": status, "error": str(exc)},
            level=logging.WARNING,
        )

    _log_data_management_activity(
        job,
        f"data_management_job_{_safe_job_item_id_part(step_name).replace('-', '_')}",
        status,
        safe_message,
        details=safe_details,
    )


def _defer_data_management_backup_job(job, message):
    """Return a lock-contended backup to the queue without recording a failure."""
    if not isinstance(job, dict):
        return None
    now = _now_iso()
    job.update({
        "status": DATA_MANAGEMENT_STATUS_QUEUED,
        "updated_at": now,
        "last_heartbeat_at": now,
        "last_message": _safe_text(message),
        "lease_holder_id": None,
        "lease_expires_at": None,
        "backup_source_lock": None,
        "deferred_due_to_active_backup": True,
        "deferred_at": now,
    })
    saved_job = _save_data_management_job(job)
    _record_data_management_job_event(
        saved_job.get("id"),
        "backup-deferred",
        saved_job,
        status=DATA_MANAGEMENT_STATUS_QUEUED,
        message=saved_job.get("last_message"),
        details={"scheduled": bool(saved_job.get("scheduled"))},
    )
    return saved_job


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


def _format_cosmos_editor_label(container_name):
    return _safe_text(container_name).replace("_", " ").title()


def _cosmos_editor_partition_key_field(partition_key_path):
    normalized_path = _safe_text(partition_key_path)
    if not normalized_path.startswith("/"):
        raise DataManagementCosmosEditorError("Cosmos editor container metadata has an invalid partition key path.")
    path_parts = [part for part in normalized_path.strip("/").split("/") if part]
    if not path_parts:
        raise DataManagementCosmosEditorError("Cosmos editor container metadata has an invalid partition key path.")
    return path_parts[-1]


def _get_document_path_value(document, path):
    if not isinstance(document, dict):
        return None
    path_parts = [part for part in _safe_text(path).strip("/").split("/") if part]
    current_value = document
    for path_part in path_parts:
        if not isinstance(current_value, dict) or path_part not in current_value:
            return None
        current_value = current_value.get(path_part)
    return current_value


def _build_cosmos_editor_container_metadata():
    containers = []
    seen_container_names = set()
    for logical_name, container_attr, container_name_attr, partition_key_path, category in DATA_MANAGEMENT_COSMOS_EDITOR_CONTAINER_DEFINITIONS:
        container_name = _safe_text(getattr(app_config, container_name_attr, logical_name))
        if not container_name or container_name in seen_container_names or not hasattr(app_config, container_attr):
            continue
        seen_container_names.add(container_name)
        containers.append({
            "id": container_name,
            "name": container_name,
            "logical_name": logical_name,
            "display_name": _format_cosmos_editor_label(container_name),
            "category": category,
            "container_attr": container_attr,
            "container_name_attr": container_name_attr,
            "partition_key_path": partition_key_path,
            "partition_key_field": _cosmos_editor_partition_key_field(partition_key_path),
            "max_page_size": DATA_MANAGEMENT_COSMOS_EDITOR_MAX_PAGE_SIZE,
            "empty_query_limit": DATA_MANAGEMENT_COSMOS_EDITOR_EMPTY_QUERY_LIMIT,
            "editable": True,
        })
    return sorted(containers, key=lambda container: (container["category"], container["display_name"]))


def get_data_management_cosmos_editor_containers():
    return [
        {
            "id": container["id"],
            "name": container["name"],
            "display_name": container["display_name"],
            "category": container["category"],
            "partition_key_path": container["partition_key_path"],
            "partition_key_field": container["partition_key_field"],
            "max_page_size": container["max_page_size"],
            "empty_query_limit": container["empty_query_limit"],
            "editable": container["editable"],
        }
        for container in _build_cosmos_editor_container_metadata()
    ]


def _get_cosmos_editor_container_metadata(container_name):
    safe_container_name = _safe_text(container_name)
    if not safe_container_name:
        raise DataManagementCosmosEditorError("Choose a Cosmos DB container.")
    for container in _build_cosmos_editor_container_metadata():
        if safe_container_name in {container["id"], container["name"], container["logical_name"]}:
            return container
    raise DataManagementCosmosEditorError("The selected Cosmos DB container is not available for Data Management editing.")


def _get_cosmos_editor_container(container_name):
    metadata = _get_cosmos_editor_container_metadata(container_name)
    return metadata, getattr(app_config, metadata["container_attr"])


def _hash_cosmos_editor_query(query_text):
    if not query_text:
        return ""
    return hashlib.sha256(query_text.encode("utf-8")).hexdigest()


def _normalize_cosmos_editor_query(query_text):
    query = _safe_text(query_text)
    if not query:
        return DATA_MANAGEMENT_COSMOS_EDITOR_EMPTY_QUERY, True
    if len(query) > DATA_MANAGEMENT_COSMOS_EDITOR_MAX_QUERY_LENGTH:
        raise DataManagementCosmosEditorError("Cosmos query text is too long.")
    if ";" in query:
        raise DataManagementCosmosEditorError("Run one SELECT query at a time without semicolons.")
    if not re.match(r"^\s*SELECT\b", query, re.IGNORECASE):
        raise DataManagementCosmosEditorError("Cosmos editor queries must start with SELECT.")
    return query, False


def log_data_management_cosmos_editor_activity(admin_user_id, admin_email, action, status, message, details=None):
    now = _now_iso()
    safe_action = _safe_text(action)
    safe_admin_user_id = _safe_text(admin_user_id, "unknown") or "unknown"
    activity_record = {
        "id": str(uuid.uuid4()),
        "user_id": safe_admin_user_id,
        "activity_type": "data_management",
        "timestamp": now,
        "created_at": now,
        "action": safe_action,
        "description": _safe_text(message) or safe_action,
        "workspace_type": "admin",
        "workspace_context": {
            "action": safe_action,
            "tool": "cosmos_json_editor",
        },
        "additional_context": {
            "tool": "cosmos_json_editor",
            "status": _safe_text(status),
            "details": _sanitize_activity_value(details if isinstance(details, dict) else {}),
        },
        "admin": {
            "user_id": safe_admin_user_id,
            "email": _safe_text(admin_email, "unknown") or "unknown",
        },
    }

    try:
        app_config.cosmos_activity_logs_container.create_item(body=activity_record)
    except Exception as exc:
        log_event(
            "[DataManagement] Failed to write Cosmos editor activity record.",
            {"action": safe_action, "status": status, "error": str(exc)},
            level=logging.WARNING,
        )


def _summarize_cosmos_editor_item(item, container_metadata):
    if not isinstance(item, dict):
        preview_text = _safe_text(item)
        return {
            "id": None,
            "partition_key": None,
            "etag": None,
            "timestamp": None,
            "selectable": False,
            "preview": preview_text[:200],
        }

    document_id = item.get("id")
    partition_key_value = _get_document_path_value(item, container_metadata["partition_key_path"])
    preview_fields = []
    for field_name in ("name", "display_name", "title", "type", "user_id", "group_id", "public_workspace_id", "created_at", "updated_at"):
        field_value = item.get(field_name)
        if field_value is not None:
            preview_fields.append(f"{field_name}: {_safe_text(field_value)[:80]}")
        if len(preview_fields) >= 3:
            break

    return {
        "id": _safe_text(document_id) if document_id is not None else None,
        "partition_key": partition_key_value,
        "etag": item.get("_etag"),
        "timestamp": item.get("_ts"),
        "selectable": document_id is not None and partition_key_value is not None,
        "preview": "; ".join(preview_fields) if preview_fields else _safe_text(document_id)[:200],
    }


def query_data_management_cosmos_editor_documents(container_name, query_text=None, page_size=None, continuation_token=None, admin_user_id=None, admin_email=None):
    container_metadata, container = _get_cosmos_editor_container(container_name)
    query, is_empty_query = _normalize_cosmos_editor_query(query_text)
    safe_page_size = _safe_int(
        page_size,
        default=DATA_MANAGEMENT_COSMOS_EDITOR_MAX_PAGE_SIZE,
        minimum=1,
        maximum=DATA_MANAGEMENT_COSMOS_EDITOR_MAX_PAGE_SIZE,
    )
    safe_continuation_token = None if is_empty_query else _safe_text(continuation_token) or None
    started_at = time.perf_counter()

    query_iterable = container.query_items(
        query=query,
        enable_cross_partition_query=True,
        max_item_count=safe_page_size,
    )
    if hasattr(query_iterable, "by_page"):
        page_iterator = query_iterable.by_page(continuation_token=safe_continuation_token)
        try:
            page_items = list(next(page_iterator))
        except StopIteration:
            page_items = []
        next_continuation_token = None if is_empty_query else getattr(page_iterator, "continuation_token", None)
    else:
        page_items = list(query_iterable)[:safe_page_size]
        next_continuation_token = None

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    items = [
        _summarize_cosmos_editor_item(item, container_metadata)
        for item in page_items
    ]
    result = {
        "container": get_data_management_cosmos_editor_container_public_metadata(container_metadata),
        "query": {
            "mode": "empty" if is_empty_query else "custom",
            "page_size": safe_page_size,
            "query_hash": _hash_cosmos_editor_query(query if not is_empty_query else ""),
            "empty_query_limit_applied": is_empty_query,
        },
        "items": items,
        "count": len(items),
        "continuation_token": next_continuation_token,
        "has_more": bool(next_continuation_token),
        "duration_ms": duration_ms,
    }
    log_data_management_cosmos_editor_activity(
        admin_user_id,
        admin_email,
        "cosmos_editor_query_executed",
        "success",
        "Executed a Cosmos DB editor query.",
        {
            "container": container_metadata["name"],
            "query_mode": result["query"]["mode"],
            "page_size": safe_page_size,
            "returned_count": len(items),
            "has_more": bool(next_continuation_token),
            "duration_ms": duration_ms,
            "query_hash": result["query"]["query_hash"],
        },
    )
    return result


def get_data_management_cosmos_editor_container_public_metadata(container_metadata):
    return {
        "id": container_metadata["id"],
        "name": container_metadata["name"],
        "display_name": container_metadata["display_name"],
        "category": container_metadata["category"],
        "partition_key_path": container_metadata["partition_key_path"],
        "partition_key_field": container_metadata["partition_key_field"],
        "max_page_size": container_metadata["max_page_size"],
        "empty_query_limit": container_metadata["empty_query_limit"],
        "editable": container_metadata["editable"],
    }


def get_data_management_cosmos_editor_document(container_name, document_id, partition_key_value, admin_user_id=None, admin_email=None):
    container_metadata, container = _get_cosmos_editor_container(container_name)
    safe_document_id = _safe_text(document_id)
    if not safe_document_id:
        raise DataManagementCosmosEditorError("Choose a Cosmos DB document.")
    if partition_key_value is None:
        raise DataManagementCosmosEditorError("The selected document is missing its partition key value.")

    document = container.read_item(item=safe_document_id, partition_key=partition_key_value)
    current_partition_key_value = _get_document_path_value(document, container_metadata["partition_key_path"])
    result = {
        "container": get_data_management_cosmos_editor_container_public_metadata(container_metadata),
        "document": document,
        "id": safe_document_id,
        "partition_key": current_partition_key_value,
        "etag": document.get("_etag") if isinstance(document, dict) else None,
    }
    log_data_management_cosmos_editor_activity(
        admin_user_id,
        admin_email,
        "cosmos_editor_document_opened",
        "success",
        "Opened a Cosmos DB document in the editor.",
        {
            "container": container_metadata["name"],
            "document_id": safe_document_id,
            "partition_key_path": container_metadata["partition_key_path"],
        },
    )
    return result


def _summarize_cosmos_editor_changes(original_document, updated_document):
    if not isinstance(original_document, dict) or not isinstance(updated_document, dict):
        return {"changed_paths": [], "changed_count": 0, "added_count": 0, "removed_count": 0, "updated_count": 0}

    changed_paths = []
    added_count = 0
    removed_count = 0
    updated_count = 0

    def compare_values(original_value, updated_value, path):
        nonlocal added_count, removed_count, updated_count
        if isinstance(original_value, dict) and isinstance(updated_value, dict):
            all_keys = sorted(set(original_value.keys()) | set(updated_value.keys()))
            for key in all_keys:
                if key.startswith("_"):
                    continue
                child_path = f"{path}.{key}" if path else key
                if key not in original_value:
                    added_count += 1
                    changed_paths.append(child_path)
                    continue
                if key not in updated_value:
                    removed_count += 1
                    changed_paths.append(child_path)
                    continue
                compare_values(original_value.get(key), updated_value.get(key), child_path)
            return
        if original_value != updated_value:
            updated_count += 1
            changed_paths.append(path)

    compare_values(original_document, updated_document, "")
    return {
        "changed_paths": changed_paths[:50],
        "changed_count": len(changed_paths),
        "added_count": added_count,
        "removed_count": removed_count,
        "updated_count": updated_count,
        "truncated": len(changed_paths) > 50,
    }


def _validate_cosmos_editor_save_confirmation(confirmation_accepted, confirmation_phrase):
    if confirmation_accepted is not True:
        raise DataManagementCosmosEditorError("Confirm that you understand this Cosmos DB edit can damage system data.")
    if _safe_text(confirmation_phrase) != DATA_MANAGEMENT_COSMOS_EDITOR_CONFIRMATION_PHRASE:
        raise DataManagementCosmosEditorError("Type the required confirmation phrase before saving this Cosmos DB document.")


def save_data_management_cosmos_editor_document(container_name, document_id, partition_key_value, etag, document, confirmation_accepted=False, confirmation_phrase="", admin_user_id=None, admin_email=None):
    container_metadata, container = _get_cosmos_editor_container(container_name)
    safe_document_id = _safe_text(document_id)
    safe_etag = _safe_text(etag)
    if not safe_document_id:
        raise DataManagementCosmosEditorError("Choose a Cosmos DB document before saving.")
    if partition_key_value is None:
        raise DataManagementCosmosEditorError("The selected document is missing its partition key value.")
    if not safe_etag:
        raise DataManagementCosmosEditorError("The selected document is missing its ETag. Refresh the document before saving.")
    if not isinstance(document, dict):
        raise DataManagementCosmosEditorError("Cosmos DB document JSON must be an object.")

    _validate_cosmos_editor_save_confirmation(confirmation_accepted, confirmation_phrase)

    if _safe_text(document.get("id")) != safe_document_id:
        raise DataManagementCosmosEditorError("Document id cannot be changed in the Cosmos DB editor.")
    updated_partition_key_value = _get_document_path_value(document, container_metadata["partition_key_path"])
    if updated_partition_key_value != partition_key_value:
        raise DataManagementCosmosEditorError("Document partition key value cannot be changed in the Cosmos DB editor.")

    original_document = container.read_item(item=safe_document_id, partition_key=partition_key_value)
    change_summary = _summarize_cosmos_editor_changes(original_document, document)
    clean_document = _strip_cosmos_system_fields(copy.deepcopy(document))
    replace_target = safe_document_id
    if isinstance(original_document, dict) and original_document.get("_self"):
        replace_target = original_document
    saved_document = container.replace_item(
        item=replace_target,
        body=clean_document,
        etag=safe_etag,
        match_condition=MatchConditions.IfNotModified,
    )

    result = {
        "container": get_data_management_cosmos_editor_container_public_metadata(container_metadata),
        "document": saved_document,
        "id": safe_document_id,
        "partition_key": _get_document_path_value(saved_document, container_metadata["partition_key_path"]),
        "etag": saved_document.get("_etag") if isinstance(saved_document, dict) else None,
        "change_summary": change_summary,
    }
    log_data_management_cosmos_editor_activity(
        admin_user_id,
        admin_email,
        "cosmos_editor_document_saved",
        "success",
        "Saved a Cosmos DB document from the Data Management editor.",
        {
            "container": container_metadata["name"],
            "document_id": safe_document_id,
            "partition_key_path": container_metadata["partition_key_path"],
            "changed_count": change_summary["changed_count"],
            "added_count": change_summary["added_count"],
            "removed_count": change_summary["removed_count"],
            "updated_count": change_summary["updated_count"],
            "changed_paths": change_summary["changed_paths"],
            "changed_paths_truncated": change_summary["truncated"],
        },
    )
    return result


def _save_data_management_job(job):
    body = _strip_cosmos_system_fields(job)
    job_etag = job.get("_etag") if isinstance(job, dict) else None
    if job_etag and hasattr(cosmos_data_management_jobs_container, "replace_item"):
        try:
            saved = cosmos_data_management_jobs_container.replace_item(
                item=job.get("id"),
                body=body,
                etag=job_etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            if getattr(exc, "status_code", None) in {409, 412}:
                if job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP:
                    raise DataManagementBackupLeaseLostError(
                        "Backup job state was changed by another worker."
                    ) from exc
                raise DataManagementMigrationLeaseLostError(
                    "Migration job state was changed by another worker."
                ) from exc
            raise
    else:
        saved = cosmos_data_management_jobs_container.upsert_item(body)
    job.clear()
    job.update(saved)
    return job


def _set_job_progress(
    job,
    message,
    completed_steps,
    total_steps,
    current_step=None,
    status=DATA_MANAGEMENT_STATUS_RUNNING,
    allow_cancel_requested=False,
):
    total_steps = max(1, total_steps)
    _assert_data_management_job_lease(
        job,
        allow_cancel_requested=allow_cancel_requested,
    )
    completed_steps = max(0, min(completed_steps, total_steps))
    percent_complete = int((completed_steps / total_steps) * 100)
    now = _now_iso()
    job.update({
        "status": status,
        "updated_at": now,
        "last_heartbeat_at": now,
        "last_progress_at": now,
        "last_message": message,
        "progress": {
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "current_step": current_step,
            "percent_complete": percent_complete,
        },
    })
    saved_job = _save_data_management_job(job)
    _record_data_management_job_event(
        saved_job.get("id"),
        current_step or "progress",
        saved_job,
        status=status,
        message=message,
        details={"progress": saved_job.get("progress") if isinstance(saved_job.get("progress"), dict) else {}},
    )
    return saved_job


def _get_backup_fernet(settings, key_reference=None):
    if not settings.get("encryption_enabled"):
        return None
    resolved_reference = _safe_text(key_reference or settings.get("encryption_key_reference"))
    if not resolved_reference:
        raise ValueError("Backup encryption is enabled but no backup encryption key has been configured.")

    try:
        if str(resolved_reference).lower().startswith("https://"):
            from functions_keyvault import retrieve_secret_from_key_vault_by_reference

            key_value = retrieve_secret_from_key_vault_by_reference(resolved_reference)
        else:
            from functions_keyvault import retrieve_secret_from_key_vault_by_full_name

            key_value = retrieve_secret_from_key_vault_by_full_name(resolved_reference)
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


def _upload_json_artifact(
    container_client,
    blob_name,
    payload,
    fernet=None,
    backup_job=None,
    backup_settings=None,
    heartbeat_message="",
):
    data = json.dumps(payload, default=_json_default, ensure_ascii=False, indent=2).encode("utf-8")
    content_type = "application/json"
    final_blob_name = _encrypted_blob_name(blob_name, fernet)
    if fernet:
        data = fernet.encrypt(data)
        content_type = "application/octet-stream"
    def upload():
        container_client.upload_blob(
            name=final_blob_name,
            data=data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    if isinstance(backup_job, dict):
        _run_backup_transfer_with_heartbeat(
            backup_job,
            backup_settings or {},
            heartbeat_message or "Uploading backup JSON artifact",
            upload,
        )
    else:
        upload()
    return {
        "path": final_blob_name,
        "bytes": len(data),
        "encrypted": bool(fernet),
    }


def _write_jsonl_artifact(
    container_client,
    blob_name,
    records,
    fernet=None,
    backup_job=None,
    backup_settings=None,
    heartbeat_message="",
):
    temp_path = None
    item_count = 0
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False) as temp_file:
            temp_path = temp_file.name
            last_heartbeat_at = time.monotonic()
            for record in records:
                line = json.dumps(record, default=_json_default, ensure_ascii=False, separators=(",", ":"))
                if fernet:
                    line = fernet.encrypt(line.encode("utf-8")).decode("utf-8")
                temp_file.write(line)
                temp_file.write("\n")
                item_count += 1
                if (
                    isinstance(backup_job, dict) and
                    time.monotonic() - last_heartbeat_at >=
                    DATA_MANAGEMENT_BACKUP_HEARTBEAT_INTERVAL_SECONDS
                ):
                    _persist_backup_heartbeat(
                        backup_job,
                        backup_settings or {},
                        heartbeat_message or "Staging backup JSONL artifact",
                    )
                    last_heartbeat_at = time.monotonic()

        final_blob_name = _encrypted_blob_name(blob_name, fernet)
        content_type = "application/octet-stream" if fernet else "application/x-jsonlines"
        def upload():
            with open(temp_path, "rb") as upload_file:
                container_client.upload_blob(
                    name=final_blob_name,
                    data=upload_file,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type),
                )

        if isinstance(backup_job, dict):
            _run_backup_transfer_with_heartbeat(
                backup_job,
                backup_settings or {},
                heartbeat_message or "Uploading backup artifact",
                upload,
            )
        else:
            upload()
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
    backup_plan = job.get("backup_plan") if isinstance(job.get("backup_plan"), dict) else {}
    prefix = _safe_text(
        backup_plan.get("backup_storage_path_prefix") or settings.get("backup_storage_path_prefix"),
        "simplechat-backups",
    ).strip("/")
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


def _copy_source_blob(
    target_container_client,
    source_blob_client,
    target_blob_name,
    fernet=None,
    backup_job=None,
    backup_settings=None,
    heartbeat_message="",
):
    def download():
        return source_blob_client.download_blob().readall()

    if isinstance(backup_job, dict):
        blob_bytes = _run_backup_transfer_with_heartbeat(
            backup_job,
            backup_settings or {},
            heartbeat_message or "Downloading source blob for backup",
            download,
        )
    else:
        blob_bytes = download()
    final_blob_name = _encrypted_blob_name(target_blob_name, fernet)
    if fernet:
        blob_bytes = fernet.encrypt(blob_bytes)

    def upload():
        target_container_client.upload_blob(
            name=final_blob_name,
            data=blob_bytes,
            overwrite=True,
            content_settings=ContentSettings(content_type="application/octet-stream"),
        )

    if isinstance(backup_job, dict):
        _run_backup_transfer_with_heartbeat(
            backup_job,
            backup_settings or {},
            heartbeat_message or "Uploading source blob backup artifact",
            upload,
        )
    else:
        upload()
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


def _get_data_management_backup_item_states_container():
    """Return the dedicated sidecar container without touching source records."""
    container = getattr(app_config, "cosmos_data_management_backup_item_states_container", None)
    if container is None:
        raise DataManagementSettingsValidationError(
            "Data Management backup item-state storage is not initialized."
        )
    return container


def _build_backup_item_state_id(source_scope, lineage_id, service, resource_name, source_identity):
    """Create a stable latest-only state id from non-content source metadata."""
    encoded = json.dumps(
        [
            _safe_text(source_scope),
            _safe_text(lineage_id),
            _safe_text(service),
            _safe_text(resource_name),
            _safe_text(source_identity),
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"backup-item-state-{hashlib.sha256(encoded).hexdigest()}"


def _build_backup_source_identity(*parts):
    """Return a stable source identity without retaining source content in state."""
    encoded = json.dumps(
        [_safe_text(part) for part in parts],
        ensure_ascii=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _build_backup_source_version(source_value):
    """Hash source version metadata or content when a service has no native ETag."""
    encoded = json.dumps(
        source_value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _read_backup_latest_item_state(source_scope, lineage_id, service, resource_name, source_identity):
    """Read one sidecar latest-state document without querying or changing its source."""
    container = _get_data_management_backup_item_states_container()
    state_id = _build_backup_item_state_id(
        source_scope,
        lineage_id,
        service,
        resource_name,
        source_identity,
    )
    try:
        return container.read_item(item=state_id, partition_key=source_scope)
    except (CosmosResourceNotFoundError, ResourceNotFoundError, KeyError):
        return None
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            return None
        raise


def _is_backup_item_due_for_export(backup_plan, latest_state, source_version, backup_job_id=""):
    """Select only items whose latest verified state differs from the source."""
    if (
        isinstance(latest_state, dict) and
        _safe_text(latest_state.get("job_id")) == _safe_text(backup_job_id) and
        _safe_text(latest_state.get("status")).lower() == "succeeded" and
        _safe_text(latest_state.get("source_version")) == _safe_text(source_version)
    ):
        return False
    if _safe_text((backup_plan or {}).get("backup_type")) == DATA_MANAGEMENT_BACKUP_FULL:
        return True
    if not isinstance(latest_state, dict):
        return True
    latest_status = _safe_text(latest_state.get("status")).lower()
    if latest_status not in {"succeeded", "skipped"}:
        return True
    return _safe_text(latest_state.get("source_version")) != _safe_text(source_version)


def _record_backup_latest_item_state(
    job,
    service,
    resource_name,
    source_identity,
    source_version,
    status,
    checkpoint_id="",
    artifact_path="",
    failure_summary="",
    skip_summary="",
):
    """Upsert one latest-only sidecar state document after a durable outcome."""
    source_scope = _get_backup_source_scope(job)
    lineage_id = _build_backup_lineage_id(job.get("backup_plan"))
    state_id = _build_backup_item_state_id(
        source_scope,
        lineage_id,
        service,
        resource_name,
        source_identity,
    )
    existing_state = _read_backup_latest_item_state(
        source_scope,
        lineage_id,
        service,
        resource_name,
        source_identity,
    )
    current_cutoff = _parse_iso_datetime(
        ((job.get("backup_plan") or {}).get("source_cutoff_at"))
    )
    existing_cutoff = _parse_iso_datetime(
        (existing_state or {}).get("source_cutoff_at")
    )
    if (
        isinstance(existing_state, dict) and
        _safe_text(existing_state.get("job_id")) != _safe_text(job.get("id")) and
        existing_cutoff and current_cutoff and existing_cutoff > current_cutoff
    ):
        return existing_state
    now = _now_iso()
    body = {
        "id": state_id,
        "type": DATA_MANAGEMENT_BACKUP_LATEST_ITEM_STATE_TYPE,
        "source_scope": source_scope,
        "backup_lineage_id": lineage_id,
        "service": _safe_text(service),
        "resource_name": _safe_text(resource_name),
        "source_identity": _safe_text(source_identity),
        "source_version": _safe_text(source_version),
        "source_cutoff_at": _safe_text(
            ((job.get("backup_plan") or {}).get("source_cutoff_at"))
        ),
        "job_id": _safe_text(job.get("id")),
        "attempt_id": _safe_text(job.get("backup_attempt_id")),
        "lease_generation": _safe_int(job.get("lease_generation"), default=0),
        "artifact_checkpoint_id": _safe_text(checkpoint_id),
        "artifact_path": _safe_text(artifact_path),
        "status": _safe_text(status),
        "timestamp": now,
        "updated_at": now,
        "failure_summary": _safe_text(failure_summary)[:500],
        "skip_summary": _safe_text(skip_summary)[:500],
    }
    return _get_data_management_backup_item_states_container().upsert_item(body)


def _queue_backup_latest_item_state_update(
    pending_updates,
    source_item,
    status,
    checkpoint_id="",
    artifact_path="",
    failure_summary="",
    skip_summary="",
):
    """Queue a sidecar acknowledgment until its job-manifest batch is durable."""
    pending_updates.append({
        "source_identity": _safe_text((source_item or {}).get("source_identity")),
        "source_version": _safe_text((source_item or {}).get("source_version")),
        "status": _safe_text(status),
        "checkpoint_id": _safe_text(checkpoint_id),
        "artifact_path": _safe_text(artifact_path),
        "failure_summary": _safe_text(failure_summary)[:500],
        "skip_summary": _safe_text(skip_summary)[:500],
    })


def _flush_backup_latest_item_state_updates(job, service, resource_name, pending_updates):
    """Advance latest-only state only after a durable job-manifest checkpoint exists."""
    for update in list(pending_updates or []):
        _assert_backup_job_lease(job)
        _record_backup_latest_item_state(
            job,
            service,
            resource_name,
            update.get("source_identity"),
            update.get("source_version"),
            update.get("status"),
            checkpoint_id=update.get("checkpoint_id"),
            artifact_path=update.get("artifact_path"),
            failure_summary=update.get("failure_summary"),
            skip_summary=update.get("skip_summary"),
        )
    if isinstance(pending_updates, list):
        pending_updates.clear()


def _sync_backup_latest_item_state_from_manifest(job, resource_name):
    """Rebuild missing sidecar acknowledgments from durable per-batch job manifests."""
    query = (
        "SELECT * FROM c WHERE c.job_id = @job_id AND c.type = @type "
        "AND c.resource_name = @resource_name ORDER BY c.created_at ASC"
    )
    parameters = [
        {"name": "@job_id", "value": _safe_text(job.get("id"))},
        {"name": "@type", "value": DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_TYPE},
        {"name": "@resource_name", "value": _safe_text(resource_name)},
    ]
    batches = cosmos_data_management_job_items_container.query_items(
        query=query,
        parameters=parameters,
        partition_key=_safe_text(job.get("id")),
        max_item_count=DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE,
    )
    for batch in batches:
        for entry in batch.get("entries") or []:
            status = _safe_text((entry or {}).get("status")).lower()
            if status not in {"succeeded", "skipped", "failed"}:
                continue
            _assert_backup_job_lease(job)
            _record_backup_latest_item_state(
                job,
                _safe_text((entry or {}).get("service")),
                resource_name,
                _safe_text((entry or {}).get("source_identity")),
                _safe_text((entry or {}).get("source_version")),
                status,
                checkpoint_id=_safe_text((entry or {}).get("artifact_checkpoint_id")),
                artifact_path=_safe_text((entry or {}).get("artifact_path")),
                failure_summary=_safe_text((entry or {}).get("failure_summary")),
                skip_summary=_safe_text((entry or {}).get("skip_summary")),
            )


def _sanitize_backup_manifest_entry(entry):
    """Keep job-manifest entries bounded and free of source content or credentials."""
    allowed_fields = {
        "service",
        "resource_name",
        "source_identity",
        "source_version",
        "status",
        "job_id",
        "attempt_id",
        "lease_generation",
        "artifact_checkpoint_id",
        "artifact_path",
        "bytes",
        "recorded_at",
        "failure_summary",
        "skip_summary",
    }
    sanitized = {
        field_name: _sanitize_activity_value((entry or {}).get(field_name))
        for field_name in allowed_fields
        if (entry or {}).get(field_name) is not None
    }
    sanitized["recorded_at"] = _safe_text(sanitized.get("recorded_at")) or _now_iso()
    sanitized["failure_summary"] = _safe_text(sanitized.get("failure_summary"))[:500]
    sanitized["skip_summary"] = _safe_text(sanitized.get("skip_summary"))[:500]
    return sanitized


def _sanitize_data_management_job_item_text(value):
    """Redact token-bearing operational detail before it reaches job timelines."""
    return _sanitize_data_management_backup_text(value)


def _sanitize_data_management_job_item_details(details):
    if not isinstance(details, dict):
        return {}
    sanitized = _sanitize_activity_value(details)

    def redact(value):
        if isinstance(value, dict):
            return {key: redact(nested_value) for key, nested_value in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str):
            return _sanitize_data_management_job_item_text(value)
        return value

    return redact(sanitized)


def _write_backup_manifest_batch(job_id, resource_name, entries):
    """Write a bounded batch of item outcomes retained with the backup job."""
    normalized_entries = [
        _sanitize_backup_manifest_entry(entry)
        for entry in (entries or [])
        if isinstance(entry, dict)
    ]
    if not normalized_entries:
        return None
    now = _now_iso()
    return cosmos_data_management_job_items_container.create_item(body={
        "id": (
            f"{_safe_job_item_id_part(job_id)}:backup-manifest:"
            f"{_safe_job_item_id_part(resource_name)}:{uuid.uuid4().hex}"
        ),
        "job_id": _safe_text(job_id),
        "type": DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_TYPE,
        "resource_name": _safe_text(resource_name),
        "created_at": now,
        "updated_at": now,
        "entry_count": len(normalized_entries),
        "entries": normalized_entries,
    })


def _create_backup_manifest_writer(job_id, resource_name):
    """Buffer per-item outcomes so checkpoint state remains bounded."""
    buffer = []

    def append(entry):
        buffer.append(entry)

    def flush():
        if not buffer:
            return None
        pending_entries = list(buffer)
        saved = _write_backup_manifest_batch(job_id, resource_name, pending_entries)
        del buffer[:len(pending_entries)]
        return saved

    return append, flush, buffer


def _backup_resource_metrics(resource):
    if not isinstance(resource, dict):
        return {}
    progress = resource.get("progress") if isinstance(resource.get("progress"), dict) else {}
    result = resource.get("result") if isinstance(resource.get("result"), dict) else {}
    if not result:
        return progress
    metrics = copy.deepcopy(progress)
    metrics.update(result)
    return metrics


def _update_backup_state_totals(state):
    """Aggregate resource counters without carrying unbounded item detail on a job."""
    totals = {
        "processed_count": 0,
        "exported_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "bytes": 0,
        "checkpoint_count": 0,
        "request_units": 0.0,
        "retry_attempt_count": 0,
        "throttle_count": 0,
    }
    current_container = ""
    started_at_values = []
    for resource in (state.get("resources") or {}).values():
        metrics = _backup_resource_metrics(resource)
        totals["processed_count"] += _safe_int(metrics.get("processed_count"), default=0, minimum=0)
        totals["exported_count"] += _safe_int(
            metrics.get("item_count", metrics.get("exported_count")),
            default=0,
            minimum=0,
        )
        totals["skipped_count"] += _safe_int(metrics.get("skipped_count"), default=0, minimum=0)
        totals["failed_count"] += _safe_int(metrics.get("failed_count"), default=0, minimum=0)
        totals["bytes"] += _safe_int(metrics.get("bytes"), default=0, minimum=0)
        totals["checkpoint_count"] += _safe_int(metrics.get("checkpoint_count"), default=0, minimum=0)
        try:
            totals["request_units"] += max(0.0, float(metrics.get("request_units") or 0.0))
        except (TypeError, ValueError) as exc:
            logging.debug(
                "Ignoring invalid backup request_units metric value %r during totals aggregation: %s",
                metrics.get("request_units"),
                exc,
            )
        totals["retry_attempt_count"] += _safe_int(
            metrics.get("retry_attempt_count"),
            default=0,
            minimum=0,
        )
        totals["throttle_count"] += _safe_int(
            metrics.get("throttle_count"),
            default=0,
            minimum=0,
        )
        resource_started_at = _parse_iso_datetime(resource.get("started_at"))
        if resource_started_at:
            started_at_values.append(resource_started_at)
        if resource.get("status") == "in_progress" and metrics.get("current_container"):
            current_container = _safe_text(metrics.get("current_container"))
    started_at = min(started_at_values) if started_at_values else None
    elapsed_seconds = max(
        0.001,
        (_now_utc() - started_at).total_seconds() if started_at else 0.001,
    )
    totals["request_units"] = round(totals["request_units"], 3)
    totals["elapsed_seconds"] = round(elapsed_seconds, 3)
    totals["records_per_second"] = round(totals["processed_count"] / elapsed_seconds, 3)
    totals["request_units_per_second"] = round(totals["request_units"] / elapsed_seconds, 3)
    state["totals"] = totals
    state["telemetry"] = {
        "current_container": current_container,
        "checkpoint_position": totals["checkpoint_count"],
        "records_processed": totals["processed_count"],
        "bytes": totals["bytes"],
        "request_units": totals["request_units"],
        "retries": totals["retry_attempt_count"],
        "throttles": totals["throttle_count"],
        "elapsed_seconds": totals["elapsed_seconds"],
        "records_per_second": totals["records_per_second"],
        "request_units_per_second": totals["request_units_per_second"],
    }
    return totals


def _append_backup_state_summary(state, field_name, summary):
    """Append a bounded failure or skip summary that is safe for admin progress APIs."""
    if not isinstance(state, dict):
        return
    values = state.setdefault(field_name, [])
    if not isinstance(values, list):
        values = []
        state[field_name] = values
    values.append(_sanitize_activity_value(summary if isinstance(summary, dict) else {}))
    del values[:-DATA_MANAGEMENT_BACKUP_MAX_PUBLIC_ITEM_SUMMARIES]


def _build_backup_checkpoint_id(job, resource_name, batch_number):
    return (
        f"{_safe_text(job.get('id'))}:"
        f"{_safe_job_item_id_part(resource_name)}:{int(batch_number):06d}"
    )


def _build_backup_batch_identity(job, resource_name, source_batch):
    """Create a stable artifact identity from item metadata, never source content."""
    identities = sorted([
        {
            "source_identity": _safe_text(source_item.get("source_identity")),
            "source_version": _safe_text(source_item.get("source_version")),
        }
        for source_item in (source_batch or [])
        if isinstance(source_item, dict)
    ], key=lambda item: (item["source_identity"], item["source_version"]))
    return hashlib.sha256(json.dumps(
        {
            "job_id": _safe_text((job or {}).get("id")),
            "resource_name": _safe_text(resource_name),
            "items": identities,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _build_backup_checkpoint_summary(checkpoint, batch_number, artifact_path=""):
    """Keep only a small rolling set of artifact checkpoint identifiers in state."""
    existing = checkpoint if isinstance(checkpoint, dict) else {}
    completed_batches = _safe_int(existing.get("completed_batch_count"), default=0, minimum=0)
    recent = list(existing.get("recent_batches") or [])
    recent.append({
        "batch_number": int(batch_number),
        "artifact_path": _safe_text(artifact_path),
    })
    del recent[:-DATA_MANAGEMENT_BACKUP_MAX_RECENT_CHECKPOINTS]
    return {
        "next_batch_number": int(batch_number) + 1,
        "completed_batch_count": completed_batches + 1,
        "recent_batches": recent,
    }


def _persist_backup_checkpoint(
    job,
    state,
    settings,
    resource_name,
    progress,
    checkpoint,
    message,
    allow_cancel_requested=False,
):
    """Save a bounded backup resource checkpoint and renew its fenced lease."""
    _assert_backup_job_lease(job, allow_cancel_requested=allow_cancel_requested)
    update_backup_resource(state, resource_name, progress, checkpoint=checkpoint)
    _update_backup_state_totals(state)
    now = _now_utc()
    state["phase"] = _safe_text(message)
    state["last_progress_at"] = now.isoformat()
    job.update({
        "backup_state": state,
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "last_progress_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": _safe_text(message),
    })
    _save_data_management_job(job)
    saved_state = job.get("backup_state") if isinstance(job.get("backup_state"), dict) else state
    if saved_state is not state:
        state.clear()
        state.update(copy.deepcopy(saved_state))
    return state


def _persist_backup_state(job, state, settings, message, allow_cancel_requested=False):
    """Persist backup-level phase changes without creating a resource checkpoint."""
    _assert_backup_job_lease(job, allow_cancel_requested=allow_cancel_requested)
    _update_backup_state_totals(state)
    now = _now_utc()
    state["updated_at"] = now.isoformat()
    job.update({
        "backup_state": state,
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": _safe_text(message),
    })
    _save_data_management_job(job)
    saved_state = job.get("backup_state") if isinstance(job.get("backup_state"), dict) else state
    if saved_state is not state:
        state.clear()
        state.update(copy.deepcopy(saved_state))
    return state


def _persist_backup_heartbeat(job, settings, message):
    """Renew job and source leases without advancing a backup checkpoint boundary."""
    _assert_backup_job_lease(job)
    now = _now_utc()
    job.update({
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": _safe_text(message),
    })
    return _save_data_management_job(job)


def _complete_backup_resource_checkpoint(job, state, settings, resource_name, result, message):
    """Mark a backup resource complete only after all recorded artifact batches verify."""
    _assert_backup_job_lease(job)
    complete_backup_resource(state, resource_name, result=result)
    _update_backup_state_totals(state)
    now = _now_utc()
    state["last_progress_at"] = now.isoformat()
    job.update({
        "backup_state": state,
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "last_progress_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": _safe_text(message),
    })
    _save_data_management_job(job)
    saved_state = job.get("backup_state") if isinstance(job.get("backup_state"), dict) else state
    if saved_state is not state:
        state.clear()
        state.update(copy.deepcopy(saved_state))
    return state


def _skip_backup_resource_checkpoint(job, state, settings, resource_name, reason, message):
    """Persist an intentional resource skip as a completed durable boundary."""
    _assert_backup_job_lease(job)
    start_backup_resource(state, resource_name, "export")
    skip_backup_resource(state, resource_name, reason)
    _update_backup_state_totals(state)
    now = _now_utc()
    job.update({
        "backup_state": state,
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": _safe_text(message),
    })
    _save_data_management_job(job)
    saved_state = job.get("backup_state") if isinstance(job.get("backup_state"), dict) else state
    if saved_state is not state:
        state.clear()
        state.update(copy.deepcopy(saved_state))
    return state


def _fail_backup_resource_checkpoint(
    job,
    state,
    settings,
    resource_name,
    error_message,
    message,
    result=None,
):
    """Persist a resource-level backup failure while allowing other resources to continue."""
    _assert_backup_job_lease(job)
    resource = fail_backup_resource(state, resource_name, _safe_text(error_message)[:1000])
    if isinstance(result, dict):
        resource["result"] = copy.deepcopy(result)
    _update_backup_state_totals(state)
    now = _now_utc()
    job.update({
        "backup_state": state,
        "updated_at": now.isoformat(),
        "last_heartbeat_at": now.isoformat(),
        "lease_expires_at": (
            now + timedelta(seconds=_get_data_management_job_lease_seconds(settings))
        ).isoformat(),
        "last_message": _safe_text(message),
    })
    _save_data_management_job(job)
    saved_state = job.get("backup_state") if isinstance(job.get("backup_state"), dict) else state
    if saved_state is not state:
        state.clear()
        state.update(copy.deepcopy(saved_state))
    return state


def _append_backup_warning(state, warning):
    """Keep warning text bounded in durable job state and the admin progress response."""
    if not isinstance(state, dict):
        return
    warnings = state.setdefault("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        state["warnings"] = warnings
    safe_warning = _safe_text(warning)[:500]
    if safe_warning:
        warnings.append(safe_warning)
    del warnings[:-DATA_MANAGEMENT_BACKUP_MAX_PUBLIC_ITEM_SUMMARIES]


def _backup_state_resource_artifacts(state):
    """Return completed resource results for the final manifest and job result."""
    artifacts = []
    for resource_name, resource in (state.get("resources") or {}).items():
        if not isinstance(resource, dict):
            continue
        result = resource.get("result") if isinstance(resource.get("result"), dict) else {}
        if not result:
            continue
        artifact = copy.deepcopy(result)
        artifact.setdefault("name", resource_name)
        artifact.setdefault("status", resource.get("status"))
        artifacts.append(artifact)
    return artifacts


def _assert_backup_execution_settings(settings, backup_plan):
    """Refuse a resume when backup artifacts would move to a different destination."""
    plan = backup_plan if isinstance(backup_plan, dict) else {}
    if (
        _safe_text(plan.get("backup_storage_container_name")) and
        _safe_text(plan.get("backup_storage_container_name")) !=
        _safe_text((settings or {}).get("backup_storage_container_name"))
    ):
        raise DataManagementSettingsValidationError(
            "Backup storage container changed after the job was queued. Queue a new backup job."
        )
    if (
        _safe_text(plan.get("backup_storage_path_prefix")).strip("/") and
        _safe_text(plan.get("backup_storage_path_prefix")).strip("/") !=
        _safe_text((settings or {}).get("backup_storage_path_prefix")).strip("/")
    ):
        raise DataManagementSettingsValidationError(
            "Backup storage path changed after the job was queued. Queue a new backup job."
        )
    if (
        _safe_text(plan.get("storage_identity")) and
        _safe_text(plan.get("storage_identity")) != _build_backup_storage_identity(settings)
    ):
        raise DataManagementSettingsValidationError(
            "Backup storage identity changed after the job was queued. Queue a new backup job."
        )
    if "encryption_enabled" in plan and _safe_bool(plan.get("encryption_enabled")) != _safe_bool(
        (settings or {}).get("encryption_enabled")
    ):
        raise DataManagementSettingsValidationError(
            "Backup encryption settings changed after the job was queued. Queue a new backup job."
        )
    expected_key_reference = _safe_text(plan.get("encryption_key_reference"))
    expected_key_fingerprint = _safe_text(plan.get("encryption_key_fingerprint"))
    expected_key_storage = _safe_text(plan.get("encryption_key_storage"))
    comparison_reference = (
        expected_key_reference if expected_key_storage == "key_vault" else
        _safe_text((settings or {}).get("encryption_key_reference"))
    )
    actual_key_fingerprint = _build_backup_encryption_key_fingerprint(
        settings,
        key_reference=comparison_reference,
    )
    if expected_key_fingerprint and expected_key_fingerprint != actual_key_fingerprint:
        raise DataManagementSettingsValidationError(
            "Backup encryption key identity changed after the job was queued. Queue a new backup job."
        )


def _is_backup_value_within_cutoff(value, source_cutoff_at):
    """Exclude source versions that appeared after the immutable backup cutoff."""
    cutoff = _parse_iso_datetime(source_cutoff_at)
    if cutoff is None or value is None:
        return True
    if isinstance(value, (int, float)):
        timestamp = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, datetime):
        timestamp = value
    else:
        timestamp = _parse_iso_datetime(value)
    if timestamp is None:
        return True
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc) <= cutoff


def _get_backup_exception_status_code(error):
    """Read an Azure SDK status code without retaining provider response content."""
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        status_code = getattr(getattr(error, "response", None), "status_code", None)
    return _safe_int(status_code, default=0, minimum=0) or None


def _get_backup_exception_headers(error):
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", None)
    return headers if hasattr(headers, "items") else {}


def _get_backup_header_value(headers, header_name):
    for candidate_name, candidate_value in (headers or {}).items():
        if _safe_text(candidate_name).lower() == header_name.lower():
            return candidate_value
    return None


def _get_backup_retry_after_seconds(error):
    """Honor Azure retry guidance while bounding a worker's cooperative delay."""
    headers = _get_backup_exception_headers(error)
    for header_name in ("x-ms-retry-after-ms", "retry-after-ms"):
        try:
            value = float(_get_backup_header_value(headers, header_name)) / 1000.0
        except (TypeError, ValueError):
            continue
        if value > 0:
            return min(DATA_MANAGEMENT_BACKUP_MAX_RETRY_DELAY_SECONDS, value)

    retry_after = _get_backup_header_value(headers, "retry-after")
    try:
        value = float(retry_after)
        if value > 0:
            return min(DATA_MANAGEMENT_BACKUP_MAX_RETRY_DELAY_SECONDS, value)
    except (TypeError, ValueError):
        try:
            parsed = parsedate_to_datetime(str(retry_after))
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delay = (parsed.astimezone(timezone.utc) - _now_utc()).total_seconds()
        return min(DATA_MANAGEMENT_BACKUP_MAX_RETRY_DELAY_SECONDS, delay) if delay > 0 else None
    return None


def _is_retryable_backup_cosmos_error(error):
    status_code = _get_backup_exception_status_code(error)
    return (
        status_code is None or
        status_code in {408, 429, 449} or
        500 <= status_code <= 599
    )


def _get_backup_retry_delay(error, attempt):
    """Use capped exponential backoff plus jitter, respecting Retry-After floors."""
    exponential_delay = min(
        DATA_MANAGEMENT_BACKUP_MAX_RETRY_DELAY_SECONDS,
        float(2 ** max(0, _safe_int(attempt, default=1, minimum=1) - 1)),
    )
    retry_after = _get_backup_retry_after_seconds(error)
    base_delay = max(exponential_delay, retry_after or 0.0)
    jitter = random.uniform(0.0, min(1.0, max(0.1, base_delay * 0.2)))
    return min(DATA_MANAGEMENT_BACKUP_MAX_RETRY_DELAY_SECONDS, base_delay + jitter)


def _iter_backup_cosmos_source_items(
    container,
    artifact,
    backup_plan,
    telemetry_callback=None,
    cancel_event=None,
):
    """Read one deterministic, bounded Cosmos page at a time without source mutation."""
    source_cutoff_epoch = _safe_int(
        (backup_plan or {}).get("cosmos_source_cutoff_epoch"),
        default=0,
        minimum=0,
    )
    container_name = _safe_text(getattr(app_config, artifact["container_name_attr"], artifact["name"]))
    retry_count = _get_backup_retry_count({}, backup_plan)
    # Keep the ordered source query compatible with existing default indexes.
    # The immutable cutoff is still applied per streamed item below.
    query = "SELECT * FROM c ORDER BY c.id"
    parameters = []

    def report_telemetry(values):
        if callable(telemetry_callback):
            telemetry_callback(values if isinstance(values, dict) else {})

    def response_hook(headers, _response):
        request_units = _get_cosmos_response_request_units(headers)
        if request_units:
            report_telemetry({"request_units": request_units})

    def normalize_item(raw_item):
        if not isinstance(raw_item, dict):
            return None
        source_timestamp = _safe_int(raw_item.get("_ts"), default=0, minimum=0)
        if source_cutoff_epoch and source_timestamp > source_cutoff_epoch:
            return None
        record = _strip_cosmos_system_fields(raw_item)
        partition_key = _get_document_path_value(record, artifact["partition_key_path"])
        source_identity = _build_backup_source_identity(
            "cosmos",
            container_name,
            record.get("id"),
            partition_key,
        )
        source_version = _build_backup_source_version({
            "etag": raw_item.get("_etag"),
            "ts": raw_item.get("_ts"),
            "record": record,
        })
        return {
            "payload": record,
            "source_identity": source_identity,
            "source_version": source_version,
        }

    continuation_token = None
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise DataManagementBackupCanceledError(
                "Cosmos source export stopped after backup cancellation or lease loss."
            )
        page_completed = False
        for attempt in range(1, retry_count + 1):
            try:
                source_iterable = container.query_items(
                    query=query,
                    parameters=parameters,
                    enable_cross_partition_query=True,
                    max_item_count=DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE,
                    populate_query_metrics=True,
                    response_hook=response_hook,
                )
                if hasattr(source_iterable, "by_page"):
                    page_iterator = source_iterable.by_page(
                        continuation_token=continuation_token,
                    )
                    try:
                        source_page = list(next(page_iterator))
                    except StopIteration:
                        return
                    normalized_page = [
                        item for item in (normalize_item(raw_item) for raw_item in source_page)
                        if item is not None
                    ]
                    normalized_page.sort(
                        key=lambda item: (item["source_identity"], item["source_version"]),
                    )
                    report_telemetry({"source_page_count": 1})
                    for source_item in normalized_page:
                        yield source_item
                    continuation_token = getattr(page_iterator, "continuation_token", None)
                    page_completed = True
                    break

                # Lightweight test doubles may not expose Cosmos paging. Keep their
                # staging bounded even though production uses continuation pages.
                buffered_items = []
                for raw_item in source_iterable:
                    normalized_item = normalize_item(raw_item)
                    if normalized_item is None:
                        continue
                    buffered_items.append(normalized_item)
                    if len(buffered_items) < DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE:
                        continue
                    buffered_items.sort(
                        key=lambda item: (item["source_identity"], item["source_version"]),
                    )
                    report_telemetry({"source_page_count": 1})
                    for source_item in buffered_items:
                        yield source_item
                    buffered_items = []
                if buffered_items:
                    buffered_items.sort(
                        key=lambda item: (item["source_identity"], item["source_version"]),
                    )
                    report_telemetry({"source_page_count": 1})
                    for source_item in buffered_items:
                        yield source_item
                return
            except (DataManagementBackupCanceledError, DataManagementBackupLeaseLostError):
                raise
            except Exception as exc:
                if not _is_retryable_backup_cosmos_error(exc) or attempt >= retry_count:
                    log_event(
                        "[DataManagement] Cosmos backup source page read failed.",
                        {
                            "container": container_name,
                            "status_code": _get_backup_exception_status_code(exc),
                            "error": str(exc),
                        },
                        level=logging.WARNING,
                    )
                    raise
                status_code = _get_backup_exception_status_code(exc)
                retry_delay = _get_backup_retry_delay(exc, attempt)
                report_telemetry({
                    "source_retry_attempt_count": 1,
                    "source_throttle_count": 1 if status_code in {429, 449} else 0,
                    "last_retry_delay_seconds": round(retry_delay, 3),
                })
                if cancel_event is not None:
                    if cancel_event.wait(retry_delay):
                        raise DataManagementBackupCanceledError(
                            "Cosmos source export stopped during retry backoff."
                        )
                else:
                    time.sleep(retry_delay)
        if not page_completed:
            return
        if not continuation_token:
            return


def _iter_backup_search_source_items(search_client, artifact, backup_plan):
    """Yield normalized AI Search documents while respecting the immutable cutoff."""
    source_cutoff = (backup_plan or {}).get("source_cutoff_at")
    results = search_client.search(search_text="*", include_total_count=True)
    for result in results:
        document = {
            key: value
            for key, value in dict(result).items()
            if not str(key).startswith("@search.")
        }
        if not _is_backup_value_within_cutoff(document.get("upload_date"), source_cutoff):
            continue
        source_identity = _build_backup_source_identity(
            "ai_search",
            artifact["index_name"],
            document.get("id") or _build_backup_source_version(document),
        )
        yield {
            "payload": document,
            "source_identity": source_identity,
            "source_version": _build_backup_source_version(document),
        }


def _build_backup_manifest_entry(job, service, resource_name, source_item, status, **details):
    """Build a secret-free outcome record for backup job-item manifest storage."""
    return {
        "service": service,
        "resource_name": resource_name,
        "source_identity": source_item.get("source_identity"),
        "source_version": source_item.get("source_version"),
        "status": status,
        "job_id": job.get("id"),
        "attempt_id": job.get("backup_attempt_id"),
        "lease_generation": job.get("lease_generation"),
        "recorded_at": _now_iso(),
        **details,
    }


def _stage_backup_jsonl_batch(
    container_client,
    batch_blob_name,
    source_batch,
    fernet,
    retry_count,
    cancel_event=None,
):
    """Stage one bounded JSONL artifact without allowing a worker to mutate job state."""
    started_at = time.perf_counter()
    retry_attempt_count = 0
    throttle_count = 0
    retry_delay_seconds = 0.0
    last_error = None
    for attempt in range(1, retry_count + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise DataManagementBackupCanceledError(
                "Backup batch staging stopped after cancellation or lease loss."
            )
        try:
            upload = _write_jsonl_artifact(
                container_client,
                batch_blob_name,
                (source_item["payload"] for source_item in source_batch),
                fernet=fernet,
            )
            return {
                "status": "succeeded",
                "upload": upload,
                "attempt": attempt,
                "retry_attempt_count": retry_attempt_count,
                "throttle_count": throttle_count,
                "retry_delay_seconds": round(retry_delay_seconds, 3),
                "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            }
        except DataManagementBackupCanceledError:
            raise
        except Exception as exc:
            last_error = exc
            if not _is_retryable_backup_cosmos_error(exc) or attempt >= retry_count:
                break
            retry_attempt_count += 1
            if _get_backup_exception_status_code(exc) in {429, 449}:
                throttle_count += 1
            retry_delay = _get_backup_retry_delay(exc, attempt)
            retry_delay_seconds += retry_delay
            if cancel_event is not None:
                if cancel_event.wait(retry_delay):
                    raise DataManagementBackupCanceledError(
                        "Backup batch staging stopped during retry backoff."
                    )
            else:
                time.sleep(retry_delay)
    return {
        "status": "failed",
        "attempt": retry_count,
        "retry_attempt_count": retry_attempt_count,
        "throttle_count": throttle_count,
        "retry_delay_seconds": round(retry_delay_seconds, 3),
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "error": "Backup batch artifact upload failed.",
    }


def _build_backup_progress_metrics(
    resource_started_at,
    source_read_count,
    exported_count,
    skipped_count,
    failed_count,
    byte_count,
    checkpoint_count,
    request_units,
    retry_attempt_count,
    throttle_count,
    parallel_operations,
    active_parallel_operations,
    source_page_count,
    current_container,
):
    """Return bounded per-container telemetry suitable for durable admin progress."""
    transfer_metrics = build_transfer_metrics(
        resource_started_at,
        copied_count=exported_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        byte_count=byte_count,
        request_units=request_units,
    )
    return {
        "source_read_count": source_read_count,
        "processed_count": transfer_metrics["processed_count"],
        "item_count": exported_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "bytes": byte_count,
        "checkpoint_count": checkpoint_count,
        "request_units": transfer_metrics["request_units"],
        "elapsed_seconds": transfer_metrics["elapsed_seconds"],
        "records_per_second": transfer_metrics["items_per_second"],
        "bytes_per_second": transfer_metrics["bytes_per_second"],
        "request_units_per_second": transfer_metrics["request_units_per_second"],
        "retry_attempt_count": retry_attempt_count,
        "throttle_count": throttle_count,
        "parallel_operations": parallel_operations,
        "active_parallel_operations": active_parallel_operations,
        "source_page_count": source_page_count,
        "current_container": _safe_text(current_container),
    }


def _execute_parallel_backup_cosmos_resource(
    job,
    state,
    settings,
    container_client,
    base_prefix,
    fernet,
    resource_name,
    artifact_metadata,
    source_container,
    artifact,
):
    """Stage ordered Cosmos JSONL checkpoint batches with bounded parallel workers."""
    _sync_backup_latest_item_state_from_manifest(job, resource_name)
    existing_resource = get_backup_resource(state, resource_name)
    if is_backup_resource_completed(state, resource_name):
        return copy.deepcopy(existing_resource.get("result") or {})

    backup_plan = job.get("backup_plan") if isinstance(job.get("backup_plan"), dict) else {}
    parallel_operations = _get_backup_parallel_operations(settings, backup_plan)
    retry_count = _get_backup_retry_count(settings, backup_plan)
    resource = start_backup_resource(state, resource_name, "cosmos_export")
    resource_started_at = resource.get("attempt_started_at") or resource.get("started_at")
    previous_progress = resource.get("progress") if isinstance(resource.get("progress"), dict) else {}
    previous_checkpoint = resource.get("checkpoint") if isinstance(resource.get("checkpoint"), dict) else {}
    exported_count = _safe_int(previous_progress.get("item_count"), default=0, minimum=0)
    skipped_count = _safe_int(previous_progress.get("skipped_count"), default=0, minimum=0)
    failed_count = 0
    source_read_count = _safe_int(previous_progress.get("source_read_count"), default=0, minimum=0)
    byte_count = _safe_int(previous_progress.get("bytes"), default=0, minimum=0)
    checkpoint_count = _safe_int(previous_progress.get("checkpoint_count"), default=0, minimum=0)
    request_units = float(previous_progress.get("request_units") or 0.0)
    retry_attempt_count = _safe_int(previous_progress.get("retry_attempt_count"), default=0, minimum=0)
    throttle_count = _safe_int(previous_progress.get("throttle_count"), default=0, minimum=0)
    source_page_count = _safe_int(previous_progress.get("source_page_count"), default=0, minimum=0)
    batch_number = _safe_int(previous_checkpoint.get("next_batch_number"), default=1, minimum=1)
    active_parallel_operations = parallel_operations
    clean_batch_count = 0
    append_manifest, flush_manifest, manifest_buffer = _create_backup_manifest_writer(
        job.get("id"),
        resource_name,
    )
    pending_latest_state_updates = []
    cancel_event = Event()
    telemetry_lock = Lock()

    def add_source_telemetry(values):
        nonlocal request_units, retry_attempt_count, throttle_count, source_page_count
        nonlocal active_parallel_operations, clean_batch_count
        with telemetry_lock:
            request_units += max(0.0, float((values or {}).get("request_units") or 0.0))
            retry_attempt_count += _safe_int(
                (values or {}).get("source_retry_attempt_count"),
                default=0,
                minimum=0,
            )
            received_throttle_count = _safe_int(
                (values or {}).get("source_throttle_count"),
                default=0,
                minimum=0,
            )
            throttle_count += received_throttle_count
            source_page_count += _safe_int(
                (values or {}).get("source_page_count"),
                default=0,
                minimum=0,
            )
            if received_throttle_count:
                active_parallel_operations = max(1, active_parallel_operations - 1)
                clean_batch_count = 0

    def persist(message, checkpoint=None, allow_cancel_requested=False):
        nonlocal state
        _assert_backup_job_lease(
            job,
            allow_cancel_requested=allow_cancel_requested,
        )
        if manifest_buffer:
            flush_manifest()
        progress = _build_backup_progress_metrics(
            resource_started_at,
            source_read_count,
            exported_count,
            skipped_count,
            failed_count,
            byte_count,
            checkpoint_count,
            request_units,
            retry_attempt_count,
            throttle_count,
            parallel_operations,
            active_parallel_operations,
            source_page_count,
            artifact_metadata.get("container_name"),
        )
        state = _persist_backup_checkpoint(
            job,
            state,
            settings,
            resource_name,
            progress,
            checkpoint if isinstance(checkpoint, dict) else previous_checkpoint,
            message,
            allow_cancel_requested=allow_cancel_requested,
        )
        _flush_backup_latest_item_state_updates(
            job,
            "cosmos",
            resource_name,
            pending_latest_state_updates,
        )
        return state

    def record_item_outcome(source_item, status, checkpoint_id="", artifact_path="", failure_summary="", skip_summary="", artifact_bytes=0):
        if status == "failed":
            _append_backup_state_summary(state, "failed_items", {
                "service": "cosmos",
                "resource_name": resource_name,
                "source_identity": source_item["source_identity"],
                "failure_summary": _safe_text(failure_summary)[:500],
            })
        elif status == "skipped":
            _append_backup_state_summary(state, "skipped_items", {
                "service": "cosmos",
                "resource_name": resource_name,
                "source_identity": source_item["source_identity"],
                "skip_summary": _safe_text(skip_summary)[:500],
            })
        append_manifest(_build_backup_manifest_entry(
            job,
            "cosmos",
            resource_name,
            source_item,
            status,
            artifact_checkpoint_id=checkpoint_id,
            artifact_path=artifact_path,
            bytes=artifact_bytes,
            failure_summary=_safe_text(failure_summary)[:500],
            skip_summary=_safe_text(skip_summary)[:500],
        ))
        _queue_backup_latest_item_state_update(
            pending_latest_state_updates,
            source_item,
            status,
            checkpoint_id=checkpoint_id,
            artifact_path=artifact_path,
            failure_summary=_safe_text(failure_summary)[:500],
            skip_summary=_safe_text(skip_summary)[:500],
        )

    def prepare_batch(sequence_number, source_batch):
        nonlocal source_read_count
        export_items = []
        skipped_items = []
        failed_items = []
        for source_item in source_batch:
            source_read_count += 1
            latest_state = _read_backup_latest_item_state(
                _get_backup_source_scope(job),
                _build_backup_lineage_id(backup_plan),
                "cosmos",
                resource_name,
                source_item["source_identity"],
            )
            if not _is_backup_item_due_for_export(
                backup_plan,
                latest_state,
                source_item["source_version"],
                backup_job_id=job.get("id"),
            ):
                skipped_items.append((
                    source_item,
                    _safe_text((latest_state or {}).get("artifact_checkpoint_id")),
                    _safe_text((latest_state or {}).get("artifact_path")),
                ))
                continue
            try:
                json.dumps(source_item["payload"], default=_json_default, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                failed_items.append((source_item, f"Backup serialization failed: {exc}"))
                continue
            export_items.append(source_item)
        batch_identity = _build_backup_batch_identity(job, resource_name, source_batch)
        return {
            "sequence_number": sequence_number,
            "source_batch": source_batch,
            "export_items": export_items,
            "skipped_items": skipped_items,
            "failed_items": failed_items,
            "batch_identity": batch_identity,
            "checkpoint_id": (
                f"{job.get('id')}:{_safe_job_item_id_part(resource_name)}:{batch_identity}"
            ),
            "batch_blob_name": (
                f"{base_prefix}/cosmos/{_safe_job_item_id_part(resource_name)}/"
                f"batches/{batch_identity}.jsonl"
            ),
        }

    def commit_batch(context, stage_result):
        nonlocal exported_count, skipped_count, failed_count, byte_count
        nonlocal checkpoint_count, batch_number, previous_checkpoint
        nonlocal retry_attempt_count, throttle_count, active_parallel_operations, clean_batch_count
        _assert_backup_job_lease(job)
        for source_item, checkpoint_id, artifact_path in context["skipped_items"]:
            skipped_count += 1
            record_item_outcome(
                source_item,
                "skipped",
                checkpoint_id=checkpoint_id,
                artifact_path=artifact_path,
                skip_summary="Latest successful backup state matches the source version.",
            )
        for source_item, failure_summary in context["failed_items"]:
            failed_count += 1
            record_item_outcome(
                source_item,
                "failed",
                failure_summary=failure_summary,
            )

        stage_result = stage_result if isinstance(stage_result, dict) else {}
        retry_attempt_count += _safe_int(
            stage_result.get("retry_attempt_count"),
            default=0,
            minimum=0,
        )
        stage_throttles = _safe_int(stage_result.get("throttle_count"), default=0, minimum=0)
        throttle_count += stage_throttles
        if stage_throttles:
            active_parallel_operations = max(1, active_parallel_operations - 1)
            clean_batch_count = 0
        else:
            clean_batch_count += 1
            if clean_batch_count >= max(1, active_parallel_operations) and active_parallel_operations < parallel_operations:
                active_parallel_operations += 1
                clean_batch_count = 0

        artifact_path = ""
        if context["export_items"] and stage_result.get("status") == "succeeded":
            upload = stage_result.get("upload") if isinstance(stage_result.get("upload"), dict) else {}
            artifact_path = _safe_text(upload.get("path"))
            exported_count += len(context["export_items"])
            byte_count += _safe_int(upload.get("bytes"), default=0, minimum=0)
            for source_item in context["export_items"]:
                record_item_outcome(
                    source_item,
                    "succeeded",
                    checkpoint_id=context["checkpoint_id"],
                    artifact_path=artifact_path,
                    artifact_bytes=_safe_int(upload.get("bytes"), default=0, minimum=0),
                )
        elif context["export_items"]:
            failure_summary = _safe_text(stage_result.get("error")) or "Backup batch artifact upload failed."
            for source_item in context["export_items"]:
                failed_count += 1
                record_item_outcome(
                    source_item,
                    "failed",
                    failure_summary=failure_summary,
                )

        checkpoint_count += 1
        previous_checkpoint = _build_backup_checkpoint_summary(
            previous_checkpoint,
            batch_number,
            artifact_path,
        )
        batch_number += 1
        persist(
            f"Checkpointed Cosmos backup batch for {artifact_metadata.get('container_name')}",
            previous_checkpoint,
        )

    def consume_completed_futures(pending_by_future, completed_results, wait_for_result):
        last_heartbeat = time.monotonic()
        while pending_by_future and (wait_for_result or completed_results):
            completed_futures, _pending_futures = wait(
                set(pending_by_future),
                timeout=DATA_MANAGEMENT_BACKUP_HEARTBEAT_POLL_SECONDS,
                return_when=FIRST_COMPLETED,
            )
            for future in completed_futures:
                context = pending_by_future.pop(future)
                try:
                    completed_results[context["sequence_number"]] = (
                        context,
                        future.result(),
                    )
                except DataManagementBackupCanceledError:
                    cancel_event.set()
                    for pending_future in pending_by_future:
                        pending_future.cancel()
                    _assert_backup_job_lease(job)
                    raise
                except Exception as exc:
                    completed_results[context["sequence_number"]] = (
                        context,
                        {
                            "status": "failed",
                            "attempt": retry_count,
                            "error": _sanitize_data_management_backup_text(str(exc)),
                        },
                    )
            now = time.monotonic()
            if pending_by_future and now - last_heartbeat >= DATA_MANAGEMENT_BACKUP_HEARTBEAT_INTERVAL_SECONDS:
                persist(
                    f"Waiting for Cosmos backup staging workers for {artifact_metadata.get('container_name')}",
                )
                last_heartbeat = now
            if completed_futures or not wait_for_result:
                return

    pending_by_future = {}
    completed_results = {}
    next_sequence_number = 1
    next_commit_sequence = 1
    source_batch = []

    try:
        source_items = _iter_backup_cosmos_source_items(
            source_container,
            artifact,
            backup_plan,
            telemetry_callback=add_source_telemetry,
            cancel_event=cancel_event,
        )
        with ThreadPoolExecutor(max_workers=parallel_operations) as executor:
            for source_item in source_items:
                source_batch.append(source_item)
                if len(source_batch) < DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE:
                    continue
                context = prepare_batch(next_sequence_number, source_batch)
                next_sequence_number += 1
                source_batch = []
                if context["export_items"]:
                    while (
                        len(pending_by_future) + len(completed_results) >=
                        active_parallel_operations
                    ):
                        consume_completed_futures(pending_by_future, completed_results, True)
                        while next_commit_sequence in completed_results:
                            commit_context, commit_result = completed_results.pop(next_commit_sequence)
                            commit_batch(commit_context, commit_result)
                            next_commit_sequence += 1
                    pending_by_future[executor.submit(
                        _stage_backup_jsonl_batch,
                        container_client,
                        context["batch_blob_name"],
                        context["export_items"],
                        fernet,
                        retry_count,
                        cancel_event,
                    )] = context
                else:
                    completed_results[context["sequence_number"]] = (
                        context,
                        {"status": "succeeded", "upload": {"path": "", "bytes": 0}},
                    )
                while next_commit_sequence in completed_results:
                    commit_context, commit_result = completed_results.pop(next_commit_sequence)
                    commit_batch(commit_context, commit_result)
                    next_commit_sequence += 1

            if source_batch:
                context = prepare_batch(next_sequence_number, source_batch)
                next_sequence_number += 1
                if context["export_items"]:
                    while (
                        len(pending_by_future) + len(completed_results) >=
                        active_parallel_operations
                    ):
                        consume_completed_futures(pending_by_future, completed_results, True)
                        while next_commit_sequence in completed_results:
                            commit_context, commit_result = completed_results.pop(next_commit_sequence)
                            commit_batch(commit_context, commit_result)
                            next_commit_sequence += 1
                    pending_by_future[executor.submit(
                        _stage_backup_jsonl_batch,
                        container_client,
                        context["batch_blob_name"],
                        context["export_items"],
                        fernet,
                        retry_count,
                        cancel_event,
                    )] = context
                else:
                    completed_results[context["sequence_number"]] = (
                        context,
                        {"status": "succeeded", "upload": {"path": "", "bytes": 0}},
                    )

            while pending_by_future:
                consume_completed_futures(pending_by_future, completed_results, True)
                while next_commit_sequence in completed_results:
                    commit_context, commit_result = completed_results.pop(next_commit_sequence)
                    commit_batch(commit_context, commit_result)
                    next_commit_sequence += 1
            while next_commit_sequence in completed_results:
                commit_context, commit_result = completed_results.pop(next_commit_sequence)
                commit_batch(commit_context, commit_result)
                next_commit_sequence += 1
    except (DataManagementBackupCanceledError, DataManagementBackupLeaseLostError):
        cancel_event.set()
        raise

    result = {
        **copy.deepcopy(artifact_metadata if isinstance(artifact_metadata, dict) else {}),
        "status": "warning" if failed_count else "completed",
        "processed_count": exported_count + skipped_count + failed_count,
        "item_count": exported_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "source_read_count": source_read_count,
        "bytes": byte_count,
        "checkpoint_count": checkpoint_count,
        "request_units": round(request_units, 3),
        "retry_attempt_count": retry_attempt_count,
        "throttle_count": throttle_count,
        "parallel_operations": parallel_operations,
        "active_parallel_operations": active_parallel_operations,
        "source_page_count": source_page_count,
        "elapsed_seconds": _build_backup_progress_metrics(
            resource_started_at,
            source_read_count,
            exported_count,
            skipped_count,
            failed_count,
            byte_count,
            checkpoint_count,
            request_units,
            retry_attempt_count,
            throttle_count,
            parallel_operations,
            active_parallel_operations,
            source_page_count,
            artifact_metadata.get("container_name"),
        )["elapsed_seconds"],
        "prefix": f"{base_prefix}/cosmos/{_safe_job_item_id_part(resource_name)}/batches/",
    }
    result["records_per_second"] = round(
        result["item_count"] / max(0.001, float(result["elapsed_seconds"])),
        3,
    )
    result["bytes_per_second"] = round(
        result["bytes"] / max(0.001, float(result["elapsed_seconds"])),
        3,
    )
    result["request_units_per_second"] = round(
        result["request_units"] / max(0.001, float(result["elapsed_seconds"])),
        3,
    )
    if failed_count:
        _fail_backup_resource_checkpoint(
            job,
            state,
            settings,
            resource_name,
            "One or more backup items failed and remain eligible for focused retry.",
            f"Completed Cosmos backup resource {artifact_metadata.get('container_name')} with retryable item failures",
            result=result,
        )
    else:
        _complete_backup_resource_checkpoint(
            job,
            state,
            settings,
            resource_name,
            result,
            f"Completed Cosmos backup resource {artifact_metadata.get('container_name')}",
        )
    return result


def _execute_backup_jsonl_resource(
    job,
    state,
    settings,
    container_client,
    base_prefix,
    fernet,
    service,
    resource_name,
    artifact_metadata,
    source_items,
):
    """Export one Cosmos or Search resource through bounded durable JSONL batches."""
    _sync_backup_latest_item_state_from_manifest(job, resource_name)
    existing_resource = get_backup_resource(state, resource_name)
    if is_backup_resource_completed(state, resource_name):
        return copy.deepcopy(existing_resource.get("result") or {})

    resource = start_backup_resource(state, resource_name, "export")
    previous_progress = resource.get("progress") if isinstance(resource.get("progress"), dict) else {}
    previous_checkpoint = resource.get("checkpoint") if isinstance(resource.get("checkpoint"), dict) else {}
    exported_count = _safe_int(previous_progress.get("item_count"), default=0, minimum=0)
    skipped_count = _safe_int(previous_progress.get("skipped_count"), default=0, minimum=0)
    failed_count = 0
    source_read_count = _safe_int(previous_progress.get("source_read_count"), default=0, minimum=0)
    byte_count = _safe_int(previous_progress.get("bytes"), default=0, minimum=0)
    checkpoint_count = _safe_int(previous_progress.get("checkpoint_count"), default=0, minimum=0)
    batch_number = _safe_int(previous_checkpoint.get("next_batch_number"), default=1, minimum=1)
    append_manifest, flush_manifest, manifest_buffer = _create_backup_manifest_writer(
        job.get("id"),
        resource_name,
    )
    pending_latest_state_updates = []
    pending_items = []

    def persist(message, checkpoint=None):
        nonlocal state
        _assert_backup_job_lease(job)
        if manifest_buffer:
            flush_manifest()
        progress = {
            "source_read_count": source_read_count,
            "processed_count": exported_count + skipped_count + failed_count,
            "item_count": exported_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "bytes": byte_count,
            "checkpoint_count": checkpoint_count,
        }
        state = _persist_backup_checkpoint(
            job,
            state,
            settings,
            resource_name,
            progress,
            checkpoint if isinstance(checkpoint, dict) else previous_checkpoint,
            message,
        )
        _flush_backup_latest_item_state_updates(
            job,
            service,
            resource_name,
            pending_latest_state_updates,
        )
        return state

    def record_failure(source_item, failure_summary):
        nonlocal failed_count
        _assert_backup_job_lease(job)
        failed_count += 1
        _append_backup_state_summary(state, "failed_items", {
            "service": service,
            "resource_name": resource_name,
            "source_identity": source_item["source_identity"],
            "failure_summary": _safe_text(failure_summary)[:500],
        })
        append_manifest(_build_backup_manifest_entry(
            job,
            service,
            resource_name,
            source_item,
            "failed",
            failure_summary=_safe_text(failure_summary)[:500],
        ))
        _queue_backup_latest_item_state_update(
            pending_latest_state_updates,
            source_item,
            "failed",
            failure_summary=_safe_text(failure_summary)[:500],
        )

    def export_batch(source_batch):
        nonlocal byte_count, exported_count, checkpoint_count, batch_number, previous_checkpoint
        batch_identity = _build_backup_batch_identity(job, resource_name, source_batch)
        checkpoint_id = f"{job.get('id')}:{_safe_job_item_id_part(resource_name)}:{batch_identity}"
        batch_blob_name = (
            f"{base_prefix}/{service}/{_safe_job_item_id_part(resource_name)}/"
            f"batches/{batch_identity}.jsonl"
        )
        _assert_backup_job_lease(job)
        try:
            upload = _write_jsonl_artifact(
                container_client,
                batch_blob_name,
                [source_item["payload"] for source_item in source_batch],
                fernet=fernet,
                backup_job=job,
                backup_settings=settings,
                heartbeat_message=f"Uploading backup batch for {resource_name}",
            )
        except (DataManagementBackupCanceledError, DataManagementBackupLeaseLostError):
            raise
        except Exception as exc:
            failure_summary = _safe_text(str(exc))[:500] or "Backup batch artifact upload failed."
            for source_item in source_batch:
                record_failure(source_item, failure_summary)
            checkpoint_count += 1
            previous_checkpoint = _build_backup_checkpoint_summary(
                previous_checkpoint,
                batch_number,
            )
            batch_number += 1
            persist(f"Recorded failed backup batch for {resource_name}", previous_checkpoint)
            return

        _assert_backup_job_lease(job)
        for source_item in source_batch:
            _assert_backup_job_lease(job)
            append_manifest(_build_backup_manifest_entry(
                job,
                service,
                resource_name,
                source_item,
                "succeeded",
                artifact_checkpoint_id=checkpoint_id,
                artifact_path=upload.get("path"),
                bytes=upload.get("bytes"),
            ))
            _queue_backup_latest_item_state_update(
                pending_latest_state_updates,
                source_item,
                "succeeded",
                checkpoint_id=checkpoint_id,
                artifact_path=upload.get("path"),
            )
        exported_count += len(source_batch)
        byte_count += _safe_int(upload.get("bytes"), default=0, minimum=0)
        checkpoint_count += 1
        previous_checkpoint = _build_backup_checkpoint_summary(
            previous_checkpoint,
            batch_number,
            upload.get("path"),
        )
        batch_number += 1
        persist(f"Checkpointed backup batch for {resource_name}", previous_checkpoint)

    for source_item in source_items:
        source_read_count += 1
        latest_state = _read_backup_latest_item_state(
            _get_backup_source_scope(job),
            _build_backup_lineage_id(job.get("backup_plan")),
            service,
            resource_name,
            source_item["source_identity"],
        )
        if not _is_backup_item_due_for_export(
            job.get("backup_plan"),
            latest_state,
            source_item["source_version"],
            backup_job_id=job.get("id"),
        ):
            skipped_count += 1
            skip_summary = "Latest successful backup state matches the source version."
            _append_backup_state_summary(state, "skipped_items", {
                "service": service,
                "resource_name": resource_name,
                "source_identity": source_item["source_identity"],
                "skip_summary": skip_summary,
            })
            append_manifest(_build_backup_manifest_entry(
                job,
                service,
                resource_name,
                source_item,
                "skipped",
                skip_summary=skip_summary,
            ))
            _queue_backup_latest_item_state_update(
                pending_latest_state_updates,
                source_item,
                "skipped",
                checkpoint_id=_safe_text((latest_state or {}).get("artifact_checkpoint_id")),
                artifact_path=_safe_text((latest_state or {}).get("artifact_path")),
                skip_summary=skip_summary,
            )
            if len(manifest_buffer) >= DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE:
                persist(f"Checkpointed unchanged backup items for {resource_name}")
            continue
        try:
            json.dumps(source_item["payload"], default=_json_default, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            record_failure(source_item, f"Backup serialization failed: {exc}")
            if len(manifest_buffer) >= DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE:
                persist(f"Checkpointed failed backup items for {resource_name}")
            continue
        pending_items.append(source_item)
        if len(pending_items) >= DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE:
            export_batch(pending_items)
            pending_items = []

    if pending_items:
        export_batch(pending_items)
    if manifest_buffer or pending_latest_state_updates:
        persist(f"Finalized backup item checkpoints for {resource_name}")

    result = {
        **copy.deepcopy(artifact_metadata if isinstance(artifact_metadata, dict) else {}),
        "status": "warning" if failed_count else "completed",
        "item_count": exported_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "source_read_count": source_read_count,
        "bytes": byte_count,
        "checkpoint_count": checkpoint_count,
        "prefix": f"{base_prefix}/{service}/{_safe_job_item_id_part(resource_name)}/batches/",
    }
    if failed_count:
        _fail_backup_resource_checkpoint(
            job,
            state,
            settings,
            resource_name,
            "One or more backup items failed and remain eligible for focused retry.",
            f"Completed backup resource {resource_name} with retryable item failures",
            result=result,
        )
    else:
        state = _complete_backup_resource_checkpoint(
            job,
            state,
            settings,
            resource_name,
            result,
            f"Completed backup resource {resource_name}",
        )
    return result


def _execute_backup_schema_resource(job, state, settings, container_client, base_prefix, fernet, artifact):
    """Write an AI Search schema once and checkpoint it independently from documents."""
    resource_name = f"ai_search_schema:{artifact['index_name']}"
    existing_resource = get_backup_resource(state, resource_name)
    if is_backup_resource_completed(state, resource_name):
        return copy.deepcopy(existing_resource.get("result") or {})
    start_backup_resource(state, resource_name, "ai_search_schema")
    _assert_backup_job_lease(job)
    upload = _upload_json_artifact(
        container_client,
        f"{base_prefix}/ai_search/{artifact['index_name']}.schema.json",
        _get_search_schema(artifact["schema_file"]),
        fernet=fernet,
        backup_job=job,
        backup_settings=settings,
        heartbeat_message=f"Uploading AI Search schema backup for {artifact['index_name']}",
    )
    _assert_backup_job_lease(job)
    result = {
        "name": f"{artifact['name']}_schema",
        "type": "ai_search_schema",
        "index_name": artifact["index_name"],
        "status": "completed",
        **upload,
        "checkpoint_count": 1,
    }
    _complete_backup_resource_checkpoint(
        job,
        state,
        settings,
        resource_name,
        result,
        f"Completed schema backup for {artifact['index_name']}",
    )
    return result


def _execute_backup_source_blob_resource(
    job,
    state,
    settings,
    container_client,
    base_prefix,
    fernet,
    source_container_client,
    source_container_name,
):
    """Copy source blobs one at a time so each successful blob is durable on restart."""
    resource_name = f"source_blobs:{source_container_name}"
    _sync_backup_latest_item_state_from_manifest(job, resource_name)
    existing_resource = get_backup_resource(state, resource_name)
    if is_backup_resource_completed(state, resource_name):
        return copy.deepcopy(existing_resource.get("result") or {})
    resource = start_backup_resource(state, resource_name, "source_blobs")
    previous_progress = resource.get("progress") if isinstance(resource.get("progress"), dict) else {}
    previous_checkpoint = resource.get("checkpoint") if isinstance(resource.get("checkpoint"), dict) else {}
    copied_count = _safe_int(previous_progress.get("blob_count"), default=0, minimum=0)
    skipped_count = _safe_int(previous_progress.get("skipped_count"), default=0, minimum=0)
    failed_count = 0
    byte_count = _safe_int(previous_progress.get("bytes"), default=0, minimum=0)
    checkpoint_count = _safe_int(previous_progress.get("checkpoint_count"), default=0, minimum=0)
    batch_number = _safe_int(previous_checkpoint.get("next_batch_number"), default=1, minimum=1)
    append_manifest, flush_manifest, manifest_buffer = _create_backup_manifest_writer(
        job.get("id"),
        resource_name,
    )
    pending_latest_state_updates = []

    def persist(message):
        nonlocal state
        _assert_backup_job_lease(job)
        if manifest_buffer:
            flush_manifest()
        progress = {
            "processed_count": copied_count + skipped_count + failed_count,
            "blob_count": copied_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "bytes": byte_count,
            "checkpoint_count": checkpoint_count,
        }
        state = _persist_backup_checkpoint(
            job,
            state,
            settings,
            resource_name,
            progress,
            previous_checkpoint,
            message,
        )
        _flush_backup_latest_item_state_updates(
            job,
            "source_blobs",
            resource_name,
            pending_latest_state_updates,
        )

    try:
        blob_properties_iterable = source_container_client.list_blobs()
        for blob_properties in blob_properties_iterable:
            artifact_path = ""
            blob_name = _safe_text(getattr(blob_properties, "name", None) or blob_properties.get("name"))
            if not blob_name:
                continue
            last_modified = getattr(blob_properties, "last_modified", None)
            if last_modified is None and isinstance(blob_properties, dict):
                last_modified = blob_properties.get("last_modified")
            if not _is_backup_value_within_cutoff(
                last_modified,
                (job.get("backup_plan") or {}).get("source_cutoff_at"),
            ):
                continue
            blob_etag = getattr(blob_properties, "etag", None)
            if blob_etag is None and isinstance(blob_properties, dict):
                blob_etag = blob_properties.get("etag")
            blob_size = getattr(blob_properties, "size", None)
            if blob_size is None and isinstance(blob_properties, dict):
                blob_size = blob_properties.get("size")
            source_item = {
                "source_identity": _build_backup_source_identity(
                    "source_blobs",
                    source_container_name,
                    blob_name,
                ),
                "source_version": _build_backup_source_version({
                    "etag": blob_etag,
                    "last_modified": last_modified,
                    "size": blob_size,
                }),
            }
            latest_state = _read_backup_latest_item_state(
                _get_backup_source_scope(job),
                _build_backup_lineage_id(job.get("backup_plan")),
                "source_blobs",
                resource_name,
                source_item["source_identity"],
            )
            if not _is_backup_item_due_for_export(
                job.get("backup_plan"),
                latest_state,
                source_item["source_version"],
                backup_job_id=job.get("id"),
            ):
                skipped_count += 1
                skip_summary = "Latest successful backup state matches the source version."
                _append_backup_state_summary(state, "skipped_items", {
                    "service": "source_blobs",
                    "resource_name": resource_name,
                    "source_identity": source_item["source_identity"],
                    "skip_summary": skip_summary,
                })
                append_manifest(_build_backup_manifest_entry(
                    job,
                    "source_blobs",
                    resource_name,
                    source_item,
                    "skipped",
                    skip_summary=skip_summary,
                ))
                _queue_backup_latest_item_state_update(
                    pending_latest_state_updates,
                    source_item,
                    "skipped",
                    checkpoint_id=_safe_text((latest_state or {}).get("artifact_checkpoint_id")),
                    artifact_path=_safe_text((latest_state or {}).get("artifact_path")),
                    skip_summary=skip_summary,
                )
                if len(manifest_buffer) >= DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE:
                    persist(f"Checkpointed unchanged source blobs for {source_container_name}")
                continue

            checkpoint_id = _build_backup_checkpoint_id(job, resource_name, batch_number)
            target_blob_name = f"{base_prefix}/source_blobs/{source_container_name}/{blob_name}"
            _assert_backup_job_lease(job)
            try:
                source_blob_client = source_container_client.get_blob_client(blob_name)
                artifact_path, uploaded_bytes = _copy_source_blob(
                    container_client,
                    source_blob_client,
                    target_blob_name,
                    fernet=fernet,
                    backup_job=job,
                    backup_settings=settings,
                    heartbeat_message=f"Copying source blob backup for {source_container_name}",
                )
                _assert_backup_job_lease(job)
                copied_count += 1
                byte_count += _safe_int(uploaded_bytes, default=0, minimum=0)
                append_manifest(_build_backup_manifest_entry(
                    job,
                    "source_blobs",
                    resource_name,
                    source_item,
                    "succeeded",
                    artifact_checkpoint_id=checkpoint_id,
                    artifact_path=artifact_path,
                    bytes=uploaded_bytes,
                ))
                _queue_backup_latest_item_state_update(
                    pending_latest_state_updates,
                    source_item,
                    "succeeded",
                    checkpoint_id=checkpoint_id,
                    artifact_path=artifact_path,
                )
            except (DataManagementBackupCanceledError, DataManagementBackupLeaseLostError):
                raise
            except Exception as exc:
                failed_count += 1
                failure_summary = _safe_text(str(exc))[:500] or "Source blob copy failed."
                _assert_backup_job_lease(job)
                _append_backup_state_summary(state, "failed_items", {
                    "service": "source_blobs",
                    "resource_name": resource_name,
                    "source_identity": source_item["source_identity"],
                    "failure_summary": failure_summary,
                })
                append_manifest(_build_backup_manifest_entry(
                    job,
                    "source_blobs",
                    resource_name,
                    source_item,
                    "failed",
                    failure_summary=failure_summary,
                ))
                _queue_backup_latest_item_state_update(
                    pending_latest_state_updates,
                    source_item,
                    "failed",
                    failure_summary=failure_summary,
                )
            checkpoint_count += 1
            previous_checkpoint = _build_backup_checkpoint_summary(
                previous_checkpoint,
                batch_number,
                artifact_path,
            )
            batch_number += 1
            persist(f"Checkpointed source blob backup for {source_container_name}")
    except (DataManagementBackupCanceledError, DataManagementBackupLeaseLostError):
        raise
    except Exception as exc:
        failed_count += 1
        _append_backup_state_summary(state, "failed_items", {
            "service": "source_blobs",
            "resource_name": resource_name,
            "failure_summary": _safe_text(str(exc))[:500],
        })

    if manifest_buffer or pending_latest_state_updates:
        persist(f"Finalized source blob checkpoints for {source_container_name}")
    result = {
        "name": source_container_name,
        "type": "source_blob_container",
        "container_name": source_container_name,
        "status": "warning" if failed_count else "completed",
        "blob_count": copied_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "bytes": byte_count,
        "encrypted": bool(fernet),
        "prefix": f"{base_prefix}/source_blobs/{source_container_name}/",
        "checkpoint_count": checkpoint_count,
    }
    if failed_count:
        _fail_backup_resource_checkpoint(
            job,
            state,
            settings,
            resource_name,
            "One or more source blobs failed and remain eligible for focused retry.",
            f"Completed source blob backup for {source_container_name} with retryable failures",
            result=result,
        )
    else:
        _complete_backup_resource_checkpoint(
            job,
            state,
            settings,
            resource_name,
            result,
            f"Completed source blob backup for {source_container_name}",
        )
    return result


def _execute_backup_cosmos_resources(
    job,
    backup_state,
    settings,
    backup_plan,
    container_client,
    base_prefix,
    fernet,
):
    """Run source Cosmos exports under one fenced capacity and checkpoint lifecycle."""
    artifacts = []
    restore_warnings = []
    capacity_attempted = False
    try:
        if _safe_bool(
            ((backup_plan.get("cosmos_execution") or {}).get("temporary_source_ru_enabled")),
            False,
        ):
            capacity_attempted = True
            _apply_temporary_backup_source_capacity(
                job,
                backup_state,
                settings,
                backup_plan,
            )
        for artifact in DATA_MANAGEMENT_COSMOS_ARTIFACTS:
            resource_name = f"cosmos:{artifact['name']}"
            if is_backup_resource_completed(backup_state, resource_name):
                existing_resource = get_backup_resource(backup_state, resource_name)
                artifacts.append(copy.deepcopy(existing_resource.get("result") or {}))
                continue
            source_container = getattr(app_config, artifact["container_attr"], None)
            if source_container is None:
                warning = f"Cosmos container '{artifact['name']}' was not initialized."
                _append_backup_warning(backup_state, warning)
                _skip_backup_resource_checkpoint(
                    job,
                    backup_state,
                    settings,
                    resource_name,
                    warning,
                    f"Skipped unavailable Cosmos container {artifact['name']}",
                )
                artifacts.append({
                    "name": artifact["name"],
                    "type": "cosmos_container",
                    "status": "skipped",
                    "warning": warning,
                })
                continue
            try:
                artifacts.append(_execute_parallel_backup_cosmos_resource(
                    job,
                    backup_state,
                    settings,
                    container_client,
                    base_prefix,
                    fernet,
                    resource_name,
                    {
                        "name": artifact["name"],
                        "type": "cosmos_container",
                        "category": artifact["category"],
                        "container_name": getattr(
                            app_config,
                            artifact["container_name_attr"],
                            artifact["name"],
                        ),
                        "partition_key_path": artifact["partition_key_path"],
                        "partial_since_epoch": None,
                    },
                    source_container,
                    artifact,
                ))
            except (DataManagementBackupCanceledError, DataManagementBackupLeaseLostError):
                raise
            except Exception as exc:
                log_event(
                    "[DataManagement] Cosmos backup resource failed.",
                    {"job_id": job.get("id"), "resource": artifact["name"], "error": str(exc)},
                    level=logging.WARNING,
                )
                warning = f"Cosmos backup resource '{artifact['name']}' failed."
                _append_backup_warning(backup_state, warning)
                _fail_backup_resource_checkpoint(
                    job,
                    backup_state,
                    settings,
                    resource_name,
                    "Cosmos backup resource failed.",
                    f"Recorded failed Cosmos backup resource {artifact['name']}",
                )
                artifacts.append({
                    "name": artifact["name"],
                    "type": "cosmos_container",
                    "status": "warning",
                    "warning": warning,
                })
    finally:
        source_capacity = (
            backup_state.get("source_capacity")
            if isinstance(backup_state.get("source_capacity"), dict) else {}
        )
        if capacity_attempted or source_capacity.get("restore_pending"):
            try:
                restore_warnings, _ = _restore_temporary_backup_source_capacity(
                    job,
                    backup_state,
                    settings,
                    allow_cancel_requested=True,
                )
            except DataManagementBackupLeaseLostError:
                raise
            except Exception as exc:
                restore_warnings = [
                    f"Failed to restore temporary source Cosmos capacity: {str(exc)[:300]}"
                ]
            for warning in restore_warnings:
                _append_backup_warning(backup_state, warning)

    source_capacity = (
        backup_state.get("source_capacity")
        if isinstance(backup_state.get("source_capacity"), dict) else {}
    )
    if source_capacity.get("restore_pending"):
        raise RuntimeError(
            "Source Cosmos capacity restoration remains pending. Retry the backup to restore the recorded capacity snapshot."
        )
    return artifacts


def execute_backup_job(job, settings):
    backup_plan = job.get("backup_plan") if isinstance(job.get("backup_plan"), dict) else {}
    if not backup_plan:
        if settings.get("encryption_enabled") and not settings.get("encryption_key_reference"):
            generate_data_management_encryption_key()
            settings = get_data_management_settings()
        backup_plan = _normalize_data_management_backup_plan(
            settings,
            job.get("backup_type"),
            job.get("options"),
            source_cutoff_at=job.get("source_cutoff_at") or _now_iso(),
        )
        job["backup_plan"] = backup_plan
        job["source_scope"] = backup_plan["source_scope"]
        job["source_cutoff_at"] = backup_plan["source_cutoff_at"]

    _assert_backup_execution_settings(settings, backup_plan)
    backup_state = initialize_backup_state(
        job.get("backup_state"),
        job.get("id"),
        backup_plan,
        backup_plan["source_scope"],
        backup_plan["source_cutoff_at"],
    )
    start_backup_attempt(
        backup_state,
        job.get("backup_attempt_id"),
        job.get("lease_generation"),
    )
    job["backup_state"] = backup_state
    _persist_backup_state(
        job,
        backup_state,
        settings,
        "Initialized durable backup plan and checkpoint state",
    )
    _recover_pending_temporary_backup_source_capacity(
        job,
        backup_state,
        settings,
    )

    container_client = _get_backup_container_client(settings)
    fernet = _get_backup_fernet(
        settings,
        key_reference=backup_plan.get("encryption_key_reference"),
    )
    base_prefix = _get_backup_base_prefix(settings, job)
    total_steps = 4
    warnings = []
    artifacts = []
    _set_job_progress(
        job,
        "Starting durable backup export",
        0,
        total_steps,
        current_step="start",
    )

    if backup_plan.get("include_cosmos"):
        artifacts.extend(_execute_backup_cosmos_resources(
            job,
            backup_state,
            settings,
            backup_plan,
            container_client,
            base_prefix,
            fernet,
        ))
    else:
        warning = "Cosmos DB export is disabled for this backup."
        _append_backup_warning(backup_state, warning)
        _skip_backup_resource_checkpoint(
            job,
            backup_state,
            settings,
            "cosmos",
            warning,
            "Skipped disabled Cosmos backup scope",
        )
    _set_job_progress(job, "Cosmos DB export step completed", 1, total_steps, current_step="cosmos")

    if backup_plan.get("include_ai_search"):
        for artifact in DATA_MANAGEMENT_SEARCH_ARTIFACTS:
            schema_resource_name = f"ai_search_schema:{artifact['index_name']}"
            documents_resource_name = f"ai_search:{artifact['index_name']}"
            source_client = CLIENTS.get(artifact["client_key"])
            if source_client is None:
                warning = f"AI Search client '{artifact['name']}' was not initialized."
                _append_backup_warning(backup_state, warning)
                for resource_name in (schema_resource_name, documents_resource_name):
                    if not is_backup_resource_completed(backup_state, resource_name):
                        _skip_backup_resource_checkpoint(
                            job,
                            backup_state,
                            settings,
                            resource_name,
                            warning,
                            f"Skipped unavailable AI Search resource {artifact['index_name']}",
                        )
                artifacts.append({
                    "name": artifact["name"],
                    "type": "ai_search_documents",
                    "status": "skipped",
                    "warning": warning,
                })
                continue
            try:
                artifacts.append(_execute_backup_schema_resource(
                    job,
                    backup_state,
                    settings,
                    container_client,
                    base_prefix,
                    fernet,
                    artifact,
                ))
            except (DataManagementBackupCanceledError, DataManagementBackupLeaseLostError):
                raise
            except Exception as exc:
                warning = f"AI Search schema backup resource '{artifact['name']}' failed: {str(exc)[:300]}"
                _append_backup_warning(backup_state, warning)
                _fail_backup_resource_checkpoint(
                    job,
                    backup_state,
                    settings,
                    schema_resource_name,
                    str(exc),
                    f"Recorded failed AI Search schema backup resource {artifact['index_name']}",
                )
                artifacts.append({
                    "name": f"{artifact['name']}_schema",
                    "type": "ai_search_schema",
                    "status": "warning",
                    "warning": warning,
                })
                continue
            try:
                artifacts.append(_execute_backup_jsonl_resource(
                    job,
                    backup_state,
                    settings,
                    container_client,
                    base_prefix,
                    fernet,
                    "ai_search",
                    documents_resource_name,
                    {
                        "name": artifact["name"],
                        "type": "ai_search_documents",
                        "index_name": artifact["index_name"],
                        "partial_filter": "latest_item_state",
                    },
                    _iter_backup_search_source_items(source_client, artifact, backup_plan),
                ))
            except (DataManagementBackupCanceledError, DataManagementBackupLeaseLostError):
                raise
            except Exception as exc:
                warning = f"AI Search backup resource '{artifact['name']}' failed: {str(exc)[:300]}"
                _append_backup_warning(backup_state, warning)
                _fail_backup_resource_checkpoint(
                    job,
                    backup_state,
                    settings,
                    documents_resource_name,
                    str(exc),
                    f"Recorded failed AI Search backup resource {artifact['index_name']}",
                )
                artifacts.append({
                    "name": artifact["name"],
                    "type": "ai_search_documents",
                    "status": "warning",
                    "warning": warning,
                })
    else:
        warning = "AI Search export is disabled for this backup."
        _append_backup_warning(backup_state, warning)
        _skip_backup_resource_checkpoint(
            job,
            backup_state,
            settings,
            "ai_search",
            warning,
            "Skipped disabled AI Search backup scope",
        )
    _set_job_progress(job, "AI Search export step completed", 2, total_steps, current_step="ai_search")

    if backup_plan.get("include_source_blobs"):
        source_blob_service_client = _get_source_blob_service_client()
        if source_blob_service_client is None:
            warning = "Source document Blob Storage client is not configured."
            _append_backup_warning(backup_state, warning)
            _skip_backup_resource_checkpoint(
                job,
                backup_state,
                settings,
                "source_blobs",
                warning,
                "Skipped unavailable source blob backup scope",
            )
            artifacts.append({
                "name": "source_blobs",
                "type": "source_blobs",
                "status": "skipped",
                "warning": warning,
            })
        else:
            for source_container_name in _source_blob_container_names():
                resource_name = f"source_blobs:{source_container_name}"
                if is_backup_resource_completed(backup_state, resource_name):
                    existing_resource = get_backup_resource(backup_state, resource_name)
                    artifacts.append(copy.deepcopy(existing_resource.get("result") or {}))
                    continue
                try:
                    artifacts.append(_execute_backup_source_blob_resource(
                        job,
                        backup_state,
                        settings,
                        container_client,
                        base_prefix,
                        fernet,
                        source_blob_service_client.get_container_client(source_container_name),
                        source_container_name,
                    ))
                except (DataManagementBackupCanceledError, DataManagementBackupLeaseLostError):
                    raise
                except Exception as exc:
                    warning = f"Source blob backup resource '{source_container_name}' failed: {str(exc)[:300]}"
                    _append_backup_warning(backup_state, warning)
                    _fail_backup_resource_checkpoint(
                        job,
                        backup_state,
                        settings,
                        resource_name,
                        str(exc),
                        f"Recorded failed source blob backup resource {source_container_name}",
                    )
                    artifacts.append({
                        "name": source_container_name,
                        "type": "source_blob_container",
                        "status": "warning",
                        "warning": warning,
                    })
    else:
        warning = "Source blob backup is disabled. Document restore will require the original source storage account."
        _append_backup_warning(backup_state, warning)
        _skip_backup_resource_checkpoint(
            job,
            backup_state,
            settings,
            "source_blobs",
            warning,
            "Skipped disabled source blob backup scope",
        )
    _set_job_progress(job, "Source blob export step completed", 3, total_steps, current_step="source_blobs")

    _assert_backup_job_lease(job)
    artifacts = _backup_state_resource_artifacts(backup_state)
    warnings = list(backup_state.get("warnings") or [])
    failed_resource_names = [
        resource_name
        for resource_name, resource in (backup_state.get("resources") or {}).items()
        if isinstance(resource, dict) and resource.get("status") == BACKUP_RESOURCE_STATUS_FAILED
    ]
    manifest = {
        "schema_version": 2,
        "app": "SimpleChat",
        "app_version": VERSION,
        "job_id": job.get("id"),
        "backup_type": job.get("backup_type"),
        "created_at": _now_iso(),
        "base_prefix": base_prefix,
        "backup_plan": copy.deepcopy(backup_plan),
        "source_cutoff_at": backup_plan.get("source_cutoff_at"),
        "differential_mode": backup_plan.get("differential_mode"),
        "deletion_policy": (backup_plan.get("source_cutoff_semantics") or {}).get("deletion_policy"),
        "encryption_enabled": bool(fernet),
        "encryption_key_storage": settings.get("encryption_key_storage"),
        "artifacts": summarize_backup_artifacts(artifacts),
        "warnings": warnings,
        "failed_resource_names": failed_resource_names,
        "totals": copy.deepcopy(backup_state.get("totals") or {}),
        "latest_item_state_contract": {
            "storage": "data_management_backup_item_states",
            "source_mutation": "none",
            "deletion_behavior": "non_destructive_not_recorded_as_delete",
        },
    }
    manifest_upload = _upload_json_artifact(
        container_client,
        f"{base_prefix}/manifest.json",
        manifest,
        fernet=fernet,
        backup_job=job,
        backup_settings=settings,
        heartbeat_message="Uploading durable backup manifest",
    )
    _assert_backup_job_lease(job)
    manifest_upload.update({"name": "manifest", "type": "manifest", "status": "completed"})
    artifacts.append(manifest_upload)
    artifact_summaries = summarize_backup_artifacts(artifacts)
    artifact_totals = _backup_artifact_totals(artifact_summaries)
    backup_state.update({
        "phase": "completed",
        "status": BACKUP_RESOURCE_STATUS_COMPLETED,
        "completed_at": _now_iso(),
        "manifest": {
            "path": manifest_upload.get("path"),
            "artifact_checkpoint_id": f"{job.get('id')}:manifest",
        },
        "failed_resource_names": failed_resource_names,
    })
    complete_backup_attempt(
        backup_state,
        "completed_with_warnings" if warnings or failed_resource_names else "completed",
    )
    _persist_backup_state(
        job,
        backup_state,
        settings,
        "Backup artifact manifest written",
    )

    _record_data_management_job_event(
        job.get("id"),
        "backup-export",
        job,
        status=(
            DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS
            if warnings or failed_resource_names else DATA_MANAGEMENT_STATUS_COMPLETED
        ),
        message="Backup export artifacts written",
        details={
            "manifest_path": manifest_upload.get("path"),
            "base_prefix": base_prefix,
            "artifact_count": len(artifacts),
            "artifact_totals": artifact_totals,
            "artifacts": artifact_summaries,
            "warnings": warnings,
            "failed_resource_count": len(failed_resource_names),
        },
    )

    settings_key = (
        "last_partial_backup_completed_at"
        if job.get("backup_type") == DATA_MANAGEMENT_BACKUP_PARTIAL else
        "last_full_backup_completed_at"
    )
    settings[settings_key] = _now_iso()
    settings["last_settings_update_at"] = _now_iso()
    cosmos_settings_container.upsert_item(normalize_data_management_settings(existing_settings=settings))

    return {
        "manifest_path": manifest_upload.get("path"),
        "base_prefix": base_prefix,
        "artifact_count": len(artifacts),
        "artifact_totals": artifact_totals,
        "artifacts": artifact_summaries,
        "warnings": warnings,
        "backup_state": backup_state,
        "failed_resource_names": failed_resource_names,
    }


def execute_migration_job(job, settings):
    options = job.get("options") if isinstance(job.get("options"), dict) else {}
    migration_plan = normalize_data_management_migration_plan(options)
    total_steps = 10
    _set_job_progress(
        job,
        "Resolving migration plan and baseline",
        0,
        total_steps,
        current_step="plan",
        allow_cancel_requested=True,
    )
    migration_plan = _resolve_data_management_migration_baseline(
        job,
        settings,
        migration_plan,
    )
    dry_run = bool(options.get("dry_run"))
    warnings = []
    artifacts = []

    plan_summary = summarize_data_management_migration_plan({"migration_plan": migration_plan})
    plan_summary["baseline_source_cutoff_at"] = migration_plan.get("baseline_source_cutoff_at")
    selected_total = sum(plan_summary[target_type]["count"] for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPES)
    if selected_total == 0:
        raise DataManagementSettingsValidationError("Choose at least one user, group, or public workspace before running migration.")

    migration_state, provenance_context = _initialize_data_management_migration_state(
        job,
        settings,
        migration_plan,
    )
    try:
        migration_state = _persist_migration_state(
            job,
            migration_state,
            settings,
            "Initialized durable migration provenance and checkpoint state",
        )
    except DataManagementMigrationCanceledError as exc:
        migration_state.update({
            "status": DATA_MANAGEMENT_STATUS_CANCELED,
            "canceled_at": _now_iso(),
            "last_error": None,
            "cancel_message": str(exc),
        })
        _persist_migration_state(
            job,
            migration_state,
            settings,
            "Migration cancellation acknowledged before execution started",
            allow_cancel_requested=True,
        )
        raise
    _set_job_progress(job, "Validated migration selection plan", 1, total_steps, current_step="plan")
    migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state
    _record_data_management_job_event(
        job.get("id"),
        "migration-plan",
        job,
        status=DATA_MANAGEMENT_STATUS_RUNNING,
        message="Migration selection plan validated",
        details={
            "migration_plan": plan_summary,
            "dry_run": dry_run,
            "migration_id": provenance_context["migration_id"],
            "parallel_operations": _get_migration_parallel_operations(settings),
        },
    )

    if dry_run:
        warning = "Migration dry run completed. No destination records were written."
        warnings.append(warning)
        migration_state.update({
            "status": MIGRATION_RESOURCE_STATUS_COMPLETED,
            "completed_at": _now_iso(),
        })
        migration_state = _persist_migration_state(job, migration_state, settings, warning)
        _set_job_progress(job, warning, total_steps, total_steps, current_step="dry_run", status=DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS)
        return {
            "migration_plan": plan_summary,
            "dry_run": True,
            "migration_id": provenance_context["migration_id"],
            "migration_state": migration_state,
            "artifacts": [],
            "artifact_totals": _backup_artifact_totals([]),
            "warnings": warnings,
        }

    _validate_target_ai_search_migration_write_safety(settings, migration_plan)
    _acquire_migration_destination_lock(job, settings, migration_plan)
    try:
        _save_data_management_job(job)
    except Exception:
        _release_migration_destination_lock(job)
        raise

    # The empty destination database must exist before it can host the target-wide coordinator.
    target_database = _get_target_cosmos_database(settings)
    try:
        _acquire_target_migration_coordinator(job, target_database, settings)
        _save_data_management_job(job)
    except Exception:
        _release_target_migration_coordinator(job)
        _release_migration_destination_lock(job)
        raise

    try:
        _set_job_progress(
            job,
            "Building server-owned migration inventory",
            1,
            total_steps,
            current_step="inventory",
        )
        preview_resource_name = "migration_preview:inventory"
        preview_resource = migration_state.get("resources", {}).get(preview_resource_name)
        migration_preview = (
            preview_resource.get("result")
            if is_migration_resource_completed(migration_state, preview_resource_name) and
            isinstance(preview_resource, dict) and
            isinstance(preview_resource.get("result"), dict)
            else None
        )
        if not isinstance(migration_preview, dict):
            start_migration_resource(migration_state, preview_resource_name)
            migration_state = _persist_migration_checkpoint(
                job,
                migration_state,
                settings,
                preview_resource_name,
                {"state": "inventory", "heartbeat_count": 0},
                "Building server-owned migration inventory preview",
            )
            preview_heartbeat_count = 0
            preview_last_heartbeat_at = 0.0

            def preview_heartbeat(message, completed_count=0):
                nonlocal migration_state, preview_heartbeat_count, preview_last_heartbeat_at
                preview_heartbeat_count += 1
                now = time.monotonic()
                if now - preview_last_heartbeat_at < 2.0:
                    return
                migration_state = _persist_migration_checkpoint(
                    job,
                    migration_state,
                    settings,
                    preview_resource_name,
                    {
                        "state": "inventory",
                        "heartbeat_count": preview_heartbeat_count,
                        "completed_count": completed_count,
                    },
                    message,
                )
                preview_last_heartbeat_at = now

            migration_preview = preview_data_management_migration_plan(
                settings,
                options,
                resolved_migration_plan=migration_plan,
                source_cutoff_at=migration_state.get("source_cutoff_at"),
                migration_id=job.get("id"),
                heartbeat_callback=preview_heartbeat,
            )
            migration_state = _complete_migration_resource_checkpoint(
                job,
                migration_state,
                settings,
                preview_resource_name,
                migration_preview,
                "Completed server-owned migration inventory preview",
            )
            options["migration_preview"] = migration_preview
            job["options"] = options
            migration_state = _persist_migration_state(
                job,
                migration_state,
                settings,
                "Pinned server-owned migration inventory preview",
            )

        _set_job_progress(job, "Migration inventory completed", 2, total_steps, current_step="inventory")
        _set_job_progress(job, "Validating migration destinations", 2, total_steps, current_step="preflight")
        migration_state = _run_data_management_migration_preflight(
            job,
            migration_state,
            settings,
            migration_plan,
        )
        _set_job_progress(job, "Destination migration preflight completed", 3, total_steps, current_step="preflight")
        migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state
        _record_data_management_job_event(
            job.get("id"),
            "migration-preflight",
            job,
            status=DATA_MANAGEMENT_STATUS_RUNNING,
            message="Verified source and destination migration access",
            details=migration_state.get("preflight") if isinstance(migration_state.get("preflight"), dict) else {},
        )

        _set_job_progress(job, "Preparing destination Cosmos capacity", 3, total_steps, current_step="capacity")
        migration_state = _apply_temporary_destination_capacity(
            job,
            migration_state,
            settings,
            migration_plan,
        )
        _set_job_progress(job, "Destination Cosmos capacity prepared", 4, total_steps, current_step="capacity")
        migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state

        _set_job_progress(job, "Migrating Cosmos records", 4, total_steps, current_step="cosmos")
        for target_type in DATA_MANAGEMENT_MIGRATION_TARGET_TYPE_ORDER:
            selection = migration_plan.get(target_type) or {}
            if selection.get("mode") == "none":
                continue
            copied = _copy_cosmos_records_to_target(
                target_database,
                target_type,
                selection,
                job,
                migration_state,
                provenance_context,
                settings,
            )
            migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state
            artifacts.extend(copied)
            _record_data_management_job_event(
                job.get("id"),
                f"migration-cosmos-{target_type}",
                job,
                status=DATA_MANAGEMENT_STATUS_RUNNING,
                message=f"Migrated {target_type.replace('_', ' ')} Cosmos records",
                details={"target_type": target_type, "artifacts": copied},
            )
        _set_job_progress(job, "Cosmos migration completed", 5, total_steps, current_step="cosmos")
        migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state

        search_artifacts = []
        if _migration_plan_includes_ai_search_documents(migration_plan):
            _set_job_progress(job, "Freezing target AI Search writers", 5, total_steps, current_step="ai_search")
            target_search_write_gate_container = _get_target_data_management_search_write_gate_container(
                target_database
            )
            target_search_write_fence = acquire_data_management_search_write_fence(
                target_search_write_gate_container,
                job.get("id"),
                _get_target_search_write_fence_lease_seconds(settings),
                heartbeat_callback=lambda: _persist_migration_heartbeat(
                    job,
                    settings,
                    "Waiting for target AI Search writers to drain",
                ),
            )
            release_target_search_write_fence = False
            try:
                _set_job_progress(job, "Migrating AI Search documents", 5, total_steps, current_step="ai_search")
                search_artifacts = _copy_ai_search_to_target(
                    settings,
                    migration_plan,
                    job,
                    migration_state,
                    provenance_context,
                    target_search_write_fence=(
                        target_search_write_gate_container,
                        target_search_write_fence,
                    ),
                )
                release_target_search_write_fence = True
            except DataManagementMigrationCanceledError:
                release_target_search_write_fence = True
                raise
            finally:
                if release_target_search_write_fence:
                    release_data_management_search_write_fence(
                        target_search_write_gate_container,
                        target_search_write_fence,
                    )
        migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state
        artifacts.extend(search_artifacts)
        _set_job_progress(job, "AI Search migration completed", 6, total_steps, current_step="ai_search")
        migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state

        _set_job_progress(job, "Migrating source document blobs", 6, total_steps, current_step="source_blobs")
        source_blob_artifacts = _copy_source_blobs_to_target(
            settings,
            migration_plan,
            job,
            migration_state,
            provenance_context,
        )
        migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state
        artifacts.extend(source_blob_artifacts)
        _set_job_progress(job, "Source blob migration completed", 7, total_steps, current_step="source_blobs")
        migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state

        _set_job_progress(job, "Reconciling source and destination", 7, total_steps, current_step="reconciliation")
        reconciliation_artifact = _run_data_management_migration_reconciliation(
            settings,
            migration_plan,
            job,
            migration_state,
            provenance_context,
            target_database,
            preview_snapshot=migration_preview,
            migration_artifacts=artifacts,
        )
        migration_state = job.get("migration_state") if isinstance(job.get("migration_state"), dict) else migration_state
        artifacts.append(reconciliation_artifact)
        _set_job_progress(job, "Migration reconciliation completed", 8, total_steps, current_step="reconciliation")
        _record_data_management_job_event(
            job.get("id"),
            "migration-reconciliation",
            job,
            status=DATA_MANAGEMENT_STATUS_RUNNING,
            message="Reconciled migration source and destination identities",
            details=reconciliation_artifact,
        )
    except DataManagementMigrationCanceledError as exc:
        migration_state.update({
            "status": DATA_MANAGEMENT_STATUS_CANCELED,
            "canceled_at": _now_iso(),
            "last_error": None,
            "cancel_message": str(exc),
        })
        _persist_migration_state(
            job,
            migration_state,
            settings,
            "Migration cancellation acknowledged at a durable checkpoint",
            allow_cancel_requested=True,
        )
        raise
    except Exception as exc:
        migration_state["status"] = MIGRATION_RESOURCE_STATUS_FAILED
        migration_state["last_error"] = str(exc)[:1000]
        _persist_migration_state(job, migration_state, settings, "Migration execution failed")
        raise
    finally:
        try:
            _set_job_progress(
                job,
                "Restoring destination Cosmos capacity",
                8,
                total_steps,
                current_step="capacity_restore",
                allow_cancel_requested=True,
            )
            restore_warnings, migration_state = _restore_temporary_destination_capacity(
                job,
                migration_state,
                settings,
                allow_cancel_requested=True,
            )
            warnings.extend(restore_warnings)
        except Exception as restore_exc:
            warnings.append(f"Failed to restore temporary destination Cosmos capacity: {str(restore_exc)[:300]}")

    capacity = (
        migration_state.get("capacity")
        if isinstance(migration_state.get("capacity"), dict)
        else {}
    )
    if capacity.get("restore_pending"):
        migration_state.update({
            "status": MIGRATION_RESOURCE_STATUS_FAILED,
            "last_error": "Destination Cosmos capacity restoration remains pending.",
        })
        _persist_migration_state(
            job,
            migration_state,
            settings,
            "Destination Cosmos capacity restoration remains pending; migration can be retried",
        )
        raise RuntimeError(
            "Destination Cosmos capacity restoration remains pending. Retry the migration to restore the recorded capacity snapshot."
        )

    for artifact in artifacts:
        if artifact.get("warning"):
            warnings.append(artifact.get("warning"))
    migration_state.update({
        "status": MIGRATION_RESOURCE_STATUS_COMPLETED,
        "completed_at": _now_iso(),
    })
    _update_migration_state_totals(migration_state)
    migration_state = _persist_migration_state(
        job,
        migration_state,
        settings,
        "Migration execution completed",
    )
    _set_job_progress(job, "Migration execution completed", 10, total_steps, current_step="complete")

    artifact_summaries = summarize_backup_artifacts(artifacts)
    artifact_totals = _backup_artifact_totals(artifact_summaries)
    _record_data_management_job_event(
        job.get("id"),
        "migration-complete",
        job,
        status=DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS if warnings else DATA_MANAGEMENT_STATUS_COMPLETED,
        message="Migration execution completed",
        details={
            "migration_plan": plan_summary,
            "migration_id": provenance_context["migration_id"],
            "migration_state": {
                "resume_count": migration_state.get("resume_count"),
                "totals": migration_state.get("totals"),
                "capacity": migration_state.get("capacity"),
            },
            "artifact_count": len(artifacts),
            "artifact_totals": artifact_totals,
            "artifacts": artifact_summaries,
            "warnings": warnings,
        },
    )
    return {
        "migration_plan": plan_summary,
        "dry_run": False,
        "migration_id": provenance_context["migration_id"],
        "migration_state": migration_state,
        "artifact_count": len(artifacts),
        "artifact_totals": artifact_totals,
        "artifacts": artifact_summaries,
        "warnings": warnings,
    }


def process_data_management_job(job_id):
    settings = get_data_management_settings()
    job = _try_claim_data_management_job(job_id, settings=settings)
    if not job:
        return None
    release_migration_lock = job.get("operation") != DATA_MANAGEMENT_OPERATION_MIGRATION
    release_backup_source_lock = job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP

    try:
        if job.get("operation") == DATA_MANAGEMENT_OPERATION_BACKUP:
            result = execute_backup_job(job, settings)
            warnings = list(job.get("warnings") or []) + result.get("warnings", [])
            failed_resource_names = list(result.get("failed_resource_names") or [])
            if failed_resource_names:
                warnings.append(
                    "One or more backup resources completed with retryable item failures."
                )
            status = DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS if warnings else DATA_MANAGEMENT_STATUS_COMPLETED
            message = "Backup completed with warnings" if warnings else "Backup completed successfully"
        elif job.get("operation") == DATA_MANAGEMENT_OPERATION_MIGRATION:
            result = execute_migration_job(job, settings)
            release_migration_lock = True
            warnings = list(job.get("warnings") or []) + result.get("warnings", [])
            status = DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS if warnings else DATA_MANAGEMENT_STATUS_COMPLETED
            message = "Migration completed with warnings" if warnings else "Migration completed successfully"
        else:
            warnings = list(job.get("warnings") or [])
            warnings.append(
                "Restore and migration apply logic has not run in this job. The durable job record, settings, and admin workflow are ready for the restore and migration implementation layer."
            )
            result = {"warnings": warnings}
            _record_data_management_job_event(
                job.get("id"),
                "orchestration-foundation",
                job,
                status=DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS,
                message="Restore and migration apply logic has not run in this job.",
                details={"message": warnings[-1]},
            )
            status = DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS
            message = "Data Management job foundation completed with implementation warnings"

        now = _now_iso()
        completed_progress = (
            copy.deepcopy(job.get("progress"))
            if isinstance(job.get("progress"), dict)
            else {}
        )
        if not completed_progress:
            completed_progress = {
                "total_steps": 1,
                "completed_steps": 1,
                "current_step": "complete",
                "percent_complete": 100,
            }
        else:
            completed_progress.update({
                "completed_steps": completed_progress.get("total_steps", 1),
                "current_step": "complete",
                "percent_complete": 100,
            })
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
            "progress": completed_progress,
        })
        saved_job = _save_data_management_job(job)
        _record_data_management_job_event(
            saved_job.get("id"),
            "completed",
            saved_job,
            status=status,
            message=message,
            details={"warnings": warnings, "result": result},
        )
        return saved_job
    except DataManagementBackupCanceledError:
        now = _now_iso()
        try:
            persisted_job = _read_job(job_id)
        except Exception:
            persisted_job = job
        backup_state = persisted_job.get("backup_state")
        if isinstance(backup_state, dict):
            backup_state.update({
                "status": BACKUP_RESOURCE_STATUS_CANCELED,
                "phase": "canceled",
                "completed_at": now,
                "updated_at": now,
                "last_error": None,
            })
            complete_backup_attempt(backup_state, "canceled")
        persisted_job.update({
            "status": DATA_MANAGEMENT_STATUS_CANCELED,
            "updated_at": now,
            "completed_at": now,
            "last_heartbeat_at": now,
            "last_message": "Backup canceled at a durable checkpoint.",
            "last_error": None,
            "lease_holder_id": None,
            "lease_expires_at": None,
            "backup_state": backup_state,
            "progress": {
                "total_steps": persisted_job.get("progress", {}).get("total_steps", 0),
                "completed_steps": persisted_job.get("progress", {}).get("completed_steps", 0),
                "current_step": "canceled",
                "percent_complete": persisted_job.get("progress", {}).get("percent_complete", 0),
            },
        })
        saved_job = _save_data_management_job(persisted_job)
        _record_data_management_job_event(
            saved_job.get("id"),
            "backup-canceled",
            saved_job,
            status=DATA_MANAGEMENT_STATUS_CANCELED,
            message="Backup canceled at a durable checkpoint.",
            details={
                "cancel_requested_at": saved_job.get("cancel_requested_at"),
                "reason_present": bool(saved_job.get("cancel_reason")),
            },
        )
        return saved_job
    except DataManagementMigrationCanceledError as exc:
        release_migration_lock = True
        now = _now_iso()
        migration_state = job.get("migration_state")
        if isinstance(migration_state, dict):
            migration_state.update({
                "status": DATA_MANAGEMENT_STATUS_CANCELED,
                "canceled_at": now,
                "updated_at": now,
                "last_error": None,
            })
        job.update({
            "status": DATA_MANAGEMENT_STATUS_CANCELED,
            "updated_at": now,
            "completed_at": now,
            "last_heartbeat_at": now,
            "last_message": "Migration canceled at a durable checkpoint.",
            "last_error": None,
            "lease_holder_id": None,
            "lease_expires_at": None,
            "migration_state": migration_state,
            "progress": {
                "total_steps": job.get("progress", {}).get("total_steps", 0),
                "completed_steps": job.get("progress", {}).get("completed_steps", 0),
                "current_step": "canceled",
                "percent_complete": job.get("progress", {}).get("percent_complete", 0),
            },
        })
        saved_job = _save_data_management_job(job)
        _record_data_management_job_event(
            saved_job.get("id"),
            "migration-canceled",
            saved_job,
            status=DATA_MANAGEMENT_STATUS_CANCELED,
            message="Migration canceled at a durable checkpoint.",
            details={
                "cancel_requested_at": saved_job.get("cancel_requested_at"),
                "reason_present": bool(saved_job.get("cancel_reason")),
            },
        )
        return saved_job
    except DataManagementBackupLeaseLostError as exc:
        log_event(
            "[DataManagement] Backup worker stopped after losing its job or source lease.",
            {"job_id": job_id, "operation": job.get("operation"), "error": str(exc)},
            level=logging.WARNING,
        )
        return None
    except DataManagementMigrationLeaseLostError as exc:
        log_event(
            "[DataManagement] Migration worker stopped after losing its job lease.",
            {"job_id": job_id, "operation": job.get("operation"), "error": str(exc)},
            level=logging.WARNING,
        )
        return None
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
        saved_job = _save_data_management_job(job)
        _record_data_management_job_event(
            saved_job.get("id"),
            "failed",
            saved_job,
            status=DATA_MANAGEMENT_STATUS_FAILED,
            message="Data Management job failed",
            details={"error": str(exc)},
        )
        return saved_job
    finally:
        if release_backup_source_lock:
            _release_backup_source_lock(job)
        if release_migration_lock:
            _release_target_migration_coordinator(job)
            _release_migration_destination_lock(job)


def submit_data_management_job(app, job_id):
    executor = app.extensions.get("executor") if app else None
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
    worker_thread = Thread(
        target=process_data_management_job,
        kwargs={"job_id": job_id},
        daemon=True,
        name=f"data-management-{job_id[:12]}",
    )
    worker_thread.start()
    return True


def build_scheduled_occurrence_id(backup_type, run_at):
    normalized_backup_type = backup_type if backup_type in DATA_MANAGEMENT_BACKUP_TYPES else DATA_MANAGEMENT_BACKUP_FULL
    scheduled_time = _parse_iso_datetime(run_at) or _now_utc()
    return f"data_management_{normalized_backup_type}_{scheduled_time.strftime('%Y%m%dT%H%MZ')}"


def check_due_data_management_jobs_once(app=None):
    settings = get_data_management_settings()
    current_time = _now_utc()
    recovery_results = recover_data_management_jobs(
        app=app,
        settings=settings,
        current_time=current_time,
    )
    if not settings.get("enabled"):
        return recovery_results

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

    return queued_jobs + recovery_results