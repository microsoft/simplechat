#!/usr/bin/env python3
"""
Functional test for Redis Microsoft Entra token authentication wiring.
Version: 0.242.070
Implemented in: 0.242.070

This test ensures Redis managed identity authentication uses the documented
Redis token scope and supplies the managed identity object ID as the Redis ACL
username.
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


def test_redis_credential_provider_uses_oid_username_and_scope():
    """Validate Redis Entra credentials include username and token."""
    import app_settings_cache

    token = _make_token({"oid": "00000000-1111-2222-3333-444444444444"})
    credential = FakeCredential(token)

    provider = app_settings_cache.RedisManagedIdentityCredentialProvider(
        credential=credential,
        scope="https://redis.azure.com/.default",
    )

    username, password = provider.get_credentials()

    assert username == "00000000-1111-2222-3333-444444444444"
    assert password == token
    assert credential.scopes == ["https://redis.azure.com/.default"]


def test_create_redis_managed_identity_client_uses_credential_provider():
    """Validate Redis client construction passes a credential provider."""
    import app_settings_cache

    original_redis = app_settings_cache.Redis
    captured_kwargs = {}

    class FakeRedis:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    try:
        app_settings_cache.Redis = FakeRedis
        app_settings_cache.create_redis_managed_identity_client(
            "example.redis.cache.usgovcloudapi.net",
            settings={"redis_entra_token_scope": "https://redis.azure.com/.default"},
            socket_timeout=5,
        )
    finally:
        app_settings_cache.Redis = original_redis

    assert captured_kwargs["host"] == "example.redis.cache.usgovcloudapi.net"
    assert captured_kwargs["port"] == 6380
    assert captured_kwargs["ssl"] is True
    assert captured_kwargs["socket_timeout"] == 5
    assert isinstance(
        captured_kwargs["credential_provider"],
        app_settings_cache.RedisManagedIdentityCredentialProvider,
    )


if __name__ == "__main__":
    tests = [
        test_redis_credential_provider_uses_oid_username_and_scope,
        test_create_redis_managed_identity_client_uses_credential_provider,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    passed = sum(results)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
