# test_cosmos_wave5a3_redis_monitoring.py
#!/usr/bin/env python3
"""
Functional test for Wave 5A3 Redis monitoring.
Version: 0.261.026
Implemented in: 0.250.026
Redis Explorer implemented in: 0.250.040
Redis Explorer DAI resolution implemented in: 0.250.043
Shared settings state compatibility fixed in: 0.261.026

This test ensures Redis monitoring reports sanitized health, memory, stats,
keyspace, DAI cache hygiene, runtime signals, and read-only Redis Explorer
previews without exposing Redis secrets.
"""

import fnmatch
import json
import os
import sys
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, "application", "single_app")
sys.path.insert(0, APP_DIR)

import app_settings_cache
import functions_redis_client
from app_settings_store import SETTINGS_STATE_KEY
from functions_redis_monitoring import (
    get_redis_explorer_keys,
    get_redis_explorer_value,
    get_redis_monitoring_status,
)


class FakeRedisClient:
    def __init__(self):
        self.items = {
            "simplechat:conversation_cache:user-1": {
                "type": "string",
                "value": json.dumps({
                    "conversation_id": "conversation-1",
                    "title": "Visible cache title",
                    "api_key": "secret-api-key",
                    "nested": {
                        "token": "secret-token",
                        "safe": "safe-value",
                    },
                }),
                "ttl": 120,
            },
            "simplechat:dai:list:user-1": {
                "type": "list",
                "value": ["document-a", "document-b"],
                "ttl": -1,
            },
            "DAI_LIST_CACHE:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {
                "type": "string",
                "value": json.dumps({"documents": [{"id": "document-a"}]}),
                "ttl": 900,
            },
            "DAI_LIST_CACHE_VERSION:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {
                "type": "string",
                "value": "23",
                "ttl": -1,
            },
            "flask_session:abc123": {
                "type": "string",
                "value": "session-cookie-secret",
                "ttl": 300,
            },
        }

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

    def scan(self, cursor=0, match="*", count=25):
        keys = [
            key
            for key in sorted(self.items)
            if fnmatch.fnmatch(key, match.replace("\\", ""))
        ]
        cursor_index = int(cursor or 0)
        next_index = min(cursor_index + int(count or 25), len(keys))
        next_cursor = 0 if next_index >= len(keys) else next_index
        return next_cursor, keys[cursor_index:next_index]

    def type(self, key):
        return self.items.get(key, {}).get("type", "none")

    def ttl(self, key):
        return self.items.get(key, {}).get("ttl", -2)

    def memory_usage(self, key):
        value = self.items.get(key, {}).get("value")
        return len(json.dumps(value))

    def get(self, key):
        return self.items.get(key, {}).get("value")

    def lrange(self, key, start, end):
        value = self.items.get(key, {}).get("value") or []
        return value[start:end + 1]

    def hscan(self, key, cursor=0, count=20):
        value = self.items.get(key, {}).get("value") or {}
        return 0, value

    def sscan(self, key, cursor=0, count=20):
        value = self.items.get(key, {}).get("value") or []
        return 0, value[:count]

    def zrange(self, key, start, end, withscores=False):
        value = self.items.get(key, {}).get("value") or []
        return value[start:end + 1]

    def xrange(self, key, min="-", max="+", count=20):
        value = self.items.get(key, {}).get("value") or []
        return value[:count]


class FakeRedisInfoFailure:
    def ping(self):
        return True

    def info(self):
        raise RuntimeError("secret-key-material")


def _fake_dai_hash_resolver(scope_hashes):
    """Return safe SimpleChat resolution metadata for test DAI version hashes."""
    return {
        scope_hash: {
            "kind": "document_access_index_version",
            "resolved": True,
            "resolution_status": "resolved",
            "label": "Document Access Index scope version",
            "cache_hash": scope_hash,
            "scope_key": "user:test-user",
            "entity_type": "user",
            "entity_id": "test-user",
            "entity_name": None,
            "entity_status": "active",
            "row_count": 2,
            "source_scopes": ["personal"],
            "access_roles": ["owner"],
            "note": "Resolved by functional test resolver.",
        }
        for scope_hash in scope_hashes
    }


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
        "service_type": "azure_cache_for_redis",
        "service_type_source": "detected",
        "port": 6380,
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
    assert status["dai_cache"]["payload_key_count"] == 1
    assert status["dai_cache"]["version_marker_count"] == 1
    assert status["dai_cache"]["version_marker_no_expiry_count"] == 1
    assert status["dai_cache"]["version_marker_ttl_seconds"] == 3600

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


