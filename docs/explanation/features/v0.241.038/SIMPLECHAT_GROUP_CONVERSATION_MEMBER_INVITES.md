# SimpleChat Group Conversation Member Invites

Implemented in version: **0.241.038**

Related config update:
- `application/single_app/config.py` now reports version `0.241.038`.

## Overview

This enhancement adds a dedicated SimpleChat capability for inviting current group members into an existing invite-managed group multi-user conversation. It complements `create_group_conversation` so an agent can first create the shared conversation and then explicitly add the right participants through the same collaboration permission model already used by the backend APIs.

## Dependencies

- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/static/js/agent_modal_stepper.js`

## Technical Specifications

Architecture overview:
- New SimpleChat capability key: `invite_group_conversation_members`
- New SimpleChat plugin function: `invite_group_conversation_members(conversation_id, participant_identifiers="")`
- The helper resolves participant identifiers through the existing directory lookup path and normalizes them into collaboration-user summaries before reusing `invite_personal_collaboration_participants(...)`.

Runtime behavior:
- `conversation_id` must point at a group multi-user collaborative conversation.
- Only invite-managed group conversations support member invitations.
- Only current members of the underlying group can be invited.
- The acting user still has to be a conversation owner or conversation admin.
- The capability returns the updated conversation plus the invited participant summaries and a result message suitable for agent follow-up.

Capability storage:
- The capability follows the existing SimpleChat capability map in both action defaults and agent-level overrides.
- Workspace and agent modals now expose a dedicated toggle labeled `Invite group conversation members`.

## Usage Instructions

1. Enable `Create group multi-user conversations` when the agent needs to start the shared conversation.
2. Enable `Invite group conversation members` when the agent also needs to add participants afterward.
3. Call `create_group_conversation` to create the invite-managed conversation.
4. Call `invite_group_conversation_members` with the resulting `conversation_id` and one or more emails, UPNs, or user IDs separated by commas or new lines.

## Testing And Validation

Functional coverage:
- `functional_tests/test_simplechat_group_conversation_member_invites.py`
- `functional_tests/test_simplechat_agent_action.py`
- `functional_tests/test_simplechat_group_multi_user_conversation.py`

UI coverage:
- `ui_tests/test_workspace_simplechat_action_modal.py`
- `ui_tests/test_agent_modal_simplechat_capabilities.py`

Validation focus:
- backend invite payload construction
- rejection for non-group conversations
- plugin metadata and forwarding
- workspace and agent capability toggle visibility and persistence