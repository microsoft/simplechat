---
layout: page
title: "Workspaces settings"
description: "Workspaces controls personal, group, and public workspace availability, file downloads, sharing policy, file-size limits, and global identities."
section: "Administration"
audience: admin
admin_tab: workspaces
redirect_from:
  - /admin/workspace-identities/
---


# Workspaces settings

## What this group controls

Workspaces controls personal, group, and public workspace availability, file downloads, sharing policy, file-size limits, and global identities.

## Why it matters

Workspace settings define where documents live and how users can move them. Public workspaces, sharing, and downloads widen the audience for files, so configure them with approval expectations.

{% include media.html src="admin-settings/workspaces.png" alt="Screenshot of the Workspaces group in Admin Settings." title="Workspaces settings" %}

{% include media.html src="admin-settings/global-identity.png" alt="Screenshot of the Workspaces group in Admin Settings." title="Workspaces settings" %}

{% include media.html type="video" title="Workspaces settings walkthrough" poster="video-posters/admin-workspaces.png" capture="Recording planned. Walk through each tab in the Workspaces group and explain when to change each setting." %}

## Before you change anything

- Define which workspace types policy supports.
- Choose file-sharing and download rules before inviting broad groups.
- Create shared identity mappings before connectors depend on them.

## Workspace Types {#workspace-types}

### Personal Workspaces {#personal-workspaces-section}

The Personal Workspaces section belongs to the Workspace Types tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Group Workspaces {#group-workspaces-section}

The Group Workspaces section belongs to the Workspace Types tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Public Workspaces {#public-workspaces-section}

The Public Workspaces section belongs to the Workspace Types tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Personal Workspaces | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_user_workspace`; capability toggle |
| Search Groups | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |
| Search Public Workspaces | Defines behavior for the related admin workflow; verify the affected feature after saving. | N/A (runtime control) | Runtime UI control |
| Enable Group Workspaces | Exposes the capability after required services, permissions, and rollout policy are ready. | On | `enable_group_workspaces`; capability toggle |
| Disable Group Creation | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | Inverse of `enable_group_creation` |
| Require CreateGroups App Role | Requires the `CreateGroups` app role before users can use this capability or view. | Off | `require_member_of_create_group` |
| Require Owner to Manage Group Agents, Actions and Workflows | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `require_owner_for_group_agent_management` |
| Enable Public Workspaces | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_public_workspaces`; capability toggle |
| End-user display name | Optional. End users will see this label instead of Public Workspace. Admin settings and internal references continue to use Public Workspace. | Empty | `public_workspace_display_name` |
| Require CreatePublicWorkspaces App Role | Requires the `CreatePublicWorkspaces` app role before users can use this capability or view. | Off | `require_member_of_create_public_workspace` |
| Enable Extract Meta Data | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_extract_meta_data`; capability toggle |
| Extraction Model | Selects the deployment SimpleChat sends requests to for this capability. | Empty | `metadata_extraction_model` |
| Enable Multi-Modal Vision Analysis | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_multimodal_vision`; capability toggle |
| Vision Model * | Select a GPT model with vision capabilities (for example, gpt-4o or supported GPT 5 and later models). Only vision-capable models are shown. | Empty | `multimodal_vision_model` |

## Files & Sharing {#files-sharing}

### File Downloads {#file-download-settings-section}

The File Downloads section belongs to the Files & Sharing tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### File Sharing {#file-sharing-section}

The File Sharing section belongs to the Files & Sharing tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Shared Conversation File Approvals {#shared-conversation-file-approvals-section}

The Shared Conversation File Approvals section belongs to the Files & Sharing tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

### Maximum File Size {#file-size-limit-section}

The Maximum File Size section belongs to the Files & Sharing tab. Use it with the adjacent settings in this group so related rollout, access, and operational choices stay aligned.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Maximum File Size (MB) | Defines a capacity or timing boundary that keeps the feature inside supported limits. | 150 | `max_file_size_mb` |
| Enable Personal Workspace Downloads | Permits enable personal workspace downloads when the related workspace or agent feature is enabled. | Off | `allow_personal_workspace_file_downloads` |
| Enable Group Workspace Downloads | Permits enable group workspace downloads when the related workspace or agent feature is enabled. | Off | `allow_group_workspace_file_downloads` |
| Require Group Assignment for Downloads | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `require_group_assignment_for_file_downloads` |
| File Download Allowed Group Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `file_download_allowed_group_ids` |
| Enable Public Workspace Downloads | Permits enable public workspace downloads when the related workspace or agent feature is enabled. | Off | `allow_public_workspace_file_downloads` |
| Require Public Workspace Assignment for Downloads | Defines behavior for the related admin workflow; verify the affected feature after saving. | Off | `require_public_workspace_assignment_for_file_downloads` |
| File Download Allowed Public Workspace Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `file_download_allowed_public_workspace_ids` |
| Enable File Sharing | Exposes the capability after required services, permissions, and rollout policy are ready. | Off | `enable_file_sharing`; capability toggle |

## Global Identities {#workspace-identities}

Global Identities is rendered dynamically and does not declare static settings sections in `admin_settings_nav.py`.

No retired-page setting rows mapped to Global Identities; use the live Admin Settings UI to review identity records.

## Common tasks

1. **Enable a workspace type.** Enable the desired scope and create a small test workspace. Outcome to verify: The workspace type appears for the intended audience.
2. **Constrain file movement.** Review download, sharing, approval, and size settings, then test a share. Outcome to verify: Files move only through the allowed path.
3. **Review global identities.** Check identity ownership and test a dependent connector. Outcome to verify: Connector activity uses the expected shared identity.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Users cannot create a group workspace | Group workspaces or group creation are disabled. | Enable the correct workspace controls and retry with an eligible user. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Workflow settings]({{ '/admin/workflow/' | relative_url }})
- [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }})
