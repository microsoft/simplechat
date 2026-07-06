# functions_app_maintenance.py
"""Application maintenance framework for safe Cosmos-backed foundation tasks."""

import logging
import time
import uuid
from datetime import datetime, timezone

from config import VERSION, cosmos_governance_policies_container, cosmos_settings_container
from functions_appinsights import log_event
from functions_cosmos_indexing import (
    COSMOS_INDEXING_POLICY_APPLY_SETTING,
    get_cosmos_indexing_policy_status,
    run_cosmos_indexing_policy_maintenance,
)
from functions_document_access_index import (
    DOCUMENT_ACCESS_ACTIVE_MAINTENANCE_INTERVAL_SETTING,
    DOCUMENT_ACCESS_BACKFILL_BATCH_SIZE_SETTING,
    DOCUMENT_ACCESS_BACKFILL_ENABLED_SETTING,
    DOCUMENT_ACCESS_REPAIR_BATCH_SIZE_SETTING,
    get_document_access_index_settings,
    get_document_access_index_backfill_status,
    is_document_access_index_maintenance_pending,
    run_document_access_index_backfill_maintenance,
)
from functions_shared_cache import ensure_shared_cache_version_doc, get_shared_cache_version


APP_MAINTENANCE_STATE_DOC_ID = 'app_maintenance_state'
APP_MAINTENANCE_DOC_TYPE = 'app_maintenance_state'
APP_MAINTENANCE_LOCK_NAME = 'app_maintenance'
APP_MAINTENANCE_DEFAULT_INTERVAL_SECONDS = 3600
APP_MAINTENANCE_DEFAULT_LEASE_SECONDS = 300
APP_MAINTENANCE_DEFAULT_ACTIVE_INTERVAL_SECONDS = 30

CACHE_VERSION_DOCUMENTS = [
    {
        'id': 'app_settings_cache_version',
        'container': 'settings',
        'description': 'App settings cache invalidation version.',
    },
    {
        'id': 'governance_cache_version',
        'container': 'governance_policies',
        'description': 'Governance and policy cache invalidation version.',
    },
    {
        'id': 'custom_pages_cache_version',
        'container': 'settings',
        'description': 'Custom pages cache invalidation version.',
    },
    {
        'id': 'chat_bootstrap_global_cache_version',
        'container': 'settings',
        'description': 'Chat bootstrap global cache invalidation version.',
    },
    {
        'id': 'document_access_index_projection_version',
        'container': 'settings',
        'description': 'Document access index projection version for future read models.',
    },
]


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_now_iso():
    return _utc_now().isoformat()


def _is_not_found_error(exc):
    return getattr(exc, 'status_code', None) == 404


def _get_cache_version_container(container_name):
    if container_name == 'governance_policies':
        return cosmos_governance_policies_container
    return cosmos_settings_container


