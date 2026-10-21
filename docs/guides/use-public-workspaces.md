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

From version **0.261.175**, **Public Workspaces** in V2 opens a directory of
every public workspace you can discover.
- Switch between **All** and **My workspaces** (the ones you own, administer
  or manage documents in), and search by name, description or id.
- **Open** a workspace to go to its page.
- From **0.261.372**, V2 searches every currently available public workspace.
  There are no Visible for chat switches or saved visibility lists in V2.
  Classic keeps its existing choices, but they do not hide sources from V2.
- The directory and the workspace pages use the names your administrator
  gave public workspaces.

The earlier **0.261.355** compatibility fix treats public workspaces created without a stored status
as active in the directory, consistent with chat and workspace
settings. Classic still lets an eligible workspace be made Visible for chat.
V2 no longer requires that step. Explicit inactive or invalid statuses still
prevent using an unavailable workspace.

Public workspace documents open in the same document explorer as My Workspace
and group workspaces, from version **0.261.132**. Open **Public Workspaces** and
choose a workspace. The address includes the workspace, so a bookmark opens the
same one. Choosing a workspace also makes it your active public workspace for
chat, but the page itself never depends on that selection: every request names
the workspace it is for.

From version **0.261.310**, the overview shows counts for available resource
cards, including Documents, Prompts, File sources, Identities, and Members.
Counts cover the complete collection visible to you in the selected workspace,
not the first page of results. Members counts the workspace's Owner, Admins,
and DocumentManagers, not everyone who can read its published content or pending
requests.
Readers who are not on that roster do not get a Members count.

A zero means the collection is empty. Counts remain blank while loading; a small
red circled X means that particular count could not load. Other counts and
navigation keep working. Returning to Overview or refreshing workspace access
reloads them. Locked cards and Settings, Activity, and Statistics stay uncounted.

- **Browse.** Search, filter, sort, and page through the workspace's documents,
  and inspect a document's details and version history. Every member can do
  this.
- **Manage** (version **0.261.133**). Owners, Admins, and DocumentManagers can
  upload files, edit metadata, and tag documents one at a time or in bulk. They
  can also extract metadata, reprocess a document (including changing its
  extraction mode), and delete the current revision or every version.
  Ordinary members can read documents but cannot change them. From version
  **0.261.186**, everyone who can read the workspace can download its documents
  when the administrator allows downloads for it, as in classic; before, only
  Owners, Admins and DocumentManagers could. From version **0.261.167**, an empty workspace tells them who
  can add documents, or why no one can right now, rather than sending them to
  the classic page.
- **Review publish requests** (version **0.261.134**). When someone asks to
  publish a generated file into the workspace, the request waits in the
  explorer. A reviewer approves, rejects, or withdraws it without leaving the
  workspace. From version **0.261.183**, only the Owner, Admins and
  DocumentManagers see a request before it's approved; other readers don't see
  it at all, in V2 or in chat's document picker.

From version **0.261.177**, a public workspace's **Prompts** are in V2 too.
Everyone can read them and use them in chat. Owners, Admins and
DocumentManagers can create, edit and delete them while the workspace is
active. **Use in chat** works even for a workspace you've hidden from chat. The
classic page's prompt changes also need an active workspace from this version.

From version **0.261.179**, the Owner and Admins manage the workspace's
**Members** in V2, under **Manage**: add Admins and DocumentManagers, change
roles, remove members, decide DocumentManager requests, and, for the Owner,
transfer ownership. Nobody can remove themselves. DocumentManagers see members'
names but not their emails. The directory offers **Create** to people allowed
to create public workspaces.

From version **0.261.182**, a workspace's Owner, Admins and DocumentManagers
keep its **Identities** and **Sync** (File Sync sources) in V2, when File Sync
is enabled for the workspace. They can create, edit and delete them, test and
browse connections, and start a sync while the workspace is active. Readers
don't see either section. See
[V2 Public Connections]({{ '/explanation/features/V2_PUBLIC_CONNECTIONS/' | relative_url }}).

From version **0.261.184**, the directory lets you ask to manage a workspace's
documents, and cancel the request, from its row. Its former visibility and
saved-list controls were removed from V2 in **0.261.372**; classic retains them.

The directory's **Chat with all public** action opens a fresh native V2 chat over all
available public workspaces. Open **Documents → Search in** to change its
public-only scope; in Orchestrate, use **Manual controls → Documents** when available.
**All public workspaces** excludes personal and group retrieval. **Current
context** supports mixed personal, group and public sources, with all eligible
public sources discoverable and explicit selections still respected.
Old V2 Visible links reopen as All. **New chat** resets the aggregate scope.
If no workspace qualifies, the request explains the empty scope rather than
searching somewhere else.

From version **0.261.185**, the Owner and Admins manage the workspace's
**Settings** (name, description, color and logo for the Owner; file downloads
and retention for both), read its **Activity**, and chart and export its
**Statistics**, which DocumentManagers can also see, under **Manage**. Deleting
the workspace still happens on the classic page, and removes only the workspace
record: its documents and prompts stay behind. See
[V2 Public Settings]({{ '/explanation/features/V2_PUBLIC_SETTINGS/' | relative_url }}).

Sharing a public document with other workspaces is not available.

From version **0.261.173**, the classic public workspace pages save changes
conditionally. If someone else changes the same workspace at that moment, a
save that can't be applied answers "The public workspace changed while your
request was being saved. Try again." Nothing else is lost, so try again.

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

From version **0.261.347**, chat's **Documents** picker searches public documents
by filename or title across the eligible current revisions before paging the
results. A document does not need a generated title to match its filename.
From **0.261.372**, the ordinary V2 picker ignores classic visibility preferences,
so a processed public guide can be selected alongside personal and group sources
without changing any directory preference. Classic retains its saved visibility
defaults.

If a source request fails, **Documents** and `#` suggestions name the unavailable
source and offer **Retry sources**. Results from successful sources remain usable.
An empty search is not evidence that access was denied.

Document details show **Metadata analysis** separately from content processing.
Failed or empty analysis keeps existing metadata and does not make successfully
indexed content unsearchable. An authorized manager can choose **Retry metadata
analysis** while metadata extraction is enabled. Content screening and generated
artifact approval still determine whether the document's content can be used.

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
