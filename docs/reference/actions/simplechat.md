---
layout: page
title: "SimpleChat"
description: "Reference for the SimpleChat SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: simplechat -->

{% include media.html src="reference/actions-simplechat-configuration.png" alt="SimpleChat action setup or assignment UI." title="SimpleChat action" capture="Capture the SimpleChat action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Lets agents create groups, conversations, workflows, alerts, messages, and generated documents using SimpleChat APIs.

## Why and when to use it

Use it for in-app automation. Do not enable capabilities beyond what the agent should do for users.

## Before you start

- Uses signed-in user permissions; no external credentials.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Choose the default SimpleChat capabilities exposed to agents.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents/' | relative_url }})
- [Workspace identities]({{ '/admin/workspace-identities/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
