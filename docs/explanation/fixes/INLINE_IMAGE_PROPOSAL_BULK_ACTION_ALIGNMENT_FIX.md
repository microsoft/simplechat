# Inline Image Proposal Bulk Action Alignment Fix

Fixed/Implemented in version: **0.241.142**

## Issue Description

The `Approve all image proposals` button appeared visually detached from the assistant message content, sitting toward the middle of the chat bubble instead of aligning with the inline image proposal card flow.

## Root Cause Analysis

The bulk action container was constrained to the image proposal card width and also used Bootstrap right alignment. On wide assistant messages, that placed the button near the middle of the available message area.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-inline-image-proposals.js`
- `application/single_app/static/css/chats.css`
- `ui_tests/test_chat_inline_image_proposal_cards.py`
- `application/single_app/config.py`

Code changes summary:

- Changed the bulk action container from right-aligned to left-aligned.
- Kept the bulk action constrained to the proposal card column while allowing it to fill that column predictably.
- Added UI regression coverage that checks the left-aligned class is present and the right-aligned class is absent.

## Validation

Validation commands:

- `node --check application/single_app/static/js/chat/chat-inline-image-proposals.js`
- `python -m py_compile application/single_app/config.py ui_tests/test_chat_inline_image_proposal_cards.py`
- `python -m pytest ui_tests/test_chat_inline_image_proposal_cards.py -q`

Expected behavior:

- The `Approve all image proposals` button appears left-aligned with the image proposal card column.
- Bulk approval behavior remains unchanged.