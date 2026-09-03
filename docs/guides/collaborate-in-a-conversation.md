---
layout: page
title: "Collaborate in a conversation"
description: "Share a chat with other people, mention participants, and approve generated files before they become available."
section: "Guides"
audience: user
---

## What this does

Collaborative conversations let more than one person work in the same chat thread. Participants see the shared message history, can reply in context, and can use `@` mentions to direct attention to another participant or an AI target.

{% include media.html type="video"
                      title="Collaborate in a conversation walkthrough"
                      poster="video-posters/guide-collaborate-in-a-conversation.png"
                      capture="Recording planned. Show sharing a conversation, mentioning a participant, and approving a shared file." %}

## Why you would use this

Use a shared conversation when the discussion, prompts, AI responses, and generated deliverables should stay in one place for a team. It is useful for handoffs, shared review, and decisions that need a visible trail. Keep private analysis in a normal one-person chat when other users should not see the messages or files.

## Before you start

- An admin must enable `enable_collaborative_conversations`; see [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- You need an existing personal or group conversation to share, or you can start from a collaborative conversation you already manage.
- The person you add must be discoverable through recent collaborators or local user settings records in SimpleChat.
- In personal shared conversations, owners and admins can add or remove members. The owner can also change member roles and delete the shared conversation for everyone.
- In shared group conversations, group access still follows the group workspace role and status rules.

## Steps

1. Open the conversation you want to share.
2. Open the conversation menu and choose **Add participants**, or open **Details** and choose **Add participant** when the button is available.
3. Search for a person by name or email, select the right result, and confirm with **Add participant**.

{% include media.html src="guides/collaborate-in-a-conversation-add-participant.png"
                      alt="Screenshot showing the Add participant dialog for a shared conversation."
                      title="Add a participant"
                      capture="Capture the Add participant dialog with a realistic collaborator search result. Redact names and email addresses." %}

4. Ask the invited person to accept the invite before they post. Pending invitees can see invite controls, but they cannot participate until they accept.
5. Type a shared message in the composer. To mention someone, type `@`, use the arrow keys if needed, then press **Tab** or **Enter** to accept the highlighted participant.

{% include media.html src="guides/collaborate-in-a-conversation-mention.png"
                      alt="Screenshot showing the shared conversation mention menu with a participant highlighted."
                      title="Mention a participant"
                      capture="Capture the mention menu in a shared conversation. Show the highlighted suggestion and redact personal details." %}

6. If the selected `@` suggestion is a collaborator who is not already in the conversation, confirm the invite before sending the message.
7. When you want the AI to answer in a shared conversation, use an explicit AI target from the `@` menu instead of assuming every shared message calls the AI.
8. When a non-owner participant generates a downloadable file, wait for the approval card. The conversation owner approves files in personal shared conversations; a group **Owner**, **Admin**, or **Document Manager** approves files in group shared conversations. The approval gate applies to downloadable deliverables such as CSV, XLSX, DOCX, PDF, JSON, and XML; generated images and charts are not held for approval.

{% include media.html src="guides/collaborate-in-a-conversation-file-approval.png"
                      alt="Screenshot showing a pending generated file approval card with Approve and Deny actions."
                      title="Approve a shared generated file"
                      capture="Capture the inline file approval card in a shared conversation. Show Approve and Deny, and redact file names if needed." %}

9. Approve the file to make it downloadable, or deny it if it should not be released. Requesters cannot approve their own generated files.

## In the V2 interface

The same shared conversations work in the V2 interface, with the controls in different places.

- **Share a conversation, or manage who is in one**: the people button in the chat header, or **Share** in the conversation's menu in the left rail. Both open the same panel, which also promotes members to admin, removes people, and lets you leave the conversation or delete it for everyone.
- **Accept an invitation**: a prompt above the conversation offers **Join** and **Decline**. You can read an invited conversation before joining, but the composer stays disabled until you do.
- **Mention somebody**: type `@` in the composer. The menu lists the people already in the conversation, then the models and agents you can address, then people you could add. Use the arrow keys and press **Tab** or **Enter** to accept the highlighted suggestion.
- **Ask the assistant**: `@`-mention a model or agent, or turn on an assistant tool such as document search, web search, image generation, deep research, reading URLs, an agent, or a saved prompt. A message with none of those goes to the other participants only, exactly as in the classic interface.
- **Reply to a specific message**: the reply button on any message. The reply shows what it is answering.
- **Approve a generated file**: files waiting on your decision are listed above the conversation with **Approve** and **Deny**, rather than on the message that produced them.

Retry, edit, attempt navigation, and fork are not offered in a shared conversation in either interface; those actions have no shared-conversation equivalent.

## Verify it worked

The conversation appears with a shared or collaborative indicator, the participant list shows accepted or pending members, and new shared messages appear for each accepted participant. A completed `@` mention appears in the message text. A participant-generated file stays unavailable while approval is pending and becomes downloadable only after an authorized approver approves it.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Add participants** is missing | Collaborative conversations are disabled, the conversation type is not supported, or your role cannot manage members | Ask an admin to confirm `enable_collaborative_conversations`, then check your role from conversation **Details**. |
| The invited person cannot post | Their invite is still pending | Have them accept the invite before replying. |
| **Tab** does not complete the `@` text | No suggestion is highlighted, the menu says no matches, or **Shift+Tab** was pressed | Keep typing until a match appears, use the arrow keys to highlight it, then press **Tab** or **Enter**. |
| A generated file cannot be downloaded | The file is waiting for approval, was denied, or expired before approval | Ask the conversation owner or eligible group approver to review the inline approval card or notification. |

## Related

- [Fork a conversation]({{ '/guides/fork-a-conversation/' | relative_url }})
- [Upload documents in chat]({{ '/guides/upload-documents-in-chat/' | relative_url }})
- [Chat controls reference]({{ '/reference/chat-controls/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
