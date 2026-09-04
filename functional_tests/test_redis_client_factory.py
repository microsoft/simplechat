#!/usr/bin/env python3
"""
Functional test for the shared Redis client factory.
Version: 0.261.010
Implemented in: 0.261.010

This test ensures every Redis authentication mode builds a client with the correct host,
port, TLS setting, and credential for both Azure Cache for Redis and Azure Managed Redis.
It also pins two behaviors that protect a running deployment: db=0 (Azure Managed Redis
serves only one database, and redis-py emits SELECT for any non-zero index), and the
fallback to the in-repo credential provider when the redis-entraid package is absent, so
an application updated without reinstalling requirements still starts.
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
sys.path.insert(0, APP_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


class _CapturingRedis:
    """Stands in for redis.Redis so no network connection is attempted."""

    captured_kwargs = {}

    def __init__(self, **kwargs):
        _CapturingRedis.captured_kwargs = dict(kwargs)


def _build_client(settings, **kwargs):
    import functions_redis_client as redis_client

    original_redis = redis_client.Redis
    try:
        redis_client.Redis = _CapturingRedis
        redis_client.create_redis_client(settings=settings, **kwargs)
    finally:
        redis_client.Redis = original_redis
    return dict(_CapturingRedis.captured_kwargs)


def test_key_auth_uses_service_specific_port():
    """Access key auth must send the key and the port matching the detected service."""
    print("Testing key authentication client...")

    classic = _build_client({
        "redis_url": "simple-chat.redis.cache.windows.net",
        "redis_auth_type": "key",
        "redis_key": "classic-access-key",
    })
    assert classic["host"] == "simple-chat.redis.cache.windows.net"
    assert classic["port"] == 6380
    assert classic["ssl"] is True
    assert classic["db"] == 0
    assert classic["password"] == "classic-access-key"
    assert "credential_provider" not in classic

    managed = _build_client({
        "redis_url": "simple-chat.eastus.redis.azure.net",
        "redis_auth_type": "key",
        "redis_key": "managed-access-key",
    })
    assert managed["port"] == 10000
    assert managed["password"] == "managed-access-key"

    print("Test passed!")
    return True


def test_managed_identity_uses_credential_provider():
    """Managed identity auth must supply a credential provider instead of a password."""
    print("Testing managed identity client...")
    import functions_redis_client as redis_client

    redis_client.reset_redis_credential_provider_cache()
    captured = _build_client({
        "redis_url": "simple-chat.eastus.redis.azure.net",
        "redis_auth_type": "managed_identity",
    })

    assert captured["port"] == 10000
    assert captured["ssl"] is True
    assert captured["db"] == 0
    assert "password" not in captured
    assert captured["credential_provider"] is not None
    assert hasattr(captured["credential_provider"], "get_credentials")

    print("Test passed!")
    return True


def test_extra_kwargs_reach_the_client():
    """Timeouts passed by the session and cache call sites must not be dropped."""
    print("Testing kwargs passthrough...")

    captured = _build_client(
        {
            "redis_url": "simple-chat.redis.cache.windows.net",
            "redis_auth_type": "key",
            "redis_key": "access-key",
        },
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    assert captured["socket_connect_timeout"] == 5
    assert captured["socket_timeout"] == 5

    print("Test passed!")
    return True


def test_missing_configuration_raises_before_connecting():
    """Incomplete settings must fail fast rather than producing a broken client."""
    print("Testing configuration validation...")
    import functions_redis_client as redis_client

    for settings in (
        {"redis_url": "", "redis_auth_type": "key", "redis_key": "access-key"},
        {"redis_url": "simple-chat.redis.cache.windows.net", "redis_auth_type": "key", "redis_key": ""},
        {"redis_url": "simple-chat.redis.cache.windows.net", "redis_auth_type": "key_vault", "redis_key": ""},
    ):
        try:
            redis_client.create_redis_client(settings=settings)
        except ValueError:
            continue
        raise AssertionError(f"Expected ValueError for settings {settings!r}")

    print("Test passed!")
    return True


def test_credential_provider_falls_back_without_redis_entraid():
    """Losing redis-entraid must degrade to the in-repo provider, not crash startup."""
    print("Testing redis-entraid fallback...")
    import builtins

    import functions_redis_client as redis_client

    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name.startswith("redis_entraid"):
            raise ImportError("simulated missing redis_entraid")
        return real_import(name, *args, **kwargs)

    redis_client.reset_redis_credential_provider_cache()
    try:
        builtins.__import__ = blocked_import
        provider = redis_client.get_redis_credential_provider({})
    finally:
        builtins.__import__ = real_import
        redis_client.reset_redis_credential_provider_cache()

    assert isinstance(provider, redis_client.RedisManagedIdentityCredentialProvider)
    assert provider.scope == "https://redis.azure.com/.default"

    print("Test passed!")
    return True


def test_streaming_provider_is_shared_and_one_shot_is_not():
    """Each long-lived client needs its own refreshing provider; ad-hoc tests need none."""
    print("Testing credential provider caching...")
    import functions_redis_client as redis_client

    redis_client.reset_redis_credential_provider_cache()
    try:
        app_cache_provider = redis_client.get_redis_credential_provider(
            {}, purpose=redis_client.CREDENTIAL_PURPOSE_APP_CACHE
        )
        again = redis_client.get_redis_credential_provider(
            {}, purpose=redis_client.CREDENTIAL_PURPOSE_APP_CACHE
        )
        assert app_cache_provider is again, "A provider must be reused for the same purpose."

        # redis-entraid keeps a single re-authentication callback slot, so sharing one
        # provider between the app cache and session clients would leave the first client's
        # pooled connections without proactive re-AUTH.
        session_provider = redis_client.get_redis_credential_provider(
            {}, purpose=redis_client.CREDENTIAL_PURPOSE_SESSION
        )
        assert session_provider is not app_cache_provider, (
            "Session and app cache clients must not share one streaming provider."
        )

        # An ad-hoc connection test must not start a background refresh thread at all.
        one_shot = redis_client.get_redis_credential_provider({}, streaming=False)
        assert isinstance(one_shot, redis_client.RedisManagedIdentityCredentialProvider), (
            "Ad-hoc test connections must use the connect-time-only provider."
        )
        assert not hasattr(one_shot, "is_streaming")
    finally:
        redis_client.reset_redis_credential_provider_cache()

    print("Test passed!")
    return True


def test_session_and_app_cache_clients_get_distinct_providers():
    """The two long-lived clients must each own a credential provider instance."""
    print("Testing per-client credential providers...")
    import functions_redis_client as redis_client

    settings = {
        "redis_url": "simple-chat.eastus.redis.azure.net",
        "redis_auth_type": "managed_identity",
    }

    redis_client.reset_redis_credential_provider_cache()
    try:
        app_cache = _build_client(settings, credential_purpose=redis_client.CREDENTIAL_PURPOSE_APP_CACHE)
        session = _build_client(settings, credential_purpose=redis_client.CREDENTIAL_PURPOSE_SESSION)
        assert app_cache["credential_provider"] is not session["credential_provider"]
    finally:
        redis_client.reset_redis_credential_provider_cache()

    print("Test passed!")
    return True


def test_admin_connection_test_does_not_expose_credential_errors():
    """A failed Redis client build must not echo Key Vault or token details to the browser."""
    print("Testing admin connection test error hardening...")
    import re

    route_file = os.path.join(APP_DIR, "route_backend_settings.py")
    with open(route_file, "r", encoding="utf-8") as handle:
        source = handle.read()

    start = source.index("def _test_redis_connection(")
    end = source.index("def _test_embedding_connection(")
    body = source[start:end]

    construction_block = body[body.index("create_redis_client("):body.index("test_key_simplechat")]

    # Validation messages are our own and safe; credential resolution errors are not.
    assert "except ValueError" in construction_block, (
        "Validation errors should be surfaced separately from credential errors."
    )
    assert not re.search(r"jsonify\(\{\s*'error':\s*f'[^']*\{str\(client_error\)\}", construction_block), (
        "The client construction error must not be returned to the browser."
    )
    assert "[REDIS_TEST]" in construction_block, (
        "Credential errors must be logged for diagnosis instead of returned."
    )

    print("Test passed!")
    return True


def test_version_includes_managed_redis_support():
    """The running application must be at or beyond the implementation version."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.010")
    print("Test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_key_auth_uses_service_specific_port,
        test_managed_identity_uses_credential_provider,
        test_extra_kwargs_reach_the_client,
        test_missing_configuration_raises_before_connecting,
        test_credential_provider_falls_back_without_redis_entraid,
        test_streaming_provider_is_shared_and_one_shot_is_not,
        test_session_and_app_cache_clients_get_distinct_providers,
        test_admin_connection_test_does_not_expose_credential_errors,
        test_version_includes_managed_redis_support,
    ]
    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
