#!/usr/bin/env python3
"""
Functional test for Redis Microsoft Entra token authentication wiring.
Version: 0.261.010
Implemented in: 0.242.070
Updated in: 0.261.010 for Azure Managed Redis support.

This test ensures Redis managed identity authentication uses the documented Redis token
scope and supplies the managed identity object ID as the Redis ACL username, for both
Azure Cache for Redis and Azure Managed Redis. It also covers the redis-entraid streaming
provider, which re-issues AUTH on pooled connections before the Entra token expires, and
the sovereign-cloud authority that Azure Government deployments depend on.
"""

import base64
import json
import os
import sys
import time
from types import SimpleNamespace

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
sys.path.insert(0, APP_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _make_token(claims):
    header = {"alg": "none", "typ": "JWT"}

    def encode_part(value):
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    return f"{encode_part(header)}.{encode_part(claims)}."


class FakeCredential:
    def __init__(self, token):
        self.token = token
        self.scopes = []

    def get_token(self, scope):
        self.scopes.append(scope)
        return SimpleNamespace(token=self.token, expires_on=int(time.time()) + 3600)


class _CapturingRedis:
    captured_kwargs = {}

    def __init__(self, **kwargs):
        _CapturingRedis.captured_kwargs = dict(kwargs)


def test_redis_credential_provider_uses_oid_username_and_scope():
    """Validate Redis Entra credentials include the object ID username and token."""
    print("Testing Entra credential provider claims...")
    import functions_redis_client as redis_client

    token = _make_token({"oid": "00000000-1111-2222-3333-444444444444"})
    credential = FakeCredential(token)

    provider = redis_client.RedisManagedIdentityCredentialProvider(
        credential=credential,
        scope="https://redis.azure.com/.default",
    )

    username, password = provider.get_credentials()

    assert username == "00000000-1111-2222-3333-444444444444"
    assert password == token
    assert credential.scopes == ["https://redis.azure.com/.default"]

    print("Test passed!")
    return True


def test_credential_provider_is_reexported_from_app_settings_cache():
    """Existing imports of the provider through app_settings_cache must keep working."""
    print("Testing app_settings_cache re-export...")
    import app_settings_cache
    import functions_redis_client as redis_client

    assert (
        app_settings_cache.RedisManagedIdentityCredentialProvider
        is redis_client.RedisManagedIdentityCredentialProvider
    )
    assert app_settings_cache.REDIS_ENTRA_TOKEN_SCOPE == "https://redis.azure.com/.default"

    print("Test passed!")
    return True


def test_create_redis_managed_identity_client_uses_credential_provider():
    """Validate Redis client construction passes a credential provider on both services."""
    print("Testing managed identity client construction...")
    import app_settings_cache
    import functions_redis_client as redis_client

    original_redis = redis_client.Redis
    try:
        redis_client.Redis = _CapturingRedis

        app_settings_cache.create_redis_managed_identity_client(
            "example.redis.cache.usgovcloudapi.net",
            settings={"redis_entra_token_scope": "https://redis.azure.com/.default"},
            socket_timeout=5,
        )
        classic = dict(_CapturingRedis.captured_kwargs)

        app_settings_cache.create_redis_managed_identity_client(
            "example.eastus.redis.azure.net",
            settings={"redis_entra_token_scope": "https://redis.azure.com/.default"},
            socket_timeout=5,
        )
        managed = dict(_CapturingRedis.captured_kwargs)
    finally:
        redis_client.Redis = original_redis

    assert classic["host"] == "example.redis.cache.usgovcloudapi.net"
    assert classic["port"] == 6380
    assert classic["ssl"] is True
    assert classic["socket_timeout"] == 5
    assert hasattr(classic["credential_provider"], "get_credentials")

    assert managed["host"] == "example.eastus.redis.azure.net"
    assert managed["port"] == 10000
    assert managed["ssl"] is True
    assert hasattr(managed["credential_provider"], "get_credentials")

    print("Test passed!")
    return True


def test_streaming_provider_refreshes_tokens_when_available():
    """redis-entraid supplies a streaming provider so pooled connections re-AUTH."""
    print("Testing streaming credential provider...")
    import functions_redis_client as redis_client

    try:
        from redis_entraid.cred_provider import EntraIdCredentialsProvider
    except ImportError:
        print("Skipped: redis-entraid is not installed in this environment.")
        return True

    redis_client.reset_redis_credential_provider_cache()
    try:
        provider = redis_client.get_redis_credential_provider({})
        assert isinstance(provider, EntraIdCredentialsProvider)
        # A streaming provider is what lets redis-py re-authenticate an already open
        # connection before the Entra token expires.
        assert hasattr(provider, "is_streaming")
    finally:
        redis_client.reset_redis_credential_provider_cache()

    print("Test passed!")
    return True


def test_sovereign_cloud_authority_is_passed_to_the_provider():
    """Azure Government tokens must come from the government authority host."""
    print("Testing sovereign cloud authority...")
    import functions_redis_client as redis_client

    captured = {}

    def fake_provider_builder(scope, authority_host):
        captured["scope"] = scope
        captured["authority"] = authority_host
        return "provider-sentinel"

    original_builder = redis_client._build_streaming_credential_provider
    original_authority = redis_client.get_entra_authority
    redis_client.reset_redis_credential_provider_cache()
    try:
        redis_client._build_streaming_credential_provider = fake_provider_builder
        redis_client.get_entra_authority = lambda: "login.microsoftonline.us"
        provider = redis_client.get_redis_credential_provider({})
    finally:
        redis_client._build_streaming_credential_provider = original_builder
        redis_client.get_entra_authority = original_authority
        redis_client.reset_redis_credential_provider_cache()

    assert provider == "provider-sentinel"
    assert captured["authority"] == "login.microsoftonline.us"
    assert captured["scope"] == "https://redis.azure.com/.default"

    print("Test passed!")
    return True


def test_custom_token_scope_is_honored():
    """A configured Redis token scope must override the documented default."""
    print("Testing custom token scope...")
    import functions_redis_client as redis_client

    assert redis_client.get_redis_entra_token_scope({}) == "https://redis.azure.com/.default"
    assert (
        redis_client.get_redis_entra_token_scope(
            {"redis_entra_token_scope": "https://redis.example.test/.default"}
        )
        == "https://redis.example.test/.default"
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
        test_redis_credential_provider_uses_oid_username_and_scope,
        test_credential_provider_is_reexported_from_app_settings_cache,
        test_create_redis_managed_identity_client_uses_credential_provider,
        test_streaming_provider_refreshes_tokens_when_available,
        test_sovereign_cloud_authority_is_passed_to_the_provider,
        test_custom_token_scope_is_honored,
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
