# Workflow Draft Instructions Assistant Gate Fix

Fixed in version: **0.261.215**

The application version is recorded in `application/single_app/config.py`.

Related: #1548 (Phase 3 of the [chat orchestration workflows roadmap](../features/CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md)), part of #1543.
Found while reviewing Phase 3c (#1593).

## Issue

The admin setting **Enable AI Workflow Assistant** (`enable_workflow_ai_assistant`, on by default, personal
workflows only) didn't stop personal AI drafting of workflow task instructions.

`POST /api/workflows/draft-instructions` calls the draft-instructions model to write a task's instructions. It
checked personal workflow access and the `WorkflowUser` role, but not the assistant setting. With the assistant
turned off:

- The V2 editor hid **Draft with AI**, but that only hid a button.
- The classic workspace's personal workflow modal still offered **Task Brief** and **Draft Workflow
  Instructions**, and the button still drafted instructions.
- Anyone who could edit personal workflows could call the route directly and get a model-written draft.

## Root cause

The setting was enforced only by the `workflow_assistant_required` decorator, which wraps the V2 editor's
**Ask AI** route (`POST /api/user/workflows/assist`). The draft route predates the assistant and serves both
personal and group scopes, so it wasn't given the decorator, and nothing else checked the setting for it. The
V2 editor followed the setting by hiding its button, and the classic page didn't look at it at all.

## Resolution

### Server

In `draft_workflow_instructions`, the personal branch now checks the assistant after the existing personal
access check:

1. `_assert_personal_workflow_draft_access(settings)` runs first, unchanged. Personal workflows that are off
   still get 400 `Personal workflows are disabled.`, and a missing `WorkflowUser` role still gets 403
   `Personal workflows require the WorkflowUser app role.`
2. `is_workflow_assistant_enabled_for_user(settings, user_roles=...)` then decides whether the assistant is
   available to the signed-in user, using the roles in the session. When it isn't, the route returns 403 with
   the decorator's body:

   ```json
   {"error": "The AI workflow assistant is not available.", "code": "workflow_assistant_disabled"}
   ```

   No model client is created and no model call is made.

The order matters. The helper also returns False when personal workflows aren't available, so checking it
first would replace the personal-workflow 400 and the role 403 with the assistant's 403.

The check runs before the route's "Provide a task brief..." 400, so an empty personal request also gets the
assistant's 403 when the assistant is off.

The route isn't wrapped in `workflow_assistant_required`, because that would refuse group requests too.
`_assert_personal_workflow_draft_access` isn't changed, because other workflow routes use it.

### Group scope

Group drafting is unchanged. The setting is documented as personal-only, and group drafting stays governed by
the group workflow settings and the caller's group role. Whether group workflows should get an AI drafting
setting of their own is to be revisited with Phase 7 (#1550).

### Classic workspace

`/workspace` now overrides `enable_workflow_ai_assistant` in the sanitized settings it gives the template with
the same role-aware result, as it already does for `allow_user_workflows` and `enable_url_access`. The value is
a boolean computed on the server, and no raw setting is passed through.

`workspace.html` renders the personal **Task Brief** box, the **Draft Workflow Instructions** button and its
status line only when that value is true. The brief only feeds the draft request and isn't saved, so hiding the
button alone would have left an input that does nothing. `workspace_workflows.js` already treats all three
elements as optional, so nothing else changes. **Task Instructions** stays, so people can still write
instructions themselves.

The group workspace's controls in `group_workspaces.html` are unchanged.

### V2 editor

No change. The editor already offers **Draft with AI** only where it offers **Ask AI**, which needs the
bootstrap's role-aware `features.enable_workflow_ai_assistant`.

## Files modified

| File | Change |
| --- | --- |
| `application/single_app/route_backend_workflows.py` | Imports `is_workflow_assistant_enabled_for_user` and refuses personal drafting when the assistant isn't available |
| `application/single_app/route_frontend_workspace.py` | Passes a role-aware `enable_workflow_ai_assistant` to the classic workspace template |
| `application/single_app/templates/workspace.html` | Renders the personal Task Brief and Draft Workflow Instructions controls only when the assistant is available |
| `application/single_app/config.py` | `VERSION = "0.261.215"` |
| `functional_tests/test_workflow_draft_instructions_assistant_gate.py` | New regression test |

Documentation updated: `docs/admin/workflow.md`, `docs/explanation/features/WORKFLOW_AI_ASSISTANT.md`,
`docs/explanation/features/VOICE_ASSISTED_WORKFLOW_ACTION_CREATION.md` and the Phase 3c follow-up in
`docs/explanation/features/CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md`.

## Impact

- **Admins** who turn the assistant off now get what the setting says: no personal AI drafting from the V2
  editor, the classic workspace or the API.
- **Users** with the assistant available see no change.
- **Users** without it no longer see the classic personal **Task Brief** and **Draft Workflow Instructions**
  controls, and they can still write task instructions themselves.
- **Group workflows** are unaffected.
- **API callers** that drafted personal instructions with the assistant off now get 403
  `workflow_assistant_disabled`, the same answer the **Ask AI** route gives.

## Validation

`functional_tests/test_workflow_draft_instructions_assistant_gate.py` runs the real route bodies, the real gate
helpers from `functions_settings.py` and the real modal markup on closed Flask and Jinja environments, with a fake
model client, group resolver and Cosmos. It covers:

- personal drafting with the assistant on reaching the model
- personal drafting with the assistant off refused with the decorator's body, before any model client is created
- a `WorkflowUser` who still needs the assistant when the role is required
- the personal-workflow 400 and the role 403, unchanged and taking precedence over the assistant's answer
- group drafting with the assistant off, still allowed, and group refusals unchanged
- an invalid scope, still a 400
- the route not being wrapped in the assistant decorator
- the classic workspace getting a role-aware flag, never the raw setting
- the personal modal hiding its draft controls when the flag is off, and the group modal keeping them

The test passes as a script and under pytest, each with and without `python -O`.

Each of these mutations fails at least one test:

- removing the server check
- also gating group scope
- inverting the flag
- checking before the personal access check
- reading the raw setting instead of the role-aware helper
- decorating the route
- removing the template condition or the route's override
- gating the group template

The route policy tests under `functional_tests/route_tests/` are unchanged and pass, because the route, its
decorators and its auth policy are the same.

### Before and after

| Request or page, assistant off | Before | After |
| --- | --- | --- |
| Personal `POST /api/workflows/draft-instructions` | 200, with a drafted answer | 403 `workflow_assistant_disabled`, no model call |
| Group `POST /api/workflows/draft-instructions` | 200 | 200, unchanged |
| Classic personal workflow modal | Shows Task Brief and Draft Workflow Instructions | Hides them, and Task Instructions stays |
| Classic group workflow modal | Shows them | Shows them, unchanged |
| V2 editor | Hides Draft with AI | Hides Draft with AI, unchanged |
