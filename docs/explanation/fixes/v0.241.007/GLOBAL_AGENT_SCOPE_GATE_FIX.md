# GLOBAL_AGENT_SCOPE_GATE_FIX.md

## Global Agent Scope Gate Fix (v0.241.007)

Fixed/Implemented in version: **0.241.007**

### Issue Description

Per-user Semantic Kernel chats could silently fall back to the standard GPT model
when a user selected a global agent from the chat UI. The frontend showed no
error because the selection API accepted the agent and the streaming request
included that `agent_info`, but the backend still dropped into model-only mode.

### Root Cause Analysis

The per-user loader treated every non-group agent as a personal agent during the
scope gate check. When `allow_user_agents` was disabled and
`merge_global_semantic_kernel_with_workspace` was enabled, selected global agents
were blocked before the loader reached the global-agent merge and selection path.

### Technical Details

Files modified:
- `application/single_app/functions_agent_scope.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/config.py`
- `functional_tests/test_global_agent_scope_gate.py`

Code changes summary:
- Added `is_selected_agent_scope_enabled()` to centralize scope gating for
  personal, global, and group agent selections.
- Updated `load_user_semantic_kernel()` so global agents bypass the
  `allow_user_agents` toggle while personal and group agent rules remain intact.
- Added regression coverage for the global-agent bypass, group-agent enforcement,
  and loader wiring.

Testing approach:
- Added `functional_tests/test_global_agent_scope_gate.py` to validate the scope
  helper behavior and confirm the per-user loader uses it.

Impact analysis:
- Global agents selected in per-user chat mode now remain on the agent invocation
  path instead of silently reverting to model-only GPT routing.
- Personal and group scope restrictions continue to behave as configured.

### Validation

Before:
- The backend logged `Using agent from request` and then immediately logged
  `User agents are disabled; skipping personal agent load.` for global agents.
- Requests fell back to `Loading core plugins only for model-only mode...`.

After:
- Global agent selections are no longer blocked by the personal-agent gate.
- Group selections still require `allow_group_agents`, and personal selections
  still require `allow_user_agents`.
- The regression test protects the shared scope gate and its loader integration.