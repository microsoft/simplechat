# V2 Workflow Activity (v0.261.445)

## Overview

The V2 interface now has a **Workflow activity** page at `/v2/workflow-activity`. It shows one
workflow run as a timeline of what it did, in order: the run itself, each tool it called, and any
Microsoft 365 email or invitation it saved for review. While a run is going, the page keeps itself
current, and it is where a run can be cancelled and where a saved Microsoft 365 action is reviewed
beside the run that saved it.

Before this change V2 had a richer **run inspector** inside the Workflows section (task results,
executions, loops and decisions), but no page for the thought and tool-call timeline the classic
`/workflow-activity` page draws, nothing that listened to its event stream, and no Microsoft 365
card beside a run. Every link that used to open workflow activity, a notification, a Support shortcut,
the chat header, a run in a workflow's history, left V2 for the classic page.

Implemented in version: **0.261.445**, tracked in `application/single_app/config.py`.

No setting, API route, database container or package is added, and the server is unchanged. The page
reads the same endpoints the classic page reads.

**Dependencies:**

- [Workflow settings](../../admin/workflow.md): personal and group workflows must be switched on.
- The activity snapshot and stream routes in `route_backend_workflows.py`, and
  `functions_workflow_activity.py`, which builds the snapshot.
- [V2 Microsoft 365 Pending-Action Cards](V2_M365_PENDING_ACTION_CARDS.md): the card shown beside a
  run is the same card chat and Approvals draw.
- [V2 Notification Bell](V2_NOTIFICATIONS_BELL.md) and [V2 Support Menu](V2_SUPPORT_MENU.md): their
  links open this page.
- [V2 Workflows Workbench and Editor](V2_WORKFLOWS_WORKBENCH_AND_EDITOR.md): its run history and
  workflow header link to it.

## What the page shows

| Part | What it holds |
| --- | --- |
| Header | The workflow's name, or its conversation's title, with the run's status as words, a glyph and a colour, and a line such as "manual run completed using Weekly digest agent." |
| **Show response preview** | Closed to start with, so the timeline keeps the height. It opens a panel holding the run's error when it has one, otherwise a preview of its response, and the answer checks the run's tasks saved. The button reads **Show run error** when the panel holds an error. |
| **Open workflow** | The workflow's conversation in V2 chat. |
| **Open run** | The run in the Workflows section's run history, in its own workspace. This is V2's addition; the classic page has no equivalent. |
| **Cancel run** | Only while the run is live. While the request is in flight, and once the run's status is `cancelling` (it then reads **Cancelling**), the button is marked unavailable but keeps keyboard focus, and pressing it again asks for nothing more. When the run settles the button goes away, and if it held focus, focus moves to **Refresh**. |
| **Refresh** | Reads the snapshot again and puts the timeline back on its newest activity. It stays focusable while it reads. |
| Four figures | The run's short id, how many activities there are, how many were tool calls, and when the run started. |
| Timeline | One card per activity, in the order they began, indented by lane. Each lane is a branch the run fanned out into: the workflow itself, each tool it called, Microsoft Graph. |
| Details | The selected activity: title, status, lane, start and duration, summary, **Technical Detail**, **Event History**, and, for a saved Microsoft 365 action, its card. |

Everything a workflow wrote, a model's sentences, a tool's arguments and results, is drawn as plain
text and never parsed as markup.

### Live updates

The page reads the snapshot once, then listens to `GET .../workflows/activity/stream` while the run
is live, while it waits on a person (an approval or a Microsoft 365 sign-in), or while a conversation
has no run yet. The server sends the whole snapshot each time it changes. The page stops listening and
closes the connection once the run has settled, so a finished run holds no connection.

- A new activity is followed: the details panel moves to the newest activity until the reader picks
  another, and the timeline scrolls to it while the reader is within 24 px of the bottom. A reader who
  scrolled up to read is left where they are, and the timeline follows again when they come back to
  the bottom. **Refresh** hands the choice back.
- A frame that is not valid JSON is skipped; the next frame carries the whole snapshot again.
- The server can end the stream by saying the activity is no longer readable. The page says so in a
  notice and keeps what it has.
