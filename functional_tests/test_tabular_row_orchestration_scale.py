# test_tabular_row_orchestration_scale.py
"""
Functional test for scalable per-row tabular orchestration.
Version: 0.250.065
Implemented in: 0.250.060; generated CSV formula safety in 0.250.065

This test ensures generated exports preserve source identity and row order while
enforcing one stable output schema across independently generated batches.
"""

import ast
import csv
import io
import importlib.util
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from collections import Counter
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / 'application' / 'single_app'
EXPORT_MODULE = REPO_ROOT / 'application' / 'single_app' / 'functions_tabular_generated_exports.py'
CHAT_ROUTE = REPO_ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
SIMPLECHAT_OPERATIONS = REPO_ROOT / 'application' / 'single_app' / 'functions_simplechat_operations.py'
CSV_QUERY_MODULE = REPO_ROOT / 'application' / 'single_app' / 'functions_tabular_csv_query.py'
sys.path.append(str(APP_ROOT))

from functions_assistant_table_exports import (  # noqa: E402
    build_safe_csv_headers,
    neutralize_csv_spreadsheet_formula,
)
CONTRACT_FUNCTIONS = {
    '_normalize_source_identity_label',
    '_select_source_row_identity',
    '_prepare_tabular_source_rows',
    '_normalize_generated_batch_entries',
}
CONTRACT_CONSTANTS = {
    'TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD',
    'TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD',
    'TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD',
    'TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD',
    'TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD',
}
CANDIDATE_FUNCTIONS = {
    '_build_tabular_generated_output_candidate_diagnostic',
    '_build_tabular_generated_output_source_signature',
    '_coalesce_tabular_generated_output_pages',
    '_build_tabular_generated_output_source_candidate',
}
STREAM_FUNCTIONS = {
    '_serialize_generated_output_value',
    '_write_ordered_output_stream',
}
SOURCE_READER_FUNCTIONS = {
    'detect_tabular_csv_numeric_columns',
    'iter_tabular_csv_query_rows',
    'validate_tabular_csv_query_expression',
}
AUTHORIZATION_FUNCTIONS = {'_authorize_tabular_export_run_execution'}
CANCELLATION_FUNCTIONS = {
    '_can_cancel_run',
    'cancel_tabular_generated_output_run',
}
SUMMARY_FUNCTIONS = {
    '_build_generated_batch_summary',
    '_build_compact_post_run_summary',
}
FENCING_FUNCTIONS = {
    '_raise_if_tabular_export_canceled',
    '_replace_claimed_run',
}
LEGACY_MIGRATION_FUNCTIONS = {
    '_normalize_source_identity_label',
    '_select_source_row_identity',
    '_prepare_tabular_source_rows',
    '_migrate_legacy_tabular_export_run',
}
FAILURE_FUNCTIONS = {
    '_build_failed_tabular_generated_output_metadata',
    '_build_tabular_generated_output_system_message',
    '_has_generated_tabular_csv_output',
    '_normalize_generated_analysis_artifact_metadata',
}
ARTIFACT_FUNCTIONS = {'_upload_generated_chat_artifact_for_current_user'}
SCHEDULER_FUNCTIONS = {'_query_scheduler_candidates_by_status'}


def _load_contract_helpers():
    """Load the pure row-contract helpers without importing the Flask app."""
    source_text = EXPORT_MODULE.read_text(encoding='utf-8')
    module_tree = ast.parse(source_text, filename=str(EXPORT_MODULE))
    selected_nodes = []
    found_functions = set()
    found_constants = set()

    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in CONTRACT_FUNCTIONS:
            selected_nodes.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if assigned_names & CONTRACT_CONSTANTS:
                selected_nodes.append(node)
                found_constants.update(assigned_names & CONTRACT_CONSTANTS)

    missing_functions = CONTRACT_FUNCTIONS - found_functions
    missing_constants = CONTRACT_CONSTANTS - found_constants
    if missing_functions or missing_constants:
        raise AssertionError(
            f'Missing row-contract implementation: functions={sorted(missing_functions)}, '
            f'constants={sorted(missing_constants)}'
        )

    namespace = {'re': re, 'uuid': uuid}
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace


def _get_function_node(function_name):
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    for node in module_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    raise AssertionError(f'Missing function {function_name}')


