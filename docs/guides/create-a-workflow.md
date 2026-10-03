---
layout: page
title: "Create a workflow"
description: "Save a repeatable multi-step task that can run manually or on a schedule."
section: "Guides"
audience: user
version: "0.261.122"
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
existing workflow in the native V2 editor. Ordered drafts still use List;
explicitly structured drafts also offer Flow authoring as described below.

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

From version **0.261.149**, a refused save names the rule that failed, such as
"Schedule value for minutes must be between 1 and 59.", and the editor checks
the same rules before you save. If someone deletes the workflow while you have
it open, saving is refused with "This workflow was deleted after it was opened,
so your changes were not saved." The draft stays open so you can copy anything
you need; saving in V2 never brings a deleted workflow back.

See [Explicit workflow data flow](../explanation/features/WORKFLOW_EXPLICIT_DATA_FLOW.md)
for binding semantics, shared references, and validation outcomes.

## Create a workflow from chat

Starting in **0.261.207**, the V2 chat can propose a personal workflow when you
ask for work that repeats, such as "Every Monday at 8, read my email and tell me
what I should focus on this week." Chat answers for the current period once, as
a preview, and a **Proposed workflow** card follows the answer. Nothing is
created until you choose.

Proposals appear only when your administrator has turned on **Propose Workflows
From Chat**, you can create personal workflows, and the conversation is private
to you. They never appear in a shared or collaborative conversation.

The card shows what the workflow would do:

- **When** and **How often**: the schedule, in your browser's time zone, and
  about how many runs a month. A workflow that watches File Sync "Runs when File
  Sync finds changes in" its source; its first run covers whatever that source's
  next sync reports.
- **Alerts**: a notification after every run, or only when a run fails. It
  appears in your notifications and never pops up.
- **Microsoft 365** and **Run as**: the Microsoft 365 data the workflow uses,
  whether it can send email or calendar invitations, and whose account it uses.
- Each task, with the agent or model that runs it and the documents it reads.
  Expand **Instructions** to read exactly what the task is told to do on every
  run. From version **0.261.220**, a task that merges spreadsheets says so
  instead, for example "Merges the input files below, in order, into one Excel
  file with code. No model runs.", and lists the files under **Files to merge,
  in order**.
- Similar workflows you already have, so you don't create a duplicate.

A proposed task reads only documents you named in that request: the documents
you picked in the chat composer and the ones you referenced with `#`. Chat never
adds a document it found by searching, even one that helped answer your question.
To have the workflow read other documents, choose **Edit** and add them to the
task.

Then choose one of these:

- **Create & start** creates the workflow and turns it on.
- **Create paused** creates it turned off. Turn it on in Workflows when you're
  ready.
- **Create** appears instead for a manual workflow. It runs only when you start
  it from Workflows.
- **Edit** opens the proposal in the workflow editor. **Save** creates it as you
  edited it, and it stays off unless you turn on **Workflow enabled**.
- **Deny** declines the proposal. Nothing is created.

Once it's created, **Open workflow** opens it in Workflows. If you delete it
later, **Create again** creates it again, paused. A proposal expires 14 days
after chat made it; after that, ask in chat again.

A workflow created from chat can't turn on URL Access. Create it first, then
turn on URL Access in the workflow editor. A task that uses Microsoft 365 runs as
you, and as with any workflow, its first run waits for you to approve Run as.
When Microsoft 365 isn't connected for workflows, the card links to the
connection in your profile.

See [Chat orchestration workflow proposals](../explanation/features/CHAT_ORCHESTRATION_WORKFLOW_PROPOSALS.md)
for how proposals are checked and created.

## Run on a calendar schedule

From version **0.261.193**, a scheduled workflow can run at a local time rather
than at a fixed interval, for example every Monday at 08:00 in New York. This
works in personal and group workflows, and you set it in the V2 editor:

1. Set **Trigger** to **Schedule**. A group workflow that watches File Sync can
   use **Monitor File Sync changes** instead.
2. In **Repeats**, choose how often it runs:
   - **At an interval** keeps a fixed interval, set with **Interval value** and
     **Interval unit**.
   - **Daily** runs every day.
   - **Weekdays (Monday to Friday)** skips weekends.
   - **Weekly on chosen days** runs on the days you select under **Days of the
     week**.
   - **Monthly on a day of the month** runs on the **Day of the month** you
     enter, from 1 to 31. A month without that day runs on its last day, so day
     31 runs on 30 April, and on 28 February or, in a leap year, 29 February.
