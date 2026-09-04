---
layout: latest-release-feature
title: "File Sync for SMB and Azure Files"
description: "File Sync can bring SMB share and Azure Files content into workspaces, with reusable identities and workflow triggers for automated refreshes."
section: "Latest Release"
---

Current release version: **0.250.001**

Users can configure sync sources where enabled, use identities for credentials, review synced-document badges, and connect sync sources to workflows that run before or after file changes. Additional sync providers are planned for future releases.

## User Side

File Sync can bring SMB share and Azure Files content into workspaces, with reusable identities and workflow triggers for automated refreshes.

## Admin Side

Availability may depend on tenant settings, governance policies, workspace scope, action configuration, or admin-managed identities. If you do not see this capability, contact your SimpleChat admin.

## Screenshot Placeholder

Replace `/images/latest-release/release_250_file_sync.png` with a screenshot showing file sync for smb and azure files in the app.

## Why It Matters

This matters because workspace documents can stay closer to authoritative file shares instead of depending on repeated manual uploads.

## How to Try It

1. Use Workspace > Sync to configure SMB or Azure Files sources when admins enable File Sync.
2. Use Workspace > Identities to reuse credentials for sync sources and actions.
3. Use workflows with File Sync triggers when analysis should run after synced content changes.

## Notes

- This guide is part of the SimpleChat 0.250.001 latest-feature set.
- Screenshot filenames are placeholders until final captures are added.
