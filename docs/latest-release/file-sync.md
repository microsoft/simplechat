---
layout: latest-release-feature
title: "File Sync Connectors"
description: "How SMB, Azure Files, and OneDrive sources keep workspace documents synchronized"
section: "Latest Release"
---

File Sync now supports richer workspace ingestion from SMB shares, Azure Files, and OneDrive sources while keeping the existing document processing, chunking, embedding, and search pipeline.

## Why It Matters

Workspace documents can stay closer to authoritative external stores instead of depending on manual re-upload habits.

## How to Try It

1. Open a workspace with File Sync enabled and go to the **Sync** tab.
2. Add a source using one of the enabled source types: SMB, Azure Files, or OneDrive.
3. Browse supported provider folders, choose selected files or folders, and review sync history after a run.
4. Use reusable identities where available so credentials are managed separately from the source definition.

## Notes

- Admins control which File Sync source types are visible.
- OneDrive and Azure Files flows can use provider-specific browsing and identity setup.
- Synced documents continue through the normal SimpleChat indexing and search pipeline.