def test_redis_explorer_lists_keys_with_safe_metadata():
    """Validate Redis Explorer uses paged SCAN output and safe key metadata."""
    previous_runtime_flag = app_settings_cache.app_cache_is_using_redis
    try:
        app_settings_cache.app_cache_is_using_redis = True
        page = get_redis_explorer_keys(
            {
                "enable_redis_cache": True,
                "redis_url": "example.redis.cache.windows.net",
                "redis_key": "do-not-expose",
            },
            app_cache_client=FakeRedisClient(),
            key_filter="simplechat",
            page_size=1,
        )
    finally:
        app_settings_cache.app_cache_is_using_redis = previous_runtime_flag

    serialized_page = json.dumps(page)
    assert page["success"] is True
    assert page["page_size"] == 1
    assert len(page["keys"]) == 1
    assert page["has_more"] is True
    assert page["keys"][0]["key"].startswith("simplechat:")
    assert "do-not-expose" not in serialized_page
    assert "example.redis.cache.windows.net" not in serialized_page


def test_redis_explorer_resolves_dai_version_marker_metadata():
    """Validate Redis Explorer resolves DAI marker hashes to safe entity metadata."""
    previous_runtime_flag = app_settings_cache.app_cache_is_using_redis
    try:
        app_settings_cache.app_cache_is_using_redis = True
        page = get_redis_explorer_keys(
            {
                "enable_redis_cache": True,
                "redis_url": "example.redis.cache.windows.net",
                "redis_key": "do-not-expose",
            },
            app_cache_client=FakeRedisClient(),
            key_filter="DAI_LIST_CACHE_VERSION",
            page_size=10,
            dai_hash_resolver=_fake_dai_hash_resolver,
        )
        preview = get_redis_explorer_value(
            {
                "enable_redis_cache": True,
                "redis_url": "example.redis.cache.windows.net",
                "redis_key": "do-not-expose",
            },
            key="DAI_LIST_CACHE_VERSION:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            app_cache_client=FakeRedisClient(),
            dai_hash_resolver=_fake_dai_hash_resolver,
        )
    finally:
        app_settings_cache.app_cache_is_using_redis = previous_runtime_flag

    serialized_payload = json.dumps({"page": page, "preview": preview})
    assert page["success"] is True
    assert len(page["keys"]) == 1
    assert page["keys"][0]["resolution"]["resolved"] is True
    assert page["keys"][0]["resolution"]["scope_key"] == "user:test-user"
    assert preview["success"] is True
    assert preview["resolution"]["entity_type"] == "user"
    assert preview["resolution"]["row_count"] == 2
    assert "do-not-expose" not in serialized_payload
    assert "example.redis.cache.windows.net" not in serialized_payload


def test_redis_explorer_value_sanitizes_json_preview():
    """Validate Redis Explorer redacts sensitive JSON fields in previews."""
    previous_runtime_flag = app_settings_cache.app_cache_is_using_redis
    try:
        app_settings_cache.app_cache_is_using_redis = True
        preview = get_redis_explorer_value(
            {
                "enable_redis_cache": True,
                "redis_url": "example.redis.cache.windows.net",
                "redis_key": "do-not-expose",
            },
            key="simplechat:conversation_cache:user-1",
            app_cache_client=FakeRedisClient(),
        )
    finally:
        app_settings_cache.app_cache_is_using_redis = previous_runtime_flag

    serialized_preview = json.dumps(preview)
    assert preview["success"] is True
    assert preview["type"] == "string"
    assert preview["preview_format"] == "json"
    assert preview["redacted"] is True
    assert "Visible cache title" in preview["preview"]
    assert "safe-value" in preview["preview"]
    assert "secret-api-key" not in serialized_preview
    assert "secret-token" not in serialized_preview
    assert "do-not-expose" not in serialized_preview
    assert "example.redis.cache.windows.net" not in serialized_preview


