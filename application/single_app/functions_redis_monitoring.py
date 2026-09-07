# functions_redis_monitoring.py

from datetime import datetime, timezone
import json
import re
import time

import app_settings_cache
import functions_redis_client


REDIS_MONITORING_STATUS_DISABLED = "disabled"
REDIS_MONITORING_STATUS_NOT_CONFIGURED = "not_configured"
REDIS_MONITORING_STATUS_UNAVAILABLE = "unavailable"
REDIS_MONITORING_STATUS_HEALTHY = "healthy"
REDIS_MONITORING_STATUS_DEGRADED = "degraded"
REDIS_MONITORING_STATUS_ERROR = "error"
REDIS_EXPLORER_DEFAULT_PAGE_SIZE = 25
REDIS_EXPLORER_MAX_PAGE_SIZE = 100
REDIS_EXPLORER_MAX_SCAN_ITERATIONS = 5
REDIS_EXPLORER_MAX_FILTER_LENGTH = 128
REDIS_EXPLORER_MAX_KEY_LENGTH = 1024
REDIS_EXPLORER_VALUE_ITEM_LIMIT = 20
REDIS_EXPLORER_PREVIEW_MAX_CHARS = 4096
REDIS_EXPLORER_RESTRICTED_KEY_TOKENS = (
    "authorization",
    "cookie",
    "credential",
    "csrf",
    "password",
    "secret",
    "session",
    "token",
)
REDIS_EXPLORER_SENSITIVE_FIELD_TOKENS = REDIS_EXPLORER_RESTRICTED_KEY_TOKENS + (
    "api_key",
    "connection",
    "key",
)
REDIS_EXPLORER_REDACTED_VALUE = "[REDACTED]"
REDIS_EXPLORER_RESTRICTED_PREVIEW = (
    "Preview restricted because the Redis key name indicates session, token, cookie, or credential data."
)
REDIS_DAI_CACHE_KEY_PREFIX = "DAI_LIST_CACHE"
REDIS_DAI_CACHE_VERSION_KEY_PREFIX = "DAI_LIST_CACHE_VERSION"
REDIS_DAI_CACHE_PAYLOAD_TTL_DEFAULT_SECONDS = 900
REDIS_DAI_CACHE_PAYLOAD_TTL_MIN_SECONDS = 60
REDIS_DAI_CACHE_PAYLOAD_TTL_MAX_SECONDS = 900
REDIS_DAI_CACHE_VERSION_TTL_MIN_SECONDS = 3600
REDIS_DAI_CACHE_VERSION_TTL_MAX_SECONDS = 86400
REDIS_DAI_CACHE_VERSION_TTL_MULTIPLIER = 4
REDIS_DAI_CACHE_KEYSPACE_SCAN_ITERATIONS = 5
REDIS_EXPLORER_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|connection[_-]?string|password|secret|token)(\s*[:=]\s*)([^\s,;}\]]+)"
)
REDIS_DAI_VERSION_KEY_PATTERN = re.compile(r"^DAI_LIST_CACHE_VERSION:([a-fA-F0-9]{64})$")
REDIS_DAI_PAYLOAD_KEY_PATTERN = re.compile(r"^DAI_LIST_CACHE:([^:]+):([^:]+):([a-fA-F0-9]{64})$")


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_int(value):
    if value is None or value == "":
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _safe_str(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return ""
    return str(value)


def _safe_float(value):
    if value is None or value == "":
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_percentage(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 2)


def _safe_error_summary(context, exc):
    return f"{context} ({exc.__class__.__name__})."


def _clamp_int(value, default_value, minimum_value, maximum_value):
    numeric_value = _safe_int(value)
    if numeric_value is None:
        return default_value
    return min(max(numeric_value, minimum_value), maximum_value)


def _calculate_dai_cache_version_ttl_seconds(settings):
    payload_ttl_seconds = _clamp_int(
        (settings or {}).get("document_access_index_cache_ttl_seconds"),
        REDIS_DAI_CACHE_PAYLOAD_TTL_DEFAULT_SECONDS,
        REDIS_DAI_CACHE_PAYLOAD_TTL_MIN_SECONDS,
        REDIS_DAI_CACHE_PAYLOAD_TTL_MAX_SECONDS,
    )
    return min(
        max(
            payload_ttl_seconds * REDIS_DAI_CACHE_VERSION_TTL_MULTIPLIER,
            REDIS_DAI_CACHE_VERSION_TTL_MIN_SECONDS,
        ),
        REDIS_DAI_CACHE_VERSION_TTL_MAX_SECONDS,
    )


def _build_empty_dai_cache_keyspace(settings):
    payload_ttl_seconds = _clamp_int(
        (settings or {}).get("document_access_index_cache_ttl_seconds"),
        REDIS_DAI_CACHE_PAYLOAD_TTL_DEFAULT_SECONDS,
        REDIS_DAI_CACHE_PAYLOAD_TTL_MIN_SECONDS,
        REDIS_DAI_CACHE_PAYLOAD_TTL_MAX_SECONDS,
    )
    return {
        "payload_ttl_seconds": payload_ttl_seconds,
        "version_marker_ttl_seconds": _calculate_dai_cache_version_ttl_seconds(settings),
        "payload_key_count": 0,
        "version_marker_count": 0,
        "version_marker_no_expiry_count": 0,
        "version_marker_expiring_count": 0,
        "version_marker_low_ttl_count": 0,
        "version_marker_memory_usage_bytes": 0,
        "scan_complete": True,
        "scan_error": None,
    }


def _scan_count_matching_keys(redis_client, pattern):
    cursor = 0
    total = 0
    iterations = 0
    while iterations < REDIS_DAI_CACHE_KEYSPACE_SCAN_ITERATIONS:
        cursor, keys = redis_client.scan(
            cursor=cursor,
            match=pattern,
            count=REDIS_EXPLORER_MAX_PAGE_SIZE,
        )
        cursor = _normalize_redis_cursor(cursor)
        total += len(list(keys or []))
        iterations += 1
        if cursor == 0:
            break
    return total, cursor == 0


def _build_dai_cache_keyspace(redis_client, settings):
    keyspace = _build_empty_dai_cache_keyspace(settings)
    if redis_client is None:
        keyspace["scan_complete"] = False
        keyspace["scan_error"] = "Redis client is not available."
        return keyspace

    try:
        payload_count, payload_scan_complete = _scan_count_matching_keys(
            redis_client,
            f"{REDIS_DAI_CACHE_KEY_PREFIX}:*",
        )
        keyspace["payload_key_count"] = payload_count
        keyspace["scan_complete"] = payload_scan_complete

        cursor = 0
        iterations = 0
        while iterations < REDIS_DAI_CACHE_KEYSPACE_SCAN_ITERATIONS:
            cursor, keys = redis_client.scan(
                cursor=cursor,
                match=f"{REDIS_DAI_CACHE_VERSION_KEY_PREFIX}:*",
                count=REDIS_EXPLORER_MAX_PAGE_SIZE,
            )
            cursor = _normalize_redis_cursor(cursor)
            iterations += 1
            for key in list(keys or []):
                keyspace["version_marker_count"] += 1
                ttl_seconds = _safe_int(redis_client.ttl(key))
                if ttl_seconds == -1:
                    keyspace["version_marker_no_expiry_count"] += 1
                elif ttl_seconds is not None and ttl_seconds >= 0:
                    keyspace["version_marker_expiring_count"] += 1
                    if ttl_seconds < keyspace["payload_ttl_seconds"]:
                        keyspace["version_marker_low_ttl_count"] += 1
                keyspace["version_marker_memory_usage_bytes"] += _get_redis_memory_usage(redis_client, key) or 0
            if cursor == 0:
                break
        keyspace["scan_complete"] = keyspace["scan_complete"] and cursor == 0
    except Exception as exc:
        keyspace["scan_complete"] = False
        keyspace["scan_error"] = _safe_error_summary("DAI cache keyspace scan failed", exc)
    return keyspace


def _redact_sensitive_text(value):
    return REDIS_EXPLORER_SENSITIVE_TEXT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDIS_EXPLORER_REDACTED_VALUE}",
        _safe_str(value),
    )


