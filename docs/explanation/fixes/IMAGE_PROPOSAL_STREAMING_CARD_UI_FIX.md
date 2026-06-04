# Image Proposal Streaming Card UI Fix

Fixed/Implemented in version: **0.241.137**

## Issue Description

Inline image proposal cards looked rough while streaming. The status appeared as a warning alert and could be broken up by leaked placeholder markup. Completed proposal cards also showed the full generation prompt by default, creating a noisy chat experience and making long generated text hard to scan.

## Root Cause Analysis

The image proposal placeholder HTML included its own replacement token as a data attribute. After replacing the markdown token with the placeholder, the injector performed a second generic token replacement and could replace the token inside the newly inserted HTML. This corrupted the opening tag and exposed `data-image-proposal` attributes in the chat message.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-inline-image-proposals.js`
- `application/single_app/static/css/chats.css`
- `application/single_app/config.py`
- `ui_tests/test_chat_inline_image_proposal_cards.py`

### Code Changes Summary

- Replaced the streaming warning alert with a chart-style card placeholder.
- Removed token-bearing attributes from inserted image proposal placeholders and made token injection avoid replacing inside newly inserted HTML.
- Hid the image generation prompt by default; it is only shown in the edit panel.
- Added wrapping and overflow handling for long titles, descriptions, badges, statuses, and prompt editor text.
- Bumped `config.py` version to `0.241.137`.

### Testing Approach

- Updated the Playwright UI regression test for image proposal cards.
- Added assertions for clean streaming placeholders, hidden prompts, edit visibility, and absence of leaked `data-image-proposal` text.

## Impact Analysis

The image proposal workflow remains opt-in and uses the same approval, edit, cancel, and approve-all actions. The visible experience is cleaner during streaming and less cluttered after the proposal is complete.

## Validation

- `node --check application/single_app/static/js/chat/chat-inline-image-proposals.js`
- `python -m py_compile ui_tests/test_chat_inline_image_proposal_cards.py`
- `python -m pytest ui_tests/test_chat_inline_image_proposal_cards.py` (skips unless `SIMPLECHAT_PLAYWRIGHT_CHAT_URL` is configured)
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`