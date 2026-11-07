# Chat orchestration workflow run wait

Implemented in version: **0.261.309**.

Application version tracking: `application\single_app\config.py`.

Related issue: part of #1546, under #1543. Builds on
[Chat orchestration workflow runs](CHAT_ORCHESTRATION_WORKFLOW_RUNS.md),
[Chat orchestration workflow results](CHAT_ORCHESTRATION_WORKFLOW_RESULTS.md) and
[Workflow result delivery to chat](CHAT_WORKFLOW_RESULT_DELIVERY.md). The
[Chat orchestration workflows roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md)
describes all the phases.

## Overview and dependencies

"Run my sales-digest workflow, then compare its totals with the Q3 report in my
workspace." Before this version, a plan could start the workflow, but the
planner dropped any `workflow_run` step that another step or the answer read.
The run's result arrived later as a separate chat post, so the plan couldn't
build on it.

With **Wait For Quick Workflows In Chat** on, a plan that starts one of the
user's quick saved workflows can wait for the run to finish, within a bound,
and hand its result to the steps that write the answer. If the run is still
going when the bound passes, the plan finishes anyway and says so, and the
existing post-back posts the result into the chat when the run finishes. Each
result reaches the chat once: in the answer or as a post, never both.

The server alone decides whether a step waits and for how long. A plan the
model writes can't make a step wait.

Dependencies:

- **Chat Orchestration** (`enable_chat_orchestration`) and personal workflows
  (`allow_user_workflows`).
- **Run Workflows From Chat** (`enable_chat_orchestration_workflow_runs`). The
  wait starts the run the same way.
- **Use Workflow Results In Chat** (`enable_chat_workflow_results`). A wait that
  runs out relies on its post-back, and the answer reads the result through its
  reader.
- **Durable execution** on the workflow, so a background continuation can read
  the run's progress.

With the setting off, planning and execution are unchanged:
`test_orchestration_workflow_run_wait_off_golden.py` compares them with output
captured from the base version.

## Technical specifications

### Settings

| Setting | Key | Default | Range |
| --- | --- | --- | --- |
| Wait For Quick Workflows In Chat | `enable_chat_orchestration_workflow_run_wait` | Off | Only a real boolean `True` turns it on. |
| Wait For A Workflow From Chat (seconds) | `chat_orchestration_workflow_run_wait_max_seconds` | 300 | 60-1800 |

The switch is in the Orchestration capabilities group, after **Run Workflows
From Chat**; the cap is in the Orchestration limits group. The admin form
shows the switch only while Chat Orchestration, personal workflows and Run
Workflows From Chat are on, and the cap only while the switch is on. Use
Workflow Results In Chat is on the Workflow tab, so the switch's help text
names it and the runtime enforces it: `wait_configured()` returns False
without it.

The cap's default of five minutes covers the short digests people run from chat
and keeps a waiting plan inside the default 15-minute run timeout. Its maximum
of 30 minutes matches the longest step timeout. A longer wait holds a chat
plan open longer than its user is likely to watch it; the post-back already
covers longer runs.

### The quick-run rule

`quick_run_eligibility(workflow, settings)` in
`functions_orchestration_workflow_run_wait.py` decides whether a plan may wait
for a run of a workflow. It reads only the stored workflow document and the
deployment's settings, never model output, and it returns a reason code for
every refusal. Anything it can't read refuses. Every rule must hold:

| Rule | Why |
| --- | --- |
| The wait is configured, and the workflow is the user's own personal workflow, not a group's. | A group workflow isn't the user's alone to wait for. |
| Durable execution is on. | Only a durable run records progress where a background continuation can read it. |
| It isn't being deleted, and isn't waiting on or resuming from Microsoft 365. | Neither can finish while the plan waits. |
| It isn't a one-time hand-off workflow. | A hand-off is large work sent out of the chat on purpose, and its report is always posted back. Hand-offs are never waitable. |
| Its flow has no For each or Repeat until node. | Their length depends on the data, so no bound fits them. |
| It isn't a structured (version 3) workflow. | Its result can't be read back into a chat answer. |
| No task needs approval. | An approval waits for a person. |
| It doesn't run as a Microsoft 365 user. | A run-as user can pause the run for that user's sign-in. |
| No task finishes only after a review or indexing (`approved` or `indexed_ready` publication). | Both wait on something outside the run. |
| It neither starts on File Sync nor runs a File Sync first. | File Sync waits for files to sync. |
| It has between one and five tasks (`QUICK_RUN_MAX_TASKS`). | Five covers the "gather, analyze, summarize" digests people start from chat and keeps a run's expected length inside the cap. |

The rule is checked three times: when the planning context marks each workflow
in its catalog `waitable`, when the run step starts, and on every continuation
while the step waits.

