---
layout: page
title: "Fork a conversation"
description: "Branch an existing chat so you can explore a different direction without changing the original thread."
section: "Guides"
audience: user
---

## What this does

Forking creates a new conversation from an existing point in a chat. The original thread remains available while the fork continues independently.

{% include media.html type="video"
                      title="Fork a conversation walkthrough"
                      poster="video-posters/guide-fork-a-conversation.png"
                      capture="Recording planned. Show fork a conversation end to end and explain why this task helps a user." %}

## Why you would use this

Fork a conversation when one path should continue as-is and another needs a different assumption, audience, model, or source set. It replaces copying previous context into a new chat by hand; it is unnecessary for a simple follow-up that belongs in the same thread.

## Before you start

- Collaborative conversation behavior depends on `enable_collaborative_conversations`.
- You must be able to open the conversation you want to fork.
- If workspace grounding was used, you still need access to the related documents.

## Steps

1. Open **Chat** and select the conversation to branch.
2. Open the message actions menu at the point you want to branch from.
3. Select **Fork conversation**.

{% include media.html src="guides/fork-a-conversation-step-3.png"
                      alt="Screenshot showing fork a conversation step 3."
                      title="Fork a conversation step 3"
                      capture="Capture the fork a conversation task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. In the confirmation modal, select **Fork conversation** again.
5. Continue in the new conversation with the alternate direction.

{% include media.html src="guides/fork-a-conversation-step-5.png"
                      alt="Screenshot showing fork a conversation step 5."
                      title="Fork a conversation step 5"
                      capture="Capture the fork a conversation task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. Rename the forked conversation if the title does not clearly describe the new path.

## Verify it worked

A new conversation opens or appears in the list. The original conversation remains unchanged.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Fork conversation** is not available | That message or conversation type does not expose the action | Start a new chat manually or export the transcript if you need a copy. |
| The fork cannot use prior documents | Your document access changed | Re-select accessible documents with **Workspaces**. |

## Related

- [Export a conversation]({{ '/guides/export-a-conversation/' | relative_url }})
- [Lock workspace scope in chat]({{ '/guides/lock-workspace-scope/' | relative_url }})
