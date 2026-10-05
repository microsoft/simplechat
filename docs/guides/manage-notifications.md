---
layout: page
title: "Manage notifications"
description: "Review, filter, search, and mark SimpleChat notifications as read, from the Notifications page or the V2 bell."
section: "Guides"
audience: user
---

## What this does

The Notifications page lists app notifications, filters read and unread items, searches the list, and opens notification details. You can mark everything read or follow a link when one is provided.

In the V2 interface, a bell in the navigation rail shows how many notifications are unread and opens the same notifications in a panel, where you can follow, read, and dismiss them without leaving the page you are on. Workflow alerts that need attention now also pop up in V2, from the bell.

{% include media.html type="video"
                      title="Manage notifications walkthrough"
                      poster="video-posters/guide-manage-notifications.png"
                      capture="Recording planned. Show manage notifications end to end and explain why this task helps a user." %}

## Why you would use this

Use notifications to catch workflow activity, shared conversation events, approvals, or other in-app updates without scanning every workspace. They complement browser pop-ups, but they are not a permanent audit log.

## Before you start

- You must be signed in.
- Desktop conversation notifications require `enable_desktop_notifications` and browser permission; see [Chat settings]({{ '/admin/chat/#desktop-notifications-section' | relative_url }}).
- Your personal desktop preference is saved from Profile in the classic interface, or from **User Settings** > **Preferences** in V2. Both save the same preference.

## Steps

1. Open **Notifications**.
2. Use **All**, **Unread**, or **Read** to filter.
3. Choose **10 per page**, **20 per page**, or **50 per page**.

