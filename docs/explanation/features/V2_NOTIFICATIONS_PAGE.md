# V2 Notifications Page (v0.261.448)

## Overview

V2 now has a full Notifications page at `/v2/notifications`, with an **All**,
**Unread** and **Read** filter, a search box, numbered pages and a page size you
choose once and keep. Until this release V2 had only the bell's panel, which lists
the newest notices 20 at a time and has no way to find last week's, so its footer
sent you to the classic page.

Implemented in version: **0.261.448**, tracked in
`application/single_app/config.py`. Phase 1 of the
[V2 classic page parity](V2_CLASSIC_PAGE_PARITY.md) plan.

The page reads and changes the same notification documents as classic and the
bell, through the same routes, so a notice you read, dismiss or acknowledge here is
read, dismissed or acknowledged everywhere. No setting, route or container is
added. `GET /api/notifications` gains two optional parameters, `status` and `q`.

Dependencies: [V2 Notification Bell and Desktop Notifications](V2_NOTIFICATIONS_BELL.md)
(the count, the link resolver and the panel), `route_backend_notifications.py`,
`functions_notifications.py`, and the per-user `notifications_per_page` setting.

### Why the server filters

Classic fetches one page and then filters and searches what it fetched. Its **Read**
filter and its search therefore see only the notices on the page in front of you,
while its page numbers still count every notice, so a search can show an empty page
with page links beneath it. V2 sends the filter and the search to the server
with the page it wants. The server applies them before it cuts the list into pages,
so "Showing 21–40 of 45 notifications" and the page numbers describe what matched.

## What the page does

| Control | What it does |
|---|---|
| **All**, **Unread**, **Read** | Lists every notice, only the unread ones, or only the read ones. Choosing one returns to page 1. |
| **Search notifications** | Lists notices whose title or message contains what you typed, ignoring case. It waits 400 ms after you stop typing, and Enter searches at once. **Clear search** empties it. Only the first 100 characters count, and the box stops at 100. |
| **Per page** | 10, 20 or 50. The choice is saved and is where the page starts next time. |
| **Mark all read** | Marks every unread notice read, not only the ones on screen. It is unavailable while the request is on its way and when nothing is unread, and keeps keyboard focus either way. |
| **Refresh** | Reads the current view again. It is unavailable, and marked busy, while it reads, and keeps keyboard focus. |
| Pager | **Previous**, **Next** and numbered pages, with "Page 2 of 4" beside them. A long list shows the first and last page, the pages around the current one, and gaps. It is hidden when everything fits on one page. **Previous** on the first page and **Next** on the last are unavailable. |

Under the controls, one sentence says what the list shows, for example "Showing
11–20 of 35 unread notifications matching your search." It is a polite live region,
so a screen reader hears the result of a filter or a search without losing its place,
and it stays quiet while a new view is still loading. After **Mark all read** it adds
"No unread notifications.", the sentence an empty **Unread** list already uses, because
a list of every notification would not otherwise say so. It is dropped the next time
the list is read, and left out where the sentence already says it.

Each notice shows what kind it is, its title and its whole message (the panel cuts a
message at three lines), how long ago it arrived, and the same actions as the panel:

- Selecting the title opens what the notice points to, using the link resolver the
  bell uses, and marks the notice read. A workflow alert that needs acknowledgment is
  acknowledged instead, because opening it is a response to it.
- **Mark as read**, for unread notices.
- **Dismiss**.
- **Acknowledge**, beside the others, for a workflow alert that needs it. Marking such
  an alert read or dismissing it leaves it waiting, as it does in the bell.

A notice whose link leaves the site, or can't be checked, says so on its row instead
of opening, exactly as in the panel.

After any of these the page reads its view again, so what is listed is what the
server has. In the **Unread** view a notice you read leaves the list and the next one
takes its place. If you dismiss the last notice on the last page, the page moves back
to the last page that still has notices. When the button you pressed goes away with
its row, focus moves to the row's next control or, failing that, to the list.

### When the list can't be shown

- While the first read is on its way, four placeholder rows are drawn.
- An empty list says why: "You're all caught up" for no notices at all, "No unread
  notifications" or "No read notifications" for a filter, and "No notifications match
  your search" with a **Clear search** button for a search.
- A failed read shows "Your notifications could not be loaded. Try again." with a
  **Try again** button. If a read fails while a list is on screen, the list stays,
  marked "What is shown may be out of date." The button goes while the new read is on
  its way, so keyboard focus waits on the list of notifications, and it returns to
  **Try again** if the read fails again.

## The address

The view is kept in the address, so Back, a bookmark and a shared link reopen it.

