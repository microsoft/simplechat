# test_desktop_notification_settings.py
"""
Functional test for desktop conversation notification settings.
Version: 0.250.102
Implemented in: 0.250.102

This test ensures the administrator gate, per-user preference, sanitized chat
bootstrap values, and successful stream completion hook remain connected.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_desktop_notification_settings_are_wired_end_to_end():
    """Verify the global and user settings are connected to Chat."""
    functions_settings = _read("application/single_app/functions_settings.py")
    admin_route = _read("application/single_app/route_frontend_admin_settings.py")
    user_route = _read("application/single_app/route_backend_users.py")
    chats_route = _read("application/single_app/route_frontend_chats.py")
    chats_template = _read("application/single_app/templates/chats.html")
    profile_template = _read("application/single_app/templates/profile.html")
    admin_template = _read("application/single_app/templates/admin_settings.html")
    streaming_script = _read("application/single_app/static/js/chat/chat-streaming.js")

    assert "'enable_desktop_notifications': False" in functions_settings
    assert '"desktopNotificationsEnabled"' in functions_settings
    assert "doc['settings']['desktopNotificationsEnabled'] = True" in functions_settings

    assert "'enable_desktop_notifications': form_data.get('enable_desktop_notifications') == 'on'" in admin_route
    assert 'id="enable_desktop_notifications"' in admin_template
    assert "settings.enable_desktop_notifications" in admin_template

    assert "'desktopNotificationsEnabled'" in user_route
    assert '"desktopNotificationsEnabled" in settings_to_update' in user_route
    assert "desktop_notifications_enabled = bool(" in chats_route
    assert 'user_settings_dict.get("desktopNotificationsEnabled", True)' in chats_route

    assert "enable_desktop_notifications:" in chats_template
    assert "desktop_notifications_enabled:" in chats_template
    assert "app_title:" in chats_template
    assert "{% if app_settings.enable_desktop_notifications %}" in profile_template
    assert 'id="desktop-notifications-toggle"' in profile_template
    assert "Notification.requestPermission()" in profile_template

    assert "showDesktopConversationNotification(data);" in streaming_script
    assert "requestDesktopNotificationPermissionIfNeeded()" in streaming_script


if __name__ == "__main__":
    test_desktop_notification_settings_are_wired_end_to_end()
    print("Desktop notification settings test passed.")
