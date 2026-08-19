---
layout: page
title: "Math"
description: "Reference for the Math SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: math -->

{% include media.html src="reference/actions-math-configuration.png" alt="Math action setup or assignment UI." title="Math action" capture="Capture the Math action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Performs deterministic calculations such as multiply, divide, power, square root, and modulus.

## Why and when to use it

Use it when an agent should calculate instead of approximating arithmetic. Use Tabular or SQL for dataset aggregations.

## Before you start

- No credentials; controlled by `enable_math_plugin`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

No service-specific configuration beyond enabling/assigning the action.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents/' | relative_url }})
- [Workspace identities]({{ '/admin/workspace-identities/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
