# AGENT_SELECTION_MODEL_ROUTING_FIX.md

## Agent Selection Model Routing Fix (v0.239.173)

Fixed/Implemented in version: **0.239.173**

### Issue Description

Per-user Semantic Kernel requests could fall back into model-only mode even when the selected
personal agent still existed. In that state, chats skipped agent invocation entirely and used the
standard GPT routing path instead.

### Root Cause Analysis

The per-user agent loader fetched personal agents correctly, merged any group agents, and then
reset `agents_cfg` back to an empty list before global-agent merge and agent selection. When
`merge_global_semantic_kernel_with_workspace` was enabled, that left only global agents in the
candidate set. Personal agents like `graph` were therefore invisible during selection even though
they were present in Cosmos.

### Technical Details

Files modified:
- `application/single_app/route_backend_agents.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_agent_selection_recovery.py`

Code changes summary:
- Added server-side validation so `/api/user/settings/selected_agent` only saves agents that are
  actually selectable for the current user and scope.
- Removed the candidate-list reset so personal agents remain available during merge and selection.
- Normalized per-user chat selection handling so dict-based `selected_agent` settings resolve to
  agent names correctly in the chat route.
- Bumped the application version and added regression coverage.

Testing approach:
- Added `functional_tests/test_agent_selection_recovery.py` to verify personal agents remain in
  the loader candidate set and invalid selections are rejected when saved.

Impact analysis:
- Prevents valid personal agents from being dropped during per-user merge logic.
- Keeps agent-routed chats on the agent’s configured model instead of dropping into the standard
  model-only fallback path.

### Validation

Before:
- Personal agents were loaded, but then removed from `agents_cfg` before selection.
- Requests then used the normal GPT model path rather than the selected agent model.

After:
- Personal agents remain in the per-user candidate set during global merge.
- Invalid agent selections are rejected when saved.
- Agent-enabled chats remain on the intended agent invocation path.