# Workflow plan replay

Implemented in version: **0.261.303**.

Application version tracking: `application\single_app\config.py`.

Related issue: part of #1550, under #1543. Builds on
[Chat orchestration workflow proposals](CHAT_ORCHESTRATION_WORKFLOW_PROPOSALS.md),
[Chat orchestration workflow runs](CHAT_ORCHESTRATION_WORKFLOW_RUNS.md),
[Chat orchestration workflow hand-off](CHAT_ORCHESTRATION_WORKFLOW_HANDOFF.md) and
[Durable workflow execution](WORKFLOW_DURABLE_EXECUTION.md). It is the first
producer adapter for action O2 in
[Workflow M5C completion and next steps](WORKFLOW_M5C_COMPLETION_AND_NEXT_STEPS.md).

## Overview and dependencies

A user asks chat orchestration to do something once, for example "search my
contract notes and summarize what changed". Then they want the same thing on a
schedule: "do this every Monday". Until this version, a saved workflow couldn't
do that. Workflow runners only have the core plugins, so the steps that chat
orchestration ran weren't available to a schedule.

Plan replay closes that gap for a deliberately small set of steps. A personal
workflow stores the plan the user approved in chat, frozen and hashed, as a
`plan_replay` task. Each run replays that plan through the same headless
orchestration harness chat uses, as the workflow's creator, in the workflow's
own conversation. The model still writes each step's output, but it never adds,
removes or rewrites a step.

Requirements:

| Setting | Why |
| --- | --- |
| `enable_workflow_plan_replay` | The feature switch. Off by default. With it off, nothing changes, and an existing replay workflow refuses to run with a fixed reason. |
| `enable_chat_orchestration` | The harness that replays the plan is chat orchestration's. |
| `allow_user_workflows` | Replay workflows are personal workflows. |

The setting lives in the admin **Chat Orchestration** pane, next to the other
"From Chat" switches, as **Repeat Chat Plans On A Schedule**.

## Identity

The binding decision, verbatim:

> "plan replay runs on the user's identity who creates the workflow or asked to create it via chat"

A replay runs as the workflow's creator and nobody else. It never runs as a
service identity, as another user, or as whoever triggered the run. Replay is
personal-only, so the creator is `workflow.user_id`.

| When | Check | Refusal |
| --- | --- | --- |
| Save | The source orchestration run belongs to the requester (`record.user_id`). | `creator_mismatch` |
| Save | The source conversation is owned by the requester and private to them. | `shared_conversation_not_allowed` |
| Save | The task records the requester as `approval.approved_by` and `provenance.created_by`. | — |
| Save | A group workflow can't carry a `plan_replay` task (`functions_group_workflows.py`). | `group_not_supported` |
| Every run | `workflow.user_id` is set, and `created_by`, `provenance.created_by` and `approval.approved_by` all equal it. | `creator_mismatch` |
| Every run | The run's actor is `workflow.user_id`. | `creator_mismatch` |
| Every run | A group workflow is refused. | `group_not_supported` |
| Every run | The workflow is read again and passes `_authorize_execution` as the actor: it exists, isn't being deleted, belongs to the actor, and personal workflows are on. | `workflow_unavailable` or `personal_workflows_disabled` |

## Roles

Background runs have no signed-in session. `capture_execution_identity` outside
a request returns empty roles and no email, so a role-gated step that worked
when the user ran the plan by hand would fail on the schedule.

Plan replay uses a role-free allowlist (option **a**). Every capability check,
at freeze and on every run, resolves capabilities with
`user_roles: []` and `user_enable_agents: False`. The harness is prepared with
the same empty identity context. A capability that needs the caller's roles is
reported by the registry as `caller_access_required` and refused as
`role_required`. `web_search` is the one such capability today and is refused
at freeze.

Because neither a manual run nor a scheduled run passes roles to the replay, a
plan behaves the same whichever starts it. It can't work when tested by hand and
then fail on Monday. Nothing is stored from the user's session, so there is no
role snapshot to age or widen.

## Freeze

The freeze runs server-side, inside the request thread, from an orchestration
run the requester owns:

- The run must be `completed`, with no outcome or outcome `completed`, an
  approval in state `approved`, no failure and no failures list, and a plan.
- The run must not itself be a replay (`workflow_replay`).
- A plan that asked the user a question (`answered_questions`,
  `elicitation_references`, or an elicitation marker in the plan) is refused as
  `elicitation_not_replayable`.
