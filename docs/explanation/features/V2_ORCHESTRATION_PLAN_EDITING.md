# V2 Orchestration Plan Editing

**Version: 0.261.104**

**Implemented in version: 0.261.102**, tracked in
`application/single_app/config.py`.

**Reasoning compatibility and capability context fixed in version: 0.261.104**,
using the same application version field.

## Overview

A proposed orchestration plan is not necessarily the plan a user wants to run.
They might want another search, less research, a different comparison, or a
change to the answer's focus. **Edit** lets them discuss those changes with the
planner before any step executes.

The editor follows the image, chart, and diagram editing pattern: a full-screen
preview, a scoped AI conversation, and revision history. Its storage is different
because a plan is executable work, not a revision of a message's rendered content.
Editor exchanges do not add duplicate messages to the main conversation.

**Review** still opens the plan drawer. Its existing step switches and document
removal controls only narrow a plan. Adding or restructuring work goes through
the server-side planner and the same capability and source-access validation used
when a plan is first created.

## Dependencies and boundaries

The V2 interface, `enable_chat_orchestration`, a configured planner or chat model,
and an unexecuted pending plan are required. There is no new administrator switch,
browser dependency, or Cosmos container.

Only capabilities already enabled for the deployment and available to the user
can be added. Editing cannot enable an integration, grant access to a document,
or introduce an output capability that orchestration does not support.

Running and finished plans are not editable. Immediate Auto mode remains
immediate for untouched plans; select Review or countdown approval when a
pre-execution editing opportunity is needed.

## Approval and revision lifecycle

Opening Edit pauses the local countdown immediately and saves a manual-approval
hold on the server. The plan then needs an explicit **Run**, including after
closing the editor or reloading the conversation. This is a safety intervention
for that plan, not a change to the deployment's default approval setting.

The hold changes the version token required to approve the plan. A stale tab
cannot run it with an approval captured before editing began. Execution and
editing use conditional persistence: whichever claims the plan first wins, and
the other request receives a conflict rather than changing work already underway.
Question cancellation carries the displayed question's identity and version. A
refresh that discovers newer work does not silently retarget the cancellation.

A successful change creates a new plan/run revision and supersedes its predecessor
atomically. Old versions remain available for history but are not additional
executed runs in the conversation's map or planner ledger. Restoring a version
creates a new current revision after checking its sources and capabilities again.

A failed model call, invalid plan, or failed save keeps the previous valid plan.
The editor does not substitute a direct-answer fallback for an unsuccessful edit.
Submission identifiers make a retried completed request reuse its saved outcome.

## Planner context and execution

The planner receives the current effective plan, including Review's narrowing
changes, the current task, the latest instruction, and a bounded editor
conversation. The saved original request, selected sources, and conversation
snapshot retain their identities.

Available capabilities come from server configuration, current access, and resource
prerequisites. Selected controls and sources are positive requirements; an unchecked
control does not veto a capability. A later edit can intentionally change an earlier
selection, with a visible review warning when selected work is removed.

Planner and answer models resolve reasoning effort independently from canonical
model metadata. Unsupported saved levels are adjusted visibly rather than breaking
Edit or Run. Runtime adjustments survive revision publication, editor projections,
and run restoration without changing immutable historical plans. See
[Reasoning compatibility]({{ '/explanation/fixes/ORCHESTRATION_REASONING_LEVEL_COMPATIBILITY_FIX/' | relative_url }}).

The planner can return an updated plan, an explanation without changing the plan,
or a clarifying question. Questions remain inside the editor; answering one
continues that edit without removing the last valid preview.

An updated plan also contains a self-contained revised request. It is saved
separately from the original user message and used for retrieval, delegated tasks,
and the final answer. A change therefore affects the work, not just the titles
shown in the preview.

User-written links and accepted clarification answers retain their provenance.
A link invented while the model rewrites the task is not permission to fetch it.

## API

