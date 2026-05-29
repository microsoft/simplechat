# Global Agent Chat Selection Fix - v0.241.122

Fixed in version: **0.241.122**

Related version update: `application/single_app/config.py` was updated to `0.241.122` for this fix.

## Issue Description

When application-level agents were enabled but Workspace Mode was disabled, the Chat page did not render the Agents button. Users could not visibly select the global `researcher` agent, but backend chat paths could still use the stored global selected agent or Semantic Kernel fallback behavior during richer chat flows.

## Root Cause Analysis

- The Chat template rendered the Agents button only when both `enable_semantic_kernel` and `per_user_semantic_kernel` were true.
- The Chat frontend preload catalog only included global agents when Workspace Mode merged global agents into workspace agents.
- The backend chat route fell back to stored `selected_agent` or `global_selected_agent` settings when the request did not include an explicit `agent_info` payload.
- Non-streaming chat also allowed Semantic Kernel orchestrator/kernel fallback steps even when no request agent was selected.

## Technical Details

### Files Modified

- `application/single_app/templates/chats.html`
- `application/single_app/route_frontend_chats.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_global_agent_chat_selection_visibility.py`

### Code Changes Summary

- The Chat page now renders the Agents button whenever app agents are enabled.
- Global agents are now included in the Chat agent catalog for global agent mode, and still included in workspace mode when global merge is enabled.
- Chat response generation now requires an explicit request `agent_info` selection before invoking an agent.
- The stored global selected agent is no longer written into message metadata unless the frontend sent an explicit selected agent.
- Non-streaming Semantic Kernel orchestrator/kernel fallback is gated behind an explicit selected agent.

### Testing Approach

- Added `functional_tests/test_global_agent_chat_selection_visibility.py` to verify the template gate, global agent catalog preload, and no-silent-fallback route behavior.

## Impact Analysis

- In global agent mode, users can now visibly enable Agents in Chat and select from global agents.
- If the user does not enable/select an agent in Chat, normal model chat remains model-only.
- Rich chat flows such as tabular analysis and search augmentation can still run their own deterministic helpers, but final agent invocation requires a visible explicit agent selection.

## Validation

- Regression coverage verifies global agents are exposed in Chat and stored default agents are not used as hidden runtime fallbacks.