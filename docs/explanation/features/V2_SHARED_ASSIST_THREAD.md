# V2 Shared Assist Thread

Implemented in version: **0.261.195**.

Application version tracking: `application\single_app\config.py`.

Related issue: #1552, part of #1543.

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
- `plan:<conversation>:<turn>` for a plan.

Closing an editor and opening it again returns to the same thread, including a request that is
still running, and any text you hadn't sent. Nothing in the store is saved: reloading the page
starts every thread empty.

The store drops threads nobody needs. When you use an editor, threads from other conversations
with nothing running, no failed or cancelled turn and no unsent text are dropped. Past 50 threads,
the least recently used go too. A thread with a request in flight is never dropped, because its
answer still has to land.

### Restricted input

The thread's input is the main composer's `ComposerEditor` with a new `restricted` prop, not a
copy of it. Restricted mode hides what doesn't belong in a scoped edit:

- file uploads and the conversation's files;
- `/` saved prompts;
- `@` mentions.

`#` document and tag references, and the **Add context** control, appear only when the thread also
passes `allowContext`. No editor does in this version. The main composer and the orchestration
question card don't pass `restricted`, so they're unchanged.

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

The counter turns red past the limit and says how many characters to remove. The send button stays
off until the message fits. A functional test fails if either side changes without the other.

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

### Files

Server:

- `application/single_app/functions_assist_submissions.py` (new)
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
- `application/v2_ui/src/stores/assistThreadStore.ts` (new)
- `application/v2_ui/src/components/chat/ComposerEditor.tsx`
- `application/v2_ui/src/components/chat/DiagramEditor.tsx`,
  `ChartEditor.tsx`, `ImageEditor.tsx` and `OrchestrationPlanEditor.tsx`
- `application/v2_ui/src/components/chat/MermaidDiagram.tsx`, `InlineChart.tsx` and
  `AssistantMarkdown.tsx`
- `application/v2_ui/src/lib/blockRevisions.ts`, `imageRevisions.ts`, `endpoints.ts`,
  `collaboration.ts`, `orchestration.ts` and `orchestrationController.ts`
- `application/v2_ui/src/stores/chatStore.ts` and `orchestrationStore.ts`

## Usage

### Enable or configure

There's nothing to turn on. The thread appears wherever its editor does:

| Editor | Available when |
|---|---|
| Diagram and chart | Always, once the reply containing it has finished. |
| Image | `enable_image_generation` is on. Sending also needs an available image model. |
| Plan | `enable_chat_orchestration` is on and the plan hasn't started. |

### Ask for a change

1. Select **Edit** under a diagram, chart or generated image, or beside an orchestration plan.
2. Open **Ask AI**, or **Ask planner** for a plan.
3. Describe the change, for example "Make it left to right and add a review step after approval".
4. Press Enter, or select the send button. Your message moves into the thread and the input
   clears.
5. Watch **Working…** count up. When the reply arrives, the diagram, chart, image or plan updates.

While you wait you can type your next message, but it won't send until the current one finishes.

### When something goes wrong

- **Cancel** stops waiting. In the diagram, chart and image editors, a change the server had
  already started may still be applied. If it is, the editor recognises it as yours and shows the
  latest version.
- **Retry** sends the same message again. It's safe after a dropped connection: a change that
  already went through isn't made twice.
- **Edit and resend** puts the message back in the input so you can change it.

### Keyboard

| Key | Effect |
|---|---|
| Enter | Send the message. |
| Shift+Enter | Add a new line. |
| Ctrl+Enter or ⌘+Enter | Send the message. The plan editor used to send only this way. |

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_assist_thread_submission_id.py` | The optional id on the personal and shared diagram, chart and image routes: storage on both turns, replay without a second model call or room event, conflicting reuse, malformed ids, access before replay, ids kept out of model prompts, and the plan edit id rule. |
| `functional_tests/test_v2_assist_thread.py` | The four editors use the shared thread, sending doesn't wait for the server, the polite log, the restricted input, refusal instead of truncation, the client and server limits, the id on every request, local image transcripts, editors staying open, and no remote assets. |
| `functional_tests/test_v2_assist_thread_logic.ts` | 116 checks of the thread logic, run by the test above: settling, Cancel, Retry, Edit and resend, the one-request rule, matching stored turns, and the store's caps. |
| `ui_tests/test_v2_assist_thread.py` | The diagram and chart editors in a browser: immediate send, Cancel then Retry, failures, keys and the counter, a shared broadcast before the reply, a cancelled change that finished, and the restricted input beside the full main composer. |
| `ui_tests/test_image_editor_capabilities.py` | The image editor's thread: immediate send, a local transcript, Cancel and Retry, a cancelled change that finished, and the counter. |
| `ui_tests/test_v2_orchestration_plan_editor.py` | The plan editor's thread: immediate send with elapsed time, Cancel through the server, and the keys and counter. |
| `ui_tests/test_v2_elicitation_composer.py` and `ui_tests/test_v2_prompt_composer_experience.py` | Regressions for the question card and the main composer, which share `ComposerEditor`. |

### Known limitations

- Cancel in the diagram, chart and image editors can't stop a change the server has already
  started. The thread says so and recognises the change if it lands.
- The image editor's transcript isn't saved. It lasts until you reload the page, or use an editor
  in another conversation. The server keeps its own transcript for the model, and **Earlier changes
  to this image** shows what it stored.
- Threads belong to one browser tab. Another tab, or a reload, doesn't see a request in flight.
  Its stored result appears there when the conversation is reloaded, or through the live update in
  a shared conversation.
- `#` references are off in every editor. Issue #1556 turns them on in the plan editor, together
  with the server-side checks they need.
