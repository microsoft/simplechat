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

## Create or edit in V2

Starting in **0.261.108**, open `/v2/workspace/workflows` for personal workflows,
or select a group under `/v2/groups`. Choose **Create workflow** or edit an
existing workflow in the native List editor.

Choose a runner and manual or interval trigger, then add tasks in execution
order. Task details separate document-action evidence from shared reference
documents and prior-task outputs. For a synthesis task, select a specific
earlier task under **Previous-task inputs** instead of depending on an
intermediate note's reply. Reordering never silently retargets that binding.

Use optional output requirements when later work needs a particular JSON
shape, record identity, count, or complete source coverage. Partial acceptance
is off by default and remains visibly partial when enabled. These requirements
validate returned data; they do not prove factual correctness or undo an
agent's earlier tool actions.

Legacy single-prompt instructions and existing settings are retained when
opened in V2. Advanced definitions cannot be saved through the classic editor
because it cannot represent their data-flow fields. A stale edit retains its
draft instead of overwriting another editor's changes.

See [Explicit workflow data flow](../explanation/features/WORKFLOW_EXPLICIT_DATA_FLOW.md)
for binding semantics, shared references, and validation outcomes.

## Classic interface steps

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

## How task results are passed

Starting in **0.261.106**, each task saves its final output separately from presentation and diagnostic notes. The next task reads the preceding successful task's authoritative output directly; generated results do not need to be uploaded into a workspace or re-indexed first.

The former 12,000-character task-handoff cap no longer clips the middle of a result. The effective model's context budget determines whether the complete selected output fits. If it does not, the result remains stored and the dependent task reports the budget problem instead of receiving a shortened substitute.

This preserves the producer's final data; it does not guarantee that an extraction is semantically complete. Prefer a clear final output format, such as a JSON record array, when another task must consume structured findings. See [Workflow data flow](../explanation/features/WORKFLOW_DATA_FLOW.md) for result references and limitations.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The Workflows section is missing | Workflows are disabled for the scope | Ask an admin to enable personal or group workflows. |
| No agents are available as runners | No authorized agents exist for this workspace | Create an agent first or use a direct model runner. |

## Related

- [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }})
- [Create an agent]({{ '/guides/create-an-agent/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
