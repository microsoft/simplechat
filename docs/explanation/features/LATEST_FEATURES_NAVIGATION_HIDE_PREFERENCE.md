# Latest Features Navigation Hide Preference

Implemented in version: **0.250.059**

## Overview

The Latest Features Navigation Hide Preference lets users hide Latest Features navigation entries for the current SimpleChat version. The preference is versioned, so Latest Features navigation automatically returns when the app version changes and new release information is available.

## Dependencies

- Current app version from `application/single_app/config.py`
- Visibility helpers in `application/single_app/functions_latest_features_nav.py`
- User settings allow-list in `application/single_app/functions_settings.py`
- User settings update route in `application/single_app/route_backend_users.py`
- Navigation templates in `_top_nav.html`, `_sidebar_nav.html`, and `_sidebar_short_nav.html`
- Profile Settings controls in `application/single_app/templates/profile.html`
- Browser behavior in `application/single_app/static/js/latest-features-nav.js`

## Technical Specifications

The feature stores a `latestFeaturesHiddenVersion` value in user UI settings. Navigation rendering compares that stored value with the current `VERSION` from `config.py`; matching values hide Latest Features entries, while older values are ignored so users see the navigation again after a version bump.

The backend normalizes incoming hidden-version values before saving them, and the frontend updates the visible navigation state after hide or unhide actions complete. A development-only `is_development=true` environment override can force Latest Features navigation to hide during local validation without changing stored user settings.

## Usage Instructions

Users can hide Latest Features from the navigation action menu. They can restore the entries from Profile Settings in the Latest Features Navigation section. No administrator configuration is required.

## Testing and Validation

- Functional coverage: `functional_tests/test_latest_features_nav_hide_preference.py`
- Existing latest-features coverage updated: `functional_tests/test_latest_features_action_links.py`
- UI coverage: `ui_tests/test_latest_features_nav_hide_preference.py`
- Release note: `docs/explanation/release_notes.md` under version `0.250.059`

Known limitation: local UI validation requires `SIMPLECHAT_UI_BASE_URL` and an authenticated Playwright storage-state file.