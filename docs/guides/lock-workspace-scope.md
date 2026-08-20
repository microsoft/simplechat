---
layout: page
title: "Lock workspace scope in chat"
description: "Keep a conversation tied to the same selected workspaces after grounded answers."
section: "Guides"
audience: user
---

## What this does

Workspace scope lock keeps a conversation associated with the workspace scope used for grounded chat. The chat header shows **Scope locked** when locked scope metadata exists.

{% include media.html type="video"
                      title="Lock workspace scope in chat walkthrough"
                      poster="video-posters/guide-lock-workspace-scope.png"
                      capture="Recording planned. Show lock workspace scope in chat end to end and explain why this task helps a user." %}

## Why you would use this

Use scope lock when a conversation should stay inside one team's documents or one workspace context. It prevents accidental drift into other accessible sources; unlock or start a new chat when you intentionally need a different source set.

## Before you start

- Workspace chat must be available through `enable_user_workspace`, `enable_group_workspaces`, or `enable_public_workspaces`.
- Admins can enforce the lock with `enforce_workspace_scope_lock`; see [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- You need access to the workspace documents you plan to use.

## Steps

1. Open **Chat**.
2. Select **Workspaces** to open **Grounded Search**.
3. Choose a **Scope**, then optionally choose **Tags** and **Document**.

{% include media.html src="guides/lock-workspace-scope-step-3.png"
                      alt="Screenshot showing lock workspace scope in chat step 3."
                      title="Lock workspace scope in chat step 3"
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
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
