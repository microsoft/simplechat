# functions_tabular_generated_exports.py
"""Durable background runs for large tabular generated exports."""

import asyncio
from collections import Counter, deque
import csv
import heapq
import hashlib
import io
import json
import logging
import math
import os
import re
import socket
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape as escape_xml_text

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import current_app, has_app_context
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import AzureChatPromptExecutionSettings
from semantic_kernel.contents.chat_history import ChatHistory as SKChatHistory
from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

from config import (
    CLIENTS,
    TABULAR_EXTENSIONS,
    cosmos_conversations_container,
    cosmos_tabular_export_runs_container,
    storage_account_group_documents_container_name,
    storage_account_personal_chat_container_name,
    storage_account_public_documents_container_name,
    storage_account_user_documents_container_name,
)
from functions_appinsights import log_event
from functions_analysis_deliverables import (
    is_analysis_internal_lineage_field,
    project_structured_deliverable_row,
)
from functions_assistant_table_exports import build_safe_csv_headers, neutralize_csv_spreadsheet_formula
from functions_tabular_csv_query import (
    iter_tabular_csv_query_rows,
    validate_tabular_csv_query_expression,
)
from functions_group import assert_group_role
from functions_generated_file_exports import (
    normalize_generated_output_format,
    serialize_generated_json,
    serialize_generated_xml,
)
from functions_model_endpoint_runtime import build_semantic_kernel_chat_service_for_model
from functions_public_workspaces import get_user_visible_public_workspace_ids_from_settings
from functions_settings import get_settings
from functions_simplechat_operations import upload_generated_analysis_artifact_stream_for_user


TABULAR_EXPORT_RUN_TYPE = 'tabular_generated_output_run'
TABULAR_EXPORT_CONTRACT_VERSION = 3
TABULAR_GENERATION_CONTRACT_VERSION = 1
TABULAR_RESPONSE_PROTOCOL_OBJECT_V1 = 'object-v1'
TABULAR_RESPONSE_PROTOCOL_COMPACT_ROW_ARRAY_V1 = 'compact-row-array-v1'
TABULAR_RESPONSE_PROTOCOLS = {
    TABULAR_RESPONSE_PROTOCOL_OBJECT_V1,
    TABULAR_RESPONSE_PROTOCOL_COMPACT_ROW_ARRAY_V1,
}
TABULAR_COMPACT_PLAN_HASH_PREFIX_LENGTH = 12
TABULAR_EXECUTOR_MODE_FIXED_WINDOW = 'fixed-window-v1'
TABULAR_EXECUTOR_MODE_ROLLING_POOL = 'rolling-pool-v1'
TABULAR_GENERATION_PLAN_VERSION = 1
TABULAR_GENERATION_PLAN_PROMPT_VERSION = 'tabular-generation-plan-v1'
TABULAR_GENERATION_PLAN_DEFAULT_RETRY_ATTEMPTS = 2
TABULAR_GENERATION_PLAN_MAX_SAMPLE_ROWS = 5
TABULAR_GENERATION_PLAN_MAX_COLUMNS = 200
TABULAR_GENERATION_PLAN_MAX_FIELDS = 50
TABULAR_GENERATION_PLAN_MAX_FIELD_NAME_CHARS = 128
TABULAR_GENERATION_PLAN_MAX_FIELD_DESCRIPTION_CHARS = 500
TABULAR_GENERATION_PLAN_MAX_QUESTION_CHARS = 24000
TABULAR_GENERATION_PLAN_MAX_GUIDANCE_CHARS = 200
TABULAR_GENERATION_PLAN_VALUE_TYPES = {
    'array',
    'boolean',
    'integer',
    'number',
    'object',
    'string',
}
TABULAR_ROLLOUT_PLANNER_MODES = {'off', 'shadow', 'active'}
TABULAR_ROLLOUT_HANDOFF_MODES = {'legacy', 'server', 'constrained_model'}
TABULAR_GENERATION_ROLLOUT_DEFAULT_PERCENTAGE = 100
TABULAR_GENERATION_ROLLOUT_BUCKET_COUNT = 100
TABULAR_GENERATION_ROLLOUT_HASH_VERSION = 1
TABULAR_GENERATION_ROLLOUT_COHORT_CANARY = 'canary'
TABULAR_GENERATION_ROLLOUT_COHORT_CONTROL = 'control'
TABULAR_RETRY_MODE_RUN_LEVEL = 'run-level-v1'
TABULAR_RETRY_MODE_INDEPENDENT_BATCH = 'independent-batch-v1'
TABULAR_RUN_TASK_STRUCTURED_EXPORT = 'structured_export'
TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS = 'hierarchical_analysis'
TABULAR_RUN_TASK_COMBINED = 'combined'
TABULAR_RUN_TASK_TYPES = {
    TABULAR_RUN_TASK_STRUCTURED_EXPORT,
    TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS,
    TABULAR_RUN_TASK_COMBINED,
}
TABULAR_RUN_CHUNK_MANIFEST_VERSION = 1
TABULAR_RUN_DEFAULT_CHUNK_MANIFEST_PAGE_SIZE = 250
TABULAR_EXPORT_STATUS_QUEUED = 'queued'
TABULAR_EXPORT_STATUS_RUNNING = 'running'
TABULAR_EXPORT_STATUS_COMPLETED = 'completed'
TABULAR_EXPORT_STATUS_FAILED = 'failed'
TABULAR_EXPORT_STATUS_CANCELED = 'canceled'
TABULAR_EXPORT_TERMINAL_STATUSES = {
    TABULAR_EXPORT_STATUS_COMPLETED,
    TABULAR_EXPORT_STATUS_FAILED,
    TABULAR_EXPORT_STATUS_CANCELED,
}

TABULAR_EXPORT_DEFAULT_INLINE_MAX_BATCHES = 75
TABULAR_EXPORT_DEFAULT_INLINE_MAX_ROWS = 500
TABULAR_EXPORT_DEFAULT_BATCH_RETRY_ATTEMPTS = 2
TABULAR_EXPORT_DEFAULT_MODEL_VALIDATION_AUTO_RETRIES = 3
TABULAR_EXPORT_DEFAULT_LEASE_SECONDS = 300
TABULAR_EXPORT_DEFAULT_STALE_SECONDS = 900
TABULAR_EXPORT_DEFAULT_SCAN_LIMIT = 5
TABULAR_EXPORT_DEFAULT_MAX_TRANSIENT_FAILURES = 20
TABULAR_EXPORT_DEFAULT_BATCH_CONCURRENCY = 16
TABULAR_EXPORT_HIGH_BATCH_CONCURRENCY = 64
TABULAR_EXPORT_MAX_BATCH_CONCURRENCY = 128
TABULAR_EXPORT_HIGH_CONCURRENCY_BATCH_THRESHOLD = 128
TABULAR_EXPORT_MAX_CONCURRENCY_BATCH_THRESHOLD = 256
TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS = 300
TABULAR_EXPORT_FINAL_SPOOL_MAX_MEMORY_BYTES = 1024 * 1024
TABULAR_EXPORT_DEFAULT_SOURCE_CHUNK_ROWS = 1000
TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_ROWS = 50
TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_CHARS = 60000
TABULAR_EXPORT_DEFAULT_SCHEMA_PROBE_ROWS = 5
TABULAR_EXPORT_MAX_SOURCE_BATCH_ROWS = 500
TABULAR_EXPORT_MAX_SOURCE_BATCH_CHARS = 720000
TABULAR_EXPORT_DEFAULT_CONTEXT_TOKEN_LIMIT = 128000
TABULAR_EXPORT_DEFAULT_OUTPUT_TOKEN_LIMIT = 65536
TABULAR_EXPORT_DEFAULT_INPUT_TOKEN_RATIO = 0.5
TABULAR_EXPORT_LARGE_CONTEXT_INPUT_TOKEN_RATIO = 0.3
TABULAR_EXPORT_DEFAULT_OUTPUT_TOKEN_RATIO = 0.6
TABULAR_EXPORT_LARGE_CONTEXT_TOKEN_THRESHOLD = 500000
TABULAR_EXPORT_INPUT_TOKEN_SOFT_CAP = 180000
TABULAR_EXPORT_PROMPT_TOKEN_RESERVE = 4096
TABULAR_EXPORT_APPROXIMATE_CHARS_PER_TOKEN = 4.0
TABULAR_EXPORT_DEFAULT_OUTPUT_EXPANSION_RATIO = 1.5
TABULAR_EXPORT_MODEL_CONTEXT_LIMIT_FIELDS = (
    'inputTokenLimit',
    'input_token_limit',
    'maxInputTokens',
    'max_input_tokens',
    'contextWindow',
    'context_window',
    'maxContextTokens',
    'max_context_tokens',
    'contextLength',
    'context_length',
)
TABULAR_EXPORT_MODEL_OUTPUT_LIMIT_FIELDS = (
    'outputTokenLimit',
    'output_token_limit',
    'maxOutputTokens',
    'max_output_tokens',
    'responseLength',
    'response_length',
    'maxCompletionTokens',
    'max_completion_tokens',
    'maxTokens',
    'max_tokens',
)
TABULAR_EXPORT_MODEL_LIMIT_CONTAINER_FIELDS = ('tokenLimits', 'token_limits', 'limits')
TABULAR_EXPORT_MODEL_IDENTIFIER_FIELDS = (
    'id',
    'modelId',
    'model_id',
    'model_deployment',
    'modelName',
    'model_name',
    'deploymentName',
    'deployment',
    'name',
)
TABULAR_ANALYSIS_DEFAULT_REDUCE_FAN_IN = 25
TABULAR_ANALYSIS_MAX_REDUCE_FAN_IN = 50
TABULAR_ANALYSIS_SUMMARY_MAX_CHARS = 24000
TABULAR_ANALYSIS_MAX_FINDINGS = 12
TABULAR_ANALYSIS_MAX_NOTABLE_ROWS = 25
TABULAR_EXPORT_SUMMARY_MAX_FIELDS = 25
TABULAR_EXPORT_SUMMARY_MAX_VALUES_PER_FIELD = 5
TABULAR_EXPORT_SUMMARY_AGGREGATE_MAX_VALUES = 25
TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_ROWS = 10
TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_CHARS = 24000
TABULAR_EXPORT_ARTIFACT_PREVIEW_CELL_MAX_CHARS = 240
TABULAR_EXPORT_PROGRESS_LOG_INTERVAL_SECONDS = 30
TABULAR_GENERATION_DEFAULT_HEARTBEAT_SECONDS = 30
TABULAR_GENERATION_DEFAULT_STALE_SECONDS = 120
TABULAR_GENERATION_DEFAULT_CHECKPOINT_WRITER_CONCURRENCY = 1
TABULAR_GENERATION_CHECKPOINT_HIGH_WATER_MULTIPLIER = 2
TABULAR_GENERATION_DEFAULT_SYSTEMIC_FAILURE_THRESHOLD = 0.5
TABULAR_GENERATION_RETRY_LEDGER_VERSION = 1
TABULAR_GENERATION_RETRY_BASE_DELAY_SECONDS = 15
TABULAR_GENERATION_RETRY_MAX_DELAY_SECONDS = 300
TABULAR_GENERATION_RETRY_MAX_JITTER_SECONDS = 12
TABULAR_EXPORT_SCHEDULER_STATUSES = (
    TABULAR_EXPORT_STATUS_QUEUED,
    TABULAR_EXPORT_STATUS_RUNNING,
    TABULAR_EXPORT_STATUS_FAILED,
)
TABULAR_EXPORT_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
TABULAR_EXPORT_RETRYABLE_EXCEPTION_NAMES = {
    'APIConnectionError',
    'APITimeoutError',
    'APIStatusError',
    'InternalServerError',
    'RateLimitError',
    'ServiceRequestError',
    'ServiceResponseError',
    'ServiceResponseTimeoutError',
    'HttpResponseError',
    'TimeoutError',
    'ConnectionError',
}
TABULAR_EXPORT_RETRYABLE_MESSAGE_MARKERS = (
    'api connection error',
    'apiconnectionerror',
    'connection error',
    'connection aborted',
    'connection reset',
    'server disconnected',
    'service unavailable',
    'temporarily unavailable',
    'too many requests',
    'rate limit',
    'timed out',
    'timeout',
    'worker exiting',
    'worker restart',
)
TABULAR_EXPORT_MODEL_VALIDATION_RETRYABLE_MESSAGE_MARKERS = (
    'failed validation',
    'schema mismatch',
    'schema drift',
    'source row token mismatch',
    'did not return the required',
    'returned no content after tool errors',
    'returned no content after workbook tool errors',
    'returned no content',
    'response did not contain valid structured_rows',
    'was not a valid compact json analysis summary',
    'was not a valid json object',
)
TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD = '__simplechat_source_row_number'
TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD = '__simplechat_source_row_identity'
TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD = '__simplechat_source_row_token'
TABULAR_EXPORT_INPUT_ROW_KEY_FIELD = '__simplechat_batch_row_key'
TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD = 'source_row_number'
TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD = 'source_row_identity'
TABULAR_GENERATION_PLAN_RESERVED_FIELDS = {
    TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD,
    TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD,
    TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD,
    TABULAR_EXPORT_INPUT_ROW_KEY_FIELD,
    TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
    TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
}


class TabularExportCanceledError(RuntimeError):
    """Raised when a durable export is canceled between checkpoints."""


class TabularExportLeaseLostError(RuntimeError):
    """Raised when a stale worker no longer owns the durable run claim."""


class TabularGenerationPlanError(RuntimeError):
    """Raised when the bounded planner exhausts its allowed attempts."""

    def __init__(self, reason):
        super().__init__('Tabular generation planner did not produce a valid plan')
        self.reason = str(reason or 'provider_failure')


def _now_utc():
    return datetime.now(timezone.utc)


def _now_iso():
    return _now_utc().isoformat()


def _safe_int(value, default=0, minimum=None, maximum=None):
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = default

    if minimum is not None:
        parsed_value = max(minimum, parsed_value)
    if maximum is not None:
        parsed_value = min(maximum, parsed_value)
    return parsed_value


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _settings_bool(settings, key, default=False):
    value = (settings or {}).get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _settings_int(settings, key, default, minimum=None, maximum=None):
    return _safe_int((settings or {}).get(key, default), default=default, minimum=minimum, maximum=maximum)


def _settings_float(settings, key, default, minimum=None, maximum=None):
    parsed_value = _safe_float((settings or {}).get(key, default), default=default)
    if minimum is not None:
        parsed_value = max(minimum, parsed_value)
    if maximum is not None:
        parsed_value = min(maximum, parsed_value)
    return parsed_value


def _settings_mode(settings, key, default, allowed_modes):
    normalized_mode = str((settings or {}).get(key, default) or default).strip().lower()
    if normalized_mode in allowed_modes:
        return normalized_mode
    return default


def _is_compact_row_array_protocol(response_protocol):
    return str(response_protocol or '').strip() == TABULAR_RESPONSE_PROTOCOL_COMPACT_ROW_ARRAY_V1


def _select_tabular_response_protocol(rollout_settings, requested_plan_mode, task_type, passthrough_input_rows=False):
    if (
        _settings_bool(rollout_settings, 'enable_tabular_compact_response_protocol', False)
        and str(requested_plan_mode or '').strip().lower() == 'active'
        and _normalize_tabular_run_task_type(task_type) == TABULAR_RUN_TASK_STRUCTURED_EXPORT
        and not passthrough_input_rows
    ):
        return TABULAR_RESPONSE_PROTOCOL_COMPACT_ROW_ARRAY_V1
    return TABULAR_RESPONSE_PROTOCOL_OBJECT_V1


def _canonical_json_bytes(payload):
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')


def _sha256_json(payload):
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _hash_tabular_generation_plan(plan):
    canonical_plan = dict(plan or {})
    canonical_plan.pop('plan_hash', None)
    return _sha256_json(canonical_plan)


def _describe_tabular_generation_plan_value(value):
    if value is None:
        return '<null>'
    if isinstance(value, bool):
        return '<boolean>'
    if isinstance(value, int):
        return '<integer>'
    if isinstance(value, float):
        return '<number>'
    if isinstance(value, dict):
        return f'<object:{len(value)} field(s)>'
    if isinstance(value, (list, tuple, set)):
        return f'<array:{len(value)} item(s)>'
    return f'<string:{len(str(value))} char(s)>'


def _infer_tabular_generation_plan_value_type(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'number'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, (list, tuple, set)):
        return 'array'
    return 'string'


def _build_tabular_generation_plan_input_contract(sample_rows):
    bounded_rows = list(sample_rows or [])[:TABULAR_GENERATION_PLAN_MAX_SAMPLE_ROWS]
    columns = []
    columns_by_name = {}
    sample_shapes = []
    for row_index, row in enumerate(bounded_rows):
        if not isinstance(row, dict):
            raise ValueError(f'Planner sample row {row_index + 1} is not an object')

        public_row = {
            str(field_name): field_value
            for field_name, field_value in row.items()
            if str(field_name) not in TABULAR_GENERATION_PLAN_RESERVED_FIELDS
        }
        sample_shape = {}
        for field_name, field_value in public_row.items():
            if not field_name or len(field_name) > TABULAR_GENERATION_PLAN_MAX_FIELD_NAME_CHARS:
                raise ValueError('Planner input column name is empty or too long')
            if field_name not in columns_by_name:
                if len(columns) >= TABULAR_GENERATION_PLAN_MAX_COLUMNS:
                    raise ValueError('Planner input column count exceeds the supported limit')
                column = {
                    'name': field_name,
                    'types': [],
                    'nullable': row_index > 0,
                }
                columns.append(column)
                columns_by_name[field_name] = column
            column = columns_by_name[field_name]
            value_type = _infer_tabular_generation_plan_value_type(field_value)
            if value_type and value_type not in column['types']:
                column['types'].append(value_type)
            if field_value is None:
                column['nullable'] = True
            sample_shape[field_name] = _describe_tabular_generation_plan_value(field_value)

        for column in columns:
            if column['name'] not in public_row:
                column['nullable'] = True
        sample_shapes.append(sample_shape)

    if not columns:
        raise ValueError('Planner input schema is empty')
    for column in columns:
        if not column['types']:
            column['types'] = ['string']

    schema_contract = {'columns': columns}
    return {
        'columns': columns,
        'sample_shapes': sample_shapes,
        'sample_row_count': len(sample_shapes),
        'input_schema_hash': _sha256_json(schema_contract),
    }


def _validate_tabular_generation_plan_output_fields(output_fields):
    if not isinstance(output_fields, list) or not output_fields:
        raise ValueError('Planner response must include at least one output field')
    if len(output_fields) > TABULAR_GENERATION_PLAN_MAX_FIELDS:
        raise ValueError('Planner response contains too many output fields')

    normalized_fields = []
    seen_names = set()
    allowed_keys = {'name', 'description', 'type', 'nullable', 'source'}
    reserved_names = {
        field_name.casefold()
        for field_name in TABULAR_GENERATION_PLAN_RESERVED_FIELDS
    }
    for field_index, output_field in enumerate(output_fields, start=1):
        if not isinstance(output_field, dict):
            raise ValueError(f'Planner output field {field_index} is not an object')
        if set(output_field) != allowed_keys:
            raise ValueError(f'Planner output field {field_index} has invalid properties')

        field_name = str(output_field.get('name') or '').strip()
        normalized_name = field_name.casefold()
        if not field_name or len(field_name) > TABULAR_GENERATION_PLAN_MAX_FIELD_NAME_CHARS:
            raise ValueError(f'Planner output field {field_index} has an invalid name')
        if any(ord(character) < 32 for character in field_name):
            raise ValueError(f'Planner output field {field_index} contains control characters')
        if normalized_name in reserved_names:
            raise ValueError(f'Planner output field {field_index} uses a reserved source field')
        if normalized_name in seen_names:
            raise ValueError(f'Planner output field {field_index} duplicates another field')
        seen_names.add(normalized_name)

        field_description = str(output_field.get('description') or '').strip()
        if (
            not field_description
            or len(field_description) > TABULAR_GENERATION_PLAN_MAX_FIELD_DESCRIPTION_CHARS
        ):
            raise ValueError(f'Planner output field {field_index} has an invalid description')
        value_type = str(output_field.get('type') or '').strip().lower()
        if value_type not in TABULAR_GENERATION_PLAN_VALUE_TYPES:
            raise ValueError(f'Planner output field {field_index} has an unsupported type')
        nullable = output_field.get('nullable')
        if not isinstance(nullable, bool):
            raise ValueError(f'Planner output field {field_index} must declare nullability')
        if str(output_field.get('source') or '').strip().lower() != 'llm':
            raise ValueError(f'Planner output field {field_index} has an unsupported source')

        normalized_fields.append({
            'name': field_name,
            'description': field_description,
            'type': value_type,
            'nullable': nullable,
            'source': 'llm',
        })
    return normalized_fields


def _get_tabular_generation_plan_source(run):
    source = (run or {}).get('source_descriptor') or (run or {}).get('source_authorization') or {}
    return {
        'blob_path': str(source.get('blob_path') or '').strip(),
        'blob_etag': str(source.get('blob_etag') or '').strip(),
        'row_count': _safe_int((run or {}).get('row_count'), minimum=0),
    }


def _build_tabular_generation_plan(run, planner_payload, input_contract, planner_model, created_at=None):
    if not isinstance(planner_payload, dict):
        raise ValueError('Planner response was not a JSON object')
    if set(planner_payload) - {'output_fields', 'output_verbosity'}:
        raise ValueError('Planner response contains unsupported top-level properties')

    llm_fields = _validate_tabular_generation_plan_output_fields(
        planner_payload.get('output_fields')
    )
    output_verbosity = str(planner_payload.get('output_verbosity') or '').strip()
    if len(output_verbosity) > TABULAR_GENERATION_PLAN_MAX_GUIDANCE_CHARS:
        raise ValueError('Planner output verbosity guidance is too long')

    output_format = str((run or {}).get('output_format') or '').strip().lower()
    if output_format not in {'csv', 'json', 'xml'}:
        raise ValueError('Planner output format is not supported')
    response_protocol = str(
        (run or {}).get('response_protocol_version') or TABULAR_RESPONSE_PROTOCOL_OBJECT_V1
    ).strip()
    if response_protocol not in TABULAR_RESPONSE_PROTOCOLS:
        raise ValueError('Planner response protocol is not supported')

    batch_budget = (run or {}).get('batch_budget') or {}
    source = _get_tabular_generation_plan_source(run)
    source['input_schema_hash'] = str(input_contract.get('input_schema_hash') or '').strip()
    if not source['input_schema_hash']:
        raise ValueError('Planner input schema hash is missing')

    normalized_planner_model = {
        field_name: str((planner_model or {}).get(field_name) or '').strip()
        for field_name in ('endpoint_id', 'model_id', 'deployment')
    }
    if not any(normalized_planner_model.values()):
        raise ValueError('Planner model identity is missing')

    plan = {
        'version': TABULAR_GENERATION_PLAN_VERSION,
        'run_id': str((run or {}).get('id') or '').strip(),
        'created_at': str(created_at or _now_iso()),
        'source': source,
        'model': normalized_planner_model,
        'request': {
            'question_hash': hashlib.sha256(
                str((run or {}).get('user_question') or '').encode('utf-8')
            ).hexdigest(),
            'output_format': output_format,
        },
        'output_fields': [
            {
                'name': TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
                'description': 'One-based source row order reattached by the server.',
                'type': 'integer',
                'nullable': False,
                'source': 'server',
            },
            {
                'name': TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
                'description': 'Source row identity reattached by the server.',
                'type': 'string',
                'nullable': False,
                'source': 'server',
            },
            *llm_fields,
        ],
        'response_protocol': response_protocol,
        'prompt_version': TABULAR_GENERATION_PLAN_PROMPT_VERSION,
        'batch_budget': {
            'max_rows': _safe_int(batch_budget.get('max_rows'), minimum=1),
            'max_chars': _safe_int(batch_budget.get('max_chars'), minimum=1),
            'input_tokens': _safe_int(batch_budget.get('input_token_budget'), minimum=1),
            'output_tokens': _safe_int(batch_budget.get('output_token_budget'), minimum=1),
        },
    }
    if output_verbosity:
        plan['output_verbosity'] = output_verbosity
    if not plan['run_id']:
        raise ValueError('Planner run identity is missing')
    plan['plan_hash'] = _hash_tabular_generation_plan(plan)
    return plan


def _validate_tabular_generation_plan(plan, run, input_schema_hash=None):
    if not isinstance(plan, dict):
        raise ValueError('Stored generation plan is not a JSON object')
    required_keys = {
        'version',
        'run_id',
        'created_at',
        'source',
        'model',
        'request',
        'output_fields',
        'response_protocol',
        'prompt_version',
        'batch_budget',
        'plan_hash',
    }
    allowed_keys = required_keys | {'output_verbosity'}
    if set(plan) - allowed_keys:
        raise ValueError('Stored generation plan contains unsupported properties')
    if not required_keys.issubset(plan):
        raise ValueError('Stored generation plan is missing required properties')
    if _safe_int(plan.get('version')) != TABULAR_GENERATION_PLAN_VERSION:
        raise ValueError('Stored generation plan version is not supported')
    if str(plan.get('run_id') or '').strip() != str((run or {}).get('id') or '').strip():
        raise ValueError('Stored generation plan run identity does not match')
    if not str(plan.get('created_at') or '').strip():
        raise ValueError('Stored generation plan creation time is missing')
    expected_hash = _hash_tabular_generation_plan(plan)
    if str(plan.get('plan_hash') or '').strip() != expected_hash:
        raise ValueError('Stored generation plan hash does not match its contents')

    source = plan.get('source')
    if not isinstance(source, dict) or set(source) != {
        'blob_path',
        'blob_etag',
        'row_count',
        'input_schema_hash',
    }:
        raise ValueError('Stored generation plan source contract is invalid')
    expected_source = _get_tabular_generation_plan_source(run)
    for field_name in ('blob_path', 'blob_etag', 'row_count'):
        if source.get(field_name) != expected_source.get(field_name):
            raise ValueError(f'Stored generation plan source {field_name} does not match')
    stored_input_schema_hash = str(source.get('input_schema_hash') or '').strip()
    if not re.fullmatch(r'[0-9a-f]{64}', stored_input_schema_hash):
        raise ValueError('Stored generation plan input schema hash is invalid')
    if input_schema_hash and source.get('input_schema_hash') != input_schema_hash:
        raise ValueError('Stored generation plan input schema hash does not match')

    model_contract = plan.get('model')
    if not isinstance(model_contract, dict) or set(model_contract) != {
        'endpoint_id',
        'model_id',
        'deployment',
    }:
        raise ValueError('Stored generation plan model contract is invalid')
    if not any(str(value or '').strip() for value in model_contract.values()):
        raise ValueError('Stored generation plan model identity is missing')
    if any(len(str(value or '')) > 500 for value in model_contract.values()):
        raise ValueError('Stored generation plan model identity is too long')
    expected_model_contract = (run or {}).get('planner_model')
    if isinstance(expected_model_contract, dict) and any(expected_model_contract.values()):
        normalized_expected_model = {
            field_name: str(expected_model_contract.get(field_name) or '').strip()
            for field_name in ('endpoint_id', 'model_id', 'deployment')
        }
        if model_contract != normalized_expected_model:
            raise ValueError('Stored generation plan model identity does not match')

    request_contract = plan.get('request')
    expected_question_hash = hashlib.sha256(
        str((run or {}).get('user_question') or '').encode('utf-8')
    ).hexdigest()
    if not isinstance(request_contract, dict) or request_contract != {
        'question_hash': expected_question_hash,
        'output_format': str((run or {}).get('output_format') or '').strip().lower(),
    }:
        raise ValueError('Stored generation plan request contract does not match')
    if plan.get('response_protocol') != (
        (run or {}).get('response_protocol_version') or TABULAR_RESPONSE_PROTOCOL_OBJECT_V1
    ):
        raise ValueError('Stored generation plan response protocol does not match')
    if plan.get('prompt_version') != TABULAR_GENERATION_PLAN_PROMPT_VERSION:
        raise ValueError('Stored generation plan prompt version does not match')

    stored_batch_budget = plan.get('batch_budget')
    run_batch_budget = (run or {}).get('batch_budget') or {}
    expected_batch_budget = {
        'max_rows': _safe_int(run_batch_budget.get('max_rows'), minimum=1),
        'max_chars': _safe_int(run_batch_budget.get('max_chars'), minimum=1),
        'input_tokens': _safe_int(run_batch_budget.get('input_token_budget'), minimum=1),
        'output_tokens': _safe_int(run_batch_budget.get('output_token_budget'), minimum=1),
    }
    if stored_batch_budget != expected_batch_budget:
        raise ValueError('Stored generation plan batch budget does not match')

    output_verbosity = str(plan.get('output_verbosity') or '').strip()
    if len(output_verbosity) > TABULAR_GENERATION_PLAN_MAX_GUIDANCE_CHARS:
        raise ValueError('Stored generation plan output guidance is too long')

    output_fields = plan.get('output_fields')
    if not isinstance(output_fields, list) or len(output_fields) < 3:
        raise ValueError('Stored generation plan output fields are invalid')
    expected_server_fields = [
        (TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD, 'integer'),
        (TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD, 'string'),
    ]
    for output_field, (expected_name, expected_type) in zip(output_fields[:2], expected_server_fields):
        if not isinstance(output_field, dict) or set(output_field) != {
            'name',
            'description',
            'type',
            'nullable',
            'source',
        }:
            raise ValueError('Stored generation plan server field properties are invalid')
        if output_field.get('name') != expected_name:
            raise ValueError('Stored generation plan server fields are invalid')
        if output_field.get('type') != expected_type or output_field.get('source') != 'server':
            raise ValueError('Stored generation plan server field contract is invalid')
        if output_field.get('nullable') is not False:
            raise ValueError('Stored generation plan server fields cannot be nullable')
        description = str(output_field.get('description') or '').strip()
        if not description or len(description) > TABULAR_GENERATION_PLAN_MAX_FIELD_DESCRIPTION_CHARS:
            raise ValueError('Stored generation plan server field description is invalid')
    normalized_llm_fields = _validate_tabular_generation_plan_output_fields(output_fields[2:])
    if normalized_llm_fields != output_fields[2:]:
        raise ValueError('Stored generation plan output fields are not normalized')
    return plan


def _get_tabular_generation_plan_output_schema(plan):
    return [
        str(output_field.get('name') or '').strip()
        for output_field in (plan or {}).get('output_fields') or []
        if isinstance(output_field, dict)
    ]


def _get_tabular_generation_plan_llm_fields(plan):
    return [
        output_field
        for output_field in (plan or {}).get('output_fields') or []
        if isinstance(output_field, dict)
        and str(output_field.get('source') or '').strip().lower() == 'llm'
    ]


def _get_compact_plan_hash_prefix(plan):
    plan_hash = str((plan or {}).get('plan_hash') or '').strip()
    if not plan_hash:
        raise ValueError('Compact response plan hash is missing')
    return plan_hash[:TABULAR_COMPACT_PLAN_HASH_PREFIX_LENGTH]


def _build_compact_batch_row_key(row_index):
    return f'r{_safe_int(row_index, minimum=1)}'


def _build_compact_batch_key_map(source_rows):
    key_map = {}
    ordered_keys = []
    for row_index, source_row in enumerate(source_rows or [], start=1):
        if not isinstance(source_row, dict):
            raise ValueError(f'Source row {row_index} is not an object')
        row_key = _build_compact_batch_row_key(row_index)
        ordered_keys.append(row_key)
        key_map[row_key] = source_row
    return ordered_keys, key_map


def _build_compact_prompt_rows(source_rows):
    prompt_rows = []
    ordered_keys, _ = _build_compact_batch_key_map(source_rows)
    for row_key, source_row in zip(ordered_keys, source_rows or []):
        prompt_row = {
            TABULAR_EXPORT_INPUT_ROW_KEY_FIELD: row_key,
        }
        prompt_row.update({
            str(field_name): field_value
            for field_name, field_value in source_row.items()
            if str(field_name) not in TABULAR_GENERATION_PLAN_RESERVED_FIELDS
        })
        prompt_rows.append(prompt_row)
    return prompt_rows


def _validate_compact_row_field_value(field_contract, field_value, row_key):
    field_name = str((field_contract or {}).get('name') or '').strip()
    field_type = str((field_contract or {}).get('type') or '').strip().lower()
    if field_value is None:
        if field_contract.get('nullable') is True:
            return
        raise ValueError(f'Compact row {row_key} returned null for non-nullable field {field_name}')

    type_matches = (
        (field_type == 'string' and isinstance(field_value, str))
        or (field_type == 'boolean' and isinstance(field_value, bool))
        or (field_type == 'integer' and isinstance(field_value, int) and not isinstance(field_value, bool))
        or (field_type == 'number' and isinstance(field_value, (int, float)) and not isinstance(field_value, bool))
        or (field_type == 'array' and isinstance(field_value, list))
        or (field_type == 'object' and isinstance(field_value, dict))
    )
    if not type_matches:
        raise ValueError(
            f'Compact row {row_key} field {field_name} did not match expected {field_type} value type'
        )


def _parse_compact_row_array_entries(response_content, source_rows, generation_plan):
    if not isinstance(generation_plan, dict):
        raise ValueError('Compact response validation requires an active generation plan')
    payload = _parse_generated_json_object(response_content)
    if not isinstance(payload, dict):
        raise ValueError('Compact response was not a JSON object')
    if set(payload) != {'p', 'rows'}:
        raise ValueError('Compact response contained unsupported top-level properties')

    expected_prefix = _get_compact_plan_hash_prefix(generation_plan)
    if str(payload.get('p') or '').strip() != expected_prefix:
        raise ValueError('Compact response plan hash prefix mismatch')
    compact_rows = payload.get('rows')
    if not isinstance(compact_rows, list):
        raise ValueError('Compact response rows must be an array')

    llm_fields = _get_tabular_generation_plan_llm_fields(generation_plan)
    if not llm_fields:
        raise ValueError('Compact response plan has no LLM output fields')
    expected_width = 1 + len(llm_fields)
    ordered_keys, key_map = _build_compact_batch_key_map(source_rows)
    entries_by_key = {}
    for response_row_index, compact_row in enumerate(compact_rows, start=1):
        if not isinstance(compact_row, list):
            raise ValueError(f'Compact response row {response_row_index} was not an array')
        if len(compact_row) != expected_width:
            raise ValueError(
                f'Compact response row {response_row_index} had {len(compact_row)} value(s); '
                f'expected {expected_width}'
            )
        row_key = str(compact_row[0] or '').strip()
        if row_key not in key_map:
            raise ValueError(f'Compact response included unknown row key {row_key}')
        if row_key in entries_by_key:
            raise ValueError(f'Compact response duplicated row key {row_key}')

        source_row = key_map[row_key]
        generated_entry = {
            TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD: str(
                source_row.get(TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD) or ''
            ).strip(),
        }
        for field_contract, field_value in zip(llm_fields, compact_row[1:]):
            _validate_compact_row_field_value(field_contract, field_value, row_key)
            generated_entry[str(field_contract.get('name') or '').strip()] = field_value
        entries_by_key[row_key] = generated_entry

    missing_keys = [row_key for row_key in ordered_keys if row_key not in entries_by_key]
    if missing_keys:
        raise ValueError(f'Compact response missed row key(s): {missing_keys}')
    return [entries_by_key[row_key] for row_key in ordered_keys]


def _normalize_tabular_generation_rollout_settings(settings):
    settings = settings or {}
    return {
        'tabular_generation_rollout_percentage': _settings_int(
            settings,
            'tabular_generation_rollout_percentage',
            TABULAR_GENERATION_ROLLOUT_DEFAULT_PERCENTAGE,
            minimum=0,
            maximum=100,
        ),
        'tabular_background_handoff_mode': _settings_mode(
            settings,
            'tabular_background_handoff_mode',
            'legacy',
            TABULAR_ROLLOUT_HANDOFF_MODES,
        ),
        'tabular_generation_plan_mode': _settings_mode(
            settings,
            'tabular_generation_plan_mode',
            'shadow',
            TABULAR_ROLLOUT_PLANNER_MODES,
        ),
        'enable_tabular_generation_plan': _settings_bool(
            settings,
            'enable_tabular_generation_plan',
            True,
        ),
        'enable_tabular_compact_response_protocol': _settings_bool(
            settings,
            'enable_tabular_compact_response_protocol',
            False,
        ),
        'enable_tabular_completion_driven_checkpointing': _settings_bool(
            settings,
            'enable_tabular_completion_driven_checkpointing',
            True,
        ),
        'enable_tabular_rolling_worker_pool': _settings_bool(
            settings,
            'enable_tabular_rolling_worker_pool',
            False,
        ),
        'enable_tabular_independent_batch_retries': _settings_bool(
            settings,
            'enable_tabular_independent_batch_retries',
            False,
        ),
        'enable_tabular_generation_balanced_batches': _settings_bool(
            settings,
            'enable_tabular_generation_balanced_batches',
            True,
        ),
        'tabular_generation_checkpoint_writer_concurrency': _settings_int(
            settings,
            'tabular_generation_checkpoint_writer_concurrency',
            TABULAR_GENERATION_DEFAULT_CHECKPOINT_WRITER_CONCURRENCY,
            minimum=1,
            maximum=16,
        ),
        'tabular_generation_heartbeat_seconds': _settings_int(
            settings,
            'tabular_generation_heartbeat_seconds',
            TABULAR_GENERATION_DEFAULT_HEARTBEAT_SECONDS,
            minimum=5,
            maximum=300,
        ),
        'tabular_generation_stale_seconds': _settings_int(
            settings,
            'tabular_generation_stale_seconds',
            TABULAR_GENERATION_DEFAULT_STALE_SECONDS,
            minimum=60,
            maximum=900,
        ),
        'tabular_generation_systemic_failure_threshold': _settings_float(
            settings,
            'tabular_generation_systemic_failure_threshold',
            TABULAR_GENERATION_DEFAULT_SYSTEMIC_FAILURE_THRESHOLD,
            minimum=0.0,
            maximum=1.0,
        ),
    }


def _get_tabular_generation_rollout_bucket(user_id, conversation_id, run_id):
    assignment_key = ':'.join((
        f'v{TABULAR_GENERATION_ROLLOUT_HASH_VERSION}',
        str(user_id or '').strip(),
        str(conversation_id or '').strip(),
        str(run_id or '').strip(),
    ))
    assignment_digest = hashlib.sha256(assignment_key.encode('utf-8')).digest()
    return int.from_bytes(assignment_digest[:8], byteorder='big') % TABULAR_GENERATION_ROLLOUT_BUCKET_COUNT + 1


def _build_tabular_generation_rollout_assignment(settings, user_id, conversation_id, run_id):
    rollout_settings = _normalize_tabular_generation_rollout_settings(settings)
    rollout_percentage = rollout_settings['tabular_generation_rollout_percentage']
    rollout_bucket = _get_tabular_generation_rollout_bucket(user_id, conversation_id, run_id)
    rollout_cohort = (
        TABULAR_GENERATION_ROLLOUT_COHORT_CANARY
        if rollout_bucket <= rollout_percentage
        else TABULAR_GENERATION_ROLLOUT_COHORT_CONTROL
    )
    if rollout_cohort == TABULAR_GENERATION_ROLLOUT_COHORT_CONTROL:
        rollout_settings.update({
            'tabular_background_handoff_mode': 'legacy',
            'tabular_generation_plan_mode': 'off',
            'enable_tabular_generation_plan': False,
            'enable_tabular_compact_response_protocol': False,
            'enable_tabular_completion_driven_checkpointing': False,
            'enable_tabular_rolling_worker_pool': False,
            'enable_tabular_independent_batch_retries': False,
            'enable_tabular_generation_balanced_batches': False,
        })
    rollout_settings.update({
        'tabular_generation_rollout_bucket': rollout_bucket,
        'tabular_generation_rollout_cohort': rollout_cohort,
        'tabular_generation_rollout_hash_version': TABULAR_GENERATION_ROLLOUT_HASH_VERSION,
    })
    return rollout_settings


def _get_tabular_generation_rollout_settings_for_run(run=None, settings=None):
    rollout_settings = (run or {}).get('generation_rollout_settings') if isinstance(run, dict) else None
    if isinstance(rollout_settings, dict) and rollout_settings:
        normalized_rollout_settings = _normalize_tabular_generation_rollout_settings(rollout_settings)
        if 'tabular_generation_stale_seconds' not in rollout_settings:
            normalized_rollout_settings['tabular_generation_stale_seconds'] = TABULAR_EXPORT_DEFAULT_STALE_SECONDS
        return normalized_rollout_settings
    if isinstance(run, dict):
        return _normalize_tabular_generation_rollout_settings({
            'tabular_generation_rollout_percentage': 0,
            'tabular_background_handoff_mode': 'legacy',
            'tabular_generation_plan_mode': 'off',
            'enable_tabular_generation_plan': False,
            'enable_tabular_compact_response_protocol': False,
            'enable_tabular_completion_driven_checkpointing': False,
            'enable_tabular_rolling_worker_pool': False,
            'enable_tabular_independent_batch_retries': False,
            'enable_tabular_generation_balanced_batches': False,
            'tabular_generation_stale_seconds': TABULAR_EXPORT_DEFAULT_STALE_SECONDS,
        })
    return _normalize_tabular_generation_rollout_settings(settings or {})


def _select_tabular_executor_mode(
    rollout_settings,
    requested_plan_mode,
    task_type,
    passthrough_input_rows=False,
):
    normalized_rollout_settings = _normalize_tabular_generation_rollout_settings(rollout_settings or {})
    normalized_task_type = _normalize_tabular_run_task_type(task_type)
    if (
        normalized_rollout_settings.get('enable_tabular_rolling_worker_pool')
        and normalized_rollout_settings.get('enable_tabular_completion_driven_checkpointing')
        and str(requested_plan_mode or '').strip().lower() == 'active'
        and normalized_task_type == TABULAR_RUN_TASK_STRUCTURED_EXPORT
        and not passthrough_input_rows
    ):
        return TABULAR_EXECUTOR_MODE_ROLLING_POOL
    return TABULAR_EXECUTOR_MODE_FIXED_WINDOW


def _select_tabular_retry_mode(rollout_settings, executor_mode):
    if (
        str(executor_mode or '').strip() == TABULAR_EXECUTOR_MODE_ROLLING_POOL
        and _settings_bool(rollout_settings, 'enable_tabular_independent_batch_retries', False)
    ):
        return TABULAR_RETRY_MODE_INDEPENDENT_BATCH
    return TABULAR_RETRY_MODE_RUN_LEVEL


def _is_rolling_executor_ready(run):
    if str((run or {}).get('executor_mode') or '').strip() != TABULAR_EXECUTOR_MODE_ROLLING_POOL:
        return False
    return (
        _normalize_tabular_run_task_type((run or {}).get('task_type')) == TABULAR_RUN_TASK_STRUCTURED_EXPORT
        and not (run or {}).get('passthrough_input_rows')
        and _get_tabular_generation_plan_mode(run) == 'active'
        and (run or {}).get('plan_status') == 'ready'
        and bool((run or {}).get('plan_blob_path'))
        and bool((run or {}).get('plan_hash'))
        and bool((run or {}).get('output_schema'))
    )


def _downgrade_rolling_executor_to_fixed_window(run, reason):
    if str((run or {}).get('executor_mode') or '').strip() != TABULAR_EXECUTOR_MODE_ROLLING_POOL:
        return run
    now = _now_iso()
    run.update({
        'executor_mode': TABULAR_EXECUTOR_MODE_FIXED_WINDOW,
        'retry_mode': TABULAR_RETRY_MODE_RUN_LEVEL,
        'updated_at': now,
        'last_heartbeat_at': now,
        'last_message': f'Rolling worker pool unavailable; continuing with fixed windows ({reason})',
    })
    return _replace_claimed_run(run)


def _sync_tabular_generation_contract_fields(run):
    if not isinstance(run, dict):
        return run

    batch_count = _safe_int(run.get('batch_count'))
    completed_batches = _safe_int(run.get('completed_batches'))
    processed_rows = _safe_int(run.get('processed_rows'))
    planned_batch_count = _safe_int(run.get('planned_batch_count'))
    if planned_batch_count <= 0 and batch_count:
        planned_batch_count = batch_count

    completed_batch_count = _safe_int(run.get('completed_batch_count'))
    if completed_batch_count <= 0 and completed_batches:
        completed_batch_count = completed_batches

    highest_contiguous_batch = _safe_int(run.get('highest_contiguous_batch'))
    if highest_contiguous_batch <= 0 and completed_batches:
        highest_contiguous_batch = completed_batches

    checkpointed_row_count = _safe_int(run.get('checkpointed_row_count'))
    if checkpointed_row_count <= 0 and processed_rows:
        checkpointed_row_count = processed_rows

    run.setdefault('generation_contract_version', TABULAR_GENERATION_CONTRACT_VERSION)
    run.setdefault('response_protocol_version', TABULAR_RESPONSE_PROTOCOL_OBJECT_V1)
    run.setdefault('executor_mode', TABULAR_EXECUTOR_MODE_FIXED_WINDOW)
    run.setdefault('retry_mode', TABULAR_RETRY_MODE_RUN_LEVEL)
    run.setdefault('plan_blob_path', None)
    run.setdefault('plan_hash', None)
    run['planned_batch_count'] = planned_batch_count
    run['completed_batch_count'] = completed_batch_count
    run['highest_contiguous_batch'] = highest_contiguous_batch
    run['active_batch_count'] = _safe_int(run.get('active_batch_count'))
    run['pending_batch_count'] = _safe_int(run.get('pending_batch_count'))
    run['checkpointing_batch_count'] = _safe_int(run.get('checkpointing_batch_count'))
    run['retry_wait_batch_count'] = _safe_int(run.get('retry_wait_batch_count'))
    run['exhausted_batch_count'] = _safe_int(run.get('exhausted_batch_count'))
    run['systemic_failure_circuit_open'] = bool(run.get('systemic_failure_circuit_open'))
    run.setdefault('systemic_failure_category', None)
    run.setdefault('systemic_failure_signature', None)
    run.setdefault('systemic_failure_opened_at', None)
    run['lineage_schema'] = _get_tabular_run_lineage_schema(run)
    run['public_output_schema'] = _get_tabular_run_public_output_schema(run)
    run['internal_checkpoint_schema'] = _get_tabular_run_internal_checkpoint_schema(run)
    run['checkpointed_row_count'] = checkpointed_row_count
    run.setdefault('generation_started_at', run.get('started_at'))
    run.setdefault('generation_completed_at', None)
    return run


def _get_tabular_run_lineage_schema(run):
    raw_schema = list((run or {}).get('lineage_schema') or [
        TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
        TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
    ])
    normalized_schema = []
    seen_fields = set()
    for field_name in raw_schema:
        normalized_field = str(field_name or '').strip()
        if not normalized_field or normalized_field in seen_fields:
            continue
        if not is_analysis_internal_lineage_field(normalized_field):
            continue
        seen_fields.add(normalized_field)
        normalized_schema.append(normalized_field)
    return normalized_schema or [
        TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
        TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
    ]


def _get_tabular_run_public_output_schema(run):
    raw_public_schema = list((run or {}).get('public_output_schema') or [])
    if not raw_public_schema:
        deliverable_contract = (
            ((run or {}).get('tabular_planner_metadata') or {}).get('deliverable_contract')
            if isinstance((run or {}).get('tabular_planner_metadata'), dict)
            else {}
        )
        raw_public_schema = list((deliverable_contract or {}).get('public_output_schema') or [])
    if not raw_public_schema:
        raw_public_schema = [
            field_name
            for field_name in list((run or {}).get('output_schema') or [])
            if not is_analysis_internal_lineage_field(field_name)
        ]

    normalized_schema = []
    seen_fields = set()
    for field_name in raw_public_schema:
        normalized_field = str(field_name or '').strip()
        if not normalized_field or normalized_field in seen_fields:
            continue
        if is_analysis_internal_lineage_field(normalized_field):
            continue
        seen_fields.add(normalized_field)
        normalized_schema.append(normalized_field)
    return normalized_schema


def _get_tabular_run_internal_checkpoint_schema(run):
    raw_internal_schema = list((run or {}).get('internal_checkpoint_schema') or [])
    if raw_internal_schema:
        return [str(field_name or '').strip() for field_name in raw_internal_schema if str(field_name or '').strip()]
    output_schema = list((run or {}).get('output_schema') or [])
    if output_schema:
        return [str(field_name or '').strip() for field_name in output_schema if str(field_name or '').strip()]
    return _get_tabular_run_lineage_schema(run) + _get_tabular_run_public_output_schema(run)


def _get_tabular_run_serialized_public_schema(run):
    public_schema = _get_tabular_run_public_output_schema(run)
    if public_schema:
        return public_schema
    return [
        field_name
        for field_name in list((run or {}).get('output_schema') or [])
        if not is_analysis_internal_lineage_field(field_name)
    ]


def _build_generation_progress_contract_fields(run, completed_batches, processed_rows):
    batch_count = _safe_int((run or {}).get('batch_count'))
    normalized_completed_batches = _safe_int(completed_batches)
    normalized_processed_rows = _safe_int(processed_rows)
    planned_batch_count = _safe_int((run or {}).get('planned_batch_count'))
    if planned_batch_count <= 0 and batch_count:
        planned_batch_count = batch_count
    return {
        'planned_batch_count': planned_batch_count,
        'completed_batch_count': normalized_completed_batches,
        'highest_contiguous_batch': normalized_completed_batches,
        'active_batch_count': 0,
        'pending_batch_count': _safe_int((run or {}).get('pending_batch_count')),
        'checkpointing_batch_count': _safe_int((run or {}).get('checkpointing_batch_count')),
        'retry_wait_batch_count': _safe_int((run or {}).get('retry_wait_batch_count')),
        'exhausted_batch_count': _safe_int((run or {}).get('exhausted_batch_count')),
        'checkpointed_row_count': normalized_processed_rows,
    }


def _extract_tabular_response_usage(result):
    def read_usage_value(source, field_names):
        if source is None:
            return None
        for field_name in field_names:
            if isinstance(source, dict):
                value = source.get(field_name)
            else:
                value = getattr(source, field_name, None)
            parsed_value = _safe_int(value, default=0)
            if parsed_value:
                return parsed_value
        return None

    first_message = result[0] if result else None
    usage_sources = []
    for source in (
        getattr(first_message, 'metadata', None),
        getattr(first_message, 'usage', None),
        getattr(getattr(first_message, 'inner_content', None), 'usage', None),
    ):
        if source is not None:
            usage_sources.append(source)
        if isinstance(source, dict):
            for nested_key in ('usage', 'token_usage', 'tokenUsage'):
                nested_source = source.get(nested_key)
                if nested_source is not None:
                    usage_sources.append(nested_source)

    usage = {
        'input_token_count': None,
        'output_token_count': None,
        'total_token_count': None,
    }
    for source in usage_sources:
        if usage['input_token_count'] is None:
            usage['input_token_count'] = read_usage_value(
                source,
                ('prompt_tokens', 'input_tokens', 'promptTokens', 'inputTokens'),
            )
        if usage['output_token_count'] is None:
            usage['output_token_count'] = read_usage_value(
                source,
                ('completion_tokens', 'output_tokens', 'completionTokens', 'outputTokens'),
            )
        if usage['total_token_count'] is None:
            usage['total_token_count'] = read_usage_value(
                source,
                ('total_tokens', 'totalTokens'),
            )
    return usage


def _resolve_tabular_batch_concurrency(settings, batch_count):
    configured_concurrency = (settings or {}).get('tabular_generated_output_batch_concurrency')
    if configured_concurrency not in (None, ''):
        return _safe_int(
            configured_concurrency,
            default=TABULAR_EXPORT_DEFAULT_BATCH_CONCURRENCY,
            minimum=1,
            maximum=TABULAR_EXPORT_MAX_BATCH_CONCURRENCY,
        )

    normalized_batch_count = _safe_int(batch_count, minimum=1)
    if normalized_batch_count <= 4:
        return normalized_batch_count
    if normalized_batch_count < TABULAR_EXPORT_DEFAULT_BATCH_CONCURRENCY:
        return 4
    if normalized_batch_count < TABULAR_EXPORT_HIGH_CONCURRENCY_BATCH_THRESHOLD:
        return TABULAR_EXPORT_DEFAULT_BATCH_CONCURRENCY
    if normalized_batch_count < TABULAR_EXPORT_MAX_CONCURRENCY_BATCH_THRESHOLD:
        return TABULAR_EXPORT_HIGH_BATCH_CONCURRENCY
    return TABULAR_EXPORT_MAX_BATCH_CONCURRENCY


def _normalize_tabular_run_task_type(task_type):
    normalized_task_type = str(task_type or '').strip().lower()
    if normalized_task_type in TABULAR_RUN_TASK_TYPES:
        return normalized_task_type
    return TABULAR_RUN_TASK_STRUCTURED_EXPORT


def _is_tabular_analysis_task(task_type):
    return _normalize_tabular_run_task_type(task_type) in {
        TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS,
        TABULAR_RUN_TASK_COMBINED,
    }


def _is_tabular_combined_task(task_type):
    return _normalize_tabular_run_task_type(task_type) == TABULAR_RUN_TASK_COMBINED


def _resolve_tabular_schema_probe_rows(
    settings,
    requested_plan_mode,
    task_type,
    row_count,
    max_batch_rows,
):
    if str(requested_plan_mode or '').strip().lower() == 'active':
        return 0
    if _normalize_tabular_run_task_type(task_type) not in {
        TABULAR_RUN_TASK_STRUCTURED_EXPORT,
        TABULAR_RUN_TASK_COMBINED,
    }:
        return 0
    return min(
        _settings_int(
            settings or {},
            'tabular_generation_schema_probe_rows',
            TABULAR_EXPORT_DEFAULT_SCHEMA_PROBE_ROWS,
            minimum=1,
            maximum=25,
        ),
        _safe_int(row_count, minimum=0),
        _safe_int(max_batch_rows, minimum=1),
    )


def _estimate_tabular_source_batch_count(row_count, max_batch_rows, schema_probe_rows=0):
    normalized_row_count = _safe_int(row_count, minimum=0)
    normalized_max_batch_rows = _safe_int(max_batch_rows, minimum=1)
    normalized_probe_rows = min(
        _safe_int(schema_probe_rows, minimum=0),
        normalized_row_count,
        normalized_max_batch_rows,
    )
    if normalized_probe_rows and normalized_row_count > normalized_probe_rows:
        return 1 + math.ceil(
            (normalized_row_count - normalized_probe_rows) / normalized_max_batch_rows
        )
    return max(1, math.ceil(normalized_row_count / normalized_max_batch_rows))


def _resolve_tabular_source_batch_capacity(
    max_batch_rows,
    max_batch_chars,
    estimated_serialized_row_chars=0,
):
    normalized_max_batch_rows = _safe_int(max_batch_rows, minimum=1)
    normalized_max_batch_chars = _safe_int(max_batch_chars, minimum=1)
    normalized_estimated_row_chars = _safe_int(
        estimated_serialized_row_chars,
        minimum=0,
    )
    if not normalized_estimated_row_chars:
        return normalized_max_batch_rows
    character_limited_rows = max(
        1,
        normalized_max_batch_chars // normalized_estimated_row_chars,
    )
    return min(normalized_max_batch_rows, character_limited_rows)


def _balance_tabular_source_batch_rows(
    settings,
    row_count,
    max_batch_rows,
    schema_probe_rows=0,
):
    normalized_row_count = _safe_int(row_count, minimum=0)
    normalized_max_batch_rows = _safe_int(max_batch_rows, minimum=1)
    normalized_probe_rows = min(
        _safe_int(schema_probe_rows, minimum=0),
        normalized_row_count,
        normalized_max_batch_rows,
    )
    remaining_rows = max(normalized_row_count - normalized_probe_rows, 0)
    if not remaining_rows or not _settings_bool(
        settings or {},
        'enable_tabular_generation_balanced_batches',
        True,
    ):
        return normalized_max_batch_rows

    unbalanced_batch_count = math.ceil(remaining_rows / normalized_max_batch_rows)
    total_batch_count = unbalanced_batch_count + (1 if normalized_probe_rows else 0)
    batch_concurrency = _resolve_tabular_batch_concurrency(settings or {}, total_batch_count)
    if unbalanced_batch_count <= batch_concurrency or unbalanced_batch_count % batch_concurrency == 0:
        return normalized_max_batch_rows

    concurrency_waves = math.ceil(unbalanced_batch_count / batch_concurrency)
    balanced_batch_count = concurrency_waves * batch_concurrency
    return min(
        normalized_max_batch_rows,
        max(1, math.ceil(remaining_rows / balanced_batch_count)),
    )


def _get_tabular_source_batch_row_limit(source_descriptor, staged_batch_count):
    max_batch_rows = _safe_int(
        (source_descriptor or {}).get('batch_max_rows'),
        default=TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_ROWS,
        minimum=1,
        maximum=TABULAR_EXPORT_MAX_SOURCE_BATCH_ROWS,
    )
    schema_probe_rows = _safe_int(
        (source_descriptor or {}).get('schema_probe_rows'),
        default=0,
        minimum=0,
        maximum=max_batch_rows,
    )
    if schema_probe_rows and _safe_int(staged_batch_count, minimum=0) == 0:
        return schema_probe_rows
    return max_batch_rows


def _iter_exception_chain(exc):
    visited = set()
    pending = [exc]
    while pending:
        current = pending.pop(0)
        if current is None:
            continue
        current_id = id(current)
        if current_id in visited:
            continue
        visited.add(current_id)
        yield current

        for related in (getattr(current, '__cause__', None), getattr(current, '__context__', None)):
            if related is not None:
                pending.append(related)
        for arg in getattr(current, 'args', ()) or ():
            if isinstance(arg, BaseException):
                pending.append(arg)


def _exception_status_code(exc):
    for candidate in _iter_exception_chain(exc):
        status_code = getattr(candidate, 'status_code', None)
        if status_code is None:
            response = getattr(candidate, 'response', None)
            status_code = getattr(response, 'status_code', None) if response is not None else None
        parsed_status_code = _safe_int(status_code, default=0)
        if parsed_status_code:
            return parsed_status_code
    return 0


def _is_retryable_export_error_message(error_message):
    normalized_message = str(error_message or '').lower()
    return any(marker in normalized_message for marker in TABULAR_EXPORT_RETRYABLE_MESSAGE_MARKERS)


def _is_retryable_model_validation_error_message(error_message):
    normalized_message = str(error_message or '').lower()
    return any(
        marker in normalized_message
        for marker in TABULAR_EXPORT_MODEL_VALIDATION_RETRYABLE_MESSAGE_MARKERS
    )


def _is_retryable_export_error(exc):
    status_code = _exception_status_code(exc)
    if status_code in TABULAR_EXPORT_RETRYABLE_STATUS_CODES:
        return True

    for candidate in _iter_exception_chain(exc):
        class_name = candidate.__class__.__name__
        if class_name in TABULAR_EXPORT_RETRYABLE_EXCEPTION_NAMES:
            return True
        if _is_retryable_export_error_message(candidate):
            return True
    return _is_retryable_export_error_message(exc)


def _is_retryable_model_validation_error(exc):
    for candidate in _iter_exception_chain(exc):
        if _is_retryable_model_validation_error_message(candidate):
            return True
    return _is_retryable_model_validation_error_message(exc)


def _sanitize_file_base_name(file_name):
    base_name = os.path.splitext(str(file_name or '').strip())[0]
    normalized_base_name = re.sub(r'[^A-Za-z0-9._-]+', '_', base_name).strip('._')
    return normalized_base_name or 'tabular_output'


def _build_generated_file_name(source_file_name, output_format):
    timestamp_suffix = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    normalized_extension = normalize_generated_output_format(output_format)
    return f"{_sanitize_file_base_name(source_file_name)}_generated_{timestamp_suffix}.{normalized_extension}"


def _build_analysis_file_name(source_file_name):
    timestamp_suffix = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    return f"{_sanitize_file_base_name(source_file_name)}_analysis_{timestamp_suffix}.md"


def _serialize_generated_output_value(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return neutralize_csv_spreadsheet_formula(json.dumps(value, default=str, ensure_ascii=False))
    if hasattr(value, 'isoformat') and not isinstance(value, str):
        try:
            return neutralize_csv_spreadsheet_formula(value.isoformat())
        except TypeError:
            pass
    return neutralize_csv_spreadsheet_formula(value)


def _sanitize_generated_xml_tag_name(value, fallback_value='Field'):
    normalized_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(value or '').strip()).strip('._-')
    if not normalized_name:
        normalized_name = fallback_value
    if not re.match(r'^[A-Za-z_]', normalized_name):
        normalized_name = f'{fallback_value}_{normalized_name}'
    return normalized_name


def _write_generated_xml_row(output_stream, row):
    output_stream.write('  <Row>\n')
    for field_name, field_value in (row or {}).items():
        tag_name = _sanitize_generated_xml_tag_name(field_name)
        serialized_value = _serialize_generated_output_value(field_value)
        output_stream.write(f'    <{tag_name}>{escape_xml_text(serialized_value)}</{tag_name}>\n')
    output_stream.write('  </Row>\n')


def _normalize_source_identity_label(value):
    return re.sub(r'[^a-z0-9]+', '', str(value or '').strip().casefold())


def _select_source_row_identity(row, source_row_number):
    if not isinstance(row, dict):
        return str(source_row_number)

    identity_priorities = (
        'sourceidentity',
        'sourceid',
        'caseid',
        'recordid',
        'rowid',
        'commentid',
        'submissionid',
        'id',
    )
    normalized_values = {}
    for field_name, field_value in row.items():
        if field_name in {
            TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD,
            TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD,
            TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD,
        }:
            continue
        normalized_label = _normalize_source_identity_label(field_name)
        if normalized_label and field_value not in (None, '', [], {}):
            normalized_values.setdefault(normalized_label, field_value)

    for identity_label in identity_priorities:
        identity_value = normalized_values.get(identity_label)
        if identity_value not in (None, '', [], {}):
            return str(identity_value)

    for identity_label, identity_value in normalized_values.items():
        if identity_label.endswith('id') and not isinstance(identity_value, (dict, list, tuple, set)):
            return str(identity_value)

    return str(source_row_number)


def _prepare_tabular_source_rows(rows, start_row=0, token_namespace=''):
    try:
        normalized_start_row = max(0, int(start_row or 0))
    except (TypeError, ValueError):
        normalized_start_row = 0

    prepared_rows = []
    for row_offset, row in enumerate(rows or []):
        source_row_number = normalized_start_row + row_offset + 1
        prepared_row = dict(row) if isinstance(row, dict) else {'value': row}
        prepared_row[TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD] = source_row_number
        prepared_row[TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD] = _select_source_row_identity(
            prepared_row,
            source_row_number,
        )
        token_seed = (
            f'simplechat-tabular-row:{token_namespace}:{source_row_number}:'
            f'{prepared_row[TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD]}'
        )
        prepared_row[TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD] = uuid.uuid5(
            uuid.NAMESPACE_URL,
            token_seed,
        ).hex
        prepared_rows.append(prepared_row)
    return prepared_rows


def _normalize_generated_batch_entries(
    source_rows,
    generated_entries,
    expected_output_schema=None,
    require_source_token=True,
):
    source_rows = list(source_rows or [])
    generated_entries = list(generated_entries or [])
    if len(source_rows) != len(generated_entries):
        raise ValueError(
            f'Generated row count {len(generated_entries)} does not match source row count {len(source_rows)}'
        )

    normalized_entries = []
    for row_index, (source_row, generated_entry) in enumerate(zip(source_rows, generated_entries), start=1):
        if not isinstance(source_row, dict):
            raise ValueError(f'Source row {row_index} is not an object')
        if not isinstance(generated_entry, dict):
            raise ValueError(f'Generated row {row_index} is not an object')

        source_row_number = source_row.get(TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD)
        source_row_identity = source_row.get(TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD)
        source_row_token = str(source_row.get(TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD) or '').strip()
        if source_row_number in (None, '') or source_row_identity in (None, ''):
            raise ValueError(f'Source identity is missing for generated row {row_index}')
        generated_row_token = str(
            generated_entry.get(TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD) or ''
        ).strip()
        if require_source_token and (
            not source_row_token
            or generated_row_token != source_row_token
        ):
            raise ValueError(
                f'Generated source row token mismatch at row {row_index}'
            )

        normalized_entry = {
            TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD: source_row_number,
            TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD: str(source_row_identity),
        }
        normalized_entry.update({
            str(field_name): field_value
            for field_name, field_value in generated_entry.items()
            if str(field_name) not in {
                TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD,
                TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD,
                TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD,
                TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
                TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
            }
        })
        normalized_entries.append(normalized_entry)

    output_schema = list(expected_output_schema or [])
    if not output_schema and normalized_entries:
        output_schema = list(normalized_entries[0])

    expected_fields = set(output_schema)
    for row_index, normalized_entry in enumerate(normalized_entries, start=1):
        actual_fields = set(normalized_entry)
        if actual_fields != expected_fields:
            missing_fields = sorted(expected_fields - actual_fields)
            unexpected_fields = sorted(actual_fields - expected_fields)
            raise ValueError(
                f'Generated output schema mismatch at row {row_index}; '
                f'missing={missing_fields}; unexpected={unexpected_fields}'
            )

    ordered_entries = [
        {field_name: entry.get(field_name) for field_name in output_schema}
        for entry in normalized_entries
    ]
    return ordered_entries, output_schema


def _generated_entry_has_source_position_conflict(source_row, generated_entry):
    source_row_number = _safe_int(source_row.get(TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD), default=0, minimum=0)
    source_row_identity = str(source_row.get(TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD) or '').strip()

    for row_number_field in (
        TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD,
        TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
    ):
        if row_number_field not in generated_entry or generated_entry.get(row_number_field) in (None, ''):
            continue
        if _safe_int(generated_entry.get(row_number_field), default=-1) != source_row_number:
            return True

    for row_identity_field in (
        TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD,
        TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
    ):
        if row_identity_field not in generated_entry or generated_entry.get(row_identity_field) in (None, ''):
            continue
        if str(generated_entry.get(row_identity_field) or '').strip() != source_row_identity:
            return True

    return False


def _parse_single_nested_csv_generated_entry(generated_entry):
    if not isinstance(generated_entry, dict):
        return None
    csv_payload = generated_entry.get('csv')
    if not isinstance(csv_payload, str) or not csv_payload.strip():
        return None
    allowed_metadata_fields = {
        'csv',
        TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD,
        TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD,
        TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD,
        TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
        TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
    }

    try:
        csv_rows = list(csv.DictReader(io.StringIO(csv_payload.strip())))
    except (csv.Error, TypeError, ValueError):
        return None
    if len(csv_rows) != 1:
        return None
    parsed_row = {
        str(field_name or '').strip(): field_value
        for field_name, field_value in (csv_rows[0] or {}).items()
        if str(field_name or '').strip()
    }
    if not parsed_row:
        return None
    for field_name, field_value in generated_entry.items():
        if field_name in allowed_metadata_fields:
            continue
        if field_name not in parsed_row:
            return None
        if str(parsed_row.get(field_name) or '') != str(field_value or ''):
            return None
    for metadata_field in allowed_metadata_fields - {'csv'}:
        if metadata_field in generated_entry and generated_entry.get(metadata_field) not in (None, ''):
            parsed_row[metadata_field] = generated_entry.get(metadata_field)
    return parsed_row


def _expand_nested_csv_generated_entries(generated_entries):
    expanded_entries = []
    recovered_count = 0
    for generated_entry in generated_entries or []:
        parsed_entry = _parse_single_nested_csv_generated_entry(generated_entry)
        if parsed_entry is None:
            expanded_entries.append(generated_entry)
            continue
        expanded_entries.append(parsed_entry)
        recovered_count += 1
    return expanded_entries, recovered_count


def _normalize_model_generated_batch_entries(
    source_rows,
    generated_entries,
    expected_output_schema=None,
    allow_source_token_recovery=True,
    run_id=None,
    batch_number=None,
):
    generated_entries, nested_csv_recovered_count = _expand_nested_csv_generated_entries(generated_entries)
    if nested_csv_recovered_count:
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Expanded nested CSV model output rows',
            {
                'run_id': run_id,
                'batch_number': batch_number,
                'recovered_row_count': nested_csv_recovered_count,
            },
            level=logging.WARNING,
        )
    try:
        return _normalize_generated_batch_entries(
            source_rows,
            generated_entries,
            expected_output_schema=expected_output_schema,
        )
    except ValueError as exc:
        if (
            not allow_source_token_recovery
            or 'source row token mismatch' not in str(exc).lower()
        ):
            raise
        for source_row, generated_entry in zip(source_rows or [], generated_entries or []):
            if not isinstance(source_row, dict) or not isinstance(generated_entry, dict):
                raise
            if _generated_entry_has_source_position_conflict(source_row, generated_entry):
                raise
        normalized_entries, output_schema = _normalize_generated_batch_entries(
            source_rows,
            generated_entries,
            expected_output_schema=expected_output_schema,
            require_source_token=False,
        )
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Recovered generated batch from source-token echo mismatch',
            {
                'run_id': run_id,
                'batch_number': batch_number,
                'row_count': len(normalized_entries),
                'recovery_reason': 'source_token_echo_mismatch',
            },
            level=logging.WARNING,
        )
        return normalized_entries, output_schema


def _build_generated_batch_summary(entries):
    entries = [entry for entry in (entries or []) if isinstance(entry, dict)]
    summary = {
        'row_count': len(entries),
        'source_row_start': None,
        'source_row_end': None,
        'fields': {},
    }
    if not entries:
        return summary

    summary['source_row_start'] = _safe_int(entries[0].get(TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD)) or None
    summary['source_row_end'] = _safe_int(entries[-1].get(TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD)) or None
    field_names = [
        field_name
        for field_name in entries[0]
        if field_name not in {
            TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
            TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
        }
    ][:TABULAR_EXPORT_SUMMARY_MAX_FIELDS]
    for field_name in field_names:
        populated_count = 0
        value_counts = Counter()
        for entry in entries:
            field_value = entry.get(field_name)
            if field_value in (None, '', [], {}):
                continue
            populated_count += 1
            if isinstance(field_value, (str, int, float, bool)):
                normalized_value = str(field_value).strip()
                if normalized_value and len(normalized_value) <= 100:
                    value_counts[normalized_value] += 1

        summary['fields'][field_name] = {
            'populated_count': populated_count,
            'empty_count': len(entries) - populated_count,
            'top_values': [
                {'value': value, 'count': count}
                for value, count in value_counts.most_common(TABULAR_EXPORT_SUMMARY_MAX_VALUES_PER_FIELD)
            ],
        }
    return summary


def _build_compact_post_run_summary(run):
    batch_count = _safe_int(run.get('batch_count'))
    row_count = _safe_int(run.get('row_count'))
    aggregate_fields = {}
    summarized_batch_count = 0
    for batch_number in range(1, batch_count + 1):
        summary_blob_path = _output_summary_blob_path(
            run.get('user_id'),
            run.get('conversation_id'),
            run.get('id'),
            batch_number,
        )
        if not _blob_exists(summary_blob_path):
            continue
        batch_summary = _download_json_blob(summary_blob_path)
        if not isinstance(batch_summary, dict):
            continue
        summarized_batch_count += 1
        for field_name, field_summary in list((batch_summary.get('fields') or {}).items())[
            :TABULAR_EXPORT_SUMMARY_MAX_FIELDS
        ]:
            aggregate_field = aggregate_fields.setdefault(field_name, {
                'populated_count': 0,
                'empty_count': 0,
                'value_counts': Counter(),
            })
            aggregate_field['populated_count'] += _safe_int(field_summary.get('populated_count'))
            aggregate_field['empty_count'] += _safe_int(field_summary.get('empty_count'))
            for value_summary in field_summary.get('top_values') or []:
                value = str(value_summary.get('value') or '').strip()
                if value:
                    aggregate_field['value_counts'][value] += _safe_int(value_summary.get('count'))
            if len(aggregate_field['value_counts']) > TABULAR_EXPORT_SUMMARY_AGGREGATE_MAX_VALUES * 2:
                aggregate_field['value_counts'] = Counter(dict(
                    aggregate_field['value_counts'].most_common(TABULAR_EXPORT_SUMMARY_AGGREGATE_MAX_VALUES)
                ))

    summary_parts = [
        f'Processed {row_count:,} ordered row(s) across {batch_count:,} checkpointed batch(es).'
    ]
    if aggregate_fields:
        field_names = list(aggregate_fields)[:10]
        summary_parts.append(f"Output fields: {', '.join(field_names)}.")
        completeness_parts = []
        for field_name in field_names[:5]:
            populated_count = aggregate_fields[field_name]['populated_count']
            completeness_percent = round((populated_count / row_count) * 100) if row_count else 0
            completeness_parts.append(f'{field_name} {completeness_percent}% populated')
        if completeness_parts:
            summary_parts.append(f"Completeness: {', '.join(completeness_parts)}.")

        common_value_parts = []
        for field_name in field_names[:5]:
            top_values = aggregate_fields[field_name]['value_counts'].most_common(3)
            if 1 < len(top_values) <= 3:
                rendered_values = ', '.join(f'{value} ({count:,})' for value, count in top_values)
                common_value_parts.append(f'{field_name}: {rendered_values}')
        if common_value_parts:
            summary_parts.append(f"Common values: {'; '.join(common_value_parts)}.")

    if summarized_batch_count != batch_count:
        summary_parts.append(
            f'Batch summaries available for {summarized_batch_count:,} of {batch_count:,} batch(es).'
        )
    return ' '.join(summary_parts)[:2000]


def _build_generated_output_csv(entries):
    ordered_columns = []
    seen_columns = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        for key in entry.keys():
            normalized_key = str(key or '').strip()
            if not normalized_key or normalized_key in seen_columns:
                continue
            seen_columns.add(normalized_key)
            ordered_columns.append(normalized_key)

    if not ordered_columns:
        ordered_columns = ['value']

    safe_ordered_columns = build_safe_csv_headers(ordered_columns)
    output_buffer = io.StringIO()
    writer = csv.DictWriter(output_buffer, fieldnames=safe_ordered_columns)
    writer.writeheader()
    for entry in entries or []:
        serialized_row = {}
        if isinstance(entry, dict):
            for field_name, safe_field_name in zip(ordered_columns, safe_ordered_columns):
                serialized_row[safe_field_name] = _serialize_generated_output_value(entry.get(field_name))
        writer.writerow(serialized_row)
    return output_buffer.getvalue()


def _get_blob_service_client():
    blob_service_client = CLIENTS.get('storage_account_office_docs_client')
    if not blob_service_client:
        raise RuntimeError('Blob storage client not available')
    return blob_service_client


def _input_blob_path(user_id, conversation_id, run_id, batch_number):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/input/batch_{batch_number:06d}.json"


def _input_batches_blob_path(user_id, conversation_id, run_id):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/input/input_batches.json"


def _tabular_generation_plan_blob_path(user_id, conversation_id, run_id):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/plan/plan_v1.json"


def _chunk_manifest_blob_prefix(user_id, conversation_id, run_id):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/manifest/chunks/"


def _chunk_manifest_page_blob_path(user_id, conversation_id, run_id, page_number):
    return f"{_chunk_manifest_blob_prefix(user_id, conversation_id, run_id)}page_{page_number:06d}.json"


def _output_blob_path(user_id, conversation_id, run_id, batch_number):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/output/batch_{batch_number:06d}.json"


def _output_blob_prefix(user_id, conversation_id, run_id):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/output/"


def _output_summary_blob_path(user_id, conversation_id, run_id, batch_number):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/summary/batch_{batch_number:06d}.json"


def _retry_blob_path(user_id, conversation_id, run_id, batch_number):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/retry/batch_{batch_number:06d}.json"


def _retry_blob_prefix(user_id, conversation_id, run_id):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/retry/"


def _analysis_chunk_summary_blob_path(user_id, conversation_id, run_id, batch_number):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/analysis/chunks/batch_{batch_number:06d}.json"


def _analysis_reduce_blob_path(user_id, conversation_id, run_id, level_number, node_number):
    return (
        f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/analysis/reduce/"
        f"level_{level_number:03d}/node_{node_number:06d}.json"
    )


def _analysis_final_blob_path(user_id, conversation_id, run_id):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/analysis/final_summary.json"


def _build_chunk_manifest_contract(user_id, conversation_id, run_id, total_chunk_count, row_count=0, page_size=None):
    normalized_total_chunk_count = _safe_int(total_chunk_count, default=0, minimum=0)
    normalized_page_size = _safe_int(
        page_size,
        default=TABULAR_RUN_DEFAULT_CHUNK_MANIFEST_PAGE_SIZE,
        minimum=1,
        maximum=1000,
    )
    page_count = math.ceil(normalized_total_chunk_count / normalized_page_size) if normalized_total_chunk_count else 0
    return {
        'version': TABULAR_RUN_CHUNK_MANIFEST_VERSION,
        'storage': 'blob',
        'container': storage_account_personal_chat_container_name,
        'blob_prefix': _chunk_manifest_blob_prefix(user_id, conversation_id, run_id),
        'page_blob_name_pattern': 'page_{page_number:06d}.json',
        'page_size': normalized_page_size,
        'page_count': page_count,
        'chunk_index_base': 1,
        'total_chunk_count': normalized_total_chunk_count,
        'row_count': _safe_int(row_count, default=0, minimum=0),
    }


def _build_chunk_manifest_entries(
    user_id,
    conversation_id,
    run_id,
    total_chunk_count,
    row_count=0,
    chunk_row_counts=None,
    estimated_rows_per_chunk=None,
    chunk_status='staged',
):
    normalized_total_chunk_count = _safe_int(total_chunk_count, default=0, minimum=0)
    normalized_row_count = _safe_int(row_count, default=0, minimum=0)
    normalized_estimated_rows_per_chunk = _safe_int(estimated_rows_per_chunk, default=0, minimum=0)
    exact_chunk_row_counts = [
        _safe_int(chunk_row_count, default=0, minimum=0)
        for chunk_row_count in (chunk_row_counts or [])
    ]
    entries = []
    next_source_row_number = 1
    for chunk_index in range(1, normalized_total_chunk_count + 1):
        chunk_row_count = 0
        if chunk_index <= len(exact_chunk_row_counts):
            chunk_row_count = exact_chunk_row_counts[chunk_index - 1]
        elif normalized_estimated_rows_per_chunk and normalized_row_count:
            remaining_rows = max(normalized_row_count - next_source_row_number + 1, 0)
            chunk_row_count = min(normalized_estimated_rows_per_chunk, remaining_rows)

        entry = {
            'chunk_index': chunk_index,
            'status': str(chunk_status or 'staged').strip() or 'staged',
            'input_blob_path': _input_blob_path(user_id, conversation_id, run_id, chunk_index),
            'output_blob_path': _output_blob_path(user_id, conversation_id, run_id, chunk_index),
            'summary_blob_path': _output_summary_blob_path(user_id, conversation_id, run_id, chunk_index),
        }
        if chunk_row_count > 0:
            entry.update({
                'source_row_start': next_source_row_number,
                'source_row_end': next_source_row_number + chunk_row_count - 1,
                'row_count': chunk_row_count,
            })
            next_source_row_number += chunk_row_count
        entries.append(entry)
    return entries


def _write_chunk_manifest_pages(user_id, conversation_id, run_id, manifest, chunk_entries):
    page_size = _safe_int(
        (manifest or {}).get('page_size'),
        default=TABULAR_RUN_DEFAULT_CHUNK_MANIFEST_PAGE_SIZE,
        minimum=1,
        maximum=1000,
    )
    total_chunk_count = _safe_int((manifest or {}).get('total_chunk_count'), default=len(chunk_entries), minimum=0)
    page_count = math.ceil(total_chunk_count / page_size) if total_chunk_count else 0
    for page_number in range(1, page_count + 1):
        page_start = (page_number - 1) * page_size
        page_entries = list(chunk_entries[page_start:page_start + page_size])
        page_payload = {
            'version': TABULAR_RUN_CHUNK_MANIFEST_VERSION,
            'run_id': run_id,
            'page_number': page_number,
            'page_count': page_count,
            'page_size': page_size,
            'chunk_index_start': page_start + 1,
            'chunk_index_end': page_start + len(page_entries),
            'chunks': page_entries,
        }
        _upload_json_blob(
            _chunk_manifest_page_blob_path(user_id, conversation_id, run_id, page_number),
            page_payload,
            metadata={
                'run_id': run_id,
                'conversation_id': conversation_id,
                'chunk_manifest': 'true',
                'page_number': page_number,
                'contract_version': TABULAR_EXPORT_CONTRACT_VERSION,
            },
        )


def _write_chunk_manifest_for_run(
    user_id,
    conversation_id,
    run_id,
    total_chunk_count,
    row_count=0,
    chunk_row_counts=None,
    estimated_rows_per_chunk=None,
    chunk_status='staged',
):
    manifest = _build_chunk_manifest_contract(
        user_id,
        conversation_id,
        run_id,
        total_chunk_count,
        row_count=row_count,
    )
    chunk_entries = _build_chunk_manifest_entries(
        user_id,
        conversation_id,
        run_id,
        total_chunk_count,
        row_count=row_count,
        chunk_row_counts=chunk_row_counts,
        estimated_rows_per_chunk=estimated_rows_per_chunk,
        chunk_status=chunk_status,
    )
    _write_chunk_manifest_pages(user_id, conversation_id, run_id, manifest, chunk_entries)
    return manifest


def _upload_json_blob(blob_path, payload, metadata=None, overwrite=True):
    blob_client = _get_blob_service_client().get_blob_client(
        container=storage_account_personal_chat_container_name,
        blob=blob_path,
    )
    blob_client.upload_blob(
        json.dumps(payload, default=str, ensure_ascii=False).encode('utf-8'),
        overwrite=overwrite,
        metadata={str(key): str(value) for key, value in (metadata or {}).items()},
    )


def _download_json_blob(blob_path):
    blob_client = _get_blob_service_client().get_blob_client(
        container=storage_account_personal_chat_container_name,
        blob=blob_path,
    )
    raw_content = blob_client.download_blob().readall()
    if isinstance(raw_content, bytes):
        raw_content = raw_content.decode('utf-8')
    return json.loads(raw_content or 'null')


def _blob_exists(blob_path):
    blob_client = _get_blob_service_client().get_blob_client(
        container=storage_account_personal_chat_container_name,
        blob=blob_path,
    )
    return bool(blob_client.exists())


def _get_blob_metadata(blob_path):
    blob_client = _get_blob_service_client().get_blob_client(
        container=storage_account_personal_chat_container_name,
        blob=blob_path,
    )
    blob_properties = blob_client.get_blob_properties()
    if isinstance(blob_properties, dict):
        metadata = blob_properties.get('metadata') or {}
    else:
        metadata = getattr(blob_properties, 'metadata', {}) or {}
    return {
        str(key).strip().lower(): str(value or '').strip()
        for key, value in metadata.items()
    }


def _get_tabular_generation_plan_source_etag(run):
    source = _get_tabular_generation_plan_source(run)
    return str(source.get('blob_etag') or '').strip().strip('"') or 'unavailable'


def _build_tabular_output_checkpoint_metadata(run, metadata=None):
    checkpoint_metadata = dict(metadata or {})
    plan_hash = str((run or {}).get('plan_hash') or '').strip()
    if plan_hash:
        checkpoint_metadata.update({
            'plan_hash': plan_hash,
            'source_etag': _get_tabular_generation_plan_source_etag(run),
        })
    return checkpoint_metadata


def _scan_output_checkpoint_batches_for_run(run):
    user_id = str((run or {}).get('user_id') or '').strip()
    conversation_id = str((run or {}).get('conversation_id') or '').strip()
    run_id = str((run or {}).get('id') or '').strip()
    batch_count = _safe_int((run or {}).get('batch_count'), default=0, minimum=0)
    if not user_id or not conversation_id or not run_id or batch_count <= 0:
        return set()

    output_prefix = _output_blob_prefix(user_id, conversation_id, run_id)
    container_client = _get_blob_service_client().get_container_client(
        storage_account_personal_chat_container_name,
    )
    output_batch_numbers = set()
    for blob_properties in container_client.list_blobs(name_starts_with=output_prefix):
        if isinstance(blob_properties, dict):
            blob_name = str(blob_properties.get('name') or '').strip()
        else:
            blob_name = str(getattr(blob_properties, 'name', '') or '').strip()
        if not blob_name.startswith(output_prefix):
            continue
        suffix = blob_name[len(output_prefix):]
        match = re.fullmatch(r'batch_(\d{6})\.json', suffix)
        if not match:
            continue
        batch_number = _safe_int(match.group(1), default=0, minimum=0)
        if 1 <= batch_number <= batch_count:
            output_batch_numbers.add(batch_number)
    return output_batch_numbers


def _validate_tabular_output_checkpoint_metadata(run, blob_path, batch_number):
    expected_plan_hash = str((run or {}).get('plan_hash') or '').strip()
    if not expected_plan_hash:
        return
    metadata = _get_blob_metadata(blob_path)
    if metadata.get('plan_hash') != expected_plan_hash:
        raise ValueError(f'Output checkpoint {batch_number} plan hash does not match')
    expected_source_etag = _get_tabular_generation_plan_source_etag(run)
    if metadata.get('source_etag') != expected_source_etag:
        raise ValueError(f'Output checkpoint {batch_number} source ETag does not match')


def _load_tabular_batch_retry_records_for_run(run, completed_batches=None):
    user_id = str((run or {}).get('user_id') or '').strip()
    conversation_id = str((run or {}).get('conversation_id') or '').strip()
    run_id = str((run or {}).get('id') or '').strip()
    batch_count = _safe_int((run or {}).get('batch_count'), default=0, minimum=0)
    if not user_id or not conversation_id or not run_id or batch_count <= 0:
        return {}

    completed_batch_numbers = set(completed_batches or set())
    retry_prefix = _retry_blob_prefix(user_id, conversation_id, run_id)
    container_client = _get_blob_service_client().get_container_client(
        storage_account_personal_chat_container_name,
    )
    retry_records = {}
    for blob_properties in container_client.list_blobs(name_starts_with=retry_prefix):
        blob_name = str(
            blob_properties.get('name')
            if isinstance(blob_properties, dict)
            else getattr(blob_properties, 'name', '')
        ).strip()
        if not blob_name.startswith(retry_prefix):
            continue
        suffix = blob_name[len(retry_prefix):]
        match = re.fullmatch(r'batch_(\d{6})\.json', suffix)
        if not match:
            continue
        batch_number = _safe_int(match.group(1), default=0, minimum=0)
        if batch_number < 1 or batch_number > batch_count:
            continue
        if batch_number in completed_batch_numbers:
            _delete_blob_if_exists(blob_name)
            continue
        retry_record = _download_json_blob(blob_name)
        if not isinstance(retry_record, dict):
            continue
        retry_record['batch_number'] = batch_number
        retry_records[batch_number] = retry_record
    return retry_records


def _safe_tabular_batch_error_code(exc):
    status_code = _exception_status_code(exc)
    if status_code:
        return f'http_{status_code}'
    for candidate in _iter_exception_chain(exc):
        class_name = candidate.__class__.__name__
        if class_name:
            return re.sub(r'[^A-Za-z0-9_]+', '_', class_name).strip('_').lower()[:80] or 'error'
    return 'error'


def _classify_tabular_batch_failure(exc):
    status_code = _exception_status_code(exc)
    if status_code == 429:
        return 'rate_limit'
    if status_code in TABULAR_EXPORT_RETRYABLE_STATUS_CODES:
        return 'provider_transient'
    if isinstance(exc, TabularExportLeaseLostError):
        return 'lease_lost'
    if isinstance(exc, PermissionError):
        return 'authorization_lost'

    normalized_message = str(exc or '').strip().lower()
    if 'source csv changed' in normalized_message or 'source etag' in normalized_message:
        return 'source_changed'
    if 'plan hash' in normalized_message or 'generation plan' in normalized_message:
        return 'plan_or_schema_systemic'
    if _is_retryable_model_validation_error(exc):
        return 'model_validation'
    if isinstance(exc, TimeoutError) or 'timeout' in normalized_message or 'timed out' in normalized_message:
        return 'timeout'
    if _is_retryable_export_error(exc):
        return 'connection'
    return 'non_retryable'


def _is_tabular_batch_failure_retryable(category):
    return str(category or '').strip().lower() in {
        'rate_limit',
        'timeout',
        'connection',
        'provider_transient',
        'model_validation',
        'checkpoint_storage',
    }


def _tabular_retry_delay_seconds(batch_number, failure_category, attempt_count):
    bounded_attempt_count = _safe_int(attempt_count, default=1, minimum=1, maximum=10)
    base_delay = min(
        TABULAR_GENERATION_RETRY_MAX_DELAY_SECONDS,
        TABULAR_GENERATION_RETRY_BASE_DELAY_SECONDS * (2 ** (bounded_attempt_count - 1)),
    )
    jitter_key = f'{batch_number}:{failure_category}:{bounded_attempt_count}'
    jitter_hash = hashlib.sha256(jitter_key.encode('utf-8')).hexdigest()
    jitter_seconds = int(jitter_hash[:4], 16) % (TABULAR_GENERATION_RETRY_MAX_JITTER_SECONDS + 1)
    return min(TABULAR_GENERATION_RETRY_MAX_DELAY_SECONDS, base_delay + jitter_seconds)


def _build_tabular_batch_retry_record(
    run,
    batch_number,
    batch_request,
    exc,
    existing_record=None,
    max_attempts=1,
    failure_category=None,
):
    existing_record = existing_record if isinstance(existing_record, dict) else {}
    failure_category = str(failure_category or '').strip().lower() or _classify_tabular_batch_failure(exc)
    existing_attempts_by_category = existing_record.get('attempts_by_category')
    attempts_by_category = dict(existing_attempts_by_category) if isinstance(existing_attempts_by_category, dict) else {}
    attempt_count = _safe_int(attempts_by_category.get(failure_category), default=0, minimum=0) + 1
    attempts_by_category[failure_category] = attempt_count
    bounded_max_attempts = _safe_int(max_attempts, default=1, minimum=1, maximum=10)
    exhausted = (
        not _is_tabular_batch_failure_retryable(failure_category)
        or attempt_count >= bounded_max_attempts
    )
    now = _now_utc()
    next_attempt_at = None
    if not exhausted:
        next_attempt_at = (now + timedelta(
            seconds=_tabular_retry_delay_seconds(batch_number, failure_category, attempt_count)
        )).isoformat()

    rows = (batch_request or {}).get('rows') if isinstance(batch_request, dict) else []
    row_count = len(rows) if isinstance(rows, list) else 0
    first_row_number = None
    last_row_number = None
    if row_count:
        first_row_number = _safe_int(rows[0].get(TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD), default=0, minimum=0)
        last_row_number = _safe_int(rows[-1].get(TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD), default=0, minimum=0)

    return {
        'version': TABULAR_GENERATION_RETRY_LEDGER_VERSION,
        'run_id': str((run or {}).get('id') or '').strip(),
        'batch_number': _safe_int(batch_number, minimum=0),
        'row_count': row_count,
        'first_source_row_number': first_row_number,
        'last_source_row_number': last_row_number,
        'plan_hash': str((run or {}).get('plan_hash') or '').strip()[:64],
        'lease_generation': _safe_int((run or {}).get('lease_generation')),
        'failure_category': failure_category,
        'safe_error_code': _safe_tabular_batch_error_code(exc),
        'attempts_by_category': attempts_by_category,
        'attempt_count': attempt_count,
        'max_attempts': bounded_max_attempts,
        'first_failure_at': existing_record.get('first_failure_at') or now.isoformat(),
        'latest_failure_at': now.isoformat(),
        'next_attempt_at': next_attempt_at,
        'exhausted': exhausted,
        'manual_intervention_required': exhausted,
    }


def _persist_tabular_batch_retry_record(run, retry_record):
    batch_number = _safe_int((retry_record or {}).get('batch_number'), default=0, minimum=0)
    if batch_number <= 0:
        return retry_record
    _upload_json_blob(
        _retry_blob_path(
            run.get('user_id'),
            run.get('conversation_id'),
            run.get('id'),
            batch_number,
        ),
        retry_record,
        metadata={
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'batch_number': batch_number,
            'retry_record': 'true',
            'failure_category': retry_record.get('failure_category'),
            'plan_hash': retry_record.get('plan_hash') or '',
        },
    )
    return retry_record


def _delete_tabular_batch_retry_record(run, batch_number):
    _delete_blob_if_exists(_retry_blob_path(
        run.get('user_id'),
        run.get('conversation_id'),
        run.get('id'),
        batch_number,
    ))


def _is_tabular_batch_retry_due(retry_record):
    if bool((retry_record or {}).get('exhausted')):
        return False
    next_attempt = _parse_iso_datetime((retry_record or {}).get('next_attempt_at'))
    return next_attempt is None or next_attempt <= _now_utc()


def _tabular_batch_retry_heap_item(retry_record):
    next_attempt = _parse_iso_datetime((retry_record or {}).get('next_attempt_at')) or _now_utc()
    return (next_attempt, _safe_int((retry_record or {}).get('batch_number'), default=0, minimum=0))


def _reset_exhausted_tabular_batch_retry_records_for_continue(run, now_iso):
    completed_batches = _scan_output_checkpoint_batches_for_run(run)
    retry_records = _load_tabular_batch_retry_records_for_run(run, completed_batches)
    reset_count = 0
    for batch_number, retry_record in retry_records.items():
        if batch_number in completed_batches or not bool((retry_record or {}).get('exhausted')):
            continue
        retry_record.update({
            'attempts_by_category': {},
            'attempt_count': 0,
            'next_attempt_at': now_iso,
            'exhausted': False,
            'manual_intervention_required': False,
            'manual_continue_reset_at': now_iso,
        })
        _persist_tabular_batch_retry_record(run, retry_record)
        reset_count += 1
    return reset_count


def _delete_blob_if_exists(blob_path):
    blob_client = _get_blob_service_client().get_blob_client(
        container=storage_account_personal_chat_container_name,
        blob=blob_path,
    )
    if blob_client.exists():
        blob_client.delete_blob()


def _authorize_tabular_export_run_execution(run):
    user_id = str((run or {}).get('user_id') or '').strip()
    conversation_id = str((run or {}).get('conversation_id') or '').strip()
    if not user_id or not conversation_id:
        raise PermissionError('Export run identity is incomplete')

    try:
        conversation = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise PermissionError('Export conversation no longer exists') from exc
    if str(conversation.get('user_id') or '').strip() != user_id:
        raise PermissionError('Export conversation ownership changed')

    source_authorization = (
        (run or {}).get('source_descriptor')
        or (run or {}).get('source_authorization')
        or {}
    )
    if not source_authorization:
        return conversation

    source = str(source_authorization.get('source') or '').strip().lower()
    container_name = str(source_authorization.get('container') or '').strip()
    blob_path = str(source_authorization.get('blob_path') or '').strip()
    scope_id = str(source_authorization.get('scope_id') or '').strip()
    if not source:
        raise PermissionError('Export source authorization is incomplete')

    if source == 'chat':
        expected_prefix = f'{user_id}/{conversation_id}/'
        authorized = not container_name and not blob_path or (
            container_name == storage_account_personal_chat_container_name
            and blob_path.startswith(expected_prefix)
        )
    elif source == 'workspace':
        expected_prefix = f'{user_id}/'
        authorized = not container_name and not blob_path or (
            container_name == storage_account_user_documents_container_name
            and blob_path.startswith(expected_prefix)
        )
    elif source == 'group':
        if not scope_id:
            raise PermissionError('Export group scope is missing')
        assert_group_role(
            user_id,
            scope_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
        authorized = not container_name and not blob_path or (
            container_name == storage_account_group_documents_container_name
            and blob_path.startswith(f'{scope_id}/')
        )
    elif source == 'public':
        if not scope_id:
            raise PermissionError('Export public workspace scope is missing')
        visible_workspace_ids = set(get_user_visible_public_workspace_ids_from_settings(user_id) or [])
        authorized = scope_id in visible_workspace_ids and (
            not container_name and not blob_path
            or (
                container_name == storage_account_public_documents_container_name
                and blob_path.startswith(f'{scope_id}/')
            )
        )
    else:
        raise PermissionError('Export source type is not supported')

    if not authorized:
        raise PermissionError('Export source is no longer authorized')
    return conversation


def _get_versioned_source_blob_client(source_descriptor):
    container_name = str((source_descriptor or {}).get('container') or '').strip()
    blob_path = str((source_descriptor or {}).get('blob_path') or '').strip()
    expected_etag = str((source_descriptor or {}).get('blob_etag') or '').strip()
    if not container_name or not blob_path or not expected_etag:
        raise ValueError('Source query descriptor is incomplete')

    blob_client = _get_blob_service_client().get_blob_client(
        container=container_name,
        blob=blob_path,
    )
    blob_properties = blob_client.get_blob_properties()
    current_etag = str(getattr(blob_properties, 'etag', '') or '').strip()
    if isinstance(blob_properties, dict):
        current_etag = current_etag or str(blob_properties.get('etag') or '').strip()
    if current_etag != expected_etag:
        raise ValueError('Source CSV changed after the export was queued')
    return blob_client


def _revalidate_tabular_source_version_for_publication(run):
    source_descriptor = (
        (run or {}).get('source_descriptor')
        or (run or {}).get('source_authorization')
    )
    if not isinstance(source_descriptor, dict) or not source_descriptor.get('blob_etag'):
        return None
    return _get_versioned_source_blob_client(source_descriptor)


def _clean_generated_json_code_fence(response_content):
    cleaned = str(response_content or '').strip()
    if not cleaned:
        return ''

    cleaned = re.sub(r'(?is)^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'(?is)\s*```$', '', cleaned)
    return cleaned.strip()


def _parse_generated_json_entries(response_content):
    cleaned = _clean_generated_json_code_fence(response_content)
    if not cleaned:
        return None

    decoder = json.JSONDecoder()
    parsed_value = None
    try:
        parsed_value, _ = decoder.raw_decode(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed_value = None

    if parsed_value is None:
        for start_index, character in enumerate(cleaned):
            if character not in '[{':
                continue
            try:
                parsed_value, _ = decoder.raw_decode(cleaned[start_index:])
                break
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

    if isinstance(parsed_value, dict):
        return [parsed_value]
    if isinstance(parsed_value, list) and all(isinstance(item, dict) for item in parsed_value):
        return parsed_value
    return None


def _parse_generated_json_object(response_content):
    parsed_entries = _parse_generated_json_entries(response_content)
    if not parsed_entries or len(parsed_entries) != 1:
        return None
    return parsed_entries[0]


def _dump_generated_output_json(value):
    return json.dumps(value, default=str, ensure_ascii=False, separators=(',', ':'))


def _normalize_analysis_text(value, max_chars=4000):
    normalized_value = re.sub(r'\s+', ' ', str(value or '').strip())
    if len(normalized_value) <= max_chars:
        return normalized_value
    return f"{normalized_value[:max_chars].rstrip()}..."


def _normalize_analysis_findings(value):
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []

    findings = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate_text = candidate.get('finding') or candidate.get('summary') or candidate.get('text')
        else:
            candidate_text = candidate
        normalized_text = _normalize_analysis_text(candidate_text, max_chars=1200)
        if normalized_text:
            findings.append(normalized_text)
        if len(findings) >= TABULAR_ANALYSIS_MAX_FINDINGS:
            break
    return findings


def _normalize_analysis_counts(value):
    if not isinstance(value, dict):
        return {}
    counts = {}
    for count_key, count_value in value.items():
        normalized_key = _normalize_analysis_text(count_key, max_chars=120)
        if not normalized_key:
            continue
        if isinstance(count_value, (int, float, str, bool)) or count_value is None:
            counts[normalized_key] = count_value
        else:
            counts[normalized_key] = _normalize_analysis_text(count_value, max_chars=500)
    return counts


def _normalize_analysis_notable_rows(value):
    if not isinstance(value, list):
        return []

    notable_rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_row_number = _safe_int(
            item.get('source_row_number')
            or item.get('row_number')
            or item.get('row')
        )
        if source_row_number <= 0:
            continue
        note = _normalize_analysis_text(
            item.get('note')
            or item.get('finding')
            or item.get('reason')
            or item.get('summary'),
            max_chars=1200,
        )
        if not note:
            continue
        notable_rows.append({
            'source_row_number': source_row_number,
            'source_row_identity': _normalize_analysis_text(
                item.get('source_row_identity') or item.get('identity'),
                max_chars=200,
            ),
            'note': note,
        })
        if len(notable_rows) >= TABULAR_ANALYSIS_MAX_NOTABLE_ROWS:
            break
    return notable_rows


def _source_row_bounds_from_rows(source_rows):
    row_numbers = [
        _safe_int(row.get(TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD))
        for row in (source_rows or [])
        if isinstance(row, dict)
    ]
    row_numbers = [row_number for row_number in row_numbers if row_number > 0]
    if not row_numbers:
        return None, None
    return min(row_numbers), max(row_numbers)


def _source_row_bounds_from_summaries(summaries):
    row_starts = []
    row_ends = []
    for summary in summaries or []:
        row_start = _safe_int((summary or {}).get('source_row_start'))
        row_end = _safe_int((summary or {}).get('source_row_end'))
        if row_start > 0:
            row_starts.append(row_start)
        if row_end > 0:
            row_ends.append(row_end)
    if not row_starts or not row_ends:
        return None, None
    return min(row_starts), max(row_ends)


def _normalize_analysis_summary_payload(payload, source_rows=None, child_summaries=None, chunk_number=None, reduce_level=None, reduce_node=None):
    payload = payload if isinstance(payload, dict) else {}
    child_summaries = [summary for summary in (child_summaries or []) if isinstance(summary, dict)]
    source_row_start, source_row_end = _source_row_bounds_from_rows(source_rows)
    if source_row_start is None or source_row_end is None:
        source_row_start, source_row_end = _source_row_bounds_from_summaries(child_summaries)

    row_count = len(source_rows or [])
    if not row_count and child_summaries:
        row_count = sum(_safe_int(summary.get('row_count')) for summary in child_summaries)

    summary_text = _normalize_analysis_text(
        payload.get('summary')
        or payload.get('answer')
        or payload.get('overview'),
        max_chars=TABULAR_ANALYSIS_SUMMARY_MAX_CHARS,
    )
    findings = _normalize_analysis_findings(payload.get('findings'))
    notable_rows = _normalize_analysis_notable_rows(
        payload.get('notable_rows')
        or payload.get('row_references')
        or payload.get('citations')
    )
    counts = _normalize_analysis_counts(payload.get('counts'))
    if not summary_text and findings:
        summary_text = findings[0]
    if not summary_text:
        summary_text = 'No concise summary was returned for this analysis segment.'

    normalized_summary = {
        'summary': summary_text,
        'findings': findings,
        'counts': counts,
        'notable_rows': notable_rows,
        'row_count': row_count,
        'source_row_start': source_row_start,
        'source_row_end': source_row_end,
    }
    if chunk_number is not None:
        normalized_summary.update({
            'kind': 'chunk_summary',
            'chunk_number': _safe_int(chunk_number),
        })
    if reduce_level is not None:
        normalized_summary.update({
            'kind': 'reduce_summary',
            'reduce_level': _safe_int(reduce_level),
            'reduce_node': _safe_int(reduce_node),
            'child_summary_count': len(child_summaries),
        })
    return normalized_summary


def _get_tabular_analysis_reduce_fan_in(settings):
    return _settings_int(
        settings,
        'tabular_hierarchical_analysis_reduce_fan_in',
        TABULAR_ANALYSIS_DEFAULT_REDUCE_FAN_IN,
        minimum=2,
        maximum=TABULAR_ANALYSIS_MAX_REDUCE_FAN_IN,
    )


def _build_analysis_reduce_groups(items, fan_in):
    normalized_fan_in = max(2, _safe_int(fan_in, default=TABULAR_ANALYSIS_DEFAULT_REDUCE_FAN_IN))
    return [
        list(items[index:index + normalized_fan_in])
        for index in range(0, len(items or []), normalized_fan_in)
    ]


def _build_analysis_reduce_plan(summary_count, fan_in):
    remaining_count = _safe_int(summary_count, minimum=0)
    normalized_fan_in = max(2, _safe_int(fan_in, default=TABULAR_ANALYSIS_DEFAULT_REDUCE_FAN_IN))
    level_counts = []
    while remaining_count > 1:
        remaining_count = math.ceil(remaining_count / normalized_fan_in)
        level_counts.append(remaining_count)
    return level_counts


def _build_analysis_chunk_prompt(run, batch_rows, batch_number, batch_count):
    analysis_objective = str(run.get('analysis_objective') or run.get('user_question') or '').strip()
    selected_sheet = str(run.get('selected_sheet') or '').strip()
    selected_sheet_line = f"Worksheet: {selected_sheet}\n" if selected_sheet else ''
    return (
        'Analyze the bounded tabular chunk below for the user.\n\n'
        f'User analytical objective:\n{analysis_objective}\n\n'
        'Return ONLY a valid JSON object with these fields: summary, findings, counts, notable_rows.\n'
        'findings must be an array of concise strings. counts must be an object of useful aggregate counts.\n'
        'notable_rows must be an array of objects with source_row_number, source_row_identity, and note.\n'
        'Use source_row_number and source_row_identity from the input rows for any row references.\n'
        'Do not claim coverage beyond this chunk. Do not include markdown fences.\n\n'
        f"Source file: {run.get('source_file_name') or 'unknown file'}\n"
        f'{selected_sheet_line}'
        f'Chunk: {batch_number}/{batch_count}\n\n'
        f'Input rows:\n{_dump_generated_output_json(batch_rows)}'
    )


def _build_combined_chunk_prompt(run, batch_rows, batch_number, batch_count, output_schema=None):
    user_question = str(run.get('user_question') or '').strip()
    analysis_objective = str(run.get('analysis_objective') or user_question).strip()
    source_file_name = str(run.get('source_file_name') or 'unknown file').strip() or 'unknown file'
    selected_sheet = str(run.get('selected_sheet') or '').strip()
    selected_sheet_line = f"Worksheet: {selected_sheet}\n" if selected_sheet else ''
    model_output_schema = [
        field_name
        for field_name in (output_schema or [])
        if field_name not in {
            TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
            TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
        }
    ]
    output_schema_line = (
        f'Use exactly these structured row fields for every object, in this order: '
        f'{json.dumps(model_output_schema, ensure_ascii=False)}.\n'
        if model_output_schema
        else ''
    )
    return (
        'Transform and analyze the bounded tabular chunk below for the user.\n\n'
        f'User structured-output instructions:\n{user_question}\n\n'
        f'User analytical objective:\n{analysis_objective}\n\n'
        'Return ONLY a valid JSON object with exactly these top-level fields: structured_rows, analysis_summary.\n'
        f'structured_rows must be an array of exactly {len(batch_rows)} object(s), one per input row, in the same order.\n'
        f'{output_schema_line}'
        f'Each structured row must copy {TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD} exactly from the matching input row. '
        f'Do not include {TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD} or {TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD} in structured rows.\n'
        'Do not drop, merge, summarize, or cap structured rows. If a requested field cannot be derived, include it with null or an empty string.\n'
        'analysis_summary must be an object with summary, findings, counts, and notable_rows. '
        'findings must be an array of concise strings. counts must be an object of useful aggregate counts. '
        'notable_rows must be an array of objects with source_row_number, source_row_identity, and note.\n'
        'Use source_row_number and source_row_identity from the input rows for any row references. '
        'Do not claim coverage beyond this chunk. Do not include markdown fences.\n\n'
        f'Source file: {source_file_name}\n'
        f'{selected_sheet_line}'
        f'Chunk: {batch_number}/{batch_count}\n\n'
        f'Input rows:\n{_dump_generated_output_json(batch_rows)}'
    )


def _normalize_combined_chunk_payload(run, payload, batch_rows, batch_number, expected_output_schema=None):
    if not isinstance(payload, dict):
        raise ValueError('Combined chunk response was not a JSON object')

    structured_rows = (
        payload.get('structured_rows')
        or payload.get('rows')
        or payload.get('entries')
    )
    if not isinstance(structured_rows, list):
        raise ValueError('Combined chunk response did not include structured_rows as an array')
    normalized_entries, output_schema = _normalize_model_generated_batch_entries(
        batch_rows,
        structured_rows,
        expected_output_schema=expected_output_schema,
        run_id=run.get('id'),
        batch_number=batch_number,
    )

    analysis_payload = payload.get('analysis_summary')
    if not isinstance(analysis_payload, dict):
        analysis_payload = {
            field_name: payload.get(field_name)
            for field_name in ('summary', 'findings', 'counts', 'notable_rows')
            if field_name in payload
        }
    analysis_summary = _normalize_analysis_summary_payload(
        analysis_payload,
        source_rows=batch_rows,
        chunk_number=batch_number,
    )
    return normalized_entries, output_schema, analysis_summary


def _build_analysis_reduce_prompt(run, summaries, level_number, node_number, node_count):
    analysis_objective = str(run.get('analysis_objective') or run.get('user_question') or '').strip()
    return (
        'Reduce the bounded tabular analysis summaries below into one higher-level summary.\n\n'
        f'User analytical objective:\n{analysis_objective}\n\n'
        'Return ONLY a valid JSON object with these fields: summary, findings, counts, notable_rows.\n'
        'Preserve row references by carrying forward source_row_number and source_row_identity in notable_rows.\n'
        'Merge duplicate findings, keep the most important evidence, and do not invent rows or counts.\n'
        'Do not include markdown fences.\n\n'
        f'Reduce level: {level_number}; node: {node_number}/{node_count}\n\n'
        f'Input summaries:\n{_dump_generated_output_json(summaries)}'
    )


def _checkpoint_source_input_batch(run, batch_rows, source_scan_row_count):
    _raise_if_tabular_export_canceled(run)
    staged_row_count = _safe_int(run.get('source_staged_rows'))
    batch_number = _safe_int(run.get('source_staged_batches')) + 1
    prepared_rows = _prepare_tabular_source_rows(
        batch_rows,
        start_row=staged_row_count,
        token_namespace=run.get('id'),
    )
    input_blob_path = _input_blob_path(
        run.get('user_id'),
        run.get('conversation_id'),
        run.get('id'),
        batch_number,
    )
    _upload_json_blob(
        input_blob_path,
        prepared_rows,
        metadata={
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'generated_output_input': 'true',
            'batch_number': batch_number,
            'source_query_checkpoint': 'true',
        },
    )
    _raise_if_tabular_export_canceled(run)

    now = _now_iso()
    run.update({
        'source_staged_rows': staged_row_count + len(prepared_rows),
        'source_staged_batches': batch_number,
        'source_scan_row_count': _safe_int(source_scan_row_count),
        'updated_at': now,
        'last_heartbeat_at': now,
        'last_message': (
            f'Staged source query batch {batch_number} '
            f'with {staged_row_count + len(prepared_rows)} row(s) ready'
        ),
    })
    return _replace_claimed_run(run)


def _iter_versioned_tabular_source_rows(
    source_descriptor,
    source_format,
    source_chunk_rows,
    resume_source_row,
):
    blob_path = str(source_descriptor.get('blob_path') or '').strip()
    tabular_plugin = TabularProcessingPlugin()

    if source_format == 'csv':
        source_blob_client = _get_versioned_source_blob_client(source_descriptor)
        with tempfile.SpooledTemporaryFile(
            max_size=TABULAR_EXPORT_FINAL_SPOOL_MAX_MEMORY_BYTES,
            mode='w+b',
        ) as source_stream:
            source_blob_client.download_blob(
                etag=source_descriptor.get('blob_etag'),
                match_condition=MatchConditions.IfNotModified,
            ).readinto(source_stream)
            source_stream.seek(0)
            source_rows = iter_tabular_csv_query_rows(
                csv_stream=source_stream,
                query_expression=source_descriptor.get('query_expression'),
                return_columns=source_descriptor.get('return_columns'),
                source_chunk_rows=source_chunk_rows,
                tabular_plugin=tabular_plugin,
                start_source_row=resume_source_row,
            )
            yield from source_rows
        return

    _get_versioned_source_blob_client(source_descriptor)
    sheet_names = [
        str(sheet_name or '').strip()
        for sheet_name in source_descriptor.get('sheet_names') or []
        if str(sheet_name or '').strip()
    ]
    if not sheet_names:
        raise ValueError('Source-backed workbook replay requires an explicit worksheet scope')
    parsed_return_columns = tabular_plugin._parse_optional_column_list_argument(
        source_descriptor.get('return_columns')
    )
    source_row_offset = 0
    for sheet_name in sheet_names:
        source_dataframe = tabular_plugin._read_tabular_blob_to_dataframe(
            source_descriptor.get('container'),
            blob_path,
            sheet_name=sheet_name,
            require_explicit_sheet=True,
        )
        source_dataframe = tabular_plugin._try_numeric_conversion(source_dataframe)
        source_dataframe.index = range(
            source_row_offset,
            source_row_offset + len(source_dataframe),
        )
        source_row_offset += len(source_dataframe)
        filtered_dataframe, _ = tabular_plugin._apply_query_expression_with_fallback(
            source_dataframe,
            query_expression=source_descriptor.get('query_expression'),
            normalize_match=False,
        )
        selected_columns = [
            column_name
            for column_name in (parsed_return_columns or list(filtered_dataframe.columns))
            if column_name in filtered_dataframe.columns
        ]
        output_records = tabular_plugin._build_row_output_records(
            filtered_dataframe,
            selected_columns,
        )
        for source_row_index, output_record in zip(filtered_dataframe.index, output_records):
            source_row_number = int(source_row_index) + 1
            if source_row_number > resume_source_row:
                yield source_row_number, output_record
    _get_versioned_source_blob_client(source_descriptor)


def _stage_tabular_generated_output_source(run, settings):
    source_descriptor = run.get('source_descriptor') or {}
    if source_descriptor.get('kind') != 'query_tabular_data':
        raise ValueError('Unsupported generated export source descriptor')
    blob_path = str(source_descriptor.get('blob_path') or '').strip()
    source_format = str(source_descriptor.get('source_format') or '').strip().lower()
    if not source_format:
        source_format = os.path.splitext(blob_path)[1].lower().lstrip('.')
    if source_format not in TABULAR_EXTENSIONS:
        raise ValueError('Source-backed generated exports require a supported tabular source')

    expected_row_count = _safe_int(source_descriptor.get('expected_row_count'))
    if expected_row_count <= 0:
        raise ValueError('Source query descriptor has no expected rows')
    source_chunk_rows = _settings_int(
        settings,
        'tabular_generated_output_source_chunk_rows',
        TABULAR_EXPORT_DEFAULT_SOURCE_CHUNK_ROWS,
        minimum=100,
        maximum=10000,
    )
    max_batch_rows = _safe_int(
        source_descriptor.get('batch_max_rows'),
        default=TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_ROWS,
        minimum=1,
        maximum=TABULAR_EXPORT_MAX_SOURCE_BATCH_ROWS,
    )
    max_batch_chars = _safe_int(
        source_descriptor.get('batch_max_chars'),
        default=TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_CHARS,
        minimum=6000,
        maximum=TABULAR_EXPORT_MAX_SOURCE_BATCH_CHARS,
    )
    resume_source_row = _safe_int(run.get('source_scan_row_count'))
    pending_rows = []
    pending_chars = 0
    last_source_row_number = resume_source_row
    source_rows = _iter_versioned_tabular_source_rows(
        source_descriptor,
        source_format,
        source_chunk_rows,
        resume_source_row,
    )

    for source_row_number, source_row in source_rows:
        source_row_text = _dump_generated_output_json(source_row)
        current_batch_row_limit = _get_tabular_source_batch_row_limit(
            source_descriptor,
            run.get('source_staged_batches'),
        )
        if pending_rows and (
            len(pending_rows) >= current_batch_row_limit
            or pending_chars + len(source_row_text) > max_batch_chars
        ):
            run = _checkpoint_source_input_batch(
                run,
                pending_rows,
                source_scan_row_count=source_row_number - 1,
            )
            pending_rows = []
            pending_chars = 0

        pending_rows.append(source_row)
        pending_chars += len(source_row_text)
        last_source_row_number = source_row_number
        if len(pending_rows) >= current_batch_row_limit:
            run = _checkpoint_source_input_batch(
                run,
                pending_rows,
                source_scan_row_count=source_row_number,
            )
            pending_rows = []
            pending_chars = 0

    if pending_rows:
        run = _checkpoint_source_input_batch(
            run,
            pending_rows,
            source_scan_row_count=last_source_row_number,
        )

    staged_row_count = _safe_int(run.get('source_staged_rows'))
    staged_batch_count = _safe_int(run.get('source_staged_batches'))
    if staged_row_count != expected_row_count:
        raise ValueError(
            f'Source query returned {staged_row_count} row(s); expected {expected_row_count}'
        )
    if staged_batch_count <= 0:
        raise ValueError('Source query produced no input checkpoints')

    staged_chunk_row_counts = []
    for batch_number in range(1, staged_batch_count + 1):
        batch_rows = _download_json_blob(_input_blob_path(
            run.get('user_id'),
            run.get('conversation_id'),
            run.get('id'),
            batch_number,
        ))
        if not isinstance(batch_rows, list):
            raise ValueError(f'Source input checkpoint {batch_number}/{staged_batch_count} was not a JSON array')
        staged_chunk_row_counts.append(len(batch_rows))

    chunk_manifest = _write_chunk_manifest_for_run(
        run.get('user_id'),
        run.get('conversation_id'),
        run.get('id'),
        staged_batch_count,
        row_count=staged_row_count,
        chunk_row_counts=staged_chunk_row_counts,
        chunk_status='staged',
    )

    now = _now_iso()
    run.update({
        'source_staging_complete': True,
        'row_count': staged_row_count,
        'batch_count': staged_batch_count,
        'total_chunk_count': staged_batch_count,
        'chunk_manifest': chunk_manifest,
        'updated_at': now,
        'last_heartbeat_at': now,
        'last_message': (
            f'Source query staging complete: {staged_row_count} row(s) '
            f'across {staged_batch_count} batch(es)'
        ),
    })
    return _replace_claimed_run(run)


def _migrate_legacy_tabular_export_run(run):
    if _safe_int(run.get('contract_version')) >= TABULAR_EXPORT_CONTRACT_VERSION:
        return _sync_tabular_generation_contract_fields(run)

    batch_count = _safe_int(run.get('batch_count'))
    expected_row_count = _safe_int(run.get('row_count'))
    if batch_count <= 0 or expected_row_count <= 0:
        raise ValueError('Legacy export run has invalid input counts')

    aggregate_input_batches = None
    aggregate_input_blob_path = str(run.get('input_blob_path') or '').strip()
    if aggregate_input_blob_path:
        aggregate_input_batches = _download_json_blob(aggregate_input_blob_path)
        if not isinstance(aggregate_input_batches, list):
            raise ValueError('Legacy input batches blob was not a JSON array')

    migrated_row_count = 0
    migrated_chunk_row_counts = []
    for batch_number in range(1, batch_count + 1):
        _raise_if_tabular_export_canceled(run)
        if aggregate_input_batches is not None:
            try:
                batch_rows = aggregate_input_batches[batch_number - 1]
            except IndexError as exc:
                raise ValueError(f'Legacy input batch {batch_number}/{batch_count} is missing') from exc
        else:
            batch_rows = _download_json_blob(_input_blob_path(
                run.get('user_id'),
                run.get('conversation_id'),
                run.get('id'),
                batch_number,
            ))
        if not isinstance(batch_rows, list):
            raise ValueError(f'Legacy input batch {batch_number}/{batch_count} was not a JSON array')

        prepared_rows = _prepare_tabular_source_rows(
            batch_rows,
            start_row=migrated_row_count,
            token_namespace=run.get('id'),
        )
        _upload_json_blob(
            _input_blob_path(
                run.get('user_id'),
                run.get('conversation_id'),
                run.get('id'),
                batch_number,
            ),
            prepared_rows,
            metadata={
                'run_id': run.get('id'),
                'conversation_id': run.get('conversation_id'),
                'generated_output_input': 'true',
                'batch_number': batch_number,
                'contract_version': TABULAR_EXPORT_CONTRACT_VERSION,
            },
        )
        _delete_blob_if_exists(_output_blob_path(
            run.get('user_id'),
            run.get('conversation_id'),
            run.get('id'),
            batch_number,
        ))
        _delete_blob_if_exists(_output_summary_blob_path(
            run.get('user_id'),
            run.get('conversation_id'),
            run.get('id'),
            batch_number,
        ))
        prepared_row_count = len(prepared_rows)
        migrated_chunk_row_counts.append(prepared_row_count)
        migrated_row_count += prepared_row_count

    if migrated_row_count != expected_row_count:
        raise ValueError(
            f'Legacy input migration found {migrated_row_count} row(s); expected {expected_row_count}'
        )

    chunk_manifest = _write_chunk_manifest_for_run(
        run.get('user_id'),
        run.get('conversation_id'),
        run.get('id'),
        batch_count,
        row_count=migrated_row_count,
        chunk_row_counts=migrated_chunk_row_counts,
        chunk_status='staged',
    )
    now = _now_iso()
    run.update({
        'contract_version': TABULAR_EXPORT_CONTRACT_VERSION,
        'generation_contract_version': TABULAR_GENERATION_CONTRACT_VERSION,
        'response_protocol_version': TABULAR_RESPONSE_PROTOCOL_OBJECT_V1,
        'executor_mode': TABULAR_EXECUTOR_MODE_FIXED_WINDOW,
        'task_type': _normalize_tabular_run_task_type(run.get('task_type')),
        'analysis_objective': str(run.get('analysis_objective') or '').strip(),
        'total_chunk_count': batch_count,
        'processed_chunk_count': 0,
        'failed_chunk_count': 0,
        'chunk_manifest': chunk_manifest,
        'input_blob_path': None,
        'completed_batches': 0,
        'processed_rows': 0,
        'planned_batch_count': batch_count,
        'completed_batch_count': 0,
        'highest_contiguous_batch': 0,
        'active_batch_count': 0,
        'retry_wait_batch_count': 0,
        'exhausted_batch_count': 0,
        'checkpointed_row_count': 0,
        'generation_started_at': run.get('started_at'),
        'generation_completed_at': None,
        'plan_blob_path': None,
        'plan_hash': None,
        'output_schema': None,
        'regenerate_legacy_output_checkpoints': False,
        'updated_at': now,
        'last_heartbeat_at': now,
        'last_message': 'Legacy export inputs migrated; output checkpoints will be regenerated',
    })
    _raise_if_tabular_export_canceled(run)
    return _replace_claimed_run(run)


def _build_batch_prompt(
    user_question,
    batch_rows,
    batch_index,
    total_batches,
    source_file_name,
    selected_sheet='',
    output_schema=None,
    response_protocol=TABULAR_RESPONSE_PROTOCOL_OBJECT_V1,
    generation_plan=None,
):
    if _is_compact_row_array_protocol(response_protocol):
        return _build_compact_batch_prompt(
            user_question,
            batch_rows,
            batch_index,
            total_batches,
            source_file_name,
            selected_sheet=selected_sheet,
            generation_plan=generation_plan,
        )

    source_file_name = str(source_file_name or 'unknown file').strip() or 'unknown file'
    selected_sheet = str(selected_sheet or '').strip()
    batch_rows_json = _dump_generated_output_json(batch_rows)
    selected_sheet_line = f"Worksheet: {selected_sheet}\n" if selected_sheet else ''
    model_output_schema = [
        field_name
        for field_name in (output_schema or [])
        if field_name not in {
            TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
            TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
        }
    ]
    output_schema_line = (
        f'Use exactly these output fields for every object, in this order: '
        f'{json.dumps(model_output_schema, ensure_ascii=False)}.\n'
        if model_output_schema
        else ''
    )

    return (
        'Transform the tabular input rows below into structured output for the user.\n\n'
        f'User instructions:\n{user_question}\n\n'
        'Return ONLY a valid JSON array.\n'
        f'Return exactly {len(batch_rows)} JSON object(s), one per input row, in the same order.\n'
        f'{output_schema_line}'
        f'Copy {TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD} exactly from each input row into its matching output object. '
        f'The {TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD} and {TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD} fields are internal; '
        'do not include those two fields in generated objects.\n'
        'Do not return CSV text, embedded CSV headers, markdown tables, or a field named csv; every requested output column must be a separate JSON object field.\n'
        'Do not drop, merge, summarize, or cap rows.\n'
        'Input rows may include normalized helper fields such as comment_id, body_text, source_file, attachment_present, attachment_names, and attachment_text. Use those normalized fields when they are present.\n'
        'Input rows may include a referenced_documents array containing row-linked evidence from explicitly referenced non-tabular documents. Use that evidence as part of the source row context when it is relevant to the requested output.\n'
        'If referenced_documents contains excerpt text or attachment_text is present, treat that excerpt content as available attachment text. Do not say attachment text is unavailable when such excerpts are present.\n'
        'If a requested field cannot be derived, include the field with null or an empty string instead of omitting the row.\n'
        'Do not wrap the JSON in markdown fences.\n\n'
        f'Source file: {source_file_name}\n'
        f'{selected_sheet_line}'
        f'Batch: {batch_index + 1}/{total_batches}\n\n'
        f'Input rows:\n{batch_rows_json}'
    )


def _build_compact_batch_prompt(
    user_question,
    batch_rows,
    batch_index,
    total_batches,
    source_file_name,
    selected_sheet='',
    generation_plan=None,
):
    source_file_name = str(source_file_name or 'unknown file').strip() or 'unknown file'
    selected_sheet = str(selected_sheet or '').strip()
    selected_sheet_line = f"Worksheet: {selected_sheet}\n" if selected_sheet else ''
    llm_fields = _get_tabular_generation_plan_llm_fields(generation_plan)
    if not llm_fields:
        raise ValueError('Compact batch prompt requires an active generation plan')
    row_keys, _ = _build_compact_batch_key_map(batch_rows)
    field_contract = [
        {
            'position': field_index,
            'name': field.get('name'),
            'type': field.get('type'),
            'nullable': field.get('nullable'),
            'description': field.get('description'),
        }
        for field_index, field in enumerate(llm_fields, start=1)
    ]
    protocol_contract = {
        'p': _get_compact_plan_hash_prefix(generation_plan),
        'row_key_position': 0,
        'fields': field_contract,
        'expected_row_keys': row_keys,
    }
    prompt_rows = _build_compact_prompt_rows(batch_rows)
    return (
        'Transform the tabular input rows below into compact positional JSON for the user.\n\n'
        f'User instructions:\n{user_question}\n\n'
        'Return ONLY one valid JSON object with exactly these top-level fields: p, rows.\n'
        'Do not include markdown fences, explanations, field names inside rows, source metadata, or extra properties.\n'
        'Each item in rows must be an array. Position 0 is the batch-local row key. Positions 1..N are the field values in the exact plan order below.\n'
        'Return every expected row key exactly once. Do not use source row tokens. Do not drop, merge, summarize, cap, or reorder by source content.\n'
        'If a nullable field cannot be derived, return null. Non-nullable fields must contain a value of the requested type.\n\n'
        f'Compact protocol contract:\n{_dump_generated_output_json(protocol_contract)}\n\n'
        f'Source file: {source_file_name}\n'
        f'{selected_sheet_line}'
        f'Batch: {batch_index + 1}/{total_batches}\n\n'
        f'Input rows:\n{_dump_generated_output_json(prompt_rows)}'
    )


def _resolve_tabular_chunk_model_selection(gpt_model, settings, model_context=None):
    chunk_model_mode = str(
        (settings or {}).get('tabular_generated_output_chunk_model_mode') or 'current'
    ).strip().lower()
    if chunk_model_mode != 'configured':
        return gpt_model, model_context

    configured_deployment = str(
        (settings or {}).get('tabular_generated_output_chunk_model_deployment') or ''
    ).strip()
    if not configured_deployment:
        return gpt_model, model_context

    return configured_deployment, {}


def _normalize_tabular_model_identifier(value):
    return re.sub(r'[^a-z0-9]+', '-', str(value or '').strip().lower()).strip('-')


def _get_tabular_model_record_identifiers(model_record):
    if not isinstance(model_record, dict):
        return set()

    identifiers = {
        _normalize_tabular_model_identifier(model_record.get(field_name))
        for field_name in TABULAR_EXPORT_MODEL_IDENTIFIER_FIELDS
        if model_record.get(field_name)
    }
    for alias in model_record.get('aliases') or []:
        normalized_alias = _normalize_tabular_model_identifier(alias)
        if normalized_alias:
            identifiers.add(normalized_alias)
    return {identifier for identifier in identifiers if identifier}


def _read_tabular_model_token_limit(model_record, field_names):
    if not isinstance(model_record, dict):
        return None

    containers = [model_record]
    containers.extend(
        model_record.get(container_name)
        for container_name in TABULAR_EXPORT_MODEL_LIMIT_CONTAINER_FIELDS
        if isinstance(model_record.get(container_name), dict)
    )
    for container in containers:
        for field_name in field_names:
            value = _safe_int(container.get(field_name))
            if value > 0:
                return value
    return None


def _iter_configured_tabular_model_records(settings):
    settings = settings or {}
    gpt_model_settings = settings.get('gpt_model')
    if isinstance(gpt_model_settings, dict):
        for model_record in gpt_model_settings.get('selected') or []:
            if isinstance(model_record, dict):
                yield model_record

    for endpoint in settings.get('model_endpoints') or []:
        if not isinstance(endpoint, dict):
            continue
        for model_record in endpoint.get('models') or []:
            if isinstance(model_record, dict):
                yield model_record


def _load_tabular_model_limit_catalog():
    catalog_path = os.path.join(
        os.path.dirname(__file__),
        'static',
        'json',
        'model_capabilities.json',
    )
    try:
        with open(catalog_path, 'r', encoding='utf-8') as catalog_file:
            catalog = json.load(catalog_file)
    except (OSError, json.JSONDecodeError):
        return []
    return [
        model_record
        for model_record in catalog.get('models') or []
        if isinstance(model_record, dict)
    ] if isinstance(catalog, dict) else []


def _resolve_tabular_model_token_limits(gpt_model, settings, model_context=None, catalog_records=None):
    chunk_gpt_model, chunk_model_context = _resolve_tabular_chunk_model_selection(
        gpt_model,
        settings,
        model_context=model_context,
    )
    chunk_model_context = chunk_model_context if isinstance(chunk_model_context, dict) else {}
    requested_identifiers = {
        _normalize_tabular_model_identifier(identifier)
        for identifier in (
            chunk_gpt_model,
            chunk_model_context.get('model_id'),
            chunk_model_context.get('model_deployment'),
        )
        if identifier
    }
    candidate_groups = [
        ('context', [chunk_model_context]),
        ('configured', list(_iter_configured_tabular_model_records(settings))),
        (
            'catalog',
            list(catalog_records) if catalog_records is not None else _load_tabular_model_limit_catalog(),
        ),
    ]
    context_token_limit = None
    output_token_limit = None
    limit_sources = []
    for source_name, model_records in candidate_groups:
        for model_record in model_records:
            if not isinstance(model_record, dict):
                continue
            record_identifiers = _get_tabular_model_record_identifiers(model_record)
            if requested_identifiers and not requested_identifiers.intersection(record_identifiers):
                continue
            requested_identifiers.update(record_identifiers)
            prior_context_token_limit = context_token_limit
            prior_output_token_limit = output_token_limit
            if context_token_limit is None:
                context_token_limit = _read_tabular_model_token_limit(
                    model_record,
                    TABULAR_EXPORT_MODEL_CONTEXT_LIMIT_FIELDS,
                )
            if output_token_limit is None:
                output_token_limit = _read_tabular_model_token_limit(
                    model_record,
                    TABULAR_EXPORT_MODEL_OUTPUT_LIMIT_FIELDS,
                )
            supplied_limit = (
                context_token_limit != prior_context_token_limit
                or output_token_limit != prior_output_token_limit
            )
            if supplied_limit and source_name not in limit_sources:
                limit_sources.append(source_name)
            if context_token_limit and output_token_limit:
                break
        if context_token_limit and output_token_limit:
            break

    return {
        'model': chunk_gpt_model,
        'context_token_limit': context_token_limit or TABULAR_EXPORT_DEFAULT_CONTEXT_TOKEN_LIMIT,
        'output_token_limit': output_token_limit or TABULAR_EXPORT_DEFAULT_OUTPUT_TOKEN_LIMIT,
        'source': '+'.join(limit_sources) if limit_sources else 'fallback',
    }


def _build_model_aware_source_batch_budget(
    gpt_model,
    settings,
    model_context=None,
    task_type=TABULAR_RUN_TASK_STRUCTURED_EXPORT,
    user_question=None,
    catalog_records=None,
):
    settings = settings or {}
    token_limits = _resolve_tabular_model_token_limits(
        gpt_model,
        settings,
        model_context=model_context,
        catalog_records=catalog_records,
    )
    context_token_limit = _safe_int(token_limits.get('context_token_limit'), minimum=1)
    output_token_limit = _safe_int(token_limits.get('output_token_limit'), minimum=1)
    input_ratio = _settings_float(
        settings,
        'tabular_generated_output_input_token_ratio',
        TABULAR_EXPORT_DEFAULT_INPUT_TOKEN_RATIO,
        minimum=0.1,
        maximum=0.8,
    )
    if context_token_limit > TABULAR_EXPORT_LARGE_CONTEXT_TOKEN_THRESHOLD:
        input_ratio = min(
            input_ratio,
            _settings_float(
                settings,
                'tabular_generated_output_large_context_input_token_ratio',
                TABULAR_EXPORT_LARGE_CONTEXT_INPUT_TOKEN_RATIO,
                minimum=0.1,
                maximum=0.5,
            ),
        )
    input_token_budget = int(context_token_limit * input_ratio)
    if context_token_limit > TABULAR_EXPORT_LARGE_CONTEXT_TOKEN_THRESHOLD:
        input_token_budget = min(
            input_token_budget,
            _settings_int(
                settings,
                'tabular_generated_output_input_token_soft_cap',
                TABULAR_EXPORT_INPUT_TOKEN_SOFT_CAP,
                minimum=16000,
                maximum=400000,
            ),
        )
    question_token_reserve = math.ceil(len(str(user_question or '')) / TABULAR_EXPORT_APPROXIMATE_CHARS_PER_TOKEN)
    input_token_budget = max(
        input_token_budget - TABULAR_EXPORT_PROMPT_TOKEN_RESERVE - question_token_reserve,
        1500,
    )
    output_token_budget = max(
        int(output_token_limit * _settings_float(
            settings,
            'tabular_generated_output_output_token_ratio',
            TABULAR_EXPORT_DEFAULT_OUTPUT_TOKEN_RATIO,
            minimum=0.1,
            maximum=0.9,
        )),
        1000,
    )
    input_bound_chars = int(input_token_budget * TABULAR_EXPORT_APPROXIMATE_CHARS_PER_TOKEN)
    max_batch_chars = input_bound_chars
    if _normalize_tabular_run_task_type(task_type) != TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS:
        output_expansion_ratio = _settings_float(
            settings,
            'tabular_generated_output_output_expansion_ratio',
            TABULAR_EXPORT_DEFAULT_OUTPUT_EXPANSION_RATIO,
            minimum=0.5,
            maximum=5.0,
        )
        output_bound_chars = int(
            output_token_budget
            * TABULAR_EXPORT_APPROXIMATE_CHARS_PER_TOKEN
            / output_expansion_ratio
        )
        max_batch_chars = min(max_batch_chars, output_bound_chars)
    max_batch_chars = _safe_int(
        max_batch_chars,
        minimum=6000,
        maximum=TABULAR_EXPORT_MAX_SOURCE_BATCH_CHARS,
    )
    configured_max_chars = settings.get('tabular_generated_output_max_batch_chars')
    if configured_max_chars not in (None, ''):
        max_batch_chars = min(
            max_batch_chars,
            _safe_int(
                configured_max_chars,
                default=TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_CHARS,
                minimum=6000,
                maximum=TABULAR_EXPORT_MAX_SOURCE_BATCH_CHARS,
            ),
        )

    scaled_batch_rows = math.ceil(
        TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_ROWS
        * max_batch_chars
        / TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_CHARS
    )
    max_batch_rows = _safe_int(
        scaled_batch_rows,
        minimum=1,
        maximum=TABULAR_EXPORT_MAX_SOURCE_BATCH_ROWS,
    )
    configured_max_rows = settings.get('tabular_generated_output_max_batch_rows')
    if configured_max_rows not in (None, ''):
        max_batch_rows = min(
            max_batch_rows,
            _safe_int(
                configured_max_rows,
                default=TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_ROWS,
                minimum=1,
                maximum=TABULAR_EXPORT_MAX_SOURCE_BATCH_ROWS,
            ),
        )

    return {
        'max_rows': max_batch_rows,
        'max_chars': max_batch_chars,
        'context_token_limit': context_token_limit,
        'output_token_limit': output_token_limit,
        'input_token_budget': input_token_budget,
        'output_token_budget': output_token_budget,
        'limit_source': token_limits.get('source'),
        'model': token_limits.get('model'),
    }


def _build_chat_service(gpt_model, settings, model_context=None, preselected=False):
    if preselected:
        chunk_gpt_model = gpt_model
        chunk_model_context = model_context
    else:
        chunk_gpt_model, chunk_model_context = _resolve_tabular_chunk_model_selection(
            gpt_model,
            settings,
            model_context=model_context,
        )
    chat_service, _ = build_semantic_kernel_chat_service_for_model(
        chunk_gpt_model,
        settings,
        service_id='tabular-generated-output-background',
        model_context=chunk_model_context,
    )
    return chat_service


def _get_tabular_generation_plan_mode(run):
    persisted_mode = str((run or {}).get('plan_mode') or '').strip().lower()
    if (
        persisted_mode in {'shadow', 'active'}
        and ((run or {}).get('plan_blob_path') or (run or {}).get('plan_hash'))
    ):
        return persisted_mode

    rollout_settings = (run or {}).get('generation_rollout_settings') or {}
    if not _settings_bool(rollout_settings, 'enable_tabular_generation_plan', False):
        return 'off'
    return _settings_mode(
        rollout_settings,
        'tabular_generation_plan_mode',
        'off',
        TABULAR_ROLLOUT_PLANNER_MODES,
    )


def _resolve_tabular_generation_planner_model(run, settings):
    chunk_model = str((run or {}).get('chunk_gpt_model') or '').strip()
    chunk_model_context = (run or {}).get('chunk_model_context')
    if not chunk_model:
        chunk_model, chunk_model_context = _resolve_tabular_chunk_model_selection(
            (run or {}).get('gpt_model'),
            settings,
            model_context=(run or {}).get('model_context'),
        )
    chunk_model_context = chunk_model_context if isinstance(chunk_model_context, dict) else {}
    endpoint_id = next((
        str(chunk_model_context.get(field_name) or '').strip()
        for field_name in ('endpoint_id', 'endpointId', 'endpoint', 'id')
        if chunk_model_context.get(field_name)
    ), '')
    model_id = next((
        str(chunk_model_context.get(field_name) or '').strip()
        for field_name in ('model_id', 'modelId', 'model_name', 'modelName')
        if chunk_model_context.get(field_name)
    ), '')
    deployment = next((
        str(chunk_model_context.get(field_name) or '').strip()
        for field_name in ('model_deployment', 'deploymentName', 'deployment_name', 'deployment')
        if chunk_model_context.get(field_name)
    ), '')
    normalized_chunk_model = str(chunk_model or '').strip()
    return {
        'endpoint_id': endpoint_id,
        'model_id': model_id or normalized_chunk_model,
        'deployment': deployment or normalized_chunk_model,
    }


def _load_tabular_generation_plan_sample_rows(run, input_batches):
    batch_count = _safe_int((run or {}).get('batch_count'), minimum=0)
    if batch_count <= 0:
        raise ValueError('Planner cannot sample a run without input batches')

    sample_rows = []
    batch_numbers = [1]
    if batch_count > 1:
        batch_numbers.append(batch_count)
    for batch_number in batch_numbers:
        batch_rows = _load_input_batch_rows(
            run,
            input_batches,
            (run or {}).get('user_id'),
            (run or {}).get('id'),
            batch_number,
            batch_count,
        )
        remaining_rows = TABULAR_GENERATION_PLAN_MAX_SAMPLE_ROWS - len(sample_rows)
        if remaining_rows <= 0:
            break
        sample_rows.extend(batch_rows[:remaining_rows])
    return sample_rows


def _build_tabular_generation_plan_prompt(run, input_contract):
    user_question = str((run or {}).get('user_question') or '').strip()
    if not user_question:
        raise ValueError('Planner user instructions are empty')
    if len(user_question) > TABULAR_GENERATION_PLAN_MAX_QUESTION_CHARS:
        raise ValueError('Planner user instructions exceed the bounded planning limit')

    planner_input = {
        'columns': input_contract.get('columns') or [],
        'sample_shapes': input_contract.get('sample_shapes') or [],
    }
    return (
        'Design the stable output schema for a row-by-row tabular generation run.\n\n'
        f'User instructions:\n{user_question}\n\n'
        f"Requested output format: {str((run or {}).get('output_format') or '').strip().lower()}\n"
        f"Source row count: {_safe_int((run or {}).get('row_count'), minimum=0)}\n"
        f'Bounded input schema and redacted value shapes:\n{_dump_generated_output_json(planner_input)}\n\n'
        'Return ONLY one JSON object with output_fields and optional output_verbosity. '
        'output_fields must be a non-empty array in exact output order. Each field object must contain '
        'name, description, type, nullable, and source. source must be "llm". Supported types are '
        'string, integer, number, boolean, object, and array. Do not include source_row_number, '
        'source_row_identity, or any __simplechat fields; the server adds source metadata. '
        'Preserve every explicit output field requested by the user. Do not answer any source row, '
        'copy sample content, include markdown, or add other top-level properties.'
    )


async def _generate_tabular_generation_plan(
    chat_service,
    run,
    input_contract,
    planner_model,
    timeout_seconds,
):
    planner_prompt = _build_tabular_generation_plan_prompt(run, input_contract)
    bounded_timeout_seconds = min(
        max(_safe_float(timeout_seconds, default=120), 30),
        120,
    )
    last_error = None
    last_reason = 'provider_failure'
    total_started_at = time.monotonic()
    for attempt_number in range(1, TABULAR_GENERATION_PLAN_DEFAULT_RETRY_ATTEMPTS + 1):
        chat_history = SKChatHistory()
        chat_history.add_system_message(
            'You plan stable tabular output schemas. Return only the requested compact JSON plan. '
            'Never answer rows or reproduce source values.'
        )
        if attempt_number > 1:
            chat_history.add_system_message(
                'The previous response was invalid. Return exactly the requested JSON shape with all '
                'explicitly requested output fields and no extra properties.'
            )
        chat_history.add_user_message(planner_prompt)
        execution_settings = AzureChatPromptExecutionSettings(
            service_id='tabular-generated-output-background'
        )
        try:
            attempt_started_at = time.monotonic()
            result = await asyncio.wait_for(
                chat_service.get_chat_message_contents(chat_history, execution_settings),
                timeout=bounded_timeout_seconds,
            )
            model_latency_seconds = time.monotonic() - attempt_started_at
            raw_response_content = result[0].content if result and result[0].content else ''
            planner_payload = _parse_generated_json_object(raw_response_content)
            plan = _build_tabular_generation_plan(
                run,
                planner_payload,
                input_contract,
                planner_model,
            )
            usage = _extract_tabular_response_usage(result)
            metrics = {
                'attempt_count': attempt_number,
                'latency_seconds': round(time.monotonic() - total_started_at, 3),
                'model_latency_seconds': round(model_latency_seconds, 3),
                'input_char_count': len(planner_prompt),
                'response_char_count': len(raw_response_content),
                'input_token_count': usage.get('input_token_count'),
                'output_token_count': usage.get('output_token_count'),
                'total_token_count': usage.get('total_token_count'),
            }
            return plan, metrics
        except asyncio.TimeoutError as exc:
            last_error = exc
            last_reason = 'timeout'
        except ValueError as exc:
            last_error = exc
            last_reason = 'invalid_response'
        except Exception as exc:
            last_error = exc
            last_reason = 'provider_failure'

        log_event(
            '[TABULAR_GENERATION_PLAN] Planner attempt failed',
            {
                'run_id': (run or {}).get('id'),
                'attempt_number': attempt_number,
                'failure_reason': last_reason,
                'exception_type': type(last_error).__name__ if last_error else None,
            },
            debug_only=True,
        )

    raise TabularGenerationPlanError(last_reason) from last_error


def _apply_active_tabular_generation_plan(run, plan):
    planned_output_schema = _get_tabular_generation_plan_output_schema(plan)
    current_output_schema = list((run or {}).get('output_schema') or [])
    if current_output_schema and current_output_schema != planned_output_schema:
        raise ValueError('Active generation plan schema does not match the persisted run schema')
    run['output_schema'] = planned_output_schema
    run['lineage_schema'] = _get_tabular_run_lineage_schema(run)
    run['public_output_schema'] = [
        str(output_field.get('name') or '').strip()
        for output_field in _get_tabular_generation_plan_llm_fields(plan)
    ]
    run['internal_checkpoint_schema'] = planned_output_schema


def _recover_tabular_generation_plan(run, input_contract, plan_blob_path, plan_mode):
    plan = _download_json_blob(plan_blob_path)
    _validate_tabular_generation_plan(
        plan,
        run,
        input_schema_hash=input_contract.get('input_schema_hash'),
    )
    persisted_plan_hash = str((run or {}).get('plan_hash') or '').strip()
    if persisted_plan_hash and persisted_plan_hash != plan.get('plan_hash'):
        raise ValueError('Stored generation plan hash does not match the run record')
    if plan_mode == 'active':
        _apply_active_tabular_generation_plan(run, plan)

    run.update({
        'plan_blob_path': plan_blob_path,
        'plan_hash': plan.get('plan_hash'),
        'plan_mode': plan_mode,
        'plan_status': 'ready',
        'plan_failure_reason': None,
        'planner_model': plan.get('model'),
        'planner_completed_at': plan.get('created_at'),
        'updated_at': _now_iso(),
        'last_heartbeat_at': _now_iso(),
    })
    return _replace_claimed_run(run), plan


def _mark_tabular_generation_plan_fallback(run, reason, attempt_count=0, latency_seconds=None):
    now = _now_iso()
    run.update({
        'plan_status': 'fallback',
        'plan_failure_reason': str(reason or 'provider_failure'),
        'planner_attempt_count': _safe_int(attempt_count, minimum=0),
        'planner_latency_seconds': latency_seconds,
        'planner_completed_at': now,
        'updated_at': now,
        'last_heartbeat_at': now,
    })
    persisted_run = _replace_claimed_run(run)
    log_event(
        '[TABULAR_GENERATION_PLAN] Planner fell back to LLM schema discovery',
        {
            'run_id': persisted_run.get('id'),
            'plan_mode': persisted_run.get('plan_mode'),
            'failure_reason': persisted_run.get('plan_failure_reason'),
            'attempt_count': persisted_run.get('planner_attempt_count'),
        },
        level=logging.WARNING,
    )
    return persisted_run


def _ensure_tabular_generation_plan(
    run,
    chat_service,
    input_batches,
    settings,
    batch_timeout_seconds,
):
    plan_mode = _get_tabular_generation_plan_mode(run)
    task_type = _normalize_tabular_run_task_type((run or {}).get('task_type'))
    if (
        task_type not in {TABULAR_RUN_TASK_STRUCTURED_EXPORT, TABULAR_RUN_TASK_COMBINED}
        or (run or {}).get('passthrough_input_rows')
        or chat_service is None
    ):
        if (run or {}).get('plan_status') not in {'ready', 'fallback', 'not_applicable'}:
            run.update({
                'plan_mode': 'off',
                'plan_status': 'not_applicable',
                'updated_at': _now_iso(),
            })
            return _replace_claimed_run(run)
        return run
    if plan_mode == 'off' and not ((run or {}).get('plan_blob_path') or (run or {}).get('plan_hash')):
        if (run or {}).get('plan_status') not in {'disabled', 'fallback'}:
            run.update({
                'plan_mode': 'off',
                'plan_status': 'disabled',
                'updated_at': _now_iso(),
            })
            return _replace_claimed_run(run)
        return run
    if plan_mode == 'shadow' and not ((run or {}).get('plan_blob_path') or (run or {}).get('plan_hash')):
        if (run or {}).get('plan_status') != 'deferred':
            now = _now_iso()
            run.update({
                'plan_mode': 'shadow',
                'plan_status': 'deferred',
                'plan_failure_reason': 'deferred_off_critical_path',
                'planner_attempt_count': 0,
                'planner_latency_seconds': 0,
                'planner_model_latency_seconds': 0,
                'planner_started_at': None,
                'planner_completed_at': None,
                'updated_at': now,
                'last_heartbeat_at': now,
                'last_message': 'Generating the initial schema checkpoint',
            })
            return _replace_claimed_run(run)
        return run

    sample_rows = _load_tabular_generation_plan_sample_rows(run, input_batches)
    input_contract = _build_tabular_generation_plan_input_contract(sample_rows)
    plan_blob_path = _tabular_generation_plan_blob_path(
        (run or {}).get('user_id'),
        (run or {}).get('conversation_id'),
        (run or {}).get('id'),
    )
    stored_plan_blob_path = str((run or {}).get('plan_blob_path') or '').strip()
    if stored_plan_blob_path and stored_plan_blob_path != plan_blob_path:
        raise ValueError('Stored generation plan path does not match the run identity')
    if _blob_exists(plan_blob_path):
        recovered_run, _ = _recover_tabular_generation_plan(
            run,
            input_contract,
            plan_blob_path,
            plan_mode,
        )
        return recovered_run
    if stored_plan_blob_path or (run or {}).get('plan_hash'):
        raise ValueError('Stored generation plan blob is missing')
    if (run or {}).get('plan_status') == 'fallback':
        return run
    if (run or {}).get('plan_status') == 'planning':
        return _mark_tabular_generation_plan_fallback(run, 'interrupted_before_persistence')

    planner_model = _resolve_tabular_generation_planner_model(run, settings)
    now = _now_iso()
    run.update({
        'plan_mode': plan_mode,
        'plan_status': 'planning',
        'plan_failure_reason': None,
        'planner_model': planner_model,
        'planner_started_at': now,
        'updated_at': now,
        'last_heartbeat_at': now,
    })
    run = _replace_claimed_run(run)
    try:
        plan, metrics = asyncio.run(_generate_tabular_generation_plan(
            chat_service,
            run,
            input_contract,
            planner_model,
            batch_timeout_seconds,
        ))
    except TabularGenerationPlanError as exc:
        return _mark_tabular_generation_plan_fallback(
            run,
            exc.reason,
            attempt_count=TABULAR_GENERATION_PLAN_DEFAULT_RETRY_ATTEMPTS,
        )
    except ValueError:
        return _mark_tabular_generation_plan_fallback(run, 'invalid_input')

    try:
        _upload_json_blob(
            plan_blob_path,
            plan,
            metadata={
                'run_id': run.get('id'),
                'conversation_id': run.get('conversation_id'),
                'generation_plan': 'true',
                'plan_hash': plan.get('plan_hash'),
                'source_etag': str((plan.get('source') or {}).get('blob_etag') or '').strip('"'),
                'contract_version': TABULAR_GENERATION_PLAN_VERSION,
            },
            overwrite=False,
        )
    except ResourceExistsError:
        recovered_run, _ = _recover_tabular_generation_plan(
            run,
            input_contract,
            plan_blob_path,
            plan_mode,
        )
        return recovered_run

    if plan_mode == 'active':
        _apply_active_tabular_generation_plan(run, plan)
    run.update({
        'plan_blob_path': plan_blob_path,
        'plan_hash': plan.get('plan_hash'),
        'plan_status': 'ready',
        'plan_failure_reason': None,
        'planner_attempt_count': metrics.get('attempt_count'),
        'planner_latency_seconds': metrics.get('latency_seconds'),
        'planner_model_latency_seconds': metrics.get('model_latency_seconds'),
        'planner_input_char_count': metrics.get('input_char_count'),
        'planner_response_char_count': metrics.get('response_char_count'),
        'planner_input_token_count': metrics.get('input_token_count'),
        'planner_output_token_count': metrics.get('output_token_count'),
        'planner_total_token_count': metrics.get('total_token_count'),
        'planner_completed_at': plan.get('created_at'),
        'updated_at': _now_iso(),
        'last_heartbeat_at': _now_iso(),
    })
    persisted_run = _replace_claimed_run(run)
    log_event(
        '[TABULAR_GENERATION_PLAN] Immutable generation plan ready',
        {
            'run_id': persisted_run.get('id'),
            'plan_mode': plan_mode,
            'plan_hash': persisted_run.get('plan_hash'),
            'planner_attempt_count': persisted_run.get('planner_attempt_count'),
            'planner_latency_seconds': persisted_run.get('planner_latency_seconds'),
            'planner_input_char_count': persisted_run.get('planner_input_char_count'),
            'planner_response_char_count': persisted_run.get('planner_response_char_count'),
            'planner_input_token_count': persisted_run.get('planner_input_token_count'),
            'planner_output_token_count': persisted_run.get('planner_output_token_count'),
            'planner_total_token_count': persisted_run.get('planner_total_token_count'),
        },
        level=logging.INFO,
    )
    return persisted_run


async def _generate_batch_entries(
    chat_service,
    user_question,
    batch_rows,
    batch_index,
    total_batches,
    source_file_name,
    selected_sheet,
    retry_attempts,
    run_id,
    expected_output_schema=None,
    batch_timeout_seconds=TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
    response_protocol=TABULAR_RESPONSE_PROTOCOL_OBJECT_V1,
    generation_plan=None,
):
    batch_number = batch_index + 1
    normalized_response_protocol = str(response_protocol or TABULAR_RESPONSE_PROTOCOL_OBJECT_V1).strip()
    compact_protocol = _is_compact_row_array_protocol(normalized_response_protocol)
    batch_prompt = _build_batch_prompt(
        user_question,
        batch_rows,
        batch_index,
        total_batches,
        source_file_name,
        selected_sheet=selected_sheet,
        output_schema=expected_output_schema,
        response_protocol=normalized_response_protocol,
        generation_plan=generation_plan,
    )

    parsed_entries = None
    raw_response_content = ''
    mismatch_count = 0
    last_validation_error = None
    last_attempt_metrics = {
        'input_char_count': len(batch_prompt),
        'response_char_count': 0,
        'model_latency_seconds': None,
        'validation_seconds': None,
        'input_token_count': None,
        'output_token_count': None,
        'total_token_count': None,
    }
    timeout_seconds = max(
        _safe_float(
            batch_timeout_seconds,
            default=TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
        ),
        0.001,
    )
    for attempt_number in range(1, retry_attempts + 1):
        chat_history = SKChatHistory()
        if compact_protocol:
            chat_history.add_system_message(
                'You transform tabular input rows into compact positional output. '
                'Return only one valid JSON object with p and rows. '
                'Never repeat field names, source tokens, markdown, explanation text, or omit rows.'
            )
        else:
            chat_history.add_system_message(
                'You transform tabular input rows into deterministic structured output. '
                'Return only a valid JSON array with one object per input row. '
                'Never add markdown, explanation text, or omit rows.'
            )
        if attempt_number > 1:
            if compact_protocol:
                chat_history.add_system_message(
                    f'The previous attempt did not return the required {len(batch_rows)} compact row array(s). '
                    'Retry now with the same p value and every expected row key exactly once.'
                )
            else:
                chat_history.add_system_message(
                    f'The previous attempt did not return the required {len(batch_rows)} JSON object(s). '
                    'Retry now and preserve the input row count exactly.'
                )
        chat_history.add_user_message(batch_prompt)

        execution_settings = AzureChatPromptExecutionSettings(service_id='tabular-generated-output-background')
        try:
            model_started_at = time.monotonic()
            result = await asyncio.wait_for(
                chat_service.get_chat_message_contents(chat_history, execution_settings),
                timeout=timeout_seconds,
            )
            model_latency_seconds = time.monotonic() - model_started_at
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f'Background structured export batch {batch_number}/{total_batches} '
                f'timed out after {timeout_seconds:g} seconds.'
            ) from exc
        raw_response_content = result[0].content if result and result[0].content else ''
        usage = _extract_tabular_response_usage(result)
        validation_started_at = time.monotonic()
        try:
            if compact_protocol and raw_response_content:
                parsed_entries = _parse_compact_row_array_entries(
                    raw_response_content,
                    batch_rows,
                    generation_plan,
                )
            else:
                parsed_entries = _parse_generated_json_entries(raw_response_content) if raw_response_content else None
        except ValueError as exc:
            parsed_entries = None
            last_validation_error = str(exc)
        parsed_entry_count = len(parsed_entries) if parsed_entries is not None else 0
        last_attempt_metrics = {
            'input_char_count': len(batch_prompt),
            'response_char_count': len(raw_response_content),
            'model_latency_seconds': round(model_latency_seconds, 3),
            'validation_seconds': None,
            'input_token_count': usage.get('input_token_count'),
            'output_token_count': usage.get('output_token_count'),
            'total_token_count': usage.get('total_token_count'),
        }
        if parsed_entries is not None and parsed_entry_count == len(batch_rows):
            try:
                normalized_entries, output_schema = _normalize_model_generated_batch_entries(
                    batch_rows,
                    parsed_entries,
                    expected_output_schema=expected_output_schema,
                    allow_source_token_recovery=not compact_protocol,
                    run_id=run_id,
                    batch_number=batch_number,
                )
                last_attempt_metrics['validation_seconds'] = round(
                    time.monotonic() - validation_started_at,
                    3,
                )
                return normalized_entries, mismatch_count, output_schema, last_attempt_metrics
            except ValueError as exc:
                last_validation_error = str(exc)
        last_attempt_metrics['validation_seconds'] = round(time.monotonic() - validation_started_at, 3)

        mismatch_count += 1
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Background export batch attempt mismatch',
            {
                'event_name': 'batch_validated',
                'run_id': run_id,
                'batch_number': batch_number,
                'batch_count': total_batches,
                'attempt_number': attempt_number,
                'expected_row_count': len(batch_rows),
                'parsed_row_count': parsed_entry_count,
                'validation_error': last_validation_error,
                'response_char_count': len(raw_response_content),
                'model_latency_seconds': last_attempt_metrics.get('model_latency_seconds'),
                'validation_seconds': last_attempt_metrics.get('validation_seconds'),
                'input_token_count': last_attempt_metrics.get('input_token_count'),
                'output_token_count': last_attempt_metrics.get('output_token_count'),
                'total_token_count': last_attempt_metrics.get('total_token_count'),
                'response_protocol_version': normalized_response_protocol,
            },
            debug_only=True,
        )

    failure_detail = last_validation_error or (
        f'returned {len(parsed_entries) if parsed_entries is not None else 0} object(s) '
        f'for {len(batch_rows)} input row(s)'
    )
    raise ValueError(
        f'Background structured export batch {batch_number}/{total_batches} failed validation: {failure_detail}.'
    )


async def _generate_batch_entries_for_window(
    semaphore,
    chat_service,
    user_question,
    batch_request,
    total_batches,
    source_file_name,
    selected_sheet,
    retry_attempts,
    run_id,
    expected_output_schema,
    batch_timeout_seconds,
    response_protocol,
    generation_plan,
):
    queued_at = time.monotonic()
    async with semaphore:
        queue_wait_seconds = time.monotonic() - queued_at
        batch_started_at = time.monotonic()
        batch_entries, mismatch_count, output_schema, attempt_metrics = await _generate_batch_entries(
            chat_service,
            user_question,
            batch_request['rows'],
            batch_request['batch_number'] - 1,
            total_batches,
            source_file_name,
            selected_sheet,
            retry_attempts,
            run_id,
            expected_output_schema=expected_output_schema,
            batch_timeout_seconds=batch_timeout_seconds,
            response_protocol=response_protocol,
            generation_plan=generation_plan,
        )
        elapsed_seconds = time.monotonic() - batch_started_at
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Background export batch model completed',
            {
                'event_name': 'batch_model_completed',
                'run_id': run_id,
                'batch_number': batch_request['batch_number'],
                'batch_count': total_batches,
                'row_count': len(batch_entries),
                'queue_wait_seconds': round(queue_wait_seconds, 3),
                'elapsed_seconds': round(elapsed_seconds, 3),
                'model_latency_seconds': attempt_metrics.get('model_latency_seconds'),
                'validation_seconds': attempt_metrics.get('validation_seconds'),
                'input_char_count': attempt_metrics.get('input_char_count'),
                'response_char_count': attempt_metrics.get('response_char_count'),
                'input_token_count': attempt_metrics.get('input_token_count'),
                'output_token_count': attempt_metrics.get('output_token_count'),
                'total_token_count': attempt_metrics.get('total_token_count'),
                'mismatch_count': mismatch_count,
            },
            debug_only=True,
        )
        return {
            'batch_number': batch_request['batch_number'],
            'batch_entries': batch_entries,
            'batch_summary': _build_generated_batch_summary(batch_entries),
            'batch_row_count': len(batch_entries),
            'elapsed_seconds': elapsed_seconds,
            'queue_wait_seconds': queue_wait_seconds,
            'model_latency_seconds': attempt_metrics.get('model_latency_seconds'),
            'validation_seconds': attempt_metrics.get('validation_seconds'),
            'input_char_count': attempt_metrics.get('input_char_count'),
            'response_char_count': attempt_metrics.get('response_char_count'),
            'input_token_count': attempt_metrics.get('input_token_count'),
            'output_token_count': attempt_metrics.get('output_token_count'),
            'total_token_count': attempt_metrics.get('total_token_count'),
            'mismatch_count': mismatch_count,
            'output_schema': output_schema,
        }


async def _generate_batch_window_entries(
    chat_service,
    user_question,
    batch_requests,
    total_batches,
    source_file_name,
    selected_sheet,
    retry_attempts,
    run_id,
    batch_concurrency,
    expected_output_schema=None,
    batch_timeout_seconds=TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
    response_protocol=TABULAR_RESPONSE_PROTOCOL_OBJECT_V1,
    generation_plan=None,
):
    semaphore = asyncio.Semaphore(max(1, batch_concurrency))
    tasks = [
        _generate_batch_entries_for_window(
            semaphore,
            chat_service,
            user_question,
            batch_request,
            total_batches,
            source_file_name,
            selected_sheet,
            retry_attempts,
            run_id,
            expected_output_schema,
            batch_timeout_seconds,
            response_protocol,
            generation_plan,
        )
        for batch_request in batch_requests
    ]
    gathered_results = await asyncio.gather(*tasks, return_exceptions=True)
    successful_results = []
    first_error = None
    for gathered_result in gathered_results:
        if isinstance(gathered_result, Exception):
            if first_error is None:
                first_error = gathered_result
            continue
        successful_results.append(gathered_result)
    return successful_results, first_error


def _is_completion_driven_checkpointing_enabled(settings, run=None):
    rollout_settings = _get_tabular_generation_rollout_settings_for_run(run, settings)
    return bool(rollout_settings.get('enable_tabular_completion_driven_checkpointing'))


def _is_rolling_worker_pool_enabled(settings, run=None):
    rollout_settings = _get_tabular_generation_rollout_settings_for_run(run, settings)
    return bool(rollout_settings.get('enable_tabular_rolling_worker_pool'))


def _get_checkpoint_writer_concurrency(settings, run=None):
    rollout_settings = _get_tabular_generation_rollout_settings_for_run(run, settings)
    return _safe_int(
        rollout_settings.get('tabular_generation_checkpoint_writer_concurrency'),
        default=TABULAR_GENERATION_DEFAULT_CHECKPOINT_WRITER_CONCURRENCY,
        minimum=1,
        maximum=16,
    )


def _get_tabular_generation_heartbeat_seconds(settings, run=None):
    rollout_settings = _get_tabular_generation_rollout_settings_for_run(run, settings)
    return _safe_int(
        rollout_settings.get('tabular_generation_heartbeat_seconds'),
        default=TABULAR_GENERATION_DEFAULT_HEARTBEAT_SECONDS,
        minimum=5,
        maximum=300,
    )


def _is_independent_batch_retries_enabled(settings, run=None):
    rollout_settings = _get_tabular_generation_rollout_settings_for_run(run, settings)
    return bool(rollout_settings.get('enable_tabular_independent_batch_retries'))


async def _checkpoint_generated_result_async(run, generated_result, writer_semaphore):
    async with writer_semaphore:
        checkpoint_results = await asyncio.to_thread(
            _checkpoint_generated_batch_results,
            run,
            [generated_result],
        )
    return checkpoint_results


async def _generate_and_checkpoint_batch_window_entries(
    run,
    chat_service,
    user_question,
    batch_requests,
    total_batches,
    source_file_name,
    selected_sheet,
    retry_attempts,
    run_id,
    batch_concurrency,
    checkpoint_writer_concurrency,
    expected_output_schema=None,
    batch_timeout_seconds=TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
    response_protocol=TABULAR_RESPONSE_PROTOCOL_OBJECT_V1,
    generation_plan=None,
):
    semaphore = asyncio.Semaphore(max(1, batch_concurrency))
    writer_semaphore = asyncio.Semaphore(max(1, checkpoint_writer_concurrency))
    tasks = [
        asyncio.create_task(
            _generate_batch_entries_for_window(
                semaphore,
                chat_service,
                user_question,
                batch_request,
                total_batches,
                source_file_name,
                selected_sheet,
                retry_attempts,
                run_id,
                expected_output_schema,
                batch_timeout_seconds,
                response_protocol,
                generation_plan,
            )
        )
        for batch_request in batch_requests
    ]
    batch_results = {}
    first_error = None
    checkpoint_tasks = set()
    checkpoint_high_water_mark = max(1, checkpoint_writer_concurrency) * 2

    def collect_checkpoint_results(completed_checkpoint_tasks):
        nonlocal first_error
        for checkpointed_task in completed_checkpoint_tasks:
            try:
                checkpointed_result = checkpointed_task.result()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                continue
            batch_results.update(checkpointed_result)

    for completed_task in asyncio.as_completed(tasks):
        try:
            generated_result = await completed_task
        except Exception as exc:
            if first_error is None:
                first_error = exc
            continue
        checkpoint_task = asyncio.create_task(
            _checkpoint_generated_result_async(run, generated_result, writer_semaphore)
        )
        checkpoint_tasks.add(checkpoint_task)
        if len(checkpoint_tasks) >= checkpoint_high_water_mark:
            completed_checkpoint_tasks, checkpoint_tasks = await asyncio.wait(
                checkpoint_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            collect_checkpoint_results(completed_checkpoint_tasks)

    if checkpoint_tasks:
        completed_checkpoint_tasks, _ = await asyncio.wait(checkpoint_tasks)
        collect_checkpoint_results(completed_checkpoint_tasks)
    return batch_results, first_error


async def _rolling_pool_heartbeat_loop(run, counts, state_lock, stop_event, heartbeat_seconds):
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=heartbeat_seconds)
            return
        except asyncio.TimeoutError:
            pass

        async with state_lock:
            await asyncio.to_thread(_raise_if_tabular_export_canceled, run)
            now = _now_iso()
            run.update({
                'updated_at': now,
                'last_heartbeat_at': now,
                'active_batch_count': _safe_int(counts.get('active')),
                'pending_batch_count': _safe_int(counts.get('pending')),
                'checkpointing_batch_count': _safe_int(counts.get('checkpointing')),
                'retry_wait_batch_count': _safe_int(counts.get('retry_wait')),
                'last_message': (
                    f"Rolling structured export active: {_safe_int(run.get('completed_batches'))} "
                    f"of {_safe_int(run.get('batch_count'))} batch(es) durable"
                ),
            })
            persisted_run = await asyncio.to_thread(_replace_claimed_run, run)
            run.clear()
            run.update(persisted_run)


async def _generate_and_checkpoint_rolling_pool_entries(
    run,
    chat_service,
    input_batches,
    user_question,
    total_batches,
    source_file_name,
    selected_sheet,
    retry_attempts,
    run_id,
    user_id,
    batch_concurrency,
    checkpoint_writer_concurrency,
    heartbeat_seconds,
    independent_batch_retries_enabled=False,
    last_logged_at=0.0,
    batch_timeout_seconds=TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
    response_protocol=TABULAR_RESPONSE_PROTOCOL_OBJECT_V1,
    generation_plan=None,
):
    model_semaphore = asyncio.Semaphore(max(1, batch_concurrency))
    writer_semaphore = asyncio.Semaphore(max(1, checkpoint_writer_concurrency))
    checkpoint_high_water_mark = max(
        1,
        checkpoint_writer_concurrency * TABULAR_GENERATION_CHECKPOINT_HIGH_WATER_MULTIPLIER,
    )
    completed_batches = _safe_int(run.get('completed_batches'))
    processed_rows = _safe_int(run.get('processed_rows'))
    durable_output_batches = _scan_output_checkpoint_batches_for_run(run)
    retry_records = {}
    if independent_batch_retries_enabled:
        retry_records = _load_tabular_batch_retry_records_for_run(run, durable_output_batches)
    retry_batch_numbers = {
        batch_number
        for batch_number, retry_record in retry_records.items()
        if not bool((retry_record or {}).get('exhausted'))
    }
    exhausted_batch_numbers = {
        batch_number
        for batch_number, retry_record in retry_records.items()
        if bool((retry_record or {}).get('exhausted'))
    }
    pending_batch_numbers = deque(
        batch_number
        for batch_number in range(completed_batches + 1, total_batches + 1)
        if batch_number not in retry_batch_numbers and batch_number not in exhausted_batch_numbers
    )
    retry_heap = [
        _tabular_batch_retry_heap_item(retry_record)
        for retry_record in retry_records.values()
        if not bool((retry_record or {}).get('exhausted'))
    ]
    heapq.heapify(retry_heap)
    active_tasks = {}
    active_batch_requests = {}
    checkpoint_tasks = set()
    checkpoint_task_contexts = {}
    batch_results = {}
    counts = {
        'active': 0,
        'pending': len(pending_batch_numbers),
        'checkpointing': 0,
        'retry_wait': len(retry_heap),
    }
    state_lock = asyncio.Lock()
    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _rolling_pool_heartbeat_loop(
            run,
            counts,
            state_lock,
            stop_heartbeat,
            heartbeat_seconds,
        )
    )
    first_error = None
    recent_failure_signatures = deque(maxlen=max(3, min(total_batches, max(1, batch_concurrency))))
    circuit_threshold = _safe_float(
        _get_tabular_generation_rollout_settings_for_run(run, {}).get('tabular_generation_systemic_failure_threshold'),
        default=TABULAR_GENERATION_DEFAULT_SYSTEMIC_FAILURE_THRESHOLD,
    )
    circuit_failure_floor = max(
        3,
        math.ceil(max(1, recent_failure_signatures.maxlen) * max(0.1, circuit_threshold)),
    )

    def refresh_counts():
        counts.update({
            'active': len(active_tasks),
            'pending': len(pending_batch_numbers),
            'checkpointing': len(checkpoint_tasks),
            'retry_wait': len(retry_heap),
        })

    async def advance_durable_progress():
        nonlocal completed_batches, processed_rows, run, last_logged_at
        if (completed_batches + 1) not in batch_results:
            return False
        previous_completed_batches = completed_batches
        async with state_lock:
            run, completed_batches, processed_rows = await asyncio.to_thread(
                _advance_run_progress_for_window,
                run,
                batch_results,
                completed_batches,
                processed_rows,
                completed_batches + 1,
                total_batches,
            )
        refresh_counts()
        last_logged_at = _log_progress_if_due(run, last_logged_at)
        return completed_batches > previous_completed_batches

    def peek_due_retry_batch_number():
        while retry_heap:
            _, batch_number = retry_heap[0]
            retry_record = retry_records.get(batch_number)
            if not retry_record or retry_record.get('exhausted'):
                heapq.heappop(retry_heap)
                continue
            if batch_number in durable_output_batches:
                heapq.heappop(retry_heap)
                retry_records.pop(batch_number, None)
                _delete_tabular_batch_retry_record(run, batch_number)
                continue
            if not _is_tabular_batch_retry_due(retry_record):
                return None
            return batch_number
        return None

    def pop_due_retry_batch_number():
        batch_number = peek_due_retry_batch_number()
        if batch_number is None:
            return None
        heapq.heappop(retry_heap)
        return batch_number

    def seconds_until_next_retry():
        while retry_heap:
            _, batch_number = retry_heap[0]
            retry_record = retry_records.get(batch_number)
            if retry_record and not retry_record.get('exhausted'):
                return max(0.0, _safe_float(_seconds_until(retry_record.get('next_attempt_at'))))
            heapq.heappop(retry_heap)
        return None

    def has_dispatchable_work():
        return bool(pending_batch_numbers) or peek_due_retry_batch_number() is not None

    def record_batch_retry(batch_number, batch_request, exc, failure_category=None):
        nonlocal first_error
        retry_record = _build_tabular_batch_retry_record(
            run,
            batch_number,
            batch_request,
            exc,
            existing_record=retry_records.get(batch_number),
            max_attempts=retry_attempts,
            failure_category=failure_category,
        )
        retry_records[batch_number] = retry_record
        _persist_tabular_batch_retry_record(run, retry_record)
        if not retry_record.get('exhausted'):
            heapq.heappush(retry_heap, _tabular_batch_retry_heap_item(retry_record))
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Rolling pool recorded batch retry',
            {
                'event_name': 'rolling_batch_retry_recorded',
                'run_id': run_id,
                'batch_number': batch_number,
                'failure_category': retry_record.get('failure_category'),
                'safe_error_code': retry_record.get('safe_error_code'),
                'attempt_count': retry_record.get('attempt_count'),
                'max_attempts': retry_record.get('max_attempts'),
                'next_attempt_at': retry_record.get('next_attempt_at'),
                'exhausted': bool(retry_record.get('exhausted')),
            },
            level=logging.WARNING,
        )
        if retry_record.get('failure_category') not in {'model_validation', 'plan_or_schema_systemic'}:
            return
        failure_signature = ':'.join([
            str(retry_record.get('failure_category') or 'unknown'),
            str(retry_record.get('safe_error_code') or 'error'),
            str(retry_record.get('plan_hash') or '')[:12],
        ])
        recent_failure_signatures.append(failure_signature)
        signature_count = Counter(recent_failure_signatures).get(failure_signature, 0)
        if first_error is None and signature_count >= circuit_failure_floor:
            now = _now_iso()
            run.update({
                'systemic_failure_circuit_open': True,
                'systemic_failure_category': retry_record.get('failure_category'),
                'systemic_failure_signature': failure_signature,
                'systemic_failure_opened_at': now,
                'last_retry_category': retry_record.get('failure_category'),
                'last_message': 'Systemic tabular generation failure circuit breaker opened',
            })
            first_error = RuntimeError('Systemic tabular batch failure circuit breaker opened')

    def build_pending_batch_task(batch_number):
        existing_results, batch_requests = _build_batch_window(
            run,
            input_batches,
            user_id,
            run_id,
            batch_number,
            batch_number,
            total_batches,
            durable_output_batches=durable_output_batches,
        )
        if existing_results:
            batch_results.update(existing_results)
            return None
        if not batch_requests:
            return None
        batch_request = batch_requests[0]
        model_task = asyncio.create_task(
            _generate_batch_entries_for_window(
                model_semaphore,
                chat_service,
                user_question,
                batch_request,
                total_batches,
                source_file_name,
                selected_sheet,
                retry_attempts,
                run_id,
                run.get('output_schema'),
                batch_timeout_seconds,
                response_protocol,
                generation_plan,
            )
        )
        active_batch_requests[model_task] = batch_request
        return model_task

    try:
        while pending_batch_numbers or retry_heap or active_tasks or checkpoint_tasks:
            await asyncio.to_thread(_raise_if_tabular_export_canceled, run)
            if heartbeat_task.done() and not stop_heartbeat.is_set():
                heartbeat_task.result()
            if first_error and not active_tasks and not checkpoint_tasks:
                break

            while (
                not first_error
                and len(active_tasks) < max(1, batch_concurrency)
                and len(checkpoint_tasks) < checkpoint_high_water_mark
                and has_dispatchable_work()
            ):
                batch_number = pop_due_retry_batch_number()
                if batch_number is None:
                    batch_number = pending_batch_numbers.popleft()
                model_task = build_pending_batch_task(batch_number)
                if model_task is not None:
                    active_tasks[model_task] = batch_number
                await advance_durable_progress()
                refresh_counts()

            await advance_durable_progress()
            refresh_counts()
            wait_tasks = set(active_tasks) | checkpoint_tasks
            if wait_tasks and not heartbeat_task.done():
                wait_tasks.add(heartbeat_task)
            if not wait_tasks:
                retry_wait_seconds = seconds_until_next_retry()
                if retry_wait_seconds is not None and not heartbeat_task.done():
                    await asyncio.wait({heartbeat_task}, timeout=retry_wait_seconds)
                continue

            completed_tasks, _ = await asyncio.wait(
                wait_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for completed_task in completed_tasks:
                if completed_task is heartbeat_task:
                    completed_task.result()
                    continue
                if completed_task in active_tasks:
                    batch_number = active_tasks.pop(completed_task)
                    batch_request = active_batch_requests.pop(completed_task, None)
                    try:
                        generated_result = completed_task.result()
                    except Exception as exc:
                        if independent_batch_retries_enabled:
                            record_batch_retry(batch_number, batch_request, exc)
                        elif first_error is None:
                            first_error = exc
                        continue
                    checkpoint_task = asyncio.create_task(
                        _checkpoint_generated_result_async(run, generated_result, writer_semaphore)
                    )
                    checkpoint_tasks.add(checkpoint_task)
                    checkpoint_task_contexts[checkpoint_task] = (batch_number, batch_request)
                    log_event(
                        '[TABULAR_GENERATED_OUTPUT] Rolling pool scheduled checkpoint',
                        {
                            'event_name': 'rolling_checkpoint_scheduled',
                            'run_id': run_id,
                            'batch_number': batch_number,
                            'active_batch_count': len(active_tasks),
                            'pending_batch_count': len(pending_batch_numbers),
                            'checkpointing_batch_count': len(checkpoint_tasks),
                            'batch_concurrency': batch_concurrency,
                            'checkpoint_high_water_mark': checkpoint_high_water_mark,
                        },
                        debug_only=True,
                    )
                    continue
                if completed_task in checkpoint_tasks:
                    checkpoint_tasks.remove(completed_task)
                    checkpoint_batch_number, checkpoint_batch_request = checkpoint_task_contexts.pop(
                        completed_task,
                        (None, None),
                    )
                    try:
                        checkpointed_results = completed_task.result()
                    except Exception as exc:
                        if independent_batch_retries_enabled and checkpoint_batch_number:
                            record_batch_retry(
                                checkpoint_batch_number,
                                checkpoint_batch_request,
                                exc,
                                failure_category='checkpoint_storage',
                            )
                        elif first_error is None:
                            first_error = exc
                        continue
                    batch_results.update(checkpointed_results)
                    durable_output_batches.update(checkpointed_results)
                    if independent_batch_retries_enabled:
                        for checkpointed_batch_number in checkpointed_results:
                            retry_records.pop(checkpointed_batch_number, None)
                            _delete_tabular_batch_retry_record(run, checkpointed_batch_number)
                    await advance_durable_progress()
            refresh_counts()

        if first_error:
            run.update({
                'active_batch_count': 0,
                'pending_batch_count': len(pending_batch_numbers),
                'checkpointing_batch_count': 0,
                'retry_wait_batch_count': len(retry_heap),
                'exhausted_batch_count': sum(
                    1
                    for retry_record in retry_records.values()
                    if bool((retry_record or {}).get('exhausted'))
                ),
            })
            raise first_error
        exhausted_batch_count = sum(
            1
            for retry_record in retry_records.values()
            if bool((retry_record or {}).get('exhausted'))
        )
        if exhausted_batch_count:
            run.update({
                'active_batch_count': 0,
                'pending_batch_count': len(pending_batch_numbers),
                'checkpointing_batch_count': 0,
                'retry_wait_batch_count': len(retry_heap),
                'exhausted_batch_count': exhausted_batch_count,
                'last_retry_category': 'batch_exhausted',
                'last_message': 'Background structured export needs manual intervention for exhausted batches',
            })
            raise RuntimeError('One or more tabular generated-output batches exhausted independent retries')
        if completed_batches < total_batches:
            raise RuntimeError(
                f'Rolling worker pool stopped at batch {completed_batches} of {total_batches}'
            )
        run.update({
            'active_batch_count': 0,
            'pending_batch_count': 0,
            'checkpointing_batch_count': 0,
            'retry_wait_batch_count': 0,
            'exhausted_batch_count': 0,
            'systemic_failure_circuit_open': False,
            'systemic_failure_category': None,
            'systemic_failure_signature': None,
            'systemic_failure_opened_at': None,
        })
        return run, completed_batches, processed_rows, last_logged_at
    finally:
        stop_heartbeat.set()
        if not heartbeat_task.done():
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        for model_task in active_tasks:
            model_task.cancel()
            active_batch_requests.pop(model_task, None)
        if active_tasks:
            await asyncio.gather(*active_tasks, return_exceptions=True)
        if checkpoint_tasks:
            await asyncio.gather(*checkpoint_tasks, return_exceptions=True)


async def _generate_analysis_chunk_summary(
    chat_service,
    run,
    batch_request,
    total_batches,
    retry_attempts,
    batch_timeout_seconds,
):
    batch_number = batch_request['batch_number']
    batch_rows = batch_request['rows']
    timeout_seconds = max(
        _safe_float(
            batch_timeout_seconds,
            default=TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
        ),
        0.001,
    )
    raw_response_content = ''
    for attempt_number in range(1, retry_attempts + 1):
        chat_history = SKChatHistory()
        chat_history.add_system_message(
            'You analyze bounded tabular data chunks and return compact, evidence-preserving JSON summaries. '
            'Return only one valid JSON object. Never include markdown or unbounded row dumps.'
        )
        if attempt_number > 1:
            chat_history.add_system_message(
                'The previous attempt was not a valid compact JSON analysis summary. Retry with exactly one JSON object.'
            )
        chat_history.add_user_message(_build_analysis_chunk_prompt(run, batch_rows, batch_number, total_batches))

        execution_settings = AzureChatPromptExecutionSettings(service_id='tabular-generated-output-background')
        try:
            result = await asyncio.wait_for(
                chat_service.get_chat_message_contents(chat_history, execution_settings),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f'Background tabular analysis chunk {batch_number}/{total_batches} '
                f'timed out after {timeout_seconds:g} seconds.'
            ) from exc
        raw_response_content = result[0].content if result and result[0].content else ''
        parsed_summary = _parse_generated_json_object(raw_response_content) if raw_response_content else None
        if parsed_summary is not None:
            return _normalize_analysis_summary_payload(
                parsed_summary,
                source_rows=batch_rows,
                chunk_number=batch_number,
            )
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Background analysis chunk attempt mismatch',
            {
                'event_name': 'batch_validated',
                'run_id': run.get('id'),
                'batch_number': batch_number,
                'batch_count': total_batches,
                'attempt_number': attempt_number,
                'row_count': len(batch_rows),
                'response_char_count': len(raw_response_content),
            },
            debug_only=True,
        )

    raise ValueError(
        f'Background tabular analysis chunk {batch_number}/{total_batches} failed validation.'
    )


async def _generate_analysis_chunk_summary_for_window(
    semaphore,
    chat_service,
    run,
    batch_request,
    total_batches,
    retry_attempts,
    batch_timeout_seconds,
):
    async with semaphore:
        batch_started_at = time.monotonic()
        analysis_summary = await _generate_analysis_chunk_summary(
            chat_service,
            run,
            batch_request,
            total_batches,
            retry_attempts,
            batch_timeout_seconds,
        )
        return {
            'batch_number': batch_request['batch_number'],
            'analysis_summary': analysis_summary,
            'batch_row_count': _safe_int(analysis_summary.get('row_count')),
            'elapsed_seconds': time.monotonic() - batch_started_at,
            'mismatch_count': 0,
        }


async def _generate_analysis_chunk_summary_window(
    chat_service,
    run,
    batch_requests,
    total_batches,
    retry_attempts,
    batch_concurrency,
    batch_timeout_seconds,
):
    semaphore = asyncio.Semaphore(max(1, batch_concurrency))
    tasks = [
        _generate_analysis_chunk_summary_for_window(
            semaphore,
            chat_service,
            run,
            batch_request,
            total_batches,
            retry_attempts,
            batch_timeout_seconds,
        )
        for batch_request in batch_requests
    ]
    gathered_results = await asyncio.gather(*tasks, return_exceptions=True)
    successful_results = []
    first_error = None
    for gathered_result in gathered_results:
        if isinstance(gathered_result, Exception):
            if first_error is None:
                first_error = gathered_result
            continue
        successful_results.append(gathered_result)
    return successful_results, first_error


async def _generate_combined_chunk_result(
    chat_service,
    run,
    batch_request,
    total_batches,
    retry_attempts,
    batch_timeout_seconds,
    expected_output_schema=None,
):
    batch_number = batch_request['batch_number']
    batch_rows = batch_request['rows']
    timeout_seconds = max(
        _safe_float(
            batch_timeout_seconds,
            default=TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
        ),
        0.001,
    )
    raw_response_content = ''
    mismatch_count = 0
    last_validation_error = None
    for attempt_number in range(1, retry_attempts + 1):
        chat_history = SKChatHistory()
        chat_history.add_system_message(
            'You transform bounded tabular chunks into structured rows and compact analysis summaries. '
            'Return only one valid JSON object with structured_rows and analysis_summary. '
            'Never add markdown, explanation text, omit rows, or dump unbounded data.'
        )
        if attempt_number > 1:
            chat_history.add_system_message(
                f'The previous attempt did not return valid combined output for exactly {len(batch_rows)} row(s). '
                'Retry now with one JSON object containing structured_rows and analysis_summary.'
            )
        chat_history.add_user_message(
            _build_combined_chunk_prompt(
                run,
                batch_rows,
                batch_number,
                total_batches,
                output_schema=expected_output_schema,
            )
        )

        execution_settings = AzureChatPromptExecutionSettings(service_id='tabular-generated-output-background')
        try:
            result = await asyncio.wait_for(
                chat_service.get_chat_message_contents(chat_history, execution_settings),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f'Background combined tabular chunk {batch_number}/{total_batches} '
                f'timed out after {timeout_seconds:g} seconds.'
            ) from exc
        raw_response_content = result[0].content if result and result[0].content else ''
        parsed_payload = _parse_generated_json_object(raw_response_content) if raw_response_content else None
        if parsed_payload is not None:
            try:
                normalized_entries, output_schema, analysis_summary = _normalize_combined_chunk_payload(
                    run,
                    parsed_payload,
                    batch_rows,
                    batch_number,
                    expected_output_schema=expected_output_schema,
                )
                return normalized_entries, output_schema, analysis_summary, mismatch_count
            except ValueError as exc:
                last_validation_error = str(exc)

        mismatch_count += 1
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Background combined chunk attempt mismatch',
            {
                'event_name': 'batch_validated',
                'run_id': run.get('id'),
                'batch_number': batch_number,
                'batch_count': total_batches,
                'attempt_number': attempt_number,
                'expected_row_count': len(batch_rows),
                'validation_error': last_validation_error,
                'response_char_count': len(raw_response_content),
            },
            debug_only=True,
        )

    failure_detail = last_validation_error or 'response did not contain valid structured_rows and analysis_summary'
    raise ValueError(
        f'Background combined tabular chunk {batch_number}/{total_batches} failed validation: {failure_detail}.'
    )


async def _generate_combined_chunk_result_for_window(
    semaphore,
    chat_service,
    run,
    batch_request,
    total_batches,
    retry_attempts,
    batch_timeout_seconds,
    expected_output_schema,
):
    async with semaphore:
        batch_started_at = time.monotonic()
        batch_entries, output_schema, analysis_summary, mismatch_count = await _generate_combined_chunk_result(
            chat_service,
            run,
            batch_request,
            total_batches,
            retry_attempts,
            batch_timeout_seconds,
            expected_output_schema=expected_output_schema,
        )
        return {
            'batch_number': batch_request['batch_number'],
            'batch_entries': batch_entries,
            'batch_summary': _build_generated_batch_summary(batch_entries),
            'analysis_summary': analysis_summary,
            'batch_row_count': len(batch_entries),
            'elapsed_seconds': time.monotonic() - batch_started_at,
            'mismatch_count': mismatch_count,
            'output_schema': output_schema,
        }


async def _generate_combined_chunk_result_window(
    chat_service,
    run,
    batch_requests,
    total_batches,
    retry_attempts,
    batch_concurrency,
    batch_timeout_seconds,
    expected_output_schema=None,
):
    semaphore = asyncio.Semaphore(max(1, batch_concurrency))
    tasks = [
        _generate_combined_chunk_result_for_window(
            semaphore,
            chat_service,
            run,
            batch_request,
            total_batches,
            retry_attempts,
            batch_timeout_seconds,
            expected_output_schema,
        )
        for batch_request in batch_requests
    ]
    gathered_results = await asyncio.gather(*tasks, return_exceptions=True)
    successful_results = []
    first_error = None
    for gathered_result in gathered_results:
        if isinstance(gathered_result, Exception):
            if first_error is None:
                first_error = gathered_result
            continue
        successful_results.append(gathered_result)
    return successful_results, first_error


async def _generate_analysis_reduce_summary(
    chat_service,
    run,
    summaries,
    level_number,
    node_number,
    node_count,
    retry_attempts,
    batch_timeout_seconds,
):
    timeout_seconds = max(
        _safe_float(
            batch_timeout_seconds,
            default=TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
        ),
        0.001,
    )
    raw_response_content = ''
    for attempt_number in range(1, retry_attempts + 1):
        chat_history = SKChatHistory()
        chat_history.add_system_message(
            'You recursively reduce bounded tabular analysis summaries. '
            'Return only one compact JSON object and preserve cited source row references.'
        )
        if attempt_number > 1:
            chat_history.add_system_message(
                'The previous reduce attempt was not a valid JSON object. Retry with exactly one JSON object.'
            )
        chat_history.add_user_message(
            _build_analysis_reduce_prompt(run, summaries, level_number, node_number, node_count)
        )

        execution_settings = AzureChatPromptExecutionSettings(service_id='tabular-generated-output-background')
        try:
            result = await asyncio.wait_for(
                chat_service.get_chat_message_contents(chat_history, execution_settings),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f'Background tabular analysis reduce level {level_number} node {node_number}/{node_count} '
                f'timed out after {timeout_seconds:g} seconds.'
            ) from exc
        raw_response_content = result[0].content if result and result[0].content else ''
        parsed_summary = _parse_generated_json_object(raw_response_content) if raw_response_content else None
        if parsed_summary is not None:
            return _normalize_analysis_summary_payload(
                parsed_summary,
                child_summaries=summaries,
                reduce_level=level_number,
                reduce_node=node_number,
            )
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Background analysis reduce attempt mismatch',
            {
                'event_name': 'batch_validated',
                'run_id': run.get('id'),
                'level_number': level_number,
                'node_number': node_number,
                'node_count': node_count,
                'attempt_number': attempt_number,
                'input_summary_count': len(summaries),
                'response_char_count': len(raw_response_content),
            },
            debug_only=True,
        )

    raise ValueError(
        f'Background tabular analysis reduce level {level_number} node {node_number}/{node_count} failed validation.'
    )


def should_queue_tabular_generated_output_background(row_count, batch_count, settings=None):
    """Return True when a structured generated export should run durably in the background."""
    settings = settings or {}
    if not _settings_bool(settings, 'enable_tabular_generated_output_background_exports', True):
        return False

    inline_max_rows = _settings_int(
        settings,
        'tabular_generated_output_inline_max_rows',
        TABULAR_EXPORT_DEFAULT_INLINE_MAX_ROWS,
        minimum=1,
    )
    inline_max_batches = _settings_int(
        settings,
        'tabular_generated_output_inline_max_batches',
        TABULAR_EXPORT_DEFAULT_INLINE_MAX_BATCHES,
        minimum=1,
    )
    return _safe_int(row_count) > inline_max_rows or _safe_int(batch_count) > inline_max_batches


def build_tabular_generated_output_row_batches(rows, settings=None):
    """Split structured rows using the shared generated-export size budget."""
    settings = settings or {}
    max_batch_rows = _settings_int(
        settings,
        'tabular_generated_output_max_batch_rows',
        TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_ROWS,
        minimum=1,
        maximum=100,
    )
    max_batch_chars = _settings_int(
        settings,
        'tabular_generated_output_max_batch_chars',
        TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_CHARS,
        minimum=6000,
        maximum=120000,
    )
    batches = []
    current_batch = []
    current_batch_chars = 0

    for row in rows or []:
        row_text = json.dumps(row, default=str, ensure_ascii=False, separators=(',', ':'))
        if current_batch and (
            len(current_batch) >= max_batch_rows
            or current_batch_chars + len(row_text) > max_batch_chars
        ):
            batches.append(current_batch)
            current_batch = []
            current_batch_chars = 0

        current_batch.append(row)
        current_batch_chars += len(row_text)

    if current_batch:
        batches.append(current_batch)

    return batches


def _parse_iso_datetime(value):
    normalized_value = str(value or '').strip()
    if not normalized_value:
        return None
    try:
        parsed_value = datetime.fromisoformat(normalized_value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed_value.tzinfo is None:
        parsed_value = parsed_value.replace(tzinfo=timezone.utc)
    return parsed_value


def _seconds_until(value):
    parsed_value = _parse_iso_datetime(value)
    if not parsed_value:
        return None
    return max(round((parsed_value - _now_utc()).total_seconds()), 0)


def _is_waiting_for_retry(run):
    status = str((run or {}).get('status') or '').strip().lower()
    if status != TABULAR_EXPORT_STATUS_QUEUED or _safe_int((run or {}).get('transient_failure_count')) <= 0:
        return False
    retry_delay_seconds = _seconds_until((run or {}).get('next_attempt_at'))
    return retry_delay_seconds is not None and retry_delay_seconds > 0


def _is_due_queued_retry_run(run):
    status = str((run or {}).get('status') or '').strip().lower()
    if status != TABULAR_EXPORT_STATUS_QUEUED or _safe_int((run or {}).get('transient_failure_count')) <= 0:
        return False
    if _is_waiting_for_retry(run):
        return False

    next_attempt_at = _parse_iso_datetime((run or {}).get('next_attempt_at'))
    return next_attempt_at is None or next_attempt_at <= _now_utc()


def _is_due_queued_run(run):
    status = str((run or {}).get('status') or '').strip().lower()
    if status != TABULAR_EXPORT_STATUS_QUEUED or _is_waiting_for_retry(run):
        return False

    next_attempt_at = _parse_iso_datetime((run or {}).get('next_attempt_at'))
    return next_attempt_at is None or next_attempt_at <= _now_utc()


def _is_stale_queued_run(run, settings):
    status = str((run or {}).get('status') or '').strip().lower()
    if status != TABULAR_EXPORT_STATUS_QUEUED or _is_waiting_for_retry(run):
        return False

    stale_seconds = _settings_int(
        settings,
        'tabular_generated_output_stale_seconds',
        TABULAR_EXPORT_DEFAULT_STALE_SECONDS,
        minimum=60,
    )
    queued_at = _parse_iso_datetime(run.get('updated_at') or run.get('created_at'))
    if not queued_at:
        return True
    return queued_at <= _now_utc() - timedelta(seconds=stale_seconds)


def _is_retryable_failed_run(run):
    status = str((run or {}).get('status') or '').strip().lower()
    last_error = (run or {}).get('last_error')
    return status == TABULAR_EXPORT_STATUS_FAILED and (
        _is_retryable_export_error_message(last_error)
        or _is_retryable_model_validation_error_message(last_error)
    )


def _has_exhausted_independent_batch_retries(run):
    return (
        _safe_int((run or {}).get('exhausted_batch_count')) > 0
        or str((run or {}).get('last_retry_category') or '').strip().lower() == 'batch_exhausted'
    )


def _is_auto_retry_exhausted(run):
    return bool((run or {}).get('auto_retry_exhausted'))


def _can_auto_retry_failed_run(run, settings=None):
    if not _is_retryable_failed_run(run) or _is_auto_retry_exhausted(run):
        return False
    return _safe_int((run or {}).get('transient_failure_count')) < _settings_int(
        settings or {},
        'tabular_generated_output_max_transient_failures',
        TABULAR_EXPORT_DEFAULT_MAX_TRANSIENT_FAILURES,
        minimum=1,
        maximum=100,
    )


def _scheduler_candidate_reason(run, settings):
    status = str((run or {}).get('status') or '').strip().lower()
    if status == TABULAR_EXPORT_STATUS_QUEUED:
        if _is_due_queued_run(run):
            return 'queued run is due'
        if _is_stale_queued_run(run, settings or {}):
            return 'queued run is stale'
        return None
    if status == TABULAR_EXPORT_STATUS_RUNNING:
        if _is_stale_running_run(run, settings or {}):
            return 'running heartbeat is stale'
        return None
    if status == TABULAR_EXPORT_STATUS_FAILED:
        if _can_auto_retry_failed_run(run, settings or {}):
            return 'failed run has retryable error'
        return None
    return None


def _scheduler_candidate_sort_key(run):
    return (
        _parse_iso_datetime((run or {}).get('updated_at'))
        or _parse_iso_datetime((run or {}).get('created_at'))
        or _parse_iso_datetime((run or {}).get('last_heartbeat_at'))
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def _query_scheduler_candidates_by_status(status, scan_limit, settings):
    per_status_limit = _safe_int(scan_limit, default=TABULAR_EXPORT_DEFAULT_SCAN_LIMIT, minimum=1, maximum=10)
    query = (
        "SELECT "
        "c.id, c.user_id, c.status, c.created_at, c.updated_at, c.last_heartbeat_at, "
        "c.next_attempt_at, c.last_error, c.transient_failure_count, c.auto_retry_exhausted "
        "FROM c WHERE c.type = @type AND c.status = @status "
        "ORDER BY c.updated_at ASC"
    )
    try:
        query_results = cosmos_tabular_export_runs_container.query_items(
            query=query,
            parameters=[
                {'name': '@type', 'value': TABULAR_EXPORT_RUN_TYPE},
                {'name': '@status', 'value': status},
            ],
            enable_cross_partition_query=True,
        )
        eligible_candidates = []
        for run in query_results:
            if not _scheduler_candidate_reason(run, settings):
                continue
            eligible_candidates.append(run)
            if len(eligible_candidates) >= per_status_limit:
                break
        return eligible_candidates
    except Exception as exc:
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Scheduler candidate query failed',
            {
                'status': status,
                'scan_limit': per_status_limit,
                'error': str(exc)[:1000],
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise


def _can_resume_run(run, settings=None):
    if not isinstance(run, dict):
        return False

    status = str(run.get('status') or '').strip().lower()
    if status in {TABULAR_EXPORT_STATUS_COMPLETED, TABULAR_EXPORT_STATUS_CANCELED}:
        return False
    if status == TABULAR_EXPORT_STATUS_QUEUED:
        return (
            _is_waiting_for_retry(run)
            or _is_due_queued_retry_run(run)
            or _is_stale_queued_run(run, settings or {})
        )
    if status == TABULAR_EXPORT_STATUS_RUNNING:
        return _is_stale_running_run(run, settings or {})
    if status == TABULAR_EXPORT_STATUS_FAILED:
        return _is_retryable_failed_run(run) or _has_exhausted_independent_batch_retries(run)
    return False


def _can_cancel_run(run):
    status = str((run or {}).get('status') or '').strip().lower()
    return not run.get('publishing_started_at') and status not in {
        TABULAR_EXPORT_STATUS_COMPLETED,
        TABULAR_EXPORT_STATUS_CANCELED,
    }


def _build_checkpoint_summary(completed_batches, batch_count, processed_rows, row_count):
    checkpoint_parts = []
    if batch_count:
        checkpoint_parts.append(f'{completed_batches:,} of {batch_count:,} batches checkpointed')
    if row_count:
        checkpoint_parts.append(f'{processed_rows:,} of {row_count:,} rows processed')
    return '; '.join(checkpoint_parts)


def _build_tabular_run_lifecycle_public_fields(run, status_detail=None, can_resume=False):
    """Return normalized lifecycle fields for generated-output status metadata."""
    run = run if isinstance(run, dict) else {}
    status_detail = status_detail if isinstance(status_detail, dict) else {}
    status = str(run.get('status') or TABULAR_EXPORT_STATUS_QUEUED).strip().lower()
    lifecycle_state = status or TABULAR_EXPORT_STATUS_QUEUED
    safe_reason_code = lifecycle_state

    if status == TABULAR_EXPORT_STATUS_RUNNING and run.get('publishing_started_at'):
        lifecycle_state = 'finalizing'
        safe_reason_code = 'finalizing_publication'
    elif status == TABULAR_EXPORT_STATUS_QUEUED and status_detail.get('waiting_for_retry'):
        lifecycle_state = 'retrying'
        safe_reason_code = 'retry_scheduled'
    elif status == TABULAR_EXPORT_STATUS_FAILED and can_resume:
        lifecycle_state = 'intervention_required'
        safe_reason_code = 'continue_required'
    elif status == TABULAR_EXPORT_STATUS_COMPLETED:
        safe_reason_code = 'completed'
    elif status == TABULAR_EXPORT_STATUS_CANCELED:
        safe_reason_code = 'durable_work_canceled'
    elif status == TABULAR_EXPORT_STATUS_FAILED:
        safe_reason_code = 'failed'

    terminal = status in TABULAR_EXPORT_TERMINAL_STATUSES
    if status == TABULAR_EXPORT_STATUS_COMPLETED:
        evidence_status = 'completed'
    elif status == TABULAR_EXPORT_STATUS_CANCELED:
        evidence_status = 'canceled'
    elif status == TABULAR_EXPORT_STATUS_FAILED:
        evidence_status = 'failed'
    else:
        evidence_status = 'pending'

    return {
        'lifecycle_state': lifecycle_state,
        'execution_state': lifecycle_state,
        'evidence_status': evidence_status,
        'terminal': terminal,
        'required_for_composition': True,
        'safe_reason_code': safe_reason_code,
    }


def _normalize_tabular_run_rollout_assignment(raw_assignment):
    """Return a low-cardinality rollout assignment safe for status metadata."""
    raw_assignment = raw_assignment if isinstance(raw_assignment, dict) else {}
    if not raw_assignment:
        return {}

    return {
        'contract_version': str(raw_assignment.get('contract_version') or '').strip()[:80],
        'mode': str(raw_assignment.get('mode') or '').strip().lower()[:40],
        'planner_mode': str(raw_assignment.get('planner_mode') or '').strip().lower()[:40],
        'assigned': bool(raw_assignment.get('assigned')),
        'cohort_bucket': _safe_int(raw_assignment.get('cohort_bucket'), minimum=0, maximum=99),
        'rollout_percent': _safe_int(raw_assignment.get('rollout_percent'), minimum=0, maximum=100),
        'search_shared_preflight_enabled': bool(raw_assignment.get('search_shared_preflight_enabled')),
        'analyze_durable_preflight_enabled': bool(raw_assignment.get('analyze_durable_preflight_enabled')),
        'mixed_deferred_composition_planning_enabled': bool(
            raw_assignment.get('mixed_deferred_composition_planning_enabled')
        ),
        'multifile_execution_unit_planning_enabled': bool(
            raw_assignment.get('multifile_execution_unit_planning_enabled')
        ),
        'legacy_post_tool_fallback_mode': str(
            raw_assignment.get('legacy_post_tool_fallback_mode') or 'enabled'
        ).strip().lower()[:40],
    }


def _build_planner_source_coverage_summary(source_coverage):
    """Summarize planner source coverage without exposing source identifiers."""
    format_counts = Counter()
    source_count = 0
    for source in list(source_coverage or []):
        if not isinstance(source, dict):
            continue
        source_count += 1
        source_format = str(source.get('source_format') or 'unknown').strip().lower()
        if source_format not in {'csv', 'xlsx', 'xls', 'xlsm'}:
            source_format = 'unknown'
        format_counts[source_format] += 1

    return {
        'source_count': source_count,
        'format_class_counts': dict(sorted(format_counts.items())),
        'terminal_source_count': 0,
        'pending_source_count': source_count,
        'completed_source_count': 0,
        'partial_source_count': 0,
    }


def _normalize_tabular_run_planner_metadata(planner_metadata):
    """Normalize shared planner metadata before storing it on a durable run."""
    planner_metadata = planner_metadata if isinstance(planner_metadata, dict) else {}
    if not planner_metadata:
        return {}

    normalized_metadata = {
        'planner_contract_version': str(planner_metadata.get('planner_contract_version') or '').strip()[:80],
        'execution_contract': str(planner_metadata.get('execution_contract') or '').strip().lower()[:80],
        'execution_state': str(planner_metadata.get('execution_state') or '').strip().lower()[:40],
        'durable_task_type': _normalize_tabular_run_task_type(planner_metadata.get('durable_task_type')),
        'reason_code': str(planner_metadata.get('reason_code') or '').strip().lower()[:80],
        'execution_group_id': str(planner_metadata.get('execution_group_id') or '').strip()[:128],
        'source_coverage_summary': _build_planner_source_coverage_summary(
            planner_metadata.get('source_coverage'),
        ),
        'rollout_assignment': _normalize_tabular_run_rollout_assignment(
            planner_metadata.get('rollout_assignment'),
        ),
    }
    deliverable_contract = planner_metadata.get('deliverable_contract')
    if isinstance(deliverable_contract, dict):
        normalized_metadata['deliverable_contract'] = {
            'contract_version': str(deliverable_contract.get('contract_version') or '').strip()[:80],
            'action_mode': str(deliverable_contract.get('action_mode') or '').strip().lower()[:40],
            'analysis_required': bool(deliverable_contract.get('analysis_required')),
            'primary_artifact_role': str(deliverable_contract.get('primary_artifact_role') or '').strip().lower()[:80],
            'public_output_schema': [
                str(field_name or '').strip()
                for field_name in list(deliverable_contract.get('public_output_schema') or [])[:TABULAR_GENERATION_PLAN_MAX_FIELDS]
                if str(field_name or '').strip()
                and not is_analysis_internal_lineage_field(field_name)
            ],
            'internal_checkpoint_schema': [
                str(field_name or '').strip()
                for field_name in list(deliverable_contract.get('internal_checkpoint_schema') or [])[
                    :TABULAR_GENERATION_PLAN_MAX_FIELDS + 2
                ]
                if str(field_name or '').strip()
            ],
            'lineage_schema': [
                str(field_name or '').strip()
                for field_name in list(deliverable_contract.get('lineage_schema') or [])[:8]
                if str(field_name or '').strip()
                and is_analysis_internal_lineage_field(field_name)
            ],
            'row_cardinality': str(deliverable_contract.get('row_cardinality') or '').strip().lower()[:80],
            'ordering': str(deliverable_contract.get('ordering') or '').strip().lower()[:80],
            'transformation_mode': str(deliverable_contract.get('transformation_mode') or '').strip().lower()[:80],
            'validation_profile': str(deliverable_contract.get('validation_profile') or '').strip().lower()[:80],
            'publication_policy': str(deliverable_contract.get('publication_policy') or '').strip().lower()[:80],
        }
    return normalized_metadata


def _normalize_tabular_run_source_format(run):
    source_descriptor = (run or {}).get('source_descriptor') if isinstance((run or {}).get('source_descriptor'), dict) else {}
    source_format = str(source_descriptor.get('source_format') or '').strip().lower()
    if not source_format:
        source_file_name = str((run or {}).get('source_file_name') or '').strip()
        source_format = os.path.splitext(source_file_name)[1].lower().lstrip('.')
    if source_format not in {'csv', 'xlsx', 'xls', 'xlsm'}:
        return 'unknown'
    return source_format


def _build_tabular_run_source_coverage_summary(run, lifecycle_fields):
    """Summarize durable run coverage for UI state without exposing source locators."""
    run = run if isinstance(run, dict) else {}
    lifecycle_fields = lifecycle_fields if isinstance(lifecycle_fields, dict) else {}
    planner_metadata = run.get('tabular_planner_metadata') if isinstance(run.get('tabular_planner_metadata'), dict) else {}
    planner_summary = planner_metadata.get('source_coverage_summary') if isinstance(planner_metadata.get('source_coverage_summary'), dict) else {}
    source_count = _safe_int(planner_summary.get('source_count'), minimum=0)
    if source_count <= 0:
        source_count = 1 if (run.get('source_file_name') or run.get('source_descriptor') or run.get('source_authorization')) else 0

    format_counts = planner_summary.get('format_class_counts') if isinstance(planner_summary.get('format_class_counts'), dict) else {}
    if not format_counts and source_count:
        format_counts = {_normalize_tabular_run_source_format(run): source_count}

    evidence_status = str(lifecycle_fields.get('evidence_status') or 'pending').strip().lower()
    terminal = bool(lifecycle_fields.get('terminal'))
    return {
        'source_count': source_count,
        'format_class_counts': {
            str(key or 'unknown').strip().lower()[:20]: _safe_int(value, minimum=0)
            for key, value in dict(format_counts or {}).items()
        },
        'terminal_source_count': source_count if terminal else 0,
        'pending_source_count': 0 if terminal else source_count,
        'completed_source_count': source_count if evidence_status == 'completed' else 0,
        'partial_source_count': source_count if evidence_status in {'failed', 'canceled'} else 0,
        'failed_source_count': source_count if evidence_status == 'failed' else 0,
        'canceled_source_count': source_count if evidence_status == 'canceled' else 0,
        'required_for_composition': bool(lifecycle_fields.get('required_for_composition')),
        'source_backed': bool(run.get('source_descriptor')),
    }


def _build_tabular_run_deferred_composition_reference(run):
    """Return safe deferred-composition state linked to this run, when present."""
    descriptor = (run or {}).get('deferred_composition')
    if not isinstance(descriptor, dict):
        return {}

    required_runs = [
        run_reference
        for run_reference in list(descriptor.get('required_tabular_runs') or [])
        if isinstance(run_reference, dict)
    ]
    return {
        'composition_id': str(descriptor.get('composition_id') or '').strip()[:128],
        'contract_version': str(descriptor.get('contract_version') or '').strip()[:80],
        'status': str(descriptor.get('status') or '').strip().lower()[:40],
        'enabled': bool(descriptor.get('enabled')),
        'planning_enabled': bool(descriptor.get('planning_enabled')),
        'continuation_available': bool(descriptor.get('continuation_available')),
        'pending_source_count': _safe_int(descriptor.get('pending_source_count'), minimum=0),
        'required_source_count': _safe_int(descriptor.get('required_source_count'), minimum=0),
        'required_tabular_run_count': len(required_runs),
    }


def _build_tabular_run_rollout_assignment_public_fields(run):
    """Return the persisted Phase 8 rollout assignment, or generation rollout fallback."""
    run = run if isinstance(run, dict) else {}
    planner_metadata = run.get('tabular_planner_metadata') if isinstance(run.get('tabular_planner_metadata'), dict) else {}
    planner_assignment = _normalize_tabular_run_rollout_assignment(
        planner_metadata.get('rollout_assignment'),
    )
    if planner_assignment:
        return planner_assignment

    generation_rollout_settings = run.get('generation_rollout_settings') if isinstance(run.get('generation_rollout_settings'), dict) else {}
    if not generation_rollout_settings:
        return {}
    generation_rollout_bucket = _safe_int(
        generation_rollout_settings.get('tabular_generation_rollout_bucket'),
        default=1,
        minimum=1,
        maximum=100,
    ) - 1
    generation_rollout_cohort = str(
        generation_rollout_settings.get('tabular_generation_rollout_cohort') or ''
    ).strip().lower()
    return {
        'contract_version': 'tabular-generation-rollout-v1',
        'mode': 'generation',
        'planner_mode': str(run.get('plan_mode') or '').strip().lower()[:40],
        'assigned': generation_rollout_cohort != 'control',
        'cohort_bucket': generation_rollout_bucket,
        'rollout_percent': _safe_int(
            generation_rollout_settings.get('tabular_generation_rollout_percentage'),
            default=100,
            minimum=0,
            maximum=100,
        ),
        'search_shared_preflight_enabled': False,
        'analyze_durable_preflight_enabled': False,
        'mixed_deferred_composition_planning_enabled': False,
        'multifile_execution_unit_planning_enabled': False,
        'legacy_post_tool_fallback_mode': 'enabled',
    }


def _build_run_status_detail(run, settings, retryable_failure, can_resume):
    status = str((run or {}).get('status') or '').strip().lower()
    task_type = _normalize_tabular_run_task_type((run or {}).get('task_type'))
    is_hierarchical_analysis = task_type == TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS
    is_combined = task_type == TABULAR_RUN_TASK_COMBINED
    is_analysis_like = is_hierarchical_analysis or is_combined
    is_stale = status == TABULAR_EXPORT_STATUS_RUNNING and _is_stale_running_run(run, settings or {})
    waiting_for_retry = _is_waiting_for_retry(run)
    retry_due = _is_due_queued_retry_run(run)
    stale_queued = _is_stale_queued_run(run, settings or {})
    retry_delay_seconds = _seconds_until((run or {}).get('next_attempt_at')) if waiting_for_retry else None
    retry_category = str((run or {}).get('last_retry_category') or '').strip().lower()

    def retry_reason_text():
        if retry_category == 'model_validation':
            return 'model output validation failed'
        if retry_category in {'transient', 'connection', 'timeout', 'provider_transient', 'rate_limit'}:
            return 'a transient provider or connection interruption occurred'
        if retry_category == 'batch_exhausted':
            return 'one or more batches exhausted independent retries'
        return 'a retryable interruption occurred'

    if status == TABULAR_EXPORT_STATUS_COMPLETED:
        return {
            'status_label': 'Complete',
            'status_tone': 'success',
            'status_detail': (
                'Analysis and export complete and ready to view.'
                if is_combined
                else
                'Analysis complete and ready to view.'
                if is_hierarchical_analysis
                else 'Export complete and ready to download.'
            ),
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if status == TABULAR_EXPORT_STATUS_CANCELED:
        return {
            'status_label': 'Canceled',
            'status_tone': 'secondary',
            'status_detail': (
                'Combined analysis and export was canceled.'
                if is_combined
                else 'Analysis was canceled.'
                if is_hierarchical_analysis
                else 'Export was canceled.'
            ),
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if bool((run or {}).get('systemic_failure_circuit_open')):
        return {
            'status_label': 'Needs Review',
            'status_tone': 'danger',
            'status_detail': 'Repeated plan or schema validation failures stopped new batch dispatch before more retry cost was spent.',
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if is_stale:
        return {
            'status_label': 'Needs Attention',
            'status_tone': 'warning',
            'status_detail': 'Worker heartbeat is stale. Continue will resume from the last checkpoint.',
            'is_stale': True,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if status == TABULAR_EXPORT_STATUS_RUNNING:
        if run.get('publishing_started_at'):
            return {
                'status_label': 'Finalizing',
                'status_tone': 'info',
                'status_detail': (
                    'Combined export validation passed and the analysis answer artifact is being published.'
                    if is_combined
                    else
                    'Analysis reduction passed and the final answer artifact is being published.'
                    if is_hierarchical_analysis
                    else 'Export validation passed and the final artifact is being published.'
                ),
                'is_stale': False,
                'waiting_for_retry': False,
                'retry_due': False,
                'retry_delay_seconds': None,
            }
        if run.get('source_descriptor') and not run.get('source_staging_complete'):
            return {
                'status_label': 'Preparing Source',
                'status_tone': 'info',
                'status_detail': 'The selected tabular source is being read and checkpointed for background processing.',
                'is_stale': False,
                'waiting_for_retry': False,
                'retry_due': False,
                'retry_delay_seconds': None,
            }
        if str((run or {}).get('plan_status') or '').strip().lower() == 'planning':
            return {
                'status_label': 'Planning Output',
                'status_tone': 'info',
                'status_detail': 'The output schema is being planned before concurrent batch generation starts.',
                'is_stale': False,
                'waiting_for_retry': False,
                'retry_due': False,
                'retry_delay_seconds': None,
            }
        if _safe_int((run or {}).get('completed_batches')) == 0:
            return {
                'status_label': 'Starting',
                'status_tone': 'info',
                'status_detail': 'The initial output checkpoint is being generated; concurrent batches will follow.',
                'is_stale': False,
                'waiting_for_retry': False,
                'retry_due': False,
                'retry_delay_seconds': None,
            }
        if _safe_int((run or {}).get('retry_wait_batch_count')) > 0:
            return {
                'status_label': 'Running with Retries',
                'status_tone': 'warning',
                'status_detail': 'Export is running; failed batches are waiting to retry while unrelated batches continue.',
                'is_stale': False,
                'waiting_for_retry': False,
                'retry_due': False,
                'retry_delay_seconds': None,
            }
        return {
            'status_label': 'Running',
            'status_tone': 'info',
            'status_detail': (
                'Combined run is reducing checkpointed chunk summaries.'
                if is_combined and (run or {}).get('analysis_phase') == 'reducing'
                else 'Analysis is reducing checkpointed chunk summaries.'
                if is_hierarchical_analysis and (run or {}).get('analysis_phase') == 'reducing'
                else 'Combined run is building export rows and checkpointed chunk summaries.'
                if is_combined
                else 'Analysis is running and checkpointing completed chunks.'
                if is_hierarchical_analysis
                else 'Export is running and checkpointing completed batches.'
            ),
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if waiting_for_retry:
        return {
            'status_label': 'Retry Scheduled',
            'status_tone': 'warning',
            'status_detail': f'Automatic retry is scheduled because {retry_reason_text()}. Continue can resume now from the last checkpoint.',
            'is_stale': False,
            'waiting_for_retry': True,
            'retry_due': False,
            'retry_delay_seconds': retry_delay_seconds,
        }
    if retry_due:
        return {
            'status_label': 'Needs Attention',
            'status_tone': 'warning',
            'status_detail': f'Automatic retry is due because {retry_reason_text()}, but no worker has picked it up. Continue will resume from the last checkpoint.',
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': True,
            'retry_delay_seconds': None,
        }
    if stale_queued:
        return {
            'status_label': 'Needs Attention',
            'status_tone': 'warning',
            'status_detail': 'Export has been queued longer than expected. Continue will submit it again from the last checkpoint.',
            'is_stale': True,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if status == TABULAR_EXPORT_STATUS_FAILED and retryable_failure:
        return {
            'status_label': 'Needs Attention',
            'status_tone': 'warning' if can_resume else 'danger',
            'status_detail': (
                f'Analysis stopped because {retry_reason_text()}. Continue will resume from the last checkpoint.'
                if is_analysis_like
                else f'Export stopped because {retry_reason_text()}. Continue will resume from the last checkpoint.'
            ),
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if status == TABULAR_EXPORT_STATUS_FAILED and _has_exhausted_independent_batch_retries(run):
        return {
            'status_label': 'Needs Attention',
            'status_tone': 'warning' if can_resume else 'danger',
            'status_detail': 'One or more batches exhausted independent retries. Continue will retry eligible missing batches from saved checkpoints.',
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if status == TABULAR_EXPORT_STATUS_FAILED:
        return {
            'status_label': 'Failed',
            'status_tone': 'danger',
            'status_detail': (
                'Analysis failed and cannot continue from checkpoints.'
                if is_analysis_like
                else 'Export failed and cannot continue from checkpoints.'
            ),
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }

    return {
        'status_label': 'Queued',
        'status_tone': 'info',
        'status_detail': (
            'Combined analysis and export is queued and waiting for a background worker.'
            if is_combined
            else
            'Analysis is queued and waiting for a background worker.'
            if is_hierarchical_analysis
            else 'Export is queued and waiting for a background worker.'
        ),
        'is_stale': False,
        'waiting_for_retry': False,
        'retry_due': False,
        'retry_delay_seconds': None,
    }



def _build_run_public_status(run, settings=None):
    if not isinstance(run, dict):
        return None
    run = _sync_tabular_generation_contract_fields(run)

    batch_count = _safe_int(run.get('batch_count'))
    completed_batches = _safe_int(run.get('completed_batches'))
    row_count = _safe_int(run.get('row_count'))
    processed_rows = _safe_int(run.get('processed_rows'))
    total_chunk_count = _safe_int(run.get('total_chunk_count'), default=batch_count, minimum=0)
    processed_chunk_count = _safe_int(run.get('processed_chunk_count'), default=completed_batches, minimum=0)
    failed_chunk_count = _safe_int(run.get('failed_chunk_count'), default=0, minimum=0)
    progress_percent = 0.0
    if batch_count:
        progress_percent = round((completed_batches / batch_count) * 100, 2)

    task_type = _normalize_tabular_run_task_type(run.get('task_type'))
    final_artifact = run.get('final_artifact') or {}
    retryable_failure = _is_retryable_failed_run(run)
    can_resume = _can_resume_run(run, settings)
    status_detail = _build_run_status_detail(run, settings, retryable_failure, can_resume)
    lifecycle_fields = _build_tabular_run_lifecycle_public_fields(
        run,
        status_detail=status_detail,
        can_resume=can_resume,
    )
    planner_metadata = run.get('tabular_planner_metadata') if isinstance(run.get('tabular_planner_metadata'), dict) else {}
    source_coverage_summary = _build_tabular_run_source_coverage_summary(run, lifecycle_fields)
    deferred_composition = _build_tabular_run_deferred_composition_reference(run)
    rollout_assignment = _build_tabular_run_rollout_assignment_public_fields(run)
    checkpoint_summary = _build_checkpoint_summary(completed_batches, batch_count, processed_rows, row_count)
    generated_artifacts = []

    def append_generated_artifact(artifact, fallback_file_name, fallback_output_format, summary):
        artifact = artifact if isinstance(artifact, dict) else {}
        if not artifact.get('artifact_message_id'):
            return
        generated_artifacts.append({
            'capability': artifact.get('capability') or 'tabular',
            'artifact_message_id': artifact.get('artifact_message_id'),
            'conversation_id': run.get('conversation_id'),
            'file_name': artifact.get('file_name') or fallback_file_name,
            'output_format': artifact.get('output_format') or fallback_output_format,
            'row_count': processed_rows or row_count,
            'storage_scope': 'chat',
            'source_file_name': run.get('source_file_name'),
            'selected_sheet': run.get('selected_sheet'),
            'summary': summary,
            'preview_rows': list(artifact.get('preview_rows') or [])[
                :TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_ROWS
            ],
            'preview_columns': list(artifact.get('preview_columns') or [])[
                :TABULAR_GENERATION_PLAN_MAX_FIELDS + 2
            ],
            'preview_text': str(artifact.get('preview_text') or '')[
                :TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_CHARS
            ],
            'suppress_assistant_text': bool(artifact.get('suppress_assistant_text')),
            'suppress_assistant_table_export': True,
        })

    if task_type == TABULAR_RUN_TASK_COMBINED:
        append_generated_artifact(
            run.get('structured_export_artifact') or final_artifact,
            run.get('generated_file_name'),
            run.get('output_format'),
            run.get('post_run_export_summary'),
        )
        append_generated_artifact(
            run.get('analysis_artifact'),
            run.get('analysis_generated_file_name'),
            'md',
            run.get('post_run_summary'),
        )
    else:
        append_generated_artifact(
            final_artifact,
            run.get('generated_file_name'),
            run.get('output_format'),
            run.get('post_run_summary'),
        )
    generated_artifact = generated_artifacts[0] if generated_artifacts else None

    return {
        'run_id': run.get('id'),
        'conversation_id': run.get('conversation_id'),
        'task_type': task_type,
        'status': run.get('status'),
        'metadata_contract_version': 'phase8.v1',
        'planner_contract_version': planner_metadata.get('planner_contract_version'),
        'execution_contract': planner_metadata.get('execution_contract') or task_type,
        'execution_group_id': planner_metadata.get('execution_group_id'),
        'planner_reason_code': planner_metadata.get('reason_code'),
        'source_coverage_summary': source_coverage_summary,
        'deferred_composition': deferred_composition,
        'rollout_assignment': rollout_assignment,
        **lifecycle_fields,
        'source_file_name': run.get('source_file_name'),
        'selected_sheet': run.get('selected_sheet'),
        'output_format': run.get('output_format'),
        'row_count': row_count,
        'processed_rows': processed_rows,
        'batch_count': batch_count,
        'completed_batches': completed_batches,
        'generation_contract_version': _safe_int(run.get('generation_contract_version')),
        'response_protocol_version': run.get('response_protocol_version'),
        'executor_mode': run.get('executor_mode'),
        'retry_mode': run.get('retry_mode'),
        'plan_mode': run.get('plan_mode'),
        'planned_batch_count': _safe_int(run.get('planned_batch_count')),
        'completed_batch_count': _safe_int(run.get('completed_batch_count')),
        'highest_contiguous_batch': _safe_int(run.get('highest_contiguous_batch')),
        'active_batch_count': _safe_int(run.get('active_batch_count')),
        'pending_batch_count': _safe_int(run.get('pending_batch_count')),
        'checkpointing_batch_count': _safe_int(run.get('checkpointing_batch_count')),
        'retry_wait_batch_count': _safe_int(run.get('retry_wait_batch_count')),
        'exhausted_batch_count': _safe_int(run.get('exhausted_batch_count')),
        'systemic_failure_circuit_open': bool(run.get('systemic_failure_circuit_open')),
        'systemic_failure_category': run.get('systemic_failure_category'),
        'systemic_failure_signature': run.get('systemic_failure_signature'),
        'checkpointed_row_count': _safe_int(run.get('checkpointed_row_count')),
        'total_chunk_count': total_chunk_count,
        'processed_chunk_count': processed_chunk_count,
        'failed_chunk_count': failed_chunk_count,
        'analysis_phase': run.get('analysis_phase'),
        'analysis_reduce_level': _safe_int(run.get('analysis_reduce_level')),
        'analysis_reduce_node': _safe_int(run.get('analysis_reduce_node')),
        'analysis_reduce_node_count': _safe_int(run.get('analysis_reduce_node_count')),
        'analysis_reduce_plan': run.get('analysis_reduce_plan') if isinstance(run.get('analysis_reduce_plan'), list) else [],
        'progress_percent': progress_percent,
        'created_at': run.get('created_at'),
        'started_at': run.get('started_at'),
        'generation_started_at': run.get('generation_started_at'),
        'generation_completed_at': run.get('generation_completed_at'),
        'updated_at': run.get('updated_at'),
        'completed_at': run.get('completed_at'),
        'last_heartbeat_at': run.get('last_heartbeat_at'),
        'last_message': run.get('last_message'),
        'status_label': status_detail.get('status_label'),
        'status_tone': status_detail.get('status_tone'),
        'status_detail': status_detail.get('status_detail'),
        'checkpoint_summary': checkpoint_summary,
        'is_stale': status_detail.get('is_stale'),
        'waiting_for_retry': status_detail.get('waiting_for_retry'),
        'retry_due': status_detail.get('retry_due'),
        'retry_delay_seconds': status_detail.get('retry_delay_seconds'),
        'estimated_remaining_seconds': run.get('estimated_remaining_seconds'),
        'estimated_total_seconds': run.get('estimated_total_seconds'),
        'rows_per_minute': run.get('rows_per_minute'),
        'batch_concurrency': _safe_int(run.get('batch_concurrency')),
        'effective_batch_concurrency': _safe_int(run.get('effective_batch_concurrency')),
        'mismatch_count': _safe_int(run.get('mismatch_count')),
        'retry_count': _safe_int(run.get('retry_count')),
        'transient_failure_count': _safe_int(run.get('transient_failure_count')),
        'auto_retry_exhausted': bool(run.get('auto_retry_exhausted')),
        'last_retry_category': run.get('last_retry_category'),
        'manual_resume_count': _safe_int(run.get('manual_resume_count')),
        'next_attempt_at': run.get('next_attempt_at'),
        'can_resume': can_resume,
        'can_cancel': _can_cancel_run(run),
        'retryable_failure': retryable_failure,
        'artifact_message_id': final_artifact.get('artifact_message_id'),
        'file_name': final_artifact.get('file_name') or run.get('generated_file_name'),
        'generated_artifact': generated_artifact,
        'generated_artifacts': generated_artifacts,
        'structured_export_artifact': run.get('structured_export_artifact'),
        'analysis_artifact': run.get('analysis_artifact'),
        'capability': 'tabular',
        'suppress_assistant_table_export': True,
        'background_export': not (
            str(run.get('status') or '').strip().lower() == TABULAR_EXPORT_STATUS_COMPLETED
            and generated_artifact
        ),
    }


def build_background_tabular_generated_output_metadata(run):
    """Build assistant metadata for a queued or running background export."""
    public_status = _build_run_public_status(run) or {}
    task_type = public_status.get('task_type') or _normalize_tabular_run_task_type((run or {}).get('task_type'))
    is_hierarchical_analysis = task_type == TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS
    is_combined = task_type == TABULAR_RUN_TASK_COMBINED
    output_label = str(public_status.get('output_format') or 'json').upper()
    row_count = _safe_int(public_status.get('row_count'))
    public_status.update({
        'export_run_id': public_status.get('run_id'),
        'background_export': True,
        'capability': 'tabular',
        'suppress_assistant_table_export': True,
        'handoff_mode': (
            'background_combined'
            if is_combined
            else 'background_analysis'
            if is_hierarchical_analysis
            else 'background_export'
        ),
        'requested_row_count': row_count,
        'preview_available': False,
        'preview_row_count': 0,
        'foreground_response_policy_version': 'phase2.v1',
        'summary': (
            f"Queued combined tabular analysis and {output_label} export for {row_count} row(s)."
            if is_combined
            else
            f"Queued hierarchical tabular analysis for {row_count} row(s)."
            if is_hierarchical_analysis
            else f"Queued structured {output_label} export for {row_count} row(s)."
        ),
    })
    return public_status


def get_tabular_generated_output_run_status(user_id, run_id):
    normalized_user_id = str(user_id or '').strip()
    normalized_run_id = str(run_id or '').strip()
    if not normalized_user_id or not normalized_run_id:
        return None

    settings = get_settings()
    try:
        run = cosmos_tabular_export_runs_container.read_item(
            item=normalized_run_id,
            partition_key=normalized_user_id,
        )
    except CosmosResourceNotFoundError:
        return None
    return _build_run_public_status(run, settings=settings)


def resume_tabular_generated_output_run(user_id, run_id):
    """Manually requeue a resumable generated-output run from its saved checkpoints."""
    normalized_user_id = str(user_id or '').strip()
    normalized_run_id = str(run_id or '').strip()
    if not normalized_user_id or not normalized_run_id:
        return None

    settings = get_settings()
    try:
        run = _read_run(normalized_user_id, normalized_run_id)
    except CosmosResourceNotFoundError:
        return None

    try:
        _authorize_tabular_export_run_execution(run)
    except (LookupError, PermissionError, ValueError):
        return {
            'success': False,
            'resumed': False,
            'submitted': False,
            'authorization_failed': True,
            'message': 'Background export access is no longer authorized.',
            'run': _build_run_public_status(run, settings=settings),
        }

    status = str(run.get('status') or '').strip().lower()
    if status == TABULAR_EXPORT_STATUS_COMPLETED:
        return {
            'success': True,
            'resumed': False,
            'submitted': False,
            'message': 'Background export is already complete.',
            'run': _build_run_public_status(run, settings=settings),
        }
    if status == TABULAR_EXPORT_STATUS_CANCELED:
        return {
            'success': False,
            'resumed': False,
            'submitted': False,
            'message': 'Canceled background exports cannot be continued.',
            'run': _build_run_public_status(run, settings=settings),
        }
    if not _can_cancel_run(run):
        return {
            'success': False,
            'resumed': False,
            'submitted': False,
            'message': 'Background export is already publishing and cannot be resumed.',
            'run': _build_run_public_status(run, settings=settings),
        }
    if status == TABULAR_EXPORT_STATUS_RUNNING and not _is_stale_running_run(run, settings):
        return {
            'success': True,
            'resumed': False,
            'submitted': False,
            'message': 'Background export is already running.',
            'run': _build_run_public_status(run, settings=settings),
        }
    if (
        status == TABULAR_EXPORT_STATUS_FAILED
        and not _is_retryable_failed_run(run)
        and not _has_exhausted_independent_batch_retries(run)
    ):
        return {
            'success': False,
            'resumed': False,
            'submitted': False,
            'message': 'Background export cannot be continued because the last failure was not retryable.',
            'run': _build_run_public_status(run, settings=settings),
        }

    now = _now_iso()
    reset_batch_retry_count = 0
    if _is_independent_batch_retries_enabled(settings, run):
        reset_batch_retry_count = _reset_exhausted_tabular_batch_retry_records_for_continue(run, now)
    run.update({
        'status': TABULAR_EXPORT_STATUS_QUEUED,
        'updated_at': now,
        'completed_at': None,
        'last_heartbeat_at': now,
        'lease_holder_id': None,
        'lease_expires_at': None,
        'next_attempt_at': now,
        'last_message': 'Manual resume queued; export will continue from completed checkpoints',
        'transient_failure_count': 0,
        'auto_retry_exhausted': False,
        'last_retry_category': 'manual_resume',
        'retry_wait_batch_count': reset_batch_retry_count,
        'exhausted_batch_count': 0,
        'systemic_failure_circuit_open': False,
        'systemic_failure_category': None,
        'systemic_failure_signature': None,
        'systemic_failure_opened_at': None,
        'manual_resume_count': _safe_int(run.get('manual_resume_count')) + 1,
        'last_manual_resume_at': now,
    })
    try:
        run = _replace_run(run)
    except Exception as exc:
        if getattr(exc, 'status_code', None) not in (409, 412):
            raise
        current_run = _read_run(normalized_user_id, normalized_run_id)
        return {
            'success': False,
            'resumed': False,
            'submitted': False,
            'message': 'Background export state changed. Refresh its status before continuing.',
            'run': _build_run_public_status(current_run, settings=settings),
        }
    submitted = submit_tabular_generated_output_run(normalized_run_id, normalized_user_id)
    run['submitted_to_executor'] = submitted
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Background export manually resumed',
        {
            'run_id': normalized_run_id,
            'conversation_id': run.get('conversation_id'),
            'user_id': normalized_user_id,
            'completed_batches': run.get('completed_batches'),
            'batch_count': run.get('batch_count'),
            'processed_rows': run.get('processed_rows'),
            'row_count': run.get('row_count'),
            'submitted_to_executor': submitted,
            'manual_resume_count': run.get('manual_resume_count'),
            'reset_batch_retry_count': reset_batch_retry_count,
        },
        level=logging.INFO,
    )
    return {
        'success': True,
        'resumed': True,
        'submitted': submitted,
        'message': 'Background export was queued to continue from completed checkpoints.',
        'run': _build_run_public_status(run, settings=settings),
    }


def cancel_tabular_generated_output_run(user_id, run_id):
    """Cancel a queued, running, retryable, or failed generated-output run."""
    normalized_user_id = str(user_id or '').strip()
    normalized_run_id = str(run_id or '').strip()
    if not normalized_user_id or not normalized_run_id:
        return None

    settings = get_settings()
    try:
        run = _read_run(normalized_user_id, normalized_run_id)
    except CosmosResourceNotFoundError:
        return None

    status = str(run.get('status') or '').strip().lower()
    if status == TABULAR_EXPORT_STATUS_COMPLETED:
        return {
            'success': False,
            'canceled': False,
            'message': 'Completed background exports cannot be canceled.',
            'run': _build_run_public_status(run, settings=settings),
        }
    if status == TABULAR_EXPORT_STATUS_CANCELED:
        return {
            'success': True,
            'canceled': True,
            'message': 'Background export is already canceled.',
            'run': _build_run_public_status(run, settings=settings),
        }
    if not _can_cancel_run(run):
        return {
            'success': False,
            'canceled': False,
            'message': 'Background export is already publishing and can no longer be canceled.',
            'run': _build_run_public_status(run, settings=settings),
        }

    now = _now_iso()
    run.update({
        'status': TABULAR_EXPORT_STATUS_CANCELED,
        'updated_at': now,
        'completed_at': now,
        'last_heartbeat_at': now,
        'lease_holder_id': None,
        'lease_expires_at': None,
        'next_attempt_at': None,
        'last_message': 'Background structured export canceled by the user',
        'last_error': None,
        'canceled_at': now,
    })
    try:
        run = _replace_run(run)
    except Exception as exc:
        if getattr(exc, 'status_code', None) not in (409, 412):
            raise
        current_run = _read_run(normalized_user_id, normalized_run_id)
        return {
            'success': False,
            'canceled': False,
            'message': 'Background export state changed. Refresh its status before canceling.',
            'run': _build_run_public_status(current_run, settings=settings),
        }
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Background export canceled',
        {
            'run_id': normalized_run_id,
            'conversation_id': run.get('conversation_id'),
            'user_id': normalized_user_id,
            'completed_batches': run.get('completed_batches'),
            'processed_rows': run.get('processed_rows'),
        },
        level=logging.INFO,
    )
    return {
        'success': True,
        'canceled': True,
        'message': 'Background export canceled.',
        'run': _build_run_public_status(run, settings=settings),
    }


def _read_run(user_id, run_id):
    return cosmos_tabular_export_runs_container.read_item(
        item=run_id,
        partition_key=user_id,
    )


def _raise_if_tabular_export_canceled(run):
    current_run = _read_run(run.get('user_id'), run.get('id'))
    current_status = str(current_run.get('status') or '').strip().lower()
    if current_status == TABULAR_EXPORT_STATUS_CANCELED:
        run.clear()
        run.update(current_run)
        raise TabularExportCanceledError('Background structured export was canceled')

    claim_matches = (
        current_status == TABULAR_EXPORT_STATUS_RUNNING
        and str(current_run.get('lease_holder_id') or '') == str(run.get('lease_holder_id') or '')
        and _safe_int(current_run.get('lease_generation')) == _safe_int(run.get('lease_generation'))
    )
    if not claim_matches:
        raise TabularExportLeaseLostError('Background structured export worker lost its claim')

    run['_etag'] = current_run.get('_etag')
    return current_run


def _replace_claimed_run(run):
    try:
        return _replace_run(run)
    except Exception as exc:
        if getattr(exc, 'status_code', None) in (409, 412):
            raise TabularExportLeaseLostError(
                'Background structured export worker lost its claim'
            ) from exc
        raise


def _replace_run(run):
    return cosmos_tabular_export_runs_container.replace_item(
        item=run.get('id'),
        body=run,
        etag=run.get('_etag'),
        match_condition=MatchConditions.IfNotModified,
    )


def _lease_holder_id():
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"


def _is_stale_running_run(run, settings):
    rollout_settings = _get_tabular_generation_rollout_settings_for_run(run, settings)
    stale_seconds = _safe_int(
        rollout_settings.get('tabular_generation_stale_seconds'),
        default=TABULAR_EXPORT_DEFAULT_STALE_SECONDS,
        minimum=60,
        maximum=900,
    )
    if str((run or {}).get('executor_mode') or '').strip() != TABULAR_EXECUTOR_MODE_ROLLING_POOL:
        batch_timeout_seconds = _settings_int(
            settings,
            'tabular_generated_output_batch_timeout_seconds',
            TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
            minimum=30,
            maximum=900,
        )
        stale_seconds = max(stale_seconds, batch_timeout_seconds + 60)
    last_heartbeat = str(run.get('last_heartbeat_at') or run.get('updated_at') or '').strip()
    if not last_heartbeat:
        return True
    try:
        last_heartbeat_time = datetime.fromisoformat(last_heartbeat)
    except ValueError:
        return True
    if last_heartbeat_time.tzinfo is None:
        last_heartbeat_time = last_heartbeat_time.replace(tzinfo=timezone.utc)
    return last_heartbeat_time <= _now_utc() - timedelta(seconds=stale_seconds)


def _try_claim_run(user_id, run_id, settings):
    try:
        run = _read_run(user_id, run_id)
    except CosmosResourceNotFoundError:
        return None

    status = str(run.get('status') or '').strip().lower()
    if status in TABULAR_EXPORT_TERMINAL_STATUSES:
        retryable_failed_run = status == TABULAR_EXPORT_STATUS_FAILED and _can_auto_retry_failed_run(run, settings)
        if not retryable_failed_run:
            return None
    if status == TABULAR_EXPORT_STATUS_RUNNING and not _is_stale_running_run(run, settings):
        return None

    lease_seconds = _settings_int(
        settings,
        'tabular_generated_output_lease_seconds',
        TABULAR_EXPORT_DEFAULT_LEASE_SECONDS,
        minimum=60,
    )
    now = _now_utc()
    run.update({
        'status': TABULAR_EXPORT_STATUS_RUNNING,
        'started_at': run.get('started_at') or now.isoformat(),
        'generation_started_at': run.get('generation_started_at') or now.isoformat(),
        'attempt_started_at': now.isoformat(),
        'updated_at': now.isoformat(),
        'completed_at': None,
        'generation_completed_at': None,
        'last_heartbeat_at': now.isoformat(),
        'lease_holder_id': _lease_holder_id(),
        'lease_generation': _safe_int(run.get('lease_generation')) + 1,
        'lease_expires_at': (now + timedelta(seconds=lease_seconds)).isoformat(),
        'next_attempt_at': None,
        'last_message': 'Background structured export is running',
    })
    _sync_tabular_generation_contract_fields(run)
    try:
        return _replace_run(run)
    except Exception as exc:
        status_code = getattr(exc, 'status_code', None)
        if status_code not in (409, 412):
            log_event(
                '[TABULAR_GENERATED_OUTPUT] Background export run claim failed',
                {'run_id': run_id, 'user_id': user_id, 'status_code': status_code, 'error': str(exc)},
                level=logging.WARNING,
            )
        return None


def _mark_run_failed(run, error_message):
    now = _now_iso()
    run.update({
        'status': TABULAR_EXPORT_STATUS_FAILED,
        'updated_at': now,
        'completed_at': now,
        'last_heartbeat_at': now,
        'active_batch_count': 0,
        'last_error': str(error_message or 'Unknown error')[:1000],
        'last_message': 'Background structured export failed',
    })
    run['performance_summary'] = _build_tabular_generation_performance_summary(run, completed_at=now)
    try:
        run = _replace_claimed_run(run)
    except TabularExportLeaseLostError:
        return _read_run(run.get('user_id'), run.get('id'))
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Background export run failed',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'completed_batches': run.get('completed_batches'),
            'batch_count': run.get('batch_count'),
            'processed_rows': run.get('processed_rows'),
            'row_count': run.get('row_count'),
            'error': str(error_message or '')[:1000],
            **run.get('performance_summary', {}),
        },
        level=logging.ERROR,
        exceptionTraceback=True,
    )
    return run


def _get_auto_retry_limit_for_category(settings, retry_category):
    if retry_category == 'model_validation':
        return _settings_int(
            settings,
            'tabular_generated_output_model_validation_auto_retries',
            TABULAR_EXPORT_DEFAULT_MODEL_VALIDATION_AUTO_RETRIES,
            minimum=0,
            maximum=10,
        )
    return _settings_int(
        settings,
        'tabular_generated_output_max_transient_failures',
        TABULAR_EXPORT_DEFAULT_MAX_TRANSIENT_FAILURES,
        minimum=1,
        maximum=100,
    )


def _mark_run_retryable(run, error_message, settings, retry_category='transient'):
    normalized_retry_category = str(retry_category or 'transient').strip().lower() or 'transient'
    transient_failure_count = _safe_int(run.get('transient_failure_count')) + 1
    max_auto_retries = _get_auto_retry_limit_for_category(settings, normalized_retry_category)
    if transient_failure_count > max_auto_retries:
        exhausted_message = (
            'Max automatic model-output retry attempts exceeded; last error: '
            if normalized_retry_category == 'model_validation'
            else 'Max transient retry attempts exceeded; last error: '
        )
        run['auto_retry_exhausted'] = True
        run['last_retry_category'] = normalized_retry_category
        run['last_auto_retry_exhausted_at'] = _now_iso()
        return _mark_run_failed(
            run,
            f'{exhausted_message}{error_message}',
        )

    now = _now_utc()
    retry_delay_seconds = min(300, 15 * transient_failure_count)
    next_attempt_at = (now + timedelta(seconds=retry_delay_seconds)).isoformat()
    run.update({
        'status': TABULAR_EXPORT_STATUS_QUEUED,
        'updated_at': now.isoformat(),
        'completed_at': None,
        'last_heartbeat_at': now.isoformat(),
        'lease_holder_id': None,
        'lease_expires_at': None,
        'active_batch_count': 0,
        'last_error': str(error_message or 'Transient background export error')[:1000],
        'last_message': (
            'Background structured export will retry after model-output validation failed'
            if normalized_retry_category == 'model_validation'
            else 'Background structured export will resume after a transient connection error'
        ),
        'transient_failure_count': transient_failure_count,
        'last_retry_category': normalized_retry_category,
        'auto_retry_exhausted': False,
        'next_attempt_at': next_attempt_at,
    })
    try:
        run = _replace_claimed_run(run)
    except TabularExportLeaseLostError:
        return _read_run(run.get('user_id'), run.get('id'))
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Background export run requeued after transient failure',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'completed_batches': run.get('completed_batches'),
            'batch_count': run.get('batch_count'),
            'processed_rows': run.get('processed_rows'),
            'row_count': run.get('row_count'),
            'transient_failure_count': transient_failure_count,
            'max_transient_failures': max_auto_retries,
            'retry_category': normalized_retry_category,
            'next_attempt_at': next_attempt_at,
            'error': str(error_message or '')[:1000],
        },
        level=logging.WARNING,
    )
    return run


def _is_schema_discovery_progress_window(run, completed_batches, window_batch_count):
    return (
        _safe_int(completed_batches) == 1
        and _safe_int(window_batch_count) == 1
        and _safe_int((run or {}).get('batch_count')) > 1
        and _safe_int((run or {}).get('batch_concurrency')) > 1
    )


def _calculate_window_throughput(
    run,
    processed_rows,
    window_rows,
    window_elapsed_seconds,
    completed_at,
):
    recent_windows = list(run.get('recent_progress_windows') or [])[-9:]
    normalized_window_rows = _safe_int(window_rows)
    normalized_window_seconds = max(_safe_float(window_elapsed_seconds), 0.0)
    if normalized_window_rows > 0 and normalized_window_seconds > 0:
        recent_windows.append({
            'row_count': normalized_window_rows,
            'elapsed_seconds': round(normalized_window_seconds, 3),
            'completed_at': completed_at.isoformat(),
        })

    sampled_rows = sum(_safe_int(window.get('row_count')) for window in recent_windows)
    sampled_seconds = sum(
        max(_safe_float(window.get('elapsed_seconds')), 0.0)
        for window in recent_windows
    )
    rows_per_minute = None
    estimated_total_seconds = None
    estimated_remaining_seconds = None
    if sampled_rows > 0 and sampled_seconds > 0:
        rows_per_second = sampled_rows / sampled_seconds
        row_count = _safe_int(run.get('row_count'))
        rows_per_minute = round(rows_per_second * 60, 2)
        estimated_total_seconds = round(row_count / rows_per_second, 1)
        estimated_remaining_seconds = round(
            max(row_count - _safe_int(processed_rows), 0) / rows_per_second,
            1,
        )

    return {
        'recent_progress_windows': recent_windows,
        'rows_per_minute': rows_per_minute,
        'estimated_total_seconds': estimated_total_seconds,
        'estimated_remaining_seconds': estimated_remaining_seconds,
    }


def _build_tabular_generation_performance_summary(run, completed_at=None):
    completed_time = _parse_iso_datetime(completed_at or (run or {}).get('completed_at')) or _now_utc()

    def elapsed_seconds(started_at):
        started_time = _parse_iso_datetime(started_at)
        if not started_time:
            return None
        return round(max((completed_time - started_time).total_seconds(), 0.0), 3)

    planner_started_at = (run or {}).get('planner_started_at')
    planner_completed_at = _parse_iso_datetime((run or {}).get('planner_completed_at'))
    planner_started_time = _parse_iso_datetime(planner_started_at)
    created_time = _parse_iso_datetime((run or {}).get('created_at'))
    started_time = _parse_iso_datetime((run or {}).get('started_at'))
    planning_latency_seconds = None
    if planner_started_time and planner_completed_at:
        planning_latency_seconds = round(
            max((planner_completed_at - planner_started_time).total_seconds(), 0.0),
            3,
        )
    queue_latency_seconds = None
    if created_time and started_time:
        queue_latency_seconds = round(
            max((started_time - created_time).total_seconds(), 0.0),
            3,
        )

    return {
        'planning_latency_seconds': planning_latency_seconds,
        'queue_latency_seconds': queue_latency_seconds,
        'generation_elapsed_seconds': elapsed_seconds((run or {}).get('generation_started_at')),
        'end_to_end_elapsed_seconds': elapsed_seconds((run or {}).get('created_at')),
        'durable_rows_per_minute': (run or {}).get('rows_per_minute'),
        'configured_concurrency': _safe_int((run or {}).get('batch_concurrency')),
        'effective_concurrency': _safe_int((run or {}).get('effective_batch_concurrency')),
        'retry_count': _safe_int((run or {}).get('retry_count')),
        'transient_failure_count': _safe_int((run or {}).get('transient_failure_count')),
        'row_count': _safe_int((run or {}).get('row_count')),
        'completed_row_count': _safe_int((run or {}).get('processed_rows')),
        'batch_count': _safe_int((run or {}).get('batch_count')),
        'completed_batch_count': _safe_int((run or {}).get('completed_batch_count')),
        'rollout_cohort': ((run or {}).get('generation_rollout_settings') or {}).get(
            'tabular_generation_rollout_cohort'
        ),
        'plan_mode': (run or {}).get('plan_mode'),
        'executor_mode': (run or {}).get('executor_mode'),
        'response_protocol_version': (run or {}).get('response_protocol_version'),
        'retry_mode': (run or {}).get('retry_mode'),
    }


def _update_run_progress(
    run,
    completed_batches,
    processed_rows,
    window_rows,
    window_elapsed_seconds,
    window_batch_count,
    mismatch_count=0,
):
    now = _now_utc()
    active_processing_seconds = max(_safe_float(run.get('active_processing_seconds')), 0.0)
    active_processing_seconds += max(_safe_float(window_elapsed_seconds), 0.0)
    batch_count = _safe_int(run.get('batch_count'))
    recent_batches = list(run.get('recent_batches') or [])[-9:]
    recent_batches.append({
        'batch_number': completed_batches,
        'batch_count': _safe_int(window_batch_count),
        'row_count': _safe_int(window_rows),
        'elapsed_seconds': round(_safe_float(window_elapsed_seconds), 3),
        'completed_at': now.isoformat(),
    })
    is_schema_discovery_window = _is_schema_discovery_progress_window(
        run,
        completed_batches,
        window_batch_count,
    )
    throughput = _calculate_window_throughput(
        run,
        processed_rows,
        0 if is_schema_discovery_window else window_rows,
        0 if is_schema_discovery_window else window_elapsed_seconds,
        now,
    )
    run.update({
        'completed_batches': completed_batches,
        'processed_rows': processed_rows,
        'processed_chunk_count': completed_batches,
        'updated_at': now.isoformat(),
        'last_heartbeat_at': now.isoformat(),
        'active_processing_seconds': round(active_processing_seconds, 3),
        'effective_batch_concurrency': _safe_int(window_batch_count),
        'mismatch_count': _safe_int(run.get('mismatch_count')) + _safe_int(mismatch_count),
        'last_message': f"Processed structured export batch {completed_batches} of {batch_count}",
        'recent_batches': recent_batches,
    })
    run.update(_build_generation_progress_contract_fields(run, completed_batches, processed_rows))
    run.update(throughput)
    return _replace_claimed_run(run)


def _log_progress_if_due(run, last_logged_at):
    now_monotonic = time.monotonic()
    if last_logged_at and now_monotonic - last_logged_at < TABULAR_EXPORT_PROGRESS_LOG_INTERVAL_SECONDS:
        return last_logged_at

    batch_count = _safe_int(run.get('batch_count'))
    completed_batches = _safe_int(run.get('completed_batches'))
    progress_percent = round((completed_batches / batch_count) * 100, 2) if batch_count else 0.0
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Background export progress',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'source_file_name': run.get('source_file_name'),
            'output_format': run.get('output_format'),
            'completed_batches': completed_batches,
            'batch_count': batch_count,
            'processed_rows': run.get('processed_rows'),
            'row_count': run.get('row_count'),
            'progress_percent': progress_percent,
            'estimated_remaining_seconds': run.get('estimated_remaining_seconds'),
            'rows_per_minute': run.get('rows_per_minute'),
            'batch_concurrency': run.get('batch_concurrency'),
            'effective_batch_concurrency': run.get('effective_batch_concurrency'),
            'active_batch_count': run.get('active_batch_count'),
            'pending_batch_count': run.get('pending_batch_count'),
            'checkpointing_batch_count': run.get('checkpointing_batch_count'),
            'mismatch_count': run.get('mismatch_count'),
        },
        debug_only=True,
    )
    return now_monotonic


def _write_ordered_output_stream(run, output_stream):
    user_id = run.get('user_id')
    conversation_id = run.get('conversation_id')
    run_id = run.get('id')
    batch_count = _safe_int(run.get('batch_count'))
    expected_row_count = _safe_int(run.get('row_count'))
    output_format = str(run.get('output_format') or 'json').strip().lower() or 'json'
    output_schema = list(run.get('output_schema') or [])
    public_output_schema = _get_tabular_run_serialized_public_schema(run)
    if not output_schema:
        raise ValueError('Generated output schema is missing')
    if not public_output_schema:
        raise ValueError('Generated public output schema is missing')
    if TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD not in output_schema:
        raise ValueError('Generated output schema is missing source row order')

    csv_writer = None
    safe_output_schema = None
    if output_format == 'csv':
        safe_output_schema = build_safe_csv_headers(public_output_schema)
        csv_writer = csv.DictWriter(output_stream, fieldnames=safe_output_schema, lineterminator='\n')
        csv_writer.writeheader()
    elif output_format == 'xml':
        output_stream.write('<?xml version="1.0" encoding="UTF-8"?>\n<GeneratedOutput>\n')
    else:
        output_stream.write('[\n')

    written_row_count = 0
    expected_source_row_number = 1
    for batch_number in range(1, batch_count + 1):
        batch_blob_path = _output_blob_path(user_id, conversation_id, run_id, batch_number)
        _validate_tabular_output_checkpoint_metadata(run, batch_blob_path, batch_number)
        batch_entries = _download_json_blob(batch_blob_path)
        if not isinstance(batch_entries, list):
            raise ValueError(f'Output checkpoint {batch_number}/{batch_count} was not a JSON array')

        for batch_row_index, entry in enumerate(batch_entries, start=1):
            if not isinstance(entry, dict):
                raise ValueError(
                    f'Output checkpoint {batch_number}/{batch_count} row {batch_row_index} was not an object'
                )
            if set(entry) != set(output_schema):
                raise ValueError(
                    f'Output checkpoint {batch_number}/{batch_count} row {batch_row_index} has schema drift'
                )

            source_row_number = _safe_int(entry.get(TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD))
            if source_row_number != expected_source_row_number:
                raise ValueError(
                    f'Source row order gap or overlap: expected {expected_source_row_number}, '
                    f'found {source_row_number}'
                )
            ordered_entry = {
                field_name: entry.get(field_name)
                for field_name in output_schema
            }
            public_entry = project_structured_deliverable_row(
                ordered_entry,
                public_output_schema,
                require_all_fields=True,
            )
            if csv_writer:
                csv_writer.writerow({
                    safe_field_name: _serialize_generated_output_value(public_entry.get(field_name))
                    for field_name, safe_field_name in zip(public_output_schema, safe_output_schema)
                })
            elif output_format == 'xml':
                _write_generated_xml_row(output_stream, public_entry)
            else:
                if written_row_count:
                    output_stream.write(',\n')
                output_stream.write(json.dumps(public_entry, default=str, ensure_ascii=False))

            written_row_count += 1
            expected_source_row_number += 1

    if output_format == 'xml':
        output_stream.write('</GeneratedOutput>\n')
    elif output_format != 'csv':
        output_stream.write('\n]\n')
    if written_row_count != expected_row_count:
        raise ValueError(
            f'Final output row count {written_row_count} does not match expected count {expected_row_count}'
        )
    return written_row_count


def _build_structured_export_preview_rows(run):
    output_schema = list((run or {}).get('output_schema') or [])
    public_output_schema = _get_tabular_run_serialized_public_schema(run)
    if not output_schema:
        return []
    if not public_output_schema:
        return []

    output_format = str((run or {}).get('output_format') or 'json').strip().lower() or 'json'
    preview_schema = (
        build_safe_csv_headers(public_output_schema)
        if output_format == 'csv'
        else public_output_schema
    )
    preview_rows = []
    preview_char_count = 0
    expected_source_row_number = 1
    batch_count = _safe_int((run or {}).get('batch_count'))
    for batch_number in range(1, batch_count + 1):
        batch_blob_path = _output_blob_path(
            (run or {}).get('user_id'),
            (run or {}).get('conversation_id'),
            (run or {}).get('id'),
            batch_number,
        )
        _validate_tabular_output_checkpoint_metadata(run, batch_blob_path, batch_number)
        batch_entries = _download_json_blob(batch_blob_path)
        if not isinstance(batch_entries, list):
            raise ValueError(f'Output checkpoint {batch_number}/{batch_count} was not a JSON array')

        for batch_row_index, entry in enumerate(batch_entries, start=1):
            if not isinstance(entry, dict) or set(entry) != set(output_schema):
                raise ValueError(
                    f'Output checkpoint {batch_number}/{batch_count} row {batch_row_index} has schema drift'
                )
            source_row_number = _safe_int(entry.get(TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD))
            if source_row_number != expected_source_row_number:
                raise ValueError(
                    f'Source row order gap or overlap: expected {expected_source_row_number}, '
                    f'found {source_row_number}'
                )

            preview_row = {}
            public_entry = project_structured_deliverable_row(
                entry,
                public_output_schema,
                require_all_fields=True,
            )
            for field_name, preview_field_name in zip(public_output_schema, preview_schema):
                rendered_value = _serialize_generated_output_value(public_entry.get(field_name))
                if len(rendered_value) > TABULAR_EXPORT_ARTIFACT_PREVIEW_CELL_MAX_CHARS:
                    rendered_value = (
                        f'{rendered_value[:TABULAR_EXPORT_ARTIFACT_PREVIEW_CELL_MAX_CHARS - 3]}...'
                    )
                preview_row[preview_field_name] = rendered_value

            preview_row_char_count = len(json.dumps(preview_row, ensure_ascii=False, separators=(',', ':')))
            if (
                preview_rows
                and preview_char_count + preview_row_char_count > TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_CHARS
            ):
                return preview_rows
            preview_rows.append(preview_row)
            preview_char_count += preview_row_char_count
            expected_source_row_number += 1
            if len(preview_rows) >= TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_ROWS:
                return preview_rows

    return preview_rows


def _build_artifact_metadata(
    uploaded_message,
    generated_file_name,
    output_format,
    preview_rows=None,
    preview_text='',
    suppress_assistant_text=False,
):
    uploaded_message = uploaded_message or {}
    normalized_preview_rows = list(preview_rows or [])[:TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_ROWS]
    return {
        'artifact_message_id': uploaded_message.get('id'),
        'file_name': uploaded_message.get('file_name') or generated_file_name,
        'blob_container': uploaded_message.get('blob_container'),
        'blob_path': uploaded_message.get('blob_path'),
        'capability': uploaded_message.get('capability') or 'tabular',
        'output_format': uploaded_message.get('output_format') or output_format,
        'preview_rows': normalized_preview_rows,
        'preview_columns': list(normalized_preview_rows[0]) if normalized_preview_rows else [],
        'preview_text': str(preview_text or '')[:TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_CHARS],
        'suppress_assistant_text': bool(suppress_assistant_text),
    }


def _publish_structured_export_artifact(run):
    output_format = normalize_generated_output_format(run.get('output_format'))
    generated_file_name = run.get('generated_file_name') or _build_generated_file_name(
        run.get('source_file_name'),
        output_format,
    )
    with tempfile.SpooledTemporaryFile(
        max_size=TABULAR_EXPORT_FINAL_SPOOL_MAX_MEMORY_BYTES,
        mode='w+b',
    ) as binary_output_stream:
        text_output_stream = io.TextIOWrapper(
            binary_output_stream,
            encoding='utf-8',
            newline='',
            write_through=True,
        )
        try:
            output_entry_count = _write_ordered_output_stream(run, text_output_stream)
            post_run_summary = _build_compact_post_run_summary(run)
            _authorize_tabular_export_run_execution(run)
            _raise_if_tabular_export_canceled(run)
            if not run.get('publishing_started_at'):
                run.update({
                    'publishing_started_at': _now_iso(),
                    'last_message': 'Final validation passed; publishing the generated artifact',
                })
                run = _replace_claimed_run(run)
            _authorize_tabular_export_run_execution(run)
            _revalidate_tabular_source_version_for_publication(run)
            text_output_stream.flush()
            output_size = binary_output_stream.tell()
            binary_output_stream.seek(0)
            upload_result = upload_generated_analysis_artifact_stream_for_user(
                current_user_id=run.get('user_id'),
                conversation_id=run.get('conversation_id'),
                file_name=generated_file_name,
                file_stream=binary_output_stream,
                file_size=output_size,
                capability='tabular',
                output_format=output_format,
                summary=post_run_summary,
                artifact_idempotency_key=f"tabular-generated-output:{run.get('id')}",
            )
            _raise_if_tabular_export_canceled(run)
        finally:
            text_output_stream.detach()

    uploaded_message = upload_result.get('message') or {}
    return run, uploaded_message, post_run_summary, output_entry_count, output_format, generated_file_name


def _complete_run(run):
    run, uploaded_message, post_run_summary, output_entry_count, output_format, generated_file_name = (
        _publish_structured_export_artifact(run)
    )
    artifact_preview_rows = _build_structured_export_preview_rows(run)
    now = _now_iso()
    run.update({
        'status': TABULAR_EXPORT_STATUS_COMPLETED,
        'updated_at': now,
        'completed_at': now,
        'generation_completed_at': now,
        'last_heartbeat_at': now,
        'processed_rows': output_entry_count,
        'completed_batches': _safe_int(run.get('batch_count')),
        'processed_chunk_count': _safe_int(run.get('batch_count')),
        'failed_chunk_count': 0,
        'last_message': 'Background structured export completed',
        'post_run_summary': post_run_summary,
        'generated_file_name': uploaded_message.get('file_name') or generated_file_name,
        'final_artifact': _build_artifact_metadata(
            uploaded_message,
            generated_file_name,
            output_format,
            preview_rows=artifact_preview_rows,
            suppress_assistant_text=True,
        ),
        'estimated_remaining_seconds': 0,
    })
    run.update(_build_generation_progress_contract_fields(
        run,
        run.get('batch_count'),
        output_entry_count,
    ))
    run['performance_summary'] = _build_tabular_generation_performance_summary(run, completed_at=now)
    run = _replace_claimed_run(run)
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Background export completed',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'source_file_name': run.get('source_file_name'),
            'output_format': output_format,
            'row_count': output_entry_count,
            'batch_count': run.get('batch_count'),
            'completed_batch_count': run.get('completed_batch_count'),
            'checkpointed_row_count': run.get('checkpointed_row_count'),
            'generation_contract_version': run.get('generation_contract_version'),
            'response_protocol_version': run.get('response_protocol_version'),
            'artifact_message_id': uploaded_message.get('id'),
            'generated_file_name': uploaded_message.get('file_name') or generated_file_name,
            **run.get('performance_summary', {}),
        },
        level=logging.INFO,
    )
    return run


def _build_analysis_summary_markdown(run, final_summary):
    final_summary = final_summary if isinstance(final_summary, dict) else {}
    markdown_parts = [
        '# Tabular Analysis',
        '',
        final_summary.get('summary') or 'Analysis completed.',
        '',
    ]
    findings = _normalize_analysis_findings(final_summary.get('findings'))
    if findings:
        markdown_parts.extend(['## Findings', ''])
        markdown_parts.extend([f'- {finding}' for finding in findings])
        markdown_parts.append('')

    counts = _normalize_analysis_counts(final_summary.get('counts'))
    if counts:
        markdown_parts.extend(['## Counts', ''])
        for count_key, count_value in counts.items():
            markdown_parts.append(f'- {count_key}: {count_value}')
        markdown_parts.append('')

    notable_rows = _normalize_analysis_notable_rows(final_summary.get('notable_rows'))
    if notable_rows:
        markdown_parts.extend(['## Notable Rows', ''])
        for notable_row in notable_rows:
            identity = str(notable_row.get('source_row_identity') or '').strip()
            identity_suffix = f" ({identity})" if identity else ''
            markdown_parts.append(
                f"- Row {notable_row.get('source_row_number')}{identity_suffix}: {notable_row.get('note')}"
            )
        markdown_parts.append('')

    markdown_parts.extend([
        '## Coverage',
        '',
        f"- Source file: {run.get('source_file_name') or 'unknown file'}",
        f"- Rows analyzed: {_safe_int(final_summary.get('row_count'), default=_safe_int(run.get('row_count'))):,}",
        f"- Source row range: {final_summary.get('source_row_start') or 1} to {final_summary.get('source_row_end') or run.get('row_count')}",
        f"- Chunks analyzed: {_safe_int(run.get('batch_count')):,}",
        f"- Run id: {run.get('id')}",
        '',
    ])
    return '\n'.join(markdown_parts)


def _publish_analysis_artifact(run, final_summary):
    generated_file_name = (
        run.get('analysis_generated_file_name')
        or run.get('generated_file_name')
        or _build_analysis_file_name(run.get('source_file_name'))
    )
    if not str(generated_file_name or '').lower().endswith('.md'):
        generated_file_name = _build_analysis_file_name(
            run.get('source_file_name')
        )
    final_summary = _normalize_analysis_summary_payload(
        final_summary,
        child_summaries=[final_summary] if isinstance(final_summary, dict) else [],
    )
    _upload_json_blob(
        _analysis_final_blob_path(run.get('user_id'), run.get('conversation_id'), run.get('id')),
        final_summary,
        metadata={
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'tabular_analysis_final_summary': 'true',
        },
    )
    markdown_content = _build_analysis_summary_markdown(run, final_summary)
    markdown_bytes = markdown_content.encode('utf-8')

    _authorize_tabular_export_run_execution(run)
    _raise_if_tabular_export_canceled(run)
    if not run.get('publishing_started_at'):
        run.update({
            'publishing_started_at': _now_iso(),
            'analysis_phase': 'publishing',
            'last_message': 'Final analysis reduction complete; publishing the answer artifact',
        })
        run = _replace_claimed_run(run)
    _authorize_tabular_export_run_execution(run)
    _revalidate_tabular_source_version_for_publication(run)

    with tempfile.SpooledTemporaryFile(
        max_size=TABULAR_EXPORT_FINAL_SPOOL_MAX_MEMORY_BYTES,
        mode='w+b',
    ) as binary_output_stream:
        binary_output_stream.write(markdown_bytes)
        binary_output_stream.seek(0)
        upload_result = upload_generated_analysis_artifact_stream_for_user(
            current_user_id=run.get('user_id'),
            conversation_id=run.get('conversation_id'),
            file_name=generated_file_name,
            file_stream=binary_output_stream,
            file_size=len(markdown_bytes),
            capability='tabular',
            output_format='md',
            summary=final_summary.get('summary'),
            artifact_idempotency_key=f"tabular-hierarchical-analysis:{run.get('id')}",
        )
        _raise_if_tabular_export_canceled(run)

    uploaded_message = upload_result.get('message') or {}
    return run, uploaded_message, final_summary, generated_file_name


def _complete_analysis_run(run, final_summary):
    run, uploaded_message, final_summary, generated_file_name = _publish_analysis_artifact(run, final_summary)
    artifact_preview_text = _build_analysis_summary_markdown(run, final_summary)
    now = _now_iso()
    run.update({
        'status': TABULAR_EXPORT_STATUS_COMPLETED,
        'updated_at': now,
        'completed_at': now,
        'generation_completed_at': now,
        'last_heartbeat_at': now,
        'analysis_phase': 'completed',
        'processed_rows': _safe_int(final_summary.get('row_count'), default=_safe_int(run.get('row_count'))),
        'completed_batches': _safe_int(run.get('batch_count')),
        'processed_chunk_count': _safe_int(run.get('batch_count')),
        'failed_chunk_count': 0,
        'last_message': 'Background tabular analysis completed',
        'post_run_summary': final_summary.get('summary'),
        'generated_file_name': uploaded_message.get('file_name') or generated_file_name,
        'output_format': 'md',
        'final_artifact': _build_artifact_metadata(
            uploaded_message,
            generated_file_name,
            'md',
            preview_text=artifact_preview_text,
            suppress_assistant_text=True,
        ),
        'estimated_remaining_seconds': 0,
    })
    run.update(_build_generation_progress_contract_fields(
        run,
        run.get('batch_count'),
        run.get('processed_rows'),
    ))
    run['performance_summary'] = _build_tabular_generation_performance_summary(run, completed_at=now)
    run = _replace_claimed_run(run)
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Background tabular analysis completed',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'source_file_name': run.get('source_file_name'),
            'row_count': run.get('processed_rows'),
            'batch_count': run.get('batch_count'),
            'artifact_message_id': uploaded_message.get('id'),
            'generated_file_name': uploaded_message.get('file_name') or generated_file_name,
            **run.get('performance_summary', {}),
        },
        level=logging.INFO,
    )
    return run


def _publish_combined_structured_export_phase(run):
    if isinstance(run.get('structured_export_artifact'), dict) and run.get('structured_export_artifact'):
        return run

    run, uploaded_message, post_run_summary, output_entry_count, output_format, generated_file_name = (
        _publish_structured_export_artifact(run)
    )
    structured_artifact = _build_artifact_metadata(
        uploaded_message,
        generated_file_name,
        output_format,
        preview_rows=_build_structured_export_preview_rows(run),
        suppress_assistant_text=True,
    )
    now = _now_iso()
    run.update({
        'updated_at': now,
        'last_heartbeat_at': now,
        'processed_rows': output_entry_count,
        'completed_batches': _safe_int(run.get('batch_count')),
        'processed_chunk_count': _safe_int(run.get('batch_count')),
        'failed_chunk_count': 0,
        'analysis_phase': 'reducing',
        'last_message': 'Combined structured export published; reducing tabular analysis summaries',
        'post_run_export_summary': post_run_summary,
        'generated_file_name': uploaded_message.get('file_name') or generated_file_name,
        'structured_export_artifact': structured_artifact,
        'final_artifact': structured_artifact,
        'estimated_remaining_seconds': None,
    })
    run = _replace_claimed_run(run)
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Combined structured export artifact published',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'source_file_name': run.get('source_file_name'),
            'output_format': output_format,
            'row_count': output_entry_count,
            'batch_count': run.get('batch_count'),
            'artifact_message_id': uploaded_message.get('id'),
            'generated_file_name': uploaded_message.get('file_name') or generated_file_name,
        },
        level=logging.INFO,
    )
    return run


def _complete_combined_analysis_run(run, final_summary):
    existing_analysis_artifact = run.get('analysis_artifact') if isinstance(run.get('analysis_artifact'), dict) else {}
    if existing_analysis_artifact:
        final_summary = _normalize_analysis_summary_payload(
            final_summary,
            child_summaries=[final_summary] if isinstance(final_summary, dict) else [],
        )
        analysis_artifact = existing_analysis_artifact
        generated_file_name = existing_analysis_artifact.get('file_name') or run.get('analysis_generated_file_name')
    else:
        run, uploaded_message, final_summary, generated_file_name = _publish_analysis_artifact(run, final_summary)
        analysis_artifact = _build_artifact_metadata(
            uploaded_message,
            generated_file_name,
            'md',
            preview_text=_build_analysis_summary_markdown(run, final_summary),
            suppress_assistant_text=True,
        )

    structured_artifact = run.get('structured_export_artifact') or run.get('final_artifact') or {}
    now = _now_iso()
    run.update({
        'status': TABULAR_EXPORT_STATUS_COMPLETED,
        'updated_at': now,
        'completed_at': now,
        'generation_completed_at': now,
        'last_heartbeat_at': now,
        'analysis_phase': 'completed',
        'processed_rows': _safe_int(final_summary.get('row_count'), default=_safe_int(run.get('row_count'))),
        'completed_batches': _safe_int(run.get('batch_count')),
        'processed_chunk_count': _safe_int(run.get('batch_count')),
        'failed_chunk_count': 0,
        'last_message': 'Background combined tabular analysis and export completed',
        'post_run_summary': final_summary.get('summary'),
        'analysis_generated_file_name': uploaded_message.get('file_name') or generated_file_name,
        'structured_export_artifact': structured_artifact,
        'analysis_artifact': analysis_artifact,
        'combined_artifacts': [
            artifact for artifact in (structured_artifact, analysis_artifact) if artifact
        ],
        'final_artifact': structured_artifact or analysis_artifact,
        'estimated_remaining_seconds': 0,
    })
    run.update(_build_generation_progress_contract_fields(
        run,
        run.get('batch_count'),
        run.get('processed_rows'),
    ))
    run['performance_summary'] = _build_tabular_generation_performance_summary(run, completed_at=now)
    run = _replace_claimed_run(run)
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Background combined tabular run completed',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'source_file_name': run.get('source_file_name'),
            'row_count': run.get('processed_rows'),
            'batch_count': run.get('batch_count'),
            'structured_artifact_message_id': structured_artifact.get('artifact_message_id'),
            'analysis_artifact_message_id': analysis_artifact.get('artifact_message_id'),
            **run.get('performance_summary', {}),
        },
        level=logging.INFO,
    )
    return run


def _load_input_batch_rows(run, input_batches, user_id, run_id, batch_number, batch_count):
    if isinstance(input_batches, list):
        try:
            batch_rows = input_batches[batch_number - 1]
        except IndexError as exc:
            raise ValueError(f'Input batch {batch_number}/{batch_count} is missing') from exc
    else:
        input_blob_path = _input_blob_path(
            user_id,
            run.get('conversation_id'),
            run_id,
            batch_number,
        )
        batch_rows = _download_json_blob(input_blob_path)
    if not isinstance(batch_rows, list):
        raise ValueError(f'Input batch {batch_number}/{batch_count} was not a JSON array')
    return batch_rows


def _build_batch_window(
    run,
    input_batches,
    user_id,
    run_id,
    window_start,
    window_end,
    batch_count,
    durable_output_batches=None,
):
    batch_results = {}
    batch_requests = []
    listed_output_batches = durable_output_batches if durable_output_batches is not None else None
    for batch_number in range(window_start, window_end + 1):
        batch_started_at = time.monotonic()
        output_blob_path = _output_blob_path(
            user_id,
            run.get('conversation_id'),
            run_id,
            batch_number,
        )
        output_checkpoint_exists = (
            batch_number in listed_output_batches
            if listed_output_batches is not None
            else _blob_exists(output_blob_path)
        )

        if output_checkpoint_exists and not run.get('regenerate_legacy_output_checkpoints'):
            _validate_tabular_output_checkpoint_metadata(run, output_blob_path, batch_number)
            batch_entries = _download_json_blob(output_blob_path)
            expected_output_schema = set(run.get('output_schema') or [])
            if not isinstance(batch_entries, list) or not batch_entries:
                raise ValueError(f'Output checkpoint {batch_number}/{batch_count} is empty or malformed')
            for checkpoint_row_index, checkpoint_entry in enumerate(batch_entries, start=1):
                if not isinstance(checkpoint_entry, dict):
                    raise ValueError(
                        f'Output checkpoint {batch_number}/{batch_count} row {checkpoint_row_index} is not an object'
                    )
                if set(checkpoint_entry) != expected_output_schema:
                    raise ValueError(
                        f'Output checkpoint {batch_number}/{batch_count} row {checkpoint_row_index} has schema drift'
                    )
            summary_blob_path = _output_summary_blob_path(
                user_id,
                run.get('conversation_id'),
                run_id,
                batch_number,
            )
            if isinstance(batch_entries, list) and not _blob_exists(summary_blob_path):
                _upload_json_blob(
                    summary_blob_path,
                    _build_generated_batch_summary(batch_entries),
                    metadata=_build_tabular_output_checkpoint_metadata(run, {
                        'run_id': run_id,
                        'conversation_id': run.get('conversation_id'),
                        'batch_number': batch_number,
                        'generated_output_summary': 'true',
                    }),
                )
            batch_results[batch_number] = {
                'batch_number': batch_number,
                'batch_row_count': len(batch_entries) if isinstance(batch_entries, list) else 0,
                'elapsed_seconds': time.monotonic() - batch_started_at,
                'mismatch_count': 0,
                'from_checkpoint': True,
            }
            continue

        batch_rows = _load_input_batch_rows(run, input_batches, user_id, run_id, batch_number, batch_count)
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Building background structured export batch',
            {
                'run_id': run_id,
                'source_file_name': run.get('source_file_name'),
                'output_format': run.get('output_format'),
                'batch_number': batch_number,
                'batch_count': batch_count,
                'row_count': len(batch_rows),
            },
            debug_only=True,
        )
        batch_requests.append({
            'batch_number': batch_number,
            'rows': batch_rows,
        })
    return batch_results, batch_requests


def _build_analysis_batch_window(run, input_batches, user_id, run_id, window_start, window_end, batch_count):
    batch_results = {}
    batch_requests = []
    for batch_number in range(window_start, window_end + 1):
        batch_started_at = time.monotonic()
        output_blob_path = _output_blob_path(
            user_id,
            run.get('conversation_id'),
            run_id,
            batch_number,
        )
        if _blob_exists(output_blob_path):
            analysis_summary = _download_json_blob(output_blob_path)
            if not isinstance(analysis_summary, dict):
                raise ValueError(f'Analysis checkpoint {batch_number}/{batch_count} was not a JSON object')
            batch_results[batch_number] = {
                'batch_number': batch_number,
                'analysis_summary': analysis_summary,
                'batch_row_count': _safe_int(analysis_summary.get('row_count')),
                'elapsed_seconds': time.monotonic() - batch_started_at,
                'mismatch_count': 0,
                'from_checkpoint': True,
            }
            continue

        batch_rows = _load_input_batch_rows(run, input_batches, user_id, run_id, batch_number, batch_count)
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Building background analysis chunk',
            {
                'run_id': run_id,
                'source_file_name': run.get('source_file_name'),
                'batch_number': batch_number,
                'batch_count': batch_count,
                'row_count': len(batch_rows),
            },
            debug_only=True,
        )
        batch_requests.append({
            'batch_number': batch_number,
            'rows': batch_rows,
        })
    return batch_results, batch_requests


def _build_combined_batch_window(run, input_batches, user_id, run_id, window_start, window_end, batch_count):
    batch_results = {}
    batch_requests = []
    for batch_number in range(window_start, window_end + 1):
        batch_started_at = time.monotonic()
        output_blob_path = _output_blob_path(
            user_id,
            run.get('conversation_id'),
            run_id,
            batch_number,
        )
        analysis_blob_path = _analysis_chunk_summary_blob_path(
            user_id,
            run.get('conversation_id'),
            run_id,
            batch_number,
        )

        if _blob_exists(output_blob_path) and _blob_exists(analysis_blob_path):
            _validate_tabular_output_checkpoint_metadata(run, output_blob_path, batch_number)
            _validate_tabular_output_checkpoint_metadata(run, analysis_blob_path, batch_number)
            batch_entries = _download_json_blob(output_blob_path)
            analysis_summary = _download_json_blob(analysis_blob_path)
            expected_output_schema = set(run.get('output_schema') or [])
            if not isinstance(batch_entries, list) or not batch_entries:
                raise ValueError(f'Combined output checkpoint {batch_number}/{batch_count} is empty or malformed')
            if not isinstance(analysis_summary, dict):
                raise ValueError(f'Combined analysis checkpoint {batch_number}/{batch_count} was not a JSON object')
            for checkpoint_row_index, checkpoint_entry in enumerate(batch_entries, start=1):
                if not isinstance(checkpoint_entry, dict):
                    raise ValueError(
                        f'Combined output checkpoint {batch_number}/{batch_count} row {checkpoint_row_index} is not an object'
                    )
                if set(checkpoint_entry) != expected_output_schema:
                    raise ValueError(
                        f'Combined output checkpoint {batch_number}/{batch_count} row {checkpoint_row_index} has schema drift'
                    )
            batch_results[batch_number] = {
                'batch_number': batch_number,
                'batch_row_count': len(batch_entries),
                'analysis_summary': analysis_summary,
                'elapsed_seconds': time.monotonic() - batch_started_at,
                'mismatch_count': 0,
                'from_checkpoint': True,
            }
            continue

        batch_rows = _load_input_batch_rows(run, input_batches, user_id, run_id, batch_number, batch_count)
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Building background combined tabular chunk',
            {
                'run_id': run_id,
                'source_file_name': run.get('source_file_name'),
                'output_format': run.get('output_format'),
                'batch_number': batch_number,
                'batch_count': batch_count,
                'row_count': len(batch_rows),
            },
            debug_only=True,
        )
        batch_requests.append({
            'batch_number': batch_number,
            'rows': batch_rows,
        })
    return batch_results, batch_requests


def _record_shadow_tabular_generation_plan_comparison(run, actual_output_schema):
    if _get_tabular_generation_plan_mode(run) != 'shadow':
        return False
    if (run or {}).get('plan_status') != 'ready' or (run or {}).get('plan_shadow_comparison'):
        return False

    plan_blob_path = str((run or {}).get('plan_blob_path') or '').strip()
    if not plan_blob_path:
        raise ValueError('Shadow generation plan path is missing')
    plan = _download_json_blob(plan_blob_path)
    _validate_tabular_generation_plan(plan, run)
    if plan.get('plan_hash') != (run or {}).get('plan_hash'):
        raise ValueError('Shadow generation plan hash does not match the run record')

    planned_schema = _get_tabular_generation_plan_output_schema(plan)
    actual_schema = list(actual_output_schema or [])
    planned_field_set = set(planned_schema)
    actual_field_set = set(actual_schema)
    additions = [field_name for field_name in actual_schema if field_name not in planned_field_set]
    omissions = [field_name for field_name in planned_schema if field_name not in actual_field_set]
    reorderings = [
        field_name
        for field_name in actual_schema
        if field_name in planned_field_set
        and actual_schema.index(field_name) != planned_schema.index(field_name)
    ]
    comparison = {
        'agreement': actual_schema == planned_schema,
        'planned_field_count': len(planned_schema),
        'actual_field_count': len(actual_schema),
        'additions': additions[:TABULAR_GENERATION_PLAN_MAX_FIELDS],
        'omissions': omissions[:TABULAR_GENERATION_PLAN_MAX_FIELDS],
        'reorderings': reorderings[:TABULAR_GENERATION_PLAN_MAX_FIELDS],
    }
    run.update({
        'plan_shadow_comparison': comparison,
        'plan_shadow_compared_at': _now_iso(),
    })
    log_event(
        '[TABULAR_GENERATION_PLAN] Shadow schema comparison completed',
        {
            'run_id': (run or {}).get('id'),
            'agreement': comparison['agreement'],
            'planned_field_count': comparison['planned_field_count'],
            'actual_field_count': comparison['actual_field_count'],
            'addition_count': len(additions),
            'omission_count': len(omissions),
            'reordering_count': len(reorderings),
        },
        debug_only=True,
    )
    return True


def _load_active_compact_generation_plan(run):
    if not _is_compact_row_array_protocol((run or {}).get('response_protocol_version')):
        return None
    if _get_tabular_generation_plan_mode(run) != 'active' or (run or {}).get('plan_status') != 'ready':
        raise ValueError('Compact row protocol requires a ready active generation plan')
    plan_blob_path = str((run or {}).get('plan_blob_path') or '').strip()
    if not plan_blob_path:
        raise ValueError('Compact row protocol plan path is missing')
    plan = _download_json_blob(plan_blob_path)
    _validate_tabular_generation_plan(plan, run)
    if plan.get('plan_hash') != (run or {}).get('plan_hash'):
        raise ValueError('Compact row protocol plan hash does not match the run record')
    return plan


def _checkpoint_generated_batch_results(run, generated_results):
    _raise_if_tabular_export_canceled(run)
    batch_results = {}
    expected_output_schema = list(run.get('output_schema') or [])
    ordered_results = sorted(generated_results, key=lambda result: result['batch_number'])
    for generated_result in ordered_results:
        generated_output_schema = list(generated_result.get('output_schema') or [])
        if not expected_output_schema:
            expected_output_schema = generated_output_schema
        if generated_output_schema != expected_output_schema:
            raise ValueError(
                f"Generated output schema drifted in batch {generated_result['batch_number']}"
            )

    if not expected_output_schema:
        raise ValueError('Generated output schema could not be established')
    run_contract_changed = False
    if list(run.get('output_schema') or []) != expected_output_schema:
        run['output_schema'] = expected_output_schema
        run['public_output_schema'] = _get_tabular_run_public_output_schema(run)
        run['internal_checkpoint_schema'] = _get_tabular_run_internal_checkpoint_schema(run)
        run_contract_changed = True
    if _record_shadow_tabular_generation_plan_comparison(run, expected_output_schema):
        run_contract_changed = True
    if run_contract_changed:
        persisted_run = _replace_claimed_run(run)
        run.clear()
        run.update(persisted_run)

    for generated_result in ordered_results:
        _raise_if_tabular_export_canceled(run)
        batch_number = generated_result['batch_number']
        output_blob_path = _output_blob_path(
            run.get('user_id'),
            run.get('conversation_id'),
            run.get('id'),
            batch_number,
        )
        checkpoint_started_at = time.monotonic()
        try:
            _upload_json_blob(
                output_blob_path,
                generated_result['batch_entries'],
                metadata=_build_tabular_output_checkpoint_metadata(run, {
                    'run_id': run.get('id'),
                    'conversation_id': run.get('conversation_id'),
                    'batch_number': batch_number,
                    'generated_output': 'true',
                    'lease_generation': run.get('lease_generation'),
                }),
                overwrite=bool(run.get('regenerate_legacy_output_checkpoints')),
            )
        except ResourceExistsError:
            _validate_tabular_output_checkpoint_metadata(run, output_blob_path, batch_number)
            checkpoint_entries = _download_json_blob(output_blob_path)
            if (
                not isinstance(checkpoint_entries, list)
                or len(checkpoint_entries) != generated_result['batch_row_count']
                or any(
                    not isinstance(entry, dict) or set(entry) != set(expected_output_schema)
                    for entry in checkpoint_entries
                )
            ):
                raise ValueError(
                    f'Concurrent output checkpoint {batch_number} failed schema or row-count validation'
                )
            generated_result['batch_entries'] = checkpoint_entries
            generated_result['batch_summary'] = _build_generated_batch_summary(checkpoint_entries)
        _upload_json_blob(
            _output_summary_blob_path(
                run.get('user_id'),
                run.get('conversation_id'),
                run.get('id'),
                batch_number,
            ),
            generated_result.get('batch_summary') or _build_generated_batch_summary(
                generated_result['batch_entries']
            ),
            metadata=_build_tabular_output_checkpoint_metadata(run, {
                'run_id': run.get('id'),
                'conversation_id': run.get('conversation_id'),
                'batch_number': batch_number,
                'generated_output_summary': 'true',
            }),
        )
        checkpoint_seconds = time.monotonic() - checkpoint_started_at
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Background export batch checkpointed',
            {
                'event_name': 'batch_checkpointed',
                'run_id': run.get('id'),
                'conversation_id': run.get('conversation_id'),
                'user_id': run.get('user_id'),
                'batch_number': batch_number,
                'batch_row_count': generated_result['batch_row_count'],
                'checkpoint_seconds': round(checkpoint_seconds, 3),
                'response_protocol_version': run.get('response_protocol_version'),
                'plan_hash_present': bool(run.get('plan_hash')),
            },
            debug_only=True,
        )
        batch_results[batch_number] = {
            'batch_number': batch_number,
            'batch_row_count': generated_result['batch_row_count'],
            'elapsed_seconds': generated_result['elapsed_seconds'],
            'queue_wait_seconds': generated_result.get('queue_wait_seconds'),
            'model_latency_seconds': generated_result.get('model_latency_seconds'),
            'validation_seconds': generated_result.get('validation_seconds'),
            'input_char_count': generated_result.get('input_char_count'),
            'response_char_count': generated_result.get('response_char_count'),
            'input_token_count': generated_result.get('input_token_count'),
            'output_token_count': generated_result.get('output_token_count'),
            'total_token_count': generated_result.get('total_token_count'),
            'checkpoint_seconds': checkpoint_seconds,
            'mismatch_count': generated_result['mismatch_count'],
            'from_checkpoint': False,
        }
    return batch_results


def _checkpoint_combined_batch_results(run, generated_results):
    batch_results = _checkpoint_generated_batch_results(run, generated_results)
    ordered_results = sorted(generated_results, key=lambda result: result['batch_number'])
    for generated_result in ordered_results:
        _raise_if_tabular_export_canceled(run)
        batch_number = generated_result['batch_number']
        analysis_summary = generated_result.get('analysis_summary') or {}
        analysis_blob_path = _analysis_chunk_summary_blob_path(
            run.get('user_id'),
            run.get('conversation_id'),
            run.get('id'),
            batch_number,
        )
        try:
            _upload_json_blob(
                analysis_blob_path,
                analysis_summary,
                metadata=_build_tabular_output_checkpoint_metadata(run, {
                    'run_id': run.get('id'),
                    'conversation_id': run.get('conversation_id'),
                    'batch_number': batch_number,
                    'tabular_combined_analysis_summary': 'true',
                    'lease_generation': run.get('lease_generation'),
                }),
                overwrite=False,
            )
        except ResourceExistsError:
            _validate_tabular_output_checkpoint_metadata(run, analysis_blob_path, batch_number)
            checkpoint_summary = _download_json_blob(analysis_blob_path)
            if not isinstance(checkpoint_summary, dict):
                raise ValueError(f'Concurrent combined analysis checkpoint {batch_number} was malformed')
            analysis_summary = checkpoint_summary
        batch_results.setdefault(batch_number, {})['analysis_summary'] = analysis_summary
    return batch_results


def _checkpoint_analysis_batch_results(run, generated_results):
    _raise_if_tabular_export_canceled(run)
    batch_results = {}
    ordered_results = sorted(generated_results, key=lambda result: result['batch_number'])
    for generated_result in ordered_results:
        _raise_if_tabular_export_canceled(run)
        batch_number = generated_result['batch_number']
        analysis_summary = generated_result.get('analysis_summary') or {}
        output_blob_path = _output_blob_path(
            run.get('user_id'),
            run.get('conversation_id'),
            run.get('id'),
            batch_number,
        )
        try:
            _upload_json_blob(
                output_blob_path,
                analysis_summary,
                metadata={
                    'run_id': run.get('id'),
                    'conversation_id': run.get('conversation_id'),
                    'batch_number': batch_number,
                    'tabular_analysis_summary': 'true',
                    'lease_generation': run.get('lease_generation'),
                },
                overwrite=False,
            )
        except ResourceExistsError:
            checkpoint_summary = _download_json_blob(output_blob_path)
            if not isinstance(checkpoint_summary, dict):
                raise ValueError(f'Concurrent analysis checkpoint {batch_number} was malformed')
            analysis_summary = checkpoint_summary
        _upload_json_blob(
            _output_summary_blob_path(
                run.get('user_id'),
                run.get('conversation_id'),
                run.get('id'),
                batch_number,
            ),
            analysis_summary,
            metadata={
                'run_id': run.get('id'),
                'conversation_id': run.get('conversation_id'),
                'batch_number': batch_number,
                'tabular_analysis_summary': 'true',
            },
        )
        batch_results[batch_number] = {
            'batch_number': batch_number,
            'analysis_summary': analysis_summary,
            'batch_row_count': _safe_int(analysis_summary.get('row_count')),
            'elapsed_seconds': generated_result['elapsed_seconds'],
            'mismatch_count': generated_result.get('mismatch_count') or 0,
            'from_checkpoint': False,
        }
    return batch_results


def _build_passthrough_batch_results(run, batch_requests):
    """Create checkpoint entries directly when rows are already final export output."""
    expected_output_schema = list(run.get('output_schema') or [])
    generated_results = []
    for batch_request in batch_requests:
        batch_started_at = time.monotonic()
        batch_entries, output_schema = _normalize_generated_batch_entries(
            batch_request['rows'],
            batch_request['rows'],
            expected_output_schema=expected_output_schema,
        )
        if not expected_output_schema:
            expected_output_schema = output_schema
        generated_results.append({
            'batch_number': batch_request['batch_number'],
            'batch_entries': batch_entries,
            'batch_summary': _build_generated_batch_summary(batch_entries),
            'batch_row_count': len(batch_entries),
            'elapsed_seconds': time.monotonic() - batch_started_at,
            'mismatch_count': 0,
            'output_schema': output_schema,
        })
    return generated_results


def _advance_run_progress_for_window(run, batch_results, completed_batches, processed_rows, window_start, window_end):
    window_results = []
    window_rows = 0
    window_mismatch_count = 0
    for batch_number in range(window_start, window_end + 1):
        batch_result = batch_results.get(batch_number)
        if not batch_result:
            break
        window_results.append(batch_result)
        completed_batches = batch_number
        batch_rows = _safe_int(batch_result.get('batch_row_count'))
        processed_rows += batch_rows
        window_rows += batch_rows
        mismatch_count = _safe_int(batch_result.get('mismatch_count'))
        window_mismatch_count += mismatch_count
        if mismatch_count:
            run['retry_count'] = _safe_int(run.get('retry_count')) + max(mismatch_count - 1, 0)
    if window_results:
        generated_elapsed_seconds = [
            max(_safe_float(batch_result.get('elapsed_seconds')), 0.0)
            for batch_result in window_results
            if not batch_result.get('from_checkpoint')
        ]
        run = _update_run_progress(
            run,
            completed_batches,
            processed_rows,
            window_rows,
            max(generated_elapsed_seconds, default=0.0),
            len(window_results),
            mismatch_count=window_mismatch_count,
        )
    return run, completed_batches, processed_rows


def _advance_analysis_map_progress_for_window(run, batch_results, completed_batches, processed_rows, window_start, window_end):
    window_results = []
    window_rows = 0
    for batch_number in range(window_start, window_end + 1):
        batch_result = batch_results.get(batch_number)
        if not batch_result:
            break
        window_results.append(batch_result)
        completed_batches = batch_number
        batch_rows = _safe_int(batch_result.get('batch_row_count'))
        processed_rows += batch_rows
        window_rows += batch_rows
    if window_results:
        generated_elapsed_seconds = [
            max(_safe_float(batch_result.get('elapsed_seconds')), 0.0)
            for batch_result in window_results
            if not batch_result.get('from_checkpoint')
        ]
        run = _update_analysis_map_progress(
            run,
            completed_batches,
            processed_rows,
            window_rows,
            max(generated_elapsed_seconds, default=0.0),
            len(window_results),
        )
    return run, completed_batches, processed_rows


def _update_analysis_map_progress(
    run,
    completed_batches,
    processed_rows,
    window_rows,
    window_elapsed_seconds,
    window_batch_count,
):
    now = _now_utc()
    active_processing_seconds = max(_safe_float(run.get('active_processing_seconds')), 0.0)
    active_processing_seconds += max(_safe_float(window_elapsed_seconds), 0.0)
    batch_count = _safe_int(run.get('batch_count'))
    recent_batches = list(run.get('recent_batches') or [])[-9:]
    recent_batches.append({
        'batch_number': completed_batches,
        'batch_count': _safe_int(window_batch_count),
        'row_count': _safe_int(window_rows),
        'elapsed_seconds': round(_safe_float(window_elapsed_seconds), 3),
        'completed_at': now.isoformat(),
        'phase': 'map',
    })
    is_schema_discovery_window = _is_schema_discovery_progress_window(
        run,
        completed_batches,
        window_batch_count,
    )
    throughput = _calculate_window_throughput(
        run,
        processed_rows,
        0 if is_schema_discovery_window else window_rows,
        0 if is_schema_discovery_window else window_elapsed_seconds,
        now,
    )
    run.update({
        'completed_batches': completed_batches,
        'processed_rows': processed_rows,
        'processed_chunk_count': completed_batches,
        'analysis_phase': 'mapping',
        'updated_at': now.isoformat(),
        'last_heartbeat_at': now.isoformat(),
        'active_processing_seconds': round(active_processing_seconds, 3),
        'effective_batch_concurrency': _safe_int(window_batch_count),
        'last_message': f'Analyzed tabular chunk {completed_batches} of {batch_count}',
        'recent_batches': recent_batches,
    })
    run.update(_build_generation_progress_contract_fields(run, completed_batches, processed_rows))
    run.update(throughput)
    return _replace_claimed_run(run)


def _load_analysis_chunk_summaries(run):
    summaries = []
    batch_count = _safe_int(run.get('batch_count'))
    for batch_number in range(1, batch_count + 1):
        summary_blob_path = (
            _analysis_chunk_summary_blob_path(
                run.get('user_id'),
                run.get('conversation_id'),
                run.get('id'),
                batch_number,
            )
            if _is_tabular_combined_task(run.get('task_type'))
            else _output_blob_path(
                run.get('user_id'),
                run.get('conversation_id'),
                run.get('id'),
                batch_number,
            )
        )
        summary = _download_json_blob(summary_blob_path)
        if not isinstance(summary, dict):
            raise ValueError(f'Analysis checkpoint {batch_number}/{batch_count} was not a JSON object')
        summaries.append(summary)
    if len(summaries) != batch_count:
        raise ValueError('Analysis map phase did not produce every chunk summary')
    return summaries


def _update_analysis_reduce_progress(run, level_number, node_number, node_count, level_counts):
    now = _now_iso()
    run.update({
        'analysis_phase': 'reducing',
        'analysis_reduce_level': level_number,
        'analysis_reduce_node': node_number,
        'analysis_reduce_node_count': node_count,
        'analysis_reduce_plan': level_counts,
        'updated_at': now,
        'last_heartbeat_at': now,
        'last_message': f'Reducing tabular analysis level {level_number} node {node_number} of {node_count}',
    })
    return _replace_claimed_run(run)


def _run_analysis_reduce_tree(run, chat_service, settings, retry_attempts, batch_timeout_seconds):
    fan_in = _get_tabular_analysis_reduce_fan_in(settings)
    current_summaries = _load_analysis_chunk_summaries(run)
    level_counts = _build_analysis_reduce_plan(len(current_summaries), fan_in)
    level_number = 1
    while len(current_summaries) > 1:
        groups = _build_analysis_reduce_groups(current_summaries, fan_in)
        next_level_summaries = []
        node_count = len(groups)
        for node_index, summary_group in enumerate(groups, start=1):
            _raise_if_tabular_export_canceled(run)
            reduce_blob_path = _analysis_reduce_blob_path(
                run.get('user_id'),
                run.get('conversation_id'),
                run.get('id'),
                level_number,
                node_index,
            )
            if _blob_exists(reduce_blob_path):
                reduced_summary = _download_json_blob(reduce_blob_path)
                if not isinstance(reduced_summary, dict):
                    raise ValueError(
                        f'Analysis reduce checkpoint level {level_number} node {node_index} was malformed'
                    )
            else:
                reduced_summary = asyncio.run(_generate_analysis_reduce_summary(
                    chat_service,
                    run,
                    summary_group,
                    level_number,
                    node_index,
                    node_count,
                    retry_attempts,
                    batch_timeout_seconds,
                ))
                _raise_if_tabular_export_canceled(run)
                _upload_json_blob(
                    reduce_blob_path,
                    reduced_summary,
                    metadata={
                        'run_id': run.get('id'),
                        'conversation_id': run.get('conversation_id'),
                        'tabular_analysis_reduce': 'true',
                        'reduce_level': level_number,
                        'reduce_node': node_index,
                    },
                    overwrite=False,
                )
            next_level_summaries.append(reduced_summary)
            run = _update_analysis_reduce_progress(
                run,
                level_number,
                node_index,
                node_count,
                level_counts,
            )
        current_summaries = next_level_summaries
        level_number += 1
    return current_summaries[0] if current_summaries else {}


def _process_hierarchical_analysis_run(
    run,
    chat_service,
    input_batches,
    retry_attempts,
    batch_concurrency,
    batch_timeout_seconds,
    settings,
):
    if chat_service is None:
        raise ValueError('Hierarchical tabular analysis requires a chat model service')

    completed_batches = _safe_int(run.get('completed_batches'))
    processed_rows = _safe_int(run.get('processed_rows'))
    batch_count = _safe_int(run.get('batch_count'))
    last_logged_at = 0.0
    while completed_batches < batch_count:
        _raise_if_tabular_export_canceled(run)
        window_start = completed_batches + 1
        window_end = min(batch_count, window_start + batch_concurrency - 1)
        batch_results, batch_requests = _build_analysis_batch_window(
            run,
            input_batches,
            run.get('user_id'),
            run.get('id'),
            window_start,
            window_end,
            batch_count,
        )
        generation_error = None
        if batch_requests:
            log_event(
                '[TABULAR_GENERATED_OUTPUT] Building background analysis chunk window',
                {
                    'run_id': run.get('id'),
                    'source_file_name': run.get('source_file_name'),
                    'window_start': window_start,
                    'window_end': window_end,
                    'batch_count': batch_count,
                    'batch_concurrency': batch_concurrency,
                    'batch_timeout_seconds': batch_timeout_seconds,
                    'generation_request_count': len(batch_requests),
                },
                debug_only=True,
            )
            generated_results, generation_error = asyncio.run(
                _generate_analysis_chunk_summary_window(
                    chat_service,
                    run,
                    batch_requests,
                    batch_count,
                    retry_attempts,
                    batch_concurrency,
                    batch_timeout_seconds,
                )
            )
            _raise_if_tabular_export_canceled(run)
            batch_results.update(_checkpoint_analysis_batch_results(run, generated_results))

        previous_completed_batches = completed_batches
        run, completed_batches, processed_rows = _advance_analysis_map_progress_for_window(
            run,
            batch_results,
            completed_batches,
            processed_rows,
            window_start,
            window_end,
        )
        last_logged_at = _log_progress_if_due(run, last_logged_at)
        if generation_error:
            raise generation_error
        if completed_batches == previous_completed_batches:
            raise RuntimeError(f'No progress was made for analysis chunk window {window_start}-{window_end}')

    _raise_if_tabular_export_canceled(run)
    final_summary = _run_analysis_reduce_tree(
        run,
        chat_service,
        settings,
        retry_attempts,
        batch_timeout_seconds,
    )
    _raise_if_tabular_export_canceled(run)
    return _complete_analysis_run(run, final_summary)


def _process_combined_run(
    run,
    chat_service,
    input_batches,
    retry_attempts,
    batch_concurrency,
    batch_timeout_seconds,
    settings,
):
    if chat_service is None:
        raise ValueError('Combined tabular analysis and export requires a chat model service')

    completed_batches = _safe_int(run.get('completed_batches'))
    processed_rows = _safe_int(run.get('processed_rows'))
    batch_count = _safe_int(run.get('batch_count'))
    last_logged_at = 0.0
    while completed_batches < batch_count:
        _raise_if_tabular_export_canceled(run)
        window_start = completed_batches + 1
        window_end = min(batch_count, window_start + batch_concurrency - 1)
        if not run.get('output_schema'):
            window_end = window_start
        batch_results, batch_requests = _build_combined_batch_window(
            run,
            input_batches,
            run.get('user_id'),
            run.get('id'),
            window_start,
            window_end,
            batch_count,
        )
        generation_error = None
        if batch_requests:
            log_event(
                '[TABULAR_GENERATED_OUTPUT] Building background combined chunk window',
                {
                    'run_id': run.get('id'),
                    'source_file_name': run.get('source_file_name'),
                    'output_format': run.get('output_format'),
                    'window_start': window_start,
                    'window_end': window_end,
                    'batch_count': batch_count,
                    'batch_concurrency': batch_concurrency,
                    'batch_timeout_seconds': batch_timeout_seconds,
                    'generation_request_count': len(batch_requests),
                },
                debug_only=True,
            )
            generated_results, generation_error = asyncio.run(
                _generate_combined_chunk_result_window(
                    chat_service,
                    run,
                    batch_requests,
                    batch_count,
                    retry_attempts,
                    batch_concurrency,
                    batch_timeout_seconds,
                    expected_output_schema=run.get('output_schema'),
                )
            )
            _raise_if_tabular_export_canceled(run)
            batch_results.update(_checkpoint_combined_batch_results(run, generated_results))

        previous_completed_batches = completed_batches
        run, completed_batches, processed_rows = _advance_analysis_map_progress_for_window(
            run,
            batch_results,
            completed_batches,
            processed_rows,
            window_start,
            window_end,
        )
        last_logged_at = _log_progress_if_due(run, last_logged_at)
        if generation_error:
            raise generation_error
        if completed_batches == previous_completed_batches:
            raise RuntimeError(f'No progress was made for combined tabular chunk window {window_start}-{window_end}')

    _raise_if_tabular_export_canceled(run)
    run = _publish_combined_structured_export_phase(run)
    _raise_if_tabular_export_canceled(run)
    final_summary = _run_analysis_reduce_tree(
        run,
        chat_service,
        settings,
        retry_attempts,
        batch_timeout_seconds,
    )
    _raise_if_tabular_export_canceled(run)
    return _complete_combined_analysis_run(run, final_summary)


def _process_structured_export_rolling_pool(
    run,
    chat_service,
    input_batches,
    retry_attempts,
    batch_concurrency,
    batch_timeout_seconds,
    settings,
    generation_plan,
):
    if chat_service is None:
        raise ValueError('Rolling tabular structured export requires a chat model service')
    if not _is_rolling_executor_ready(run):
        raise ValueError('Rolling worker pool requires a ready active generation plan')

    batch_count = _safe_int(run.get('batch_count'))
    log_event(
        '[TABULAR_GENERATED_OUTPUT] Rolling worker pool started',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'batch_count': batch_count,
            'batch_concurrency': batch_concurrency,
            'checkpoint_writer_concurrency': _get_checkpoint_writer_concurrency(settings, run),
            'heartbeat_seconds': _get_tabular_generation_heartbeat_seconds(settings, run),
            'independent_batch_retries_enabled': _is_independent_batch_retries_enabled(settings, run),
            'response_protocol_version': run.get('response_protocol_version'),
            'plan_hash_present': bool(run.get('plan_hash')),
        },
        level=logging.INFO,
    )
    run, completed_batches, _processed_rows, last_logged_at = asyncio.run(
        _generate_and_checkpoint_rolling_pool_entries(
            run,
            chat_service,
            input_batches,
            run.get('user_question'),
            batch_count,
            run.get('source_file_name'),
            run.get('selected_sheet'),
            retry_attempts,
            run.get('id'),
            run.get('user_id'),
            batch_concurrency,
            _get_checkpoint_writer_concurrency(settings, run),
            _get_tabular_generation_heartbeat_seconds(settings, run),
            independent_batch_retries_enabled=_is_independent_batch_retries_enabled(settings, run),
            last_logged_at=0.0,
            batch_timeout_seconds=batch_timeout_seconds,
            response_protocol=run.get('response_protocol_version'),
            generation_plan=generation_plan,
        )
    )
    del last_logged_at
    if completed_batches != batch_count:
        raise RuntimeError(f'Rolling worker pool completed {completed_batches} of {batch_count} batch(es)')
    _raise_if_tabular_export_canceled(run)
    return _complete_run(run)


def process_tabular_generated_output_run(run_id, user_id):
    """Process or resume a checkpointed tabular generated-output run."""
    normalized_run_id = str(run_id or '').strip()
    normalized_user_id = str(user_id or '').strip()
    if not normalized_run_id or not normalized_user_id:
        return None

    settings = get_settings()
    run = _try_claim_run(normalized_user_id, normalized_run_id, settings)
    if not run:
        return None

    try:
        _authorize_tabular_export_run_execution(run)
        run = _migrate_legacy_tabular_export_run(run)
        if run.get('source_descriptor') and not run.get('source_staging_complete'):
            run = _stage_tabular_generated_output_source(run, settings)

        retry_attempts = _settings_int(
            settings,
            'tabular_generated_output_batch_retry_attempts',
            TABULAR_EXPORT_DEFAULT_BATCH_RETRY_ATTEMPTS,
            minimum=1,
            maximum=5,
        )
        batch_concurrency = _resolve_tabular_batch_concurrency(
            settings,
            run.get('batch_count'),
        )
        if _safe_int(run.get('batch_concurrency')) != batch_concurrency:
            run.update({
                'batch_concurrency': batch_concurrency,
                'updated_at': _now_iso(),
                'last_heartbeat_at': _now_iso(),
            })
            run = _replace_claimed_run(run)
        stale_seconds = _settings_int(
            settings,
            'tabular_generated_output_stale_seconds',
            TABULAR_EXPORT_DEFAULT_STALE_SECONDS,
            minimum=60,
        )
        batch_timeout_seconds = min(
            _settings_int(
                settings,
                'tabular_generated_output_batch_timeout_seconds',
                TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
                minimum=30,
                maximum=900,
            ),
            max(30, stale_seconds - 30),
        )
        chat_service = None
        if not run.get('passthrough_input_rows'):
            has_snapshotted_chunk_model = bool(str(run.get('chunk_gpt_model') or '').strip())
            chat_service = _build_chat_service(
                run.get('chunk_gpt_model') if has_snapshotted_chunk_model else run.get('gpt_model'),
                settings,
                model_context=(
                    run.get('chunk_model_context')
                    if has_snapshotted_chunk_model
                    else run.get('model_context')
                ),
                preselected=has_snapshotted_chunk_model,
            )
        completed_batches = _safe_int(run.get('completed_batches'))
        processed_rows = _safe_int(run.get('processed_rows'))
        batch_count = _safe_int(run.get('batch_count'))
        last_logged_at = 0.0
        input_batches = None
        input_batches_blob_path = str(run.get('input_blob_path') or '').strip()
        if input_batches_blob_path:
            input_batches = _download_json_blob(input_batches_blob_path)
            if not isinstance(input_batches, list):
                raise ValueError('Input batches blob was not a JSON array')

        run = _ensure_tabular_generation_plan(
            run,
            chat_service,
            input_batches,
            settings,
            batch_timeout_seconds,
        )
        generation_plan = _load_active_compact_generation_plan(run)
        if str(run.get('executor_mode') or '').strip() == TABULAR_EXECUTOR_MODE_ROLLING_POOL:
            if not _is_rolling_executor_ready(run):
                if str(run.get('plan_status') or '').strip().lower() in {'fallback', 'disabled', 'not_applicable'}:
                    run = _downgrade_rolling_executor_to_fixed_window(run, run.get('plan_status'))
                else:
                    raise ValueError('Rolling worker pool requires a ready active generation plan')

        log_event(
            '[TABULAR_GENERATED_OUTPUT] Background export run started',
            {
                'run_id': normalized_run_id,
                'conversation_id': run.get('conversation_id'),
                'user_id': normalized_user_id,
                'source_file_name': run.get('source_file_name'),
                'output_format': run.get('output_format'),
                'task_type': _normalize_tabular_run_task_type(run.get('task_type')),
                'row_count': run.get('row_count'),
                'batch_count': batch_count,
                'resume_completed_batches': completed_batches,
                'batch_concurrency': batch_concurrency,
                'batch_timeout_seconds': batch_timeout_seconds,
                'executor_mode': run.get('executor_mode'),
            },
            level=logging.INFO,
        )

        normalized_task_type = _normalize_tabular_run_task_type(run.get('task_type'))
        if normalized_task_type == TABULAR_RUN_TASK_COMBINED:
            return _process_combined_run(
                run,
                chat_service,
                input_batches,
                retry_attempts,
                batch_concurrency,
                batch_timeout_seconds,
                settings,
            )

        if normalized_task_type == TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS:
            return _process_hierarchical_analysis_run(
                run,
                chat_service,
                input_batches,
                retry_attempts,
                batch_concurrency,
                batch_timeout_seconds,
                settings,
            )

        if str(run.get('executor_mode') or '').strip() == TABULAR_EXECUTOR_MODE_ROLLING_POOL:
            return _process_structured_export_rolling_pool(
                run,
                chat_service,
                input_batches,
                retry_attempts,
                batch_concurrency,
                batch_timeout_seconds,
                settings,
                generation_plan,
            )

        durable_output_batches = _scan_output_checkpoint_batches_for_run(run)
        while completed_batches < batch_count:
            _raise_if_tabular_export_canceled(run)
            window_start = completed_batches + 1
            window_end = min(batch_count, window_start + batch_concurrency - 1)
            if not run.get('output_schema'):
                window_end = window_start
            batch_results, batch_requests = _build_batch_window(
                run,
                input_batches,
                normalized_user_id,
                normalized_run_id,
                window_start,
                window_end,
                batch_count,
                durable_output_batches=durable_output_batches,
            )

            generation_error = None
            if batch_requests:
                log_event(
                    '[TABULAR_GENERATED_OUTPUT] Building background structured export batch window',
                    {
                        'run_id': normalized_run_id,
                        'source_file_name': run.get('source_file_name'),
                        'output_format': run.get('output_format'),
                        'window_start': window_start,
                        'window_end': window_end,
                        'batch_count': batch_count,
                        'batch_concurrency': batch_concurrency,
                        'batch_timeout_seconds': batch_timeout_seconds,
                        'generation_request_count': len(batch_requests),
                    },
                    debug_only=True,
                )
                if run.get('passthrough_input_rows'):
                    generated_results = _build_passthrough_batch_results(run, batch_requests)
                elif _is_completion_driven_checkpointing_enabled(settings, run):
                    generated_batch_results, generation_error = asyncio.run(
                        _generate_and_checkpoint_batch_window_entries(
                            run,
                            chat_service,
                            run.get('user_question'),
                            batch_requests,
                            batch_count,
                            run.get('source_file_name'),
                            run.get('selected_sheet'),
                            retry_attempts,
                            normalized_run_id,
                            batch_concurrency,
                            _get_checkpoint_writer_concurrency(settings, run),
                            expected_output_schema=run.get('output_schema'),
                            batch_timeout_seconds=batch_timeout_seconds,
                            response_protocol=run.get('response_protocol_version'),
                            generation_plan=generation_plan,
                        )
                    )
                    batch_results.update(generated_batch_results)
                    durable_output_batches.update(generated_batch_results)
                    generated_results = []
                else:
                    generated_results, generation_error = asyncio.run(
                        _generate_batch_window_entries(
                            chat_service,
                            run.get('user_question'),
                            batch_requests,
                            batch_count,
                            run.get('source_file_name'),
                            run.get('selected_sheet'),
                            retry_attempts,
                            normalized_run_id,
                            batch_concurrency,
                            expected_output_schema=run.get('output_schema'),
                            batch_timeout_seconds=batch_timeout_seconds,
                            response_protocol=run.get('response_protocol_version'),
                            generation_plan=generation_plan,
                        )
                    )
                _raise_if_tabular_export_canceled(run)
                if generated_results:
                    checkpointed_batch_results = _checkpoint_generated_batch_results(run, generated_results)
                    batch_results.update(checkpointed_batch_results)
                    durable_output_batches.update(checkpointed_batch_results)

            previous_completed_batches = completed_batches
            run, completed_batches, processed_rows = _advance_run_progress_for_window(
                run,
                batch_results,
                completed_batches,
                processed_rows,
                window_start,
                window_end,
            )
            last_logged_at = _log_progress_if_due(run, last_logged_at)
            if generation_error:
                raise generation_error
            if completed_batches == previous_completed_batches:
                raise RuntimeError(f'No progress was made for batch window {window_start}-{window_end}')

        _raise_if_tabular_export_canceled(run)
        return _complete_run(run)
    except TabularExportCanceledError:
        return _read_run(normalized_user_id, normalized_run_id)
    except TabularExportLeaseLostError:
        return _read_run(normalized_user_id, normalized_run_id)
    except Exception as exc:
        if _is_retryable_export_error(exc):
            return _mark_run_retryable(run, exc, settings, retry_category='transient')
        if _is_retryable_model_validation_error(exc):
            return _mark_run_retryable(run, exc, settings, retry_category='model_validation')
        return _mark_run_failed(run, exc)


def submit_tabular_generated_output_run(run_id, user_id):
    """Submit a queued export run to the app executor when one is available."""
    if not has_app_context():
        return False

    executor = current_app.extensions.get('executor')
    if executor and hasattr(executor, 'submit_stored'):
        executor.submit_stored(
            f'tabular_generated_output_{run_id}',
            process_tabular_generated_output_run,
            run_id=run_id,
            user_id=user_id,
        )
        return True
    if executor and hasattr(executor, 'submit'):
        executor.submit(process_tabular_generated_output_run, run_id, user_id)
        return True
    return False


def queue_tabular_generated_output_run(
    user_id,
    conversation_id,
    user_question,
    source_candidate,
    output_format,
    row_batches,
    gpt_model,
    settings=None,
    model_context=None,
    source_descriptor=None,
    passthrough_input_rows=False,
    task_type=TABULAR_RUN_TASK_STRUCTURED_EXPORT,
    analysis_objective=None,
    planner_metadata=None,
):
    """Stage batch input blobs, create a run record, and submit background processing."""
    normalized_user_id = str(user_id or '').strip()
    normalized_conversation_id = str(conversation_id or '').strip()
    if not normalized_user_id or not normalized_conversation_id:
        raise ValueError('user_id and conversation_id are required for background tabular export')

    run_id = str(uuid.uuid4())
    source_candidate = source_candidate if isinstance(source_candidate, dict) else {}
    source_file_name = str(source_candidate.get('filename') or 'tabular_output').strip() or 'tabular_output'
    selected_sheet = str(source_candidate.get('selected_sheet') or '').strip()
    normalized_task_type = _normalize_tabular_run_task_type(task_type)
    normalized_output_format = str(output_format or 'json').strip().lower() or 'json'
    if normalized_task_type == TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS:
        normalized_output_format = 'md'
    normalized_analysis_objective = str(analysis_objective or '').strip()
    if not normalized_analysis_objective and normalized_task_type in {
        TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS,
        TABULAR_RUN_TASK_COMBINED,
    }:
        normalized_analysis_objective = str(user_question or '').strip()
    if normalized_task_type == TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS:
        generated_file_name = _build_analysis_file_name(source_file_name)
    else:
        generated_file_name = _build_generated_file_name(source_file_name, normalized_output_format)
    analysis_generated_file_name = (
        _build_analysis_file_name(source_file_name)
        if normalized_task_type == TABULAR_RUN_TASK_COMBINED
        else None
    )
    settings = settings or {}
    source_descriptor = dict(source_descriptor or {})
    tabular_planner_metadata = _normalize_tabular_run_planner_metadata(planner_metadata)
    source_authorization = dict(source_candidate.get('source_authorization') or {})
    staged_row_count = 0
    staged_char_count = 0
    staged_batch_count = 0
    staged_chunk_row_counts = []
    model_batch_budget = _build_model_aware_source_batch_budget(
        gpt_model,
        settings,
        model_context=model_context,
        task_type=normalized_task_type,
        user_question=user_question,
    )
    chunk_gpt_model, chunk_model_context = _resolve_tabular_chunk_model_selection(
        gpt_model,
        settings,
        model_context=model_context,
    )
    rollout_settings = _build_tabular_generation_rollout_assignment(
        settings,
        normalized_user_id,
        normalized_conversation_id,
        run_id,
    )
    requested_plan_mode = (
        rollout_settings.get('tabular_generation_plan_mode')
        if rollout_settings.get('enable_tabular_generation_plan')
        else 'off'
    )
    if normalized_task_type == TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS or passthrough_input_rows:
        requested_plan_mode = 'off'
    response_protocol_version = _select_tabular_response_protocol(
        rollout_settings,
        requested_plan_mode,
        normalized_task_type,
        passthrough_input_rows=passthrough_input_rows,
    )
    executor_mode = _select_tabular_executor_mode(
        rollout_settings,
        requested_plan_mode,
        normalized_task_type,
        passthrough_input_rows=passthrough_input_rows,
    )
    retry_mode = _select_tabular_retry_mode(rollout_settings, executor_mode)

    if source_descriptor:
        staged_row_count = _safe_int(source_descriptor.get('expected_row_count'))
        if staged_row_count <= 0:
            raise ValueError('Source query descriptor must include the expected row count')
        source_descriptor['batch_max_rows'] = model_batch_budget['max_rows']
        source_descriptor['batch_max_chars'] = model_batch_budget['max_chars']
        schema_probe_rows = _resolve_tabular_schema_probe_rows(
            settings,
            requested_plan_mode,
            normalized_task_type,
            staged_row_count,
            source_descriptor['batch_max_rows'],
        )
        source_descriptor['schema_probe_rows'] = schema_probe_rows
        token_max_batch_rows = source_descriptor['batch_max_rows']
        estimated_serialized_row_chars = _safe_int(
            source_descriptor.get('estimated_serialized_row_chars'),
            minimum=0,
        )
        if not estimated_serialized_row_chars:
            sampled_candidate_rows = [
                row
                for row in (source_candidate.get('rows') or [])[:5]
                if isinstance(row, dict)
            ]
            if sampled_candidate_rows:
                estimated_serialized_row_chars = max(
                    len(_dump_generated_output_json(row))
                    for row in sampled_candidate_rows
                )
                source_descriptor['estimated_serialized_row_chars'] = estimated_serialized_row_chars
        character_aware_batch_rows = _resolve_tabular_source_batch_capacity(
            token_max_batch_rows,
            source_descriptor['batch_max_chars'],
            estimated_serialized_row_chars,
        )
        balance_settings = dict(settings)
        balance_settings['enable_tabular_generation_balanced_batches'] = bool(
            rollout_settings.get('enable_tabular_generation_balanced_batches')
        )
        unbalanced_batch_rows = character_aware_batch_rows
        source_descriptor['batch_max_rows'] = _balance_tabular_source_batch_rows(
            balance_settings,
            staged_row_count,
            unbalanced_batch_rows,
            schema_probe_rows,
        )
        model_batch_budget['token_max_rows'] = token_max_batch_rows
        model_batch_budget['character_max_rows'] = character_aware_batch_rows
        model_batch_budget['max_rows'] = source_descriptor['batch_max_rows']
        staged_batch_count = _estimate_tabular_source_batch_count(
            staged_row_count,
            source_descriptor['batch_max_rows'],
            schema_probe_rows,
        )
        if source_descriptor['batch_max_rows'] != unbalanced_batch_rows:
            log_event(
                '[TABULAR_GENERATED_OUTPUT] Balanced source batches across concurrency waves',
                {
                    'run_id': run_id,
                    'row_count': staged_row_count,
                    'schema_probe_rows': schema_probe_rows,
                    'token_max_rows': token_max_batch_rows,
                    'character_max_rows': character_aware_batch_rows,
                    'balanced_max_rows': source_descriptor['batch_max_rows'],
                    'balanced_batch_count': staged_batch_count,
                },
                level=logging.INFO,
            )
        source_authorization = {
            field_name: source_descriptor.get(field_name)
            for field_name in ('source', 'scope_id', 'container', 'blob_path')
        }
    else:
        for index, batch_rows in enumerate(row_batches or [], start=1):
            if not isinstance(batch_rows, list):
                batch_rows = list(batch_rows or [])
            prepared_batch_rows = _prepare_tabular_source_rows(
                batch_rows,
                start_row=staged_row_count,
                token_namespace=run_id,
            )
            _upload_json_blob(
                _input_blob_path(normalized_user_id, normalized_conversation_id, run_id, index),
                prepared_batch_rows,
                metadata={
                    'run_id': run_id,
                    'conversation_id': normalized_conversation_id,
                    'generated_output_input': 'true',
                    'batch_number': index,
                },
            )
            staged_row_count += len(prepared_batch_rows)
            staged_chunk_row_counts.append(len(prepared_batch_rows))
            staged_char_count += len(json.dumps(prepared_batch_rows, default=str, ensure_ascii=False))
            staged_batch_count = index

        if not staged_batch_count or not staged_row_count:
            raise ValueError('At least one source row is required for a background tabular export')

    chunk_manifest = _write_chunk_manifest_for_run(
        normalized_user_id,
        normalized_conversation_id,
        run_id,
        staged_batch_count,
        row_count=staged_row_count,
        chunk_row_counts=staged_chunk_row_counts if staged_chunk_row_counts else None,
        estimated_rows_per_chunk=source_descriptor.get('batch_max_rows') if source_descriptor else None,
        chunk_status='pending_source_staging' if source_descriptor else 'staged',
    )

    now = _now_iso()
    run = {
        'id': run_id,
        'type': TABULAR_EXPORT_RUN_TYPE,
        'contract_version': TABULAR_EXPORT_CONTRACT_VERSION,
        'generation_contract_version': TABULAR_GENERATION_CONTRACT_VERSION,
        'response_protocol_version': response_protocol_version,
        'executor_mode': executor_mode,
        'retry_mode': retry_mode,
        'generation_rollout_settings': rollout_settings,
        'tabular_planner_metadata': tabular_planner_metadata,
        'task_type': normalized_task_type,
        'analysis_objective': normalized_analysis_objective,
        'user_id': normalized_user_id,
        'conversation_id': normalized_conversation_id,
        'status': TABULAR_EXPORT_STATUS_QUEUED,
        'created_at': now,
        'updated_at': now,
        'started_at': None,
        'completed_at': None,
        'last_heartbeat_at': None,
        'user_question': str(user_question or ''),
        'source_file_name': source_file_name,
        'selected_sheet': selected_sheet,
        'output_format': normalized_output_format,
        'gpt_model': str(gpt_model or '').strip(),
        'model_context': model_context if isinstance(model_context, dict) else {},
        'chunk_gpt_model': str(chunk_gpt_model or '').strip(),
        'chunk_model_context': chunk_model_context if isinstance(chunk_model_context, dict) else {},
        'passthrough_input_rows': bool(passthrough_input_rows),
        'passthrough_reason_code': (
            str(source_candidate.get('passthrough_reason_code') or '').strip()[:80]
            if passthrough_input_rows
            else None
        ),
        'generated_file_name': generated_file_name,
        'analysis_generated_file_name': analysis_generated_file_name,
        'row_count': staged_row_count,
        'batch_count': staged_batch_count,
        'total_chunk_count': staged_batch_count,
        'processed_chunk_count': 0,
        'failed_chunk_count': 0,
        'chunk_manifest': chunk_manifest,
        'completed_batches': 0,
        'planned_batch_count': staged_batch_count,
        'completed_batch_count': 0,
        'highest_contiguous_batch': 0,
        'active_batch_count': 0,
        'pending_batch_count': staged_batch_count,
        'checkpointing_batch_count': 0,
        'retry_wait_batch_count': 0,
        'exhausted_batch_count': 0,
        'systemic_failure_circuit_open': False,
        'systemic_failure_category': None,
        'systemic_failure_signature': None,
        'systemic_failure_opened_at': None,
        'checkpointed_row_count': 0,
        'generation_started_at': None,
        'generation_completed_at': None,
        'plan_blob_path': None,
        'plan_hash': None,
        'plan_mode': requested_plan_mode,
        'plan_status': 'pending' if requested_plan_mode in {'shadow', 'active'} else 'disabled',
        'plan_failure_reason': None,
        'planner_model': None,
        'planner_started_at': None,
        'planner_completed_at': None,
        'processed_rows': 0,
        'output_schema': None,
        'public_output_schema': [],
        'internal_checkpoint_schema': [],
        'lineage_schema': [
            TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD,
            TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD,
        ],
        'source_descriptor': source_descriptor or None,
        'batch_budget': model_batch_budget,
        'source_authorization': source_authorization or None,
        'source_staging_complete': not bool(source_descriptor),
        'source_staged_rows': 0 if source_descriptor else staged_row_count,
        'source_staged_batches': 0 if source_descriptor else staged_batch_count,
        'source_scan_row_count': 0,
        'input_blob_container': storage_account_personal_chat_container_name,
        'input_blob_path': None,
        'input_blob_prefix': f'{normalized_user_id}/{normalized_conversation_id}/generated/tabular_runs/{run_id}/input/',
        'output_blob_container': storage_account_personal_chat_container_name,
        'output_blob_prefix': f'{normalized_user_id}/{normalized_conversation_id}/generated/tabular_runs/{run_id}/output/',
        'retry_blob_container': storage_account_personal_chat_container_name,
        'retry_blob_prefix': f'{normalized_user_id}/{normalized_conversation_id}/generated/tabular_runs/{run_id}/retry/',
        'staged_input_char_count': staged_char_count,
        'mismatch_count': 0,
        'retry_count': 0,
        'recent_batches': [],
        'recent_progress_windows': [],
        'analysis_phase': 'queued' if _is_tabular_analysis_task(normalized_task_type) else None,
        'active_processing_seconds': 0,
        'last_message': (
            'Queued background tabular run; preparing source checkpoints'
            if source_descriptor
            else
            'Queued background combined tabular analysis and export'
            if normalized_task_type == TABULAR_RUN_TASK_COMBINED
            else
            'Queued background tabular analysis'
            if normalized_task_type == TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS
            else 'Queued background structured export'
        ),
        'last_error': None,
        'final_artifact': None,
        'structured_export_artifact': None,
        'analysis_artifact': None,
        'combined_artifacts': [],
    }
    cosmos_tabular_export_runs_container.create_item(body=run)
    submitted = submit_tabular_generated_output_run(run_id, normalized_user_id)
    run['submitted_to_executor'] = submitted

    log_event(
        '[TABULAR_GENERATED_OUTPUT] Queued background export run',
        {
            'run_id': run_id,
            'conversation_id': normalized_conversation_id,
            'user_id': normalized_user_id,
            'source_file_name': source_file_name,
            'selected_sheet': selected_sheet,
            'output_format': normalized_output_format,
            'task_type': normalized_task_type,
            'row_count': staged_row_count,
            'batch_count': staged_batch_count,
            'total_chunk_count': staged_batch_count,
            'staged_input_char_count': staged_char_count,
            'batch_max_rows': model_batch_budget.get('max_rows'),
            'batch_token_max_rows': model_batch_budget.get('token_max_rows'),
            'batch_character_max_rows': model_batch_budget.get('character_max_rows'),
            'batch_max_chars': model_batch_budget.get('max_chars'),
            'batch_input_token_budget': model_batch_budget.get('input_token_budget'),
            'batch_output_token_budget': model_batch_budget.get('output_token_budget'),
            'model_limit_source': model_batch_budget.get('limit_source'),
            'generation_contract_version': TABULAR_GENERATION_CONTRACT_VERSION,
            'response_protocol_version': response_protocol_version,
            'executor_mode': executor_mode,
            'retry_mode': retry_mode,
            'rollout_percentage': rollout_settings.get('tabular_generation_rollout_percentage'),
            'rollout_bucket': rollout_settings.get('tabular_generation_rollout_bucket'),
            'rollout_cohort': rollout_settings.get('tabular_generation_rollout_cohort'),
            'rollout_hash_version': rollout_settings.get('tabular_generation_rollout_hash_version'),
            'planner_mode': rollout_settings.get('tabular_generation_plan_mode'),
            'compact_protocol_enabled': rollout_settings.get('enable_tabular_compact_response_protocol'),
            'completion_checkpointing_enabled': rollout_settings.get(
                'enable_tabular_completion_driven_checkpointing'
            ),
            'rolling_pool_enabled': rollout_settings.get('enable_tabular_rolling_worker_pool'),
            'independent_retries_enabled': rollout_settings.get('enable_tabular_independent_batch_retries'),
            'source_backed': bool(source_descriptor),
            'submitted_to_executor': submitted,
        },
        level=logging.INFO,
    )
    return run


def check_due_tabular_generated_output_runs_once(limit=None):
    """Resume queued or stale tabular generated-output runs."""
    settings = get_settings()
    scan_limit = _safe_int(
        limit,
        default=_settings_int(
            settings,
            'tabular_generated_output_scheduler_scan_limit',
            TABULAR_EXPORT_DEFAULT_SCAN_LIMIT,
            minimum=1,
            maximum=10,
        ),
        minimum=1,
        maximum=10,
    )

    scanned_candidates = []
    status_counts = {}
    for status in TABULAR_EXPORT_SCHEDULER_STATUSES:
        status_candidates = _query_scheduler_candidates_by_status(status, scan_limit, settings)
        status_counts[status] = len(status_candidates)
        scanned_candidates.extend(status_candidates)

    seen_keys = set()
    candidates = []
    skipped = []
    for run in sorted(scanned_candidates, key=_scheduler_candidate_sort_key):
        candidate_key = (run.get('user_id'), run.get('id'))
        if candidate_key in seen_keys:
            continue
        seen_keys.add(candidate_key)
        status = str(run.get('status') or '').strip().lower()
        candidate_reason = _scheduler_candidate_reason(run, settings)
        if not candidate_reason:
            skipped.append({
                'run_id': run.get('id'),
                'status': status,
                'reason': 'candidate is not due',
            })
            continue
        candidates.append({'run': run, 'reason': candidate_reason})
        if len(candidates) >= scan_limit:
            break

    processed = []
    for candidate in candidates:
        run = candidate.get('run') or {}
        status = str(run.get('status') or '').strip().lower()
        submitted = submit_tabular_generated_output_run(run.get('id'), run.get('user_id'))
        if submitted:
            processed.append(run.get('id'))
        else:
            processed_run = process_tabular_generated_output_run(run.get('id'), run.get('user_id'))
            if processed_run:
                processed.append(processed_run.get('id'))
            else:
                skipped.append({
                    'run_id': run.get('id'),
                    'status': status,
                    'reason': f"{candidate.get('reason')}; claim or processing did not start",
                })

    if scanned_candidates or candidates:
        log_event(
            '[TABULAR_GENERATED_OUTPUT] Background scheduler scan result',
            {
                'scanned_count': len(scanned_candidates),
                'candidate_count': len(candidates),
                'status_counts': status_counts,
                'processed_run_ids': processed,
                'processed_count': len(processed),
                'skipped': skipped[:10],
            },
            debug_only=True,
        )
    return processed
