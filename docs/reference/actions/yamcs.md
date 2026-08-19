---
layout: page
title: "Yamcs"
description: "Reference for the Yamcs SimpleChat action."
section: "Reference"
audience: user
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

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents/' | relative_url }})
- [Workspace identities]({{ '/admin/workspace-identities/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
