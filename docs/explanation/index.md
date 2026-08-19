---
layout: page
title: "Explanation"
permalink: /explanation/
menubar: docs_menu
description: "Use the explanation section when you want the reasoning behind the product: architecture, operating principles, rollout guidance, and runtime patterns."
---

This section is for decisions, not just steps. Use it when you need to understand why Simple Chat is put together the way it is and how that affects deployment, operations, and feature rollout.

## Architecture

Understand how App Service, Azure OpenAI, AI Search, Cosmos DB, Storage, and optional services combine into one application surface.

[Open architecture]({{ '/explanation/architecture/' | relative_url }})

## Design principles

See the operating philosophy behind the product, including security, enterprise readiness, modularity, observability, and user-centered design.

[Open design principles]({{ '/explanation/design_principles/' | relative_url }})

## Feature guidance

Use the feature guidance page to decide which capabilities belong in a first rollout and which ones should be layered in after the platform stabilizes.

[Open feature guidance]({{ '/explanation/feature_guidance/' | relative_url }})

## Runtime patterns

Compare the recommended local developer loop with the Azure production runtime model so startup decisions stay consistent with the deployment model.

[Local runtime]({{ '/explanation/running_simplechat_locally/' | relative_url }}) · [Azure production]({{ '/explanation/running_simplechat_azure_production/' | relative_url }})

## Use these pages differently from how-to guides

How-to guides are task-oriented. The explanation section is where you go when you want to understand the tradeoffs behind deployment models, feature boundaries, or operational choices before you commit to one path.

## Continue into deeper references

Use these references when you need examples or historical context after the conceptual overview.

### Scenarios

Example workspace and agent scenarios show how the product can be applied in concrete business contexts.

[Agent examples]({{ '/explanation/scenarios/agents/' | relative_url }}) · [Workspace examples]({{ '/explanation/scenarios/workspaces/' | relative_url }})

### Version history

Track release history when you need historical context for rollout planning or regression analysis.

[Open release notes]({{ '/explanation/release_notes/' | relative_url }})
