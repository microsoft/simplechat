# Chat Search Dropdown Menu Width Fix

Fixed/Implemented in version: **0.241.031**

## Issue Description

The grounded-search filter strip kept the opened Scope, Tags, and Document dropdown menus the same width as their compact closed controls. This made workspace names, tags, and document titles difficult to read, especially in full-canvas and constrained canvas views. The document search field also appeared ineffective because filtered document rows were still forced visible by CSS.

## Root Cause Analysis

The dropdown sizing helper measured the closed filter field and applied that width directly to the opened menu. At the same time, document dropdown rows used a high-specificity `display: block !important` rule that overrode the searchable dropdown helper's `.d-none` hidden state.

## Technical Details

Files modified:
- `application/single_app/static/css/chats.css`
- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/templates/chats.html`
- `application/single_app/config.py`
- `ui_tests/test_chat_search_panel_document_row_layout.py`

Code changes summary:
- Made the closed Action and Scope controls more compact in the desktop filter grid while preserving a flexible Document column.
- Gave Scope, Tags, and Document menus independent preferred open widths with viewport-aware caps.
- Capped opened menu height so long lists scroll after roughly ten visible items instead of extending far up the canvas.
- Removed inline width and height styles from the chat filter markup so CSS and the dropdown sizing helper own layout behavior.
- Restored document search filtering by allowing `.d-none` to hide document rows.
- Updated `config.py` from version `0.241.030` to `0.241.031`.

## Validation

Testing approach:
- Extended the Playwright UI regression to confirm Search and Analyze still keep the Document picker on the desktop row.
- Added assertions that open Scope and Tags menus are wider than their closed controls, Document menu remains readable, and all opened menus have capped scrollable item regions.
- Added an assertion that a document row hidden by search resolves to `display: none`.
- Preserved mobile validation that the filter controls stack without horizontal overflow.

Expected behavior after the fix:
- Closed controls stay compact in full-canvas layouts.
- Opened workspace, tag, and document menus are wider and easier to scan.
- Long menus scroll within a capped height.
- Document search hides non-matching document rows correctly.
