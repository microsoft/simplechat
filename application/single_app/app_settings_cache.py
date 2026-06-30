# app_settings_cache.py
"""
WARNING: NEVER 'from app_settings_cache import' settings or any other module that imports settings.
ALWAYS import app_settings_cache and use app_settings_cache.get_settings_cache() to get settings.
This supports the dynamic selection of redis or in-memory caching of settings.
"""
import json
import logging
import copy
import base64
import os
import threading
import time
from datetime import datetime, timedelta
from redis import Redis
from redis.credentials import CredentialProvider
from azure.identity import DefaultAzureCredential

# NOTE: functions_keyvault is imported locally inside configure_app_cache to avoid a circular
# import (functions_keyvault -> app_settings_cache -> functions_keyvault).
# functions_appinsights is also imported locally for the same reason.

_settings = None
_logger = logging.getLogger(__name__)
REDIS_ENTRA_TOKEN_SCOPE = 'https://redis.azure.com/.default'
REDIS_TOKEN_REFRESH_BUFFER_SECONDS = 300
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
COSMOS_CACHE_ENTRY_DOC_TYPE = 'app_cache_entry'
COSMOS_CACHE_ENTRY_PREFIX = 'app_cache_entry:'
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


def _get_redis_entra_token_scope(settings=None):
    configured_scope = (settings or {}).get('redis_entra_token_scope') or os.getenv('REDIS_ENTRA_TOKEN_SCOPE')
    return (configured_scope or REDIS_ENTRA_TOKEN_SCOPE).strip()


def _decode_token_claims(access_token):
    parts = access_token.split('.')
    if len(parts) < 2:
        raise ValueError('Redis Microsoft Entra token did not contain JWT claims.')

    payload = parts[1]
    payload += '=' * (-len(payload) % 4)
    decoded_payload = base64.urlsafe_b64decode(payload.encode('utf-8')).decode('utf-8')
    return json.loads(decoded_payload)


def _get_redis_username_from_claims(access_token):
    claims = _decode_token_claims(access_token)
    username = claims.get('oid') or claims.get('appid')
    if not username:
        raise ValueError('Redis Microsoft Entra token did not include an object ID claim.')
    return username


class RedisManagedIdentityCredentialProvider(CredentialProvider):
    """Provides Redis ACL username and Microsoft Entra token credentials."""

    def __init__(self, credential=None, scope=None):
        self.credential = credential or DefaultAzureCredential()
        self.scope = scope or REDIS_ENTRA_TOKEN_SCOPE
        self._cached_credentials = None
        self._expires_on = 0

    def get_credentials(self):
        now = time.time()
        if self._cached_credentials and now < self._expires_on - REDIS_TOKEN_REFRESH_BUFFER_SECONDS:
            return self._cached_credentials

        token = self.credential.get_token(self.scope)
        username = _get_redis_username_from_claims(token.token)
        self._cached_credentials = (username, token.token)
        self._expires_on = token.expires_on
        return self._cached_credentials


def create_redis_managed_identity_client(redis_url, settings=None, **redis_kwargs):
    credential_provider = RedisManagedIdentityCredentialProvider(
        scope=_get_redis_entra_token_scope(settings)
    )
    return Redis(
        host=redis_url,
        port=6380,
        db=0,
        credential_provider=credential_provider,
        ssl=True,
        **redis_kwargs
    )


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


def _log_cache_fallback(operation, exception, log_event_func=None):
    message = f"[ASC] Redis cache operation failed; using Cosmos/local fallback for {operation}."
    _logger.warning("%s Error: %s", message, exception)
    if callable(log_event_func):
        log_event_func(
            message,
            extra={
                'operation': operation,
                'error': str(exception),
            },
            level=logging.WARNING,
        )


def _build_cosmos_cache_doc_id(cache_key):
    return f"{COSMOS_CACHE_ENTRY_PREFIX}{cache_key}"


def _get_cosmos_cache_container():
    from config import cosmos_settings_container
    return cosmos_settings_container


