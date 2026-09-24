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

## Use group workspaces in V2

The shared V2 shell was implemented in version **0.261.127**. It uses the same
grouped navigation and overview as My Workspace.

Open **Group Workspaces**, then choose a group in **Group workspace**. Selection
makes that group active and loads its name, description, owner, role, status,
and available sections. Your saved active group is restored on a later visit.
If no valid selection exists, the page asks you to choose rather than selecting
an arbitrary group.

**Search your groups** searches the full membership list, not just the displayed
page. A selected group stays selected when searching or changing result pages.
Section URLs include the group ID, so a bookmark opens the intended group.

### Browse group documents

Native document browsing is available from version **0.261.128**, with
permission-aware document management added in **0.261.129**.
Choose **Documents** to search by filename/title, use shared-workspace tags and
classification filters, sort results, and page through the group's sources.
Counts describe the whole visible workspace rather than the current page.

Inspect a document for available metadata, its owning/shared-group relationship,
processing or screening status, and **Version history**. Pending shares and held
sources remain restricted and cannot be selected for chat. On narrow screens,
use **Filters** and the details toggle to open the same controls in dialogs.

Select eligible documents and choose **Chat** to carry their group/document
context into the existing chat experience. Current access is checked again
before those sources are adopted. This does not create a group-only retrieval
mode or override an existing conversation's workspace lock.

### Manage group files and tags

Owners, Admins, and DocumentManagers can use the available upload, metadata,
tag, extraction, reprocessing, deletion, and download commands. Each command
also depends on group status and the selected files; readable incoming shares
are not editable source documents. Ordinary User membership stays read-only.
On compact screens, **Actions** holds selected-file commands while Upload and
Filters stay directly reachable.

Use **Tags** to create, rename, recolour, or remove the group's vocabulary.
Changes apply to current documents owned by that group, not historical
revisions or incoming shared sources. If propagation or a vocabulary update
only partly succeeds, the old vocabulary can remain until the reported
failures are resolved.

Review each upload/bulk result. Queued extraction or metadata screening is not
finished processing, and a partial outcome is not an instruction to retry the
successful items. Failed metadata saves keep the draft.

Before deleting, confirm the selected files and whether the operation covers
only the current revision or every version. Files managed by sync or linked
to conversations can require additional explicit choices. Historical or
restricted content does not acquire ordinary editing rights merely because it
is visible in the explorer.

Share a document with another group, withdraw a share, accept a document
another group shared with yours, or remove your group's access from the same
explorer (version **0.261.131**). A generated file that a member asked to
publish into the group waits for an owner-side decision, and reviewers approve,
reject or cancel it without leaving the workspace. Group-specific saved views
and content previews remain deferred.

### Prompts, actions, and agents

These sections use the same editors as My Workspace. Each one reads and saves
through the selected group, never through whichever group your account last
made active.

- **Prompts** (version **0.261.136**). Owners, Admins, and DocumentManagers
  create, edit, duplicate, and delete the group's prompts while the group is
  active. Everyone in the group can read them and use them in chat. Rewording a
  group prompt in the chat composer applies to that one message and never
  changes the saved prompt.
- **Actions** (version **0.261.137**). Owners and Admins create, edit, test,
  and delete group actions. When an administrator requires it, only the Owner
  can. Everyone else sees read-only details. Actions provided by an
  administrator appear as **Provided · Read only**. From version **0.261.139**
  an action can use one of the group's reusable identities. Saved MCP
  preconfigurations cannot yet be chosen in the group action editor.
- **Agents** (version **0.261.138**). Owners and Admins create, edit, and delete
  group agents, under the same owner-only rule. Everyone in the group can open
  an agent and use it in chat. **Use in chat** opens the agent in its own
  group. An agent's model list, assigned knowledge, actions, and instruction
  drafting are all resolved for the selected group. The model list holds the
  administrator's connections you may use, plus the group's own when allowed.
  Discovery of agents behind a group-scoped Foundry connection is not available
  yet; enter those project fields manually.

If two people edit the same prompt, action, or agent at once, the second save
is refused and the editor keeps your changes, so you can reload and reapply
them. When group agents are turned off for your organization, the Agents
section is not offered. When only group actions are off, **Actions** keeps the
**Call agent** manager.

### Identities

From version **0.261.139**, Owners, Admins, and DocumentManagers manage the
group's reusable identities in **Identities**. These are the credentials that
File Sync sources and actions use. Stored secrets are never shown; enter a new
value to replace one. A new value only takes effect when the save succeeds. You
cannot delete an identity while a File Sync source or an action still uses it:
the editor lists what uses it, so you can move those to another identity first.
Ordinary members do not see identities.

### Use group tools and manage the workspace

Use **Workflows** for the native workflow editor and run history. From version
**0.261.141**, workflow managers can also set a group workflow to run when File
Sync finds changes, or to sync first before each run. Alert settings appear
read-only; see [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }}).
**Sync** and **Endpoints** are marked **Classic** while their native V2
experiences are being built. **Open classic group workspace** confirms the
selected group before navigating; choose the relevant classic tab there.
Owners and administrators also have **Manage group (classic)** for members,
join requests, and group settings.

Save or cancel open changes before switching groups. Navigating away from an
unfinished editor asks whether to discard it. Returning to the browser refreshes
workspace access without replacing a retained draft on a temporary failure.
If access cannot be confirmed, saving is disabled until refresh succeeds.
Revoked membership removes the cached workspace content.

If another tab changes the active group, the current page keeps its explicit
group and explains the difference. **Make this group active** selects it again.
After an uncertain switch, use **Refresh workspace selection** to reconcile the
server's selection without repeating the change.

File Sync sources, model endpoints, group membership administration, group
settings, and public workspace pages still use the classic interface.

## Use the classic workspace

1. Open **Profile** and choose **Groups** when you need to create or find a group.
2. Use **Create Group** when permitted, or **Find Group** to locate an existing group.
3. Open **Group Workspaces**.

{% include media.html src="guides/manage-group-workspaces-step-3.png"
                      alt="The Group Workspace page showing the active group banner, the group selector with the viewer's role, and the Documents, Prompts, Identities, Sync, Actions, Agents, and Workflows tabs."
                      title="The group workspace and its tabs"
                      capture="Capture the manage group workspaces task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. Select the active group from the group selector.
5. Use **Documents** to upload, filter, tag, and chat with shared files.

{% include media.html src="guides/manage-group-workspaces-step-5.png"
                      alt="The group Documents tab with search and filter fields expanded, showing filters for file name, author, keywords, abstract, and tags above the shared document list."
                      title="Filtering shared group documents"
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
