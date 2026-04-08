# AI Message Minimum Width Fix

Fixed/Implemented in version: **0.240.084**

Related config.py update: `VERSION = "0.240.084"`

## Issue Description

Short AI messages could render with bubbles that were too narrow to comfortably fit the assistant message action buttons.

## Root Cause Analysis

Assistant message bubbles inherited the default message bubble minimum width of `250px`. That width was too tight for the assistant footer controls when the response content was only a few words long.

## Technical Details

### Files Modified

- `application/single_app/static/css/chats.css`
- `application/single_app/config.py`
- `functional_tests/test_chat_ai_message_min_width_fix.py`

### Code Changes Summary

- Increased the assistant bubble minimum width to `min(320px, 90%)`.
- Kept the change scoped to AI messages so user, file, and image bubbles retain their existing sizing.
- Bumped the application version for traceability.

### Testing Approach

- Added a functional regression test that verifies the AI bubble CSS rule, version bump, and fix documentation alignment.

### Impact Analysis

- AI messages with very short text now reserve enough horizontal space for the action row.
- Narrow layouts still remain bounded because the new minimum width respects `90%` of the available container width.

## Validation

### Test Results

- Functional regression test added in `functional_tests/test_chat_ai_message_min_width_fix.py`.

### Before/After Comparison

- Before: short assistant messages could appear cramped, causing action buttons to compete for limited width.
- After: short assistant messages keep a larger minimum bubble width, improving action button visibility.

### User Experience Improvements

- Short AI replies now look more consistent.
- Footer controls have more predictable space without changing the general chat layout.