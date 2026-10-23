---
layout: page
title: "Reference and send between conversations"
description: "Pull bounded evidence from another private conversation with ~ or delegate a queued AI task with Send To Conversation."
section: "Guides"
audience: user
version: "0.261.381"
---

## What this does

SimpleChat lets you connect separate private conversations in two different ways:

- **Reference Conversation (`~`)** pulls relevant excerpts from another private conversation into the chat, orchestration plan, or personal workflow you are currently working on, without changing the source conversation.
- **Send To Conversation** sends a focused instruction and bounded context to a destination private conversation and starts a new AI response there, queueing automatically if that conversation is already busy.

## Why you would use this

Long projects often work better as separate conversations: one thread for raw research, another for budget numbers, and another for drafting a proposal. Referencing lets the drafting conversation read conclusions from the research thread without pasting the whole transcript. Sending lets you hand off a focused follow-up task to a dedicated thread while staying in your current conversation.

## Before you start

- Use the React V2 interface (`/v2/chat` or `/v2/workspace/workflows`).
- Both conversations must be your own private conversations. Shared and group conversations are not offered as reference sources or handoff destinations.
- Masked text, deleted messages, and inactive retry attempts are automatically excluded from referenced evidence.

## Reference another conversation in chat or Ask AI

1. In the V2 chat composer, orchestration plan editor **Ask AI**, or workflow **Ask AI**, type `~` at the start of the message or after a space.
2. Type part of a conversation title, or switch to content search in the picker to match visible message text.
3. Select the conversation from the list. SimpleChat inserts an inline `~[Conversation title]` token and adds a conversation pill above the composer.
4. You can also open any private conversation's menu (`...`) in the left rail and choose **Reference Conversation**:
   - **Use in current conversation** attaches that conversation as a pill in the open composer.
   - **Copy reference** copies a portable reference that you can paste into another composer to attach the same conversation.
5. Send your message. SimpleChat retrieves bounded excerpts from the latest visible messages of each referenced conversation and cites the source conversation in the reply.

## Send a task to another conversation

1. In the conversation rail, open the actions menu (`...`) on the source conversation and select **Send To Conversation**.
2. Choose the destination private conversation and write the instruction you want the destination conversation to run.
3. Review the destination conversation's resolved model or agent and the bounded source preview.
4. Select **Send and start AI**.
   - If the destination conversation is idle, it begins generating its response right away.
   - If the destination conversation is already running a turn, SimpleChat queues the handoff in FIFO order and starts it as soon as the active turn completes.
5. Track progress from the outgoing handoff status card in the source conversation or open the destination conversation to read the full reply.

## Use conversation references in personal workflows

1. Open **Workspaces → Workflows** in V2 and create or edit a personal workflow.
2. Add a private conversation under **Shared references** or use **Ask AI** with `~` to bind a conversation source to a task.
3. When the workflow runs, each task receives fresh bounded excerpts from the latest visible messages of its bound conversations.
4. If an orchestrated plan or workflow includes a **Send To Conversation** step, previously approved destinations run within their approved scope, while any new destination pauses for explicit approval.

## Verify it worked

- For a reference, the sent message displays the referenced conversation pill and **Show sources** on the reply lists the source conversation and message excerpts used.
- For **Send To Conversation**, the source conversation shows an outgoing handoff card (`Queued`, `Running`, or `Completed`) and the destination conversation contains the attributed incoming request and its AI reply.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A conversation does not appear in the `~` menu | It is shared/collaborative, belongs to a group, or is the conversation currently open as the destination | Reference a different private personal conversation. |
| Referenced evidence says coverage is partial | The source conversation has more than 200 visible messages or exceeds the per-turn excerpt budget | Narrow the question or reference specific messages/turns. |
| A handoff stays in **Queued** status | The destination conversation is finishing an earlier turn or waiting on an approval card | Let the active turn finish or cancel the queued handoff from its status card. |

## Related

- [Fork a conversation]({{ '/guides/fork-a-conversation/' | relative_url }})
- [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }})
- [Chat interface controls]({{ '/reference/chat-controls/' | relative_url }})
