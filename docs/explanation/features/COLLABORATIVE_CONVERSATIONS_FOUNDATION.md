# Collaborative Conversations Foundation (v0.241.007)

Fixed and implemented in version: **0.241.007**

## Overview

This document describes the initial backend foundation for collaborative conversations in SimpleChat.
The implementation adds new collaboration-specific conversation, message, and user-state models without changing the current single-user chat behavior.

The goal of this first slice is to establish safe multi-user primitives before integrating the full collaborative chat user experience into the existing chat page.

## Dependencies

- Flask route registration and authentication decorators
- Azure Cosmos DB containers for collaborative conversations, messages, and per-user state
- Existing group RBAC enforcement via `assert_group_role(...)`
- Existing application cache infrastructure for replayable SSE event streams

## Technical Specifications

### Architecture Overview

The collaborative conversation foundation introduces three new persistence areas:

- `collaboration_conversations`
- `collaboration_messages`
- `collaboration_user_state`

Single-user conversations remain unchanged in the existing `conversations` and `messages` containers.
This keeps the current chat experience stable while the collaborative workflow is built incrementally.

### Conversation Modes

Two new collaborative conversation types are defined:

- `personal_multi_user`
- `group_multi_user`

Personal collaborative conversations:

- Use owner-managed invites
- Require invited users to accept before they can participate
- Are designed for personal and public knowledge only

Group collaborative conversations:

- Are visible to current members of one group
- Reuse group RBAC checks on every protected operation
- Are designed for one locked group plus optional public knowledge

### API Endpoints

The new backend route module exposes the following endpoints:

- `GET /api/collaboration/conversations`
- `POST /api/collaboration/conversations`
- `GET /api/collaboration/conversations/<conversation_id>`
- `POST /api/collaboration/conversations/<conversation_id>/invite-response`
- `POST /api/collaboration/conversations/<conversation_id>/members`
- `DELETE /api/collaboration/conversations/<conversation_id>/members/<member_user_id>`
- `GET /api/collaboration/conversations/<conversation_id>/messages`
- `POST /api/collaboration/conversations/<conversation_id>/messages`
- `POST /api/collaboration/conversations/<conversation_id>/typing`
- `GET /api/collaboration/conversations/<conversation_id>/events`

### Configuration

The foundation introduces a new setting in `functions_settings.py`:

- `enable_collaborative_conversations`

This setting is intended to control rollout while the broader collaborative UI and AI orchestration are implemented in later passes.

### File Structure

Key files added in this slice:

- `application/single_app/collaboration_models.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_collaboration.py`
- `functional_tests/test_collaborative_conversation_foundation.py`

## Usage Instructions

This slice is backend-first.
It establishes the conversation lifecycle, invite state model, human-message persistence, typing events, and a conversation-wide SSE stream for collaboration events.

Frontend integration is intentionally deferred so the current single-user chat experience is not destabilized while the shared experience is still under construction.

## Testing and Validation

Related functional test:

- `functional_tests/test_collaborative_conversation_foundation.py`

Validated behaviors in this slice:

- Personal collaborative conversation creation with pending invite state
- Invite acceptance transitions from pending to accepted
- Group collaborative conversation creation with a locked group scope
- Collaborative human-message document construction with reply linkage

## Known Limitations

- Existing `/chats` UI is not yet wired to the new collaboration APIs
- Explicit AI request orchestration for collaborative conversations is not yet connected to the existing chat generation pipeline
- Read receipts and presence are deferred beyond this initial foundation
- Personal collaborative knowledge sharing remains intentionally conservative until the shared-document workflow is added