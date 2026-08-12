#!/usr/bin/env python3
"""
Functional test for durable tabular generated-output background exports.
Version: 0.250.176
Implemented in: 0.241.060; throughput and timeout hardening in: 0.250.070; unified durable run contract in: 0.250.128; Phase 6 rolling worker pool compatibility in: 0.250.142; safe retry reason status text in: 0.250.147; collapsed operational details in: 0.250.150; simplified completed artifact cards in: 0.250.151; balanced batches and foreground JSON/XML cards in: 0.250.152; plural artifact-set completion rendering in: 0.250.176

This test ensures that large tabular structured exports are wired through the
durable background queue, status API, queued retry recovery, and chat progress
UI without requiring live Azure services.
"""

import asyncio
import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / 'application' / 'single_app'
EXPORT_MODULE = APP_ROOT / 'functions_tabular_generated_exports.py'
CHAT_ROUTE = APP_ROOT / 'route_backend_chats.py'
CHAT_MESSAGES_JS = APP_ROOT / 'static' / 'js' / 'chat' / 'chat-messages.js'
BACKGROUND_TASKS = APP_ROOT / 'background_tasks.py'
CONFIG = APP_ROOT / 'config.py'
GUNICORN_CONFIG = APP_ROOT / 'gunicorn.conf.py'


def read_text(path):
    """Read a source file as UTF-8 text."""
    return path.read_text(encoding='utf-8')


def parse_python(path):
    """Parse a Python source file and fail clearly on syntax errors."""
    return ast.parse(read_text(path), filename=str(path))


def get_function(module_tree, function_name):
    """Find a top-level function definition in an AST tree."""
    for node in module_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    return None


def assert_contains(source_text, needle, description):
    """Assert that a source file contains an expected implementation marker."""
    if needle not in source_text:
        raise AssertionError(f'Missing {description}: {needle}')


