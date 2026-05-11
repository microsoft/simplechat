# test_chat_multi_endpoint_notice_template_fallback.py
# test_chat_multi_endpoint_notice_template_fallback.py
"""
Functional test for obsolete multi-endpoint notice removal.
Version: 0.240.073
Implemented in: 0.240.072

This test ensures the obsolete migrated-endpoint notice is no longer rendered
or bootstrapped in chat and admin UIs, and its old message is removed from the
admin settings flow.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = REPO_ROOT / "application" / "single_app" / "functions_settings.py"
ADMIN_ROUTE = REPO_ROOT / "application" / "single_app" / "route_frontend_admin_settings.py"
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
ADMIN_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_model_endpoints.js"
CHAT_ROUTE = REPO_ROOT / "application" / "single_app" / "route_frontend_chats.py"
CHAT_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
CHAT_ONLOAD_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-onload.js"
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
OBSOLETE_NOTICE = (
    "Multi-endpoint has been enabled and your existing AI endpoint was migrated. "
    "Agents using the default connection may need to be updated to select a new model endpoint."
)


def test_user_sanitized_settings_disable_multi_endpoint_notice():
    """Verify user-facing sanitized settings always suppress the migration notice."""
    settings_content = SETTINGS_FILE.read_text(encoding="utf-8")

    assert "if isinstance(sanitized.get('multi_endpoint_migration_notice'), dict):" in settings_content, (
        "Expected sanitize_settings_for_user to override the migration notice for non-admin routes."
    )
    assert "'enabled': False," in settings_content, (
        "Expected sanitized multi-endpoint migration notices to be disabled for user-facing pages."
    )


def test_obsolete_notice_removed_from_admin_flow():
    """Verify the obsolete migration notice text is not defined or rendered in admin settings."""
    settings_content = SETTINGS_FILE.read_text(encoding="utf-8")
    admin_route_content = ADMIN_ROUTE.read_text(encoding="utf-8")
    admin_template_content = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    admin_js_content = ADMIN_JS.read_text(encoding="utf-8")

    assert OBSOLETE_NOTICE not in settings_content, (
        "Expected functions_settings.py to stop defining the obsolete migration notice text."
    )
    assert OBSOLETE_NOTICE not in admin_route_content, (
        "Expected route_frontend_admin_settings.py to stop defining the obsolete migration notice text."
    )
    assert 'id="multi-endpoint-warning"' not in admin_template_content, (
        "Expected admin_settings.html to remove the obsolete migration warning banner."
    )
    assert 'window.multiEndpointMigrationNotice =' not in admin_template_content, (
        "Expected admin_settings.html to stop bootstrapping the obsolete migration notice."
    )
    assert 'window.multiEndpointMigrationNotice' not in admin_js_content, (
        "Expected admin_model_endpoints.js to stop reading obsolete migration notice state."
    )
    assert 'const migrationWarning = document.getElementById("multi-endpoint-warning");' not in admin_js_content, (
        "Expected admin_model_endpoints.js to remove the obsolete migration warning DOM hook."
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

    assert 'VERSION = "0.240.073"' in config_content, "Expected config.py version 0.240.073"


if __name__ == "__main__":
    test_user_sanitized_settings_disable_multi_endpoint_notice()
    test_obsolete_notice_removed_from_admin_flow()
    test_chat_multi_endpoint_notice_ui_removed()
    test_config_version_bumped_for_notice_suppression()
    print("✅ Obsolete multi-endpoint migration notice removal verified.")
