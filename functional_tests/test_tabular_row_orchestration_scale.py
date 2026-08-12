# test_tabular_row_orchestration_scale.py
"""
Functional test for scalable per-row tabular orchestration.
Version: 0.250.178
Implemented in: 0.250.060; generated CSV formula safety in 0.250.065; generated file export routing in 0.250.072; source descriptor generalization in 0.250.127; unified durable run contract in 0.250.128; hierarchical analysis in 0.250.129; combined analysis and export in 0.250.130; scale validation in 0.250.132; direct source-backed exhaustive queueing in 0.250.133; direct queue call-site hardening in 0.250.134; model-validation auto retry in 0.250.135; model-aware parallel throughput in 0.250.136; Phase 1 acceleration contracts and observability in 0.250.137; Phase 2 truthful background handoff in 0.250.138; Phase 3 durable LLM generation planning in 0.250.139; Phase 4 compact row response protocol in 0.250.140; Phase 5 completion-driven checkpointing in 0.250.141; Phase 6 rolling worker pool in 0.250.142; Phase 7 independent batch retries in 0.250.143; Phase 8 scale, chaos, and rollout in 0.250.144; background metadata streaming fix in 0.250.145; source-token echo recovery in 0.250.146; fixed-window stale heartbeat fix in 0.250.147; nested CSV output recovery in 0.250.148; generic tabular artifact routing and fast startup in 0.250.149; balanced concurrency waves and default completion checkpoints in 0.250.152; Search shared preflight adapter in 0.250.159; aggregate route-helper harness coverage in 0.250.166; Analyze artifact Phase 7A harness compatibility updated in 0.250.178

This test ensures generated exports preserve source identity and row order while
enforcing one stable output schema across independently generated batches.
"""

import ast
import asyncio
import csv
import heapq
import hashlib
import io
import importlib.util
import json
import logging
import math
import os
import pandas
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from collections import Counter
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / 'application' / 'single_app'
EXPORT_MODULE = REPO_ROOT / 'application' / 'single_app' / 'functions_tabular_generated_exports.py'
SETTINGS_MODULE = REPO_ROOT / 'application' / 'single_app' / 'functions_settings.py'
CHAT_ROUTE = REPO_ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
SIMPLECHAT_OPERATIONS = REPO_ROOT / 'application' / 'single_app' / 'functions_simplechat_operations.py'
CSV_QUERY_MODULE = REPO_ROOT / 'application' / 'single_app' / 'functions_tabular_csv_query.py'
TABULAR_PLUGIN_MODULE = APP_ROOT / 'semantic_kernel_plugins' / 'tabular_processing_plugin.py'
sys.path.append(str(APP_ROOT))
sys.path.append(str(Path(__file__).resolve().parent))

from generate_tabular_scale_fixtures import (  # noqa: E402
    SCALE_TIERS,
    iter_synthetic_rows,
)

from functions_assistant_table_exports import (  # noqa: E402
    assistant_table_export_requested,
    build_safe_csv_headers,
    has_generated_tabular_csv_output,
    neutralize_csv_spreadsheet_formula,
)
from functions_generated_file_exports import (  # noqa: E402
    get_requested_generated_file_format,
    get_requested_structured_artifact_format,
)
from functions_analysis_deliverables import (  # noqa: E402
    is_analysis_internal_lineage_field,
    project_structured_deliverable_row,
)
from functions_tabular_transformations import normalize_tabular_transformation_spec  # noqa: E402
from functions_tabular_orchestration import (  # noqa: E402
    build_tabular_legacy_post_tool_fallback_decision,
    get_tabular_generated_output_format,
    get_tabular_generated_output_task_type,
    question_requests_tabular_generated_output,
    settings_flag_enabled,
)
CONTRACT_FUNCTIONS = {
    '_safe_int',
    '_normalize_source_identity_label',
    '_select_source_row_identity',
    '_prepare_tabular_source_rows',
    '_normalize_generated_batch_entries',
    '_generated_entry_has_source_position_conflict',
    '_parse_single_nested_csv_generated_entry',
    '_expand_nested_csv_generated_entries',
    '_normalize_model_generated_batch_entries',
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
    '_validate_tabular_output_checkpoint_metadata',
    '_get_tabular_run_public_output_schema',
    '_get_tabular_run_serialized_public_schema',
    '_write_ordered_output_stream',
}
SOURCE_VERSION_FUNCTIONS = {'_revalidate_tabular_source_version_for_publication'}
CHECKPOINT_RESUME_FUNCTIONS = {'_build_batch_window'}
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
RETRY_FUNCTIONS = {
    '_safe_int',
    '_settings_int',
    '_parse_iso_datetime',
    '_build_tabular_generation_performance_summary',
    '_is_retryable_export_error_message',
    '_is_retryable_model_validation_error_message',
    '_is_retryable_failed_run',
    '_has_exhausted_independent_batch_retries',
    '_is_auto_retry_exhausted',
    '_can_auto_retry_failed_run',
    '_can_resume_run',
    '_mark_run_failed',
    '_get_auto_retry_limit_for_category',
    '_mark_run_retryable',
}
RETRY_CONSTANTS = {
    'TABULAR_EXPORT_STATUS_FAILED',
    'TABULAR_EXPORT_STATUS_QUEUED',
    'TABULAR_EXPORT_STATUS_RUNNING',
    'TABULAR_EXPORT_STATUS_COMPLETED',
    'TABULAR_EXPORT_STATUS_CANCELED',
    'TABULAR_EXPORT_DEFAULT_MAX_TRANSIENT_FAILURES',
    'TABULAR_EXPORT_DEFAULT_MODEL_VALIDATION_AUTO_RETRIES',
    'TABULAR_EXPORT_RETRYABLE_MESSAGE_MARKERS',
    'TABULAR_EXPORT_MODEL_VALIDATION_RETRYABLE_MESSAGE_MARKERS',
}
LEGACY_MIGRATION_FUNCTIONS = {
    '_normalize_source_identity_label',
    '_select_source_row_identity',
    '_prepare_tabular_source_rows',
    '_sync_tabular_generation_contract_fields',
    '_migrate_legacy_tabular_export_run',
}
FAILURE_FUNCTIONS = {
    '_build_failed_tabular_generated_output_metadata',
    '_build_active_tabular_background_handoff_content',
    '_build_tabular_background_handoff_content',
    '_build_tabular_generated_output_system_message',
    '_has_generated_tabular_csv_output',
    '_format_tabular_background_handoff_row_phrase',
    '_is_active_tabular_background_handoff',
    '_normalize_generated_analysis_artifact_metadata',
    '_tabular_background_handoff_has_preview',
}
BACKGROUND_METADATA_FUNCTIONS = {'build_background_tabular_generated_output_metadata'}
STATUS_DETAIL_FUNCTIONS = {'_build_run_status_detail'}
ARTIFACT_FUNCTIONS = {'_upload_generated_chat_artifact_for_current_user'}
SCHEDULER_FUNCTIONS = {'_query_scheduler_candidates_by_status'}
MANIFEST_FUNCTIONS = {
    '_normalize_tabular_run_task_type',
    '_input_blob_path',
    '_chunk_manifest_blob_prefix',
    '_chunk_manifest_page_blob_path',
    '_output_blob_path',
    '_output_summary_blob_path',
    '_build_chunk_manifest_contract',
    '_build_chunk_manifest_entries',
    '_write_chunk_manifest_pages',
    '_write_chunk_manifest_for_run',
}
ANALYSIS_FUNCTIONS = {
    '_safe_int',
    '_settings_int',
    '_normalize_analysis_text',
    '_normalize_analysis_findings',
    '_normalize_analysis_counts',
    '_normalize_analysis_notable_rows',
    '_source_row_bounds_from_rows',
    '_source_row_bounds_from_summaries',
    '_normalize_analysis_summary_payload',
    '_get_tabular_analysis_reduce_fan_in',
    '_build_analysis_reduce_groups',
    '_build_analysis_reduce_plan',
    '_build_analysis_summary_markdown',
}
ANALYSIS_CONSTANTS = {
    'TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD',
    'TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD',
    'TABULAR_ANALYSIS_DEFAULT_REDUCE_FAN_IN',
    'TABULAR_ANALYSIS_MAX_REDUCE_FAN_IN',
    'TABULAR_ANALYSIS_SUMMARY_MAX_CHARS',
    'TABULAR_ANALYSIS_MAX_FINDINGS',
    'TABULAR_ANALYSIS_MAX_NOTABLE_ROWS',
}
PERFORMANCE_FUNCTIONS = {
    '_safe_int',
    '_safe_float',
    '_settings_bool',
    '_settings_int',
    '_settings_float',
    '_settings_mode',
    '_normalize_tabular_generation_rollout_settings',
    '_get_tabular_generation_rollout_bucket',
    '_build_tabular_generation_rollout_assignment',
    '_get_tabular_generation_rollout_settings_for_run',
    '_sync_tabular_generation_contract_fields',
    '_get_tabular_run_lineage_schema',
    '_get_tabular_run_public_output_schema',
    '_get_tabular_run_internal_checkpoint_schema',
    '_build_generation_progress_contract_fields',
    '_extract_tabular_response_usage',
    '_resolve_tabular_batch_concurrency',
    '_normalize_tabular_run_task_type',
    '_resolve_tabular_schema_probe_rows',
    '_estimate_tabular_source_batch_count',
    '_resolve_tabular_source_batch_capacity',
    '_balance_tabular_source_batch_rows',
    '_get_tabular_source_batch_row_limit',
    '_resolve_tabular_chunk_model_selection',
    '_normalize_tabular_model_identifier',
    '_get_tabular_model_record_identifiers',
    '_read_tabular_model_token_limit',
    '_iter_configured_tabular_model_records',
    '_load_tabular_model_limit_catalog',
    '_resolve_tabular_model_token_limits',
    '_build_model_aware_source_batch_budget',
    '_is_schema_discovery_progress_window',
    '_calculate_window_throughput',
    '_parse_iso_datetime',
    '_build_tabular_generation_performance_summary',
    '_advance_run_progress_for_window',
}
GENERATION_PLAN_FUNCTIONS = {
    '_safe_int',
    '_safe_float',
    '_settings_bool',
    '_settings_mode',
    '_canonical_json_bytes',
    '_sha256_json',
    '_hash_tabular_generation_plan',
    '_describe_tabular_generation_plan_value',
    '_infer_tabular_generation_plan_value_type',
    '_build_tabular_generation_plan_input_contract',
    '_validate_tabular_generation_plan_output_fields',
    '_get_tabular_generation_plan_source',
    '_build_tabular_generation_plan',
    '_validate_tabular_generation_plan',
    '_get_tabular_generation_plan_output_schema',
    '_get_tabular_generation_plan_llm_fields',
    '_get_tabular_run_lineage_schema',
    '_get_tabular_run_public_output_schema',
    '_get_tabular_run_transformation_spec',
    '_tabular_generation_plan_blob_path',
    '_get_tabular_generation_plan_source_etag',
    '_build_tabular_output_checkpoint_metadata',
    '_validate_tabular_output_checkpoint_metadata',
    '_get_tabular_generation_plan_mode',
    '_load_tabular_generation_plan_sample_rows',
    '_build_tabular_generation_plan_prompt',
    '_generate_tabular_generation_plan',
    '_apply_active_tabular_generation_plan',
    '_recover_tabular_generation_plan',
    '_mark_tabular_generation_plan_fallback',
    '_ensure_tabular_generation_plan',
    '_record_shadow_tabular_generation_plan_comparison',
    '_dump_generated_output_json',
}
GENERATION_PLAN_CONSTANTS = {
    'TABULAR_RESPONSE_PROTOCOL_OBJECT_V1',
    'TABULAR_RESPONSE_PROTOCOL_COMPACT_ROW_ARRAY_V1',
    'TABULAR_RESPONSE_PROTOCOLS',
    'TABULAR_COMPACT_PLAN_HASH_PREFIX_LENGTH',
    'TABULAR_ROLLOUT_PLANNER_MODES',
    'TABULAR_RUN_TASK_STRUCTURED_EXPORT',
    'TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS',
    'TABULAR_RUN_TASK_COMBINED',
    'TABULAR_RUN_TASK_TYPES',
    'TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD',
    'TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD',
    'TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD',
    'TABULAR_EXPORT_INPUT_ROW_KEY_FIELD',
    'TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD',
    'TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD',
}
COMPACT_PROTOCOL_FUNCTIONS = {
    '_safe_int',
    '_settings_bool',
    '_settings_mode',
    '_canonical_json_bytes',
    '_sha256_json',
    '_hash_tabular_generation_plan',
    '_normalize_tabular_run_task_type',
    '_is_compact_row_array_protocol',
    '_select_tabular_response_protocol',
    '_clean_generated_json_code_fence',
    '_parse_generated_json_entries',
    '_parse_generated_json_object',
    '_dump_generated_output_json',
    '_describe_tabular_generation_plan_value',
    '_infer_tabular_generation_plan_value_type',
    '_build_tabular_generation_plan_input_contract',
    '_validate_tabular_generation_plan_output_fields',
    '_get_tabular_generation_plan_source',
    '_build_tabular_generation_plan',
    '_validate_tabular_generation_plan',
    '_get_tabular_generation_plan_output_schema',
    '_get_tabular_generation_plan_llm_fields',
    '_get_compact_plan_hash_prefix',
    '_build_compact_batch_row_key',
    '_build_compact_batch_key_map',
    '_build_compact_prompt_rows',
    '_validate_compact_row_field_value',
    '_parse_compact_row_array_entries',
    '_build_batch_prompt',
    '_build_compact_batch_prompt',
    '_normalize_generated_batch_entries',
}
COMPLETION_CHECKPOINT_FUNCTIONS = {
    '_safe_int',
    '_safe_float',
    '_settings_bool',
    '_settings_int',
    '_settings_float',
    '_settings_mode',
    '_normalize_tabular_run_task_type',
    '_normalize_tabular_generation_rollout_settings',
    '_get_tabular_generation_rollout_settings_for_run',
    '_select_tabular_executor_mode',
    '_select_tabular_retry_mode',
    '_is_rolling_worker_pool_enabled',
    '_is_independent_batch_retries_enabled',
    '_get_tabular_generation_plan_mode',
    '_is_rolling_executor_ready',
    '_retry_blob_path',
    '_retry_blob_prefix',
    '_output_blob_prefix',
    '_scan_output_checkpoint_batches_for_run',
    '_load_tabular_batch_retry_records_for_run',
    '_safe_tabular_batch_error_code',
    '_classify_tabular_batch_failure',
    '_is_tabular_batch_failure_retryable',
    '_tabular_retry_delay_seconds',
    '_build_tabular_batch_retry_record',
    '_persist_tabular_batch_retry_record',
    '_delete_tabular_batch_retry_record',
    '_is_tabular_batch_retry_due',
    '_tabular_batch_retry_heap_item',
    '_reset_exhausted_tabular_batch_retry_records_for_continue',
    '_is_completion_driven_checkpointing_enabled',
    '_get_checkpoint_writer_concurrency',
    '_get_tabular_generation_heartbeat_seconds',
    '_is_stale_running_run',
    '_checkpoint_generated_result_async',
    '_generate_and_checkpoint_batch_window_entries',
    '_rolling_pool_heartbeat_loop',
    '_generate_and_checkpoint_rolling_pool_entries',
    '_now_utc',
    '_now_iso',
    '_parse_iso_datetime',
    '_seconds_until',
    '_iter_exception_chain',
    '_exception_status_code',
    '_is_retryable_export_error_message',
    '_is_retryable_model_validation_error_message',
    '_is_retryable_export_error',
    '_is_retryable_model_validation_error',
}


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

    namespace = {'csv': csv, 'io': io, 're': re, 'uuid': uuid}
    namespace['log_event'] = lambda *args, **kwargs: None
    namespace['logging'] = logging
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


def _load_query_descriptor_helper():
    """Load the generalized durable query descriptor adapter in isolation."""
    module_tree = ast.parse(CHAT_ROUTE.read_text(encoding='utf-8'), filename=str(CHAT_ROUTE))
    function_node = next(
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_build_tabular_generated_output_query_descriptor'
    )
    source_reader_helpers = _load_source_reader_helpers()
    namespace = {
        '_get_tabular_generated_output_batch_budget': lambda settings: {
            'max_rows': 60,
            'max_chars': 60000,
        },
        '_safe_int': lambda value: int(value or 0),
        'validate_tabular_csv_query_expression': source_reader_helpers[
            'validate_tabular_csv_query_expression'
        ],
    }
    extracted_module = ast.Module(body=[function_node], type_ignores=[])
    exec(compile(extracted_module, str(CHAT_ROUTE), 'exec'), namespace)
    return namespace['_build_tabular_generated_output_query_descriptor']


def _load_generated_output_router(route_dependencies):
    """Load maybe_create_tabular_generated_output with focused dependency stubs."""
    module_tree = ast.parse(CHAT_ROUTE.read_text(encoding='utf-8'), filename=str(CHAT_ROUTE))
    helper_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {
            '_settings_flag_enabled',
            '_get_tabular_generated_output_task_type',
        }
    ]
    function_node = next(
        node
        for node in module_tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == 'maybe_create_tabular_generated_output'
    )
    namespace = dict(route_dependencies)
    namespace.setdefault('TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS', 'hierarchical_analysis')
    namespace.setdefault('TABULAR_RUN_TASK_COMBINED', 'combined')
    namespace.setdefault(
        '_shared_get_tabular_generated_output_task_type',
        get_tabular_generated_output_task_type,
    )
    namespace.setdefault(
        '_shared_build_tabular_legacy_post_tool_fallback_decision',
        build_tabular_legacy_post_tool_fallback_decision,
    )
    namespace.setdefault('_shared_settings_flag_enabled', settings_flag_enabled)
    namespace.setdefault('question_requests_tabular_hierarchical_analysis', lambda question: False)
    extracted_module = ast.Module(body=[*helper_nodes, function_node], type_ignores=[])
    exec(compile(extracted_module, str(CHAT_ROUTE), 'exec'), namespace)
    return namespace['maybe_create_tabular_generated_output']


def _load_direct_source_queue_helpers(route_dependencies):
    """Load direct source-backed queue helpers with focused dependency stubs."""
    module_tree = ast.parse(CHAT_ROUTE.read_text(encoding='utf-8'), filename=str(CHAT_ROUTE))
    helper_names = {
        '_build_direct_tabular_generated_output_source',
        'maybe_queue_direct_tabular_generated_output',
    }
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    if len(selected_nodes) != len(helper_names):
        raise AssertionError('Missing direct source-backed queue helper implementation')

    namespace = dict(route_dependencies)
    namespace.setdefault('TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS', 'hierarchical_analysis')
    namespace.setdefault('TABULAR_RUN_TASK_COMBINED', 'combined')
    namespace.setdefault('TABULAR_EXTENSIONS', {'csv', 'xlsx', 'xls', 'xlsm'})
    namespace.setdefault(
        '_dump_tabular_generated_output_json',
        lambda value: json.dumps(value, default=str, ensure_ascii=False, separators=(',', ':')),
    )
    namespace.setdefault('json', json)
    namespace.setdefault('math', math)
    namespace.setdefault('os', os)
    namespace.setdefault('inspect', SimpleNamespace(isawaitable=lambda value: False))
    namespace.setdefault('asyncio', SimpleNamespace(run=lambda value: value))
    namespace.setdefault('MixedSourceCancellationError', type('MixedSourceCancellationError', (Exception,), {}))
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(CHAT_ROUTE), 'exec'), namespace)
    return namespace


def _load_tabular_request_intent_helpers():
    """Load tabular artifact intent helpers with the shared file-format detector."""
    module_tree = ast.parse(CHAT_ROUTE.read_text(encoding='utf-8'), filename=str(CHAT_ROUTE))
    helper_names = {
        'get_tabular_generated_output_format',
        'question_requests_tabular_generated_output',
    }
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    if len(selected_nodes) != len(helper_names):
        raise AssertionError('Missing tabular request intent helpers')
    namespace = {
        '_shared_get_tabular_generated_output_format': get_tabular_generated_output_format,
        '_shared_question_requests_tabular_generated_output': (
            question_requests_tabular_generated_output
        ),
        'assistant_table_export_requested': assistant_table_export_requested,
        'get_requested_generated_file_format': get_requested_generated_file_format,
        'get_requested_structured_artifact_format': get_requested_structured_artifact_format,
        're': re,
    }
    exec(
        compile(ast.Module(body=selected_nodes, type_ignores=[]), str(CHAT_ROUTE), 'exec'),
        namespace,
    )
    return namespace


def _load_tabular_descriptor_builder():
    """Load the plugin's version-pinned tabular descriptor builder in isolation."""
    module_tree = ast.parse(
        TABULAR_PLUGIN_MODULE.read_text(encoding='utf-8'),
        filename=str(TABULAR_PLUGIN_MODULE),
    )
    plugin_class = next(
        node
        for node in module_tree.body
        if isinstance(node, ast.ClassDef) and node.name == 'TabularProcessingPlugin'
    )
    function_node = next(
        node
        for node in plugin_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_build_generated_export_query_descriptor_from_location'
    )
    namespace = {
        'List': list,
        'Optional': Optional,
        'validate_tabular_csv_query_expression': _load_source_reader_helpers()[
            'validate_tabular_csv_query_expression'
        ],
    }
    exec(
        compile(ast.Module(body=[function_node], type_ignores=[]), str(TABULAR_PLUGIN_MODULE), 'exec'),
        namespace,
    )
    return namespace['_build_generated_export_query_descriptor_from_location']


def _load_tabular_source_replay_helper(fake_plugin, version_checks):
    """Load durable tabular replay with a fake workbook parser and version check."""
    function_node = _get_function_node('_iter_versioned_tabular_source_rows')
    namespace = {
        'MatchConditions': SimpleNamespace(IfNotModified='if-not-modified'),
        'TABULAR_EXPORT_FINAL_SPOOL_MAX_MEMORY_BYTES': 1024 * 1024,
        'TabularProcessingPlugin': lambda: fake_plugin,
        '_get_versioned_source_blob_client': lambda descriptor: version_checks.append(descriptor) or object(),
        'iter_tabular_csv_query_rows': lambda **kwargs: (),
        'tempfile': __import__('tempfile'),
    }
    exec(
        compile(ast.Module(body=[function_node], type_ignores=[]), str(EXPORT_MODULE), 'exec'),
        namespace,
    )
    return namespace['_iter_versioned_tabular_source_rows']


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