### Plan rules

`compute_workflow_run_waits(steps, final_response, workflow_planning)` decides,
when the plan is normalized, which step waits. A plan waits only when all of
these hold:

- It has exactly one enabled `workflow_run` step, and the step isn't optional.
- It uses no `web_search`, `url_fetch`, `deep_research`, `agent_invoke`,
  `action_invoke`, `workflow_propose` or `workflow_handoff` step
  (`SESSION_NEEDING_CAPABILITIES`). A waiting plan resumes in the background
  without the user's sign-in, and those need the signed-in session or the
  user's roles.
- Every capability it uses is still available to a background continuation
  (`headless_capability_ids`, computed with no roles, email or native bridge).
- The workflow's catalog entry is `waitable`.
- Only `compose` steps read the run step, directly or through another
  `compose` step. At least one enabled `compose` binds the run's `run` output
  through a required input, and the final response isn't the run step itself.
  It's the same masking rule as `workflow_results`, so no export, analysis,
  agent or action can copy the run's result out of the answer.
- **Require Membership In WorkflowUser** (`require_member_of_workflow_user`) is
  off, because a background continuation has no roles to check.

The result is a marker on the plan:
`plan['workflow_run_waits'] = {step_id: {'version': 1, 'workflow': handle}}`.
A marker the model wrote is discarded. A saved plan validated again keeps its
marker only when it still fits the plan exactly (`stored_workflow_run_waits`).

`drop_workflow_runs` keeps a run step another step reads only when the step is
in that marker. Any other run step that's read is dropped, as before, with a
note that the plan can't wait for it.

### Planner hint

`WORKFLOW_RUN_WAIT_INSTRUCTIONS` is added to the planner prompt only when the
planning projection marks at least one workflow `waitable`.
`waitable_projection` removes every `waitable` flag unless a wait is possible:
the server's wait marker is present, and `workflow_run` and `compose` are both
usable by a background continuation. Without the setting, the prompt and the
projection are unchanged.

### The bound

`workflow_run_wait_deadline` computes the wait's deadline when the run step
starts:

```text
deadline = min(now + cap,
               plan deadline - (90 s + step timeout x steps that use the result))
```

The plan keeps 90 seconds (`WAIT_RESERVE_SECONDS`) for the continuation that
notices the run finished, plus a step timeout for each step that uses the
result, so it can still write its answer. When less than 60 seconds
(`WAIT_MIN_SECONDS`) would be left, the step doesn't wait. With the defaults (a
300-second cap, a 900-second run timeout, a 180-second step timeout and one
compose step), the cap applies, so a plan waits up to five minutes.

### Wait kind and continuation

The wait kind is `SAVED_WORKFLOW_RUN_WAIT_KIND = 'saved_workflow_run'`, exported
from `functions_orchestration_workflow_run_wait.py` so that other features can
refuse it. The waiting step result carries
`wait = {kind, run_id, workflow_id, wait_deadline}`.

- `resume_waiting_dependency_step` in `functions_orchestration_executor.py`
  routes the kind to `resume_workflow_run_wait`.
- `_scheduled_wait_claimable` in `functions_orchestration_continuation.py`,
  formerly `_native_wait_claimable`, maps each scheduled wait kind to the one
  capability whose step may declare it: `native_tabular_compute` to
  `tabular_analyze`, as before, and `saved_workflow_run` to `workflow_run`.
- The orchestration scheduler doesn't change. It already picks up waiting runs
  once their lease expires.

Each continuation authorizes the wait again with `_reauthorize_wait`:

| Check | Reason when it fails |
| --- | --- |
| Run Workflows From Chat and the wait are still configured. | `wait_disabled` |
| The user still may run workflows and read their results. | `access_lost` |
| The conversation still exists and is still the user's. | `conversation_unavailable` |
| The conversation is still private. | `conversation_shared` |
| The workflow is still in the planning catalog, still exists and is still the user's personal workflow. | `workflow_unavailable` |
| The workflow is still a quick run. | `workflow_not_quick` |

A failure ends the wait cleanly. The plan releases its hold on the post-back,
and the post-back applies its own rules to a chat that was shared or deleted,
or to access that was lost. The answer promises no post, because those rules
may refuse it.

### Exactly-once delivery

The wait and the post-back share one record: the run's `chat_delivery`
document, which the post-back worker already claims with ETags. The wait adds
`chat_delivery.plan_wait`, and every change to it is a compare-and-set on that
document's ETag (`hold_chat_delivery`, `consume_chat_delivery` and
`release_chat_delivery` in `functions_orchestration_workflow_runs.py`, applying
`apply_plan_wait_hold`, `apply_plan_wait_consume` and `apply_plan_wait_release`
from `functions_workflow_chat_delivery.py`).

