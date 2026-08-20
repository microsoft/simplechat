---
layout: page
title: "Update profile preferences"
description: "Adjust personal SimpleChat preferences such as appearance, tutorials, notifications, memory, and retention."
section: "Guides"
audience: user
---

## What this does

The Profile page combines account information, usage statistics, and personal preferences. This guide opens settings and saves changes that affect only your SimpleChat experience.

{% include media.html type="video"
                      title="Update profile preferences walkthrough"
                      poster="video-posters/guide-update-profile-preferences.png"
                      capture="Recording planned. Show update profile preferences end to end and explain why this task helps a user." %}

## Why you would use this

Profile preferences are for personal comfort and control: font size, navigation behavior, tutorial buttons, desktop notifications, fact memory, retention, microphone permission, and text-to-speech. They replace admin requests for account-only changes; they do not change tenant-wide settings.

## Before you start

- You must be signed in.
- Some cards appear only when admins enable features such as `enable_desktop_notifications`, `enable_fact_memory_plugin`, or retention policy toggles.
- Browser permission may be required for microphone or desktop notifications.

## Steps

1. Open **Profile**.
2. Choose **Settings**.
3. In **Appearance Preferences**, pick **Font size** and select **Save Font Size**.

{% include media.html src="guides/update-profile-preferences-step-3.png"
                      alt="Screenshot showing update profile preferences step 3."
                      title="Update profile preferences step 3"
                      capture="Capture the update profile preferences task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. In **Navigation Preferences**, choose the sidebar hide button style and select **Save Navigation Preferences**.
5. In **Tutorial Preferences**, choose whether tutorial buttons appear and select **Save Tutorial Preferences**.

{% include media.html src="guides/update-profile-preferences-step-5.png"
                      alt="Screenshot showing update profile preferences step 5."
                      title="Update profile preferences step 5"
                      capture="Capture the update profile preferences task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. If shown, configure **Desktop Conversation Notifications**, **Fact Memory**, retention settings, microphone permission, or text-to-speech settings.

## Verify it worked

Each card shows a status message after saving. Reload the app and confirm the preference still applies.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A preference card is missing | The admin disabled that feature | Ask whether the related capability can be enabled. |
| Browser notifications do not appear | Browser permission or profile preference is off | Allow notifications and save the preference again. |

## Related

- [Manage notifications]({{ '/guides/manage-notifications/' | relative_url }})
- [Send feedback]({{ '/guides/send-feedback/' | relative_url }})
- [Safety settings]({{ '/admin/security/' | relative_url }})
