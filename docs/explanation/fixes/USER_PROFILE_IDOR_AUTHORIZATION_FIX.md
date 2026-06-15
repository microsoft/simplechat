# User Profile IDOR Authorization Fix

Fixed/Implemented in version: **0.241.203**

## Issue Description

The `/api/user/info/<user_id>` and `/api/user/profile-image/<user_id>` endpoints accepted a caller-supplied Entra object ID and read the matching user-settings document directly from Cosmos DB. The routes were protected by login and User/Admin role decorators, but they did not verify that the authenticated caller was authorized to view the target user's profile metadata.

## Root Cause Analysis

The affected route handlers bypassed the existing user-settings access guard and called `cosmos_user_settings_container.read_item(...)` with the URL path value as both item ID and partition key. That created a horizontal authorization gap for profile metadata lookup by known user ID.

## Technical Details

Files modified:

- `application/single_app/route_backend_users.py`
- `scripts/check_broken_access_control.py`
- `functional_tests/test_user_profile_idor_authorization.py`
- `application/single_app/config.py`

Code changes summary:

- Added a user-profile authorization boundary before user-settings document reads.
- Allowed profile lookup only for the same user, Admin callers, shared group relationships, shared document relationships, or shared collaboration conversation relationships.
- Replaced direct route-level user-settings reads with `_read_authorized_user_profile_document(...)`.
- Removed full user document console logging from `/api/user/info/<user_id>`.
- Extended the Broken Access Control checker to flag direct `cosmos_user_settings_container.read_item(...)` calls from request-derived `user_id` values in `route_backend_users.py`.

## Validation

Testing approach:

- Added a focused functional regression test that verifies self lookup is allowed, unrelated low-privilege lookup is denied before the Cosmos user-settings read, Admin lookup is allowed, relationship-based lookups remain allowed, and the static BAC checker catches the old direct-read pattern.

Before/after comparison:

- Before: any authenticated User/Admin role holder could request another known user ID and receive profile metadata.
- After: profile document reads occur only after object-level authorization succeeds; unauthorized lookups receive a generic not-found/access-denied response.

Related version update:

- `application/single_app/config.py` was incremented from `0.241.201` to `0.241.203` across the endpoint authorization fix and generalized guardrail follow-up.