- A read that fails after the page has loaded keeps what is on screen and says why, where the classic
  page replaced the whole view.

### Statuses

The run is live in `running`, `cancelling` and the waiting states `awaiting_approval`,
`awaiting_sharing_approval`, `awaiting_analysis_approval`, `awaiting_run_as_approval`,
`awaiting_sign_in`, `ready_to_resume` and `resuming`: the same set as the classic page and as the
server's stream. Running is drawn in the accent colour, a wait for a person as a warning, a failure as
an error, a finish as a success and a cancelled run in neutral grey, each with its own glyph so colour
is never the only carrier.

## Addresses

`/v2/workflow-activity` takes the query the classic page takes, so every link already in circulation
maps to it one to one.

| Parameter | Meaning |
| --- | --- |
| `conversationId` | The workflow's conversation. The latest run in it is shown. |
| `workflowId` | The workflow. |
| `runId` | One run. |
| `scope` | `personal` (the default) or `group`. Case and padding are forgiven. |
| `groupId` | The group, for `scope=group`. The reader's active group when it is left out. |

Any one of the three ids is enough. With none the page shows an empty state: "Open this page from a
workflow conversation or a workflow run history entry." A link with an id a link must not carry (over
256 characters, padded, a dot segment, or containing `/`, `\`, `?`, `#` or a control character) or a
scope that is neither word is refused as a whole with "This workflow activity link is not valid." and
the server is not asked. Every address the application builds is written by one module,
`lib/workflowActivity.ts`, in a fixed order and without `scope` for the default personal one.

## Who can open it

The page has no gate of its own. It is served as part of the V2 shell, and everything it shows comes
from the activity API, so whoever the API lets in is whoever the page lets in. The API gates are
exactly the classic page's:

| Scope | Allowed when |
| --- | --- |
| Personal | `allow_user_workflows` is on and, when `require_member_of_workflow_user` is on, the reader holds the `WorkflowUser` app role. |
| Group | `enable_group_workspaces` and `allow_group_workflows` are on, the group is assigned when assignment is required, and the reader is an Owner, Admin, DocumentManager or User of it. |

The server's refusal is shown in its own words, because those words say what to ask an administrator
for: a 400, 403, 404 or 500 each reads as a problem panel with **Try again**. A 403 for a missing
role carries its sentence under `message`, which the page prefers. A response that is not JSON, such
as a gateway's error page, is never shown as the server's sentence: the status picks the words
instead. A call that never gets an answer reads "Unable to load workflow activity. Check your
connection and try again."

`functional_tests/test_v2_workflow_activity_gates.py` runs the real classic page gate and the real API
routes over every combination of settings, app roles and group membership and fails if they ever
disagree about who is let in or why they are refused. No API change was needed.

## Where it is opened from

| From | How |
| --- | --- |
| The chat header | A **Open workflow activity** icon beside the conversation details button, for a conversation a workflow made (`chat_type` of `workflow`, or a workflow id on the conversation or its provenance), while personal workflows are on for the reader. A conversation a group workflow made opens the group's page when group workspaces are on. |
| A run in a workflow's history | **Open activity** on each run in the Workflows section's **Runs** tab, personal or group, carrying the run's conversation and workflow and, for a group, `scope=group&groupId=`. |
| The workflow's own header | **Activity**, once the workflow has a conversation and a run under way or on record. |
| A notification | A link the server wrote for the classic page, `/workflow-activity?...`, now always opens this page with its query kept. See [V2 Notification Bell](V2_NOTIFICATIONS_BELL.md). Microsoft 365 notices no longer need the classic page, because this page draws the saved action. |
| A Support shortcut | `/workflow-activity` in the Support menu or an announcement opens this page. A shortcut that names a run is rebuilt from ids the page can read. See [V2 Support Menu](V2_SUPPORT_MENU.md). |

The three buttons in V2's own screens open the page in a new tab, as the classic buttons do, so the
workflow list or the chat, and a draft being typed in it, stay where they are. They are real links
rather than script, so the address can be copied and the link followed from the keyboard.

