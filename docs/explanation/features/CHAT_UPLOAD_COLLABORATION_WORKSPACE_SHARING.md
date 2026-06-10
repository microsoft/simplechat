# Chat Upload Collaboration Workspace Sharing

Implemented in version: **0.241.175**

## Overview

Personal multi-user collaborative conversations now keep chat-uploaded files in the uploader's personal workspace and automatically share those workspace-backed documents with accepted collaboration participants. Pending invitees do not receive access until they accept the invitation.

This extends the chat upload personal workspace handoff without creating duplicate workspace copies for every participant. The owner copy remains the source of truth, and SimpleChat manages collaboration-specific share grants on that document.

## Technical Specifications

### Architecture

- The `/upload` route resolves a visible personal collaboration conversation ID to its hidden source conversation before creating the source chat file message.
- Workspace document metadata records both the hidden source conversation and visible collaboration conversation IDs.
- The document sharing sync adds approved `shared_user_ids` entries for accepted participants, excluding the owner.
- Managed grants are tracked in `chat_upload_auto_shared_user_ids` so participants can be revoked when they leave, are removed, or the collaboration is deleted.
- Search chunk visibility is synchronized after share metadata changes so accepted participants can ask questions against the shared upload from that collaboration.

### API and Data Flow

1. The browser posts the upload with the visible collaboration `conversation_id`.
2. The backend validates the user can participate in the collaboration.
3. The backend resolves or creates the hidden collaboration source conversation.
4. The file is queued as a personal workspace document owned by the uploader.
5. Accepted participants are added to the document's approved sharing metadata.
6. The source file message is mirrored into the visible collaboration timeline.
7. The upload response returns the visible collaboration ID so the client stays in the collaborative chat.

### File Structure

- `application/single_app/route_frontend_chats.py` resolves collaborative uploads and mirrors workspace-backed file messages.
- `application/single_app/functions_documents.py` manages collaboration document share grants and chunk visibility.
- `application/single_app/functions_collaboration.py` syncs grants when participants accept, leave, are removed, or the conversation is deleted.
- `application/single_app/collaboration_models.py` preserves workspace file fields while mirroring messages.
- `application/single_app/static/js/chat/chat-input-actions.js` reloads collaborative uploads through the collaboration timeline loader.
- `application/single_app/static/js/chat/chat-collaboration.js` renders mirrored file messages with the existing workspace file card renderer.

## Usage Instructions

Users upload files from the chat input as usual. In a personal collaborative conversation, accepted participants automatically receive access to the workspace-backed file for that collaboration. If a participant accepts an invite later, SimpleChat syncs existing chat-uploaded workspace documents to that newly accepted participant.

If a participant leaves or is removed, SimpleChat removes only the collaboration-managed share grant. The document remains in the owner's personal workspace and continues to follow the workspace document retention policy.

## Testing and Validation

- Functional contract test: `functional_tests/test_chat_upload_collaboration_workspace_sharing.py`
- Existing handoff regression coverage: `functional_tests/test_chat_upload_personal_workspace_handoff.py`

The collaboration sharing test validates upload resolution, participant authorization, metadata stamping, approved sharing entries, search chunk propagation, membership lifecycle sync, message mirroring, collaboration file rendering, and the `0.241.175` version update.

## Known Limitations

Automatic sharing applies to personal multi-user collaborative conversations. Group collaboration document access continues to use the group workspace and group authorization model.