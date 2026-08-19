---
layout: page
title: "Workspaces Settings"
description: "Controls personal, group, and public workspace availability, downloads, workflows, file uploads, metadata, classification, retention, and agreements."
section: "Administration"
audience: admin
admin_tab: workspaces
---

## What this tab controls

Controls personal, group, and public workspace availability, downloads, workflows, file uploads, metadata, classification, retention, and agreements.

## Why it matters

Workspace settings define the tenant's data boundaries: personal, group, public, workflow, file download, retention, classification, and agreement behavior. Enabling a scope creates new places where documents and conversations can live; disabling or role-gating a scope changes what users can see or create. Retention and download settings directly affect compliance and data-loss risk.

{% include media.html src="admin-settings/workspaces.png" alt="Screenshot of the Workspaces settings tab showing controls for personal, group, and public workspaces, uploads, workflows, metadata, retention, and agreements." title="Workspaces settings tab" %}

{% include media.html type="video" title="Workspaces settings walkthrough" poster="video-posters/admin-workspaces.png" capture="Recording planned. Walk through every setting on the Workspaces tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Personal Workspaces | Makes personal workspaces available in the product when its required service and access policy are configured. | On | `enable_user_workspace`; capability toggle |
| Enable Personal Workflows | Permits enable personal workflows when the related workspace or agent feature is enabled. | Off | `allow_user_workflows` |
| Require WorkflowUser App Role | Requires the `WorkflowUser` app role before users can use this capability or view. | Off | `require_member_of_workflow_user` |
| Workflow Agent Action Limit | Maximum automatic tool or action calls an agent can make during one workflow run. Default is 60; increase for large document sets. | 60 | `workflow_max_auto_invoke_attempts` |
| Workflow Task Limit | Maximum ordered instruction tasks users can add to one workflow. Default is 50; supported range is 1-100. | 50 | `workflow_max_tasks` |
| Enable Group Workflows | Permits enable group workflows when the related workspace or agent feature is enabled. | Off | `allow_group_workflows` |
| Require Group Assignment to Use Workflow | Controls how SimpleChat uses require group assignment to use workflow on this tab. | Off | `require_group_assignment_for_group_workflows` |
| Group Workflow Allowed Group Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `group_workflow_allowed_group_ids` |
| Enable Personal Workspace Downloads | Permits enable personal workspace downloads when the related workspace or agent feature is enabled. | Off | `allow_personal_workspace_file_downloads` |
| Enable Group Workspace Downloads | Permits enable group workspace downloads when the related workspace or agent feature is enabled. | Off | `allow_group_workspace_file_downloads` |
| Require Group Assignment for Downloads | Controls how SimpleChat uses require group assignment for downloads on this tab. | Off | `require_group_assignment_for_file_downloads` |
| File Download Allowed Group Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `file_download_allowed_group_ids` |
| Enable Public Workspace Downloads | Permits enable public workspace downloads when the related workspace or agent feature is enabled. | Off | `allow_public_workspace_file_downloads` |
| Require Public Workspace Assignment for Downloads | Controls how SimpleChat uses require public workspace assignment for downloads on this tab. | Off | `require_public_workspace_assignment_for_file_downloads` |
| File Download Allowed Public Workspace Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `file_download_allowed_public_workspace_ids` |
| Search Groups | Controls how SimpleChat uses search groups on this tab. | N/A (runtime control) | Runtime UI control |
| Search Groups | Controls how SimpleChat uses search groups on this tab. | N/A (runtime control) | Runtime UI control |
| Search Public Workspaces | Controls how SimpleChat uses search public workspaces on this tab. | N/A (runtime control) | Runtime UI control |
| Enable Group Workspaces | Makes group workspaces available in the product when its required service and access policy are configured. | On | `enable_group_workspaces`; capability toggle |
| Disable Group Creation | Makes disable group creation available in the product when its required service and access policy are configured. | Off | Inverse of `enable_group_creation` |
| Require CreateGroups App Role | Requires the `CreateGroups` app role before users can use this capability or view. | Off | `require_member_of_create_group` |
| Require Owner to Manage Group Agents, Actions and Workflows | Controls how SimpleChat uses require owner to manage group agents, actions and workflows on this tab. | Off | `require_owner_for_group_agent_management` |
| Enable Public Workspaces | Makes public workspaces available in the product when its required service and access policy are configured. | Off | `enable_public_workspaces`; capability toggle |
| End-user display name | Optional. End users will see this label instead of Public Workspace. Admin settings and internal references continue to use Public Workspace. | Empty | `public_workspace_display_name` |
| Require CreatePublicWorkspaces App Role | Requires the `CreatePublicWorkspaces` app role before users can use this capability or view. | Off | `require_member_of_create_public_workspace` |
| Enable File Sharing | Makes file sharing available in the product when its required service and access policy are configured. | Off | `enable_file_sharing`; capability toggle |
| Enable Chat File Uploads | Makes chat file uploads available in the product when its required service and access policy are configured. | On | `enable_chat_file_uploads`; capability toggle |
| Enable Conversation Contents Drawer | Makes conversation contents drawer available in the product when its required service and access policy are configured. | On | `enable_conversation_contents_drawer`; capability toggle |
| Collaborative conversations | Enables shared conversation records and collaboration endpoints so permitted users can create and participate in collaborative conversations instead of only single-user conversation threads. | On | `enable_collaborative_conversations`; no visible field in `admin_settings.html` |
| Require ChatFileUploadUser App Role | Requires the `ChatFileUploadUser` app role before users can use this capability or view. | Off | `require_member_of_chat_file_upload_user` |
| Enable Extract Meta Data | Makes extract meta data available in the product when its required service and access policy are configured. | Off | `enable_extract_meta_data`; capability toggle |
| Extraction Model | Chooses the model or deployment SimpleChat uses for extraction model. | Empty | `metadata_extraction_model` |
| Enable Multi-Modal Vision Analysis | Makes multi-modal vision analysis available in the product when its required service and access policy are configured. | Off | `enable_multimodal_vision`; capability toggle |
| Vision Model * | Select a GPT model with vision capabilities (for example, gpt-4o or supported GPT 5 and later models). Only vision-capable models are shown. | Empty | `multimodal_vision_model` |
| Enable Document Classification | Makes document classification available in the product when its required service and access policy are configured. | Off | `enable_document_classification`; capability toggle |
| Enable for Personal Workspaces | Makes for personal workspaces available in the product when its required service and access policy are configured. | Off | `enable_retention_policy_personal`; capability toggle |
| Enable for Group Workspaces | Makes for group workspaces available in the product when its required service and access policy are configured. | Off | `enable_retention_policy_group`; capability toggle |
| Enable for Public Workspaces | Makes for public workspaces available in the product when its required service and access policy are configured. | Off | `enable_retention_policy_public`; capability toggle |
| Conversation Retention | Controls how SimpleChat uses conversation retention on this tab. | none | `default_retention_conversation_personal` |
| Document Retention | Controls how SimpleChat uses document retention on this tab. | none | `default_retention_document_personal` |
| Conversation Retention | Controls how SimpleChat uses conversation retention on this tab. | none | `default_retention_conversation_group` |
| Document Retention | Controls how SimpleChat uses document retention on this tab. | none | `default_retention_document_group` |
| Conversation Retention | Controls how SimpleChat uses conversation retention on this tab. | none | `default_retention_conversation_public` |
| Document Retention | Controls how SimpleChat uses document retention on this tab. | none | `default_retention_document_public` |
| Scheduled Execution Time (Hour of Day) | Retention policy will run once daily at this hour (UTC timezone). | 2 | `retention_policy_execution_hour` |
| Enforce Workspace Scope Lock | Controls how SimpleChat uses enforce workspace scope lock on this tab. | On | `enforce_workspace_scope_lock` |
| Enable User Agreement | Makes user agreement available in the product when its required service and access policy are configured. | Off | `enable_user_agreement`; capability toggle |
| Personal Workspaces | Controls how SimpleChat uses personal workspaces on this tab. | On | `user_agreement_apply_personal` |
| Group Workspaces | Controls how SimpleChat uses group workspaces on this tab. | On | `user_agreement_apply_group` |
| Public Workspaces | Controls how SimpleChat uses public workspaces on this tab. | On | `user_agreement_apply_public` |
| Chat | Controls how SimpleChat uses chat on this tab. | Off | `user_agreement_apply_chat` |
| Agreement Text * (Markdown supported) | Controls the user-facing copy or name shown for agreement text * (markdown supported). | Empty | `user_agreement_text` |
| Allow users to accept once per day | Makes allow users to accept once per day available in the product when its required service and access policy are configured. | Off | `enable_user_agreement_daily`; capability toggle |

### Retention policy

Retention settings define default cleanup windows for conversations and documents by workspace type. Use `none` when users or workspace owners control retention manually; choose day-based defaults only after confirming records policy.

### User agreement

The user agreement can apply to personal, group, public, and chat surfaces. Use it when users need to acknowledge workspace-specific handling terms, and decide whether daily reacceptance is required before enabling it.

### Role-gated workspace actions

Role requirements such as CreateGroups, CreatePublicWorkspaces, WorkflowUser, and ChatFileUploadUser restrict capabilities after sign-in. Assign the Entra app roles before enabling the corresponding requirement to avoid blocking intended users.

### Collaborative conversations

`enable_collaborative_conversations` is enforced by collaboration backend routes rather than a visible field in `admin_settings.html`. When it is on, SimpleChat can use the collaboration conversation, message, and user-state containers. Turning it off blocks collaboration endpoints, so verify existing collaborative conversations and user expectations before disabling it.

## Before you change anything

- Decide which scopes are allowed: personal, group, public, workflows, and chat uploads.
- Create Entra app roles before enabling requirements such as `CreateGroups`, `CreatePublicWorkspaces`, `WorkflowUser`, or `ChatFileUploadUser`.
- Review retention requirements before setting default document or conversation retention.
- Configure embeddings, AI Search, and Document Intelligence before promoting document-heavy workspace use.

## Common tasks

1. **Enable workspace scopes.**
    1. Enable **Personal Workspaces**, **Group Workspaces**, or **Public Workspaces** according to policy.
    2. For public workspaces, set **End-user display name** if the tenant uses another label.
    3. Save and verify navigation with a normal user account.
    Outcome to verify: Only approved workspace scopes appear.

{% include media.html src="admin/workspaces-enable-workspace-scopes.png" alt="Screenshot of the Workspaces settings tab showing enable workspace scopes." title="Workspaces: Enable workspace scopes" capture="Capture the Workspaces tab while performing Enable workspace scopes. Show the relevant controls and redact secrets." %}

2. **Restrict creation and upload actions.**
    1. Create the needed Entra app roles first.
    2. Enable **Require CreateGroups App Role**, **Require CreatePublicWorkspaces App Role**, **Require WorkflowUser App Role**, or **Require ChatFileUploadUser App Role**.
    3. Save and test with one assigned and one unassigned user.
    Outcome to verify: Role-gated actions are available only to assigned users.

{% include media.html src="admin/workspaces-restrict-creation-and-upload-actions.png" alt="Screenshot of the Workspaces settings tab showing restrict creation and upload actions." title="Workspaces: Restrict creation and upload actions" capture="Capture the Workspaces tab while performing Restrict creation and upload actions. Show the relevant controls and redact secrets." %}

3. **Set retention defaults.**
    1. Enable retention for personal, group, or public workspaces.
    2. Choose conversation and document retention defaults for each enabled scope.
    3. Set **Scheduled Execution Time**.
    4. Save and review workspace retention behavior.
    Outcome to verify: New defaults match the retention policy.

{% include media.html src="admin/workspaces-set-retention-defaults.png" alt="Screenshot of the Workspaces settings tab showing set retention defaults." title="Workspaces: Set retention defaults" capture="Capture the Workspaces tab while performing Set retention defaults. Show the relevant controls and redact secrets." %}

4. **Enable user agreements.**
    1. Enable **User Agreement**.
    2. Choose where it applies: personal, group, public, and/or chat.
    3. Enter **Agreement Text**.
    4. Decide whether **Allow users to accept once per day** is needed.
    Outcome to verify: Users see the agreement on the selected surfaces.

{% include media.html src="admin/workspaces-enable-user-agreements.png" alt="Screenshot of the Workspaces settings tab showing enable user agreements." title="Workspaces: Enable user agreements" capture="Capture the Workspaces tab while performing Enable user agreements. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Users cannot create groups | Group creation is disabled or the CreateGroups role requirement is enabled. | Enable group creation or assign the CreateGroups app role. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [File Sync]({{ '/admin/file-sync/' | relative_url }})
- [Search and Extract]({{ '/admin/search-extract/' | relative_url }})
- [Citations]({{ '/admin/citation/' | relative_url }})
