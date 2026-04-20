# Workflow Visualization Conversation Mirror Fix

Fixed in version: **0.241.052**

## Issue Description

Workflow runs could report that they created an inline visualization such as an Azure Maps view, but the visualization never appeared in either of the places users actually needed it:

1. the workflow conversation itself
2. the personal or collaborative conversation the workflow created during the run

The result was a text-only assistant reply that said a map had been created even though the rendered map card was missing from both conversations.

## Root Cause Analysis

- Agent workflow execution stored only the assistant reply text in `functions_workflow_runner.py` and discarded the plugin invocation payloads that normal chat persists as `agent_citations`.
- Inline maps render from structured citation payloads such as `render_type` plus `map_payload`, not from plain text.
- Created conversations seeded through the SimpleChat plugin received only the initial user-authored message, so there was no assistant-side visualization payload to render there either.
- Collaborative conversations do not rely on workflow-chat assistant artifact hydration in the same way as personal chats, so mirrored visualization payloads need to be present directly on the collaboration message.

## Version Implemented

- **0.241.052**

## Files Modified

- `application/single_app/functions_workflow_runner.py`
- `application/single_app/config.py`
- `functional_tests/test_workflow_visualization_conversation_mirroring_fix.py`
- `functional_tests/test_scope_lock_collaboration_unlock_fix.py`

## Code Changes Summary

- Added workflow-side extraction of detailed plugin invocations and converted them into `agent_citations` for agent workflow runs.
- Persisted workflow assistant citation artifacts on the workflow conversation assistant message so inline maps can render in the workflow conversation itself.
- Added a workflow visualization mirroring path that identifies newly created SimpleChat conversations and posts a mirrored assistant response into them.
- Mirrored visualization payloads directly into collaborative conversations with `mirror_source_message_to_collaboration(...)` and into personal conversations with a dedicated assistant-message persistence helper.
- Scoped created-conversation mirroring to visualization-style citations so the handoff stays focused on renderable outputs instead of copying every tool invocation.

## Testing Approach

- Added `functional_tests/test_workflow_visualization_conversation_mirroring_fix.py`.
- Updated the latest version-sensitive functional test so its config version assertion stays aligned with `config.py` after this change.

## Impact Analysis

- Workflow conversations now preserve the structured agent citations required to render inline maps and similar visualization payloads.
- Created conversations now receive the same visualization output instead of only the user seed message, so the rendered artifact appears where the workflow said it created it.
- Personal and collaborative conversations both follow their existing storage models without introducing a new container or a parallel workflow-specific message format.

## Validation

- Before: the workflow conversation and the created conversation both showed only text such as “Created map visualization.”
- After: the workflow conversation stores the visualization citation payload, and the created conversation receives a mirrored assistant message that can render the created visualization.