#!/usr/bin/env python3
# test_latest_features_nav_hide_preference.py
"""
Functional test for versioned Latest Features navigation hiding.
Version: 0.250.058
Implemented in: 0.250.058

This test ensures that Latest Features navigation entries hide only for the
current version or explicit development override, and that the settings,
templates, and JavaScript wiring are present.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from functions_latest_features_nav import (  # noqa: E402
    LATEST_FEATURES_HIDDEN_VERSION_SETTING,
    is_development_env_enabled,
    normalize_latest_features_hidden_version,
    should_hide_latest_features_nav,
)


CURRENT_VERSION = "0.250.058"
PREVIOUS_VERSION = "0.250.057"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_contains(path: Path, markers: list[str]) -> None:
    content = read_text(path)
    missing_markers = [marker for marker in markers if marker not in content]
    assert not missing_markers, f"Missing markers in {path.name}: {missing_markers}"


def test_latest_features_nav_helper_logic():
    """Validate current-version and development override visibility rules."""
    print("Testing Latest Features nav helper logic...")

    assert LATEST_FEATURES_HIDDEN_VERSION_SETTING == "latestFeaturesHiddenVersion"
    assert normalize_latest_features_hidden_version(None) is None
    assert normalize_latest_features_hidden_version("") is None
    assert normalize_latest_features_hidden_version(f"  {CURRENT_VERSION}  ") == CURRENT_VERSION

    assert is_development_env_enabled("true") is True
    assert is_development_env_enabled(" TRUE ") is True
    assert is_development_env_enabled("false") is False
    assert is_development_env_enabled("") is False
    assert is_development_env_enabled("yes") is False

    assert should_hide_latest_features_nav({}, CURRENT_VERSION) is False
    assert should_hide_latest_features_nav(
        {"settings": {LATEST_FEATURES_HIDDEN_VERSION_SETTING: CURRENT_VERSION}},
        CURRENT_VERSION,
    ) is True
    assert should_hide_latest_features_nav(
        {"settings": {LATEST_FEATURES_HIDDEN_VERSION_SETTING: PREVIOUS_VERSION}},
        CURRENT_VERSION,
    ) is False
    assert should_hide_latest_features_nav(
        {"settings": {LATEST_FEATURES_HIDDEN_VERSION_SETTING: PREVIOUS_VERSION}},
        CURRENT_VERSION,
        is_development=True,
    ) is True

    print("Latest Features nav helper logic passed")
    return True


def test_latest_features_nav_wiring():
    """Validate backend, template, and JavaScript wiring markers."""
    print("Testing Latest Features nav wiring markers...")

    config_file = APP_DIR / "config.py"
    app_file = APP_DIR / "app.py"
    functions_settings_file = APP_DIR / "functions_settings.py"
    route_backend_users_file = APP_DIR / "route_backend_users.py"
    base_template = APP_DIR / "templates" / "base.html"
    top_nav_template = APP_DIR / "templates" / "_top_nav.html"
    sidebar_template = APP_DIR / "templates" / "_sidebar_nav.html"
    short_sidebar_template = APP_DIR / "templates" / "_sidebar_short_nav.html"
    profile_template = APP_DIR / "templates" / "profile.html"
    latest_features_js = APP_DIR / "static" / "js" / "latest-features-nav.js"

    assert_contains(
        config_file,
        [
            f'VERSION = "{CURRENT_VERSION}"',
            "IS_DEVELOPMENT = is_development_env_enabled()",
        ],
    )
    assert_contains(
        app_file,
        [
            "app.config['IS_DEVELOPMENT'] = IS_DEVELOPMENT",
            "latest_features_nav_hidden=latest_features_nav_hidden",
            "latest_features_nav_hidden_by_development=IS_DEVELOPMENT",
        ],
    )
    assert_contains(
        functions_settings_file,
        [
            "LATEST_FEATURES_HIDDEN_VERSION_SETTING",
            "USER_UI_SETTINGS_KEYS",
        ],
    )
    assert_contains(
        route_backend_users_file,
        [
            "normalize_latest_features_hidden_version",
            "Invalid Latest Features hidden version",
        ],
    )
    assert_contains(
        base_template,
        [
            "window.simplechatLatestFeaturesNav",
            "js/latest-features-nav.js",
        ],
    )
    for template in (top_nav_template, sidebar_template, short_sidebar_template):
        assert_contains(
            template,
            [
                "latest_features_nav_is_hidden",
                "data-latest-features-nav-item",
                "data-latest-features-hide-action",
            ],
        )
    assert_contains(
        sidebar_template,
        [
            "{% if not latest_features_nav_is_hidden %}",
            'data-tab="latest-features"',
        ],
    )
    assert_contains(
        profile_template,
        [
            'id="latest-features-nav-preferences"',
            'id="unhide-latest-features-nav-btn"',
            "latest_features_nav_hidden_by_development",
        ],
    )
    assert_contains(
        latest_features_js,
        [
            "// latest-features-nav.js",
            "hideLatestFeaturesNavItems",
            "showLatestFeaturesNavItems",
            "latestFeaturesHiddenVersion",
        ],
    )

    print("Latest Features nav wiring markers passed")
    return True


if __name__ == "__main__":
    tests = [
        test_latest_features_nav_helper_logic,
        test_latest_features_nav_wiring,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
