# functions_redis_monitoring.py

from datetime import datetime, timezone
import time

import app_settings_cache


REDIS_MONITORING_STATUS_DISABLED = "disabled"
REDIS_MONITORING_STATUS_NOT_CONFIGURED = "not_configured"
REDIS_MONITORING_STATUS_UNAVAILABLE = "unavailable"
REDIS_MONITORING_STATUS_HEALTHY = "healthy"
REDIS_MONITORING_STATUS_DEGRADED = "degraded"
REDIS_MONITORING_STATUS_ERROR = "error"


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
    status["health"]["status"] = (
        REDIS_MONITORING_STATUS_HEALTHY
        if status["health"]["ping_success"]
        else REDIS_MONITORING_STATUS_DEGRADED
    )
    return status
