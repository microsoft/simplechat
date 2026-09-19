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

## Choose branches and optional work

In **0.261.116**, **Enable structured control flow** explicitly converts a V2
draft to definition version 3. Existing workflows stay ordered unless you
choose this conversion; nothing is persisted until **Save workflow**.

Use a JSON output contract with **Structured decision fields** when a task
must supply a Boolean, number, or enum for a decision. Add **If/else**, bind
that saved output by name, and choose the field and comparison. Put the
appropriate tasks in **Then** and **Else**, then configure **Join outputs**
to give later tasks one explicit result from the selected path.

**Run when** skips a task when its condition is false. A skipped task produces
no output, so downstream consumers need an optional binding or a required join
output. **Forward route** may bypass optional work only by selecting a later
sibling or exiting the current branch to its join. Invalid dependencies are
shown before saving; moving a block never silently changes its input source.

Declare promised deliverables under **Final outputs**. This prevents a run from
reporting completion when a selected path did not produce the required result.
Structured definitions require durable execution and preserve their choices
across waits and restarts. For each and Collect are added in **0.261.117** below.
Repeat until is added in **0.261.120** below. M5A read-only Flow and M5B visual
authoring remain separate later milestones.

See [Structured workflow control flow](../explanation/features/WORKFLOW_STRUCTURED_CONTROL_FLOW.md)
for condition semantics, execution identity, limits, and compatibility.

## Process a frozen collection

In **0.261.117**, add a **For each** block to apply its body to selected
documents, an earlier complete saved collection, or a workspace query. For a
query, choose exhaustive metadata/keyword matches or an explicit **Best N**
relevance selection. A preview is advisory; the loop freezes its actual
membership when it starts and does not reselect documents on Resume.

The default administrator ceiling is 500 items, configurable from 1-5,000 for
new runs only, and the editor shows the effective limit. This counts actual
loop visits, not the searchable workspace. If the selection is too large,
narrow it before running; no first-500 subset is silently substituted.

Bind the current item to body tasks and choose current-document Analyze when
appropriate. Keep shared criteria in shared references. Declare the body's
exact output, then add **Collect** outside the loop to preserve every eligible
record in item/producer order. A later task binds to Collect, not to whichever
child ran last.

For a qualitative explanation of a large collected dataset, explicitly choose
**Saved-record report** processing. Original records remain stored while the
report uses bounded calls and source-linked support. Ordinary tasks pause if
their full input cannot safely fit; they do not silently become summary tasks.

See [Serial For each and exact Collect](../explanation/features/WORKFLOW_FOR_EACH_COLLECT.md)
for local-runner requirements, partial coverage, nested scopes, and limitations.

## Refine saved state with Repeat until

In **0.261.120**, use **Repeat until** when each round should work on saved
state from the preceding round, such as a report draft and a structured review
decision. It is a serial, post-body loop: the body always runs at least once.
Select an eligible model or local agent; hosted non-loop workflows are
unchanged, but hosted loop execution is unavailable.

1. Produce the initial data in earlier tasks, then add **Repeat until**.
   Declare named state with explicit `text`, `json`, `records`, or
   `document_results` contracts. Select each initial saved output; entering
   starting literals is not supported.
2. Choose **Maximum rounds before manual continuation** explicitly. The field
   starts unset. The administrator ceiling defaults to 25 and can be 1-1,000;
   this is separate from For each's 500-item default and the global run budgets.
3. Bind body tasks to **Current Repeat state**, declare their body outputs, and
   select a next body output for every state slot. To keep data unchanged,
   explicitly pass through its current-state receipt rather than asking a
   model to echo it.
4. Under **Stop after a round when**, select typed next-state fields. Use a
   schema-validated Boolean such as `review.ready`, not a sentence saying the
   work is complete. Configure explicit final exports for later tasks.
5. Save and reopen the workflow to review those exact bindings. An invalid
   removal or move keeps the binding and reports the problem rather than
   silently choosing another producer.

