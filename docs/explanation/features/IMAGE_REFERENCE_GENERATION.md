# Image Reference Generation

Implemented in version: **0.250.021**

## Overview

Image Reference Generation lets chat image generation use selected images from the current conversation or enabled workspaces as visual references. The feature connects existing chat image uploads, generated chat images, and workspace image documents to the inline image proposal workflow.

## Purpose

Users can ask for images naturally in chat and approve inline image generation cards without toggling the Image toolbar button first. When a reference image is selected, SimpleChat saves or reuses the image in the appropriate writable workspace before generation and links the generated image back to the conversation and reference metadata.

Selected workspace images are only auto-collected as generation references when the user's message explicitly asks to create, generate, draw, design, or render a visual. General questions about a selected image continue through the normal chat/document context path.

When a selected workspace image is used for general Q&A, SimpleChat directly adds available image vision metadata to the model context so generic prompts such as "summarize" or "what is this image about" do not depend on search recall.

The selected-image context path initializes its citation/document list before streaming and non-streaming augmentation, preventing interrupted streams when no search result list has been built yet.

If a configured image generation deployment rejects reference-image bytes, SimpleChat falls back to text-to-image generation using the selected image's vision description and shows a warning on the generated card.

Reference-image edit requests use Azure OpenAI image API version `2025-04-01-preview` or later even when older image-generation defaults are present, because GPT-image reference editing requires the newer image edit API.

Saved reference and generated image workspace documents use readable filenames, the `conversations` tag, and chat-upload-style conversation link metadata so they remain traceable from the workspace document list.

## Dependencies

- Chat image generation must be enabled by an administrator.
- The selected image generation deployment must support reference-image generation/editing when references are used.
- Enhanced citation/blob storage must be available for persisted chat and workspace image content.
- Group workspace saves require `Owner`, `Admin`, or `DocumentManager` permissions.

## Technical Specifications

### Architecture

The feature adds an image-reference selection contract between the chat browser UI and the image generation backend:

- `chat-image-references.js` manages selected reference-image state in the chat composer.
- `chat-messages.js` adds existing chat images to the reference tray and includes saved references in `/api/chat` payloads.
- `chat-inline-image-proposals.js` includes saved references when approving inline image generation cards.
- `functions_image_generation.py` resolves references, validates image bytes, chooses the target workspace, saves reference copies, calls the provider reference-image surface, and stores generated output metadata.
- `route_backend_chats.py` passes reference payloads through both direct image generation and inline proposal approval endpoints.

### API Contract

Image generation requests may include:

```json
{
  "image_references": [
    {
      "source_type": "chat_image",
      "message_id": "conversation_image_message_id"
    },
    {
      "source_type": "workspace_image",
      "document_id": "workspace_document_id",
      "scope_type": "group",
      "group_id": "group_workspace_id"
    }
  ],
  "image_reference_target": {
    "scope_type": "group",
    "group_id": "group_workspace_id"
  }
}
```

If multiple writable group workspaces are active and no target is selected, the backend returns `409` with `requires_image_reference_target` and target options.

### Workspace Save Rules

- Personal workspace images stay in personal scope.
- Group workspace images can be used when the user can read the group image. Generated output saves to the selected writable group workspace.
- If multiple writable group workspaces are active, the user must choose one.
- If no writable group target is available, the UI can save to personal instead.
- Public workspace images are treated as read-only references. Reference copies and generated outputs save to personal workspace.
- Conversation images are saved into the resolved target workspace before generation.

### Metadata

Generated image messages include reference metadata without raw bytes:

- `image_references`
- `image_reference_target`
- `workspace_document`
- `image_proposal` when generated from an inline proposal

Workspace documents saved by this feature include `image_generation_reference` metadata for traceability.

## Usage Instructions

1. Ask for an image naturally in chat, or approve an existing inline image proposal card.
2. Use the image message menu to choose `Use as image reference`, or select image documents in the workspace picker and add them from the reference tray.
3. Click `Save` on each collected reference image.
4. If prompted, choose a group workspace save target.
5. Approve the image proposal.

If image generation is disabled, the user sees a message explaining that the request is possible but an administrator needs to enable image generation.

## Testing and Validation

- `functional_tests/test_image_reference_generation.py` validates target selection, reference metadata serialization, and provider dispatch behavior.
- `ui_tests/test_chat_image_reference_tray.py` validates the browser reference tray workflow when a Playwright chat test URL is configured.

## Known Limitations

- Phase 1 supports chat and workspace image references only.
- Web-discovered public image references are planned separately.
- Reference-image generation requires provider support for an image edit/reference input surface.
