# functions_document_access_index.py
"""Document access index projection helpers for Cosmos-backed document reads."""

import copy
import hashlib
import json
import logging
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from time import perf_counter

import app_settings_cache
from azure.core import MatchConditions
from config import (
    cosmos_document_access_index_container,
    cosmos_groups_container,
    cosmos_group_documents_container,
    cosmos_group_documents_container_name,
    cosmos_public_workspaces_container,
    cosmos_public_documents_container,
    cosmos_public_documents_container_name,
    cosmos_settings_container,
    cosmos_user_settings_container,
    cosmos_user_documents_container,
    cosmos_user_documents_container_name,
)
from functions_appinsights import log_event
from functions_settings import get_settings


DOCUMENT_ACCESS_INDEX_TYPE = 'document_access_index'
DOCUMENT_ACCESS_REPAIR_TYPE = 'document_access_index_repair'
DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_TYPE = 'document_access_index_repair_backlog_state'
DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID = 'document_access_index_repair_backlog_state'
DOCUMENT_ACCESS_BACKFILL_STATE_TYPE = 'document_access_index_backfill_state'
DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID = 'document_access_index_backfill_state'
DOCUMENT_ACCESS_SHADOW_STATE_TYPE = 'document_access_index_shadow_validation_state'
DOCUMENT_ACCESS_SHADOW_STATE_DOC_ID = 'document_access_index_shadow_validation_state'
DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION = 2

DOCUMENT_ACCESS_SCOPE_PERSONAL = 'personal'
DOCUMENT_ACCESS_SCOPE_GROUP = 'group'
DOCUMENT_ACCESS_SCOPE_PUBLIC = 'public'
DOCUMENT_ACCESS_PRINCIPAL_USER = 'user'

DOCUMENT_ACCESS_OPERATION_UPSERT = 'upsert'
DOCUMENT_ACCESS_OPERATION_DELETE = 'delete'

DOCUMENT_ACCESS_APPROVAL_APPROVED = 'approved'
DOCUMENT_ACCESS_APPROVAL_NOT_APPROVED = 'not_approved'

DOCUMENT_ACCESS_BACKFILL_ENABLED_SETTING = 'enable_startup_document_access_index_backfill'
DOCUMENT_ACCESS_BACKFILL_BATCH_SIZE_SETTING = 'document_access_index_backfill_batch_size'
DOCUMENT_ACCESS_REPAIR_BATCH_SIZE_SETTING = 'document_access_index_repair_batch_size'
DOCUMENT_ACCESS_ACTIVE_MAINTENANCE_INTERVAL_SETTING = 'document_access_index_active_maintenance_interval_seconds'
DOCUMENT_ACCESS_CACHE_ENABLED_SETTING = 'enable_document_access_index_cache'
DOCUMENT_ACCESS_CACHE_TTL_SECONDS_SETTING = 'document_access_index_cache_ttl_seconds'
DOCUMENT_ACCESS_DEFAULT_BACKFILL_BATCH_SIZE = 200
DOCUMENT_ACCESS_MAX_BACKFILL_BATCH_SIZE = 1000
DOCUMENT_ACCESS_DEFAULT_REPAIR_BATCH_SIZE = 100
DOCUMENT_ACCESS_MAX_REPAIR_BATCH_SIZE = 500
DOCUMENT_ACCESS_DEFAULT_CACHE_TTL_SECONDS = 900
DOCUMENT_ACCESS_MIN_CACHE_TTL_SECONDS = 60
DOCUMENT_ACCESS_MAX_CACHE_TTL_SECONDS = 900
DOCUMENT_ACCESS_CACHE_VERSION_MIN_TTL_SECONDS = 3600
DOCUMENT_ACCESS_CACHE_VERSION_MAX_TTL_SECONDS = 86400
DOCUMENT_ACCESS_CACHE_VERSION_TTL_MULTIPLIER = 4
DOCUMENT_ACCESS_CACHE_VERSION_HYGIENE_BATCH_SIZE = 100
DOCUMENT_ACCESS_BOUNDED_CATALOG_MAX_SCOPES = 25
DOCUMENT_ACCESS_CACHE_VERSION_HYGIENE_MAX_SCAN_ITERATIONS = 5
DOCUMENT_ACCESS_CACHE_KEY_PREFIX = 'DAI_LIST_CACHE'
DOCUMENT_ACCESS_CACHE_VERSION_KEY_PREFIX = 'DAI_LIST_CACHE_VERSION'
DOCUMENT_ACCESS_ARCHIVED_REVISION_BLOB_PATH_MODE = 'archived_revision'
DOCUMENT_ACCESS_SHADOW_MAX_SAMPLE_IDS = 20
DOCUMENT_ACCESS_SHADOW_METRIC_WINDOWS_MINUTES = (5, 15)
DOCUMENT_ACCESS_SHADOW_METRIC_RETENTION_MINUTES = 60
DOCUMENT_ACCESS_SHADOW_METRIC_MAX_SAMPLES = 1000
DOCUMENT_ACCESS_SHADOW_STATE_WRITE_MAX_RETRIES = 5
DOCUMENT_ACCESS_READ_METRIC_WINDOWS_MINUTES = (5, 15, 60)
DOCUMENT_ACCESS_READ_METRIC_RETENTION_MINUTES = 60
DOCUMENT_ACCESS_READ_METRIC_MAX_SAMPLES = 2000
DOCUMENT_ACCESS_CACHE_METRIC_WINDOWS_MINUTES = (5, 15, 60)
DOCUMENT_ACCESS_CACHE_METRIC_RETENTION_MINUTES = 60
DOCUMENT_ACCESS_CACHE_METRIC_MAX_SAMPLES = 2000
DOCUMENT_ACCESS_STATE_READ_TTL_SECONDS = 30
DOCUMENT_ACCESS_BACKFILL_READY_STATUSES = {'succeeded', 'succeeded_with_errors'}
DOCUMENT_ACCESS_BACKFILL_COMPLETE_STATUSES = DOCUMENT_ACCESS_BACKFILL_READY_STATUSES | {'skipped_completed'}

DOCUMENT_ACCESS_SOURCE_SCOPES = (
    DOCUMENT_ACCESS_SCOPE_PERSONAL,
    DOCUMENT_ACCESS_SCOPE_GROUP,
    DOCUMENT_ACCESS_SCOPE_PUBLIC,
)

_document_access_read_metric_lock = threading.Lock()
_document_access_read_metric_samples = []
_document_access_cache_metric_lock = threading.Lock()
_document_access_state_cache = {}
_document_access_state_cache_lock = threading.Lock()
_document_access_cache_metric_samples = []
_document_access_cache_epoch_lock = threading.Lock()
_document_access_cache_process_epoch = uuid.uuid4().hex
_document_access_cache_local_generation = 0


class DocumentAccessIndexCacheInvalidationError(RuntimeError):
    """Raised when DAI cache scope invalidation fails after projection mutation."""

    def __init__(self, operation, status, scope_keys=None):
        super().__init__(
            'Document access index cache invalidation failed '
            f'for {operation}: {status or "unknown"}'
        )
        self.operation = operation
        self.status = status
        self.scope_keys = list(scope_keys or [])


class DocumentAccessIndexProjectionMutationError(RuntimeError):
    """Raised when projection mutation fails after affected cache scopes are known."""

    def __init__(self, operation, error, scope_keys=None):
        super().__init__(str(error))
        self.operation = operation
        self.original_error = error
        self.scope_keys = list(scope_keys or [])


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_datetime(value):
    if not value:
        return None
    try:
        parsed_value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed_value.tzinfo is None:
        parsed_value = parsed_value.replace(tzinfo=timezone.utc)
    return parsed_value.astimezone(timezone.utc)


def _get_cached_document_access_state(doc_id):
    now = perf_counter()
    with _document_access_state_cache_lock:
        cached_state = _document_access_state_cache.get(doc_id)
        if not cached_state:
            return False, None
        if cached_state.get('expires_at', 0) <= now:
            _document_access_state_cache.pop(doc_id, None)
            return False, None
        return True, copy.deepcopy(cached_state.get('value'))


def _set_cached_document_access_state(doc_id, value):
    with _document_access_state_cache_lock:
        _document_access_state_cache[doc_id] = {
            'value': copy.deepcopy(value),
            'expires_at': perf_counter() + DOCUMENT_ACCESS_STATE_READ_TTL_SECONDS,
        }


def _normalize_positive_int(value, default_value, min_value=1, max_value=1000):
    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        normalized_value = default_value
    return min(max(normalized_value, min_value), max_value)


def _calculate_document_access_cache_version_ttl_seconds(cache_ttl_seconds):
    normalized_cache_ttl = _normalize_positive_int(
        cache_ttl_seconds,
        DOCUMENT_ACCESS_DEFAULT_CACHE_TTL_SECONDS,
        min_value=DOCUMENT_ACCESS_MIN_CACHE_TTL_SECONDS,
        max_value=DOCUMENT_ACCESS_MAX_CACHE_TTL_SECONDS,
    )
    return min(
        max(
            normalized_cache_ttl * DOCUMENT_ACCESS_CACHE_VERSION_TTL_MULTIPLIER,
            DOCUMENT_ACCESS_CACHE_VERSION_MIN_TTL_SECONDS,
        ),
        DOCUMENT_ACCESS_CACHE_VERSION_MAX_TTL_SECONDS,
    )


def _safe_float(value):
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_metric(value, digits=3):
    normalized_value = _safe_float(value)
    if normalized_value is None:
        return None
    return round(normalized_value, digits)


def _sum_metric_values(items, key):
    values = [
        _safe_float(item.get(key))
        for item in items or []
        if _safe_float(item.get(key)) is not None
    ]
    if not values:
        return None
    return _round_metric(sum(values))


def _average_metric_values(items, key):
    values = [
        _safe_float(item.get(key))
        for item in items or []
        if _safe_float(item.get(key)) is not None
    ]
    if not values:
        return None
    return _round_metric(sum(values) / len(values))


