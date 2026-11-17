---
layout: page
title: "Reuse a generated file"
description: "Add a file a reply created to a workspace, or turn a generated Markdown file into a PowerPoint deck."
section: "Guides"
audience: user
version: "0.261.445"
---

## What this does

When a reply creates a file, such as a Markdown report or a CSV export, its card in the
conversation offers more than **Download** and **View**. **Add to workspace** saves the file as a
document in a personal, group, or public workspace, where it can be searched and cited like any
other document. **Create PowerPoint** turns a generated Markdown file into a slide deck and
downloads it.

Both are available in the V2 interface and in classic chat, where the first is named
**Add to Workspace**.

## Why you would use this

A generated file stays inside the conversation that made it. Add it to a workspace when other
chats, or other people, should be able to ground answers in it. Create a PowerPoint when a
generated outline or report is really the first draft of a presentation, so you do not have to
copy it into slides yourself.

## Before you start

- The file must be finished. A background export that is still running, or a file waiting for
  the conversation owner's approval, offers neither action.
- To add a file to a workspace, that kind of workspace must be turned on:
  `enable_user_workspace`, `enable_group_workspaces`, or `enable_public_workspaces`. See
  [Workspaces]({{ '/admin/workspaces/' | relative_url }}).
- For a group or public workspace you need a role that can add documents there, and the workspace
  must currently allow uploads. Group workspaces accept files from Owners, Admins, Document
  Managers and Users; public workspaces accept them from Owners, Admins and Document Managers.

## Steps

### Add a file to a workspace

1. Open the conversation that produced the file and find its card.
2. Select **Add to workspace**.
3. Read where the file will be saved. A personal conversation offers your personal workspace. A
   group or public conversation offers that group or public workspace and says the file becomes
   available once one of its approvers accepts the request. If the conversation does not name its
   workspace, you choose from your own.
4. Select **Add to Personal**, **Submit to Group**, **Submit to Public**, or **Add to selected
   workspace**.

The card then shows **Added to workspace** for your personal workspace, or **Pending approval**
for a group or public workspace. A group or public copy appears in the workspace once an approver
accepts it. See [Review approval requests]({{ '/guides/review-approval-requests/' | relative_url }}).

### Create a PowerPoint from a Markdown file

1. Find the card of a generated Markdown file.
2. Select **Create PowerPoint**.
3. Wait while the slides are planned, which can take a minute. A message tells you the deck is
   being built, and the button shows **Creating**.
4. Your browser downloads the `.pptx` file.

The deck is built from the stored file, not from the reply's text, so it reflects the whole
document. Diagrams in the file are drawn into the slides.

## Verify it worked

A personal copy shows **Added to workspace** on the card and appears in your workspace documents
after processing. A group or public request shows **Pending approval** until a reviewer acts. A
PowerPoint shows "Markdown artifact exported as PowerPoint." and the file lands in your downloads.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| **Add to workspace** is missing | The file is still being generated, is waiting for approval, the conversation has not finished loading, or that kind of workspace is turned off | Wait for the file or the approval, or ask an admin about the workspace setting. |
| **Create PowerPoint** is missing | The file is not Markdown, is a spreadsheet export, or you are in a shared conversation | Use a Markdown file in your own conversation. |
| The dialog says you are not permitted to publish | Your role in the group or public workspace cannot add documents, or the workspace does not currently allow uploads | Ask the workspace owner, or choose another workspace. |
| The card says the publication could not be fully confirmed | The server could not confirm that every step of the publication finished | Select **Check again**. It returns the existing publication and does not create a second copy. |
| "PowerPoint export failed" | The server could not build the deck, for example because the file or reply is no longer available | Try again; if it keeps failing, refresh the conversation and retry. |
| **Add to workspace** reappears after you reload the page | The card remembers what it did only while the page is open | Select it again. The server returns the publication that already exists rather than adding another. |

## Related

- [Create files with orchestration]({{ '/guides/create-files-with-orchestration/' | relative_url }})
- [Upload and manage documents]({{ '/guides/upload-and-manage-documents/' | relative_url }})
- [Review approval requests]({{ '/guides/review-approval-requests/' | relative_url }})
- [Chat interface controls]({{ '/reference/chat-controls/#generated-file-actions-v2-interface' | relative_url }})
