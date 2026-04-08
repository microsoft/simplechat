# User Tutorial Visibility Preference (v0.240.068)

Fixed/Implemented in version: **0.240.068**

## Overview

Users can now decide whether the floating guided tutorial launch buttons stay visible on Chat and Personal Workspace. The launchers remain visible by default for new and existing users, but each person can hide or restore them later from the profile page.

## Dependencies

- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_users.py`
- `application/single_app/templates/profile.html`
- `application/single_app/templates/chats.html`
- `application/single_app/templates/workspace.html`
- `application/single_app/support_menu_config.py`
- `application/single_app/templates/latest_features.html`

## Technical Specifications

### Architecture Overview

The preference is stored as a per-user setting named `showTutorialButtons` inside the existing Cosmos-backed user settings document. The setting defaults to `True` when a user settings document is created or repaired.

### Configuration and Data Flow

- `functions_settings.get_user_settings()` now ensures `showTutorialButtons` exists and defaults to `True`.
- `route_backend_users.py` allows `showTutorialButtons` through the shared `/api/user/settings` update endpoint.
- `profile.html` exposes a dedicated Tutorial Preferences card with a toggle and save action.
- `chats.html` and `workspace.html` only render tutorial launchers when the current user setting is enabled.
- `support_menu_config.py` adds a Guided Tutorials action card that links directly to the profile preference.

### File Structure

- `application/single_app/templates/profile.html`
- `application/single_app/templates/chats.html`
- `application/single_app/templates/workspace.html`
- `application/single_app/support_menu_config.py`
- `application/single_app/templates/latest_features.html`
- `functional_tests/test_user_tutorial_visibility_preference.py`
- `ui_tests/test_profile_tutorial_visibility_preference.py`

## Usage Instructions

1. Open the Profile page.
2. Scroll to `Tutorial Preferences`.
3. Turn `Show tutorial buttons on Chat and Personal Workspace` on or off.
4. Save the preference.
5. Visit Chat or Personal Workspace to confirm the launchers match the saved preference.

Users can also open `Support > Latest Features > Guided Tutorials` and use the new profile action card to jump directly to the same preference.

## Testing and Validation

- Functional coverage: `functional_tests/test_user_tutorial_visibility_preference.py`
- UI coverage: `ui_tests/test_profile_tutorial_visibility_preference.py`
- Existing tutorial selector coverage remains in:
  - `functional_tests/test_chat_tutorial_selector_coverage.py`
  - `functional_tests/test_personal_workspace_tutorial_selector_coverage.py`

## Limitations

- The preference is user-specific and does not change the global availability of Guided Tutorials.
- The Personal Workspace tutorial launcher only appears when Personal Workspace itself is available in the environment.