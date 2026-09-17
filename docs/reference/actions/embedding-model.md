---
layout: page
title: "Embedding Model"
description: "Reference for the Embedding Model SimpleChat action."
section: "Reference"
audience: user
version: "0.261.106"
---

<!-- action-slug: embedding-model -->

{% include media.html src="reference/actions-embedding-model-configuration.png" alt="Embedding Model action setup or assignment UI." title="Embedding Model action" capture="Capture the Embedding Model action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Creates embeddings for supplied text through a configured embedding endpoint.
The default action uses the global AI Connections embedding default; this integration
was implemented in version **0.261.106**.

## Why and when to use it

Use it for workflows that need vector representations, not for conversational answers.

## Before you start

- A configured global embedding model in AI Connections and the
  `enable_default_embedding_model_plugin` capability. Azure identity authentication
  does not require storing an API key.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Configure existing/default embedding action settings through Agents controls.
The default action follows the administrator's global selection. Explicitly
configured action manifests retain their own endpoint contract; they are not
silently redirected to the application's document-search model.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
