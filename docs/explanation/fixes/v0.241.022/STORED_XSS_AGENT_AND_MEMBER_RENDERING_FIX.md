# STORED_XSS_AGENT_AND_MEMBER_RENDERING_FIX.md

# Stored XSS Agent And Member Rendering Fix

Fixed in version: **0.241.017**

## Issue Description

Stored and reflected browser-side XSS risks existed in chat agent display-name rendering and in group/public workspace member-management surfaces that interpolated untrusted display names and emails into HTML or inline JavaScript.

## Root Cause Analysis

- Chat message rendering in `chat-messages.js` inserted `agent_display_name` into HTML without encoding in both the sender header and metadata drawer.
- Public and group workspace member-management scripts built HTML rows, option elements, summaries, and search-result buttons from raw `displayName` and `email` values.
- The public workspace search-result renderer embedded user data inside an inline `onclick` handler.
- `/api/userSearch` built a Microsoft Graph OData filter from the raw query string, allowing apostrophes to break the literal context.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/public/manage_public_workspace.js`
- `application/single_app/static/js/group/manage_group.js`
- `application/single_app/route_backend_users.py`
- `functional_tests/test_stored_xss_chat_workspace_rendering_fix.py`
- `ui_tests/test_public_workspace_member_rendering_escaping.py`
- `ui_tests/test_group_workspace_member_rendering_escaping.py`
- `application/single_app/config.py`

### Code Changes Summary

- Escaped `agent_display_name` before insertion into the chat sender header and message metadata drawer.
- Escaped public and group workspace member-management display names and emails before using them in table rows, request lists, ownership-transfer options, bulk-remove summaries, and CSV validation previews.
- Replaced the public workspace inline `selectUserForAdd(...)` handler with delegated click handling using `data-*` attributes.
- Added `_escape_graph_odata_literal(...)` to escape apostrophes before building the Microsoft Graph `$filter` expression for `/api/userSearch`.
- Added functional and Playwright regression coverage for the affected browser workflows.

### Testing Approach

- Static functional regression coverage verifies the escaped chat, group, public, and OData filter code paths.
- UI regression tests mock malicious payloads in public and group workspace member-management flows and assert that the payloads render as inert text with no DOM execution.

## Impact Analysis

- The fix preserves existing display behavior for normal names and emails.
- Search-result selection still populates the add-member form with the original string values.
- The OData fix only changes escaping behavior for embedded apostrophes and does not alter successful prefix-search behavior for normal queries.

## Validation

### Before

- Untrusted agent display names could render in chat HTML without encoding.
- Untrusted member display names and emails could render inside group/public workspace HTML and inline event handler attributes.
- Apostrophes in `/api/userSearch` could break the Microsoft Graph filter literal.

### After

- Chat and member-management surfaces HTML-encode untrusted display names and emails before insertion.
- The public search-result selection flow no longer embeds untrusted data inside inline JavaScript.
- `/api/userSearch` escapes apostrophes using the repo's established OData literal rule.