def _contains_sensitive_token(value, sensitive_tokens=REDIS_EXPLORER_RESTRICTED_KEY_TOKENS):
    normalized_value = _safe_str(value).lower()
    return any(token in normalized_value for token in sensitive_tokens)


def _sanitize_preview_payload(value, parent_key=""):
    if _contains_sensitive_token(parent_key, REDIS_EXPLORER_SENSITIVE_FIELD_TOKENS):
        return REDIS_EXPLORER_REDACTED_VALUE
    if isinstance(value, dict):
        return {
            _safe_str(key): _sanitize_preview_payload(item_value, parent_key=_safe_str(key))
            for key, item_value in list(value.items())[:REDIS_EXPLORER_VALUE_ITEM_LIMIT]
        }
    if isinstance(value, (list, tuple, set)):
        sanitized_items = [
            _sanitize_preview_payload(item, parent_key=parent_key)
            for item in list(value)[:REDIS_EXPLORER_VALUE_ITEM_LIMIT]
        ]
        if len(value) > REDIS_EXPLORER_VALUE_ITEM_LIMIT:
            sanitized_items.append(f"... {len(value) - REDIS_EXPLORER_VALUE_ITEM_LIMIT} more item(s)")
        return sanitized_items
    if isinstance(value, bytes):
        return _redact_sensitive_text(value)
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    return value