## Technical specifications

Paths are relative to `application/v2_ui/src`.

| File | Responsibility |
| --- | --- |
| `pages/WorkflowActivityPage.tsx` | The page: the states (empty, invalid, loading, error, ready), the header, and the two-column body. |
| `components/workflowActivity/useWorkflowActivity.ts` | Reading, the live stream, cancelling and selection. Everything that runs later than the render that made it (a read, a frame, a cancel's answer, a card's update) holds the address it was made for and does nothing once the reader has gone to another run, so a cancel that finishes late cannot stop the read of the run they are on. |
| `components/workflowActivity/WorkflowActivityHero.tsx` | The header: title, status, caption, the buttons, the four figures and the response panel. |
| `components/workflowActivity/WorkflowActivityTimeline.tsx` | The lane-indented timeline and following the newest card. |
| `components/workflowActivity/WorkflowActivityDetail.tsx` | The selected activity, its event history and its Microsoft 365 card. |
| `components/workflowActivity/ActivityPendingAction.tsx` | The shared `PendingActionCard` with a store of its own, told what the snapshot says. |
| `components/workflowActivity/ActivityStatusBadge.tsx` | The status as words, a glyph and a tone. |
| `components/workflowActivity/WorkflowActivityLinks.tsx` | The chat header icon, **Open activity** on a run and **Activity** on a workflow. |
| `lib/workflowActivity.ts` | The address: parse, validate, build, the entry-point links and the API URLs. Dependency-light, because the notification resolver and the Support shortcut translator import it. |
| `lib/workflowActivitySnapshot.ts` | Reading the server's snapshot defensively, and the page's pure rules: the caption, the figures, statuses, selection and following. |
| `lib/workflowActivityStream.ts` | The one `EventSource`, made to this application. |
| `lib/notificationLinks.ts`, `lib/latestFeatureShortcuts.ts` | Open this page for a `/workflow-activity` link. |
| `scripts/check_xss_sinks.py` | Lists `workflowActivityHref`, `workflowConversationActivityHref` and `activityRunHref` as reviewed same-origin link builders. |

### API calls

| Call | Used for |
| --- | --- |
| `GET /api/user/workflows/activity` | The personal snapshot, with `conversation_id`, `workflow_id` and `run_id`. |
| `GET /api/group/workflows/activity` | The group snapshot, with the same query and `group_id`. |
| `GET .../workflows/activity/stream` | The same snapshot, whole, as `data:` frames while the run is live. |
| `POST /api/{user\|group}/workflows/<id>/runs/<run>/cancel` | **Cancel run**; the page reads the snapshot again after it. A group call carries `group_id`. |
| `GET /api/m365/preferences`, `GET` and `POST /api/msgraph/pending-actions/<id>[/send-now\|approve\|cancel]` | The saved action's card, through the same store chat and Approvals use. |

### The Microsoft 365 card

An activity that stands for a saved email or invitation carries the action in the snapshot. The page
draws it with the shared `PendingActionCard`, in the same `inline` form chat uses, so Send, Send now
and Cancel submit the version that was reviewed, the server's answer is the one that counts, and
nothing is ever sent by the browser on its own. Opening the page sends nothing. The card is given the
snapshot as a snapshot rather than as a read the server confirmed, so the store still checks the
action against the server before it sends. When the card learns something newer than the snapshot, the
page reads the snapshot again, once; an update that changes nothing does not.

### Layout and accessibility

- Two columns from 992 px (the timeline, then the details), one column below. Under 992 px every card
  has the same indent and the timeline is capped at half the screen so the details stay reachable.
- Colour comes only from theme tokens, so the page follows light, dark and the other themes.
- The timeline is an ordered list named **Workflow activity timeline**; each card is a button, and the
  selected one carries `aria-current`. The response button carries `aria-expanded` and `aria-controls`.
  A visually hidden status line announces the counts and the run's status as they change.