3. Set **Time** and **Time zone**. The time zone is an IANA name, such as
   `America/New_York` or `Europe/London`; start typing to choose one from the
   list. A new calendar schedule starts at 09:00 in your browser's time zone.
   If the server doesn't offer your browser's zone, the schedule starts in UTC
   and the editor says so; choose the zone the schedule should follow.
4. Check the summary under the fields, such as "Schedule: Mondays 08:00
   America/New_York", then save. The workflow list shows the same summary.

Runs follow the local time in the zone you chose, through daylight saving
changes. "Mondays 08:00 America/New_York" runs at 12:00 UTC in summer and 13:00
UTC in winter. On the night the clocks go forward, a time they skip runs later
by the amount skipped, so 02:30 in New York runs at 03:30. On the night the
clocks go back, a time that happens twice runs once, the first time it happens.

If a run was missed, for example while the app was stopped, the workflow runs
once when the scheduler catches up, then waits for its next scheduled time. It
doesn't make up each missed run.

From version **0.261.202**, each run of a calendar workflow tells the model when
it started, in the schedule's time zone, for example "Current date and time:
Monday, 28 September 2026, 09:00 (America/New_York)". Instructions such as "list
this week's to-dos" then mean the week of the run. Scheduled runs and **Run
now** both include it. Workflows that run at a fixed interval, or only when
started by hand, don't.

Existing interval workflows keep their schedules, and their Microsoft 365 Run
as approvals stay valid. The schedule is part of that approval, so changing it,
including to a calendar schedule, is a material change that needs renewed
approval.

The classic editor can't edit calendar schedules. Opening one there shows
"This workflow uses a calendar schedule. Open V2 to edit it without losing its
configuration. Run and Cancel remain available here."

From version **0.261.202**, the V2 editor also opens a workflow read-only when
it can't show the workflow's schedule exactly, such as a kind of schedule or a
**Repeats** frequency saved by a newer version of SimpleChat, or an interval
unit or value it doesn't recognize. The editor says so, and the schedule stays
exactly as saved, so a save never swaps in a schedule you didn't choose.

Your administrator can set a minimum interval. A new or changed interval that
runs more often is refused with a message that names the minimum, such as
"This schedule runs more often than the administrator allows. Choose an
interval of at least 5 minutes." Workflows already saved on a shorter interval
keep running, and calendar schedules aren't affected.

See [Workflow calendar schedules](../explanation/features/WORKFLOW_CALENDAR_SCHEDULES.md)
for the stored format and the full rules.

## Run a workflow when File Sync finds changes

From version **0.261.141**, the V2 editor for group workflows can author File
Sync, and from version **0.261.207** so can the editor for personal workflows.
Owners, Admins, and other workflow managers of a group, and anyone editing
their own personal workflow, see these choices when there are File Sync
sources to choose from:

- **Monitor File Sync changes** is a trigger. On the schedule you set, it syncs
  the selected sources, waits for the sync to finish, and runs the workflow only
  when files changed.
- **Run File Sync before each run** syncs the selected sources first on a manual
  or interval workflow. **Wait for File Sync** and **Continue the workflow**
  decide whether the workflow waits, and whether it runs when nothing changed.
