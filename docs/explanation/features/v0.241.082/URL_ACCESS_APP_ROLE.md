# URL Access App Role Governance

## Overview
Admins can now require the `UrlAccessUser` Enterprise App role before users can use URL Access. This gives URL fetching its own governance boundary separate from Deep Research while preserving the shared URL safety and domain policy controls.

Implemented in version: **0.241.082**

Config version reference: `application/single_app/config.py` version `0.241.082`.

## Dependencies
- `functions_source_review.py` for URL Access role checks and request validation
- `route_backend_chats.py` for chat request enforcement
- `route_backend_workflows.py` for workflow save/manual-run enforcement
- `functions_workflow_runner.py` for scheduled workflow enforcement
- `admin_settings.html` and `route_frontend_admin_settings.py` for admin configuration
- `deployers/azurecli/appRegistrationRoles.json` for the `UrlAccessUser` app role definition

## Technical Specifications
- New app role value: `UrlAccessUser`
- New setting: `require_member_of_url_access_user`
- Default: `False`
- When enabled, chat URL Access requests require the signed-in user's token to include `UrlAccessUser`.
- Workflow authoring requires the role before a workflow can be saved with URL Access enabled.
- Scheduled workflows use the saved `url_access_authorized` marker created during an authorized workflow save, while still respecting the current global URL Access admin toggle.
- Deep Research remains governed separately by `DeepResearchUser`.

## Usage Instructions
1. Update the Entra app registration app roles from `deployers/azurecli/appRegistrationRoles.json`.
2. Assign the `UrlAccessUser` Enterprise App role to users or groups that should use direct URL fetching.
3. Open Admin Settings.
4. Go to Search & Extract.
5. Enable URL Access.
6. Enable `Require UrlAccessUser app role`.
7. Save settings.

## Testing and Validation
- `functional_tests/test_source_review_security.py` validates the app role definition, role detection, user-aware URL Access enablement, and request validation failure reason.
- `functional_tests/test_workflow_url_access_policy.py` validates workflow save authorization metadata and runner preauthorization handling.
- `ui_tests/test_admin_source_review_settings.py` validates the admin toggle.

## Known Limitations
- Scheduled workflows cannot inspect a live user token. They rely on workflow URL Access authorization captured at save time, plus the current global URL Access admin toggle.
- If admins enable the role requirement after workflows were saved by users without `UrlAccessUser`, those workflows must be re-saved by an authorized user before scheduled URL Access can continue.