def _sum_int_values(items, key):
    total = 0
    for item in items or []:
        try:
            total += int(item.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _safe_int(value, default_value=0):
    try:
        return int(value or default_value)
    except (TypeError, ValueError):
        return default_value


def _get_header_value(headers, name):
    if not hasattr(headers, 'get'):
        return None
    return headers.get(name) or headers.get(name.lower()) or headers.get(name.upper())


def _metric_delta(source_value, projection_value):
    source_metric = _safe_float(source_value)
    projection_metric = _safe_float(projection_value)
    if source_metric is None or projection_metric is None:
        return None
    return _round_metric(source_metric - projection_metric)


def _metric_percent(numerator, denominator):
    try:
        denominator_value = float(denominator or 0)
        if denominator_value <= 0:
            return None
        return _round_metric((float(numerator or 0) / denominator_value) * 100)
    except (TypeError, ValueError):
        return None


def _percentile_metric_value(items, key, percentile):
    values = sorted(
        _safe_float(item.get(key))
        for item in items or []
        if _safe_float(item.get(key)) is not None
    )
    if not values:
        return None
    index = int(round((len(values) - 1) * percentile))
    return _round_metric(values[min(max(index, 0), len(values) - 1)])


def _empty_read_metric_window(window_minutes):
    return {
        'window_minutes': window_minutes,
        'sample_count': 0,
        'served_from_index_count': 0,
        'served_from_cache_count': 0,
        'source_fallback_count': 0,
        'query_failed_count': 0,
        'fallback_rate_percent': None,
        'cache_hit_rate_percent': None,
        'request_charge': None,
        'elapsed_ms_avg': None,
        'elapsed_ms_p95': None,
        'item_count': 0,
        'page_count': 0,
        'operation_counts': {},
        'status_counts': {},
        'first_checked_at': None,
        'last_checked_at': None,
    }


def _prune_read_metric_samples(samples, now):
    cutoff = now - timedelta(minutes=DOCUMENT_ACCESS_READ_METRIC_RETENTION_MINUTES)
    pruned_samples = []
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        checked_at = _parse_utc_datetime(sample.get('checked_at'))
        if not checked_at or checked_at < cutoff:
            continue
        pruned_samples.append(copy.deepcopy(sample))

    pruned_samples.sort(key=lambda sample: sample.get('checked_at') or '')
    return pruned_samples[-DOCUMENT_ACCESS_READ_METRIC_MAX_SAMPLES:]


def _increment_count(counts, key):
    normalized_key = str(key or 'unknown').strip().lower() or 'unknown'
    counts[normalized_key] = int(counts.get(normalized_key) or 0) + 1


def _build_read_metric_window(samples, now, window_minutes):
    cutoff = now - timedelta(minutes=window_minutes)
    window_samples = [
        sample
        for sample in samples or []
        if (_parse_utc_datetime(sample.get('checked_at')) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    if not window_samples:
        return _empty_read_metric_window(window_minutes)

    served_samples = [
        sample
        for sample in window_samples
        if sample.get('served_from_index')
    ]
    operation_counts = {}
    status_counts = {}
    for sample in window_samples:
        _increment_count(operation_counts, sample.get('operation'))
        _increment_count(status_counts, sample.get('status'))

    source_fallback_count = sum(1 for sample in window_samples if sample.get('source_fallback'))
    served_from_cache_count = sum(1 for sample in served_samples if sample.get('served_from_cache'))
    return {
        'window_minutes': window_minutes,
        'sample_count': len(window_samples),
        'served_from_index_count': len(served_samples),
        'served_from_cache_count': served_from_cache_count,
        'source_fallback_count': source_fallback_count,
        'query_failed_count': sum(1 for sample in window_samples if sample.get('status') == 'query_failed'),
        'fallback_rate_percent': _metric_percent(source_fallback_count, len(window_samples)),
        'cache_hit_rate_percent': _metric_percent(served_from_cache_count, len(served_samples)),
        'request_charge': _sum_metric_values(served_samples, 'request_charge'),
        'elapsed_ms_avg': _average_metric_values(served_samples, 'elapsed_ms'),
        'elapsed_ms_p95': _percentile_metric_value(served_samples, 'elapsed_ms', 0.95),
        'item_count': _sum_int_values(served_samples, 'item_count'),
        'page_count': _sum_int_values(served_samples, 'page_count'),
        'operation_counts': operation_counts,
        'status_counts': status_counts,
        'first_checked_at': window_samples[0].get('checked_at'),
        'last_checked_at': window_samples[-1].get('checked_at'),
    }


def _build_read_metrics(samples, now):
    fallback_samples = [
        sample
        for sample in samples or []
        if sample.get('source_fallback')
    ]
    return {
        'updated_at': now.isoformat(),
        'retention_minutes': DOCUMENT_ACCESS_READ_METRIC_RETENTION_MINUTES,
        'sample_limit': DOCUMENT_ACCESS_READ_METRIC_MAX_SAMPLES,
        'sample_count': len(samples or []),
        'last_sample': copy.deepcopy(samples[-1]) if samples else None,
        'last_fallback_sample': copy.deepcopy(fallback_samples[-1]) if fallback_samples else None,
        'windows': {
            f'{window_minutes}m': _build_read_metric_window(samples, now, window_minutes)
            for window_minutes in DOCUMENT_ACCESS_READ_METRIC_WINDOWS_MINUTES
        },
    }


def _record_document_access_read_metric(
    operation,
    source_scope,
    status,
    served_from_index,
    diagnostics=None,
    scope_key_count=0,
    served_from_cache=False,
    cache_status=None,
    error=None,
):
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    sample = {
        'checked_at': _utc_now_iso(),
        'operation': str(operation or 'document_list').strip().lower(),
        'source_scope': str(source_scope or '').strip().lower(),
        'status': str(status or 'unknown').strip().lower() or 'unknown',
        'served_from_index': bool(served_from_index),
        'served_from_cache': bool(served_from_cache),
        'source_fallback': not bool(served_from_index),
        'cache_status': str(cache_status or '').strip().lower() or None,
        'request_charge': _round_metric(diagnostics.get('request_charge')),
        'elapsed_ms': _round_metric(diagnostics.get('elapsed_ms')),
        'item_count': _safe_int(diagnostics.get('item_count')),
        'page_count': _safe_int(diagnostics.get('page_count')),
        'scope_key_count': _safe_int(scope_key_count),
    }
    if error:
        sample['error'] = str(error)

    with _document_access_read_metric_lock:
        now = datetime.now(timezone.utc)
        samples = _prune_read_metric_samples(_document_access_read_metric_samples, now)
        samples.append(sample)
        del samples[:-DOCUMENT_ACCESS_READ_METRIC_MAX_SAMPLES]
        _document_access_read_metric_samples[:] = samples
    return sample


def get_document_access_index_read_metrics():
    """Return lightweight in-process rolling metrics for production DAI reads."""
    with _document_access_read_metric_lock:
        samples = copy.deepcopy(_document_access_read_metric_samples)
    now = datetime.now(timezone.utc)
    samples = _prune_read_metric_samples(samples, now)
    return _build_read_metrics(samples, now)


def _empty_cache_metric_window(window_minutes):
    return {
        'window_minutes': window_minutes,
        'sample_count': 0,
        'hit_count': 0,
        'miss_count': 0,
        'bypass_count': 0,
        'write_count': 0,
        'invalidation_count': 0,
        'error_count': 0,
        'hit_rate_percent': None,
        'operation_counts': {},
        'event_counts': {},
        'reason_counts': {},
        'first_checked_at': None,
        'last_checked_at': None,
    }


def _prune_cache_metric_samples(samples, now):
    cutoff = now - timedelta(minutes=DOCUMENT_ACCESS_CACHE_METRIC_RETENTION_MINUTES)
    pruned_samples = []
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        checked_at = _parse_utc_datetime(sample.get('checked_at'))
        if not checked_at or checked_at < cutoff:
            continue
        pruned_samples.append(copy.deepcopy(sample))

    pruned_samples.sort(key=lambda sample: sample.get('checked_at') or '')
    return pruned_samples[-DOCUMENT_ACCESS_CACHE_METRIC_MAX_SAMPLES:]


def _cache_metric_matches(sample, event_types):
    return str(sample.get('event_type') or '').strip().lower() in event_types


def _build_cache_metric_window(samples, now, window_minutes):
    cutoff = now - timedelta(minutes=window_minutes)
    window_samples = [
        sample
        for sample in samples or []
        if (_parse_utc_datetime(sample.get('checked_at')) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    if not window_samples:
        return _empty_cache_metric_window(window_minutes)

    operation_counts = {}
    event_counts = {}
    reason_counts = {}
    for sample in window_samples:
        _increment_count(operation_counts, sample.get('operation'))
        _increment_count(event_counts, sample.get('event_type'))
        _increment_count(reason_counts, sample.get('reason'))

    hit_count = sum(1 for sample in window_samples if _cache_metric_matches(sample, {'hit'}))
    miss_count = sum(1 for sample in window_samples if _cache_metric_matches(sample, {'miss'}))
    bypass_count = sum(1 for sample in window_samples if _cache_metric_matches(sample, {'bypass'}))
    write_count = sum(1 for sample in window_samples if _cache_metric_matches(sample, {'write'}))
    invalidation_count = sum(1 for sample in window_samples if _cache_metric_matches(sample, {'invalidate'}))
    error_count = sum(
        1
        for sample in window_samples
        if _cache_metric_matches(sample, {'read_failed', 'write_failed', 'version_read_failed', 'invalidate_failed'})
    )
    return {
        'window_minutes': window_minutes,
        'sample_count': len(window_samples),
        'hit_count': hit_count,
        'miss_count': miss_count,
        'bypass_count': bypass_count,
        'write_count': write_count,
        'invalidation_count': invalidation_count,
        'error_count': error_count,
        'hit_rate_percent': _metric_percent(hit_count, hit_count + miss_count),
        'operation_counts': operation_counts,
        'event_counts': event_counts,
        'reason_counts': reason_counts,
        'first_checked_at': window_samples[0].get('checked_at'),
        'last_checked_at': window_samples[-1].get('checked_at'),
    }


def _build_cache_metrics(samples, now):
    error_samples = [
        sample
        for sample in samples or []
        if str(sample.get('event_type') or '').strip().lower().endswith('_failed')
    ]
    invalidation_samples = [
        sample
        for sample in samples or []
        if str(sample.get('event_type') or '').strip().lower() == 'invalidate'
    ]
    return {
        'updated_at': now.isoformat(),
        'retention_minutes': DOCUMENT_ACCESS_CACHE_METRIC_RETENTION_MINUTES,
        'sample_limit': DOCUMENT_ACCESS_CACHE_METRIC_MAX_SAMPLES,
        'sample_count': len(samples or []),
        'last_event': copy.deepcopy(samples[-1]) if samples else None,
        'last_error': copy.deepcopy(error_samples[-1]) if error_samples else None,
        'last_invalidation': copy.deepcopy(invalidation_samples[-1]) if invalidation_samples else None,
        'windows': {
            f'{window_minutes}m': _build_cache_metric_window(samples, now, window_minutes)
            for window_minutes in DOCUMENT_ACCESS_CACHE_METRIC_WINDOWS_MINUTES
        },
    }


def _record_document_access_cache_metric(
    event_type,
    operation=None,
    source_scope=None,
    scope_key_count=0,
    reason=None,
    elapsed_ms=None,
    ttl_seconds=None,
    error=None,
):
    sample = {
        'checked_at': _utc_now_iso(),
        'event_type': str(event_type or 'unknown').strip().lower() or 'unknown',
        'operation': str(operation or 'document_list').strip().lower() or 'document_list',
        'source_scope': str(source_scope or '').strip().lower(),
        'scope_key_count': _safe_int(scope_key_count),
        'reason': str(reason or '').strip().lower() or None,
        'elapsed_ms': _round_metric(elapsed_ms),
        'ttl_seconds': _safe_int(ttl_seconds),
    }
    if error:
        sample['error_type'] = type(error).__name__

    with _document_access_cache_metric_lock:
        now = datetime.now(timezone.utc)
        samples = _prune_cache_metric_samples(_document_access_cache_metric_samples, now)
        samples.append(sample)
        del samples[:-DOCUMENT_ACCESS_CACHE_METRIC_MAX_SAMPLES]
        _document_access_cache_metric_samples[:] = samples
    return sample


def get_document_access_index_cache_metrics():
    """Return lightweight in-process rolling metrics for Redis DAI list caching."""
    with _document_access_cache_metric_lock:
        samples = copy.deepcopy(_document_access_cache_metric_samples)
    now = datetime.now(timezone.utc)
    samples = _prune_cache_metric_samples(samples, now)
    return _build_cache_metrics(samples, now)


def get_document_access_index_settings(settings=None):
    """Normalize document access index feature flags."""
    if settings is None:
        try:
            settings = get_settings()
        except Exception as exc:
            log_event(
                '[DocumentAccessIndex] Settings could not be loaded; DAI reads will use source fallback until settings are available.',
                extra={'error': str(exc)},
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            settings = {}
    if not isinstance(settings, dict):
        log_event(
            '[DocumentAccessIndex] Settings payload was invalid; DAI reads will use source fallback until settings are available.',
            extra={'settings_type': type(settings).__name__},
            level=logging.WARNING,
        )
        settings = {}
    cache_ttl_seconds = _normalize_positive_int(
        settings.get(DOCUMENT_ACCESS_CACHE_TTL_SECONDS_SETTING),
        DOCUMENT_ACCESS_DEFAULT_CACHE_TTL_SECONDS,
        min_value=DOCUMENT_ACCESS_MIN_CACHE_TTL_SECONDS,
        max_value=DOCUMENT_ACCESS_MAX_CACHE_TTL_SECONDS,
    )
    return {
        'container_enabled': True,
        'write_through_enabled': True,
        'reads_enabled': True,
        'shadow_validation_enabled': bool(settings.get('enable_document_access_index_shadow_validation', False)),
        'startup_backfill_enabled': True,
        'backfill_batch_size': _normalize_positive_int(
            settings.get(DOCUMENT_ACCESS_BACKFILL_BATCH_SIZE_SETTING),
            DOCUMENT_ACCESS_DEFAULT_BACKFILL_BATCH_SIZE,
            max_value=DOCUMENT_ACCESS_MAX_BACKFILL_BATCH_SIZE,
        ),
        'repair_batch_size': _normalize_positive_int(
            settings.get(DOCUMENT_ACCESS_REPAIR_BATCH_SIZE_SETTING),
            DOCUMENT_ACCESS_DEFAULT_REPAIR_BATCH_SIZE,
            max_value=DOCUMENT_ACCESS_MAX_REPAIR_BATCH_SIZE,
        ),
        'cache_enabled': bool(settings.get(DOCUMENT_ACCESS_CACHE_ENABLED_SETTING, True)),
        'redis_cache_configured': bool(settings.get('enable_redis_cache', False)),
        'cache_ttl_seconds': cache_ttl_seconds,
        'cache_version_ttl_seconds': _calculate_document_access_cache_version_ttl_seconds(cache_ttl_seconds),
    }


def is_document_access_shadow_validation_enabled(settings=None):
    """Return True when shadow validation should collect comparison diagnostics."""
    normalized_settings = get_document_access_index_settings(settings)
    return (
        bool(normalized_settings.get('container_enabled'))
        and bool(normalized_settings.get('shadow_validation_enabled'))
    )


def is_document_access_index_reads_enabled(settings=None):
    """Return True when the default DAI read path is enabled."""
    normalized_settings = get_document_access_index_settings(settings)
    return (
        bool(normalized_settings.get('container_enabled'))
        and bool(normalized_settings.get('write_through_enabled'))
        and bool(normalized_settings.get('reads_enabled'))
    )


def query_items_with_cosmos_diagnostics(container, diagnostics_label, collect_diagnostics=True, **query_kwargs):
    """Run a Cosmos query and optionally capture elapsed time and request charge."""
    if not collect_diagnostics:
        return list(container.query_items(**query_kwargs)), None

    query_kwargs = copy.copy(query_kwargs)
    existing_response_hook = query_kwargs.get('response_hook')
    request_charge_total = 0.0
    has_request_charge = False
    page_count = 0
    activity_ids = []
    query_metrics = []

    def capture_response_headers(headers, response):
        nonlocal request_charge_total, has_request_charge, page_count
        if callable(existing_response_hook):
            existing_response_hook(headers, response)

        if hasattr(response, 'by_page'):
            return

        page_count += 1
        request_charge = _safe_float(_get_header_value(headers, 'x-ms-request-charge'))
        if request_charge is not None:
            request_charge_total += request_charge
            has_request_charge = True

        activity_id = _get_header_value(headers, 'x-ms-activity-id')
        if activity_id:
            activity_ids.append(str(activity_id))

        query_metric = _get_header_value(headers, 'x-ms-documentdb-query-metrics')
        if query_metric:
            query_metrics.append(str(query_metric))

    query_kwargs['populate_query_metrics'] = True
    query_kwargs['response_hook'] = capture_response_headers
    started_at = perf_counter()
    items = list(container.query_items(**query_kwargs))
    elapsed_ms = _round_metric((perf_counter() - started_at) * 1000)
    diagnostics = {
        'label': diagnostics_label,
        'request_charge': _round_metric(request_charge_total) if has_request_charge else None,
        'elapsed_ms': elapsed_ms,
        'item_count': len(items),
        'page_count': page_count,
    }
    if activity_ids:
        diagnostics['activity_ids'] = activity_ids[:5]
    if query_metrics:
        diagnostics['query_metrics'] = query_metrics[:5]
    return items, diagnostics


def _combine_query_diagnostics(label, diagnostics_list):
    diagnostics_list = [diagnostics for diagnostics in diagnostics_list or [] if isinstance(diagnostics, dict)]
    request_charges = [
        _safe_float(diagnostics.get('request_charge'))
        for diagnostics in diagnostics_list
        if _safe_float(diagnostics.get('request_charge')) is not None
    ]
    elapsed_values = [
        _safe_float(diagnostics.get('elapsed_ms'))
        for diagnostics in diagnostics_list
        if _safe_float(diagnostics.get('elapsed_ms')) is not None
    ]
    return {
        'label': label,
        'request_charge': _round_metric(sum(request_charges)) if request_charges else None,
        'elapsed_ms': _round_metric(sum(elapsed_values)) if elapsed_values else None,
        'item_count': sum(int(diagnostics.get('item_count') or 0) for diagnostics in diagnostics_list),
        'page_count': sum(int(diagnostics.get('page_count') or 0) for diagnostics in diagnostics_list),
    }


def _build_shadow_metric_fields(source_query_metrics, projection_query_metrics, candidate_read_metrics=None):
    source_ru = _round_metric((source_query_metrics or {}).get('request_charge'))
    validation_index_ru = _round_metric((projection_query_metrics or {}).get('request_charge'))
    source_ms = _round_metric((source_query_metrics or {}).get('elapsed_ms'))
    validation_index_ms = _round_metric((projection_query_metrics or {}).get('elapsed_ms'))
    candidate_metrics_available = (
        isinstance(candidate_read_metrics, dict)
        and not candidate_read_metrics.get('partial_failure')
        and not candidate_read_metrics.get('errors')
    )
    candidate_read_ru = (
        _round_metric(candidate_read_metrics.get('request_charge'))
        if candidate_metrics_available
        else None
    )
    candidate_read_ms = (
        _round_metric(candidate_read_metrics.get('elapsed_ms'))
        if candidate_metrics_available
        else None
    )
    return {
        'source_query_ru': source_ru,
        'projection_query_ru': validation_index_ru,
        'validation_index_ru': validation_index_ru,
        'candidate_read_ru': candidate_read_ru,
        'estimated_ru_savings': _metric_delta(source_ru, validation_index_ru),
        'estimated_wave5_ru_savings': _metric_delta(source_ru, candidate_read_ru),
        'shadow_overhead_ru': validation_index_ru,
        'source_query_ms': source_ms,
        'projection_query_ms': validation_index_ms,
        'validation_index_ms': validation_index_ms,
        'candidate_read_ms': candidate_read_ms,
        'estimated_ms_savings': _metric_delta(source_ms, validation_index_ms),
        'estimated_wave5_ms_savings': _metric_delta(source_ms, candidate_read_ms),
        'shadow_overhead_ms': validation_index_ms,
        'source_query_item_count': int((source_query_metrics or {}).get('item_count') or 0),
        'projection_query_item_count': int((projection_query_metrics or {}).get('item_count') or 0),
        'candidate_read_item_count': int((candidate_read_metrics or {}).get('item_count') or 0),
        'source_query_page_count': int((source_query_metrics or {}).get('page_count') or 0),
        'projection_query_page_count': int((projection_query_metrics or {}).get('page_count') or 0),
        'candidate_read_page_count': int((candidate_read_metrics or {}).get('page_count') or 0),
    }


def _is_container_enabled(settings=None):
    normalized_settings = get_document_access_index_settings(settings)
    return normalized_settings.get('container_enabled')


def _is_write_through_enabled(settings=None, force=False):
    normalized_settings = get_document_access_index_settings(settings)
    if force:
        return normalized_settings.get('container_enabled')
    return normalized_settings.get('container_enabled') and normalized_settings.get('write_through_enabled')


def _is_not_found_error(exc):
    return getattr(exc, 'status_code', None) == 404


def _is_write_conflict_error(exc):
    return getattr(exc, 'status_code', None) in (409, 412)


def _safe_id_part(value):
    normalized = str(value or '').strip()
    normalized = re.sub(r'[^A-Za-z0-9_.:-]+', '_', normalized)
    return normalized or 'none'


def build_document_access_scope_key(scope_type, scope_id):
    """Build the access-index partition key for a user, group, or public workspace scope."""
    normalized_scope_type = str(scope_type or '').strip().lower()
    normalized_scope_id = str(scope_id or '').strip()
    if not normalized_scope_type or not normalized_scope_id:
        return None
    return f'{normalized_scope_type}:{normalized_scope_id}'


def _document_access_cache_hash(value):
    serialized_value = json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(serialized_value.encode('utf-8')).hexdigest()


def build_document_access_cache_scope_hash(scope_key):
    """Return the stable Redis DAI cache hash for a user/group/public scope key."""
    return _document_access_cache_hash({'scope_key': scope_key})


def _document_access_cache_version_key(scope_key):
    scope_hash = build_document_access_cache_scope_hash(scope_key)
    return f'{DOCUMENT_ACCESS_CACHE_VERSION_KEY_PREFIX}:{scope_hash}'


def _document_access_cache_entry_key(operation, source_scope, scope_versions, key_payload):
    cache_hash = _document_access_cache_hash({
        'operation': operation,
        'source_scope': source_scope,
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        'local_epoch': _get_document_access_cache_local_epoch(),
        'scope_versions': scope_versions,
        'key_payload': key_payload or {},
    })
    return f'{DOCUMENT_ACCESS_CACHE_KEY_PREFIX}:{operation}:{source_scope}:{cache_hash}'


def _get_document_access_cache_local_epoch():
    with _document_access_cache_epoch_lock:
        return f'{_document_access_cache_process_epoch}:{_document_access_cache_local_generation}'


def _bump_document_access_cache_local_epoch():
    global _document_access_cache_local_generation
    with _document_access_cache_epoch_lock:
        _document_access_cache_local_generation += 1
        return f'{_document_access_cache_process_epoch}:{_document_access_cache_local_generation}'


def _decode_cache_json(raw_value):
    if raw_value is None:
        return None
    if isinstance(raw_value, bytes):
        raw_value = raw_value.decode('utf-8')
    return json.loads(raw_value)


def _get_document_access_cache_client(
    normalized_settings,
    operation,
    source_scope,
    scope_key_count,
    require_cache_enabled=True,
):
    if require_cache_enabled and not normalized_settings.get('cache_enabled'):
        _record_document_access_cache_metric(
            'bypass',
            operation=operation,
            source_scope=source_scope,
            scope_key_count=scope_key_count,
            reason='disabled',
        )
        return None

    redis_client = app_settings_cache.get_app_cache_redis_client()
    if redis_client is None:
        _record_document_access_cache_metric(
            'bypass',
            operation=operation,
            source_scope=source_scope,
            scope_key_count=scope_key_count,
            reason='redis_unavailable',
        )
        return None
    return redis_client


def _set_document_access_cache_version_key_if_missing(redis_client, version_key, ttl_seconds):
    try:
        return redis_client.set(version_key, 0, ex=ttl_seconds, nx=True)
    except TypeError:
        created = redis_client.setnx(version_key, 0)
        if created:
            redis_client.expire(version_key, ttl_seconds)
        return created


def _refresh_document_access_cache_version_key_ttl(redis_client, version_key, ttl_seconds):
    return redis_client.expire(version_key, ttl_seconds)


def _read_document_access_cache_scope_versions(redis_client, scope_keys, operation, source_scope, version_ttl_seconds):
    scope_versions = []
    started_at = perf_counter()
    try:
        for scope_key in sorted(set(scope_keys or [])):
            version_key = _document_access_cache_version_key(scope_key)
            version_value = redis_client.get(version_key)
            if version_value is None:
                created = _set_document_access_cache_version_key_if_missing(
                    redis_client,
                    version_key,
                    version_ttl_seconds,
                )
                if created:
                    version_value = 0
                else:
                    version_value = redis_client.get(version_key)
                    if version_value is None:
                        _set_document_access_cache_version_key_if_missing(
                            redis_client,
                            version_key,
                            version_ttl_seconds,
                        )
                        version_value = 0
            else:
                _refresh_document_access_cache_version_key_ttl(
                    redis_client,
                    version_key,
                    version_ttl_seconds,
                )
            scope_versions.append({
                'scope_hash': build_document_access_cache_scope_hash(scope_key),
                'version': _safe_int(version_value),
            })
    except Exception as exc:
        _record_document_access_cache_metric(
            'version_read_failed',
            operation=operation,
            source_scope=source_scope,
            scope_key_count=len(scope_keys or []),
            reason='redis_error',
            elapsed_ms=(perf_counter() - started_at) * 1000,
            error=exc,
        )
        log_event(
            '[DocumentAccessIndexCache] Failed to read Redis DAI cache scope versions; DAI query will run uncached.',
            extra={
                'operation': operation,
                'source_scope': source_scope,
                'scope_key_count': len(scope_keys or []),
                'error_type': type(exc).__name__,
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None
    return scope_versions


def _build_document_access_cache_context(operation, source_scope, scope_keys, key_payload, normalized_settings):
    redis_client = _get_document_access_cache_client(
        normalized_settings,
        operation,
        source_scope,
        len(scope_keys or []),
    )
    if redis_client is None:
        return None

    scope_versions = _read_document_access_cache_scope_versions(
        redis_client,
        scope_keys,
        operation,
        source_scope,
        normalized_settings.get('cache_version_ttl_seconds'),
    )
    if scope_versions is None:
        return None

    return {
        'redis_client': redis_client,
        'cache_key': _document_access_cache_entry_key(operation, source_scope, scope_versions, key_payload),
        'operation': operation,
        'source_scope': source_scope,
        'scope_key_count': len(scope_keys or []),
        'ttl_seconds': normalized_settings.get('cache_ttl_seconds'),
    }


def _try_get_document_access_cache_entry(cache_context):
    if not cache_context:
        return None

    started_at = perf_counter()
    operation = cache_context.get('operation')
    source_scope = cache_context.get('source_scope')
    scope_key_count = cache_context.get('scope_key_count')
    try:
        cached_value = cache_context['redis_client'].get(cache_context['cache_key'])
    except Exception as exc:
        _record_document_access_cache_metric(
            'read_failed',
            operation=operation,
            source_scope=source_scope,
            scope_key_count=scope_key_count,
            reason='redis_error',
            elapsed_ms=(perf_counter() - started_at) * 1000,
            error=exc,
        )
        log_event(
            '[DocumentAccessIndexCache] Redis DAI cache read failed; DAI query will run uncached.',
            extra={
                'operation': operation,
                'source_scope': source_scope,
                'scope_key_count': scope_key_count,
                'error_type': type(exc).__name__,
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None

    elapsed_ms = (perf_counter() - started_at) * 1000
    if cached_value is None:
        _record_document_access_cache_metric(
            'miss',
            operation=operation,
            source_scope=source_scope,
            scope_key_count=scope_key_count,
            elapsed_ms=elapsed_ms,
        )
        return None

    try:
        payload = _decode_cache_json(cached_value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        _record_document_access_cache_metric(
            'read_failed',
            operation=operation,
            source_scope=source_scope,
            scope_key_count=scope_key_count,
            reason='decode_failed',
            elapsed_ms=elapsed_ms,
            error=exc,
        )
        return None

    _record_document_access_cache_metric(
        'hit',
        operation=operation,
        source_scope=source_scope,
        scope_key_count=scope_key_count,
        elapsed_ms=elapsed_ms,
        ttl_seconds=cache_context.get('ttl_seconds'),
    )
    return payload if isinstance(payload, dict) else None


def _try_set_document_access_cache_entry(cache_context, payload):
    if not cache_context:
        return False

    started_at = perf_counter()
    operation = cache_context.get('operation')
    source_scope = cache_context.get('source_scope')
    scope_key_count = cache_context.get('scope_key_count')
    ttl_seconds = _safe_int(cache_context.get('ttl_seconds'), DOCUMENT_ACCESS_DEFAULT_CACHE_TTL_SECONDS)
    try:
        cache_context['redis_client'].setex(
            cache_context['cache_key'],
            ttl_seconds,
            json.dumps(payload or {}, default=str),
        )
    except Exception as exc:
        _record_document_access_cache_metric(
            'write_failed',
            operation=operation,
            source_scope=source_scope,
            scope_key_count=scope_key_count,
            reason='redis_error',
            elapsed_ms=(perf_counter() - started_at) * 1000,
            ttl_seconds=ttl_seconds,
            error=exc,
        )
        log_event(
            '[DocumentAccessIndexCache] Redis DAI cache write failed; DAI read result was still returned.',
            extra={
                'operation': operation,
                'source_scope': source_scope,
                'scope_key_count': scope_key_count,
                'error_type': type(exc).__name__,
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return False

    _record_document_access_cache_metric(
        'write',
        operation=operation,
        source_scope=source_scope,
        scope_key_count=scope_key_count,
        elapsed_ms=(perf_counter() - started_at) * 1000,
        ttl_seconds=ttl_seconds,
    )
    return True


def _document_access_scope_keys_from_document_item(document_item):
    try:
        rows = build_document_access_index_rows(document_item)
    except Exception:
        rows = []
    return sorted({
        row.get('scope_key')
        for row in rows
        if row.get('scope_key')
    })


def invalidate_document_access_index_cache_scope_keys(scope_keys, reason=None, settings=None):
    """Bump Redis-only DAI cache versions for affected access scopes."""
    normalized_scope_keys = sorted({
        str(scope_key or '').strip()
        for scope_key in scope_keys or []
        if str(scope_key or '').strip()
    })
    if not normalized_scope_keys:
        return {
            'success': True,
            'status': 'skipped_no_scope_keys',
            'invalidated_count': 0,
        }

    operation = 'scope_invalidation'
    source_scope = 'mixed'
    normalized_settings = get_document_access_index_settings(settings)
    redis_client = _get_document_access_cache_client(
        normalized_settings,
        operation,
        source_scope,
        len(normalized_scope_keys),
        require_cache_enabled=False,
    )
    if redis_client is None:
        if normalized_settings.get('cache_enabled') and normalized_settings.get('redis_cache_configured'):
            _record_document_access_cache_metric(
                'invalidate_failed',
                operation=operation,
                source_scope=source_scope,
                scope_key_count=len(normalized_scope_keys),
                reason='redis_unavailable',
            )
            return {
                'success': False,
                'status': 'redis_unavailable',
                'invalidated_count': 0,
            }
        _bump_document_access_cache_local_epoch()
        return {
            'success': True,
            'status': 'skipped_cache_unavailable',
            'invalidated_count': 0,
        }

    invalidated_count = 0
    started_at = perf_counter()
    try:
        version_ttl_seconds = normalized_settings.get('cache_version_ttl_seconds')
        for scope_key in normalized_scope_keys:
            version_key = _document_access_cache_version_key(scope_key)
            redis_client.incr(version_key)
            _refresh_document_access_cache_version_key_ttl(
                redis_client,
                version_key,
                version_ttl_seconds,
            )
            invalidated_count += 1
    except Exception as exc:
        _record_document_access_cache_metric(
            'invalidate_failed',
            operation=operation,
            source_scope=source_scope,
            scope_key_count=len(normalized_scope_keys),
            reason=reason or 'redis_error',
            elapsed_ms=(perf_counter() - started_at) * 1000,
            error=exc,
        )
        log_event(
            '[DocumentAccessIndexCache] Failed to invalidate Redis DAI cache scope versions.',
            extra={
                'scope_key_count': len(normalized_scope_keys),
                'invalidated_count': invalidated_count,
                'reason': reason,
                'error_type': type(exc).__name__,
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return {
            'success': False,
            'status': 'invalidate_failed',
            'invalidated_count': invalidated_count,
        }

    _record_document_access_cache_metric(
        'invalidate',
        operation=operation,
        source_scope=source_scope,
        scope_key_count=invalidated_count,
        reason=reason,
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )
    return {
        'success': True,
        'status': 'invalidated',
        'invalidated_count': invalidated_count,
    }


def _normalize_document_access_cache_scope_keys(scope_keys):
    return sorted({
        str(scope_key or '').strip()
        for scope_key in scope_keys or []
        if str(scope_key or '').strip()
    })


def _cache_scope_keys_from_exception(error):
    return _normalize_document_access_cache_scope_keys(getattr(error, 'scope_keys', None))


def _raise_for_failed_cache_invalidation(invalidation_result, operation, scope_keys=None):
    if not isinstance(invalidation_result, dict) or invalidation_result.get('success'):
        return
    raise DocumentAccessIndexCacheInvalidationError(
        operation,
        invalidation_result.get('status') or 'unknown',
        scope_keys=scope_keys,
    )


def _normalize_document_access_cache_version_hashes(scope_hashes):
    return sorted({
        str(scope_hash or '').strip().lower()
        for scope_hash in scope_hashes or []
        if re.fullmatch(r'[a-f0-9]{64}', str(scope_hash or '').strip().lower())
    })


def _empty_document_access_cache_version_resolution(scope_hash):
    return {
        'kind': 'document_access_index_scope_version',
        'label': 'DAI scope version marker',
        'resolved': False,
        'resolution_status': 'unresolved',
        'scope_hash': scope_hash,
        'scope_key': None,
        'entity_type': None,
        'entity_id': None,
        'entity_name': None,
        'entity_status': None,
        'row_count': None,
        'granted_row_count': None,
        'source_scopes': {},
        'access_roles': {},
        'note': 'No matching SimpleChat user, group, public workspace, or DAI projection scope was found.',
    }


def _document_access_resolution_entity_type(scope_type):
    if scope_type == DOCUMENT_ACCESS_SCOPE_GROUP:
        return 'group_workspace'
    if scope_type == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        return 'public_workspace'
    if scope_type == DOCUMENT_ACCESS_PRINCIPAL_USER:
        return 'user'
    return scope_type


def _build_document_access_cache_version_resolution(
    scope_hash,
    scope_key,
    entity_type,
    entity_id,
    entity_name=None,
    entity_status=None,
    row_count=None,
    granted_row_count=None,
    source_scopes=None,
    access_roles=None,
    source='document_access_index',
):
    return {
        'kind': 'document_access_index_scope_version',
        'label': 'DAI scope version marker',
        'resolved': True,
        'resolution_status': 'resolved',
        'scope_hash': scope_hash,
        'scope_key': scope_key,
        'entity_type': _document_access_resolution_entity_type(entity_type),
        'entity_id': entity_id,
        'entity_name': entity_name,
        'entity_status': entity_status,
        'row_count': row_count,
        'granted_row_count': granted_row_count,
        'source_scopes': source_scopes or {},
        'access_roles': access_roles or {},
        'source': source,
        'note': 'Resolved by re-hashing known SimpleChat access scope keys.',
    }


def _increment_counter(counter, key):
    normalized_key = str(key or '').strip() or 'unknown'
    counter[normalized_key] = counter.get(normalized_key, 0) + 1


def _resolve_document_access_hashes_from_projection(scope_hashes, resolutions):
    if not scope_hashes:
        return
    query = (
        'SELECT c.scope_key, c.scope_type, c.scope_id, c.source_scope, c.access_role, c.access_granted '
        'FROM c WHERE c.type = @type'
    )
    projection_rows = cosmos_document_access_index_container.query_items(
        query=query,
        parameters=[{'name': '@type', 'value': DOCUMENT_ACCESS_INDEX_TYPE}],
        enable_cross_partition_query=True,
    )
    scope_summaries = {}
    for row in projection_rows:
        scope_key = str(row.get('scope_key') or '').strip()
        if not scope_key:
            continue
        scope_hash = build_document_access_cache_scope_hash(scope_key)
        if scope_hash not in scope_hashes:
            continue
        summary = scope_summaries.setdefault(scope_hash, {
            'scope_key': scope_key,
            'entity_type': row.get('scope_type'),
            'entity_id': row.get('scope_id'),
            'row_count': 0,
            'granted_row_count': 0,
            'source_scopes': {},
            'access_roles': {},
        })
        summary['row_count'] += 1
        if row.get('access_granted'):
            summary['granted_row_count'] += 1
        _increment_counter(summary['source_scopes'], row.get('source_scope'))
        _increment_counter(summary['access_roles'], row.get('access_role'))

    for scope_hash, summary in scope_summaries.items():
        resolutions[scope_hash] = _build_document_access_cache_version_resolution(
            scope_hash,
            summary.get('scope_key'),
            summary.get('entity_type'),
            summary.get('entity_id'),
            row_count=summary.get('row_count'),
            granted_row_count=summary.get('granted_row_count'),
            source_scopes=summary.get('source_scopes'),
            access_roles=summary.get('access_roles'),
        )


def _resolve_document_access_hashes_from_workspace_container(
    scope_hashes,
    resolutions,
    container,
    scope_type,
    entity_status_default='active',
):
    if not scope_hashes:
        return
    query = 'SELECT c.id, c.name, c.status FROM c'
    for item in container.query_items(query=query, enable_cross_partition_query=True):
        entity_id = str(item.get('id') or '').strip()
        if not entity_id:
            continue
        scope_key = build_document_access_scope_key(scope_type, entity_id)
        scope_hash = build_document_access_cache_scope_hash(scope_key)
        if scope_hash not in scope_hashes:
            continue
        if resolutions.get(scope_hash, {}).get('resolved'):
            resolutions[scope_hash]['entity_name'] = item.get('name')
            resolutions[scope_hash]['entity_status'] = item.get('status') or entity_status_default
            continue
        resolutions[scope_hash] = _build_document_access_cache_version_resolution(
            scope_hash,
            scope_key,
            scope_type,
            entity_id,
            entity_name=item.get('name'),
            entity_status=item.get('status') or entity_status_default,
            row_count=0,
            granted_row_count=0,
            source='workspace_container',
        )


def _resolve_document_access_hashes_from_user_settings(scope_hashes, resolutions):
    if not scope_hashes:
        return
    query = 'SELECT c.id, c.displayName, c.name FROM c'
    for item in cosmos_user_settings_container.query_items(query=query, enable_cross_partition_query=True):
        entity_id = str(item.get('id') or '').strip()
        if not entity_id:
            continue
        scope_key = build_document_access_scope_key(DOCUMENT_ACCESS_PRINCIPAL_USER, entity_id)
        scope_hash = build_document_access_cache_scope_hash(scope_key)
        if scope_hash not in scope_hashes:
            continue
        if resolutions.get(scope_hash, {}).get('resolved'):
            resolutions[scope_hash]['entity_name'] = item.get('displayName') or item.get('name')
            continue
        resolutions[scope_hash] = _build_document_access_cache_version_resolution(
            scope_hash,
            scope_key,
            DOCUMENT_ACCESS_PRINCIPAL_USER,
            entity_id,
            entity_name=item.get('displayName') or item.get('name'),
            row_count=0,
            granted_row_count=0,
            source='user_settings',
        )


def resolve_document_access_cache_version_hashes(scope_hashes):
    """Resolve Redis DAI version marker hashes to safe SimpleChat scope metadata."""
    normalized_hashes = _normalize_document_access_cache_version_hashes(scope_hashes)
    resolutions = {
        scope_hash: _empty_document_access_cache_version_resolution(scope_hash)
        for scope_hash in normalized_hashes
    }
    if not normalized_hashes:
        return resolutions

    try:
        _resolve_document_access_hashes_from_projection(set(normalized_hashes), resolutions)
    except Exception as exc:
        log_event(
            '[DocumentAccessIndexCache] Failed to resolve DAI Redis hashes from projection rows.',
            extra={'hash_count': len(normalized_hashes), 'error_type': type(exc).__name__},
            level=logging.WARNING,
            exceptionTraceback=True,
        )

    try:
        _resolve_document_access_hashes_from_workspace_container(
            set(normalized_hashes),
            resolutions,
            cosmos_groups_container,
            DOCUMENT_ACCESS_SCOPE_GROUP,
        )
    except Exception as exc:
        log_event(
            '[DocumentAccessIndexCache] Failed to resolve DAI Redis hashes from group workspaces.',
            extra={'hash_count': len(normalized_hashes), 'error_type': type(exc).__name__},
            level=logging.WARNING,
            exceptionTraceback=True,
        )

    try:
        _resolve_document_access_hashes_from_workspace_container(
            set(normalized_hashes),
            resolutions,
            cosmos_public_workspaces_container,
            DOCUMENT_ACCESS_SCOPE_PUBLIC,
        )
    except Exception as exc:
        log_event(
            '[DocumentAccessIndexCache] Failed to resolve DAI Redis hashes from public workspaces.',
            extra={'hash_count': len(normalized_hashes), 'error_type': type(exc).__name__},
            level=logging.WARNING,
            exceptionTraceback=True,
        )

    try:
        _resolve_document_access_hashes_from_user_settings(set(normalized_hashes), resolutions)
    except Exception as exc:
        log_event(
            '[DocumentAccessIndexCache] Failed to resolve DAI Redis hashes from user settings.',
            extra={'hash_count': len(normalized_hashes), 'error_type': type(exc).__name__},
            level=logging.WARNING,
            exceptionTraceback=True,
        )

    return resolutions


def refresh_document_access_cache_version_marker_ttls(settings=None, redis_client=None, batch_size=None):
    """Apply the derived TTL policy to legacy DAI Redis version markers."""
    normalized_settings = get_document_access_index_settings(settings)
    resolved_client = redis_client or _get_document_access_cache_client(
        normalized_settings,
        'version_marker_hygiene',
        'mixed',
        0,
        require_cache_enabled=False,
    )
    version_ttl_seconds = normalized_settings.get('cache_version_ttl_seconds')
    payload_ttl_seconds = normalized_settings.get('cache_ttl_seconds')
    result = {
        'success': True,
        'status': 'skipped_redis_unavailable',
        'version_marker_ttl_seconds': version_ttl_seconds,
        'payload_ttl_seconds': payload_ttl_seconds,
        'scanned_count': 0,
        'refreshed_count': 0,
        'no_expiry_count': 0,
        'unsafe_ttl_count': 0,
        'skipped_count': 0,
        'scan_iterations': 0,
        'has_more': False,
    }
    if resolved_client is None:
        return result

    normalized_batch_size = _normalize_positive_int(
        batch_size,
        DOCUMENT_ACCESS_CACHE_VERSION_HYGIENE_BATCH_SIZE,
        min_value=1,
        max_value=1000,
    )
    cursor = 0
    try:
        while result['scan_iterations'] < DOCUMENT_ACCESS_CACHE_VERSION_HYGIENE_MAX_SCAN_ITERATIONS:
            cursor, keys = resolved_client.scan(
                cursor=cursor,
                match=f'{DOCUMENT_ACCESS_CACHE_VERSION_KEY_PREFIX}:*',
                count=normalized_batch_size,
            )
            cursor = _safe_int(cursor)
            result['scan_iterations'] += 1
            for key in list(keys or []):
                result['scanned_count'] += 1
                try:
                    ttl_seconds = int(resolved_client.ttl(key))
                except (TypeError, ValueError):
                    ttl_seconds = -2
                if ttl_seconds == -1:
                    result['no_expiry_count'] += 1
                if ttl_seconds == -1 or (ttl_seconds >= 0 and ttl_seconds < payload_ttl_seconds):
                    if ttl_seconds >= 0 and ttl_seconds < payload_ttl_seconds:
                        result['unsafe_ttl_count'] += 1
                    _refresh_document_access_cache_version_key_ttl(
                        resolved_client,
                        key,
                        version_ttl_seconds,
                    )
                    result['refreshed_count'] += 1
                else:
                    result['skipped_count'] += 1
            if cursor == 0:
                break
        result['has_more'] = cursor != 0
        result['status'] = 'completed'
        return result
    except Exception as exc:
        log_event(
            '[DocumentAccessIndexCache] Failed to refresh DAI Redis version marker TTLs.',
            extra={
                'scanned_count': result.get('scanned_count'),
                'refreshed_count': result.get('refreshed_count'),
                'error_type': type(exc).__name__,
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        result['success'] = False
        result['status'] = 'failed'
        result['error'] = str(exc)
        return result


def build_document_access_index_row_id(scope_key, source_scope, document_id, version):
    """Build a deterministic Cosmos id for one scope/document/version projection row."""
    raw_id = ':'.join([
        'dai',
        _safe_id_part(scope_key),
        _safe_id_part(source_scope),
        _safe_id_part(document_id),
        _safe_id_part(version),
    ])
    if len(raw_id) <= 900:
        return raw_id
    return f'dai:{hashlib.sha256(raw_id.encode("utf-8")).hexdigest()}'


def _normalize_string_list(value):
    if not isinstance(value, list):
        return []
    return [
        str(item).strip()
        for item in value
        if str(item or '').strip()
    ]


def _normalize_filter_text(value):
    return str(value or '').strip().lower()


def _has_persisted_blob_reference(document_item):
    if not isinstance(document_item, dict):
        return False
    if document_item.get('blob_path'):
        return True
    return (
        document_item.get('blob_path_mode') == DOCUMENT_ACCESS_ARCHIVED_REVISION_BLOB_PATH_MODE
        and bool(document_item.get('archived_blob_path'))
    )


def _document_identity(document_item):
    if not isinstance(document_item, dict):
        return None
    document_id = str(
        document_item.get('document_id')
        or document_item.get('source_document_id')
        or document_item.get('id')
        or ''
    ).strip()
    try:
        version = int(document_item.get('version') or 0)
    except (TypeError, ValueError):
        version = 0
    if not document_id:
        return None
    return f'{document_id}:{version}'


def _document_family_identity(document_item, source_scope):
    if not isinstance(document_item, dict):
        return None
    revision_family_id = str(document_item.get('revision_family_id') or '').strip()
    if revision_family_id:
        return revision_family_id

    if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        scope_value = document_item.get('owner_public_workspace_id') or document_item.get('public_workspace_id')
    elif source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        scope_value = document_item.get('owner_group_id') or document_item.get('group_id')
    else:
        scope_value = document_item.get('owner_user_id') or document_item.get('user_id')
    return f'legacy::{scope_value or "unknown"}::{document_item.get("file_name") or ""}'


def _normalize_share_entry(entry):
    normalized_entry = str(entry or '').strip()
    if not normalized_entry:
        return None
    if ',' in normalized_entry:
        scope_id, approval_status = normalized_entry.split(',', 1)
        approval_status = str(approval_status or '').strip().lower() or 'unknown'
    else:
        scope_id = normalized_entry
        approval_status = DOCUMENT_ACCESS_APPROVAL_NOT_APPROVED

    scope_id = str(scope_id or '').strip()
    if not scope_id:
        return None
    return {
        'scope_id': scope_id,
        'approval_status': approval_status,
        'raw_entry': normalized_entry,
    }


def _resolve_source_scope(document_item):
    if document_item.get('public_workspace_id'):
        return DOCUMENT_ACCESS_SCOPE_PUBLIC
    if document_item.get('group_id'):
        return DOCUMENT_ACCESS_SCOPE_GROUP
    return DOCUMENT_ACCESS_SCOPE_PERSONAL


def _source_scope_container_name(source_scope):
    if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        return 'public_documents'
    if source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        return 'group_documents'
    return 'documents'


def _get_document_version(document_item):
    try:
        return int(document_item.get('version') or 0)
    except (TypeError, ValueError):
        return 0


def _build_base_row(document_item, source_scope, scope_type, scope_id, access_role, approval_status, projected_at):
    document_id = str(document_item.get('id') or document_item.get('document_id') or '').strip()
    version = _get_document_version(document_item)
    scope_key = build_document_access_scope_key(scope_type, scope_id)
    if not document_id or not scope_key:
        return None

    approval_status = str(approval_status or '').strip().lower() or 'unknown'
    access_granted = approval_status == DOCUMENT_ACCESS_APPROVAL_APPROVED
    source_updated_at = document_item.get('last_updated') or document_item.get('upload_date')

    return {
        'id': build_document_access_index_row_id(scope_key, source_scope, document_id, version),
        'type': DOCUMENT_ACCESS_INDEX_TYPE,
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        'projection_status': 'ready',
        'projection_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        'repair_required': False,
        'projected_at': projected_at,
        'scope_key': scope_key,
        'scope_type': scope_type,
        'scope_id': str(scope_id or '').strip(),
        'source_scope': source_scope,
        'source_container': _source_scope_container_name(source_scope),
        'source_document_id': document_id,
        'source_partition_key': document_id,
        'document_id': document_id,
        'revision_family_id': document_item.get('revision_family_id'),
        'version': version,
        'is_current_version': bool(document_item.get('is_current_version', True)),
        'search_visibility_state': str(document_item.get('search_visibility_state') or 'active').strip().lower(),
        'access_role': access_role,
        'approval_status': approval_status,
        'access_granted': access_granted,
        'shared_user_ids': _normalize_string_list(document_item.get('shared_user_ids')),
        'shared_group_ids': _normalize_string_list(document_item.get('shared_group_ids')),
        'file_name': document_item.get('file_name'),
        'title': document_item.get('title'),
        'document_classification': document_item.get('document_classification'),
        'tags': _normalize_string_list(document_item.get('tags')),
        'authors': _normalize_string_list(document_item.get('authors')),
        'keywords': _normalize_string_list(document_item.get('keywords')),
        'abstract': document_item.get('abstract'),
        'status': document_item.get('status'),
        'percentage_complete': document_item.get('percentage_complete'),
        'number_of_pages': document_item.get('number_of_pages'),
        'publication_date': document_item.get('publication_date'),
        'enhanced_citations': _has_persisted_blob_reference(document_item),
        'document_intelligence_extraction_mode': document_item.get('document_intelligence_extraction_mode'),
        'generated_artifact_promotion_status': document_item.get('generated_artifact_promotion_status'),
        'generated_artifact_requested_by_user_id': document_item.get('generated_artifact_requested_by_user_id'),
        'file_sync': document_item.get('file_sync'),
        'created_from_chat_upload': document_item.get('created_from_chat_upload'),
        'conversation_id': document_item.get('conversation_id'),
        'conversation_title_at_upload': document_item.get('conversation_title_at_upload'),
        'upload_date': document_item.get('upload_date'),
        'last_updated': document_item.get('last_updated'),
        'source_ts': document_item.get('_ts'),
        'source_updated_at': source_updated_at,
        'user_id': document_item.get('user_id'),
        'owner_user_id': document_item.get('user_id'),
        'owner_group_id': document_item.get('group_id'),
        'owner_public_workspace_id': document_item.get('public_workspace_id'),
    }


def _prefer_projection_row(existing_row, candidate_row):
    if not existing_row:
        return candidate_row
    existing_sort_key = (
        _safe_int(existing_row.get('version')),
        str(existing_row.get('upload_date') or ''),
        _safe_int(existing_row.get('source_ts')),
    )
    candidate_sort_key = (
        _safe_int(candidate_row.get('version')),
        str(candidate_row.get('upload_date') or ''),
        _safe_int(candidate_row.get('source_ts')),
    )
    if candidate_sort_key > existing_sort_key:
        return candidate_row
    if candidate_sort_key < existing_sort_key:
        return existing_row
    if existing_row.get('access_role') == 'owner':
        return existing_row
    if candidate_row.get('access_role') == 'owner':
        return candidate_row
    if existing_row.get('access_granted') and not candidate_row.get('access_granted'):
        return candidate_row
    return existing_row


def build_document_access_index_rows(document_item):
    """Build deterministic per-scope projection rows for one source document."""
    if not isinstance(document_item, dict):
        return []

    source_scope = _resolve_source_scope(document_item)
    projected_at = _utc_now_iso()
    rows_by_key = {}

    def add_row(scope_type, scope_id, access_role, approval_status):
        row = _build_base_row(
            document_item,
            source_scope,
            scope_type,
            scope_id,
            access_role,
            approval_status,
            projected_at,
        )
        if not row:
            return
        row_key = (row['scope_key'], row['id'])
        rows_by_key[row_key] = _prefer_projection_row(rows_by_key.get(row_key), row)

    if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        add_row(
            DOCUMENT_ACCESS_SCOPE_PUBLIC,
            document_item.get('public_workspace_id'),
            'public_workspace',
            DOCUMENT_ACCESS_APPROVAL_APPROVED,
        )
    elif source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        add_row(
            DOCUMENT_ACCESS_SCOPE_GROUP,
            document_item.get('group_id'),
            'owner',
            DOCUMENT_ACCESS_APPROVAL_APPROVED,
        )
        for share_entry in _normalize_string_list(document_item.get('shared_group_ids')):
            normalized_share = _normalize_share_entry(share_entry)
            if normalized_share:
                add_row(
                    DOCUMENT_ACCESS_SCOPE_GROUP,
                    normalized_share['scope_id'],
                    'shared_group',
                    normalized_share['approval_status'],
                )
    else:
        add_row(
            DOCUMENT_ACCESS_PRINCIPAL_USER,
            document_item.get('user_id'),
            'owner',
            DOCUMENT_ACCESS_APPROVAL_APPROVED,
        )
        for share_entry in _normalize_string_list(document_item.get('shared_user_ids')):
            normalized_share = _normalize_share_entry(share_entry)
            if normalized_share:
                add_row(
                    DOCUMENT_ACCESS_PRINCIPAL_USER,
                    normalized_share['scope_id'],
                    'shared_user',
                    normalized_share['approval_status'],
                )

    return sorted(rows_by_key.values(), key=lambda row: (row['scope_key'], row['id']))


def _query_existing_projection_rows(source_scope, document_id):
    query = (
        'SELECT c.id, c.scope_key FROM c '
        'WHERE c.type = @type AND c.source_scope = @source_scope AND c.source_document_id = @document_id'
    )
    return list(cosmos_document_access_index_container.query_items(
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_INDEX_TYPE},
            {'name': '@source_scope', 'value': source_scope},
            {'name': '@document_id', 'value': document_id},
        ],
        enable_cross_partition_query=True,
    ))


def _read_shadow_validation_state(use_cache=True):
    if use_cache:
        cache_hit, cached_state = _get_cached_document_access_state(DOCUMENT_ACCESS_SHADOW_STATE_DOC_ID)
        if cache_hit:
            return cached_state
    try:
        state = cosmos_settings_container.read_item(
            item=DOCUMENT_ACCESS_SHADOW_STATE_DOC_ID,
            partition_key=DOCUMENT_ACCESS_SHADOW_STATE_DOC_ID,
        )
    except Exception as exc:
        if _is_not_found_error(exc):
            _set_cached_document_access_state(DOCUMENT_ACCESS_SHADOW_STATE_DOC_ID, None)
            return None
        log_event(
            '[DocumentAccessIndex] Failed to read document access shadow validation state.',
            extra={'error': str(exc)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None
    _set_cached_document_access_state(DOCUMENT_ACCESS_SHADOW_STATE_DOC_ID, state)
    return state


def _empty_shadow_metric_window(window_minutes):
    return {
        'window_minutes': window_minutes,
        'sample_count': 0,
        'comparable_sample_count': 0,
        'matched_count': 0,
        'mismatch_count': 0,
        'error_count': 0,
        'source_query_ru': None,
        'validation_index_ru': None,
        'candidate_read_ru': None,
        'estimated_wave5_ru_savings': None,
        'shadow_overhead_ru': None,
        'source_query_ms_avg': None,
        'candidate_read_ms_avg': None,
        'estimated_wave5_ms_savings_avg': None,
        'source_query_item_count': 0,
        'candidate_read_item_count': 0,
        'source_query_page_count': 0,
        'candidate_read_page_count': 0,
        'first_checked_at': None,
        'last_checked_at': None,
    }


def _empty_shadow_rolling_metrics():
    return {
        'updated_at': None,
        'retention_minutes': DOCUMENT_ACCESS_SHADOW_METRIC_RETENTION_MINUTES,
        'sample_limit': DOCUMENT_ACCESS_SHADOW_METRIC_MAX_SAMPLES,
        'sample_count': 0,
        'windows': {
            f'{window_minutes}m': _empty_shadow_metric_window(window_minutes)
            for window_minutes in DOCUMENT_ACCESS_SHADOW_METRIC_WINDOWS_MINUTES
        },
    }


def _build_shadow_metric_sample(state_body):
    if not isinstance(state_body, dict):
        return None

    metric_keys = (
        'source_query_ru',
        'validation_index_ru',
        'candidate_read_ru',
        'source_query_ms',
        'candidate_read_ms',
    )
    if not any(_safe_float(state_body.get(metric_key)) is not None for metric_key in metric_keys):
        return None

    scope_keys = state_body.get('scope_keys')
    return {
        'checked_at': state_body.get('checked_at') or _utc_now_iso(),
        'status': str(state_body.get('status') or 'unknown').strip().lower() or 'unknown',
        'context': str(state_body.get('context') or '').strip(),
        'source_scope': str(state_body.get('source_scope') or '').strip().lower(),
        'scope_key_count': len(scope_keys) if isinstance(scope_keys, list) else 0,
        'authoritative_count': _safe_int(state_body.get('authoritative_count')),
        'projection_count': _safe_int(state_body.get('projection_count')),
        'missing_count': _safe_int(state_body.get('missing_count')),
        'extra_count': _safe_int(state_body.get('extra_count')),
        'source_query_ru': _round_metric(state_body.get('source_query_ru')),
        'validation_index_ru': _round_metric(state_body.get('validation_index_ru')),
        'candidate_read_ru': _round_metric(state_body.get('candidate_read_ru')),
        'estimated_wave5_ru_savings': _round_metric(state_body.get('estimated_wave5_ru_savings')),
        'shadow_overhead_ru': _round_metric(state_body.get('shadow_overhead_ru')),
        'source_query_ms': _round_metric(state_body.get('source_query_ms')),
        'candidate_read_ms': _round_metric(state_body.get('candidate_read_ms')),
        'estimated_wave5_ms_savings': _round_metric(state_body.get('estimated_wave5_ms_savings')),
        'source_query_item_count': _safe_int(state_body.get('source_query_item_count')),
        'candidate_read_item_count': _safe_int(state_body.get('candidate_read_item_count')),
        'source_query_page_count': _safe_int(state_body.get('source_query_page_count')),
        'candidate_read_page_count': _safe_int(state_body.get('candidate_read_page_count')),
    }


def _prune_shadow_metric_samples(samples, now):
    cutoff = now - timedelta(minutes=DOCUMENT_ACCESS_SHADOW_METRIC_RETENTION_MINUTES)
    pruned_samples = []
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        checked_at = _parse_utc_datetime(sample.get('checked_at'))
        if not checked_at or checked_at < cutoff:
            continue
        pruned_samples.append(copy.deepcopy(sample))

    pruned_samples.sort(key=lambda sample: sample.get('checked_at') or '')
    return pruned_samples[-DOCUMENT_ACCESS_SHADOW_METRIC_MAX_SAMPLES:]


def _build_shadow_metric_window(samples, now, window_minutes):
    cutoff = now - timedelta(minutes=window_minutes)
    window_samples = [
        sample
        for sample in samples or []
        if (_parse_utc_datetime(sample.get('checked_at')) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    if not window_samples:
        return _empty_shadow_metric_window(window_minutes)

    paired_ru_samples = [
        sample
        for sample in window_samples
        if _safe_float(sample.get('source_query_ru')) is not None
        and _safe_float(sample.get('candidate_read_ru')) is not None
    ]
    paired_ms_samples = [
        sample
        for sample in window_samples
        if _safe_float(sample.get('source_query_ms')) is not None
        and _safe_float(sample.get('candidate_read_ms')) is not None
    ]
    paired_source_ru = _sum_metric_values(paired_ru_samples, 'source_query_ru')
    paired_candidate_ru = _sum_metric_values(paired_ru_samples, 'candidate_read_ru')
    source_ms_avg = _average_metric_values(paired_ms_samples, 'source_query_ms')
    candidate_ms_avg = _average_metric_values(paired_ms_samples, 'candidate_read_ms')

    return {
        'window_minutes': window_minutes,
        'sample_count': len(window_samples),
        'comparable_sample_count': len(paired_ru_samples),
        'matched_count': sum(1 for sample in window_samples if sample.get('status') == 'matched'),
        'mismatch_count': sum(1 for sample in window_samples if sample.get('status') == 'mismatch'),
        'error_count': sum(1 for sample in window_samples if sample.get('status') == 'error'),
        'source_query_ru': paired_source_ru,
        'validation_index_ru': _sum_metric_values(window_samples, 'validation_index_ru'),
        'candidate_read_ru': paired_candidate_ru,
        'estimated_wave5_ru_savings': _metric_delta(paired_source_ru, paired_candidate_ru),
        'shadow_overhead_ru': _sum_metric_values(window_samples, 'shadow_overhead_ru'),
        'source_query_ms_avg': source_ms_avg,
        'candidate_read_ms_avg': candidate_ms_avg,
        'estimated_wave5_ms_savings_avg': _metric_delta(source_ms_avg, candidate_ms_avg),
        'source_query_item_count': _sum_int_values(paired_ru_samples, 'source_query_item_count'),
        'candidate_read_item_count': _sum_int_values(paired_ru_samples, 'candidate_read_item_count'),
        'source_query_page_count': _sum_int_values(paired_ru_samples, 'source_query_page_count'),
        'candidate_read_page_count': _sum_int_values(paired_ru_samples, 'candidate_read_page_count'),
        'first_checked_at': window_samples[0].get('checked_at'),
        'last_checked_at': window_samples[-1].get('checked_at'),
    }


def _build_shadow_rolling_metrics(samples, now):
    return {
        'updated_at': now.isoformat(),
        'retention_minutes': DOCUMENT_ACCESS_SHADOW_METRIC_RETENTION_MINUTES,
        'sample_limit': DOCUMENT_ACCESS_SHADOW_METRIC_MAX_SAMPLES,
        'sample_count': len(samples or []),
        'windows': {
            f'{window_minutes}m': _build_shadow_metric_window(samples, now, window_minutes)
            for window_minutes in DOCUMENT_ACCESS_SHADOW_METRIC_WINDOWS_MINUTES
        },
    }


def _merge_shadow_rolling_metrics(state_body, previous_state=None):
    previous_state = previous_state or {}
    samples = _prune_shadow_metric_samples(
        previous_state.get('recent_metric_samples') if isinstance(previous_state, dict) else [],
        datetime.now(timezone.utc),
    )
    metric_sample = _build_shadow_metric_sample(state_body)
    if metric_sample:
        samples.append(metric_sample)
    now = datetime.now(timezone.utc)
    samples = _prune_shadow_metric_samples(samples, now)
    state_body['recent_metric_samples'] = samples
    state_body['rolling_metrics'] = _build_shadow_rolling_metrics(samples, now)
    return state_body


def _write_shadow_validation_state(state):
    state_body = None
    last_conflict = None

    for attempt in range(DOCUMENT_ACCESS_SHADOW_STATE_WRITE_MAX_RETRIES):
        previous_state = _read_shadow_validation_state(use_cache=False)
        state_body = copy.deepcopy(state or {})
        state_body.update({
            'id': DOCUMENT_ACCESS_SHADOW_STATE_DOC_ID,
            'type': DOCUMENT_ACCESS_SHADOW_STATE_TYPE,
            'updated_at': _utc_now_iso(),
            'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        })
        state_body = _merge_shadow_rolling_metrics(state_body, previous_state=previous_state)

        try:
            if previous_state:
                replace_kwargs = {}
                etag = previous_state.get('_etag') if isinstance(previous_state, dict) else None
                if etag:
                    replace_kwargs['etag'] = etag
                    replace_kwargs['match_condition'] = MatchConditions.IfNotModified
                cosmos_settings_container.replace_item(
                    item=DOCUMENT_ACCESS_SHADOW_STATE_DOC_ID,
                    body=state_body,
                    **replace_kwargs,
                )
            else:
                cosmos_settings_container.create_item(body=state_body)
            _set_cached_document_access_state(DOCUMENT_ACCESS_SHADOW_STATE_DOC_ID, state_body)
            return state_body
        except Exception as exc:
            if _is_write_conflict_error(exc):
                last_conflict = exc
                log_event(
                    '[DocumentAccessIndex] Retrying shadow validation state write after ETag conflict.',
                    extra={'attempt': attempt + 1, 'error': str(exc)},
                    level=logging.WARNING,
                    debug_only=True,
                )
                continue
            raise

    log_event(
        '[DocumentAccessIndex] Failed to persist shadow validation state after ETag conflicts.',
        extra={
            'attempt_count': DOCUMENT_ACCESS_SHADOW_STATE_WRITE_MAX_RETRIES,
            'error': str(last_conflict) if last_conflict else None,
        },
        level=logging.WARNING,
    )
    return state_body


def _query_projection_rows_for_scope(scope_key, source_scope):
    rows, _diagnostics = _query_projection_rows_for_scope_with_diagnostics(scope_key, source_scope)
    return rows


def _query_projection_rows_for_scope_with_diagnostics(scope_key, source_scope):
    query = (
        'SELECT * FROM c '
        'WHERE c.type = @type '
        'AND c.source_scope = @source_scope '
        'AND c.scope_key = @scope_key '
        'AND c.access_granted = true '
        'AND c.is_current_version = true '
        'AND c.projection_version = @projection_version'
    )
    return query_items_with_cosmos_diagnostics(
        cosmos_document_access_index_container,
        diagnostics_label=f'projection:{scope_key}',
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_INDEX_TYPE},
            {'name': '@source_scope', 'value': source_scope},
            {'name': '@scope_key', 'value': scope_key},
            {'name': '@projection_version', 'value': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION},
        ],
        partition_key=scope_key,
    )


def _query_candidate_projection_rows_for_scope(scope_key, source_scope):
    query = (
        'SELECT c.id, c.document_id, c.source_document_id, c.version, c.scope_key, '
        'c.scope_id, c.access_role, c.approval_status, c.access_granted, '
        'c.shared_user_ids, c.shared_group_ids, c.file_name, c.title, c.document_classification, c.tags, c.authors, c.keywords, '
        'c.abstract, c.status, c.percentage_complete, c.number_of_pages, c.publication_date, '
        'c.enhanced_citations, c.document_intelligence_extraction_mode, '
        'c.generated_artifact_promotion_status, c.generated_artifact_requested_by_user_id, '
        'c.file_sync, c.created_from_chat_upload, '
        'c.conversation_id, c.conversation_title_at_upload, c.upload_date, c.last_updated, '
        'c.revision_family_id, c.search_visibility_state, c.source_ts, '
        'c.user_id, c.owner_user_id, c.owner_group_id, c.owner_public_workspace_id '
        'FROM c '
        'WHERE c.type = @type '
        'AND c.source_scope = @source_scope '
        'AND c.scope_key = @scope_key '
        'AND c.access_granted = true '
        'AND c.is_current_version = true '
        'AND c.projection_version = @projection_version'
    )
    return query_items_with_cosmos_diagnostics(
        cosmos_document_access_index_container,
        diagnostics_label=f'candidate_read:{scope_key}',
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_INDEX_TYPE},
            {'name': '@source_scope', 'value': source_scope},
            {'name': '@scope_key', 'value': scope_key},
            {'name': '@projection_version', 'value': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION},
        ],
        partition_key=scope_key,
    )


def _query_bounded_projection_rows_for_scope(scope_key, source_scope, max_rows):
    normalized_max_rows = max(1, min(_safe_int(max_rows), 1001))
    query = (
        f'SELECT TOP {normalized_max_rows} c.document_id, c.source_document_id, c.version, '
        'c.revision_family_id, c.source_ts, c.file_name, '
        'c.owner_user_id, c.owner_group_id, c.owner_public_workspace_id '
        'FROM c '
        'WHERE c.type = @type '
        'AND c.source_scope = @source_scope '
        'AND c.scope_key = @scope_key '
        'AND c.access_granted = true '
        'AND c.is_current_version = true '
        'AND c.projection_version = @projection_version '
        'ORDER BY c.source_ts DESC'
    )
    return list(cosmos_document_access_index_container.query_items(
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_INDEX_TYPE},
            {'name': '@source_scope', 'value': source_scope},
            {'name': '@scope_key', 'value': scope_key},
            {'name': '@projection_version', 'value': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION},
        ],
        partition_key=scope_key,
    ))


def enumerate_bounded_document_access_index_ids(
    source_scope,
    max_documents,
    user_id=None,
    group_ids=None,
    public_workspace_id=None,
    public_workspace_ids=None,
    settings=None,
):
    """Return current candidate IDs only when the ready access-index catalog fits the bound."""
    source_scope = str(source_scope or '').strip().lower()
    if source_scope not in DOCUMENT_ACCESS_SOURCE_SCOPES:
        return {'success': False, 'status': 'invalid_source_scope', 'document_ids': []}
    max_documents = _safe_int(max_documents)
    if max_documents <= 0:
        return {'success': False, 'status': 'invalid_document_limit', 'document_ids': []}

    readiness = _get_document_access_index_readiness(source_scope, settings=settings)
    if not readiness.get('ready'):
        return {
            'success': False,
            'status': readiness.get('status'),
            'document_ids': [],
            'readiness': readiness,
        }
    scope_keys = [
        scope_key
        for scope_key in _build_shadow_scope(
            source_scope,
            user_id=user_id,
            group_ids=group_ids,
            public_workspace_id=public_workspace_id,
            public_workspace_ids=public_workspace_ids,
        )
        if scope_key
    ]
    if not scope_keys:
        return {'success': False, 'status': 'missing_scope_keys', 'document_ids': []}
    if len(scope_keys) > DOCUMENT_ACCESS_BOUNDED_CATALOG_MAX_SCOPES:
        return {
            'success': False,
            'status': 'scope_limit_exceeded',
            'document_ids': [],
            'scope_count': len(scope_keys),
        }

    rows_by_identity = {}
    query_limit = max_documents + 1
    for scope_key in scope_keys:
        for row in _query_bounded_projection_rows_for_scope(
            scope_key,
            source_scope,
            query_limit,
        ):
            identity = _document_family_identity(row, source_scope)
            if not identity:
                continue
            rows_by_identity[identity] = _prefer_projection_row(
                rows_by_identity.get(identity),
                row,
            )
            if len(rows_by_identity) > max_documents:
                return {
                    'success': False,
                    'status': 'document_limit_exceeded',
                    'document_ids': [],
                    'document_count_lower_bound': max_documents + 1,
                }

    ordered_rows = sorted(
        rows_by_identity.values(),
        key=lambda row: (
            _safe_int(row.get('source_ts')),
            str(row.get('source_document_id') or row.get('document_id') or ''),
        ),
        reverse=True,
    )
    document_ids = [
        str(row.get('source_document_id') or row.get('document_id') or '').strip()
        for row in ordered_rows
        if str(row.get('source_document_id') or row.get('document_id') or '').strip()
    ]
    return {
        'success': True,
        'status': 'bounded_catalog_ready',
        'document_ids': document_ids,
        'document_count': len(document_ids),
        'scope_count': len(scope_keys),
    }


def _query_tag_projection_rows_for_scope(scope_key, source_scope):
    query = (
        'SELECT c.document_id, c.source_document_id, c.version, c.scope_key, '
        'c.scope_id, c.access_role, c.access_granted, c.file_name, c.tags, c.revision_family_id, '
        'c.source_ts, c.owner_user_id, c.owner_group_id, c.owner_public_workspace_id '
        'FROM c '
        'WHERE c.type = @type '
        'AND c.source_scope = @source_scope '
        'AND c.scope_key = @scope_key '
        'AND c.access_granted = true '
        'AND c.is_current_version = true '
        'AND c.projection_version = @projection_version '
        'AND IS_DEFINED(c.tags) '
        'AND ARRAY_LENGTH(c.tags) > 0'
    )
    return query_items_with_cosmos_diagnostics(
        cosmos_document_access_index_container,
        diagnostics_label=f'tag_read:{scope_key}',
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_INDEX_TYPE},
            {'name': '@source_scope', 'value': source_scope},
            {'name': '@scope_key', 'value': scope_key},
            {'name': '@projection_version', 'value': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION},
        ],
        partition_key=scope_key,
    )


def _query_legacy_projection_rows_for_scope(scope_key, source_scope, access_role):
    query = (
        'SELECT c.document_id, c.source_document_id, c.version, c.revision_family_id, '
        'c.file_name, c.owner_user_id, c.owner_group_id, c.owner_public_workspace_id '
        'FROM c '
        'WHERE c.type = @type '
        'AND c.source_scope = @source_scope '
        'AND c.scope_key = @scope_key '
        'AND c.access_role = @access_role '
        'AND c.access_granted = true '
        'AND c.projection_version = @projection_version '
        'AND (NOT IS_DEFINED(c.percentage_complete) OR IS_NULL(c.percentage_complete))'
    )
    return list(cosmos_document_access_index_container.query_items(
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_INDEX_TYPE},
            {'name': '@source_scope', 'value': source_scope},
            {'name': '@scope_key', 'value': scope_key},
            {'name': '@access_role', 'value': access_role},
            {'name': '@projection_version', 'value': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION},
        ],
        partition_key=scope_key,
    ))


def _collect_candidate_read_metrics(
    scope_keys,
    source_scope,
):
    diagnostics = []
    errors = []
    for scope_key in scope_keys:
        try:
            _rows, scope_diagnostics = _query_candidate_projection_rows_for_scope(
                scope_key,
                source_scope,
            )
            diagnostics.append(scope_diagnostics)
        except Exception as exc:
            errors.append(str(exc))
            log_event(
                '[DocumentAccessIndex] Candidate read metrics query failed.',
                extra={
                    'scope_key': scope_key,
                    'source_scope': source_scope,
                    'error': str(exc),
                },
                level=logging.WARNING,
                exceptionTraceback=True,
            )
    combined = _combine_query_diagnostics('candidate_read', diagnostics)
    if errors:
        combined['errors'] = errors[:DOCUMENT_ACCESS_SHADOW_MAX_SAMPLE_IDS]
        combined['error_count'] = len(errors)
        combined['partial_failure'] = True
    return combined


def _projection_row_to_document(row, source_scope):
    document_id = str(row.get('source_document_id') or row.get('document_id') or '').strip()
    approval_status = str(row.get('approval_status') or DOCUMENT_ACCESS_APPROVAL_APPROVED).strip().lower()
    scope_id = str(row.get('scope_id') or '').strip()
    access_role = str(row.get('access_role') or '').strip().lower()
    document_item = {
        'id': document_id,
        'document_id': document_id,
        'file_name': row.get('file_name'),
        'title': row.get('title'),
        'document_classification': row.get('document_classification'),
        'tags': _normalize_string_list(row.get('tags')),
        'authors': _normalize_string_list(row.get('authors')),
        'keywords': _normalize_string_list(row.get('keywords')),
        'abstract': row.get('abstract'),
        'status': row.get('status'),
        'percentage_complete': row.get('percentage_complete'),
        'number_of_pages': row.get('number_of_pages'),
        'publication_date': row.get('publication_date'),
        'enhanced_citations': row.get('enhanced_citations'),
        'document_intelligence_extraction_mode': row.get('document_intelligence_extraction_mode'),
        'generated_artifact_promotion_status': row.get('generated_artifact_promotion_status'),
        'generated_artifact_requested_by_user_id': row.get('generated_artifact_requested_by_user_id'),
        'file_sync': row.get('file_sync'),
        'created_from_chat_upload': row.get('created_from_chat_upload'),
        'conversation_id': row.get('conversation_id'),
        'conversation_title_at_upload': row.get('conversation_title_at_upload'),
        'upload_date': row.get('upload_date'),
        'last_updated': row.get('last_updated'),
        'revision_family_id': row.get('revision_family_id') or document_id,
        'version': _get_document_version(row),
        'is_current_version': True,
        'search_visibility_state': str(row.get('search_visibility_state') or 'active').strip().lower(),
        '_ts': _safe_int(row.get('source_ts')),
    }

    if source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        owner_group_id = row.get('owner_group_id')
        document_item['group_id'] = owner_group_id
        document_item['owner_group_id'] = owner_group_id
        document_item['shared_group_ids'] = _normalize_string_list(row.get('shared_group_ids'))
        if access_role == 'shared_group' and scope_id:
            shared_entry = f'{scope_id},{approval_status}'
            if shared_entry not in document_item['shared_group_ids']:
                document_item['shared_group_ids'].append(shared_entry)
    elif source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        public_workspace_id = row.get('owner_public_workspace_id')
        document_item['public_workspace_id'] = public_workspace_id
        document_item['owner_public_workspace_id'] = public_workspace_id
        document_item['user_id'] = row.get('user_id')
    else:
        owner_user_id = row.get('owner_user_id')
        document_item['user_id'] = owner_user_id
        document_item['owner_user_id'] = owner_user_id
        document_item['shared_user_ids'] = _normalize_string_list(row.get('shared_user_ids'))
        if access_role == 'shared_user' and scope_id:
            shared_entry = f'{scope_id},{approval_status}'
            if shared_entry not in document_item['shared_user_ids']:
                document_item['shared_user_ids'].append(shared_entry)

    return document_item


def _is_backfill_state_ready_for_scope(state, source_scope):
    if not isinstance(state, dict):
        return False
    if _safe_int(state.get('schema_version')) != DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION:
        return False
    if str(state.get('status') or '').strip().lower() not in DOCUMENT_ACCESS_BACKFILL_READY_STATUSES:
        return False
    completed_scopes = {
        str(scope or '').strip().lower()
        for scope in state.get('completed_source_scopes') or []
    }
    return source_scope in completed_scopes


def _get_document_access_index_readiness(source_scope, settings=None):
    normalized_settings = get_document_access_index_settings(settings)
    if not normalized_settings.get('container_enabled'):
        return {
            'ready': False,
            'status': 'container_disabled',
            'settings': normalized_settings,
        }
    if not normalized_settings.get('reads_enabled'):
        return {
            'ready': False,
            'status': 'reads_disabled',
            'settings': normalized_settings,
        }
    try:
        state = _read_backfill_state()
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] DAI read path readiness check failed; source document read should be used.',
            extra={'source_scope': source_scope, 'error': str(exc)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return {
            'ready': False,
            'status': 'readiness_check_failed',
            'settings': normalized_settings,
        }
    if not _is_backfill_state_ready_for_scope(state, source_scope):
        return {
            'ready': False,
            'status': 'backfill_not_ready',
            'settings': normalized_settings,
            'backfill_status': (state or {}).get('status'),
        }

    has_repair_backlog = has_document_access_index_repair_backlog()
    if has_repair_backlog is None:
        return {
            'ready': False,
            'status': 'repair_backlog_unknown',
            'settings': normalized_settings,
            'backfill_status': state.get('status'),
        }
    if has_repair_backlog:
        return {
            'ready': False,
            'status': 'repair_backlog_present',
            'settings': normalized_settings,
            'backfill_status': state.get('status'),
        }

    return {
        'ready': True,
        'status': 'ready',
        'settings': normalized_settings,
        'backfill_status': state.get('status'),
    }


def query_document_access_index_documents(
    source_scope,
    user_id=None,
    group_ids=None,
    public_workspace_id=None,
    public_workspace_ids=None,
    filters=None,
    settings=None,
):
    """Return list-ready documents from DAI when the default read path is ready."""
    source_scope = str(source_scope or '').strip().lower()
    if source_scope not in DOCUMENT_ACCESS_SOURCE_SCOPES:
        return {
            'success': False,
            'status': 'invalid_source_scope',
            'documents': [],
        }

    readiness = _get_document_access_index_readiness(source_scope, settings=settings)
    if not readiness.get('ready'):
        _record_document_access_read_metric(
            'document_list',
            source_scope,
            readiness.get('status'),
            served_from_index=False,
        )
        return {
            'success': False,
            'status': readiness.get('status'),
            'documents': [],
            'readiness': readiness,
        }

    scope_keys = [
        scope_key
        for scope_key in _build_shadow_scope(
            source_scope,
            user_id=user_id,
            group_ids=group_ids,
            public_workspace_id=public_workspace_id,
            public_workspace_ids=public_workspace_ids,
        )
        if scope_key
    ]
    if not scope_keys:
        _record_document_access_read_metric(
            'document_list',
            source_scope,
            'missing_scope_keys',
            served_from_index=False,
        )
        return {
            'success': False,
            'status': 'missing_scope_keys',
            'documents': [],
            'readiness': readiness,
        }

    normalized_settings = readiness.get('settings') if isinstance(readiness.get('settings'), dict) else get_document_access_index_settings(settings)
    cache_context = _build_document_access_cache_context(
        'document_list',
        source_scope,
        scope_keys,
        {'filters': filters or {}},
        normalized_settings,
    )
    cached_payload = _try_get_document_access_cache_entry(cache_context)
    if cached_payload is not None:
        cached_documents = copy.deepcopy(cached_payload.get('documents') or [])
        cache_diagnostics = {
            'label': 'document_access_index_cache_hit',
            'request_charge': 0,
            'elapsed_ms': None,
            'item_count': len(cached_documents),
            'page_count': 0,
            'cache_hit': True,
        }
        _record_document_access_read_metric(
            'document_list',
            source_scope,
            'served_from_cache',
            served_from_index=True,
            diagnostics=cache_diagnostics,
            scope_key_count=len(scope_keys),
            served_from_cache=True,
            cache_status='hit',
        )
        return {
            'success': True,
            'status': 'served_from_cache',
            'documents': cached_documents,
            'scope_keys': copy.deepcopy(cached_payload.get('scope_keys') or scope_keys),
            'diagnostics': cache_diagnostics,
            'readiness': readiness,
            'cache': {
                'hit': True,
                'ttl_seconds': normalized_settings.get('cache_ttl_seconds'),
            },
        }

    projection_rows = []
    diagnostics = []
    try:
        for scope_key in scope_keys:
            scope_rows, scope_diagnostics = _query_candidate_projection_rows_for_scope(
                scope_key,
                source_scope,
            )
            projection_rows.extend(scope_rows)
            diagnostics.append(scope_diagnostics)
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] DAI read path failed; source document read should be used.',
            extra={
                'source_scope': source_scope,
                'scope_key_count': len(scope_keys),
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        _record_document_access_read_metric(
            'document_list',
            source_scope,
            'query_failed',
            served_from_index=False,
            scope_key_count=len(scope_keys),
            error=exc,
        )
        return {
            'success': False,
            'status': 'query_failed',
            'documents': [],
            'scope_keys': scope_keys,
            'error': str(exc),
            'readiness': readiness,
        }

    rows_by_identity = {}
    for row in projection_rows:
        if not _matches_shadow_filters(row, filters):
            continue
        identity = _document_family_identity(row, source_scope)
        if not identity:
            continue
        rows_by_identity[identity] = _prefer_projection_row(rows_by_identity.get(identity), row)

    documents = [
        _projection_row_to_document(row, source_scope)
        for row in rows_by_identity.values()
    ]
    combined_diagnostics = _combine_query_diagnostics('document_access_index_read', diagnostics)
    _record_document_access_read_metric(
        'document_list',
        source_scope,
        'served_from_index',
        served_from_index=True,
        diagnostics=combined_diagnostics,
        scope_key_count=len(scope_keys),
    )
    _try_set_document_access_cache_entry(
        cache_context,
        {
            'documents': documents,
            'scope_keys': scope_keys,
        },
    )
    return {
        'success': True,
        'status': 'served_from_index',
        'documents': documents,
        'scope_keys': scope_keys,
        'diagnostics': combined_diagnostics,
        'readiness': readiness,
        'cache': {
            'hit': False,
            'ttl_seconds': normalized_settings.get('cache_ttl_seconds'),
        },
    }


def _projection_rows_to_tag_counts(rows, source_scope):
    owner_access_roles = {'owner'}
    if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        owner_access_roles.add('public_workspace')

    rows_by_identity = {}
    for row in rows or []:
        access_role = str(row.get('access_role') or '').strip().lower()
        if access_role not in owner_access_roles:
            continue
        identity = _document_family_identity(row, source_scope)
        if not identity:
            continue
        rows_by_identity[identity] = _prefer_projection_row(rows_by_identity.get(identity), row)

    tag_counts = {}
    for row in rows_by_identity.values():
        for tag in _normalize_string_list(row.get('tags')):
            normalized_tag = _normalize_filter_text(tag)
            if normalized_tag:
                tag_counts[normalized_tag] = tag_counts.get(normalized_tag, 0) + 1

    return tag_counts


def _merge_tag_counts(tag_count_items):
    merged_counts = {}
    for tag_counts in tag_count_items or []:
        for tag_name, count in (tag_counts or {}).items():
            normalized_tag = _normalize_filter_text(tag_name)
            if not normalized_tag:
                continue
            merged_counts[normalized_tag] = merged_counts.get(normalized_tag, 0) + _safe_int(count)
    return merged_counts


def query_document_access_index_tag_counts(
    source_scope,
    user_id=None,
    group_ids=None,
    public_workspace_id=None,
    public_workspace_ids=None,
    settings=None,
):
    """Return document tag counts from DAI when the default read path is ready."""
    source_scope = str(source_scope or '').strip().lower()
    if source_scope not in DOCUMENT_ACCESS_SOURCE_SCOPES:
        return {
            'success': False,
            'status': 'invalid_source_scope',
            'tag_counts': {},
            'tag_counts_by_scope_key': {},
        }

    readiness = _get_document_access_index_readiness(source_scope, settings=settings)
    if not readiness.get('ready'):
        _record_document_access_read_metric(
            'tag_list',
            source_scope,
            readiness.get('status'),
            served_from_index=False,
        )
        return {
            'success': False,
            'status': readiness.get('status'),
            'tag_counts': {},
            'tag_counts_by_scope_key': {},
            'readiness': readiness,
        }

    scope_keys = [
        scope_key
        for scope_key in _build_shadow_scope(
            source_scope,
            user_id=user_id,
            group_ids=group_ids,
            public_workspace_id=public_workspace_id,
            public_workspace_ids=public_workspace_ids,
        )
        if scope_key
    ]
    if not scope_keys:
        _record_document_access_read_metric(
            'tag_list',
            source_scope,
            'missing_scope_keys',
            served_from_index=False,
        )
        return {
            'success': False,
            'status': 'missing_scope_keys',
            'tag_counts': {},
            'tag_counts_by_scope_key': {},
            'readiness': readiness,
        }

    normalized_settings = readiness.get('settings') if isinstance(readiness.get('settings'), dict) else get_document_access_index_settings(settings)
    cache_context = _build_document_access_cache_context(
        'tag_list',
        source_scope,
        scope_keys,
        {},
        normalized_settings,
    )
    cached_payload = _try_get_document_access_cache_entry(cache_context)
    if cached_payload is not None:
        cached_tag_counts = copy.deepcopy(cached_payload.get('tag_counts') or {})
        cached_tag_counts_by_scope_key = copy.deepcopy(cached_payload.get('tag_counts_by_scope_key') or {})
        cache_diagnostics = {
            'label': 'document_access_index_tag_cache_hit',
            'request_charge': 0,
            'elapsed_ms': None,
            'item_count': len(cached_tag_counts),
            'page_count': 0,
            'cache_hit': True,
        }
        _record_document_access_read_metric(
            'tag_list',
            source_scope,
            'served_from_cache',
            served_from_index=True,
            diagnostics=cache_diagnostics,
            scope_key_count=len(scope_keys),
            served_from_cache=True,
            cache_status='hit',
        )
        return {
            'success': True,
            'status': 'served_from_cache',
            'tag_counts': cached_tag_counts,
            'tag_counts_by_scope_key': cached_tag_counts_by_scope_key,
            'scope_keys': copy.deepcopy(cached_payload.get('scope_keys') or scope_keys),
            'readiness': readiness,
            'cache': {
                'hit': True,
                'ttl_seconds': normalized_settings.get('cache_ttl_seconds'),
            },
        }

    diagnostics = []
    tag_counts_by_scope_key = {}
    try:
        for scope_key in scope_keys:
            scope_rows, scope_diagnostics = _query_tag_projection_rows_for_scope(
                scope_key,
                source_scope,
            )
            tag_counts_by_scope_key[scope_key] = _projection_rows_to_tag_counts(
                scope_rows,
                source_scope,
            )
            diagnostics.append(scope_diagnostics)
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] DAI tag read path failed; source document tag read should be used.',
            extra={
                'source_scope': source_scope,
                'scope_key_count': len(scope_keys),
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        _record_document_access_read_metric(
            'tag_list',
            source_scope,
            'query_failed',
            served_from_index=False,
            scope_key_count=len(scope_keys),
            error=exc,
        )
        return {
            'success': False,
            'status': 'query_failed',
            'tag_counts': {},
            'tag_counts_by_scope_key': {},
            'scope_keys': scope_keys,
            'error': str(exc),
            'readiness': readiness,
        }

    combined_diagnostics = _combine_query_diagnostics('document_access_index_tag_read', diagnostics)
    _record_document_access_read_metric(
        'tag_list',
        source_scope,
        'served_from_index',
        served_from_index=True,
        diagnostics=combined_diagnostics,
        scope_key_count=len(scope_keys),
    )
    result = {
        'success': True,
        'status': 'served_from_index',
        'tag_counts': _merge_tag_counts(tag_counts_by_scope_key.values()),
        'tag_counts_by_scope_key': tag_counts_by_scope_key,
        'scope_keys': scope_keys,
        'cache': {
            'hit': False,
            'ttl_seconds': normalized_settings.get('cache_ttl_seconds'),
        },
    }
    _try_set_document_access_cache_entry(
        cache_context,
        {
            'tag_counts': result['tag_counts'],
            'tag_counts_by_scope_key': tag_counts_by_scope_key,
            'scope_keys': scope_keys,
        },
    )
    return result


def query_document_access_index_legacy_count(
    source_scope,
    user_id=None,
    group_ids=None,
    public_workspace_id=None,
    public_workspace_ids=None,
    settings=None,
):
    """Return the unfiltered owner-scope legacy document count from DAI."""
    source_scope = str(source_scope or '').strip().lower()
    if source_scope not in DOCUMENT_ACCESS_SOURCE_SCOPES:
        return {
            'success': False,
            'status': 'invalid_source_scope',
            'legacy_count': 0,
        }

    readiness = _get_document_access_index_readiness(source_scope, settings=settings)
    if not readiness.get('ready'):
        return {
            'success': False,
            'status': readiness.get('status'),
            'legacy_count': 0,
            'readiness': readiness,
        }

    scope_keys = [
        scope_key
        for scope_key in _build_shadow_scope(
            source_scope,
            user_id=user_id,
            group_ids=group_ids,
            public_workspace_id=public_workspace_id,
            public_workspace_ids=public_workspace_ids,
        )
        if scope_key
    ]
    if not scope_keys:
        return {
            'success': False,
            'status': 'missing_scope_keys',
            'legacy_count': 0,
            'readiness': readiness,
        }

    normalized_settings = readiness.get('settings') if isinstance(readiness.get('settings'), dict) else get_document_access_index_settings(settings)
    access_role = 'public_workspace' if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC else 'owner'
    cache_context = _build_document_access_cache_context(
        'legacy_count',
        source_scope,
        scope_keys,
        {'access_role': access_role},
        normalized_settings,
    )
    cached_payload = _try_get_document_access_cache_entry(cache_context)
    if cached_payload is not None:
        return {
            'success': True,
            'status': 'served_from_cache',
            'legacy_count': _safe_int(cached_payload.get('legacy_count')),
            'scope_keys': copy.deepcopy(cached_payload.get('scope_keys') or scope_keys),
            'readiness': readiness,
            'cache': {
                'hit': True,
                'ttl_seconds': normalized_settings.get('cache_ttl_seconds'),
            },
        }

    legacy_identities = set()
    try:
        for scope_key in scope_keys:
            for row in _query_legacy_projection_rows_for_scope(scope_key, source_scope, access_role):
                identity = _document_identity(row)
                if identity:
                    legacy_identities.add(identity)
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] DAI legacy count query failed; legacy update prompt should use safe default.',
            extra={
                'source_scope': source_scope,
                'scope_key_count': len(scope_keys),
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return {
            'success': False,
            'status': 'query_failed',
            'legacy_count': 0,
            'scope_keys': scope_keys,
            'error': str(exc),
            'readiness': readiness,
        }

    result = {
        'success': True,
        'status': 'served_from_index',
        'legacy_count': len(legacy_identities),
        'scope_keys': scope_keys,
        'readiness': readiness,
        'cache': {
            'hit': False,
            'ttl_seconds': normalized_settings.get('cache_ttl_seconds'),
        },
    }
    _try_set_document_access_cache_entry(
        cache_context,
        {
            'legacy_count': result['legacy_count'],
            'scope_keys': scope_keys,
        },
    )
    return result


def _matches_shadow_filters(row, filters):
    filters = filters or {}
    array_match_mode = str(filters.get('array_match_mode') or 'contains').strip().lower()

    def array_matches(items, filter_value):
        if array_match_mode == 'exact':
            raw_filter = str(filter_value or '').strip()
            if not raw_filter:
                return True
            raw_items = [str(item or '').strip() for item in items or []]
            return any(item == raw_filter for item in raw_items)

        normalized_filter = _normalize_filter_text(filter_value)
        if not normalized_filter:
            return True
        normalized_items = [_normalize_filter_text(item) for item in items or []]
        return any(normalized_filter in item for item in normalized_items)

    search_term = _normalize_filter_text(filters.get('search'))
    if search_term:
        searchable_text = ' '.join([
            _normalize_filter_text(row.get('file_name')),
            _normalize_filter_text(row.get('title')),
        ])
        if search_term not in searchable_text:
            return False

    classification_filter_raw = str(filters.get('classification') or '').strip()
    if classification_filter_raw:
        classification_filter = _normalize_filter_text(classification_filter_raw)
        classification = str(row.get('document_classification') or '').strip()
        if classification_filter == 'none':
            normalized_classification = _normalize_filter_text(classification)
            none_values = {'', 'none'} if filters.get('classification_none_matches_literal') else {''}
            if normalized_classification not in none_values:
                return False
        elif classification != classification_filter_raw:
            return False

    if not array_matches(row.get('authors'), filters.get('author')):
        return False

    if not array_matches(row.get('keywords'), filters.get('keywords')):
        return False

    abstract_filter = _normalize_filter_text(filters.get('abstract'))
    if abstract_filter and abstract_filter not in _normalize_filter_text(row.get('abstract')):
        return False

    tag_filters = [
        _normalize_filter_text(tag)
        for tag in filters.get('tags') or []
        if _normalize_filter_text(tag)
    ]
    if tag_filters:
        row_tags = {_normalize_filter_text(tag) for tag in row.get('tags') or []}
        if not all(tag in row_tags for tag in tag_filters):
            return False

    return True


def _build_shadow_scope(source_scope, user_id=None, group_ids=None, public_workspace_id=None, public_workspace_ids=None):
    if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        workspace_ids = list(public_workspace_ids or [])
        if not workspace_ids and public_workspace_id:
            workspace_ids = [public_workspace_id]
        return [
            build_document_access_scope_key(DOCUMENT_ACCESS_SCOPE_PUBLIC, workspace_id)
            for workspace_id in workspace_ids
        ]
    if source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        return [
            build_document_access_scope_key(DOCUMENT_ACCESS_SCOPE_GROUP, group_id)
            for group_id in list(group_ids or [])
        ]
    return [build_document_access_scope_key(DOCUMENT_ACCESS_PRINCIPAL_USER, user_id)]


def validate_document_access_index_shadow(
    authoritative_documents,
    source_scope,
    user_id=None,
    group_ids=None,
    public_workspace_id=None,
    public_workspace_ids=None,
    filters=None,
    source_query_metrics=None,
    settings=None,
    context='document_list',
):
    """Compare source document-list results with projection rows without changing reads."""
    normalized_settings = get_document_access_index_settings(settings)
    source_scope = str(source_scope or '').strip().lower()
    if not normalized_settings.get('container_enabled') or not normalized_settings.get('shadow_validation_enabled'):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'context': context,
        }
    if source_scope not in DOCUMENT_ACCESS_SOURCE_SCOPES:
        return {
            'success': False,
            'status': 'skipped_invalid_scope',
            'context': context,
        }

    scope_keys = [
        scope_key
        for scope_key in _build_shadow_scope(
            source_scope,
            user_id=user_id,
            group_ids=group_ids,
            public_workspace_id=public_workspace_id,
            public_workspace_ids=public_workspace_ids,
        )
        if scope_key
    ]
    if not scope_keys:
        return {
            'success': False,
            'status': 'skipped_missing_scope',
            'context': context,
        }

    projection_query_metrics = None
    candidate_read_metrics = None
    try:
        authoritative_ids = {
            identity
            for identity in (
                _document_family_identity(document_item, source_scope)
                for document_item in authoritative_documents or []
            )
            if identity
        }
        projection_rows = []
        projection_scope_diagnostics = []
        for scope_key in scope_keys:
            scope_rows, scope_diagnostics = _query_projection_rows_for_scope_with_diagnostics(scope_key, source_scope)
            projection_rows.extend(scope_rows)
            projection_scope_diagnostics.append(scope_diagnostics)
        projection_query_metrics = _combine_query_diagnostics(
            'projection',
            projection_scope_diagnostics,
        )
        candidate_read_metrics = _collect_candidate_read_metrics(
            scope_keys,
            source_scope,
        )

        projection_ids = {
            identity
            for identity in (
                _document_family_identity(row, source_scope)
                for row in projection_rows
                if _matches_shadow_filters(row, filters)
            )
            if identity
        }
        missing_from_projection = sorted(authoritative_ids - projection_ids)
        extra_in_projection = sorted(projection_ids - authoritative_ids)
        status = 'matched' if not missing_from_projection and not extra_in_projection else 'mismatch'
        result = {
            'success': status == 'matched',
            'status': status,
            'context': context,
            'source_scope': source_scope,
            'scope_keys': scope_keys,
            'authoritative_count': len(authoritative_ids),
            'projection_count': len(projection_ids),
            'missing_count': len(missing_from_projection),
            'extra_count': len(extra_in_projection),
            'missing_sample': missing_from_projection[:DOCUMENT_ACCESS_SHADOW_MAX_SAMPLE_IDS],
            'extra_sample': extra_in_projection[:DOCUMENT_ACCESS_SHADOW_MAX_SAMPLE_IDS],
            'checked_at': _utc_now_iso(),
        }
        result.update(_build_shadow_metric_fields(
            source_query_metrics,
            projection_query_metrics,
            candidate_read_metrics,
        ))
        _write_shadow_validation_state(result)
        log_level = logging.INFO if status == 'matched' else logging.WARNING
        log_event(
            '[DocumentAccessIndex] Shadow validation completed.',
            extra=result,
            level=log_level,
        )
        return result
    except Exception as exc:
        result = {
            'success': False,
            'status': 'error',
            'context': context,
            'source_scope': source_scope,
            'scope_keys': scope_keys,
            'error': str(exc),
            'checked_at': _utc_now_iso(),
        }
        result.update(_build_shadow_metric_fields(
            source_query_metrics,
            projection_query_metrics,
            candidate_read_metrics,
        ))
        try:
            _write_shadow_validation_state(result)
        except Exception as state_error:
            log_event(
                '[DocumentAccessIndex] Failed to persist shadow validation error state.',
                extra={'error': str(state_error), 'shadow_error': str(exc)},
                level=logging.WARNING,
                exceptionTraceback=True,
            )
        log_event(
            '[DocumentAccessIndex] Shadow validation failed; source document results remain authoritative.',
            extra=result,
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return result


def _repair_document_id(source_scope, document_id):
    raw_id = f'document_access_projection_repair:{source_scope}:{document_id}'
    if len(raw_id) <= 900:
        return raw_id
    return f'document_access_projection_repair:{hashlib.sha256(raw_id.encode("utf-8")).hexdigest()}'


def _record_projection_repair_required(document_item, operation, error):
    document_item = document_item if isinstance(document_item, dict) else {}
    document_id = str(document_item.get('id') or document_item.get('document_id') or '').strip()
    if not document_id:
        return None
    source_scope = _resolve_source_scope(document_item)
    repair_doc_id = _repair_document_id(source_scope, document_id)
    repair_doc = {
        'id': repair_doc_id,
        'type': DOCUMENT_ACCESS_REPAIR_TYPE,
        'status': 'repair_required',
        'operation': operation,
        'source_scope': source_scope,
        'source_document_id': document_id,
        'source_updated_at': document_item.get('last_updated') or document_item.get('upload_date'),
        'error': str(error),
        'updated_at': _utc_now_iso(),
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
    }
    cache_scope_keys = _cache_scope_keys_from_exception(error)
    if cache_scope_keys:
        repair_doc['cache_scope_keys'] = cache_scope_keys
    try:
        cosmos_settings_container.upsert_item(repair_doc)
    except Exception:
        _try_write_repair_backlog_state(
            True,
            reason=f'{operation}_repair_doc_write_failed',
            repair_tracking_failed=True,
        )
        raise

    if _try_write_repair_backlog_state(True, reason=operation) is None:
        _try_delete_repair_backlog_state(reason=f'{operation}_repair_state_untrusted')
    return repair_doc


def _clear_projection_repair_required(source_scope, document_id):
    repair_doc_id = _repair_document_id(source_scope, document_id)
    try:
        cosmos_settings_container.delete_item(item=repair_doc_id, partition_key=repair_doc_id)
    except Exception as exc:
        if _is_not_found_error(exc):
            pass
        else:
            log_event(
                '[DocumentAccessIndex] Failed to clear projection repair state.',
                extra={
                    'source_scope': source_scope,
                    'document_id': document_id,
                    'error': str(exc),
                },
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            return

    try:
        has_backlog = _query_repair_backlog_exists()
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] Failed to refresh projection repair backlog state after repair clear.',
            extra={
                'source_scope': source_scope,
                'document_id': document_id,
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return

    if not has_backlog:
        try:
            state = _read_repair_backlog_state()
        except Exception as exc:
            log_event(
                '[DocumentAccessIndex] Failed to verify repair backlog state after repair clear.',
                extra={
                    'source_scope': source_scope,
                    'document_id': document_id,
                    'error': str(exc),
                },
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            return
        if _repair_backlog_state_has_untracked_failure(state):
            return

    updated_state = _try_write_repair_backlog_state(has_backlog, reason='repair_cleared')
    if updated_state is None and not has_backlog:
        _try_delete_repair_backlog_state(reason='repair_cleared_write_failed')


def sync_document_access_index_for_document(
    document_item,
    operation=DOCUMENT_ACCESS_OPERATION_UPSERT,
    settings=None,
    force=False,
):
    """Synchronize access-index rows for one source document."""
    if not _is_write_through_enabled(settings, force=force):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'operation': operation,
            'upserted_count': 0,
            'deleted_count': 0,
        }

    rows = build_document_access_index_rows(document_item)
    document_id = str((document_item or {}).get('id') or (document_item or {}).get('document_id') or '').strip()
    if not document_id:
        raise ValueError('document_item must include id or document_id')

    source_scope = _resolve_source_scope(document_item)
    expected_keys = {(row['scope_key'], row['id']) for row in rows}
    existing_rows = _query_existing_projection_rows(source_scope, document_id)
    affected_scope_keys = sorted({
        row.get('scope_key')
        for row in rows + existing_rows
        if row.get('scope_key')
    })
    deleted_count = 0

    try:
        for existing_row in existing_rows:
            existing_key = (existing_row.get('scope_key'), existing_row.get('id'))
            if existing_key in expected_keys:
                continue
            cosmos_document_access_index_container.delete_item(
                item=existing_row.get('id'),
                partition_key=existing_row.get('scope_key'),
            )
            deleted_count += 1

        for row in rows:
            cosmos_document_access_index_container.upsert_item(copy.deepcopy(row))

        _clear_projection_repair_required(source_scope, document_id)
        invalidation_result = invalidate_document_access_index_cache_scope_keys(
            affected_scope_keys,
            reason=operation,
            settings=settings,
        )
        _raise_for_failed_cache_invalidation(invalidation_result, operation, affected_scope_keys)
    except DocumentAccessIndexCacheInvalidationError:
        raise
    except Exception as exc:
        raise DocumentAccessIndexProjectionMutationError(operation, exc, affected_scope_keys) from exc

    return {
        'success': True,
        'status': 'synchronized',
        'operation': operation,
        'source_scope': source_scope,
        'document_id': document_id,
        'upserted_count': len(rows),
        'deleted_count': deleted_count,
    }


def delete_document_access_index_for_document(
    document_item,
    operation=DOCUMENT_ACCESS_OPERATION_DELETE,
    settings=None,
    force=False,
):
    """Delete all access-index rows for one source document."""
    if not _is_write_through_enabled(settings, force=force):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'operation': operation,
            'deleted_count': 0,
        }

    document_id = str((document_item or {}).get('id') or (document_item or {}).get('document_id') or '').strip()
    if not document_id:
        raise ValueError('document_item must include id or document_id')

    source_scope = _resolve_source_scope(document_item)
    existing_rows = _query_existing_projection_rows(source_scope, document_id)
    affected_scope_keys = sorted({
        existing_row.get('scope_key')
        for existing_row in existing_rows
        if existing_row.get('scope_key')
    }) or _document_access_scope_keys_from_document_item(document_item)
    deleted_count = 0
    try:
        for existing_row in existing_rows:
            cosmos_document_access_index_container.delete_item(
                item=existing_row.get('id'),
                partition_key=existing_row.get('scope_key'),
            )
            deleted_count += 1

        _clear_projection_repair_required(source_scope, document_id)
        invalidation_result = invalidate_document_access_index_cache_scope_keys(
            affected_scope_keys,
            reason=operation,
            settings=settings,
        )
        _raise_for_failed_cache_invalidation(invalidation_result, operation, affected_scope_keys)
    except DocumentAccessIndexCacheInvalidationError:
        raise
    except Exception as exc:
        raise DocumentAccessIndexProjectionMutationError(operation, exc, affected_scope_keys) from exc

    return {
        'success': True,
        'status': 'deleted',
        'operation': operation,
        'source_scope': source_scope,
        'document_id': document_id,
        'deleted_count': deleted_count,
    }


def sync_document_access_index_for_document_fail_open(document_item, operation=DOCUMENT_ACCESS_OPERATION_UPSERT, settings=None):
    """Synchronize projection rows without failing the source document mutation."""
    try:
        return sync_document_access_index_for_document(document_item, operation=operation, settings=settings)
    except Exception as exc:
        cache_scope_keys = (
            _cache_scope_keys_from_exception(exc)
            or _document_access_scope_keys_from_document_item(document_item)
        )
        invalidate_document_access_index_cache_scope_keys(
            cache_scope_keys,
            reason=f'{operation}_failed',
            settings=settings,
        )
        log_event(
            '[DocumentAccessIndex] Document access index synchronization failed; source document remains authoritative.',
            extra={
                'document_id': (document_item or {}).get('id'),
                'operation': operation,
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        try:
            _record_projection_repair_required(document_item, operation, exc)
        except Exception as repair_exc:
            log_event(
                '[DocumentAccessIndex] Failed to record projection repair state.',
                extra={
                    'document_id': (document_item or {}).get('id'),
                    'operation': operation,
                    'error': str(repair_exc),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
        return {
            'success': False,
            'status': 'repair_required',
            'operation': operation,
            'error': str(exc),
        }


def delete_document_access_index_for_document_fail_open(document_item, operation=DOCUMENT_ACCESS_OPERATION_DELETE, settings=None):
    """Delete projection rows without failing the source document mutation."""
    try:
        return delete_document_access_index_for_document(document_item, operation=operation, settings=settings)
    except Exception as exc:
        cache_scope_keys = (
            _cache_scope_keys_from_exception(exc)
            or _document_access_scope_keys_from_document_item(document_item)
        )
        invalidate_document_access_index_cache_scope_keys(
            cache_scope_keys,
            reason=f'{operation}_failed',
            settings=settings,
        )
        log_event(
            '[DocumentAccessIndex] Document access index delete failed; source document remains authoritative.',
            extra={
                'document_id': (document_item or {}).get('id'),
                'operation': operation,
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        try:
            _record_projection_repair_required(document_item, operation, exc)
        except Exception as repair_exc:
            log_event(
                '[DocumentAccessIndex] Failed to record projection delete repair state.',
                extra={
                    'document_id': (document_item or {}).get('id'),
                    'operation': operation,
                    'error': str(repair_exc),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
        return {
            'success': False,
            'status': 'repair_required',
            'operation': operation,
            'error': str(exc),
        }


def _write_repair_backlog_state(
    has_repair_backlog,
    repair_required_count=None,
    reason=None,
    repair_tracking_failed=False,
):
    state_doc = {
        'id': DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID,
        'type': DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_TYPE,
        'has_repair_backlog': bool(has_repair_backlog),
        'updated_at': _utc_now_iso(),
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
    }
    if repair_required_count is not None:
        state_doc['repair_required_count'] = _safe_int(repair_required_count)
    if reason:
        state_doc['reason'] = str(reason)
    if repair_tracking_failed:
        state_doc['repair_tracking_failed'] = True
    cosmos_settings_container.upsert_item(state_doc)
    _set_cached_document_access_state(DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID, state_doc)
    return state_doc


def _try_write_repair_backlog_state(
    has_repair_backlog,
    repair_required_count=None,
    reason=None,
    repair_tracking_failed=False,
):
    try:
        return _write_repair_backlog_state(
            has_repair_backlog,
            repair_required_count=repair_required_count,
            reason=reason,
            repair_tracking_failed=repair_tracking_failed,
        )
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] Failed to update projection repair backlog state.',
            extra={
                'has_repair_backlog': bool(has_repair_backlog),
                'repair_required_count': repair_required_count,
                'reason': reason,
                'repair_tracking_failed': bool(repair_tracking_failed),
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def _try_delete_repair_backlog_state(reason=None):
    try:
        cosmos_settings_container.delete_item(
            item=DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID,
            partition_key=DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID,
        )
        _set_cached_document_access_state(DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID, None)
        return True
    except Exception as exc:
        if _is_not_found_error(exc):
            _set_cached_document_access_state(DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID, None)
            return True
        log_event(
            '[DocumentAccessIndex] Failed to delete projection repair backlog state.',
            extra={
                'reason': reason,
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return False


def _read_repair_backlog_state(use_cache=True):
    if use_cache:
        cache_hit, cached_state = _get_cached_document_access_state(DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID)
        if cache_hit:
            return cached_state
    try:
        state = cosmos_settings_container.read_item(
            item=DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID,
            partition_key=DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID,
        )
    except Exception as exc:
        if _is_not_found_error(exc):
            _set_cached_document_access_state(DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID, None)
            return None
        raise
    if not isinstance(state, dict) or state.get('type') != DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_TYPE:
        _set_cached_document_access_state(DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID, None)
        return None
    if not isinstance(state.get('has_repair_backlog'), bool):
        _set_cached_document_access_state(DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID, None)
        return None
    _set_cached_document_access_state(DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID, state)
    return state


def _repair_backlog_state_has_untracked_failure(state):
    return (
        isinstance(state, dict)
        and bool(state.get('has_repair_backlog'))
        and bool(state.get('repair_tracking_failed'))
    )


def _query_repair_backlog_exists():
    query = (
        'SELECT TOP 1 VALUE c.id FROM c '
        'WHERE c.type = @type AND c.status = @status'
    )
    repair_ids = list(cosmos_settings_container.query_items(
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_REPAIR_TYPE},
            {'name': '@status', 'value': 'repair_required'},
        ],
        enable_cross_partition_query=True,
        max_item_count=1,
    ))
    return bool(repair_ids)


def _refresh_repair_backlog_state_from_query(reason=None):
    existing_state = _read_repair_backlog_state(use_cache=False)
    has_backlog = _query_repair_backlog_exists()
    if not has_backlog and _repair_backlog_state_has_untracked_failure(existing_state):
        return True
    _write_repair_backlog_state(has_backlog, reason=reason or 'repair_backlog_query')
    return has_backlog


def _get_source_scope_container(source_scope):
    if source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        return cosmos_group_documents_container, cosmos_group_documents_container_name
    if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        return cosmos_public_documents_container, cosmos_public_documents_container_name
    return cosmos_user_documents_container, cosmos_user_documents_container_name


def _normalize_source_scopes(source_scopes=None):
    if not source_scopes:
        return list(DOCUMENT_ACCESS_SOURCE_SCOPES)
    if isinstance(source_scopes, str):
        source_scopes = [source_scopes]
    normalized_scopes = []
    for source_scope in list(source_scopes or []):
        normalized_scope = str(source_scope or '').strip().lower()
        if normalized_scope in DOCUMENT_ACCESS_SOURCE_SCOPES and normalized_scope not in normalized_scopes:
            normalized_scopes.append(normalized_scope)
    return normalized_scopes or list(DOCUMENT_ACCESS_SOURCE_SCOPES)


def _query_first_page(container, query, parameters=None, continuation_token=None, max_item_count=100):
    query_iterable = container.query_items(
        query=query,
        parameters=list(parameters or []),
        enable_cross_partition_query=True,
        max_item_count=max_item_count,
    )
    if not hasattr(query_iterable, 'by_page'):
        return list(query_iterable), None

    try:
        page_iterator = query_iterable.by_page(continuation_token=continuation_token)
    except TypeError:
        page_iterator = query_iterable.by_page(continuation_token)
    try:
        page = next(page_iterator)
    except StopIteration:
        return [], None

    return list(page), getattr(page_iterator, 'continuation_token', None)


def _query_source_document_page(source_scope, continuation_token=None, max_item_count=100):
    source_container, source_container_name = _get_source_scope_container(source_scope)
    query = (
        'SELECT * FROM c '
        'WHERE (NOT IS_DEFINED(c.type) OR c.type = @document_metadata_type)'
    )
    documents, next_token = _query_first_page(
        source_container,
        query=query,
        parameters=[{'name': '@document_metadata_type', 'value': 'document_metadata'}],
        continuation_token=continuation_token,
        max_item_count=max_item_count,
    )
    return {
        'source_scope': source_scope,
        'source_container': source_container_name,
        'documents': documents,
        'continuation_token': next_token,
    }


def _query_repair_documents(max_item_count=DOCUMENT_ACCESS_DEFAULT_REPAIR_BATCH_SIZE):
    query = (
        'SELECT * FROM c '
        'WHERE c.type = @type AND c.status = @status'
    )
    repair_docs, _next_token = _query_first_page(
        cosmos_settings_container,
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_REPAIR_TYPE},
            {'name': '@status', 'value': 'repair_required'},
        ],
        max_item_count=max_item_count,
    )
    return repair_docs


def _read_backfill_state(use_cache=True):
    if use_cache:
        cache_hit, cached_state = _get_cached_document_access_state(DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID)
        if cache_hit:
            return cached_state
    try:
        state = cosmos_settings_container.read_item(
            item=DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID,
            partition_key=DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID,
        )
    except Exception as exc:
        if _is_not_found_error(exc):
            _set_cached_document_access_state(DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID, None)
            return None
        log_event(
            '[DocumentAccessIndex] Failed to read document access index backfill state.',
            extra={'error': str(exc)},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise
    _set_cached_document_access_state(DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID, state)
    return state


def _write_backfill_state(state):
    state_body = copy.deepcopy(state or {})
    state_body.update({
        'id': DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID,
        'type': DOCUMENT_ACCESS_BACKFILL_STATE_TYPE,
        'updated_at': _utc_now_iso(),
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
    })
    cosmos_settings_container.upsert_item(state_body)
    _set_cached_document_access_state(DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID, state_body)
    return state_body


def _build_initial_backfill_state(source_scopes):
    return {
        'id': DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID,
        'type': DOCUMENT_ACCESS_BACKFILL_STATE_TYPE,
        'status': 'not_started',
        'source_scopes': list(source_scopes),
        'completed_source_scopes': [],
        'continuation_tokens': {},
        'current_source_scope': None,
        'total_documents_processed': 0,
        'total_documents_failed': 0,
        'total_rows_upserted': 0,
        'total_rows_deleted': 0,
        'last_error': None,
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
    }


def _get_next_backfill_scope(source_scopes, completed_source_scopes):
    completed = set(completed_source_scopes or [])
    for source_scope in source_scopes:
        if source_scope not in completed:
            return source_scope
    return None


def _repair_document_stub(source_scope, document_id):
    document_stub = {'id': document_id}
    if source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        document_stub['group_id'] = 'repair'
    elif source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        document_stub['public_workspace_id'] = 'repair'
    return document_stub


def _read_source_document_for_repair(source_scope, document_id):
    source_container, _source_container_name = _get_source_scope_container(source_scope)
    return source_container.read_item(item=document_id, partition_key=document_id)


def _repair_operation_represents_delete(operation):
    normalized_operation = str(operation or '').strip().lower()
    return 'delete' in normalized_operation or 'cleanup' in normalized_operation


def _mark_repair_document_failed(repair_doc, error):
    updated_repair_doc = copy.deepcopy(repair_doc or {})
    updated_repair_doc.update({
        'status': 'repair_required',
        'last_repair_error': str(error),
        'last_repair_attempted_at': _utc_now_iso(),
        'repair_attempt_count': int(updated_repair_doc.get('repair_attempt_count') or 0) + 1,
    })
    cosmos_settings_container.upsert_item(updated_repair_doc)
    return updated_repair_doc


def count_document_access_index_repair_documents():
    """Return the current number of projection repair documents."""
    query = (
        'SELECT VALUE COUNT(1) FROM c '
        'WHERE c.type = @type AND c.status = @status'
    )
    try:
        count_items = list(cosmos_settings_container.query_items(
            query=query,
            parameters=[
                {'name': '@type', 'value': DOCUMENT_ACCESS_REPAIR_TYPE},
                {'name': '@status', 'value': 'repair_required'},
            ],
            enable_cross_partition_query=True,
            max_item_count=1,
        ))
        repair_count = _safe_int(count_items[0]) if count_items else 0
        if repair_count <= 0:
            state = _read_repair_backlog_state()
            if _repair_backlog_state_has_untracked_failure(state):
                return None
            _try_write_repair_backlog_state(False, repair_required_count=0, reason='repair_count')
            return 0
        _try_write_repair_backlog_state(
            repair_count > 0,
            repair_required_count=repair_count,
            reason='repair_count',
        )
        return repair_count
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] Failed to count projection repair documents.',
            extra={'error': str(exc)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def has_document_access_index_repair_backlog():
    """Return whether any projection repair record is currently pending."""
    try:
        state = _read_repair_backlog_state()
        if state is not None:
            if state.get('has_repair_backlog'):
                return True
            has_backlog = _query_repair_backlog_exists()
            if has_backlog:
                _try_write_repair_backlog_state(True, reason='repair_backlog_false_state_corrected')
            return has_backlog
        return _refresh_repair_backlog_state_from_query(reason='repair_backlog_state_initialize')
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] Failed to check projection repair backlog.',
            extra={'error': str(exc)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def _build_document_access_index_maintenance_summary(state, repair_required_count, normalized_settings):
    state = state if isinstance(state, dict) else {}
    normalized_status = str(state.get('status') or 'not_started').strip().lower() or 'not_started'
    repair_count_known = repair_required_count is not None
    has_repair_work = repair_count_known and int(repair_required_count or 0) > 0
    has_unknown_repair_work = not repair_count_known
    has_backfill_work = normalized_status not in DOCUMENT_ACCESS_BACKFILL_COMPLETE_STATUSES

    if not normalized_settings.get('container_enabled'):
        next_action = 'disabled'
    elif has_unknown_repair_work:
        next_action = 'check_repair_backlog'
    elif has_repair_work:
        next_action = 'repair'
    elif has_backfill_work:
        next_action = 'backfill'
    else:
        next_action = 'monitor'

    return {
        'mode': 'automatic',
        'auto_maintenance_enabled': bool(normalized_settings.get('container_enabled')),
        'has_more_work': bool(normalized_settings.get('container_enabled') and (
            has_unknown_repair_work or has_repair_work or has_backfill_work
        )),
        'next_action': next_action,
        'backfill_status': normalized_status,
        'repair_required_count': repair_required_count,
        'last_batch_processed_count': _safe_int(state.get('last_processed_count')),
        'last_batch_failed_count': _safe_int(state.get('last_failed_count')),
        'last_batch_rows_upserted': _safe_int(state.get('last_rows_upserted')),
        'last_batch_rows_deleted': _safe_int(state.get('last_rows_deleted')),
        'last_completed_at': state.get('last_completed_at'),
        'last_error': state.get('last_error'),
    }


def is_document_access_index_maintenance_pending(status_payload):
    """Return True when DAI repair/backfill work should keep active maintenance polling."""
    if not isinstance(status_payload, dict):
        return False
    backfill_status = status_payload.get('document_access_index_backfill')
    if isinstance(backfill_status, dict):
        status_payload = backfill_status
    maintenance_summary = status_payload.get('maintenance')
    if isinstance(maintenance_summary, dict) and 'has_more_work' in maintenance_summary:
        return bool(maintenance_summary.get('has_more_work'))

    state = status_payload.get('state') if isinstance(status_payload.get('state'), dict) else {}
    repair_required_count = status_payload.get('repair_required_count')
    settings = status_payload.get('settings') if isinstance(status_payload.get('settings'), dict) else {}
    return _build_document_access_index_maintenance_summary(
        state,
        repair_required_count,
        {
            'container_enabled': settings.get('container_enabled', True),
        },
    ).get('has_more_work')


def get_document_access_index_backfill_status(settings=None):
    """Return persisted backfill state and repair backlog diagnostics."""
    normalized_settings = get_document_access_index_settings(settings)
    state = _read_backfill_state() or _build_initial_backfill_state(DOCUMENT_ACCESS_SOURCE_SCOPES)
    repair_required_count = count_document_access_index_repair_documents()
    shadow_validation = {
        'status': 'not_run',
        'missing_count': 0,
        'extra_count': 0,
        'source_query_ru': None,
        'projection_query_ru': None,
        'validation_index_ru': None,
        'candidate_read_ru': None,
        'estimated_ru_savings': None,
        'estimated_wave5_ru_savings': None,
        'shadow_overhead_ru': None,
        'source_query_ms': None,
        'projection_query_ms': None,
        'validation_index_ms': None,
        'candidate_read_ms': None,
        'estimated_ms_savings': None,
        'estimated_wave5_ms_savings': None,
        'shadow_overhead_ms': None,
    }
    if normalized_settings.get('shadow_validation_enabled'):
        shadow_validation = _read_shadow_validation_state() or shadow_validation
    if isinstance(shadow_validation, dict) and not isinstance(shadow_validation.get('rolling_metrics'), dict):
        shadow_validation['rolling_metrics'] = _empty_shadow_rolling_metrics()
    return {
        'success': True,
        'state': state,
        'repair_required_count': repair_required_count,
        'maintenance': _build_document_access_index_maintenance_summary(
            state,
            repair_required_count,
            normalized_settings,
        ),
        'read_metrics': get_document_access_index_read_metrics(),
        'cache_metrics': get_document_access_index_cache_metrics(),
        'shadow_validation': shadow_validation,
        'settings': {
            'container_enabled': normalized_settings.get('container_enabled'),
            'write_through_enabled': normalized_settings.get('write_through_enabled'),
            'reads_enabled': normalized_settings.get('reads_enabled'),
            'shadow_validation_enabled': normalized_settings.get('shadow_validation_enabled'),
            'startup_backfill_enabled': normalized_settings.get('startup_backfill_enabled'),
            'backfill_batch_size': normalized_settings.get('backfill_batch_size'),
            'repair_batch_size': normalized_settings.get('repair_batch_size'),
            'cache_enabled': normalized_settings.get('cache_enabled'),
            'cache_ttl_seconds': normalized_settings.get('cache_ttl_seconds'),
        },
    }


def reconcile_document_access_index_repair_documents(settings=None, max_repairs=None, force=False):
    """Repair projection rows recorded by fail-open write-through operations."""
    if not _is_container_enabled(settings) and not force:
        return {
            'success': True,
            'status': 'skipped_disabled',
            'repairs_processed': 0,
            'repairs_succeeded': 0,
            'repairs_failed': 0,
        }

    normalized_settings = get_document_access_index_settings(settings)
    max_repairs = _normalize_positive_int(
        max_repairs,
        normalized_settings.get('repair_batch_size'),
        max_value=DOCUMENT_ACCESS_MAX_REPAIR_BATCH_SIZE,
    )
    repair_docs = _query_repair_documents(max_item_count=max_repairs)
    repairs_succeeded = 0
    repairs_failed = 0

    for repair_doc in repair_docs:
        document_id = str(repair_doc.get('source_document_id') or '').strip()
        source_scope = str(repair_doc.get('source_scope') or '').strip().lower()
        operation = repair_doc.get('operation')
        if not document_id or source_scope not in DOCUMENT_ACCESS_SOURCE_SCOPES:
            repairs_failed += 1
            _mark_repair_document_failed(repair_doc, 'Repair document is missing source scope or document id.')
            continue

        try:
            repair_cache_scope_keys = _normalize_document_access_cache_scope_keys(
                repair_doc.get('cache_scope_keys')
            )
            if repair_cache_scope_keys:
                invalidation_result = invalidate_document_access_index_cache_scope_keys(
                    repair_cache_scope_keys,
                    reason='document_access_repair_historical_scope',
                    settings=settings,
                )
                _raise_for_failed_cache_invalidation(
                    invalidation_result,
                    'document_access_repair_historical_scope',
                    repair_cache_scope_keys,
                )

            if _repair_operation_represents_delete(operation):
                delete_document_access_index_for_document(
                    _repair_document_stub(source_scope, document_id),
                    operation='document_access_repair_delete',
                    settings=settings,
                    force=True,
                )
            else:
                try:
                    source_document = _read_source_document_for_repair(source_scope, document_id)
                except Exception as source_error:
                    if not _is_not_found_error(source_error):
                        raise
                    delete_document_access_index_for_document(
                        _repair_document_stub(source_scope, document_id),
                        operation='document_access_repair_source_missing',
                        settings=settings,
                        force=True,
                    )
                else:
                    sync_document_access_index_for_document(
                        source_document,
                        operation='document_access_repair_sync',
                        settings=settings,
                        force=True,
                    )
            repairs_succeeded += 1
        except Exception as exc:
            repairs_failed += 1
            _mark_repair_document_failed(repair_doc, exc)
            log_event(
                '[DocumentAccessIndex] Projection repair reconciliation failed.',
                extra={
                    'document_id': document_id,
                    'source_scope': source_scope,
                    'operation': operation,
                    'error': str(exc),
                },
                level=logging.WARNING,
                exceptionTraceback=True,
            )

    try:
        _refresh_repair_backlog_state_from_query(reason='repair_reconciliation')
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] Projection repair backlog state refresh failed after reconciliation.',
            extra={'error': str(exc)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
    return {
        'success': repairs_failed == 0,
        'status': 'reconciled' if repairs_failed == 0 else 'reconciled_with_errors',
        'repairs_processed': len(repair_docs),
        'repairs_succeeded': repairs_succeeded,
        'repairs_failed': repairs_failed,
    }


def run_document_access_index_backfill_once(
    settings=None,
    batch_size=None,
    source_scopes=None,
    reset=False,
    force=False,
):
    """Run one resumable batch of document access index backfill work."""
    normalized_settings = get_document_access_index_settings(settings)
    if not normalized_settings.get('container_enabled'):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'processed_count': 0,
            'failed_count': 0,
        }
    if not force and not normalized_settings.get('startup_backfill_enabled'):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'processed_count': 0,
            'failed_count': 0,
        }

    source_scopes = _normalize_source_scopes(source_scopes)
    batch_size = _normalize_positive_int(
        batch_size,
        normalized_settings.get('backfill_batch_size'),
        max_value=DOCUMENT_ACCESS_MAX_BACKFILL_BATCH_SIZE,
    )
    state = None if reset else _read_backfill_state()
    if (
        not state
        or state.get('type') != DOCUMENT_ACCESS_BACKFILL_STATE_TYPE
        or _safe_int(state.get('schema_version')) != DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION
    ):
        state = _build_initial_backfill_state(source_scopes)
    else:
        state = copy.deepcopy(state)
        state['source_scopes'] = source_scopes
        state.setdefault('completed_source_scopes', [])
        state.setdefault('continuation_tokens', {})
        state.setdefault('total_documents_processed', 0)
        state.setdefault('total_documents_failed', 0)
        state.setdefault('total_rows_upserted', 0)
        state.setdefault('total_rows_deleted', 0)

    if state.get('status') == 'succeeded' and not reset:
        return {
            'success': True,
            'status': 'skipped_completed',
            'processed_count': 0,
            'failed_count': 0,
            'state': state,
        }

    run_processed = 0
    run_failed = 0
    run_rows_upserted = 0
    run_rows_deleted = 0
    state['status'] = 'running'
    state['last_started_at'] = _utc_now_iso()
    state['last_error'] = None

    try:
        while run_processed < batch_size:
            source_scope = _get_next_backfill_scope(
                source_scopes,
                state.get('completed_source_scopes', []),
            )
            if not source_scope:
                break

            continuation_token = state.get('continuation_tokens', {}).get(source_scope)
            remaining_count = batch_size - run_processed
            page_result = _query_source_document_page(
                source_scope,
                continuation_token=continuation_token,
                max_item_count=remaining_count,
            )
            documents = page_result.get('documents', [])
            next_token = page_result.get('continuation_token')

            if not documents:
                completed_scopes = state.setdefault('completed_source_scopes', [])
                if source_scope not in completed_scopes:
                    completed_scopes.append(source_scope)
                state.setdefault('continuation_tokens', {}).pop(source_scope, None)
                state['current_source_scope'] = None
                continue

            state['current_source_scope'] = source_scope
            for document_item in documents:
                run_processed += 1
                state['total_documents_processed'] = int(state.get('total_documents_processed') or 0) + 1
                try:
                    result = sync_document_access_index_for_document(
                        document_item,
                        operation='document_access_backfill',
                        settings=settings,
                        force=True,
                    )
                except Exception as exc:
                    run_failed += 1
                    state['total_documents_failed'] = int(state.get('total_documents_failed') or 0) + 1
                    try:
                        _record_projection_repair_required(document_item, 'document_access_backfill', exc)
                    except Exception as repair_error:
                        log_event(
                            '[DocumentAccessIndex] Failed to record backfill repair state.',
                            extra={
                                'document_id': (document_item or {}).get('id'),
                                'source_scope': source_scope,
                                'error': str(repair_error),
                            },
                            level=logging.ERROR,
                            exceptionTraceback=True,
                        )
                    log_event(
                        '[DocumentAccessIndex] Backfill projection failed for one source document.',
                        extra={
                            'document_id': (document_item or {}).get('id'),
                            'source_scope': source_scope,
                            'error': str(exc),
                        },
                        level=logging.WARNING,
                        exceptionTraceback=True,
                    )
                    continue
                if result.get('success') is False:
                    run_failed += 1
                    state['total_documents_failed'] = int(state.get('total_documents_failed') or 0) + 1
                    continue
                run_rows_upserted += int(result.get('upserted_count') or 0)
                run_rows_deleted += int(result.get('deleted_count') or 0)
                state['total_rows_upserted'] = (
                    int(state.get('total_rows_upserted') or 0)
                    + int(result.get('upserted_count') or 0)
                )
                state['total_rows_deleted'] = (
                    int(state.get('total_rows_deleted') or 0)
                    + int(result.get('deleted_count') or 0)
                )

            if next_token:
                state.setdefault('continuation_tokens', {})[source_scope] = next_token
                break

            state.setdefault('continuation_tokens', {}).pop(source_scope, None)
            completed_scopes = state.setdefault('completed_source_scopes', [])
            if source_scope not in completed_scopes:
                completed_scopes.append(source_scope)
            state['current_source_scope'] = None

        if _get_next_backfill_scope(source_scopes, state.get('completed_source_scopes', [])):
            state['status'] = 'in_progress'
        elif int(state.get('total_documents_failed') or 0) > 0:
            state['status'] = 'succeeded_with_errors'
        else:
            state['status'] = 'succeeded'

        state.update({
            'last_completed_at': _utc_now_iso(),
            'last_processed_count': run_processed,
            'last_failed_count': run_failed,
            'last_rows_upserted': run_rows_upserted,
            'last_rows_deleted': run_rows_deleted,
        })
        state = _write_backfill_state(state)
        return {
            'success': run_failed == 0,
            'status': state.get('status'),
            'processed_count': run_processed,
            'failed_count': run_failed,
            'rows_upserted': run_rows_upserted,
            'rows_deleted': run_rows_deleted,
            'state': state,
        }
    except Exception as exc:
        state['status'] = 'failed'
        state['last_error'] = str(exc)
        state['last_completed_at'] = _utc_now_iso()
        state = _write_backfill_state(state)
        log_event(
            '[DocumentAccessIndex] Document access index backfill batch failed.',
            extra={'error': str(exc), 'current_source_scope': state.get('current_source_scope')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return {
            'success': False,
            'status': 'failed',
            'processed_count': run_processed,
            'failed_count': run_failed,
            'error': str(exc),
            'state': state,
        }


def run_document_access_index_backfill_maintenance(
    settings=None,
    run_backfill=None,
    reset=False,
    batch_size=None,
    repair_batch_size=None,
):
    """Run repair reconciliation and one optional backfill batch for app maintenance."""
    normalized_settings = get_document_access_index_settings(settings)
    if run_backfill is None:
        run_backfill = normalized_settings.get('startup_backfill_enabled', False)
    if not normalized_settings.get('container_enabled'):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'repair_reconciliation': {
                'success': True,
                'status': 'skipped_disabled',
            },
            'backfill': {
                'success': True,
                'status': 'skipped_disabled',
            },
            'current_status': get_document_access_index_backfill_status(settings=settings),
        }

    repair_result = reconcile_document_access_index_repair_documents(
        settings=settings,
        max_repairs=repair_batch_size,
        force=True,
    )
    if run_backfill:
        backfill_result = run_document_access_index_backfill_once(
            settings=settings,
            batch_size=batch_size,
            reset=reset,
            force=True,
        )
    else:
        backfill_result = {
            'success': True,
            'status': 'skipped_disabled',
            'processed_count': 0,
            'failed_count': 0,
        }
    success = repair_result.get('success') and backfill_result.get('success')
    current_status = get_document_access_index_backfill_status(settings=settings)
    maintenance_pending = is_document_access_index_maintenance_pending(current_status)
    status = 'completed' if success else 'completed_with_errors'
    if success and maintenance_pending:
        status = 'completed_more_work_pending'
    return {
        'success': bool(success),
        'status': status,
        'maintenance_pending': maintenance_pending,
        'next_action': (current_status.get('maintenance') or {}).get('next_action'),
        'repair_reconciliation': repair_result,
        'backfill': backfill_result,
        'current_status': current_status,
    }
