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

## Steps

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
                      alt="Screenshot showing use public workspaces step 5."
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
