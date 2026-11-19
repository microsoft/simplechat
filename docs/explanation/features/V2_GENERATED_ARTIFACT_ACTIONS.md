# V2 Generated Artifact Actions

## Overview

When a reply produces a file, V2 draws a generated-file card with **Download** and **View**.
The classic card carried two more buttons that V2 did not: **Add to Workspace**, which turns the
file into a workspace document the search index can use, and **Create PowerPoint**, which builds
a deck from a generated Markdown file.
[V2 Tabular Analysis](V2_TABULAR_ANALYSIS.md) recorded both as "better rebuilt with V2's own
export machinery than ported", and a V2 user who wanted a generated report to become knowledge,
or a generated outline to become slides, had to switch to the classic interface.

Both actions are now on the V2 card, using the routes the classic card already used and V2's own
dialog, toast and download machinery.

Implemented in version **0.261.448**.

### Dependencies

None added. `POST /api/chat_artifacts/promote` and `POST /api/message/export-powerpoint`
already existed and are unchanged; the work is entirely in `application/v2_ui`. The PowerPoint
action reuses the message-level export's download helper and its diagram collection
(`buildMessageVisualAssets`).

## What classic does and what V2 does

| | Classic | V2 |
|---|---|---|
| **Add to Workspace** appears on | A finished file card that carries its message id and conversation id | The same, and not while the file is a background run still in progress or is withheld for approval |
| Destination | The conversation's own workspace: a group conversation offers its group, a public one its public workspace, anything else the personal workspace | The same rule; it is not offered until the conversation's metadata has loaded, because guessing "personal" for a group conversation would offer the wrong place |
| Confirmation | A dialog: "Add to *name*?" when the destination is settled, a **Choose Workspace** list otherwise | The same two shapes |
| Request | `{ conversation_id, message_id, workspace_scope, group_id?, public_workspace_id? }` with no `request_id` | The same body. `conversation_id` is the file's own, which in a shared conversation is the source conversation the file was written under |
| Outcome | A toast; the button becomes **Added to Workspace** or **Pending Approval**; any failure, a 409 included, is a toast | A toast; a status chip **Added to workspace** or **Pending approval** that outlives the card being drawn again; a 409 is read as "unconfirmed" with **Check again** |
| **Create PowerPoint** appears on | A finished Markdown file that is not a completed row-level export | The same, but not in a shared conversation |
| Request | `{ message_id, conversation_id, artifact_message_id, visual_assets }` | The same body |
| Embedded cards in an orchestration answer | No buttons | No buttons |

V2 differs from classic in three deliberate places:

- **A 409 is not a failure.** The route answers 409 when it could not confirm whether the
  publication finished, and puts its sentence under `message` rather than `error`. Classic then
  shows "Server responded with status 409". V2 shows the server's sentence and keeps the card in
  an *unconfirmed* state with **Check again**, because a copy may well exist.
- **The card remembers what it did.** Classic loses the button's state on a reload and relies on
  the server answering the repeated request with the publication that already exists. That still
  holds in V2, but the card should not need the round trip to remember what it just did while the
  page is open.
- **Create PowerPoint is hidden in shared conversations** rather than offered and refused. See
  the limitations below.

## When each action appears

Both actions need a finished file that lives on its own message in the conversation: not a
background export that has no file yet, and not a file waiting for the conversation owner's
release, which the server refuses for everyone.

**Add to workspace** also needs somewhere to put it. The workspace kinds the deployment has
switched on decide that: the personal workspace unless `enable_user_workspace` is off, group
workspaces only with `enable_group_workspaces`, public workspaces only with
`enable_public_workspaces`. A group or public conversation that does not name its workspace (one
that predates the field) offers the reader's own personal, group and public workspaces instead,
so they can say where the file belongs.

**Create PowerPoint** needs the file to be Markdown, not a completed CSV, Excel, JSON or XML
export, and needs the reply that carries it so the deck is built beside it.

Neither rule decides who may do it. The server checks the reader's role in the destination and
its approval policy:

