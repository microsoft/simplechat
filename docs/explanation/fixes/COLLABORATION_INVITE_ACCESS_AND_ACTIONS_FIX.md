# Collaboration Invite Access and Actions Fix

Fixed/Implemented in version: **0.241.011**

## Issue Description

Personal conversations converted into collaborative conversations still had several broken invite and follow-up action paths.

- Pending invitees could hit a 403 when the chats page tried to load collaborative messages or connect to the shared event stream before they accepted.
- Invitees did not get a clear notification or prompt to review the invite.
- Metadata refreshes could strip the collaborative icon and related state from the conversation list.
- Converted personal shared chats lost expected per-user actions in the main and sidebar menus, leaving only a reduced collaboration-specific subset.

## Root Cause Analysis

The collaboration UI and route layer had partial support for converted personal chats, but several paths still assumed the legacy single-user conversation APIs.

- Message and event access checks required accepted membership even for pre-acceptance read-only access.
- Invite notifications depended too heavily on active conversation event flow instead of list-driven detection.
- Metadata update helpers preserved the pin icon but not other title icons or collaboration dataset flags.
- Main and sidebar menu actions continued calling legacy conversation endpoints for rename, pin, and hide.

## Files Modified

- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/static/js/chat/chat-sidebar-conversations.js`
- `functional_tests/test_collaboration_invite_access_and_actions_fix.py`
- `application/single_app/config.py`

## Code Changes Summary

- Allowed pending invitees to access collaborative message and event endpoints in read-only mode.
- Added pending invite notification and prompt handling in the collaboration client.
- Preserved collaboration icons and collaboration-specific dataset flags during metadata refreshes.
- Added a shared badge for `personal_multi_user` conversations.
- Added collaboration-aware rename, pin, and hide endpoints for personal collaborative conversations.
- Rewired main-list and sidebar actions to call collaboration endpoints when the selected item is collaborative.
- Guarded sidebar double-click title editing so non-managing collaborative participants are not dropped into a rename flow they cannot complete.

## Testing Approach

- Added a functional regression test that verifies:
  - pending invite access allowances remain in the collaboration routes
  - collaboration helper functions for title, pin, and hide remain available
  - collaboration invite notification hooks remain present in the browser client
  - main and sidebar action wiring continues to target collaboration endpoints

## Impact Analysis

- Invitees can now open a shared conversation and review it before responding to the invite.
- Converted personal collaborative chats retain core per-user actions expected in the existing chat UX.
- Collaboration state remains visibly consistent after metadata updates, reducing UI confusion.

## Validation

- Static diagnostics reported no new errors in the touched Python and JavaScript files.
- The new regression test provides focused coverage for the invite-access and action-wiring paths.