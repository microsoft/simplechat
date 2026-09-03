# Image Proposal Pipeline

Implemented in version: **0.241.135**
V2 interface support added in version: **0.261.029**

## Overview

The image proposal pipeline lets models and agents suggest generated images inside normal chat responses without generating images automatically. Assistant output can include fenced `simpleimage` JSON blocks, which the chat frontend renders as opt-in approval cards. Users can approve, edit, or cancel each card, and messages with more than two pending cards show an approve-all control at the bottom of the assistant message.

The feature uses the existing image generation model configuration and stores approved images in the chat-associated storage path before rendering them as normal chat image messages.

Both chat interfaces implement the pipeline against the same fence and the same endpoint, so a conversation started in one renders and behaves the same way in the other.

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

#### Classic interface

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

#### V2 interface

The V2 React UI renders the same fence as a component rather than as injected HTML, so it has
no extract/inject/hydrate step and no HTML sink to sanitize.

- `application/v2_ui/src/lib/imageProposalSpec.ts`
  - Parses and normalizes a `simpleimage` payload using the same caps as
    `normalize_image_proposal`, so a card cannot display or send a proposal the server would
    reject.
  - Reads `metadata.image_proposal` on stored image messages and matches an approved image
    back to the card that proposed it.
  - `proposalCardKey` names a card within its message, from the fence index
    `rehypeRichBlockIndex` stamps on each rich fence.
- `application/v2_ui/src/lib/imageProposalCardState.ts`
  - The state of one card — status, queue position, failure, edited prompt, editor open — and
    the reducer that patches it.
- `application/v2_ui/src/lib/imageProposalQueue.ts`
  - Runs approvals one at a time and reports queue position, so approving several proposals
    does not open several image generation requests at once.
- `application/v2_ui/src/components/chat/InlineImageProposal.tsx`
  - The approval card, its approve/edit/cancel states, and the approved image, which opens in
    the same viewer as any other chat image. Once the image exists the card shows the title,
    the image and the model that produced it; the proposal's description and badges describe an
    image that does not yet exist, so they are not repeated afterwards.
- `application/v2_ui/src/components/chat/ImageProposalContext.tsx`
  - Supplies each card with the assistant message it belongs to and the images already
    generated for that message, renders the approve-all control, and owns each card's state.
    That last point matters: a card is rendered from inside the markdown output, which React
    can rebuild at any time, so a card that held its own approval status would lose it — see
    `docs/explanation/fixes/V2_INLINE_IMAGE_PROPOSAL_STATUS_PERSISTENCE_FIX.md`.
- `application/v2_ui/src/components/chat/AssistantMarkdown.tsx`
  - Renders the fence as a card and, while a reply is streaming, shows a placeholder for a
    fence that has not finished arriving. Its react-markdown component map is memoised, because
    react-markdown uses those functions as element types and React rebuilds a subtree whenever
    an element's type changes.
- `application/v2_ui/src/components/chat/MessageList.tsx`
  - Files approved images under the assistant message that proposed them and takes them out of
    the flat thread once a card has claimed them.
- `application/v2_ui/src/stores/chatStore.ts`
  - `approveImageProposal` calls the endpoint and adds the stored image to the thread.

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
- `functional_tests/test_v2_inline_image_proposals.py` validates that the V2 card agrees with both the classic client and the server: the same fence language, the same sanitization caps, the registered endpoint path, the same approve-all threshold, and that generation is opt-in, serialized, and rendered without any HTML sink.
- `functional_tests/test_v2_inline_image_proposal_logic.mjs` executes the V2 parsing, result matching, card identity, card state and approval queue against the real modules, covering the cases where a mistake would render perfectly and still be wrong: a proposal approved after its prompt was edited, a prompt whose newlines the server flattened, several approvals started at once, and one card's progress disturbing another's.
- `functional_tests/test_v2_inline_image_proposal_status_persistence.py` validates that the markdown component map is memoised and that a card's approval state is owned by its message, so an approval still in flight keeps reporting itself when the card is rebuilt.
- Version was updated in `application/single_app/config.py` to `0.241.135` for traceability, to `0.261.029` when V2 support was added, and to `0.261.045` when V2 approval state was made to survive a re-render.

## Known Limitations

- The first implementation scopes approval to personal chat conversations because existing `/api/image/<image_id>` authorization is personal-conversation based. Approving inside a collaborative conversation is refused by the endpoint, and the V2 card reports that refusal rather than hiding it.
- Image generation remains opt-in in chat. Future agent setup workflows can add agent-level auto-allow controls without changing the card renderer or storage helper.
- In the V2 interface, a proposal cannot be approved until the response has finished streaming, because the assistant message the image would be filed under does not exist until then.
- Cancelling a proposal dismisses the card for the current view only. Nothing is written to the message, so the card returns when the conversation is reopened.
