---
layout: page
title: "Microsoft 365 OneDrive"
description: "Find OneDrive files and ground conversations in their content without a workspace sync."
section: "Reference"
audience: user
version: "0.261.029"
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

## What sharing means

Sharing acknowledgement publishes **retained evidence as well as the answer**
to conversation participants. They can reuse the published snapshot even if
they cannot open the original in OneDrive. New remote searches and downloads
still require the requesting user's delegated access.

Evidence is labeled with source and capture information and follows conversation
retention. Disconnecting Microsoft 365 does not retract an already-published copy.

## Related

- [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
- [SharePoint Online action]({{ '/reference/actions/m365-sharepoint/' | relative_url }})
