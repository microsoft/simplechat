---
layout: page
title: "Wait"
description: "Reference for the Wait SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: wait -->

{% include media.html src="reference/actions-wait-configuration.png" alt="Wait action setup or assignment UI." title="Wait action" capture="Capture the Wait action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Provides wait/sleep behavior with invocation logging.

## Why and when to use it

Use it only in workflows or tool chains that intentionally pause between operations.

## Before you start

- No credentials; controlled by `enable_wait_plugin`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

No service-specific configuration beyond enabling/assigning the action.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