1. **Hold.** When the step starts waiting, `plan_wait` becomes `holding` until
   the deadline plus 120 seconds (`WAIT_HOLD_GRACE_SECONDS`). Only a record
   whose post hasn't begun can be held. While a hold is live, the post-back
   worker moves the post's next attempt to the end of the hold.
2. **Consume.** When the run finished and its result can be read, the step
   marks the record `delivered` with `notice_kind` `none`, `outcome_reason`
   `used_in_answer` and no message, and marks `plan_wait` `consumed`. The
   worker never posts a delivered record. A failed or cancelled run is consumed
   the same way, so the answer, not a post, says what happened.
3. **Release.** When the wait times out, is stopped, or fails its
   authorization check, the step marks `plan_wait` `released` and signals the
   post-back worker, which posts as usual.
4. **Lapse.** If the plan never comes back, the hold lapses on its own at its
   `until` time, and the post-back posts.

When the run finishes just as the wait times out, the compare-and-set picks one
winner. If the consume wins, the result is used in the answer and never posted.
If the post-back started its post first, the record is no longer unposted, so
the consume refuses and the step reports that the result is posted. Each
decision re-reads the record and retries on an ETag conflict.

### What later steps and the answer see

The run step completes with its usual `run` output, plus `wait`: the run id,
its status, its start and finish times, `outcome`, `posts_to_chat` and, for a
consumed run, `result_pointer`. The pointer holds ids and the result's digest,
never content.

A `compose` step that reads the run gets fenced, untrusted notes from
`workflow_results_compose_inputs`:

- **Consumed:** the result is read again through the `workflow_results`
  reader, which authorizes the read and checks the digest, and is fenced like
  any stored workflow result.
- **Any other outcome:** an application-owned note with the workflow's name,
  the run's status and how the wait ended.

| Outcome | Step | Answer note |
| --- | --- | --- |
| Consumed | Completes: "The saved workflow finished; its result is ready for this plan." | "Ran `X`. Its results were used in this answer." If no compose step could use them: "This answer couldn't use its results; they're in its run in Workflows." |
| Failed run | Fails with `workflow_run_failed`; steps that need it follow the plan's dependency rules. | "failed, so its results couldn't be used. Its run in Workflows says why." |
| Cancelled run | Fails with `workflow_run_cancelled`. | "was cancelled before it finished, so it has no results to use." |
| Timeout | Completes: "Still running. Its result will be posted to this chat when it finishes." | "Started `X`. It was still running when this answer was written." |
| Posted | Completes: "The saved workflow finished; its result is posted to this chat separately." | "Its results are posted to this chat separately." |
| Ended | Completes: "The plan stopped waiting for the saved workflow." | "Started `X`. The plan stopped waiting for it." |
| Stopped by the user | Cancelled. The run goes on, and its post-back is released. | "Started `X`. The plan stopped waiting for it." |

A timeout, a post and an end never fail the plan.

### Turning the setting off mid-wait

Each continuation checks the setting again (`wait_disabled`). A settings change
also changes the step's input fingerprint, and a continuation refuses a step
whose inputs changed (`result_input_changed`), so the plan stops. Its hold
lapses at the deadline plus 120 seconds, and the post-back then posts the
result once.

### Timing

The orchestration scheduler runs every 30 seconds and claims up to four due
runs per tick, and a claim's lease lasts 45 seconds. A waiting step is checked
again once its run's lease expires, so after a run finishes the plan notices it
within about 75 seconds when the scheduler isn't backlogged. With more than
four due runs per tick, it can take longer. The 120-second hold grace outlasts
that delay, so the post-back never posts a result a plan is about to use.

### V2

- The plan card's progress line shows the waiting step's summary:
  `Waiting for "<name>" to finish (up to N min).` The name comes from the
  server as plain text and renders as text (`workflowRunWaitingLine` in
  `orchestrationPlan.ts`). The steps that use the result show the existing
  "Waiting for required results."
- The started-workflow card says "Its results were used in a chat answer." for
  a run whose delivery is `delivered` with reason `used_in_answer`, and never
  offers a jump to a posted message for it (`workflowFinishedResultsText` in
  `workflowRunStatus.ts`).
- The run tracker and the notifications bell don't change. Both announce a
  delivery only when it has a message id, and a consumed delivery has none.

No routes were added.

### File structure

