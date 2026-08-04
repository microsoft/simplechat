# functions_tabular_generated_exports.py
"""Durable background runs for large tabular generated exports."""

import asyncio
from collections import Counter
import csv
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

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import current_app, has_app_context
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import AzureChatPromptExecutionSettings
from semantic_kernel.contents.chat_history import ChatHistory as SKChatHistory
from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

from config import (
    CLIENTS,
    cosmos_conversations_container,
    cosmos_tabular_export_runs_container,
    storage_account_group_documents_container_name,
    storage_account_personal_chat_container_name,
    storage_account_public_documents_container_name,
    storage_account_user_documents_container_name,
)
from functions_appinsights import log_event
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
TABULAR_EXPORT_CONTRACT_VERSION = 2
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
TABULAR_EXPORT_DEFAULT_LEASE_SECONDS = 300
TABULAR_EXPORT_DEFAULT_STALE_SECONDS = 420
TABULAR_EXPORT_DEFAULT_SCAN_LIMIT = 5
TABULAR_EXPORT_DEFAULT_MAX_TRANSIENT_FAILURES = 20
TABULAR_EXPORT_DEFAULT_BATCH_CONCURRENCY = 3
TABULAR_EXPORT_MAX_BATCH_CONCURRENCY = 5
TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS = 300
TABULAR_EXPORT_FINAL_SPOOL_MAX_MEMORY_BYTES = 1024 * 1024
TABULAR_EXPORT_DEFAULT_SOURCE_CHUNK_ROWS = 1000
TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_ROWS = 50
TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_CHARS = 60000
TABULAR_EXPORT_SUMMARY_MAX_FIELDS = 25
TABULAR_EXPORT_SUMMARY_MAX_VALUES_PER_FIELD = 5
TABULAR_EXPORT_SUMMARY_AGGREGATE_MAX_VALUES = 25
TABULAR_EXPORT_PROGRESS_LOG_INTERVAL_SECONDS = 30
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
TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD = '__simplechat_source_row_number'
TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD = '__simplechat_source_row_identity'
TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD = '__simplechat_source_row_token'
TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD = 'source_row_number'
TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD = 'source_row_identity'


class TabularExportCanceledError(RuntimeError):
    """Raised when a durable export is canceled between checkpoints."""


class TabularExportLeaseLostError(RuntimeError):
    """Raised when a stale worker no longer owns the durable run claim."""


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


def _sanitize_file_base_name(file_name):
    base_name = os.path.splitext(str(file_name or '').strip())[0]
    normalized_base_name = re.sub(r'[^A-Za-z0-9._-]+', '_', base_name).strip('._')
    return normalized_base_name or 'tabular_output'


def _build_generated_file_name(source_file_name, output_format):
    timestamp_suffix = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    normalized_extension = normalize_generated_output_format(output_format)
    return f"{_sanitize_file_base_name(source_file_name)}_generated_{timestamp_suffix}.{normalized_extension}"


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


def _output_blob_path(user_id, conversation_id, run_id, batch_number):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/output/batch_{batch_number:06d}.json"


def _output_summary_blob_path(user_id, conversation_id, run_id, batch_number):
    return f"{user_id}/{conversation_id}/generated/tabular_runs/{run_id}/summary/batch_{batch_number:06d}.json"


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


def _truncate_response_preview(response_content, max_chars=400):
    cleaned = _clean_generated_json_code_fence(response_content)
    normalized = re.sub(r'\s+', ' ', cleaned).strip()
    if not normalized:
        return ''
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars]}..."


def _dump_generated_output_json(value):
    return json.dumps(value, default=str, ensure_ascii=False, separators=(',', ':'))


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


