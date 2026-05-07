# Security Authorization Hardening Fix

Fixed/Implemented in version: **0.241.007**

## Overview

This hardening pass closed a set of authenticated authorization gaps where route entry authentication existed, but later operations still trusted caller-controlled ids or stale stored scope values. The changes were intentionally concentrated at shared helper boundaries so the application could reject unauthorized cross-scope requests consistently without adding broad latency across unrelated flows.

Version implemented:
`config.py` was updated to `VERSION = "0.241.007"` for this fix.

## Root Cause Pattern

The underlying issue was not missing session authentication. Users were authenticated, but several later-stage operations relied on one of the following unsafe assumptions:

- A caller-supplied identifier was treated as trustworthy after login.
- A value stored earlier in user settings was reused without checking whether access still existed.
- Eligibility logic existed for list views or normal paths but was not enforced again on direct detail or mutation routes.
- Untrusted stored metadata was rendered into HTML without escaping.

The remediation strategy was therefore to revalidate authorization at the point where the sensitive operation actually happens, not just at route entry.

## Remediation By Finding

### Search Filter Literal Hardening

Issue:
Azure AI Search filter construction interpolated raw ids directly into single-quoted OData expressions. A maliciously crafted document id, group id, public workspace id, or shared-id value could alter the meaning of the filter.

Root cause:
Filter fragments were built with direct f-string interpolation instead of a shared escaping helper.

Changes implemented:
- Added `_escape_odata_literal(value)`.
- Added `_build_odata_eq(field_name, value)`.
- Added `_build_odata_any_eq(collection_field, iterator_name, value)`.
- Replaced raw interpolation for `document_id`, `user_id`, `group_id`, `shared_group_ids`, `shared_user_ids`, and `public_workspace_id` filter clauses.

Files involved:
- `application/single_app/functions_search.py`

Security outcome:
The search layer now preserves the intended filter semantics even when ids contain embedded quote characters.

Performance impact:
Negligible. The change is string escaping and helper reuse only.

### Active Group Selection Hardening

Issue:
Both the generic user settings update path and the frontend active-group setter could persist an arbitrary `activeGroupOid` value without verifying that the current user was still a member of that group.

Root cause:
Active group updates were treated like a normal preference write instead of an authorization-sensitive context change.

Changes implemented:
- Hardened `update_active_group_for_user(group_id, user_id=None)` to enforce membership through `assert_group_role(...)` before writing settings.
- Hardened `require_active_group(user_id, allowed_roles=...)` to revalidate stored active group membership before returning it.
- Updated `POST /api/user/settings` so `activeGroupOid` is routed through `update_active_group_for_user(...)` and returns `404` for missing groups or `403` for non-membership.
- Updated the frontend `/set_active_group` flow to use the same validated helper instead of writing settings directly.

Files involved:
- `application/single_app/functions_group.py`
- `application/single_app/route_backend_users.py`
- `application/single_app/route_frontend_group_workspaces.py`

Security outcome:
Users can no longer pivot into another group's active context by writing or submitting an arbitrary group id.

Behavioral change:
Stale group selections now fail fast instead of being silently persisted and reused later.

### Group Scope Authorization Enforcement

Issue:
Group prompt routes trusted the stored active group, and the group details route returned full group data without confirming the caller remained a member.

Root cause:
The code assumed that once an active group had been selected, downstream group-scoped operations could reuse it safely.

Changes implemented:
- Added `_get_active_group_or_error(user_id)` in the group prompt route module.
- Switched all group prompt CRUD routes to the validated active-group helper path.
- Added explicit membership enforcement in `api_get_group_details(group_id)` before returning the full group document.

Files involved:
- `application/single_app/route_backend_group_prompts.py`
- `application/single_app/route_backend_groups.py`
- `application/single_app/functions_group.py`

Security outcome:
Direct requests into group prompt and group detail routes now depend on current membership rather than previously stored state alone.

Behavioral change:
Unauthorized group detail requests now return `403` instead of exposing the group document.

### Approval Authorization Enforcement

Issue:
Approval-related views had policy logic, but direct read, approve, and deny operations did not consistently enforce that policy for the specific approval being accessed.

Root cause:
Eligibility checks were not centralized and were not consistently reused between list, detail, and mutation flows.

Changes implemented:
- Added `get_authorized_approval(approval_id, group_id, user_id, user_roles, require_approval_rights=False)`.
- Used `_can_user_view(...)` for read access and `_can_user_approve(...)` for mutation eligibility.
- Updated both admin and general approval GET-by-id endpoints to load approvals through the shared authorization helper.
- Updated approve and deny endpoints to require approval rights explicitly and to pass the already authorized approval document into `approve_request(...)` and `deny_request(...)`.
- Updated `can_approve` output to reflect the real approval policy instead of a requester-only shortcut.

Files involved:
- `application/single_app/functions_approvals.py`
- `application/single_app/route_backend_control_center.py`

Security outcome:
Knowing an approval id is no longer enough to read or act on that approval unless the caller is actually authorized for that approval record.

Performance impact:
Low. The route now performs the authorization check up front and reuses the loaded approval document during mutation to avoid redundant reads.

### History-Grounded Fallback Revalidation

Issue:
When workspace search was disabled or unavailable, follow-up chat flows could rebuild search scope from prior grounded references without checking whether the user still had access to those group or public workspace scopes.

