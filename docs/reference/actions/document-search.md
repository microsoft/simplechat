---
layout: page
title: "Document Search"
description: "Reference for the Document Search SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: document-search -->

{% include media.html src="reference/actions-document-search-configuration.png" alt="The Document Search configuration pane noting that the action uses internal search and the current user's access, with default scope, result limit, windowing, and summary settings." title="Document Search action configuration" capture="Capture the Document Search action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Searches accessible SimpleChat documents, retrieves chunks, and summarizes documents using current user access.

## Why and when to use it

Use it when an agent should reason over workspace documents as a tool. Use the normal grounded-search panel for one-off user searches.

## Before you start

- Accessible personal, group, or public workspace content; no external credentials.
- Users also need access to the action through workspace or governance policy where applicable.


## Configuration overview

Document Search can be narrowed without granting the agent any access the user does not already have. Choose the allowed scopes:

- **My workspace** for the signed-in user's personal documents.
- **Group workspaces** for groups the signed-in user can access. Choose all accessible groups or restrict the action to selected group IDs.
- **Public workspaces** for public workspaces the signed-in user can access. Choose all accessible public workspaces or restrict the action to selected public workspace IDs.

At runtime, SimpleChat intersects those action settings with the current user's group and public workspace access. A disabled scope is rejected even if the user asks for it explicitly.

Set the default result limit with the slider or number input. The UI slider covers 5–100 results for normal setup, and the number input accepts values up to the existing backend maximum of 500 for specialized actions.

## Summary and windowing controls

The window unit controls how much source material goes into each summarization pass. Use **Automatic** when SimpleChat should choose the amount, **Fixed size** when a predictable number of pages or chunks is needed, or **Percent of document** when long documents should be sampled proportionally. Only the selected sizing value is stored; unused values are cleared to avoid conflicting instructions.

Focus instructions tell the summarizer what to prioritize, such as contract dates, safety incidents, or implementation steps. Window summary and final summary target lengths are stored as page targets from the V2 sliders. Legacy free-text values, such as word counts, are preserved as custom values and can be reset to page-based targets.

The V2 editor no longer offers ad hoc custom fields. Use **Advanced → JSON** only to review preserved legacy values.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
