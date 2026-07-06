#!/usr/bin/env python3
# test_cosmos_wave5a3_redis_monitoring.py
"""
Functional test for Wave 5A3 Redis monitoring.
Version: 0.250.026
Implemented in: 0.250.026

This test ensures Redis monitoring reports sanitized health, memory, stats,
keyspace, and runtime signals without exposing Redis secrets.
"""

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, "application", "single_app")
sys.path.insert(0, APP_DIR)

import app_settings_cache
from functions_redis_monitoring import get_redis_monitoring_status


class FakeRedisClient:
    def ping(self):
        return True

    def info(self):
        return {
            "redis_version": "7.2.4",
            "uptime_in_seconds": 3600,
            "uptime_in_days": 0,
            "connected_clients": 12,
            "blocked_clients": 0,
            "tracking_clients": 1,
            "maxclients": 1000,
            "used_memory": 1024,
            "used_memory_human": "1.00K",
            "maxmemory": 4096,
            "maxmemory_human": "4.00K",
            "maxmemory_policy": "allkeys-lru",
            "mem_fragmentation_ratio": "1.15",
            "total_connections_received": 42,
            "total_commands_processed": 500,
            "instantaneous_ops_per_sec": 9,
            "keyspace_hits": 80,
            "keyspace_misses": 20,
            "expired_keys": 3,
            "evicted_keys": 1,
            "rejected_connections": 0,
            "total_error_replies": 2,
            "db0": {"keys": 17, "expires": 5, "avg_ttl": 30000},
        }


class FakeRedisInfoFailure:
    def ping(self):
        return True

    def info(self):
        raise RuntimeError("secret-key-material")


def test_redis_monitoring_healthy_metrics():
    """Validate healthy Redis monitoring metrics and sanitized payload shape."""
    previous_runtime_flag = app_settings_cache.app_cache_is_using_redis
    try:
        app_settings_cache.app_cache_is_using_redis = True
        status = get_redis_monitoring_status(
            {
                "enable_redis_cache": True,
                "redis_url": "example.redis.cache.windows.net",
                "redis_auth_type": "managed_identity",
                "redis_key": "do-not-expose",
            },
            app_cache_client=FakeRedisClient(),
            session_type="filesystem",
            now_func=lambda: "2026-07-03T00:00:00Z",
        )
    finally:
        app_settings_cache.app_cache_is_using_redis = previous_runtime_flag

    assert status["checked_at"] == "2026-07-03T00:00:00Z"
    assert status["configuration"] == {
        "enabled": True,
        "configured": True,
        "auth_type": "managed_identity",
    }
    assert status["runtime"]["app_cache_using_redis"] is True
    assert status["runtime"]["monitoring_source"] == "app_cache"
    assert status["health"]["status"] == "healthy"
    assert status["health"]["ping_success"] is True
    assert status["health"]["ping_latency_ms"] is not None
    assert status["memory"]["usage_percent"] == 25.0
    assert status["stats"]["keyspace_hit_rate_percent"] == 80.0
    assert status["keyspace"]["total_keys"] == 17
    assert status["keyspace"]["expiring_keys"] == 5

    serialized_status = json.dumps(status)
    assert "do-not-expose" not in serialized_status
    assert "example.redis.cache.windows.net" not in serialized_status


def test_redis_monitoring_reports_runtime_unavailable():
    """Validate enabled Redis without an active client reports an actionable status."""
    status = get_redis_monitoring_status(
        {
            "enable_redis_cache": True,
            "redis_url": "example.redis.cache.windows.net",
            "redis_auth_type": "key",
            "redis_key": "do-not-expose",
        },
        app_cache_client=None,
        session_redis_client=None,
        session_type="filesystem",
        now_func=lambda: "2026-07-03T00:00:00Z",
    )

    assert status["health"]["status"] == "unavailable"
    assert status["runtime"]["client_available"] is False
    assert status["health"]["last_error"] == "Redis is configured, but no active runtime Redis client is available."
    assert "do-not-expose" not in json.dumps(status)


def test_redis_monitoring_sanitizes_info_failures():
    """Validate Redis INFO failures are surfaced without raw exception text."""
    status = get_redis_monitoring_status(
        {
            "enable_redis_cache": True,
            "redis_url": "example.redis.cache.windows.net",
            "redis_auth_type": "key",
            "redis_key": "do-not-expose",
        },
        app_cache_client=FakeRedisInfoFailure(),
        now_func=lambda: "2026-07-03T00:00:00Z",
    )

    assert status["health"]["status"] == "degraded"
    assert status["health"]["ping_success"] is True
    assert status["health"]["last_error"] == "Redis INFO metrics failed (RuntimeError)."
    serialized_status = json.dumps(status)
    assert "secret-key-material" not in serialized_status
    assert "do-not-expose" not in serialized_status


if __name__ == "__main__":
    tests = [
        test_redis_monitoring_healthy_metrics,
        test_redis_monitoring_reports_runtime_unavailable,
        test_redis_monitoring_sanitizes_info_failures,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
