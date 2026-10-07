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

4. Use the workflow row **Actions** to start a manual run, or edit the workflow to adjust **Trigger**. In V2, select the workflow and choose **Run** beside its name; its **Runs** tab opens on the new run.
5. For scheduled operation, choose the **Schedule** trigger (**Interval Schedule** in the classic editor) and leave the workflow enabled. It can repeat at a fixed interval or, in the V2 editor, at a local time on a calendar schedule; see [Run on a calendar schedule]({{ '/guides/create-a-workflow/' | relative_url }}#run-on-a-calendar-schedule).
6. After a run starts, open **Open workflow activity view** from the chat header when available.

{% include media.html src="guides/trigger-a-workflow-step-6.png"
                      alt="Screenshot showing trigger a workflow step 6."
                      title="Trigger a workflow step 6"
                      capture="Capture the trigger a workflow task at this step in SimpleChat with realistic sample data and redact secrets." %}

7. Review status, task output, failures, and completion alerts in activity or history.

## Verify it worked

The workflow's **Last Run** updates, and the activity view or history shows the run status and task output.

## Run a workflow from chat

Since **0.261.212**, you can ask chat orchestration to start one of your saved personal
workflows, for example "run my weekly digest now". The plan starts the same background
run that **Run** does, so the run appears in the workflow's run history like any other.

Before you ask:

- Your administrator must turn on **Run Workflows From Chat**, and you need access to
  personal workflows.
- The workflow must have **Durable execution** on. Check it in the V2 workflow editor.
- Ask from a conversation that's private to you. A shared conversation can't start
  workflows.

1. Turn on **Orchestrate**, name the workflow, and ask to run it now. Asking about a
   workflow, or asking for work on a schedule, doesn't start one.
2. Check the plan card. It names each workflow the plan would start and always waits for
   you, even when your approval mode is a countdown or Auto. A workflow that's turned off
   shows **Paused**. Starting it here runs it once and leaves it turned off.
3. Select **Approve**. The plan starts each workflow once.
4. Read the answer. It says which workflows started, and which didn't and why.
5. Under the answer, each started workflow shows its run's status: the step it's on,
   the time elapsed, and anything it needs from you. V2 keeps checking while the run
   is in flight, even while you're on another page. Select **Check now** to check
   straight away, or **Open run** to follow it in the workflow's run history.

The plan doesn't wait for the workflow to finish. While a run is going, a spinner beside
its chat in the chat list says so. From the card you can cancel a run that's still going
with **Cancel run**, and resume a failed one with **Retry**, which continues the same run
instead of starting another. Stopping the plan doesn't stop a workflow it already
started. Retrying a failed step of the plan never starts a workflow twice: when the plan
already started it, the retry links that run instead.

When your administrator also turns on **Use Workflow Results In Chat**, a
durable personal run started from chat can post its outcome back into that same
private chat after it finishes. The chat is marked unread, and a bell
notification opens the chat. If the chat was deleted or shared before delivery,
you get a workflow notification that opens the run instead. A posted result has
**Follow up**, to ask about it in the same chat, and **Open run**. A note that the
run failed offers **Retry workflow run** while the run can still be resumed.
Without that setting, results arrive where the workflow already sends them, such
as its conversation or alerts. See
[Results posted to the chat]({{ '/reference/chat-controls/' | relative_url }}#results-posted-to-the-chat).

A workflow that's already running isn't started again; the answer says so, and you can
start it once that run finishes. If a run the plan started waits for a Microsoft 365
approval or sign-in, its status shows **Needs you**, and for a sign-in the card offers
**Reconnect Microsoft 365**; follow
[Microsoft 365 authorization waits](#microsoft-365-authorization-waits) to continue it.

## Hand large work off to a workflow

Since **0.261.293**, a request too big for one chat plan, such as "review every
contract in my Legal workspace and list the renewal terms", can be handed off to a
one-time workflow. The workflow reviews each document, writes one report, and posts
the outcome back into the chat. It runs in the background, so the work goes on after
the chat turn ends and can resume after an interruption.

Before you ask:

- Your administrator must turn on **Hand Off Large Work From Chat** and the settings
  it needs, and you need access to personal workflows.
- Ask from a conversation that's private to you. A shared conversation can't hand
  work off.
- Name the documents to review, or the workspace to search. A hand-off reviews at
  most 25 named documents, or a bounded number of documents from a workspace search;
  the card says how many.

1. Turn on **Orchestrate** and describe the work, naming the documents or the
   workspace.
2. Check the plan card. It says the plan hands work off to a one-time workflow and
   always waits for you, even when your approval mode is a countdown or Auto.
3. Select **Approve**. Approving only prepares the workflow. The answer says
   "Prepared a one-time workflow for this request. Nothing runs until you approve it
   on the hand-off card."
4. Read the **Workflow hand-off** card under the answer. It says what the workflow
   covers, such as "200 documents" or "up to 500 best-matching documents", which
   workspaces it searches, its two tasks and what each runs on, and when the offer
   expires.
5. Choose and confirm:
   - **Accept** creates the workflow, turned off so it never runs on a schedule, and
     starts its one run.
   - **Edit** opens it in the workflow editor first. **Save** creates the workflow as
     edited and starts its run.
   - **Decline** creates nothing.
6. Follow the run on the card: its status, the step it's on and the time elapsed,
   with **Cancel run** and **Open run**. When the run ends, its outcome is posted in
   this chat.

An edit must keep the manual trigger and the For each over the documents or the
workspace search, and its tasks can use only your own local agents. URL Access and
Run as aren't available; turn URL Access on in the workflow editor once the workflow
exists. If an edit is refused, the editor stays open with your draft and says what
to change.

A search for all matching documents pauses before it reviews any if, when the run
starts, more documents match than the hand-off can review. The card shows **Needs
you** and says why. Select **Cancel run**, then ask again with a narrower request;
the workflow can't be resumed.

After its run, the workflow stays in Workflows, turned off. Chat won't start it
again, but you can run it from Workflows. Each hand-off workflow from the last 24
hours counts toward a daily limit your administrator sets, until you delete it. See
[Workflow hand-offs]({{ '/reference/chat-controls/' | relative_url }}#workflow-hand-offs-v2-interface)
for every control on the card.

## Continue a durable run

With durable execution enabled in **0.261.111**, **Run** queues background work
rather than keeping a browser request open. Open its V2 run history, the
workflow's **Runs** tab, to inspect progress and run memory. Closing the page
does not cancel the run.

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

This viewer remains read-only in **0.261.122**. **Flow authoring** edits a draft
in the workflow editor, never a run's frozen definition or saved evidence.

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
[saved-definition viewer]({{ '/guides/create-a-workflow/' | relative_url }}#preview-the-structure-without-changing-execution).
Open the workflow editor separately when you intend to change an unsaved draft.

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
| A calendar-scheduled workflow stopped running | Its saved time zone is no longer in the server's time zone database, so no next run can be worked out | Open it in the V2 editor, choose a time zone from the list, and save. |
| A run fails immediately | A runner, action, document, or File Sync source is unavailable | Open run details, fix the dependency, and run again. |
| Chat never plans to run your workflow | **Run Workflows From Chat** is off, the conversation is shared, or the request didn't ask to run the workflow now | Ask from your own conversation, name the workflow and ask to run it now, or ask your administrator about the setting. |
| The answer says only workflows with durable execution can be started from chat | The workflow runs synchronously | Turn on **Durable execution** in the V2 editor and save, or select **Run** in Workflows. |
| The answer says the workflow is waiting for a Microsoft 365 approval or sign-in | An earlier run is waiting on Microsoft 365 | Finish that approval or sign-in, then ask again. |
| A started workflow's link says it's unavailable | The workflow was deleted, or the run is no longer in its run history | Open the workflow in Workflows to start a new run. |
| A started workflow shows **Status unavailable** | V2 couldn't read the run's status with certainty, for example because the run stopped while nothing was checking it | Select **Check now**, or **Open run** to see the run in Workflows. |
| A failed run started from chat doesn't offer **Retry** | The workflow changed or was deleted after the run started, another run of it is in progress, the run reached its time limit, it didn't run because nothing changed, or starting workflows from chat was turned off | Read the reason on the card, then start a new run from Workflows if you still need one. |
| Chat never offers to hand work off | **Hand Off Large Work From Chat** or a setting it needs is off, the conversation is shared, or you don't have the workflow role your deployment requires | Ask from your own conversation, or ask your administrator about the settings and your role. |
| A hand-off card shows **Can't be used** and says the request covers more documents than one hand-off can review | You named more documents, or asked for a broader search, than one hand-off can review | Ask again with a narrower request. |
| A hand-off run shows **Needs you** and says it paused before reviewing any documents | When the run started, a search for all matching documents found more than the hand-off can review | Select **Cancel run**, then ask again with a narrower request. The workflow can't be resumed. |
| Accepting a hand-off says you reached the daily limit | You already have as many hand-off workflows from the last 24 hours as your administrator allows | Try again later, or delete a hand-off workflow you no longer need. |
| Saving an edited hand-off is refused | The edit changed the trigger, removed the For each, used an agent that isn't one of your own local agents, or turned on URL Access or Run as | Read the message in the editor, undo that change and save again. Your draft is kept. |
| A hand-off card says the offer expired | A hand-off can be accepted for 14 days | Ask again in chat for a new one. |

## Related

- [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }})
- [Create a file sync]({{ '/guides/create-a-file-sync/' | relative_url }})
- [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }})
- [Ask about workflow results]({{ '/guides/ask-about-workflow-results/' | relative_url }})
