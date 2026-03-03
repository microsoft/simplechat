# Chats User Settings Hardening Fix (v0.238.025)

## Issue Description
A single user could fail to load the chats page while other users worked normally.

## Root Cause Analysis
The chats route expected `user_settings["settings"]` to always be a dictionary. If that field existed but had malformed data (for example, string/null/list), the route could throw before rendering.

## Version Implemented
Fixed/Implemented in version: **0.238.025**

## Technical Details
### Files Modified
- application/single_app/functions_settings.py
- application/single_app/route_frontend_chats.py
- application/single_app/config.py
- functional_tests/test_chats_user_settings_hardening_fix.py

### Code Changes Summary
- Hardened `get_user_settings()` to normalize malformed or missing `settings` to `{}` and persist the repaired document.
- Added repair telemetry for malformed settings shape.
- Hardened `/chats` route to safely read nested settings with dictionary fallbacks.
- Incremented application version.

### Testing Approach
- Added a functional regression test validating both malformed and missing `settings` cases are repaired and upserted.

## Impact Analysis
- Healthy users are unaffected.
- Corrupted user settings documents are self-healed on read.
- Prevents user-specific chats page crashes caused by malformed settings shape.

## Validation
- Functional test: functional_tests/test_chats_user_settings_hardening_fix.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.238.025**.
