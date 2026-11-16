# V2 Shared Assist Thread

Implemented in version: **0.261.200**.

Document and tag references in the plan editor added in version: **0.261.201**.

Options for the workflow editor's **Ask AI** tab added in version: **0.261.213**.

Application version tracking: `application\single_app\config.py`.

Related issues: #1552 (the shared thread), #1556 (`#` document references) and #1548 (the
workflow editor's **Ask AI** tab), part of #1543.

## Overview and dependencies

Four V2 editors let you describe a change in words:

- **Ask AI** in the diagram editor;
- **Ask AI** in the chart editor;
- **Ask AI** in the image editor;
- **Ask planner** in the orchestration plan editor.

Before this version, each of them left your message in the input box until the server answered,
which for an image or a plan can take a while. The message only moved into the conversation, and
the box only cleared, once the reply arrived. The diagram, chart and image editors had no way to
stop a request, and a failure left the text in the box with an error. Each input also had a
`maxLength`, so a long paste silently lost its end.

The four editors now share one assist thread:

- Your message joins the thread the moment you send it, and the input clears.
- A reply placeholder shows **Working…**, the seconds elapsed, and **Cancel**.
- A failed request stays in the thread with its error, **Retry** and **Edit and resend**.
- A counter shows the length against the limit. A message over the limit is refused, not
  shortened.
- Enter sends and Shift+Enter adds a line in every editor. Ctrl+Enter and ⌘+Enter also send.

Each message carries an id the browser makes up, the *submission id*. The server stores it on both
turns of the exchange, which lets the editor match the message it showed early to the one stored
later. In a shared conversation the live update for your change can arrive before your own reply,
and the id is what stops the message showing twice. The same id makes **Retry** safe: if the first
attempt had already succeeded, the server answers from what it stored instead of making the change
again.

From version **0.261.201**, **Ask planner** also takes `#` documents and tags. The server checks
them for the person asking as the request arrives, adds them to that revision's plan inputs
exactly once, and stores them on the user turn so the thread can show them. The other three
editors don't offer them. See **Document and tag references in the plan editor** below.

From version **0.261.213**, the V2 workflow editor's **Ask AI** tab runs on the same thread. It
needed a few things the four editors above don't, such as counting in code points and keeping its
thread while the editor is open. Each one is an option that's off by default, so the four editors
are unchanged. See **Options for the workflow editor** below, and
[Workflow AI assistant](WORKFLOW_AI_ASSISTANT.md) for the tab itself.

Dependencies:

- The V2 interface in `application/v2_ui`. The classic interface has none of these editors and is
  unchanged.
- The revision features the editors belong to:
  [V2 inline diagram editing](V2_INLINE_DIAGRAM_EDITING.md), which also covers charts,
  [V2 inline image editing](V2_INLINE_IMAGE_EDITING.md), and orchestration plan editing. Their
  routes, storage and permissions are unchanged apart from the optional submission id.
- `zustand`, already a V2 dependency, for the thread store. No package is added.

There's no new route, setting or database container.

## Technical specifications

### Architecture

| Layer | File | Role |
|---|---|---|
| Store | `application/v2_ui/src/stores/assistThreadStore.ts` | Holds the threads outside React, so a request outlives the editor that started it. |
| Logic | `application/v2_ui/src/lib/assistThread.ts` | Sending, settling, Cancel, Retry, Edit and resend, matching stored turns, and the `useAssistThread` hook. |
| Limits | `application/v2_ui/src/lib/assistLimits.ts` | The longest instruction each editor accepts. |
| Component | `application/v2_ui/src/components/chat/AssistThread.tsx` | The log, the pending and failed turns, the counter and the input. |
| Input | `application/v2_ui/src/components/chat/ComposerEditor.tsx` | The main composer's editor, used here in a restricted mode. |

Each editor gives the hook a `send` function that makes the editor's existing request and reports
how it ended. The thread handles everything else, so the four editors behave the same way.

A thread is keyed by what it edits:

- `block:<conversation>:<kind>:<message>:<index>` for a diagram or chart;
- `image:<conversation>:<message>` for an image;
- `plan:<conversation>:<turn>` for a plan;
- from 0.261.213, `workflow:personal:<workflow>` for a saved personal workflow, or
  `workflow:new:<id>` for a new or proposal draft, with an id made when the workflow editor opens.
  These threads use the conversation id `workflow-editor`, because the workflow editor isn't part
  of a chat.

Closing an editor and opening it again returns to the same thread, including a request that is
still running, and any text you hadn't sent. Nothing in the store is saved: reloading the page
starts every thread empty.

