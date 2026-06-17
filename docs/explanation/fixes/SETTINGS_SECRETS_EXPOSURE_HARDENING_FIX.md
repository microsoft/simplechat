# Settings Secrets Exposure Hardening Fix

Fixed/Implemented in version: **0.242.059**

## Issue Description

The Settings and Secrets Exposure audit found three places where secret-bearing values or service diagnostics could be exposed more broadly than needed:

- Admin Settings rendered stored keys, client secrets, subscription keys, and connection strings into password input values.
- Admin Settings test buttons depended on those raw DOM values for connection tests, making simple blanking unsafe without breaking tests.
- The Azure Billing community action logged token endpoint details and response bodies on service-principal token failures.
- The TTS route returned raw SDK/configuration exception detail to authenticated clients.

## Root Cause Analysis

Admin Settings loaded raw settings for admin functionality and passed them to the template. Although the route is admin-only, password inputs still made stored values browser-inspectable. Test-connection requests were built from current input values, so removing secrets from the DOM required a server-side way to resolve a stored sentinel. Azure Billing used direct `logging.error(...)` with token response text, and TTS returned raw exception strings from Azure Speech SDK paths.

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/route_backend_settings.py`
- `application/community_customizations/actions/azure_billing_retriever/azure_billing_plugin.py`
- `application/single_app/route_backend_tts.py`
- `application/single_app/config.py`
- `functional_tests/test_settings_secrets_exposure_hardening.py`

### Code Changes Summary

- Added `ADMIN_SETTINGS_SECRET_REDACTED_VALUE` and shared Admin Settings redaction/preservation helpers.
- Redacted stored Admin Settings secrets before rendering the admin template.
- Preserved existing stored values when Admin Settings POST submits the redacted sentinel.
- Resolved the same sentinel in `/api/admin/settings/test_connection` so tests continue to work without re-entering secret values.
- Replaced Azure Billing token-failure raw logging/raised response details with `log_event(...)` and generic user-facing failures.
- Replaced TTS raw client-facing SDK/configuration exception responses with stable generic messages while logging sanitized details server-side.
- Updated application version from `0.242.058` to `0.242.059` in `config.py`.

## Validation

### Test Results

Focused validation is covered by `functional_tests/test_settings_secrets_exposure_hardening.py`, which checks:

- Admin Settings secret fields are registered for redaction.
- Admin saves use the preservation helper instead of direct raw secret assignment.
- Admin test-connection payloads resolve stored sentinel values server-side.
- Azure Billing token errors no longer include token endpoint response details in logs or raised exceptions.
- TTS client-facing failures no longer return raw exception strings.

### Before/After Comparison

Before: Stored secrets were available in Admin Settings browser markup, and some external-service failures exposed raw provider diagnostics.

After: Admin Settings renders a redacted sentinel for stored secret-bearing fields, test/save flows resolve that sentinel back to the stored value server-side, and external-service failures return generic client messages with sanitized diagnostic logging.

## Impact Analysis

Admins can still test configured services without re-entering keys, secrets, or connection strings. Blank secret fields still clear values intentionally, while `***REDACTED***` means preserve the stored value. Non-admin settings rendering remains unchanged and continues to use public settings sanitization.
