---
layout: page
title: "Time"
description: "Reference for the Time SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: time -->

{% include media.html src="reference/actions-time-configuration.png" alt="Time action setup or assignment UI." title="Time action" capture="Capture the Time action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Provides time-related functions with invocation logging.

## Why and when to use it

Use it when an agent needs current time or time calculations as a tool.

## Before you start

- No credentials; controlled by `enable_time_plugin`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

No service-specific configuration beyond enabling/assigning the action.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
