# Ask AI in the Agent and Action Editors (v0.261.282)

## Overview

The V2 agent and action editors have an **Ask AI** panel that works like the workflow editor's.
A person describes what they want in plain language, for example "a helpdesk agent that answers
from our IT policy documents and can look up tickets", and the assistant fills in the unsaved
draft. Every changed field is highlighted, each turn lists its changes with **Jump to**, and
**Undo this change** takes a whole turn back. The assistant never saves, never sees or enters keys,
secrets or other credentials, and only offers what the person could choose in the editor.

In the agent editor the assistant can also draft up to three new actions for the agent. They are
created in the agent's workspace only when the agent is saved.

Implemented in version: **0.261.278** (the shared backend), **0.261.279** (agent editor),
**0.261.280** (action editor), **0.261.281** (drafted actions) and **0.261.282** (tests,
documentation and the drafted-action hand-off fix), tracked in `application/single_app/config.py`.

Dependencies:

- **Enable Agents** (`enable_semantic_kernel`) must be on.
- The deployment's instruction-drafting model deployment, the same one **Draft with AI** uses.
- The [workflow AI assistant](WORKFLOW_AI_ASSISTANT.md) rate limiter, which these editors share.

## Technical Specifications

### Architecture

The feature is one shared framework with two editor adapters.

- **Backend**: `functions_editor_assist.py` validates the request, builds the prompt from a
  *view* of the draft (its sections and fields, each with a kind, limits and allowed options),
  calls the model, and checks the answer. The model may only return values for fields the view
  described, within their limits and option lists, plus optional new items. The endpoint never
  receives or returns a whole record and writes nothing. `functions_editor_assist_runtime.py`
  runs the model call with a deadline, one correction retry and the shared rate limiter.
- **Frontend framework**: `lib/editorAssist.ts` defines the view, patch and change contract.
  `components/editorAssist/useEditorAssist.ts` runs turns, checks that the answer still matches
  the draft it was sent with, applies it, and records per-turn undo in `stores/editorAssistStore.ts`.
  `components/editorAssist/EditorAskAiPanel.tsx` is the side panel and header toggle, shown through
  `WorkspaceEditorFrame.tsx`'s side-panel slot.
- **Agent adapter**: `lib/agentEditorAssist.ts` describes and applies display name, description,
  instructions, model, assigned actions, completion token limit, reasoning effort and knowledge
  (whether to use it, workspaces, specific documents, tags and web pages). Agent type is shown
  read-only.
- **Action adapter**: `lib/actionEditorAssist.ts` describes and applies name, description, action
  type and, for the chosen type, its configuration fields, capabilities and sign-in method. Fields
  that hold secrets are never described, so their values never leave the browser.

### API endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /api/agents/assist` | Runs one Ask AI turn for an agent draft. |
| `POST /api/actions/assist` | Runs one Ask AI turn for an action draft. |

Both take `scope` (`personal`, `group` or `global`), `group_id` for group scope, the instruction,
recent turns and the draft view, and return a reply, a patch of changed values, warnings and, for
agents, any new items. They authorize by scope:

- **Global**: the signed-in user must be an administrator.
- **Group**: the user must hold a group role that may edit agents or actions, and the group must
  be available.
- **Personal**: `allow_user_agents` or `allow_user_plugins` must be on.

When the editor's toggle is off they return `agent_assistant_disabled` or
`action_assistant_disabled`. Request limits include a 2,000-character instruction, 20 earlier
turns, 300 fields and 80 operations per answer.

### Configuration

| Setting | Default | Effect |
| --- | --- | --- |
| `enable_agent_ai_assistant` | On | Shows Ask AI in the agent editor and allows `POST /api/agents/assist`. |
| `enable_action_ai_assistant` | On | Shows Ask AI in the action editor and allows `POST /api/actions/assist`. |

Both are in **Admin Settings > Agents and Actions** and take effect only while Enable Agents is on.
The bootstrap exposes them to the V2 app as `features.enable_agent_ai_assistant` and
`features.enable_action_ai_assistant`.

### Drafted actions

When no existing action fits, the agent assistant may return up to three new actions. Each is held
in the agent draft under a placeholder reference (`new:N1` and so on) and listed under **New
actions from Ask AI** in the Actions section, with any validation issues shown as **Needs attention
before saving**. Call agent actions are never drafted.

- **Save agent** first creates each drafted action in the agent's workspace, then saves the agent
  with the placeholders replaced by the new action IDs. A drafted action with validation issues
  blocks the save before anything is written.
- **Finish in action editor** opens the new-action editor already filled in with the drafted
  action. Saving it returns to the agent and replaces that placeholder with the new action. The
  hand-off is recorded in the same in-memory draft cache as the created-action hand-off, scoped to
  the owner and workspace.
- **Remove** drops a drafted action. Undoing the turn that drafted it does the same, and undoing a
  later turn that removed it brings it back.

## Usage Instructions

1. Open an agent or action in the V2 editor, for a personal, group or global agent or action.
2. Select **Ask AI** in the editor's header and describe what you want.
3. Review the highlighted fields. Use **Jump to** to see a change in its section, or **Undo this
   change** to take the turn back.
4. Enter any credentials yourself, then save as usual.

The guides [Create an agent](../../guides/create-an-agent.md) and
[Create an action](../../guides/create-an-action.md) walk through this for people building agents.

## Testing and Validation

- `functional_tests/test_editor_assist_core.py`: request validation, prompt building and answer checking.
- `functional_tests/route_tests/test_editor_assist_policy.py`: scope authorization, feature toggles and route policy.
- `functional_tests/test_v2_agent_editor_assist_logic.mjs`, `test_v2_action_editor_assist_logic.mjs`
  and `test_v2_agent_drafted_actions_logic.mjs`: the adapters' describe and apply logic.
- `ui_tests/test_v2_agent_action_ask_ai.py`: an agent turn applied and undone, a drafted action
  finished in the action editor and saved with the agent, an action turn that never sends the
  stored key, and the panels hidden while the toggles are off.
- `ui_tests/test_v2_group_action_drafts.ts` (run by `test_v2_group_actions.py`): the drafted-action
  hand-off never crosses a workspace boundary.

### Known limitations

- The assistant can't set the endpoint for action types without a native definition, other than
  OpenAPI and MCP. A drafted action of such a type shows "Endpoint is required" and must be
  finished in the action editor.
- It never enters credentials, uploads or fetches OpenAPI specifications, or saves.
- Drafted actions live only in the browser tab until the agent is saved.
