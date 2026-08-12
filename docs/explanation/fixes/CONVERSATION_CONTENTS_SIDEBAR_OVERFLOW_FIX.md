# Conversation Contents Sidebar Overflow Fix

Fixed/Implemented in version: **0.250.169**

Related configuration update: `VERSION = "0.250.169"` in `application/single_app/config.py`.

## Issue Description

The shared Conversation contents / Used documents drawer could expose a horizontal scrollbar when a user message, document title, filename, classification, or workspace name exceeded the sidebar width. The document cards also displayed backend-oriented chunk counts and document IDs that added visual noise for normal users.

## Root Cause Analysis

- The list grids used automatic minimum tracks, so nowrap content could contribute its full intrinsic width before truncation was applied.
- Several document-card flex and text children did not have a zero minimum width.
- User-message labels allowed up to 72 displayed characters, which made the compact navigation entries unnecessarily wide.
- Conversation document tags retained filenames while collecting metadata but dropped the field from the final tag consumed by the drawer.
- Document cards repeated chunk counts and internal IDs even though cited pages and workspace scope were the useful user-facing details.

## Technical Details

### Files Modified

- `application/single_app/functions_conversation_metadata.py`
- `application/single_app/static/js/chat/chat-conversation-contents.js`
- `application/single_app/static/css/chats.css`
- `application/single_app/config.py`
- `functional_tests/test_document_action_conversation_scope_metadata.py`
- `ui_tests/test_chat_conversation_contents_drawer.py`
- `docs/explanation/features/CONVERSATION_CONTENTS_DRAWER.md`

### Code Changes Summary

- Preserved `file_name` on new and refreshed conversation document tags.
- Reduced contents labels to a maximum of 30 displayed characters including the ellipsis.
- Limited document cards to title, filename, cited pages, scope, and classification.
- Removed chunk-count and document-ID rows from the drawer.
- Reduced card spacing and typography while retaining selection and focus behavior.
- Added zero-minimum grid and flex sizing, maximum-width constraints, and visible-text ellipsis rules across both drawer tabs.
- Continued rendering untrusted message and document values with DOM APIs and `textContent`.

### Testing Approach

- Extended the document-action metadata functional test to cover new tags and existing-tag filename backfill.
- Extended the existing Playwright drawer test at desktop and mobile viewports to verify the compact field set, 30-character label behavior, XSS-safe rendering, and `scrollWidth <= clientWidth` for both tabs.
- Included a JavaScript syntax check and repository whitespace validation.

### Impact Analysis

- The authorized metadata endpoint, feature gates, drawer width, navigation, keyboard behavior, and responsive off-canvas behavior are unchanged.
- Existing conversation tags without a separate filename continue to show their title; refreshed and newly created tags can display a distinct source filename.
- Long values remain available as safe hover text while their visible rows stay within the sidebar.

## Validation

### Before and After

- **Before:** Long nowrap content could widen grid tracks, and document cards exposed chunk counts and backend IDs.
- **After:** Contents and document rows remain within the allocated drawer width and show only user-relevant metadata.

### Test Results

- `functional_tests/test_document_action_conversation_scope_metadata.py`: 5 tests passed.
- A local Playwright harness loaded the production module and stylesheet and confirmed the field set and no horizontal overflow at 1440px and 430px viewports.
- `ui_tests/test_chat_conversation_contents_drawer.py`: both authenticated viewport cases were collected and skipped because the required UI environment variables were not available locally.
- JavaScript syntax, Python compilation, and repository whitespace checks passed.
