# Deep Research App Role Governance

## Overview
Deep Research can be enabled globally for chat and optionally restricted to users assigned the `DeepResearchUser` Enterprise App role. This replaces the prior UI-managed allowed-user list with tenant-scale Entra app role governance.

Implemented in version: **0.241.069**

## Dependencies
- SimpleChat application setting `enable_source_review`
- Optional SimpleChat setting `require_member_of_deep_research_user`
- Entra Enterprise App role value `DeepResearchUser`
- App role definition in `deployers/azurecli/appRegistrationRoles.json`
- Deployer version `1.0.4`

## Technical Specifications
- `functions_source_review.is_source_review_enabled_for_user()` enforces the Deep Research master toggle and, when configured, requires the authenticated session role claim to include `DeepResearchUser`.
- Chat frontend settings only expose Deep Research to authorized users when the role requirement is enabled.
- Chat backend routes pass session roles into the authorization helper so client-side toggles cannot bypass the role requirement.
- Legacy `source_review_allowed_users` and `source_review_blocked_users` settings are normalized to empty lists and are not used for runtime authorization.
- `config.py` version was updated to `0.241.069`; deployer version was updated to `1.0.4` for the new app role definition.

## Usage Instructions
1. Enable Deep Research in Admin Settings under Search & Extract.
2. Leave `Require DeepResearchUser app role` off to allow all signed-in users who can chat to use Deep Research.
3. Turn on `Require DeepResearchUser app role` to restrict Deep Research.
4. Assign users or groups to the `DeepResearchUser` role in the Enterprise App before enforcing the requirement.

## Testing and Validation
- `functional_tests/test_source_review_security.py` validates runtime role gating and the deployment app role definition.
- `ui_tests/test_admin_source_review_settings.py` validates the Admin Settings app-role toggle and confirms the old assigned-user UI is removed.
- Deployer regression tests validate the deployer version bump to `1.0.4`.

## Known Limitations
- Existing signed-in sessions may need to refresh after a role assignment so the updated role claim is present in `session['user']['roles']`.
