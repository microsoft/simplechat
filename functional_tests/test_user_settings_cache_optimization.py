# test_user_settings_cache_optimization.py
#!/usr/bin/env python3
"""
Functional test for user settings cache optimization.
Version: 0.242.044
Implemented in: 0.242.044

This test ensures user settings reads use request-scoped caching, shared UI settings
caches support Redis and no-Redis deployments, and frontend scripts reuse injected
user UI settings before fetching the full user settings document.
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


def test_user_settings_request_cache_contract():
    """Validate full user settings reads use request-scoped memoization."""
    print("Testing user settings request cache contract...")

    settings_content = _read("application", "single_app", "functions_settings.py")

    for marker in [
        "USER_SETTINGS_REQUEST_CACHE_ATTR",
        "_get_user_settings_request_cache()",
        "_get_request_cached_user_settings(user_id)",
        "_set_request_cached_user_settings(user_id, doc)",
        "_delete_request_cached_user_settings(user_id)",
        "return _clone_user_settings_doc(doc)",
    ]:
        assert marker in settings_content, f"Missing request cache marker: {marker}"

    assert "cached_doc = _get_request_cached_user_settings(user_id)" in settings_content, (
        "Expected get_user_settings to check the request cache before Cosmos"
    )

    print("PASS: user settings request cache contract verified")


def test_user_ui_settings_cache_contract():
    """Validate UI settings cache supports Redis and process-local fallback."""
    print("Testing user UI settings cache contract...")

    cache_content = _read("application", "single_app", "app_settings_cache.py")
    settings_content = _read("application", "single_app", "functions_settings.py")

    for marker in [
        "APP_USER_UI_SETTINGS_CACHE",
        "USER_UI_SETTINGS_CACHE_KEY_PREFIX",
        "USER_UI_SETTINGS_CACHE_TTL_SECONDS = 120",
        "get_user_ui_settings_cache_redis",
        "set_user_ui_settings_cache_redis",
        "delete_user_ui_settings_cache_redis",
        "get_user_ui_settings_cache_mem",
        "set_user_ui_settings_cache_mem",
        "delete_user_ui_settings_cache_mem",
    ]:
        assert marker in cache_content, f"Missing user UI cache marker: {marker}"

    for marker in [
        "USER_UI_SETTINGS_KEYS",
        "def get_user_ui_settings(user_id, allow_cross_user=False):",
        "_extract_user_ui_settings(doc)",
        "invalidate_user_settings_caches(user_id)",
        "_delete_user_ui_settings_cache(user_id)",
    ]:
        assert marker in settings_content, f"Missing user UI settings marker: {marker}"

    assert "APP_SETTINGS_CACHE_VERSION_DOC_ID" in cache_content, "Expected existing app settings versioning to remain"
    assert "USER_UI_SETTINGS_CACHE_VERSION_DOC_ID" not in cache_content, (
        "User UI settings cache should not add per-user Cosmos version documents"
    )

    print("PASS: user UI settings cache contract verified")


def test_user_settings_write_invalidation_contract():
    """Validate user settings writes invalidate lightweight UI caches."""
    print("Testing user settings write invalidation contract...")

    settings_content = _read("application", "single_app", "functions_settings.py")
    retention_content = _read("application", "single_app", "route_backend_retention_policy.py")

    assert "_set_request_cached_user_settings(user_id, doc)" in settings_content, (
        "Expected update_user_settings to refresh request cache after writes"
    )
    assert "_delete_user_ui_settings_cache(user_id)" in settings_content, (
        "Expected update_user_settings to clear UI cache after writes"
    )
    assert settings_content.count("invalidate_user_settings_caches(user_id)") >= 2, (
        "Expected direct search-history upserts to invalidate user settings caches"
    )
    assert "invalidate_user_settings_caches(user_id)" in retention_content, (
        "Expected retention force-push direct upserts to invalidate user settings caches"
    )

    print("PASS: user settings write invalidation contract verified")


def test_frontend_reuses_injected_user_ui_settings():
    """Validate shared scripts use injected UI settings before API fallback."""
    print("Testing frontend injected user UI settings reuse...")

    base_content = _read("application", "single_app", "templates", "base.html")
    dark_mode_content = _read("application", "single_app", "static", "js", "dark-mode.js")
    sidebar_content = _read("application", "single_app", "static", "js", "sidebar.js")

    assert "window.simplechatUserSettings" in base_content, (
        "Expected base template to expose lightweight user UI settings to scripts"
    )
    assert "getInjectedUserSettings()" in dark_mode_content, (
        "Expected dark mode script to read injected user settings"
    )
    assert "if (!(USER_SETTINGS_KEY_DARK_MODE in settings))" in dark_mode_content, (
        "Expected dark mode script to fetch full settings only when injected data is missing"
    )
    assert "window.simplechatUserSettings && typeof window.simplechatUserSettings === 'object'" in sidebar_content, (
        "Expected sidebar script to reuse injected user settings before API fallback"
    )

    print("PASS: frontend injected user UI settings reuse verified")


if __name__ == "__main__":
    tests = [
        test_user_settings_request_cache_contract,
        test_user_ui_settings_cache_contract,
        test_user_settings_write_invalidation_contract,
        test_frontend_reuses_injected_user_ui_settings,
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
