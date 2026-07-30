# Admin Settings Save 500 Fix

## Issue Description

Saving Admin Settings successfully persisted configuration changes but returned an HTTP 500 error to the browser. The error occurred after the settings update completed, during the post-save logo and favicon file refresh path.

## Root Cause Analysis

The `/admin/settings` POST handler in `route_frontend_admin_settings.py` called `ensure_custom_logo_file_exists(app, updated_settings_for_file)` and `ensure_custom_favicon_file_exists(app, updated_settings_for_file)` using an `app` symbol that was not defined in that module. Flask logged a `NameError: name 'app' is not defined` after the settings update, causing the 500 response even though the settings were saved.

## Version Implemented

- Fixed in version: **0.250.005**

## Technical Details

- Files modified:
  - `application/single_app/route_frontend_admin_settings.py`
  - `application/single_app/config.py`

- Code changes summary:
  - Replaced the undefined `app` reference with Flask's `current_app` when calling the logo and favicon helpers after a successful settings update.
  - Bumped the application `VERSION` constant from `0.250.004` to `0.250.005` in `config.py`.

- Updated logic (high level):
  - After `update_settings(new_settings)` succeeds and fresh settings are loaded via `get_settings()`, the route now imports `current_app` from Flask and passes it into:
    - `ensure_custom_logo_file_exists(current_app, updated_settings_for_file)`
    - `ensure_custom_favicon_file_exists(current_app, updated_settings_for_file)`
    - `initialize_clients(updated_settings_for_file)` remains unchanged.

## Testing Approach

- Local validation:
  - Verified that saving Admin Settings no longer throws a 500 and returns a success flash message while still persisting changes.
  - Confirmed that logo and favicon regeneration still run after a successful save.

- Guardrail checks:
  - `python -m py_compile application/single_app/route_frontend_admin_settings.py`
  - `python scripts/check_swagger_routes.py application/single_app/route_frontend_admin_settings.py`
  - `python scripts/check_broken_access_control.py --full-file application/single_app/route_frontend_admin_settings.py`
  - `python scripts/check_xss_sinks.py --full-file application/single_app/route_frontend_admin_settings.py`
  - `git diff --check upstream/Development...HEAD`

All checks passed.

## Impact Analysis

- User experience:
  - Admins now see a successful response when saving Admin Settings instead of an HTTP 500, eliminating confusion where settings appeared to save but the page reported an error.

- Functional behavior:
  - Settings persistence, Application Insights reconfiguration, logo/favicon file regeneration, and client reinitialization remain intact.

- Risk:
  - Low. The change only replaces an undefined `app` symbol with the correct Flask `current_app` reference in the post-save path.
