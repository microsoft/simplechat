# app_settings_cache.py
"""
WARNING: NEVER 'from app_settings_cache import' settings or any other module that imports settings.
ALWAYS import app_settings_cache and use app_settings_cache.get_settings_cache() to get settings.
This supports the dynamic selection of redis or in-memory caching of settings.
"""
import json
import logging
import threading
import time
from redis import Redis
from azure.identity import DefaultAzureCredential

# NOTE: functions_keyvault is imported locally inside configure_app_cache to avoid a circular
# import (functions_keyvault -> app_settings_cache -> functions_keyvault).
# functions_appinsights is also imported locally for the same reason.

_settings = None
APP_SETTINGS_CACHE = {}
APP_STREAM_SESSION_METADATA = {}
APP_STREAM_SESSION_EVENTS = {}
update_settings_cache = None
get_settings_cache = None
initialize_stream_session_cache = None
set_stream_session_meta = None
get_stream_session_meta = None
append_stream_session_event = None
get_stream_session_events = None
delete_stream_session_cache = None
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

def configure_app_cache(settings, redis_cache_endpoint=None):
    global _settings, update_settings_cache, get_settings_cache, APP_SETTINGS_CACHE
    global APP_STREAM_SESSION_METADATA, APP_STREAM_SESSION_EVENTS
    global initialize_stream_session_cache, set_stream_session_meta, get_stream_session_meta
    global append_stream_session_event, get_stream_session_events, delete_stream_session_cache
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

        def update_settings_cache_redis(new_settings):
            redis_client.set('APP_SETTINGS_CACHE', json.dumps(new_settings))

        def get_settings_cache_redis():
            cached = redis_client.get('APP_SETTINGS_CACHE')
            return json.loads(cached) if cached else {}

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

        update_settings_cache = update_settings_cache_redis
        get_settings_cache = get_settings_cache_redis
        initialize_stream_session_cache = initialize_stream_session_cache_redis
        set_stream_session_meta = set_stream_session_meta_redis
        get_stream_session_meta = get_stream_session_meta_redis
        append_stream_session_event = append_stream_session_event_redis
        get_stream_session_events = get_stream_session_events_redis
        delete_stream_session_cache = delete_stream_session_cache_redis

    else:
        def update_settings_cache_mem(new_settings):
            global APP_SETTINGS_CACHE
            APP_SETTINGS_CACHE = new_settings

        def get_settings_cache_mem():
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

        update_settings_cache = update_settings_cache_mem
        get_settings_cache = get_settings_cache_mem
        initialize_stream_session_cache = initialize_stream_session_cache_mem
        set_stream_session_meta = set_stream_session_meta_mem
        get_stream_session_meta = get_stream_session_meta_mem
        append_stream_session_event = append_stream_session_event_mem
        get_stream_session_events = get_stream_session_events_mem
        delete_stream_session_cache = delete_stream_session_cache_mem