---
layout: page
title: "Manage notifications"
description: "Review, filter, search, and mark SimpleChat notifications as read, from the Notifications page or the V2 bell."
section: "Guides"
audience: user
---

## What this does

The Notifications page lists app notifications, filters read and unread items, searches the list, and opens notification details. You can mark everything read or follow a link when one is provided.

In the V2 interface, a bell in the navigation rail shows how many notifications are unread and opens the same notifications in a panel, where you can follow, read, and dismiss them without leaving the page you are on.

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

## Verify it worked

Unread notifications lose unread styling after being marked read. Filters and search update the list without changing unrelated notifications.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Desktop pop-ups do not show | Browser permission or profile preference is off | Enable browser notifications and save the profile setting, or turn the preference on in V2 **Preferences**. |
| Older items are hard to find | Search or status filters are narrowing the list | Clear search and choose **All**. |
| V2 **Preferences** has no **Desktop notifications** section | An administrator has not enabled desktop notifications | Ask an administrator about **Enable Desktop Conversation Notifications**. |
| V2 **Preferences** says the browser is blocking notifications | Permission was denied for this site | Allow notifications in the browser's site settings, then return to the tab. |

## Related

- [Update profile preferences]({{ '/guides/update-profile-preferences/' | relative_url }})
- [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }})
- [Safety settings]({{ '/admin/security/' | relative_url }})
