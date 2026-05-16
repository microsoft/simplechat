# PowerPoint Artifact Export Source Fix

## Header Information

Fixed in version: **0.241.033**

Issue description:

Generated Markdown artifact cards contained the full slide material for a presentation, but the nearby `Create PowerPoint Presentation` action exported the short assistant summary message instead. Users saw the correct MD artifact attached to the chat, but the PowerPoint output did not reflect that artifact content.

Root cause analysis:

The frontend PowerPoint export request only sent the visible assistant `message_id` and `conversation_id`. The backend export route only loaded message `content`, while generated chat artifacts are stored as separate `role: file` message records with blob-backed Markdown content.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.033"`.

## Technical Details

Files modified:

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/static/js/chat/chat-message-export.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_per_message_powerpoint_export.py`
- `ui_tests/test_chat_inline_export_action_buttons.py`
- `ui_tests/test_chat_generated_tabular_output_card.py`

Code changes summary:

- Added `artifact_message_id` support to `/api/message/export-powerpoint`.
- Validated generated artifact ownership through the existing conversation/message authorization path.
- Restricted artifact-backed PowerPoint export to generated Markdown artifacts with blob-backed content.
- Downloaded the artifact blob and used its Markdown as the PowerPoint source content.
- Added a direct `Create PowerPoint` button to generated Markdown artifact cards.
- Updated the existing inline `Create PowerPoint Presentation` action to prefer an attached generated Markdown artifact when one is present.

Testing approach:

- Expanded the focused PowerPoint export functional test to verify artifact blob content becomes the export source.
- Added static regression checks for the `artifact_message_id` payload and generated artifact PowerPoint button.
- Updated UI regression coverage so inline PowerPoint actions prefer attached Markdown artifacts and generated Markdown artifact cards expose direct PowerPoint export.

## Validation

Before:

- The generated MD artifact could be downloaded or viewed, but PowerPoint export ignored it.
- PowerPoint output was based on the short assistant response rather than the full slide deck Markdown.

After:

- PowerPoint export can target the generated MD artifact backing the chat card.
- The existing inline PowerPoint button uses the attached Markdown artifact when available.
- The artifact card also offers an explicit `Create PowerPoint` action.

Related functional test:

- `functional_tests/test_per_message_powerpoint_export.py`