def _serialize_datetime(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _set_cosmos_cache_entry(cache_key, payload, ttl_seconds=None, log_event_func=None):
    try:
        now = datetime.utcnow()
        expires_at = None
        if ttl_seconds is not None:
            expires_at = now + timedelta(seconds=max(int(ttl_seconds), 0))
        doc_id = _build_cosmos_cache_doc_id(cache_key)
        _get_cosmos_cache_container().upsert_item({
            'id': doc_id,
            'type': COSMOS_CACHE_ENTRY_DOC_TYPE,
            'cache_key': cache_key,
            'payload': copy.deepcopy(payload),
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'expires_at': _serialize_datetime(expires_at),
        })
        return True
    except Exception as ex:
        _logger.warning("[ASC] Cosmos cache fallback write failed for %s: %s", cache_key, ex)
        if callable(log_event_func):
            log_event_func(
                "[ASC] Cosmos cache fallback write failed.",
                extra={'cache_key': cache_key, 'error': str(ex)},
                level=logging.WARNING,
            )
        return False


def _get_cosmos_cache_entry(cache_key, log_event_func=None):
    try:
        doc_id = _build_cosmos_cache_doc_id(cache_key)
        doc = _get_cosmos_cache_container().read_item(item=doc_id, partition_key=doc_id)
        expires_at = doc.get('expires_at')
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) <= datetime.utcnow():
                    return None
            except (TypeError, ValueError):
                return None
        return copy.deepcopy(doc.get('payload'))
    except Exception as ex:
        status_code = getattr(ex, 'status_code', None)
        if status_code != 404:
            _logger.warning("[ASC] Cosmos cache fallback read failed for %s: %s", cache_key, ex)
            if callable(log_event_func):
                log_event_func(
                    "[ASC] Cosmos cache fallback read failed.",
                    extra={'cache_key': cache_key, 'error': str(ex), 'status_code': status_code},
                    level=logging.WARNING,
                )
        return None


def _delete_cosmos_cache_entry(cache_key, log_event_func=None):
    try:
        doc_id = _build_cosmos_cache_doc_id(cache_key)
        _get_cosmos_cache_container().delete_item(item=doc_id, partition_key=doc_id)
        return True
    except Exception as ex:
        status_code = getattr(ex, 'status_code', None)
        if status_code != 404:
            _logger.warning("[ASC] Cosmos cache fallback delete failed for %s: %s", cache_key, ex)
            if callable(log_event_func):
                log_event_func(
                    "[ASC] Cosmos cache fallback delete failed.",
                    extra={'cache_key': cache_key, 'error': str(ex), 'status_code': status_code},
                    level=logging.WARNING,
                )
        return False


def _get_app_settings_cache_version_fallback(log_event_func=None):
    global APP_SETTINGS_CACHE_VERSION
    try:
        from config import cosmos_settings_container
        return _get_ttl_cached_cosmos_version(
            APP_SETTINGS_SHARED_VERSION_CACHE,
            cosmos_settings_container,
            APP_SETTINGS_CACHE_VERSION_DOC_ID,
            APP_SETTINGS_CACHE_VERSION,
            log_event_func=log_event_func,
        )
    except Exception as ex:
        _logger.warning("[ASC] Shared cache version read failed; using local version fallback: %s", ex)
        if callable(log_event_func):
            log_event_func(
                "[ASC] Shared cache version read failed; using local version fallback.",
                extra={'version_doc_id': APP_SETTINGS_CACHE_VERSION_DOC_ID, 'error': str(ex)},
                level=logging.WARNING,
            )
        with _app_cache_lock:
            return APP_SETTINGS_CACHE_VERSION


def _bump_app_settings_cache_version_fallback(log_event_func=None):
    global APP_SETTINGS_CACHE_VERSION
    try:
        from config import cosmos_settings_container
        bumped_version = _bump_cosmos_cache_version(
            cosmos_settings_container,
            APP_SETTINGS_CACHE_VERSION_DOC_ID,
            log_event_func=log_event_func,
        )
        if bumped_version is not None:
            with _app_cache_lock:
                APP_SETTINGS_CACHE_VERSION = bumped_version
            _set_ttl_cached_version(APP_SETTINGS_SHARED_VERSION_CACHE, bumped_version)
            return bumped_version
    except Exception as ex:
        _logger.warning("[ASC] Shared cache version bump failed; using local version fallback: %s", ex)
        if callable(log_event_func):
            log_event_func(
                "[ASC] Shared cache version bump failed; using local version fallback.",
                extra={'version_doc_id': APP_SETTINGS_CACHE_VERSION_DOC_ID, 'error': str(ex)},
                level=logging.WARNING,
            )

    with _app_cache_lock:
        APP_SETTINGS_CACHE_VERSION += 1
        fallback_version = APP_SETTINGS_CACHE_VERSION
    _set_ttl_cached_version(APP_SETTINGS_SHARED_VERSION_CACHE, fallback_version)
    return fallback_version