- A refused read and a notice about a failed refresh, cancel or stream are announced as alerts.
- **Refresh** and **Cancel run** are marked `aria-busy` and `aria-disabled` while they work, and are
  never given the native `disabled` attribute: a disabled button hands the reader's focus to the page,
  so a keyboard user who pressed one would be back at the top of the document. The button keeps focus
  and ignores another press. If **Cancel run** goes away while it holds focus, because the run settled,
  focus moves to **Refresh**, which is beside it.
- A name or text with no spaces in it, such as a workflow called
  `weekly_customer_feedback_digest_report_for_q4_2026` or a long tool name, wraps inside its card at
  any width. The title, the lane labels, the technical detail and the event history break anywhere
  rather than widen the page. In a workflow's run history, **Open activity** and **Ask in chat** wrap
  under the run's time on a narrow screen, so the time that tells runs apart stays readable.

## Usage

See [View workflow activity](../../guides/view-workflow-activity.md).

## Testing and validation

- `functional_tests/test_v2_workflow_activity.py` pins the route and every entry point; the query,
  endpoints and live statuses against the classic page; the new-tab, response-preview, theme and layout
  contracts ported from the classic tests; that no markup sink, `display:none` or off-site asset is
  used; and runs the Node probes below.
- `functional_tests/test_v2_workflow_activity_logic.mjs` executes the real modules against snapshots
  built by the server's own `build_workflow_activity_snapshot`: the address contract and its allowlist,
  every entry-point link, the live statuses read from the server and the classic script, the failure
  wording, the page's rules for the caption, figures, selection and following, the stream with a fake
  `EventSource`, and notification and Support links.
- `functional_tests/test_v2_workflow_run_link_routing.mjs` (updated) covers how a notice's classic link
  resolves, including group runs and Microsoft 365 notices.
- `functional_tests/test_v2_workflow_activity_gates.py` runs the classic page gate and the API routes
  side by side, and checks the stream is gated as the snapshot is.
- `functional_tests/test_v2_notifications_bell.py` and `functional_tests/test_v2_support_menu_logic.ts`
  (updated) cover the links that now open this page.
- `ui_tests/test_v2_workflow_activity.py` drives the real page in a browser against the server's own
  snapshots and a held event stream: the empty, refused and failed states; a finished run; a live run
  followed over the stream until it settles, with the connection closed afterwards; the follow-the-bottom
  rule; selection; the response panel; cancelling and its failures; a group run; a Microsoft 365 card
  that is cancelled without a reload loop; text-only output; layout at 1280, 992, 991 and 390 px; light
  and dark contrast; and the entry points. It also covers keyboard focus after Enter on **Refresh** and
  **Cancel run** (never the page, at 1280 and 390 px), a cancel that finishes after the reader moved to
  another run (the other run still finishes loading) and the busy state of a cancel that is still under
  way, and text with no spaces in it at 390 and 360 px (no scroller, card or element wider than the
  screen). The existing `ui_tests/test_v2_notifications_bell.py` was updated for the new routing.
- `ui_tests/test_v2_workflow_run_history_layout.py` drives the real Workflows workbench and measures a
  run's row in the run history at 390 and 360 px, with and without **Ask in chat**: nothing wider than
  the row or clipped by the workbench, and the run's time kept readable.

### Known limitations

- The classic page treats an unknown `scope` as personal. This page refuses it, because a link that
  names a scope neither page knows is not one the application wrote.
- The caption reads a wait state as words ("awaiting sign in"), where the classic page prints the
  stored word.
- A notice that carries no link of its own and is about a Microsoft 365 action stays without a link.
  The server always writes one for these.
- The timeline jumps to the newest card rather than scrolling smoothly, because a smooth scroll sends
  scroll events from the middle of its own journey and each would look like the reader leaving the
  bottom.
- The server's refusals are shown as it words them, so a disabled personal-workflows setting reads
  "Allow User Workflows is disabled." where the classic page printed "Personal workflows are disabled."
- A cancelled Microsoft 365 action reads **Failed** on the timeline, because the server maps a
  cancelled action to a failed activity, as it does for the classic page. The card beside it says
  **Cancelled**.
- A group link that names no group reads the reader's active group, as on the classic page, and so has
  no **Open run** link, because the run's group cannot be named in it.