{% include media.html src="guides/manage-notifications-step-3.png"
                      alt="The Notifications page showing the All, Unread, and Read filter buttons, the per-page selector, and a search box narrowing the list to document-ready notifications, with paging beneath."
                      title="Manage notifications step 3"
                      capture="Capture the manage notifications task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Type in **Search notifications...** to narrow the list.
5. Select a notification to open the **Notification** modal.
6. Use **Go to Link** when it appears.

{% include media.html src="guides/manage-notifications-step-6.png"
                      alt="Screenshot showing manage notifications step 6."
                      title="Manage notifications step 6"
                      capture="Capture the manage notifications task at this step in SimpleChat with realistic sample data and redact secrets." %}

7. Select **Mark All Read** after reviewing the queue, or refresh the list.

## Use the bell in the V2 interface

Since **0.261.195**, the V2 bell sits at the top of the navigation rail, beside the
application's name or logo. Its badge counts unread notifications up to **9+**. When the rail
is collapsed to icons, a dot on the bell shows that something is unread.

1. Select the bell to open **Notifications**. The newest are first; select **Load more** for older ones.
2. Select a notification's title to go where it points. Chat notifications open the conversation in V2. Approvals and workflow activity open in the classic interface until V2 has those pages. Opening a notification marks it read.
3. Use **Mark as read** or **Dismiss** on one notification, or **Mark all read** in the panel's header.
4. Select **Open all in the classic interface** when you need search or the read and unread filters.

{% include media.html src="guides/manage-notifications-v2-panel.png"
                      alt="The V2 navigation rail with the notification bell beside the application name and its panel open, listing an AI responded notice, a workflow alert, and a document notice with Mark as read and Dismiss buttons, and Mark all read in the header."
                      title="V2 notification panel"
                      capture="Capture the V2 rail with the bell's panel open over realistic sample notifications. Redact conversation titles and names." %}

A notification whose link leads to another site, or can't be checked, says so
instead of opening. V2 opens only links on this site, because a notification can
quote content from outside it.

To get a desktop notification when a reply finishes while you are in another tab
or window, open the account menu at the foot of the rail, choose **User Settings**,
then **Preferences**, and turn on **Notify me when a reply is ready** under
**Desktop notifications**. The browser asks for permission in the same click. The
notification names the conversation, never the reply, and clicking it opens that
conversation.

## Workflow alerts that pop up in V2

Since **0.261.199**, a workflow alert that needs attention pops up in V2 as a
small notice. Since **0.261.236** it hangs from the notification bell, where you can
always find it again. With the rail expanded, it drops down from the bell the way the
bell's panel does. When the rail is collapsed to icons, or on a phone, it flies out
beside the bell instead. It never moves the cursor away from what you are typing, so
you can finish your sentence before you look.

An alert pops up only when all of these are true:

- **It is meant to pop up.** Alerts on every run always pop up. An alert rule pops
  up when its delivery is **Pop-up alert**, or **Default for severity** with a
  medium, high or critical severity. **Notification bell only** alerts, and info and
  low alerts left at the default, go to the bell only. See
  [Set up alerts]({{ '/guides/create-a-workflow/#set-up-alerts' | relative_url }}).
- **It is unread and arrived in the last 24 hours.** Older alerts wait in the bell,
  so coming back after a few days away doesn't bring a pile of pop-ups.
- **No other V2 tab in this browser has shown it.** Each alert pops up once, however
  many tabs you have open.
- **You can see it.** The tab must be in view, with no dialog open, the bell's panel
  closed, and on a phone the navigation menu closed. An alert that arrives in the
  meantime waits until then.

The notice names the alert's priority, its title and the workflow that raised it.
Several alerts from one workflow share one notice, with a line such as "Failed 4
times since 9:40 AM", and **+2 more** means other alerts are waiting behind it. The
most urgent alert comes first.

Info, low and medium notices tuck into the bell after about eight seconds. Pointing
at the notice, or moving focus into it, pauses that timer. High and critical
notices stay until you open or close them. Closing a notice with **×** or Escape
tucks it into the bell, where it stays unread; it doesn't pop up again.

{% include media.html src="guides/manage-notifications-v2-alert-notice.png"
                      alt="The V2 navigation rail with a high priority workflow alert notice hanging below the notification bell, showing its priority tag, the alert's title, the workflow's name, a Failed 3 times line, and a close button."
                      title="V2 workflow alert notice"
                      capture="Capture the V2 rail with a high priority workflow alert notice under the notification bell, using realistic sample alerts. Redact workflow and conversation names." %}

Select the notice to open the full alert. It says why you are seeing it and which
rules matched, the summary, and what went wrong for a failed run. From there you
can:

- Select **Open** to go to what the workflow made: the conversation it created, or
  else the conversation it posted into, its run or the workflow itself. This marks
  the alert read. An alert with nothing to open offers **Mark read** instead.
- Select **Dismiss** to dismiss it. When the notice stands for several alerts from
  one workflow, Open and Dismiss both act on all of them.
- Select **Show more** for the details, the alert's facts, and the other ways in:
  - **Open workflow** goes to the workflow in its personal or group workspace,
    with the run that raised the alert open. This marks the alert read.
  - Other links the alert carries, such as **Open workflow conversation**.
  - **Ask about this**, on an alert about a completed run of one of your personal
    workflows, asks chat about that run's stored result without running the
    workflow again. The alert closes and stays unread. See
    [Ask about workflow results]({{ '/guides/ask-about-workflow-results/' | relative_url }}).
- Select **Next** to step through the other waiting alerts, or **Mark all read** to
  clear them all. Both appear when more than one alert is waiting.

Closing the full alert without choosing anything leaves its alerts unread in the
bell.

With a keyboard, the notice comes right after the bell in the tab order.
Press Enter on it to open the full alert. Focus moves into the alert, and returns to
where you were when it closes. Screen readers announce each notice once, after what
they are reading; a critical alert is announced straight away.

## Alerts that need acknowledgment

Since **0.261.235**, a workflow's owner can make an alert rule require
acknowledgment, play a sound, take more of the screen, or reach everyone in a group
workflow's group. These alerts are for things someone has to act on, such as a failure
an operations team must pick up, so they stay in front of you until someone responds.
See [Make an alert hard to miss]({{ '/guides/create-a-workflow/#make-an-alert-hard-to-miss' | relative_url }}).

An alert that needs acknowledgment is marked **Needs acknowledgment**, and:

- **It keeps coming back.** It pops up again after you refresh, in every tab, and on
  every device, however old it is, until someone acknowledges it. Closing it, or
  pressing Escape, only shrinks it: V2 keeps its notice in a row of its own under the
  notification bell, where it pushes **New chat** and the navigation down rather than
  covering them, and classic keeps a
  banner at the bottom of the page with **Review**. It never tucks into the bell,
  and **Mark all read** doesn't clear it. Alerts that need acknowledgment are shown
  before any others, whatever their severity.
- **Select Acknowledge to clear it.** **Acknowledge** replaces **Dismiss**. Selecting
  **Open** acknowledges the alert too, because you're responding to it. Any other alert
  that needs acknowledgment stays up. The alert then
  disappears from your other tabs straight away, and from other devices when they next
  check. In the bell, the alert has its own **Acknowledge** button, and opening it from
  the bell acknowledges it too. Marking it read or dismissing it there leaves it waiting.
- **It may sound.** The tone gets more urgent with the severity, and may repeat every
  five seconds until someone acknowledges the alert. Only one tab in your browser plays
  it, and when several alerts repeat you hear one tone, the most urgent one's. An alert
  set to **Play once** chimes once in your browser, not again in another tab or after a
  refresh, and alerts that arrive together chime once, in the most urgent tone.
- **It may be larger.** A medium alert opens in full straight away. A large alert fills
  the screen.

A team alert reaches everyone in the group and says so. When any member acknowledges
it, it stops for everyone, and the bell shows "Acknowledged by *name* at *time*". If
you aren't the workflow's owner, the alert is simpler: its severity, the workflow, the
rules that matched, and **Open** to what the run created in the group.

### Sound on this device

Browsers don't play sound on a page nobody has clicked or typed in since it loaded.
If that stops an alert's sound, the alert shows **Enable sound**. Select it, or click
anywhere on the page, and the sound starts. **Enable sound** goes away once a sound
has played.

To silence workflow alert sounds on one device, turn off **Play alert sounds** under
**Workflow alerts on this device** in V2 **Preferences**, or **Play workflow alert
sounds on this device** in the classic Profile settings. It applies to this browser
only, in both interfaces. Administrators can turn workflow alert sounds off for
everyone.

### Keep an operations screen watching

On a screen that has to notice alerts within seconds, turn on **Alert monitor** under
**Workflow alerts on this device** in V2 **Preferences**. V2 then checks for workflow
alerts every 30 seconds, even when the tab is in the background, rather than slowing
down while nothing changes. For a display that reloads unattended, ask your browser
administrator to add SimpleChat to **Allow media autoplay on specific sites**
(`AutoplayAllowlist` in Microsoft Edge and Google Chrome). Sound can then play without
anyone clicking first.

## Verify it worked

Unread notifications lose unread styling after being marked read. Filters and search update the list without changing unrelated notifications.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Desktop pop-ups do not show | Browser permission or profile preference is off | Enable browser notifications and save the profile setting, or turn the preference on in V2 **Preferences**. |
| Older items are hard to find | Search or status filters are narrowing the list | Clear search and choose **All**. |
| V2 **Preferences** has no **Desktop notifications** section | An administrator has not enabled desktop notifications | Ask an administrator about **Enable Desktop Conversation Notifications**. |
| V2 **Preferences** says the browser is blocking notifications | Permission was denied for this site | Allow notifications in the browser's site settings, then return to the tab. |
| A workflow alert didn't pop up in V2 | It is set to go to the bell only, it is more than 24 hours old, or another V2 tab already showed it | Open the bell, where it is still unread. To make a rule pop up, set its delivery to **Pop-up alert**. |
| A workflow alert pops up later than expected | V2 checks for new notifications every 30 seconds, less often while nothing changes, and holds the notice while a dialog is open | Return to the tab or close the dialog. Switching back to the tab checks straight away. |
| The notice tucked away before I read it | Info, low and medium notices tuck into the bell after about eight seconds | Open the bell; the alert is still unread there. Point at a notice to keep it open. |
| The full alert has no **Open workflow** | The alert was raised before 0.261.199 and doesn't say which workspace its workflow belongs to | Open the workflow from its workspace's workflows list. |
| A workflow alert keeps coming back | Its rule requires acknowledgment | Select **Acknowledge** or **Open**. Mark read, Dismiss and Mark all read don't clear it. |
| A workflow alert shows **Enable sound** | The browser blocks sound until you click or type on the page | Select **Enable sound**, or click anywhere on the page. |
| A workflow alert makes no sound | Sound is off on this device, an administrator turned workflow alert sounds off, or another tab in this browser is playing it | Check **Play alert sounds** in V2 **Preferences**, or ask an administrator about **Enable Workflow Alert Sounds**. |
| An operations screen shows alerts late | V2 slows down while nothing changes and doesn't check in a background tab | Turn on **Alert monitor** in V2 **Preferences** on that screen. |

## Related

- [Update profile preferences]({{ '/guides/update-profile-preferences/' | relative_url }})
- [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }})
- [Ask about workflow results]({{ '/guides/ask-about-workflow-results/' | relative_url }})
- [Safety settings]({{ '/admin/security/' | relative_url }})
