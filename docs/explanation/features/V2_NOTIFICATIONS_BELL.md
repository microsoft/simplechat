# V2 Notification Bell and Desktop Notifications (v0.261.194)

## Overview

The V2 interface now shows your notifications and raises a desktop notification
when a reply finishes while you are looking elsewhere. Before this release it did
neither. Classic shows an unread badge on the account menu and lists every notice
on its Notifications page, but V2 had no count and no list, so workflow alerts,
Microsoft 365 approval requests, "AI responded" notices, document processing
results and share requests were invisible unless a V2 user went to the classic
page. The **Desktop notifications** toggle in V2 Preferences saved the preference
the two interfaces share, but nothing in V2 acted on it.

Implemented in version: **0.261.194**, tracked in
`application/single_app/config.py`. Track N1 of the
[chat orchestration workflows roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md)
(#1554, part of #1543).

No setting, route or container is added. V2 uses the existing notification routes
in `route_backend_notifications.py`, the existing administrator setting
`enable_desktop_notifications` and the existing user preference
`desktopNotificationsEnabled`, and it reads them exactly as classic does.

## The bell

V2 has no top bar, so the bell sits in the navigation rail's header beside the
brand mark.

| Rail | What the bell shows |
|---|---|
| Expanded | The unread count as a badge, `1` to `9`, then `9+` |
| Collapsed to the icon strip | A dot, on the row under the brand mark, because there is no room for a number |
| Mobile | The strip's bell with its dot, and the numbered bell once the navigation is opened |

The accessible name always carries the count, for example "Notifications, 3
unread", so a collapsed rail loses nothing for a screen reader. The server caps the
count at 10 (`get_unread_notification_count`), which is why the badge stops at
`9+`.

### How the count stays current

There is no event stream for personal notices, so the count is polled from
`GET /api/notifications/count`. The poller is built to stay cheap:

- It reads the count when V2 starts, whenever the window regains focus and whenever
  the tab becomes visible, because those are the moments someone is about to look.
- While the tab is visible it repeats every 30 seconds, doubling the wait each time
  nothing changed, up to five minutes. A change, a return to the tab, or anything
  you do to your notifications brings it back to 30 seconds. Each wait is
  jittered so several open tabs don't ask in step.
- While the tab is hidden it doesn't poll at all. Browsers throttle hidden-tab
  timers anyway, and nobody is looking at the bell; one read on return catches up.
- A failed read is tried again later, less often. A signed-out answer (401, 403,
  or the sign-in page served in place of JSON) stops polling for the rest of the
  visit rather than asking a page that will never answer.

`subscribeNotificationCount` in `stores/notificationStore.ts` reports every read as
`{ count, previousCount, changed, rose, reason }`. The panel uses `rose` to list a
notice that arrives while it is open. Track N2's workflow-alert pop-ups are meant
to subscribe the same way; this release doesn't add them.

## The panel

Selecting the bell opens a panel with your notices, newest first, 20 at a time
with **Load more**. Each row shows what kind of notice it is, its title, up to
three lines of its message, how long ago it arrived, and **Mark as read** (unread
notices only) and **Dismiss**. **Mark all read** is in the header. The footer link
**Open all in the classic interface** leads to the classic Notifications page,
which adds search and filters.

Read, dismiss and mark all read call `POST /api/notifications/<id>/read`,
`DELETE /api/notifications/<id>/dismiss` and
`POST /api/notifications/mark-all-read`. Each change shows at once and is put back,
with a message, if the server refuses it.

Notification text is untrusted, because a workflow alert or a reply preview can
quote email or web content. Titles and messages are rendered as plain text, never
as HTML or Markdown.

The panel is drawn through a portal so it can extend past the rail, which is 68
pixels wide when collapsed. Escape or a click outside closes it.

### What each notice is labeled

The label comes from the server's `notification_type`, and the icon's color from
the server's own `type_config.color`, so V2 and classic agree on how loud each
notice is. The label always names the kind, so color never carries the meaning
alone.

| Label | Notification types |
|---|---|
| Workflow alert, Workflow run failed | `workflow_priority_alert` |
| Microsoft 365 approval | `m365_approval_*` |
| AI responded | `chat_response_complete` |
| Shared conversation | `collaboration_message_received` |
| Document processed, Document failed, Deletion request | `document_processing_complete`, `document_processing_failed`, `document_deletion_request` |
| Share request, Share approved, Share declined, Share removed | `*_document_share_*` |
| Approval request, Agent template, File approval | `approval_request_*`, `agent_template_*`, `generated_file_approval_*` |
| Content safety | `safety_violation_*` |
| Secret expiring | `key_vault_secret_expiring` |
| Announcement | `system_announcement` |
| Ownership transfer, Group deletion, Group | `ownership_transfer_request`, `group_deletion_request`, other `group_*` |
| Conversation | `conversation_created` |

Anything else is labeled "Notification".

## Where a notice opens

Notification links are written by the server for classic, so most name classic
pages. `lib/notificationLinks.ts` accepts every spelling the classic resolver
accepts and opens the V2 page where V2 has one. A page V2 hasn't rebuilt yet opens
in classic rather than leaving the notice with nowhere to go.

| Link | Opens |
|---|---|
| `/chats`, `/chat` or `/v2/chat` with `conversationId` or `conversation_id` | The conversation in V2 chat |
| The same with `m365_pending_action` | Classic chat, the only page that shows the pending-action card |
| `/approvals` | Classic Approvals |
| `/workflow-activity` | Classic workflow activity (see the Phase 6b seams below) |
| `/workspace` | Your V2 document list; there is no per-document link yet |
| `/group_workspaces` | The notice's group's documents in V2, or the group list |
| `/groups/<id>` | That group's V2 overview |
| `/v2/groups/<id>/documents?document_id=` | That document, only when the group and document match the notice's own context |
| `/public_directory`, `/public_workspaces`, `/public_workspaces/<id>` | The V2 public directory or workspace |
| `/profile`, `/profile?tab=violations` | V2 User Settings, or its Violations tab |
| Any other `/v2/...` path | That V2 route |
| Any other same-site page | That classic page |

Opening a notice marks it read. Before a classic page opens, the notice's group is
made the active group, best effort, as classic does, because classic group pages
act on the active group rather than on one named in their URL.

Some links are refused with a message on the row instead of being followed: a link
to another site, a link carrying credentials or a scheme other than `http` or
`https`, an `/api/` endpoint, and a malformed or mismatched link. Classic follows
an off-site link; V2 deliberately doesn't, since a notice about your own work
never needs to leave the site.

On the chat page, a notice for another conversation opens it in place. A notice for
a conversation that has been deleted, or that you can no longer see, says so and
leaves the open conversation alone.

### The seams for Phase 6b

- **Run pages.** `v2WorkflowRunPath(workflowId, runId)` in `lib/notificationLinks.ts`
  returns the V2 route for a workflow run. It returns `null` until Phase 6b adds the
  run page, so `/workflow-activity` links keep opening classic. Filling it in is
  the whole change needed to move those links, and workflow notices that carry a
  run but no link, into V2.
- **Delivered results.** When 6b posts a result back into a chat, announcing it
  through `announceCompletedReply` in `lib/replyEvents.ts` with
  `source: 'workflow'` raises the desktop notification under the same rules and
  deduplication as a chat reply, and clicking it opens that chat.
- **Undeliverable results.** A notice about a result that couldn't be delivered is
  listed in the panel like any other. If 6b adds a notification type for it, it is
  labeled "Notification" until it is given a label in `describeType` in
  `lib/notifications.ts`.

## Desktop notifications

**User Settings > Preferences > Desktop notifications**, opened from the account
menu at the foot of the rail, now works. It appears only when
an administrator has turned on `enable_desktop_notifications`, and it stores the
same `desktopNotificationsEnabled` preference as the classic profile page, so
turning it off in either interface turns it off in both. A user who never chose is
opted in, as in classic.

A notification is raised when a reply finishes and all of these hold:

- The administrator setting is on and your preference isn't off.
- Your preferences have loaded. V2 loads them after the page, and until they have
  loaded, or if they failed to, your choice is unknown and treated as off. This is
  stricter than classic, which has the preference before the page runs.
- The tab is hidden or the window doesn't have focus.
- The safety filter didn't replace the reply.
- The browser has granted permission.
- No notification was already raised for this reply. Replies are recognized by
  message ID, then orchestration run ID, then conversation.

The notification shows the application title and the conversation's title, never
the reply, so nothing from the conversation appears on a lock screen. It uses the
same `simplechat-conversation-<id>` tag as classic, so the system replaces an older
notice for the same conversation rather than stacking them. Clicking it opens that
conversation and brings the window forward.

Ordinary chat replies notify, and so do orchestrated answers that complete. A plan
waiting for approval, a failed or stopped run, and a run picked up again after a
reload don't. Notifications come from the reply's own completion event, not from a
timer, so hidden-tab timer throttling doesn't delay them. The unread-count poller
never raises one.

### Asking for permission

Browsers show their permission prompt only in response to a click or key press.
V2 asks:

- When you send a message, if the browser hasn't been asked yet and notifications
  are on. It asks once per page, as classic does.
- When you turn the preference on, in the same click.
- When you select **Allow notifications**, which appears under the preference
  while it is on and the browser is undecided.

When the browser can't notify, the preference says why: the browser is blocking
notifications for the site, or it doesn't support them.

## "AI responded" notices and read receipts

When a personal conversation finishes a reply, the server marks it unread and
creates an "AI responded" notice. A read receipt
(`POST /api/conversations/<id>/mark-read`) clears both. V2 already sent one when
you opened an unread conversation, but not for a reply that finished while its
conversation was open, so with a bell the count would have included replies you
had just watched arrive. Now:

- A reply you watch finish, with the tab visible and the chat page showing, is
  read at once, and its notice leaves the bell.
- A reply that finishes while the tab is hidden or another V2 page is showing
  stays unread, and its notice stays in the bell, until you come back to that
  conversation. Returning through a link, whether from the panel, a desktop
  notification or the address bar, counts as coming back to the conversation it
  names.
- A reply that finishes in a conversation you have already left stays unread
  until you open it.

Group and public conversations aren't marked unread by the server, and shared
conversations keep their own read tracking, so neither is affected.

## Files

| File | Change |
|---|---|
| `application/v2_ui/src/components/layout/NotificationBell.tsx` | New: the bell, its badge and dot |
| `application/v2_ui/src/components/layout/NotificationPanel.tsx` | New: the panel |
| `application/v2_ui/src/components/layout/Sidebar.tsx` | The bell in the rail's header, and under the brand mark when collapsed |
| `application/v2_ui/src/lib/notifications.ts` | New: the route calls, normalization and labels |
| `application/v2_ui/src/stores/notificationStore.ts` | New: the count, poller, list and actions, and `subscribeNotificationCount` |
| `application/v2_ui/src/lib/notificationLinks.ts` | New: link resolution and `v2WorkflowRunPath` |
| `application/v2_ui/src/lib/notificationNavigation.ts` | New: following a link, shared by the panel and desktop notifications |
| `application/v2_ui/src/lib/desktopNotifications.ts` | New: gating, permission and the notification itself |
| `application/v2_ui/src/lib/replyEvents.ts` | New: the "reply finished" signal chat and orchestration both send |
| `application/v2_ui/src/lib/appNavigation.ts`, `lib/useNotificationRuntime.ts` | New: start the poller and the reply listener once a session has loaded, and let code outside React follow a route |
| `application/v2_ui/src/App.tsx` | Mounts the notification runtime |
| `application/v2_ui/src/stores/chatStore.ts` | Announces finished replies and defers read receipts |
| `application/v2_ui/src/lib/orchestrationController.ts` | Announces completed runs |
| `application/v2_ui/src/components/chat/Composer.tsx` | Asks for permission on send |
| `application/v2_ui/src/components/settings/PreferencesTab.tsx` | The working preference and its permission status |
| `ui_tests/fixtures/v2_notification_stubs.py` | New: the count and read-receipt answers other V2 suites now need, since every page shows the bell |
| `ui_tests/fixtures/v2_admin_settings.py`, `workspace_authoring.py`, `group_documents.py`, `group_document_management.py` | Answer or permit those requests in the existing V2 suites |
| `ui_tests/fixtures/notification_bell/` | New: the harness build for the UI suite |

## Known limitations

- Microsoft 365 approvals, pending Microsoft 365 actions and workflow activity open
  in classic until V2 has those pages.
- A personal document notice opens your document list, not the document.
- The count is polled. While the tab is visible and nothing is changing, a new
  notice can take up to five minutes to appear; returning to the tab reads it at
  once.
- Desktop notifications come only from an open V2 tab that is following the reply,
  as in classic. A reply that finishes after the tab is closed is found in the
  bell.
- Notices assigned to a role are listed in the panel but not counted in the badge,
  because `get_unread_notification_count` doesn't pass the user's roles. Classic
  behaves the same way; the server is unchanged here.
- Creating an image from a reference in the image editor doesn't ask for
  permission. Its reply still notifies once permission has been granted from a
  send or from Preferences.
- V2 doesn't play the completion sound (`enable_chat_completion_audio_cues`), and
  doesn't use `GET /api/notifications/chat-completions`, which exists for that
  sound.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_v2_notifications_bell.py` | 9 | The client's routes, methods, page size and count cap against the server; the administrator setting and preference reaching V2 through the bootstrap and settings sanitizer; the gating rules against classic's; permission asked only from a click or key press; the runtime starting once; the N2 and Phase 6b seams; no HTML sinks and same-site links only |
| `functional_tests/test_desktop_notification_settings.py` | Existing | Classic's desktop notifications, unchanged |
| `ui_tests/test_v2_notifications_bell.py` | 37 | The bell and panel with the rail expanded, collapsed and on mobile; read, dismiss and mark all read, including refused changes; every link kind, refused links and a deleted conversation; backoff, hidden-tab rest, retry and sign-out; read receipts for watched, hidden, other-page and left-behind replies; desktop notifications with the Notification API stubbed, including once per reply, the lock-screen text, the click, permission on send, Enter and the preference, and each reason a browser can't notify |

The UI suite runs the real V2 components in a harness build with `page.route`
stubs, following `ui_tests/test_v2_elicitation_composer.py`, and needs no live
data.

## Related

- [Desktop Conversation Notifications](DESKTOP_CONVERSATION_NOTIFICATIONS.md)
- [Chat Orchestration Workflows Roadmap](CHAT_ORCHESTRATION_WORKFLOWS_ROADMAP.md), Track N
- [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
