---
layout: latest-release-feature
title: "Sync Documents From Azure Blob Storage"
description: "Azure Blob Storage containers can now be used as File Sync sources for personal, group, and public workspaces, with folder browsing and change detection."
section: "Latest Release"
---

Current release version for Sync Documents From Azure Blob Storage: **0.260.001**

Blob Storage joins the existing File Sync connectors. Sources support managed identity, Key Vault backed service principals, connection strings, and SAS tokens, and you can browse virtual folders rather than typing paths blind. Change detection uses ETags so only changed blobs are reprocessed, and prefix and filter controls keep a sync narrow.

## User Side

Azure Blob Storage containers can now be used as File Sync sources for personal, group, and public workspaces, with folder browsing and change detection.

## Admin Side

Admins decide whether Sync Documents From Azure Blob Storage is available in your environment. If you cannot find Open Workspace Sync and Open Group Workspaces, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Screenshot Placeholder

The v0.260.001 app catalog currently provides branded placeholder captures for Sync Documents From Azure Blob Storage. Replace these copied documentation images when final screenshots are ready:

- `/images/latest-release/release_260_azure_blob_file_sync_1.png`
- `/images/latest-release/release_260_azure_blob_file_sync_2.png`
- `/images/latest-release/release_260_azure_blob_file_sync_3.png`

## Why It Matters

This matters because a lot of organizational content already lives in blob containers, and syncing it keeps workspace documents current without manual re-uploads.

## How to Try It

1. Open Personal Workspace and go to the Sync section.
2. Add a new sync source and choose Azure Blob Storage.
3. Select the authentication method your container uses, such as managed identity or a SAS token.
4. Browse the virtual folders in the container and pick the prefix you want to sync.
5. Apply filters so only the file types you care about are pulled in.
6. Run the sync and watch the status, counts, and history for that source.
7. Open the Documents section and confirm the synced files appear with their sync badges.

## Notes

- The Sync Documents From Azure Blob Storage guide belongs to the SimpleChat 0.260.001 latest-feature set.
- The gallery for this page uses `release_260_azure_blob_file_sync_1.png`, `release_260_azure_blob_file_sync_2.png`, `release_260_azure_blob_file_sync_3.png` from the app Latest Features catalog.
