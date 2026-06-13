# app_settings_cache.py
"""
WARNING: NEVER 'from app_settings_cache import' settings or any other module that imports settings.
ALWAYS import app_settings_cache and use app_settings_cache.get_settings_cache() to get settings.
This supports the dynamic selection of redis or in-memory caching of settings.
"""
import json
import logging
import copy
import threading
import time
from datetime import datetime
from redis import Redis
from azure.identity import DefaultAzureCredential

# NOTE: functions_keyvault is imported locally inside configure_app_cache to avoid a circular
# import (functions_keyvault -> app_settings_cache -> functions_keyvault).
# functions_appinsights is also imported locally for the same reason.

_settings = None
_logger = logging.getLogger(__name__)
APP_SETTINGS_CACHE = {}
APP_USER_UI_SETTINGS_CACHE = {}
APP_STREAM_SESSION_METADATA = {}
APP_STREAM_SESSION_EVENTS = {}
APP_SETTINGS_CACHE_VERSION = 0
APP_GOVERNANCE_CACHE_VERSION = 0
APP_SETTINGS_SHARED_VERSION_CACHE = {'value': 0, 'expires_at': 0}
APP_GOVERNANCE_SHARED_VERSION_CACHE = {'value': 0, 'expires_at': 0}
APP_SETTINGS_CACHE_KEY = 'APP_SETTINGS_CACHE'
APP_SETTINGS_CACHE_VERSION_KEY = 'APP_SETTINGS_CACHE_VERSION'
APP_SETTINGS_CACHE_VERSION_DOC_ID = 'app_settings_cache_version'
USER_UI_SETTINGS_CACHE_KEY_PREFIX = 'USER_UI_SETTINGS'
USER_UI_SETTINGS_CACHE_TTL_SECONDS = 120
GOVERNANCE_CACHE_VERSION_KEY = 'GOVERNANCE_CACHE_VERSION'
GOVERNANCE_CACHE_VERSION_DOC_ID = 'governance_cache_version'
CACHE_VERSION_DOC_TYPE = 'cache_version'
CACHE_VERSION_READ_TTL_SECONDS = 15
update_settings_cache = None
get_settings_cache = None
get_app_settings_cache_version = None
bump_app_settings_cache_version = None
initialize_stream_session_cache = None
set_stream_session_meta = None
get_stream_session_meta = None
append_stream_session_event = None
get_stream_session_events = None
delete_stream_session_cache = None
get_user_ui_settings_cache = None
set_user_ui_settings_cache = None
delete_user_ui_settings_cache = None
get_governance_cache_version = None
bump_governance_cache_version = None
app_cache_is_using_redis = False
_app_cache_lock = threading.Lock()


def _get_expiration_timestamp(ttl_seconds=None):
    if ttl_seconds is None:
        return None
    return time.time() + max(int(ttl_seconds), 0)


def _is_expired(entry):
    if not entry:
        return True
    expires_at = entry.get('expires_at')
    return expires_at is not None and expires_at <= time.time()


def _normalize_cache_version(value):
    if isinstance(value, bytes):
        value = value.decode('utf-8')
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _read_cosmos_cache_version(container, doc_id, log_event_func=None):
    try:
        doc = container.read_item(item=doc_id, partition_key=doc_id)
        return _normalize_cache_version((doc or {}).get('version'))
    except Exception as ex:
        _logger.warning("[ASC] Shared cache version read failed for %s; using local version fallback: %s", doc_id, ex)
        return None


def _bump_cosmos_cache_version(container, doc_id, log_event_func=None):
    try:
        current_version = _read_cosmos_cache_version(container, doc_id, log_event_func=None)
        next_version = _normalize_cache_version(current_version) + 1
        container.upsert_item({
            'id': doc_id,
            'type': CACHE_VERSION_DOC_TYPE,
            'version': next_version,
            'updated_at': datetime.utcnow().isoformat(),
        })
        return next_version
    except Exception as ex:
        _logger.warning("[ASC] Shared cache version bump failed for %s; using local version fallback: %s", doc_id, ex)
        return None