def _build_preview_response(value, preview_format="text"):
    truncated = False
    if preview_format == "json":
        sanitized_payload = _sanitize_preview_payload(value)
        preview = json.dumps(sanitized_payload, indent=2, sort_keys=True, default=str)
    else:
        preview = _redact_sensitive_text(value)

    if len(preview) > REDIS_EXPLORER_PREVIEW_MAX_CHARS:
        preview = preview[:REDIS_EXPLORER_PREVIEW_MAX_CHARS]
        truncated = True

    return {
        "preview": preview,
        "preview_format": preview_format,
        "redacted": REDIS_EXPLORER_REDACTED_VALUE in preview,
        "truncated": truncated,
    }


def _build_string_preview(value):
    text_value = _safe_str(value)
    try:
        decoded_json = json.loads(text_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _build_preview_response(text_value, preview_format="text")
    return _build_preview_response(decoded_json, preview_format="json")


def _build_collection_preview(value):
    return _build_preview_response(value, preview_format="json")


def _escape_redis_glob(value):
    escaped_value = ""
    for character in _safe_str(value):
        if character in ("*", "?", "[", "]", "\\"):
            escaped_value += f"\\{character}"
        else:
            escaped_value += character
    return escaped_value


def _normalize_key_filter(raw_filter):
    filter_text = _safe_str(raw_filter).strip()
    if not filter_text:
        return ""
    return filter_text[:REDIS_EXPLORER_MAX_FILTER_LENGTH]


def _build_scan_pattern(raw_filter):
    normalized_filter = _normalize_key_filter(raw_filter)
    if not normalized_filter:
        return "*"
    return f"*{_escape_redis_glob(normalized_filter)}*"


def _normalize_redis_cursor(raw_cursor):
    cursor_value = _safe_int(raw_cursor)
    if cursor_value is None or cursor_value < 0:
        return 0
    return cursor_value


def _normalize_redis_key(raw_key):
    key = _safe_str(raw_key).strip()
    if not key:
        raise ValueError("Redis key is required.")
    if len(key) > REDIS_EXPLORER_MAX_KEY_LENGTH:
        raise ValueError("Redis key is too long.")
    return key


def _get_redis_type(redis_client, key):
    return _safe_str(redis_client.type(key)).lower()


def _get_redis_memory_usage(redis_client, key):
    try:
        return _safe_int(redis_client.memory_usage(key))
    except (AttributeError, TypeError):
        return None


def _build_resolution_payload(kind, label, resolved=False, **kwargs):
    payload = {
        "kind": kind,
        "label": label,
        "resolved": bool(resolved),
    }
    payload.update(kwargs)
    return payload


def _resolve_dai_version_hashes(scope_hashes, dai_hash_resolver=None):
    resolver = dai_hash_resolver
    if resolver is None:
        try:
            # Imported lazily because the DAI module initializes Cosmos-backed containers.
            from functions_document_access_index import resolve_document_access_cache_version_hashes

            resolver = resolve_document_access_cache_version_hashes
        except Exception as exc:
            return {
                scope_hash: _build_resolution_payload(
                    "document_access_index_scope_version",
                    "DAI scope version marker",
                    resolved=False,
                    resolution_status="unavailable",
                    scope_hash=scope_hash,
                    note=_safe_error_summary("DAI hash resolution unavailable", exc),
                )
                for scope_hash in scope_hashes
            }
    try:
        return resolver(scope_hashes)
    except Exception as exc:
        return {
            scope_hash: _build_resolution_payload(
                "document_access_index_scope_version",
                "DAI scope version marker",
                resolved=False,
                resolution_status="unavailable",
                scope_hash=scope_hash,
                note=_safe_error_summary("DAI hash resolution failed", exc),
            )
            for scope_hash in scope_hashes
        }


def _resolve_redis_keys(keys, dai_hash_resolver=None):
    resolutions = {}
    dai_version_hashes = []
    dai_version_keys_by_hash = {}
    for key in list(keys or []):
        normalized_key = _safe_str(key)
        dai_version_match = REDIS_DAI_VERSION_KEY_PATTERN.match(normalized_key)
        if dai_version_match:
            scope_hash = dai_version_match.group(1).lower()
            dai_version_hashes.append(scope_hash)
            dai_version_keys_by_hash[scope_hash] = normalized_key
            continue

        dai_payload_match = REDIS_DAI_PAYLOAD_KEY_PATTERN.match(normalized_key)
        if dai_payload_match:
            operation, source_scope, cache_hash = dai_payload_match.groups()
            resolutions[normalized_key] = _build_resolution_payload(
                "document_access_index_payload",
                "DAI read-through cache payload",
                resolved=False,
                operation=operation,
                source_scope=source_scope,
                cache_hash=cache_hash.lower(),
                note="Payload keys include filters, scope versions, and process epoch, so the key hash is not reversible from Redis alone.",
            )
            continue

        if normalized_key == app_settings_cache.APP_SETTINGS_CACHE_KEY:
            resolutions[normalized_key] = _build_resolution_payload(
                "app_settings_cache",
                "App settings cache payload",
                resolved=True,
                note="Global app settings cache payload.",
            )
        elif normalized_key == app_settings_cache.APP_SETTINGS_CACHE_VERSION_KEY:
            resolutions[normalized_key] = _build_resolution_payload(
                "app_settings_cache_version",
                "App settings cache version",
                resolved=True,
                note="Global app settings cache invalidation version.",
            )

    if dai_version_hashes:
        dai_resolutions = _resolve_dai_version_hashes(dai_version_hashes, dai_hash_resolver=dai_hash_resolver)
        for scope_hash, resolution in (dai_resolutions or {}).items():
            key = dai_version_keys_by_hash.get(scope_hash)
            if key:
                resolutions[key] = resolution
    return resolutions


def _build_redis_key_summary(redis_client, key, resolution=None):
    normalized_key = _safe_str(key)
    return {
        "key": normalized_key,
        "type": _get_redis_type(redis_client, normalized_key),
        "ttl_seconds": _safe_int(redis_client.ttl(normalized_key)),
        "memory_usage_bytes": _get_redis_memory_usage(redis_client, normalized_key),
        "preview_restricted": _contains_sensitive_token(normalized_key),
        "resolution": resolution,
    }


def _build_explorer_unavailable_status(settings, app_cache_client, session_redis_client, session_type):
    monitoring_status = get_redis_monitoring_status(
        settings,
        app_cache_client=app_cache_client,
        session_redis_client=session_redis_client,
        session_type=session_type,
    )
    return {
        "success": False,
        "status": monitoring_status.get("health", {}).get("status") or REDIS_MONITORING_STATUS_UNAVAILABLE,
        "checked_at": monitoring_status.get("checked_at"),
        "runtime": monitoring_status.get("runtime", {}),
        "last_error": monitoring_status.get("health", {}).get("last_error"),
    }


def _resolve_explorer_client(settings, app_cache_client=None, session_redis_client=None, session_type=None):
    safe_settings = settings if isinstance(settings, dict) else {}
    resolved_app_cache_client = (
        app_cache_client
        if app_cache_client is not None
        else app_settings_cache.get_app_cache_redis_client()
    )
    monitoring_client, monitoring_source = _select_monitoring_client(
        resolved_app_cache_client,
        session_redis_client,
    )

    if not bool(safe_settings.get("enable_redis_cache")):
        return None, _build_explorer_unavailable_status(
            safe_settings,
            resolved_app_cache_client,
            session_redis_client,
            session_type,
        )
    if not str(safe_settings.get("redis_url") or "").strip():
        return None, _build_explorer_unavailable_status(
            safe_settings,
            resolved_app_cache_client,
            session_redis_client,
            session_type,
        )
    if monitoring_client is None:
        return None, _build_explorer_unavailable_status(
            safe_settings,
            resolved_app_cache_client,
            session_redis_client,
            session_type,
        )

    return monitoring_client, {
        "success": True,
        "status": REDIS_MONITORING_STATUS_HEALTHY,
        "checked_at": _utc_now_iso(),
        "runtime": {
            "monitoring_source": monitoring_source,
            "client_available": True,
        },
    }


def _parse_keyspace_database(value):
    if isinstance(value, dict):
        return {
            "keys": _safe_int(value.get("keys")),
            "expires": _safe_int(value.get("expires")),
            "avg_ttl": _safe_int(value.get("avg_ttl")),
        }

    if isinstance(value, bytes):
        value = value.decode("utf-8")

    parsed = {}
    for segment in str(value or "").split(","):
        if "=" not in segment:
            continue
        key, raw_value = segment.split("=", 1)
        parsed[key.strip()] = _safe_int(raw_value.strip())

    return {
        "keys": parsed.get("keys"),
        "expires": parsed.get("expires"),
        "avg_ttl": parsed.get("avg_ttl"),
    }


def _extract_keyspace(info):
    databases = {}
    total_keys = 0
    expiring_keys = 0
    for key, value in (info or {}).items():
        key_name = str(key)
        if not key_name.startswith("db"):
            continue
        database = _parse_keyspace_database(value)
        databases[key_name] = database
        total_keys += database.get("keys") or 0
        expiring_keys += database.get("expires") or 0

    return {
        "databases": databases,
        "total_keys": total_keys,
        "expiring_keys": expiring_keys,
    }


def _build_empty_metric_sections():
    return {
        "server": {},
        "clients": {},
        "memory": {},
        "stats": {},
        "keyspace": {
            "databases": {},
            "total_keys": 0,
            "expiring_keys": 0,
        },
    }


def _build_info_metric_sections(info):
    used_memory = _safe_int(info.get("used_memory"))
    maxmemory = _safe_int(info.get("maxmemory"))
    keyspace_hits = _safe_int(info.get("keyspace_hits"))
    keyspace_misses = _safe_int(info.get("keyspace_misses"))
    keyspace_total = (keyspace_hits or 0) + (keyspace_misses or 0)

    return {
        "server": {
            "redis_version": info.get("redis_version"),
            "uptime_in_seconds": _safe_int(info.get("uptime_in_seconds")),
            "uptime_in_days": _safe_int(info.get("uptime_in_days")),
        },
        "clients": {
            "connected_clients": _safe_int(info.get("connected_clients")),
            "blocked_clients": _safe_int(info.get("blocked_clients")),
            "tracking_clients": _safe_int(info.get("tracking_clients")),
            "maxclients": _safe_int(info.get("maxclients")),
        },
        "memory": {
            "used_memory": used_memory,
            "used_memory_human": info.get("used_memory_human"),
            "maxmemory": maxmemory,
            "maxmemory_human": info.get("maxmemory_human"),
            "maxmemory_policy": info.get("maxmemory_policy"),
            "usage_percent": _safe_percentage(used_memory, maxmemory),
            "mem_fragmentation_ratio": _safe_float(info.get("mem_fragmentation_ratio")),
        },
        "stats": {
            "total_connections_received": _safe_int(info.get("total_connections_received")),
            "total_commands_processed": _safe_int(info.get("total_commands_processed")),
            "instantaneous_ops_per_sec": _safe_int(info.get("instantaneous_ops_per_sec")),
            "keyspace_hits": keyspace_hits,
            "keyspace_misses": keyspace_misses,
            "keyspace_hit_rate_percent": _safe_percentage(keyspace_hits, keyspace_total),
            "expired_keys": _safe_int(info.get("expired_keys")),
            "evicted_keys": _safe_int(info.get("evicted_keys")),
            "rejected_connections": _safe_int(info.get("rejected_connections")),
            "total_error_replies": _safe_int(info.get("total_error_replies")),
        },
        "keyspace": _extract_keyspace(info),
    }


def _select_monitoring_client(app_cache_client, session_redis_client):
    if app_cache_client is not None:
        return app_cache_client, "app_cache"
    if session_redis_client is not None:
        return session_redis_client, "session"
    return None, "none"


def get_redis_monitoring_status(
    settings,
    app_cache_client=None,
    session_redis_client=None,
    session_type=None,
    now_func=None,
):
    """Return sanitized Redis health and capacity metrics for admin monitoring."""
    safe_settings = settings if isinstance(settings, dict) else {}
    enabled = bool(safe_settings.get("enable_redis_cache"))
    configured = bool(str(safe_settings.get("redis_url") or "").strip())
    auth_type = str(safe_settings.get("redis_auth_type") or "key").strip().lower() or "key"
    # Without a host name there is nothing to resolve, so report the service as unknown
    # rather than showing the Azure Cache for Redis fallback used for connection attempts.
    connection = (
        functions_redis_client.describe_redis_connection(safe_settings)
        if configured
        else {"service_type": None, "service_type_source": None, "port": None}
    )
    resolved_app_cache_client = (
        app_cache_client
        if app_cache_client is not None
        else app_settings_cache.get_app_cache_redis_client()
    )
    app_cache_using_redis = bool(app_settings_cache.app_cache_is_using_redis and resolved_app_cache_client)
    session_using_redis = str(session_type or "").strip().lower() == "redis" and session_redis_client is not None
    monitoring_client, monitoring_source = _select_monitoring_client(
        resolved_app_cache_client,
        session_redis_client,
    )
    checked_at = (now_func or _utc_now_iso)()

    status = {
        "checked_at": checked_at,
        "configuration": {
            "enabled": enabled,
            "configured": configured,
            "auth_type": auth_type,
            "service_type": connection["service_type"],
            "service_type_source": connection["service_type_source"],
            "port": connection["port"],
        },
        "runtime": {
            "app_cache_using_redis": app_cache_using_redis,
            "session_using_redis": session_using_redis,
            "monitoring_source": monitoring_source,
            "client_available": monitoring_client is not None,
        },
        "health": {
            "status": REDIS_MONITORING_STATUS_DISABLED,
            "ping_success": False,
            "ping_latency_ms": None,
            "last_error": None,
        },
        "dai_cache": _build_empty_dai_cache_keyspace(safe_settings),
        **_build_empty_metric_sections(),
    }

    if not enabled:
        return status

    if not configured:
        status["health"]["status"] = REDIS_MONITORING_STATUS_NOT_CONFIGURED
        status["health"]["last_error"] = "Redis cache is enabled but no host name is configured."
        return status

    if monitoring_client is None:
        status["health"]["status"] = REDIS_MONITORING_STATUS_UNAVAILABLE
        status["health"]["last_error"] = "Redis is configured, but no active runtime Redis client is available."
        return status

    ping_started_at = time.perf_counter()
    try:
        status["health"]["ping_success"] = bool(monitoring_client.ping())
        status["health"]["ping_latency_ms"] = round((time.perf_counter() - ping_started_at) * 1000, 2)
    except Exception as exc:
        status["health"]["status"] = REDIS_MONITORING_STATUS_ERROR
        status["health"]["last_error"] = _safe_error_summary("Redis ping failed", exc)
        return status

    try:
        info = monitoring_client.info()
    except Exception as exc:
        status["health"]["status"] = REDIS_MONITORING_STATUS_DEGRADED
        status["health"]["last_error"] = _safe_error_summary("Redis INFO metrics failed", exc)
        return status

    if not isinstance(info, dict):
        status["health"]["status"] = REDIS_MONITORING_STATUS_DEGRADED
        status["health"]["last_error"] = "Redis INFO metrics returned an unexpected response."
        return status

    status.update(_build_info_metric_sections(info))
    status["dai_cache"] = _build_dai_cache_keyspace(monitoring_client, safe_settings)
    status["health"]["status"] = (
        REDIS_MONITORING_STATUS_HEALTHY
        if status["health"]["ping_success"]
        else REDIS_MONITORING_STATUS_DEGRADED
    )
    return status


def get_redis_explorer_keys(
    settings,
    cursor=0,
    page_size=REDIS_EXPLORER_DEFAULT_PAGE_SIZE,
    key_filter="",
    app_cache_client=None,
    session_redis_client=None,
    session_type=None,
    dai_hash_resolver=None,
):
    """Return one cursor-paginated Redis key page with safe metadata only."""
    redis_client, status = _resolve_explorer_client(
        settings,
        app_cache_client=app_cache_client,
        session_redis_client=session_redis_client,
        session_type=session_type,
    )
    if redis_client is None:
        return {
            **status,
            "keys": [],
            "cursor": str(_normalize_redis_cursor(cursor)),
            "next_cursor": "0",
            "has_more": False,
            "page_size": _clamp_int(
                page_size,
                REDIS_EXPLORER_DEFAULT_PAGE_SIZE,
                1,
                REDIS_EXPLORER_MAX_PAGE_SIZE,
            ),
            "filter": _normalize_key_filter(key_filter),
        }

    normalized_cursor = _normalize_redis_cursor(cursor)
    normalized_page_size = _clamp_int(
        page_size,
        REDIS_EXPLORER_DEFAULT_PAGE_SIZE,
        1,
        REDIS_EXPLORER_MAX_PAGE_SIZE,
    )
    normalized_filter = _normalize_key_filter(key_filter)
    scan_pattern = _build_scan_pattern(normalized_filter)
    next_cursor = normalized_cursor
    collected_keys = []
    scan_iterations = 0

    while len(collected_keys) < normalized_page_size and scan_iterations < REDIS_EXPLORER_MAX_SCAN_ITERATIONS:
        raw_cursor, scanned_keys = redis_client.scan(
            cursor=next_cursor,
            match=scan_pattern,
            count=normalized_page_size,
        )
        next_cursor = _normalize_redis_cursor(raw_cursor)
        scan_iterations += 1
        for key in list(scanned_keys or []):
            if len(collected_keys) >= normalized_page_size:
                break
            collected_keys.append(_safe_str(key))
        if next_cursor == 0:
            break

    resolutions = _resolve_redis_keys(collected_keys, dai_hash_resolver=dai_hash_resolver)
    return {
        **status,
        "keys": [
            _build_redis_key_summary(redis_client, key, resolution=resolutions.get(key))
            for key in collected_keys
        ],
        "cursor": str(normalized_cursor),
        "next_cursor": str(next_cursor),
        "has_more": next_cursor != 0,
        "page_size": normalized_page_size,
        "filter": normalized_filter,
        "scan_iterations": scan_iterations,
    }


def _read_redis_value_preview(redis_client, key, key_type):
    if key_type == "string":
        return _build_string_preview(redis_client.get(key))
    if key_type == "hash":
        _cursor, values = redis_client.hscan(key, cursor=0, count=REDIS_EXPLORER_VALUE_ITEM_LIMIT)
        return _build_collection_preview({
            _safe_str(field): _safe_str(value)
            for field, value in dict(values or {}).items()
        })
    if key_type == "list":
        return _build_collection_preview([
            _safe_str(value)
            for value in list(redis_client.lrange(key, 0, REDIS_EXPLORER_VALUE_ITEM_LIMIT - 1) or [])
        ])
    if key_type == "set":
        _cursor, values = redis_client.sscan(key, cursor=0, count=REDIS_EXPLORER_VALUE_ITEM_LIMIT)
        return _build_collection_preview([_safe_str(value) for value in list(values or [])])
    if key_type == "zset":
        return _build_collection_preview([
            {
                "value": _safe_str(value),
                "score": score,
            }
            for value, score in list(redis_client.zrange(
                key,
                0,
                REDIS_EXPLORER_VALUE_ITEM_LIMIT - 1,
                withscores=True,
            ) or [])
        ])
    if key_type == "stream":
        return _build_collection_preview([
            {
                "id": _safe_str(entry_id),
                "fields": {
                    _safe_str(field): _safe_str(value)
                    for field, value in dict(fields or {}).items()
                },
            }
            for entry_id, fields in list(redis_client.xrange(
                key,
                min="-",
                max="+",
                count=REDIS_EXPLORER_VALUE_ITEM_LIMIT,
            ) or [])
        ])
    return {
        "preview": f"Preview is not available for Redis key type '{key_type}'.",
        "preview_format": "text",
        "redacted": False,
        "truncated": False,
    }


def get_redis_explorer_value(
    settings,
    key,
    app_cache_client=None,
    session_redis_client=None,
    session_type=None,
    dai_hash_resolver=None,
):
    """Return sanitized metadata and preview content for one Redis key."""
    normalized_key = _normalize_redis_key(key)
    redis_client, status = _resolve_explorer_client(
        settings,
        app_cache_client=app_cache_client,
        session_redis_client=session_redis_client,
        session_type=session_type,
    )
    if redis_client is None:
        return {
            **status,
            "key": normalized_key,
            "type": "unknown",
            "preview": "",
            "preview_format": "text",
            "redacted": False,
            "truncated": False,
            "preview_restricted": False,
        }

    key_type = _get_redis_type(redis_client, normalized_key)
    if key_type in ("", "none"):
        return {
            **status,
            "success": False,
            "status": "not_found",
            "key": normalized_key,
            "type": "none",
            "ttl_seconds": -2,
            "memory_usage_bytes": None,
            "preview": "Redis key was not found.",
            "preview_format": "text",
            "redacted": False,
            "truncated": False,
            "preview_restricted": False,
        }

    resolutions = _resolve_redis_keys([normalized_key], dai_hash_resolver=dai_hash_resolver)
    metadata = {
        "key": normalized_key,
        "type": key_type,
        "ttl_seconds": _safe_int(redis_client.ttl(normalized_key)),
        "memory_usage_bytes": _get_redis_memory_usage(redis_client, normalized_key),
        "preview_restricted": _contains_sensitive_token(normalized_key),
        "resolution": resolutions.get(normalized_key),
    }
    if metadata["preview_restricted"]:
        return {
            **status,
            **metadata,
            "preview": REDIS_EXPLORER_RESTRICTED_PREVIEW,
            "preview_format": "text",
            "redacted": True,
            "truncated": False,
        }

    preview = _read_redis_value_preview(redis_client, normalized_key, key_type)
    return {
        **status,
        **metadata,
        **preview,
    }
