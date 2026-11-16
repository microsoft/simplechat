# Agent Editor Internal ID Exposure Fix

Fixed in version: **0.261.277**

## Issue

The shared agent editor, which is used for personal, group and global agents, showed internal identifiers that mean nothing to users:

- The header showed "Stable ID: <guid>", and a generic icon appeared instead of the agent's own logo (for example the Microsoft 365 PNG shown on the agents list).
- The Identity section repeated the stable ID.
- Model & connection → Current selection showed the Endpoint ID, the Model ID and raw provider codes such as `aoai`.
- The action picker showed `ID: <guid>` on every action.
- In Assigned knowledge, source workspaces showed `<scope> · <guid>` and documents showed `<workspace> · <guid>`. Unavailable references printed the raw key.

## Root cause

The editor was built as an authoring surface and rendered the stored references directly, because they were the only values guaranteed to exist.

## Changes

- `WorkspaceEditorFrame.tsx`: added an optional `iconNode` prop for the title tile.
- `AgentEditorPage.tsx`: passes `<AgentIcon icon={draft.icon} />`, the same component the agents list uses. The header subtitle is now the agent description instead of the stable ID.
- `AgentIdentityFields.tsx`: removed the stable ID line.
- `workspaceAgentAuthoring.ts`: `AgentModelChoice` now carries `endpointName`, and unnamed connections fall back to "Unnamed connection" instead of the endpoint ID.
- `AgentModelFields.tsx`: Current selection now shows **Deployment**, **Model**, **Connection** and **Provider**:
  - The provider shows its friendly label, such as "Azure OpenAI".
  - Values that are GUIDs are never shown; a readable fallback appears instead.
- `AgentActionPicker.tsx`: removed action IDs. Unresolved references show "Unavailable action [n]".
- `AgentKnowledgeFields.tsx`:
  - Workspaces show their type ("Personal workspace", "Group workspace" or "Public workspace").
  - Documents show the workspace and file name, and keep their tags.
  - Unavailable references use friendly text.
  - IDs are no longer part of the search text.

The stored data is unchanged. Only how it is presented changed.

## Validation

- `functional_tests/test_agent_editor_hides_internal_ids.py`
- `npm run typecheck` in `application/v2_ui`
