# Agent Chat Launch Selection Fix

Fixed in version: **0.240.075**

## Issue Description

Selecting an agent from workspace or group agent lists redirected users to the chat page, but after multi-endpoint migration the chat experience could still open in model-selection mode instead of agent mode. That made the saved agent selection appear to be lost even though the redirect completed.

## Root Cause Analysis

- Workspace and group agent launch buttons saved `selected_agent`, then redirected to `/chats`.
- The chat page only shows the agent selector when the user setting `enable_agents` is true.
- Multi-endpoint chat keeps the model selector visible by default, so redirecting without also enabling agent mode left the selected agent hidden behind the model picker.

## Technical Details

### Files Modified

- `application/single_app/route_backend_agents.py`
- `application/single_app/static/js/workspace/workspace_agents.js`
- `application/single_app/static/js/workspace/group_agents.js`
- `functional_tests/test_chat_agent_workspace_launch_selection.py`

### Code Changes Summary

- The selected-agent API now sets `enable_agents = True` whenever a user explicitly launches chat with an agent.
- Workspace and group agent launch payloads now include the canonical agent ID and display name so chat can restore the exact agent more reliably.
- A focused regression test now verifies that explicit workspace and group launches both preserve agent selection and open chat in agent mode.

## Validation

- Verified the selected-agent API persists both `selected_agent` and `enable_agents`.
- Verified workspace and group launch payloads include scope-aware agent metadata.
- Added functional coverage in `functional_tests/test_chat_agent_workspace_launch_selection.py`.

## Impact

- Personal and group workspace agent launches once again behave like an explicit “chat with this agent” action.
- Multi-endpoint deployments no longer land users on the chat page with the chosen agent hidden behind the model selector.