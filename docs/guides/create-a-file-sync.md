---
layout: page
title: "Create a file sync"
description: "Connect an external file source so SimpleChat can import workspace documents."
section: "Guides"
audience: user
---

## What this does

File Sync creates a source that imports files from an approved external location into a personal, group, or public workspace. This guide chooses a source type, connection, filters, tags, delete policy, and optional schedule.

{% include media.html type="video"
                      title="Create a file sync walkthrough"
                      poster="video-posters/guide-create-a-file-sync.png"
                      capture="Recording planned. Show create a file sync end to end and explain why this task helps a user." %}

## Why you would use this

Use File Sync when important documents already live in a share or storage container and should stay current without repeated uploads. It replaces manual drag-and-drop for stable repositories; it is the wrong choice for temporary files, unapproved repositories, or sources too broad for the workspace.

## Before you start

- Admins must enable `enable_file_sync` and the target scope toggle: `enable_file_sync_personal`, `enable_file_sync_group`, or `enable_file_sync_public`; see [File Sync settings]({{ '/admin/knowledge/' | relative_url }}).
- The workspace scope must be enabled on [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- You need permission to manage sync sources and a readable credential or **Reusable identity**.

## Steps

1. Open the workspace that should receive synced documents.
2. Choose **Sync** from **Section** or the workspace tabs.
3. Select **Add Sync Source**.

{% include media.html src="guides/create-a-file-sync-step-3.png"
                      alt="The Add Sync Source dialog on the Source Type step, offering SMB Share, Azure Files, and Azure Blob Storage as available source types."
                      title="Create a file sync step 3"
                      capture="Capture the create a file sync task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. On **1. Source Type**, choose **SMB Share**, **Azure Files**, **Azure Blob Storage**, or another available card.
5. Select **Configure Source**.
6. In **General**, enter **Source name** and connection fields such as **UNC path**, **File service URL**, **Share name**, **Container name**, or **Blob prefix**.
7. In **Identity and Authentication**, choose **Reusable identity** or source-local credentials.
8. In **Selection, Subfolders, and Filters**, choose paths, subfolders, patterns, and file types.
9. In **Tags**, choose fixed tags; in **Sync Schedule**, enable **Scheduled sync** only when automatic refresh is wanted.

{% include media.html src="guides/create-a-file-sync-step-9.png"
                      alt="The Configure step of the Add Sync Source dialog for an SMB share, showing source name and UNC path, the reusable identity and authentication choices, and the subfolder and filter selection controls."
                      title="Create a file sync step 9"
                      capture="Capture the create a file sync task at this step in SimpleChat with realistic sample data and redact secrets." %}

10. Select **Test Connection**, then **Add Source** or **Save Source**.

## Verify it worked

The source appears in the Sync list. Imported files later appear on the workspace **Documents** tab with fixed or folder tags.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| No source types are visible | Admins have not made a source type visible | Ask an admin to review File Sync source type visibility. |
| **Include subfolders** is disabled | Recursive sources are disabled by admin policy | Sync a top-level path or ask whether recursion is allowed. |
| **Test Connection** fails | The credential, path, container, or share is wrong | Correct the fields and retest. |

## Related

- [Create and manage tags]({{ '/guides/create-and-manage-tags/' | relative_url }})
- [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }})
- [File Sync settings]({{ '/admin/knowledge/' | relative_url }})
