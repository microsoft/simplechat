---
layout: latest-release-feature
title: "File Sync Connectors"
description: "How SMB and Azure Files sources keep workspace documents synchronized"
section: "Latest Release"
---

Current release version: **0.241.183**

File Sync now supports richer workspace ingestion from SMB shares and Azure Files while keeping the existing document processing, chunking, embedding, and search pipeline.

## User Side

Workspace users and managers can add SMB or Azure Files sync sources, browse supported folders where available, select files or folders, run sync, review history, and reuse workspace identities when credentials are needed.

## Admin Side

Admins choose whether SMB Share and Azure Files connector types are available and configure reusable identity options from Admin Settings. The screenshot gallery pairs those admin controls with the user Sync and Identities tabs.

## Screenshot Placeholder

Add a current admin screenshot showing only SMB Share and Azure Files as enabled source-type controls.

Add a user screenshot showing a workspace Sync tab with one SMB source and one Azure Files source so the active connector set is obvious.

## Why It Matters

Workspace documents can stay closer to authoritative external stores instead of depending on manual re-upload habits.

## How to Try It

1. Open a workspace with File Sync enabled and go to the **Sync** tab.
2. Add a source using one of the enabled source types: SMB or Azure Files.
3. Browse supported provider folders, choose selected files or folders, and review sync history after a run.
4. Use reusable identities where available so credentials are managed separately from the source definition.

## Notes

- Admins control which File Sync source types are visible.
- SMB and Azure Files flows can use provider-specific connection and identity setup.
- Other cloud-drive connectors are not part of the current user-facing File Sync connector set while validation continues.
- Synced documents continue through the normal SimpleChat indexing and search pipeline.
