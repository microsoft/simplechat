---
layout: page
title: "Export a conversation"
description: "Download one or more conversations as JSON, Markdown, or PDF."
section: "Guides"
audience: user
---

## What this does

The export wizard downloads selected conversations in a structured or readable format. This guide chooses conversations, format, packaging, optional AI-generated intro summary, and download.

{% include media.html type="video"
                      title="Export a conversation walkthrough"
                      poster="video-posters/guide-export-a-conversation.png"
                      capture="Recording planned. Show export a conversation end to end and explain why this task helps a user." %}

## Why you would use this

Export conversations when you need an audit copy, handoff, or transcript for documentation. JSON is best for structured analysis, Markdown is easiest to edit, and PDF is best for print-ready sharing. Do not export content your organization does not allow you to remove from the app.

## Before you start

- You must be signed in and able to see the conversations you want to export.
- A chat model must be available if you want an AI-generated intro summary.
- If retention or archiving matters, review `enable_conversation_archiving` on [Safety settings]({{ '/admin/safety/' | relative_url }}).

## Steps

1. Open **Chat**.
2. Select one or more conversations in the conversation list.
3. Select **Export selected conversations**.

{% include media.html src="guides/export-a-conversation-step-3.png"
                      alt="Screenshot showing export a conversation step 3."
                      title="Export a conversation step 3"
                      capture="Capture the export a conversation task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. In **Export Conversations**, review the selected conversations and remove any unwanted item.
5. Choose **JSON**, **Markdown**, or **PDF**.
6. Choose **Single File** or **ZIP Archive**.
7. Optionally enable **Include AI-generated intro summary** and choose a **Summary model**.

{% include media.html src="guides/export-a-conversation-step-7.png"
                      alt="Screenshot showing export a conversation step 7."
                      title="Export a conversation step 7"
                      capture="Capture the export a conversation task at this step in SimpleChat with realistic sample data and redact secrets." %}

8. On **Ready to Export**, select **Download**.

## Verify it worked

A `.json`, `.md`, `.pdf`, or `.zip` file downloads. Open it and confirm it contains the expected titles and messages.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The wizard says no conversations are selected | No conversation is selected | Select at least one conversation first. |
| The downloaded format is unexpected | Format and packaging were chosen separately | Run the wizard again and verify both choices. |

## Related

- [Use tags on conversations]({{ '/guides/use-tags-on-conversations/' | relative_url }})
- [Fork a conversation]({{ '/guides/fork-a-conversation/' | relative_url }})
- [Safety settings]({{ '/admin/safety/' | relative_url }})
