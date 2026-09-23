---
layout: page
title: "Review and edit orchestration plans"
description: "Refine proposed work with the planner before running it."
section: "Guides"
audience: user
version: "0.261.127"
---

## Decide what should run

An orchestration plan explains how SimpleChat intends to answer your question.
Review it when you want to check its sources or cost before committing to that
work. Edit it when the approach needs another step, less research, or a different
focus.

Conversational plan editing was implemented in version **0.261.102**, recorded in
`application/single_app/config.py`. It is available in the V2 interface for plans
that have not started.

## Choose requirements, not permissions

Since **0.261.104**, every Orchestrate request reaches the planner, including
short questions. Selected supported tools, documents, and agents tell it what
the plan must use. Leaving Web Search or Deep Research unchecked does not
forbid those capabilities: the planner can choose them when they are enabled,
authorized, and useful for the task. Say "do not browse" when that is an actual
requirement.

Deep Research does not require selecting the Web button first. Its automatic
source discovery still depends on the administrator enabling Web Search.
Selected workspaces and document filters continue to bound document access.
Image generation has no orchestration adapter; use ordinary chat for that work.
If Image was already selected, Send and Enter pause for an explicit choice:
**Use regular Chat with Image**, or **Use Orchestrate without Image for this
message**. The second choice excludes Image only from that orchestration message
and preserves your ordinary-chat Image preference.

URL Access uses the full resolved message, including an attached prompt. Removing
the URL from the draft clears that now-ineligible selection; it does not clear
other selected requirements.

Research is not compulsory. The planner can answer directly when the available
context is enough. Capability lookup or model failures produce errors rather
than a replacement answer-only plan.

Pinned documents specify the inputs, not the operation. Since **0.261.115**, the
planner may Analyze or Compare those inputs without adding a Search step merely
because they were pinned. Explicitly selected Search still constrains the plan,
and the validator still rejects a plan that omits selected documents.

## Review versus Edit

**Review** opens the existing drawer. You can inspect steps and their rationales,
switch off eligible steps, and remove documents from a step. These controls
only reduce the work already proposed.

**Edit** opens a full-screen preview with **Ask planner** and **History**. Use it
to discuss a change instead of asking a new question in the main conversation.
The planner creates a new version of the same plan.

If plans currently run immediately, choose Review or countdown approval before
asking your question, if your administrator permits that choice. A plan that has
already started cannot be edited.

## Read dependency-driven plans

