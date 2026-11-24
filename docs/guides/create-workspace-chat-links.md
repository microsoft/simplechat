---
layout: page
title: "Create workspace chat links"
description: "Share an exact model or agent, one workspace, and selected documents with people who already have access."
section: "Guides"
audience: user
version: "0.261.473"
---

## What this does

Workspace chat links give another person a short URL that opens SimpleChat with
the same available model or agent, workspace, and selected documents. The link
does not share a conversation and does not grant access.

Implemented in **0.261.473**.

## Before you start

- Select an available agent or model.
- Select one personal, group, or public workspace.
- Select one or more explicit documents.
- Do not mix workspaces or use a tag/workspace-wide selection for the link.

## Create a link

1. Open a new or existing personal chat.
2. Configure the runner and selected documents.
3. Select **Create chat link** in the composer tools.
4. Review the runner, workspace, and document count.
5. Choose an expiry:
   - 7 days
   - 30 days
   - 90 days (default)
   - 1 year
   - Never expires
6. Select **Create link**, then copy the plain-text URL.

The copied URL is short enough to paste directly into plain-text email.

## Open a link

The recipient signs in normally and completes any required access or Terms of
Use step. SimpleChat checks every dependency again. If any dependency is
missing, held, revoked, disabled, or unavailable, the whole launch is refused
rather than silently substituting a runner or dropping documents.

SimpleChat prepares a new private chat and does not send a prompt automatically.

## Manage your links

The link dialog lists your active links. Select **Revoke** when a link should
stop working. Existing conversations created from the link continue normally.

Full Control Center administrators can review and revoke all active links from
**Control Center → Chat Links**. This surface does not grant the administrator
access to launch a link whose resources they cannot otherwise use.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The create control says to select explicit documents | The composer has none, has a tag-only selection, or spans multiple workspaces | Select exact documents from one workspace. |
| The recipient sees a permission message | The recipient is not authorized for a runner, workspace, or selected document | Grant access through the normal workspace, sharing, or governance process. The link itself cannot grant it. |
| The recipient sees that the link is unavailable | It expired, was revoked, or one of its referenced resources no longer exists | Create a new link from a currently valid configuration. |
| A link opens but later returns a configuration-changed message | The current model/agent or document selection changed before the first send | Resolve the link again and send without changing its setup. |
| Clipboard copy is unavailable | The browser denied clipboard permission | Focus the displayed URL, then copy it manually. |

## Related

- [Chat interface controls]({{ '/reference/chat-controls/' | relative_url }})
- [V2 Control Center]({{ '/guides/v2-control-center/' | relative_url }})
