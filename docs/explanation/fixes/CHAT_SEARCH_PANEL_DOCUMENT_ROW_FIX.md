# Chat Search Panel Document Row Fix

Fixed/Implemented in version: **0.241.030**

## Issue Description

The chat grounded-search panel allowed the Document picker to wrap onto a second row for Search and Analyze on constrained desktop widths. Compare did not show the same visual issue, which made the action layouts feel inconsistent.

## Root Cause Analysis

The filter strip used a wrapping flex row. The Document picker had a large flex basis, so the browser made the wrap decision before the field could shrink into the available remaining space.

## Technical Details

Files modified:
- `application/single_app/static/css/chats.css`
- `application/single_app/config.py`
- `ui_tests/test_chat_search_panel_document_row_layout.py`

Code changes summary:
- Changed the desktop grounded-search filter strip to a four-column grid with bounded Action, Scope, and Tags columns plus a flexible Document column.
- Preserved the existing mobile drawer behavior, where the controls stack in a single column.
- Updated `config.py` from version `0.241.029` to `0.241.030` for traceability.

Testing approach:
- Added a Playwright UI regression test that validates Search and Analyze keep the Document picker on the same row at a constrained desktop width.
- Added mobile validation to ensure the Document picker still stacks below Tags without page-level horizontal overflow.

## Validation

Expected behavior after the fix:
- Search, Analyze, and Compare use a consistent single-row desktop layout for Action, Scope, Tags, and Document.
- Mobile and smaller canvas layouts continue to stack controls inside the drawer.
- The Document button fills its field and does not introduce horizontal scrolling.