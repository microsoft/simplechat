# Chat Comparison Modal Summary

## Overview

Version: 0.241.104

Implemented in version: **0.241.104**

The chat comparison editor now stays out of the main chat layout until users need it. The inline compare area was reduced to compact Source and Target tags with a single edit button, while the full comparison editor moved into a larger scrollable modal.

Dependencies:

- `application/single_app/templates/chats.html`
- `application/single_app/static/js/chat/chat-messages.js`
- existing conversation-aware comparison support from `functions_document_comparison.py` and `functions_search_service.py`

## Technical Specifications

### Architecture Overview

The comparison payload contract is unchanged. Chat still serializes one Source document through `left_document_id` and one or more Target documents through `right_document_ids`, but the visible compare surface is now split into:

- a compact inline summary bar with Source and Target tags
- a modal editor that contains the full Available Items, Source, and Targets board

This keeps the main chat input area compact while preserving the richer drag-and-drop comparison setup flow.

### File Structure

- `application/single_app/templates/chats.html`
- `application/single_app/static/js/chat/chat-messages.js`
- `functional_tests/test_document_actions_and_comparison_feature.py`
- `ui_tests/test_chat_document_action_selector_labels.py`

## Usage Instructions

1. Choose `Compare` in the chat document action selector.
2. Review the compact Source and Target tags under the document controls.
3. Select `Edit Compare` to open the larger comparison modal.
4. Use the modal to drag items or assign them into Source and Targets.
5. Close the modal with `Done` and continue chatting with the compact summary preserved inline.

## Testing And Validation

Functional coverage:

- `functional_tests/test_document_actions_and_comparison_feature.py`

UI coverage:

- `ui_tests/test_chat_document_action_selector_labels.py`

Performance considerations:

- The modal reuses the existing comparison selection state instead of reloading a separate compare workflow.
- The inline summary renders compact labels so long version details do not expand the chat composer area.