- A plan that depends on earlier chat turns (`result_aliases` or
  `analysis_result_contexts`) is refused as `conversation_context_not_replayable`.

What is stored on the task (`plan_replay`):

| Field | Content |
| --- | --- |
| `version` | `1` (`PLAN_REPLAY_TASK_VERSION`) |
| `allowlist_version` | `plan-replay-allowlist-v1` |
| `request` | The resolved request, with only the trailing run-time line removed. |
| `frozen_plan` | `normalize_plan_contract(plan)`: the plan contract fields (`plan_id`, `planner_contract_version`, `intent`, `assumptions`, `steps`, `inputs`, `outputs`, `final_response`, `deliverables`, `model_routing`), each step reduced to its contract fields. Run identity, status, approval and edit state are dropped. |
| `frozen_seeds` | The request choices a replay may reuse: model and reasoning choices, `doc_scope`, `document_ids`, `tags`, `document_filter_mode`, `active_group_ids` and `active_public_workspace_ids`. A scope outside `all`, `personal`, `group` and `public` is refused. |
| `plan_sha256` | SHA-256 of the canonical JSON of `{task_version, allowlist_version, request, plan, seeds}`. |
| `approval` | `{approved_by, approved_at, plan_sha256}` |
| `provenance` | `{source_run_id, source_conversation_id, created_by, frozen_at, time_handling, time_zone}` |

The workflow also carries the usual chat origin (`source: orchestration`, the
source conversation, run id and a `replay-<run>-<hash>` proposal id), and is
created `durable_execution: true`, `definition_version: 2`, with one task.

The hash binds approval:

- Saving requires the `plan_sha256` the preview returned. If the plan changed
  since the card loaded, the save is refused as `plan_hash_mismatch` (409).
- Every run recomputes the hash and refuses on a mismatch with either stored
  copy. It also refuses a stored plan that isn't already in normalized form.
- The ordinary workflow save keeps the frozen plan read-only. A payload that
  changes `plan_replay`, a task, or the task type is refused as
  `plan_replay_read_only`. Only the name, description, trigger, schedule, whether
  it's on, and the alert fields can change; everything else keeps its stored
  value.
- `tasks`, including `plan_replay`, is part of `WORKFLOW_DEFINITION_FIELDS`, so
  any change also changes the workflow's definition revision, and a durable run
  pins the definition it started with.

At run time the frozen plan becomes an executable plan with new run, plan and
turn ids, `status: approved` and every step `pending`
(`build_executable_replay_plan`). The harness executes it without calling the
planner, so the model never adds, removes or rewrites steps. Steps that call a
model, such as Prepare content or Analyse documents, still run with the frozen
instructions.

## Allowlist

Deny by default. `classify_plan_steps` serves both the freeze and the run-time
preflight, so both apply the same rules. A plan can have at most 8 enabled
steps.

Allowed (`plan-replay-allowlist-v1`):

| Capability | Label | Why it is safe to repeat as the creator |
| --- | --- | --- |
| `document_search` | Search documents | Searches documents the creator can still open; access is re-checked before every run. |
| `document_analyze` | Analyse documents | Analyzes documents the creator can still open, with the frozen instructions. |
| `document_compare` | Compare documents | Compares documents the creator can still open, with the frozen instructions. |
| `document_merge` | Merge documents | Merges documents the creator can still open into a file kept with the run. |
| `tabular_inspect` | Inspect spreadsheets | Reads the shape of tabular files the creator can still open; it finishes in the step. |
| `compose` | Prepare content | Writes the answer from earlier step results with the frozen instructions. |
| `generate_image` | Generate image | Creates a new image from the frozen prompt; reference images are refused. |

Refused, with the per-step reason shown on the card:

