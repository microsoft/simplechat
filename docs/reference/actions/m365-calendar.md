---
layout: page
title: "Microsoft 365 Calendar"
description: "Read calendar context and prepare invitations using delegated Microsoft 365 access."
section: "Reference"
audience: user
version: "0.261.029"
---

<!-- action-slug: m365-calendar -->

## What this action does

Microsoft 365 Calendar gives an agent calendar events, mailbox time zone, and
invitation capabilities without also granting it Email, OneDrive, or SharePoint
tools. Interactive requests use the person asking, not the agent's creator.

Use it to discuss upcoming meetings or prepare an invitation. Calendar writes
keep their configured manual, delayed, or automatic delivery behavior; permission
to share calendar context does not replace invitation approval.

## Configure and use

Create a **Microsoft 365 Calendar** action, enable the required capabilities,
and assign it to an agent. Choose conservative invitation delivery settings if
users should review invitations before sending.

Microsoft Entra consent is separate from SimpleChat's sharing acknowledgement.
In a shared conversation, the acknowledgement explains that calendar context
may be disclosed to participants. The action's maximum acknowledgement duration
can be shorter than the user's saved preference.

Example: "What meetings do I have tomorrow, and prepare an invitation for the
project review without sending it yet."

## Workflow identity

A workflow uses its explicitly approved **Microsoft 365 Run as** account for
both manual and scheduled runs. Connecting that account in Profile does not
automatically authorize a workflow. Material workflow changes require renewed
approval from the account holder.

## Related

- [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
- [Email action]({{ '/reference/actions/m365-email/' | relative_url }})
- [Legacy Microsoft Graph]({{ '/reference/actions/msgraph/' | relative_url }})
