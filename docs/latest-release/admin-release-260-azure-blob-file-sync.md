---
layout: latest-release-feature
title: Azure Blob Storage File Sync Configuration
description: Admins can configure Azure Blob Storage containers as File Sync sources for personal, group, and public workspaces.
section: Latest Release
generated_from_catalog: true
---

Current release version for Azure Blob Storage File Sync Configuration: **0.261.001**

Blob File Sync authenticates with a managed identity, a service principal client secret, or a connection string. Admin configuration includes virtual-folder browsing, ETag change detection, and prefix and filter controls. A SAS URL supplied through the connection string is parsed and reported back with its scope, permissions, and expiry, so an over-permissive account SAS is visible before it is used; once enabled, workspace users can sync approved Blob content into their workspace document sets.

## Why It Matters

This matters because admins can connect governed storage sources without forcing users to manually upload every file.

## How to Try It

1. Open Admin Settings > File Sync and add an Azure Blob Storage source for the intended workspace type.
2. Choose managed identity, a service principal client secret, or a connection string based on tenant policy.
3. Use prefix and filter controls to limit which container content users can sync.
4. Validate SAS permissions and expiry guidance before allowing workspace owners to run sync jobs.

## Where to Find It

- **Open File Sync** &mdash; Configure Azure Blob Storage sync sources and authentication.
- **Open Workspace Types** &mdash; Review workspace availability for synced Blob content.
