---
layout: page
title: "Chart"
description: "Reference for the Chart SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: chart -->

{% include media.html src="reference/actions-chart-configuration.png" alt="Chart action setup or assignment UI." title="Chart action" capture="Capture the Chart action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Builds validated inline chart payloads for line, bar, pie, scatter, area, bubble, radar, and stacked chart variants.

## Why and when to use it

Use it when a visual answer is easier to understand than prose. Pair it with a data action for computed values.

## Before you start

- No external credentials; rendered with SimpleChat internal Chart.js assets.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Choose the default chart types exposed to agents.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents/' | relative_url }})
- [Workspace identities]({{ '/admin/workspace-identities/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
