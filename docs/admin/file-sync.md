---
layout: page
title: "File Sync Settings"
description: "Controls file sync availability, visible connector types, per-scope sync policy, source limits, and source-management access."
section: "Administration"
audience: admin
admin_tab: file-sync
---

## What this tab controls

Controls file sync availability, visible connector types, per-scope sync policy, source limits, and source-management access.

## Why it matters

File Sync imports external repositories into SimpleChat workspaces. It can quickly create many documents, so source counts, schedule intervals, file and byte limits, recursive behavior, and scope restrictions protect the app from accidental ingestion spikes and keep synced data attached to the right owner.

{% include media.html src="admin/file-sync-overview.png" alt="Screenshot of the File Sync settings tab showing file sync tab." title="File Sync tab" capture="Capture the File Sync tab for File Sync tab. Show relevant controls and redact secrets." %}

{% include media.html type="video" title="File Sync settings walkthrough" poster="video-posters/admin-file-sync.png" capture="Recording planned. Walk through every setting on the File Sync tab and explain when to change each one." %}

## Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable File Sync | Enables the File Sync feature so configured external sources can import files into workspaces. | Off | `enable_file_sync`; capability toggle |
| Max Sources | Caps or schedules max sources so the feature stays within expected capacity. | 10 | `file_sync_max_sources_per_scope` |
| Min Schedule Minutes | Caps or schedules min schedule minutes so the feature stays within expected capacity. | 15 | `file_sync_min_schedule_interval_minutes` |
| Max Files Per Run | Caps or schedules max files per run so the feature stays within expected capacity. | 1000 | `file_sync_max_files_per_run` |
| Max GB Per Run | Caps or schedules max gb per run so the feature stays within expected capacity. | 5 GB | `file_sync_max_gb_per_run` |
| Max Concurrent Runs | Caps or schedules max concurrent runs so the feature stays within expected capacity. | 2 | `file_sync_max_concurrent_runs` |
| Allow Recursive Sources | Controls how SimpleChat uses allow recursive sources on this tab. | On | `file_sync_allow_recursive_sources` |
| SMB Share | Available now. | On | `file_sync_visible_source_types` |
| OneDrive | Coming Soon. | Off | `file_sync_visible_source_type_onedrive` |
| On-prem SharePoint | Coming Soon. | Off | `file_sync_visible_source_type_sharepoint_on_prem` |
| Google Workspace | Coming Soon. | Off | `file_sync_visible_source_type_google_workspace` |
| Enable personal sync | Makes personal sync available in the product when its required service and access policy are configured. | On | `enable_file_sync_personal`; capability toggle |
| Admins manage sources only | Controls how SimpleChat uses admins manage sources only on this tab. | Off | `file_sync_personal_admin_only` |
| Require PersonalFileSyncUser App Role | Controls how SimpleChat uses require personalfilesyncuser app role on this tab. | Off | `file_sync_personal_require_app_role` |
| Manage User Sources | Controls how SimpleChat uses manage user sources on this tab. | Not specified in defaults | Runtime UI control |
| Enable group sync | Makes group sync available in the product when its required service and access policy are configured. | On | `enable_file_sync_group`; capability toggle |
| Admins manage sources only | Controls how SimpleChat uses admins manage sources only on this tab. | Off | `file_sync_group_admin_only` |
| Require Group Assignment to Use File Sync | Controls how SimpleChat uses require group assignment to use file sync on this tab. | Off | `require_group_assignment_for_file_sync` |
| File Sync Allowed Group Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `file_sync_allowed_group_ids` |
| Manage Group Sources | Controls how SimpleChat uses manage group sources on this tab. | Not specified in defaults | Runtime UI control |
| Enable public sync | Makes public sync available in the product when its required service and access policy are configured. | Off | `enable_file_sync_public`; capability toggle |
| Admins manage sources only | Controls how SimpleChat uses admins manage sources only on this tab. | Off | `file_sync_public_admin_only` |
| Require Public Workspace Assignment to Use File Sync | Controls how SimpleChat uses require public workspace assignment to use file sync on this tab. | Off | `require_public_workspace_assignment_for_file_sync` |
| File Sync Allowed Public Workspace Ids | Lists the approved IDs, domains, groups, workspaces, or sources that may use this feature. | Empty list | `file_sync_allowed_public_workspace_ids` |
| Manage Public Workspace Sources | Controls how SimpleChat uses manage public workspace sources on this tab. | Not specified in defaults | Runtime UI control |
| Search Groups | Controls how SimpleChat uses search groups on this tab. | N/A (runtime control) | Runtime UI control |
| Search Public Workspaces | Controls how SimpleChat uses search public workspaces on this tab. | N/A (runtime control) | Runtime UI control |

### Run limits

Source, schedule, file, byte, concurrency, and recursive-source limits bound how much external content each run can import. Lower limits protect small deployments; higher limits should follow storage, search, and processing capacity testing.

### Workspace scope controls

Personal, group, and public sync switches decide where synced files may land. Admin-only and assignment options are stronger controls than the global File Sync switch because they determine who can create sources for each scope.

## Before you change anything

- Enable the target workspace scope on the Workspaces tab before enabling sync for that scope.
- Create required app roles or assignment lists before enabling role-gated sync.
- Set source count, schedule, file, byte, and concurrency limits before letting users create sources.

## Common tasks

1. **Enable File Sync within limits.**
    1. Enable **Enable File Sync**.
    2. Set **Max Sources**, **Min Schedule Minutes**, **Max Files Per Run**, **Max GB Per Run**, and **Max Concurrent Runs**.
    3. Decide whether **Allow Recursive Sources** is allowed.
    4. Save before creating sources.
    Outcome to verify: New sync sources inherit safe run limits.

{% include media.html src="admin/file-sync-enable-file-sync-within-limits.png" alt="Screenshot of the File Sync settings tab showing enable file sync within limits." title="File Sync: Enable File Sync within limits" capture="Capture the File Sync tab while performing Enable File Sync within limits. Show the relevant controls and redact secrets." %}

2. **Enable sync for a workspace scope.**
    1. Enable **personal sync**, **group sync**, or **public sync**.
    2. Choose whether **Admins manage sources only** is required.
    3. For personal sync, enable **Require PersonalFileSyncUser App Role** only after assigning it.
    4. Save and verify source creation in that scope.
    Outcome to verify: The selected scope can create sync sources under the chosen policy.

{% include media.html src="admin/file-sync-enable-sync-for-a-workspace-scope.png" alt="Screenshot of the File Sync settings tab showing enable sync for a workspace scope." title="File Sync: Enable sync for a workspace scope" capture="Capture the File Sync tab while performing Enable sync for a workspace scope. Show the relevant controls and redact secrets." %}

3. **Restrict group or public sync targets.**
    1. Enable the group or public assignment requirement.
    2. Use the assignment search control to select allowed groups or public workspaces.
    3. Save and test with an allowed and disallowed target.
    Outcome to verify: Sync source creation is limited to approved targets.

{% include media.html src="admin/file-sync-restrict-group-or-public-sync-targets.png" alt="Screenshot of the File Sync settings tab showing restrict group or public sync targets." title="File Sync: Restrict group or public sync targets" capture="Capture the File Sync tab while performing Restrict group or public sync targets. Show the relevant controls and redact secrets." %}

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| A source type is not selectable | Only visible source types are shown; several listed source types are marked coming soon. | Enable only source types that the UI marks available and supported. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Workspaces]({{ '/admin/workspaces/' | relative_url }})
- [Global Identities]({{ '/admin/workspace-identities/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})
