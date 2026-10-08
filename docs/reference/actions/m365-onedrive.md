---
layout: page
title: "Microsoft 365 OneDrive"
description: "Find OneDrive files and ground conversations in their content without a workspace sync."
section: "Reference"
audience: user
version: "0.261.303"
---

<!-- action-slug: m365-onedrive -->

## What this action does

Microsoft 365 OneDrive searches accessible work or school OneDrive content and
retrieves evidence for an agent's answer. It does not copy files into a
SimpleChat workspace or build another Azure AI Search index.

Use it when a file is already maintained in Microsoft 365 and the question
needs its content, not just a filename listing. A request can identify a
folder or file; action configuration does not impose separate folder allowlists.

## Retrieval and larger files

For supported, verified Copilot-licensed users, Copilot Retrieval returns text
extracts from the existing Microsoft 365 index. Otherwise, delegated Graph
search and content retrieval provide the file path. PAYG is not used.

Small analyses run within the fast windows. When relevant work exceeds those
windows, users can choose deeper analysis or a faster answer with disclosed
coverage limits. Profile has a OneDrive analysis preference independent from
its sharing preference. Deeper analysis stores evidence and checkpoints in
conversation working memory instead of relying on one model context window.

Example: "Find the project proposal in my Planning folder and compare its
milestones with the latest review document."

## Citations and Open online

Implemented in version: **0.261.303** (`application/single_app/config.py`).

Every file a search, capture or read returns carries a citation value, so the
answer cites a OneDrive file with a chip after the claim, showing the file name.
The chip's card shows the location, modified date and size, and **Open in
OneDrive** opens the file in OneDrive with the reader's own sign-in. Nothing is
downloaded from the card.

Cited files, and every file whose content was captured or read for an answer,
are listed under **SharePoint & OneDrive** in the conversation's **Documents**
pane with **Open online**. A list of files uses one line per file:
"**File name** — OneDrive, modified Sep 1, 2026", followed by its chip. See
[Microsoft 365 Source Citations]({{ '/explanation/features/M365_SOURCE_CITATIONS/' | relative_url }}).

## What sharing means

Sharing acknowledgement publishes **retained evidence as well as the answer**
to conversation participants. They can reuse the published snapshot even if
they cannot open the original in OneDrive. New remote searches and downloads
still require the requesting user's delegated access.

Evidence is labeled with source and capture information and follows conversation
retention. Disconnecting Microsoft 365 does not retract an already-published copy.


## V2 action configuration

The V2 editor registers this as a native Microsoft 365 action instead of relying on the legacy Microsoft Graph action. Capability switches come from the action catalogue and are stored under `additionalFields.m365_capabilities`, so owners can expose only the calendar, email, file, or site operations this action needs.

The Microsoft Graph endpoint is read-only and derived from the deployment cloud: commercial deployments use `graph.microsoft.com`, and US Government deployments use `graph.microsoft.us`. Custom cloud endpoint behavior follows the deployment's configured Microsoft 365 runtime instead of being edited per action.

Connection testing appears in **Authentication**, after the delegated or workflow identity choice. The V2 editor no longer offers ad hoc custom fields; preserved legacy values remain available in **Advanced → JSON**.

## Related

- [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
- [SharePoint Online action]({{ '/reference/actions/m365-sharepoint/' | relative_url }})
