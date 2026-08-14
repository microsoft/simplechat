# Top Navigation Public Workspace Label Crash Fix

Fixed/Implemented in version: **0.250.192**

Version reference: `application/single_app/config.py` reports version `0.250.192`.

## Issue Description

Users could save the top navigation preference, but subsequent page requests returned a server error when Public Workspaces was enabled. Removing `"navLayout": "top"` from the user's Cosmos settings document allowed the application to render again because it restored the sidebar navigation path.

## Root Cause Analysis

The stored navigation preference was valid. It caused `base.html` to include `_top_nav.html`, where the signed-in user menu referenced `public_workspace_labels.plural` before the template assigned `public_workspace_labels`.

Jinja treats an assignment in the template as a template-local variable. The earlier attribute lookup therefore raised `jinja2.exceptions.UndefinedError` instead of using the label context already available through `app_settings`. The sidebar navigation did not fail because it initialized the same variable before its first use.

## Technical Details

Files modified:

- `application/single_app/templates/_top_nav.html`
- `application/single_app/config.py`
- `functional_tests/test_public_workspace_display_name_settings.py`
- `ui_tests/test_chat_sidebar_toggle_controls.py`
- `docs/explanation/fixes/TOP_NAV_PUBLIC_WORKSPACE_LABEL_CRASH_FIX.md`
- `docs/explanation/release_notes.md`

Code changes summary:

- Moved the `public_workspace_labels` assignment to the top-navigation initialization block.
- Preserved the existing `navLayout` setting, Cosmos document shape, navigation conditions, routes, and responsive behavior.
- Added a deterministic render regression using the real top-navigation template with a signed-in user, Public Workspaces enabled, a custom label, and the persisted top-navigation preference.
- Strengthened the authenticated browser workflow to verify that a page loaded with persisted top navigation returns successfully and exposes a usable user menu.

Impact:

- Users can select top navigation without becoming locked out of the application when Public Workspaces is enabled.
- Default and customized Public Workspace labels continue to appear in the top-navigation user menu.
- No settings migration or manual Cosmos profile repair is required after deployment.

## Validation

Testing approach:

- Run `python functional_tests/test_public_workspace_display_name_settings.py`.
- Run `pytest ui_tests/test_chat_sidebar_toggle_controls.py::test_chat_sidebar_desktop_uses_sidebar_toggle_without_inline_duplicate` against an authenticated UI environment.
- Run `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

Test results:

- The Public Workspace display-name functional test passed all four checks, including the real top-navigation render regression.
- The changed Python test files passed syntax compilation.
- The authenticated Playwright test was collected successfully and skipped because the local UI base URL and storage state were not configured.
- The repository diff check passed.

Before:

- Rendering `_top_nav.html` for a signed-in user with Public Workspaces enabled raised `UndefinedError: 'public_workspace_labels' is undefined`.
- Any page using the persisted top-navigation layout could return a server error.

After:

- The label context is initialized before any top-navigation branch reads it.
- The same render path succeeds and includes the configured Public Workspace label.
