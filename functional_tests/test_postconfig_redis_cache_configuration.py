#!/usr/bin/env python3
# test_postconfig_redis_cache_configuration.py
"""
Functional test for post-deployment Redis cache configuration.
Version: 0.261.023
Implemented in: 0.261.023

This test ensures the AZD post-deployment configuration script writes the Redis
cache settings that the application reads, so a deployed Azure Managed Redis
instance is actually used instead of silently falling back to filesystem
sessions and in-memory caching.
"""

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
POSTCONFIG = REPO_ROOT / "deployers" / "bicep" / "postconfig.py"
REDIS_CLIENT = REPO_ROOT / "application" / "single_app" / "functions_redis_client.py"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def require_not_contains(content: str, unexpected: str, description: str) -> None:
    if unexpected in content:
        raise AssertionError(f"Unexpected {description}: {unexpected}")


def test_postconfig_writes_redis_cache_settings() -> bool:
    print("🧪 Testing postconfig Redis cache configuration")
    print("=" * 70)

    content = POSTCONFIG.read_text(encoding="utf-8")

    require_not_contains(content, "todo support redis cache configuration", "unimplemented Redis configuration")

    for key in (
        "enable_redis_cache",
        "redis_url",
        "redis_auth_type",
        "redis_service_type",
        "redis_port",
        "redis_key",
    ):
        require_contains(content, f'item["{key}"]', f"Redis setting assignment for {key}")

    require_contains(content, 'if redis_cache_host_name:', "guard so an operator-configured cache is preserved")

    print("✅ postconfig writes every Redis setting the application reads")
    print("✅ postconfig only overwrites Redis settings when it provisioned a cache")
    return True


def test_service_type_identifiers_match_application() -> bool:
    """The deployer must emit the identifiers the application accepts.

    The Bicep parameter uses managed/classic while the application uses
    azure_managed_redis/azure_cache_for_redis, so a mismatch here would leave the
    port and TLS behavior resolving to the wrong Redis offering.
    """
    print("\n🧪 Testing Redis service type identifiers match the application")
    print("=" * 70)

    postconfig = POSTCONFIG.read_text(encoding="utf-8")
    client = REDIS_CLIENT.read_text(encoding="utf-8")

    supported = dict(
        re.findall(
            r"^(SERVICE_TYPE_[A-Z_]+)\s*=\s*'([a-z_]+)'",
            client,
            flags=re.MULTILINE,
        )
    )
    if not supported:
        raise AssertionError("Could not read SERVICE_TYPE constants from functions_redis_client.py")

    managed = supported.get("SERVICE_TYPE_AZURE_MANAGED_REDIS")
    classic = supported.get("SERVICE_TYPE_AZURE_CACHE_FOR_REDIS")
    if not managed or not classic:
        raise AssertionError(f"Missing expected SERVICE_TYPE constants, found: {sorted(supported)}")

    require_contains(postconfig, f'"{managed}"', "managed Redis service type identifier")
    require_contains(postconfig, f'"{classic}"', "classic Redis service type identifier")

    # The Bicep vocabulary must be translated rather than written through unchanged.
    assigned = re.search(
        r'item\["redis_service_type"\]\s*=\s*\((.*?)\)',
        postconfig,
        flags=re.DOTALL,
    )
    if not assigned:
        raise AssertionError("Could not locate the redis_service_type assignment")
    if '"managed"' not in assigned.group(1):
        raise AssertionError("redis_service_type assignment does not branch on the Bicep redisCacheKind value")

    print(f"✅ deployer emits '{managed}' and '{classic}'")
    print("✅ deployer translates the Bicep redisCacheKind vocabulary")
    return True


if __name__ == "__main__":
    tests = [
        test_postconfig_writes_redis_cache_settings,
        test_service_type_identifiers_match_application,
    ]
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f"❌ {test.__name__} failed: {exc}")
            results.append(False)

    print(f"\n📊 Results: {sum(1 for r in results if r)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
