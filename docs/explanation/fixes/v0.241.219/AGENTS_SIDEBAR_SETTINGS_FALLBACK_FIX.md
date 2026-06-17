# Agents Sidebar Settings Fallback Fix

Fixed in version: **0.241.219**

## Issue Description

Pages that render the shared sidebar with only `app_settings` in the template context could fail with `jinja2.exceptions.UndefinedError: 'settings' is undefined` after the Agents navigation link was added under Chat.

## Root Cause

The new Agents sidebar link used `settings.enable_semantic_kernel` directly. Some frontend routes, including the landing page, pass sanitized settings as `app_settings` but do not pass a separate `settings` variable.

## Technical Details

Files modified:

- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/templates/_sidebar_short_nav.html`
- `application/single_app/config.py`
- `functional_tests/test_agents_catalog_feature.py`

Code changes:

- Added a local `sidebar_settings = settings if settings is defined else app_settings` fallback in both sidebar templates.
- Updated Agents and related sidebar feature gates to use `sidebar_settings` instead of directly requiring `settings`.
- Added regression assertions to the Agents catalog functional test.

## Validation

- `functional_tests/test_agents_catalog_feature.py` validates the fallback exists and direct `settings.enable_semantic_kernel` sidebar checks are not reintroduced.
- `application/single_app/config.py` version updated to **0.241.219**.
