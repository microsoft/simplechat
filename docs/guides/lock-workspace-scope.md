---
layout: page
title: "Lock workspace scope in chat"
description: "Keep a conversation tied to the same selected workspaces after grounded answers."
section: "Guides"
audience: user
---

## What this does

Workspace scope lock keeps a conversation associated with the workspace scope used for grounded chat. The chat header shows **Scope locked** when locked scope metadata exists.

{% include media.html id="slide-workspace-scope-lock" %}

The lock binds workspace context, not a frozen copy of its files. Documents
can change, current permissions still apply, and configured web, Microsoft 365,
or other actions have their own access and governance rules. It is not
immutable storage or a universal external-tool isolation boundary.

{% include media.html type="video"
                      title="Lock workspace scope in chat walkthrough"
                      poster="video-posters/guide-lock-workspace-scope.png"
                      capture="Recording planned. Show lock workspace scope in chat end to end and explain why this task helps a user." %}

## Why you would use this

Use scope lock when grounded retrieval should stay associated with one team's documents or selected workspace context. It prevents accidental workspace drift; unlock when permitted, or start a new chat, when you intentionally need a different workspace set.

## Before you start

- Workspace chat must be available through `enable_user_workspace`, `enable_group_workspaces`, or `enable_public_workspaces`.
- Admins can enforce the lock with `enforce_workspace_scope_lock`; see [Chat settings]({{ '/admin/chat/' | relative_url }}).
- You need access to the workspace documents you plan to use.

## Steps

These steps use the classic **Grounded Search** controls. In V2, workspace
and document context is selected through **Documents**; see the
[document-source picker]({{ '/reference/chat-controls/#react-v2-document-source-picker' | relative_url }}).
The scope boundary and enforcement policy remain separate from that interface choice.

1. Open **Chat**.
2. Select **Workspaces** to open **Grounded Search**.
3. Choose a **Scope**, then optionally choose **Tags** and **Document**.

{% include media.html src="guides/lock-workspace-scope-step-3.png"
                      alt="The Grounded Search panel open above the composer, showing the Action, Scope, Document, and Tags selectors used to choose what a message searches."
                      title="Choosing scope in Grounded Search"
                      capture="Capture the lock workspace scope in chat task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Send a grounded message.
5. Look for **Scope locked** in the chat header or beside **Scope**.
6. Select the lock indicator to manage it; if enforced, the modal explains that it cannot be unlocked.

{% include media.html src="guides/lock-workspace-scope-step-6.png"
                      alt="Screenshot showing lock workspace scope in chat step 6."
                      title="Lock workspace scope in chat step 6"
                      capture="Capture the lock workspace scope in chat task at this step in SimpleChat with realistic sample data and redact secrets." %}

7. Start a new conversation when you need a different locked source set.

## Verify it worked

The conversation continues to show the locked scope, and conflicting workspace selections are prevented or require unlocking first.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| You cannot unlock the scope | `enforce_workspace_scope_lock` is enabled | Start another conversation for a different source set. |
| Scope choices are disabled | They conflict with the locked conversation scope | Use the lock modal or create a new chat. |

## Related

- [Use tags in chat]({{ '/guides/use-tags-in-chat/' | relative_url }})
- [Fork a conversation]({{ '/guides/fork-a-conversation/' | relative_url }})
- [Chat settings]({{ '/admin/chat/' | relative_url }})
- [Workspace scope lock]({{ '/features/workspace-scope-lock/' | relative_url }})
