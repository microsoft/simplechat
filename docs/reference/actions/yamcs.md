---
layout: page
title: "Yamcs"
description: "Reference for the Yamcs SimpleChat action."
section: "Reference"
audience: user
version: "0.261.107"
---

<!-- action-slug: yamcs -->

{% include media.html src="reference/actions-yamcs-configuration.png" alt="Yamcs action setup or assignment UI." title="Yamcs action" capture="Capture the Yamcs action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Retrieves read-only Yamcs telemetry, mission database, archive, event, packet, alarm, and link information.

## Why and when to use it

Use it for mission-control visibility. Do not use it for commanding; the plugin source intentionally does not support commands or writes.

## Before you start

- Yamcs server URL, instance, processor, auth method, and retrieval limits.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Set Server URL, Instance, Processor, Authentication Method, credentials, Max Rows, Timeout, Verify TLS, and optional read-only archive SQL.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Use your own account with a global action

From **0.261.107**, an administrator can select **Each user's personal identity**
and define the identity name, defaulting to **Yamcs**. The action stays global,
but every new call uses the person submitting the turn. Conversation ownership
and agent ownership do not supply credentials.

Provide the identity in your personal workspace or in the private credential
card shown before execution. Native Yamcs login, gateway HTTP Basic, bearer
tokens, and `x-api-key` credentials are supported. The card and its answers are
not part of chat history.

In shared chats, the returned data is shared with conversation participants.
Previous results remain shared history even when another participant's service
permissions differ. See [Connect your own action account]({{ '/guides/personal-action-authentication/' | relative_url }}).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
