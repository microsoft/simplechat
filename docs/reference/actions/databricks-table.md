---
layout: page
title: "Databricks Table"
description: "Reference for the Databricks Table SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: databricks-table -->

{% include media.html src="reference/actions-databricks-table-configuration.png" alt="Databricks Table action setup or assignment UI." title="Databricks Table action" capture="Capture the Databricks Table action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Compatibility wrapper for legacy `databricks_table` manifests.

## Why and when to use it

Use only to keep older manifests working. For new work, use Databricks.

## Before you start

- Existing legacy manifest with key auth; the create-action UI hides `databricks_table`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

No new-action panel; migrate to [Databricks]({{ '/reference/actions/databricks/' | relative_url }}) for new actions.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents/' | relative_url }})
- [Workspace identities]({{ '/admin/workspace-identities/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
