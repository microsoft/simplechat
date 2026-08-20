---
layout: page
title: "Cosmos Query"
description: "Reference for the Cosmos Query SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: cosmos-query -->

{% include media.html src="reference/actions-cosmos-query-configuration.png" alt="Cosmos Query action setup or assignment UI." title="Cosmos Query action" capture="Capture the Cosmos Query action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Runs read-only Azure Cosmos DB for NoSQL queries and validates Cosmos SQL-style queries.

## Why and when to use it

Use it for governed lookup over one Cosmos container. Use SQL Query for relational databases.

## Before you start

- Cosmos endpoint, database, container, partition key path, and managed identity or account key.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Set account/container fields, auth method, optional field hints, max items, timeout, and test the connection.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
