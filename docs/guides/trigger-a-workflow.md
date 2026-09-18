---
layout: page
title: "Trigger a workflow"
description: "Run a workflow now, schedule future runs, and inspect run activity."
section: "Guides"
audience: user
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

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A scheduled workflow does not run | It is disabled or still configured for manual trigger | Edit the trigger and confirm the workflow is enabled. |
| A run fails immediately | A runner, action, document, or File Sync source is unavailable | Open run details, fix the dependency, and run again. |

## Related

- [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }})
- [Create a file sync]({{ '/guides/create-a-file-sync/' | relative_url }})
- [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }})
