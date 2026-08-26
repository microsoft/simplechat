---
layout: latest-release-feature
title: "Sync Documents From Azure Blob Storage"
description: "Azure Blob Storage containers can now be used as File Sync sources for personal, group, and public workspaces, with folder browsing and change detection."
section: "Latest Release"
---

Current release version for Sync Documents From Azure Blob Storage: **0.261.001**

Blob Storage joins the existing File Sync connectors. Sources support managed identity, Key Vault backed service principals, connection strings, and SAS tokens, and you can browse virtual folders rather than typing paths blind. Change detection uses ETags so only changed blobs are reprocessed, and prefix and filter controls keep a sync narrow.

## User Side

Azure Blob Storage containers can now be used as File Sync sources for personal, group, and public workspaces, with folder browsing and change detection.

## Admin Side

Blob sources are added under File Sync, which has separate sections for personal, group, and public workspace sync, so a container can be exposed to one workspace tier without exposing it to the others.

A Blob source authenticates with a managed identity, a service principal client secret, or a connection string. Managed identity avoids storing a credential at all and is the better choice where the app already has an identity on the storage account. When a SAS URL is supplied, SimpleChat parses it and reports what it actually grants: whether it is an account, container, or blob SAS, which permissions are attached, and when it expires. An account SAS is flagged as broader than a single-container source needs, and permissions beyond Read and List are called out. If the SAS is bound to a stored access policy, the permissions cannot be read from the token, and SimpleChat says so rather than implying it validated something it could not see.

Prefix and filter controls limit which part of a container users can pull from, and change detection is based on ETags, so a sync run moves changed blobs instead of re-ingesting everything.

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

- The Sync Documents From Azure Blob Storage guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_azure_blob_file_sync_1.png`, `release_260_azure_blob_file_sync_2.png`, `release_260_azure_blob_file_sync_3.png` from the app Latest Features catalog.