def _get_ttl_cached_cosmos_version(version_cache, container, doc_id, fallback_version, log_event_func=None):
    now = time.time()
    with _app_cache_lock:
        cached_expires_at = version_cache.get('expires_at') or 0
        if cached_expires_at > now:
            return _normalize_cache_version(version_cache.get('value'))

    shared_version = _read_cosmos_cache_version(container, doc_id, log_event_func=log_event_func)
    if shared_version is None:
        shared_version = fallback_version

    with _app_cache_lock:
        version_cache['value'] = _normalize_cache_version(shared_version)
        version_cache['expires_at'] = now + CACHE_VERSION_READ_TTL_SECONDS
        return _normalize_cache_version(version_cache.get('value'))


def _set_ttl_cached_version(version_cache, version):
    with _app_cache_lock:
        version_cache['value'] = _normalize_cache_version(version)
        version_cache['expires_at'] = time.time() + CACHE_VERSION_READ_TTL_SECONDS

def configure_app_cache(settings, redis_cache_endpoint=None):
    global _settings, update_settings_cache, get_settings_cache, APP_SETTINGS_CACHE
    global APP_USER_UI_SETTINGS_CACHE, APP_STREAM_SESSION_METADATA, APP_STREAM_SESSION_EVENTS
    global APP_SETTINGS_CACHE_VERSION, APP_GOVERNANCE_CACHE_VERSION
    global APP_SETTINGS_SHARED_VERSION_CACHE, APP_GOVERNANCE_SHARED_VERSION_CACHE
    global initialize_stream_session_cache, set_stream_session_meta, get_stream_session_meta
    global append_stream_session_event, get_stream_session_events, delete_stream_session_cache
    global get_user_ui_settings_cache, set_user_ui_settings_cache, delete_user_ui_settings_cache
    global get_app_settings_cache_version, bump_app_settings_cache_version
    global get_governance_cache_version, bump_governance_cache_version
    global app_cache_is_using_redis
    # Local import to avoid circular dependency: functions_keyvault imports app_settings_cache.
    from functions_appinsights import log_event
    _settings = settings
    use_redis = _settings.get('enable_redis_cache', False)
    app_cache_is_using_redis = False

    if use_redis:
        app_cache_is_using_redis = True
        redis_url = settings.get('redis_url', '').strip()
        redis_auth_type = settings.get('redis_auth_type', 'key').strip().lower()
        if redis_auth_type == 'managed_identity':
            log_event("[ASC] Redis enabled using Managed Identity", level=logging.INFO)
            credential = DefaultAzureCredential()
            cache_endpoint = redis_cache_endpoint
            token = credential.get_token(cache_endpoint)
            redis_client = Redis(
                host=redis_url,
                port=6380,
                db=0,
                password=token.token,
                ssl=True
            )
        elif redis_auth_type == 'key_vault':
            log_event("[ASC] Redis enabled using Key Vault Secret", level=logging.INFO)
            # Local import to avoid circular dependency: functions_keyvault imports app_settings_cache.
            from functions_keyvault import retrieve_secret_direct
            redis_key_secret_name = settings.get('redis_key', '').strip()
            try:
                # Pass settings directly: get_settings_cache() is still None at this point
                # because configure_app_cache has not finished initialising the cache yet.
                redis_password = retrieve_secret_direct(redis_key_secret_name, settings=settings)
                if redis_password:
                    redis_password = redis_password.strip()
                log_event("[ASC] Redis key retrieved from Key Vault successfully", level=logging.INFO)
            except Exception as kv_err:
                log_event(f"[ASC] ERROR: Failed to retrieve Redis key from Key Vault: {kv_err}", level=logging.ERROR, exceptionTraceback=True)
                raise

            redis_client = Redis(
                host=redis_url,
                port=6380,
                db=0,
                password=redis_password,
                ssl=True
            )
        else:
            redis_key = settings.get('redis_key', '').strip()
            log_event("[ASC] Redis enabled using Access Key", level=logging.INFO)
            redis_client = Redis(
                host=redis_url,
                port=6380,
                db=0,
                password=redis_key,
                ssl=True
            )

        def get_app_settings_cache_version_redis():
            cached = redis_client.get(APP_SETTINGS_CACHE_VERSION_KEY)
            if cached is None:
                redis_client.setnx(APP_SETTINGS_CACHE_VERSION_KEY, 0)
                return 0
            return _normalize_cache_version(cached)

        def bump_app_settings_cache_version_redis():
            return _normalize_cache_version(redis_client.incr(APP_SETTINGS_CACHE_VERSION_KEY))

        def get_ttl_cached_app_settings_version_redis():
            now = time.time()
            with _app_cache_lock:
                if APP_SETTINGS_SHARED_VERSION_CACHE.get('expires_at', 0) > now:
                    return _normalize_cache_version(APP_SETTINGS_SHARED_VERSION_CACHE.get('value'))

            shared_version = get_app_settings_cache_version_redis()
            _set_ttl_cached_version(APP_SETTINGS_SHARED_VERSION_CACHE, shared_version)
            return shared_version

        def update_settings_cache_redis(new_settings):
            global APP_SETTINGS_CACHE, APP_SETTINGS_CACHE_VERSION
            redis_client.set(APP_SETTINGS_CACHE_KEY, json.dumps(new_settings))
            shared_version = get_app_settings_cache_version_redis()
            with _app_cache_lock:
                APP_SETTINGS_CACHE = new_settings
                APP_SETTINGS_CACHE_VERSION = shared_version
            _set_ttl_cached_version(APP_SETTINGS_SHARED_VERSION_CACHE, shared_version)

        def get_settings_cache_redis():
            global APP_SETTINGS_CACHE, APP_SETTINGS_CACHE_VERSION
            shared_version = get_ttl_cached_app_settings_version_redis()
            with _app_cache_lock:
                if APP_SETTINGS_CACHE and APP_SETTINGS_CACHE_VERSION == shared_version:
                    return APP_SETTINGS_CACHE

            cached = redis_client.get(APP_SETTINGS_CACHE_KEY)
            loaded_settings = json.loads(cached) if cached else {}
            with _app_cache_lock:
                APP_SETTINGS_CACHE = loaded_settings
                APP_SETTINGS_CACHE_VERSION = shared_version
            return loaded_settings

        def get_stream_session_metadata_key(cache_key):
            return f'STREAM_SESSION_META:{cache_key}'

        def get_stream_session_events_key(cache_key):
            return f'STREAM_SESSION_EVENTS:{cache_key}'

        def initialize_stream_session_cache_redis(cache_key, metadata, ttl_seconds=None):
            metadata_key = get_stream_session_metadata_key(cache_key)
            events_key = get_stream_session_events_key(cache_key)
            pipeline = redis_client.pipeline()
            pipeline.delete(events_key)
            pipeline.set(metadata_key, json.dumps(metadata))
            if ttl_seconds is not None:
                pipeline.expire(metadata_key, int(ttl_seconds))
            pipeline.execute()

        def set_stream_session_meta_redis(cache_key, metadata, ttl_seconds=None):
            metadata_key = get_stream_session_metadata_key(cache_key)
            events_key = get_stream_session_events_key(cache_key)
            pipeline = redis_client.pipeline()
            pipeline.set(metadata_key, json.dumps(metadata))
            if ttl_seconds is not None:
                pipeline.expire(metadata_key, int(ttl_seconds))
                if redis_client.exists(events_key):
                    pipeline.expire(events_key, int(ttl_seconds))
            pipeline.execute()

        def get_stream_session_meta_redis(cache_key):
            cached = redis_client.get(get_stream_session_metadata_key(cache_key))
            return json.loads(cached) if cached else None

        def append_stream_session_event_redis(cache_key, event_text, ttl_seconds=None):
            metadata_key = get_stream_session_metadata_key(cache_key)
            events_key = get_stream_session_events_key(cache_key)
            pipeline = redis_client.pipeline()
            pipeline.rpush(events_key, event_text)
            if ttl_seconds is not None:
                pipeline.expire(events_key, int(ttl_seconds))
                if redis_client.exists(metadata_key):
                    pipeline.expire(metadata_key, int(ttl_seconds))
            pipeline.execute()

        def get_stream_session_events_redis(cache_key, start_index=0):
            cached_events = redis_client.lrange(
                get_stream_session_events_key(cache_key),
                int(start_index or 0),
                -1,
            )
            normalized_events = []
            for event in cached_events:
                if isinstance(event, bytes):
                    normalized_events.append(event.decode('utf-8'))
                else:
                    normalized_events.append(event)
            return normalized_events

        def delete_stream_session_cache_redis(cache_key):
            redis_client.delete(
                get_stream_session_metadata_key(cache_key),
                get_stream_session_events_key(cache_key),
            )

        def get_user_ui_settings_cache_key(user_id):
            return f'{USER_UI_SETTINGS_CACHE_KEY_PREFIX}:{user_id}'

        def get_user_ui_settings_cache_redis(user_id):
            cached = redis_client.get(get_user_ui_settings_cache_key(user_id))
            return json.loads(cached) if cached else None

        def set_user_ui_settings_cache_redis(user_id, ui_settings, ttl_seconds=None):
            ttl = int(ttl_seconds or USER_UI_SETTINGS_CACHE_TTL_SECONDS)
            redis_client.setex(
                get_user_ui_settings_cache_key(user_id),
                ttl,
                json.dumps(ui_settings or {})
            )

        def delete_user_ui_settings_cache_redis(user_id):
            redis_client.delete(get_user_ui_settings_cache_key(user_id))

        def get_governance_cache_version_redis():
            cached = redis_client.get(GOVERNANCE_CACHE_VERSION_KEY)
            if cached is None:
                redis_client.setnx(GOVERNANCE_CACHE_VERSION_KEY, 0)
                return 0
            return _normalize_cache_version(cached)

        def bump_governance_cache_version_redis():
            return _normalize_cache_version(redis_client.incr(GOVERNANCE_CACHE_VERSION_KEY))

        update_settings_cache = update_settings_cache_redis
        get_settings_cache = get_settings_cache_redis
        get_app_settings_cache_version = get_app_settings_cache_version_redis
        bump_app_settings_cache_version = bump_app_settings_cache_version_redis
        initialize_stream_session_cache = initialize_stream_session_cache_redis
        set_stream_session_meta = set_stream_session_meta_redis
        get_stream_session_meta = get_stream_session_meta_redis
        append_stream_session_event = append_stream_session_event_redis
        get_stream_session_events = get_stream_session_events_redis
        delete_stream_session_cache = delete_stream_session_cache_redis
        get_user_ui_settings_cache = get_user_ui_settings_cache_redis
        set_user_ui_settings_cache = set_user_ui_settings_cache_redis
        delete_user_ui_settings_cache = delete_user_ui_settings_cache_redis
        get_governance_cache_version = get_governance_cache_version_redis
        bump_governance_cache_version = bump_governance_cache_version_redis

    else:
        def update_settings_cache_mem(new_settings):
            global APP_SETTINGS_CACHE, APP_SETTINGS_CACHE_VERSION
            shared_version = get_app_settings_cache_version_mem()
            with _app_cache_lock:
                APP_SETTINGS_CACHE = new_settings
                APP_SETTINGS_CACHE_VERSION = shared_version

        def get_settings_cache_mem():
            global APP_SETTINGS_CACHE, APP_SETTINGS_CACHE_VERSION
            shared_version = get_app_settings_cache_version_mem()
            with _app_cache_lock:
                if APP_SETTINGS_CACHE and APP_SETTINGS_CACHE_VERSION == shared_version:
                    return APP_SETTINGS_CACHE

            try:
                from config import cosmos_settings_container
                loaded_settings = cosmos_settings_container.read_item(
                    item='app_settings',
                    partition_key='app_settings',
                )
                with _app_cache_lock:
                    APP_SETTINGS_CACHE = loaded_settings
                    APP_SETTINGS_CACHE_VERSION = shared_version
                return loaded_settings
            except Exception as ex:
                _logger.warning("[ASC] Failed to refresh app settings cache from Cosmos; using local cache fallback: %s", ex)
                with _app_cache_lock:
                    return APP_SETTINGS_CACHE

        def initialize_stream_session_cache_mem(cache_key, metadata, ttl_seconds=None):
            expiration_timestamp = _get_expiration_timestamp(ttl_seconds)
            with _app_cache_lock:
                APP_STREAM_SESSION_METADATA[cache_key] = {
                    'value': dict(metadata or {}),
                    'expires_at': expiration_timestamp,
                }
                APP_STREAM_SESSION_EVENTS[cache_key] = {
                    'value': [],
                    'expires_at': expiration_timestamp,
                }

        def set_stream_session_meta_mem(cache_key, metadata, ttl_seconds=None):
            expiration_timestamp = _get_expiration_timestamp(ttl_seconds)
            with _app_cache_lock:
                APP_STREAM_SESSION_METADATA[cache_key] = {
                    'value': dict(metadata or {}),
                    'expires_at': expiration_timestamp,
                }
                if cache_key not in APP_STREAM_SESSION_EVENTS or _is_expired(APP_STREAM_SESSION_EVENTS.get(cache_key)):
                    APP_STREAM_SESSION_EVENTS[cache_key] = {
                        'value': [],
                        'expires_at': expiration_timestamp,
                    }
                elif expiration_timestamp is not None:
                    APP_STREAM_SESSION_EVENTS[cache_key]['expires_at'] = expiration_timestamp

        def get_stream_session_meta_mem(cache_key):
            with _app_cache_lock:
                entry = APP_STREAM_SESSION_METADATA.get(cache_key)
                if _is_expired(entry):
                    APP_STREAM_SESSION_METADATA.pop(cache_key, None)
                    APP_STREAM_SESSION_EVENTS.pop(cache_key, None)
                    return None
                return dict(entry.get('value') or {})

        def append_stream_session_event_mem(cache_key, event_text, ttl_seconds=None):
            expiration_timestamp = _get_expiration_timestamp(ttl_seconds)
            with _app_cache_lock:
                entry = APP_STREAM_SESSION_EVENTS.get(cache_key)
                if _is_expired(entry):
                    entry = {
                        'value': [],
                        'expires_at': expiration_timestamp,
                    }
                    APP_STREAM_SESSION_EVENTS[cache_key] = entry
                entry['value'].append(event_text)
                if expiration_timestamp is not None:
                    entry['expires_at'] = expiration_timestamp
                metadata_entry = APP_STREAM_SESSION_METADATA.get(cache_key)
                if metadata_entry and expiration_timestamp is not None:
                    metadata_entry['expires_at'] = expiration_timestamp

        def get_stream_session_events_mem(cache_key, start_index=0):
            with _app_cache_lock:
                entry = APP_STREAM_SESSION_EVENTS.get(cache_key)
                if _is_expired(entry):
                    APP_STREAM_SESSION_EVENTS.pop(cache_key, None)
                    APP_STREAM_SESSION_METADATA.pop(cache_key, None)
                    return []
                return list((entry.get('value') or [])[int(start_index or 0):])

        def delete_stream_session_cache_mem(cache_key):
            with _app_cache_lock:
                APP_STREAM_SESSION_METADATA.pop(cache_key, None)
                APP_STREAM_SESSION_EVENTS.pop(cache_key, None)

        def get_user_ui_settings_cache_mem(user_id):
            with _app_cache_lock:
                entry = APP_USER_UI_SETTINGS_CACHE.get(user_id)
                if _is_expired(entry):
                    APP_USER_UI_SETTINGS_CACHE.pop(user_id, None)
                    return None
                return copy.deepcopy(entry.get('value') or {})

        def set_user_ui_settings_cache_mem(user_id, ui_settings, ttl_seconds=None):
            expiration_timestamp = _get_expiration_timestamp(
                ttl_seconds or USER_UI_SETTINGS_CACHE_TTL_SECONDS
            )
            with _app_cache_lock:
                APP_USER_UI_SETTINGS_CACHE[user_id] = {
                    'value': copy.deepcopy(ui_settings or {}),
                    'expires_at': expiration_timestamp,
                }

        def delete_user_ui_settings_cache_mem(user_id):
            with _app_cache_lock:
                APP_USER_UI_SETTINGS_CACHE.pop(user_id, None)

        def get_app_settings_cache_version_mem():
            global APP_SETTINGS_CACHE_VERSION
            try:
                from config import cosmos_settings_container
                return _get_ttl_cached_cosmos_version(
                    APP_SETTINGS_SHARED_VERSION_CACHE,
                    cosmos_settings_container,
                    APP_SETTINGS_CACHE_VERSION_DOC_ID,
                    APP_SETTINGS_CACHE_VERSION,
                    log_event_func=log_event,
                )
            except Exception:
                with _app_cache_lock:
                    return APP_SETTINGS_CACHE_VERSION

        def bump_app_settings_cache_version_mem():
            global APP_SETTINGS_CACHE_VERSION
            try:
                from config import cosmos_settings_container
                bumped_version = _bump_cosmos_cache_version(
                    cosmos_settings_container,
                    APP_SETTINGS_CACHE_VERSION_DOC_ID,
                    log_event_func=log_event,
                )
                if bumped_version is not None:
                    with _app_cache_lock:
                        APP_SETTINGS_CACHE_VERSION = bumped_version
                    _set_ttl_cached_version(APP_SETTINGS_SHARED_VERSION_CACHE, bumped_version)
                    return bumped_version
            except Exception:
                pass

            with _app_cache_lock:
                APP_SETTINGS_CACHE_VERSION += 1
                fallback_version = APP_SETTINGS_CACHE_VERSION
            _set_ttl_cached_version(APP_SETTINGS_SHARED_VERSION_CACHE, fallback_version)
            return fallback_version

        def get_governance_cache_version_mem():
            global APP_GOVERNANCE_CACHE_VERSION
            try:
                from config import cosmos_governance_policies_container
                return _get_ttl_cached_cosmos_version(
                    APP_GOVERNANCE_SHARED_VERSION_CACHE,
                    cosmos_governance_policies_container,
                    GOVERNANCE_CACHE_VERSION_DOC_ID,
                    APP_GOVERNANCE_CACHE_VERSION,
                    log_event_func=log_event,
                )
            except Exception:
                with _app_cache_lock:
                    return APP_GOVERNANCE_CACHE_VERSION

        def bump_governance_cache_version_mem():
            global APP_GOVERNANCE_CACHE_VERSION
            try:
                from config import cosmos_governance_policies_container
                bumped_version = _bump_cosmos_cache_version(
                    cosmos_governance_policies_container,
                    GOVERNANCE_CACHE_VERSION_DOC_ID,
                    log_event_func=log_event,
                )
                if bumped_version is not None:
                    with _app_cache_lock:
                        APP_GOVERNANCE_CACHE_VERSION = bumped_version
                    _set_ttl_cached_version(APP_GOVERNANCE_SHARED_VERSION_CACHE, bumped_version)
                    return bumped_version
            except Exception:
                pass

            with _app_cache_lock:
                APP_GOVERNANCE_CACHE_VERSION += 1
                fallback_version = APP_GOVERNANCE_CACHE_VERSION
            _set_ttl_cached_version(APP_GOVERNANCE_SHARED_VERSION_CACHE, fallback_version)
            return fallback_version

        update_settings_cache = update_settings_cache_mem
        get_settings_cache = get_settings_cache_mem
        get_app_settings_cache_version = get_app_settings_cache_version_mem
        bump_app_settings_cache_version = bump_app_settings_cache_version_mem
        initialize_stream_session_cache = initialize_stream_session_cache_mem
        set_stream_session_meta = set_stream_session_meta_mem
        get_stream_session_meta = get_stream_session_meta_mem
        append_stream_session_event = append_stream_session_event_mem
        get_stream_session_events = get_stream_session_events_mem
        delete_stream_session_cache = delete_stream_session_cache_mem
        get_user_ui_settings_cache = get_user_ui_settings_cache_mem
        set_user_ui_settings_cache = set_user_ui_settings_cache_mem
        delete_user_ui_settings_cache = delete_user_ui_settings_cache_mem
        get_governance_cache_version = get_governance_cache_version_mem
        bump_governance_cache_version = bump_governance_cache_version_mem