# Message Layered Masking

Implemented in version: **0.241.098**

## Overview

Layered message masking lets users add multiple text masks to a chat message and independently apply or remove a full-message mask. This avoids the previous binary behavior where masking an already-masked message could only clear every mask.

## Purpose

Users can now progressively hide more content from future model context without losing existing selected-text masks. The behavior applies to personal conversations, group-context conversations, personal collaborative conversations, and group collaborative conversations.

## Dependencies

* `application/single_app/config.py` version `0.241.098`
* Bootstrap Icons for mask action icons
* Cosmos DB message metadata fields: `metadata.masked` and `metadata.masked_ranges`
* Collaboration event stream for shared conversation updates

## Technical Specifications

### Architecture

Mask state is managed as two independent layers:

* Full-message mask: `metadata.masked`, `metadata.masked_by_user_id`, `metadata.masked_timestamp`, and `metadata.masked_by_display_name`
* Text-range masks: `metadata.masked_ranges`, with canonical `start`, `end`, `text`, user, and timestamp values

The shared masking logic lives in `functions_message_masking.py`. It validates selection offsets against stored message content, falls back only when selected text is unique, merges overlapping ranges, and preserves selected ranges when the full-message mask is removed.

### API Endpoints

* `POST /api/message/<message_id>/mask`
* `POST /api/collaboration/conversations/<conversation_id>/messages/<message_id>/mask`

Supported actions:

* `mask_all`: applies a full-message mask without clearing selected ranges
* `mask_selection`: adds and merges a selected text range
* `unmask_message`: removes only the full-message mask
* `clear_all_masks`: clears both full-message and selected-range masks
* `unmask_all`: legacy destructive clear-all behavior

The backend derives mask user identity from the authenticated session. The browser does not send `user_id` or `display_name` in masking payloads.

### Collaboration Sync

Collaborative message masking updates the collaboration message metadata and syncs mask metadata to linked source messages. This keeps shared UI state and future AI conversation history aligned for personal and group collaborative conversations.

The collaboration event stream publishes `collaboration.message.masked`, allowing visible shared messages to update without requiring a page reload.

## Usage Instructions

Use the mask button on a message footer:

* Select text and press the mask-plus control to add a text mask.
* Press the mask-plus control without a selection to apply a full-message mask.
* Press the mask-minus control while a full-message mask is active to remove only that full-message layer and preserve selected text masks.
* Press the mask-minus control when only selected text masks remain to clear those text masks.

## File Structure

* `application/single_app/functions_message_masking.py`
* `application/single_app/route_backend_chats.py`
* `application/single_app/route_backend_collaboration.py`
* `application/single_app/static/js/chat/chat-messages.js`
* `application/single_app/static/js/chat/chat-collaboration.js`
* `application/single_app/static/css/styles.css`
* `functional_tests/test_chat_layered_message_masking.py`
* `ui_tests/test_chat_message_layered_mask_controls.py`

## Testing and Validation

Coverage includes:

* Additive selected-text masking and range merging
* Full-message mask removal that preserves selected text masks
* Canonical stored-content validation for selected ranges
* Browser control rendering for mask-plus and mask-minus buttons
* Collaboration mask endpoint routing and event-driven UI updates

Known limitation: individual selected ranges are merged when adjacent or overlapping, so clearing one specific sub-range is not yet exposed as a separate UI action.

## Version Tracking

The application version was updated in `application/single_app/config.py` to `0.241.098` for this implementation. Functional and UI regression tests include the same version in their headers.