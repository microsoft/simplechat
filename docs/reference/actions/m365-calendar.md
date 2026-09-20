---
layout: page
title: "Microsoft 365 Calendar"
description: "Read calendar context and prepare invitations using delegated Microsoft 365 access."
section: "Reference"
audience: user
version: "0.261.038"
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

Chat offers **Connect Microsoft 365** before model execution when Calendar
consent is missing. Selecting Calendar requests its event, invitation,
timezone, and recipient-lookup permission bundle in one consent flow.
This does not enable invitation capabilities that the action owner disabled.

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

## Review an invitation

Implemented in version: **0.261.038** (`application/single_app/config.py`).

In manual mode, the invitation appears as an action card in Chat as soon as it
is saved, even while the agent's answer is streaming. Review the attendees,
subject, body, start/end time, timezone, location, and Teams option before
selecting **Send**. **Cancel** stops the pending invitation without creating an
event. Approvals and workflow activity can recover the same saved card.

Only the data owner can send or cancel. Another conversation participant or
workflow runner cannot approve on the owner's behalf. Shared viewers receive a
read-only summary without private body or attendee lists.

Delayed mode shows the scheduled time and, while allowed, **Send now** and
**Cancel**. The browser never sends an invitation because its countdown expires
or a historical card is loaded. A lost interactive timer requires renewed
review rather than automatic replay after a restart.

Send rechecks current access and the reviewed revision. Reconnect returns to the
same invitation without rerunning the agent or sending automatically. Concurrent
clicks cannot claim separate deliveries. If Graph may have created the event
but the response was interrupted, the card requires checking Outlook instead of
blindly retrying. Cancel is not a recall of an already-created meeting.

Automatic invitation mode retains its immediate behavior, without a second
Send button. Older unbound pending invitations remain visible and cancellable,
but need to be prepared again for safe confirmation.

## Related

- [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
- [Email action]({{ '/reference/actions/m365-email/' | relative_url }})
- [Legacy Microsoft Graph]({{ '/reference/actions/msgraph/' | relative_url }})
