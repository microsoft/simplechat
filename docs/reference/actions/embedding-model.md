---
layout: page
title: "Embedding Model"
description: "Reference for the Embedding Model SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: embedding-model -->

{% include media.html src="reference/actions-embedding-model-configuration.png" alt="Embedding Model action setup or assignment UI." title="Embedding Model action" capture="Capture the Embedding Model action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Creates embeddings for supplied text through a configured embedding endpoint.

## Why and when to use it

Use it for workflows that need vector representations, not for conversational answers.

## Before you start

- Embedding endpoint and key; global toggle `enable_default_embedding_model_plugin`; UI hides `embedding_model`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Configure existing/default embedding action settings through Agents controls.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
