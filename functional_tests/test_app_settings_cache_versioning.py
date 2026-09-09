# test_app_settings_cache_versioning.py
#!/usr/bin/env python3
"""
Functional test for shared app settings and governance cache versioning.
Version: 0.261.025
Implemented in: 0.242.020

Settings versions are now carried with the shared document. Governance caches
retain their separate version documents and bounded local version-read TTLs.
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
    store_content = _read("application", "single_app", "app_settings_store.py")

    for marker in [
        "get_settings_store",
        "get_app_settings_cache_version = _get_settings_revision",
        "cosmos_settings_container",
    ]:
        assert marker in cache_content, f"Missing app settings cache version marker: {marker}"

    assert "APP_SETTINGS_SHARED_VERSION_CACHE" not in cache_content
    assert "APP_SETTINGS_CACHE = " not in cache_content
    assert "store.write(normalize_loaded_settings)" in settings_content
    assert "write(apply_updates, expected_etag=expected_etag)" in settings_content
    assert 'candidate[SETTINGS_REVISION_FIELD]' in store_content
    assert '"document": dict(stored)' in store_content

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