The store drops threads nobody needs. When you use an editor, threads from other conversations
with nothing running, no failed or cancelled turn and no unsent text are dropped. Past 50 threads,
the least recently used go too. A thread with a request in flight is never dropped, because its
answer still has to land. From 0.261.213, a thread an open editor holds is never dropped either,
and using it doesn't drop other conversations' threads. See **Held threads** below.

### Restricted input

The thread's input is the main composer's `ComposerEditor` with a new `restricted` prop, not a
copy of it. Restricted mode hides what doesn't belong in a scoped edit:

- file uploads and the conversation's files;
- `/` saved prompts;
- `@` mentions.

`#` document and tag references, and the **Add context** control, appear only when the thread also
passes `allowContext`. From 0.261.201 the plan editor does; the diagram, chart and image editors
don't. A restricted input offers documents and tags only, never whole workspaces, because those are
all the plan route accepts: its search scope sets `workspacesEnabled: false`, which
`searchContextCandidates` (as `includeWorkspaces`) and `DocumentPickerPopover` honour. The main
composer and the orchestration question card don't pass `restricted`, so they're unchanged.

From 0.261.213 the workflow editor's **Ask AI** tab passes `allowContext` with
`contextDocumentsOnly`, so its input offers documents only, without tags, because the workflow
assist route refuses tags.

### Stored and local threads

The diagram, chart and plan editors already show the transcript the server stored. Their threads
are *stored* threads: a finished exchange leaves the thread, and the stored turns show it instead.

The image editor's stored transcript is written for the model and isn't shown turn by turn, so its
thread is a *local* one. It keeps up to 20 finished exchanges as the page's own record of what you
asked for in this visit. They're held in memory only and never saved. Earlier changes the server
stored are listed above the thread under **Earlier changes to this image**.

**Create image from reference** has a thread of its own, because a new image isn't a change to the
picture it's based on. The new image arrives in the conversation, so the editor closes once the
request is on its way.

### Sending

On submit the thread checks the message, clears the input and appends your turn with a pending
reply, all before the request starts. It then sends.

A thread allows one request at a time. A second send is refused and its text stays in the input.

The request carries no transcript from the browser. The model sees only the turns the server
stored, and the server stores an exchange only when its change succeeds. A request that failed is
never replayed to the model; one you cancelled is only if the server finished it anyway.

### Cancel

In the diagram, chart and image editors, **Cancel** stops the browser's request. The turn then
reads "Cancelled. The change may still be applied if the server had already started it." The server
can't be stopped once it has called the model, so the thread remembers the cancelled id.

If your next request is refused because the item changed, and the stored transcript shows the
cancelled request did finish, the editor shows the latest version and says so: "Your earlier request
finished after you cancelled it. The latest version is shown. Send again if you still want this
change." Your new message goes back into the input.

In the plan editor, **Cancel** asks the server to discard the pending change, as the editor's
**Cancel change** button already did, and the turn waits for that answer. Once the change is
discarded your message goes back into the input. If you've already started typing something else,
the message stays in the thread as cancelled, with **Retry** and **Edit and resend**. If the
planner had finished before the discard, its stored reply shows instead.

### Retry and Edit and resend

**Retry** sends the same message again with the same submission id. If the first attempt had
reached the server and been stored, the server replays the stored result instead of calling the
model a second time.

In the plan editor, **Retry** reuses the id only while the request is still exactly the one it was
sent with: the same plan version, step edits and action. The plan route holds an id to the first
request it arrived with, even one that failed, and refuses it with anything else for good. Cancel
moves the plan to a new version, so a retry after it, or after you toggle a step, goes out under a
fresh id. The thread still recognises the stored turns of every id it sent
(`application/v2_ui/src/lib/planSubmissionIds.ts`).

**Edit and resend** removes the exchange and puts its text back into the input, above anything you
had started typing, so you can change it before sending.

### Submission ids

`submission_id` is a new, optional field on these requests:

| Request | Route |
|---|---|
| Diagram or chart change | `POST /api/message/<message_id>/block-revision/assist` |
| Image change | `POST /api/message/<message_id>/image-revision` |
| Diagram or chart change in a shared conversation | `POST /api/collaboration/conversations/<conversation_id>/messages/<message_id>/block-revision/assist` |
| Image change in a shared conversation | `POST /api/collaboration/conversations/<conversation_id>/messages/<message_id>/image-revision` |

The rules live in `application/single_app/functions_assist_submissions.py`:

- An id is 1 to 128 letters, digits, `.`, `_`, `:` or `-`. A malformed id is rejected with
  400 before the model is called. A request without one behaves exactly as before.
