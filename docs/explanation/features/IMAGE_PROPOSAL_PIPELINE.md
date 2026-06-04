# Image Proposal Pipeline

Implemented in version: **0.241.135**

## Overview

The image proposal pipeline lets models and agents suggest generated images inside normal chat responses without generating images automatically. Assistant output can include fenced `simpleimage` JSON blocks, which the chat frontend renders as opt-in approval cards. Users can approve, edit, or cancel each card, and messages with more than two pending cards show an approve-all control at the bottom of the assistant message.

The feature uses the existing image generation model configuration and stores approved images in the chat-associated storage path before rendering them as normal chat image messages.

## Dependencies

- Image generation must be enabled in application settings.
- Existing Azure OpenAI or APIM image generation configuration is reused.
- Chat blob storage is used through the same generated chat image storage helper used for chat-associated artifacts.
- Frontend rendering uses local static JavaScript modules only.

## Technical Specifications

### Model Proposal Schema

Models and agents can emit proposals with fenced Markdown:

````markdown
```simpleimage
{
  "version": 1,
  "visualId": "slide_09_timeline",
  "title": "Timeline of major events, 1700-1750",
  "description": "An illustrated timeline showing key early American events between 1700 and 1750.",
  "prompt": "Create a horizontal illustrated timeline for 1700 to 1750 featuring key events with readable labels.",
  "visualType": "timeline",
  "slideNumber": 9,
  "context": "Major events"
}
```
````

### Backend Components

- `functions_image_generation.py`
  - Builds image proposal model guidance.
  - Normalizes image proposal payloads.
  - Creates the configured image generation client.
  - Generates and stores approved chat image messages.
- `route_backend_chats.py`
  - Adds image proposal guidance when image generation is enabled and the user asks for visual/slide/image-friendly content.
  - Adds `POST /api/chat/image-proposals/generate` for user-approved generation.
  - Authorizes personal chat access before generation.

### Frontend Components

- `static/js/chat/chat-inline-image-proposals.js`
  - Extracts `simpleimage` blocks before Markdown sanitization.
  - Injects inert placeholders into sanitized assistant HTML.
  - Hydrates placeholders into approval cards after chat message masking/restoration.
  - Calls the approval endpoint and appends the resulting image message.
- `static/js/chat/chat-messages.js`
  - Integrates image proposals with assistant rendering and final message hydration.
- `static/js/chat/chat-streaming.js`
  - Hydrates proposal cards during streaming, stopped-stream rendering, and error rendering.
- `static/css/chats.css`
  - Styles proposal cards, prompt editors, status text, and approve-all actions.

## Usage Instructions

1. Enable image generation in application settings.
2. Ask for visual-friendly content such as slide visuals, timelines, diagrams, illustrations, maps, or infographics.
3. When the assistant includes an image proposal card, choose one of the available actions:
   - **Approve** generates and stores that image.
   - **Edit** lets the user revise the image prompt before approval.
   - **Cancel** dismisses the proposal.
   - **Approve all image proposals** appears when a message has more than two pending proposal cards.

## Testing and Validation

- `functional_tests/test_image_proposal_pipeline.py` validates proposal normalization, guidance text, and settings gates.
- `ui_tests/test_chat_inline_image_proposal_cards.py` validates card rendering, approve-all, edit, and cancel workflows with the approval endpoint mocked by Playwright.
- Version was updated in `application/single_app/config.py` to `0.241.135` for traceability.

## Known Limitations

- The first implementation scopes approval to personal chat conversations because existing `/api/image/<image_id>` authorization is personal-conversation based.
- Image generation remains opt-in in chat. Future agent setup workflows can add agent-level auto-allow controls without changing the card renderer or storage helper.
