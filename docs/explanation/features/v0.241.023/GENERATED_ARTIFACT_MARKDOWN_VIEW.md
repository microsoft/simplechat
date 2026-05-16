# Generated Artifact Markdown View

Fixed/Implemented in version: **0.241.023**

## Overview and Purpose

Generated Markdown artifacts in chat now include a `View MD` action next to `Download MD`. The action opens the generated file in a modal and renders the Markdown so users can inspect the artifact without downloading it first.

## Dependencies

- Chat generated analysis artifact metadata with `artifact_message_id` or `document_id`
- Existing authorized artifact download endpoints
- Browser-side `marked` and `DOMPurify` libraries loaded by the chat page
- Existing citation modal infrastructure in `chat-citations.js`

## Technical Specifications

### Architecture Overview

The generated artifact card detects Markdown artifacts by `output_format` (`md` or `markdown`) or by `.md` / `.markdown` file extension. When a Markdown artifact is detected, the card renders a `View MD` button alongside the existing download action.

Clicking `View MD` fetches the same authorized artifact content used for downloads and passes it to the citation modal with Markdown rendering enabled. The modal sanitizes `marked.parse(...)` output with `DOMPurify.sanitize(...)` before inserting it into the page.

### API Endpoints

- `GET /api/chat_artifacts/download?conversation_id=<id>&message_id=<id>`
- `GET /api/workspace_documents/download?doc_id=<id>`

### Configuration Options

No new configuration is required.

### File Structure

- `application/single_app/static/js/chat/chat-messages.js` adds the `View MD` action and artifact fetch logic.
- `application/single_app/static/js/chat/chat-citations.js` reuses the citation modal and adds safe Markdown rendering support.
- `application/single_app/static/css/chats.css` constrains rendered Markdown modal content.
- `ui_tests/test_chat_generated_tabular_output_card.py` covers rendered previews and the full Markdown modal view.

## Usage Instructions

When a chat response creates a Markdown artifact, users can choose:

- `Download MD` to save the file locally.
- `View MD` to render the generated Markdown in a modal.
- `Add to Workspace` when the artifact can be promoted into a workspace.

## Testing and Validation

The UI test injects a generated Markdown artifact card, verifies the preview renders Markdown, clicks `View MD`, and confirms the modal renders headings and bold text while stripping unsafe event-handler attributes.

## Known Limitations

The modal view is only shown for artifacts detected as Markdown. JSON, CSV, and other generated formats continue to use their existing download and preview behavior.