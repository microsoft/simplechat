# test_chat_multi_endpoint_notice_template_fallback.py
# test_chat_multi_endpoint_notice_template_fallback.py
"""
Functional test for user-facing multi-endpoint migration notice suppression.
Version: 0.240.070
Implemented in: 0.240.070

This test ensures the migrated-endpoint notice is disabled in sanitized
settings used by user-facing routes and no longer renders on the chats page.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = REPO_ROOT / "application" / "single_app" / "functions_settings.py"
CHAT_ROUTE = REPO_ROOT / "application" / "single_app" / "route_frontend_chats.py"
CHAT_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
CHAT_ONLOAD_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-onload.js"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"


def test_user_sanitized_settings_disable_multi_endpoint_notice():
    """Verify user-facing sanitized settings always suppress the migration notice."""
    settings_content = SETTINGS_FILE.read_text(encoding="utf-8")

    assert "if isinstance(sanitized.get('multi_endpoint_migration_notice'), dict):" in settings_content, (
        "Expected sanitize_settings_for_user to override the migration notice for non-admin routes."
    )
    assert "'enabled': False," in settings_content, (
        "Expected sanitized multi-endpoint migration notices to be disabled for user-facing pages."
    )


def test_chat_multi_endpoint_notice_ui_removed():
    """Verify chat no longer renders or bootstraps the migration notice."""
    route_content = CHAT_ROUTE.read_text(encoding="utf-8")
    template_content = CHAT_TEMPLATE.read_text(encoding="utf-8")
    js_content = CHAT_ONLOAD_FILE.read_text(encoding="utf-8")

    assert 'multi_endpoint_notice = public_settings.get("multi_endpoint_migration_notice", {})' not in route_content, (
        "Expected chats route to stop loading the migration notice into the template context."
    )
    assert 'multi_endpoint_notice=multi_endpoint_notice,' not in route_content, (
        "Expected chats route to stop passing the migration notice into the template."
    )
    assert 'multi_endpoint_notice_data' not in template_content, (
        "Expected chats.html to remove the multi-endpoint notice bootstrap variable."
    )
    assert 'id="multi-endpoint-notice"' not in template_content, (
        "Expected chats.html to remove the multi-endpoint notice banner."
    )
    assert 'window.multiEndpointNotice =' not in template_content, (
        "Expected chats.html to stop bootstrapping the migration notice into JavaScript."
    )
    assert 'window.multiEndpointNotice' not in js_content, (
        "Expected chat-onload.js to stop reading the migration notice bootstrap payload."
    )
    assert 'multi-endpoint-notice' not in js_content, (
        "Expected chat-onload.js to remove notice DOM handling."
    )
    assert 'dismissedMultiEndpointNotice' not in js_content, (
        "Expected chat-onload.js to stop persisting notice dismissal state."
    )


def test_config_version_bumped_for_notice_suppression():
    """Verify config version was bumped for the user-facing notice removal."""
    config_content = CONFIG_FILE.read_text(encoding="utf-8")

    assert 'VERSION = "0.240.070"' in config_content, "Expected config.py version 0.240.070"


if __name__ == "__main__":
    test_user_sanitized_settings_disable_multi_endpoint_notice()
    test_chat_multi_endpoint_notice_ui_removed()
    test_config_version_bumped_for_notice_suppression()
    print("✅ User-facing multi-endpoint migration notice suppression verified.")