def _called_function_names(function_node):
    return {
        call.func.id
        for call in ast.walk(function_node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    }


def _load_candidate_helpers():
    """Load candidate-selection helpers with minimal invocation adapters."""
    module_tree = ast.parse(CHAT_ROUTE.read_text(encoding='utf-8'), filename=str(CHAT_ROUTE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in CANDIDATE_FUNCTIONS
    ]
    found_functions = {node.name for node in selected_nodes}
    missing_functions = CANDIDATE_FUNCTIONS - found_functions
    if missing_functions:
        raise AssertionError(f'Missing candidate helpers: {sorted(missing_functions)}')

    def get_result_payload(invocation):
        return invocation.result if isinstance(invocation.result, dict) else None

    namespace = {
        'json': json,
        '_safe_int': lambda value: int(value or 0),
        'get_tabular_invocation_error_message': lambda invocation: invocation.error_message,
        'get_tabular_invocation_result_payload': get_result_payload,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(CHAT_ROUTE), 'exec'), namespace)
    return namespace


def _build_query_invocation(start_row, row_count, total_matches=300, source_etag='etag-source-7'):
    class InvocationPayload(dict):
        pass

    rows = [
        {'Case ID': f'SC-{2001 + row_index}'}
        for row_index in range(start_row, start_row + row_count)
    ]
    result_payload = InvocationPayload({
        'filename': 'simplechat_row_orchestration_dataset_300.csv',
        'query_expression': 'index == index',
        'start_row': start_row,
        'returned_rows': row_count,
        'total_matches': total_matches,
        'has_more': start_row + row_count < total_matches,
        'next_start_row': start_row + row_count if start_row + row_count < total_matches else None,
        'data': rows,
    })
    result_payload.internal_metadata = {
        'tabular_generated_export_source': {
            'version': 1,
            'kind': 'query_tabular_data',
            'source': 'chat',
            'container': 'personal-chat',
            'blob_path': 'user-1/conversation-1/nested/version-7/source.csv',
            'blob_etag': source_etag,
            'filename': 'simplechat_row_orchestration_dataset_300.csv',
            'query_expression': 'index == index',
            'expected_row_count': total_matches,
        },
        'tabular_source_authorization': {
            'source': 'chat',
            'scope_id': None,
            'container': 'personal-chat',
            'blob_path': 'user-1/conversation-1/nested/version-7/source.csv',
            'blob_etag': source_etag,
        },
    }
    return SimpleNamespace(
        plugin_name='TabularProcessingPlugin',
        function_name='query_tabular_data',
        parameters={
            'filename': 'simplechat_row_orchestration_dataset_300.csv',
            'query_expression': 'index == index',
            'source': 'chat',
            'start_row': str(start_row),
            'max_rows': '100',
        },
        result=result_payload,
        error_message=None,
    )


class _CountingTextSink:
    """Text sink that records write bounds without retaining generated output."""

    def __init__(self):
        self.write_count = 0
        self.total_char_count = 0
        self.max_write_chars = 0

    def write(self, value):
        value_length = len(value)
        self.write_count += 1
        self.total_char_count += value_length
        self.max_write_chars = max(self.max_write_chars, value_length)
        return value_length


def _load_stream_writer(download_json_blob):
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in STREAM_FUNCTIONS
    ]
    if len(selected_nodes) != len(STREAM_FUNCTIONS):
        raise AssertionError('Missing bounded output stream writer')

    namespace = {
        'build_safe_csv_headers': build_safe_csv_headers,
        'csv': csv,
        'json': json,
        'neutralize_csv_spreadsheet_formula': neutralize_csv_spreadsheet_formula,
        '_safe_int': lambda value: int(value or 0),
        '_output_blob_path': lambda user_id, conversation_id, run_id, batch_number: batch_number,
        '_download_json_blob': download_json_blob,
        'TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD': 'source_row_number',
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace['_write_ordered_output_stream']


class _SourceReaderPlugin:
    """Small plugin stand-in that records the largest source chunk received."""

    max_chunk_rows = 0

    def _normalize_dataframe_columns(self, dataframe):
        self.__class__.max_chunk_rows = max(self.__class__.max_chunk_rows, len(dataframe))
        normalized = dataframe.copy()
        normalized.columns = [str(column).strip() for column in normalized.columns]
        return normalized

    def _apply_query_expression_with_fallback(self, dataframe, query_expression=None, normalize_match=False):
        del normalize_match
        return dataframe.query(query_expression) if query_expression else dataframe, False

    def _parse_optional_column_list_argument(self, columns):
        if not columns:
            return None
        return [column.strip() for column in str(columns).split(',') if column.strip()]

    def _build_row_output_records(self, dataframe, selected_columns):
        return dataframe[selected_columns].to_dict(orient='records')


def _load_source_reader_helpers():
    module_spec = importlib.util.spec_from_file_location('functions_tabular_csv_query_test', CSV_QUERY_MODULE)
    query_module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(query_module)
    return {
        function_name: getattr(query_module, function_name)
        for function_name in SOURCE_READER_FUNCTIONS
    } | {'module': query_module}


def _load_authorization_helper(conversation_owner, visible_public_ids=None, group_authorizer=None):
    class CosmosResourceNotFoundError(Exception):
        pass

    class ConversationContainer:
        def read_item(self, item, partition_key):
            assert item == partition_key
            return {'id': item, 'user_id': conversation_owner}

    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in AUTHORIZATION_FUNCTIONS
    ]
    if len(selected_nodes) != len(AUTHORIZATION_FUNCTIONS):
        raise AssertionError('Missing export execution authorization helper')

    namespace = {
        'cosmos_conversations_container': ConversationContainer(),
        'CosmosResourceNotFoundError': CosmosResourceNotFoundError,
        'storage_account_personal_chat_container_name': 'personal-chat',
        'storage_account_user_documents_container_name': 'user-documents',
        'storage_account_group_documents_container_name': 'group-documents',
        'storage_account_public_documents_container_name': 'public-documents',
        'assert_group_role': group_authorizer or (lambda *args, **kwargs: 'User'),
        'get_user_visible_public_workspace_ids_from_settings': lambda user_id: list(visible_public_ids or []),
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace['_authorize_tabular_export_run_execution']


def _load_cancellation_helpers(initial_run):
    class CosmosResourceNotFoundError(Exception):
        pass

    stored_run = dict(initial_run)
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in CANCELLATION_FUNCTIONS
    ]
    if len(selected_nodes) != len(CANCELLATION_FUNCTIONS):
        raise AssertionError('Missing durable export cancellation helpers')

    def read_run(user_id, run_id):
        assert user_id == stored_run['user_id']
        assert run_id == stored_run['id']
        return dict(stored_run)

    def replace_run(run):
        stored_run.clear()
        stored_run.update(run)
        return dict(stored_run)

    namespace = {
        'logging': logging,
        'CosmosResourceNotFoundError': CosmosResourceNotFoundError,
        'TABULAR_EXPORT_STATUS_COMPLETED': 'completed',
        'TABULAR_EXPORT_STATUS_CANCELED': 'canceled',
        'get_settings': lambda: {},
        '_read_run': read_run,
        '_replace_run': replace_run,
        '_now_iso': lambda: '2026-07-21T18:00:00+00:00',
        'log_event': lambda *args, **kwargs: None,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    namespace['_build_run_public_status'] = lambda run, settings=None: {
        'status': run.get('status'),
        'can_cancel': namespace['_can_cancel_run'](run),
    }
    return namespace, stored_run


def _load_summary_helpers(batch_summaries):
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in SUMMARY_FUNCTIONS
    ]
    if len(selected_nodes) != len(SUMMARY_FUNCTIONS):
        raise AssertionError('Missing bounded post-run summary helpers')

    namespace = {
        'Counter': Counter,
        '_safe_int': lambda value: int(value or 0),
        'TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD': 'source_row_number',
        'TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD': 'source_row_identity',
        'TABULAR_EXPORT_SUMMARY_MAX_FIELDS': 25,
        'TABULAR_EXPORT_SUMMARY_MAX_VALUES_PER_FIELD': 5,
        'TABULAR_EXPORT_SUMMARY_AGGREGATE_MAX_VALUES': 25,
        '_output_summary_blob_path': lambda user_id, conversation_id, run_id, batch_number: batch_number,
        '_blob_exists': lambda batch_number: batch_number in batch_summaries,
        '_download_json_blob': lambda batch_number: batch_summaries[batch_number],
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace


def _load_fencing_helpers(current_run, replace_error=None):
    class TabularExportCanceledError(RuntimeError):
        pass

    class TabularExportLeaseLostError(RuntimeError):
        pass

    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in FENCING_FUNCTIONS
    ]
    if len(selected_nodes) != len(FENCING_FUNCTIONS):
        raise AssertionError('Missing lease fencing helpers')

    namespace = {
        'TABULAR_EXPORT_STATUS_CANCELED': 'canceled',
        'TABULAR_EXPORT_STATUS_RUNNING': 'running',
        'TabularExportCanceledError': TabularExportCanceledError,
        'TabularExportLeaseLostError': TabularExportLeaseLostError,
        '_safe_int': lambda value: int(value or 0),
        '_read_run': lambda user_id, run_id: dict(current_run),
        '_replace_run': lambda run: (_ for _ in ()).throw(replace_error) if replace_error else dict(run),
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace


def _load_legacy_migration_helper(aggregate_batches):
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in LEGACY_MIGRATION_FUNCTIONS
    ]
    if len(selected_nodes) != len(LEGACY_MIGRATION_FUNCTIONS):
        raise AssertionError('Missing legacy export migration helpers')

    uploaded_batches = {}
    deleted_blobs = []
    namespace = {
        're': re,
        'uuid': uuid,
        'TABULAR_EXPORT_CONTRACT_VERSION': 2,
        'TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD': '__simplechat_source_row_number',
        'TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD': '__simplechat_source_row_identity',
        'TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD': '__simplechat_source_row_token',
        '_safe_int': lambda value: int(value or 0),
        '_download_json_blob': lambda path: aggregate_batches if path == 'legacy-input.json' else uploaded_batches[path],
        '_upload_json_blob': lambda path, payload, metadata=None: uploaded_batches.__setitem__(path, payload),
        '_input_blob_path': lambda user_id, conversation_id, run_id, batch_number: f'batch-{batch_number}',
        '_output_blob_path': lambda user_id, conversation_id, run_id, batch_number: f'output-{batch_number}',
        '_output_summary_blob_path': lambda user_id, conversation_id, run_id, batch_number: f'summary-{batch_number}',
        '_delete_blob_if_exists': deleted_blobs.append,
        '_now_iso': lambda: '2026-07-21T18:00:00+00:00',
        '_raise_if_tabular_export_canceled': lambda run: run,
        '_replace_claimed_run': lambda run: dict(run),
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace['_migrate_legacy_tabular_export_run'], uploaded_batches, deleted_blobs


def _load_failed_export_helpers():
    module_tree = ast.parse(CHAT_ROUTE.read_text(encoding='utf-8'), filename=str(CHAT_ROUTE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in FAILURE_FUNCTIONS
    ]
    if len(selected_nodes) != len(FAILURE_FUNCTIONS):
        raise AssertionError('Missing explicit failed-export fallback helpers')

    namespace = {
        '_safe_int': lambda value: int(value or 0),
        '_build_tabular_generated_output_file_name': (
            lambda filename, output_format: f"{Path(filename).stem}_generated.{output_format}"
        ),
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(CHAT_ROUTE), 'exec'), namespace)
    return namespace


def _load_idempotent_artifact_helper():
    class CosmosResourceNotFoundError(Exception):
        pass

    class ConversationContainer:
        def read_item(self, item, partition_key):
            return {'id': item, 'user_id': 'user-1'}

    class MessageContainer:
        def __init__(self):
            self.items = {}
            self.upsert_count = 0

        def read_item(self, item, partition_key):
            if item not in self.items:
                raise CosmosResourceNotFoundError()
            return dict(self.items[item])

        def upsert_item(self, item):
            self.items[item['id']] = dict(item)
            self.upsert_count += 1
            return dict(item)

    class BlobClient:
        def __init__(self):
            self.uploaded = False

        def exists(self):
            return self.uploaded

        def upload_blob(self, content, overwrite, metadata):
            del content, overwrite, metadata
            self.uploaded = True

    class BlobServiceClient:
        def __init__(self):
            self.clients = {}

        def get_blob_client(self, container, blob):
            return self.clients.setdefault((container, blob), BlobClient())

    module_tree = ast.parse(SIMPLECHAT_OPERATIONS.read_text(encoding='utf-8'), filename=str(SIMPLECHAT_OPERATIONS))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in ARTIFACT_FUNCTIONS
    ]
    if len(selected_nodes) != len(ARTIFACT_FUNCTIONS):
        raise AssertionError('Missing idempotent artifact helper')

    message_container = MessageContainer()
    blob_service_client = BlobServiceClient()
    namespace = {
        'Any': Any,
        'Dict': Dict,
        'Optional': Optional,
        'CLIENTS': {'storage_account_office_docs_client': blob_service_client},
        'CosmosResourceNotFoundError': CosmosResourceNotFoundError,
        'TABULAR_EXTENSIONS': {'csv'},
        'cosmos_conversations_container': ConversationContainer(),
        'cosmos_messages_container': message_container,
        'datetime': datetime,
        'timezone': timezone,
        'os': os,
        'uuid': uuid,
        'storage_account_personal_chat_container_name': 'personal-chat',
        '_get_latest_personal_thread_id': lambda conversation_id: None,
        'log_event': lambda *args, **kwargs: None,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(SIMPLECHAT_OPERATIONS), 'exec'), namespace)
    return namespace['_upload_generated_chat_artifact_for_current_user'], message_container


