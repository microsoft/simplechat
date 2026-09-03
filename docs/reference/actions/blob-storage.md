---
layout: page
title: "Blob Storage"
description: "Reference for the Blob Storage SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: blob-storage -->

{% include media.html src="reference/actions-blob-storage-configuration.png" alt="The Blob Storage configuration pane showing the container-scoped notice, authentication type, connection string, container name and blob prefix fields, and the default capability toggles for listing and reading blobs." title="Blob Storage action configuration" capture="Capture the Blob Storage action setup or assignment UI with relevant fields visible. Redact secrets and user identifiers." %}

## What this action does

Lists, reads, and uploads supported files in one configured Azure Blob container, optionally narrowed to a prefix.

## Why and when to use it

Use it when an agent should work with a controlled container path without broad storage access. Use Workspace upload/search for normal SimpleChat documents.

## Before you start

- One authentication method for the target container: a storage connection string, managed identity access to the storage account, or an account key.
- For managed identity, the SimpleChat application identity must already have Azure Blob Storage data-plane access to the account or container. Use a read role for list/read-only actions and a write-capable role when uploads are enabled.
- Agents enabled with `enable_semantic_kernel`.
- Users also need access to the action through workspace or governance policy where applicable.

## Configuration overview

Choose **Authentication Type**:

- **Connection String** stores the full Azure Storage connection string through the normal action secret flow. Choose it when the action needs a self-contained credential and managed identity is not available.
- **Managed Identity** uses the application's Azure identity with the **Blob Service Endpoint**. Choose it when you want to avoid stored secrets and can grant the app identity the required Storage Blob data role ahead of time.
- **Account Key** uses the **Blob Service Endpoint** plus a primary or secondary storage account key. Choose it when a full connection string is not desired but key-based access is still required.

Then set **Container Name**, optional **Blob Prefix**, default capabilities, and supported read/upload file types. The endpoint must be an Azure Blob service hostname such as `https://account.blob.core.windows.net`; SimpleChat validates the endpoint before saving and again before building the action client.

Shared wizard steps: [Common action setup steps](../#common-action-setup-steps).

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
