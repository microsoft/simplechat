# Authorization State Confusion Settings Fix

Fixed/Implemented in version: **0.241.011**

## Overview

This follow-up hardening closes the remaining authorization-state confusion gap left after the earlier group and chat authorization fixes. The original execution-verified group prompt exploit path was already closed by the active-group and group-prompt hardening in version **0.241.007**. This version completes the settings-boundary remediation by hardening `activePublicWorkspaceOid` writes, filtering unsupported settings keys, and routing public prompt scope resolution through a shared validator.

Version implemented:
`config.py` now reports `VERSION = "0.241.011"` for this fix.

## Issue Description

The application still treated part of the user settings document as an authorization-adjacent state bag:

- `POST /api/user/settings` accepted `activePublicWorkspaceOid` as a normal settings value and could persist any caller-supplied workspace id without validating that the workspace existed.
- The backend and frontend public-workspace setters used the same unvalidated persistence path.
- The invalid-key check in `/api/user/settings` logged unknown keys but still allowed the original payload shape to flow into the generic settings merge helper.
- Public prompt routes reloaded `activePublicWorkspaceOid` directly from stored settings instead of using a shared active-workspace validator.

That no longer reproduced the original group prompt exploit, but it preserved the same root-cause pattern: authorization-sensitive state could still bypass centralized validation if a route treated it like an ordinary preference write.

## Root Cause

- Authorization-sensitive settings were not handled consistently at the write boundary.
- `activeGroupOid` had a dedicated validator, but `activePublicWorkspaceOid` did not.
- The generic settings route still tolerated unsupported keys after only printing a warning.
- Public workspace routes duplicated active-scope checks instead of sharing a canonical resolver.

## Technical Changes

### Active Public Workspace Write Validation

Changes implemented:

- Hardened `update_active_public_workspace_for_user(user_id, ws_id)` to normalize the value, allow explicit clearing, and fail closed with `LookupError` when the workspace does not exist.
- Switched the helper to use the live `functions_settings` module object for persistence so the write path does not depend on transitive star imports.

Files involved:

- `application/single_app/functions_public_workspaces.py`

Security outcome:

Caller-supplied public workspace ids no longer persist silently when they do not resolve to a real workspace.

### Shared Active Public Workspace Resolver

Changes implemented:

- Added `require_active_public_workspace(user_id, allowed_roles=...)` to re-load the stored active public workspace, verify it still exists, and verify the current user still holds an allowed role.
- Added `_get_active_public_workspace_or_error(user_id)` in the public prompt route module to translate resolver failures into stable `400` / `404` / `403` responses.
- Updated all public prompt CRUD routes to use the shared resolver instead of reading `activePublicWorkspaceOid` directly from raw settings.

Files involved:

- `application/single_app/functions_public_workspaces.py`
- `application/single_app/route_backend_public_prompts.py`

Security outcome:

Public prompt operations now depend on a single canonical active-workspace validation path instead of repeated direct settings reads.

### Settings Route Boundary Hardening

Changes implemented:

- Updated `POST /api/user/settings` to route `activePublicWorkspaceOid` through `update_active_public_workspace_for_user(...)`, mirroring the existing `activeGroupOid` handling.
- Updated the invalid-key handling so unsupported settings keys are stripped before persistence and the route returns `400` with `No valid settings keys provided` when nothing valid remains.

Files involved:

- `application/single_app/route_backend_users.py`

Security outcome:

The generic settings route no longer blindly merges arbitrary unsupported keys into the persisted user settings document.

### Setter Route Alignment

Changes implemented:

- Updated `PATCH /api/public_workspaces/setActive` to use `update_active_public_workspace_for_user(...)` as the only persistence path.
- Updated `/set_active_public_workspace` to use the same helper instead of writing `activePublicWorkspaceOid` directly through `update_user_settings(...)`.

Files involved:

- `application/single_app/route_backend_public_workspaces.py`
- `application/single_app/route_frontend_public_workspaces.py`

Security outcome:

All current active-public-workspace selection paths now share the same validation boundary before user settings are updated.

## Files Modified

- `application/single_app/functions_public_workspaces.py`
- `application/single_app/route_backend_users.py`
- `application/single_app/route_backend_public_workspaces.py`
- `application/single_app/route_frontend_public_workspaces.py`
- `application/single_app/route_backend_public_prompts.py`
- `application/single_app/config.py`
- `functional_tests/test_security_authorization_hardening.py`
- `functional_tests/test_stored_xss_admin_rendering_fix.py`
- `functional_tests/test_multimedia_support_reorganization.py`

## Validation

Testing approach:

- Extended the existing authorization hardening regression to cover the validated public-workspace write path, shared public prompt resolver adoption, and invalid-key filtering in `/api/user/settings`.
- Updated version-pinned functional tests to the current `config.py` version so the version bump remains internally consistent.
- Validated the touched Python files with targeted compile checks and reran the authorization hardening functional test after each implementation slice.

Validation performed for this implementation:

- `python -m py_compile application/single_app/functions_public_workspaces.py`
- `python -m py_compile application/single_app/route_backend_users.py`
- `python -m py_compile application/single_app/route_backend_public_workspaces.py`
- `python -m py_compile application/single_app/route_frontend_public_workspaces.py`
- `python -m py_compile application/single_app/route_backend_public_prompts.py`
- `python functional_tests/test_security_authorization_hardening.py`

## Before And After

Before:

- `activePublicWorkspaceOid` could be written through multiple routes without shared validation.
- `/api/user/settings` accepted unsupported keys after only logging a warning.
- Public prompt routes trusted the stored active public workspace setting through direct reads.

After:

- Every active-public-workspace setter route uses the same validated helper.
- `/api/user/settings` strips unsupported keys and rejects payloads that contain no valid settings keys.
- Public prompt routes resolve the active public workspace through a shared helper that revalidates existence and access.

## User Experience Impact

Normal valid workspace selection and prompt flows stay the same. The visible behavior changes are the intended secure outcomes:

- Invalid public workspace ids now fail with `404` instead of being silently stored.
- Unsupported settings payloads now fail with `400` when they contain no valid settings keys.
- Public prompt routes now return the expected scoped `400` / `404` / `403` responses when the stored active workspace is missing, stale, or unauthorized.