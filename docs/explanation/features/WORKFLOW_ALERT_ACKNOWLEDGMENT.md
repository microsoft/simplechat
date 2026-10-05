# Workflow Alert Acknowledgment, Sounds, Sizes and Team Delivery (v0.261.235)

## Overview

A workflow alert used to pop up once and then wait, unread, in the notification bell.
V2 recorded each alert as shown in `localStorage` for 25 hours and classic recorded it in
the tab's `sessionStorage`, so after a refresh the pop-up didn't come back, and V2 also
skipped alerts older than 24 hours. A group workflow's alert reached only the workflow's
owner, and nothing made a sound.

That's fine for a nightly digest, but not for an operations center, where an alert has to
stay in front of the team, keep sounding until someone takes it on, and show who did. Each
alert rule can now:

- **require acknowledgment**, so the alert keeps coming back on every page load, tab and
  device until someone acknowledges it;
- **play a sound**, once, or every five seconds until the alert is acknowledged;
- choose a **size**: small (the usual pop-up), medium (the full alert opens straight away)
  or large (full screen);
- in a group workflow, alert **everyone in the group**, with one acknowledgment that clears
  the alert for all of them.

Implemented in version: **0.261.235**, tracked in `application/single_app/config.py`.
Issue: [#1634](https://github.com/microsoft/simplechat/issues/1634).

Dependencies:

- [Workflow Alert Rules](WORKFLOW_ALERT_RULES.md), which decide whether a run alerts and how loudly.
- [V2 Workflow Alert Notices](V2_WORKFLOW_ALERT_NOTICES.md) and the classic alert modal
  ([Workflow Priority Alerts](WORKFLOW_PRIORITY_ALERTS.md)), which show alerts.
- [V2 Workflow Alert Editing](V2_WORKFLOW_ALERT_EDITING.md) and the classic workflow editor.

## The rule options

| Option | Values | Notes |
|---|---|---|
| Require acknowledgment | Off (default), on | The rule must pop up |
| Sound | Off (default), Play once, Repeat until acknowledged | The rule must pop up; repeating needs acknowledgment |
| Size | Small (default), Medium, Large (full screen) | The rule must pop up |
| Who gets it | Workflow owner (default), Everyone in the group | Group workflows only; also works for bell-only rules |

Rules store an option only when it isn't the default, so rules saved before this release keep
their exact shape. The "On every run" mode has no options.

When several rules match one run, severity, category and delivery still come from the
highest-severity rule. Each option instead takes the **strongest value any matched rule asked
for**: one rule requiring acknowledgment makes the alert require it, and the loudest sound, the
largest size and the widest audience apply. An option that only makes sense as a pop-up forces
the delivery to pop-up.

For the same reason, a model-evaluated rule is no longer skipped just because a deterministic
rule already matched at a higher severity. It is still sent to the model when it asks for an
option the matches don't already give. Otherwise a failed run that also met that rule would get
a weaker alert than a completed one.

### Validation

`normalize_alert_rule` in `functions_workflow_alerts.py` checks, after the existing checks and
in this order, and answers with these reviewed messages (`{n}` is the rule's position):

1. "Alert rule {n} sound must be off, once or repeat."
2. "Alert rule {n} size must be small, medium or large."
3. "Alert rule {n} audience must be owner or group."
4. "Alert rule {n} can alert the whole group only in a group workflow."
5. "Alert rule {n} must pop up to require acknowledgment, play a sound or change its size."
   This covers a delivery of **Notification bell only**, and **Default for severity** with an
   info or low severity.
6. "Alert rule {n} can repeat its sound only when it requires acknowledgment."

`normalize_workflow_alert_settings` takes a `workflow_scope` (`personal` or `group`), passed by
both save paths, for check 4. Stored rules that weren't sent with the request are carried over
without that check, as their task references already are. The acknowledgment flag is read the
way `enabled` always has been: the strings `1`, `true`, `yes` and `on` mean on.

The V2 editor (`workflowAlertErrors` in `lib/workflowAlerts.ts`) mirrors these checks word for
word, and `functional_tests/test_workflow_alert_client_parity.py` runs it against the real
normalizer. The classic editor shows the server's message on save.

## Who receives an alert

An owner-audience alert is personal to the workflow's owner, as before.

When any matched rule asks for the group in a group workflow, the runner
(`_create_workflow_priority_alert`) creates **one group-scoped alert** for that group instead,
through `create_workflow_priority_notification(..., group_id=...)`. It records the owner in
`metadata.owner_user_id`. A rule can't save a group audience in a personal workflow. If one
reaches the runner anyway, the runner logs a warning and alerts the owner instead.

### What members see

A team alert is built from the owner's side of the run. Its summary and detail can quote
conversations and actions in the owner's own space, and its links include the owner's workflow
conversation and private conversations, which members can't open. So `_decorate_workflow_alert`
gives every reader except the owner a simpler alert, in the bell list and in the pop-up read
alike. It tells them there is an alert, how severe it is, and offers **Open** to what the run
created in the group. The run's output stays in the group's workflow run history, under that
history's own access rules. The simpler alert keeps and drops these:

| Kept | Removed or rebuilt |
|---|---|
| Severity, category, delivery, the pop-up options | Title, rebuilt as "*Priority* priority workflow alert: *workflow*" |
| Workflow name and id, scope, group, run id, run status, trigger, runner | Message, rebuilt as "Matched *rule names*. Open it for details." |
| Matched rules' ids, names, severities and condition types | Rule reasons, summary, detail, response preview, error, event and alert titles, enrichments, agent names |
| Links to group conversations the run created in this group | The owner's workflow conversation, personal conversations, other groups' links |

Every reader gets only their own read and dismissed state, never other members' ids. Responses
say which view they carry in `content_scope` (`full` or `member`). A team alert without a recorded
owner is reduced for everyone.

## Acknowledgment

These acknowledge a must-acknowledge alert: the **Acknowledge** button, and **Open** on the alert
itself. Opening an alert is a deliberate response to it.

These never acknowledge: closing it, Escape, the backdrop, a refresh, Mark read, Dismiss, and
**Mark all read**, whether in the bell or on the alert.

`POST /api/notifications/<notification_id>/acknowledge` (`acknowledge_workflow_alert` in
`functions_notifications.py`):

- Only a recipient can acknowledge: the owner of a personal alert, or a **current** member of a
  team alert's group. Membership is checked with `assert_group_role` and every group workflow
  member role. Anyone else gets `404`, so the answer never confirms an alert they can't see.
- An alert that doesn't need acknowledgment gets `400`.
- It records `acknowledged_at` and `acknowledged_by` (`user_id` and display name), and marks the
  alert read for the caller. One acknowledgment clears a team alert for every member. Each
  member's bell entry stays unread for them, and reads "Acknowledged by *name* at *time*".
- **The first acknowledgment wins.** The write is conditional on the alert's ETag and retried on
  a conflict. A later or losing acknowledgment answers `200` with `already_acknowledged: true`
  and the first acknowledger.

A shared alert is written by many members, so `mark_notification_read` and
`dismiss_notification` now make the same ETag-conditional write (`_write_notification_change`).
Before, they upserted the copy they had read. A member marking a team alert read with a copy
from before someone's acknowledgment would have erased that acknowledgment, and two members
reading at once could drop one read.

### Reading alerts that should pop up

`GET /api/notifications/workflow-alerts` now uses `get_workflow_alert_popups`. It makes four
bounded reads, each capped at `limit`:

1. the user's unread pop-up alerts (unchanged, `get_unread_workflow_priority_notifications`);
2. the user's must-acknowledge alerts nobody has acknowledged, **whatever their age or the
   user's read or dismissed state**;
3. unread pop-up team alerts from the groups the user belongs to now;
4. unacknowledged must-acknowledge team alerts from those groups.

Must-acknowledge alerts have reads of their own, so newer alerts can't crowd them out of `TOP`.
`since_hours` narrows only the unread reads. Group ids come from the server (`get_user_groups`),
never from the request, and the group reads are one cross-partition query each. The response
adds:

- `complete`: false when any read came back full, so V2 no longer infers completeness from the
  list's length;
- `sounds_enabled`: the administrator's setting.

Every workflow alert, here and in `GET /api/notifications`, carries top-level
`require_acknowledgment`, `sound`, `size`, `audience`, `acknowledged`, `acknowledged_at`,
`acknowledged_by_name` and `content_scope`.

## How an alert appears

| Size | V2 | Classic |
|---|---|---|
| Small | The notice under **My Workspace**, which opens into the full alert | The usual centered dialog |
| Medium | The full alert opens straight away, in a wider dialog | A wider dialog (`modal-lg`) with larger type |
| Large | A full-screen takeover with large type and the severity band | A full-screen dialog (`modal-fullscreen`) |

V2 still waits for the page to be free, with no other dialog open, before it opens a medium or
large alert.

A must-acknowledge alert:

- comes back after a refresh, in every tab and on every device, and is never tucked into the bell.
  V2 skips its one-tab claim and its 24-hour window, and classic doesn't record it as shown;
- comes first. V2 puts alerts that need acknowledgment ahead of every other alert, whatever their
  severity, because they are the ones that won't go away and may be sounding;
- shrinks to a persistent notice when it is closed or Escape is pressed. In V2 the notice has no
  close button and doesn't time out. In the full rail it takes its own room below
  **My Workspace**, pushing the items under it down, rather than covering them as an ordinary
  notice does for a few seconds. As a flyout beside the collapsed rail it steps aside, invisible,
  when focus moves onto something it covers, and comes back when focus moves on. A new alert that
  takes the lead is shown whatever focus did before it arrived. Classic keeps a slim
  banner at the bottom of the page, "*N* workflow alerts need acknowledgment", with **Review**;
- shows **Acknowledge** in place of **Dismiss**, or in place of **Mark read** when there is nothing
  to open. With somewhere to open, **Open** stays the one green button, since it acknowledges too.
  Opening one alert acknowledges that one only: any other alert that needs acknowledgment stays,
  in the notice, and keeps sounding;
- can be acknowledged from the bell, where opening its row acknowledges it as well. Marking it read
  or dismissing it there leaves it waiting;
- disappears from every other tab of the browser at once, through the `BroadcastChannel`
  `simplechat.workflowAlerts` that classic and V2 share. Other devices and teammates notice when
  they next check: V2 re-checks every 20 seconds while such an alert is waiting, even in a
  background tab, and classic checks every 20 to 40 seconds.

A team alert says it was sent to everyone in the group.

## Sound

Three tones were synthesized for SimpleChat by `scripts/generate_workflow_alert_sounds.py`. It
uses only the Python standard library and is deterministic. The tones are served locally from
`static/audio/workflow-alerts/`:

| File | Severities |
|---|---|
| `chime.wav` | Info, low |
| `urgent.wav` | Medium, high |
| `alarm.wav` | Critical |

- **Play once** chimes once per browser: when the alert is shown, or for a must-acknowledge alert,
  when the browser first receives it. Alerts that arrive together chime once, in the tone of the
  loudest of them. The browser records each chime in `localStorage`
  (`simplechat.workflowAlerts.soundedOnce`, kept 25 hours, at most 500 alerts), checked and
  written while holding the lock, so another tab, classic or V2, doesn't chime again for the same
  alert, and neither does a reload. A chime never plays over a repeating sound.
- **Repeat until acknowledged** sounds every five seconds (`WORKFLOW_ALERT_SOUND_REPEAT_MS`). One
  loop sounds for every alert that repeats, in the tone of the loudest, until the last one is
  acknowledged. Acknowledging one leaves the loop going for the rest, in the next one's tone.
- A must-acknowledge alert starts sounding as soon as the browser receives it, even if the tab is
  in the background or a dialog holds the visual back. It stops as soon as it is acknowledged,
  here, in another tab, on another device or by a teammate, even if it was never shown.
- Only one tab per browser plays, the one holding the Web Lock `simplechat.workflowAlertSound`.
  Classic and V2 share the lock, so a classic tab and a V2 tab don't sound together. A tab whose
  sound the browser refuses gives the lock up, so a tab that may play takes over.
- Sound plays only when all of these allow it: the rule's sound, the administrator's **Enable
  Workflow Alert Sounds** (`enable_workflow_alert_sounds`, on by default), and the device's **Play
  alert sounds** switch.
- Sound is never the only signal. The alert is always shown as well.

### When the browser blocks sound

Browsers don't play sound on a page nobody has clicked or typed in since it loaded. When that
happens the alert shows **Enable sound**, and the next click or key press anywhere on the page
tries the sound again. **Enable sound** stays until a sound actually plays, so it doesn't vanish
under the pointer or flicker while the browser still refuses. A refused sound is dropped, not
retried, once its alert is acknowledged or closed.

A wall display that reloads unattended can allow SimpleChat to play sound without a click, through
the browser's enterprise policy. In Microsoft Edge and Google Chrome, add the SimpleChat site to
**Allow media autoplay on specific sites** (`AutoplayAllowlist`).

## Settings

| Setting | Where | Default | Effect |
|---|---|---|---|
| Enable Workflow Alert Sounds (`enable_workflow_alert_sounds`) | Admin Settings, Workflow | On | Off silences every workflow alert sound for everyone. Alerts still pop up and still need acknowledgment. Sent to V2 in the bootstrap and with each alerts read |
| Play alert sounds | V2 Preferences ("Workflow alerts on this device"), and the classic Profile settings | On | Per browser (`localStorage` `simplechat.workflowAlerts.playSounds`), shared by classic and V2 |
| Alert monitor | V2 Preferences ("Workflow alerts on this device") | Off | Per browser (`localStorage` `simplechat.workflowAlerts.monitor`). V2 checks every 30 seconds without backing off, even in a background tab, for operations screens |

Without the monitor, V2 checks every 30 seconds, backs off to five minutes while nothing changes,
and doesn't check while the tab is hidden.

## Files

| File | Change |
|---|---|
| `application/single_app/functions_workflow_alerts.py` | Rule options, validation, scope, strongest-option merge, forced pop-up |
| `application/single_app/functions_personal_workflows.py`, `functions_group_workflows.py` | Pass the workflow scope to the normalizer |
| `application/single_app/functions_workflow_runner.py` | Options on the alert and run decision; one group-scoped alert for a group audience |
| `application/single_app/functions_notifications.py` | Group-scoped creation, member reduction, the four-read pop-up query, acknowledgment, ETag-conditional read and dismiss |
| `application/single_app/route_backend_notifications.py` | The acknowledge route; `complete` and `sounds_enabled` |
| `application/single_app/functions_workflow_activity.py` | The options in activity's rule list |
| `application/single_app/functions_settings.py`, `admin_settings_fields.py`, `route_frontend_admin_settings.py`, `templates/admin/_panes/workflow.html`, `route_backend_v2.py` | `enable_workflow_alert_sounds` |
| `scripts/generate_workflow_alert_sounds.py`, `static/audio/workflow-alerts/*.wav` | The tones |
| `application/v2_ui/src/lib/workflowAlerts.ts`, `components/workflows/WorkflowAlertEditor.tsx`, `WorkflowAlertSummary.tsx`, `WorkflowEditorDialog.tsx`, `lib/workflowEditor.ts` | V2 editor and validation mirror |
| `application/v2_ui/src/lib/workflowAlertNotices.ts`, `lib/notifications.ts` | V2: the new fields, eligibility of alerts that need acknowledgment, the server's `complete` flag |
| `application/v2_ui/src/stores/workflowAlertStore.ts`, `lib/workflowAlertActions.ts` | V2: acknowledging, minimizing instead of tucking, Open acknowledging and leaving other pending alerts up, Mark all read skipping, never re-presenting an acknowledged alert, the shared channel |
| `application/v2_ui/src/lib/workflowAlertSound.ts`, `lib/workflowAlertDevicePreferences.ts` | New: V2 sound player, which follows the alerts the store holds, and the per-device switches |
| `application/v2_ui/src/lib/useWorkflowAlertRuntime.ts`, `stores/notificationStore.ts` | V2: re-reading every 20 seconds while an alert waits for acknowledgment, the Alert monitor, the bell no longer retiring an alert that was only read |
| `application/v2_ui/src/components/notifications/WorkflowAlertNotice.tsx`, `.css`, `WorkflowAlertCard.tsx`, `components/ui/Modal.tsx` | V2: the tags, Acknowledge, Enable sound, the notice taking its own room in the rail and stepping aside as a flyout, sizes and the `full` dialog size |
| `application/v2_ui/src/components/layout/NotificationPanel.tsx`, `components/settings/PreferencesTab.tsx` | V2: the bell's Acknowledge and "Acknowledged by", and "Workflow alerts on this device" |
| `application/v2_ui/src/dev/AlertLabPage.tsx`, `alertLabSamples.ts` | Alert lab scenarios for each size, sound, blocked audio, a member's view and acknowledgment elsewhere |
| `application/single_app/static/js/workspace/workspace_workflows.js`, `templates/workspace.html`, `templates/group_workspaces.html` | Classic editor |
| `application/single_app/static/js/workflow-alert-sound.js` | New: the classic sound player, with one repeating loop, the shared lock and "sounded once" record, and the gates |
| `application/single_app/static/js/notifications.js`, `templates/base.html` | Classic alert dialog: re-showing, Acknowledge, the banner, sizes, the team line, the shared channel, and the notifications page's Acknowledge and "Acknowledged by" |
| `application/single_app/templates/profile.html` | Classic per-device sound switch |

## Testing and validation

| Suite | Covers |
|---|---|
| `functional_tests/test_workflow_alert_acknowledgment.py` | Every option and reviewed message, the strongest-option merge, model-evaluated rules still sent when they ask for a stronger option, the runner's group alert and fallback, acknowledgment authorization (owner, member, non-member, deleted group), idempotency, the first acknowledgment winning a race, stale reads and dismissals not undoing it, Mark all read not acknowledging, the member reduction in the bell and the pop-up read, the four bounded reads and `complete` |
| `functional_tests/route_tests/test_workflow_alert_acknowledge_policy.py` | The route's Blueprint, Swagger and authentication decorators, the session identity, every response shape, no exception text in errors |
| `functional_tests/route_tests/test_workflow_alert_since_hours_policy.py` | The alerts route's new fields and failure shapes |
| `functional_tests/test_workflow_alert_client_parity.py` | The V2 editor accepts and refuses exactly what the server does, with the same messages, in both scopes |
| `functional_tests/test_workflow_alert_sounds_setting.py`, `test_workflow_alert_sound_assets.py` | The admin setting end to end; the tones, their format and the generator's determinism |
| `functional_tests/test_workflow_alert_sound_parity.py` | Classic and V2 share the lock, storage keys, limits, timing, channel and tones |
| `ui_tests/test_v2_workflow_alerts.py`, `ui_tests/test_workspace_workflow_alert_rules.py` | Both editors |
| `ui_tests/test_v2_workflow_alert_notices.py` | V2: bypassing claims and the 24-hour window, no tuck, Escape minimizing, Acknowledge and Open acknowledging, Mark all read skipping, medium and large sizes and the large dialog's height, large type, the sound's once, repeat, blocked and gated paths, no extra beeps on clicks or key presses, Play once playing once across reads and once between two tabs, alerts arriving together chiming once in the loudest tone, Enable sound retrying refused chimes as one, a showing alert not presented again, Enable sound as its own control, re-reads every 20 seconds, broadcast retirement, a waiting alert acknowledged elsewhere going quiet, no retry for a refused alert acknowledged elsewhere, Open and Acknowledge leaving the next pending alert up and sounding in its tone, pending alerts leading, the notice taking its own room in the full rail and stepping aside as a flyout, a flyout that stepped aside showing the next alert that leads, the member view, the Preferences switches, the Alert monitor while hidden, and the bell's Acknowledge, read and open |
| `ui_tests/test_v2_notifications_bell.py` | The bell's Acknowledge and "Acknowledged by" |
| `ui_tests/test_workflow_alert_classic_acknowledgment.py` | The real classic scripts on an offline page: a must-acknowledge alert returning after a reload while an ordinary one stays suppressed, Acknowledge, the banner and **Review**, staying in the banner across polls, acknowledgment elsewhere by poll or broadcast, a capped read not retiring an alert, the repeat interval and every sound gate, resuming sound when it is turned back on, **Play once** playing once, **Enable sound** in the dialog and banner, a refused sound giving up the lock, **Enable sound** retrying a refused chime once, alerts arriving together chiming once in the loudest tone, refused chimes retried as one, a chime another tab played not repeated, **Mark as read** for an alert without links, sizes, the team line, and polls skipping the alerts read when nothing needs it |

## Known limitations

- After each page load, sound waits for a click or key press unless the browser policy allows the
  site to autoplay.
- Background tabs are throttled by the browser, so a repeating sound in a hidden tab can drift by
  a second or so.
- Members other than the owner see a simpler alert, and reach the run's output through **Open**
  or the group's workflow run history.
- A team alert reaches the group's current members. An owner who has left the group no longer sees
  it.
- A page loaded before this release treats a must-acknowledge alert as an ordinary pop-up until it
  is reloaded.
- A group manager's rule can make every member's browser sound. Admins can turn sounds off, and
  each person can turn them off on their own device. There is no per-member opt-out from team
  alerts yet.
- The AI workflow assistant keeps a rule's options when it edits a workflow, but can't set them yet.
- Run activity doesn't show acknowledgments yet.

## Related

- [Workflow Alert Rules](WORKFLOW_ALERT_RULES.md)
- [V2 Workflow Alert Notices](V2_WORKFLOW_ALERT_NOTICES.md)
- [V2 Workflow Alert Editing](V2_WORKFLOW_ALERT_EDITING.md)
- [Workflow Priority Alerts](WORKFLOW_PRIORITY_ALERTS.md)
