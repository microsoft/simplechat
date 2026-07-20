# functions_latest_features_nav.py

import os


LATEST_FEATURES_HIDDEN_VERSION_SETTING = "latestFeaturesHiddenVersion"


def is_development_env_enabled(value=None):
    """Return True only when the development env flag is explicitly true."""
    raw_value = os.getenv("is_development", "") if value is None else value
    return str(raw_value or "").strip().lower() == "true"


def normalize_latest_features_hidden_version(value):
    """Normalize a hidden-version setting value for storage and comparison."""
    if value is None:
        return None

    normalized_value = str(value).strip()
    return normalized_value or None


def extract_latest_features_hidden_version(user_settings_payload):
    """Extract the hidden-version value from either a settings dict or user settings document."""
    if not isinstance(user_settings_payload, dict):
        return None

    settings = user_settings_payload.get("settings")
    if isinstance(settings, dict):
        return normalize_latest_features_hidden_version(
            settings.get(LATEST_FEATURES_HIDDEN_VERSION_SETTING)
        )

    return normalize_latest_features_hidden_version(
        user_settings_payload.get(LATEST_FEATURES_HIDDEN_VERSION_SETTING)
    )


def should_hide_latest_features_nav(user_settings_payload, current_version, is_development=False):
    """Determine whether Latest Features nav entries should be hidden."""
    if bool(is_development):
        return True

    normalized_current_version = normalize_latest_features_hidden_version(current_version)
    if not normalized_current_version:
        return False

    hidden_version = extract_latest_features_hidden_version(user_settings_payload)
    return hidden_version == normalized_current_version
