# Orchestration Run History Hydration Fix

Fixed in version: **0.261.099**

## Issue Description

Orchestration plans appeared to live only in the browser that created them. A user who
planned and ran a question on one device, then opened the same conversation on another,
saw an empty orchestration panel with no trace of the earlier runs. Reloading the page on
the original device had the same effect. The assistant's answer survived, because it is an
ordinary chat message, but the plan behind it, its steps and its results did not.

Two further consequences followed from the same gap:

1. A plan left waiting for approval was stranded. The user had to ask the question again
   on the new device, which produced a second plan and a second run for the same request.
2. A run whose browser went away mid-flight left no record at all. Nothing distinguished
   "this never happened" from "this was interrupted".

## Root Cause Analysis

The server was never the problem. Runs and steps were already persisted in Cosmos DB, in
`cosmos_orchestration_runs_container` (partitioned by `/conversation_id`) and
`cosmos_orchestration_run_steps_container` (partitioned by `/run_id`), and the planner
already read earlier runs back to build its ledger. Two read endpoints existed and were
correct.

The V2 interface simply never called them.

- No module under `application/v2_ui/src` referenced `/api/v2/orchestration/runs` or
  `/api/v2/orchestration/runs/<run_id>/steps`. The orchestration drawer was populated
  entirely from in-memory Zustand state, persisted only to `sessionStorage`, which is
  per-tab and per-device by definition.
- `restorePersistedRuns()` was exported from the orchestration store but was never
  invoked anywhere in the application, so even same-device restoration after a reload did
  not happen.
- There was no route that returned a single run with its plan, so the panel had no way to
  fetch the plan for a run it had not itself produced.
- The user's question was saved to the conversation without its `orchestration_turn_id`,
  so a hydrating client had no reliable way to line an inbound run up with the message
  that caused it.

## Version Implemented

- **0.261.099**

## Files Modified

- `application/single_app/route_backend_orchestration.py`
- `application/single_app/config.py`
- `application/v2_ui/src/lib/orchestration.ts`
- `application/v2_ui/src/lib/orchestrationResume.ts` (new)
- `application/v2_ui/src/lib/orchestrationController.ts`
- `application/v2_ui/src/stores/orchestrationStore.ts`
- `application/v2_ui/src/components/chat/OrchestrationMapView.tsx`
- `application/v2_ui/src/components/chat/OrchestrationPlanPanel.tsx`
- `application/v2_ui/src/components/chat/OrchestrationRunView.tsx`
- `application/v2_ui/src/pages/ChatPage.tsx`
- `application/v2_ui/src/App.tsx`
- `ui_tests/fixtures/orchestration/harness_entry.tsx`
- `ui_tests/test_v2_orchestration_run_hydration.py` (new)
- `ui_tests/test_v2_orchestration_pending_approval_resume.py` (new)
- `functional_tests/test_orchestration_run_hydration_routes.py` (new)
- `functional_tests/test_orchestration_turn_recovery_identifiers.py` (new)
- `docs/admin/orchestration.md`

## Code Changes Summary

### Server

- Added `GET /api/v2/orchestration/runs/<run_id>`, which returns one run together with its
  plan. Ownership is enforced inside `get_orchestration_run`, and a run belonging to
  another user is reported as not found rather than forbidden.
- Introduced `_run_summary_row` and `_run_detail_row`, allowlist projections that decide
  what leaves the server. The run list now returns summaries rather than raw records, so
  `user_id`, `approved_by`, `seeds`, `conversation_context`, `request_resolution`,
  `user_message_fingerprint`, Cosmos system fields and the full artifact payloads stay on
  the server. This replaces an earlier blocklist that stripped three of those fields by
  name; an allowlist keeps excluding whatever the record gains later, until it is named.
  `?include_plan=true` widens the projection to include the plan rather than bypassing it,
  so no caller can reach a stored record as it is.
- Stamped the persisted user message with `metadata.orchestration_turn_id`, so a client
  that has only the conversation can associate a stored run with the message that started
  it. The stamp is applied in `_save_turn_message` for every orchestrated question. It was
  previously written only when the turn happened to carry a selected prompt, which left the
  key absent on ordinary questions even though `chatStore.ts` already read it. The added
  metadata carries no `thread_info`, so `/api/get_messages` continues to include the
  message.

