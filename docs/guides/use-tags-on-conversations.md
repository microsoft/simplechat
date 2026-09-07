---
layout: page
title: "Use tags on conversations"
description: "Organize conversation work by tagging the documents and document sets that drive the chat."
section: "Guides"
audience: user
---

## What this does

SimpleChat tags are document organization, and those tags carry into chat when you select tagged documents for grounded work. This guide uses tagged document sets to keep conversations understandable.

{% include media.html type="video"
                      title="Use tags on conversations walkthrough"
                      poster="video-posters/guide-use-tags-on-conversations.png"
                      capture="Recording planned. Show use tags on conversations end to end and explain why this task helps a user." %}

## Why you would use this

Conversation lists get hard to scan when many chats have similar questions. Tagging the underlying documents gives you a reliable way to return to the same source set, start a fresh thread, or explain which files shaped an answer. This is not direct conversation labeling.

## Before you start

- The relevant workspace must be enabled with `enable_user_workspace`, `enable_group_workspaces`, or `enable_public_workspaces`.
- Tags must already exist on the documents you plan to use.
- You need chat and document access for the workspace.

## Steps

1. Open the workspace **Documents** tab.
2. Use **Filter by Tags** or **Folders** to confirm the source set.
3. Select **Multi-select** and choose the tagged documents.

{% include media.html src="guides/use-tags-on-conversations-step-3.png"
                      alt="Screenshot showing use tags on conversations step 3."
                      title="Use tags on conversations step 3"
                      capture="Capture the use tags on conversations task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Select **Chat with Selected**.
5. Ask a focused question about the selected document set.
6. Rename the conversation so the task is clear.

{% include media.html src="guides/use-tags-on-conversations-step-6.png"
                      alt="Screenshot showing use tags on conversations step 6."
                      title="Use tags on conversations step 6"
                      capture="Capture the use tags on conversations task at this step in SimpleChat with realistic sample data and redact secrets." %}

7. Pin important threads and use export for handoff or archiving.

## Verify it worked

The conversation is grounded in the selected tagged documents, and you can return to the same tag later to start another conversation from that source set.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| You cannot find the same source set later | Documents were not tagged consistently | Apply one shared tag to the set. |
| The chat includes too many sources | The tag is too broad or all documents were selected | Create a narrower tag or select specific documents. |

## Related

- [Create and manage tags]({{ '/guides/create-and-manage-tags/' | relative_url }})
- [Use tags in chat]({{ '/guides/use-tags-in-chat/' | relative_url }})
- [Export a conversation]({{ '/guides/export-a-conversation/' | relative_url }})
