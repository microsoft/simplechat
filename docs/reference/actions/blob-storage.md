---
layout: page
title: "Blob Storage"
description: "Reference for the Blob Storage SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: blob-storage -->

{% include media.html src="reference/actions-blob-storage-configuration.png" alt="Blob Storage action setup or assignment UI." title="Blob Storage action" capture="Capture the Blob Storage action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Lists, reads, and uploads supported files in one configured Azure Blob container, optionally narrowed to a prefix.

## Why and when to use it

Use it when an agent should work with a controlled container path without broad storage access. Use Workspace upload/search for normal SimpleChat documents.

## Before you start

- Storage connection string with access to the target container; agents enabled with `enable_semantic_kernel`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Set **Connection String**, **Container Name**, optional **Blob Prefix**, default capabilities, and supported read/upload file types.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents/' | relative_url }})
- [Workspace identities]({{ '/admin/workspace-identities/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