def test_redis_explorer_restricts_session_key_preview():
    """Validate sensitive key names return restricted previews."""
    previous_runtime_flag = app_settings_cache.app_cache_is_using_redis
    try:
        app_settings_cache.app_cache_is_using_redis = True
        preview = get_redis_explorer_value(
            {
                "enable_redis_cache": True,
                "redis_url": "example.redis.cache.windows.net",
            },
            key="flask_session:abc123",
            app_cache_client=FakeRedisClient(),
        )
    finally:
        app_settings_cache.app_cache_is_using_redis = previous_runtime_flag

    serialized_preview = json.dumps(preview)
    assert preview["success"] is True
    assert preview["preview_restricted"] is True
    assert preview["redacted"] is True
    assert "Preview restricted" in preview["preview"]
    assert "session-cookie-secret" not in serialized_preview


def test_redis_explorer_resolves_shared_and_legacy_settings_keys():
    """Use the real cache module, which no longer exports legacy settings constants."""
    client = FakeRedisClient()
    settings = {"enable_redis_cache": True, "redis_url": "example.redis.cache.windows.net"}
    expected_kinds = {
        SETTINGS_STATE_KEY: "app_settings_state",
        "APP_SETTINGS_CACHE": "app_settings_cache",
        "APP_SETTINGS_CACHE_VERSION": "app_settings_cache_version",
    }
    for key in expected_kinds:
        client.items[key] = {"type": "string", "value": "{}", "ttl": -1}

    page = get_redis_explorer_keys(
        settings,
        app_cache_client=client,
        key_filter="APP_SETTINGS",
        dai_hash_resolver=_fake_dai_hash_resolver,
    )
    assert page["success"] is True
    assert {item["key"]: item["resolution"]["kind"] for item in page["keys"]} == expected_kinds
    for key, kind in expected_kinds.items():
        preview = get_redis_explorer_value(settings, key=key, app_cache_client=client)
        assert preview["success"] is True
        assert preview["resolution"]["kind"] == kind
        if key != SETTINGS_STATE_KEY:
            assert "Legacy" in preview["resolution"]["label"]


def test_redis_explorer_shared_state_previews_redact_credentials():
    """Both ready and pending records must hide the Cosmos session token."""
    client = FakeRedisClient()
    settings = {"enable_redis_cache": True, "redis_url": "example.redis.cache.windows.net"}
    for state in ("ready", "pending"):
        payload = {
            "state": state,
            "session_token": "private-cosmos-session-value",
        }
        if state == "ready":
            payload["document"] = {
                "app_title": "Visible application title",
                "_settings_revision": 12,
                "redis_key": "private-redis-key",
                "azure_openai_gpt_key": "private-model-key",
                "nested": {"client_secret": "private-client-secret"},
            }
        else:
            payload["owner"] = "write-owner"
            payload["deadline"] = 1000
        client.items[SETTINGS_STATE_KEY] = {
            "type": "string",
            "value": json.dumps(payload),
            "ttl": -1,
        }
        preview = get_redis_explorer_value(settings, key=SETTINGS_STATE_KEY, app_cache_client=client)
        assert preview["success"] is True
        assert preview["redacted"] is True
        decoded = json.loads(preview["preview"])
        assert decoded["state"] == state
        assert decoded["session_token"] == "[REDACTED]"
        if state == "ready":
            assert decoded["document"]["app_title"] == "Visible application title"
        for secret in (
            "private-cosmos-session-value",
            "private-redis-key",
            "private-model-key",
            "private-client-secret",
        ):
            assert secret not in json.dumps(preview)


