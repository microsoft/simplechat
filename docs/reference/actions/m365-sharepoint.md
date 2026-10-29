---
layout: page
title: "Microsoft 365 SharePoint Online"
description: "Retrieve SharePoint document evidence through the user's delegated permissions."
section: "Reference"
audience: user
version: "0.261.029"
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

## Permission and disclosure boundaries

Source access, SimpleChat sharing approval, and approval for additional analysis
are different decisions. A denied source read is not retried with application
credentials or another user's identity.

Once sharing is approved, retained evidence and answers become conversation
snapshots readable by its participants, even if some lack the original
SharePoint permission. Revoking source access stops new reads but does not
delete those published copies. Sharing a previously private conversation also
requires acknowledgement of this disclosure.

## Related

- [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
- [OneDrive action]({{ '/reference/actions/m365-onedrive/' | relative_url }})
- [Create a workflow]({{ '/guides/create-a-workflow/' | relative_url }})
