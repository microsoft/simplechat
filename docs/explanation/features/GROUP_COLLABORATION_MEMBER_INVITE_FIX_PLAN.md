# Group Collaboration Member Invite Fix Plan

Planning version: **0.250.062**

Implemented in version: **Not implemented - discovery and planning only**

Related configuration version: `application/single_app/config.py` currently sets `VERSION = "0.250.062"`.

## Overview

This plan captures the investigation and proposed fix direction for a local MCP testing issue where adding a participant to an active group-scoped conversation calls:

```text
POST /api/collaboration/conversations/from-group/<conversation_id>/members
```

and returns `404 Conversation not found`.

The desired product behavior is intentionally narrow:

- Group-scoped collaborative conversations should support inviting **current group workspace members only**.
- SimpleChat should **not** add or invite arbitrary local users into a group workspace through the conversation participant flow.
- The add-participant UI should make that group-member-only scope clear.

No code changes are included in this document.

## Current Symptoms

Observed behavior:

1. In an active group-scoped chat, opening **Add participant** shows only one available user.
2. The modal copy says "Search recent collaborators or local users", which implies broader local-user search.
3. Inviting any shown user sends a request to:

   ```text
   /api/collaboration/conversations/from-group/<conversation_id>/members
   ```

4. The request returns 404 with a "Conversation not found" toast.
5. For personal conversations, adding a participant can show a similar stale "conversation not found" toast, but the participant is added and the flow moves on.

## Investigation Summary

Relevant frontend files:

- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/templates/chats.html`

Relevant backend files:

- `application/single_app/route_backend_collaboration.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_groups.py`
- `application/single_app/route_backend_users.py`
- `application/single_app/functions_simplechat_operations.py`

### Endpoint Selection

The client chooses the add-member endpoint in `chat-collaboration.js`:

- Existing collaborative conversation:

  ```text
  /api/collaboration/conversations/<conversation_id>/members
  ```

- Legacy personal single-user conversation:

  ```text
  /api/collaboration/conversations/from-personal/<conversation_id>/members
  ```

- Legacy group single-user conversation:

  ```text
  /api/collaboration/conversations/from-group/<conversation_id>/members
  ```

The failing route exists, so this is not a missing Flask route. The 404 most likely happens because the ID being sent to the `from-group` endpoint is not resolvable as a legacy group conversation in the group conversations container, or the active conversation DOM metadata incorrectly still looks like `group-single-user` after conversion.

### Group Candidate Search

For group conversations, candidate search is intentionally scoped to group membership:

```text
GET /api/groups/<group_id>/members?search=<term>
```

The group member endpoint returns users from the group's `users` collection. It does not search all local SimpleChat users.

For non-group personal conversations, candidate search uses:

```text
GET /api/user/collaboration-suggestions?query=<term>
```

That endpoint can search recent collaborators and local user settings records.

### Backend Group-Member Guardrail

Group collaborative invites are already constrained server-side. `functions_collaboration._normalize_group_conversation_participants(...)` resolves invitees against the group member lookup and rejects non-members with:

```text
Only current group members can be added to this shared conversation
```

This guardrail is correct and should remain.

## Goals

1. Keep group conversation participant invites limited to current group members.
2. Fix endpoint selection so already-collaborative group conversations use the collaborative member route instead of the legacy conversion route.
3. Make active conversation metadata reliable before participant invite actions run.
4. Clarify the participant picker UI copy for group conversations so admins/users understand they are searching group members, not all local users.
5. Suppress or avoid stale "Conversation not found" toasts after successful personal/group conversion.
6. Add regression coverage for endpoint selection, group member candidate scope, and stale source-conversation refresh behavior.

## Non-Goals

- Do not support adding arbitrary local users to group workspaces from the conversation participant modal.
- Do not auto-add local users to a group workspace as part of a conversation invite.
- Do not bypass group role checks or group status checks.
- Do not broaden the MCP group conversation invite tool beyond current group members.
- Do not change the backend group-member guardrail that rejects non-group members.

## Proposed Implementation Plan

### Phase 1: Confirm Runtime Metadata Shape

Capture browser-side metadata for failing cases before code changes:

1. Inspect the active conversation element for:

   ```js
   const id = "<conversation_id>";
   const el = document.querySelector(`[data-conversation-id="${id}"]`);
   el?.dataset;
   el?.getAttribute("data-chat-type");
   el?.getAttribute("data-group-id");
   ```

2. Confirm whether the active item reports:
   - `data-chat-type="group-single-user"` when it is already a collaborative group conversation.
   - missing or stale `data-conversation-kind`.
   - missing `data-can-manage-members`.

3. Confirm backend metadata response shape for the same conversation:
   - `chat_type`
   - `conversation_kind`
   - `can_manage_members`
   - group context
   - source conversation linkage fields

Expected outcome:

- Identify whether this is primarily stale client metadata, endpoint fallback logic, backend metadata serialization, or a source/collaboration ID mismatch.

### Phase 2: Fix Endpoint Selection

Update `chat-collaboration.js` so `addParticipantToConversation(...)` uses the collaborative member endpoint when the active conversation is already collaborative, including group collaborative conversations.

Target behavior:

| Conversation state | Expected endpoint |
| --- | --- |
| Legacy personal single-user | `/api/collaboration/conversations/from-personal/<source_id>/members` |
| Legacy group single-user | `/api/collaboration/conversations/from-group/<source_id>/members` |
| Existing personal collaborative | `/api/collaboration/conversations/<collab_id>/members` |
| Existing group collaborative | `/api/collaboration/conversations/<collab_id>/members` |

Implementation considerations:

- Prefer `conversation_kind === "collaborative"` over chat type alone.
- Treat `group_multi_user` as collaborative when metadata indicates a collaborative conversation.
- Avoid using a legacy conversion endpoint after conversion has already happened.

### Phase 3: Strengthen Metadata Refresh

Update the participant flow to rely on current metadata before opening or confirming the add-participant modal.

Possible approaches:

1. Ensure `selectConversation(...)` applies fetched metadata before participant actions are available.
2. Add a lightweight metadata refresh inside `openParticipantPicker(...)` when active DOM metadata is stale or incomplete.
3. After conversion, update or replace the active conversation item so subsequent actions target the new collaboration conversation ID.

Expected outcome:

- The UI does not keep using the hidden legacy source conversation after a successful conversion.
- Follow-up add-member operations use the collaboration conversation ID.

### Phase 4: Clarify Group Participant Picker Copy

Update `chats.html` and `chat-collaboration.js` so the modal copy changes based on the active conversation scope.

Suggested copy:

- Personal conversations:

  ```text
  Search recent collaborators or local users
  ```

  Help text:

  ```text
  Suggestions come from recent collaborators first, then local user settings records already stored in SimpleChat.
  ```

- Group conversations:

  ```text
  Search group members
  ```

  Help text:

  ```text
  Only current members of this group workspace can be invited to this shared conversation.
  ```

Empty state for group conversations:

```text
No eligible group members found.
```

This makes the non-goal explicit without changing backend authorization behavior.

### Phase 5: Backend Hardening

Keep the existing group-member-only server guardrail.

Consider adding a defensive backend improvement to the legacy conversion route:

- If `/from-group/<conversation_id>/members` receives an ID that already exists in the collaboration conversations container and is a group collaborative conversation, return a clearer `409` or delegate to the regular member invite path.
- If not delegating, return a more precise error:

  ```text
  Conversation is already collaborative; use the collaborative member endpoint.
  ```

This is optional but useful for diagnostics and future UI regressions.

### Phase 6: Personal Conversion Stale Toast Cleanup

For personal conversations, conversion appears to succeed while a stale "Conversation not found" toast can still surface.

Planned cleanup:

1. After conversion returns a new collaboration conversation ID, stop any pending refresh/load work against the hidden source conversation ID.
2. Select the returned collaboration conversation ID.
3. Suppress expected 404s for the old source ID when conversion has already succeeded.

Expected outcome:

- A successful conversion does not show a contradictory error toast.

## Test Plan

Add or update tests after implementation.

### JavaScript/UI Tests

Cover:

1. Legacy group single-user conversation uses `/from-group/<source_id>/members`.
2. Existing group collaborative conversation uses `/api/collaboration/conversations/<collab_id>/members`.
3. Group participant modal shows "Search group members".
4. Group participant modal help text says only current group workspace members can be invited.
5. Personal participant modal keeps existing recent/local-user copy.
6. Successful conversion selects the returned collaboration conversation ID and does not display a stale source-conversation 404 toast.

### Backend Functional Tests

Cover:

1. Group invite rejects participants who are not current group members.
2. Group invite allows current group members when the actor has permission.
3. Existing group collaborative conversation member invites use `invite_personal_collaboration_participants(...)` with the group guardrail intact.
4. Legacy group conversion returns clear errors for missing source conversation, missing group context, inactive group, or non-owner conversion attempts.
5. Optional: `/from-group/<id>/members` returns a clearer diagnostic when `<id>` is already a collaboration conversation ID.

### MCP Operation Tests

Cover:

1. `invite_group_conversation_members_for_current_user(...)` accepts only current group members.
2. Participant identifiers that resolve to local users outside the group are rejected with a clear message.
3. The MCP tool description remains clear that it invites current group members only.

## Acceptance Criteria

- Existing group collaborative conversations no longer call `/from-group/<id>/members` when adding participants.
- Legacy group single-user conversations still convert through `/from-group/<source_id>/members`.
- Only current group workspace members are searchable and inviteable from group-scoped conversations.
- The participant picker label and help text clearly distinguish group-member search from personal local-user search.
- Personal conversation conversion no longer surfaces a stale "Conversation not found" toast after a successful invite.
- Backend protections continue to reject non-group members for group collaborative conversations.
- UI and functional tests cover the routing, copy, and authorization behavior.

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| Stale DOM metadata still chooses the wrong endpoint | Refresh or apply authoritative metadata before participant actions. |
| Existing converted conversations keep old source IDs active in the UI | Select and cache the returned collaboration conversation ID after conversion. |
| Users expect local-user search in group conversations | Use explicit "Search group members" copy and group-only empty states. |
| MCP tool users pass local users who are not group members | Keep server-side group membership validation and improve error messaging. |
| Backend route changes could accidentally widen group access | Add tests proving non-members are rejected and group role checks still apply. |

## Open Questions

1. Should `/from-group/<id>/members` delegate when `<id>` is already a group collaborative conversation ID, or should it return a diagnostic error?
2. Should the UI show a one-line hint with the active group name in the participant picker?
3. Should group participant suggestions include pending group users, or only accepted/current group members? Current behavior should remain accepted/current members unless product requirements change.