- The id is stored on both turns of the exchange. Turns stored before this version have none.
- An id that is already stored with the same instruction is a *replay*. The route returns what it
  stored with `"replayed": true`. It doesn't call the model, write a revision or notify a shared
  conversation again. Access is checked first, as for any other request.
- An id that is already stored with a different instruction is refused with 409 and
  `"code": "submission_conflict"`.
- Only an image instruction carries an id. The **Prompt** and **Controls** tabs write no
  transcript turns, so the id is ignored for them.

A retry can be sent while the request it repeats is still waiting on the model. It then finds
nothing stored when it's first checked, so it's checked again once the model has answered:

- The image routes check the id again in the copy of the image they read after the model call. A
  repeat is answered from what the first request stored, and a reused id is refused, so neither
  stores a second version or exchange. The model was called twice, and the second image is left
  unused.
- The personal diagram and chart route writes with a version check. When its write loses to the
  first request's, it reads the message again and answers the same way. A write lost to an
  unrelated change is the ordinary 409 with the current revisions. Without an id it's still a 500,
  as before.
- A revision conflict an image route finds after the model call returns the versions that beat
  the request, from the copy read after the call, not the ones it started from.

The shared diagram and chart route saves without a version check, so there a racing retry
replaces the first request's result instead of adding a second one.

The plan edit route, `POST /api/v2/orchestration/runs/<run_id>/edit`, already required a
`submission_id` and already replayed or refused a repeated one. It now holds the id to the same
format as the routes above, and stores it on the plan's edit chat turns. The format is stricter
than the plan route's old rule, but every id the V2 client has minted, a UUID or a `turn-` token,
already matched it.

Submission ids are bookkeeping. They're never shown to a model.

### Matching stored turns

Whenever the stored turns change, from the editor's own reply or from a shared conversation's live
update, the thread compares their ids with its own exchanges:

- A pending exchange whose id is already stored is hidden, so it isn't shown twice when the shared
  conversation's live update for your change arrives before your reply. The input stays busy until
  the reply lands.
- A failed or cancelled exchange whose id turns up stored is removed. The change happened after
  all, and the stored turns now show it.

### Limits

Every editor accepts up to 2,000 characters, which matches the server:

| Editor | Server limit |
|---|---|
| Diagram and chart | `MAX_INSTRUCTION_LENGTH` in `functions_block_revision_assist.py` |
| Image | `MAX_INSTRUCTION_LENGTH` in `functions_message_image_revisions.py` |
| Plan | `EDIT_INSTRUCTION_LIMIT` in `functions_orchestration_plan_revisions.py` |
| Workflow (**Ask AI**, from 0.261.213) | `ASSIST_INSTRUCTION_MAX_LENGTH` in `functions_workflow_assist.py`, counted in code points |

The counter turns red past the limit and says how many characters to remove. The send button stays
off until the message fits. A functional test fails if either side changes without the other; for
the workflow editor that's `test_the_instruction_limit_matches_the_server` in
`functional_tests/test_v2_workflow_ask_ai.py`.

### Accessibility

- The thread is a `role="log"` region with `aria-live="polite"`, so a screen reader announces a new
  turn or reply without interrupting.
- The elapsed seconds are hidden from screen readers, so they aren't announced every second.
- A failed reply is marked as an alert.
- The counter and the over-limit message are linked to the input with `aria-describedby`, and an
  over-limit input is marked invalid.
- Composing text with an input method editor doesn't send on Enter.

### Diagram and chart editors stay open

Two rendering faults closed an open diagram or chart editor whenever its message changed, for
example when a revision was saved:

- `AssistantMarkdown` re-parsed the message whenever it received a new masks list, even an equal
  one. Any change to the message made a new list, and the re-parse remounted every diagram and
  chart in it. The parse is now keyed on what the masks contain.
- `MermaidDiagram` returned a different element tree while a new source rendered or failed, which
  unmounted its editor. It now renders the same tree in every state.

An editor now stays open until you close it.

### Document and tag references in the plan editor

