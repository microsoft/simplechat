---
layout: page
title: "Create and manage tags"
description: "Create colored workspace tags and apply them to documents."
section: "Guides"
audience: user
---

## What this does

Tags are workspace labels that organize documents and create filtered source sets for chat. This guide creates a tag and applies it to documents.

{% include media.html type="video"
                      title="Create and manage tags walkthrough"
                      poster="video-posters/guide-create-and-manage-tags.png"
                      capture="Recording planned. Show create and manage tags end to end and explain why this task helps a user." %}

## Why you would use this

Use tags when folders and file names are not enough: a document can belong to a project, phase, customer, or review set without being moved. Tags replace brittle naming conventions and long manual selections, but they are not access control.

## Before you start

- The workspace type must be enabled with `enable_user_workspace`, `enable_group_workspaces`, or `enable_public_workspaces`; see [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- You need permission to manage documents in the workspace.
- Upload or sync at least one document if you want to assign the tag immediately.

## Steps

1. Open **Personal Workspace**, **Group Workspace**, or **Public Workspaces**.
2. Open the **Documents** tab.
3. Select **Manage Tags**.

{% include media.html src="guides/create-and-manage-tags-step-3.png"
                      alt="Screenshot showing create and manage tags step 3."
                      title="Create and manage tags step 3"
                      capture="Capture the create and manage tags task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. In **Manage Workspace Tags**, enter a name in **Tag name (lowercase, alphanumeric)**.
5. Pick a **Color** and select **Add**.
6. To tag several documents, select **Multi-select** and choose documents.
7. Use **Tag Assignment** or **Tag Selected**.

{% include media.html src="guides/create-and-manage-tags-step-7.png"
                      alt="Screenshot showing create and manage tags step 7."
                      title="Create and manage tags step 7"
                      capture="Capture the create and manage tags task at this step in SimpleChat with realistic sample data and redact secrets." %}

8. Choose **Add Tags (append to existing)**, **Remove Tags (remove specific tags)**, or **Replace All Tags (overwrite existing)**, then select **Apply to Selected Documents**.

## Verify it worked

The tag appears in **Existing Tags** with a count after assignment. **Folders**, **Folders + Cards**, and **Filter by Tags** can use it.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The tag name changes after typing | Tag names are normalized to allowed characters | Use lowercase letters, numbers, hyphens, or underscores. |
| A tag count is zero | The tag exists but is not assigned | Use **Multi-select** and tag assignment to apply it. |

## Related

- [Use tags in chat]({{ '/guides/use-tags-in-chat/' | relative_url }})
- [Use tags on conversations]({{ '/guides/use-tags-on-conversations/' | relative_url }})
- [Create a file sync]({{ '/guides/create-a-file-sync/' | relative_url }})
