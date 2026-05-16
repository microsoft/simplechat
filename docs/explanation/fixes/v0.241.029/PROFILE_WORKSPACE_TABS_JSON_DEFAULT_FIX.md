# Profile Workspace Tabs JSON Default Fix

## Header Information

Issue description: Opening `/profile` could return HTTP 500 when the Profile template attempted to serialize an undefined workspace permission variable into `window.profilePageConfig`.

Root cause analysis: The Profile route normally passes `can_create_groups` and `can_create_public_workspaces`, but Jinja `tojson` cannot serialize an `Undefined` value. If the template was rendered without those variables, such as during a reload mismatch or alternate render path, the page failed before any frontend JavaScript could run.

Version implemented: **0.241.029**

Fixed/Implemented in version: **0.241.029**

## Technical Details

Files modified:

- `application/single_app/templates/profile.html`
- `functional_tests/test_profile_workspace_tabs.py`
- `ui_tests/test_profile_workspace_tabs.py`
- `application/single_app/config.py`

Code changes summary:

- Added Jinja `default(false)` safeguards before JSON serialization of profile workspace create-permission flags.
- Added default safeguards for the related profile page config feature flags.
- Extended the profile workspace tab functional test to assert the defaulted `tojson` contract remains in place.

Testing approach:

- Run JavaScript syntax validation for the profile tab script.
- Compile the modified Python route and tests.
- Run the focused profile workspace functional regression test.
- Run diff whitespace validation.

Impact analysis:

Users can open the Profile page even if workspace permission values are missing from the render context. The profile tabs still receive concrete booleans in normal route execution, and the template fallback prevents a server-side 500.

## Validation

Test results:

- `functional_tests/test_profile_workspace_tabs.py` covers the profile workspace tab static contract and the JSON default safeguards.

Before/after comparison:

- Before: `{{ can_create_groups | tojson }}` could raise `TypeError: Object of type Undefined is not JSON serializable`.
- After: `{{ (can_create_groups | default(false)) | tojson }}` always serializes a concrete boolean.

User experience improvements:

The Profile page now loads reliably instead of failing with an internal server error when workspace permission context is absent.

## Version Tracking

The application version for this fix is tracked in `application/single_app/config.py` as `0.241.029`.
