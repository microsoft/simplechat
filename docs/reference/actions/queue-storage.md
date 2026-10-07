---
layout: page
title: "Queue Storage"
description: "Reference for the Queue Storage SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: queue-storage -->

{% include media.html src="reference/actions-queue-storage-configuration.png" alt="Queue Storage action setup or assignment UI." title="Queue Storage action" capture="Capture the Queue Storage action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Sends messages to an Azure Queue Storage queue.

## Why and when to use it

Use it when an agent should enqueue work for another system. Do not use it for long-form storage.

## Before you start

- Queue endpoint and identity or key auth; the create-action UI hides `queue_storage`.
- Users also need access to the action through workspace or governance policy where applicable.


## Configuration overview

`queue_storage` is hidden from new-action creation because it is a legacy/internal integration. Existing queue manifests continue to load for review or migration where governance permits.

The V2 editor no longer offers ad hoc custom fields; preserved legacy values remain available in **Advanced → JSON**.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