| Parameter | Values | Default |
|---|---|---|
| `status` | `all`, `unread`, `read` | `all` |
| `q` | Up to 100 characters | No search |
| `page` | A whole number from 1 | 1 |
| `per_page` | `10`, `20` or `50` | Your saved size, else 20 |

Only values that differ from the defaults are written, in that order, so a plain
`/v2/notifications` stays plain. The page is lenient in what it reads: an unknown
`status`, a `per_page` the server doesn't offer, or a `page` that isn't a whole
number falls back to its default instead of stranding you on a request the server
would refuse. A `page` past the end opens the last page that exists.

Choosing a filter, a page or a size adds a history entry. Typing a search replaces
the current entry instead, so Back leaves the page rather than undoing a letter.

### Page size

The page starts from, in order, a `per_page` in the address, the `notifications_per_page`
saved with your user settings (the same value classic's selector uses), and 20. The
first read waits for your settings to arrive, so the list isn't read at 20 and then
again at your size. A `per_page` in the address wins for the visit and saves nothing.

Choosing a size posts `{ "notifications_per_page": <size> }` to
`POST /api/notifications/settings` and updates the preferences V2 already holds. It
doesn't use `/api/user/settings`, which doesn't accept this key. If the save fails
the size still applies for the visit and a message says it wasn't kept.

## Where it is linked from

- **View all notifications**, the footer of the bell's panel, replaces "Open all in
  the classic interface". It is a link inside the application and closes the panel.
- **Notifications** is the first entry of the account menu at the foot of the rail,
  with an unread badge that reads the bell's count (`1` to `9`, then `9+`). Its
  accessible name carries the count, for example "Notifications, 3 unread". On a
  phone the same menu is in the navigation drawer.
- A notice's classic `/notifications` link, and the `/notifications` shortcut in
  the latest-features catalogue, open this page. `status`, `q`, `page` and `per_page`
  in such a link are kept, rewritten in their canonical form; nothing else is.

## API

`GET /api/notifications` keeps `page`, `per_page` (10, 20 or 50, else 20),
`include_read` and `include_dismissed`, and adds:

| Parameter | Meaning |
|---|---|
| `status` | `all`, `unread` or `read`, in any letter case. Blank means `all`. Any other value is refused with `400` and `{"success": false, "error": "Invalid status. Use all, unread or read."}`, because listing everything under a filter that was meant to hide notices would be worse than an error. |
| `q` | Text the title or message must contain, ignoring case. Blank matches everything; longer text is cut to its first 100 characters. |

Both narrow the list before it is paged, so `total` and `has_more` describe the
filtered list. The classic page sends neither and is answered exactly as before.

`get_user_notifications` in `functions_notifications.py` takes the same two values as
`read_status` and `search`. It reads the same notifications it always did, filters
them in memory, and never puts the search text in a Cosmos query. The search is
matched against the title and message as the signed-in user is shown them, so a team
alert that is reduced for a group member can't be found by the text it hides. The
unread and read filters use the reader's own read state, including for a team alert.

## How the page stays current

The page keeps its own list, read for one view at a time, instead of using the
bell's list, which only grows and is meant for a panel. An answer is kept with the
view it was for, so a slow answer to an earlier filter or search is never shown
under a later one, and a read in flight is cancelled when the view changes.

The bell's count stays in the notification store. The page reads the count when it
opens and after every change it makes, and when the store's poller reports that the
count rose, which means something new arrived, the page reads its view again. A
notice that arrives while you are on another page of the list therefore shows up
without a click.

Notification text is untrusted, because a workflow alert or a reply preview can
quote email or web content. Titles, messages and the search box are plain text
throughout, and the search is sent as plain text and never interpreted.

## Phones and accessibility

- Controls have a 44 px minimum height on a phone. The filter, the search and the
  page size wrap when there is no room for them side by side, and a long unbroken
  title or message wraps rather than scrolling the page sideways.
- The filter is a labelled group of buttons that use `aria-pressed`. The search and
  the page size have screen-reader labels. The pager is a labelled navigation
  landmark and marks the current page with `aria-current="page"`.
- Keyboard focus stays on the control you pressed. A browser takes focus from a button
  that becomes disabled and leaves it at the top of the page, so the controls that can
  become unavailable are marked `aria-disabled` instead. They stay in the tab order,
  announce as unavailable, and do nothing when pressed:
  - **Previous** on the first page and **Next** on the last. Moving to another page,
    from a numbered button or from **Previous** and **Next**, leaves focus on the
    button used, so the keyboard can go on from where it was.
  - **Refresh** while it reads, which it also reports with `aria-busy`.
  - **Mark all read** while it is being sent, and when nothing is unread.
- Where a control goes away with what it acted on, focus is moved deliberately. A row's
  button goes to the row's next control or to the list, and **Try again** goes to the
  list while the new read is on its way, then back to the button if the read fails
  again. The list is a region named "Your notifications" that can hold focus.
- The results region reports `aria-busy` while it loads.

## Files

| File | Change |
|---|---|
| `application/single_app/functions_notifications.py` | `get_user_notifications` takes `read_status` and `search`, with `parse_notification_read_status` and `normalize_notification_search` |
| `application/single_app/route_backend_notifications.py` | `api_get_notifications` reads and validates `status` and `q` |
| `application/v2_ui/src/pages/NotificationsPage.tsx` | New: the page |
| `application/v2_ui/src/components/notifications/NotificationsHeader.tsx` | New: the page's header, drawn here rather than through `PageHeader`, whose actions become natively disabled while they are busy, which drops keyboard focus. The markup and classes are the shared header's; Refresh and Mark all read use `aria-disabled` |
| `application/v2_ui/src/lib/notificationsPage.ts` | New: reading and writing the address, page arithmetic and wording, free of React so Node can run it |
| `application/v2_ui/src/lib/useNotificationsList.ts` | New: the page's own list. `reload` resolves with the answer it read |
| `application/v2_ui/src/components/notifications/NotificationRow.tsx` | New: the row, moved out of the panel and shared with it |
| `application/v2_ui/src/components/notifications/NotificationsPager.tsx` | New: the pager, whose end stops are `aria-disabled` |
| `application/v2_ui/src/lib/notifications.ts` | `fetchNotificationPage` takes a status, a search and a page size and returns `total` and `perPage`; `saveNotificationsPerPage` |
| `application/v2_ui/src/components/layout/NotificationPanel.tsx` | Uses the shared row; the footer link |
| `application/v2_ui/src/components/layout/Sidebar.tsx` | The account menu's **Notifications** entry and badge |
| `application/v2_ui/src/App.tsx` | The `/notifications` route |
| `application/v2_ui/src/lib/notificationLinks.ts`, `lib/latestFeatureShortcuts.ts` | A classic `/notifications` link opens the V2 page |
| `functional_tests/cosmos_response_boundaries.json` | The reviewed hashes for `functions_notifications.py`, which changed |
| `ui_tests/fixtures/notifications_page/` | New: the harness build for the UI suite |

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_notifications_status_and_search_filters.py` | 29 | `get_user_notifications` against a fake Cosmos container: each filter, search in the title and in the message, both together, totals and `has_more` across pages, dismissed notices left out, blank and over-long searches, a team alert's hidden text, the unchanged default list, and the route's validation (a bad `status` is a 400, a bad `per_page` becomes 20, the search is cut at 100 characters) |
| `functional_tests/test_v2_notifications_page.py` | 10 | The route and both entry points, the client's parameters against the server's, `notificationsPage.ts` run under Node, the link resolvers (including that `//host`, `/api/` and off-site links stay refused), the page owning its list while sharing the row, no HTML sinks, that the pager and the header actions are never natively disabled, and the classic page's request unchanged |
| `ui_tests/test_v2_notifications_page.py` | 55 | The real page in a harness build with `page.route` stubs: each filter, search and its debounce, totals and pages, page size and its saving, every row action, mark all read, refusals, empty, failed and slow states, the bell and account-menu entries, a 390 px layout, tab order, the live region, and text that looks like markup. Keyboard focus, at desktop width and at 390 px: Enter on **Next** to the last page and **Previous** to the first, on a numbered page as the window of numbers moves, on **Refresh** while it reads, on **Mark all read** while it is sent, when it leaves nothing unread and when it is refused, and on **Try again** |
| `ui_tests/test_v2_notifications_bell.py` | Existing | The panel's footer link and the `/notifications` link rows |

## Known limitations

- Each read still loads the signed-in user's notifications from the same four
  sources and filters them in memory, as the unfiltered list always did. A very
  large inbox costs the same per page whether or not it is filtered.
- The search is a case-insensitive substring match on the title and message. It
  doesn't match the notice's type label or its link.
- Notices assigned to a role are listed but not counted in the bell's badge, because
  `get_unread_notification_count` doesn't pass the user's roles. Classic behaves the
  same way.
- A change made in another tab appears here when the page next reads its view,
  through **Refresh**, a rise in the bell's count, or a change of page.

## Related

- [V2 Notification Bell and Desktop Notifications](V2_NOTIFICATIONS_BELL.md)
- [V2 Workflow Alert Notices](V2_WORKFLOW_ALERT_NOTICES.md)
- [V2 Classic Page Parity](V2_CLASSIC_PAGE_PARITY.md)
- [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }})