All editor routes use the authenticated orchestration Blueprint and check
conversation and run ownership.

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/v2/orchestration/runs/<run_id>/editor` | GET | Read current editor state and a page of revision history. Does not start an edit or approve work. |
| `/api/v2/orchestration/runs/<run_id>/edit` | POST | Establish the manual-approval hold and return canonical editor state. |
| `/api/v2/orchestration/runs/<run_id>/revisions` | POST | Stream an `ask`, `answer`, `restore`, or `discard` operation. |
| `/api/v2/orchestration/run` | POST | Run the saved current plan, including its expected edit-version token when held. |

Revision requests name the conversation, expected version, and submission ID.
They contain an instruction, a stored source-version ID, or a clarification
response, never a browser-authored executable plan. Instructions are limited to
2,000 characters; an oversized instruction is rejected rather than truncated.

Terminal revision frames reuse `orchestration_plan` and
`orchestration_elicitation`, with an `editor` projection containing the current
plan, narrowing edits, chat, history, and pending question. Private source
snapshots, seeds, storage metadata, and in-flight claims are not included.

History is paged with `before_revision`; it is not an ever-growing array of full
plans in one Cosmos document. The scoped conversation retains recent turns, while
plan versions remain separate records under the existing retention behavior.

## File structure

| File | Responsibility |
| --- | --- |
| `application/v2_ui/src/components/chat/OrchestrationPlanEditor.tsx` | Full-screen preview, planner conversation, and history |
| `application/v2_ui/src/components/chat/OrchestrationPlanCard.tsx` | Inline Edit entry and countdown intervention |
| `application/v2_ui/src/components/chat/OrchestrationPlanPanel.tsx` | Review-drawer integration |
| `application/v2_ui/src/lib/orchestrationController.ts` | Scoped requests and explicit execution |
| `application/v2_ui/src/stores/orchestrationStore.ts` | Plan/editor state across component and conversation changes |
| `application/single_app/functions_orchestration_plan_editing.py` | Edit context, current source authorization, planner integration, and restore validation |
| `application/single_app/functions_orchestration_plan_revisions.py` | Holds, claims, atomic publication, version history, and execution guards |
| `application/single_app/functions_orchestration_planner.py` | Revision prompt and failure behavior |
| `application/single_app/route_backend_orchestration.py` | Owned editor HTTP/SSE operations and run integration |

## Usage

See [Review and edit orchestration plans]({{ '/guides/review-and-edit-orchestration-plans/' | relative_url }})
for the complete workflow. A typical refinement is to add a focused evidence-gathering
step, inspect the new preview, remove unnecessary work, and then run the accepted
version. No planned search, integration action, or answer step executes merely because the
editor is opened or an instruction is sent.

## Testing and limitations

`functional_tests/test_orchestration_plan_revision_store.py` covers ownership,
conditional transitions, idempotency, history, and edit/run conflicts.
`functional_tests/test_orchestration_plan_revision_routes.py` covers the real
planner-to-persistence-to-execution flow, including clarification, error recovery,
preserved source selections, and the final revised request.
`functional_tests/test_orchestration_plan_revision_planner.py` covers the strict
edit-output contract. Initial planning is strict too: a provider failure or an
invalid plan no longer becomes a successful direct-answer fallback.

The orchestration UI harness covers the editor and existing narrowing-only Review
behavior. Model responses are deterministic in these tests; they establish the
application contract, not that every natural-language request will produce the
desired plan on its first attempt.

`ui_tests/test_v2_orchestration_plan_editor.py` covers browser interactions and
recovery states. `ui_tests/test_v2_orchestration_plan_editor_backend.py` forwards
real browser requests through the Flask handlers to cover the combined
add/remove, clarification, restore, and explicit-run workflow.

Each AI refinement costs a planner call and may require metadata/search work to
resolve eligible sources. It does not execute the proposed steps. Existing
capability limits still apply. There is no raw JSON editor, running-plan replanner,
or classic-interface counterpart.