Added in **0.261.201** (#1556). **Ask planner** passes `allowContext`, so its restricted input
offers `#` documents and tags and **Add context**. There's no new route, setting or container.

#### The request

The `ask` action of `POST /api/v2/orchestration/runs/<run_id>/revisions` takes an optional
`references` list. Each entry is what the reader picked, which is a claim, not authorization:

```json
{"kind": "document", "id": "<document id>", "label": "Q4 pricing",
 "scope": {"kind": "group", "id": "<group id>"}}
```

- `kind` is `document` or `tag`. A tag's `id` is its name.
- `scope.kind` is `personal`, `group` or `public`. A group or public workspace needs its `id`; a
  personal one needs none.
- At most 20 distinct entries (`REQUEST_REFERENCE_LIMIT`) and 100 raw ones before duplicates are
  removed. An id is at most 512 characters.
- `label` is display text only. Control and bidirectional formatting characters are removed and
  it's cut to 200 characters. A `scope.name` from the picker is accepted and dropped.
- Chat attachments, whole workspaces (`kind: "scope"`) and the `chat` scope are refused.

#### One canonical form

`canonical_request_references` in `functions_assist_references.py` checks the shape, removes
duplicates by kind, id and workspace (keeping the first label), and sorts by kind, workspace and
id in code point order. `_normalize_request` keeps that form in the claimed request, so the
submission fingerprint that already told a replay from a conflict now covers the references too.
An Ask without references keeps the fingerprint it had before.

The browser computes the same form with `canonicalPlanReferences` in `lib/planReferences.ts`,
sends exactly that, and includes it in the fingerprint `choosePlanSubmissionId` compares. One
fixture, `functional_tests/fixtures/plan_reference_canonicalization.json`, runs through both. So:

- reordered or repeated chips are the same request, and **Retry** reuses its id;
- the same id with different references is refused with 409 `submission_conflict`;
- a request sent after the chips change goes out under a fresh id.

#### The check

The route claims the submission and then, unless the claim is a replay, calls
`resolve_plan_edit_references` before anything streams. It authorizes each reference for the
acting user as of now with `resolve_scope_references` (next section), applies the conversation's
workspace lock exactly as the question card does, and caps what a plan has gathered at 100
(`ELICITATION_REFERENCE_LIMIT`). Only a plan's owner can revise it, as before, so references are
only checked for the owner.

A refused reference releases the claim. The route answers with JSON `{"error": ..., "code": ...}`
and changes neither the plan nor its chat:

| Code | Status | When |
|---|---|---|
| `reference_unavailable` | 400 | A document was deleted, isn't finished processing, or can't be read by the user any more; a tag no longer exists; or the workspace is turned off, gone, or outside the conversation's lock. |
| `reference_limit` | 400 | More than 20 references, or the plan would have more than 100. |
| `invalid_request` | 400 | A malformed entry, a chat attachment, a whole workspace or the `chat` scope. |
| `reference_check_failed` | 503 | The check itself failed. Nothing changed, and a retry is safe. |
| `submission_conflict` | 409 | The submission id was already used for a different request. |

The message names the reference by the label the reader picked, for example "“Q4 pricing” is no
longer available to you. Remove it and pick another document.", never by a title read from the
server. A deleted document and one the reader can no longer read get the same message, so an error
doesn't reveal whether a document exists. The thread shows it in the planner's turn, where **Edit
and resend** puts back both the text and the chips.

#### Plan inputs

`build_plan_edit_outcome` adds the authorized references to that revision's seeds with
`merge_elicitation_context`, the function question-card answers use. Documents join
`document_ids`, with their labels in `document_labels`; tags join `tags`; and group and public
workspaces join the active workspace lists. The planner then sees the documents among its
candidates, marked as selected. A document search step that names no documents of its own searches
the selected ones, when the plan is checked and when it runs. A revision that leaves a selected
document out isn't refused: the planner's turn says "The plan does not use all selected
documents. Review this change before running."

`merge_elicitation_context` narrows the search scope and the active workspace lists to the new
references' workspaces when the plan had no selection. `_merge_ask_references` then widens them
back just enough to keep every source the current plan already uses, each authorized again for
the user, so a document from another workspace doesn't break an existing step.

The seeds are saved with the new revision when the planner returns a plan, and with its question
when it asks one, so an answer keeps them. A reply that changes nothing saves no seeds. The browser
then puts the chips back in the input with a note, so they aren't lost.

#### What's stored

- The user turn stores the references as authorized: kind, id, the server's label, and the
  workspace's kind and id.
- When a revision first limits a plan that searched everything the reader can read, the planner's
  turn stores a `scope_notice`, `{"kind": "search_limited", "documents": [...], "tags": [...],
  "more": n}`. The thread shows it as "Searches in this plan now look only at what you attached:
  …".

Both are display data for the thread, bounded by `_bounded_chat`. The planner is shown only each
turn's role and content, and reads the authorized seeds instead. Labels render as plain text,
never as markdown or HTML.

A replayed submission is answered from what was stored. Its references aren't checked or merged
again, so a plan's seeds are never merged twice.

#### Untrusted content

Checking a reference reads document metadata only (`include_content=False`). Document text
reaches the model only through the plan's existing bounded search and context steps, as untrusted
content. Labels, ids and document text are never logged; a refusal logs its reason and position.

### The scope reference authorizer

`resolve_scope_references(references, user_id, settings=None, *, allowed_workspaces=None,
limit=ELICITATION_REFERENCE_LIMIT)` in `functions_orchestration_context.py` authorizes `#`
references outside a conversation; the default limit is 100. The plan editor uses it now; the
workflow assistant is expected to reuse it. It reads no Flask request state and no conversation.

- **Accepts** documents and tags in personal, group and public workspaces the user can read now.
  Group membership and public visibility are checked again on every call, and the workspace type
  must be turned on (`enable_user_workspace`, `enable_group_workspaces` or
  `enable_public_workspaces`). A document must resolve in the workspace it was picked from,
  through the document-context and source-manifest boundaries mixed-source reads use, and be
  finished processing. A tag must still exist in its workspace.
- **Refuses** chat attachments, whole workspaces and the `chat` scope.
- **`allowed_workspaces`** is an allowlist shaped like a scope-locked conversation's
  `locked_contexts`: items with `scope` and `id`. `None` adds no limit beyond the user's access
  and the enabled workspace types.
- **Returns** the references in order, without duplicates, in the question card's normalized
  shape: `kind`, `id`, `scope` with the workspace's `kind`, `id` and `name`, and a `label` from
  the server's record. `merge_elicitation_context` takes that shape as it is.
- **Raises** `ScopeReferenceError`, a subclass of `ElicitationContextError`, with `message`,
  `reason`, `reference_index` and the cleaned `label`. `reason` is one of `document_unavailable`,
  `document_not_ready`, `tag_unavailable`, `workspace_disabled`, `workspace_unavailable`,
  `workspace_locked`, `unsupported_kind`, `invalid_reference`, `too_many` or
  `verification_failed`. The message names the reference by its label, or as "A selected
  document" or "A selected tag" when it has none.

The question card's `resolve_elicitation_references` is now its conversation checks plus the same
private core, `_authorize_references`. A golden test captured from the code before the change,
`functional_tests/fixtures/orchestration_elicitation_reference_golden.json`, holds its results and
messages identical.

Document provenance, the origin ids and `workflow` tag added in 0.261.194, is metadata. It never
makes a document readable, and a document a workflow created is referenced like any other.

### Options for the workflow editor

Added in **0.261.213** (#1548). The V2 workflow editor's **Ask AI** tab runs on this thread. Its
route counts characters differently, its server writes nothing, and the editor can open from a
chat, so it needed a few options the other editors don't use. Each one is off by default, and the
diagram, chart, image and plan editors don't pass any of them.

The tab calls the hook like this (`application/v2_ui/src/components/workflows/useWorkflowAssist.ts`):

```ts
useAssistThread({
    key,                                          // workflow:personal:<id> or workflow:new:<id>
    conversationId: 'workflow-editor',
    mode: 'local',
    maxLength: WORKFLOW_ASSIST_INSTRUCTION_LIMIT, // 2,000
    send,
    countCodePoints: true,
    retain: true,
});
```

| Option | Where | Default | What it does |
|---|---|---|---|
| `countCodePoints` | `useAssistThread` and `AssistSubmitOptions` | Off | Measures `maxLength` in Unicode code points rather than UTF-16 units, the way the workflow assist route measures `ASSIST_INSTRUCTION_MAX_LENGTH`, so an emoji counts once and the counter agrees with the server. `assistTextLength` and `describeDraftProblem` take the same flag. The helpers are in `lib/codePoints.ts`, which counts a lone surrogate as one, as Python does. |
| `retain` | `useAssistThread` | Off | Holds the thread while the editor is mounted, through `holdAssistThread(key)`. See **Held threads** below. |
| `text` | `AssistSubmitOptions` | Unset | Sends that text as a message of its own and leaves the input as it is. The controller's new `sendText(text)` uses it for the tab's quick actions. |
| `cancelledMessage` | `AssistThread` | The default note | Replaces "Cancelled. The change may still be applied if the server had already started it." on a cancelled turn. It's only for an editor whose server writes nothing, so a cancel is safe. The workflow tab passes "Cancelled. Nothing was changed." |
| `contextDocumentsOnly` | `AssistThread` and `ComposerEditor` | Off | With `allowContext`, offers `#` documents only: no tags and no workspaces, because the workflow assist route refuses tags. It sets `documentsOnly` on the search scope, which `useContextSuggestions` and `DocumentPickerPopover` honour, and the picker's search box reads "Search documents…". |

Two smaller changes go with them:

- `renderReply` already existed, and no editor passed it. With it, the reply is now wrapped in a
  `div` with `break-words` instead of the default paragraph with `whitespace-pre-wrap`, so an
  editor can render a card with blocks of its own. Without it, the default paragraph is unchanged.
  The workflow tab's card puts the model's reply, warnings and errors in as text, never as HTML or
  Markdown.
- `ComposerEditor` sets `data-composer-menu-open` on its holder while its `#` list or another menu
  is open. In the workflow editor, Escape inside the side panel normally closes the panel. The
  dialog reads this attribute, and the **Add context** picker, so that Escape closes only the open
  list or picker and focus stays in the **Ask AI** input.

#### Held threads

Using a thread sweeps idle threads of other conversations. The chat editors all belong to a chat,
so the sweep only clears what you left behind in other chats. The workflow editor belongs to none:
its threads use the conversation id `workflow-editor`. Without a hold, using **Ask AI** would drop
the idle threads of the chat you were in, such as an image editor's local transcript. The workflow
proposal card's **Edit** opens the workflow editor from a chat, so this is a real case.

`holdAssistThread(key)` in `assistThreadStore.ts` keeps a thread while its editor is mounted:

- A held thread is never dropped, by the sweep or by the 50-thread cap.
- Using a held thread doesn't sweep other conversations' threads.
- Holds are counted per key. The release function it returns is safe to call twice.
- A key that was held stays *quiet* after it's released, until its thread leaves the store. Using
  a quiet thread doesn't sweep either, so an answer that lands after the editor closed leaves the
  chat's threads alone.
- With nothing held, `pruneThreads` behaves exactly as before.

Closing the workflow editor stops waiting for a request that's still running. The workflow assist
route writes nothing, so nothing is left half done. The hook cancels the request before it releases
its hold, so the cancel doesn't sweep either.

### Files

Server:

- `application/single_app/functions_assist_submissions.py` (new)
- `application/single_app/functions_image_edit.py`
- `application/single_app/functions_message_block_revisions.py`
- `application/single_app/functions_message_image_revisions.py`
- `application/single_app/functions_orchestration_plan_editing.py`
- `application/single_app/functions_orchestration_plan_revisions.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/route_backend_orchestration.py`

V2 interface:

- `application/v2_ui/src/components/chat/AssistThread.tsx` (new)
- `application/v2_ui/src/lib/assistThread.ts` (new)
- `application/v2_ui/src/lib/assistLimits.ts` (new)
- `application/v2_ui/src/lib/planSubmissionIds.ts` (new)
- `application/v2_ui/src/stores/assistThreadStore.ts` (new)
- `application/v2_ui/src/components/chat/ComposerEditor.tsx`
- `application/v2_ui/src/components/chat/DiagramEditor.tsx`,
  `ChartEditor.tsx`, `ImageEditor.tsx` and `OrchestrationPlanEditor.tsx`
- `application/v2_ui/src/components/chat/MermaidDiagram.tsx`, `InlineChart.tsx` and
  `AssistantMarkdown.tsx`
- `application/v2_ui/src/lib/blockRevisions.ts`, `imageRevisions.ts`, `endpoints.ts`,
  `collaboration.ts`, `orchestration.ts` and `orchestrationController.ts`
- `application/v2_ui/src/stores/chatStore.ts` and `orchestrationStore.ts`

Added for document and tag references in 0.261.201:

- `application/single_app/functions_assist_references.py` (new): the request's canonical form.
- `application/single_app/functions_orchestration_context.py`: `resolve_scope_references` and the
  shared core behind `resolve_elicitation_references`.
- `application/single_app/functions_orchestration_plan_editing.py`,
  `functions_orchestration_plan_revisions.py` and `route_backend_orchestration.py`: the check,
  the seed merge, the stored chips and notice, and the request identity.
- `application/v2_ui/src/lib/planReferences.ts` (new): the browser's canonical form, the chips a
  request sends and a stored turn shows, and the notice text.
- `application/v2_ui/src/components/chat/OrchestrationPlanEditor.tsx`, `AssistThread.tsx`,
  `ComposerEditor.tsx`, `ContextMenu.tsx` and `DocumentPickerPopover.tsx`, and
  `application/v2_ui/src/lib/contextMentions.ts`, `assistThread.ts`, `orchestration.ts`,
  `orchestrationController.ts` and `planSubmissionIds.ts`.

Added for the workflow editor's **Ask AI** tab in 0.261.213:

- `application/v2_ui/src/lib/codePoints.ts` (new): code point length and a prefix that never
  splits a surrogate pair.
- `application/v2_ui/src/lib/assistThread.ts`: `countCodePoints`, `retain`, `text` and `sendText`.
- `application/v2_ui/src/stores/assistThreadStore.ts`: held and quiet threads, and
  `holdAssistThread`.
- `application/v2_ui/src/components/chat/AssistThread.tsx`: `cancelledMessage`,
  `contextDocumentsOnly` and the `renderReply` wrapper.
- `application/v2_ui/src/components/chat/ComposerEditor.tsx`, `ContextMenu.tsx` and
  `DocumentPickerPopover.tsx`: documents-only search and `data-composer-menu-open`.

The tab itself, and its files, are described in [Workflow AI assistant](WORKFLOW_AI_ASSISTANT.md).

## Usage

### Enable or configure

There's nothing to turn on. The thread appears wherever its editor does:

| Editor | Available when |
|---|---|
| Diagram and chart | Always, once the reply containing it has finished. |
| Image | `enable_image_generation` is on. Sending also needs an available image model. |
| Plan | `enable_chat_orchestration` is on and the plan hasn't started. |

`#` documents and tags in **Ask planner** need nothing more. A pick is accepted only from a
workspace type that's turned on (`enable_user_workspace`, `enable_group_workspaces` or
`enable_public_workspaces`); the server refuses the rest.

### Ask for a change

1. Select **Edit** under a diagram, chart or generated image, or beside an orchestration plan.
2. Open **Ask AI**, or **Ask planner** for a plan.
3. Describe the change, for example "Make it left to right and add a review step after approval".
4. Press Enter, or select the send button. Your message moves into the thread and the input
   clears.
5. Watch **Working…** count up. When the reply arrives, the diagram, chart, image or plan updates.

While you wait you can type your next message, but it won't send until the current one finishes.

### Point the planner at a document

1. In **Ask planner**, type `#` and part of a document or tag name, or select **Add context**.
2. Pick one with the arrow keys and Enter or Tab, or click it. It becomes a chip in the input. Remove
   a chip before sending to leave it out.
3. Describe the change and send. The chips appear in your turn in the thread.

If the plan searched everything you can read before, the planner's reply says its searches now
look only at what you attached. If the planner answers without changing the plan, your chips go
back in the input.

### When something goes wrong

- **Cancel** stops waiting. In the diagram, chart and image editors, a change the server had
  already started may still be applied. If it is, the editor recognises it as yours and shows the
  latest version.
- **Retry** sends the same message again. It's safe after a dropped connection: a change that
  already went through isn't made twice.
- **Edit and resend** puts the message back in the input so you can change it.
- A document or tag the planner can't use is named in the planner's turn, by the name you picked.
  **Edit and resend** puts back your text and chips, so you can remove it and send again.

### Keyboard

| Key | Effect |
|---|---|
| Enter | Send the message. |
| Shift+Enter | Add a new line. |
| Ctrl+Enter or ⌘+Enter | Send the message. The plan editor used to send only this way. |

In **Ask planner**, while the `#` list is open:

| Key | Effect |
|---|---|
| Up and Down arrows | Move through the list. It wraps at either end. |
| Enter or Tab | Attach the highlighted document or tag. Neither sends the message while the list is open, or while it's still loading. |
| Escape | Close the list, or the **Add context** picker, and stay in the input. The editor stays open; Escape again closes it, as before. |

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_assist_thread_submission_id.py` | The optional id on the personal and shared diagram, chart and image routes: storage on both turns, replay without a second model call or room event, conflicting reuse, malformed ids, access before replay, a retry that races the request it repeats, conflicts found after the model call, ids kept out of model prompts, and the plan edit id rule. The image routes run the real revision flow with only the model and blob storage replaced. |
| `functional_tests/test_v2_assist_thread.py` | The four editors use the shared thread, sending doesn't wait for the server, the polite log, the restricted input, refusal instead of truncation, the client and server limits, the id on every request, local image transcripts, editors staying open, and no remote assets. |
| `functional_tests/test_v2_assist_thread_logic.ts` | The thread logic, run by the test above: settling, Cancel, Retry, Edit and resend, the one-request rule, matching stored turns, the ids a plan retry goes out under, and the store's caps. |
| `ui_tests/test_v2_assist_thread.py` | The diagram and chart editors in a browser: immediate send, Cancel then Retry, failures, keys and the counter, a shared broadcast before the reply, a cancelled change that finished, and the restricted input beside the full main composer. |
| `ui_tests/test_image_editor_capabilities.py` | The image editor's thread: immediate send, a local transcript, Cancel and Retry, a cancelled change that finished, and the counter. |
| `ui_tests/test_v2_orchestration_plan_editor.py` | The plan editor's thread: immediate send with elapsed time, Cancel through the server, and the keys and counter. |
| `ui_tests/test_v2_elicitation_composer.py` and `ui_tests/test_v2_prompt_composer_experience.py` | Regressions for the question card and the main composer, which share `ComposerEditor`. |
| `functional_tests/test_orchestration_reference_authorizer_golden.py` | The question card's reference check gives the same results and messages as the code before the shared core, for every case in `fixtures/orchestration_elicitation_reference_golden.json`, success and each error family. |
| `functional_tests/test_orchestration_scope_reference_authorizer.py` | `resolve_scope_references`: personal, group and public documents and tags accepted with server labels, and a result `merge_elicitation_context` and the question card's check both accept. Refused: chat attachments and whole workspaces, another user's documents and personal workspace, a group the user left, a public workspace they can't see, a document picked from the wrong workspace, turned-off workspace types, the allowlist, deleted, unready and missing items, and over-limit lists. Also the messages, which never use a server title, retryable failed checks, and logs without labels or ids. |
| `functional_tests/test_orchestration_plan_revision_references.py` | The revision route end to end: a `#` document reaching the revised plan and its search at run time, a tag filtering that search, references surviving a planner question, a reply that changes nothing, a replay that isn't checked or merged again, a conflicting reuse of a submission id, refused references that change nothing and leave no turn, owner-only revision, the workspace lock, the search notice, the planner seeing only role and content, keeping the plan's own sources, and the per-plan limit. |
| `functional_tests/test_assist_reference_canonicalization.py` | The server's canonical form against `fixtures/plan_reference_canonicalization.json`, the request identity it gives, `references` allowed only on `ask`, and the bounded chips and notice on stored turns. |
| `functional_tests/test_v2_plan_editor_references.py` | Only the plan editor offers references, documents and tags only, canonical references on the request, the browser's limits, chips as text, chips never lost, Escape, and no remote assets. It runs `test_v2_plan_references_logic.ts`, which checks the browser's canonical form against the same fixture, the submission ids a changed selection goes out under, and the notice text. |
| `ui_tests/test_v2_plan_editor_references.py` | In a browser with stubbed routes: `#` by keyboard to a chip, a chip in the thread and a plan that reads it; **Add context** with group documents and tags, and Escape keeping the editor open; a removed chip not sent; the refusal with **Edit and resend**; chips coming back; titles rendered as text; a lost reply retried under the same id; the main composer and question card keeping their tools; and no `#` in the diagram, chart and image editors. |
| `functional_tests/test_v2_workflow_ask_ai.py` | The workflow editor's options, from 0.261.213: each defaults to off, and the diagram, chart, image and plan editors pass none of them. The tab's limit matches `ASSIST_INSTRUCTION_MAX_LENGTH` and is counted in code points. It runs `test_v2_workflow_ask_ai_logic.ts`, which checks the limit in code points against the default count in UTF-16 units, a quick action sent as its own message with the input left alone, and held and quiet threads: a held thread, a released one whose answer lands late, one held twice, and pruning as before once nothing holds it. |
| `ui_tests/test_v2_workflow_ask_ai.py` and `ui_tests/test_v2_workflow_ask_ai_proposal.py` | The workflow **Ask AI** tab in a browser, including the limit in code points, a `#` list with documents only, Escape closing only that list or the picker, the cancelled wording and quick actions. The proposal file opens the workflow editor from a chat with an idle image thread through the proposal card's **Edit**, sends a turn and closes the editor. The image thread is still there, and once the editor has let go the chat prunes as before. |

### Known limitations

- Cancel in the diagram, chart and image editors can't stop a change the server has already
  started. The thread says so and recognises the change if it lands.
- An image change refused after the model call, as a repeat or a conflict, leaves the image it
  generated unused in storage. Conflicts already did this before this version.
- The image editor's transcript isn't saved. It lasts until you reload the page, or use an editor
  in another conversation. The server keeps its own transcript for the model, and **Earlier changes
  to this image** shows what it stored.
- Threads belong to one browser tab. Another tab, or a reload, doesn't see a request in flight.
  Its stored result appears there when the conversation is reloaded, or through the live update in
  a shared conversation.
- `#` references are offered only in **Ask planner** and, from 0.261.213, the workflow editor's
  **Ask AI** tab, which offers documents only. The diagram, chart and image editors don't offer
  them.
- A planner reply that changes nothing doesn't keep the documents and tags you sent. The chips go
  back in the input, and sending again uses them.
- A revision can add documents and tags to a plan but not take them away. To search everything
  again, restore an earlier version from **History** or start a new request.
- A tag is matched by name in every workspace the plan searches, not only the one it was picked
  from.
- After text changes that come without key presses, such as a mouse paste or dictation, the first
  arrow key or Escape in an open `#` list can be undone and the list reopens. Typing, or pressing
  the key again, works. This comes from `ComposerEditor` and affects every composer, not only the
  plan editor.
