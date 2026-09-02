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

A workflow only helps when it runs at the right moment and leaves evidence you can inspect. Manual runs are best for tests and controlled work; schedules fit routine checks that can run unattended. Do not schedule workflows that require approval before each step.

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

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A scheduled workflow does not run | It is disabled or still configured for manual trigger | Edit the trigger and confirm the workflow is enabled. |
| A run fails immediately | A runner, action, document, or File Sync source is unavailable | Open run details, fix the dependency, and run again. |

## Related

- [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }})
- [Create a file sync]({{ '/guides/create-a-file-sync/' | relative_url }})
- [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }})
