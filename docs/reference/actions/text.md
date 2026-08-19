---
layout: page
title: "Text"
description: "Reference for the Text SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: text -->

{% include media.html src="reference/actions-text-configuration.png" alt="Text action setup or assignment UI." title="Text action" capture="Capture the Text action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Provides Semantic Kernel text functions with invocation logging.

## Why and when to use it

Use it for simple text transformations inside agent workflows; plain prompting is enough for many cases.

## Before you start

- No credentials; controlled by `enable_text_plugin`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

No service-specific configuration beyond enabling/assigning the action.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents/' | relative_url }})
- [Workspace identities]({{ '/admin/workspace-identities/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
