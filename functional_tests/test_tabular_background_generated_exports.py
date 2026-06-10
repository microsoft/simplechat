#!/usr/bin/env python3
"""
Functional test for durable tabular generated-output background exports.
Version: 0.241.186
Implemented in: 0.241.060

This test ensures that large tabular structured exports are wired through the
durable background queue, status API, queued retry recovery, and chat progress
UI without requiring live Azure services.
"""

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
        'check_due_tabular_generated_output_runs_once',
        '_is_due_queued_retry_run',
        '_is_stale_queued_run',
    }

    missing_functions = required_functions - function_names
    if missing_functions:
        raise AssertionError(f'Missing runner functions: {sorted(missing_functions)}')

    source_text = read_text(EXPORT_MODULE)
    assert_contains(source_text, "STATUS_QUEUED = 'queued'", 'queued status constant')
    assert_contains(source_text, 'input_batches.json', 'single staged input-batches blob')
    assert_contains(source_text, 'output/batch_', 'per-batch output checkpoint blobs')
    assert_contains(source_text, 'upload_generated_analysis_artifact_for_user', 'background-safe artifact upload')
    assert_contains(source_text, "'generated_artifact': generated_artifact", 'completed artifact status payload')
    assert_contains(source_text, '_mark_run_retryable', 'retryable transient failure requeue')
    assert_contains(source_text, 'transient_failure_count', 'bounded transient failure counter')
    assert_contains(source_text, 'TABULAR_EXPORT_DEFAULT_SCAN_LIMIT = 5', 'non-starving scheduler scan limit')
    assert_contains(source_text, 'APIConnectionError', 'OpenAI connection error retry classification')
    assert_contains(source_text, 'build_semantic_kernel_chat_service_for_model', 'provider-aware background model service')
    assert_contains(source_text, 'model_context=run.get(\'model_context\')', 'background model context rehydration')
    assert_contains(source_text, "'model_context': model_context if isinstance(model_context, dict) else {}", 'persisted non-secret model context')
    assert_contains(source_text, 'TABULAR_EXPORT_STATUS_FAILED', 'retryable failed-run scheduler pickup')
    assert_contains(source_text, 'TABULAR_EXPORT_SCHEDULER_STATUSES', 'status-specific scheduler scans')
    assert_contains(source_text, '_query_scheduler_candidates_by_status', 'simple scheduler status query helper')
    assert_contains(source_text, '_scheduler_candidate_reason', 'Python-side scheduler due filtering')
    assert_contains(source_text, 'FROM c WHERE c.type = @type AND c.status = @status', 'Cosmos-safe scheduler query shape')
    assert_contains(source_text, 'active_processing_seconds', 'active-time ETA accounting')
    assert_contains(source_text, 'or _is_due_queued_retry_run(run)', 'queued retry-due manual resume eligibility')
    assert_contains(source_text, 'or _is_stale_queued_run(run, settings or {})', 'stale queued manual resume eligibility')
    assert_contains(source_text, 'Automatic retry is due but no worker has picked it up', 'queued retry-due status detail')
    assert_contains(source_text, "'retry_due': status_detail.get('retry_due')", 'retry-due public status payload')
    assert_contains(source_text, 'Manual resume queued', 'manual checkpoint resume message')
    assert_contains(source_text, 'manual_resume_count', 'manual resume counter')
    assert_contains(source_text, 'status_detail', 'safe status detail payload')
    assert_contains(source_text, 'checkpoint_summary', 'checkpoint summary payload')
    assert_contains(source_text, 'waiting_for_retry', 'scheduled retry status payload')
    assert_contains(source_text, 'retry_delay_seconds', 'retry delay status payload')
    assert_contains(source_text, 'Background scheduler scan result', 'scheduler scan diagnostics')


def test_background_runner_bounded_batch_concurrency():
    """Validate Phase 4 bounded model-batch concurrency in the background runner."""
    source_text = read_text(EXPORT_MODULE)
    assert_contains(source_text, 'TABULAR_EXPORT_DEFAULT_BATCH_CONCURRENCY = 2', 'default batch concurrency')
    assert_contains(source_text, 'TABULAR_EXPORT_MAX_BATCH_CONCURRENCY = 5', 'maximum batch concurrency')
    assert_contains(source_text, 'tabular_generated_output_batch_concurrency', 'settings override for batch concurrency')
    assert_contains(source_text, '_generate_batch_window_entries', 'async batch window generation helper')
    assert_contains(source_text, 'asyncio.Semaphore', 'bounded async batch semaphore')
    assert_contains(source_text, 'asyncio.gather(*tasks, return_exceptions=True)', 'bounded window gather with exception capture')
    assert_contains(source_text, '_checkpoint_generated_batch_results', 'checkpoint successful concurrent batches')
    assert_contains(source_text, '_advance_run_progress_for_window', 'contiguous progress advancement after batch window')
    assert_contains(source_text, 'Building background structured export batch window', 'batch window diagnostics')


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
    assert_contains(source_text, 'resume_tabular_generated_output_run', 'manual resume route helper')
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
    assert_contains(source_text, '/resume', 'manual resume endpoint call')
    assert_contains(source_text, 'formatGeneratedOutputTimestamp', 'localized status timestamps')
    assert_contains(source_text, 'formatGeneratedOutputDuration', 'readable retry and ETA durations')
    assert_contains(source_text, 'shouldPollBackgroundGeneratedOutput', 'retry-aware polling guard')
    assert_contains(source_text, 'status_detail', 'safe status detail rendering')
    assert_contains(source_text, '/api/tabular/generated-output/runs/', 'status polling endpoint')
    assert_contains(source_text, 'textContent', 'safe text rendering boundary')


def main():
    """Run all checks and report a compact summary."""
    tests = [
        test_export_runner_module,
        test_background_runner_bounded_batch_concurrency,
        test_chat_route_wires_background_exports,
        test_generated_export_batch_packing_phase_three,
        test_background_scheduler_and_config_registered,
        test_chat_ui_renders_and_polls_background_exports,
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