def _update_settings_cache_fallback(new_settings, log_event_func=None):
    global APP_SETTINGS_CACHE, APP_SETTINGS_CACHE_VERSION
    shared_version = _get_app_settings_cache_version_fallback(log_event_func=log_event_func)
    with _app_cache_lock:
        APP_SETTINGS_CACHE = copy.deepcopy(new_settings or {})
        APP_SETTINGS_CACHE_VERSION = shared_version


def _get_settings_cache_fallback(log_event_func=None):
    global APP_SETTINGS_CACHE, APP_SETTINGS_CACHE_VERSION
    shared_version = _get_app_settings_cache_version_fallback(log_event_func=log_event_func)
    with _app_cache_lock:
        if APP_SETTINGS_CACHE and APP_SETTINGS_CACHE_VERSION == shared_version:
            return copy.deepcopy(APP_SETTINGS_CACHE)

    try:
        from config import cosmos_settings_container
        loaded_settings = cosmos_settings_container.read_item(
            item='app_settings',
            partition_key='app_settings',
        )
        with _app_cache_lock:
            APP_SETTINGS_CACHE = copy.deepcopy(loaded_settings or {})
            APP_SETTINGS_CACHE_VERSION = shared_version
        return copy.deepcopy(loaded_settings or {})
    except Exception as ex:
        _logger.warning("[ASC] Failed to refresh app settings cache from Cosmos; using local cache fallback: %s", ex)
        if callable(log_event_func):
            log_event_func(
                "[ASC] Failed to refresh app settings cache from Cosmos; using local cache fallback.",
                extra={'error': str(ex)},
                level=logging.WARNING,
            )
        with _app_cache_lock:
            return copy.deepcopy(APP_SETTINGS_CACHE)


def _get_governance_cache_version_fallback(log_event_func=None):
    global APP_GOVERNANCE_CACHE_VERSION
    try:
        from config import cosmos_governance_policies_container
        return _get_ttl_cached_cosmos_version(
            APP_GOVERNANCE_SHARED_VERSION_CACHE,
            cosmos_governance_policies_container,
            GOVERNANCE_CACHE_VERSION_DOC_ID,
            APP_GOVERNANCE_CACHE_VERSION,
            log_event_func=log_event_func,
        )
    except Exception as ex:
        _logger.warning("[ASC] Governance cache version read failed; using local version fallback: %s", ex)
        if callable(log_event_func):
            log_event_func(
                "[ASC] Governance cache version read failed; using local version fallback.",
                extra={'version_doc_id': GOVERNANCE_CACHE_VERSION_DOC_ID, 'error': str(ex)},
                level=logging.WARNING,
            )
        with _app_cache_lock:
            return APP_GOVERNANCE_CACHE_VERSION


def _bump_governance_cache_version_fallback(log_event_func=None):
    global APP_GOVERNANCE_CACHE_VERSION
    try:
        from config import cosmos_governance_policies_container
        bumped_version = _bump_cosmos_cache_version(
            cosmos_governance_policies_container,
            GOVERNANCE_CACHE_VERSION_DOC_ID,
            log_event_func=log_event_func,
        )
        if bumped_version is not None:
            with _app_cache_lock:
                APP_GOVERNANCE_CACHE_VERSION = bumped_version
            _set_ttl_cached_version(APP_GOVERNANCE_SHARED_VERSION_CACHE, bumped_version)
            return bumped_version
    except Exception as ex:
        _logger.warning("[ASC] Governance cache version bump failed; using local version fallback: %s", ex)
        if callable(log_event_func):
            log_event_func(
                "[ASC] Governance cache version bump failed; using local version fallback.",
                extra={'version_doc_id': GOVERNANCE_CACHE_VERSION_DOC_ID, 'error': str(ex)},
                level=logging.WARNING,
            )

    with _app_cache_lock:
        APP_GOVERNANCE_CACHE_VERSION += 1
        fallback_version = APP_GOVERNANCE_CACHE_VERSION
    _set_ttl_cached_version(APP_GOVERNANCE_SHARED_VERSION_CACHE, fallback_version)
    return fallback_version


