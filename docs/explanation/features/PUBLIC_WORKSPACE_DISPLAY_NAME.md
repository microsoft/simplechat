# Public Workspace Display Name

Current version: **0.250.110**

Implemented in version: **0.250.110**

## Overview

Admins can configure an end-user display name for Public Workspace so organizations can present terminology that matches their internal knowledge-management vocabulary, such as "Domain Knowledge". Admin settings and internal implementation details continue to use Public Workspace/public_workspace so app admins can clearly map the custom label back to the platform capability.

## Dependencies

- Admin settings defaults and sanitization in `application/single_app/functions_settings.py`
- Admin Settings save route in `application/single_app/route_frontend_admin_settings.py`
- Admin Settings UI in `application/single_app/templates/admin_settings.html`
- Shared frontend label context in `application/single_app/templates/base.html`
- End-user templates and JavaScript for public workspace navigation, profile, public directory, public workspace management, and chat document scope selection

## Technical Specifications

The feature stores a single setting named `public_workspace_display_name`. The value is normalized by trimming whitespace, collapsing line breaks and repeated spaces, and capping the stored value at 32 characters. Empty or missing values preserve the default user-facing labels:

- Singular: `Public Workspace`
- Plural: `Public Workspaces`
- Lowercase singular: `public workspace`
- Lowercase plural: `public workspaces`
- Short navigation label: `Public`

When a custom display name is configured, the exact custom value is reused for singular and plural contexts. This avoids awkward automatic pluralization for labels such as "Domain Knowledge".

`get_public_workspace_label_context()` derives the frontend-safe label context from settings. `sanitize_settings_for_user()` always adds the derived `public_workspace_labels` object for templates and JavaScript without exposing sensitive settings. The derived labels are removed before settings are persisted so Cosmos DB stores only the raw `public_workspace_display_name` value.

## Configuration Options

- `public_workspace_display_name`: Optional end-user label for Public Workspace. Maximum length is 32 characters.

Admins configure this in Admin Settings > Workspaces > Public Workspaces using the "End-user display name" field. The field helper text clarifies that admin settings and internal references continue to use Public Workspace.

## Usage Instructions

1. Open Admin Settings.
2. Select the Workspaces tab.
3. Find the Public Workspaces section.
4. Enter an end-user display name, for example `Domain Knowledge`.
5. Save Admin Settings.

End users then see the configured label in navigation, profile Public Workspace areas, the public directory, public workspace management pages, chat scope selection, and related browser messages. Admin-only screens such as Admin Settings and Control Center continue to use Public Workspace terminology.

## Testing and Validation

Functional coverage is in `functional_tests/test_public_workspace_display_name_settings.py`. It validates normalization, default/custom label derivation, sanitized frontend label exposure, and removal of derived labels before persistence.

UI coverage is in `ui_tests/test_public_workspace_display_name_ui.py`. It validates that the Admin Settings field is visible with a 32-character limit and that the public directory consumes the same label context exposed to browser code.

Known limitations:

- The feature intentionally does not rename routes, APIs, Cosmos containers, permissions, app roles, log field names, or backend identifiers.
- Custom labels are reused exactly rather than automatically pluralized.