| Destination | Server rule |
|---|---|
| Personal | Always permitted; the file is queued for processing |
| Group | The reader must be an Owner, Admin, Document Manager or User of the group, and the group must currently allow uploads. The file is submitted for approval |
| Public | The reader must be an Owner, Admin or Document Manager of the workspace, and it must currently allow uploads. The file is submitted for approval |

## The experience

### Add to workspace

1. Select **Add to workspace** on the card.
2. The dialog names where the file will be saved. For a settled destination it reads "Add to
   *name*?" with **Add to Personal**, **Submit to Group** or **Submit to Public**; a group or
   public destination also says the file becomes available once one of the workspace's approvers
   accepts the request. When the destination is not settled it reads **Choose workspace** with a
   radio list and **Add to selected workspace**.
3. While the request runs the dialog stays open and cannot be dismissed.
4. The result stays on the card:

| Server answer | The card shows | The reader is told |
|---|---|---|
| 200, personal | **Added to workspace** | "Added to your personal workspace." |
| 202, group or public | **Pending approval** | "Submitted to *name* for approval." |
| 200 with the publication already approved | **Added to workspace** | The server's sentence: the publication has already been approved |
| 409, `uncertain` or `approval_failed` | The sentence under the card and **Check again** | The server's sentence: the publication could not be fully confirmed and no second copy was created |
| 400, 403, 404, 500 | Nothing changes; the dialog stays open | The server's reason in an alert inside the dialog, so the request can be sent again |

Because the request carries no `request_id`, the server treats every request for a file as the
same one. Sending it again after a reload, or choosing **Check again**, returns the existing
publication rather than creating a second copy.

### Create PowerPoint

1. Select **Create PowerPoint** on a Markdown file's card.
2. A toast says the deck is being built and that planning the slides can take a minute; the
   button shows **Creating** and is disabled meanwhile.
3. V2 sends the diagrams already drawn in the reply beside the file's own message id. The server
   builds the deck from the stored file, not from the reply text, matches the pictures to the
   file's own diagrams by their text, and draws any it was not sent.
4. The browser downloads the `.pptx`, and the toast turns into "Markdown artifact exported as
   PowerPoint." A failure turns it into "PowerPoint export failed: *reason*" and the button is
   available again.

Selecting the message-level **Export to PowerPoint** still builds a deck from the reply text.
Classic additionally redirects that button to an attached Markdown file; V2 does not, and the
card's **Create PowerPoint** is the way to build from the file.

## Architecture

Rules live in a pure module, the page-lifetime memory in a small store, and the buttons and
dialog in components that consume them.

```
lib/generatedArtifactActions.ts          Whether each action applies, where a file can go,
                                         the request bodies, the outcome of each answer
stores/generatedArtifactActionStore.ts   How far each file got, kept for the life of the page
components/chat/GeneratedArtifactActions.tsx   The buttons, the two requests, their feedback
components/chat/ArtifactPromotionDialog.tsx    The confirmation and the workspace chooser
components/chat/GeneratedArtifactCard.tsx      Hosts the actions beside Download and View
lib/endpoints.ts                         promoteGeneratedArtifact(), artifact_message_id on
                                         the export request
```

The actions render only while the open conversation's metadata has loaded for the conversation on
screen. The destination comes from that metadata, and a stale or missing read would default to
"personal".

### Accessibility

