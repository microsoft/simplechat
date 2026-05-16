# Chat Comparison Source/Target And Uploads

## Overview

Version: 0.241.103

Implemented in version: **0.241.103**

This enhancement expands chat document comparison so users can stage one Source document and multiple Target documents in a split comparison board. The board now supports both workspace document versions and files uploaded directly into the active chat conversation.

Dependencies:

- Chat comparison UI in `templates/chats.html`
- Chat comparison state in `static/js/chat/chat-messages.js`
- Conversation-aware analysis/comparison resolution in `functions_search_service.py`, `functions_document_analysis.py`, and `functions_document_comparison.py`

## Technical Specifications

### Architecture Overview

The chat comparison flow still submits the existing backend contract with `left_document_id` and `right_document_ids`, but the user-facing experience now uses Source and Target terminology.

When a comparison request includes an active `conversation_id`, the document analysis/search layer can now resolve uploaded chat files from conversation messages and load their content for comparison alongside workspace documents.

### File Structure

- `application/single_app/templates/chats.html`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/functions_search_service.py`
- `application/single_app/functions_document_analysis.py`
- `application/single_app/functions_document_comparison.py`
- `application/single_app/route_backend_chats.py`

## Usage Instructions

1. Open the chat compare action.
2. Select workspace documents to load their available versions.
3. Drag or assign one item into Source.
4. Add one or more versions or uploaded chat files into Targets.
5. Run compare to evaluate the selected Source document against all chosen Targets.

Uploaded files appear automatically when they are part of the active conversation history.

## Testing And Validation

Functional coverage:

- `functional_tests/test_document_actions_and_comparison_feature.py`

UI coverage:

- `ui_tests/test_chat_document_action_selector_labels.py`
- `ui_tests/test_workflow_document_action_modal.py`

Performance considerations:

- Uploaded chat files are resolved only when a comparison/review request carries an active `conversation_id`.
- The chat board keeps the existing comparison payload shape to avoid widening downstream workflow contracts.