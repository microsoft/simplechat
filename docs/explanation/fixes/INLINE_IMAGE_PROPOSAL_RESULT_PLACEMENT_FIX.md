# Inline Image Proposal Result Placement Fix

Fixed/Implemented in version: **0.241.140**

## Issue Description

Approved inline image proposal cards generated images successfully, but the generated image was appended as a separate conversation image message instead of appearing where the proposal card was approved.

## Root Cause Analysis

The approval client called the normal image-message append path after generation. The saved image message already carried proposal metadata, but the chat loader did not use that metadata to associate generated images back to the assistant message that requested them.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-inline-image-proposals.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/css/chats.css`
- `application/single_app/route_backend_chats.py`
- `ui_tests/test_chat_inline_image_proposal_cards.py`
- `application/single_app/config.py`

Code changes summary:

- Generated image proposal approvals now render the returned image inside the original proposal card.
- Multiple approved proposals are queued client-side and cards show queued/generating/completed status in order.
- Saved generated image messages with `metadata.image_proposal.source_assistant_message_id` are folded back into their source assistant proposal card during conversation reload.
- The approval endpoint returns only the proposal association metadata needed by the frontend.

## Validation

Validation commands:

- `node --check application/single_app/static/js/chat/chat-inline-image-proposals.js application/single_app/static/js/chat/chat-messages.js`
- `python -m py_compile application/single_app/route_backend_chats.py ui_tests/test_chat_inline_image_proposal_cards.py`
- `python -m pytest ui_tests/test_chat_inline_image_proposal_cards.py -q`

Expected behavior:

- Approving one proposal replaces the proposal card contents with the generated image.
- Approving several proposals queues them and updates each card as it starts and completes.
- Reloading the conversation keeps generated proposal images inline with their original cards instead of showing duplicate standalone image bubbles.