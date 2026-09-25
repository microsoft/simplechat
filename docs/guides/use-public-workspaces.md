---
layout: page
title: "Use public workspaces"
description: "Browse and manage shared public workspace content when your tenant enables it."
section: "Guides"
audience: user
---

## What this does

Public workspaces make selected documents and prompts available through a shared workspace surface. This guide selects a public workspace, browses documents, and uses filters, tags, and chat actions where your role permits.

{% include media.html type="video"
                      title="Use public workspaces walkthrough"
                      poster="video-posters/guide-use-public-workspaces.png"
                      capture="Recording planned. Show use public workspaces end to end and explain why this task helps a user." %}

## Why you would use this

Use public workspaces for curated materials intended for a broad audience, such as reference libraries, policies, onboarding packs, or published knowledge collections. They reduce duplicate uploads; use group workspaces instead when membership or contribution must be tighter.

## Before you start

- Admins must enable `enable_public_workspaces`; creation may require `require_member_of_create_public_workspace`; see [Workspaces settings]({{ '/admin/workspaces/' | relative_url }}).
- Your role determines whether you can upload, manage prompts, tag documents, or only browse.
- Downloads and File Sync for public workspaces have separate admin controls.

## Use public workspaces in V2

Public workspace documents open in the same document explorer as My Workspace
and group workspaces, from version **0.261.132**. Open **Public Workspaces** and
choose a workspace. The address includes the workspace, so a bookmark opens the
same one. Choosing a workspace also makes it your active public workspace for
chat, but the page itself never depends on that selection: every request names
the workspace it is for.

- **Browse.** Search, filter, sort, and page through the workspace's documents,
  and inspect a document's details and version history. Every member can do
  this.
- **Manage** (version **0.261.133**). Owners, Admins, and DocumentManagers can
  upload files, edit metadata, and tag documents one at a time or in bulk. They
  can also extract metadata, reprocess a document (including changing its
  extraction mode), and delete the current revision or every version.
  Downloads are available to them when the administrator allows downloads for
  the workspace. Ordinary members can read documents but cannot change or
  download them. From version **0.261.167**, an empty workspace tells them who
  can add documents, or why no one can right now, rather than sending them to
  the classic page.
- **Review publish requests** (version **0.261.134**). When someone asks to
  publish a generated file into the workspace, the request waits in the
  explorer. A reviewer approves, rejects, or withdraws it without leaving the
  workspace.

Sharing a public document with other workspaces is not available. Public
prompts and workspace administration (members, roles, ownership, settings,
logo, requests, statistics, and activity) still use the classic page, as do the
directory's visibility preferences and saved visibility lists.

## Use the classic workspace

1. Open **Public Workspaces**.
2. Use **Select a workspace...** to choose the public workspace.
3. Review the role indicator.

{% include media.html src="guides/use-public-workspaces-step-3.png"
                      alt="The Public Workspace Directory listing available public workspaces with per-workspace visibility and Chat buttons, plus controls for saving and loading curated visibility lists."
                      title="Use public workspaces step 3"
                      capture="Capture the use public workspaces task at this step in SimpleChat with realistic sample data and redact secrets." %}

4. On **Documents**, use **Show Search/Filters** to search by file name, title, classification, author, keywords, abstract, or tags.
5. Switch between **List**, **Cards**, **Folders**, and **Folders + Cards** views as needed.

{% include media.html src="guides/use-public-workspaces-step-5.png"
                      alt="A public workspace in Cards view, showing the List, Cards, Folders and Folders + Cards view switcher above document cards that each carry status, version, page count, tags, and Chat and Edit actions."
                      title="Use public workspaces step 5"
                      capture="Capture the use public workspaces task at this step in SimpleChat with realistic sample data and redact secrets." %}

6. If permitted, upload files, select documents, use **Chat with Selected**, or manage prompts from **Prompts**.

## Verify it worked

The selected public workspace shows owner, description, role, documents, and prompts. A chat started with selected documents uses public workspace files as context.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| You cannot upload or manage prompts | Your role does not allow management | Ask the public workspace owner to update your role. |
| Public workspace navigation is missing | Public workspaces are disabled | Ask an admin to enable `enable_public_workspaces`. |

## Related

- [Use tags in chat]({{ '/guides/use-tags-in-chat/' | relative_url }})
- [Create a file sync]({{ '/guides/create-a-file-sync/' | relative_url }})
- [Workspaces settings]({{ '/admin/workspaces/' | relative_url }})
