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
                      alt="The profile Settings tab showing preference cards for font size, response completion audio, navigation, Latest Features visibility, tutorials, desktop notifications, conversation navigation, fact memory, microphone permission, and text-to-speech voice."
                      title="Update profile preferences step 3"
                      capture="Capture the update profile preferences task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. In **Navigation Preferences**, choose the sidebar hide button style and select **Save Navigation Preferences**.
5. In **Tutorial Preferences**, choose whether tutorial buttons appear and select **Save Tutorial Preferences**.

{% include media.html src="guides/update-profile-preferences-step-5.png"
                      alt="The Tutorial Preferences card with the switch that shows or hides the floating guided tutorial launchers on Chat and Personal Workspace, and its Save Tutorial Preference button."
                      title="Update profile preferences step 5"
                      capture="Capture the update profile preferences task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. If shown, configure **Desktop Conversation Notifications**, **Fact Memory**, retention settings, microphone permission, or text-to-speech settings.
7. In **Workflow Alert Sounds**, choose whether workflow alerts can play sounds in this browser. The switch takes effect at once and applies only to this browser, so a shared operations screen and your own laptop can differ. See [Alerts that need acknowledgment]({{ '/guides/manage-notifications/#alerts-that-need-acknowledgment' | relative_url }}).

## In the new interface

In the new interface, open **User Settings** from the account menu. The left rail lists
**Preferences**, **Stats**, **Groups**, **Public workspaces**, **Feedback**, and
**Violations**. To give the settings more room, collapse the rail to icons with the button
at its top. The rail stays collapsed until you expand it again, on any device.

Each tab is laid out as cards. On wide screens an **On this page** index on the right
lists them, so you can jump straight to a card. Preferences are grouped under
**Appearance**, **Chat**, **Voice and audio**, **Notifications and alerts**, **Memory and
data**, **Connected accounts**, and **Diagrams and charts**. Most changes save as soon as you make them.

Under **Voice and audio**, which cards appear depends on what your administrator has
turned on:

- **Completion sounds** plays a short sound when a reply finishes while you are looking at
  something else, such as another conversation, another page, or another window. Pick a
  sound and volume, and use **Preview** to hear it. **Mute for now** silences it without losing
  your choice.
- **Spoken replies** sets the voice and speed used when a reply is read aloud, with a
  sample you can play. Turn on **Read replies aloud automatically** to hear each reply in
  the open conversation as soon as it finishes.
- **Microphone** shows whether this browser lets the site use your microphone for voice
  input, and lets you allow it.

Under **Memory and data**, **Fact memory** holds what the assistant should know about you.
Add a memory as an **Instruction**, which shapes every reply, or a **Fact**, which is
recalled only when it is relevant to what you ask. The list beside the editor lets you
search and filter your memories; select one to change its wording or type, or to delete
it. If your administrator has turned fact memory off, the card says so: you can still tidy
your memories, but they are not used until it is turned back on.

**Retention** sets how long your own conversations and
documents are kept. You can follow your organization's default, keep them indefinitely, or
pick a period. Select **Save** to apply it: items older than the period are deleted at the
next retention run, and deleted conversations are archived first if your organization has
archiving turned on.

Under **Connected accounts**, the Microsoft 365 cards cover the same ground as the classic
page, described in the next section: **Microsoft 365 sharing**, **Chat connection**,
**Workflow connection**, and **Workflow authorizations**. Every revocation and disconnect asks
you to confirm first. Chat reconnect opens Microsoft sign-in in a pop-up and keeps you on the
page; connecting for workflows signs in through the classic Profile page and returns there.

**Violations** is always listed. If content safety is off for your application, the tab
says so instead of showing an empty list.

## Microsoft 365 data preferences

Calendar, Email, OneDrive, and SharePoint have independent sharing preferences,
so users can control disclosure even when they cannot edit the agent or action.
OneDrive and SharePoint also have separate fast/deeper-analysis preferences.
Workflow connections are explicit, revocable opt-ins and are not implied by
ordinary sign-in.

The workflow connection status is not the status of interactive chat. When
an agent needs Microsoft 365 consent, Chat offers **Connect Microsoft 365**
in the conversation and resumes the saved request after sign-in.
For workflows, select each source once; its supported read/write permissions
are explained before Microsoft's consent step, without extra permission
checkboxes. Action capability limits and outgoing-delivery review still apply.

Use the separate **Microsoft 365 chat connection** card to reconnect even when
no chat is waiting or a saved sign-in is already present. Select sources, choose
**Reconnect Microsoft 365 for chat**, and verify your same-account sign-in with
Microsoft. Then retry the original question. This renews the current interactive
session without changing saved workflow connections, permissions at the source,
or sharing approvals.

See [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
for approval duration, retained-evidence sharing, and Run as behavior
introduced in **0.261.029** and updated in **0.261.034**.

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