def test_export_runner_module():
    """Validate that the durable export runner exposes the required lifecycle."""
    module_tree = parse_python(EXPORT_MODULE)
    function_names = {
        node.name
        for node in module_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    required_functions = {
        'should_queue_tabular_generated_output_background',
        'queue_tabular_generated_output_run',
        'get_tabular_generated_output_run_status',
        'build_background_tabular_generated_output_metadata',
        'process_tabular_generated_output_run',
        'resume_tabular_generated_output_run',
        'cancel_tabular_generated_output_run',
        'check_due_tabular_generated_output_runs_once',
        '_is_due_queued_retry_run',
        '_is_stale_queued_run',
    }

    missing_functions = required_functions - function_names
    if missing_functions:
        raise AssertionError(f'Missing runner functions: {sorted(missing_functions)}')

    source_text = read_text(EXPORT_MODULE)
    assert_contains(source_text, "STATUS_QUEUED = 'queued'", 'queued status constant')
    assert_contains(source_text, 'input/batch_', 'per-batch staged input blobs')
    assert_contains(source_text, 'output/batch_', 'per-batch output checkpoint blobs')
    assert_contains(source_text, 'upload_generated_analysis_artifact_stream_for_user', 'bounded-memory artifact upload')
    assert_contains(source_text, '_write_ordered_output_stream', 'ordered streaming finalization')
    assert_contains(source_text, '_stage_tabular_generated_output_source', 'bounded source-query staging')
    assert_contains(source_text, '_authorize_tabular_export_run_execution', 'worker-boundary authorization')
    assert_contains(source_text, '_migrate_legacy_tabular_export_run', 'legacy run contract migration')
    assert_contains(source_text, 'TABULAR_EXPORT_CONTRACT_VERSION = 3', 'versioned row orchestration contract')
    assert_contains(source_text, "TABULAR_RUN_TASK_STRUCTURED_EXPORT = 'structured_export'", 'structured export task type')
    assert_contains(source_text, "'total_chunk_count': staged_batch_count", 'compact chunk counter')
    assert_contains(source_text, "'chunk_manifest': chunk_manifest", 'blob-backed chunk manifest pointer')
    assert_contains(source_text, '_write_chunk_manifest_for_run', 'paged chunk manifest writer')
    assert_contains(source_text, 'lease_generation', 'worker fencing generation')
    assert_contains(source_text, '_replace_claimed_run', 'ETag-fenced worker persistence')
    assert_contains(source_text, 'TABULAR_EXPORT_INPUT_ROW_TOKEN_FIELD', 'opaque row binding token')
    assert_contains(source_text, '_build_generated_batch_summary', 'per-batch compact summaries')
    assert_contains(source_text, '_build_compact_post_run_summary', 'checkpoint-derived post-run summary')
    assert_contains(source_text, "'generated_artifact': generated_artifact", 'completed artifact status payload')
    assert_contains(source_text, '_mark_run_retryable', 'retryable transient failure requeue')
    assert_contains(source_text, 'transient_failure_count', 'bounded transient failure counter')
    assert_contains(source_text, 'TABULAR_EXPORT_DEFAULT_SCAN_LIMIT = 5', 'non-starving scheduler scan limit')
    assert_contains(source_text, 'APIConnectionError', 'OpenAI connection error retry classification')
    assert_contains(source_text, 'build_semantic_kernel_chat_service_for_model', 'provider-aware background model service')
    assert_contains(source_text, 'has_snapshotted_chunk_model', 'snapshot-aware chunk model rehydration')
    assert_contains(source_text, "run.get('chunk_model_context')", 'chunk model context rehydration')
    assert_contains(source_text, "else run.get('model_context')", 'fallback model context rehydration')
    assert_contains(source_text, "'model_context': model_context if isinstance(model_context, dict) else {}", 'persisted non-secret model context')
    assert_contains(source_text, 'TABULAR_EXPORT_STATUS_FAILED', 'retryable failed-run scheduler pickup')
    assert_contains(source_text, 'TABULAR_EXPORT_SCHEDULER_STATUSES', 'status-specific scheduler scans')
    assert_contains(source_text, '_query_scheduler_candidates_by_status', 'simple scheduler status query helper')
    assert_contains(source_text, '_scheduler_candidate_reason', 'Python-side scheduler due filtering')
    assert_contains(source_text, 'FROM c WHERE c.type = @type AND c.status = @status', 'Cosmos-safe scheduler query shape')
    assert_contains(source_text, 'ORDER BY c.updated_at ASC', 'oldest-first scheduler ordering')
    assert_contains(source_text, 'if len(eligible_candidates) >= per_status_limit', 'eligibility-before-limit scheduler scan')
    assert_contains(source_text, 'active_processing_seconds', 'active-time ETA accounting')
    assert_contains(source_text, 'or _is_due_queued_retry_run(run)', 'queued retry-due manual resume eligibility')
    assert_contains(source_text, 'or _is_stale_queued_run(run, settings or {})', 'stale queued manual resume eligibility')
    assert_contains(source_text, 'Automatic retry is due because', 'queued retry-due status detail')
    assert_contains(source_text, "'retry_due': status_detail.get('retry_due')", 'retry-due public status payload')
    assert_contains(source_text, 'Manual resume queued', 'manual checkpoint resume message')
    assert_contains(source_text, 'manual_resume_count', 'manual resume counter')
    assert_contains(source_text, 'can_cancel', 'public cancellation capability')
    assert_contains(source_text, 'status_detail', 'safe status detail payload')
    assert_contains(source_text, 'checkpoint_summary', 'checkpoint summary payload')
    assert_contains(source_text, 'waiting_for_retry', 'scheduled retry status payload')
    assert_contains(source_text, 'retry_delay_seconds', 'retry delay status payload')
    assert_contains(source_text, 'Background scheduler scan result', 'scheduler scan diagnostics')

    simplechat_operations_source = read_text(APP_ROOT / 'functions_simplechat_operations.py')
    assert_contains(simplechat_operations_source, 'artifact_idempotency_key', 'idempotent artifact key')
    assert_contains(simplechat_operations_source, 'uuid.uuid5', 'deterministic artifact message identity')


def test_background_runner_bounded_batch_concurrency():
    """Validate bounded adaptive model-batch concurrency in the background runner."""
    source_text = read_text(EXPORT_MODULE)
    assert_contains(source_text, 'TABULAR_EXPORT_DEFAULT_BATCH_CONCURRENCY = 16', 'default batch concurrency')
    assert_contains(source_text, 'TABULAR_EXPORT_HIGH_BATCH_CONCURRENCY = 64', 'high batch concurrency')
    assert_contains(source_text, 'TABULAR_EXPORT_MAX_BATCH_CONCURRENCY = 128', 'maximum batch concurrency')
    assert_contains(source_text, 'TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS = 300', 'bounded batch timeout')
    assert_contains(source_text, 'tabular_generated_output_batch_concurrency', 'settings override for batch concurrency')
    assert_contains(source_text, 'tabular_generated_output_batch_timeout_seconds', 'settings override for batch timeout')
    assert_contains(source_text, '_generate_batch_window_entries', 'async batch window generation helper')
    assert_contains(source_text, 'asyncio.Semaphore', 'bounded async batch semaphore')
    assert_contains(source_text, 'asyncio.gather(*tasks, return_exceptions=True)', 'bounded window gather with exception capture')
    assert_contains(source_text, 'asyncio.wait_for(', 'bounded model-call timeout')
    assert_contains(source_text, '_checkpoint_generated_batch_results', 'checkpoint successful concurrent batches')
    assert_contains(source_text, '_advance_run_progress_for_window', 'contiguous progress advancement after batch window')
    assert_contains(source_text, 'Building background structured export batch window', 'batch window diagnostics')
    assert_contains(source_text, '_balance_tabular_source_batch_rows', 'concurrency-wave batch balancer')
    assert_contains(source_text, "'token_max_rows'", 'token-derived batch limit telemetry')


def test_background_batch_timeout_prevents_indefinite_model_wait():
    """A stalled model call must fail as retryable timeout before a worker can hang indefinitely."""
    module_tree = parse_python(EXPORT_MODULE)
    helper_node = get_function(module_tree, '_generate_batch_entries')
    if helper_node is None:
        raise AssertionError('_generate_batch_entries was not found')

    class FakeChatHistory:
        def add_system_message(self, _message):
            return None

        def add_user_message(self, _message):
            return None

    class FakeExecutionSettings:
        def __init__(self, service_id):
            self.service_id = service_id

    class SlowChatService:
        async def get_chat_message_contents(self, _history, _settings):
            await asyncio.sleep(0.01)
            return []

    namespace = {
        'asyncio': asyncio,
        'SKChatHistory': FakeChatHistory,
        'AzureChatPromptExecutionSettings': FakeExecutionSettings,
        'TABULAR_EXPORT_DEFAULT_BATCH_TIMEOUT_SECONDS': 300,
        'TABULAR_RESPONSE_PROTOCOL_OBJECT_V1': 'object-v1',
        'time': __import__('time'),
        '_safe_float': lambda value, default=0.0: float(value) if value is not None else default,
        '_is_compact_row_array_protocol': lambda _response_protocol: False,
        '_build_model_expected_output_schema': (
            lambda expected_output_schema, transformation_spec=None: list(expected_output_schema or [])
        ),
        '_build_batch_prompt': lambda *args, **kwargs: 'test prompt',
    }
    extracted_module = ast.Module(body=[helper_node], type_ignores=[])
    ast.fix_missing_locations(extracted_module)
    exec(compile(extracted_module, str(EXPORT_MODULE), 'exec'), namespace)

    try:
        asyncio.run(
            namespace['_generate_batch_entries'](
                SlowChatService(),
                'Create a CSV.',
                [{'name': 'Example'}],
                0,
                1,
                'example.csv',
                '',
                1,
                'run-1',
                batch_timeout_seconds=0.001,
            )
        )
    except TimeoutError as exc:
        assert 'timed out after' in str(exc), exc
    else:
        raise AssertionError('Expected a stalled background model call to time out')


def test_chat_route_wires_background_exports():
    """Validate chat route queueing, metadata normalization, and status endpoint wiring."""
    module_tree = parse_python(CHAT_ROUTE)
    maybe_create = get_function(module_tree, 'maybe_create_tabular_generated_output')
    if maybe_create is None:
        raise AssertionError('maybe_create_tabular_generated_output was not found')

    maybe_create_arg_names = [arg.arg for arg in maybe_create.args.args]
    if 'user_id' not in maybe_create_arg_names:
        raise AssertionError('maybe_create_tabular_generated_output must accept user_id')
    if 'model_context' not in maybe_create_arg_names:
        raise AssertionError('maybe_create_tabular_generated_output must accept model_context')

    source_text = read_text(CHAT_ROUTE)
    assert_contains(source_text, 'should_queue_tabular_generated_output_background', 'background queue decision')
    assert_contains(source_text, 'queue_tabular_generated_output_run(', 'background queue creation')
    assert_contains(source_text, 'model_context=model_context', 'background queue model context handoff')
    assert_contains(source_text, 'build_background_tabular_generated_output_metadata', 'background metadata handoff')
    assert_contains(source_text, "'/api/tabular/generated-output/runs/<run_id>'", 'run status API route')
    assert_contains(source_text, "'/api/tabular/generated-output/runs/<run_id>/resume'", 'run resume API route')
    assert_contains(source_text, "'/api/tabular/generated-output/runs/<run_id>/cancel'", 'run cancel API route')
    assert_contains(source_text, 'resume_tabular_generated_output_run', 'manual resume route helper')
    assert_contains(source_text, 'cancel_tabular_generated_output_run', 'cancel route helper')
    assert_contains(source_text, '@swagger_route(security=get_auth_security())', 'secured status route decorator')
    assert_contains(source_text, "output_metadata.get('background_export')", 'background assistant handoff message')


def test_generated_export_batch_packing_phase_three():
    """Validate compact row packing markers for large generated exports."""
    chat_source = read_text(CHAT_ROUTE)
    export_source = read_text(EXPORT_MODULE)
    assert_contains(chat_source, 'TABULAR_STRUCTURED_EXPORT_MAX_BATCH_ROWS = 50', 'larger generated-export row budget')
    assert_contains(chat_source, 'TABULAR_STRUCTURED_EXPORT_MAX_BATCH_CHARS = 60000', 'larger generated-export char budget')
    assert_contains(chat_source, 'tabular_generated_output_max_batch_rows', 'settings override for generated-export row budget')
    assert_contains(chat_source, 'tabular_generated_output_max_batch_chars', 'settings override for generated-export char budget')
    assert_contains(chat_source, 'TABULAR_GENERATED_OUTPUT_INTERNAL_ROW_FIELDS', 'internal helper field pruning')
    assert_contains(chat_source, '_compact_tabular_generated_output_referenced_documents', 'row-linked evidence compaction')
    assert_contains(chat_source, "separators=(',', ':')", 'compact prompt JSON serialization')
    assert_contains(chat_source, "'batch_char_budget': batch_budget['max_chars']", 'batch budget diagnostics')
    assert_contains(export_source, '_dump_generated_output_json', 'background compact prompt serialization')
    assert_contains(export_source, "separators=(',', ':')", 'background compact JSON serialization')


def test_background_scheduler_and_config_registered():
    """Validate the scheduler and Cosmos container registration are present."""
    background_source = read_text(BACKGROUND_TASKS)
    assert_contains(background_source, 'check_due_tabular_generated_output_runs_once', 'background export scheduler import')
    assert_contains(background_source, 'run_tabular_generated_output_scheduler_loop', 'background export scheduler loop')
    assert_contains(background_source, "'tabular_generated_output_scheduler_scan'", 'distributed scheduler lock')

    gunicorn_source = read_text(GUNICORN_CONFIG)
    assert_contains(gunicorn_source, 'SIMPLECHAT_RUN_BACKGROUND_TASKS', 'background-task-aware gunicorn defaults')
    assert_contains(gunicorn_source, "max_requests = _env_int('GUNICORN_MAX_REQUESTS', 0 if background_tasks_enabled else 500)", 'disabled request-count recycling for background exports')
    assert_contains(gunicorn_source, "graceful_timeout = _env_int('GUNICORN_GRACEFUL_TIMEOUT', 300 if background_tasks_enabled else 60)", 'longer graceful timeout for background exports')

    config_source = read_text(CONFIG)
    assert_contains(config_source, 'cosmos_tabular_export_runs_container_name', 'export runs container name')
    assert_contains(config_source, 'tabular_export_runs', 'export runs Cosmos container')
    assert_contains(config_source, 'PartitionKey(path="/user_id")', 'per-user partition key')


def test_chat_ui_renders_and_polls_background_exports():
    """Validate browser progress UI support for queued background exports."""
    source_text = read_text(CHAT_MESSAGES_JS)
    assert_contains(source_text, 'background_export', 'background export normalization')
    assert_contains(source_text, 'createBackgroundGeneratedOutputStatusBlock', 'background progress card')
    assert_contains(source_text, 'refreshBackgroundGeneratedOutputStatus', 'status refresh function')
    assert_contains(source_text, 'continueBackgroundGeneratedOutputRun', 'manual continue function')
    assert_contains(source_text, 'generated-tabular-continue-btn', 'manual continue button')
    assert_contains(source_text, 'generated-tabular-cancel-btn', 'cancel button')
    assert_contains(source_text, '/resume', 'manual resume endpoint call')
    assert_contains(source_text, '/cancel', 'cancel endpoint call')
    assert_contains(source_text, 'formatGeneratedOutputTimestamp', 'localized status timestamps')
    assert_contains(source_text, 'formatGeneratedOutputDuration', 'readable retry and ETA durations')
    assert_contains(source_text, 'shouldPollBackgroundGeneratedOutput', 'retry-aware polling guard')
    assert_contains(source_text, 'status_detail', 'safe status detail rendering')
    assert_contains(source_text, '/api/tabular/generated-output/runs/', 'status polling endpoint')
    assert_contains(source_text, 'textContent', 'safe text rendering boundary')
    assert_contains(source_text, "details.dataset.generatedExportDetails = 'true'", 'collapsed details selector')
    assert_contains(source_text, "detailsSummary.textContent = 'View details'", 'details disclosure label')
    assert_contains(source_text, 'supportingDetailElements.forEach', 'supporting metadata disclosure routing')
    assert_contains(source_text, 'backgroundStatusElements?.detailsContent', 'background preview disclosure routing')
    assert_contains(source_text, 'isCompletedTabularArtifact', 'completed tabular card state')
    assert_contains(source_text, 'generated-artifact-view-btn', 'completed artifact View action')
    assert_contains(source_text, 'generated-artifact-preview-modal', 'bounded artifact preview modal')
    assert_contains(source_text, 'hideCompletedGeneratedArtifactHandoff', 'stale completion handoff suppression')
    assert_contains(source_text, 'normalizeGeneratedArtifactSet', 'plural artifact-set normalizer')
    assert_contains(source_text, 'replaceBackgroundGeneratedOutputCardWithArtifacts', 'plural completion replacement path')
    assert_contains(source_text, "role === 'primary_analysis'", 'Analyze Markdown primary ordering')
    assert_contains(source_text, 'generated_artifacts', 'authoritative plural status field')
    assert_contains(source_text, 'simplechat:generated-artifact-set', 'safe artifact-set UI event')
    assert_contains(source_text, 'Download ${fileName}', 'unique download accessible name')
    if 'details.open = true' in source_text:
        raise AssertionError('Background export operational details must remain collapsed until the user expands them')
    if 'generated-tabular-refresh-status-btn' in source_text or 'Refresh Status' in source_text:
        raise AssertionError('Background export cards must rely on automatic polling without a manual refresh button')


def test_completed_artifact_preview_is_bounded_and_ordered():
    """Completed artifact metadata carries only a bounded validated preview."""
    module_tree = parse_python(EXPORT_MODULE)
    helper_names = {
        '_build_structured_export_preview_rows',
        '_build_artifact_metadata',
    }
    helper_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    if len(helper_nodes) != len(helper_names):
        raise AssertionError('Completed artifact preview helpers were not found')

    batches = {
        'output-1': [
            {'source_row_number': 1, 'source_row_identity': 'A-1', 'answer': 'first'},
            {'source_row_number': 2, 'source_row_identity': 'A-2', 'answer': 'x' * 20},
        ],
        'output-2': [
            {'source_row_number': 3, 'source_row_identity': 'A-3', 'answer': 'third'},
            {'source_row_number': 4, 'source_row_identity': 'A-4', 'answer': 'fourth'},
        ],
    }
    validated_batches = []
    namespace = {
        'TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_ROWS': 3,
        'TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_CHARS': 24000,
        'TABULAR_EXPORT_ARTIFACT_PREVIEW_CELL_MAX_CHARS': 12,
        'TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD': 'source_row_number',
        '_safe_int': lambda value: int(value or 0),
        '_get_tabular_run_serialized_public_schema': (
            lambda run: [
                field_name
                for field_name in list((run or {}).get('output_schema') or [])
                if field_name not in {'source_row_number', 'source_row_identity'}
            ]
        ),
        '_output_blob_path': lambda user_id, conversation_id, run_id, batch_number: f'output-{batch_number}',
        '_validate_tabular_output_checkpoint_metadata': (
            lambda run, path, batch_number: validated_batches.append((path, batch_number))
        ),
        '_download_json_blob': lambda path: batches[path],
        'project_structured_deliverable_row': (
            lambda entry, public_schema, require_all_fields=True: {
                field_name: entry[field_name]
                for field_name in public_schema
            }
        ),
        '_serialize_generated_output_value': lambda value: '' if value is None else str(value),
        'build_safe_csv_headers': lambda values: list(values),
        'json': __import__('json'),
    }
    exec(
        compile(ast.Module(body=helper_nodes, type_ignores=[]), str(EXPORT_MODULE), 'exec'),
        namespace,
    )

    run = {
        'id': 'run-preview',
        'user_id': 'user-1',
        'conversation_id': 'conversation-1',
        'batch_count': 2,
        'output_format': 'csv',
        'output_schema': ['source_row_number', 'source_row_identity', 'answer'],
    }
    preview_rows = namespace['_build_structured_export_preview_rows'](run)
    artifact = namespace['_build_artifact_metadata'](
        {'id': 'artifact-1', 'file_name': 'generated.csv'},
        'fallback.csv',
        'csv',
        preview_rows=preview_rows,
        preview_text='m' * 25000,
        suppress_assistant_text=True,
    )

    assert [row['answer'] for row in preview_rows] == ['first', 'xxxxxxxxx...', 'third']
    assert 'source_row_number' not in preview_rows[0]
    assert 'source_row_identity' not in preview_rows[0]
    assert validated_batches == [('output-1', 1), ('output-2', 2)]
    assert artifact['preview_rows'] == preview_rows
    assert artifact['preview_columns'] == ['answer']
    assert len(artifact['preview_text']) == 24000
    assert artifact['suppress_assistant_text'] is True


def main():
    """Run all checks and report a compact summary."""
    tests = [
        test_export_runner_module,
        test_background_runner_bounded_batch_concurrency,
        test_background_batch_timeout_prevents_indefinite_model_wait,
        test_chat_route_wires_background_exports,
        test_generated_export_batch_packing_phase_three,
        test_background_scheduler_and_config_registered,
        test_chat_ui_renders_and_polls_background_exports,
        test_completed_artifact_preview_is_bounded_and_ordered,
    ]
    results = []

    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            print(f'PASS {test.__name__}')
            results.append(True)
        except Exception as exc:
            print(f'FAIL {test.__name__}: {exc}')
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f'Results: {passed}/{len(results)} tests passed')
    return all(results)


if __name__ == '__main__':
    sys.exit(0 if main() else 1)