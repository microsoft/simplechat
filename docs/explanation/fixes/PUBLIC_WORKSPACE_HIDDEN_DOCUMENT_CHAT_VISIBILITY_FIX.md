# Hidden Public Workspace Document Chat Visibility Fix - v0.250.200

Fixed in version: **0.250.200**

Related issue: [#1245](https://github.com/microsoft/simplechat/issues/1245)

Related version update: `application/single_app/config.py` was updated to `0.250.200` for this fix.

## Issue Description

When a user hid an accessible public workspace from the public directory, they could still visit the workspace and choose **Chat** for one or more documents. The Chat page appeared to carry the document selection, but the workspace remained absent from the public scope selector and its documents were excluded from grounded search.

## Root Cause Analysis

- Public workspace document chat links supplied the workspace and document IDs to the Chat page.
- The Chat page and public document endpoint intentionally loaded only workspaces enabled in the user's `publicDirectorySettings`.
- The handoff did not add the explicitly selected workspace to that visibility preference before the Chat page built its public workspace and document state.

## Technical Details

### Files Modified

- `application/single_app/route_frontend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_public_workspace_hidden_document_chat_visibility.py`

### Code Changes Summary

- The Chat route now recognizes explicit public document-search handoffs before it builds the public workspace selector.
- The caller-supplied workspace ID is resolved and access is revalidated before user settings are changed.
- A hidden workspace is added to `publicDirectorySettings` while all existing visibility choices are preserved.
- Already-visible workspaces do not trigger a redundant settings write.

### Testing Approach

- Added a focused functional regression test for hidden, already-visible, invalid-scope, malformed, and unauthorized handoffs.
- Verified that visibility is applied before visible public workspace data is loaded for the Chat page.

## Impact Analysis

- Choosing **Chat** for a document in an accessible hidden public workspace now makes that workspace available in Chat.
- The selected document can be loaded by the visible-workspace document endpoint and included in grounded search.
- Other public workspaces that the user has made visible remain visible.

## Validation

- The focused regression test passes all visibility, authorization, ordering, and version checks.