| File | Change |
| --- | --- |
| `functions_orchestration_workflow_run_wait.py` | New: the quick-run rule, plan rules, bound, marker, planner projection and the wait kind. |
| `functions_orchestration_workflow_runs.py` | Starting, observing, consuming and ending a wait, the step summaries and the answer note. |
| `functions_workflow_chat_delivery.py`, `functions_workflow_chat_delivery_worker.py`, `functions_workflow_chat_delivery_status.py` | `plan_wait` hold, consume and release, the worker's deferral, and the `used_in_answer` reason. |
| `functions_orchestration_executor.py`, `functions_orchestration_continuation.py` | The wait kind's resume path and scheduled claim. |
| `functions_orchestration_workflow_results.py`, `functions_orchestration_composition.py` | Compose reads a waited run through the results reader. |
| `functions_orchestration_planner.py`, `functions_orchestration_schema.py`, `functions_orchestration_plan_editing.py`, `functions_orchestration_workflow_context.py`, `functions_orchestration_registry.py`, `functions_orchestration_execution.py` | The marker, the gated hint, the `waitable` catalog flag and the headless context. |
| `functions_settings.py`, `functions_workflow_limits.py`, `admin_settings_fields.py`, `route_frontend_admin_settings.py`, `templates/admin/_panes/chat-orchestration.html` | The setting and the cap. |
| `v2_ui/src/lib/orchestrationPlan.ts`, `v2_ui/src/lib/workflowRunStatus.ts`, `v2_ui/src/components/chat/WorkflowRunCard.tsx` | The waiting line and the used-in-answer text. |

## Usage instructions

1. Turn on **Chat Orchestration**, personal workflows, **Run Workflows From
   Chat** and, in Workflow settings, **Use Workflow Results In Chat**.
2. Turn on **Wait For Quick Workflows In Chat** on the Orchestration tab.
   Optionally change **Wait For A Workflow From Chat (seconds)**.
3. A user turns on **Orchestrate** in a private chat and asks to run a quick
   workflow and use its result, for example "Run my sales-digest workflow,
   then compare its totals with the Q3 report in my workspace."
4. The plan card always waits for the user to approve it, because a plan that
   starts a workflow stays on the manual approval floor.
5. While the run goes on, the plan card shows
   `Waiting for "sales-digest" to finish (up to 5 min).`
6. When the run finishes in time, the answer uses its result and says so, and
   nothing is posted later. Otherwise the answer says the workflow was still
   running, and its result is posted into the chat when the run finishes.

User documentation: [Trigger a workflow](../../guides/trigger-a-workflow.md).
Admin documentation: [Orchestration settings](../../admin/orchestration.md).

## Testing and validation

| Test | Covers |
| --- | --- |
| `test_orchestration_workflow_run_wait_off_golden.py` | With the setting off, normalization and execution match output captured from the base version. |
| `test_orchestration_workflow_run_wait_eligibility.py` | Each quick-run rule and its reason, including the hand-off refusal, the settings gate, and that model fields are ignored. |
| `test_orchestration_workflow_run_wait_plan_rules.py` | The plan rules: one run step, headless capabilities, compose-only consumers, and the server's marker. |
| `test_orchestration_workflow_run_wait_planner.py` | The `waitable` catalog flag, normalization, `drop_workflow_runs`, the gated hint and plan revisions. |
| `test_orchestration_workflow_run_wait_delivery.py` | The bound, the hold, consume and release, the worker's deferral, and the finish-versus-timeout race in both orders. |
| `test_orchestration_workflow_run_wait_execution.py` | Waiting, consuming within the bound, a timeout with one post, failed and cancelled runs, a user stop, the races, re-authorization failures mid-wait and setting changes. |
| `test_orchestration_workflow_run_wait_claims.py` | The scheduler claims each wait kind only for its own capability, including native tabular waits as before, and respects the lease. |
| `test_orchestration_workflow_run_wait_results.py` | Compose reads a consumed result through the re-authorizing reader, and every other outcome becomes a fenced note. |
| `test_v2_orchestration_run_progress_status.mjs`, `test_v2_workflow_run_status.mjs`, `test_v2_workflow_run_tracker.mjs` | The V2 waiting line, the used-in-answer text, and that the tracker never announces a used result. |
| `ui_tests/test_v2_workflow_run_wait.py` | The waiting line and the run card in the browser, with hostile workflow names. |

Every Python test runs under pytest, under `pytest -O`, as a script and as an
`-O` script.

### Known limitations

- Only one waited run per plan, and only personal workflows.
- The plan finds out the run finished by polling, so it can take up to about
  75 seconds longer than the run.
- While a plan waits, the run's delivery is `pending`, so a started-workflow
  card for the run elsewhere would say "Posting results…" until the plan uses
  the result. The card under the answer appears only after the plan finishes.
- If storage fails between consuming the result and saving the step, the
  result stays in the run's history and isn't posted.
- A plan that stops for another reason while it waits keeps its hold until the
  hold lapses, up to the deadline plus 120 seconds, before the post-back
  posts.
