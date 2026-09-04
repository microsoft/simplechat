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

Configure default scope, result limit, preferred windowing, and summary defaults.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
