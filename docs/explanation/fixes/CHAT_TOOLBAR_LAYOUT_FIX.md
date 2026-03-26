# Chat Toolbar Layout Fix

Fixed/Implemented in version: **0.239.170**

## Issue Description

The chat toolbar could either leave an empty band above the chat input or let prompt and agent/model selectors crowd each other when the chat pane became narrower.

## Root Cause Analysis

- The selector and toggle controls are separate sibling groups, but the actions cluster can wrap internally as the available pane width shrinks.
- Without a medium-width breakpoint, that internal wrapping either created a blank band above the controls or forced the prompt and agent/model selectors to compete for the same row.
- The layout needed different behavior for wide, medium, and mobile widths instead of a single desktop rule.

## Technical Details

### Files Modified

- `application/single_app/static/css/chats.css`
- `application/single_app/config.py`
- `functional_tests/test_chat_toolbar_layout.py`

### Code Changes Summary

- Kept the selector and toggle controls as separate sibling groups.
- Updated the wide-layout toolbar flex rules so the controls stay on one row and align to the bottom edge.
- Added a medium-width breakpoint that promotes the actions and controls clusters to separate full-width rows before selector overlap can occur.
- Kept the mobile breakpoint wrapped behavior so the toolbar can still stack on narrow screens.
- Added a regression test to verify the sibling structure plus the wide and medium responsive layout hooks remain in place.

### Testing Approach

- Functional regression: `functional_tests/test_chat_toolbar_layout.py`

## Validation

### Before

- The selector dropdowns and the voice toggle could drop awkwardly or crowd each other, depending on the pane width.

### After

- The selector dropdowns and the voice toggle remain as separate sibling groups.
- On wide layouts they stay aligned on a single row.
- On medium widths they switch to clean full-width rows before prompt and agent/model controls can overlap.