def _build_filter_invocation(
    start_row,
    row_count,
    total_matches=3000,
    source_etag='etag-source-filter-7',
    replay_error=None,
):
    """Build one logged filter_rows page with server-only replay metadata."""
    class InvocationPayload(dict):
        pass

    rows = [
        {'transaction_id': f'BT-{row_index + 1:04d}'}
        for row_index in range(start_row, start_row + row_count)
    ]
    result_payload = InvocationPayload({
        'filename': 'bank_treasury_operations_dataset-3000.csv',
        'filter_applied': ['transaction_id contains BT-'],
        'normalize_match': bool(replay_error),
        'start_row': start_row,
        'returned_rows': row_count,
        'total_matches': total_matches,
        'has_more': start_row + row_count < total_matches,
        'next_start_row': start_row + row_count if start_row + row_count < total_matches else None,
        'data': rows,
    })
    result_payload.internal_metadata = {
        'tabular_source_authorization': {
            'source': 'workspace',
            'scope_id': None,
            'container': 'user-documents',
            'blob_path': 'user-1/nested/version-7/source.csv',
            'blob_etag': source_etag,
        },
    }
    if replay_error:
        result_payload.internal_metadata['tabular_generated_export_source_error'] = replay_error
    else:
        result_payload.internal_metadata['tabular_generated_export_source'] = {
            'version': 1,
            'kind': 'query_tabular_data',
            'source_function': 'filter_rows',
            'source': 'workspace',
            'scope_id': None,
            'container': 'user-documents',
            'blob_path': 'user-1/nested/version-7/source.csv',
            'blob_etag': source_etag,
            'filename': 'bank_treasury_operations_dataset-3000.csv',
            'query_expression': '(`transaction_id`.astype("str").str.contains("BT-", case=False, regex=False, na=False))',
            'return_columns': 'transaction_id',
            'expected_row_count': total_matches,
        }
    return SimpleNamespace(
        plugin_name='TabularProcessingPlugin',
        function_name='filter_rows',
        parameters={
            'filename': 'bank_treasury_operations_dataset-3000.csv',
            'column': 'transaction_id',
            'operator': 'contains',
            'value': 'BT-',
            'source': 'workspace',
            'return_columns': 'transaction_id',
            'start_row': str(start_row),
            'max_rows': '3000',
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
        'is_analysis_internal_lineage_field': is_analysis_internal_lineage_field,
        'project_structured_deliverable_row': project_structured_deliverable_row,
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


def _load_source_version_publication_helper(revalidated_descriptors):
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in SOURCE_VERSION_FUNCTIONS
    ]
    if len(selected_nodes) != len(SOURCE_VERSION_FUNCTIONS):
        raise AssertionError('Missing source-version publication helper')

    namespace = {
        '_get_versioned_source_blob_client': lambda descriptor: revalidated_descriptors.append(
            dict(descriptor)
        ),
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace['_revalidate_tabular_source_version_for_publication']


def _load_checkpoint_resume_helper(blobs, uploads):
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in CHECKPOINT_RESUME_FUNCTIONS
    ]
    if len(selected_nodes) != len(CHECKPOINT_RESUME_FUNCTIONS):
        raise AssertionError('Missing checkpoint resume helper')

    def output_blob_path(user_id, conversation_id, run_id, batch_number):
        del user_id, conversation_id, run_id
        return f'output/batch_{batch_number:06d}.json'

    def summary_blob_path(user_id, conversation_id, run_id, batch_number):
        del user_id, conversation_id, run_id
        return f'summary/batch_{batch_number:06d}.json'

    def upload_json_blob(path, payload, metadata=None):
        blobs[path] = payload
        uploads.append({'path': path, 'metadata': dict(metadata or {})})

    namespace = {
        'time': time,
        '_output_blob_path': output_blob_path,
        '_output_summary_blob_path': summary_blob_path,
        '_blob_exists': lambda path: path in blobs,
        '_download_json_blob': lambda path: blobs[path],
        '_upload_json_blob': upload_json_blob,
        '_validate_tabular_output_checkpoint_metadata': lambda *args, **kwargs: None,
        '_build_generated_batch_summary': lambda rows: {'row_count': len(rows)},
        '_build_tabular_output_checkpoint_metadata': lambda run, metadata: dict(metadata),
        '_load_input_batch_rows': (
            lambda run, input_batches, user_id, run_id, batch_number, batch_count:
            input_batches[batch_number - 1]
        ),
        'log_event': lambda *args, **kwargs: None,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace['_build_batch_window']


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


def _load_retry_helpers():
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = []
    found_functions = set()
    found_constants = set()

    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in RETRY_FUNCTIONS:
            selected_nodes.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if assigned_names & RETRY_CONSTANTS:
                selected_nodes.append(node)
                found_constants.update(assigned_names & RETRY_CONSTANTS)

    missing_functions = RETRY_FUNCTIONS - found_functions
    missing_constants = RETRY_CONSTANTS - found_constants
    if missing_functions or missing_constants:
        raise AssertionError(
            f'Missing retry helpers: functions={sorted(missing_functions)}, constants={sorted(missing_constants)}'
        )

    stored_run = {}

    def replace_claimed_run(run):
        stored_run.clear()
        stored_run.update(run)
        return dict(stored_run)

    namespace = {
        'datetime': datetime,
        'timedelta': timedelta,
        'timezone': timezone,
        'logging': logging,
        'TabularExportLeaseLostError': RuntimeError,
        '_now_iso': lambda: '2026-08-09T16:00:00+00:00',
        '_now_utc': lambda: datetime(2026, 8, 9, 16, 0, 0, tzinfo=timezone.utc),
        '_replace_claimed_run': replace_claimed_run,
        '_read_run': lambda user_id, run_id: dict(stored_run),
        'log_event': lambda *args, **kwargs: None,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace, stored_run


def _load_legacy_migration_helper(aggregate_batches):
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in LEGACY_MIGRATION_FUNCTIONS | MANIFEST_FUNCTIONS
    ]
    found_functions = {node.name for node in selected_nodes}
    missing_functions = (LEGACY_MIGRATION_FUNCTIONS | MANIFEST_FUNCTIONS) - found_functions
    if missing_functions:
        raise AssertionError('Missing legacy export migration helpers')

    def safe_int(value, default=0, minimum=None, maximum=None):
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            parsed_value = default
        if minimum is not None:
            parsed_value = max(minimum, parsed_value)
        if maximum is not None:
            parsed_value = min(maximum, parsed_value)
        return parsed_value

    uploaded_batches = {}
    deleted_blobs = []
    namespace = {
        're': re,
        'uuid': uuid,
        'math': math,
        'TABULAR_EXPORT_CONTRACT_VERSION': 3,
        'TABULAR_GENERATION_CONTRACT_VERSION': 1,
        'TABULAR_RESPONSE_PROTOCOL_OBJECT_V1': 'object-v1',
        'TABULAR_EXECUTOR_MODE_FIXED_WINDOW': 'fixed-window-v1',
        'TABULAR_RETRY_MODE_RUN_LEVEL': 'run-level-v1',
        'TABULAR_RUN_TASK_STRUCTURED_EXPORT': 'structured_export',
        'TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS': 'hierarchical_analysis',
        'TABULAR_RUN_TASK_COMBINED': 'combined',
        'TABULAR_RUN_TASK_TYPES': {'structured_export', 'hierarchical_analysis', 'combined'},
        'TABULAR_RUN_CHUNK_MANIFEST_VERSION': 1,
        'TABULAR_RUN_DEFAULT_CHUNK_MANIFEST_PAGE_SIZE': 250,
        'TABULAR_EXPORT_INPUT_ROW_NUMBER_FIELD': '__simplechat_source_row_number',
        'TABULAR_EXPORT_INPUT_ROW_IDENTITY_FIELD': '__simplechat_source_row_identity',
        'TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD': '__simplechat_source_row_token',
        'storage_account_personal_chat_container_name': 'personal-chat',
        '_safe_int': safe_int,
        '_download_json_blob': lambda path: aggregate_batches if path == 'legacy-input.json' else uploaded_batches[path],
        '_upload_json_blob': lambda path, payload, metadata=None: uploaded_batches.__setitem__(path, payload),
        '_delete_blob_if_exists': deleted_blobs.append,
        '_now_iso': lambda: '2026-07-21T18:00:00+00:00',
        '_raise_if_tabular_export_canceled': lambda run: run,
        '_replace_claimed_run': lambda run: dict(run),
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace['_migrate_legacy_tabular_export_run'], uploaded_batches, deleted_blobs


def _load_manifest_helpers():
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in MANIFEST_FUNCTIONS
    ]
    found_functions = {node.name for node in selected_nodes}
    missing_functions = MANIFEST_FUNCTIONS - found_functions
    if missing_functions:
        raise AssertionError(f'Missing manifest helpers: {sorted(missing_functions)}')

    uploaded_pages = {}

    def safe_int(value, default=0, minimum=None, maximum=None):
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            parsed_value = default
        if minimum is not None:
            parsed_value = max(minimum, parsed_value)
        if maximum is not None:
            parsed_value = min(maximum, parsed_value)
        return parsed_value

    namespace = {
        'math': math,
        'TABULAR_EXPORT_CONTRACT_VERSION': 3,
        'TABULAR_RUN_TASK_STRUCTURED_EXPORT': 'structured_export',
        'TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS': 'hierarchical_analysis',
        'TABULAR_RUN_TASK_COMBINED': 'combined',
        'TABULAR_RUN_TASK_TYPES': {'structured_export', 'hierarchical_analysis', 'combined'},
        'TABULAR_RUN_CHUNK_MANIFEST_VERSION': 1,
        'TABULAR_RUN_DEFAULT_CHUNK_MANIFEST_PAGE_SIZE': 250,
        'storage_account_personal_chat_container_name': 'personal-chat',
        '_safe_int': safe_int,
        '_upload_json_blob': lambda path, payload, metadata=None: uploaded_pages.__setitem__(path, payload),
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace, uploaded_pages


def _load_analysis_helpers():
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = []
    found_functions = set()
    found_constants = set()

    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ANALYSIS_FUNCTIONS:
            selected_nodes.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if assigned_names & ANALYSIS_CONSTANTS:
                selected_nodes.append(node)
                found_constants.update(assigned_names & ANALYSIS_CONSTANTS)

    missing_functions = ANALYSIS_FUNCTIONS - found_functions
    missing_constants = ANALYSIS_CONSTANTS - found_constants
    if missing_functions or missing_constants:
        raise AssertionError(
            f'Missing analysis helpers: functions={sorted(missing_functions)}, '
            f'constants={sorted(missing_constants)}'
        )

    namespace = {'math': math, 're': re}
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace


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
        'TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS': 'hierarchical_analysis',
        'TABULAR_RUN_TASK_COMBINED': 'combined',
        'has_generated_tabular_csv_output': has_generated_tabular_csv_output,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(CHAT_ROUTE), 'exec'), namespace)
    return namespace


def _load_background_generated_output_metadata_helper():
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in BACKGROUND_METADATA_FUNCTIONS
    ]
    if len(selected_nodes) != len(BACKGROUND_METADATA_FUNCTIONS):
        raise AssertionError('Missing background generated-output metadata helper')

    namespace = {
        '_build_run_public_status': lambda run: dict(run.get('_public_status') or {}),
        '_normalize_tabular_run_task_type': lambda task_type: task_type or 'structured_export',
        '_safe_int': lambda value: int(value or 0),
        'TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS': 'hierarchical_analysis',
        'TABULAR_RUN_TASK_COMBINED': 'combined',
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace['build_background_tabular_generated_output_metadata']


def _load_run_status_detail_helper():
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in STATUS_DETAIL_FUNCTIONS
    ]
    if len(selected_nodes) != len(STATUS_DETAIL_FUNCTIONS):
        raise AssertionError('Missing run status detail helper')

    namespace = {
        'TABULAR_EXPORT_STATUS_COMPLETED': 'completed',
        'TABULAR_EXPORT_STATUS_CANCELED': 'canceled',
        'TABULAR_EXPORT_STATUS_RUNNING': 'running',
        'TABULAR_EXPORT_STATUS_FAILED': 'failed',
        'TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS': 'hierarchical_analysis',
        'TABULAR_RUN_TASK_COMBINED': 'combined',
        '_normalize_tabular_run_task_type': lambda task_type: task_type or 'structured_export',
        '_is_stale_running_run': lambda run, settings: bool(run.get('_test_is_stale')),
        '_is_waiting_for_retry': lambda run: bool(run.get('_test_waiting_for_retry')),
        '_is_due_queued_retry_run': lambda run: bool(run.get('_test_retry_due')),
        '_is_stale_queued_run': lambda run, settings: bool(run.get('_test_stale_queued')),
        '_seconds_until': lambda value: 15 if value else None,
        '_safe_int': lambda value: int(value or 0),
        '_has_exhausted_independent_batch_retries': lambda run: bool(run.get('_test_exhausted')),
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace['_build_run_status_detail']


def _assert_concise_background_handoff_contract(text, expected_row_count, expected_output_label):
    normalized_text = str(text or '')
    normalized_lower = normalized_text.lower()
    assert f"{expected_row_count:,}" in normalized_text
    assert expected_output_label.lower() in normalized_lower
    assert 'background' in normalized_lower or 'appear in this chat when ready' in normalized_lower
    prohibited_markers = (
        'can only',
        'could not be completed',
        'available tool results',
        'schema preview',
        'if you want, i can',
        'run id',
        'run_id',
        'blob',
        'batch',
        'checkpoint',
    )
    for marker in prohibited_markers:
        assert marker not in normalized_lower


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


def _load_performance_helpers(progress_updates=None):
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = []
    found_functions = set()
    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in PERFORMANCE_FUNCTIONS:
            selected_nodes.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if any(
                name.startswith('TABULAR_EXPORT_')
                or name.startswith('TABULAR_RUN_TASK_')
                or name.startswith('TABULAR_GENERATION_')
                or name.startswith('TABULAR_RESPONSE_')
                or name.startswith('TABULAR_EXECUTOR_')
                or name.startswith('TABULAR_RETRY_')
                or name.startswith('TABULAR_ROLLOUT_')
                for name in assigned_names
            ):
                selected_nodes.append(node)

    missing_functions = PERFORMANCE_FUNCTIONS - found_functions
    if missing_functions:
        raise AssertionError(f'Missing performance helper functions: {sorted(missing_functions)}')

    namespace = {
        '__file__': str(EXPORT_MODULE),
        'datetime': datetime,
        'hashlib': hashlib,
        'json': json,
        'math': math,
        'os': os,
        're': re,
        'timezone': timezone,
        'is_analysis_internal_lineage_field': is_analysis_internal_lineage_field,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)

    progress_updates = progress_updates if progress_updates is not None else []

    def update_progress(
        run,
        completed_batches,
        processed_rows,
        window_rows,
        window_elapsed_seconds,
        window_batch_count,
        mismatch_count=0,
    ):
        progress_updates.append({
            'completed_batches': completed_batches,
            'processed_rows': processed_rows,
            'window_rows': window_rows,
            'window_elapsed_seconds': window_elapsed_seconds,
            'window_batch_count': window_batch_count,
            'mismatch_count': mismatch_count,
        })
        return run

    namespace['_update_run_progress'] = update_progress
    return namespace


def _load_generation_plan_helpers():
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = []
    found_functions = set()
    for node in module_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in GENERATION_PLAN_FUNCTIONS:
            selected_nodes.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if assigned_names & GENERATION_PLAN_CONSTANTS or any(
                name.startswith('TABULAR_GENERATION_PLAN_')
                for name in assigned_names
            ):
                selected_nodes.append(node)

    missing_functions = GENERATION_PLAN_FUNCTIONS - found_functions
    if missing_functions:
        raise AssertionError(f'Missing generation plan helpers: {sorted(missing_functions)}')

    class PlannerError(RuntimeError):
        def __init__(self, reason):
            super().__init__('planner failed')
            self.reason = reason

    class ChatHistory:
        def add_system_message(self, message):
            del message

        def add_user_message(self, message):
            del message

    class ExecutionSettings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    state = {
        'blobs': {},
        'metadata': {},
        'uploads': [],
        'replace_count': 0,
    }

    def upload_json_blob(path, payload, metadata=None, overwrite=True):
        state['uploads'].append({
            'path': path,
            'payload': payload,
            'metadata': dict(metadata or {}),
            'overwrite': overwrite,
        })
        if not overwrite and path in state['blobs']:
            raise FileExistsError(path)
        state['blobs'][path] = payload
        state['metadata'][path] = dict(metadata or {})

    def replace_claimed_run(run):
        state['replace_count'] += 1
        return dict(run)

    namespace = {
        'asyncio': asyncio,
        'hashlib': hashlib,
        'json': json,
        'logging': logging,
        're': re,
        'time': time,
        'ResourceExistsError': FileExistsError,
        'TabularGenerationPlanError': PlannerError,
        'SKChatHistory': ChatHistory,
        'AzureChatPromptExecutionSettings': ExecutionSettings,
        '_now_iso': lambda: '2026-08-10T12:00:00+00:00',
        '_parse_generated_json_object': lambda content: json.loads(content),
        '_extract_tabular_response_usage': lambda result: {
            'input_token_count': 10,
            'output_token_count': 5,
            'total_token_count': 15,
        },
        '_download_json_blob': lambda path: state['blobs'][path],
        '_blob_exists': lambda path: path in state['blobs'],
        '_get_blob_metadata': lambda path: state['metadata'].get(path, {}),
        '_upload_json_blob': upload_json_blob,
        '_replace_claimed_run': replace_claimed_run,
        '_load_input_batch_rows': (
            lambda run, input_batches, user_id, run_id, batch_number, batch_count:
            (input_batches or run['_test_batches'])[batch_number - 1]
        ),
        '_normalize_tabular_run_task_type': lambda value: value or 'structured_export',
        'is_analysis_internal_lineage_field': is_analysis_internal_lineage_field,
        'normalize_tabular_transformation_spec': normalize_tabular_transformation_spec,
        '_resolve_tabular_generation_planner_model': lambda run, settings: {
            'endpoint_id': 'endpoint-1',
            'model_id': 'gpt-plan',
            'deployment': 'gpt-plan',
        },
        'log_event': lambda *args, **kwargs: None,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace, PlannerError, state


def _load_compact_protocol_helpers():
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = []
    found_functions = set()
    for node in module_tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in COMPACT_PROTOCOL_FUNCTIONS:
            selected_nodes.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if any(
                name.startswith('TABULAR_EXPORT_')
                or name.startswith('TABULAR_GENERATION_')
                or name.startswith('TABULAR_RESPONSE_')
                or name.startswith('TABULAR_RUN_TASK_')
                or name.startswith('TABULAR_ROLLOUT_')
                or name.startswith('TABULAR_COMPACT_')
                for name in assigned_names
            ):
                selected_nodes.append(node)

    missing_functions = COMPACT_PROTOCOL_FUNCTIONS - found_functions
    if missing_functions:
        raise AssertionError(f'Missing compact protocol helpers: {sorted(missing_functions)}')

    namespace = {
        'hashlib': hashlib,
        'json': json,
        're': re,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace


def _load_completion_checkpoint_helpers():
    module_tree = ast.parse(EXPORT_MODULE.read_text(encoding='utf-8'), filename=str(EXPORT_MODULE))
    selected_nodes = []
    found_functions = set()
    for node in module_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in COMPLETION_CHECKPOINT_FUNCTIONS:
            selected_nodes.append(node)
            found_functions.add(node.name)
        elif isinstance(node, ast.Assign):
            assigned_names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if any(name.startswith('TABULAR_') for name in assigned_names):
                selected_nodes.append(node)

    missing_functions = COMPLETION_CHECKPOINT_FUNCTIONS - found_functions
    if missing_functions:
        raise AssertionError(f'Missing completion checkpoint helpers: {sorted(missing_functions)}')

    namespace = {
        'asyncio': asyncio,
        'Counter': Counter,
        'deque': __import__('collections').deque,
        'datetime': datetime,
        'hashlib': hashlib,
        'heapq': heapq,
        'logging': logging,
        'math': math,
        're': re,
        'timedelta': timedelta,
        'timezone': timezone,
        'storage_account_personal_chat_container_name': 'personal-chat',
        'TabularExportLeaseLostError': RuntimeError,
        'TABULAR_RUN_TASK_STRUCTURED_EXPORT': 'structured_export',
        'TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS': 'hierarchical_analysis',
        'TABULAR_RUN_TASK_COMBINED': 'combined',
        'TABULAR_RUN_TASK_TYPES': {'structured_export', 'hierarchical_analysis', 'combined'},
        'log_event': lambda *args, **kwargs: None,
    }
    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)
    return namespace


def _build_phase_three_test_run(plan_mode='shadow', plan_status='pending'):
    return {
        'id': 'run-phase-3',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'user_question': 'For every row, return answer and risk.',
        'output_format': 'csv',
        'response_protocol_version': 'object-v1',
        'task_type': 'structured_export',
        'gpt_model': 'gpt-plan',
        'model_context': {'endpoint_id': 'endpoint-1', 'model_id': 'gpt-plan'},
        'source_descriptor': {
            'blob_path': 'user-1/source.csv',
            'blob_etag': '"etag-1"',
        },
        'row_count': 2,
        'batch_count': 2,
        'batch_budget': {
            'max_rows': 50,
            'max_chars': 60000,
            'input_token_budget': 60000,
            'output_token_budget': 30000,
        },
        'generation_rollout_settings': {
            'enable_tabular_generation_plan': True,
            'tabular_generation_plan_mode': plan_mode,
        },
        'plan_mode': plan_mode,
        'plan_status': plan_status,
        'plan_blob_path': None,
        'plan_hash': None,
        'output_schema': None,
        'passthrough_input_rows': False,
        '_test_batches': [
            [{
                'Case ID': 'SC-1',
                'Comment': 'Sensitive first comment',
                '__simplechat_source_row_number': 1,
                '__simplechat_source_row_identity': 'SC-1',
                '__simplechat_source_row_token': 'token-1',
            }],
            [{
                'Case ID': 'SC-2',
                'Comment': 'Sensitive second comment',
                '__simplechat_source_row_number': 2,
                '__simplechat_source_row_identity': 'SC-2',
                '__simplechat_source_row_token': 'token-2',
            }],
        ],
    }


def _build_phase_three_plan(helpers, run):
    input_contract = helpers['_build_tabular_generation_plan_input_contract'](
        run['_test_batches'][0] + run['_test_batches'][1]
    )
    plan = helpers['_build_tabular_generation_plan'](
        run,
        {
            'output_fields': [
                {
                    'name': 'answer',
                    'description': 'Answer requested for the source row.',
                    'type': 'string',
                    'nullable': False,
                    'source': 'llm',
                },
                {
                    'name': 'risk',
                    'description': 'Risk level requested for the source row.',
                    'type': 'string',
                    'nullable': True,
                    'source': 'llm',
                },
            ],
            'output_verbosity': 'concise',
        },
        input_contract,
        {
            'endpoint_id': 'endpoint-1',
            'model_id': 'gpt-plan',
            'deployment': 'gpt-plan',
        },
        created_at='2026-08-10T12:00:00+00:00',
    )
    return plan, input_contract


def _build_phase_four_plan(helpers, run):
    input_contract = helpers['_build_tabular_generation_plan_input_contract'](
        run['_test_batches'][0] + run['_test_batches'][1]
    )
    plan = helpers['_build_tabular_generation_plan'](
        run,
        {
            'output_fields': [
                {
                    'name': 'answer',
                    'description': 'Answer requested for the source row.',
                    'type': 'string',
                    'nullable': False,
                    'source': 'llm',
                },
                {
                    'name': 'risk',
                    'description': 'Risk level requested for the source row.',
                    'type': 'string',
                    'nullable': True,
                    'source': 'llm',
                },
                {
                    'name': 'score',
                    'description': 'Numeric score requested for the source row.',
                    'type': 'number',
                    'nullable': False,
                    'source': 'llm',
                },
                {
                    'name': 'flagged',
                    'description': 'Boolean flag requested for the source row.',
                    'type': 'boolean',
                    'nullable': False,
                    'source': 'llm',
                },
                {
                    'name': 'evidence',
                    'description': 'Compact evidence object for the source row.',
                    'type': 'object',
                    'nullable': False,
                    'source': 'llm',
                },
                {
                    'name': 'tags',
                    'description': 'Array of tags requested for the source row.',
                    'type': 'array',
                    'nullable': False,
                    'source': 'llm',
                },
            ],
            'output_verbosity': 'concise',
        },
        input_contract,
        {
            'endpoint_id': 'endpoint-1',
            'model_id': 'gpt-plan',
            'deployment': 'gpt-plan',
        },
        created_at='2026-08-10T12:00:00+00:00',
    )
    return plan, input_contract


class FakeTabularModelHarness:
    """Chat-service compatible fake model that releases calls in a caller-chosen order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.completed_batches = []
        self._release_events = {}

    async def get_chat_message_contents(self, chat_history, execution_settings):
        del chat_history, execution_settings
        call_index = len(self.calls)
        response = dict(self.responses[call_index])
        batch_number = response.get('batch_number')
        release_event = asyncio.Event()
        self.calls.append(batch_number)
        self._release_events[batch_number] = release_event
        await release_event.wait()
        if response.get('exception'):
            raise response['exception']
        self.completed_batches.append(batch_number)
        usage = response.get('usage') or {}
        return [SimpleNamespace(
            content=response.get('content', '[]'),
            metadata={'usage': usage},
        )]

    def release_batch(self, batch_number):
        self._release_events[batch_number].set()


class FakeTabularStorageHarness:
    """In-memory JSON blob harness with injectable upload and download failures."""

    def __init__(self):
        self.blobs = {}
        self.metadata = {}
        self.upload_failures = set()
        self.download_failures = set()

    def upload_json_blob(self, path, payload, metadata=None, overwrite=True):
        if path in self.upload_failures:
            raise RuntimeError(f'Injected upload failure for {path}')
        if not overwrite and path in self.blobs:
            raise FileExistsError(path)
        self.blobs[path] = payload
        self.metadata[path] = dict(metadata or {})

    def download_json_blob(self, path):
        if path in self.download_failures:
            raise RuntimeError(f'Injected download failure for {path}')
        return self.blobs[path]

    def blob_exists(self, path):
        return path in self.blobs


def test_model_aware_batch_budget_uses_safe_token_limits():
    """Batch planning uses output limits and caps very large input contexts."""
    helpers = _load_performance_helpers()
    build_budget = helpers['_build_model_aware_source_batch_budget']

    fallback_budget = build_budget(
        'unlisted-model',
        {},
        model_context={'model_id': 'unlisted-model'},
    )
    assert fallback_budget['limit_source'] == 'fallback'
    assert fallback_budget['max_chars'] == 104856
    assert fallback_budget['max_rows'] == 88

    catalog_records = [{
        'id': 'large-context-model',
        'tokenLimits': {
            'inputTokenLimit': 1000000,
            'outputTokenLimit': 200000,
        },
    }]
    structured_budget = build_budget(
        'large-context-model',
        {},
        model_context={'model_id': 'large-context-model'},
        catalog_records=catalog_records,
    )
    assert structured_budget['limit_source'] == 'catalog'
    assert structured_budget['context_token_limit'] == 1000000
    assert structured_budget['output_token_limit'] == 200000
    assert structured_budget['input_token_budget'] == 175904
    assert structured_budget['output_token_budget'] == 120000
    assert structured_budget['max_chars'] == 320000
    assert structured_budget['max_rows'] == 267

    analysis_budget = build_budget(
        'large-context-model',
        {},
        model_context={'model_id': 'large-context-model'},
        task_type='hierarchical_analysis',
        catalog_records=catalog_records,
    )
    assert analysis_budget['max_chars'] == 703616
    assert analysis_budget['max_rows'] == 500

    custom_deployment_budget = build_budget(
        'prod-west-chat',
        {
            'gpt_model': {
                'selected': [{
                    'deploymentName': 'prod-west-chat',
                    'modelName': 'large-context-model',
                }],
            },
        },
        catalog_records=catalog_records,
    )
    assert custom_deployment_budget['limit_source'] == 'catalog'
    assert custom_deployment_budget['context_token_limit'] == 1000000
    assert custom_deployment_budget['output_token_limit'] == 200000


def test_dynamic_concurrency_and_parallel_window_eta():
    """Large runs use 16 calls and ETA measures rows per parallel wall-clock window."""
    progress_updates = []
    helpers = _load_performance_helpers(progress_updates)
    resolve_concurrency = helpers['_resolve_tabular_batch_concurrency']
    assert resolve_concurrency({}, 1) == 1
    assert resolve_concurrency({}, 10) == 4
    assert resolve_concurrency({}, 100) == 16
    assert resolve_concurrency({}, 128) == 64
    assert resolve_concurrency({}, 256) == 128
    assert resolve_concurrency({'tabular_generated_output_batch_concurrency': 96}, 1000) == 96
    is_schema_window = helpers['_is_schema_discovery_progress_window']
    assert is_schema_window({'batch_count': 909, 'batch_concurrency': 128}, 1, 1) is True
    assert is_schema_window({'batch_count': 909, 'batch_concurrency': 128}, 129, 128) is False
    assert is_schema_window({'batch_count': 1, 'batch_concurrency': 1}, 1, 1) is False

    throughput = helpers['_calculate_window_throughput'](
        {'row_count': 30000},
        processed_rows=528,
        window_rows=528,
        window_elapsed_seconds=155,
        completed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )
    assert math.isclose(throughput['rows_per_minute'], 204.39, abs_tol=0.01)
    assert throughput['estimated_total_seconds'] == 8806.8
    assert throughput['estimated_remaining_seconds'] == 8651.8

    run = {'retry_count': 0}
    updated_run, completed_batches, processed_rows = helpers['_advance_run_progress_for_window'](
        run,
        {
            1: {'batch_row_count': 33, 'elapsed_seconds': 150, 'mismatch_count': 0},
            2: {'batch_row_count': 33, 'elapsed_seconds': 149, 'mismatch_count': 2},
            3: {
                'batch_row_count': 33,
                'elapsed_seconds': 0.01,
                'mismatch_count': 0,
                'from_checkpoint': True,
            },
        },
        completed_batches=0,
        processed_rows=0,
        window_start=1,
        window_end=3,
    )
    assert updated_run['retry_count'] == 1
    assert completed_batches == 3
    assert processed_rows == 99
    assert progress_updates == [{
        'completed_batches': 3,
        'processed_rows': 99,
        'window_rows': 99,
        'window_elapsed_seconds': 150.0,
        'window_batch_count': 3,
        'mismatch_count': 2,
    }]


def test_phase_one_generation_contract_fields_are_additive_and_compact():
    """Phase 1 mirrors legacy progress fields without per-batch Cosmos arrays."""
    helpers = _load_performance_helpers()
    sync_fields = helpers['_sync_tabular_generation_contract_fields']
    progress_fields = helpers['_build_generation_progress_contract_fields']

    old_run = {
        'id': 'old-run',
        'batch_count': 909,
        'completed_batches': 3,
        'processed_rows': 99,
        'started_at': '2026-08-09T00:00:00+00:00',
    }
    synced_run = sync_fields(old_run)

    assert synced_run['generation_contract_version'] == 1
    assert synced_run['response_protocol_version'] == 'object-v1'
    assert synced_run['executor_mode'] == 'fixed-window-v1'
    assert synced_run['planned_batch_count'] == 909
    assert synced_run['completed_batch_count'] == 3
    assert synced_run['highest_contiguous_batch'] == 3
    assert synced_run['checkpointed_row_count'] == 99
    assert synced_run['plan_blob_path'] is None
    assert synced_run['plan_hash'] is None
    assert 'completed_batch_list' not in synced_run

    fields = progress_fields({'batch_count': 909}, completed_batches=7, processed_rows=231)
    assert fields == {
        'planned_batch_count': 909,
        'completed_batch_count': 7,
        'highest_contiguous_batch': 7,
        'active_batch_count': 0,
        'pending_batch_count': 0,
        'checkpointing_batch_count': 0,
        'retry_wait_batch_count': 0,
        'exhausted_batch_count': 0,
        'checkpointed_row_count': 231,
    }
    serialized_run_document = json.dumps(synced_run, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    assert len(serialized_run_document) < 2048


def test_phase_three_rollout_activates_shadow_only_and_stays_backend_only():
    """Phase 3 defaults to output-neutral shadow planning and remains backend-only."""
    helpers = _load_performance_helpers()
    normalize_rollout = helpers['_normalize_tabular_generation_rollout_settings']

    defaults = normalize_rollout({})
    assert defaults == {
        'tabular_generation_rollout_percentage': 100,
        'tabular_background_handoff_mode': 'legacy',
        'tabular_generation_plan_mode': 'shadow',
        'enable_tabular_generation_plan': True,
        'enable_tabular_compact_response_protocol': False,
        'enable_tabular_completion_driven_checkpointing': True,
        'enable_tabular_rolling_worker_pool': False,
        'enable_tabular_independent_batch_retries': False,
        'enable_tabular_generation_balanced_batches': True,
        'tabular_generation_checkpoint_writer_concurrency': 1,
        'tabular_generation_heartbeat_seconds': 30,
        'tabular_generation_stale_seconds': 120,
        'tabular_generation_systemic_failure_threshold': 0.5,
    }
    overridden = normalize_rollout({
        'tabular_background_handoff_mode': 'server',
        'tabular_generation_plan_mode': 'shadow',
        'enable_tabular_generation_plan': 'true',
        'enable_tabular_compact_response_protocol': 'yes',
        'enable_tabular_completion_driven_checkpointing': '1',
        'enable_tabular_rolling_worker_pool': 'on',
        'enable_tabular_independent_batch_retries': True,
        'enable_tabular_generation_balanced_batches': True,
        'tabular_generation_checkpoint_writer_concurrency': 99,
        'tabular_generation_heartbeat_seconds': 1,
        'tabular_generation_systemic_failure_threshold': 2,
    })
    assert overridden['tabular_background_handoff_mode'] == 'server'
    assert overridden['tabular_generation_plan_mode'] == 'shadow'
    assert overridden['enable_tabular_generation_plan'] is True
    assert overridden['enable_tabular_compact_response_protocol'] is True
    assert overridden['enable_tabular_completion_driven_checkpointing'] is True
    assert overridden['enable_tabular_rolling_worker_pool'] is True
    assert overridden['enable_tabular_independent_batch_retries'] is True
    assert overridden['enable_tabular_generation_balanced_batches'] is True
    assert overridden['tabular_generation_checkpoint_writer_concurrency'] == 16
    assert overridden['tabular_generation_heartbeat_seconds'] == 5
    assert overridden['tabular_generation_systemic_failure_threshold'] == 1.0

    settings_source = SETTINGS_MODULE.read_text(encoding='utf-8')
    for setting_key in defaults:
        assert f"'{setting_key}'" in settings_source
    assert 'TABULAR_GENERATION_BACKEND_SETTING_KEYS' in settings_source
    assert 'if k in TABULAR_GENERATION_BACKEND_SETTING_KEYS' in settings_source
    assert "'enable_tabular_generation_balanced_batches'" in settings_source


def test_shadow_generation_plan_is_deferred_off_the_production_critical_path():
    """Shadow telemetry must not add a serial model call before batch generation."""
    helpers, _, _ = _load_generation_plan_helpers()
    run = _build_phase_three_test_run(plan_mode='shadow', plan_status='pending')
    planner_calls = []

    async def unexpected_planner_call(*args, **kwargs):
        planner_calls.append((args, kwargs))
        raise AssertionError('Shadow planning must not block production generation')

    helpers['_generate_tabular_generation_plan'] = unexpected_planner_call
    deferred_run = helpers['_ensure_tabular_generation_plan'](
        run,
        object(),
        run['_test_batches'],
        {},
        60,
    )

    assert planner_calls == []
    assert deferred_run['plan_mode'] == 'shadow'
    assert deferred_run['plan_status'] == 'deferred'
    assert deferred_run['plan_failure_reason'] == 'deferred_off_critical_path'
    assert deferred_run['planner_attempt_count'] == 0
    assert deferred_run['planner_latency_seconds'] == 0
    assert deferred_run['output_schema'] is None
    assert deferred_run['last_message'] == 'Generating the initial schema checkpoint'


def test_schema_probe_starts_small_then_uses_normal_batch_budget():
    """Unplanned source-backed runs checkpoint a small first batch before concurrency opens."""
    helpers = _load_performance_helpers()
    resolve_probe = helpers['_resolve_tabular_schema_probe_rows']
    estimate_batches = helpers['_estimate_tabular_source_batch_count']
    resolve_capacity = helpers['_resolve_tabular_source_batch_capacity']
    balance_batches = helpers['_balance_tabular_source_batch_rows']
    batch_row_limit = helpers['_get_tabular_source_batch_row_limit']

    probe_rows = resolve_probe({}, 'shadow', 'structured_export', 300, 58)
    descriptor = {
        'batch_max_rows': 58,
        'schema_probe_rows': probe_rows,
    }

    assert probe_rows == 5
    assert estimate_batches(300, 58, probe_rows) == 7
    assert batch_row_limit(descriptor, 0) == 5
    assert batch_row_limit(descriptor, 1) == 58
    assert resolve_probe({}, 'active', 'structured_export', 300, 58) == 0
    assert estimate_batches(300, 58, 0) == 6
    assert resolve_probe({}, 'shadow', 'hierarchical_analysis', 300, 58) == 0
    assert balance_batches({}, 300, 58, probe_rows) == 37
    assert estimate_batches(300, 37, probe_rows) == 9
    assert balance_batches({}, 200, 58, probe_rows) == 58
    assert balance_batches(
        {'enable_tabular_generation_balanced_batches': False},
        300,
        58,
        probe_rows,
    ) == 58
    assert resolve_capacity(88, 104856, 1800) == 58
    character_aware_rows = resolve_capacity(88, 104856, 1800)
    assert balance_batches({}, 300, character_aware_rows, probe_rows) == 37


def test_phase_eight_rollout_assignment_is_stable_and_control_runs_stay_legacy():
    """Percentage rollout is deterministic per run and frozen for every resume."""
    helpers = _load_performance_helpers()
    build_assignment = helpers['_build_tabular_generation_rollout_assignment']
    get_rollout_for_run = helpers['_get_tabular_generation_rollout_settings_for_run']
    enabled_settings = {
        'tabular_generation_rollout_percentage': 25,
        'tabular_background_handoff_mode': 'server',
        'enable_tabular_generation_plan': True,
        'tabular_generation_plan_mode': 'active',
        'enable_tabular_compact_response_protocol': True,
        'enable_tabular_completion_driven_checkpointing': True,
        'enable_tabular_rolling_worker_pool': True,
        'enable_tabular_independent_batch_retries': True,
    }
    assignment = build_assignment(
        enabled_settings,
        'user-1',
        'conversation-1',
        'run-phase-8',
    )
    repeated_assignment = build_assignment(
        enabled_settings,
        'user-1',
        'conversation-1',
        'run-phase-8',
    )

    assert repeated_assignment == assignment
    assert 1 <= assignment['tabular_generation_rollout_bucket'] <= 100
    expected_cohort = (
        'canary'
        if assignment['tabular_generation_rollout_bucket'] <= 25
        else 'control'
    )
    assert assignment['tabular_generation_rollout_cohort'] == expected_cohort
    assert assignment['tabular_generation_rollout_hash_version'] == 1

    if expected_cohort == 'canary':
        assert assignment['tabular_generation_plan_mode'] == 'active'
        assert assignment['enable_tabular_rolling_worker_pool'] is True
    else:
        assert assignment['tabular_background_handoff_mode'] == 'legacy'
        assert assignment['tabular_generation_plan_mode'] == 'off'
        assert assignment['enable_tabular_generation_plan'] is False
        assert assignment['enable_tabular_compact_response_protocol'] is False
        assert assignment['enable_tabular_completion_driven_checkpointing'] is False
        assert assignment['enable_tabular_rolling_worker_pool'] is False
        assert assignment['enable_tabular_independent_batch_retries'] is False
        assert assignment['enable_tabular_generation_balanced_batches'] is False

    resumed_settings = get_rollout_for_run(
        {'generation_rollout_settings': assignment},
        {
            'tabular_generation_rollout_percentage': 100,
            'tabular_generation_plan_mode': 'active',
            'enable_tabular_rolling_worker_pool': not assignment['enable_tabular_rolling_worker_pool'],
        },
    )
    assert resumed_settings['tabular_generation_plan_mode'] == assignment['tabular_generation_plan_mode']
    assert resumed_settings['enable_tabular_rolling_worker_pool'] == assignment['enable_tabular_rolling_worker_pool']

    legacy_settings = get_rollout_for_run(
        {'id': 'pre-snapshot-run'},
        enabled_settings,
    )
    assert legacy_settings['tabular_generation_rollout_percentage'] == 0
    assert legacy_settings['tabular_generation_plan_mode'] == 'off'
    assert legacy_settings['enable_tabular_generation_plan'] is False
    assert legacy_settings['enable_tabular_rolling_worker_pool'] is False
    assert legacy_settings['tabular_generation_stale_seconds'] == 900

    control_assignment = build_assignment(
        {**enabled_settings, 'tabular_generation_rollout_percentage': 0},
        'user-1',
        'conversation-1',
        'run-phase-8-control',
    )
    canary_assignment = build_assignment(
        {**enabled_settings, 'tabular_generation_rollout_percentage': 100},
        'user-1',
        'conversation-1',
        'run-phase-8-canary',
    )
    assert control_assignment['tabular_generation_rollout_cohort'] == 'control'
    assert control_assignment['enable_tabular_generation_plan'] is False
    assert canary_assignment['tabular_generation_rollout_cohort'] == 'canary'
    assert canary_assignment['enable_tabular_rolling_worker_pool'] is True


def test_phase_eight_retry_and_stale_reclaim_modes_are_snapshotted():
    """New runs reclaim stale workers promptly while legacy snapshots retain their timeout."""
    helpers = _load_completion_checkpoint_helpers()
    now = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    helpers['_now_utc'] = lambda: now
    rolling_mode = helpers['TABULAR_EXECUTOR_MODE_ROLLING_POOL']
    fixed_mode = helpers['TABULAR_EXECUTOR_MODE_FIXED_WINDOW']

    assert helpers['_select_tabular_retry_mode'](
        {'enable_tabular_independent_batch_retries': True},
        rolling_mode,
    ) == 'independent-batch-v1'
    assert helpers['_select_tabular_retry_mode'](
        {'enable_tabular_independent_batch_retries': True},
        fixed_mode,
    ) == 'run-level-v1'

    rolling_run = {
        'executor_mode': rolling_mode,
        'last_heartbeat_at': (now - timedelta(seconds=121)).isoformat(),
        'generation_rollout_settings': {
            'tabular_generation_stale_seconds': 120,
        },
    }
    fixed_window_run = {
        'executor_mode': fixed_mode,
        'last_heartbeat_at': (now - timedelta(seconds=121)).isoformat(),
        'generation_rollout_settings': {
            'tabular_generation_stale_seconds': 120,
        },
    }
    stale_fixed_window_run = {
        **fixed_window_run,
        'last_heartbeat_at': (now - timedelta(seconds=361)).isoformat(),
    }
    legacy_run = {
        'executor_mode': fixed_mode,
        'last_heartbeat_at': (now - timedelta(seconds=121)).isoformat(),
        'generation_rollout_settings': {
            'enable_tabular_generation_plan': True,
        },
    }
    assert helpers['_is_stale_running_run'](rolling_run, {}) is True
    assert helpers['_is_stale_running_run'](fixed_window_run, {}) is False
    assert helpers['_is_stale_running_run'](stale_fixed_window_run, {}) is True
    assert helpers['_is_stale_running_run'](legacy_run, {}) is False


def test_retry_status_detail_exposes_safe_retry_reason():
    """Public status explains retry categories without exposing raw provider errors."""
    build_status_detail = _load_run_status_detail_helper()

    scheduled_detail = build_status_detail(
        {
            'status': 'queued',
            'last_retry_category': 'model_validation',
            'next_attempt_at': '2026-08-10T12:01:00+00:00',
            '_test_waiting_for_retry': True,
        },
        {},
        retryable_failure=False,
        can_resume=True,
    )
    assert scheduled_detail['status_label'] == 'Retry Scheduled'
    assert 'model output validation failed' in scheduled_detail['status_detail']
    assert 'raw' not in scheduled_detail['status_detail'].lower()

    failed_detail = build_status_detail(
        {
            'status': 'failed',
            'last_retry_category': 'transient',
        },
        {},
        retryable_failure=True,
        can_resume=True,
    )
    assert 'transient provider or connection interruption' in failed_detail['status_detail']


def test_startup_status_detail_reports_active_phase_before_first_checkpoint():
    """Zero-row startup reports source, planner, and initial checkpoint activity truthfully."""
    build_status_detail = _load_run_status_detail_helper()
    base_run = {
        'status': 'running',
        'task_type': 'structured_export',
        'completed_batches': 0,
    }

    preparing_source = build_status_detail(
        {
            **base_run,
            'source_descriptor': {'kind': 'query_tabular_data'},
            'source_staging_complete': False,
        },
        {},
        retryable_failure=False,
        can_resume=False,
    )
    planning_output = build_status_detail(
        {
            **base_run,
            'source_staging_complete': True,
            'plan_status': 'planning',
        },
        {},
        retryable_failure=False,
        can_resume=False,
    )
    starting_generation = build_status_detail(
        {
            **base_run,
            'source_staging_complete': True,
            'plan_status': 'deferred',
        },
        {},
        retryable_failure=False,
        can_resume=False,
    )

    assert preparing_source['status_label'] == 'Preparing Source'
    assert planning_output['status_label'] == 'Planning Output'
    assert starting_generation['status_label'] == 'Starting'
    assert 'concurrent batches will follow' in starting_generation['status_detail']


def test_phase_eight_publication_revalidates_source_version():
    """Every source-backed artifact rechecks its queued ETag immediately before upload."""
    revalidated_descriptors = []
    revalidate_source = _load_source_version_publication_helper(revalidated_descriptors)
    source_descriptor = {
        'source': 'chat',
        'container': 'personal-chat',
        'blob_path': 'user-1/conversation-1/source.csv',
        'blob_etag': 'etag-queued',
    }

    revalidate_source({'source_descriptor': source_descriptor})
    revalidate_source({'source_authorization': source_descriptor})

    assert revalidated_descriptors == [source_descriptor, source_descriptor]
    structured_publish_source = ast.unparse(_get_function_node('_publish_structured_export_artifact'))
    analysis_publish_source = ast.unparse(_get_function_node('_publish_analysis_artifact'))
    for publish_source in (structured_publish_source, analysis_publish_source):
        assert publish_source.index('_revalidate_tabular_source_version_for_publication') < publish_source.index(
            'upload_generated_analysis_artifact_stream_for_user'
        )


def test_phase_eight_committed_output_survives_summary_and_progress_crash():
    """Resume reuses an authoritative output Blob and regenerates only its derived summary."""
    committed_output_path = 'output/batch_000001.json'
    summary_path = 'summary/batch_000001.json'
    blobs = {
        committed_output_path: [
            {'source_row_number': 1, 'answer': 'durable answer'},
        ],
    }
    uploads = []
    build_batch_window = _load_checkpoint_resume_helper(blobs, uploads)
    run = {
        'id': 'run-phase-8-crash',
        'conversation_id': 'conversation-1',
        'source_file_name': 'source.csv',
        'output_format': 'csv',
        'completed_batches': 0,
        'processed_rows': 0,
        'output_schema': ['source_row_number', 'answer'],
    }
    input_batches = [
        [{'Case ID': 'SC-1'}],
        [{'Case ID': 'SC-2'}],
    ]

    batch_results, batch_requests = build_batch_window(
        run,
        input_batches,
        'user-1',
        run['id'],
        1,
        2,
        2,
        durable_output_batches={1},
    )

    assert batch_results[1]['from_checkpoint'] is True
    assert batch_results[1]['batch_row_count'] == 1
    assert [request['batch_number'] for request in batch_requests] == [2]
    assert blobs[committed_output_path][0]['answer'] == 'durable answer'
    assert blobs[summary_path] == {'row_count': 1}
    assert [upload['path'] for upload in uploads] == [summary_path]


def test_phase_eight_performance_summary_is_bounded_and_cohort_comparable():
    """Terminal metrics retain safe rollout dimensions without prompts or row payloads."""
    helpers = _load_performance_helpers()
    helpers['_now_utc'] = lambda: datetime(2026, 8, 10, 12, 20, 0, tzinfo=timezone.utc)
    summary = helpers['_build_tabular_generation_performance_summary']({
        'created_at': '2026-08-10T12:00:00+00:00',
        'started_at': '2026-08-10T12:01:00+00:00',
        'generation_started_at': '2026-08-10T12:02:00+00:00',
        'planner_started_at': '2026-08-10T12:02:00+00:00',
        'planner_completed_at': '2026-08-10T12:02:03.500000+00:00',
        'row_count': 30000,
        'processed_rows': 30000,
        'batch_count': 909,
        'completed_batch_count': 909,
        'rows_per_minute': 1625.25,
        'batch_concurrency': 64,
        'effective_batch_concurrency': 61,
        'retry_count': 4,
        'transient_failure_count': 2,
        'generation_rollout_settings': {
            'tabular_generation_rollout_cohort': 'canary',
        },
        'plan_mode': 'active',
        'executor_mode': 'rolling-pool-v1',
        'response_protocol_version': 'compact-row-array-v1',
        'retry_mode': 'independent-batch-v1',
    }, completed_at='2026-08-10T12:20:00+00:00')

    assert summary['planning_latency_seconds'] == 3.5
    assert summary['queue_latency_seconds'] == 60.0
    assert summary['generation_elapsed_seconds'] == 1080.0
    assert summary['end_to_end_elapsed_seconds'] == 1200.0
    assert summary['durable_rows_per_minute'] == 1625.25
    assert summary['configured_concurrency'] == 64
    assert summary['effective_concurrency'] == 61
    assert summary['rollout_cohort'] == 'canary'
    serialized_summary = json.dumps(summary, sort_keys=True)
    assert len(serialized_summary.encode('utf-8')) < 2048
    assert 'prompt' not in serialized_summary
    assert 'source_file' not in serialized_summary


def test_phase_eight_public_status_omits_private_execution_details():
    """Browser status contains safe aggregate modes but no raw errors or assignment internals."""
    public_status_source = ast.unparse(_get_function_node('_build_run_public_status'))

    assert "'executor_mode': run.get('executor_mode')" in public_status_source
    assert "'retry_mode': run.get('retry_mode')" in public_status_source
    assert "'plan_mode': run.get('plan_mode')" in public_status_source
    for private_field in (
        "'last_error'",
        'generation_rollout_settings',
        'tabular_generation_rollout_bucket',
        'tabular_generation_rollout_hash_version',
        'lease_holder_id',
        'user_question',
        'performance_summary',
    ):
        assert private_field not in public_status_source


def test_phase_one_observability_uses_safe_metrics_not_response_content():
    """Telemetry records usage counts and excludes generated response previews."""
    helpers = _load_performance_helpers()
    usage = helpers['_extract_tabular_response_usage']([
        SimpleNamespace(metadata={
            'usage': {
                'prompt_tokens': 123,
                'completion_tokens': 45,
                'total_tokens': 168,
            },
        }),
    ])

    assert usage == {
        'input_token_count': 123,
        'output_token_count': 45,
        'total_token_count': 168,
    }
    export_source = EXPORT_MODULE.read_text(encoding='utf-8')
    assert 'response_preview' not in export_source
    assert 'batch_model_completed' in export_source
    assert 'batch_checkpointed' in export_source
    assert 'model_latency_seconds' in export_source
    assert 'checkpoint_seconds' in export_source


def test_phase_one_fake_harnesses_control_completion_order_and_storage_failures():
    """Reusable fakes let later phases force stragglers, usage counts, and blob failures."""
    async def complete_out_of_order():
        model = FakeTabularModelHarness([
            {
                'batch_number': 1,
                'content': '[{"answer":"one"}]',
                'usage': {'prompt_tokens': 10, 'completion_tokens': 3},
            },
            {'batch_number': 2, 'content': '[{"answer":"two"}]'},
            {'batch_number': 3, 'content': '[{"answer":"three"}]'},
        ])
        tasks = [
            asyncio.create_task(model.get_chat_message_contents(None, None))
            for _ in range(3)
        ]
        await asyncio.sleep(0)
        model.release_batch(2)
        await asyncio.sleep(0)
        model.release_batch(3)
        await asyncio.sleep(0)
        model.release_batch(1)
        results = await asyncio.gather(*tasks)
        return model, results

    model, results = asyncio.run(complete_out_of_order())
    assert model.calls == [1, 2, 3]
    assert model.completed_batches == [2, 3, 1]
    assert results[0][0].metadata['usage']['prompt_tokens'] == 10

    storage = FakeTabularStorageHarness()
    storage.upload_json_blob(
        'output/batch_000002.json',
        [{'source_row_number': 2, 'answer': 'two'}],
        metadata={'batch_number': 2},
        overwrite=False,
    )
    assert storage.blob_exists('output/batch_000002.json') is True
    assert storage.download_json_blob('output/batch_000002.json')[0]['answer'] == 'two'
    assert storage.metadata['output/batch_000002.json']['batch_number'] == 2
    storage.upload_failures.add('output/batch_000003.json')
    try:
        storage.upload_json_blob('output/batch_000003.json', [], overwrite=False)
    except RuntimeError as exc:
        assert 'Injected upload failure' in str(exc)
    else:
        raise AssertionError('Injected storage failures must be observable')


def test_phase_three_plan_contract_is_bounded_immutable_and_private():
    """The planner sees only bounded shapes and persists one canonical, content-free contract."""
    helpers, _, _ = _load_generation_plan_helpers()
    run = _build_phase_three_test_run()
    plan, input_contract = _build_phase_three_plan(helpers, run)

    serialized_input = json.dumps(input_contract, sort_keys=True)
    serialized_plan = json.dumps(plan, sort_keys=True)
    assert input_contract['sample_row_count'] == 2
    assert 'Sensitive first comment' not in serialized_input
    assert 'Sensitive second comment' not in serialized_input
    assert '<string:' in serialized_input
    assert run['user_question'] not in serialized_plan
    assert 'Sensitive first comment' not in serialized_plan
    assert plan['plan_hash'] == helpers['_hash_tabular_generation_plan'](plan)
    assert len(plan['plan_hash']) == 64
    assert helpers['_get_tabular_generation_plan_output_schema'](plan) == [
        'source_row_number',
        'source_row_identity',
        'answer',
        'risk',
    ]
    helpers['_validate_tabular_generation_plan'](
        plan,
        run,
        input_schema_hash=input_contract['input_schema_hash'],
    )

    tampered_plan = json.loads(json.dumps(plan))
    tampered_plan['output_fields'][2]['description'] = 'Changed after persistence.'
    try:
        helpers['_validate_tabular_generation_plan'](tampered_plan, run)
    except ValueError as exc:
        assert 'hash' in str(exc).lower()
    else:
        raise AssertionError('Plan mutation must fail canonical hash validation')


def test_phase_three_plan_rejects_malformed_fields_and_source_changes():
    """Duplicate, reserved, excessive, unsupported, and source-mismatched plans fail closed."""
    helpers, _, _ = _load_generation_plan_helpers()
    run = _build_phase_three_test_run()
    _, input_contract = _build_phase_three_plan(helpers, run)
    valid_field = {
        'name': 'answer',
        'description': 'Answer requested for the source row.',
        'type': 'string',
        'nullable': False,
        'source': 'llm',
    }
    invalid_field_sets = [
        [valid_field, {**valid_field, 'name': 'ANSWER'}],
        [{**valid_field, 'name': 'source_row_number'}],
        [{**valid_field, 'type': 'date'}],
        [{key: value for key, value in valid_field.items() if key != 'source'}],
        [{**valid_field, 'name': f'field_{index}'} for index in range(51)],
    ]
    for invalid_fields in invalid_field_sets:
        try:
            helpers['_build_tabular_generation_plan'](
                run,
                {'output_fields': invalid_fields},
                input_contract,
                {'model_id': 'gpt-plan', 'deployment': 'gpt-plan'},
            )
        except ValueError:
            continue
        raise AssertionError(f'Invalid planner fields were accepted: {invalid_fields[:2]}')

    plan, _ = _build_phase_three_plan(helpers, run)
    changed_source_run = dict(run)
    changed_source_run['source_descriptor'] = {
        **run['source_descriptor'],
        'blob_etag': '"etag-2"',
    }
    try:
        helpers['_validate_tabular_generation_plan'](plan, changed_source_run)
    except ValueError as exc:
        assert 'etag' in str(exc).lower()
    else:
        raise AssertionError('A source ETag change must invalidate the stored plan')

    missing_contract_plan = json.loads(json.dumps(plan))
    missing_contract_plan.pop('model')
    missing_contract_plan['plan_hash'] = helpers['_hash_tabular_generation_plan'](
        missing_contract_plan
    )
    try:
        helpers['_validate_tabular_generation_plan'](missing_contract_plan, run)
    except ValueError as exc:
        assert 'required' in str(exc).lower()
    else:
        raise AssertionError('A plan missing a required contract must fail validation')


def test_phase_three_shadow_active_and_checkpoint_contracts():
    """Shadow records differences while active mode and checkpoints enforce the planned schema."""
    helpers, _, state = _load_generation_plan_helpers()
    shadow_run = _build_phase_three_test_run(plan_mode='shadow', plan_status='ready')
    plan, _ = _build_phase_three_plan(helpers, shadow_run)
    plan_path = helpers['_tabular_generation_plan_blob_path'](
        shadow_run['user_id'],
        shadow_run['conversation_id'],
        shadow_run['id'],
    )
    shadow_run.update({'plan_blob_path': plan_path, 'plan_hash': plan['plan_hash']})
    state['blobs'][plan_path] = plan

    changed = helpers['_record_shadow_tabular_generation_plan_comparison'](
        shadow_run,
        ['source_row_number', 'source_row_identity', 'risk', 'answer', 'extra'],
    )
    assert changed is True
    assert shadow_run['output_schema'] is None
    assert shadow_run['plan_shadow_comparison']['agreement'] is False
    assert shadow_run['plan_shadow_comparison']['additions'] == ['extra']
    assert shadow_run['plan_shadow_comparison']['omissions'] == []
    assert shadow_run['plan_shadow_comparison']['reorderings'] == ['risk', 'answer']

    agreement_run = _build_phase_three_test_run(plan_mode='shadow', plan_status='ready')
    agreement_run.update({'plan_blob_path': plan_path, 'plan_hash': plan['plan_hash']})
    assert helpers['_record_shadow_tabular_generation_plan_comparison'](
        agreement_run,
        ['source_row_number', 'source_row_identity', 'answer', 'risk'],
    ) is True
    assert agreement_run['plan_shadow_comparison']['agreement'] is True
    assert agreement_run['plan_shadow_comparison']['additions'] == []
    assert agreement_run['plan_shadow_comparison']['omissions'] == []
    assert agreement_run['plan_shadow_comparison']['reorderings'] == []

    active_run = _build_phase_three_test_run(plan_mode='active')
    helpers['_apply_active_tabular_generation_plan'](active_run, plan)
    assert active_run['output_schema'] == [
        'source_row_number',
        'source_row_identity',
        'answer',
        'risk',
    ]

    checkpoint_metadata = helpers['_build_tabular_output_checkpoint_metadata'](
        {**active_run, 'plan_hash': plan['plan_hash']},
        {'batch_number': 1},
    )
    assert checkpoint_metadata['plan_hash'] == plan['plan_hash']
    assert checkpoint_metadata['source_etag'] == 'etag-1'
    state['metadata']['output/batch_000001.json'] = checkpoint_metadata
    helpers['_validate_tabular_output_checkpoint_metadata'](
        {**active_run, 'plan_hash': plan['plan_hash']},
        'output/batch_000001.json',
        1,
    )
    state['metadata']['output/batch_000001.json']['plan_hash'] = 'wrong-plan'
    try:
        helpers['_validate_tabular_output_checkpoint_metadata'](
            {**active_run, 'plan_hash': plan['plan_hash']},
            'output/batch_000001.json',
            1,
        )
    except ValueError as exc:
        assert 'plan hash' in str(exc).lower()
    else:
        raise AssertionError('Checkpoint plan metadata mismatch must fail')


def test_phase_three_planner_timeout_retries_before_fallback():
    """The bounded planner retries provider timeouts and reports a safe fallback reason."""
    helpers, PlannerError, _ = _load_generation_plan_helpers()
    run = _build_phase_three_test_run(plan_mode='active')
    _, input_contract = _build_phase_three_plan(helpers, run)

    class TimeoutPlanner:
        def __init__(self):
            self.calls = 0

        async def get_chat_message_contents(self, chat_history, execution_settings):
            del chat_history, execution_settings
            self.calls += 1
            raise asyncio.TimeoutError()

    planner = TimeoutPlanner()
    try:
        asyncio.run(helpers['_generate_tabular_generation_plan'](
            planner,
            run,
            input_contract,
            {'model_id': 'gpt-plan', 'deployment': 'gpt-plan'},
            30,
        ))
    except PlannerError as exc:
        assert exc.reason == 'timeout'
    else:
        raise AssertionError('Planner timeout exhaustion must request legacy fallback')
    assert planner.calls == 2


def test_phase_three_plan_persistence_boundaries_never_replan():
    """Resume recovers an immutable plan or falls back without automatically replanning."""
    helpers, PlannerError, state = _load_generation_plan_helpers()
    active_run = _build_phase_three_test_run(plan_mode='active', plan_status='planning')
    plan, _ = _build_phase_three_plan(helpers, active_run)
    plan_path = helpers['_tabular_generation_plan_blob_path'](
        active_run['user_id'],
        active_run['conversation_id'],
        active_run['id'],
    )
    state['blobs'][plan_path] = plan
    planner_calls = []

    async def unexpected_planner_call(*args, **kwargs):
        planner_calls.append((args, kwargs))
        raise AssertionError('Resume must not call the planner')

    helpers['_generate_tabular_generation_plan'] = unexpected_planner_call
    recovered_run = helpers['_ensure_tabular_generation_plan'](
        active_run,
        object(),
        active_run['_test_batches'],
        {},
        60,
    )
    assert planner_calls == []
    assert recovered_run['plan_status'] == 'ready'
    assert recovered_run['plan_blob_path'] == plan_path
    assert recovered_run['plan_hash'] == plan['plan_hash']
    assert recovered_run['output_schema'][-2:] == ['answer', 'risk']

    interrupted_run = _build_phase_three_test_run(plan_mode='active', plan_status='planning')
    state['blobs'].clear()
    fallback_run = helpers['_ensure_tabular_generation_plan'](
        interrupted_run,
        object(),
        interrupted_run['_test_batches'],
        {},
        60,
    )
    assert planner_calls == []
    assert fallback_run['plan_status'] == 'fallback'
    assert fallback_run['plan_failure_reason'] == 'interrupted_before_persistence'
    assert fallback_run['output_schema'] is None

    pending_run = _build_phase_three_test_run(plan_mode='active', plan_status='pending')

    async def timed_out_planner(*args, **kwargs):
        del args, kwargs
        raise PlannerError('timeout')

    helpers['_generate_tabular_generation_plan'] = timed_out_planner
    timeout_fallback_run = helpers['_ensure_tabular_generation_plan'](
        pending_run,
        object(),
        pending_run['_test_batches'],
        {},
        60,
    )
    assert timeout_fallback_run['plan_status'] == 'fallback'
    assert timeout_fallback_run['plan_failure_reason'] == 'timeout'
    assert timeout_fallback_run['output_schema'] is None

    upload_helpers, _, upload_state = _load_generation_plan_helpers()
    new_run = _build_phase_three_test_run(plan_mode='active', plan_status='pending')
    new_plan, _ = _build_phase_three_plan(upload_helpers, new_run)
    successful_planner_calls = []

    async def successful_planner(*args, **kwargs):
        successful_planner_calls.append((args, kwargs))
        return new_plan, {
            'attempt_count': 1,
            'latency_seconds': 0.25,
            'model_latency_seconds': 0.2,
            'input_char_count': 1000,
            'response_char_count': 300,
            'input_token_count': 250,
            'output_token_count': 75,
            'total_token_count': 325,
        }

    upload_helpers['_generate_tabular_generation_plan'] = successful_planner
    planned_run = upload_helpers['_ensure_tabular_generation_plan'](
        new_run,
        object(),
        new_run['_test_batches'],
        {},
        60,
    )
    assert len(successful_planner_calls) == 1
    assert len(upload_state['uploads']) == 1
    assert upload_state['uploads'][0]['overwrite'] is False
    assert upload_state['uploads'][0]['path'].endswith('/plan/plan_v1.json')
    assert upload_state['uploads'][0]['metadata']['plan_hash'] == new_plan['plan_hash']
    assert planned_run['plan_status'] == 'ready'
    assert planned_run['output_schema'][-2:] == ['answer', 'risk']

    async def ready_state_planner(*args, **kwargs):
        raise AssertionError('A ready run must reload its immutable plan')

    upload_helpers['_generate_tabular_generation_plan'] = ready_state_planner
    reloaded_run = upload_helpers['_ensure_tabular_generation_plan'](
        planned_run,
        object(),
        planned_run['_test_batches'],
        {},
        60,
    )
    assert reloaded_run['plan_hash'] == new_plan['plan_hash']
    assert len(upload_state['uploads']) == 1

    mismatched_run = dict(planned_run)
    mismatched_run['plan_hash'] = '0' * 64
    try:
        upload_helpers['_ensure_tabular_generation_plan'](
            mismatched_run,
            object(),
            mismatched_run['_test_batches'],
            {},
            60,
        )
    except ValueError as exc:
        assert 'run record' in str(exc).lower()
    else:
        raise AssertionError('A run-level plan hash mismatch must fail resume')

    old_run = _build_phase_three_test_run(plan_mode='off', plan_status='disabled')
    old_run['generation_rollout_settings'] = {}
    legacy_run = upload_helpers['_ensure_tabular_generation_plan'](
        old_run,
        object(),
        old_run['_test_batches'],
        {},
        60,
    )
    assert legacy_run['plan_blob_path'] is None
    assert legacy_run['plan_hash'] is None
    assert legacy_run['output_schema'] is None


def test_phase_four_compact_protocol_requires_active_plan_rollout():
    """Compact row arrays are selected only for new active planned structured exports."""
    helpers = _load_compact_protocol_helpers()
    select_protocol = helpers['_select_tabular_response_protocol']
    object_protocol = helpers['TABULAR_RESPONSE_PROTOCOL_OBJECT_V1']
    compact_protocol = helpers['TABULAR_RESPONSE_PROTOCOL_COMPACT_ROW_ARRAY_V1']

    assert select_protocol({}, 'active', 'structured_export') == object_protocol
    assert select_protocol(
        {'enable_tabular_compact_response_protocol': True},
        'shadow',
        'structured_export',
    ) == object_protocol
    assert select_protocol(
        {'enable_tabular_compact_response_protocol': True},
        'active',
        'combined',
    ) == object_protocol
    assert select_protocol(
        {'enable_tabular_compact_response_protocol': True},
        'active',
        'structured_export',
        passthrough_input_rows=True,
    ) == object_protocol
    assert select_protocol(
        {'enable_tabular_compact_response_protocol': True},
        'active',
        'structured_export',
    ) == compact_protocol

    run = _build_phase_three_test_run(plan_mode='active')
    run['response_protocol_version'] = compact_protocol
    plan, input_contract = _build_phase_three_plan(helpers, run)
    assert plan['response_protocol'] == compact_protocol
    helpers['_validate_tabular_generation_plan'](
        plan,
        run,
        input_schema_hash=input_contract['input_schema_hash'],
    )

    invalid_run = dict(run)
    invalid_run['response_protocol_version'] = 'unknown-protocol'
    try:
        helpers['_build_tabular_generation_plan'](
            invalid_run,
            {'output_fields': plan['output_fields'][2:]},
            input_contract,
            {'model_id': 'gpt-plan', 'deployment': 'gpt-plan'},
        )
    except ValueError as exc:
        assert 'protocol' in str(exc).lower()
    else:
        raise AssertionError('Unknown response protocols must fail plan creation')


def test_phase_four_compact_response_reconstructs_object_contract():
    """Compact rows normalize to the same object-shaped checkpoint entries as object-v1."""
    helpers = _load_compact_protocol_helpers()
    compact_protocol = helpers['TABULAR_RESPONSE_PROTOCOL_COMPACT_ROW_ARRAY_V1']
    run = _build_phase_three_test_run(plan_mode='active')
    run['response_protocol_version'] = compact_protocol
    plan, _ = _build_phase_four_plan(helpers, run)
    source_rows = run['_test_batches'][0] + run['_test_batches'][1]

    prompt = helpers['_build_batch_prompt'](
        run['user_question'],
        source_rows,
        0,
        1,
        'source.csv',
        output_schema=helpers['_get_tabular_generation_plan_output_schema'](plan),
        response_protocol=compact_protocol,
        generation_plan=plan,
    )
    assert '__simplechat_batch_row_key' in prompt
    assert '__simplechat_source_row_token' not in prompt
    assert 'token-1' not in prompt
    assert 'token-2' not in prompt

    response_payload = {
        'p': helpers['_get_compact_plan_hash_prefix'](plan),
        'rows': [
            ['r2', 'second answer', None, 9.5, False, {'quote': 'line, quote "two"'}, ['beta']],
            ['r1', 'first answer', 'low', 7, True, {'note': 'line one\nline two'}, ['alpha']],
        ],
    }
    generated_entries = helpers['_parse_compact_row_array_entries'](
        json.dumps(response_payload),
        source_rows,
        plan,
    )
    normalized_entries, output_schema = helpers['_normalize_generated_batch_entries'](
        source_rows,
        generated_entries,
        expected_output_schema=helpers['_get_tabular_generation_plan_output_schema'](plan),
    )

    assert output_schema == [
        'source_row_number',
        'source_row_identity',
        'answer',
        'risk',
        'score',
        'flagged',
        'evidence',
        'tags',
    ]
    assert normalized_entries[0]['source_row_number'] == 1
    assert normalized_entries[0]['source_row_identity'] == 'SC-1'
    assert normalized_entries[0]['answer'] == 'first answer'
    assert normalized_entries[0]['risk'] == 'low'
    assert normalized_entries[0]['score'] == 7
    assert normalized_entries[0]['flagged'] is True
    assert normalized_entries[0]['evidence']['note'] == 'line one\nline two'
    assert normalized_entries[1]['source_row_number'] == 2
    assert normalized_entries[1]['answer'] == 'second answer'
    assert normalized_entries[1]['risk'] is None
    assert '__simplechat_source_row_token' not in normalized_entries[0]


def test_phase_four_compact_response_rejects_key_and_value_failures():
    """Malformed compact rows fail validation instead of receiving deterministic answers."""
    helpers = _load_compact_protocol_helpers()
    compact_protocol = helpers['TABULAR_RESPONSE_PROTOCOL_COMPACT_ROW_ARRAY_V1']
    run = _build_phase_three_test_run(plan_mode='active')
    run['response_protocol_version'] = compact_protocol
    plan, _ = _build_phase_four_plan(helpers, run)
    source_rows = run['_test_batches'][0] + run['_test_batches'][1]
    prefix = helpers['_get_compact_plan_hash_prefix'](plan)
    valid_r1 = ['r1', 'first answer', 'low', 7, True, {'note': 'one'}, ['alpha']]
    valid_r2 = ['r2', 'second answer', None, 9.5, False, {'note': 'two'}, ['beta']]
    failure_cases = [
        (
            {'p': prefix, 'rows': [valid_r1, valid_r1]},
            'duplicated',
        ),
        (
            {'p': prefix, 'rows': [valid_r1]},
            'missed',
        ),
        (
            {'p': prefix, 'rows': [valid_r1, ['r3', 'third', 'high', 1, False, {}, []]]},
            'unknown',
        ),
        (
            {'p': prefix, 'rows': [valid_r1, ['r2', 'second answer']]},
            'expected',
        ),
        (
            {'p': 'bad-prefix', 'rows': [valid_r1, valid_r2]},
            'hash',
        ),
        (
            {'p': prefix, 'rows': [[*valid_r1[:1], None, *valid_r1[2:]], valid_r2]},
            'non-nullable',
        ),
        (
            {'p': prefix, 'rows': [[*valid_r1[:3], 'not-a-number', *valid_r1[4:]], valid_r2]},
            'expected number',
        ),
    ]
    for payload, expected_message in failure_cases:
        try:
            helpers['_parse_compact_row_array_entries'](
                json.dumps(payload),
                source_rows,
                plan,
            )
        except ValueError as exc:
            assert expected_message in str(exc).lower()
        else:
            raise AssertionError(f'Compact validation accepted invalid payload: {payload}')


def test_phase_five_completion_driven_checkpointing_commits_fast_batch_before_straggler():
    """A completed model response is checkpointed before a slower batch in the same fixed window settles."""
    helpers = _load_completion_checkpoint_helpers()
    events = []
    straggler_finished_at = {'value': None}

    async def generate_batch_entries_for_window(
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
        del chat_service, user_question, total_batches, source_file_name, selected_sheet
        del retry_attempts, run_id, expected_output_schema, batch_timeout_seconds
        del response_protocol, generation_plan
        batch_number = batch_request['batch_number']
        async with semaphore:
            if batch_number == 2:
                await asyncio.sleep(0.2)
                straggler_finished_at['value'] = time.monotonic()
            else:
                await asyncio.sleep(0.01)
            return {
                'batch_number': batch_number,
                'batch_entries': [{'source_row_number': batch_number, 'answer': f'a{batch_number}'}],
                'batch_summary': {'row_count': 1},
                'batch_row_count': 1,
                'elapsed_seconds': 0.01 if batch_number == 1 else 0.2,
                'mismatch_count': 0,
                'output_schema': ['source_row_number', 'answer'],
            }

    def checkpoint_generated_batch_results(run, generated_results):
        del run
        generated_result = generated_results[0]
        batch_number = generated_result['batch_number']
        events.append({
            'batch_number': batch_number,
            'checkpointed_at': time.monotonic(),
        })
        return {
            batch_number: {
                'batch_number': batch_number,
                'batch_row_count': generated_result['batch_row_count'],
                'elapsed_seconds': generated_result['elapsed_seconds'],
                'mismatch_count': 0,
                'from_checkpoint': False,
            }
        }

    helpers['_generate_batch_entries_for_window'] = generate_batch_entries_for_window
    helpers['_checkpoint_generated_batch_results'] = checkpoint_generated_batch_results

    settings = {
        'enable_tabular_completion_driven_checkpointing': True,
        'tabular_generation_checkpoint_writer_concurrency': '1',
    }
    assert helpers['_is_completion_driven_checkpointing_enabled'](settings) is True
    assert helpers['_get_checkpoint_writer_concurrency'](settings) == 1

    batch_results, generation_error = asyncio.run(
        helpers['_generate_and_checkpoint_batch_window_entries'](
            {'id': 'run-phase-5', 'output_schema': ['source_row_number', 'answer']},
            None,
            'answer every row',
            [
                {'batch_number': 1, 'rows': [{'row': 1}]},
                {'batch_number': 2, 'rows': [{'row': 2}]},
            ],
            2,
            'source.csv',
            None,
            1,
            'run-phase-5',
            2,
            1,
            expected_output_schema=['source_row_number', 'answer'],
        )
    )

    assert generation_error is None
    assert set(batch_results) == {1, 2}
    fast_checkpoint = next(event for event in events if event['batch_number'] == 1)
    assert straggler_finished_at['value'] is not None
    assert fast_checkpoint['checkpointed_at'] < straggler_finished_at['value']


def test_phase_five_resume_scan_lists_output_prefix_once():
    """Resume builds the durable completed set from one output-prefix listing."""
    helpers = _load_completion_checkpoint_helpers()
    list_calls = []
    run = {
        'id': 'run-phase-5',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'batch_count': 3,
    }
    prefix = helpers['_output_blob_prefix']('user-1', 'conversation-1', 'run-phase-5')

    class BlobProperties:
        def __init__(self, name):
            self.name = name

    class ContainerClient:
        def list_blobs(self, name_starts_with=None):
            list_calls.append(name_starts_with)
            return [
                BlobProperties(f'{prefix}batch_000001.json'),
                BlobProperties(f'{prefix}batch_000003.json'),
                BlobProperties(f'{prefix}batch_000004.json'),
                BlobProperties(f'{prefix}batch_bad.json'),
                BlobProperties('other/run/output/batch_000002.json'),
            ]

    class BlobServiceClient:
        def get_container_client(self, container_name):
            assert container_name == 'personal-chat'
            return ContainerClient()

    helpers['_get_blob_service_client'] = lambda: BlobServiceClient()

    completed_batches = helpers['_scan_output_checkpoint_batches_for_run'](run)

    assert completed_batches == {1, 3}
    assert list_calls == [prefix]


def test_phase_six_rolling_executor_selection_requires_active_planned_checkpointing():
    """Rolling mode is recorded only for active planned structured exports with durable checkpoints."""
    helpers = _load_completion_checkpoint_helpers()
    select_executor = helpers['_select_tabular_executor_mode']
    fixed_mode = helpers['TABULAR_EXECUTOR_MODE_FIXED_WINDOW']
    rolling_mode = helpers['TABULAR_EXECUTOR_MODE_ROLLING_POOL']

    enabled_rollout = {
        'enable_tabular_generation_plan': True,
        'tabular_generation_plan_mode': 'active',
        'enable_tabular_completion_driven_checkpointing': True,
        'enable_tabular_rolling_worker_pool': True,
    }
    assert select_executor(enabled_rollout, 'active', 'structured_export') == rolling_mode
    assert select_executor(enabled_rollout, 'shadow', 'structured_export') == fixed_mode
    assert select_executor({**enabled_rollout, 'enable_tabular_completion_driven_checkpointing': False}, 'active', 'structured_export') == fixed_mode
    assert select_executor(enabled_rollout, 'active', 'combined') == fixed_mode
    assert select_executor(enabled_rollout, 'active', 'structured_export', passthrough_input_rows=True) == fixed_mode

    ready_run = {
        'executor_mode': rolling_mode,
        'task_type': 'structured_export',
        'passthrough_input_rows': False,
        'generation_rollout_settings': enabled_rollout,
        'plan_mode': 'active',
        'plan_status': 'ready',
        'plan_blob_path': 'plan/plan_v1.json',
        'plan_hash': 'f' * 64,
        'output_schema': ['source_row_number', 'source_row_identity', 'answer'],
    }
    assert helpers['_is_rolling_worker_pool_enabled']({}, ready_run) is True
    assert helpers['_is_completion_driven_checkpointing_enabled']({}, ready_run) is True
    assert helpers['_get_tabular_generation_heartbeat_seconds']({}, ready_run) == 30
    assert helpers['_is_rolling_executor_ready'](ready_run) is True
    fallback_run = {**ready_run, 'plan_status': 'fallback', 'output_schema': None}
    assert helpers['_is_rolling_executor_ready'](fallback_run) is False


def test_phase_six_rolling_pool_replenishes_completed_slot_before_straggler():
    """A completed rolling task is replaced without waiting for another active straggler."""
    helpers = _load_completion_checkpoint_helpers()
    scheduled_at = {}
    finished_at = {}
    checkpointed = []

    def scan_output_checkpoint_batches_for_run(run):
        del run
        return set()

    def raise_if_not_canceled(run):
        return run

    def build_batch_window(run, input_batches, user_id, run_id, window_start, window_end, batch_count, durable_output_batches=None):
        del run, input_batches, user_id, run_id, window_end, batch_count, durable_output_batches
        scheduled_at[window_start] = time.monotonic()
        return {}, [{'batch_number': window_start, 'rows': [{'row': window_start}]}]

    async def generate_batch_entries_for_window(
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
        del chat_service, user_question, total_batches, source_file_name, selected_sheet
        del retry_attempts, run_id, expected_output_schema, batch_timeout_seconds
        del response_protocol, generation_plan
        batch_number = batch_request['batch_number']
        async with semaphore:
            await asyncio.sleep(0.2 if batch_number == 2 else 0.01)
            finished_at[batch_number] = time.monotonic()
            return {
                'batch_number': batch_number,
                'batch_entries': [{'source_row_number': batch_number, 'answer': f'a{batch_number}'}],
                'batch_summary': {'row_count': 1},
                'batch_row_count': 1,
                'elapsed_seconds': 0.2 if batch_number == 2 else 0.01,
                'mismatch_count': 0,
                'output_schema': ['source_row_number', 'answer'],
            }

    async def checkpoint_generated_result_async(run, generated_result, writer_semaphore):
        del run
        async with writer_semaphore:
            batch_number = generated_result['batch_number']
            checkpointed.append(batch_number)
            return {
                batch_number: {
                    'batch_number': batch_number,
                    'batch_row_count': 1,
                    'elapsed_seconds': generated_result['elapsed_seconds'],
                    'mismatch_count': 0,
                    'from_checkpoint': False,
                }
            }

    def advance_progress(run, batch_results, completed_batches, processed_rows, window_start, window_end):
        for batch_number in range(window_start, window_end + 1):
            if batch_number not in batch_results:
                break
            completed_batches = batch_number
            processed_rows += batch_results[batch_number]['batch_row_count']
        run['completed_batches'] = completed_batches
        run['processed_rows'] = processed_rows
        return run, completed_batches, processed_rows

    helpers['_scan_output_checkpoint_batches_for_run'] = scan_output_checkpoint_batches_for_run
    helpers['_raise_if_tabular_export_canceled'] = raise_if_not_canceled
    helpers['_build_batch_window'] = build_batch_window
    helpers['_generate_batch_entries_for_window'] = generate_batch_entries_for_window
    helpers['_checkpoint_generated_result_async'] = checkpoint_generated_result_async
    helpers['_advance_run_progress_for_window'] = advance_progress
    helpers['_log_progress_if_due'] = lambda run, last_logged_at: last_logged_at

    run = {
        'id': 'run-phase-6',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'batch_count': 4,
        'completed_batches': 0,
        'processed_rows': 0,
        'output_schema': ['source_row_number', 'answer'],
    }
    result_run, completed_batches, processed_rows, _ = asyncio.run(
        helpers['_generate_and_checkpoint_rolling_pool_entries'](
            run,
            object(),
            None,
            'answer every row',
            4,
            'source.csv',
            None,
            1,
            'run-phase-6',
            'user-1',
            2,
            2,
            300,
        )
    )

    assert result_run is run
    assert completed_batches == 4
    assert processed_rows == 4
    assert checkpointed == [1, 3, 4, 2]
    assert scheduled_at[3] < finished_at[2]
    assert max(scheduled_at) == 4


def test_phase_six_rolling_pool_heartbeat_records_active_counts():
    """The rolling heartbeat writes lease liveness and bounded scheduler counters."""
    helpers = _load_completion_checkpoint_helpers()
    heartbeat_writes = []

    def raise_if_not_canceled(run):
        return run

    def replace_claimed_run(run):
        heartbeat_writes.append(dict(run))
        return dict(run)

    helpers['_raise_if_tabular_export_canceled'] = raise_if_not_canceled
    helpers['_replace_claimed_run'] = replace_claimed_run
    helpers['_now_iso'] = lambda: f"2026-08-10T12:00:0{len(heartbeat_writes)}+00:00"

    async def run_heartbeat_once():
        run = {
            'id': 'run-phase-6-heartbeat',
            'completed_batches': 2,
            'batch_count': 10,
        }
        counts = {
            'active': 4,
            'pending': 6,
            'checkpointing': 1,
            'retry_wait': 0,
        }
        state_lock = asyncio.Lock()
        stop_event = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            helpers['_rolling_pool_heartbeat_loop'](
                run,
                counts,
                state_lock,
                stop_event,
                0.001,
            )
        )
        while not heartbeat_writes:
            await asyncio.sleep(0)
        stop_event.set()
        await heartbeat_task
        return run

    run = asyncio.run(run_heartbeat_once())

    assert heartbeat_writes[0]['active_batch_count'] == 4
    assert heartbeat_writes[0]['pending_batch_count'] == 6
    assert heartbeat_writes[0]['checkpointing_batch_count'] == 1
    assert heartbeat_writes[0]['last_heartbeat_at'].startswith('2026-08-10T12:00:00')
    assert 'Rolling structured export active: 2 of 10 batch(es) durable' in run['last_message']


def test_phase_six_rolling_pool_pauses_dispatch_at_checkpoint_high_water():
    """Checkpoint backlog high-water pauses new model dispatch until a writer completes."""
    helpers = _load_completion_checkpoint_helpers()
    scheduled_at = {}
    checkpoint_started = []
    checkpoint_release = None

    def scan_output_checkpoint_batches_for_run(run):
        del run
        return set()

    def raise_if_not_canceled(run):
        return run

    def build_batch_window(run, input_batches, user_id, run_id, window_start, window_end, batch_count, durable_output_batches=None):
        del run, input_batches, user_id, run_id, window_end, batch_count, durable_output_batches
        scheduled_at[window_start] = time.monotonic()
        return {}, [{'batch_number': window_start, 'rows': [{'row': window_start}]}]

    async def generate_batch_entries_for_window(
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
        del chat_service, user_question, total_batches, source_file_name, selected_sheet
        del retry_attempts, run_id, expected_output_schema, batch_timeout_seconds
        del response_protocol, generation_plan
        async with semaphore:
            await asyncio.sleep(0)
            batch_number = batch_request['batch_number']
            return {
                'batch_number': batch_number,
                'batch_entries': [{'source_row_number': batch_number, 'answer': f'a{batch_number}'}],
                'batch_summary': {'row_count': 1},
                'batch_row_count': 1,
                'elapsed_seconds': 0.01,
                'mismatch_count': 0,
                'output_schema': ['source_row_number', 'answer'],
            }

    async def checkpoint_generated_result_async(run, generated_result, writer_semaphore):
        del run, writer_semaphore
        batch_number = generated_result['batch_number']
        checkpoint_started.append(batch_number)
        if batch_number <= 2:
            await checkpoint_release.wait()
        return {
            batch_number: {
                'batch_number': batch_number,
                'batch_row_count': 1,
                'elapsed_seconds': generated_result['elapsed_seconds'],
                'mismatch_count': 0,
                'from_checkpoint': False,
            }
        }

    def advance_progress(run, batch_results, completed_batches, processed_rows, window_start, window_end):
        for batch_number in range(window_start, window_end + 1):
            if batch_number not in batch_results:
                break
            completed_batches = batch_number
            processed_rows += batch_results[batch_number]['batch_row_count']
        run['completed_batches'] = completed_batches
        run['processed_rows'] = processed_rows
        return run, completed_batches, processed_rows

    helpers['_scan_output_checkpoint_batches_for_run'] = scan_output_checkpoint_batches_for_run
    helpers['_raise_if_tabular_export_canceled'] = raise_if_not_canceled
    helpers['_build_batch_window'] = build_batch_window
    helpers['_generate_batch_entries_for_window'] = generate_batch_entries_for_window
    helpers['_checkpoint_generated_result_async'] = checkpoint_generated_result_async
    helpers['_advance_run_progress_for_window'] = advance_progress
    helpers['_log_progress_if_due'] = lambda run, last_logged_at: last_logged_at

    async def run_backpressure_scenario():
        nonlocal checkpoint_release
        checkpoint_release = asyncio.Event()
        run = {
            'id': 'run-phase-6-backpressure',
            'user_id': 'user-1',
            'conversation_id': 'conversation-1',
            'batch_count': 3,
            'completed_batches': 0,
            'processed_rows': 0,
            'output_schema': ['source_row_number', 'answer'],
        }
        rolling_task = asyncio.create_task(
            helpers['_generate_and_checkpoint_rolling_pool_entries'](
                run,
                object(),
                None,
                'answer every row',
                3,
                'source.csv',
                None,
                1,
                'run-phase-6-backpressure',
                'user-1',
                2,
                1,
                300,
            )
        )
        while len(checkpoint_started) < 2:
            await asyncio.sleep(0)
        assert set(scheduled_at) == {1, 2}
        checkpoint_release.set()
        result_run, completed_batches, processed_rows, _ = await rolling_task
        return result_run, completed_batches, processed_rows

    result_run, completed_batches, processed_rows = asyncio.run(run_backpressure_scenario())

    assert completed_batches == 3
    assert processed_rows == 3
    assert result_run['completed_batches'] == 3
    assert set(scheduled_at) == {1, 2, 3}


def test_phase_seven_retry_ledger_uses_safe_bounded_metadata():
    """Per-batch retry records persist safe bounded metadata without raw provider errors."""
    helpers = _load_completion_checkpoint_helpers()
    helpers['_now_utc'] = lambda: datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    run = {
        'id': 'run-phase-7',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'plan_hash': 'abcdef1234567890',
        'lease_generation': 3,
        'batch_count': 8,
    }
    batch_request = {
        'batch_number': 7,
        'rows': [
            {'__simplechat_source_row_number': 301, 'Case ID': 'SC-301'},
            {'__simplechat_source_row_number': 302, 'Case ID': 'SC-302'},
        ],
    }

    class RateLimitError(Exception):
        status_code = 429

    retry_record = helpers['_build_tabular_batch_retry_record'](
        run,
        7,
        batch_request,
        RateLimitError('raw provider detail should not be persisted'),
        max_attempts=2,
    )

    assert helpers['_retry_blob_path']('user-1', 'conversation-1', 'run-phase-7', 7).endswith(
        '/retry/batch_000007.json'
    )
    assert retry_record['failure_category'] == 'rate_limit'
    assert retry_record['safe_error_code'] == 'http_429'
    assert retry_record['attempts_by_category'] == {'rate_limit': 1}
    assert retry_record['row_count'] == 2
    assert retry_record['first_source_row_number'] == 301
    assert retry_record['last_source_row_number'] == 302
    assert retry_record['next_attempt_at'] is not None
    assert retry_record['exhausted'] is False
    serialized_record = json.dumps(retry_record, sort_keys=True)
    assert 'raw provider detail' not in serialized_record

    exhausted_record = helpers['_build_tabular_batch_retry_record'](
        run,
        7,
        batch_request,
        ValueError('failed validation: raw schema mismatch detail'),
        max_attempts=1,
    )
    assert exhausted_record['failure_category'] == 'model_validation'
    assert exhausted_record['safe_error_code'] == 'valueerror'
    assert exhausted_record['exhausted'] is True
    assert exhausted_record['next_attempt_at'] is None

    persisted_records = {}
    helpers['_scan_output_checkpoint_batches_for_run'] = lambda active_run: set()
    helpers['_load_tabular_batch_retry_records_for_run'] = lambda active_run, completed: {
        7: dict(exhausted_record),
    }
    helpers['_persist_tabular_batch_retry_record'] = lambda active_run, record: persisted_records.__setitem__(
        record['batch_number'],
        dict(record),
    )
    reset_count = helpers['_reset_exhausted_tabular_batch_retry_records_for_continue'](
        run,
        '2026-08-10T12:01:00+00:00',
    )

    assert reset_count == 1
    assert persisted_records[7]['attempt_count'] == 0
    assert persisted_records[7]['attempts_by_category'] == {}
    assert persisted_records[7]['exhausted'] is False
    assert persisted_records[7]['next_attempt_at'] == '2026-08-10T12:01:00+00:00'


def test_phase_seven_independent_retry_keeps_healthy_batches_running():
    """A failed rolling batch retries independently while unrelated pending batches continue."""
    helpers = _load_completion_checkpoint_helpers()
    scheduled_batches = []
    generation_attempts = Counter()
    checkpointed_batches = []
    retry_records = {}
    deleted_retry_records = []

    def build_batch_window(run, input_batches, user_id, run_id, window_start, window_end, batch_count, durable_output_batches=None):
        del run, input_batches, user_id, run_id, window_end, batch_count, durable_output_batches
        scheduled_batches.append(window_start)
        return {}, [{
            'batch_number': window_start,
            'rows': [{
                '__simplechat_source_row_number': window_start,
                'Case ID': f'SC-{window_start}',
            }],
        }]

    async def generate_batch_entries_for_window(
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
        del chat_service, user_question, total_batches, source_file_name, selected_sheet
        del retry_attempts, run_id, expected_output_schema, batch_timeout_seconds
        del response_protocol, generation_plan
        async with semaphore:
            batch_number = batch_request['batch_number']
            generation_attempts[batch_number] += 1
            await asyncio.sleep(0.01)
            if batch_number == 2 and generation_attempts[batch_number] == 1:
                raise ValueError('failed validation: missing answer field')
            return {
                'batch_number': batch_number,
                'batch_entries': [{'source_row_number': batch_number, 'answer': f'a{batch_number}'}],
                'batch_summary': {'row_count': 1},
                'batch_row_count': 1,
                'elapsed_seconds': 0.01,
                'mismatch_count': 0,
                'output_schema': ['source_row_number', 'answer'],
            }

    async def checkpoint_generated_result_async(run, generated_result, writer_semaphore):
        del run
        async with writer_semaphore:
            batch_number = generated_result['batch_number']
            checkpointed_batches.append(batch_number)
            return {
                batch_number: {
                    'batch_number': batch_number,
                    'batch_row_count': 1,
                    'elapsed_seconds': generated_result['elapsed_seconds'],
                    'mismatch_count': 0,
                    'from_checkpoint': False,
                }
            }

    def advance_progress(run, batch_results, completed_batches, processed_rows, window_start, window_end):
        for batch_number in range(window_start, window_end + 1):
            if batch_number not in batch_results:
                break
            completed_batches = batch_number
            processed_rows += batch_results[batch_number]['batch_row_count']
        run['completed_batches'] = completed_batches
        run['processed_rows'] = processed_rows
        return run, completed_batches, processed_rows

    helpers['_scan_output_checkpoint_batches_for_run'] = lambda run: set()
    helpers['_load_tabular_batch_retry_records_for_run'] = lambda run, completed: {}
    helpers['_raise_if_tabular_export_canceled'] = lambda run: run
    helpers['_build_batch_window'] = build_batch_window
    helpers['_generate_batch_entries_for_window'] = generate_batch_entries_for_window
    helpers['_checkpoint_generated_result_async'] = checkpoint_generated_result_async
    helpers['_advance_run_progress_for_window'] = advance_progress
    helpers['_log_progress_if_due'] = lambda run, last_logged_at: last_logged_at
    helpers['_persist_tabular_batch_retry_record'] = lambda run, record: retry_records.__setitem__(
        record['batch_number'],
        dict(record),
    )
    helpers['_delete_tabular_batch_retry_record'] = lambda run, batch_number: deleted_retry_records.append(
        batch_number
    )
    helpers['_is_tabular_batch_retry_due'] = lambda record: 3 in scheduled_batches

    run = {
        'id': 'run-phase-7-independent-retry',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'batch_count': 4,
        'completed_batches': 0,
        'processed_rows': 0,
        'output_schema': ['source_row_number', 'answer'],
        'plan_hash': 'abcdef1234567890',
        'generation_rollout_settings': {
            'enable_tabular_independent_batch_retries': True,
            'tabular_generation_systemic_failure_threshold': 1.0,
        },
    }
    result_run, completed_batches, processed_rows, _ = asyncio.run(
        helpers['_generate_and_checkpoint_rolling_pool_entries'](
            run,
            object(),
            None,
            'answer every row',
            4,
            'source.csv',
            None,
            2,
            'run-phase-7-independent-retry',
            'user-1',
            2,
            2,
            300,
            independent_batch_retries_enabled=True,
        )
    )

    second_batch_dispatches = [
        index
        for index, batch_number in enumerate(scheduled_batches)
        if batch_number == 2
    ]
    assert len(second_batch_dispatches) == 2
    assert scheduled_batches.index(3) < second_batch_dispatches[1]
    assert generation_attempts[2] == 2
    assert retry_records[2]['failure_category'] == 'model_validation'
    assert deleted_retry_records.count(2) >= 1
    assert set(checkpointed_batches) == {1, 2, 3, 4}
    assert completed_batches == 4
    assert processed_rows == 4
    assert result_run['retry_wait_batch_count'] == 0
    assert result_run['exhausted_batch_count'] == 0


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


def test_model_batch_token_echo_recovery_preserves_order_contract():
    """Model responses may omit hidden token echoes but cannot contradict row order."""
    helpers = _load_contract_helpers()
    prepared_rows = helpers['_prepare_tabular_source_rows'](
        [
            {'Case ID': 'SC-2001', 'Comment': 'first'},
            {'Case ID': 'SC-2002', 'Comment': 'second'},
        ],
        start_row=0,
    )
    token_echo_mismatch_entries = [
        {
            '__simplechat_source_row_token': 'model-made-up-token-1',
            'source_row_number': 1,
            'source_row_identity': 'SC-2001',
            'answer': 'yes',
        },
        {
            '__simplechat_source_row_token': 'model-made-up-token-2',
            'source_row_number': 2,
            'source_row_identity': 'SC-2002',
            'answer': 'no',
        },
    ]

    recovered_entries, output_schema = helpers['_normalize_model_generated_batch_entries'](
        prepared_rows,
        token_echo_mismatch_entries,
        run_id='run-token-recovery',
        batch_number=2,
    )

    assert output_schema == ['source_row_number', 'source_row_identity', 'answer']
    assert recovered_entries == [
        {'source_row_number': 1, 'source_row_identity': 'SC-2001', 'answer': 'yes'},
        {'source_row_number': 2, 'source_row_identity': 'SC-2002', 'answer': 'no'},
    ]

    try:
        helpers['_normalize_model_generated_batch_entries'](
            prepared_rows,
            [
                {
                    '__simplechat_source_row_token': 'model-made-up-token-1',
                    'source_row_number': 2,
                    'source_row_identity': 'SC-2002',
                    'answer': 'no',
                },
                {
                    '__simplechat_source_row_token': 'model-made-up-token-2',
                    'source_row_number': 1,
                    'source_row_identity': 'SC-2001',
                    'answer': 'yes',
                },
            ],
        )
    except ValueError as exc:
        assert 'token mismatch' in str(exc).lower()
    else:
        raise AssertionError('Explicit source row conflicts must not use positional recovery')


def test_model_batch_nested_csv_output_is_flattened_before_schema_inference():
    """Object responses that wrap one CSV row are expanded into final columns."""
    helpers = _load_contract_helpers()
    prepared_rows = helpers['_prepare_tabular_source_rows'](
        [
            {'transaction_id': 'BT-000001'},
            {'transaction_id': 'BT-000002'},
        ],
        start_row=0,
    )
    generated_entries = [
        {
            'transaction_id': 'BT-000001',
            'csv': (
                'transaction_id,transaction_summary,counterparty_classification\n'
                'BT-000001,"summary one","Treasury"'
            ),
        },
        {
            'transaction_id': 'BT-000002',
            'csv': (
                'transaction_id,transaction_summary,counterparty_classification\n'
                'BT-000002,"summary two","Bank-to-bank"'
            ),
        },
    ]

    recovered_entries, output_schema = helpers['_normalize_model_generated_batch_entries'](
        prepared_rows,
        generated_entries,
        run_id='run-nested-csv',
        batch_number=1,
    )

    assert output_schema == [
        'source_row_number',
        'source_row_identity',
        'transaction_id',
        'transaction_summary',
        'counterparty_classification',
    ]
    assert recovered_entries[0] == {
        'source_row_number': 1,
        'source_row_identity': 'BT-000001',
        'transaction_id': 'BT-000001',
        'transaction_summary': 'summary one',
        'counterparty_classification': 'Treasury',
    }
    assert 'csv' not in recovered_entries[0]


def test_model_batch_nested_csv_output_supports_arbitrary_csv_headers():
    """Nested CSV recovery is not tied to one source dataset or field set."""
    helpers = _load_contract_helpers()
    prepared_rows = helpers['_prepare_tabular_source_rows'](
        [
            {'case_id': 'CASE-001', 'department': 'Operations'},
            {'case_id': 'CASE-002', 'department': 'Support'},
        ],
        start_row=0,
    )
    expected_schema = [
        'source_row_number',
        'source_row_identity',
        'case_id',
        'quality_score',
        'next_step',
    ]
    generated_entries = [
        {
            'csv': (
                'case_id,quality_score,next_step\n'
                'CASE-001,high,"Escalate with notes"'
            ),
        },
        {
            'csv': (
                'case_id,quality_score,next_step\n'
                'CASE-002,medium,"Monitor until resolved"'
            ),
        },
    ]

    recovered_entries, output_schema = helpers['_normalize_model_generated_batch_entries'](
        prepared_rows,
        generated_entries,
        expected_output_schema=expected_schema,
        run_id='run-nested-csv-generic',
        batch_number=1,
    )

    assert output_schema == expected_schema
    assert recovered_entries == [
        {
            'source_row_number': 1,
            'source_row_identity': 'CASE-001',
            'case_id': 'CASE-001',
            'quality_score': 'high',
            'next_step': 'Escalate with notes',
        },
        {
            'source_row_number': 2,
            'source_row_identity': 'CASE-002',
            'case_id': 'CASE-002',
            'quality_score': 'medium',
            'next_step': 'Monitor until resolved',
        },
    ]
    assert all('csv' not in recovered_entry for recovered_entry in recovered_entries)


def test_durable_runner_enforces_row_contract():
    """Queueing, generation, and checkpointing must all enforce the shared contract."""
    queue_calls = _called_function_names(_get_function_node('queue_tabular_generated_output_run'))
    queue_source = ast.unparse(_get_function_node('queue_tabular_generated_output_run'))
    generation_calls = _called_function_names(_get_function_node('_generate_batch_entries'))
    checkpoint_source = ast.unparse(_get_function_node('_checkpoint_generated_batch_results'))
    process_source = ast.unparse(_get_function_node('process_tabular_generated_output_run'))

    assert '_prepare_tabular_source_rows' in queue_calls
    assert '_balance_tabular_source_batch_rows' in queue_calls
    assert "model_batch_budget['token_max_rows']" in queue_source
    assert "model_batch_budget['max_rows'] = source_descriptor['batch_max_rows']" in queue_source
    assert '_normalize_model_generated_batch_entries' in generation_calls
    assert "run['output_schema']" in checkpoint_source
    assert "run.get('output_schema')" in process_source
    assert 'window_end = window_start' in process_source
    assert process_source.index('_authorize_tabular_export_run_execution') < process_source.index(
        '_migrate_legacy_tabular_export_run'
    )
    resume_source = ast.unparse(_get_function_node('resume_tabular_generated_output_run'))
    assert resume_source.index('_authorize_tabular_export_run_execution') < resume_source.index('run.update')
    publish_source = ast.unparse(_get_function_node('_publish_structured_export_artifact'))
    assert publish_source.index('_write_ordered_output_stream') < publish_source.index(
        'upload_generated_analysis_artifact_stream_for_user'
    )
    complete_source = ast.unparse(_get_function_node('_complete_run'))
    assert complete_source.index('_publish_structured_export_artifact') < complete_source.index(
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


def test_filter_rows_pages_queue_full_3000_row_source_replay():
    """Incomplete filter pages queue one durable run from the full source descriptor."""
    candidate_helpers = _load_candidate_helpers()
    descriptor_builder = _load_query_descriptor_helper()
    invocations = [
        _build_filter_invocation(0, 60),
        _build_filter_invocation(60, 60),
    ]
    candidate = candidate_helpers['_build_tabular_generated_output_source_candidate'](
        invocations
    )
    queued_calls = []

    def queue_run(**kwargs):
        queued_calls.append(kwargs)
        return {
            'id': 'filter-run-3000',
            'row_count': kwargs['source_descriptor']['expected_row_count'],
            'batch_count': 50,
        }

    async def emit_thought(*args, **kwargs):
        return None

    class MixedSourceCancellationError(Exception):
        pass

    router = _load_generated_output_router({
        'MixedSourceCancellationError': MixedSourceCancellationError,
        '_build_failed_tabular_generated_output_metadata': lambda source, output_format, reason: {
            'status': 'failed',
            'status_detail': reason,
        },
        '_build_tabular_generated_output_candidate_diagnostics': lambda values: [],
        '_build_tabular_generated_output_input_row': lambda row, source_file_name=None: row,
        '_build_tabular_generated_output_query_descriptor': descriptor_builder,
        '_build_tabular_generated_output_row_batches': lambda rows, settings=None: [rows],
        '_build_tabular_generated_output_source_authorization': lambda source: source.get(
            'source_authorization'
        ),
        '_build_tabular_generated_output_source_candidate': lambda values: candidate,
        '_safe_int': lambda value: int(value or 0),
        'build_background_tabular_generated_output_metadata': lambda run: {
            'background_export': True,
            'export_run_id': run['id'],
            'row_count': run['row_count'],
        },
        'build_tabular_post_processing_activity_payload': lambda *args, **kwargs: {},
        'cancel_tabular_generated_output_run': lambda *args, **kwargs: None,
        'emit_tabular_post_processing_thought': emit_thought,
        'get_tabular_generated_output_format': lambda question: 'csv',
        'logging': logging,
        'log_event': lambda *args, **kwargs: None,
        'question_requests_tabular_generated_output': lambda question: True,
        'question_requests_tabular_structured_object_output': lambda question: True,
        'queue_tabular_generated_output_run': queue_run,
        'raise_if_mixed_source_cancelled': lambda *args, **kwargs: None,
        'should_queue_tabular_generated_output_background': lambda *args, **kwargs: True,
    })

    output_metadata = asyncio.run(router(
        user_question='For each row, answer each question and generate a CSV.',
        invocations=invocations,
        gpt_model='test-model',
        settings={},
        conversation_id='conversation-1',
        user_id='user-1',
    ))

    assert candidate['full_result_available'] is False
    assert candidate['row_count'] == 120
    assert candidate['total_matches'] == 3000
    assert len(queued_calls) == 1
    assert queued_calls[0]['row_batches'] is None
    queued_descriptor = queued_calls[0]['source_descriptor']
    assert queued_descriptor['source_function'] == 'filter_rows'
    assert queued_descriptor['expected_row_count'] == 3000
    assert queued_descriptor['batch_max_rows'] == 60
    assert output_metadata['background_export'] is True
    assert output_metadata['export_run_id'] == 'filter-run-3000'


def test_filter_rows_pages_queue_hierarchical_analysis_run():
    """Analysis-only row-scale requests queue the durable hierarchical analysis task."""
    candidate_helpers = _load_candidate_helpers()
    descriptor_builder = _load_query_descriptor_helper()
    invocations = [
        _build_filter_invocation(0, 60),
        _build_filter_invocation(60, 60),
    ]
    candidate = candidate_helpers['_build_tabular_generated_output_source_candidate'](
        invocations
    )
    queued_calls = []

    def queue_run(**kwargs):
        queued_calls.append(kwargs)
        return {
            'id': 'analysis-run-3000',
            'task_type': kwargs.get('task_type'),
            'output_format': kwargs.get('output_format'),
            'row_count': kwargs['source_descriptor']['expected_row_count'],
            'batch_count': 50,
        }

    async def emit_thought(*args, **kwargs):
        return None

    class MixedSourceCancellationError(Exception):
        pass

    router = _load_generated_output_router({
        'MixedSourceCancellationError': MixedSourceCancellationError,
        '_build_failed_tabular_generated_output_metadata': lambda source, output_format, reason: {
            'status': 'failed',
            'status_detail': reason,
        },
        '_build_tabular_generated_output_candidate_diagnostics': lambda values: [],
        '_build_tabular_generated_output_input_row': lambda row, source_file_name=None: row,
        '_build_tabular_generated_output_query_descriptor': descriptor_builder,
        '_build_tabular_generated_output_row_batches': lambda rows, settings=None: [rows],
        '_build_tabular_generated_output_source_authorization': lambda source: source.get(
            'source_authorization'
        ),
        '_build_tabular_generated_output_source_candidate': lambda values: candidate,
        '_safe_int': lambda value: int(value or 0),
        'build_background_tabular_generated_output_metadata': lambda run: {
            'background_export': True,
            'export_run_id': run['id'],
            'task_type': run['task_type'],
            'output_format': run['output_format'],
            'row_count': run['row_count'],
        },
        'build_tabular_post_processing_activity_payload': lambda *args, **kwargs: {},
        'cancel_tabular_generated_output_run': lambda *args, **kwargs: None,
        'emit_tabular_post_processing_thought': emit_thought,
        'get_tabular_generated_output_format': lambda question: None,
        'logging': logging,
        'log_event': lambda *args, **kwargs: None,
        'question_requests_tabular_generated_output': lambda question: False,
        'question_requests_tabular_hierarchical_analysis': lambda question: True,
        'question_requests_tabular_structured_object_output': lambda question: False,
        'queue_tabular_generated_output_run': queue_run,
        'raise_if_mixed_source_cancelled': lambda *args, **kwargs: None,
        'should_queue_tabular_generated_output_background': lambda *args, **kwargs: True,
    })

    output_metadata = asyncio.run(router(
        user_question='Summarize risk patterns across every row in this dataset.',
        invocations=invocations,
        gpt_model='test-model',
        settings={'enable_tabular_hierarchical_analysis': True},
        conversation_id='conversation-1',
        user_id='user-1',
    ))

    assert len(queued_calls) == 1
    assert queued_calls[0]['row_batches'] is None
    assert queued_calls[0]['task_type'] == 'hierarchical_analysis'
    assert queued_calls[0]['output_format'] == 'md'
    assert queued_calls[0]['analysis_objective'] == 'Summarize risk patterns across every row in this dataset.'
    assert queued_calls[0]['source_descriptor']['expected_row_count'] == 3000
    assert output_metadata['background_export'] is True
    assert output_metadata['task_type'] == 'hierarchical_analysis'


def test_filter_rows_pages_queue_combined_analysis_and_export_run():
    """Export plus analysis prompts queue one combined run over the replayable source."""
    candidate_helpers = _load_candidate_helpers()
    descriptor_builder = _load_query_descriptor_helper()
    invocations = [
        _build_filter_invocation(0, 60),
        _build_filter_invocation(60, 60),
    ]
    candidate = candidate_helpers['_build_tabular_generated_output_source_candidate'](
        invocations
    )
    queued_calls = []

    def queue_run(**kwargs):
        queued_calls.append(kwargs)
        return {
            'id': 'combined-run-3000',
            'task_type': kwargs.get('task_type'),
            'output_format': kwargs.get('output_format'),
            'row_count': kwargs['source_descriptor']['expected_row_count'],
            'batch_count': 50,
        }

    async def emit_thought(*args, **kwargs):
        return None

    class MixedSourceCancellationError(Exception):
        pass

    router = _load_generated_output_router({
        'MixedSourceCancellationError': MixedSourceCancellationError,
        '_build_failed_tabular_generated_output_metadata': lambda source, output_format, reason: {
            'status': 'failed',
            'status_detail': reason,
        },
        '_build_tabular_generated_output_candidate_diagnostics': lambda values: [],
        '_build_tabular_generated_output_input_row': lambda row, source_file_name=None: row,
        '_build_tabular_generated_output_query_descriptor': descriptor_builder,
        '_build_tabular_generated_output_row_batches': lambda rows, settings=None: [rows],
        '_build_tabular_generated_output_source_authorization': lambda source: source.get(
            'source_authorization'
        ),
        '_build_tabular_generated_output_source_candidate': lambda values: candidate,
        '_safe_int': lambda value: int(value or 0),
        'build_background_tabular_generated_output_metadata': lambda run: {
            'background_export': True,
            'export_run_id': run['id'],
            'task_type': run['task_type'],
            'output_format': run['output_format'],
            'row_count': run['row_count'],
        },
        'build_tabular_post_processing_activity_payload': lambda *args, **kwargs: {},
        'cancel_tabular_generated_output_run': lambda *args, **kwargs: None,
        'emit_tabular_post_processing_thought': emit_thought,
        'get_tabular_generated_output_format': lambda question: 'csv',
        'logging': logging,
        'log_event': lambda *args, **kwargs: None,
        'question_requests_tabular_generated_output': lambda question: True,
        'question_requests_tabular_hierarchical_analysis': lambda question: True,
        'question_requests_tabular_structured_object_output': lambda question: True,
        'queue_tabular_generated_output_run': queue_run,
        'raise_if_mixed_source_cancelled': lambda *args, **kwargs: None,
        'should_queue_tabular_generated_output_background': lambda *args, **kwargs: True,
    })

    output_metadata = asyncio.run(router(
        user_question='For each row, answer each question, generate a CSV, and summarize risk patterns.',
        invocations=invocations,
        gpt_model='test-model',
        settings={'enable_tabular_hierarchical_analysis': True},
        conversation_id='conversation-1',
        user_id='user-1',
    ))

    assert len(queued_calls) == 1
    assert queued_calls[0]['row_batches'] is None
    assert queued_calls[0]['task_type'] == 'combined'
    assert queued_calls[0]['output_format'] == 'csv'
    assert queued_calls[0]['analysis_objective'] == (
        'For each row, answer each question, generate a CSV, and summarize risk patterns.'
    )
    assert queued_calls[0]['source_descriptor']['expected_row_count'] == 3000
    assert output_metadata['background_export'] is True
    assert output_metadata['task_type'] == 'combined'


def test_downloadable_complete_csv_request_uses_shared_artifact_intent():
    """Downloadable CSV wording must not bypass durable tabular routing."""
    helpers = _load_tabular_request_intent_helpers()
    user_question = """
    Do per-row analysis of the complete selected CSV file.
    Analyze every source item independently and produce exactly one output row for each source row.
    Produce exactly these columns in this order: Item_ID, Timeline_Status, Overall_Attention.
    Process all source rows and preserve source-row order.
    Create one complete downloadable CSV containing all result rows.
    """

    assert helpers['get_tabular_generated_output_format'](user_question) == 'csv'
    assert helpers['question_requests_tabular_generated_output'](user_question) is True


def test_durable_tabular_descriptor_supports_all_configured_formats():
    """Version-pinned replay descriptors cover CSV and every supported workbook type."""
    descriptor_builder = _load_tabular_descriptor_builder()

    class FakeDescriptorPlugin:
        SUPPORTED_EXTENSIONS = ('.csv', '.xls', '.xlsm', '.xlsx')

        @staticmethod
        def _infer_source_from_container(container_name):
            assert container_name == 'user-documents'
            return 'workspace'

        @staticmethod
        def _get_tabular_blob_version(*args, **kwargs):
            raise AssertionError('The supplied version pin must be used')

    plugin = FakeDescriptorPlugin()
    for source_format in ('csv', 'xlsx', 'xls', 'xlsm'):
        is_workbook = source_format != 'csv'
        descriptor = descriptor_builder(
            plugin,
            container_name='user-documents',
            blob_path=f'user-1/source.{source_format}',
            filename=f'source.{source_format}',
            query_expression='index == index',
            expected_row_count=12,
            blob_version={'blob_etag': 'etag-12', 'blob_size': 2048},
            sheet_names=['First', 'Second'] if is_workbook else None,
        )

        assert descriptor['source_format'] == source_format
        assert descriptor['expected_row_count'] == 12
        assert descriptor['blob_etag'] == 'etag-12'
        if is_workbook:
            assert descriptor['sheet_names'] == ['First', 'Second']
        else:
            assert 'sheet_names' not in descriptor


def test_durable_workbook_replay_preserves_sheet_order_and_resume_position():
    """Workbook rows replay in sheet order and resume after the last staged physical row."""
    class FakeWorkbookPlugin:
        def __init__(self):
            self.frames = {
                'First': pandas.DataFrame([
                    {'Item_ID': 'A-1', 'Value': 'one'},
                    {'Item_ID': 'A-2', 'Value': 'two'},
                ]),
                'Second': pandas.DataFrame([
                    {'Item_ID': 'B-1', 'Value': 'three'},
                ]),
            }

        @staticmethod
        def _parse_optional_column_list_argument(value):
            assert value is None
            return None

        def _read_tabular_blob_to_dataframe(self, container, blob_path, sheet_name, require_explicit_sheet):
            assert container == 'user-documents'
            assert blob_path == 'user-1/source.xlsx'
            assert require_explicit_sheet is True
            return self.frames[sheet_name].copy()

        @staticmethod
        def _try_numeric_conversion(dataframe):
            return dataframe

        @staticmethod
        def _apply_query_expression_with_fallback(dataframe, query_expression, normalize_match):
            assert query_expression == 'index == index'
            assert normalize_match is False
            return dataframe.query(query_expression), False

        @staticmethod
        def _build_row_output_records(dataframe, selected_columns):
            return dataframe[selected_columns].to_dict(orient='records')

    version_checks = []
    replay_rows = _load_tabular_source_replay_helper(FakeWorkbookPlugin(), version_checks)
    descriptor = {
        'container': 'user-documents',
        'blob_path': 'user-1/source.xlsx',
        'blob_etag': 'etag-source',
        'query_expression': 'index == index',
        'return_columns': None,
        'sheet_names': ['First', 'Second'],
    }

    all_rows = list(replay_rows(descriptor, 'xlsx', 1000, 0))
    resumed_rows = list(replay_rows(descriptor, 'xlsx', 1000, 2))

    assert [source_row_number for source_row_number, _ in all_rows] == [1, 2, 3]
    assert [row['Item_ID'] for _, row in all_rows] == ['A-1', 'A-2', 'B-1']
    assert resumed_rows == [(3, {'Item_ID': 'B-1', 'Value': 'three'})]
    assert len(version_checks) == 4


def test_direct_source_backed_queue_supports_all_workbook_formats():
    """Selected XLSX, XLS, and XLSM files use the same direct durable route as CSV."""
    original_module = sys.modules.get('semantic_kernel_plugins.tabular_processing_plugin')
    fake_module = ModuleType('semantic_kernel_plugins.tabular_processing_plugin')

    class FakeWorkbookPlugin:
        def _resolve_blob_location_with_fallback(self, user_id, conversation_id, filename, source, **kwargs):
            assert user_id == 'user-1'
            assert conversation_id == 'conversation-1'
            assert source == 'workspace'
            return 'user-documents', f'user-1/{filename}'

        @staticmethod
        def _get_workbook_metadata(container_name, blob_path):
            return {'is_workbook': True, 'sheet_names': ['First', 'Second']}

        @staticmethod
        def _read_tabular_blob_to_dataframe(*args, sheet_name=None, **kwargs):
            return pandas.DataFrame([
                {'item_id': f'{sheet_name}-1', 'value': 'first'},
                {'item_id': f'{sheet_name}-2', 'value': 'second'},
            ])

        @staticmethod
        def _try_numeric_conversion(dataframe):
            return dataframe

        @staticmethod
        def _apply_query_expression_with_fallback(dataframe, **kwargs):
            return dataframe, False

        @staticmethod
        def _build_row_output_records(dataframe, selected_columns):
            return dataframe[selected_columns].to_dict(orient='records')

        @staticmethod
        def _get_tabular_blob_version(*args, **kwargs):
            return {'blob_etag': 'etag-workbook', 'blob_size': 4096}

        @staticmethod
        def _build_generated_export_query_descriptor_from_location(**kwargs):
            return {
                'version': 1,
                'kind': 'query_tabular_data',
                'source': 'workspace',
                'container': kwargs['container_name'],
                'blob_path': kwargs['blob_path'],
                'blob_etag': kwargs['blob_version']['blob_etag'],
                'filename': kwargs['filename'],
                'source_format': kwargs['filename'].rsplit('.', 1)[-1],
                'query_expression': kwargs['query_expression'],
                'return_columns': kwargs['return_columns'],
                'expected_row_count': kwargs['expected_row_count'],
                'selected_sheet': kwargs['selected_sheet'],
                'sheet_names': kwargs['sheet_names'],
            }

        @staticmethod
        def _build_source_authorization_from_location(container_name, blob_path, blob_version):
            return {
                'source': 'workspace',
                'container': container_name,
                'blob_path': blob_path,
                'blob_etag': blob_version['blob_etag'],
            }

    fake_module.TabularProcessingPlugin = FakeWorkbookPlugin
    sys.modules['semantic_kernel_plugins.tabular_processing_plugin'] = fake_module
    queued_runs = []
    log_events = []
    try:
        helpers = _load_direct_source_queue_helpers({
            '_safe_int': lambda value: int(value or 0),
            '_get_tabular_generated_output_batch_budget': lambda settings=None: {
                'max_rows': 60,
                'max_chars': 60000,
            },
            '_get_tabular_generated_output_task_type': lambda *args, **kwargs: None,
            'question_requests_tabular_generated_output': lambda question: True,
            'question_requests_tabular_hierarchical_analysis': lambda question: False,
            'get_tabular_generated_output_format': lambda question: 'csv',
            'dedupe_tabular_file_contexts': lambda contexts=None: list(contexts or []),
            'raise_if_mixed_source_cancelled': lambda *args, **kwargs: None,
            'queue_tabular_generated_output_run': lambda **kwargs: queued_runs.append(kwargs) or {
                'id': f'run-{len(queued_runs)}',
                'row_count': kwargs['source_descriptor']['expected_row_count'],
                'batch_count': 1,
            },
            'build_background_tabular_generated_output_metadata': lambda run: {
                'background_export': True,
                'export_run_id': run['id'],
                'row_count': run['row_count'],
            },
            'build_tabular_post_processing_activity_payload': lambda *args, **kwargs: {},
            '_build_failed_tabular_generated_output_metadata': lambda *args: {
                'status': 'failed',
            },
            'logging': logging,
            'log_event': lambda *args, **kwargs: log_events.append((args, kwargs)),
        })
        for source_format in ('xlsx', 'xls', 'xlsm'):
            output_metadata = helpers['maybe_queue_direct_tabular_generated_output'](
                user_question='Create one complete downloadable CSV for every source row.',
                file_contexts=[{
                    'file_name': f'source.{source_format}',
                    'source_hint': 'workspace',
                }],
                user_id='user-1',
                conversation_id='conversation-1',
                gpt_model='test-model',
                settings={},
            )
            assert output_metadata.get('background_export') is True, log_events
    finally:
        if original_module is None:
            sys.modules.pop('semantic_kernel_plugins.tabular_processing_plugin', None)
        else:
            sys.modules['semantic_kernel_plugins.tabular_processing_plugin'] = original_module

    assert len(queued_runs) == 3
    assert [run['source_descriptor']['source_format'] for run in queued_runs] == [
        'xlsx',
        'xls',
        'xlsm',
    ]
    assert all(
        run['source_descriptor']['sheet_names'] == ['First', 'Second']
        for run in queued_runs
    )


def test_direct_source_backed_csv_queue_bypasses_tool_paging():
    """Explicit exhaustive CSV prompts queue directly from one authorized source blob."""
    original_module = sys.modules.get('semantic_kernel_plugins.tabular_processing_plugin')
    fake_module = ModuleType('semantic_kernel_plugins.tabular_processing_plugin')

    class FakePluginResult(str):
        def __new__(cls, value, internal_metadata=None):
            instance = super().__new__(cls, value)
            instance.internal_metadata = internal_metadata or {}
            return instance

    class FakeTabularProcessingPlugin:
        def _resolve_blob_location_with_fallback(self, user_id, conversation_id, filename, source, group_id=None, public_workspace_id=None):
            assert user_id == 'user-1'
            assert conversation_id == 'conversation-1'
            assert filename == 'bank_treasury_operations_dataset-3000.csv'
            assert source == 'workspace'
            assert group_id is None
            assert public_workspace_id is None
            return 'user-documents', 'user-1/bank_treasury_operations_dataset-3000.csv'

        def _query_csv_data_in_bounded_chunks(self, container_name, blob_path, filename, query_expression, return_columns, start_row, max_rows):
            assert container_name == 'user-documents'
            assert blob_path == 'user-1/bank_treasury_operations_dataset-3000.csv'
            assert filename == 'bank_treasury_operations_dataset-3000.csv'
            assert query_expression == 'index == index'
            assert return_columns is None
            assert start_row == 0
            assert max_rows == 5
            return FakePluginResult(
                json.dumps({'total_matches': 3000, 'data': [{'transaction_id': 'BT-000001'}]}),
                internal_metadata={
                    'tabular_generated_export_source': {
                        'version': 1,
                        'kind': 'query_tabular_data',
                        'source_function': 'query_tabular_data',
                        'source': 'workspace',
                        'scope_id': None,
                        'container': container_name,
                        'blob_path': blob_path,
                        'blob_etag': 'etag-3000',
                        'filename': filename,
                        'query_expression': query_expression,
                        'return_columns': return_columns,
                        'expected_row_count': 3000,
                    },
                    'tabular_source_authorization': {
                        'source': 'workspace',
                        'scope_id': None,
                        'container': container_name,
                        'blob_path': blob_path,
                        'blob_etag': 'etag-3000',
                    },
                },
            )

    fake_module.TabularProcessingPlugin = FakeTabularProcessingPlugin
    sys.modules['semantic_kernel_plugins.tabular_processing_plugin'] = fake_module
    queued_runs = []
    thought_payloads = []

    try:
        helpers = _load_direct_source_queue_helpers({
            '_safe_int': lambda value: int(value or 0),
            '_get_tabular_generated_output_batch_budget': lambda settings=None: {
                'max_rows': 60,
                'max_chars': 60000,
            },
            '_get_tabular_generated_output_task_type': (
                lambda generated, analysis, settings, action_mode=None:
                'combined' if generated and analysis else None
            ),
            'question_requests_tabular_generated_output': lambda question: True,
            'question_requests_tabular_hierarchical_analysis': lambda question: True,
            'get_tabular_generated_output_format': lambda question: 'csv',
            'dedupe_tabular_file_contexts': lambda contexts=None: list(contexts or []),
            'raise_if_mixed_source_cancelled': lambda *args, **kwargs: None,
            'queue_tabular_generated_output_run': lambda **kwargs: queued_runs.append(kwargs) or {
                'id': 'direct-run-3000',
                'task_type': kwargs.get('task_type'),
                'output_format': kwargs.get('output_format'),
                'row_count': kwargs['source_descriptor']['expected_row_count'],
                'batch_count': 50,
            },
            'build_background_tabular_generated_output_metadata': lambda run: {
                'background_export': True,
                'export_run_id': run['id'],
                'task_type': run['task_type'],
                'output_format': run['output_format'],
                'row_count': run['row_count'],
            },
            'build_tabular_post_processing_activity_payload': lambda *args, **kwargs: {
                'phase': kwargs.get('phase'),
            },
            'logging': logging,
            'log_event': lambda *args, **kwargs: None,
        })

        output_metadata = helpers['maybe_queue_direct_tabular_generated_output'](
            user_question='For each row, answer each question, generate a CSV, and summarize risk patterns.',
            file_contexts=[{
                'file_name': 'bank_treasury_operations_dataset-3000.csv',
                'source_hint': 'workspace',
            }],
            user_id='user-1',
            conversation_id='conversation-1',
            gpt_model='test-model',
            settings={},
            thought_callback=lambda payload: thought_payloads.append(payload),
            model_context={'endpoint_id': 'model-1'},
        )
    finally:
        if original_module is None:
            sys.modules.pop('semantic_kernel_plugins.tabular_processing_plugin', None)
        else:
            sys.modules['semantic_kernel_plugins.tabular_processing_plugin'] = original_module

    assert len(queued_runs) == 1
    queued_run = queued_runs[0]
    assert queued_run['row_batches'] is None
    assert queued_run['task_type'] == 'combined'
    assert queued_run['output_format'] == 'csv'
    assert queued_run['analysis_objective'].startswith('For each row')
    assert queued_run['source_descriptor']['expected_row_count'] == 3000
    assert queued_run['source_descriptor']['batch_max_rows'] == 60
    assert output_metadata['background_export'] is True
    assert output_metadata['task_type'] == 'combined'
    assert thought_payloads
    assert 'run_id=direct-run-3000' in thought_payloads[0]['detail']


def test_direct_source_backed_queue_failure_suppresses_inline_exhaustive_output():
    """Artifact queue failures return safe metadata instead of dumping rows into chat."""
    original_module = sys.modules.get('semantic_kernel_plugins.tabular_processing_plugin')
    fake_module = ModuleType('semantic_kernel_plugins.tabular_processing_plugin')

    class FakeTabularProcessingPlugin:
        def _resolve_blob_location_with_fallback(self, *args, **kwargs):
            raise RuntimeError('simulated credential challenge')

    fake_module.TabularProcessingPlugin = FakeTabularProcessingPlugin
    sys.modules['semantic_kernel_plugins.tabular_processing_plugin'] = fake_module
    logged_events = []
    queued_runs = []

    try:
        helpers = _load_direct_source_queue_helpers({
            '_safe_int': lambda value: int(value or 0),
            '_get_tabular_generated_output_batch_budget': lambda settings=None: {
                'max_rows': 60,
                'max_chars': 60000,
            },
            '_get_tabular_generated_output_task_type': (
                lambda generated, analysis, settings, action_mode=None: None
            ),
            'question_requests_tabular_generated_output': lambda question: True,
            'question_requests_tabular_hierarchical_analysis': lambda question: False,
            'get_tabular_generated_output_format': lambda question: 'csv',
            'dedupe_tabular_file_contexts': lambda contexts=None: list(contexts or []),
            'raise_if_mixed_source_cancelled': lambda *args, **kwargs: None,
            'queue_tabular_generated_output_run': lambda **kwargs: queued_runs.append(kwargs),
            'build_background_tabular_generated_output_metadata': lambda run: run,
            'build_tabular_post_processing_activity_payload': lambda *args, **kwargs: {},
            '_build_failed_tabular_generated_output_metadata': lambda source, output_format, reason: {
                'background_export': True,
                'status': 'failed',
                'output_format': output_format,
                'source_file_name': source.get('filename'),
                'status_detail': reason,
                'suppress_assistant_table_export': True,
            },
            'logging': logging,
            'log_event': lambda *args, **kwargs: logged_events.append((args, kwargs)),
        })

        output_metadata = helpers['maybe_queue_direct_tabular_generated_output'](
            user_question='For each row, answer each question and generate a CSV.',
            file_contexts=[{
                'file_name': 'interior_resource_operations_dataset-30000.csv',
                'source_hint': 'workspace',
            }],
            user_id='user-1',
            conversation_id='conversation-1',
            gpt_model='test-model',
            settings={},
        )
    finally:
        if original_module is None:
            sys.modules.pop('semantic_kernel_plugins.tabular_processing_plugin', None)
        else:
            sys.modules['semantic_kernel_plugins.tabular_processing_plugin'] = original_module

    assert output_metadata['status'] == 'failed'
    assert output_metadata['background_export'] is True
    assert output_metadata['suppress_assistant_table_export'] is True
    assert output_metadata['source_file_name'] == 'interior_resource_operations_dataset-30000.csv'
    assert 'No inline row output was generated' in output_metadata['status_detail']
    assert queued_runs == []
    assert any(
        args and args[0] == '[TABULAR_GENERATED_OUTPUT] Direct source-backed generated output queueing skipped'
        for args, _kwargs in logged_events
    )


def test_direct_source_backed_queue_call_sites_use_required_keywords():
    """Every Search queue call site passes required arguments explicitly."""
    module_tree = ast.parse(CHAT_ROUTE.read_text(encoding='utf-8'), filename=str(CHAT_ROUTE))
    search_queue_calls = [
        call
        for call in ast.walk(module_tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == 'maybe_queue_search_tabular_generated_output'
    ]
    direct_queue_calls = [
        call
        for call in ast.walk(module_tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == 'maybe_queue_direct_tabular_generated_output'
    ]
    assert len(search_queue_calls) >= 4
    assert len(direct_queue_calls) >= 1

    required_keyword_names = {
        'user_question',
        'file_contexts',
        'user_id',
        'conversation_id',
        'gpt_model',
        'settings',
    }
    for call in search_queue_calls + direct_queue_calls:
        keyword_names = {
            keyword.arg
            for keyword in call.keywords
            if keyword.arg
        }
        assert required_keyword_names <= keyword_names


def test_model_validation_failures_auto_retry_then_manual_continue():
    """Model-output validation failures auto retry briefly, then remain manually resumable."""
    helpers, stored_run = _load_retry_helpers()
    settings = {
        'tabular_generated_output_model_validation_auto_retries': 3,
    }
    run = {
        'id': 'validation-run',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'status': 'running',
        'completed_batches': 1,
        'processed_rows': 33,
        'batch_count': 91,
        'row_count': 3000,
        '_etag': 'etag-1',
    }
    validation_error = ValueError(
        'Background structured export batch 2/91 failed validation: returned 0 object(s) for 33 input row(s).'
    )

    first_retry = helpers['_mark_run_retryable'](
        dict(run),
        validation_error,
        settings,
        retry_category='model_validation',
    )
    assert first_retry['status'] == 'queued'
    assert first_retry['transient_failure_count'] == 1
    assert first_retry['last_retry_category'] == 'model_validation'
    assert first_retry['auto_retry_exhausted'] is False
    assert first_retry['next_attempt_at']

    exhausted_run = dict(first_retry)
    exhausted_run.update({
        'status': 'running',
        'transient_failure_count': 3,
        '_etag': 'etag-2',
    })
    exhausted_retry = helpers['_mark_run_retryable'](
        exhausted_run,
        validation_error,
        settings,
        retry_category='model_validation',
    )
    assert exhausted_retry['status'] == 'failed'
    assert exhausted_retry['auto_retry_exhausted'] is True
    assert exhausted_retry['last_retry_category'] == 'model_validation'
    assert helpers['_is_retryable_failed_run'](stored_run) is True
    assert helpers['_can_auto_retry_failed_run'](stored_run, settings) is False

    exhausted_batch_run = {
        'status': 'failed',
        'last_retry_category': 'batch_exhausted',
        'exhausted_batch_count': 1,
    }
    assert helpers['_has_exhausted_independent_batch_retries'](exhausted_batch_run) is True
    assert helpers['_can_resume_run'](exhausted_batch_run, settings) is True


def test_hierarchical_analysis_routing_requires_feature_flag():
    """Lane C queueing stays behind the feature flag until scale hardening completes."""
    candidate_helpers = _load_candidate_helpers()
    descriptor_builder = _load_query_descriptor_helper()
    candidate = candidate_helpers['_build_tabular_generated_output_source_candidate']([
        _build_filter_invocation(0, 60),
    ])
    queued_calls = []

    class MixedSourceCancellationError(Exception):
        pass

    router = _load_generated_output_router({
        'MixedSourceCancellationError': MixedSourceCancellationError,
        '_build_failed_tabular_generated_output_metadata': lambda source, output_format, reason: {
            'status': 'failed',
            'status_detail': reason,
        },
        '_build_tabular_generated_output_candidate_diagnostics': lambda values: [],
        '_build_tabular_generated_output_input_row': lambda row, source_file_name=None: row,
        '_build_tabular_generated_output_query_descriptor': descriptor_builder,
        '_build_tabular_generated_output_row_batches': lambda rows, settings=None: [rows],
        '_build_tabular_generated_output_source_authorization': lambda source: source.get(
            'source_authorization'
        ),
        '_build_tabular_generated_output_source_candidate': lambda values: candidate,
        '_safe_int': lambda value: int(value or 0),
        'build_background_tabular_generated_output_metadata': lambda run: run,
        'build_tabular_post_processing_activity_payload': lambda *args, **kwargs: {},
        'cancel_tabular_generated_output_run': lambda *args, **kwargs: None,
        'emit_tabular_post_processing_thought': lambda *args, **kwargs: None,
        'get_tabular_generated_output_format': lambda question: None,
        'logging': logging,
        'log_event': lambda *args, **kwargs: None,
        'question_requests_tabular_generated_output': lambda question: False,
        'question_requests_tabular_hierarchical_analysis': lambda question: True,
        'question_requests_tabular_structured_object_output': lambda question: False,
        'queue_tabular_generated_output_run': lambda **kwargs: queued_calls.append(kwargs),
        'raise_if_mixed_source_cancelled': lambda *args, **kwargs: None,
        'should_queue_tabular_generated_output_background': lambda *args, **kwargs: True,
    })

    output_metadata = asyncio.run(router(
        user_question='Analyze every row and summarize patterns.',
        invocations=[],
        gpt_model='test-model',
        settings={},
        conversation_id='conversation-1',
        user_id='user-1',
    ))

    assert output_metadata is None
    assert queued_calls == []


def test_non_replayable_filter_rows_reports_explicit_failure():
    """Normalized filter semantics fail closed with a user-visible reason."""
    candidate_helpers = _load_candidate_helpers()
    descriptor_builder = _load_query_descriptor_helper()
    replay_error = (
        'filter_rows with normalize_match=true cannot be replayed equivalently '
        'by the row-local CSV engine'
    )
    invocations = [
        _build_filter_invocation(0, 60, replay_error=replay_error),
    ]
    candidate = candidate_helpers['_build_tabular_generated_output_source_candidate'](
        invocations
    )
    queued_calls = []

    async def emit_thought(*args, **kwargs):
        return None

    class MixedSourceCancellationError(Exception):
        pass

    router = _load_generated_output_router({
        'MixedSourceCancellationError': MixedSourceCancellationError,
        '_build_failed_tabular_generated_output_metadata': lambda source, output_format, reason: {
            'status': 'failed',
            'status_detail': reason,
        },
        '_build_tabular_generated_output_candidate_diagnostics': lambda values: [],
        '_build_tabular_generated_output_input_row': lambda row, source_file_name=None: row,
        '_build_tabular_generated_output_query_descriptor': descriptor_builder,
        '_build_tabular_generated_output_row_batches': lambda rows, settings=None: [rows],
        '_build_tabular_generated_output_source_authorization': lambda source: source.get(
            'source_authorization'
        ),
        '_build_tabular_generated_output_source_candidate': lambda values: candidate,
        '_safe_int': lambda value: int(value or 0),
        'build_background_tabular_generated_output_metadata': lambda run: run,
        'build_tabular_post_processing_activity_payload': lambda *args, **kwargs: {},
        'cancel_tabular_generated_output_run': lambda *args, **kwargs: None,
        'emit_tabular_post_processing_thought': emit_thought,
        'get_tabular_generated_output_format': lambda question: 'csv',
        'logging': logging,
        'log_event': lambda *args, **kwargs: None,
        'question_requests_tabular_generated_output': lambda question: True,
        'question_requests_tabular_structured_object_output': lambda question: True,
        'queue_tabular_generated_output_run': lambda **kwargs: queued_calls.append(kwargs),
        'raise_if_mixed_source_cancelled': lambda *args, **kwargs: None,
        'should_queue_tabular_generated_output_background': lambda *args, **kwargs: True,
    })

    output_metadata = asyncio.run(router(
        user_question='For every row, answer the question and generate a CSV.',
        invocations=invocations,
        gpt_model='test-model',
        settings={},
        conversation_id='conversation-1',
        user_id='user-1',
    ))

    assert not queued_calls
    assert output_metadata['status'] == 'failed'
    assert 'normalize_match=true' in output_metadata['status_detail']
    assert 'No partial CSV was created' in output_metadata['status_detail']


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


def test_scale_fixture_generator_streams_all_required_tiers():
    """Synthetic scale fixtures cover every required tier without list materialization."""
    assert tuple(SCALE_TIERS) == (30, 300, 3000, 30000, 100000)

    for row_tier in SCALE_TIERS:
        generated_count = 0
        first_row = None
        last_row = None
        for generated_row in iter_synthetic_rows(row_tier):
            generated_count += 1
            first_row = first_row or generated_row
            last_row = generated_row

        assert generated_count == row_tier
        assert first_row['Case ID'] == 'SC-000001'
        assert last_row['Case ID'] == f'SC-{row_tier:06d}'
        assert set(first_row) == {'Case ID', 'Score', 'Risk', 'Question'}


def test_scale_tiers_plan_export_and_analysis_with_bounded_manifests():
    """All required tiers keep Lane B and Lane C planning metadata bounded."""
    manifest_helpers, uploaded_pages = _load_manifest_helpers()
    analysis_helpers = _load_analysis_helpers()
    batch_size = 50
    reduce_fan_in = analysis_helpers['_get_tabular_analysis_reduce_fan_in']({
        'tabular_hierarchical_analysis_reduce_fan_in': 25,
    })

    for row_tier in SCALE_TIERS:
        batch_count = math.ceil(row_tier / batch_size)
        chunk_row_counts = [batch_size] * batch_count
        remainder = row_tier % batch_size
        if remainder:
            chunk_row_counts[-1] = remainder

        manifest = manifest_helpers['_write_chunk_manifest_for_run'](
            'user-1',
            'conversation-1',
            f'run-tier-{row_tier}',
            batch_count,
            row_count=row_tier,
            chunk_row_counts=chunk_row_counts,
            chunk_status='staged',
        )
        export_plan = {
            'lane': 'structured_export',
            'row_count': row_tier,
            'batch_count': batch_count,
            'chunk_manifest': manifest,
        }
        analysis_plan = {
            'lane': 'hierarchical_analysis',
            'row_count': row_tier,
            'batch_count': batch_count,
            'reduce_plan': analysis_helpers['_build_analysis_reduce_plan'](batch_count, reduce_fan_in),
            'chunk_manifest': manifest,
        }
        serialized_run_document = json.dumps(
            {
                'id': f'run-tier-{row_tier}',
                'type': 'tabular_generated_output_run',
                'contract_version': 3,
                'task_type': export_plan['lane'],
                'row_count': row_tier,
                'batch_count': batch_count,
                'chunk_manifest': manifest,
            },
            separators=(',', ':'),
            ensure_ascii=False,
        ).encode('utf-8')

        assert len(serialized_run_document) < 16 * 1024
        assert 'chunks' not in manifest
        assert export_plan['batch_count'] == analysis_plan['batch_count']
        assert max(chunk_row_counts) <= batch_size
        assert sum(chunk_row_counts) == row_tier
        reduce_groups = analysis_helpers['_build_analysis_reduce_groups'](
            list(range(batch_count)),
            reduce_fan_in,
        )
        assert all(len(group) <= reduce_fan_in for group in reduce_groups)

    max_manifest_page_size = max(
        len(json.dumps(page, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
        for page in uploaded_pages.values()
    )
    assert max_manifest_page_size < 128 * 1024


def test_100000_row_hardening_contracts_revalidate_source_and_cancel_terminally():
    """The largest tier keeps source-version, authorization, and cancel contracts explicit."""
    source_version_source = ast.unparse(_get_function_node('_get_versioned_source_blob_client'))
    staging_source = ast.unparse(_get_function_node('_stage_tabular_generated_output_source'))
    replay_source = ast.unparse(_get_function_node('_iter_versioned_tabular_source_rows'))
    assert 'blob_etag' in source_version_source
    assert 'Source CSV changed after the export was queued' in source_version_source
    assert '_iter_versioned_tabular_source_rows' in staging_source
    assert 'MatchConditions.IfNotModified' in replay_source
    assert 'source_scan_row_count' in staging_source

    authorize_personal = _load_authorization_helper('user-1')
    large_run = {
        'id': 'run-100000-auth',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'row_count': 100000,
        'batch_count': 2000,
        'source_descriptor': {
            'source': 'chat',
            'container': 'personal-chat',
            'blob_path': 'user-1/conversation-1/source-100000.csv',
            'blob_etag': 'etag-100000',
        },
    }
    assert authorize_personal(large_run)['user_id'] == 'user-1'

    helpers, stored_run = _load_cancellation_helpers({
        'id': 'run-100000-cancel',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'status': 'running',
        'row_count': 100000,
        'batch_count': 2000,
        'completed_batches': 1500,
        'processed_rows': 75000,
    })
    cancel_result = helpers['cancel_tabular_generated_output_run']('user-1', 'run-100000-cancel')
    assert cancel_result['success'] is True
    assert stored_run['status'] == 'canceled'
    assert stored_run['completed_at']
    assert helpers['_can_cancel_run'](stored_run) is False
    assert cancel_result['run']['can_cancel'] is False


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

    staged_chat_run = {
        'id': 'run-staged-chat',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'source_authorization': {
            'source': 'chat',
        },
    }
    assert authorize_personal(staged_chat_run)['user_id'] == 'user-1'

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


def test_chunk_manifest_contract_stays_compact_at_100000_rows():
    """Large run manifests keep chunk entries outside the Cosmos run document."""
    helpers, uploaded_pages = _load_manifest_helpers()

    manifest = helpers['_write_chunk_manifest_for_run'](
        'user-1',
        'conversation-1',
        'run-100000',
        2000,
        row_count=100000,
        estimated_rows_per_chunk=50,
        chunk_status='pending_source_staging',
    )
    run_document = {
        'id': 'run-100000',
        'type': 'tabular_generated_output_run',
        'contract_version': 3,
        'task_type': 'structured_export',
        'analysis_objective': '',
        'row_count': 100000,
        'batch_count': 2000,
        'total_chunk_count': manifest['total_chunk_count'],
        'processed_chunk_count': 0,
        'failed_chunk_count': 0,
        'chunk_manifest': manifest,
    }
    safe_cosmos_document_threshold = 16 * 1024
    serialized_run_document = json.dumps(
        run_document,
        separators=(',', ':'),
        ensure_ascii=False,
    ).encode('utf-8')

    assert len(serialized_run_document) < safe_cosmos_document_threshold
    assert 'chunks' not in run_document['chunk_manifest']
    assert manifest['page_count'] == 8
    assert len(uploaded_pages) == 8

    first_page = uploaded_pages[
        'user-1/conversation-1/generated/tabular_runs/run-100000/manifest/chunks/page_000001.json'
    ]
    last_page = uploaded_pages[
        'user-1/conversation-1/generated/tabular_runs/run-100000/manifest/chunks/page_000008.json'
    ]
    assert first_page['chunk_index_start'] == 1
    assert len(first_page['chunks']) == 250
    assert first_page['chunks'][0]['source_row_start'] == 1
    assert first_page['chunks'][0]['source_row_end'] == 50
    assert last_page['chunk_index_end'] == 2000
    assert last_page['chunks'][-1]['source_row_end'] == 100000

    max_manifest_page_size = max(
        len(json.dumps(page, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
        for page in uploaded_pages.values()
    )
    assert max_manifest_page_size < 128 * 1024


def test_hierarchical_analysis_summary_contract_and_recursive_reduce():
    """Analysis summaries preserve row evidence and reduce recursively under fan-in caps."""
    helpers = _load_analysis_helpers()
    source_rows = [
        {
            '__simplechat_source_row_number': 1,
            '__simplechat_source_row_identity': 'SC-1',
            'risk': 'low',
        },
        {
            '__simplechat_source_row_number': 2,
            '__simplechat_source_row_identity': 'SC-2',
            'risk': 'high',
        },
    ]
    chunk_summary = helpers['_normalize_analysis_summary_payload'](
        {
            'summary': 'High risk appears in the second row.',
            'findings': ['One high-risk record is present.'],
            'counts': {'high_risk': 1},
            'notable_rows': [
                {
                    'source_row_number': 2,
                    'source_row_identity': 'SC-2',
                    'note': 'The row is marked high risk.',
                },
            ],
        },
        source_rows=source_rows,
        chunk_number=1,
    )

    assert chunk_summary['kind'] == 'chunk_summary'
    assert chunk_summary['row_count'] == 2
    assert chunk_summary['source_row_start'] == 1
    assert chunk_summary['source_row_end'] == 2
    assert chunk_summary['notable_rows'][0]['source_row_number'] == 2

    reduce_fan_in = helpers['_get_tabular_analysis_reduce_fan_in']({
        'tabular_hierarchical_analysis_reduce_fan_in': 20,
    })
    assert reduce_fan_in == 20
    assert helpers['_build_analysis_reduce_plan'](61, reduce_fan_in) == [4, 1]
    reduce_groups = helpers['_build_analysis_reduce_groups'](list(range(61)), reduce_fan_in)
    assert [len(group) for group in reduce_groups] == [20, 20, 20, 1]

    reduced_summary = helpers['_normalize_analysis_summary_payload'](
        {
            'summary': 'High risk is isolated but important.',
            'findings': [{'finding': 'One chunk includes high-risk evidence.'}],
            'counts': {'chunks_with_high_risk': 1},
            'notable_rows': chunk_summary['notable_rows'],
        },
        child_summaries=[chunk_summary],
        reduce_level=1,
        reduce_node=1,
    )
    assert reduced_summary['kind'] == 'reduce_summary'
    assert reduced_summary['row_count'] == 2

    markdown = helpers['_build_analysis_summary_markdown'](
        {
            'id': 'analysis-run-1',
            'source_file_name': 'cases.csv',
            'row_count': 2,
            'batch_count': 1,
        },
        reduced_summary,
    )
    assert '# Tabular Analysis' in markdown
    assert 'Row 2 (SC-2): The row is marked high risk.' in markdown
    assert 'Rows analyzed: 2' in markdown


def test_runner_routes_hierarchical_analysis_into_map_reduce():
    """The durable processor branches hierarchical analysis away from structured export finalization."""
    export_source = EXPORT_MODULE.read_text(encoding='utf-8')
    process_source = ast.unparse(_get_function_node('process_tabular_generated_output_run'))
    queue_source = ast.unparse(_get_function_node('queue_tabular_generated_output_run'))

    assert '_process_hierarchical_analysis_run(' in process_source
    assert 'TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS' in process_source
    assert "normalized_output_format = 'md'" in queue_source
    assert '_build_analysis_file_name(source_file_name)' in queue_source
    assert '_generate_analysis_chunk_summary_window' in export_source
    assert '_run_analysis_reduce_tree' in export_source
    assert 'tabular_hierarchical_analysis_reduce_fan_in' in export_source
    assert "'analysis_phase': run.get('analysis_phase')" in export_source
    assert 'tabular-hierarchical-analysis:' in export_source


def test_runner_routes_combined_analysis_and_export_once():
    """Combined durable runs share one chunk pass and publish both deliverables."""
    export_source = EXPORT_MODULE.read_text(encoding='utf-8')
    process_source = ast.unparse(_get_function_node('process_tabular_generated_output_run'))
    combined_source = ast.unparse(_get_function_node('_process_combined_run'))
    load_summaries_source = ast.unparse(_get_function_node('_load_analysis_chunk_summaries'))
    public_status_source = ast.unparse(_get_function_node('_build_run_public_status'))
    queue_source = ast.unparse(_get_function_node('queue_tabular_generated_output_run'))

    assert 'TABULAR_RUN_TASK_COMBINED' in process_source
    assert '_process_combined_run(' in process_source
    assert '_generate_combined_chunk_result_window' in combined_source
    assert '_generate_batch_window_entries' not in combined_source
    assert '_generate_analysis_chunk_summary_window' not in combined_source
    assert '_checkpoint_combined_batch_results' in combined_source
    assert combined_source.index('_publish_combined_structured_export_phase') < combined_source.index(
        '_run_analysis_reduce_tree'
    )
    assert combined_source.index('_run_analysis_reduce_tree') < combined_source.index(
        '_complete_combined_analysis_run'
    )
    assert '_analysis_chunk_summary_blob_path' in load_summaries_source
    assert "'generated_artifacts': generated_artifacts" in public_status_source
    assert "'structured_export_artifact': structured_export_public_artifact" in public_status_source
    assert "'analysis_artifact': analysis_public_artifact" in public_status_source
    assert "'structured_export_artifact': run.get('structured_export_artifact')" not in public_status_source
    assert "'analysis_artifact': run.get('analysis_artifact')" not in public_status_source
    assert 'analysis_generated_file_name' in queue_source
    assert '_generate_combined_chunk_result_window' in export_source
    assert 'tabular_combined_analysis_summary' in export_source


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

    input_batch_1_path = 'user-1/conversation-1/generated/tabular_runs/legacy-run/input/batch_000001.json'
    input_batch_2_path = 'user-1/conversation-1/generated/tabular_runs/legacy-run/input/batch_000002.json'
    output_batch_1_path = 'user-1/conversation-1/generated/tabular_runs/legacy-run/output/batch_000001.json'
    output_batch_2_path = 'user-1/conversation-1/generated/tabular_runs/legacy-run/output/batch_000002.json'
    summary_batch_1_path = 'user-1/conversation-1/generated/tabular_runs/legacy-run/summary/batch_000001.json'
    summary_batch_2_path = 'user-1/conversation-1/generated/tabular_runs/legacy-run/summary/batch_000002.json'
    manifest_page_path = 'user-1/conversation-1/generated/tabular_runs/legacy-run/manifest/chunks/page_000001.json'

    assert migrated_run['contract_version'] == 3
    assert migrated_run['generation_contract_version'] == 1
    assert migrated_run['response_protocol_version'] == 'object-v1'
    assert migrated_run['executor_mode'] == 'fixed-window-v1'
    assert migrated_run['task_type'] == 'structured_export'
    assert migrated_run['analysis_objective'] == ''
    assert migrated_run['total_chunk_count'] == 2
    assert migrated_run['processed_chunk_count'] == 0
    assert migrated_run['failed_chunk_count'] == 0
    assert migrated_run['chunk_manifest']['page_count'] == 1
    assert migrated_run['completed_batches'] == 0
    assert migrated_run['planned_batch_count'] == 2
    assert migrated_run['completed_batch_count'] == 0
    assert migrated_run['highest_contiguous_batch'] == 0
    assert migrated_run['checkpointed_row_count'] == 0
    assert migrated_run['processed_rows'] == 0
    assert migrated_run['plan_blob_path'] is None
    assert migrated_run['plan_hash'] is None
    assert migrated_run['output_schema'] is None
    assert migrated_run['regenerate_legacy_output_checkpoints'] is False
    assert migrated_run['input_blob_path'] is None
    assert [row['__simplechat_source_row_number'] for row in uploaded_batches[input_batch_1_path]] == [1, 2]
    assert uploaded_batches[input_batch_2_path][0]['__simplechat_source_row_number'] == 3
    assert uploaded_batches[manifest_page_path]['chunks'][0]['row_count'] == 2
    assert deleted_blobs == [
        output_batch_1_path,
        summary_batch_1_path,
        output_batch_2_path,
        summary_batch_2_path,
    ]
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
    assert uploaded_batches[input_batch_1_path][0]['__simplechat_source_row_token'] == (
        second_uploaded_batches[input_batch_1_path][0]['__simplechat_source_row_token']
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

    route_module = ast.parse(route_source, filename=str(CHAT_ROUTE))
    generated_file_export = next(
        node
        for node in route_module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == 'maybe_create_generated_file_output'
    )
    generated_file_export_source = ast.get_source_segment(route_source, generated_file_export)
    assert "'source': 'chat'," in generated_file_export_source
    assert "'container': storage_account_personal_chat_container_name" not in generated_file_export_source

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


def test_phase_two_background_handoff_contracts_are_server_composed():
    """Queued export, analysis, and combined runs use concise truthful handoff text."""
    helpers = _load_failed_export_helpers()

    export_output = {
        'background_export': True,
        'status': 'queued',
        'export_run_id': 'run-export-30000',
        'output_format': 'csv',
        'row_count': 30000,
        'batch_count': 909,
        'preview_rows': [{'question': 'Sample?', 'answer': 'Yes'}],
    }
    export_handoff = helpers['_build_tabular_background_handoff_content'](export_output)
    _assert_concise_background_handoff_contract(export_handoff, 30000, 'CSV')
    assert 'rows shown here are a sample' in export_handoff.lower()
    assert 'complete file will appear in this chat when ready' in export_handoff.lower()

    analysis_output = {
        'background_export': True,
        'status': 'running',
        'export_run_id': 'run-analysis-30000',
        'task_type': 'hierarchical_analysis',
        'output_format': 'md',
        'row_count': 30000,
        'preview_text': 'sample finding',
    }
    analysis_handoff = helpers['_build_tabular_background_handoff_content'](analysis_output)
    _assert_concise_background_handoff_contract(analysis_handoff, 30000, 'analysis')
    assert 'any content shown here is a sample' in analysis_handoff.lower()
    assert 'complete analysis is continuing' in analysis_handoff.lower()

    combined_output = {
        'background_export': True,
        'status': 'queued',
        'export_run_id': 'run-combined-30000',
        'task_type': 'combined',
        'output_format': 'csv',
        'row_count': 30000,
        'preview_available': True,
        'preview_row_count': 3,
    }
    combined_handoff = helpers['_build_tabular_background_handoff_content'](combined_output)
    _assert_concise_background_handoff_contract(combined_handoff, 30000, 'CSV')
    assert 'complete csv and analysis' in combined_handoff.lower()
    assert 'both completed results will appear in this chat when ready' in combined_handoff.lower()

    system_message = helpers['_build_tabular_generated_output_system_message'](export_output)
    assert export_handoff in system_message
    _assert_concise_background_handoff_contract(system_message, 30000, 'CSV')

    final_handoff = helpers['_build_active_tabular_background_handoff_content']([
        {'background_export': True, 'status': 'completed', 'output_format': 'csv', 'row_count': 30000},
        combined_output,
    ])
    assert final_handoff == combined_handoff

    canceled_handoff = helpers['_build_tabular_background_handoff_content']({
        'background_export': True,
        'status': 'canceled',
        'output_format': 'csv',
        'row_count': 30000,
    })
    assert canceled_handoff == ''


def test_background_metadata_uses_public_status_row_count():
    """Accepted durable runs build stream metadata from their safe public row count."""
    build_metadata = _load_background_generated_output_metadata_helper()
    cases = (
        ('structured_export', 'csv', 'background_export'),
        ('hierarchical_analysis', 'md', 'background_analysis'),
        ('combined', 'csv', 'background_combined'),
    )

    for task_type, output_format, handoff_mode in cases:
        metadata = build_metadata({
            'task_type': task_type,
            '_public_status': {
                'run_id': f'run-{task_type}',
                'task_type': task_type,
                'output_format': output_format,
                'row_count': 3000,
                'batch_count': 52,
            },
        })

        assert metadata['requested_row_count'] == 3000
        assert metadata['row_count'] == 3000
        assert metadata['handoff_mode'] == handoff_mode
        assert '3,000' not in metadata['summary']
        assert '3000 row(s)' in metadata['summary']


def main():
    """Run focused row-orchestration contract checks."""
    tests = [
        test_model_aware_batch_budget_uses_safe_token_limits,
        test_dynamic_concurrency_and_parallel_window_eta,
        test_phase_one_generation_contract_fields_are_additive_and_compact,
        test_phase_three_rollout_activates_shadow_only_and_stays_backend_only,
        test_shadow_generation_plan_is_deferred_off_the_production_critical_path,
        test_schema_probe_starts_small_then_uses_normal_batch_budget,
        test_phase_eight_rollout_assignment_is_stable_and_control_runs_stay_legacy,
        test_phase_eight_retry_and_stale_reclaim_modes_are_snapshotted,
        test_retry_status_detail_exposes_safe_retry_reason,
        test_startup_status_detail_reports_active_phase_before_first_checkpoint,
        test_phase_eight_publication_revalidates_source_version,
        test_phase_eight_committed_output_survives_summary_and_progress_crash,
        test_phase_eight_performance_summary_is_bounded_and_cohort_comparable,
        test_phase_eight_public_status_omits_private_execution_details,
        test_phase_one_observability_uses_safe_metrics_not_response_content,
        test_phase_one_fake_harnesses_control_completion_order_and_storage_failures,
        test_phase_three_plan_contract_is_bounded_immutable_and_private,
        test_phase_three_plan_rejects_malformed_fields_and_source_changes,
        test_phase_three_shadow_active_and_checkpoint_contracts,
        test_phase_three_planner_timeout_retries_before_fallback,
        test_phase_three_plan_persistence_boundaries_never_replan,
        test_phase_four_compact_protocol_requires_active_plan_rollout,
        test_phase_four_compact_response_reconstructs_object_contract,
        test_phase_four_compact_response_rejects_key_and_value_failures,
        test_source_identity_and_order_contract,
        test_generated_batch_schema_contract,
        test_model_batch_token_echo_recovery_preserves_order_contract,
        test_model_batch_nested_csv_output_is_flattened_before_schema_inference,
        test_model_batch_nested_csv_output_supports_arbitrary_csv_headers,
        test_durable_runner_enforces_row_contract,
        test_paginated_candidate_coalesces_all_300_rows,
        test_paginated_candidate_rejects_gaps,
        test_paginated_candidate_rejects_mixed_source_versions,
        test_filter_rows_pages_queue_full_3000_row_source_replay,
        test_filter_rows_pages_queue_hierarchical_analysis_run,
        test_filter_rows_pages_queue_combined_analysis_and_export_run,
        test_downloadable_complete_csv_request_uses_shared_artifact_intent,
        test_durable_tabular_descriptor_supports_all_configured_formats,
        test_durable_workbook_replay_preserves_sheet_order_and_resume_position,
        test_direct_source_backed_queue_supports_all_workbook_formats,
        test_direct_source_backed_csv_queue_bypasses_tool_paging,
        test_direct_source_backed_queue_failure_suppresses_inline_exhaustive_output,
        test_phase_two_background_handoff_contracts_are_server_composed,
        test_background_metadata_uses_public_status_row_count,
        test_direct_source_backed_queue_call_sites_use_required_keywords,
        test_model_validation_failures_auto_retry_then_manual_continue,
        test_hierarchical_analysis_routing_requires_feature_flag,
        test_non_replayable_filter_rows_reports_explicit_failure,
        test_streaming_finalizer_writes_30000_rows_in_bounded_chunks,
        test_streaming_finalizer_neutralizes_csv_formulas,
        test_streaming_finalizer_rejects_source_order_gaps,
        test_csv_query_source_reader_scales_and_resumes,
        test_scale_fixture_generator_streams_all_required_tiers,
        test_scale_tiers_plan_export_and_analysis_with_bounded_manifests,
        test_100000_row_hardening_contracts_revalidate_source_and_cancel_terminally,
        test_worker_revalidates_conversation_and_workspace_authorization,
        test_durable_cancellation_is_idempotent_and_terminal,
        test_worker_lease_fencing_rejects_stale_claims,
        test_chunk_manifest_contract_stays_compact_at_100000_rows,
        test_hierarchical_analysis_summary_contract_and_recursive_reduce,
        test_runner_routes_hierarchical_analysis_into_map_reduce,
        test_runner_routes_combined_analysis_and_export_once,
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