# test_app_settings_cache_versioning.py
#!/usr/bin/env python3
"""
Functional test for shared app settings and governance cache versioning.
Version: 0.242.020
Implemented in: 0.242.020

This test ensures Redis deployments keep shared version keys and non-Redis
multi-worker deployments use Cosmos-backed version documents with bounded local
version-read TTLs for app settings and governance policy caches.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.append(SINGLE_APP_DIR)


def _read(*parts):
    path = os.path.join(ROOT_DIR, *parts)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_app_settings_cache_shared_version_contract():
    print("Testing app settings shared cache version contract...")

    cache_content = _read("application", "single_app", "app_settings_cache.py")
    settings_content = _read("application", "single_app", "functions_settings.py")

    for marker in [
        "APP_SETTINGS_CACHE_VERSION_KEY",
        "APP_SETTINGS_CACHE_VERSION_DOC_ID",
        "CACHE_VERSION_READ_TTL_SECONDS = 15",
        "get_app_settings_cache_version_redis",
        "bump_app_settings_cache_version_redis",
        "get_app_settings_cache_version_mem",
        "bump_app_settings_cache_version_mem",
        "cosmos_settings_container",
        "_get_ttl_cached_cosmos_version(",
        "APP_SETTINGS_SHARED_VERSION_CACHE",
    ]:
        assert marker in cache_content, f"Missing app settings cache version marker: {marker}"

    assert "bump_app_settings_cache_version" in settings_content, (
        "Expected app settings writes to bump shared app settings cache version"
    )
    assert "_refresh_app_settings_cache_after_write(merged, context=\"merge_upsert\")" in settings_content, (
        "Expected merge upsert path to refresh and version app settings cache"
    )
    assert "_refresh_app_settings_cache_after_write(settings_item, context=\"update_settings\")" in settings_content, (
        "Expected update_settings path to refresh and version app settings cache"
    )
    assert "before_version_bump" in settings_content and "after_version_bump" in settings_content, (
        "Expected cache refresh helper to write payload before and after version bump"
    )

    print("PASS: app settings shared cache version contract verified")


def test_governance_cache_cosmos_fallback_contract():
    print("Testing governance cache Cosmos fallback contract...")

    cache_content = _read("application", "single_app", "app_settings_cache.py")
    governance_content = _read("application", "single_app", "functions_governance.py")

    for marker in [
        "GOVERNANCE_CACHE_VERSION_KEY",
        "GOVERNANCE_CACHE_VERSION_DOC_ID",
        "APP_GOVERNANCE_SHARED_VERSION_CACHE",
        "get_governance_cache_version_redis",
        "bump_governance_cache_version_redis",
        "get_governance_cache_version_mem",
        "bump_governance_cache_version_mem",
        "cosmos_governance_policies_container",
    ]:
        assert marker in cache_content, f"Missing governance cache version marker: {marker}"

    for marker in [
        "_get_shared_governance_cache_version()",
        "_bump_shared_governance_cache_version()",
        "entry.get(\"version\") != current_version",
        "invalidate_governance_cache()",
    ]:
        assert marker in governance_content, f"Missing governance shared version usage marker: {marker}"

    print("PASS: governance Cosmos fallback cache version contract verified")


if __name__ == "__main__":
    tests = [
        test_app_settings_cache_shared_version_contract,
        test_governance_cache_cosmos_fallback_contract,
    ]
    results = []

    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__} -> {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