def _get_stream_session_metadata_key(cache_key):
    return f'STREAM_SESSION_META:{cache_key}'


def _get_stream_session_events_key(cache_key):
    return f'STREAM_SESSION_EVENTS:{cache_key}'


def _initialize_stream_session_cache_fallback(cache_key, metadata, ttl_seconds=None, log_event_func=None):
    expiration_timestamp = _get_expiration_timestamp(ttl_seconds)
    with _app_cache_lock:
        APP_STREAM_SESSION_METADATA[cache_key] = {
            'value': copy.deepcopy(metadata or {}),
            'expires_at': expiration_timestamp,
        }
        APP_STREAM_SESSION_EVENTS[cache_key] = {
            'value': [],
            'expires_at': expiration_timestamp,
        }
    _set_cosmos_cache_entry(
        _get_stream_session_metadata_key(cache_key),
        metadata or {},
        ttl_seconds=ttl_seconds,
        log_event_func=log_event_func,
    )
    _set_cosmos_cache_entry(
        _get_stream_session_events_key(cache_key),
        [],
        ttl_seconds=ttl_seconds,
        log_event_func=log_event_func,
    )


def _set_stream_session_meta_fallback(cache_key, metadata, ttl_seconds=None, log_event_func=None):
    expiration_timestamp = _get_expiration_timestamp(ttl_seconds)
    with _app_cache_lock:
        APP_STREAM_SESSION_METADATA[cache_key] = {
            'value': copy.deepcopy(metadata or {}),
            'expires_at': expiration_timestamp,
        }
    _set_cosmos_cache_entry(
        _get_stream_session_metadata_key(cache_key),
        metadata or {},
        ttl_seconds=ttl_seconds,
        log_event_func=log_event_func,
    )


def _get_stream_session_meta_fallback(cache_key, log_event_func=None):
    with _app_cache_lock:
        entry = APP_STREAM_SESSION_METADATA.get(cache_key)
        if entry and not _is_expired(entry):
            return copy.deepcopy(entry.get('value') or {})
        if entry:
            APP_STREAM_SESSION_METADATA.pop(cache_key, None)

    cached = _get_cosmos_cache_entry(
        _get_stream_session_metadata_key(cache_key),
        log_event_func=log_event_func,
    )
    return copy.deepcopy(cached or {}) if cached is not None else None


def _append_stream_session_event_fallback(cache_key, event_text, ttl_seconds=None, log_event_func=None):
    expiration_timestamp = _get_expiration_timestamp(ttl_seconds)
    with _app_cache_lock:
        entry = APP_STREAM_SESSION_EVENTS.get(cache_key)
        if _is_expired(entry):
            entry = {'value': [], 'expires_at': expiration_timestamp}
            APP_STREAM_SESSION_EVENTS[cache_key] = entry
        entry['value'].append(event_text)
        if expiration_timestamp is not None:
            entry['expires_at'] = expiration_timestamp
        events_payload = list(entry.get('value') or [])
    _set_cosmos_cache_entry(
        _get_stream_session_events_key(cache_key),
        events_payload,
        ttl_seconds=ttl_seconds,
        log_event_func=log_event_func,
    )


def _get_stream_session_events_fallback(cache_key, start_index=0, log_event_func=None):
    start = int(start_index or 0)
    with _app_cache_lock:
        entry = APP_STREAM_SESSION_EVENTS.get(cache_key)
        if entry and not _is_expired(entry):
            return list((entry.get('value') or [])[start:])
        if entry:
            APP_STREAM_SESSION_EVENTS.pop(cache_key, None)

    cached = _get_cosmos_cache_entry(
        _get_stream_session_events_key(cache_key),
        log_event_func=log_event_func,
    )
    return list((cached or [])[start:])


