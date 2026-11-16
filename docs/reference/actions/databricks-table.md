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

`databricks_table` is hidden from new-action creation. Existing actions continue to load so owners can review, edit, or migrate them, but new governed Databricks work should use [Databricks]({{ '/reference/actions/databricks/' | relative_url }}).

Connection testing, when available for an editable migrated configuration, appears in **Authentication**. The V2 editor no longer offers ad hoc custom fields; preserved legacy values remain available in **Advanced → JSON**.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
