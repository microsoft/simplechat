---
layout: page
title: "Microsoft 365 SharePoint Online"
description: "Retrieve SharePoint document evidence through the user's delegated permissions."
section: "Reference"
audience: user
version: "0.261.303"
---

<!-- action-slug: m365-sharepoint -->

## What this action does

Microsoft 365 SharePoint Online brings document-library content into an agent's
conversation without group file sync. New searches and reads use the person's
delegated access, rather than an application identity that might read more
than that person can.

This action covers document-library files, not SharePoint Server, site pages,
or general list rows. It searches accessible SharePoint content unless the
request narrows it to a folder or file. There is no action-level site allowlist.
Source attribution uses **SPO**.

## Search, evidence, and citations

Copilot Retrieval is preferred where the API is supported and the user has a
verified Microsoft 365 Copilot license. It supplies relevant text extracts,
not necessarily an entire document. Ordinary Graph search and file retrieval
are used for other supported deployments and users. No PAYG request is made.

Government L4/L5 use the Graph path; custom clouds use their configured
authority and endpoints. An unavailable API never causes a request to be sent
to a different cloud.

Example: "Search the Engineering site's Release Notes folder for the rollback
procedure and explain the prerequisites."

Large or multi-file analysis can require an explicit deeper-analysis decision.
Progress and captured evidence are retained with the conversation so analysis
can proceed in stages. A faster answer identifies omitted coverage rather than
claiming to have read everything.

### Citations and Open online

Implemented in version: **0.261.303** (`application/single_app/config.py`).

Every file a search, capture or read returns carries a citation value, so the
answer cites a SharePoint file the same way it cites a workspace document: a
chip after the claim, showing the file name. The chip's card shows the location,
modified date and size, and **Open in SharePoint** opens the file in SharePoint
with the reader's own permissions. Nothing is downloaded from the card.

Cited files, and every file whose content was captured or read for an answer,
are listed under **SharePoint & OneDrive** in the conversation's **Documents**
pane with **Open online**. A list of files uses one line per file:
"**File name** — SharePoint, modified Sep 1, 2026", followed by its chip. This
applies in chat with an agent and in orchestrated answers. See
[Microsoft 365 Source Citations]({{ '/explanation/features/M365_SOURCE_CITATIONS/' | relative_url }}).

## Permission and disclosure boundaries

Source access, SimpleChat sharing approval, and approval for additional analysis
are different decisions. A denied source read is not retried with application
credentials or another user's identity.

Once sharing is approved, retained evidence and answers become conversation
snapshots readable by its participants, even if some lack the original
SharePoint permission. Revoking source access stops new reads but does not
delete those published copies. Sharing a previously private conversation also
requires acknowledgement of this disclosure.


## V2 action configuration

The V2 editor registers this as a native Microsoft 365 action instead of relying on the legacy Microsoft Graph action. Capability switches come from the action catalogue and are stored under `additionalFields.m365_capabilities`, so owners can expose only the calendar, email, file, or site operations this action needs.

The Microsoft Graph endpoint is read-only and derived from the deployment cloud: commercial deployments use `graph.microsoft.com`, and US Government deployments use `graph.microsoft.us`. Custom cloud endpoint behavior follows the deployment's configured Microsoft 365 runtime instead of being edited per action.

Connection testing appears in **Authentication**, after the delegated or workflow identity choice. The V2 editor no longer offers ad hoc custom fields; preserved legacy values remain available in **Advanced → JSON**.

## Related

- [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
- [OneDrive action]({{ '/reference/actions/m365-onedrive/' | relative_url }})
- [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }})
