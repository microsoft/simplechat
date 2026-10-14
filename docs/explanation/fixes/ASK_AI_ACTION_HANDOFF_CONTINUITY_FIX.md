# Ask AI action setup continuity

Fixed in version: **0.261.333**

## Issue and root cause

Ask AI could draft an action while building a React agent, but its setup card
was only in the agent's Actions section. Opening the action editor and saving
correctly restored the agent draft and selected the action, while the Ask AI
conversation disappeared. The action editor's generic Back label also obscured
the return destination.

`useEditorAssist.ts` intentionally generated a fresh visit key on every editor
mount to isolate Undo from unrelated drafts. The action detour unmounted the
agent editor, so returning created a different conversation key and reset the
panel's local open state. Draft restoration alone did not preserve this session.

## Changes

- `EditorAskAiPanel.tsx` adds inline setup cards associated with actual pending
  action references and their originating turns. Cards show existing validation
  guidance and use the same finish-setup handler as the Actions section.
- `editorAssistHandoff.ts` temporarily retains the explicit editor visit,
  panel state, reading position, and pending-action Undo stash. The shared
  thread retains messages and unsent composer input. Sessions are scoped to the
  user, workspace and originating agent path, bounded in memory, and released on
  return or abandonment.
- `workspaceEditorDrafts.ts` can retain a clean draft for an explanatory
  conversation's detour without treating it as an unsaved-change warning.
- `AgentEditorPage.tsx` reuses the retained visit and resolves successful saves
  once. Cards show whether the saved action is currently selected. Earlier Undo
  cannot overwrite a saved-reference replacement; unrelated unchanged fields
  remain undoable.
- `WorkspaceEditorFrame.tsx` accepts a contextual Back label, and
  `ActionEditorPage.tsx` uses **Back to agent** and **Save action and return to
  agent** for validated return paths. Standalone action labels are unchanged.
- `App.tsx` releases abandoned handoffs and clears editor history on owner or
  authentication changes.
- `application/single_app/config.py` increments the patch version from
  `0.261.332` to `0.261.333`.

## Behavior and boundaries

Opening a setup card does not save anything. Saving an action writes only the
action, selects it for the agent, and restores the previous conversation.
The confirmation explicitly states that the agent is not saved yet. Returning
without saving still uses the existing unsaved-action confirmation.

Personal, group and administrator-owned global editors reuse the existing
permission and return-path boundaries. Removed or undone drafts have no live
setup link. Unselecting a saved action changes the status instead of continuing
to claim it is selected. Agent Undo never deletes a separately saved action.

Cards and handoff transcript metadata contain only safe labels and identifiers,
not action credentials or raw configuration. Credentials remain in the existing
action editor. No browser storage, server chat persistence, external runtime
assets, new permissions or SQL connection execution are added.
Refreshes and separate editor visits start fresh conversations. Existing
transcript limits still apply.

## Validation

`functional_tests/test_v2_editor_assist_handoff.mjs` executes the real handoff
and thread stores to cover repeated render reads, scoped paths, owner isolation,
retention during thread eviction, bounded cleanup and abandonment.

`ui_tests/test_v2_agent_action_ask_ai.py` exercises the real production bundle
and scripted server assist pipeline: SQL setup at desktop and mobile widths,
keyboard navigation, restored conversation/composer/focus, follow-up context,
Back/Cancel/browser Back, safe Undo, save failure and retry, multiple actions,
renamed actions, clean explanatory conversations and fresh visits.

The personal workspace, group agent and global editor browser suites also cover
their native action return paths and ensure an action save does not save the
agent. Existing agent/action assist logic tests cover safe views, secret
exclusion and draft patch behavior.

Validation results:

| Check | Result |
| --- | --- |
| `npm --prefix .\application\v2_ui run build` | Passed TypeScript compilation and production build |
| `node .\functional_tests\test_v2_editor_assist_handoff.mjs` | Passed lifecycle, retention, cleanup and isolation checks |
| `node .\functional_tests\test_v2_agent_editor_assist_logic.mjs` | Passed agent view and patch checks |
| `node .\functional_tests\test_v2_action_editor_assist_logic.mjs` | 7/7 passed |
| `python .\functional_tests\test_v2_assist_thread.py` | 14/14 passed, including 140 shared TypeScript logic checks |
| Production-bundle browser tests: Ask AI and global editor files, plus targeted personal/group action return and navigation cases | 41 passed |
| `python .\functional_tests\test_docs_app_surface_coverage.py` | 7/7 passed; regenerated inventory unchanged |
| `python .\functional_tests\test_docs_site_quality.py` | 6/6 passed |

Browser coverage ran with the existing local fallback,
`PLAYWRIGHT_SERVICE_URL=''`, and the fixture, functional-test and application
directories on `PYTHONPATH`. The fixture supplies the production assets and
scripted API responses; no live database, Azure service or language model was
contacted. Desktop and mobile screenshots confirmed the returned card and
composer without horizontal page overflow.

Before this fix, finishing setup returned to an empty, closed Ask AI panel.
Afterwards, the setup handoff returns to the same conversation and visibly
distinguishes a saved action from an unsaved agent.