Version-aware plan inspection was implemented in version **0.261.127**, recorded
in `application/single_app/config.py` (Refs: microsoft/simplechat#1509). It does
not enable a new planning contract by itself. The following details appear when
the server supplies a contract-v2 plan; older saved plans retain their original
phase labels and meaning.

A saved v1 step keeps its server-recorded phase even if the current capability
catalog changes. A step whose phase cannot be resolved is still listed.

**Gather**, **Reason**, and **Render** describe a task's purpose, not three
mandatory stages. The preview follows the server's saved dependency/execution
order. For example, Gather → Reason → Gather → Reason remains four consecutive
groups; the second search is not moved ahead of the work it depends on. Running
tasks show Gathering, Reasoning, or Rendering.

Each task can show **Named inputs** and **Named outputs**. An input names its
producing task and output, or an explicitly selected retained-result alias.
The description also says whether complete results are required or partial
results are accepted. Outputs show their kind, ordered columns, and any
server-declared prepared-content profile or schema. **Final chat response**
identifies the prepared content selected for the answer.

Named results are not download links. A retained result or a planned output
does not prove that a file has been created. The interface does not count those
results as completed file artifacts.

When the server supplies an explicit `render_file` task, **Planned file** shows
its intended name, format, profile, bound source, and options before approval.
These are descriptions of requested work, not success links. Changing a file
specification requires a validated planner revision; the browser does not infer
a format or replace the chosen source.

A producer's switch explains which consumers require it. You cannot silently
disconnect those consumers by disabling the producer. Even a skipped consumer
retains its declared bindings: use **Ask planner** to change or remove the
consumer and its requested outputs in a validated revision. A saved edit with
an unavailable producer blocks approval and identifies the affected inputs.
Restoring the producer clears that conflict; it does not discard any edges.

File-format reference information is optional and uses only the shared catalog
supplied by the server. It is not a separate browser format list or permission
to add a file-producing task. Where available, its profiles, source kinds,
option rules, and default renderer limits are read-only. Ask the planner for a
validated revision rather than changing capability arguments in the browser.
If the current view has no catalog, **Load server file format reference** asks
the server for the reference authorized for that saved plan. A failed lookup
does not substitute guessed formats or change the plan.

## Refine the plan with the planner

1. Ask your question with orchestration enabled and wait for the proposed plan.
2. Select **Edit** beside Review, or open Edit from the plan drawer.
3. In **Ask planner**, describe what should change. For example: "Add a second
   document search focused on pricing" or "Remove the extra research and compare
   only the selected contracts."
4. Read the updated preview. Check the steps, source selections, assumptions,
   and any adjustments reported by the planner.
5. Continue refining the same plan, or select **Run** when the current version
   describes the work you want.

The planner may ask a clarifying question or explain why a requested capability
is unavailable. Answer within the editor to continue the change. A request to add
a feature does not enable that feature for the deployment or grant access to its
sources.

Editor exchanges do not create duplicate messages in your main conversation.
The eventual answer follows your accepted changes while the original question
remains intact.

If an accepted edit removes an originally selected operation or document, the
preview reports that change for review. It does not rewrite your standing
composer preferences.

## Understand reasoning adjustments

The reasoning picker uses the selected model's supported levels. For example,
GPT-5.6 Luna supports **None**, **Low**, **Medium**, **High**, and **XHigh**, not
Minimal. A previously saved Minimal choice becomes Low with a visible notice.
This also applies to older saved plans when edited or run.

**None** is an explicit level on models that support it. **Model default** means
the request omitted the effort parameter; it does not claim the provider chose
None or Low. If the provider rejects an otherwise supported effort, SimpleChat
can retry once using the model default and reports the adjustment. Other model
errors still stop the affected operation. Neither adjustment switches models
or approves a plan.

## Understand the countdown pause

Opening Edit stops any countdown and establishes a manual-approval hold. The
plan waits for an explicit **Run**, even if you close the editor without changing
anything or reload the conversation.

Closing the editor is not approval. A failed edit also does not cause the previous
plan to run automatically. If another tab already started the work before the
edit hold was acquired, the editor reports a conflict instead of pretending it
can modify that run.

## Return to an earlier version

Use **History** to inspect prior versions and restore one that better matches
your intent. Restoring creates a new current version; it does not delete later
history or reactivate an old execution.

Capabilities and source access are checked again. A version that depends on a
document or integration you can no longer use may not be restorable.

## Recover before a plan exists

Since **0.261.115**, **Retry** on a failed planning question retries planning with
the original prompt, model or agent selection, documents, scope, and approval
mode retained in that browser tab. It does not use the temporary chat bubble as
a saved message ID or append a duplicate question. Stop interrupts the local
planning request; a late response cannot populate another or deleted conversation.

If the request context is no longer available, follow the notice to copy the
original message into the composer, review its selections, and send it deliberately.
The application does not guess a model or document selection from current controls.
If a plan or clarification already exists, continue from that plan or question
instead; Retry must not discard accepted answers or start an independent execution.

## Recover from a failed change

The last valid plan remains available when an instruction cannot be planned or
saved. Read the error and retry the change rather than sending the original
question again. If a clarification is no longer needed, cancel the proposed
change to return to the existing plan.

When another tab changes the plan, refresh the editor's current version before
continuing. An outdated approval cannot run a superseded plan.
If Cancel discovers a newer pending change, the editor shows that change without
cancelling it. Review it before explicitly choosing Cancel again.

## Recover from a failed run

Since **0.261.105**, an execution failure remains visible in the conversation and
Run view. The explanation distinguishes a measured timeout from a user-requested
Stop and describes the work that could not finish. If answering also fails, a
status explanation still reports the incomplete request.

For checkpoint-based runs without individual file recovery, use **Retry from
failed step** when the run has recoverable saved progress.
Review which steps will be reused and which work will execute. Completed steps
are restored from checkpoints and labelled **Reused saved result**; retry does
not ask the planner to choose a new agent or start the whole plan again.

An agent step may have performed several tool calls before failing. If retry
could repeat external effects, read and confirm the warning before continuing.
The retry resumes at the orchestration-step boundary, not inside that agent's
tool loop.

The new attempt retains the original question and effective plan, including
source restrictions, clarification answers, and the selected model. It does not
duplicate your question. The earlier attempt remains available in history.
Retry always requires your action, even when normal approval is Auto or timed.

A browser disconnect does not mean the server stopped. Let the interface check
the existing attempt before retrying. A live attempt cannot be retried, and a
lost retry response is recovered without starting a second copy.

The Run view can finish before its final conversation message has been saved.
The interface keeps checking during that interval instead of prematurely
reporting a missing message. If saving fails, or the server stops before saving
can be confirmed, the visible status explains the difference.

Use **Check saved status** if the connection still cannot confirm the outcome.
If retry preparation was saved but execution never started, open that attempt
and select **Run prepared retry**. It remains paused across reloads. **View
current attempt** and **View previous attempt** navigate the linked history
without running work.

If sources, permissions, or saved context changed, or an older run has no full
checkpoints, recovery explains why it cannot continue. Create a new plan in that
case; the application will not quietly rerun completed actions to fill a gap.
Editing an already-started plan remains unavailable.

## Wait for retained computation

Since **0.261.127**, a server-reported **Waiting for required results** state
remains active in the same execution attempt. It is neither successful
completion nor cancellation. Dependent tasks wait for the producer's results,
and the Map shows **Waiting for results**, including after a conversation reload.

**Check saved status** reads the existing run. It does not approve another plan,
repeat a task, or create a retry attempt. **Retry from failed step** and **Run
prepared retry** are not offered for a waiting attempt. **Stop execution**
continues to request cancellation from the server; closing the browser does not
mean the computation stopped.

The interface recognizes waiting without assuming that a downloadable file
exists. Per-file publication and retry controls require their own server-owned
output lifecycle; waiting alone does not enable them.

## Track and retry individual files

Implemented in version **0.261.127**, recorded in
`application/single_app/config.py` (Refs: microsoft/simplechat#1509). These controls
appear only when the server publishes individual output states. They do not
enable a new planner, renderer, or scheduler on their own.

**Files** appears beside the response and in the Run view. Each requested file
keeps its own name, format, profile, status, attempt count, and server-reported
automatic-attempt limit. Waiting and Rendering are unfinished work, not download
links. **Automatic retry scheduled** shows the server's next retry time; the
browser does not start a retry when that time arrives.

A completed file uses the existing generated-artifact Download control only
when the server also supplies its matching committed download descriptor. A
filename is never turned into a guessed URL. If download details are missing,
use **Check saved file status**. A file marked **Unavailable**, for example
after source deletion or a screening/access change, withholds its download
without hiding other ready files.

Availability does not rewrite the saved completion state. If access is restored
or a screening hold is lifted, **Check saved file status** can restore the same
committed download without another rendering attempt. A network or server error
while reading status instead shows a refresh error and retains previous progress;
it does not invent a source-access denial.

Generated-file history entries do not substitute for committed output cards or
open uploaded-file previews. An unavailable history entry shows the server's safe
explanation and closes any previously opened preview. Empty TXT and MD files
remain valid downloads; a zero row, character, or byte count is not a failure.

**Retry file** appears only when the server says that specific failed output
can be retried. It requests that file again from retained results, not another
plan, producer task, or sibling output. An exhausted automatic-attempt count
does not by itself authorize a manual retry. Non-retryable failures keep their
status and reason instead of offering a whole-plan replay.

If a retry response is lost, **Retry same request** keeps the original action
identity. The identity is saved in this browser tab before the request and
survives a page reload. Reloading only reads saved progress; it never submits
the retry automatically. If the browser cannot save that identity, no new retry
is sent. A sign-in, permission, or conflict error stays visible until you check
the saved state before trying again.

Pending files continue to refresh while visible even if the earlier aggregate
run result remains failed or partially completed. **Check saved file status**
is also available for an immediate read. The run's explanation and the files'
individual states are separate server records; the interface does not invent
a successful run just because one file is ready.

## Related

- [Chat orchestration](https://github.com/microsoft/simplechat/blob/main/docs/explanation/features/CHAT_ORCHESTRATION.md)
- [Plan editing architecture](https://github.com/microsoft/simplechat/blob/main/docs/explanation/features/V2_ORCHESTRATION_PLAN_EDITING.md)
- [Checkpoint recovery architecture](https://github.com/microsoft/simplechat/blob/Development/docs/explanation/features/ORCHESTRATION_CHECKPOINT_RECOVERY.md)
- [Orchestration settings]({{ '/admin/orchestration/' | relative_url }})
