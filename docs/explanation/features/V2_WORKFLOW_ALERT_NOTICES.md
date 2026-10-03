# V2 Workflow Alert Notices (v0.261.199)

## Overview

A workflow alert that needs attention now pops up in V2. Until this release, V2 only
counted workflow alerts in the bell (added in 0.261.195), so a critical alert
waited there until someone happened to open the panel. Classic has always popped
these alerts up as a modal. V2 shows a small notice instead, anchored to
**My Workspace** in the navigation rail. The notice doesn't take focus, so it never
interrupts typing. Opening it grows it into the full alert card, and closing it
tucks it into the bell, where the alert stays unread.

Implemented in version: **0.261.199**, tracked in
`application/single_app/config.py`. Track N2 of the
[chat orchestration workflows roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md)
(#1553, part of #1543).

Open and Dismiss up front, with everything else under Show more, since version: **0.261.228** (#1624).

Dependencies:

- The V2 bell ([V2 Notification Bell and Desktop Notifications](V2_NOTIFICATIONS_BELL.md)).
  The notice reuses its count poller, link resolver and navigation. It adds no
  second polling loop and no second notification store.
- `GET /api/notifications/workflow-alerts`, the route classic's pop-up already reads.
- [Workflow alert rules](WORKFLOW_ALERT_RULES.md), which decide each alert's priority
  and delivery.

No setting and no container are added. The alerts route gains one optional query
parameter, `since_hours`. The workflow runner now records where each workflow
lives on the alerts it creates, so **Open workflow** can find it.

## When a notice appears

An alert pops up only when all of these hold:

- **Its delivery is pop-up.** The server settles delivery when the alert is raised.
  An alert on every run always pops up, as it always has. For an alert rule, its
  delivery decides; left at **Default for severity**, info and low alerts are
  notify-only, and medium, high and critical alerts pop up. A notify-only alert is
  never shown as a notice; it waits in the bell.
- **It is unread, not dismissed, and recent.** Only alerts created in the last 24
  hours pop up; older ones stay in the bell. So a user coming back from a week away
  isn't met by a week of pop-ups. An alert dated more than five minutes in the future
  is treated as a clock error and left in the bell too.
- **No other tab has shown it.** Each alert is claimed before it is shown, and a
  claimed alert pops up in only one tab.
- **The page is free.** The tab must be visible, the mobile navigation closed, and
  no dialog open. Any visible `role="dialog"`, `role="alertdialog"` or open
  `<dialog>` counts, including the bell's own panel. A waiting alert shows as soon
  as the page is free again. It is checked every 700 ms while something waits, and
  whenever a dialog is added or removed.

### One tab per alert

Classic remembers the alerts it has shown in `sessionStorage`, which is per tab, so
every open classic tab pops the same alert. V2 claims each alert in `localStorage`
(`simplechat.v2.workflowAlertClaims`) before showing it, under the Web Locks API so
two tabs can't claim the same alert at the same instant. Where Web Locks aren't
available, the claim is written, read back 50 ms later, and the tab whose claim
survived shows the alert. If storage can't be used at all, claims are kept for the
tab alone, which is classic's behavior.

A claim means "shown somewhere", not "being shown here now". An alert that was
closed, tucked away, or whose tab was closed stays unread in the bell and doesn't
pop up again. Claims expire after 25 hours, longer than the pop-up window, and at
most 500 are kept.

### How alerts are read

The notice has no timer of its own for the server. It listens to the bell's count
reports (`subscribeNotificationCount`) and reads
`GET /api/notifications/workflow-alerts?limit=10&since_hours=24` only when the
count suggests something changed:

- On the first count of the visit, and when the reader comes back to the tab.
  Reads for a return that come within two seconds of each other count as one,
  unless the count rose on the way back: a rise is a new alert, so it is always read.
- When the count rises. A read asked for while another is on its way runs as soon
  as that one lands, because the earlier read may have left before the new alert
  was written.
- On every poll while the count is at the server's cap of 10, where a new alert
  can't raise it. Otherwise there is one safety read at most every five minutes.
- When the count falls while an alert is waiting or showing and the card didn't
  cause it, so an alert read in another tab or on another device leaves this tab
  too. A fall within three seconds of one of the card's own actions is taken to be
  that action.

Only a successful alerts read retires an alert. When fewer than 10 alerts come back
the answer is complete. Any alert missing from it is no longer unread and recent,
perhaps read or dismissed elsewhere, so it is dropped. A read that fails changes
nothing: what waits and what shows stay, and the next successful read decides.

The count can't retire an alert either. The count route answers zero when it can't
count as well as when nothing is unread, so a count of zero while an alert waits or
shows is confirmed with an alerts read. If a read is already on its way, another
follows it. With nothing waiting or showing, nothing is read while the count is
zero, because there is nothing unread to pop up.

When a tab that was hidden comes back, alerts that waited while it was away are held
for up to three seconds for a fresh read. So an alert read in another tab meanwhile
doesn't flash up on return.

## The notice

The notice is a callout from **My Workspace**, where workflows live, with a notch
pointing at the item.

| Rail | Placement |
|---|---|
| Expanded | Drops down below My Workspace and overlays the items under it rather than pushing them, so the conversation list never jumps |
| Collapsed to the icon strip | Flies out to the right of the icon |
| Mobile | Flies out from the strip's icon, as when collapsed, and waits while the navigation drawer is open |

It shows one entry at a time: the loudest waiting, and then the newest. Each entry
shows:

- a priority tag with its icon, which always names the priority in words
- the alert's title and its workflow's name
- for a group, a line such as "Failed 4 times since 10:42 AM"
- **+N more** when more entries are waiting

The whole notice is one button that opens the card, and **Close alert notice** (×)
sits beside it. Its accessible name reads the same as its announcement, for example
"Open high priority workflow alert: Deploy gate is red, from Nightly release
readiness scan."

Info, low and medium notices tuck into the bell after eight seconds. The timer
pauses while the pointer is over the notice or focus is inside it. When it resumes,
at least 2.5 seconds are left, so a notice doesn't vanish the moment the pointer
leaves. High and critical notices stay until they are opened or closed.

Closing the notice, or pressing Escape while focus is in it, tucks it into the bell
straight away, and the bell swings. Nothing is marked read by tucking: the alert
stays unread in the bell and, having been claimed, doesn't pop up again.

### Focus and announcements

- The notice never takes focus, so typing is never interrupted.
- It sits in the tab order right after **My Workspace**, the item it hangs from.
- Moving focus onto something the notice covers, such as the rail items under it,
  tucks the notice, so it never hides what has focus.
- Each new notice is announced once through a live region. The announcement is
  polite, or assertive when the loudest alert is critical. For example:
  "Critical priority workflow alert: Ledger totals do not match, from Payments
  reconciliation. 1 more waiting." An alert that has to wait is announced when it is
  finally shown, not when it arrives. The region is cleared after seven seconds.

## The alert card

Opening the notice grows it into the full alert card, built on the shared `Modal`
shell. Escape, the backdrop and the focus trap behave as in every other V2 dialog.
Focus moves into the card and goes back to where the reader was when it closes,
because the notice that opened it is gone by then.

The card shows just enough to decide what to do:

- **A header band** in the priority's colors, with the priority, the kind ("Alert"
  or "Run failed"), the title, the workflow and when it arrived.
- **A group note** when one workflow raised several alerts, on the first entry only.
- **Why you're seeing this.** A sentence such as "Build watcher is set to alert at
  high priority when a run fails." or "Build watcher sent this alert at high
  priority.", followed by the rules that matched, each with its severity and
  reason. The runner's own log line ("HIGH alert triggered by: …") is left out,
  because the sentence and the rules already say it. A reason that says anything
  else is shown.
- **The summary.**
- **What went wrong**, for a failed run.
- **Open**, a large green button, and **Dismiss**. Open goes to the conversation the
  workflow created when it created one; otherwise to the conversation it posted
  into, then its run, then the workflow. Its accessible name and tooltip name the
  destination, for example "Open created conversation". An alert with nothing to
  open offers **Mark read** in its place.

**Show more** holds everything else, so a busy alert, such as one that stood up a
response group, a meeting, a map and a briefing, doesn't bury its summary and Open
button under a dozen chips and links:

- **The detail**.
- **Chips** for the alert's enrichments and its trigger, runner and agent.
- **The other links** the alert carries, checked by the bell's resolver. Classic
  labels the link to the conversation a workflow posts into "Open workflow"; V2
  names it **Open workflow conversation**, because the card's own **Open workflow**
  goes to the workflow. A link to another site isn't offered; a note says so.
- **Open workflow**, which goes to the workflows list of the workspace the workflow
  lives in and opens the run that raised the alert:
  `/workspace/workflows?workflow_id=<id>&run_id=<id>`, or
  `/groups/<group id>/workflows?workflow_id=<id>&run_id=<id>` for a group workflow.
  It works when that list is already open, too. The workflows section acts on each
  navigation that names a workflow once, so choosing Open workflow again, even for
  the same run, opens the run again. Anything else that later changes the list, such
  as running another workflow, doesn't reopen a run it has already opened.
  When the open list doesn't have the workflow, as when it was created in another tab
  after the list was read, the section reads the list once more for that navigation.
  If the workflow still isn't there, as when it was deleted after the run, nothing
  opens and the list isn't read again until Open workflow is chosen again.
  Alerts from before this release have no recorded scope. For those, it is taken
  from the workspace named on their **Open workflow** conversation link, and when
  that doesn't name one the button isn't shown rather than guessing.
- **Ask about this**, when the alert offers it.

Below the card's body:

- **"1 of 3", Next and Mark all read** when more than one entry is waiting. Next
  steps through the entries and wraps around.

### What the actions change

| Action | Effect |
|---|---|
| Open, Dismiss | Every alert in the entry shown, so a grouped workflow's alerts are handled together. Open marks them read and goes to its destination. The button's tooltip says how many, for example "Acts on all 2 alerts from this workflow." |
| Mark read | Shown in Open's place only when the alert has nothing to open. Every alert in the entry shown. |
| Mark all read | Every alert the card holds, one request each. It never calls the bell's own `mark-all-read`, which would also clear notices the card never showed. |
| Another link, Open workflow | Opens the page and marks every alert in the entry read, as Open does |
| Ask about this | Opens a new chat that answers from the run's stored result ([Phase 6a](CHAT_WORKFLOW_RESULTS_FOLLOW_UP.md)). Nothing is marked, as with Close: the alert stays unread in the bell. |
| Close (×, Escape, backdrop) | Nothing is marked. The alerts stay unread in the bell and don't pop up again. |

Buttons stay focusable while a request is in flight (`aria-disabled`), so a
keyboard user doesn't lose their place.

### Hooks for later phases

- **Open run.** `workflowAlertOpenRunPath` calls `v2WorkflowRunPath` from
  `lib/notificationLinks.ts`, which returns `null` until Phase 6b adds a V2 run page.
  While it does, the card offers Open workflow, whose `run_id` already opens the
  run's history. Once it returns a path, **Open run** takes Open workflow's place.
- **Ask about this.** Phase 6a (0.261.214) fills in `workflowAlertFollowUpAction`.
  It returns `{ label: 'Ask about this', run }` for a personal workflow's alert that
  names a run which had finished (`completed` or `completed_partial`, read from the
  alert's `status`) when the alert was raised, and only while the reader's bootstrap
  carries `enable_chat_workflow_results`. Group alerts, alerts without a run, and
  failed or cancelled runs get no button. `run` opens the chat through
  `openWorkflowResultInChat` (`lib/workflowResultFollowUp.ts`), which reads the run
  again before anything is selected; see
  [Workflow Results in Chat](CHAT_WORKFLOW_RESULTS_FOLLOW_UP.md).

## Priority styling

Colors come from the V2 theme tokens, following `WORKFLOW_ALERT_PRIORITY_CONFIG`,
which classic's pop-up reads. Color never carries the meaning alone: the priority
is always written out, and a failed run always says so.

| Priority | Icon | Notice edge | Tag and card band |
|---|---|---|---|
| Info | Info | None | Info tint (`bg-info-soft`) |
| Low | Bell | None | Info tint |
| Medium | Circle alert | None | Warning tint (`bg-warn-soft`) |
| High | Triangle alert | Danger edge | Danger tint (`bg-danger-soft`) |
| Critical | Octagon alert | Stronger danger edge | Solid danger (`bg-danger`) with inverse text |

A failed run shows the failed-run icon (octagon ×) at any priority. Tags keep the
ordinary text color over a tint, because the light theme's `--warn` is too pale to
pass as text. The notice is drawn on `--surface-modal`. Under
`prefers-reduced-transparency` the theme swaps glass for solid surfaces, including
the notch.

## Alert storms

A workflow that fails on every run for an hour is one thing to know, not twelve. All
waiting alerts from one workflow become one entry with a count. The entry leads with
its loudest alert, and the newest of those. Its line reads "Failed N times since
*time*" when every alert is a failed run, and "N alerts since *time*" otherwise.
Entries are ordered loudest first. Alerts that arrive while the notice or card is
up join it and are re-sorted, so a critical alert takes the notice over from a
medium one. The card keeps the entry it is showing.

## Motion

- **Entrance.** CSS keyframes: `wf-alert-drop` below the item, `wf-alert-flyout`
  beside the icon (220 ms).
- **The bell's swing.** `wf-bell-swing` (720 ms), on the notice's icon as it arrives
  and on the bell when a notice tucks into it.
- **Grow and tuck.** Web Animations, because they run between boxes only script can
  measure: the notice grows into the card (280 ms), and tucks into the bell (420 ms).

Only `transform` and `opacity` are animated, and no animation library is added.
Reduced motion is checked in code, with
`matchMedia('(prefers-reduced-motion: reduce)')`, rather than relying on the global
CSS rule, which only covers CSS. Under reduced motion the entrance, grow and tuck are
160 ms fades, and the bell doesn't swing.

## Untrusted text and links

Alert text can quote email, documents or web content, so every field is rendered as
text, never as HTML or Markdown. Fields are trimmed to bounded lengths: 600
characters for the summary, 4,000 for the detail and 80 for each enrichment. An
alert shows at most 3 links, 10 rules and 8 enrichments. Links go through the
bell's resolver (`resolveNotificationLink`) and navigation, so only this site's
pages open. The resolver refuses links to other sites, API endpoints and malformed
links, however they are spelled.

## Server: the bounded query

`get_unread_workflow_priority_notifications(user_id, limit=5, since_hours=None, raise_on_error=False)` in
`functions_notifications.py` used to read every workflow alert the user had within
the 60-day TTL and filter it in Python. It now pushes these filters into one
parameterized Cosmos query with `SELECT TOP @limit ... ORDER BY c.created_at DESC`:

- the user
- the notification type
- not read and not dismissed by the user
- not notify-only

Category isn't a filter. Alerts and failed runs both pop up, as they always have,
and the category only chooses the icon and wording.
The Python re-check is unchanged and still stops at the limit. The query stays
within the user's partition. It filters and sorts on single properties, which the
container's default range index serves, so no composite index is needed.

`GET /api/notifications/workflow-alerts` accepts an optional `since_hours`:

| Parameter | Values | Effect |
|---|---|---|
| `limit` | 1 to 10, default 5 | Unchanged. Out-of-range values fall back to 5. |
| `since_hours` | A whole number of hours, 1 to 1440 (the 60-day TTL) | Keeps alerts created within that many hours. Anything else is refused with `400` and `{ "success": false, "notifications": [], "error": "..." }` before anything is read. |

The response shape is unchanged. V2 asks for `since_hours=24`. Classic doesn't pass
it, so it gets the same alerts as before, at the same cadence, from a bounded read.
The route keeps its Blueprint, Swagger and authentication decorators.

A read that fails is logged and answered with an empty list, as it always was. V2
can't take an empty list at its word, though: it treats a short answer as every
unread pop-up alert there is, and retires anything missing. So the route passes
`raise_on_error=True` whenever `since_hours` is given, which only V2 does. For V2, a
failed read reaches the route's existing `500` answer,
`{ "success": false, "notifications": [] }`, and V2 keeps what it holds. Classic
still gets the empty list.

The workflow runner now records `workflow_scope` (`personal` or `group`) and
`workflow_group_id` (empty for a personal workflow) in the metadata of the alerts it
creates, which is how Open workflow finds the right workflows list. The key isn't
`group_id`. When a notification is opened, classic makes `link_context.group_id` or
`metadata.group_id` the active group. So a `group_id` in the metadata would switch
groups whenever a group workflow's alert opens a link that names no group, such as a
failure raised before the workflow's conversation existed, or an agent's personal
conversation.

## The alert lab

`/v2/dev/alert-lab` shows sample alerts with the real notice and card inside the
real application shell, so changes to them can be tried without a workflow to
trigger. It exists only on the Vite dev server (`npm run dev`, then
`http://localhost:5174/v2/dev/alert-lab`). `App.tsx` loads it with
`lazy(() => import('./dev/AlertLabPage'))`, created only inside the
`import.meta.env.DEV` branch, and renders it in `Suspense`. A production build
defines `import.meta.env.DEV` as false, drops that branch, and never references the
module, even if a lab file later does something when it is imported.

`functional_tests/test_v2_alert_lab_excluded_from_build.py` checks both halves. In
the source, that lazy import must be the only reference to `src/dev/`, and the check
looks at every form one can take: `from`, a bare `import '...'`, a dynamic
`import(...)` (including inside `lazy`), `require(...)` and `import.meta.glob(...)`.
In a production build, no emitted file is named for the lab, and no emitted text
file holds one of the lab's markers. The check searches an existing build and
doesn't build one. With no build, or a build older than the notice, it is skipped.

While the lab is open it feeds the notice itself. The server feed is paused, and the
card's read, dismiss and open actions only record what they would have done, so
nothing reaches the server. Leaving the page puts both back. The lab offers:

- **Notice**: theme, rail expanded or collapsed, motion (System, Reduced or Full),
  and **Open a 360 px window**.
- **State**: the current phase, what is showing, what waits to be claimed and what
  is held back. **Refuse read and dismiss** makes the card's actions fail, as they
  would if the server refused them, and **What happened** logs what they did.
- **Scenarios**: every priority, every priority as a failed run, an alert storm,
  long text, a short alert with no links, hostile text and links, a group workflow,
  an alert while a dialog is open, notify-only, and older than 24 hours. Each says
  what should happen.
- **One alert at each priority**, as an alert or a failed run.
- **Replay** and **Clear**.

Every sample goes through the same reader as a real alert, and each send makes new
ids, because a claimed alert never pops up twice.

The Vite dev server now also serves the app for page loads at `/v2` and `/v2/...`,
as Flask does in production. Before, it answered those with Vite's "did you mean
/static/v2/" page.

## Files

| File | Change |
|---|---|
| `application/single_app/functions_notifications.py` | The bounded, parameterized query, `raise_on_error`, and `parse_workflow_alert_since_hours` |
| `application/single_app/route_backend_notifications.py` | Validates `since_hours`, passes it through, and answers `500` when V2's read fails |
| `application/single_app/functions_workflow_runner.py` | Records `workflow_scope` and `workflow_group_id` on new alerts |
| `application/v2_ui/src/lib/workflowAlertNotices.ts` | New: reading and bounding alerts, eligibility, grouping, wording and paths |
| `application/v2_ui/src/lib/useWorkflowAlertRuntime.ts` | New: when to read alerts, and when the page is free to show them |
| `application/v2_ui/src/lib/workflowAlertClaims.ts` | New: one tab per alert |
| `application/v2_ui/src/lib/workflowAlertActions.ts` | New: read and dismiss, through the bell's store when it holds the notice |
| `application/v2_ui/src/lib/workflowAlertMotion.ts` | New: reduced motion, grow and tuck |
| `application/v2_ui/src/stores/workflowAlertStore.ts` | New: the queue, entries, phases and actions |
| `application/v2_ui/src/components/notifications/WorkflowAlertNotice.tsx`, `.css` | New: the notice, its slot in the rail, its keyframes |
| `application/v2_ui/src/components/notifications/WorkflowAlertCard.tsx` | New: the card |
| `application/v2_ui/src/components/notifications/WorkflowAlertLiveRegion.tsx` | New: the announcements |
| `application/v2_ui/src/components/notifications/workflowAlertTone.ts` | New: priority colors and icons |
| `application/v2_ui/src/components/ui/Modal.tsx` | A header that replaces the title row, for the card's band |
| `application/v2_ui/src/components/layout/Sidebar.tsx`, `AppShell.tsx`, `NotificationBell.tsx` | The notice's slot under My Workspace, the card and live region, the bell's swing |
| `application/v2_ui/src/App.tsx` | Mounts the runtime, and loads the lab route lazily in development only |
| `application/v2_ui/src/dev/AlertLabPage.tsx`, `alertLabSamples.ts` | New: the alert lab |
| `application/v2_ui/src/pages/workspace/WorkflowsSection.tsx` | Acts on each navigation that names a workflow once, read from the router, so Open workflow works while the list is open |
| `application/v2_ui/vite.config.ts` | Serves `/v2` page loads in development |
| `ui_tests/fixtures/workflow_alerts/` | New: the harness build for the UI suite |
| `ui_tests/fixtures/v2_notification_stubs.py` | Workflow alert answers for Playwright stubs |

## Known limitations

- Claims live in the browser's storage, so an unread alert can pop up once in each
  browser or device where V2 is open. Classic tabs keep their own pop-up, so a user
  with classic and V2 open can see an alert in both.
- The count is polled every 30 seconds, doubling while nothing changes, up to five
  minutes. So in a tab that has been quiet for a while an alert can take up to five
  minutes to appear. Focusing the window or returning to the tab reads it at once.
- Open run arrives with Phase 6b. Ask about this (Phase 6a) is offered for personal
  workflows only, and only while **Use Workflow Results In Chat** is on.
- The card's **Open** button uses `--ok-strong` with `--on-ok`, a green chosen to keep
  its text at 5.5:1 in the light theme and 7.9:1 in the dark theme. **Mark read**,
  shown only when there is nothing to open, pairs `--accent` with `--on-accent` at
  4.49:1 in the light theme, just under 4.5:1. That is a design-token matter shared
  by every V2 primary button.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_workflow_alert_bounded_query.py` | 12 functions | The query is parameterized, limited with `TOP`, and filtered in Cosmos; limits clamp to 1–10; `since_hours` adds a bounded `created_at` window, and the parser accepts whole hours inside the TTL and rejects everything else; the Python re-check and response decoration are unchanged; a query failure still returns an empty list by default and is raised with `raise_on_error`; classic's request and cadence are unchanged; new alerts record their workflow's scope and `workflow_group_id`, never `group_id` |
| `functional_tests/route_tests/test_workflow_alert_since_hours_policy.py` | 8 functions | The route keeps its Blueprint, Swagger and authentication policy; classic's request is unchanged; V2's window is validated and passed through; out-of-range limits fall back as before; invalid windows are refused without reading; a reader failure keeps the existing error shape; through the real reader with a failing Cosmos query, V2's read answers `500` and classic's still answers an empty list |
| `functional_tests/test_v2_alert_lab_excluded_from_build.py` | 4 | The lab's markers exist only in lab code; the reference scanner recognizes every import form; the only reference to the lab is App.tsx's lazy import inside the `import.meta.env.DEV` branch; an existing production build has no file named for the lab and no lab marker (skipped without a build) |
| `functional_tests/test_workflow_priority_alerts.py` | Existing | Classic's workflow alert contract, with the new signature |
| `ui_tests/test_v2_workflow_alert_notices.py` | 29 | Pop-up versus notify-only and the 24-hour window against a server that leaves both filters out; one claim across two tabs of one browser, and a tab opened later; waiting behind a dialog, the bell's panel and a hidden tab; only a successful read retiring an alert, through a failed read on return and a zero count whose confirming read fails; a rise on return read behind a read already on its way; the eight-second tuck, its hover and focus pause, and high and critical staying; storm grouping; every card action; only Close, Show more, Dismiss and the green Open shown up front, with Open going to the created conversation and settling every alert of the entry, and the detail, chips and other actions under Show more; keyboard focus, Escape and the tuck on covering focus; motion with and without reduced motion, including the Web Animations' properties and every `wf-*` keyframe; the rail expanded, collapsed and on a 360 px phone in both themes; text contrast for every priority and category in both themes, with and without reduced transparency; hostile text rendered as text; refused off-site links; and Open workflow's personal, group and unplaceable cases |
| `ui_tests/test_v2_document_provenance.py` | 6 added | Against the real workflows section, personal and group: Open workflow while the list is open expands the run; a second Open workflow for the same run opens it again; running another workflow afterwards doesn't reopen it; a workflow created after the list was read is found with exactly one more list read, which opens its run; a workflow missing from that read too costs one list read per navigation and no more, opens nothing, shows no error and leaves the list usable |

The UI suite mounts the real V2 frame in a harness build, following
`ui_tests/test_v2_notifications_bell.py`. It stubs HTTP with `page.route` and fakes
only page visibility and window focus, so it needs no live data.

## Related

- [V2 Notification Bell and Desktop Notifications](V2_NOTIFICATIONS_BELL.md)
- [Workflow Priority Alerts](WORKFLOW_PRIORITY_ALERTS.md)
- [Workflow Alert Rules](WORKFLOW_ALERT_RULES.md)
- [Chat Orchestration Workflows Roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md), Track N
- [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }})