def _load_scheduler_query_helper(runs):
    class RunContainer:
        def __init__(self):
            self.query = None

        def query_items(self, query, parameters, enable_cross_partition_query):
            del parameters, enable_cross_partition_query
            self.query = query
            return iter(runs)

    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in SCHEDULER_FUNCTIONS
    ]
    if len(selected_nodes) != len(SCHEDULER_FUNCTIONS):
        raise AssertionError('Missing scheduler candidate query helper')

    run_container = RunContainer()
    namespace = {
        'TABULAR_EXPORT_DEFAULT_SCAN_LIMIT': 5,
        'TABULAR_EXPORT_RUN_TYPE': 'tabular_generated_output_run',
        '_safe_int': lambda value, default=0, minimum=None, maximum=None: max(
            minimum or int(value or default),
            min(maximum or int(value or default), int(value or default)),
        ),
        '_scheduler_candidate_reason': lambda run, settings: 'eligible' if run.get('eligible') else None,
        'cosmos_tabular_export_runs_container': run_container,
        'log_event': lambda *args, **kwargs: None,
        'logging': logging,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace['_query_scheduler_candidates_by_status'], run_container


def test_source_identity_and_order_contract():
    """Every row receives a canonical ordinal and preserves its source identifier."""
    helpers = _load_contract_helpers()
    source_rows = [
        {'Case ID': f'SC-{2001 + index}', 'Comment': f'row {index + 1}'}
        for index in range(300)
    ]

    prepared_rows = helpers['_prepare_tabular_source_rows'](source_rows, start_row=0)

    assert len(prepared_rows) == 300
    assert prepared_rows[0]['__simplechat_source_row_number'] == 1
    assert prepared_rows[-1]['__simplechat_source_row_number'] == 300
    assert prepared_rows[0]['__simplechat_source_row_identity'] == 'SC-2001'
    assert prepared_rows[-1]['__simplechat_source_row_identity'] == 'SC-2300'
    assert len({row['__simplechat_source_row_token'] for row in prepared_rows}) == 300
    assert [row['__simplechat_source_row_number'] for row in prepared_rows] == list(range(1, 301))


def test_generated_batch_schema_contract():
    """Batch output is ordered by the first schema and source identity is authoritative."""
    helpers = _load_contract_helpers()
    prepared_rows = helpers['_prepare_tabular_source_rows'](
        [
            {'Case ID': 'SC-2001', 'Comment': 'first'},
            {'Case ID': 'SC-2002', 'Comment': 'second'},
        ],
        start_row=0,
    )
    generated_entries = [
        {
            '__simplechat_source_row_token': prepared_rows[0]['__simplechat_source_row_token'],
            'answer': 'yes',
            'risk': 'low',
        },
        {
            '__simplechat_source_row_token': prepared_rows[1]['__simplechat_source_row_token'],
            'risk': 'high',
            'answer': 'no',
        },
    ]

    normalized_entries, output_schema = helpers['_normalize_generated_batch_entries'](
        prepared_rows,
        generated_entries,
    )

    assert output_schema == ['source_row_number', 'source_row_identity', 'answer', 'risk']
    assert list(normalized_entries[1]) == output_schema
    assert normalized_entries[0]['source_row_number'] == 1
    assert normalized_entries[1]['source_row_identity'] == 'SC-2002'

    try:
        helpers['_normalize_generated_batch_entries'](
            prepared_rows,
            [
                {
                    '__simplechat_source_row_token': prepared_rows[0]['__simplechat_source_row_token'],
                    'answer': 'yes',
                    'risk': 'low',
                },
                {
                    '__simplechat_source_row_token': prepared_rows[1]['__simplechat_source_row_token'],
                    'answer': 'no',
                    'unexpected': 'schema drift',
                },
            ],
            expected_output_schema=output_schema,
        )
    except ValueError as exc:
        assert 'schema' in str(exc).lower()
    else:
        raise AssertionError('Schema drift must fail before a batch is checkpointed')

    try:
        helpers['_normalize_generated_batch_entries'](
            prepared_rows,
            [
                {
                    '__simplechat_source_row_token': prepared_rows[1]['__simplechat_source_row_token'],
                    'answer': 'no',
                    'risk': 'high',
                },
                {
                    '__simplechat_source_row_token': prepared_rows[0]['__simplechat_source_row_token'],
                    'answer': 'yes',
                    'risk': 'low',
                },
            ],
            expected_output_schema=output_schema,
        )
    except ValueError as exc:
        assert 'token mismatch' in str(exc).lower()
    else:
        raise AssertionError('Swapped model rows must fail source-token validation')


def test_durable_runner_enforces_row_contract():
    """Queueing, generation, and checkpointing must all enforce the shared contract."""
    queue_calls = _called_function_names(_get_function_node('queue_tabular_generated_output_run'))
    generation_calls = _called_function_names(_get_function_node('_generate_batch_entries'))
    checkpoint_source = ast.unparse(_get_function_node('_checkpoint_generated_batch_results'))
    process_source = ast.unparse(_get_function_node('process_tabular_generated_output_run'))

    assert '_prepare_tabular_source_rows' in queue_calls
    assert '_normalize_generated_batch_entries' in generation_calls
    assert "run['output_schema']" in checkpoint_source
    assert "run.get('output_schema')" in process_source
    assert 'window_end = window_start' in process_source
    assert process_source.index('_authorize_tabular_export_run_execution') < process_source.index(
        '_migrate_legacy_tabular_export_run'
    )
    resume_source = ast.unparse(_get_function_node('resume_tabular_generated_output_run'))
    assert resume_source.index('_authorize_tabular_export_run_execution') < resume_source.index('run.update')
    complete_source = ast.unparse(_get_function_node('_complete_run'))
    assert complete_source.index('_write_ordered_output_stream') < complete_source.index(
        'upload_generated_analysis_artifact_stream_for_user'
    )
    assert complete_source.index('upload_generated_analysis_artifact_stream_for_user') < complete_source.index(
        "'status': TABULAR_EXPORT_STATUS_COMPLETED"
    )


def test_paginated_candidate_coalesces_all_300_rows():
    """Compatible tool pages form one exhaustive, ordered export source."""
    helpers = _load_candidate_helpers()
    invocations = [
        _build_query_invocation(0, 94),
        _build_query_invocation(94, 95),
        _build_query_invocation(189, 94),
        _build_query_invocation(283, 17),
    ]

    candidate = helpers['_build_tabular_generated_output_source_candidate'](invocations)

    assert candidate['full_result_available'] is True
    assert candidate['row_count'] == 300
    assert len(candidate['rows']) == 300
    assert candidate['rows'][0]['Case ID'] == 'SC-2001'
    assert candidate['rows'][-1]['Case ID'] == 'SC-2300'
    assert candidate['page_count'] == 4
    assert candidate['source_descriptor']['blob_path'] == (
        'user-1/conversation-1/nested/version-7/source.csv'
    )
    assert candidate['source_descriptor']['blob_etag'] == 'etag-source-7'
    assert candidate['source_authorization']['container'] == 'personal-chat'


def test_paginated_candidate_rejects_gaps():
    """Missing source intervals remain incomplete instead of producing a partial export."""
    helpers = _load_candidate_helpers()
    invocations = [
        _build_query_invocation(0, 94),
        _build_query_invocation(95, 205),
    ]

    candidate = helpers['_build_tabular_generated_output_source_candidate'](invocations)

    assert candidate['full_result_available'] is False
    assert candidate['validation_error']
    assert 'gap' in candidate['validation_error'].lower()


def test_paginated_candidate_rejects_mixed_source_versions():
    """Contiguous pages from different blob ETags cannot form an exhaustive source."""
    helpers = _load_candidate_helpers()
    invocations = [
        _build_query_invocation(0, 150, source_etag='etag-source-7'),
        _build_query_invocation(150, 150, source_etag='etag-source-8'),
    ]

    candidate = helpers['_build_tabular_generated_output_source_candidate'](invocations)

    assert candidate['full_result_available'] is False
    assert 'different source blobs or versions' in candidate['validation_error'].lower()


def test_streaming_finalizer_writes_30000_rows_in_bounded_chunks():
    """Final assembly reads one checkpoint at a time and never builds a full row list."""
    requested_batches = []

    def download_batch(batch_number):
        requested_batches.append(batch_number)
        first_row_number = ((batch_number - 1) * 50) + 1
        return [
            {
                'source_row_number': first_row_number + offset,
                'source_row_identity': f'SC-{first_row_number + offset}',
                'answer': 'yes',
            }
            for offset in range(50)
        ]

    write_output = _load_stream_writer(download_batch)
    output_sink = _CountingTextSink()
    run = {
        'id': 'run-30000',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'output_format': 'csv',
        'row_count': 30000,
        'batch_count': 600,
        'output_schema': ['source_row_number', 'source_row_identity', 'answer'],
    }

    written_rows = write_output(run, output_sink)

    assert written_rows == 30000
    assert requested_batches == list(range(1, 601))
    assert output_sink.total_char_count > 30000
    assert output_sink.max_write_chars < 1000


def test_streaming_finalizer_neutralizes_csv_formulas():
    """Durable CSV assembly neutralizes formula-like headers and values."""
    def download_batch(batch_number):
        assert batch_number == 1
        return [
            {
                'source_row_number': 1,
                'source_row_identity': 'SC-1',
                '=Result': '=WEBSERVICE("https://example.invalid")',
                'Amount': '-1,234.50',
            }
        ]

    write_output = _load_stream_writer(download_batch)
    output_stream = io.StringIO()
    run = {
        'id': 'run-formula-safety',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'output_format': 'csv',
        'row_count': 1,
        'batch_count': 1,
        'output_schema': ['source_row_number', 'source_row_identity', '=Result', 'Amount'],
    }

    written_rows = write_output(run, output_stream)
    csv_rows = list(csv.DictReader(io.StringIO(output_stream.getvalue())))

    assert written_rows == 1
    assert csv_rows[0]["'=Result"].startswith("'=")
    assert csv_rows[0]['Amount'] == '-1,234.50'


def test_streaming_finalizer_rejects_source_order_gaps():
    """An ordinal gap fails final validation before the artifact is published."""
    def download_batch(batch_number):
        if batch_number == 1:
            return [
                {'source_row_number': 1, 'source_row_identity': 'SC-1', 'answer': 'yes'},
                {'source_row_number': 2, 'source_row_identity': 'SC-2', 'answer': 'yes'},
            ]
        return [
            {'source_row_number': 4, 'source_row_identity': 'SC-4', 'answer': 'yes'},
        ]

    write_output = _load_stream_writer(download_batch)
    run = {
        'id': 'run-gap',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'output_format': 'json',
        'row_count': 3,
        'batch_count': 2,
        'output_schema': ['source_row_number', 'source_row_identity', 'answer'],
    }

    try:
        write_output(run, _CountingTextSink())
    except ValueError as exc:
        assert 'order' in str(exc).lower() or 'gap' in str(exc).lower()
    else:
        raise AssertionError('Finalization must reject a source ordinal gap')


def test_csv_query_source_reader_scales_and_resumes():
    """CSV replay scans bounded chunks and can resume from a physical source row."""
    helpers = _load_source_reader_helpers()
    _SourceReaderPlugin.max_chunk_rows = 0
    csv_content = 'Case ID,Score\n' + ''.join(
        f'SC-{row_number},{row_number}\n'
        for row_number in range(1, 30001)
    )
    descriptor = {
        'query_expression': 'Score >= 0',
        'return_columns': 'Case ID,Score',
    }

    original_read_csv = helpers['module'].pandas.read_csv
    observed_skiprows = []

    def recording_read_csv(*args, **kwargs):
        observed_skiprows.append(kwargs.get('skiprows'))
        return original_read_csv(*args, **kwargs)

    helpers['module'].pandas.read_csv = recording_read_csv
    try:
        row_iterator = helpers['iter_tabular_csv_query_rows'](
            csv_stream=io.StringIO(csv_content),
            query_expression=descriptor['query_expression'],
            return_columns=descriptor['return_columns'],
            source_chunk_rows=257,
            tabular_plugin=_SourceReaderPlugin(),
            start_source_row=15000,
        )
        row_count = 0
        first_result = None
        last_result = None
        for result in row_iterator:
            row_count += 1
            first_result = first_result or result
            last_result = result
    finally:
        helpers['module'].pandas.read_csv = original_read_csv

    assert row_count == 15000
    assert first_result == (15001, {'Case ID': 'SC-15001', 'Score': 15001})
    assert last_result == (30000, {'Case ID': 'SC-30000', 'Score': 30000})
    assert _SourceReaderPlugin.max_chunk_rows <= 257
    assert any(callable(skiprows) for skiprows in observed_skiprows)

    assert helpers['validate_tabular_csv_query_expression'](
        '`Case ID` in ["SC-1", "SC-2"] and Score >= 0'
    )
    try:
        helpers['validate_tabular_csv_query_expression']('Score > Score.mean()')
    except ValueError as exc:
        assert 'bounded chunks' in str(exc)
    else:
        raise AssertionError('Cross-row aggregation calls must be rejected')

    try:
        list(helpers['iter_tabular_csv_query_rows'](
            csv_stream=io.StringIO(csv_content),
            query_expression='Score > @dynamic_threshold',
            return_columns=None,
            source_chunk_rows=257,
            tabular_plugin=_SourceReaderPlugin(),
        ))
    except ValueError as exc:
        assert 'bounded chunks' in str(exc)
    else:
        raise AssertionError('Cross-chunk query context must be rejected for durable replay')


def test_worker_revalidates_conversation_and_workspace_authorization():
    """Stored source descriptors are authorized again whenever a worker executes."""
    authorize_personal = _load_authorization_helper('user-1')
    personal_run = {
        'id': 'run-personal',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'source_descriptor': {
            'source': 'chat',
            'container': 'personal-chat',
            'blob_path': 'user-1/conversation-1/source.csv',
        },
    }
    assert authorize_personal(personal_run)['user_id'] == 'user-1'

    authorize_wrong_owner = _load_authorization_helper('different-user')
    try:
        authorize_wrong_owner(personal_run)
    except PermissionError as exc:
        assert 'ownership' in str(exc).lower()
    else:
        raise AssertionError('A worker must reject a conversation whose ownership changed')

    authorized_groups = []

    def authorize_group(user_id, group_id, allowed_roles):
        authorized_groups.append((user_id, group_id, tuple(allowed_roles)))
        return 'User'

    authorize_group_run = _load_authorization_helper('user-1', group_authorizer=authorize_group)
    group_run = {
        'id': 'run-group',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'source_descriptor': {
            'source': 'group',
            'scope_id': 'group-1',
            'container': 'group-documents',
            'blob_path': 'group-1/source.csv',
        },
    }
    authorize_group_run(group_run)
    assert authorized_groups == [
        ('user-1', 'group-1', ('Owner', 'Admin', 'DocumentManager', 'User')),
    ]

    authorize_public = _load_authorization_helper('user-1', visible_public_ids=['public-1'])
    public_run = {
        'id': 'run-public',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'source_descriptor': {
            'source': 'public',
            'scope_id': 'public-1',
            'container': 'public-documents',
            'blob_path': 'public-1/source.csv',
        },
    }
    authorize_public(public_run)


def test_durable_cancellation_is_idempotent_and_terminal():
    """Cancel persists a terminal state that cannot be resumed or canceled again."""
    helpers, stored_run = _load_cancellation_helpers({
        'id': 'run-cancel',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'status': 'running',
        'completed_batches': 25,
        'processed_rows': 1250,
    })

    cancel_result = helpers['cancel_tabular_generated_output_run']('user-1', 'run-cancel')
    assert cancel_result['success'] is True
    assert cancel_result['canceled'] is True
    assert cancel_result['run']['can_cancel'] is False
    assert stored_run['status'] == 'canceled'
    assert stored_run['next_attempt_at'] is None

    repeated_result = helpers['cancel_tabular_generated_output_run']('user-1', 'run-cancel')
    assert repeated_result['success'] is True
    assert repeated_result['message'] == 'Background export is already canceled.'


def test_worker_lease_fencing_rejects_stale_claims():
    """A reclaimed or canceled run stops the stale worker before it mutates state."""
    owned_run = {
        'id': 'run-fenced',
        'user_id': 'user-1',
        'status': 'running',
        'lease_holder_id': 'worker-a',
        'lease_generation': 3,
        '_etag': 'etag-3',
    }
    helpers = _load_fencing_helpers(owned_run)
    local_run = dict(owned_run)
    helpers['_raise_if_tabular_export_canceled'](local_run)
    assert local_run['_etag'] == 'etag-3'

    reclaimed_run = dict(owned_run, lease_holder_id='worker-b', lease_generation=4, _etag='etag-4')
    helpers = _load_fencing_helpers(reclaimed_run)
    try:
        helpers['_raise_if_tabular_export_canceled'](dict(owned_run))
    except RuntimeError as exc:
        assert 'lost its claim' in str(exc)
    else:
        raise AssertionError('A stale worker must lose its lease fence')

    canceled_run = dict(owned_run, status='canceled', _etag='etag-canceled')
    helpers = _load_fencing_helpers(canceled_run)
    try:
        helpers['_raise_if_tabular_export_canceled'](dict(owned_run))
    except RuntimeError as exc:
        assert 'canceled' in str(exc)
    else:
        raise AssertionError('A canceled run must stop its worker')

    class PreconditionFailed(Exception):
        status_code = 412

    helpers = _load_fencing_helpers(owned_run, replace_error=PreconditionFailed())
    try:
        helpers['_replace_claimed_run'](dict(owned_run))
    except RuntimeError as exc:
        assert 'lost its claim' in str(exc)
    else:
        raise AssertionError('An ETag conflict must fence the stale worker')


def test_legacy_run_migration_tokenizes_inputs_and_resets_outputs():
    """Pre-contract runs migrate deterministic inputs and regenerate old outputs."""
    aggregate_batches = [
        [{'Case ID': 'SC-1'}, {'Case ID': 'SC-2'}],
        [{'Case ID': 'SC-3'}],
    ]
    migrate_run, uploaded_batches, deleted_blobs = _load_legacy_migration_helper(aggregate_batches)
    migrated_run = migrate_run({
        'id': 'legacy-run',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'row_count': 3,
        'batch_count': 2,
        'completed_batches': 1,
        'processed_rows': 2,
        'input_blob_path': 'legacy-input.json',
    })

    assert migrated_run['contract_version'] == 2
    assert migrated_run['completed_batches'] == 0
    assert migrated_run['processed_rows'] == 0
    assert migrated_run['output_schema'] is None
    assert migrated_run['regenerate_legacy_output_checkpoints'] is False
    assert migrated_run['input_blob_path'] is None
    assert [row['__simplechat_source_row_number'] for row in uploaded_batches['batch-1']] == [1, 2]
    assert uploaded_batches['batch-2'][0]['__simplechat_source_row_number'] == 3
    assert deleted_blobs == ['output-1', 'summary-1', 'output-2', 'summary-2']
    migrate_again, second_uploaded_batches, _ = _load_legacy_migration_helper(aggregate_batches)
    migrate_again({
        'id': 'legacy-run',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'row_count': 3,
        'batch_count': 2,
        'completed_batches': 1,
        'processed_rows': 2,
        'input_blob_path': 'legacy-input.json',
    })
    assert uploaded_batches['batch-1'][0]['__simplechat_source_row_token'] == (
        second_uploaded_batches['batch-1'][0]['__simplechat_source_row_token']
    )


def test_post_run_summary_uses_only_bounded_batch_summaries():
    """Thirty-thousand-row overall analysis merges compact checkpoint summaries only."""
    batch_summaries = {}
    helpers = _load_summary_helpers(batch_summaries)
    for batch_number in range(1, 601):
        first_row_number = ((batch_number - 1) * 50) + 1
        batch_entries = [
            {
                'source_row_number': first_row_number + offset,
                'source_row_identity': f'SC-{first_row_number + offset}',
                'answer': 'yes' if offset % 2 == 0 else 'no',
                'risk': 'low' if offset < 40 else 'high',
            }
            for offset in range(50)
        ]
        batch_summaries[batch_number] = helpers['_build_generated_batch_summary'](batch_entries)

    summary = helpers['_build_compact_post_run_summary']({
        'id': 'run-summary',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'row_count': 30000,
        'batch_count': 600,
    })

    assert 'Processed 30,000 ordered row(s) across 600 checkpointed batch(es).' in summary
    assert 'answer 100% populated' in summary
    assert 'risk 100% populated' in summary
    assert 'answer: yes (15,000), no (15,000)' in summary
    assert len(summary) < 2000


def test_final_artifact_publication_is_retry_idempotent():
    """Retrying final publication reuses one deterministic artifact message and blob."""
    upload_artifact, message_container = _load_idempotent_artifact_helper()
    upload_arguments = {
        'current_user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'normalized_file_name': 'generated.csv',
        'file_content_bytes': b'source_row_number,answer\n1,yes\n',
        'artifact_metadata': {
            'capability': 'tabular',
            'output_format': 'csv',
            'summary': 'Processed 1 ordered row.',
        },
        'artifact_idempotency_key': 'tabular-generated-output:run-1',
    }

    first_result = upload_artifact(**upload_arguments)
    second_result = upload_artifact(**upload_arguments)

    assert first_result['message']['id'] == second_result['message']['id']
    assert first_result['message']['blob_path'] == second_result['message']['blob_path']
    assert message_container.upsert_count == 1


def test_scheduler_filters_before_limiting_candidates():
    """Ineligible rows before the scan limit cannot hide an older recoverable run."""
    runs = [
        {'id': f'healthy-{index}', 'eligible': False}
        for index in range(1, 7)
    ] + [
        {'id': 'stale-run', 'eligible': True},
    ]
    query_candidates, run_container = _load_scheduler_query_helper(runs)

    candidates = query_candidates('running', 1, settings={})

    assert [candidate['id'] for candidate in candidates] == ['stale-run']
    assert 'TOP' not in run_container.query.upper()
    assert 'ORDER BY c.updated_at ASC' in run_container.query


def test_route_queues_replayable_pages_and_suppresses_summary_fallback():
    """Multi-page runs expose durable metadata that blocks assistant-table fallback exports."""
    route_source = CHAT_ROUTE.read_text(encoding='utf-8')
    assert 'should_queue_source_backed_run' in route_source
    assert 'should_queue_materialized_pages' in route_source
    assert 'exceeds_background_threshold' in route_source
    assert 'source_descriptor=source_descriptor' in route_source
    assert "output_metadata.get('background_export')" in route_source
    assert '_has_generated_tabular_csv_output(existing_outputs)' in route_source

    helpers = _load_failed_export_helpers()
    failed_output = helpers['_build_failed_tabular_generated_output_metadata'](
        {
            'filename': 'source.csv',
            'total_matches': 300,
        },
        'json',
        'Source replay failed. No partial export was created.',
    )
    assert failed_output['status'] == 'failed'
    assert failed_output['background_export'] is True
    assert failed_output['suppress_assistant_table_export'] is True
    assert helpers['_has_generated_tabular_csv_output']([failed_output]) is True
    normalized_failure = helpers['_normalize_generated_analysis_artifact_metadata'](
        failed_output,
        default_capability='tabular',
    )
    assert normalized_failure['status'] == 'failed'
    assert normalized_failure['background_export'] is True
    assert not normalized_failure.get('export_run_id')
    failure_handoff = helpers['_build_tabular_generated_output_system_message'](failed_output)
    assert 'failed' in failure_handoff.lower()
    assert 'do not recreate' in failure_handoff.lower()
    chat_messages_source = (
        REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-messages.js'
    ).read_text(encoding='utf-8')
    assert 'isTerminalExportStatus' in chat_messages_source
    assert 'output.suppress_assistant_table_export' in chat_messages_source


def main():
    """Run focused row-orchestration contract checks."""
    tests = [
        test_source_identity_and_order_contract,
        test_generated_batch_schema_contract,
        test_durable_runner_enforces_row_contract,
        test_paginated_candidate_coalesces_all_300_rows,
        test_paginated_candidate_rejects_gaps,
        test_paginated_candidate_rejects_mixed_source_versions,
        test_streaming_finalizer_writes_30000_rows_in_bounded_chunks,
        test_streaming_finalizer_neutralizes_csv_formulas,
        test_streaming_finalizer_rejects_source_order_gaps,
        test_csv_query_source_reader_scales_and_resumes,
        test_worker_revalidates_conversation_and_workspace_authorization,
        test_durable_cancellation_is_idempotent_and_terminal,
        test_worker_lease_fencing_rejects_stale_claims,
        test_legacy_run_migration_tokenizes_inputs_and_resets_outputs,
        test_post_run_summary_uses_only_bounded_batch_summaries,
        test_final_artifact_publication_is_retry_idempotent,
        test_scheduler_filters_before_limiting_candidates,
        test_route_queues_replayable_pages_and_suppresses_summary_fallback,
    ]
    for test in tests:
        print(f'Running {test.__name__}...')
        test()
        print(f'PASS {test.__name__}')
    return True


if __name__ == '__main__':
    sys.exit(0 if main() else 1)