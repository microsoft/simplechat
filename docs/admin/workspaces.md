---
layout: page
title: "Workspaces settings"
description: "Workspaces controls which workspace types exist, who may create them, and how files move in and out of them through sharing, downloads, and approvals."
section: "Administration"
audience: admin
admin_tab: workspaces
---


# Workspaces settings

## What this group controls

Workspaces decides which of the three workspace types exist in your deployment, who is
allowed to create one, and how a file may leave a workspace once it is in there.

Two things that used to be in this group now live elsewhere, because neither is really a
workspace decision:

- **Maximum File Size** is on [Knowledge > Document Extraction]({{ '/admin/knowledge/#file-size-limit-section' | relative_url }}). It caps chat attachments as well as workspace uploads, and it exists to protect the extraction pipeline.
- **Global Identities** are on [Security > Global Identities]({{ '/admin/security/#workspace-identities' | relative_url }}). They are stored credentials that File Sync sources and actions reuse, and they keep their secrets in Key Vault.

## Why it matters

Workspace types set the default audience for a document. Personal is one person, group is a
named membership, and public is everyone in the organisation. Sharing and downloads then
decide whether a file can leave that audience, which is the point at which a document
management decision becomes a data movement decision.

{% include media.html src="admin-settings/workspaces.png" alt="Screenshot of the Workspaces group in Admin Settings." title="Workspaces settings" %}

{% include media.html type="video" title="Workspaces settings walkthrough" poster="video-posters/admin-workspaces.png" capture="Recording planned. Walk through each tab in the Workspaces group and explain when to change each setting." %}

## Before you change anything

- Decide which workspace types your policy supports before enabling them; a public workspace is readable organisation-wide.
- Assign the `CreateGroups` and `CreatePublicWorkspaces` app roles in the Enterprise App before requiring them, or nobody will be able to create anything.
- Decide the download policy before inviting a broad audience. Turning downloads on later is easier than retracting files that have already left.

## Workspace Types {#workspace-types}

### Personal Workspaces {#personal-workspaces-section}

Every user gets one private space for their own documents, prompts, agents and actions, which
nobody else can reach. The new interface presents it to end users as **My Workspace**; admin
settings and internal references call it the personal workspace.

Turning this off hides the destination and removes the personal scope from chat. Documents
already stored stay in place but become unreachable, so this retires the feature rather than
clearing it.

### Group Workspaces {#group-workspaces-section}

A group is a named membership sharing one document library, prompt set and agent catalogue.
Three separate controls decide who can make one, and they stack:

1. **Group workspaces** must be enabled at all.
2. **Allow Users to Create Groups** can be switched off to freeze the group list without
   disabling existing groups, which is useful during a migration or a review. Off here
   overrides the role requirement entirely.
3. **Require CreateGroups App Role** then narrows creation to holders of that role.

Separately, group agent management can be restricted to the group Owner. Group Admins keep
read access, so they can see what a group's agents are configured to do without being able to
change it.

### Public Workspaces {#public-workspaces-section}

A public workspace is readable by anyone in the organisation without being a member;
membership still controls who can add or change documents. Because publishing here reaches
everybody, requiring the `CreatePublicWorkspaces` role is usually the setting to reach for
before enabling the type broadly.

The end-user display name renames the type wherever users meet it, so it can match what your
organisation already calls this material -- "Knowledge Base" or "Library", for example. Admin
settings and internal references keep saying Public Workspace, so a support conversation
about a setting still resolves to the same words.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Personal Workspaces | Gives every user a private space, shown to end users as My Workspace. | On | `enable_user_workspace`; capability toggle |
| Enable Group Workspaces | Lets users form groups that share a document library, prompts and agents. Gates everything else in the section. | On | `enable_group_workspaces`; capability toggle |
| Allow Users to Create Groups | Off freezes the group list without disabling existing groups, and overrides the role requirement below. | On | `enable_group_creation`; the classic page renders this inverted, as "Disable Group Creation" |
| Require CreateGroups App Role | Narrows group creation to holders of the `CreateGroups` role. | Off | `require_member_of_create_group` |
| Require Owner to Manage Group Agents, Actions and Workflows | Restricts changing a group's agents, actions and workflows to the Owner; Admins keep read access. | Off | `require_owner_for_group_agent_management` |
| Enable Public Workspaces | Adds a workspace type any user in the organisation can read without being a member. | Off | `enable_public_workspaces`; capability toggle |
| End-user display name | Renames the type for end users only, up to 32 characters. Admin settings keep saying Public Workspace. | Empty | `public_workspace_display_name` |
| Require CreatePublicWorkspaces App Role | Narrows public workspace creation to holders of the `CreatePublicWorkspaces` role. | Off | `require_member_of_create_public_workspace` |