- **Use changed files as Analyze targets** lets an Analyze task with no
  selected documents work on the files each sync changed. From version
  **0.261.220**, it also lets a **Merge files** task merge them; see
  [Merge files in a workflow](#merge-files-in-a-workflow).

A group workflow uses between 1 and 10 of the group's own sources. A source the
group no longer offers is marked **No longer available**; remove it before
saving. From version **0.261.149**, if a source is deleted while you're editing,
saving is refused with "A selected File Sync source is no longer available.
Remove it and save again." Your changes stay in the editor, and the source is
marked so you can remove it. When File Sync is turned off for the group, the
editor says so instead of showing an empty list.

A personal workflow uses between 1 and 10 of the sources you may sync: your own
personal sources, and those of your active group and active public workspace
when you're an Owner, Admin or DocumentManager there. Each source is labelled
with where it lives, such as "Home share (Personal)". Your personal sources are
offered only while your administrator allows personal File Sync for you, which
can require the **PersonalFileSyncUser** role. When it's off, the editor says so,
and sources the workflow already uses stay selected so you can keep or remove
them. The save checks every source again: a deleted source is refused with the
same message as for a group, and a source you're no longer allowed to use with
"Workflow settings or sources are not allowed for this account."

## Merge files in a workflow

From version **0.261.220**, a task can merge many CSV and Excel files into one CSV
or Excel file, and from **0.261.221** it can also join PDFs into one PDF or put
several spreadsheets on separate sheets of one workbook. Use it for a merge that's
too big for one chat turn, such as a year of weekly exports, or one that should
happen on its own, such as every Monday or whenever a synced folder gets a new
export. A merge task runs with code, not a model or agent: rows and pages are
copied exactly and the task's answer summarizes what was merged.

1. Add a task and choose **Merge files** as its **Document action**. Write a
   short note in **Instructions** describing the merge; the merge itself
   doesn't read it. **Merge files** isn't offered while your administrator has
   Merge turned off.
2. Choose a **Merge type**:
   - **Combine rows (CSV/Excel)** stacks the rows of CSV and Excel files into
     one table.
   - **One workbook, a sheet per file** keeps each CSV or Excel file as its own
     sheet of one Excel workbook, named after the file.
   - **Combine PDFs** joins PDFs into one PDF, with a bookmark for each file.
3. Under **Files to merge**, choose:
   - **Selected files, in this order** to merge files you pick, at least two.
     Set their order under **Merge order**.
   - **All matching files in scope** to merge every file of that type in the
     workflow's workspace when the run starts.
   - **Recently added or updated files** to merge those added or changed within
     **Recent window in minutes** before the run, 60 by default.
   - **Files changed by File Sync** to merge the files each sync adds or
     changes. It's offered when File Sync is on and **Use changed files as
     Analyze targets** is selected.

   Files found when the run starts are merged in file-name order.
4. For row merges, choose **Output format**, CSV or Excel workbook. Workbook
   merges create an Excel workbook and PDF merges a PDF. Optionally set an
   **Output file name** without an extension.
5. Open **More merge options**. For row merges, decide how columns are matched,
   add column aliases, choose sheets or a header row, leave out files whose
   columns don't match, remove duplicates, or sort; these are the same settings
   you can ask for in a [chat merge]({{ '/guides/merge-files/' | relative_url }}).
   For workbooks, choose the first sheet, every sheet, or a named sheet of each
   file. For PDFs, turn **Add bookmarks** off if you don't want a bookmark per
   file.

Each run attaches the merged file to the run's conversation, and later tasks
can read the merge task's summary. A workflow merges up to 100 files and
1,000,000 rows by default; your administrator sets these limits under
[Document Action Capabilities]({{ '/admin/agents-actions/' | relative_url }}#document-action-capabilities-card).
A PDF merge reads at most 300 MB of PDFs in total. Merged PDFs keep links to
pages and to web and email addresses, but not scripts, form actions, or links
that open other files or programs, and the task's answer says when any were
removed.

A run with nothing to merge finishes and says so without creating a file.
Files that can't be merged are handled by how they were chosen:

- For **Selected files**, a file that's no longer available, or isn't a CSV or
  Excel file, fails the task and says which.
- For files found at run time, those files are skipped and named in the
  task's answer.
- When more files match than the limit allows, the task fails rather than
  merging only some of them. Narrow the files, or ask your administrator to
  raise the limit.

A merge failure caused by the files or settings is shown on the task and isn't
retried, because the same merge would fail the same way.

## Set up alerts

From version **0.261.144**, personal and group workflows are given alerts in the
V2 editor, under **Alerts** after the tasks. The alert settings are:

- **When to alert:** **Never notify me**, **On every run** (choose a **Pop-up
  alert priority**), or **Only when a condition is met**.
- **Alert rules**, up to 20, used by **Only when a condition is met**. Each rule
  has a condition:
  - the run finished with a status;
  - a task finished with a status;
  - the output text contains, lacks or matches a pattern;
  - a File Sync result;
  - the run produced no output;
  - a model judges a condition you describe;
  - the agent raised an alert.

  A rule that reads output (task status, output text, no output, or a model's
  judgement) can look at the final output, any task's output, or one task. Run
  status, File Sync results and agent alerts apply to the whole run. A rule's
  **severity** decides where the alert lands: info and low go to the
  notification bell, and medium and above open the pop-up alert, unless you
  choose the delivery yourself. A new rule is named after its condition until you
  give it a name.
- **If a model evaluated condition cannot be judged** appears when a rule asks a
  model to judge. It either skips the rule silently, or alerts anyway so a
  failure isn't missed.

When several rules match one run, the highest severity wins and every matched
rule is listed. Rules you keep while alerts are off, or on every run, are still
saved and still checked.

If you delete a task that a rule watches, the rule is marked, and the editor
won't save until you choose another task or remove the rule. A problem with the
alert settings is shown with the rule's number.

Members who can't manage the workflow see a read-only summary. A workflow saved
in V2 can no longer be opened by the classic editor.

## Choose the Microsoft 365 Run as account

Native V2 **Run as** authoring is implemented in version **0.261.122**. Use
**Microsoft 365 Run as** in the editor when a workflow needs someone's Microsoft
365 account for manual or scheduled actions. Personal workflows offer your
account; group workflows load eligible choices for the selected group.

New workflows start with **No Microsoft 365 account selected**. Neither workflow
ownership nor having an account in the list grants consent. The selected person
must connect Microsoft 365 and approve the workflow. Changes to instructions,
capabilities, or destinations require approval again; choosing an account does
not establish that the current revision is approved.

Save the workflow to persist your choice. To explicitly remove it, choose **No
Microsoft 365 account selected** and save. If the list cannot load or a saved
account is absent from it, V2 retains the current selection rather than silently
clearing it or choosing someone else. Retry the account list or review the
unavailable selection before running; unrelated edits can still be saved without
changing that account, subject to the usual workflow permissions and validation.

In a structured workflow, Undo and Redo also restore unsaved Run as selections
across List and Flow, including an explicitly cleared account (version
**0.261.124**). This does not grant consent or restore an earlier approval.

People who can't manage the workflow see only whether an account is selected
(version **0.261.149**). Only workflow managers can see who it is or change it.

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
Repeat until is added in **0.261.120** below. Version **0.261.121** adds the
read-only saved/run Flow inspection described below. Version **0.261.122**
adds **List authoring** and **Flow authoring** for the same structured draft.

See [Structured workflow control flow](../explanation/features/WORKFLOW_STRUCTURED_CONTROL_FLOW.md)
for condition semantics, execution identity, limits, and compatibility.

## Edit with List or Flow

In **0.261.122**, the structured editor offers **List authoring** and
**Flow authoring** over one draft. List is the default, including on small
screens. Use Flow when seeing branches, joins, and loop boundaries helps you
place work in the right region; use List when a compact sequence of forms is
easier to follow. Switching does not convert an ordered workflow or create a
different saved definition.

1. Open the structured workflow in Edit, then choose **Flow authoring**.
   Workflow basics, runner, schedule, shared references, limits, and Save
   remain common to both surfaces.
2. Select the block you want to configure. Tasks retain their instructions,
   runner, approval, document-action, reporting, publication, and typed-input
   fields. If/else, Forward route, For each, Repeat until, and Collect use the
   same forms as List. Select the owning structure to edit join, body, or
   final outputs.
3. Add a block with an explicit destination region and a position before or
   after a sibling, or at the end. For example, add a review task inside
   **Else**, not after the entire If/else, when only that branch needs review.
   A new Repeat maximum stays unset until you choose it.
4. To change execution order or move work into another region, use the move
   controls and choose the destination and position. Dragging a box only
   rearranges your view. You cannot create a dependency, reconnect a route,
   or reparent work by drawing or dragging a connector.
5. Before confirming a reference-breaking move or removal, review the listed
   consumers and exact selectors. Confirming retains those references, even
   if they now point to a missing or out-of-scope producer. Repair them before
   saving; the editor does not cascade removal into consumers or silently
   select a replacement source. Cancel the confirmation to keep the draft
   unchanged.
6. Finish required fields and use **Save workflow**. The same validation,
   active-run protection, and saved-revision checks apply in either surface.
   Saving does not start the workflow.

Incomplete supported boxes stay selectable as **Unvalidated draft**, including
an empty task, an unfinished schema, or a Repeat with no maximum yet.
Executable control arrows appear only after the server compiler accepts that
exact current draft. Old successful arrows cannot describe newer invalid
edits. Typed bindings are authored relationships, not extra execution paths.
An unknown executable shape stays intact and read-only rather than being
silently converted.

List/Flow switches and selecting another node preserve unfinished schema text,
field errors, and other in-progress fields. They also preserve the current
selection and unsaved-change/discard protection. A stale-save conflict or
ordinary network error retains your draft; it does not overwrite someone
else's saved changes or automatically rebase your work.

All editing operations have keyboard/button alternatives. Use the controls
that focus the selected configuration form and return to its block. Selection
is revealed when switching surfaces; after removal, focus recovers to a
surviving sibling or its parent/root. Flow's panel stacks on narrow screens,
and page scrolling and browser zoom remain available.

Pan, zoom, collapse, and temporary box positions are not executable edits and
are not saved. There is no autosave or implicit execution, Analyze invocation,
publication, or readiness check when switching or configuring blocks.

### Undo unsaved edits

Starting in **0.261.123**, use the shared **Undo** and **Redo** buttons in a
structured editor to reverse and restore edits across List and Flow. This
includes common fields, block configuration, moves/removals, unfinished
schema text and errors, and Repeat state fields. Typing during one field visit
is one action; schema-builder and other compound changes stay together.

Inside text fields, Ctrl/Cmd+Z keeps native text undo. Outside text fields,
Ctrl/Cmd+Z undoes a workflow action; Ctrl/Cmd+Shift+Z or Ctrl+Y redoes one.
Replay that removes blocks or affects other references asks for confirmation.
Review the impact and repair any resulting invalid selectors before Save.
Undo/Redo does not start work, reverse a publication, or change a saved run.

The editor retains up to 100 actions across both directions and 32 MiB of
additional accounted history data, not total browser memory. It announces
when old steps are removed. An individually oversized edit asks before
applying its complete contents and clearing history; **Keep draft unchanged**
retains your previous work.

Successful Save, discard, reload, or switching to a different workflow/scope
starts a fresh history session. Failed saves keep your draft and history
without replacing the original saved revision. Confirmed loss of authoring
access clears protected history and requires reopening after access returns.
Converting an ordered workflow starts empty v3 history; Undo does not reverse
that explicit conversion.

## Review your changes

Starting in **0.261.203**, the V2 editor tracks what changed since you opened
the workflow. You can check a long editing session before you save, and take
back one change without undoing everything you did after it. This works for
personal and group workflows, in every format.

### See what changed

Each changed field is framed and labeled **Edited**. Changes made by AI assist
are framed in blue and labeled **AI assist** instead. From **0.261.213**,
[**Ask AI**](#ask-ai-to-change-a-workflow) and **Draft with AI** make them.

- **Previously** shows the value the field had when you opened the editor.
  Long values are cut short, with **Show more**.
- **Revert** puts back that one field and keeps every other change.
- A task or block you added is labeled **Added · by you**, and its **Revert**
  removes it.
- A removed task leaves a **Removed task** row where it was, with **Restore**.
  Restore puts back the saved version of the task in its saved place. On the
  Flow surface, removed blocks are listed under **Removed blocks** above the
  canvas.
- Moving tasks around is one **Task order** change, not a change to every task.

{% include media.html src="guides/create-a-workflow-review-changes.png"
                      alt="The V2 workflow editor with a renamed workflow and an edited task instruction each framed and labeled Edited, and the Changes panel beside the editor listing the unsaved changes with Jump and Revert buttons."
                      title="Reviewing unsaved workflow changes"
                      capture="Open a saved workflow in the V2 editor at a wide window size, rename it, edit one task's instructions, remove another task, then choose Changes. Use sample data." %}

### Use the Changes panel

Choose **Changes** in the editor footer. The button shows how many changes are
unsaved, and the panel lists them in two parts:

- **Unsaved changes**: each change with its before and after values and who
  made it. **Jump** moves to the field, switching from Flow to List when the
  field isn't on Flow. **Revert** (or **Restore** for a removed item) takes
  back that change.
- **This session**: the steps you took, newest first. **Restore to here**
  returns the workflow to how it was after that step. It is added as a new
  step, so the later steps stay in the list and nothing is lost. The last row,
  **Opened version**, is the workflow as you opened it.

On wide screens the panel opens beside the editor. On narrower screens it
takes the editor's place until you close it or choose **Jump**. Press Escape to
close the panel and return to the **Changes** button.

When the workflow runs as a Microsoft 365 account, the panel notes when your
changes mean **Saving requires re-approving Run as**. See
[Microsoft 365 Run as](#microsoft-365-run-as).

### Save after reviewing

Saving your own changes is still one click. When some unsaved changes came
from AI assist, the first **Save workflow** opens **Review before saving** in
the Changes panel instead. Check the changes, then choose **Confirm and save**.

Read-only editors show none of this. In a workflow that has never been saved,
everything is new, so only AI assist changes are pointed out. After you convert
an ordered workflow to the structured format, changes are still listed, but
they can only be discarded together, with **Cancel**.

## Ask AI to change a workflow

Starting in **0.261.213**, the V2 editor's **Ask AI** tab changes a personal
workflow from a plain-language request, such as "run this at 7 AM on weekdays
and only alert me when something is urgent". Use it when you know what you want
the workflow to do but not which fields hold it, or to make the same kind of
change across many tasks. It never saves. Its changes are highlighted like your
own, and you review them before you save.

**Ask AI** appears when your administrator has turned the assistant on, the
workflow is personal, and you can edit it. Group workflows don't offer it.

### Ask for a change

1. Open a personal workflow in the V2 editor, or choose **Edit** on a workflow
   proposal in chat.
2. Choose **Ask AI** in the editor footer. To ask about one task, choose
   **Ask AI** on that task instead. The tab shows **About:** with the task's
   name until you clear it.
3. Type what you want and send it, or choose a quick action such as **Explain
   this workflow** or **Add a schedule**.
4. Wait for the answer. The editor is locked while Ask AI works, so the answer
   fits the draft you sent. **Cancel request** stops it, and nothing changes.

A message can be up to 2,000 characters, and an emoji counts as one. When your
browser's time zone is one the schedule editor offers, Ask AI sends it, so
"7 AM" means 7 AM where you are.

{% include media.html src="guides/create-a-workflow-ask-ai.png"
                      alt="The V2 workflow editor with the Ask AI tab open beside it, showing a request to run the workflow at 7 AM on weekdays, the assistant's reply, and a card listing the schedule changes with Jump to and Undo this change, while the changed schedule fields are framed in blue and labeled AI assist."
                      title="Asking AI to change a workflow"
                      capture="Open a saved personal workflow in the V2 editor at a wide window size, choose Ask AI, and send 'Run this at 7 AM on weekdays'. Capture the answered turn with its card and the highlighted schedule fields. Use sample data." %}

### Point it at a document

Type `#` in your message to pick a document from a personal, group or public
workspace you can use. Depending on what you ask, Ask AI reads it as
background, adds it as a reference shared by every task or used by particular
tasks, or makes it the document a task works on. For example, "Use #X to
design the steps" only reads it, and "Summarize #X every Friday" adds it to
that task. When it can't tell, it asks.

You can attach up to 20 documents in one message. Tags and whole workspaces
aren't offered here, because a workflow refers to documents.

### Review what it changed

An answer that changes the draft shows a card listing the changes, and the
changed fields are framed in blue and labeled **AI assist**.

- **Jump to** moves to a change. On the Flow surface it selects the block.
- **Read as context** names the documents Ask AI read.
- **Warnings** point out anything to check, such as a change that means saving
  requires re-approving [Run as](#microsoft-365-run-as).
- **Undo this change** takes back the whole answer. A field you changed again
  afterwards keeps your value, and the card says it was skipped.
- **Revert** on one field, and the editor's Undo, work as they do for your own
  edits.

An answer that explains or asks you something changes nothing. Ask your
follow-up in the same thread: Ask AI sees the earlier turns, and which of their
changes you kept or undid.

Because the draft now has AI changes, the first **Save workflow** opens
[**Review before saving**](#save-after-reviewing). Choose **Confirm and save**.

### Draft task instructions

A task with empty instructions has **Draft with AI**. It writes instructions
from the workflow's name and description and the task's name, adds them as one
change you can undo, and moves you to them. Give the workflow or the task a
name first, so it has something to go on.

### When Ask AI can't help

- If someone saved the workflow after you opened it, Ask AI keeps your draft
  and offers **Reload workflow**. Reloading discards your unsaved changes.
- If you've sent a lot of requests, Ask AI tells you when you can send again.
- A failed or cancelled request changes nothing. **Retry** sends it again with
  the draft as it is now.
- The conversation isn't saved with the workflow. Reopening a saved workflow
  in the same page shows it again; reloading the page starts over.

## Preview the structure without changing execution

In **0.261.121**, choose **View Flow for ...** beside a saved structured
workflow to see its branches, joins, routes, and single loop templates.
This is independent of Edit, so an authorized reader can inspect a saved
definition while it has an active run. This viewer remains read-only in
**0.261.122**. The List/Flow authoring switch replaces only the old preview-only
control inside Edit; it does not change the saved or historical Flow entries.
For unsaved changes, return to the editor and choose **Flow authoring**.
A compiler-checked draft picture is not a saved definition or permission to
execute.

Select a node to read its configuration, condition, contracts, or source
selection. Solid arrows describe execution order. Dashed arrows describe
declared data connections for the selected detail page, not extra execution
paths. Expand a loop to see its template once, not one box per item or round.

Use **Structure list** for a textual view of the same definition. In the
diagram, arrow keys move focus, Enter selects, and **Inspect selected node**
opens the inspection focus target. **Return to selected node** takes focus
back. Pan, zoom, fit, collapse, and moving a box are temporary viewing choices:
they do not reorder executable work, save it, invalidate approval, or restart
it.

Saved Flow has no historical run coloring. To see what a run actually used,
open its [frozen-definition Flow]({{ '/guides/trigger-a-workflow/' | relative_url }}#inspect-a-runs-frozen-flow)
rather than comparing it with today's edited definition.

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
5. In **Trigger**, choose manual execution or a scheduled interval. Calendar
   schedules, such as weekdays at 08:00, are set in the V2 editor.
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

In the V2 editor, enable **Publish a workflow file** on a later task and
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

## Find documents a workflow saved

Starting in **0.261.194**, a document that a workflow publishes to a workspace
records which workflow and run created it. In the V2 workspace, its document
details show **Created by *workflow name* · run *date and time*** under
**Origin**. Select it to open this Workflows section with that run expanded in
the history. If the run isn't among the 10 most recent runs, the history says
so.

These documents also get a removable `workflow` tag, so you can filter a
workspace for workflow output. In a group or public workspace the tag is added
only when the person publishing can manage tags there; the origin is recorded
either way. Workspace members who can't open your workflow see only **Created
by a workflow**. See
[Uploading and managing documents]({{ '/guides/upload-and-manage-documents/' | relative_url }}).

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The Workflows section is missing | Workflows are disabled for the scope | Ask an admin to enable personal or group workflows. |
| No agents are available as runners | No authorized agents exist for this workspace | Create an agent first or use a direct model runner. |
| Flow shows Unvalidated draft without execution arrows | The current draft has not passed its compiler preview | Keep editing the visible blocks and repair the reported fields or selectors; do not interpret old topology as the current draft. |
| Save is blocked after moving or removing a block | A retained reference is now missing or out of scope | Use the affected-selector diagnostics to repair each consumer explicitly. |
| Save is refused with "This schedule runs more often than the administrator allows." | The new or changed interval is shorter than the administrator's minimum | Choose the interval the message names or longer, or use a calendar schedule. |
| A calendar schedule's time zone isn't accepted | The name isn't an exact IANA time zone that the server offers; names are case-sensitive | Choose a zone from the **Time zone** list, such as `America/New_York`. |
| The classic editor won't open a workflow | It uses a calendar schedule, advanced data flow, or a **Merge files** task, which the classic editor can't represent | Edit it in V2. Run and Cancel still work in the classic workspace. |
| The V2 editor has no **Ask AI** tab | The assistant is turned off, the workflow belongs to a group, or the editor can't change the workflow, for example because it's running or you can only view it | Ask an admin to turn on **Enable AI Workflow Assistant**, or open a personal workflow you can edit. |
| Ask AI says the saved workflow changed | Someone saved the workflow after you opened it | Choose **Reload workflow**. Reloading discards your unsaved changes, so copy anything you need first. |

## Related

- [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }})
- [Create an agent]({{ '/guides/create-an-agent/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