Root cause:
The existing helper translated prior grounded refs into search parameters correctly, but it did not serve as an authorization boundary.

Changes implemented:
- Added `revalidate_prior_grounded_document_search_parameters(user_id, search_parameters)`.
- Filtered `active_group_ids` by current group membership.
- Filtered `active_public_workspace_ids` by currently visible public workspace ids.
- Cleared `document_ids` and `doc_scope` when all prior scope had been revoked.
- Inserted the revalidation step at both history-grounded fallback call sites before the search reuse path is enabled.

Files involved:
- `application/single_app/route_backend_chats.py`

Security outcome:
Previously grounded references no longer revive access to group or public documents after authorization changes.

Behavioral change:
Some follow-up requests may now lose prior grounded reuse if the user's access changed since the earlier conversation turn. That is the intended secure behavior.

## Defense-In-Depth Hardening Outside The Finding-Mapped Items

These changes were part of the same hardening pass but are not tied to the `f` findings listed above.

### Control Center Public Workspace Escaping

Issue:
The Control Center public workspace row renderer and adjacent activity-log summary strings contained raw interpolation into HTML-building paths.

Changes implemented:
- Escaped public workspace `name`, `description`, `id`, `ownerName`, and `ownerEmail` before row rendering.
- Escaped `profile_image` when written into avatar markup.
- Escaped activity-log summary fields for login method, conversation titles and ids, file names and file types, token type, and model name.

Files involved:
- `application/single_app/static/js/control-center.js`

Outcome:
Untrusted metadata in the Control Center admin UI now renders as inert text instead of raw HTML.

### CSP Hardening Status

The broader CSP tightening work was deliberately not implemented in this pass. The current changes reduce exposure at the specific rendering sinks that were validated, but CSP remains a separate hardening track.

## Files Modified In The Hardening Pass

- `application/single_app/functions_search.py`
- `application/single_app/functions_group.py`
- `application/single_app/route_backend_users.py`
- `application/single_app/route_frontend_group_workspaces.py`
- `application/single_app/route_backend_group_prompts.py`
- `application/single_app/route_backend_groups.py`
- `application/single_app/functions_approvals.py`
- `application/single_app/route_backend_control_center.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/control-center.js`
- `application/single_app/config.py`
- `functional_tests/test_security_authorization_hardening.py`
- `ui_tests/test_control_center_public_workspace_escaping.py`

## Validation And Regression Coverage

Testing approach:
- Added a functional regression test covering OData escaping, active-group validation, approval authorization, history fallback revalidation, Control Center escaping, documentation presence, and version bump checks.
- Added a Playwright UI regression that stubs malicious public workspace metadata and verifies the Control Center renders it as inert text.
- Validated the new tests through `py_compile`, direct functional execution, and targeted `pytest` execution.

Test results from this implementation pass:
- `functional_tests/test_security_authorization_hardening.py`: passed.
- `ui_tests/test_control_center_public_workspace_escaping.py`: collected under `pytest` and skipped when authenticated UI environment variables were not present, which is the intended fallback behavior for local non-UI environments.

Regression guarantees provided by the new tests:
- Search filter helper coverage fails if raw OData interpolation is reintroduced.
- Active-group coverage fails if membership validation is bypassed on settings or frontend setter paths.
- Approval coverage fails if direct approval authorization stops using the shared helper.
- Chat fallback coverage fails if revoked scope ids continue to survive reuse.
- Control Center coverage fails if malicious workspace metadata is rendered into real DOM elements.

## Performance And Latency Notes

The runtime impact of these changes is intentionally low.

- Search hardening is string escaping only.
- Active-group and group-scope hardening adds targeted membership validation only where the active group is written or consumed as an authorization-sensitive context.
- Approval hardening centralizes checks and reuses the loaded approval record during mutation.
- History fallback revalidation performs small scope-filtering checks only on the fallback path, not on every normal search.
- Control Center escaping is local output encoding in already-rendered admin UI paths.

In practice, these changes should not create a user-visible latency increase outside of the specific protected operations, and even there the cost is bounded and appropriate for the security value gained.

## Before And After

Before:
- Authenticated users could attempt to widen Azure AI Search filters with crafted literals.
- Caller-controlled or stale active-group ids could influence later group-scoped operations.
- Group prompt and detail flows could trust stored context more than current authorization.
- Approval detail and mutation routes could be reached without a single shared per-approval authorization boundary.
- Prior grounded references could continue to influence follow-up search scope after access changed.
- Control Center workspace metadata could be injected into HTML-building paths.

After:
- Sensitive ids are escaped before entering OData filters.
- Active group writes and reads both validate membership.
- Group prompt and group detail flows fail closed when the user lacks current access.
- Approval reads and mutations share a single explicit authorization path.
- History-grounded fallback only reuses scopes the caller can still access.
- Control Center metadata is rendered safely as text.

## User Experience Impact

Normal authorized workflows stay the same. The user-visible changes are limited to security-correct behavior:

- Unauthorized or stale cross-scope requests now fail explicitly with `403` or `404` responses.
- Group-scoped UI flows do not silently persist invalid active-group state.
- Follow-up grounded search reuse may stop when prior access has been revoked.
- Control Center administrators see suspicious workspace metadata rendered as text instead of interpreted markup.