def _delete_stream_session_cache_fallback(cache_key, log_event_func=None):
    with _app_cache_lock:
        APP_STREAM_SESSION_METADATA.pop(cache_key, None)
        APP_STREAM_SESSION_EVENTS.pop(cache_key, None)
    _delete_cosmos_cache_entry(
        _get_stream_session_metadata_key(cache_key),
        log_event_func=log_event_func,
    )
    _delete_cosmos_cache_entry(
        _get_stream_session_events_key(cache_key),
        log_event_func=log_event_func,
    )


def _get_user_ui_settings_cache_key(user_id):
    return f'{USER_UI_SETTINGS_CACHE_KEY_PREFIX}:{user_id}'


def _get_user_ui_settings_cache_fallback(user_id, log_event_func=None):
    with _app_cache_lock:
        entry = APP_USER_UI_SETTINGS_CACHE.get(user_id)
        if entry and not _is_expired(entry):
            return copy.deepcopy(entry.get('value') or {})
        if entry:
            APP_USER_UI_SETTINGS_CACHE.pop(user_id, None)

    cached = _get_cosmos_cache_entry(
        _get_user_ui_settings_cache_key(user_id),
        log_event_func=log_event_func,
    )
    return copy.deepcopy(cached) if cached is not None else None


def _set_user_ui_settings_cache_fallback(user_id, ui_settings, ttl_seconds=None, log_event_func=None):
    ttl = int(ttl_seconds or USER_UI_SETTINGS_CACHE_TTL_SECONDS)
    expiration_timestamp = _get_expiration_timestamp(ttl)
    with _app_cache_lock:
        APP_USER_UI_SETTINGS_CACHE[user_id] = {
            'value': copy.deepcopy(ui_settings or {}),
            'expires_at': expiration_timestamp,
        }
    _set_cosmos_cache_entry(
        _get_user_ui_settings_cache_key(user_id),
        ui_settings or {},
        ttl_seconds=ttl,
        log_event_func=log_event_func,
    )


def _delete_user_ui_settings_cache_fallback(user_id, log_event_func=None):
    with _app_cache_lock:
        APP_USER_UI_SETTINGS_CACHE.pop(user_id, None)
    _delete_cosmos_cache_entry(
        _get_user_ui_settings_cache_key(user_id),
        log_event_func=log_event_func,
    )