## Files & Sharing {#files-sharing}

### File Downloads {#file-download-settings-section}

Downloads return the original uploaded file rather than the extracted text the model reads,
so enabling them turns a workspace into a way to move a file back out of the tenant. That is
why all three scopes default to off.

Group and public downloads are a ceiling rather than an outcome: a group Owner or Admin, or a
public workspace Owner, can still switch downloads off locally. Requiring an assignment
narrows the ceiling further to a named list, which is the usual way to pilot downloads with a
few teams before opening them up. A group or workspace left off that list behaves as though
downloads were never enabled.

### File Sharing {#file-sharing-section}

Lets a user hand a workspace file to another user or workspace from inside the application,
rather than downloading it and sending it on. It is a separate decision from downloads: you
can allow movement within SimpleChat while still refusing to hand out the original file.

### Shared Conversation File Approvals {#shared-conversation-file-approvals-section}

When a participant generates a downloadable file in a conversation they do not own, the file
is written into the owner's storage. Left ungated, that means one participant can put content
into another person's workspace.

With approvals on, the file is created but withheld until an approver releases it: the
conversation owner, or in a group conversation any Owner, Admin or Document Manager. Anything
left unapproved is declined and deleted after three days, so the queue does not accumulate.
It covers CSV, XLSX, DOCX, PDF, JSON and XML; generated images and charts are never held.

#### Settings

| Setting | What it does | Default | Notes |
| --- | --- | --- | --- |
| Enable Personal Workspace Downloads | Lets users retrieve the original uploaded file from their own workspace. | Off | `allow_personal_workspace_file_downloads` |
| Enable Group Workspace Downloads | Permits group downloads. A group Owner or Admin can still disable them locally. | Off | `allow_group_workspace_file_downloads` |
| Require Group Assignment for Downloads | Limits downloads to the groups named below instead of every group. | Off | `require_group_assignment_for_file_downloads` |
| Groups allowed to download | The named groups. A group left off this list cannot offer downloads. | Empty list | `file_download_allowed_group_ids` |
| Enable Public Workspace Downloads | Permits public workspace downloads, which makes originals retrievable by anyone who can see the workspace. | Off | `allow_public_workspace_file_downloads` |
| Require Public Workspace Assignment for Downloads | Limits downloads to the public workspaces named below. | Off | `require_public_workspace_assignment_for_file_downloads` |
| Public workspaces allowed to download | The named public workspaces. | Empty list | `file_download_allowed_public_workspace_ids` |
| Enable File Sharing | Lets a user hand a workspace file to another user or workspace inside the application. | Off | `enable_file_sharing`; capability toggle |
| Require approval for participant-generated files | Holds files a participant generates in someone else's shared conversation until an approver releases them. | On | `require_shared_conversation_file_approval` |

## Common tasks

1. **Pilot downloads with one team.** Enable group workspace downloads, require group assignment, and add the pilot group. Outcome to verify: members of that group see a download option and members of another group do not.
2. **Freeze the group list during a migration.** Turn off Allow Users to Create Groups. Outcome to verify: existing groups keep working and the create action is unavailable to everyone, including role holders.
3. **Rename the public workspace for end users.** Set the end-user display name and reload a user session. Outcome to verify: the new name appears in navigation and chat scope while Admin Settings still reads Public Workspace.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Users cannot create a group workspace | Group workspaces are disabled, group creation is switched off, or the `CreateGroups` role is required and unassigned. | Work down the three controls in order; the first one that is off explains it. |
| A group has downloads enabled but users still cannot download | Group assignment is required and the group is not on the list, or a group Owner disabled downloads locally. | Check the assignment list first, then the group's own setting. |
| A generated file never appears for the recipient | Shared conversation file approvals are on and nobody released it. | Have the conversation owner, or a group Owner, Admin or Document Manager, approve it within three days. |

## Related

- [Administration settings overview]({{ '/admin/' | relative_url }})
- [Knowledge settings]({{ '/admin/knowledge/' | relative_url }})
- [Security settings]({{ '/admin/security/' | relative_url }})
- [Workflow settings]({{ '/admin/workflow/' | relative_url }})
- [Agents & Actions settings]({{ '/admin/agents-actions/' | relative_url }})
