# Collaborative Image Proposal Rehydration Fix

Fixed/Implemented in version: **0.241.144**

## Issue Description

When a personal conversation with approved inline image proposal cards was converted into a multi-user conversation by adding a participant, the generated images could lose their inline placement. The shared conversation could render the saved generated image as a separate message and leave the original proposal card looking unapproved.

## Root Cause Analysis

Legacy-to-collaboration conversion creates new collaboration message IDs. Generated image messages preserved `metadata.image_proposal.source_assistant_message_id`, but that value still pointed at the old personal assistant message ID. The collaboration frontend also loaded messages one at a time and did not reuse the personal chat logic that folds saved generated proposal images back into their source assistant card.

## Technical Details

Files modified:

- `application/single_app/collaboration_models.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `functional_tests/test_collaboration_inline_image_proposal_porting_fix.py`
- `application/single_app/config.py`

Code changes summary:

- Added a pure metadata translator that rewrites `metadata.image_proposal.source_assistant_message_id` from the legacy assistant message ID to the copied collaboration assistant message ID.
- Applied that translation for both personal-to-collaboration and group-to-collaboration legacy message copy paths before saving copied messages.
- Exported the generated image proposal grouping helpers from the personal chat renderer.
- Updated the collaboration message loader and live event renderer to fold generated proposal image messages into the source assistant card instead of rendering a duplicate standalone image bubble.
- Updated the application version in `config.py` to `0.241.144`.

## Validation

Validation approach:

- Functional coverage verifies the metadata translation and the collaboration frontend folding contract.
- JavaScript syntax validation covers the changed chat modules.
- Python compile validation covers the changed backend modules and the new functional test.

Expected behavior:

- Adding a participant to a personal conversation with approved image proposal cards keeps generated images inline in the converted shared conversation.
- Reloading a collaborative conversation does not make already-approved image proposal cards ask for approval again.
- Generated proposal images that arrive while a shared conversation is open are attached to the rendered source assistant card when possible.