### Client

- Added a typed read layer — `fetchConversationRuns`, `fetchOrchestrationRun` and
  `fetchRunSteps` — alongside the existing streaming client.
- Added hydration to the orchestration store: `hydrateConversationRuns` merges persisted
  run summaries into history, and `adoptPersistedPlan` installs a fetched plan and its
  steps for display. Locally tracked runs win over hydrated ones for the same run id.
- Reconciled stale state during hydration. A run restored from storage that the server
  reports as finished is dropped from the in-flight set instead of spinning forever.
- Distinguished an interrupted run from a running one in the map view, and added loading,
  error, retry and empty states so a failed fetch is visible rather than silent.
- Made a run opened from history read-only. The run view shows a banner explaining that it
  is a record, and approval controls are suppressed.
- Restored a plan that was still awaiting approval as an approvable card, guarded so it
  only applies to the newest run, only when nothing is already active locally, and only
  when no assistant message already follows the question.
- Neutralised a restored timed approval to manual, so a countdown started on one device
  cannot run work unattended on another.
- Handled the existing HTTP 409 re-run guard on the client. If the plan was approved
  elsewhere first, the local turn settles and the conversation reloads to show the answer
  that already exists, rather than surfacing an error.
- Called `restorePersistedRuns()` during application bootstrap, and hydrated each
  conversation once when it is opened.

## Testing Approach

- `ui_tests/test_v2_orchestration_run_hydration.py` drives the real store and components
  in a browser against intercepted API routes, covering hydration, merge precedence, the
  interrupted status, lazy step fetching, read-only adoption and the retry path.
- `ui_tests/test_v2_orchestration_pending_approval_resume.py` covers the resume guards and
  the timed-approval neutralisation.
- `functional_tests/test_orchestration_run_hydration_routes.py` asserts the route
  contract, decorator ordering and the projection allowlist, including the fields that
  must not be projected.
- `functional_tests/test_orchestration_turn_recovery_identifiers.py` asserts that the user
  message is stamped with its turn id, that the run record keeps both identifiers, that
  the re-run guard exists, and that the run route takes its inputs from the stored record
  rather than the request body.

## Impact Analysis

- No data migration is required. Run records already carried `turn_id` and
  `user_message_id`; the change is that clients now read them.
- Conversations that predate the fix hydrate correctly, because their runs were persisted
  all along. Only the user-message turn-id stamp is new, and every code path that uses it
  falls back to `user_message_id`.
- The run list response is smaller and no longer includes plans by default, and no longer
  returns a stored record verbatim on any path. A caller that needs plans can pass
  `include_plan=true`, which returns the same projected shape plus `plan`.
- Approving a restored plan is safe because the run route already refused a plan whose
  status is running or completed, and reads the plan, seeds and question from the stored
  record rather than from the request.

## Validation

- `functional_tests/test_orchestration_run_hydration_routes.py` — 6/6 passing.
- `functional_tests/test_orchestration_turn_recovery_identifiers.py` — 6/6 passing.
- `ui_tests/test_v2_orchestration_run_hydration.py` — 6/6 passing.
- `ui_tests/test_v2_orchestration_pending_approval_resume.py` — 5/5 passing.
- `functional_tests/route_tests/` route policy suites — passing.
- `npx tsc -b --noEmit` and `npm run build` in `application/v2_ui` — clean.

### Before and after

| Situation | Before | After |
| --- | --- | --- |
| Open a conversation on a second device | Orchestration panel is empty | Earlier runs are listed, and can be expanded to their steps and results |
| Reload the page mid-conversation | Run history is lost | Run history is rebuilt from the server |
| Plan left awaiting approval, user moves device | Plan is stranded; the question must be asked again | Plan reappears and can be approved, edited or discarded |
| That plan was approved on the first device | Second approval would race | Second approval is refused and the existing answer is loaded |
| Browser closed mid-run | No record | Run is listed as interrupted |
