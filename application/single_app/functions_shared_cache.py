# functions_shared_cache.py
"""Shared versioned cache helpers with Redis-first and Cosmos fallback behavior."""

import copy
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from config import cosmos_settings_container
from functions_appinsights import log_event


SHARED_CACHE_ENTRY_DOC_TYPE = 'shared_cache_entry'
SHARED_CACHE_ENTRY_PREFIX = 'shared_cache_entry:'
SHARED_CACHE_VERSION_DOC_TYPE = 'cache_version'
SHARED_CACHE_VERSION_READ_TTL_SECONDS = 15
SHARED_CACHE_VERSION_BUMP_MAX_RETRIES = 5

_version_cache = {}
_version_cache_lock = None


def _get_version_cache_lock():
    global _version_cache_lock
    if _version_cache_lock is None:
        _version_cache_lock = threading.Lock()
    return _version_cache_lock


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_now_iso():
    return _utc_now().isoformat()


def _normalize_cache_version(value):
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_not_found_error(exc):
    return getattr(exc, 'status_code', None) == 404


def _log_cache_warning(operation, error, extra=None):
    context = {
        'operation': operation,
        'error': str(error),
    }
    if extra:
        context.update(extra)
    log_event(
        f"[SharedCache] {operation} failed.",
        extra=context,
        level=logging.WARNING,
        exceptionTraceback=True,
    )


def _build_entry_doc_id(namespace, key):
    normalized_namespace = str(namespace or '').strip()
    normalized_key = str(key or '').strip()
    if not normalized_namespace or not normalized_key:
        raise ValueError('Shared cache namespace and key are required.')
    return f"{SHARED_CACHE_ENTRY_PREFIX}{normalized_namespace}:{normalized_key}"


def _build_redis_key(namespace, key):
    return _build_entry_doc_id(namespace, key)


def _serialize_for_cache(value):
    return json.dumps(value, default=str)


def _deserialize_from_cache(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    return json.loads(value)


def _get_expires_at(ttl_seconds=None):
    if ttl_seconds is None:
        return None
    return _utc_now() + timedelta(seconds=max(int(ttl_seconds), 0))


def _is_expired(entry):
    expires_at = entry.get('expires_at') if isinstance(entry, dict) else None
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) <= _utc_now()
    except (TypeError, ValueError):
        return True


def set_shared_cache_entry(namespace, key, value, ttl_seconds=None, redis_client=None):
    """Set a shared cache entry, falling back to Cosmos when Redis is unavailable."""
    redis_key = _build_redis_key(namespace, key)
    if redis_client is not None:
        try:
            serialized_value = _serialize_for_cache(value)
            if ttl_seconds is None:
                redis_client.set(redis_key, serialized_value)
            else:
                redis_client.setex(redis_key, int(ttl_seconds), serialized_value)
            return True
        except Exception as ex:
            _log_cache_warning('redis_set_shared_cache_entry', ex, {'cache_key': redis_key})

    expires_at = _get_expires_at(ttl_seconds)
    body = {
        'id': redis_key,
        'type': SHARED_CACHE_ENTRY_DOC_TYPE,
        'namespace': str(namespace),
        'key': str(key),
        'value': copy.deepcopy(value),
        'expires_at': expires_at.isoformat() if expires_at else None,
        'updated_at': _utc_now_iso(),
    }
    try:
        cosmos_settings_container.upsert_item(body)
        return True
    except Exception as ex:
        _log_cache_warning('cosmos_set_shared_cache_entry', ex, {'cache_key': redis_key})
        return False


def get_shared_cache_entry(namespace, key, redis_client=None):
    """Read a shared cache entry, falling back to Cosmos when Redis is unavailable."""
    redis_key = _build_redis_key(namespace, key)
    if redis_client is not None:
        try:
            value = redis_client.get(redis_key)
            if value is not None:
                return _deserialize_from_cache(value)
        except Exception as ex:
            _log_cache_warning('redis_get_shared_cache_entry', ex, {'cache_key': redis_key})

    try:
        entry = cosmos_settings_container.read_item(item=redis_key, partition_key=redis_key)
        if _is_expired(entry):
            delete_shared_cache_entry(namespace, key)
            return None
        return copy.deepcopy(entry.get('value'))
    except Exception as ex:
        if _is_not_found_error(ex):
            return None
        _log_cache_warning('cosmos_get_shared_cache_entry', ex, {'cache_key': redis_key})
        return None


def delete_shared_cache_entry(namespace, key, redis_client=None):
    """Delete a shared cache entry from Redis and Cosmos without failing callers."""
    redis_key = _build_redis_key(namespace, key)
    deleted = True
    if redis_client is not None:
        try:
            redis_client.delete(redis_key)
        except Exception as ex:
            deleted = False
            _log_cache_warning('redis_delete_shared_cache_entry', ex, {'cache_key': redis_key})

    try:
        cosmos_settings_container.delete_item(item=redis_key, partition_key=redis_key)
    except Exception as ex:
        if not _is_not_found_error(ex):
            deleted = False
            _log_cache_warning('cosmos_delete_shared_cache_entry', ex, {'cache_key': redis_key})
    return deleted


