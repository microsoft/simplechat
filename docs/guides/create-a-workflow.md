---
layout: page
title: "Create a workflow"
description: "Save a repeatable multi-step task that can run manually or on a schedule."
section: "Guides"
audience: user
---

## What this does

A workflow is an ordered set of instruction tasks that runs with a selected model or agent. This guide creates a workflow with runner, trigger, tasks, reliability choices, and review.

{% include media.html type="video"
                      title="Create a workflow walkthrough"
                      poster="video-posters/guide-create-a-workflow.png"
                      capture="Recording planned. Show create a workflow end to end and explain why this task helps a user." %}

## Why you would use this

Use workflows for repeatable work where sequence matters: weekly document checks, multi-stage summaries, or group processes that should run the same way each time. It replaces copying a checklist into chat; it is not ideal for exploratory conversations that need a human decision after every answer.

## Before you start

- Personal workflows require `allow_user_workflows`; group workflows require `allow_group_workflows`; see [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- Admins may require `require_member_of_workflow_user` before users can create workflows.
- If tasks use documents, upload them or configure File Sync first.

## Steps

1. Open **Personal Workspace** or a **Group Workspace**.
2. Choose **Workflows** from **Section** or the tab row.
3. Select **New Personal Workflow** or **New Group Workflow**.

{% include media.html src="guides/create-a-workflow-step-3.png"
                      alt="The Create Group Workflow dialog on the General step, showing the workflow name, default runner, description, and model source fields, with Trigger, Tasks, Reliability, and Review still ahead."
                      title="Creating a group workflow"
                      capture="Capture the create a workflow task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. In **General**, enter a name, description, and default runner.
5. In **Trigger**, choose manual execution or a scheduled interval.
6. In **Tasks**, write the first task instructions and add more tasks with **Add Task**.
7. For each task, decide whether it inherits the runner or uses a specific **Direct Model** or **Agent**.
8. Optionally set a document action such as **Search**, **Analyze**, or **Compare**.

{% include media.html src="guides/create-a-workflow-step-8.png"
                      alt="Screenshot showing create a workflow step 8."
                      title="Create a workflow step 8"
                      capture="Capture the create a workflow task at this step in SimpleChat with realistic sample data and redact secrets." %}

9. In **Reliability**, choose retry and failure behavior, then review and save.

## Verify it worked

The workflow appears in the Workflows table with **Name**, **Runner**, **Trigger**, **Last Run**, and **Actions** columns.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The Workflows section is missing | Workflows are disabled for the scope | Ask an admin to enable personal or group workflows. |
| No agents are available as runners | No authorized agents exist for this workspace | Create an agent first or use a direct model runner. |

## Related

- [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }})
- [Create an agent]({{ '/guides/create-an-agent/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
