# Chat Document Search Bulk Selection Fix

Fixed/Implemented in version: **0.241.032**

## Issue Description

When users typed in the Document dropdown search box and then used the top bulk action, the picker still selected every available document instead of only the documents visible in the filtered search results. This made Search, Analyze, and Compare workflows select a much broader document set than the user intended.

## Root Cause Analysis

The document bulk action calculated selection from the hidden `document-select` options. That hidden select knows which documents are available for the current scope and tag filters, but it does not know which dropdown rows are currently hidden by the document search text.

## Technical Details

Files modified:
- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/static/js/chat/chat-searchable-select.js`
- `application/single_app/config.py`
- `ui_tests/test_chat_search_panel_document_row_layout.py`

Code changes summary:
- Added a filter-applied callback to the reusable searchable dropdown helper.
- Updated the Document picker action label while users type in the document search box.
- Changed the top Document action to show `Select All Searched`, `Clear Searched`, or `No Matching Documents` when document search is active.
- Scoped bulk selection to visible searched document rows for Search, Analyze, and Compare.
- Disabled the bulk action when a document search has no matching documents.
- Updated `config.py` to version `0.241.032`.

## Validation

Testing approach:
- Extended the Playwright UI regression with a real `chat-documents.js` module fixture.
- Verified `Select All Searched` selects only matching searched document IDs for Search, Analyze, and Compare.
- Verified no-match searches disable the bulk action and do not select hidden documents.

Expected behavior after the fix:
- Searching documents and clicking the top action selects only the currently searched documents.
- Analyze and Compare bulk selection respects the same searched subset.
- No-match searches cannot accidentally select all available documents.