| Class | Capabilities | Code |
| --- | --- | --- |
| Asynchronous waits | `tabular_analyze`, `render_file`, any step declaring a wait kind (`native_tabular_compute`, `orchestration_output`, `orchestration_result`, and Phase 6c's `saved_workflow_run`), and a plan that delivers a `file` | `replay_wait_unsupported` |
| Needs the caller's roles | `web_search` | `role_required` |
| Workflow capabilities | `workflow_propose`, `workflow_run`, `workflow_results`, `workflow_handoff` | `capability_not_replayable` |
| External effects | `action_invoke`, `agent_invoke` (and `workflow_run`) | `capability_not_replayable` |
| Approval floor | Every capability returned by `approval_floor_capability_ids()` | `capability_not_replayable` |
| Not on the list | `url_fetch`, `deep_research`, `tabular_merge` and any capability added later | `capability_not_replayable` |
| Reference images | `generate_image` with reference documents or messages | `capability_not_replayable` |
| Image offers | `compose` offering an image for the user to accept | `capability_not_replayable` |
| Other deliverables | A deliverable kind outside answer, image, chart, diagram and file | `capability_not_replayable` |
| Questions | A plan that asked the user a question | `elicitation_not_replayable` |
| Size | No enabled steps, or more than 8 | `capability_unavailable`, `replay_budget_exceeded` |

Phase 6c's wait kind isn't on this base yet, so its value is mirrored as
`SAVED_WORKFLOW_RUN_WAIT_KIND` in `functions_workflow_plan_replay.py`.
`workflow_run` is refused regardless, which already covers it.

Microsoft 365 is unreachable in this version. Mail and calendar steps reach
Microsoft 365 only through `action_invoke`, which is refused.

## Re-authorization on every run

`execute_plan_replay_task` calls `authorize_plan_replay_run` and then reloads
the workflow before it creates any orchestration run, so a refusal stops the
run without running any step. Each run checks, in order:

1. `enable_workflow_plan_replay`, `enable_chat_orchestration` and
   `allow_user_workflows` are on.
2. The workflow is personal, and the creator checks in [Identity](#identity) pass.
3. The task and allowlist versions are supported.
4. The stored hash matches the recomputed hash and the approval's hash.
5. The stored plan asks no question.
6. `classify_plan_steps` refuses nothing.
7. Every enabled step's capability is still on and still in the admin list
   (`chat_orchestration_enabled_capabilities`), resolved with no roles.
8. Every source is still readable by the creator: each group in the seeds still
   counts them as a member and allows chat; each public workspace still exists
   and allows chat; and every document id in the seeds or the plan resolves as
   `authorized` through `resolve_authorized_source_manifest`.
9. The workflow passes `_authorize_execution` as the creator.
10. The run's conversation is the workflow's own conversation (see below).

The harness then revalidates the conversation, memory and capabilities, as it
does for any chat plan.

## Conversation

A replay runs in the workflow's own conversation, which the workflow runner
creates with `_ensure_workflow_conversation`. Before step 1, and every time the
orchestration lease reads its run, `_verify_workflow_conversation` requires
that the conversation:

- isn't the source chat;
- belongs to the creator, isn't deleted for orchestration, and is private to
  them;
- is a `workflow` conversation for this workflow, with no group.

The source chat is never read at run time. Sharing it later changes nothing:
the replay doesn't read it, and its answer never goes there. Results land in the
workflow conversation like any other workflow result.

## Execution and durability

Replay workflows are durable. The runner wraps the replay in one
`workflow_unit`, marked replay-safe because it has no external effects and
reconciles earlier attempts before it starts. Attempts are numbered by the
durable unit, so a resumed attempt never reuses an identity a dead worker left
behind.

Each attempt:

1. Derives deterministic orchestration run, plan and turn ids from the workflow
   run id, task id and attempt number.
2. Reconciles every earlier attempt. A completed attempt of the same frozen
   plan is adopted, not repeated. A dead one is settled as failed with
   `ownership_lost` and fenced. A live one is asked to stop and fenced, but never
   taken over; if it doesn't stop within one orchestration lease period plus a
   heartbeat, this attempt fails.
3. Creates the orchestration run idempotently in the workflow conversation,
   bound to the workflow by `workflow_replay` (`workflow_id`,
   `workflow_run_id`, `task_id`, `plan_sha256`, `attempt`). The run's user
   message is the workflow run's own user message.
4. Claims the run and holds an orchestration `ExecutionLease`.
5. Runs `HarnessExecution` on a worker thread and polls it every 5 seconds.
   Each poll calls the workflow runner's cancel check, which also asserts the
   durable workflow lease.
6. On cancellation, a lost lease, or the 15-minute budget, it requests
   cancellation, fences publication, waits up to 30 seconds for the worker, and
   settles its own run.

Only the workflow drives a replay run. The orchestration scheduler's due-run
query excludes runs with `workflow_replay`, and a replay run that reaches the
scheduler anyway is deferred untouched. Chat routes that would run, retry,
edit, revise or cancel a replay run return 409 `workflow_replay_run_managed`.

## Typed output

A completed replay records `plan-replay-result-v1` on the task:

| Field | Source |
| --- | --- |
| `contract` | `plan-replay-result-v1` |
| `orchestration_run_id` | The orchestration run record's `id`. |
| `conversation_id` | The run record's conversation, the workflow conversation. |
| `plan_sha256` | The run record's `workflow_replay.plan_sha256`. |
| `status`, `outcome` | The run record. |
| `steps` | Each enabled frozen step with `step_id`, `capability_id`, its label and its status from the executor's `execution_steps` or `task_results`, or `not_run`. |
| `final_response` | The answer message id and the run record's message. |
| `artifacts` | Generated images from the answer message's stored metadata (`visual_id`) and the run record's artifacts, each normalized to `image` or `file` with its stored id. |

Every id comes from a stored record. Model prose is never parsed for an
execution id or treated as an engine result.

The task's run item carries the same result for the V2 run inspector, with the
final response capped at 4,000 characters and a `truncated` flag; the full
answer stays in the workflow conversation and the task's stored result. The
inspector's **Saved chat plan run** block shows the run id, status, each step
with its status, the final response and the artifacts. A redacted run item
withholds `plan_replay` along with the rest of the result.

## Creation path

Creation path **B**: a **Repeat on a schedule** button under a finished
orchestrated answer opens a **Save this chat plan** card.

Why B rather than asking the planner: the plan being saved is one the user
already saw run, so the card can show exactly that plan. The planner never
writes a definition, and a "save" can't be produced by model output. The
existing proposal and hand-off paths stay unchanged.

The button shows only when all three settings are on, under a completed,
unmasked answer with a run id, in the active conversation, when that
conversation is private to the user, and when the plan didn't propose, start or
hand off a workflow.

Routes, both `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required`, `@enabled_required('allow_user_workflows')`
and `@workflow_user_required`:

| Route | Purpose |
| --- | --- |
| `GET /api/v2/orchestration/runs/<run_id>/plan-replay?conversation_id=` | Freezes the run in memory and returns what would be saved, with any refusals. Writes nothing. |
| `POST /api/v2/orchestration/runs/<run_id>/plan-replay` | Freezes again, requires the previewed `plan_sha256`, re-checks every source, checks the quota and creates the workflow. 201 when created, 200 when this plan is already saved. |

The card fetches the preview only when the user opens it. Before anything is
saved, it discloses the request, how dates are handled and in which time zone,
the shortest interval allowed, the step cap, that runs act as the user in the
workflow's own conversation, and every frozen step with its title and
capability label. A refused plan lists each refusal under **This plan has
replay notes** and can't be saved. Saving is always a manual choice, and the
workflow is saved paused unless the user turns on **Turn on the schedule now**.

The workflow id is derived from the user, the source run and the hash, so
saving the same plan twice returns the existing workflow. A workflow that was
deleted can be created again from the same card.

### Editor

The V2 workflow editor shows a replay workflow's **Saved chat plan** section
read-only: the request, when it was frozen, the allowlist version, the time
handling, and the numbered steps with each title and capability label. It tells
the user to run the request again in chat and save the new plan to change the
steps. The name, description, trigger, schedule, alerts and whether it's on stay
editable. The Classic workflow page routes a replay workflow to V2: "This
workflow uses a saved chat plan. Open V2 to edit it without losing its
configuration."

## Relative time

Dates written in the request stay as written. Each run appends a server-built
line with the current local date and time
(`request_local_time_line`) to the resolved message the harness reads, so a
request about "this week" is read against the day the run happens.

The time zone is the schedule's `timezone`, then the source run's time zone,
then UTC. The card names it, and V2 mirrors the same fallback.

## Waits and budgets

Steps that finish after the plan stops waiting are refused in this version (see
[Allowlist](#allowlist)), so a replay never parks a durable workflow run on an
orchestration wait.

| Budget | Value |
| --- | --- |
| Steps | 8 enabled steps (`PLAN_REPLAY_MAX_STEPS`) |
| Run time | 900 seconds (`PLAN_REPLAY_MAX_SECONDS`); then the run is cancelled and fenced and fails with `replay_budget_exceeded` |
| Stop grace | 30 seconds for the worker to stop after cancellation |
| Earlier attempts | One orchestration lease period plus a heartbeat for a live earlier attempt to stop |
| Durable attempts | 3, the shared bound for a replay-safe durable unit |

## Cost

There is no spend cap, so replay reuses the caps on chat-created workflows:

- The schedule must meet `get_orchestration_workflow_min_interval_seconds`, the
  larger of `chat_orchestration_min_workflow_interval_seconds` (one hour by
  default) and `workflow_min_schedule_interval_seconds`. It is enforced on every
  save of a replay workflow, including later edits.
- Replay workflows count toward `chat_orchestration_max_workflows_per_user`
  (20 by default). Over the limit, the save is refused as `quota_exceeded` (429).

## Prompt injection

Documents, web pages and email are untrusted.

- There are no free-form destinations. Actions, agents, page fetches, web
  search, rendered files and Microsoft 365 are all refused. A run writes only to
  the workflow's own conversation and the run's own artifacts.
- The card discloses the request and every step before the user saves.
- The replay adds no new prompt around document text. Untrusted content stays
  fenced by the harness's existing prompts, and the only new text in the
  prompt is the server-built run-time line.

## Refusals

Every refusal is a fixed message from `REFUSAL_MESSAGES`, never model output.

| Code | When | HTTP (save/preview) | What the user sees |
| --- | --- | --- | --- |
| `replay_disabled` | Setting off | 403 | Card: inline error. Run: fails with "Repeating chat plans is turned off. Ask an admin to turn it on, then run the workflow again." |
| `orchestration_disabled` | Chat orchestration off | 403 | Same places, "Chat orchestration is turned off, so this saved plan can't run." |
| `personal_workflows_disabled` | Personal workflows off | 403 | The routes refuse first; a run fails with the fixed text. |
| `group_not_supported` | Group workflow | 422 | Save or run refused. |
| `creator_mismatch` | Actor isn't the creator | 403 | Save or run refused. |
| `shared_conversation_not_allowed` | Shared source chat | 403 | Card error. |
| `run_not_found` | Missing or another user's run | 404 | Card error. |
| `source_run_not_eligible` | Not a completed, approved plan | 409 | Card error. |
| `plan_hash_mismatch` | Plan changed since the preview, or a stored hash mismatch | 409 | Card: **Reload plan**. Run: "This saved plan changed after it was approved. Create it again from chat." |
| `allowlist_version_unsupported` | Unknown task or allowlist version | 422 | Run fails with the fixed text. |
| `capability_not_replayable`, `role_required`, `replay_wait_unsupported`, `elicitation_not_replayable`, `conversation_context_not_replayable` | Refused step or plan | 422 | Card: **This plan has replay notes**, one line per step. Run: the first refusal's text. |
| `capability_unavailable` | A capability was turned off or removed from the admin list | 422 | Run fails with "A step in this plan is turned off or no longer available." |
| `source_unavailable` | Lost document, group or public workspace access | 422 | Save or run refused. |
| `replay_budget_exceeded` | More than 8 steps, or the run exceeded 15 minutes | 422 | Card note, or the run fails. |
| `replay_execution_failed`, `model_unavailable` | The harness couldn't finish | — | Run fails with the fixed text. |
| `workflow_unavailable` | Workflow deleted or being deleted | — | Run stops before step 1. |
| `plan_replay_read_only` | A save tried to change the frozen plan | 422 | Editor save error. |
| `quota_exceeded` | Too many chat-created workflows | 429 | Card error. |
| `workflow_conflict` | The workflow is being changed or deleted | 409 | Card error. |
| `workflow_replay_run_managed` | A chat route on a replay run | 409 | Chat action refused. |
| `invalid_request`, `service_unavailable` | Bad request, store failure | 422, 503 | Card error, without detail. |

A run-time refusal isn't retried. The run fails with the fixed text, which
shows on the run's task in the run inspector and in the run history. Alerts
follow the workflow's own alert settings, as for any failed run. There is no
separate replay alert, and nothing is sent to the bell unless the workflow's
alert settings send one.

### When the setting is turned off or a capability is removed

Nothing is deleted or rewritten. The **Repeat on a schedule** button
disappears, the routes refuse with `replay_disabled`, and every existing replay
workflow fails its next run with the fixed `replay_disabled` reason before
running any step. Turning the setting back on lets the same workflows run again.

When an admin turns off or removes an allowed capability, a replay workflow
with that step fails its next run with `capability_unavailable` until the
capability is back. A removed group membership, public workspace or document
fails the run with `source_unavailable`.

## With the setting off

Off is the default. With it off, workflows without a `plan_replay` task behave
exactly as on the base commit: `test_workflow_plan_replay_off_golden.py`
compares the runner's task sequences, personal workflow saves, group workflow
builds and run-history redaction against a golden captured from base
`fa3422dee`.

## Files

| File | Change |
| --- | --- |
| `functions_workflow_plan_replay.py` | New: allowlist, freeze, hash, preview, save, run-time authorization, executor, reconciliation and typed result. |
| `functions_workflow_runner.py` | Dispatches a `plan_replay` task to the replay executor in one durable unit, and records the typed result on the run item. |
| `functions_personal_workflows.py` | Keeps the frozen plan read-only on save and applies the chat cadence floor to replay workflows. |
| `functions_group_workflows.py` | Refuses a `plan_replay` task. |
| `functions_orchestration_scheduler.py` | Excludes replay runs from the due-run query. |
| `route_backend_orchestration.py` | Preview and save routes; 409 for chat routes on replay runs. |
| `functions_settings.py`, `admin_settings_fields.py`, `route_frontend_admin_settings.py`, `templates/admin/_panes/chat-orchestration.html` | The setting, default off, saved only as a real `True`. |
| `functions_orchestration_registry.py` | The setting's name. |
| `functions_saved_analysis.py` | Redaction withholds `plan_replay`. |
| `static/js/workspace/workspace_workflows.js` | The Classic page routes replay workflows to V2. |
| `v2_ui/src/components/chat/PlanReplaySaveCard.tsx`, `MessageList.tsx` | The card and when it shows. |
| `v2_ui/src/lib/workflowPlanReplay.ts` | API client, parsing and disclosure text. |
| `v2_ui/src/components/workflows/WorkflowEditorDialog.tsx`, `WorkflowRunHistory.tsx`, `lib/workflowEditor.ts`, `lib/workflowEditorSections.ts` | Read-only editor section and the run inspector block. |

## Testing and validation

| Test | Covers |
| --- | --- |
| `functional_tests/test_workflow_plan_replay_off_golden.py` | Off-golden against the base, the fixed reason while off, default off and the save-path coercion. |
| `functional_tests/test_workflow_plan_replay_freeze.py` | Allowlist reasons and every refused class, wait kinds including Phase 6c's, freeze eligibility, the hash, edit invalidation, per-run setting, capability, role, question and source checks, creator-only actor, group refusal, manual and scheduled parity. |
| `functional_tests/test_workflow_plan_replay_execution.py` | End-to-end replay under the headless harness with the model and search stubbed, the conversation binding and later sharing, creator-only runs, deleted or changed workflows, cancellation, budget and lease loss, durable restart, adoption and reconciliation, typed output and redaction, relative time. |
| `functional_tests/test_workflow_plan_replay_routes.py` | Preview disclosure, paused save, hash binding, settings, cadence floor, shared chats, refused steps, group access lost at save, quota and conflicts, read-only saves, the chat-route 409s. |
| `functional_tests/test_workflow_plan_replay_boundaries.py` | Import order and boundaries, scheduler exclusion. |
| `functional_tests/route_tests/test_route_blueprint_policy_inventory.py`, `test_route_unauthenticated_policy_contract.py` | Route policy for the two new routes. |
| `functional_tests/test_v2_workflow_plan_replay_client.mjs` | V2 client parsing, disclosure text, time-zone fallback and editor payloads. |
| `ui_tests/test_v2_workflow_plan_replay_card.py` | The card, refusals and save in a browser, with hostile step titles and workflow names. |
| `ui_tests/test_workflow_classic_advanced_guard.py` | The Classic page routes replay workflows to V2. |

## Limits and follow-ups

- Only the seven capabilities above replay. Waiting producers (`render_file`,
  `tabular_analyze`), role-gated producers (`web_search`), `url_fetch`,
  `deep_research` and Microsoft 365 need their own design.
- A failed replay records the fixed reason, but no typed result.
- The workflow conversation receives both the orchestration answer and the
  workflow's result message.
- A durable restart starts a new orchestration attempt rather than resuming the
  same orchestration run.
- A worker that doesn't stop within the stop grace is fenced and settled, but
  not finalized further.
- Group workflows, the SimpleChat action's workflow creation (#1347) and
  Monitor triggers (#949) are out of scope.
