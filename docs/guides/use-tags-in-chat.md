---
layout: page
title: "Use tags in chat"
description: "Filter workspace documents by tag before asking grounded questions."
section: "Guides"
audience: user
---

## What this does

Tags in chat narrow the document pool used by **Grounded Search**. This guide chooses scope, tags, optional documents, and a document action before sending a question.

{% include media.html type="video"
                      title="Use tags in chat walkthrough"
                      poster="video-posters/guide-use-tags-in-chat.png"
                      capture="Recording planned. Show use tags in chat end to end and explain why this task helps a user." %}

## Why you would use this

Use tag filters when a workspace contains many documents but your question belongs to one project, case, client, or review batch. Tags reduce irrelevant citations and avoid selecting files one by one; skip them when you need every accessible document.

## Before you start

- Workspaces must be enabled with `enable_user_workspace`, `enable_group_workspaces`, or `enable_public_workspaces`; see [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- Documents must be processed and tagged.
- You need access to the workspace that contains the tagged documents.

## Steps

1. Open **Chat**.
2. Select **Workspaces** to open **Grounded Search**.
3. Under **Scope**, choose a workspace or leave **All**.

{% include media.html src="guides/use-tags-in-chat-step-3.png"
                      alt="Screenshot showing use tags in chat step 3."
                      title="Use tags in chat step 3"
                      capture="Capture the use tags in chat task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Under **Tags**, select one or more tags.
5. Leave **Document** at **All Documents** or choose specific documents to narrow further.
6. Choose **Search**, **Analyze**, or **Compare** in **Action**.

{% include media.html src="guides/use-tags-in-chat-step-6.png"
                      alt="Screenshot showing use tags in chat step 6."
                      title="Use tags in chat step 6"
                      capture="Capture the use tags in chat task at this step in SimpleChat with realistic sample data and redact secrets." %}

7. Type your question and select **Send Message**.

## Verify it worked

The answer should cite or discuss documents from the selected tag set. The conversation may show **Scope locked** after a grounded response.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The **Tags** dropdown stays disabled | No tags loaded for the selected scope | Choose the correct scope and confirm the workspace has tags. |
| Expected files are missing | The documents are untagged or unprocessed | Check the workspace Documents tab and **Filter by Tags**. |

## Related

- [Create and manage tags]({{ '/guides/create-and-manage-tags/' | relative_url }})
- [Lock workspace scope in chat]({{ '/guides/lock-workspace-scope/' | relative_url }})
- [Agents settings]({{ '/admin/agents/' | relative_url }})
