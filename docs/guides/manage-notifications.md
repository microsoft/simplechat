---
layout: page
title: "Manage notifications"
description: "Review, filter, search, and mark SimpleChat notifications as read."
section: "Guides"
audience: user
---

## What this does

The Notifications page lists app notifications, filters read and unread items, searches the list, and opens notification details. You can mark everything read or follow a link when one is provided.

{% include media.html type="video"
                      title="Manage notifications walkthrough"
                      poster="video-posters/guide-manage-notifications.png"
                      capture="Recording planned. Show manage notifications end to end and explain why this task helps a user." %}

## Why you would use this

Use notifications to catch workflow activity, shared conversation events, approvals, or other in-app updates without scanning every workspace. They complement browser pop-ups, but they are not a permanent audit log.

## Before you start

- You must be signed in.
- Desktop conversation notifications require `enable_desktop_notifications` and browser permission; see [Safety settings]({{ '/admin/security/' | relative_url }}).
- Your personal desktop preference is saved from Profile.

## Steps

1. Open **Notifications**.
2. Use **All**, **Unread**, or **Read** to filter.
3. Choose **10 per page**, **20 per page**, or **50 per page**.

{% include media.html src="guides/manage-notifications-step-3.png"
                      alt="Screenshot showing manage notifications step 3."
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

## Verify it worked

Unread notifications lose unread styling after being marked read. Filters and search update the list without changing unrelated notifications.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Desktop pop-ups do not show | Browser permission or profile preference is off | Enable browser notifications and save the profile setting. |
| Older items are hard to find | Search or status filters are narrowing the list | Clear search and choose **All**. |

## Related

- [Update profile preferences]({{ '/guides/update-profile-preferences/' | relative_url }})
- [Trigger a workflow]({{ '/guides/trigger-a-workflow/' | relative_url }})
- [Safety settings]({{ '/admin/security/' | relative_url }})
