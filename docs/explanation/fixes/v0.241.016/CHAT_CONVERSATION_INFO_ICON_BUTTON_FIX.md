# Chat Conversation Info Icon Button Fix - Version 0.241.016

Fixed in version: **0.241.016**

## Issue Description

The conversation details button in the chat header displayed as a dark outlined circular button. This made the info affordance stand out more than intended.

## Root Cause Analysis

The button used Bootstrap's `btn-outline-secondary` class together with the chat icon button shape, creating a visible bordered circle around the `bi-info-circle` icon.

## Technical Details

### Files Modified

- `application/single_app/templates/chats.html`
- `ui_tests/test_chat_sidebar_toggle_controls.py`
- `application/single_app/config.py`

### Code Changes Summary

- Removed `btn-outline-secondary` from `#conversation-info-btn`.
- Added transparent background, no-border, and no-shadow states for the info button.
- Preserved hover color and keyboard focus visibility.
- Updated UI test coverage to prevent the outline class from returning.
- Updated `config.py` version to `0.241.016`.

## Testing Approach

- Python syntax checks for edited Python files.
- Jinja template parsing for the edited chat template.
- Focused UI test collection for chat sidebar/header coverage.

## Impact Analysis

The chat header now shows only the info icon for conversation details while retaining tooltip, click behavior, and accessible keyboard focus.

## Validation

Before: the info button showed a visually prominent outlined circular border.

After: the info button renders as a quiet icon-only action with no persistent border or background.