def test_redis_explorer_client_factory_works_for_both_azure_services():
    """Exercise real service/port routing and Explorer with fake Redis I/O only."""
    services = (
        ("example.redis.cache.windows.net", "azure_cache_for_redis", 6380),
        ("example.eastus.redis.azure.net", "azure_managed_redis", 10000),
    )
    credential_provider = object()

    class ExplorerRedisClient(FakeRedisClient):
        def __init__(self, **kwargs):
            super().__init__()
            self.connection_options = kwargs
            self.items[SETTINGS_STATE_KEY] = {
                "type": "string",
                "value": json.dumps({
                    "state": "ready",
                    "document": {"app_title": "Shared settings", "redis_key": "private-settings-key"},
                    "session_token": "private-cosmos-token",
                }),
                "ttl": -1,
            }

        def info(self):
            info = super().info()
            if self.connection_options["port"] == 10000:
                # Enterprise INFO can omit counters; Explorer must not depend on them.
                for key in ("maxclients", "tracking_clients", "total_error_replies", "db0"):
                    info.pop(key, None)
            return info

    for hostname, service_type, port in services:
        for auth_type in ("key", "managed_identity"):
            settings = {
                "enable_redis_cache": True,
                "redis_url": hostname,
                "redis_auth_type": auth_type,
                "redis_key": "private-connection-key",
            }
            with (
                patch.object(functions_redis_client, "Redis", ExplorerRedisClient),
                patch.object(functions_redis_client, "get_redis_credential_provider", return_value=credential_provider),
            ):
                client = functions_redis_client.create_redis_client(settings=settings)
            assert client.connection_options["host"] == hostname
            assert client.connection_options["port"] == port
            assert client.connection_options["ssl"] is True
            assert client.connection_options["db"] == 0
            if auth_type == "managed_identity":
                assert client.connection_options["credential_provider"] is credential_provider
                assert "password" not in client.connection_options
            else:
                assert client.connection_options["password"] == "private-connection-key"

            for source in ("app_cache", "session"):
                client_args = (
                    {"app_cache_client": client}
                    if source == "app_cache"
                    else {"session_redis_client": client, "session_type": "redis"}
                )
                with patch.object(app_settings_cache, "get_app_cache_redis_client", return_value=None):
                    status = get_redis_monitoring_status(settings, **client_args)
                    assert status["health"]["status"] == "healthy"
                    assert status["configuration"]["service_type"] == service_type
                    assert status["configuration"]["port"] == port
                    assert status["runtime"]["monitoring_source"] == source
                    seen_keys = []
                    cursor = 0
                    while True:
                        page = get_redis_explorer_keys(
                            settings,
                            cursor=cursor,
                            page_size=2,
                            dai_hash_resolver=_fake_dai_hash_resolver,
                            **client_args,
                        )
                        assert page["success"] is True
                        seen_keys.extend(item["key"] for item in page["keys"])
                        if not page["has_more"]:
                            break
                        cursor = page["next_cursor"]
                        assert len(seen_keys) <= len(client.items)
                    assert set(seen_keys) == set(client.items)
                    preview = get_redis_explorer_value(settings, key=SETTINGS_STATE_KEY, **client_args)
                    assert preview["success"] is True
                    assert preview["resolution"]["kind"] == "app_settings_state"
                    serialized = json.dumps(preview)
                    assert "Shared settings" in serialized
                    assert "private-settings-key" not in serialized
                    assert "private-cosmos-token" not in serialized
                    assert "private-connection-key" not in serialized
                    print(f"PASS: {service_type}, TLS {port}, {auth_type}, {source}")


if __name__ == "__main__":
    tests = [
        test_redis_monitoring_healthy_metrics,
        test_redis_monitoring_reports_runtime_unavailable,
        test_redis_monitoring_sanitizes_info_failures,
        test_redis_explorer_lists_keys_with_safe_metadata,
        test_redis_explorer_resolves_dai_version_marker_metadata,
        test_redis_explorer_value_sanitizes_json_preview,
        test_redis_explorer_restricts_session_key_preview,
        test_redis_explorer_resolves_shared_and_legacy_settings_keys,
        test_redis_explorer_shared_state_previews_redact_credentials,
        test_redis_explorer_client_factory_works_for_both_azure_services,
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
