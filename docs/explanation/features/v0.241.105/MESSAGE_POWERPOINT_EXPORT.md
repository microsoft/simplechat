# Message PowerPoint Export

## Overview

Version: 0.241.105

Implemented in version: **0.241.105**

Chat message actions now include `Export to PowerPoint`, producing a `.pptx` deck from a single message. The exporter keeps the existing markdown-to-export formatting behavior, adds appendix slides for visuals, tables, code blocks, and citations, and attempts to reuse the same model deployment recorded on the source assistant message to reorganize the content into presentation-friendly slides.

Dependencies:

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/static/js/chat/chat-message-export.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-tutorial.js`
- `application/single_app/requirements.txt`

## Technical Specifications

### Architecture Overview

- The backend exposes `POST /api/message/export-powerpoint` alongside the existing Word and email draft export routes.
- The route loads the requested message, resolves a preferred model deployment from the message metadata when one is available, and asks the existing Azure OpenAI export client path for a slide-outline JSON plan.
- If model-based slide planning is unavailable, the exporter falls back to deterministic markdown sectioning so the deck is still generated.
- After the outline slides are built, the renderer appends supporting slides for inline visuals, markdown tables, fenced code blocks, and citations.

### File Structure

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/static/js/chat/chat-message-export.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-tutorial.js`
- `functional_tests/test_per_message_powerpoint_export.py`
- `functional_tests/test_chat_tutorial_selector_coverage.py`

## Usage Instructions

1. Open the three-dots menu on a chat message.
2. Select `Export to PowerPoint`.
3. Wait for the `.pptx` download to complete.
4. Open the presentation to review the AI-shaped outline slides first, then the appendix slides for visuals, tables, code, and references.

## Testing And Validation

Functional coverage:

- `functional_tests/test_per_message_powerpoint_export.py`
- `functional_tests/test_chat_tutorial_selector_coverage.py`

Performance considerations:

- Model planning input is capped before the AI call so very long messages do not balloon the outline prompt.
- Appendix slide counts are capped for visuals, tables, and code blocks to keep exported decks readable.

Known limitations:

- The AI plan is outline-focused, so highly bespoke slide layouts still require manual polishing after export.
- Supporting content such as tables and code blocks is preserved as appendix material rather than being merged into the main AI-generated storyline.