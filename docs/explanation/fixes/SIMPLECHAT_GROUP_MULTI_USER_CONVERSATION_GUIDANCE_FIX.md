# SIMPLECHAT_GROUP_MULTI_USER_CONVERSATION_GUIDANCE_FIX.md

# SimpleChat Group Multi-User Conversation Guidance Fix

Fixed/Implemented in version: **0.241.031**

> Note: This guidance was later superseded by invite-managed group multi-user conversations in version **0.241.034**. Group members now need to be added as conversation participants instead of inheriting access automatically through group membership.

## Issue Description

SimpleChat already supported creating a group collaborative conversation, but the capability text was vague enough that an agent could interpret it as a one-off group chat that still needed separate participant invites. In incident-style workflows this led to incomplete execution summaries such as creating the group and adding users, but reporting that the group conversation tool was unavailable or insufficient.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.031"`.

## Root Cause Analysis

- The existing capability label used the generic phrase `Create Group Conversations`.
- The existing tool description did not make it clear that this is the group multi-user conversation path.
- The existing result payload did not explicitly tell the agent that current and future group members inherit access through group membership without separate conversation invites.

## Technical Details

Files modified:

- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/static/js/agent_modal_stepper.js`
- `functional_tests/test_simplechat_group_multi_user_conversation.py`
- `ui_tests/test_agent_modal_simplechat_capabilities.py`
- `ui_tests/test_workspace_simplechat_action_modal.py`

Code changes summary:

- Renamed the user-facing capability label to `Create Group Multi-User Conversations`.
- Updated backend and plugin descriptions to state that the conversation is tied to group membership.
- Added an explicit plugin return message for the original group-membership model. That guidance is now superseded by the invite-managed participant flow introduced in `0.241.034`.
- Added a focused functional regression to lock the new guidance in place.

Testing approach:

- Functional test for metadata and result messaging.
- Existing SimpleChat capability and UI regressions updated to reflect the clarified label.

## Validation

Before:

- The agent could treat group conversation creation as ambiguous and report the tool as effectively unavailable for a multi-user incident flow.

After:

- The tool surface now clearly advertises that it creates the group multi-user conversation for the group itself.
- The return payload reinforces that added users do not need separate conversation invites.

Related functional tests:

- `functional_tests/test_simplechat_group_multi_user_conversation.py`
- `functional_tests/test_simplechat_agent_action.py`