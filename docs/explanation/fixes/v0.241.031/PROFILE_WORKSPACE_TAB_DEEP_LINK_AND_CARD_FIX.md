# Profile Workspace Tab Deep Link and Card Interaction Fix

## Header Information

Issue description: The Profile-hosted My Groups and My Public Workspaces tabs could miss create buttons for eligible users when permission values were absent from the render context. Sidebar account links to those tabs could land on Profile without selecting the requested tab. Workspace cards also lacked the same hover and click affordance used by agent and action cards.

Root cause analysis: The Profile template depended directly on route-provided permission booleans for create buttons. The server-rendered active tab also depended on route-side tab normalization, so any settings mismatch could leave Stats selected even when the URL contained `?tab=groups` or `?tab=public-workspaces`. Workspace cards were rendered as passive containers with only explicit Manage buttons.

Version implemented: **0.241.031**

Fixed/Implemented in version: **0.241.031**

## Technical Details

Files modified:

- `application/single_app/templates/profile.html`
- `application/single_app/static/js/profile/profile-tabs.js`
- `application/single_app/config.py`
- `functional_tests/test_profile_workspace_tabs.py`
- `ui_tests/test_profile_workspace_tabs.py`

Code changes summary:

- Added Profile template fallback permission variables based on `app_settings` and current session roles, while still honoring route-provided values when present.
- Updated the create button and modal guards to use the resolved Profile permission variables.
- Added client-side Profile tab activation from the URL query string when the requested tab exists.
- Added card hover/focus styling and click-to-manage behavior for group and public workspace cards.
- Extended the static functional regression test for the permission fallback, deep-link activation, and card navigation contracts.

Testing approach:

- JavaScript syntax check for `profile-tabs.js`.
- Python compile checks for modified Python files and tests.
- Focused functional regression test for the Profile workspace tabs.
- UI test entrypoint for browser behavior, with clean skip when authenticated Playwright state is not configured.
- Git whitespace validation.

Impact analysis:

Eligible users now see Create Group and Create Public Workspace controls even if the route context is missing those booleans. Sidebar links reliably select the intended Profile tab. Card view is more discoverable and faster to use because clicking the card opens the corresponding manage page.

## Validation

Test results:

- `functional_tests/test_profile_workspace_tabs.py` validates the static Profile workspace tab contracts.
- `ui_tests/test_profile_workspace_tabs.py` validates tab view switching when a configured browser session is available.

Before/after comparison:

- Before: Sidebar account links could open Profile with Stats still selected, and cards were not clickable.
- After: URL tab values activate the matching tab client-side, and cards have hover/focus styling plus click-to-manage behavior.

User experience improvements:

The Profile workspace tabs now match the expected agents/actions-style card affordance and keep create/join/manage actions close to the user's account workflow.

## Version Tracking

The application version was updated in `application/single_app/config.py` to `0.241.031` for this fix.
