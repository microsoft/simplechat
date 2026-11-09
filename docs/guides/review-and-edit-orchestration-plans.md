---
layout: page
title: "Review and edit orchestration plans"
description: "Refine proposed work with the planner before running it."
section: "Guides"
audience: user
version: "0.261.422"
---

## Decide what should run

An orchestration plan explains how SimpleChat intends to answer your question.
Review it when you want to check its sources or cost before committing to that
work. Edit it when the approach needs another step, less research, or a different
focus.

{% include media.html id="slide-orchestration" %}

The slide illustrates the reviewed path. Your deployment's approval mode
determines whether execution waits for review, uses a countdown, or starts
automatically; selecting a model or answering a follow-up is not a separate
authorization to run.

Conversational plan editing was implemented in version **0.261.102**, recorded in
`application/single_app/config.py`. It is available in the V2 interface for plans
that have not started.

## Answer necessary follow-up questions

Since **0.261.411**, follow-ups use a focused question flow with suggested choices
where useful, custom answers for open questions, Back/Next navigation, and a final
review before one submission. Local agents running inside a plan can also pause
for necessary input without restarting completed tool calls.
See [Answer an agent's follow-up questions]({{ '/guides/answer-agent-questions/' | relative_url }}).

Fixed/Implemented in version: **0.261.367**
(`application/single_app/config.py`).

If a required fact is missing, the planner can ask for it before proposing work.
For example, ask it to confirm an unknown budget before preparing a brief, then
answer the budget question in **Follow-up questions**. Your answer supplements the
original request; it does not replace identifiers, filenames, or other requirements.

For a self-contained request with no earlier conversation to resolve, answering
returns directly to planning rather than starting another history-resolution pass.
Optional extra sections, tone, or formatting should use sensible defaults within
your requested scope, not become an additional required interview.

A genuinely missing source, business rule, or other essential fact can still need
another question. There is no one-question limit, and unanswered required fields
still prevent submission. When your plan is ready, the selected approval mode still
applies; answering a question does not authorize execution by itself.

## Leave or refresh without losing an accepted question

Fixed/Implemented in version: **0.261.415**
(`application/single_app/config.py`).

Once the server accepts your question, it saves the question and its planning
state before the plan is ready. You can switch conversations or refresh, then
return to the saved question and its current status. Originally authorized Auto
work continues server-side; a review-required plan still waits for approval.
Reopening a saved countdown does not approve it again.

A planning failure stays with the saved question. Use **Retry** to reuse its
original selections and review a new plan rather than rebuilding the request
from today's composer controls. Follow-up questions are restored too, so answer
the current question instead of submitting another copy of the original request.

Use **Stop** when you want cancellation. Leaving the page is not Stop. If Stop
races with completion, the saved answer is restored rather than described as
cancelled. Work already performed by an external integration is not rolled back.
A status outage reports uncertainty and does not start another execution.

An interrupted server worker can require an explicit retry. The saved question
remains available, but this is not a promise of transparent recovery from every
process restart, or reconstruction of messages an older version never saved.

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
Since **0.261.138**, **Image** means you want images: the plan includes at least one
image you asked for, generated as its own task when the plan runs. Without Image, a
plan still generates images your request explicitly asks for, and it can suggest
others as proposal cards that you approve one at a time. Plans can also include
charts and Mermaid diagrams.
Your saved Instruction memories, such as "I don't like charts", decide which
visuals you get unless your current message explicitly asks for one.

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

### Recover ordinary planning mistakes without widening the work

Fixed/Implemented in version: **0.261.422**
(`application/single_app/config.py`).

A missing file ID should not require you to rebuild an otherwise useful plan.
For a single verified available selection, SimpleChat can fill an absent binding
on an existing independent reader. The visible plan then contains the source it
will actually read. Explicit IDs, dependent/dynamic inputs, disabled work,
unavailable sources, and ambiguous multi-file selections are not overwritten.

Other recognized draft mistakes receive specific feedback to the same planner.
The initial proposal and at most two corrections share one allowance across
different validation errors. No source reader or external action runs during
those corrections, and your selected approval mode still applies afterward.
Permissions, unavailable capabilities, provider refusals, and exhausted correction
attempts remain real failures rather than permission to run an invalid plan.

### Open the evidence behind document answers

Since **0.261.356**, Analyze and Compare supply source references through the same
document-citation pipeline as Search. Click an inline citation to inspect the
original passage; a comparison can reference both the baseline and target
documents. Saved answers retain their citations when reopened.

Fixed/Implemented in version: **0.261.365**
(`application/single_app/config.py`).
Search now preserves its passage references whether a later task receives its
retained excerpts (`evidence`) or prepared search content (`prepared`). Ask your
question normally; you do not need to request source quotations to make those
references available. A sources-only input identifies documents but does not
provide passages to cite. This does not prescribe an answer format or a fixed
number of citations.

Use those passages to check the answer against the source. A reference identifies
evidence, not an independent verification of every conclusion. Partial coverage
and uncertainty still matter, and opening a source still requires access to it.
A missing source location is not replaced with an invented page. Existing answers
without stored passage references are not rewritten automatically.

### Work from content already in the conversation

Fixed/Implemented in version: **0.261.416**
(`application/single_app/config.py`).
An unambiguous image already attached to the conversation can supply a
transcription request without another file-selection question. When saved
extracted text is absent, the source step uses the image itself through the
authorized vision-capable model. Unavailable image bytes or a model without
vision support need recovery; they do not become an invented transcription.
If several attachments are plausible, clarification can still be necessary.

For workspace-backed Excel workbooks, annotation requests use native Notes and
threaded-comment inspection, preserving available metadata and saved cell
values. Reported pagination and resource limits still bound what was inspected.

Since **0.261.422**, workspace Word `.docx`, `.docm`, and `.dotx` review comments
use the Word reader instead. Ask to include reviewer text and replies, and open a
native citation to inspect the retained comment, its available anchored text,
author/date, and resolution metadata. A bounded or unavailable anchor is not a
complete quotation, and a missing resolution flag is not proof that a comment is
unresolved. Word evidence does not offer an Excel worksheet preview.

The reader needs accessible original bytes; ordinary stored style metadata is not
the structured Word comment inventory. Unavailable or malformed originals remain
read failures. An inspected package with no comments is distinct from a failed
inspection. Historical failed runs are not automatically replayed by this change.

Fixed/Implemented in version: **0.261.341**
(`application/single_app/config.py`).
When you ask to rewrite, audit, summarize, or otherwise transform material
already pasted into the conversation, that material is the source to resolve
first. A short planning preview is not the complete input. The execution step
reopens the referenced saved message with current access and content checks.
An earlier AI answer can be rewritten as text, but it is not independently
verified evidence for new factual claims.

Since **0.261.370**, a formatting-only follow-up can reuse the selected answer's
retained result and original passage references. For example, ask to turn an
existing comparison into an old/new/change table without searching again.
SimpleChat carries the selected answer's provenance through the transformation,
so citations remain available in the saved response and after reload. Reusing
an answer is not a new check of the underlying facts, and opening a cited source
still requires current access.

This association requires the saved answer to match its retained text. Edited
or partially masked answers are not replaced with an unedited original to recover
citations. Source-free text does not gain source references, and unrelated
messages do not supply them.

If the intended material is missing or unclear, identify it when the planner
asks for clarification. Review a proposed workspace search before running if
you wanted work on the conversation instead. A source that exceeds the
selected model's verified input budget needs a smaller selection or an
appropriate configured model; repeating the unchanged plan does not add space.

## Review versus Edit

Fixed/Implemented in version: **0.261.416**
(`application/single_app/config.py`).

While work runs, Quiet activity keeps the conversation focused on your request.
Since **0.261.417**, the activity headline names the confirmed task and phase,
for example **Gathering: Read workbook comments** or **Reasoning: Prepare audit**.
A successful running-status check restores this progress; it is not an unknown
execution outcome. **Reconnecting to progress…** appears only when updates
cannot be confirmed and qualifies displayed tasks as last known. Reconnection
reads saved state without replaying tasks. **Saving final response** remains
distinct from a successfully published answer.

Expand the activity or open plan details to distinguish preparing an answer from
checking it. **Stop** remains in the composer. Technical failure details stay in
run inspection rather than taking over the answer.

Content preparation steps offer **Semantic review: Auto / On / Off** before
execution. Auto normally reviews the prepared content against your instructions
and supplied evidence. On requests that review where administration permits it.
Off skips optional semantic review only: required output formats, source access,
and safety checks still apply. A skipped review is not a passed factual check.

When checking finds an actionable omission or format problem, SimpleChat uses
the actual findings to adjust the answer and check the changed version again.
This uses the administrator's bounded correction allowance, normally two; an
explicit zero allows checking without automatic correction. If required checking cannot finish, the prepared work stays saved. An eligible
retry reuses retained content without regenerating the composition.

Fixed/Implemented in version: **0.261.418**
(`application/single_app/config.py`).
When you ask for a simple rewrite or prose draft using text you already supplied,
the original message is source material for checking the draft's meaning and
facts. It does not need outside verification merely to express your account.
The reviewer may still identify invented additions, omissions, or changed meaning.

For eligible single-step, text-only work, Auto can recover from a checker error
without blocking delivery. Required format, access and safety checks still run;
a completed review's content findings are not ignored. On continues to require
review, and plans using gathered information or substantive analysis keep their
stricter checking. Older or ambiguous plans without proven intent remain strict.

Open the plan to see what actually finished: **Reviewed against your supplied
text**, **Reviewed against gathered information**, or **Reviewed against your
message and gathered information** identifies a completed review and its basis.
General answers can instead show **Reviewed against your request**. **Required
output format validated** describes format validation only. A skipped optional
review stays in plan diagnostics, not as a warning appended to the chat answer.
These statements are not a guarantee of factual accuracy or independent
verification of your account.

Since **0.261.321**, integration steps show whether they **Gather information** or perform
a **Requested operation**. For example, an email request can research missing event facts,
prepare the email, and pass that content as a named input to an email action. Use
**Ask planner** before running to change the intended operation or destination.

Existing integration policies still apply. A manual-delivery email action creates a draft
and outgoing-action card for review; running the plan does not automatically send it.
Delayed and automatic delivery follow their configured modes. Check the step summary and
card for the actual outcome: a pending draft or schedule is not a completed send.
Old M365 plans without explicit operation intent remain read-only until replanned.

**Review** opens the existing drawer. You can inspect steps and their rationales,
switch off eligible steps, and remove documents from a step. These controls reduce the work already proposed or change its optional semantic
review choice; they cannot remove required validators.

**Edit** opens a full-screen preview with **Ask planner** and **History**. Use it
to discuss a change instead of asking a new question in the main conversation.
The planner creates a new version of the same plan.

If plans currently run immediately, choose Review or countdown approval before
asking your question, if your administrator permits that choice. A plan that has
already started cannot be edited.

## Read dependency-driven plans

Gather / Reason / Render plan inspection was implemented in version **0.261.127**
and became the only plan view in **0.261.139**, recorded in
`application/single_app/config.py` (Refs: microsoft/simplechat#1509). Plans
created by an earlier orchestration version now show the message that they can't
be opened or rerun, and should be replaced with a new request.

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

Since **0.261.341**, shortening a search preview does not by itself make the
retained source selection incomplete. The full retained result and its
coverage still govern downstream work. A complete top-N selection is not proof
that every relevant document or every passage in a document was examined.
Genuinely incomplete evidence still blocks a task that requires complete input.

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

### Check who planned the work and what the answer may rely on

Since **0.261.134**, the plan panel's first line under the summary names the model
that wrote the plan and how it was chosen: the model you selected, your
administrator's planning model, or the default model. When the request used
**Auto**, it also says that each step uses its own Auto-routed model. Each step still
shows its own **Execution model**.

An answer-writing task shows its **answer basis**:

- **General knowledge**: stable, widely known facts such as state capitals or
  historical dates, with no retrieval planned.
- **Gathered sources only**: every claim must come from the named inputs. The
  planner uses this for your documents, integration data, and current or local
  facts.
- **Gathered sources, plus general knowledge for stable facts**: gathered sources
  lead, and well-established knowledge may fill gaps.

A named input marked **Optional** means the answer is still written if that input
cannot be gathered, for example when a web search service is temporarily
unavailable. The answer then says what could not be gathered, and the failed task
remains visible with its reason. Read-only gathering retries once on its own after
a temporary service error.

**Visuals** lists the charts, Mermaid diagrams, or image proposal cards the planner
asked the answer to include.

Since **0.261.399**, ordinary narrative preparation uses **Use available
information** as its answer behavior. It answers what the inputs support and
explains missing information or unresolved disagreement in the answer and
requested narrative documents. **Results with limits** describes usable retained
information, not an error on an otherwise answered request. Exact datasets and
explicit complete-only transformations still require complete inputs.

Since **0.261.341**, a schedule with activity lanes, such as eating and drinking
before, during, and after a ride, is planned as a **Diagram**, even when you call
it a chart. The diagram preserves the supplied events and relative-time labels;
it shows their order rather than a quantitatively scaled time axis. Numerical
trends and comparisons still use inline data charts.

### Check what you asked for

Since **0.261.138**, **You asked for** appears at the top of the plan panel and on the
approval card. It lists what you asked to receive: the answer, each file with its
format, images with their count, and any chart or diagram. Each item shows its state:

- **Planned**, then **In progress**, **Delivered**, or **Not delivered** as its steps run.
- **Turned off** when you switched off the only step that produces it.
- **Not available**, in a warning color with the server's reason, when this plan cannot
  produce it. The rest of the plan still runs, and the answer's **Delivery notes** name it
  once instead of promising it.

The plan panel also names the step that produces each item. **Also included** lists what
the planner added without being asked, such as a suggested chart. Ask the planner for a
revision if something you need is missing from the list.

When an answer-writing step omits an explicitly requested chart or diagram,
SimpleChat asks that step to correct its answer once, if the correction fits the
model's context budget. This shares the existing correction allowance for
malformed prepared outputs; it does not rerun source gathering or integration
actions. Suggested visuals do not trigger a correction.

If a usable answer still omits the requested visual, the answer remains available,
the visual is **Not delivered**, and the run reports partial completion. A
completed answer-writing task alone does not mean its chart or diagram arrived.
For a schedule saved under the wrong visual kind, use a new request or, before
running, **Ask planner** to make it a timeline diagram.

A **Generate image** step shows the image prompt and caption it will use. Each image
follows the requested visual style, including photorealistic, and is captioned as an
AI-generated image when the plan runs and shows it in the answer. When a report or deck
binds an image, its input is optional: if the image cannot be generated, the content is
still written and the delivery notes say what is missing.

Since **0.261.192**, a **Generate image** step can also use your own pictures as reference
images, such as "a cartoon of my house" with a photo of the house attached. Turn on **Image**,
then attach the pictures, select workspace images, or choose **Use as reference** on an image
in the conversation. The step shows each reference as a chip with a thumbnail and its name.
In **Review**, remove a reference to leave it out of the step, and restore it if you change
your mind. With every reference removed, the image is generated from its prompt alone. When
the configured image model can't use reference images, attached pictures are still read as
documents, and planned images are generated from their prompts. See
[Generate images]({{ '/guides/generate-images/' | relative_url }}).

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
4. Press Enter to send, or Shift+Enter for a new line. Your request moves into the
   conversation straight away while the planner works. Select **Cancel** there to
   discard it and keep the current plan.
5. Read the updated preview. Check the steps, source selections, assumptions,
   and any adjustments reported by the planner.
6. Continue refining the same plan, or select **Run** when the current version
   describes the work you want.

If a request fails, select **Retry** to send it again or **Edit and resend** to
reword it first. Requests are limited to 2,000 characters; the counter under the
box shows how many you've used.

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

### Point the planner at documents and tags

Since **0.261.201**, **Ask planner** takes `#` documents and tags, as the main
composer does.

1. In **Ask planner**, type `#` and part of a document's name or a tag. Pick one
   with the arrow keys and Enter, or with the mouse. To browse instead, select
   **Add context**.
2. Check the chips above the box. Remove any you don't want; a removed chip
   isn't sent.
3. Describe the change and send it. For example, "Compare the regional figures
   with `#[Q4 pricing]`", where `#[Q4 pricing]` is the document you picked.

The chips show under your message in the thread. The server checks each one when
the request arrives, and accepts only documents and tags you can read now: in your
personal workspace, in groups you belong to, and in public workspaces you can see.
A conversation limited to certain workspaces accepts picks from those workspaces
only. Whole workspaces, file uploads and `/` saved prompts aren't offered here.

The planner is told which documents you picked, and a document search that
doesn't name its own documents looks only at your picks. If the plan searched
everything you can read before, the planner's reply says that it now doesn't. If
the revised plan leaves out a document you picked, the reply says so, so you can
ask again or remove it. Sources the plan already used stay available to it.

If a pick can't be used, because the document was deleted, is still processing,
or you've lost access to it, the request is refused before the planner runs and
the plan doesn't change. The reply names the pick by the label you chose. Select
**Edit and resend**, remove the chip, and send again.

If the planner answers without changing the plan, your chips go back into the box
so you can send them again or remove them.

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

Since **0.261.212**, a plan that starts one of your saved workflows never counts
down or runs automatically, whatever approval mode you chose. It waits for you to
approve it, and the card says why and names each workflow. See
[Run a workflow from chat]({{ '/guides/trigger-a-workflow/' | relative_url }}#run-a-workflow-from-chat).

## Return to an earlier version

Use **History** to inspect prior versions and restore one that better matches
your intent. Restoring creates a new current version; it does not delete later
history or reactivate an old execution.

Capabilities and source access are checked again. A version that depends on a
document or integration you can no longer use may not be restorable.

## Recover before a plan exists

Since **0.261.115**, **Retry** on a failed planning question retries planning with
the original prompt, model or agent selection, documents, and scope retained in
that browser tab. Since **0.261.317**, the resulting plan always requires review,
including when the original approval mode was Auto. It does not use the temporary
chat bubble as
a saved message ID or append a duplicate question. Stop interrupts the local
planning request; a late response cannot populate another or deleted conversation.

If the request context is no longer available, follow the notice to copy the
original message into the composer, review its selections, and send it deliberately.
The application does not guess a model or document selection from current controls.
If a plan or clarification already exists, continue from that plan or question
instead; Retry must not discard accepted answers or start an independent execution.

## Generate a fresh plan from a saved question

Implemented in version: **0.261.317** (`application/single_app/config.py`).
Select the message's **Retry** when you want a new plan for the question you are
viewing, not a continuation of its old execution. This works after deleting the
answer, provided the question and complete saved planning inputs remain available.

Retry preserves the viewed attempt's wording, prompt, model or agent, sources,
options, and accepted clarification answers. Current composer selections do not
replace them. Sources and permissions are checked again; a missing original
selection is explained rather than replaced with a different one.

The old answer is hidden while the new attempt plans at the question's position.
It remains available through the message's attempt arrows unless you deleted it.
Failures belong to their own attempt, so viewing a successful older answer does
not leave the newer failure over that answer.

Review the new plan and select **Approve and run the plan** when you want its work
to execute. Retry cannot run it automatically, even with Auto configured or after
a clarification. Editing the regenerated plan does not remove that requirement.
Earlier completed actions are not undone and could be repeated by the new plan.
Use **Retry from failed step** for recovery that reuses saved completed work.

Finish or stop a running or waiting execution before requesting another plan.
Retrying an earlier question keeps later messages, but excludes them from the
earlier question's planning context. A request whose planning failed before a run
was saved remains retryable when its saved inputs are complete.

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

A step that starts a saved workflow asks for the same confirmation, because its
workflow may already have started. Its retry never starts the workflow twice: if
the plan already started it, the retry links that run instead of starting another.

The new attempt retains the original question and effective plan, including
source restrictions, clarification answers, and the selected model. It does not
duplicate your question. The earlier attempt remains available in history.
Retry always requires your action, even when normal approval is Auto or timed.

A browser disconnect does not mean the server stopped. Let the interface check
the existing attempt before retrying. A live attempt cannot be retried, and a
lost retry response is recovered without starting a second copy.

Since **0.261.141**, reopening a conversation whose run already completed,
failed, or was cancelled shows that outcome and its recovery options, such as
**Retry from failed step**. The plan's approval controls are not offered again
for a run that has finished.

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

Since **0.261.419**, a restored waiting execution does not take over the
composer's Send/Stop control when no reply is streaming. Use the plan's saved
status and cancellation controls for that execution; waiting is not permission
to start a competing plan.

Since **0.261.303**, if the attempt fails or is stopped as a whole while a task
still waits, the plan shows that task as **Not finished** and what it produces as
**Not delivered**. Nothing will finish that wait any more, so **Retry from failed
step** is offered; it runs the waiting task again and reuses the completed ones.

The interface recognizes waiting without assuming that a downloadable file
exists. Per-file publication and retry controls require their own server-owned
output lifecycle; waiting alone does not enable them.

## Track and retry individual files

Implemented in version **0.261.127**, recorded in
`application/single_app/config.py` (Refs: microsoft/simplechat#1509). These controls
appear only when the server publishes individual output states. They do not
enable a new planner, renderer, or scheduler on their own.

**Files** appears beside the response and in the Run view. Since **0.261.141**,
each file card shows the file's name, type, and status, plus its row count and
size once it is completed. A failed, cancelled, or unavailable file also shows the
server's explanation, such as a step that reached its time limit. Attempt counts,
automatic-attempt limits, and failure codes stay in the saved run and the server
logs rather than on the card. Waiting and Rendering are unfinished work, not download
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
status and the server's explanation. Since **0.261.303**, when a failed file
can't be retried on its own and no other file is still being prepared, the
recovery card offers **Retry from failed step**, which creates the plan's files
again without repeating completed plan steps.

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

- [Chat orchestration]({{ '/features/chat-orchestration/' | relative_url }})
- [Create files with orchestration]({{ '/guides/create-files-with-orchestration/' | relative_url }})
- [Choose models for orchestration]({{ '/guides/model-catalog-routing/' | relative_url }})
- [Orchestration settings]({{ '/admin/orchestration/' | relative_url }})