def _read_maintenance_state():
    try:
        return cosmos_settings_container.read_item(
            item=APP_MAINTENANCE_STATE_DOC_ID,
            partition_key=APP_MAINTENANCE_STATE_DOC_ID,
        )
    except Exception as ex:
        if _is_not_found_error(ex):
            return None
        log_event(
            '[AppMaintenance] Failed to read maintenance state.',
            extra={'error': str(ex)},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise


def _write_maintenance_state(state):
    state_body = dict(state or {})
    state_body.update({
        'id': APP_MAINTENANCE_STATE_DOC_ID,
        'type': APP_MAINTENANCE_DOC_TYPE,
        'updated_at': _utc_now_iso(),
    })
    cosmos_settings_container.upsert_item(state_body)
    return state_body


def _record_started(run_id, triggered_by, requested_by):
    existing = _read_maintenance_state() or {}
    state = dict(existing)
    state.update({
        'current_run_id': run_id,
        'last_status': 'running',
        'last_triggered_by': triggered_by,
        'last_requested_by': requested_by,
        'last_started_at': _utc_now_iso(),
        'last_completed_at': None,
        'last_duration_ms': None,
        'last_error': None,
        'app_version': VERSION,
    })
    return _write_maintenance_state(state)


def _record_completed(run_id, started_at, triggered_by, requested_by, steps):
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    existing = _read_maintenance_state() or {}
    last_status = 'succeeded'
    if any(step.get('status') == 'failed' for step in list(steps or [])):
        last_status = 'succeeded_with_warnings'
    state = dict(existing)
    state.update({
        'current_run_id': None,
        'last_run_id': run_id,
        'last_status': last_status,
        'last_triggered_by': triggered_by,
        'last_requested_by': requested_by,
        'last_completed_at': _utc_now_iso(),
        'last_duration_ms': duration_ms,
        'last_error': None,
        'last_steps': steps,
        'app_version': VERSION,
    })
    return _write_maintenance_state(state)


def _record_failed(run_id, started_at, triggered_by, requested_by, error):
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    existing = _read_maintenance_state() or {}
    state = dict(existing)
    state.update({
        'current_run_id': None,
        'last_run_id': run_id,
        'last_status': 'failed',
        'last_triggered_by': triggered_by,
        'last_requested_by': requested_by,
        'last_completed_at': _utc_now_iso(),
        'last_duration_ms': duration_ms,
        'last_error': str(error),
        'app_version': VERSION,
    })
    return _write_maintenance_state(state)


def get_app_maintenance_settings(settings):
    """Normalize maintenance settings from app settings."""
    settings = settings or {}
    document_access_settings = get_document_access_index_settings(settings)
    enabled = bool(settings.get('enable_app_maintenance', True))
    run_on_startup = bool(settings.get('enable_startup_app_maintenance', True))
    document_access_container_enabled = bool(document_access_settings.get('container_enabled'))
    return {
        'enabled': enabled,
        'run_on_startup': run_on_startup,
        'check_interval_seconds': max(
            int(settings.get(
                'app_maintenance_check_interval_seconds',
                APP_MAINTENANCE_DEFAULT_INTERVAL_SECONDS,
            ) or APP_MAINTENANCE_DEFAULT_INTERVAL_SECONDS),
            60,
        ),
        'lease_seconds': max(
            int(settings.get(
                'app_maintenance_job_lease_seconds',
                APP_MAINTENANCE_DEFAULT_LEASE_SECONDS,
            ) or APP_MAINTENANCE_DEFAULT_LEASE_SECONDS),
            60,
        ),
        'apply_cosmos_indexing_policies': bool(settings.get(COSMOS_INDEXING_POLICY_APPLY_SETTING, False)),
        'run_document_access_index_backfill': document_access_container_enabled,
        'document_access_index_auto_maintenance': (
            enabled and run_on_startup and document_access_container_enabled
        ),
        'document_access_index_active_interval_seconds': max(
            int(settings.get(
                DOCUMENT_ACCESS_ACTIVE_MAINTENANCE_INTERVAL_SETTING,
                APP_MAINTENANCE_DEFAULT_ACTIVE_INTERVAL_SECONDS,
            ) or APP_MAINTENANCE_DEFAULT_ACTIVE_INTERVAL_SECONDS),
            15,
        ),
        'document_access_index_backfill_batch_size': max(
            int(settings.get(DOCUMENT_ACCESS_BACKFILL_BATCH_SIZE_SETTING, 200) or 200),
            1,
        ),
        'document_access_index_repair_batch_size': max(
            int(settings.get(DOCUMENT_ACCESS_REPAIR_BATCH_SIZE_SETTING, 100) or 100),
            1,
        ),
    }


def calculate_app_maintenance_sleep_seconds(maintenance_result, maintenance_settings):
    """Return the next scheduler sleep interval, using a short loop while DAI work remains."""
    maintenance_settings = maintenance_settings or {}
    default_sleep_seconds = max(
        int(maintenance_settings.get('check_interval_seconds') or APP_MAINTENANCE_DEFAULT_INTERVAL_SECONDS),
        60,
    )
    active_sleep_seconds = max(
        int(
            maintenance_settings.get('document_access_index_active_interval_seconds')
            or APP_MAINTENANCE_DEFAULT_ACTIVE_INTERVAL_SECONDS
        ),
        15,
    )
    if is_document_access_index_maintenance_pending(_extract_document_access_index_step_status(maintenance_result)):
        return active_sleep_seconds
    return default_sleep_seconds


def _extract_document_access_index_step_status(maintenance_result):
    if not isinstance(maintenance_result, dict):
        return None
    for step in maintenance_result.get('steps') or []:
        if isinstance(step, dict) and step.get('name') == 'document_access_index_backfill':
            results = step.get('results') if isinstance(step.get('results'), dict) else {}
            return results.get('current_status') or results
    return maintenance_result.get('document_access_index_backfill')


def initialize_cache_version_documents():
    """Ensure shared cache version documents exist in the settings container."""
    results = []
    for version_doc in CACHE_VERSION_DOCUMENTS:
        result = ensure_shared_cache_version_doc(
            version_doc['id'],
            initial_version=0,
            description=version_doc.get('description', ''),
            container=_get_cache_version_container(version_doc.get('container')),
        )
        result['container'] = version_doc.get('container', 'settings')
        results.append(result)
    return results


def get_cache_version_document_status():
    """Return current cache version document status for admin and diagnostics."""
    statuses = []
    for version_doc in CACHE_VERSION_DOCUMENTS:
        version = get_shared_cache_version(
            version_doc['id'],
            default_version=0,
            container=_get_cache_version_container(version_doc.get('container')),
        )
        statuses.append({
            'id': version_doc['id'],
            'container': version_doc.get('container', 'settings'),
            'description': version_doc.get('description', ''),
            'version': version,
        })
    return statuses


def get_app_maintenance_status(settings=None):
    """Return the latest app maintenance state and foundation document status."""
    state = _read_maintenance_state() or {
        'id': APP_MAINTENANCE_STATE_DOC_ID,
        'type': APP_MAINTENANCE_DOC_TYPE,
        'last_status': 'not_run',
        'app_version': VERSION,
    }
    maintenance_settings = get_app_maintenance_settings(settings or {})
    document_access_index_status = get_document_access_index_backfill_status(settings=settings or {})
    if isinstance(document_access_index_status.get('maintenance'), dict):
        document_access_index_status['maintenance'].update({
            'auto_maintenance_enabled': maintenance_settings.get('document_access_index_auto_maintenance'),
            'active_interval_seconds': maintenance_settings.get('document_access_index_active_interval_seconds'),
            'check_interval_seconds': maintenance_settings.get('check_interval_seconds'),
        })
    return {
        'success': True,
        'state': state,
        'cache_version_documents': get_cache_version_document_status(),
        'cosmos_indexing_policies': get_cosmos_indexing_policy_status(),
        'document_access_index_backfill': document_access_index_status,
        'settings': {
            'apply_cosmos_indexing_policies': maintenance_settings.get('apply_cosmos_indexing_policies'),
            'cosmos_indexing_policy_apply_setting': COSMOS_INDEXING_POLICY_APPLY_SETTING,
            'run_document_access_index_backfill': maintenance_settings.get('run_document_access_index_backfill'),
            'document_access_index_auto_maintenance': maintenance_settings.get('document_access_index_auto_maintenance'),
            'document_access_index_active_interval_seconds': maintenance_settings.get('document_access_index_active_interval_seconds'),
            'document_access_index_backfill_setting': DOCUMENT_ACCESS_BACKFILL_ENABLED_SETTING,
        },
        'app_version': VERSION,
    }


def run_app_maintenance_once(
    triggered_by='manual',
    requested_by=None,
    settings=None,
    apply_indexing_policies=None,
    run_document_access_backfill=None,
    reset_document_access_backfill=False,
):
    """Run idempotent app maintenance tasks once and persist the outcome."""
    run_id = str(uuid.uuid4())
    started_at = time.perf_counter()
    try:
        maintenance_settings = get_app_maintenance_settings(settings or {})
        if apply_indexing_policies is None:
            apply_indexing_policies = maintenance_settings.get('apply_cosmos_indexing_policies', False)
        if run_document_access_backfill is None:
            run_document_access_backfill = maintenance_settings.get('run_document_access_index_backfill', False)
        _record_started(run_id, triggered_by, requested_by)
        log_event(
            '[AppMaintenance] Maintenance run started.',
            extra={'run_id': run_id, 'triggered_by': triggered_by, 'requested_by': requested_by},
            level=logging.INFO,
        )
        cache_version_results = initialize_cache_version_documents()
        indexing_policy_results = run_cosmos_indexing_policy_maintenance(
            apply_changes=bool(apply_indexing_policies),
        )
        document_access_backfill_results = run_document_access_index_backfill_maintenance(
            settings=settings,
            run_backfill=bool(run_document_access_backfill),
            reset=bool(reset_document_access_backfill),
            batch_size=maintenance_settings.get('document_access_index_backfill_batch_size'),
            repair_batch_size=maintenance_settings.get('document_access_index_repair_batch_size'),
        )
        steps = [
            {
                'name': 'initialize_cache_version_documents',
                'status': 'succeeded',
                'results': cache_version_results,
            },
            {
                'name': 'cosmos_indexing_policy_maintenance',
                'status': 'succeeded' if indexing_policy_results.get('success') else 'failed',
                'apply_requested': bool(apply_indexing_policies),
                'results': indexing_policy_results,
            },
            {
                'name': 'document_access_index_backfill',
                'status': 'succeeded' if document_access_backfill_results.get('success') else 'failed',
                'run_requested': bool(run_document_access_backfill),
                'reset_requested': bool(reset_document_access_backfill),
                'results': document_access_backfill_results,
            },
        ]
        overall_success = all(step.get('status') == 'succeeded' for step in steps)
        state = _record_completed(run_id, started_at, triggered_by, requested_by, steps)
        log_event(
            '[AppMaintenance] Maintenance run completed.',
            extra={
                'run_id': run_id,
                'triggered_by': triggered_by,
                'duration_ms': state.get('last_duration_ms'),
                'success': overall_success,
            },
            level=logging.INFO,
        )
        return {
            'success': overall_success,
            'run_id': run_id,
            'state': state,
            'steps': steps,
            'error': None if overall_success else 'One or more maintenance steps failed.',
        }
    except Exception as ex:
        try:
            state = _record_failed(run_id, started_at, triggered_by, requested_by, ex)
        except Exception as state_error:
            state = {
                'last_status': 'failed',
                'last_error': 'Failed to record maintenance state.',
            }
            log_event(
                '[AppMaintenance] Failed to record maintenance failure state.',
                extra={
                    'run_id': run_id,
                    'triggered_by': triggered_by,
                    'error': str(state_error),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
        log_event(
            '[AppMaintenance] Maintenance run failed.',
            extra={'run_id': run_id, 'triggered_by': triggered_by, 'error': str(ex)},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return {
            'success': False,
            'run_id': run_id,
            'state': state,
            'error': str(ex),
        }
