---
layout: page
title: "Trigger a workflow"
description: "Run a workflow now, schedule future runs, and inspect run activity."
section: "Guides"
audience: user
version: "0.261.122"
---

## What this does

This guide starts a saved workflow, explains scheduling, and points you to the activity view after a run begins. It applies to personal and group workflows.

{% include media.html type="video"
                      title="Trigger a workflow walkthrough"
                      poster="video-posters/guide-trigger-a-workflow.png"
                      capture="Recording planned. Show trigger a workflow end to end and explain why this task helps a user." %}

## Why you would use this

A workflow only helps when it runs at the right moment and leaves evidence you can inspect. Manual runs are best for tests and controlled work; schedules fit routine checks. A scheduled durable run can wait for approval, but later due triggers do not overlap that waiting run.

## Before you start

- Create the workflow first.
- The relevant toggle must be enabled: `allow_user_workflows` or `allow_group_workflows`; see [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- If the workflow uses File Sync, the selected source must be enabled and reachable.

## Steps

1. Open the workspace that owns the workflow.
2. Choose **Workflows**.
3. Search with **Search workflows by name, runner, or task prompt...** if needed.

{% include media.html src="guides/trigger-a-workflow-step-3.png"
                      alt="The personal workspace Workflows tab listing a saved workflow with its runner, manual trigger, last run status, and the Run, Activity, and History buttons."
                      title="Trigger a workflow step 3"
                      capture="Capture the trigger a workflow task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Use the workflow row **Actions** to start a manual run, or edit the workflow to adjust **Trigger**.
5. For scheduled operation, choose an interval trigger and leave the workflow enabled.
6. After a run starts, open **Open workflow activity view** from the chat header when available.

{% include media.html src="guides/trigger-a-workflow-step-6.png"
                      alt="Screenshot showing trigger a workflow step 6."
                      title="Trigger a workflow step 6"
                      capture="Capture the trigger a workflow task at this step in SimpleChat with realistic sample data and redact secrets." %}

7. Review status, task output, failures, and completion alerts in activity or history.

## Verify it worked

The workflow's **Last Run** updates, and the activity view or history shows the run status and task output.

## Continue a durable run

With durable execution enabled in **0.261.111**, **Run** queues background work
rather than keeping a browser request open. Open its V2 run history to inspect
progress and run memory. Closing the page does not cancel the run.

**Waiting for approval** needs an authorized decision. **Waiting for output**
keeps the original background result reference and resumes when its supported
final representation becomes available; a preview does not satisfy that gate.
**Waiting for recovery** means an action might already have happened. Inspect
the external destination before confirming a retry.

Resume continues the same definition and reuses completed checkpoints. It does
not silently pick up edited source content. Cancel and start a new run if its
saved inputs changed. Cancelling fences further checkpoint writes but cannot
undo an email, upload, or other completed external action.

Classic workflows remain synchronous unless opted in. Classic can run and cancel
durable definitions, but V2 provides their approval, checkpoint-resume, and
memory controls. See [Durable workflow execution](../explanation/features/WORKFLOW_DURABLE_EXECUTION.md).

### Microsoft 365 authorization waits

V2 compatibility in **0.261.122** preserves `awaiting_approval`,
`awaiting_sharing_approval`, `awaiting_analysis_approval`,
`awaiting_run_as_approval`, and `awaiting_sign_in` as active waits, not failed
runs. A `m365_authorization` pause explains which approval or connection step
is needed.

Follow that reason in **Approvals** or Microsoft 365 connection settings.
Generic workflow **Resume** and **Approve task** do not satisfy this gate;
authorized operators can still cancel. After authorization, the dedicated
Microsoft 365 continuation uses the durable engine to continue the same run.
Selecting a Run as account in the editor is not itself authorization.

## Inspect a structured path

For definition-version-3 workflows introduced in **0.261.116**, inspect the
selected If/else path and each task's skip reason before interpreting a missing
output as a failure. A false **Run when**, an unselected branch, and a validated
forward route are intentional skips; they do not create empty successful
results.

Execution and attempt identities distinguish the exact result and approval
being inspected. Use the paged execution/decision views rather than treating
the task name or the latest reply as the producer identity. Result excerpts
load separately and remain subject to current source permissions.

Required final outputs and selected-path work determine completion. A budget
or deadline limit cannot be cleared by a normal Resume, and changing source
data cannot silently choose a different branch. See
[Structured workflow control flow](../explanation/features/WORKFLOW_STRUCTURED_CONTROL_FLOW.md).

## Inspect a run's frozen Flow

In **0.261.121**, expand a version-3 run in V2 history and choose **Show Flow
for this run**. **Run's frozen definition** is the exact configuration admitted
for that run, even if someone later edited the saved workflow or reused a node
name. Missing snapshots report an error instead of showing today's definition.
**Hide Flow for this run** returns to the execution list.

Select a node to inspect its exact execution and attempts. One bounded
metadata page is loaded; **Not loaded** does not mean Pending or Completed.
**No execution recorded** is an explicit lookup result, not an empty successful
output. Configuration sections, result excerpts, full records, and contributor
pages remain separate requests.

Then/Else and body regions group the structure rather than having separate
execution records. Inspect their enclosing control or a contained task for
run evidence; a recorded If-path label comes from that exact instance's saved
decision.

Loops show one template. Inspect the enclosing loop's frozen item or Repeat
round pages, then choose **Use item N in Flow** or **Use round N in Flow**.
That selects the exact mixed instance path, including its outer item/round.
An unselected template cannot stand in for its latest execution.

The runtime panel keeps its own authorized approval, recovery, Resume, and
continuation controls outside Flow. Its actual gate overrides retained Repeat
counters. Inspect execution status, output validation, and saved publication
observations separately: a submitted file is not necessarily approved or
indexed-ready, and graph refresh does not perform a new readiness check.

On narrow screens, **Structure list** is the initial read-only presentation;
**Flow diagram** enables the optional picture. Both use the same inspector.
For configuration without run evidence, use the
[saved or unsaved-draft view]({{ '/guides/create-a-workflow/' | relative_url }}#preview-the-structure-without-changing-execution).

## Inspect loop progress

For each runs introduced in **0.261.117** retain their frozen item count, order,
and keys. Inspect an item and its exact execution/attempt rather than relying on
the repeated task name. An approval or recovery confirmation for one item does
not apply to another.

Use the paged item, record, and contributor views to inspect a large run.
Successful empty results, intentional skips, partial coverage, failures, and
pending work are different outcomes. Collect retains records exactly; an
accepted subset remains visibly partial.

Resume reuses successful siblings and the saved item cursor. It does not rerun
a workspace query or adopt a newly changed administrator ceiling. An
over-limit selection must be narrowed for a new run; a paused unsafe large-input
task retains its data rather than receiving a truncated substitute.

See [Serial For each and exact Collect](../explanation/features/WORKFLOW_FOR_EACH_COLLECT.md).

## Continue a Repeat batch

In **0.261.120**, **Repeat until** saves the state admitted for each round and
its validated next state. Inspect lifetime round, current automatic batch,
batch usage/limit, condition outcome, exact producer attempts, partial coverage,
and remaining global budgets. Paged inspection avoids loading every round or
record at once; an uncommitted after-state is unavailable, not an empty result.

If the condition is still false at the authored maximum, the workflow pauses.
Review the retained state before choosing **Continue Repeat for up to another
N rounds** and confirming the grant. Only users with the current workflow
decision permission may do this. A stale or already-used gate must refresh
rather than create another grant.

This grants the same frozen batch size, even if an administrator has since
changed the Repeat setting. Only batch usage resets; lifetime round numbers,
cumulative execution admissions, and the original elapsed deadline do not.
Waiting for a person consumes elapsed time. The shared limits remain at most
5,000 admissions and 86,400 seconds, and can block further continuation.

Ordinary Resume, polling, scheduled triggers, retries, and a model's response
cannot grant another batch. The grant does not approve body tasks or workspace
publication, and cannot make failed, invalid, pending, or unauthorized state
usable. If a separate budget or access gate is the blocker, address that exact
gate rather than treating it as a Repeat-limit pause.

A true condition completes Repeat, including on the last allowed round.
Only then are its declared final exports eligible for downstream tasks.
Earlier saved state and accepted partial limitations remain retained.
See [Repeat until](../explanation/features/WORKFLOW_REPEAT_UNTIL.md).

## Inspect a saved-output publication

In **0.261.119**, a task explicitly configured with **Saved workflow output**
renders its selected saved records as JSON and submits that file to its chosen
destination. Run inspection identifies the exact producer, output and attempt;
a repeated task name or latest chat reply is not the source identity.

Repeat final records in **0.261.120** retain that same source-bound identity.
A new round with a genuinely new producer is distinct from retrying a
publication of one already saved output. Continuation never redirects an
existing immutable file to a newer source.

Use the existing generated-file card to download the full JSON, not a preview
of the first records. Record order, duplicates, nested values and retained
provenance are preserved. Accepted partial output remains visibly partial;
a file never supplies records that its producer did not save.

Reloading or resuming retains the same source representation and publication
receipt. It does not rerun Analyze or select a newer producer attempt merely
to obtain a file. A downloadable file is not proof that the destination is
approved or indexed-ready: inspect the separate completion observations.
An empty JSON array may be a valid file without searchable content.

Private downloads still require current conversation, workflow and source
access. Already-published workspace copies follow their own destination
permissions. See
[Publish saved workflow records]({{ '/guides/create-a-workflow/' | relative_url }}#publish-saved-workflow-records)
for source choices and requirements.

## Troubleshooting

### A publication is waiting

In **0.261.118**, version-3 durable publication tasks can wait for a chosen
completion level. Inspect the requested level and the separate submission,
approval, processing, screening and index observations in run details.

**Waiting for destination approval** means the request is in the existing
workspace review, not that the workflow's task-approval button can approve it.
If processing or indexing is pending, the run retains its exact receipt and
does not rerun Analyze or create another document just to check progress.

For uncertain effects or restored access, use Resume/check again only when
offered. It rechecks the existing receipt. A rejected request or changed
original content cannot silently satisfy the policy; cancel and start a new
authorized request where appropriate. The elapsed deadline still includes
these waits.

See [Workflow publication completion](../explanation/features/WORKFLOW_PUBLICATION_COMPLETION.md).

### Other run problems

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A scheduled workflow does not run | It is disabled or still configured for manual trigger | Edit the trigger and confirm the workflow is enabled. |
| A run fails immediately | A runner, action, document, or File Sync source is unavailable | Open run details, fix the dependency, and run again. |

## Related

- [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }})
- [Create a file sync]({{ '/guides/create-a-file-sync/' | relative_url }})
- [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }})