def _assign_fallback_cache_functions(log_event_func=None):
    global update_settings_cache, get_settings_cache
    global initialize_stream_session_cache, set_stream_session_meta, get_stream_session_meta
    global append_stream_session_event, get_stream_session_events, delete_stream_session_cache
    global get_user_ui_settings_cache, set_user_ui_settings_cache, delete_user_ui_settings_cache
    global get_app_settings_cache_version, bump_app_settings_cache_version
    global get_governance_cache_version, bump_governance_cache_version
    global app_cache_is_using_redis

    app_cache_is_using_redis = False
    update_settings_cache = lambda new_settings: _update_settings_cache_fallback(
        new_settings,
        log_event_func=log_event_func,
    )
    get_settings_cache = lambda: _get_settings_cache_fallback(log_event_func=log_event_func)
    get_app_settings_cache_version = lambda: _get_app_settings_cache_version_fallback(
        log_event_func=log_event_func,
    )
    bump_app_settings_cache_version = lambda: _bump_app_settings_cache_version_fallback(
        log_event_func=log_event_func,
    )
    initialize_stream_session_cache = lambda cache_key, metadata, ttl_seconds=None: (
        _initialize_stream_session_cache_fallback(
            cache_key,
            metadata,
            ttl_seconds=ttl_seconds,
            log_event_func=log_event_func,
        )
    )
    set_stream_session_meta = lambda cache_key, metadata, ttl_seconds=None: (
        _set_stream_session_meta_fallback(
            cache_key,
            metadata,
            ttl_seconds=ttl_seconds,
            log_event_func=log_event_func,
        )
    )
    get_stream_session_meta = lambda cache_key: _get_stream_session_meta_fallback(
        cache_key,
        log_event_func=log_event_func,
    )
    append_stream_session_event = lambda cache_key, event_text, ttl_seconds=None: (
        _append_stream_session_event_fallback(
            cache_key,
            event_text,
            ttl_seconds=ttl_seconds,
            log_event_func=log_event_func,
        )
    )
    get_stream_session_events = lambda cache_key, start_index=0: _get_stream_session_events_fallback(
        cache_key,
        start_index=start_index,
        log_event_func=log_event_func,
    )
    delete_stream_session_cache = lambda cache_key: _delete_stream_session_cache_fallback(
        cache_key,
        log_event_func=log_event_func,
    )
    get_user_ui_settings_cache = lambda user_id: _get_user_ui_settings_cache_fallback(
        user_id,
        log_event_func=log_event_func,
    )
    set_user_ui_settings_cache = lambda user_id, ui_settings, ttl_seconds=None: (
        _set_user_ui_settings_cache_fallback(
            user_id,
            ui_settings,
            ttl_seconds=ttl_seconds,
            log_event_func=log_event_func,
        )
    )
    delete_user_ui_settings_cache = lambda user_id: _delete_user_ui_settings_cache_fallback(
        user_id,
        log_event_func=log_event_func,
    )
    get_governance_cache_version = lambda: _get_governance_cache_version_fallback(
        log_event_func=log_event_func,
    )
    bump_governance_cache_version = lambda: _bump_governance_cache_version_fallback(
        log_event_func=log_event_func,
    )


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
        redis_url = settings.get('redis_url', '').strip()
        redis_auth_type = settings.get('redis_auth_type', 'key').strip().lower()
        try:
            if not redis_url:
                raise ValueError('Redis cache is enabled but redis_url is empty.')
            if redis_auth_type == 'managed_identity':
                log_event("[ASC] Redis enabled using Managed Identity", level=logging.INFO)
                redis_client = create_redis_managed_identity_client(
                    redis_url,
                    settings=settings
                )
            elif redis_auth_type == 'key_vault':
                log_event("[ASC] Redis enabled using Key Vault Secret", level=logging.INFO)
                # Local import to avoid circular dependency: functions_keyvault imports app_settings_cache.
                from functions_keyvault import retrieve_secret_direct
                redis_key_secret_name = settings.get('redis_key', '').strip()
                # Pass settings directly: get_settings_cache() is still None at this point
                # because configure_app_cache has not finished initialising the cache yet.
                redis_password = retrieve_secret_direct(redis_key_secret_name, settings=settings)
                if redis_password:
                    redis_password = redis_password.strip()
                log_event("[ASC] Redis key retrieved from Key Vault successfully", level=logging.INFO)

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
            app_cache_is_using_redis = True
        except Exception as redis_init_error:
            _log_cache_fallback('redis_initialization', redis_init_error, log_event_func=log_event)
            _assign_fallback_cache_functions(log_event_func=log_event)
            return

        def get_app_settings_cache_version_redis():
            try:
                cached = redis_client.get(APP_SETTINGS_CACHE_VERSION_KEY)
                if cached is None:
                    redis_client.setnx(APP_SETTINGS_CACHE_VERSION_KEY, 0)
                    return 0
                return _normalize_cache_version(cached)
            except Exception as ex:
                _log_cache_fallback('get_app_settings_cache_version', ex, log_event_func=log_event)
                return _get_app_settings_cache_version_fallback(log_event_func=log_event)

        def bump_app_settings_cache_version_redis():
            try:
                return _normalize_cache_version(redis_client.incr(APP_SETTINGS_CACHE_VERSION_KEY))
            except Exception as ex:
                _log_cache_fallback('bump_app_settings_cache_version', ex, log_event_func=log_event)
                return _bump_app_settings_cache_version_fallback(log_event_func=log_event)

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
            try:
                redis_client.set(APP_SETTINGS_CACHE_KEY, json.dumps(new_settings))
                shared_version = get_app_settings_cache_version_redis()
                with _app_cache_lock:
                    APP_SETTINGS_CACHE = copy.deepcopy(new_settings or {})
                    APP_SETTINGS_CACHE_VERSION = shared_version
                _set_ttl_cached_version(APP_SETTINGS_SHARED_VERSION_CACHE, shared_version)
            except Exception as ex:
                _log_cache_fallback('update_settings_cache', ex, log_event_func=log_event)
                _update_settings_cache_fallback(new_settings, log_event_func=log_event)

        def get_settings_cache_redis():
            global APP_SETTINGS_CACHE, APP_SETTINGS_CACHE_VERSION
            try:
                shared_version = get_ttl_cached_app_settings_version_redis()
                with _app_cache_lock:
                    if APP_SETTINGS_CACHE and APP_SETTINGS_CACHE_VERSION == shared_version:
                        return copy.deepcopy(APP_SETTINGS_CACHE)

                cached = redis_client.get(APP_SETTINGS_CACHE_KEY)
                if cached is None:
                    return _get_settings_cache_fallback(log_event_func=log_event)
                loaded_settings = json.loads(cached)
                with _app_cache_lock:
                    APP_SETTINGS_CACHE = copy.deepcopy(loaded_settings or {})
                    APP_SETTINGS_CACHE_VERSION = shared_version
                return copy.deepcopy(loaded_settings or {})
            except Exception as ex:
                _log_cache_fallback('get_settings_cache', ex, log_event_func=log_event)
                return _get_settings_cache_fallback(log_event_func=log_event)

        def get_stream_session_metadata_key(cache_key):
            return f'STREAM_SESSION_META:{cache_key}'

        def get_stream_session_events_key(cache_key):
            return f'STREAM_SESSION_EVENTS:{cache_key}'

        def initialize_stream_session_cache_redis(cache_key, metadata, ttl_seconds=None):
            try:
                metadata_key = get_stream_session_metadata_key(cache_key)
                events_key = get_stream_session_events_key(cache_key)
                pipeline = redis_client.pipeline()
                pipeline.delete(events_key)
                pipeline.set(metadata_key, json.dumps(metadata))
                if ttl_seconds is not None:
                    pipeline.expire(metadata_key, int(ttl_seconds))
                pipeline.execute()
            except Exception as ex:
                _log_cache_fallback('initialize_stream_session_cache', ex, log_event_func=log_event)
                _initialize_stream_session_cache_fallback(
                    cache_key,
                    metadata,
                    ttl_seconds=ttl_seconds,
                    log_event_func=log_event,
                )

        def set_stream_session_meta_redis(cache_key, metadata, ttl_seconds=None):
            try:
                metadata_key = get_stream_session_metadata_key(cache_key)
                events_key = get_stream_session_events_key(cache_key)
                pipeline = redis_client.pipeline()
                pipeline.set(metadata_key, json.dumps(metadata))
                if ttl_seconds is not None:
                    pipeline.expire(metadata_key, int(ttl_seconds))
                    if redis_client.exists(events_key):
                        pipeline.expire(events_key, int(ttl_seconds))
                pipeline.execute()
            except Exception as ex:
                _log_cache_fallback('set_stream_session_meta', ex, log_event_func=log_event)
                _set_stream_session_meta_fallback(
                    cache_key,
                    metadata,
                    ttl_seconds=ttl_seconds,
                    log_event_func=log_event,
                )

        def get_stream_session_meta_redis(cache_key):
            try:
                cached = redis_client.get(get_stream_session_metadata_key(cache_key))
                return json.loads(cached) if cached else None
            except Exception as ex:
                _log_cache_fallback('get_stream_session_meta', ex, log_event_func=log_event)
                return _get_stream_session_meta_fallback(cache_key, log_event_func=log_event)

        def append_stream_session_event_redis(cache_key, event_text, ttl_seconds=None):
            try:
                metadata_key = get_stream_session_metadata_key(cache_key)
                events_key = get_stream_session_events_key(cache_key)
                pipeline = redis_client.pipeline()
                pipeline.rpush(events_key, event_text)
                if ttl_seconds is not None:
                    pipeline.expire(events_key, int(ttl_seconds))
                    if redis_client.exists(metadata_key):
                        pipeline.expire(metadata_key, int(ttl_seconds))
                pipeline.execute()
            except Exception as ex:
                _log_cache_fallback('append_stream_session_event', ex, log_event_func=log_event)
                _append_stream_session_event_fallback(
                    cache_key,
                    event_text,
                    ttl_seconds=ttl_seconds,
                    log_event_func=log_event,
                )

        def get_stream_session_events_redis(cache_key, start_index=0):
            try:
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
            except Exception as ex:
                _log_cache_fallback('get_stream_session_events', ex, log_event_func=log_event)
                return _get_stream_session_events_fallback(
                    cache_key,
                    start_index=start_index,
                    log_event_func=log_event,
                )

        def delete_stream_session_cache_redis(cache_key):
            try:
                redis_client.delete(
                    get_stream_session_metadata_key(cache_key),
                    get_stream_session_events_key(cache_key),
                )
            except Exception as ex:
                _log_cache_fallback('delete_stream_session_cache', ex, log_event_func=log_event)
                _delete_stream_session_cache_fallback(cache_key, log_event_func=log_event)

        def get_user_ui_settings_cache_key(user_id):
            return f'{USER_UI_SETTINGS_CACHE_KEY_PREFIX}:{user_id}'

        def get_user_ui_settings_cache_redis(user_id):
            try:
                cached = redis_client.get(get_user_ui_settings_cache_key(user_id))
                return json.loads(cached) if cached else None
            except Exception as ex:
                _log_cache_fallback('get_user_ui_settings_cache', ex, log_event_func=log_event)
                return _get_user_ui_settings_cache_fallback(user_id, log_event_func=log_event)

        def set_user_ui_settings_cache_redis(user_id, ui_settings, ttl_seconds=None):
            ttl = int(ttl_seconds or USER_UI_SETTINGS_CACHE_TTL_SECONDS)
            try:
                redis_client.setex(
                    get_user_ui_settings_cache_key(user_id),
                    ttl,
                    json.dumps(ui_settings or {})
                )
            except Exception as ex:
                _log_cache_fallback('set_user_ui_settings_cache', ex, log_event_func=log_event)
                _set_user_ui_settings_cache_fallback(
                    user_id,
                    ui_settings,
                    ttl_seconds=ttl,
                    log_event_func=log_event,
                )

        def delete_user_ui_settings_cache_redis(user_id):
            try:
                redis_client.delete(get_user_ui_settings_cache_key(user_id))
            except Exception as ex:
                _log_cache_fallback('delete_user_ui_settings_cache', ex, log_event_func=log_event)
                _delete_user_ui_settings_cache_fallback(user_id, log_event_func=log_event)

        def get_governance_cache_version_redis():
            try:
                cached = redis_client.get(GOVERNANCE_CACHE_VERSION_KEY)
                if cached is None:
                    redis_client.setnx(GOVERNANCE_CACHE_VERSION_KEY, 0)
                    return 0
                return _normalize_cache_version(cached)
            except Exception as ex:
                _log_cache_fallback('get_governance_cache_version', ex, log_event_func=log_event)
                return _get_governance_cache_version_fallback(log_event_func=log_event)

        def bump_governance_cache_version_redis():
            try:
                return _normalize_cache_version(redis_client.incr(GOVERNANCE_CACHE_VERSION_KEY))
            except Exception as ex:
                _log_cache_fallback('bump_governance_cache_version', ex, log_event_func=log_event)
                return _bump_governance_cache_version_fallback(log_event_func=log_event)

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
            except Exception as ex:
                _logger.warning("[ASC] Shared cache version read failed; using local version fallback: %s", ex)
                log_event(
                    "[ASC] Shared cache version read failed; using local version fallback.",
                    extra={'version_doc_id': APP_SETTINGS_CACHE_VERSION_DOC_ID, 'error': str(ex)},
                    level=logging.WARNING,
                )
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
            except Exception as ex:
                _logger.warning("[ASC] Shared cache version bump failed; using local version fallback: %s", ex)
                log_event(
                    "[ASC] Shared cache version bump failed; using local version fallback.",
                    extra={'version_doc_id': APP_SETTINGS_CACHE_VERSION_DOC_ID, 'error': str(ex)},
                    level=logging.WARNING,
                )

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
            except Exception as ex:
                _logger.warning("[ASC] Governance cache version read failed; using local version fallback: %s", ex)
                log_event(
                    "[ASC] Governance cache version read failed; using local version fallback.",
                    extra={'version_doc_id': GOVERNANCE_CACHE_VERSION_DOC_ID, 'error': str(ex)},
                    level=logging.WARNING,
                )
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
            except Exception as ex:
                _logger.warning("[ASC] Governance cache version bump failed; using local version fallback: %s", ex)
                log_event(
                    "[ASC] Governance cache version bump failed; using local version fallback.",
                    extra={'version_doc_id': GOVERNANCE_CACHE_VERSION_DOC_ID, 'error': str(ex)},
                    level=logging.WARNING,
                )

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