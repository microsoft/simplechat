---
layout: page
title: "Manage group workspaces"
description: "Use group workspaces for shared documents, prompts, agents, actions, and workflows."
section: "Guides"
audience: user
---

## What this does

Group workspaces are shared spaces for team documents and reusable AI assets. This guide helps you find or create a group, select it, and use the available workspace tabs.

{% include media.html type="video"
                      title="Manage group workspaces walkthrough"
                      poster="video-posters/guide-manage-group-workspaces.png"
                      capture="Recording planned. Show manage group workspaces end to end and explain why this task helps a user." %}

## Why you would use this

Use a group workspace when a team needs common source documents, prompts, agents, and workflows instead of each person maintaining copies. It keeps shared material in one place and lets owners manage contribution; use personal workspaces for private drafts.

## Before you start

- Admins must enable `enable_group_workspaces`; creating groups also depends on `enable_group_creation` and may require `require_member_of_create_group`; see [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- You need group membership or permission to create/find groups from Profile.
- Tabs such as **Sync**, **Workflows**, **Agents**, and **Actions** require their own admin toggles.

## Steps

1. Open **Profile** and choose **Groups** when you need to create or find a group.
2. Use **Create Group** when permitted, or **Find Group** to locate an existing group.
3. Open **Group Workspaces**.

{% include media.html src="guides/manage-group-workspaces-step-3.png"
                      alt="Screenshot showing manage group workspaces step 3."
                      title="Manage group workspaces step 3"
                      capture="Capture the manage group workspaces task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Select the active group from the group selector.
5. Use **Documents** to upload, filter, tag, and chat with shared files.

{% include media.html src="guides/manage-group-workspaces-step-5.png"
                      alt="Screenshot showing manage group workspaces step 5."
                      title="Manage group workspaces step 5"
                      capture="Capture the manage group workspaces task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. Use **Prompts**, **Sync**, **Workflows**, **Agents**, or **Actions** when those tabs are enabled and your role allows them.

## Verify it worked

The active group name appears, documents load for that group, and group-scoped assets are visible only when the selected group and your role allow them.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Users cannot create groups | Group creation is disabled or the `CreateGroups` role is required | Ask an admin to enable group creation or assign the role. |
| The Sync tab is missing | Group File Sync is disabled | Ask an admin to enable `enable_file_sync` and `enable_file_sync_group`. |

## Related

- [Create a file sync]({{ '/guides/create-a-file-sync/' | relative_url }})
- [Create an agent with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