def _get_version_cache_key(container, version_doc_id):
    return f"{id(container)}:{version_doc_id}"


def _set_cached_shared_cache_version(container, version_doc_id, version):
    cache_lock = _get_version_cache_lock()
    with cache_lock:
        _version_cache[_get_version_cache_key(container, version_doc_id)] = {
            'value': version,
            'expires_at': time.time() + SHARED_CACHE_VERSION_READ_TTL_SECONDS,
        }


def get_shared_cache_version(version_doc_id, default_version=0, container=None, use_local_cache=True):
    """Read a Cosmos-backed shared cache version with a short local TTL."""
    cache_container = container or cosmos_settings_container
    cache_key = _get_version_cache_key(cache_container, version_doc_id)
    now = time.time()
    cache_lock = _get_version_cache_lock()
    if use_local_cache:
        with cache_lock:
            cached = _version_cache.get(cache_key)
            if cached and cached.get('expires_at', 0) > now:
                return _normalize_cache_version(cached.get('value'))

    try:
        doc = cache_container.read_item(item=version_doc_id, partition_key=version_doc_id)
        version = _normalize_cache_version(doc.get('version', default_version))
    except Exception as ex:
        if not _is_not_found_error(ex):
            _log_cache_warning('cosmos_get_shared_cache_version', ex, {'version_doc_id': version_doc_id})
        version = _normalize_cache_version(default_version)

    if use_local_cache:
        _set_cached_shared_cache_version(cache_container, version_doc_id, version)
    return version


def ensure_shared_cache_version_doc(version_doc_id, initial_version=0, description='', container=None):
    """Create a cache version document if it is missing and return its current state."""
    cache_container = container or cosmos_settings_container
    try:
        doc = cache_container.read_item(item=version_doc_id, partition_key=version_doc_id)
        return {
            'id': version_doc_id,
            'created': False,
            'version': _normalize_cache_version(doc.get('version', initial_version)),
            'description': doc.get('description') or description,
        }
    except Exception as ex:
        if not _is_not_found_error(ex):
            _log_cache_warning('cosmos_read_shared_cache_version_doc', ex, {'version_doc_id': version_doc_id})
            raise

    version = _normalize_cache_version(initial_version)
    body = {
        'id': version_doc_id,
        'type': SHARED_CACHE_VERSION_DOC_TYPE,
        'description': description,
        'version': version,
        'created_at': _utc_now_iso(),
        'updated_at': _utc_now_iso(),
    }
    try:
        cache_container.create_item(body=body)
        return {
            'id': version_doc_id,
            'created': True,
            'version': version,
            'description': description,
        }
    except Exception as ex:
        if getattr(ex, 'status_code', None) == 409:
            doc = cache_container.read_item(item=version_doc_id, partition_key=version_doc_id)
            return {
                'id': version_doc_id,
                'created': False,
                'version': _normalize_cache_version(doc.get('version', initial_version)),
                'description': doc.get('description') or description,
            }
        _log_cache_warning('cosmos_create_shared_cache_version_doc', ex, {'version_doc_id': version_doc_id})
        raise


def bump_shared_cache_version(version_doc_id, description='', container=None):
    """Increment a Cosmos-backed shared cache version document with optimistic concurrency."""
    cache_container = container or cosmos_settings_container
    ensure_shared_cache_version_doc(version_doc_id, description=description, container=cache_container)

    last_conflict = None
    for _ in range(SHARED_CACHE_VERSION_BUMP_MAX_RETRIES):
        try:
            doc = cache_container.read_item(item=version_doc_id, partition_key=version_doc_id)
            current_version = _normalize_cache_version(doc.get('version'))
            next_version = current_version + 1
            replacement_doc = dict(doc)
            replacement_doc.update({
                'id': version_doc_id,
                'type': SHARED_CACHE_VERSION_DOC_TYPE,
                'description': doc.get('description') or description,
                'version': next_version,
                'updated_at': _utc_now_iso(),
            })
            cache_container.replace_item(
                item=version_doc_id,
                body=replacement_doc,
                etag=doc.get('_etag'),
                match_condition=MatchConditions.IfNotModified,
            )
            _set_cached_shared_cache_version(cache_container, version_doc_id, next_version)
            return next_version
        except Exception as ex:
            status_code = getattr(ex, 'status_code', None)
            if _is_not_found_error(ex):
                ensure_shared_cache_version_doc(version_doc_id, description=description, container=cache_container)
                last_conflict = ex
                continue
            if status_code in (409, 412):
                last_conflict = ex
                continue
            _log_cache_warning('cosmos_bump_shared_cache_version', ex, {'version_doc_id': version_doc_id})
            raise

    _log_cache_warning(
        'cosmos_bump_shared_cache_version_conflict',
        last_conflict or RuntimeError('Version bump retry limit exceeded.'),
        {'version_doc_id': version_doc_id, 'max_retries': SHARED_CACHE_VERSION_BUMP_MAX_RETRIES},
    )
    if last_conflict:
        raise last_conflict
    raise RuntimeError('Shared cache version bump retry limit exceeded.')
