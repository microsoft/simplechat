# functions_conversation_contents.py


def is_conversation_contents_drawer_enabled(app_settings, user_settings):
    """Return whether both the admin gate and current-user preference allow the drawer."""
    normalized_app_settings = app_settings if isinstance(app_settings, dict) else {}
    normalized_user_settings = user_settings if isinstance(user_settings, dict) else {}
    return bool(
        normalized_app_settings.get('enable_conversation_contents_drawer', True)
        and normalized_user_settings.get('conversationContentsDrawerEnabled', True)
    )