Each button carries the file name in its label ("Add to workspace: *file*", "Check again:
*file*", "Create PowerPoint from *file*"), so several cards in one thread stay distinguishable.
**Add to workspace** has `aria-haspopup="dialog"`, and **Create** is `aria-busy` while it runs. The
status chips and the unconfirmed sentence are `role="status"`, a refusal in the dialog is a
`role="alert"`, and the workspace chooser is a fieldset of radio buttons with a screen-reader
legend.

## API surface

No routes were added or changed.

| Route | Used for |
|---|---|
| `POST /api/chat_artifacts/promote` | Add to workspace. Body `{ conversation_id, message_id, workspace_scope, group_id?, public_workspace_id? }`. Returns 200 (personal), 202 (approval needed) or 409 (`publication.state` `uncertain` or `approval_failed`, sentence under `message`); failures return `{ error }` |
| `POST /api/message/export-powerpoint` | Create PowerPoint. Body `{ message_id, conversation_id, artifact_message_id, visual_assets? }`. Returns the `.pptx` |

## Configuration

| Setting | Effect |
|---|---|
| `enable_user_workspace` | When explicitly off, the personal workspace is not offered |
| `enable_group_workspaces` | Group destinations are offered only when on |
| `enable_public_workspaces` | Public destinations are offered only when on |

These reach the browser in the `features` block of `/api/v2/bootstrap`. Approval policy and
roles are enforced by the server and are not read by the browser.

## Usage

**Make a generated report searchable.** Select **Add to workspace** on its card, check the
destination and confirm. A personal copy is queued for processing; a group or public copy waits
for that workspace's approvers.

**Turn an outline into slides.** Ask for a Markdown outline, then select **Create PowerPoint** on
its card. The deck downloads when it is ready.

**Find out whether a copy exists.** If the card says it could not confirm the publication, choose
**Check again**. The server answers with the existing publication; it never creates a second copy.

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_artifact_actions.py` | The client sends the body and path the routes read; `request_id` is left to the server; the `409` body shape is the one the client reads; each button is gated on the same file states the server enforces; the actions mount on the card with the message id; no remote assets or unsafe sinks |
| `functional_tests/test_v2_artifact_actions_logic.ts` | 17 behavioural checks, run through the Python file with esbuild and node: destination resolution for personal, group, public and unknown conversations, availability filtering, the request bodies, every outcome including the 409, and the PowerPoint rules |
| `ui_tests/test_v2_artifact_actions.py` | The real components against stubbed routes: confirm and chooser dialogs, success and approval states, an unconfirmed answer and **Check again**, refusal kept inside the dialog, the PowerPoint request body and download, hidden in a shared conversation, hidden when workspaces are off, the card remembering its state, and a 390 px phone |

### Known limitations

- **Create PowerPoint is not offered in a shared conversation.** The export route reads the reply
  from the personal conversations container and requires the caller to own that conversation,
  which a participant in a shared conversation does not, so the action is left out rather than
  offered and refused. The message-level export has the same boundary. Classic does not gate the
  button on conversation type, so the request is simply sent there and the server decides.
- **Orchestration file outputs have neither action.** The embedded card inside an orchestrated
  answer has no classic equivalent, so a file rendered by a plan keeps the **Download** and
  **View** controls it had.
- **The state is remembered for the life of the page.** A reload shows **Add to workspace** again.
  Choosing it returns the existing publication, because the request carries no `request_id`, but
  the card cannot tell beforehand that the file is already there.
- **Shared-conversation promotion rests on the route's participation check.** The route
  authorizes participants against the linked shared conversation, and V2 addresses the file by its
  own source conversation id. The automated tests exercise this against stubbed responses; it was
  not run against a live shared conversation.
- **The message-level PowerPoint button does not prefer an attached Markdown file.** Classic
  redirects the reply's **Create PowerPoint Presentation** to the Markdown file when one is
  attached. V2 leaves the message-level export on the reply text and puts the file-based export
  on the file's card.
- **Only Markdown files build decks.** The route rejects other formats, so no button is drawn for
  them.

## See also

- [V2 Tabular Analysis](V2_TABULAR_ANALYSIS.md)
- [Generated Analysis Artifact Workspace Promotion](v0.241.127/GENERATED_ANALYSIS_ARTIFACT_WORKSPACE_PROMOTION.md)
- [PowerPoint Artifact Export Source Fix](../fixes/v0.241.033/POWERPOINT_ARTIFACT_EXPORT_SOURCE_FIX.md)
- [Message PowerPoint Export](v0.241.105/MESSAGE_POWERPOINT_EXPORT.md)
- [React V2 User Interface](REACT_V2_UI.md)