def _stage_tabular_generated_output_source(run, settings):
    source_descriptor = run.get('source_descriptor') or {}
    if source_descriptor.get('kind') != 'query_tabular_data':
        raise ValueError('Unsupported generated export source descriptor')
    if not str(source_descriptor.get('blob_path') or '').lower().endswith('.csv'):
        raise ValueError('Source-backed generated exports require a CSV source')

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
        maximum=100,
    )
    max_batch_chars = _safe_int(
        source_descriptor.get('batch_max_chars'),
        default=TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_CHARS,
        minimum=6000,
        maximum=120000,
    )
    source_blob_client = _get_versioned_source_blob_client(source_descriptor)
    resume_source_row = _safe_int(run.get('source_scan_row_count'))
    pending_rows = []
    pending_chars = 0
    last_source_row_number = resume_source_row

    with tempfile.SpooledTemporaryFile(
        max_size=TABULAR_EXPORT_FINAL_SPOOL_MAX_MEMORY_BYTES,
        mode='w+b',
    ) as source_stream:
        source_blob_client.download_blob(
            etag=source_descriptor.get('blob_etag'),
            match_condition=MatchConditions.IfNotModified,
        ).readinto(source_stream)
        source_stream.seek(0)

        tabular_plugin = TabularProcessingPlugin()
        for source_row_number, source_row in iter_tabular_csv_query_rows(
            csv_stream=source_stream,
            query_expression=source_descriptor.get('query_expression'),
            return_columns=source_descriptor.get('return_columns'),
            source_chunk_rows=source_chunk_rows,
            tabular_plugin=tabular_plugin,
            start_source_row=resume_source_row,
        ):
            source_row_text = _dump_generated_output_json(source_row)
            if pending_rows and (
                len(pending_rows) >= max_batch_rows
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
            if len(pending_rows) >= max_batch_rows:
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

    now = _now_iso()
    run.update({
        'source_staging_complete': True,
        'row_count': staged_row_count,
        'batch_count': staged_batch_count,
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
        return run

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
        migrated_row_count += len(prepared_rows)

    if migrated_row_count != expected_row_count:
        raise ValueError(
            f'Legacy input migration found {migrated_row_count} row(s); expected {expected_row_count}'
        )

    now = _now_iso()
    run.update({
        'contract_version': TABULAR_EXPORT_CONTRACT_VERSION,
        'input_blob_path': None,
        'completed_batches': 0,
        'processed_rows': 0,
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
):
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


def _build_chat_service(gpt_model, settings, model_context=None):
    chat_service, _ = build_semantic_kernel_chat_service_for_model(
        gpt_model,
        settings,
        service_id='tabular-generated-output-background',
        model_context=model_context,
    )
    return chat_service


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
):
    batch_number = batch_index + 1
    batch_prompt = _build_batch_prompt(
        user_question,
        batch_rows,
        batch_index,
        total_batches,
        source_file_name,
        selected_sheet=selected_sheet,
        output_schema=expected_output_schema,
    )

    parsed_entries = None
    raw_response_content = ''
    mismatch_count = 0
    last_validation_error = None
    timeout_seconds = max(
        _safe_float(
            batch_timeout_seconds,
            default=TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS,
        ),
        0.001,
    )
    for attempt_number in range(1, retry_attempts + 1):
        chat_history = SKChatHistory()
        chat_history.add_system_message(
            'You transform tabular input rows into deterministic structured output. '
            'Return only a valid JSON array with one object per input row. '
            'Never add markdown, explanation text, or omit rows.'
        )
        if attempt_number > 1:
            chat_history.add_system_message(
                f'The previous attempt did not return the required {len(batch_rows)} JSON object(s). '
                'Retry now and preserve the input row count exactly.'
            )
        chat_history.add_user_message(batch_prompt)

        execution_settings = AzureChatPromptExecutionSettings(service_id='tabular-generated-output-background')
        try:
            result = await asyncio.wait_for(
                chat_service.get_chat_message_contents(chat_history, execution_settings),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f'Background structured export batch {batch_number}/{total_batches} '
                f'timed out after {timeout_seconds:g} seconds.'
            ) from exc
        raw_response_content = result[0].content if result and result[0].content else ''
        parsed_entries = _parse_generated_json_entries(raw_response_content) if raw_response_content else None
        parsed_entry_count = len(parsed_entries) if parsed_entries is not None else 0
        if parsed_entries is not None and parsed_entry_count == len(batch_rows):
            try:
                normalized_entries, output_schema = _normalize_generated_batch_entries(
                    batch_rows,
                    parsed_entries,
                    expected_output_schema=expected_output_schema,
                )
                return normalized_entries, mismatch_count, output_schema
            except ValueError as exc:
                last_validation_error = str(exc)

        mismatch_count += 1
        log_event(
            '[Tabular Generated Output] Background export batch attempt mismatch',
            {
                'run_id': run_id,
                'batch_number': batch_number,
                'batch_count': total_batches,
                'attempt_number': attempt_number,
                'expected_row_count': len(batch_rows),
                'parsed_row_count': parsed_entry_count,
                'validation_error': last_validation_error,
                'response_char_count': len(raw_response_content),
                'response_preview': _truncate_response_preview(raw_response_content),
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
):
    async with semaphore:
        batch_started_at = time.monotonic()
        batch_entries, mismatch_count, output_schema = await _generate_batch_entries(
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
        )
        return {
            'batch_number': batch_request['batch_number'],
            'batch_entries': batch_entries,
            'batch_summary': _build_generated_batch_summary(batch_entries),
            'batch_row_count': len(batch_entries),
            'elapsed_seconds': time.monotonic() - batch_started_at,
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
    return status == TABULAR_EXPORT_STATUS_FAILED and _is_retryable_export_error_message((run or {}).get('last_error'))


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
        if _is_retryable_failed_run(run):
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
        "c.next_attempt_at, c.last_error, c.transient_failure_count "
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
            '[Tabular Generated Output] Scheduler candidate query failed',
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
        return _is_retryable_failed_run(run)
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


def _build_run_status_detail(run, settings, retryable_failure, can_resume):
    status = str((run or {}).get('status') or '').strip().lower()
    is_stale = status == TABULAR_EXPORT_STATUS_RUNNING and _is_stale_running_run(run, settings or {})
    waiting_for_retry = _is_waiting_for_retry(run)
    retry_due = _is_due_queued_retry_run(run)
    stale_queued = _is_stale_queued_run(run, settings or {})
    retry_delay_seconds = _seconds_until((run or {}).get('next_attempt_at')) if waiting_for_retry else None

    if status == TABULAR_EXPORT_STATUS_COMPLETED:
        return {
            'status_label': 'Complete',
            'status_tone': 'success',
            'status_detail': 'Export complete and ready to download.',
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if status == TABULAR_EXPORT_STATUS_CANCELED:
        return {
            'status_label': 'Canceled',
            'status_tone': 'secondary',
            'status_detail': 'Export was canceled.',
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
                'status_detail': 'Export validation passed and the final artifact is being published.',
                'is_stale': False,
                'waiting_for_retry': False,
                'retry_due': False,
                'retry_delay_seconds': None,
            }
        return {
            'status_label': 'Running',
            'status_tone': 'info',
            'status_detail': 'Export is running and checkpointing completed batches.',
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if waiting_for_retry:
        return {
            'status_label': 'Retry Scheduled',
            'status_tone': 'warning',
            'status_detail': 'Automatic retry is scheduled. Continue can resume now from the last checkpoint.',
            'is_stale': False,
            'waiting_for_retry': True,
            'retry_due': False,
            'retry_delay_seconds': retry_delay_seconds,
        }
    if retry_due:
        return {
            'status_label': 'Needs Attention',
            'status_tone': 'warning',
            'status_detail': 'Automatic retry is due but no worker has picked it up. Continue will resume from the last checkpoint.',
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
            'status_detail': 'Export stopped after a retryable interruption. Continue will resume from the last checkpoint.',
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }
    if status == TABULAR_EXPORT_STATUS_FAILED:
        return {
            'status_label': 'Failed',
            'status_tone': 'danger',
            'status_detail': 'Export failed and cannot continue from checkpoints.',
            'is_stale': False,
            'waiting_for_retry': False,
            'retry_due': False,
            'retry_delay_seconds': None,
        }

    return {
        'status_label': 'Queued',
        'status_tone': 'info',
        'status_detail': 'Export is queued and waiting for a background worker.',
        'is_stale': False,
        'waiting_for_retry': False,
        'retry_due': False,
        'retry_delay_seconds': None,
    }



def _build_run_public_status(run, settings=None):
    if not isinstance(run, dict):
        return None

    batch_count = _safe_int(run.get('batch_count'))
    completed_batches = _safe_int(run.get('completed_batches'))
    row_count = _safe_int(run.get('row_count'))
    processed_rows = _safe_int(run.get('processed_rows'))
    progress_percent = 0.0
    if batch_count:
        progress_percent = round((completed_batches / batch_count) * 100, 2)

    final_artifact = run.get('final_artifact') or {}
    retryable_failure = _is_retryable_failed_run(run)
    can_resume = _can_resume_run(run, settings)
    status_detail = _build_run_status_detail(run, settings, retryable_failure, can_resume)
    checkpoint_summary = _build_checkpoint_summary(completed_batches, batch_count, processed_rows, row_count)
    generated_artifact = None
    if final_artifact.get('artifact_message_id'):
        generated_artifact = {
            'capability': final_artifact.get('capability') or 'tabular',
            'artifact_message_id': final_artifact.get('artifact_message_id'),
            'conversation_id': run.get('conversation_id'),
            'file_name': final_artifact.get('file_name') or run.get('generated_file_name'),
            'output_format': final_artifact.get('output_format') or run.get('output_format'),
            'row_count': processed_rows or row_count,
            'storage_scope': 'chat',
            'source_file_name': run.get('source_file_name'),
            'selected_sheet': run.get('selected_sheet'),
            'summary': run.get('post_run_summary'),
            'suppress_assistant_table_export': True,
        }

    return {
        'run_id': run.get('id'),
        'conversation_id': run.get('conversation_id'),
        'status': run.get('status'),
        'source_file_name': run.get('source_file_name'),
        'selected_sheet': run.get('selected_sheet'),
        'output_format': run.get('output_format'),
        'row_count': row_count,
        'processed_rows': processed_rows,
        'batch_count': batch_count,
        'completed_batches': completed_batches,
        'progress_percent': progress_percent,
        'created_at': run.get('created_at'),
        'started_at': run.get('started_at'),
        'updated_at': run.get('updated_at'),
        'completed_at': run.get('completed_at'),
        'last_heartbeat_at': run.get('last_heartbeat_at'),
        'last_message': run.get('last_message'),
        'last_error': run.get('last_error'),
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
        'mismatch_count': _safe_int(run.get('mismatch_count')),
        'retry_count': _safe_int(run.get('retry_count')),
        'transient_failure_count': _safe_int(run.get('transient_failure_count')),
        'manual_resume_count': _safe_int(run.get('manual_resume_count')),
        'next_attempt_at': run.get('next_attempt_at'),
        'can_resume': can_resume,
        'can_cancel': _can_cancel_run(run),
        'retryable_failure': retryable_failure,
        'artifact_message_id': final_artifact.get('artifact_message_id'),
        'file_name': final_artifact.get('file_name') or run.get('generated_file_name'),
        'generated_artifact': generated_artifact,
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
    public_status.update({
        'export_run_id': public_status.get('run_id'),
        'background_export': True,
        'capability': 'tabular',
        'suppress_assistant_table_export': True,
        'summary': (
            f"Queued structured {str(public_status.get('output_format') or 'json').upper()} export "
            f"for {public_status.get('row_count', 0)} row(s) across {public_status.get('batch_count', 0)} batch(es)."
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
    if status == TABULAR_EXPORT_STATUS_FAILED and not _is_retryable_failed_run(run):
        return {
            'success': False,
            'resumed': False,
            'submitted': False,
            'message': 'Background export cannot be continued because the last failure was not retryable.',
            'run': _build_run_public_status(run, settings=settings),
        }

    now = _now_iso()
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
        '[Tabular Generated Output] Background export manually resumed',
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
        '[Tabular Generated Output] Background export canceled',
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
    stale_seconds = _settings_int(
        settings,
        'tabular_generated_output_stale_seconds',
        TABULAR_EXPORT_DEFAULT_STALE_SECONDS,
        minimum=60,
    )
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
        retryable_failed_run = (
            status == TABULAR_EXPORT_STATUS_FAILED
            and _is_retryable_export_error_message(run.get('last_error'))
            and _safe_int(run.get('transient_failure_count')) < _settings_int(
                settings,
                'tabular_generated_output_max_transient_failures',
                TABULAR_EXPORT_DEFAULT_MAX_TRANSIENT_FAILURES,
                minimum=1,
                maximum=100,
            )
        )
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
        'attempt_started_at': now.isoformat(),
        'updated_at': now.isoformat(),
        'completed_at': None,
        'last_heartbeat_at': now.isoformat(),
        'lease_holder_id': _lease_holder_id(),
        'lease_generation': _safe_int(run.get('lease_generation')) + 1,
        'lease_expires_at': (now + timedelta(seconds=lease_seconds)).isoformat(),
        'next_attempt_at': None,
        'last_message': 'Background structured export is running',
    })
    try:
        return _replace_run(run)
    except Exception as exc:
        status_code = getattr(exc, 'status_code', None)
        if status_code not in (409, 412):
            log_event(
                '[Tabular Generated Output] Background export run claim failed',
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
        'last_error': str(error_message or 'Unknown error')[:1000],
        'last_message': 'Background structured export failed',
    })
    try:
        run = _replace_claimed_run(run)
    except TabularExportLeaseLostError:
        return _read_run(run.get('user_id'), run.get('id'))
    log_event(
        '[Tabular Generated Output] Background export run failed',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'completed_batches': run.get('completed_batches'),
            'batch_count': run.get('batch_count'),
            'processed_rows': run.get('processed_rows'),
            'row_count': run.get('row_count'),
            'error': str(error_message or '')[:1000],
        },
        level=logging.ERROR,
        exceptionTraceback=True,
    )
    return run


def _mark_run_retryable(run, error_message, settings):
    transient_failure_count = _safe_int(run.get('transient_failure_count')) + 1
    max_transient_failures = _settings_int(
        settings,
        'tabular_generated_output_max_transient_failures',
        TABULAR_EXPORT_DEFAULT_MAX_TRANSIENT_FAILURES,
        minimum=1,
        maximum=100,
    )
    if transient_failure_count > max_transient_failures:
        return _mark_run_failed(
            run,
            f'Max transient retry attempts exceeded; last error: {error_message}',
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
        'last_error': str(error_message or 'Transient background export error')[:1000],
        'last_message': 'Background structured export will resume after a transient connection error',
        'transient_failure_count': transient_failure_count,
        'next_attempt_at': next_attempt_at,
    })
    try:
        run = _replace_claimed_run(run)
    except TabularExportLeaseLostError:
        return _read_run(run.get('user_id'), run.get('id'))
    log_event(
        '[Tabular Generated Output] Background export run requeued after transient failure',
        {
            'run_id': run.get('id'),
            'conversation_id': run.get('conversation_id'),
            'user_id': run.get('user_id'),
            'completed_batches': run.get('completed_batches'),
            'batch_count': run.get('batch_count'),
            'processed_rows': run.get('processed_rows'),
            'row_count': run.get('row_count'),
            'transient_failure_count': transient_failure_count,
            'max_transient_failures': max_transient_failures,
            'next_attempt_at': next_attempt_at,
            'error': str(error_message or '')[:1000],
        },
        level=logging.WARNING,
    )
    return run


def _update_run_progress(run, completed_batches, processed_rows, batch_rows, batch_elapsed_seconds, mismatch_count=0):
    now = _now_utc()
    started_at = str(run.get('started_at') or '').strip()
    elapsed_seconds = 0.0
    if started_at:
        try:
            started_time = datetime.fromisoformat(started_at)
            if started_time.tzinfo is None:
                started_time = started_time.replace(tzinfo=timezone.utc)
            elapsed_seconds = max((now - started_time).total_seconds(), 0.0)
        except ValueError:
            elapsed_seconds = 0.0

    active_processing_seconds = max(_safe_float(run.get('active_processing_seconds')), 0.0)
    active_processing_seconds += max(_safe_float(batch_elapsed_seconds), 0.0)
    recent_batches = list(run.get('recent_batches') or [])[-9:]
    recent_batches.append({
        'batch_number': completed_batches,
        'row_count': _safe_int(batch_rows),
        'elapsed_seconds': round(_safe_float(batch_elapsed_seconds), 3),
        'completed_at': now.isoformat(),
    })

    batch_count = _safe_int(run.get('batch_count'))
    estimated_total_seconds = None
    estimated_remaining_seconds = None
    if completed_batches > 0 and batch_count > 0:
        recent_elapsed_values = [
            _safe_float(batch.get('elapsed_seconds'))
            for batch in recent_batches
            if _safe_float(batch.get('elapsed_seconds')) > 0
        ]
        if recent_elapsed_values:
            seconds_per_batch = sum(recent_elapsed_values) / len(recent_elapsed_values)
        elif active_processing_seconds > 0:
            seconds_per_batch = active_processing_seconds / completed_batches
        else:
            seconds_per_batch = elapsed_seconds / completed_batches
        estimated_total_seconds = round(seconds_per_batch * batch_count, 1)
        estimated_remaining_seconds = round(seconds_per_batch * max(batch_count - completed_batches, 0), 1)

    run.update({
        'completed_batches': completed_batches,
        'processed_rows': processed_rows,
        'updated_at': now.isoformat(),
        'last_heartbeat_at': now.isoformat(),
        'active_processing_seconds': round(active_processing_seconds, 3),
        'estimated_total_seconds': estimated_total_seconds,
        'estimated_remaining_seconds': estimated_remaining_seconds,
        'mismatch_count': _safe_int(run.get('mismatch_count')) + _safe_int(mismatch_count),
        'last_message': f"Processed structured export batch {completed_batches} of {batch_count}",
    })
    run['recent_batches'] = recent_batches

    return _replace_claimed_run(run)


def _log_progress_if_due(run, last_logged_at):
    now_monotonic = time.monotonic()
    if last_logged_at and now_monotonic - last_logged_at < TABULAR_EXPORT_PROGRESS_LOG_INTERVAL_SECONDS:
        return last_logged_at

    batch_count = _safe_int(run.get('batch_count'))
    completed_batches = _safe_int(run.get('completed_batches'))
    progress_percent = round((completed_batches / batch_count) * 100, 2) if batch_count else 0.0
    log_event(
        '[Tabular Generated Output] Background export progress',
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
    if not output_schema:
        raise ValueError('Generated output schema is missing')
    if TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD not in output_schema:
        raise ValueError('Generated output schema is missing source row order')

    csv_writer = None
    safe_output_schema = None
    if output_format == 'csv':
        safe_output_schema = build_safe_csv_headers(output_schema)
        csv_writer = csv.DictWriter(output_stream, fieldnames=safe_output_schema, lineterminator='\n')
        csv_writer.writeheader()
    else:
        output_stream.write('[\n')

    written_row_count = 0
    expected_source_row_number = 1
    for batch_number in range(1, batch_count + 1):
        batch_blob_path = _output_blob_path(user_id, conversation_id, run_id, batch_number)
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
            if csv_writer:
                csv_writer.writerow({
                    safe_field_name: _serialize_generated_output_value(ordered_entry.get(field_name))
                    for field_name, safe_field_name in zip(output_schema, safe_output_schema)
                })
            else:
                if written_row_count:
                    output_stream.write(',\n')
                output_stream.write(json.dumps(ordered_entry, default=str, ensure_ascii=False))

            written_row_count += 1
            expected_source_row_number += 1

    if output_format != 'csv':
        output_stream.write('\n]\n')
    if written_row_count != expected_row_count:
        raise ValueError(
            f'Final output row count {written_row_count} does not match expected count {expected_row_count}'
        )
    return written_row_count


def _complete_run(run):
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
    now = _now_iso()
    run.update({
        'status': TABULAR_EXPORT_STATUS_COMPLETED,
        'updated_at': now,
        'completed_at': now,
        'last_heartbeat_at': now,
        'processed_rows': output_entry_count,
        'completed_batches': _safe_int(run.get('batch_count')),
        'last_message': 'Background structured export completed',
        'post_run_summary': post_run_summary,
        'generated_file_name': uploaded_message.get('file_name') or generated_file_name,
        'final_artifact': {
            'artifact_message_id': uploaded_message.get('id'),
            'file_name': uploaded_message.get('file_name') or generated_file_name,
            'blob_container': uploaded_message.get('blob_container'),
            'blob_path': uploaded_message.get('blob_path'),
            'capability': uploaded_message.get('capability') or 'tabular',
            'output_format': uploaded_message.get('output_format') or output_format,
        },
        'estimated_remaining_seconds': 0,
    })
    run = _replace_claimed_run(run)
    log_event(
        '[Tabular Generated Output] Background export completed',
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


def _build_batch_window(run, input_batches, user_id, run_id, window_start, window_end, batch_count):
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

        if _blob_exists(output_blob_path) and not run.get('regenerate_legacy_output_checkpoints'):
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
                    metadata={
                        'run_id': run_id,
                        'conversation_id': run.get('conversation_id'),
                        'batch_number': batch_number,
                        'generated_output_summary': 'true',
                    },
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
            '[Tabular Generated Output] Building background structured export batch',
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
    if list(run.get('output_schema') or []) != expected_output_schema:
        run['output_schema'] = expected_output_schema
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
        try:
            _upload_json_blob(
                output_blob_path,
                generated_result['batch_entries'],
                metadata={
                    'run_id': run.get('id'),
                    'conversation_id': run.get('conversation_id'),
                    'batch_number': batch_number,
                    'generated_output': 'true',
                    'lease_generation': run.get('lease_generation'),
                },
                overwrite=bool(run.get('regenerate_legacy_output_checkpoints')),
            )
        except ResourceExistsError:
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
            metadata={
                'run_id': run.get('id'),
                'conversation_id': run.get('conversation_id'),
                'batch_number': batch_number,
                'generated_output_summary': 'true',
            },
        )
        batch_results[batch_number] = {
            'batch_number': batch_number,
            'batch_row_count': generated_result['batch_row_count'],
            'elapsed_seconds': generated_result['elapsed_seconds'],
            'mismatch_count': generated_result['mismatch_count'],
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
    for batch_number in range(window_start, window_end + 1):
        batch_result = batch_results.get(batch_number)
        if not batch_result:
            break
        completed_batches = batch_number
        processed_rows += _safe_int(batch_result.get('batch_row_count'))
        mismatch_count = _safe_int(batch_result.get('mismatch_count'))
        if mismatch_count:
            run['retry_count'] = _safe_int(run.get('retry_count')) + max(mismatch_count - 1, 0)
        run = _update_run_progress(
            run,
            completed_batches,
            processed_rows,
            batch_result.get('batch_row_count'),
            batch_result.get('elapsed_seconds'),
            mismatch_count=mismatch_count,
        )
    return run, completed_batches, processed_rows


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
        batch_concurrency = _settings_int(
            settings,
            'tabular_generated_output_batch_concurrency',
            TABULAR_EXPORT_DEFAULT_BATCH_CONCURRENCY,
            minimum=1,
            maximum=TABULAR_EXPORT_MAX_BATCH_CONCURRENCY,
        )
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
            chat_service = _build_chat_service(
                run.get('gpt_model'),
                settings,
                model_context=run.get('model_context'),
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

        log_event(
            '[Tabular Generated Output] Background export run started',
            {
                'run_id': normalized_run_id,
                'conversation_id': run.get('conversation_id'),
                'user_id': normalized_user_id,
                'source_file_name': run.get('source_file_name'),
                'output_format': run.get('output_format'),
                'row_count': run.get('row_count'),
                'batch_count': batch_count,
                'resume_completed_batches': completed_batches,
                'batch_concurrency': batch_concurrency,
                'batch_timeout_seconds': batch_timeout_seconds,
            },
            level=logging.INFO,
        )

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
            )

            generation_error = None
            if batch_requests:
                log_event(
                    '[Tabular Generated Output] Building background structured export batch window',
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
                        )
                    )
                _raise_if_tabular_export_canceled(run)
                batch_results.update(_checkpoint_generated_batch_results(run, generated_results))

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
            return _mark_run_retryable(run, exc, settings)
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
    normalized_output_format = str(output_format or 'json').strip().lower() or 'json'
    generated_file_name = _build_generated_file_name(source_file_name, normalized_output_format)
    settings = settings or {}
    source_descriptor = dict(source_descriptor or {})
    source_authorization = dict(source_candidate.get('source_authorization') or {})
    staged_row_count = 0
    staged_char_count = 0
    staged_batch_count = 0

    if source_descriptor:
        staged_row_count = _safe_int(source_descriptor.get('expected_row_count'))
        if staged_row_count <= 0:
            raise ValueError('Source query descriptor must include the expected row count')
        source_descriptor['batch_max_rows'] = _safe_int(
            source_descriptor.get('batch_max_rows'),
            default=_settings_int(
                settings,
                'tabular_generated_output_max_batch_rows',
                TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_ROWS,
                minimum=1,
                maximum=100,
            ),
            minimum=1,
            maximum=100,
        )
        source_descriptor['batch_max_chars'] = _safe_int(
            source_descriptor.get('batch_max_chars'),
            default=_settings_int(
                settings,
                'tabular_generated_output_max_batch_chars',
                TABULAR_EXPORT_DEFAULT_SOURCE_BATCH_CHARS,
                minimum=6000,
                maximum=120000,
            ),
            minimum=6000,
            maximum=120000,
        )
        staged_batch_count = max(
            1,
            math.ceil(staged_row_count / source_descriptor['batch_max_rows']),
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
            staged_char_count += len(json.dumps(prepared_batch_rows, default=str, ensure_ascii=False))
            staged_batch_count = index

        if not staged_batch_count or not staged_row_count:
            raise ValueError('At least one source row is required for a background tabular export')

    now = _now_iso()
    run = {
        'id': run_id,
        'type': TABULAR_EXPORT_RUN_TYPE,
        'contract_version': TABULAR_EXPORT_CONTRACT_VERSION,
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
        'passthrough_input_rows': bool(passthrough_input_rows),
        'generated_file_name': generated_file_name,
        'row_count': staged_row_count,
        'batch_count': staged_batch_count,
        'completed_batches': 0,
        'processed_rows': 0,
        'output_schema': None,
        'source_descriptor': source_descriptor or None,
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
        'staged_input_char_count': staged_char_count,
        'mismatch_count': 0,
        'retry_count': 0,
        'recent_batches': [],
        'active_processing_seconds': 0,
        'last_message': 'Queued background structured export',
        'last_error': None,
        'final_artifact': None,
    }
    cosmos_tabular_export_runs_container.create_item(body=run)
    submitted = submit_tabular_generated_output_run(run_id, normalized_user_id)
    run['submitted_to_executor'] = submitted

    log_event(
        '[Tabular Generated Output] Queued background export run',
        {
            'run_id': run_id,
            'conversation_id': normalized_conversation_id,
            'user_id': normalized_user_id,
            'source_file_name': source_file_name,
            'selected_sheet': selected_sheet,
            'output_format': normalized_output_format,
            'row_count': staged_row_count,
            'batch_count': staged_batch_count,
            'staged_input_char_count': staged_char_count,
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
            '[Tabular Generated Output] Background scheduler scan result',
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
