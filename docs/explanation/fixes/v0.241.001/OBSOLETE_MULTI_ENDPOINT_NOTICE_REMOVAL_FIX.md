# Obsolete Multi-Endpoint Notice Removal Fix

Fixed/Implemented in version: **0.240.072**

## Issue Description

The admin AI Models area still carried an older migration notice stating that the existing AI endpoint was migrated and agents using the default connection might need manual updates. That message was obsolete after the shared loader fallback and admin migration workflow were added.

## Root Cause Analysis

- The old migration notice text still existed in admin settings defaults.
- The admin settings template still rendered a warning banner for that notice.
- The AI Models JavaScript still bootstrapped and checked obsolete notice state.

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_multi_endpoint_notice_template_fallback.py`
- `functional_tests/test_admin_agent_default_model_migration.py`
- `functional_tests/test_single_app_template_json_bootstrap_safety.py`

### Code Changes Summary

- Removed the obsolete multi-endpoint migration banner from the admin settings template.
- Stopped bootstrapping the old notice object into the AI Models admin JavaScript.
- Replaced the old message defaults with an empty disabled notice payload so future admin saves no longer preserve the obsolete text.
- Updated regression tests to ensure the message text and old warning banner do not return.

## Validation

- Admin settings no longer render the obsolete migration warning.
- The AI Models migration workflow continues to use the newer review and bulk-migration panel instead of the old banner.
- Regression tests now verify the obsolete message text is absent from the admin flow.

## Config Version Reference

`config.py` updated to `VERSION = "0.240.072"`.