The final exports become available only when the condition is true, including
when it first becomes true on the last allowed round. Otherwise the workflow
pauses at the batch limit with prior outputs and next state retained. See
[manual continuation](trigger-a-workflow.md#continue-a-repeat-batch) before
granting another batch.

Partial state is rejected unless the producer, state slot, and relevant
consumers explicitly accept it. Accepted coverage limitations remain visible
through later rounds and final results. Approval cannot repair failed,
invalid, pending, missing, or unauthorized data.

See [Repeat until with saved typed state](../explanation/features/WORKFLOW_REPEAT_UNTIL.md)
for state contracts, frozen policy, mixed nesting, and exact result identity.

## Durable execution and task approval

Starting in **0.261.111**, new V2 workflows enable **Durable execution**.
Existing workflows keep their previous setting until you opt in. The run saves
its definition, completed task results, and decisions so closing the browser or
restarting a worker does not discard progress.

For a task that needs a review before execution, enable its approval requirement
and explain what the reviewer should inspect. In run history, review the gate
and choose whether to approve or reject it. Approval applies only to those
specific inputs; it cannot make an invalid output valid.

Run memory shows checkpoint units, attempts, and decisions. If a worker may have
performed an external action without saving its result, a recovery gate asks you
to check the destination before retrying. This is different from rerunning every
task. See [Durable workflow execution](../explanation/features/WORKFLOW_DURABLE_EXECUTION.md)
for readiness, recovery, and cancellation limits.

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

## Microsoft 365 Run as

When a workflow uses Calendar, Email, OneDrive, or SharePoint actions, select an
explicit **Microsoft 365 Run as** account. Manual and scheduled runs use that
account, not the person pressing Run or an application identity.

The selected person must connect Microsoft 365 from Profile and approve the
workflow's sources, instructions, and destinations. Material changes require
renewed approval. Missing approval or sign-in pauses the operation and creates
a notification; the person can respond from Approvals without reopening the
conversation.

When a mail or calendar action uses manual delivery, its separate review is sent
to the Run as user and shown in workflow activity. Other group members can see
the run without gaining permission to send from that person's account.

See [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
for the controls introduced in **0.261.029**.

## Verify it worked

The workflow appears in the Workflows table with **Name**, **Runner**, **Trigger**, **Last Run**, and **Actions** columns.

## How task results are passed

Starting in **0.261.106**, each task saves its final output separately from presentation and diagnostic notes. The next task reads the preceding successful task's authoritative output directly; generated results do not need to be uploaded into a workspace or re-indexed first.

The former 12,000-character task-handoff cap no longer clips the middle of a result. The effective model's context budget determines whether the complete selected output fits. If it does not, the result remains stored and the dependent task reports the budget problem instead of receiving a shortened substitute.

This preserves the producer's final data; it does not guarantee that an extraction is semantically complete. Prefer a clear final output format, such as a JSON record array, when another task must consume structured findings. See [Workflow data flow](../explanation/features/WORKFLOW_DATA_FLOW.md) for result references and limitations.

For Analyze results produced in **0.261.109**, a later explanation uses accepted
findings and their saved provenance. Ordinary narrative analysis does not require
you to configure columns or scoring. Read
[Saved Analyze results](analyze-results.md) for the difference between source
coverage, accepted findings, and validation.

## Publish an existing analysis artifact

In the V2 List editor, enable **Publish a workflow file** on a later task and
choose **Existing Analyze file** as its **Publication source**. Servers without
the new source options retain **Publish an existing analysis artifact**.
Choose an **Existing artifact format** and **Destination scope**. A group or
public destination also requires its **Destination workspace ID**. That
destination is saved with the task; changing your active workspace later
does not redirect the publication.

This task copies an existing artifact rather than calling a model to recreate
it. Ensure the analysis produced the selected format. Passing validation alone
does not publish anything: this explicit task or a manual workspace-save action
is required. This native-artifact path does not publish partial or invalid
results as final outputs. Existing definitions with no explicit publication
source keep native Analyze behavior.

Group and public copies retain their approval process. An uncertain publication
shows the existing destination/receipt instead of blindly creating another copy.
Once explicitly published, the copy follows the destination's access rules.

## Publish saved workflow records

In **0.261.119**, a version-3 durable workflow can publish records from a real
task, **Collect**, or an explicit **Join outputs** selection. Use this when you
need the complete collected dataset as a file, rather than an explanation of
the dataset or a copy of one native Analyze artifact.

In **0.261.120**, a satisfied **Repeat until** boundary can also supply a named
eligible records export, directly or through a join. An exhausted batch does
not expose a final export; current-state metadata is not a publication source.
The same exact JSON renderer, immutable file identity, and destination receipt
remain in use.

1. Produce an eligible records output. For example, Analyze each document in a
   frozen For each selection, then Collect the records outside the loop.
2. In a later task, enable **Publish a workflow file** and explicitly select
   **Saved workflow output**. Bind exactly one required records output from
   the chosen producer. Do not select the current loop item, diagnostics,
   text, an arbitrary JSON value, or a per-document results bundle.
3. Choose **JSON - exact saved records**, an explicit destination, and the
   completion level described below.

The JSON array contains every selected saved record object, including nested
values and retained provenance, in the saved order. Repeated records stay
repeated. It is not a preview or a model reconstruction; serialization preserves
JSON values rather than an uploaded document's original formatting. The
original records remain available to later tasks through their typed bindings.

Partial coverage is usable only when both the producer/Collect policy and the
publishing input explicitly accept it. It stays visibly partial. Invalid
uniqueness, failed or pending results, unavailable sources, and files exceeding
the configured limit fail rather than being silently repaired or truncated.

This Publish task creates a downloadable file through the shared Generated
File Export Framework **and submits it to the selected workspace**; it is not
a new download-only mode. Generic CSV, Markdown, Word/DOCX, PDF, PowerPoint/PPTX
and XML mappings are not enabled. Those are future extensions of the same
framework; existing native formats keep their behavior.

If the server does not advertise saved-output publication, the option is
unavailable rather than silently falling back to native Analyze. Unsupported
saved source/format configurations remain intact and read-only.

## Choose when publication completes

Starting in **0.261.118**, a version-3 durable publication task can choose
**Complete publication when**: **Submitted**, **Approved**, or **Indexed and
ready**. Use Submitted to hand a deliverable into a review queue; use Indexed
and ready when the next step depends on workspace retrieval. Personal
workspaces do not have a destination approval gate, so Approved reports
approval as not required. These same levels apply to Saved workflow output
in **0.261.119**.

New publication tasks default to Submitted when the server advertises support.
Existing tasks retain their previous behavior until you explicitly choose a
policy. Queued, approved and indexed-ready are different stages; a failed or
uncertain explicit policy pauses instead of publishing another copy or
continuing on error. A valid JSON download, including an empty array, does not
prove that its destination has searchable content. See
[Workflow publication completion](../explanation/features/WORKFLOW_PUBLICATION_COMPLETION.md)
for readiness proof, screening and recovery limitations.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The Workflows section is missing | Workflows are disabled for the scope | Ask an admin to enable personal or group workflows. |
| No agents are available as runners | No authorized agents exist for this workspace | Create an agent first or use a direct model runner. |

## Related

- [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }})
- [Create an agent]({{ '/guides/create-an-agent/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
