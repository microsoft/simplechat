---
layout: page
title: "Microsoft 365 Email"
description: "Read mail and prepare or send messages without enabling unrelated Microsoft 365 tools."
section: "Reference"
audience: user
version: "0.261.038"
---

<!-- action-slug: m365-email -->

## What this action does

Microsoft 365 Email provides mail reading, read-state updates, and message
composition/delivery using delegated access. It does not expose calendar or
file-retrieval tools.

Use it for mailbox context, drafting a response, or marking a message read.
The user must have the Microsoft 365 permissions required by the chosen
operation; a shared conversation never gives participants access to the user's
mailbox credentials.

## Configure and use

Create a **Microsoft 365 Email** action and enable only the operations the agent
needs. Keep **Send mail** separate from reading. Preserve a manual-review
delivery mode where messages must not leave the mailbox without user review.

When consent is missing, Chat offers **Connect Microsoft 365** for the Email
source rather than requiring Profile setup. The source permission bundle
includes mail reads, drafts/read-state changes, sending, and recipient lookup.
Granting it does not enable disabled action capabilities or approve a send.

Example: "Summarize the recent project emails and draft a reply for me to review."

In shared conversations, email results can disclose personal information.
Users acknowledge that disclosure in chat or Approvals. Their source preference
is managed in Profile and is constrained by the action's permitted duration.
This acknowledgement does not authorize a mail send or grant OAuth scopes.

## Failure and approval behavior

If the user declines sharing Email, the agent continues without new Email
access and explains the limitation. Missing Microsoft 365 consent or sign-in
is reported separately; the app never substitutes its own identity.

Workflows use the selected, consenting Run as account, not the person pressing
Run. The account holder must approve material changes to that workflow.

## Review and send a prepared message

Implemented in version: **0.261.038** (`application/single_app/config.py`).

Manual mode produces an action card in Chat with the recipients, subject, and
body. Review the complete message before selecting **Send**; a long body offers
a full-review control rather than silently approving truncated content.
**Cancel** stops SimpleChat's delivery without needing a working mailbox token.
The same saved action is available in **Approvals** and workflow activity.

The sender alone can act on the card. Shared-conversation viewers do not receive
the private body or recipient/BCC lists. Sign-in recovery refreshes the saved
card and requires another explicit Send; it never generates a replacement draft
or sends merely because sign-in succeeded.

SimpleChat checks the draft's version, then sends the content reviewed on the
card. The original Outlook draft remains after both Send and Cancel, so external
edits are not deleted. **Do not send that retained draft again.** A successful
send means Microsoft 365 accepted the message for sending, not that every
recipient has received it.

Delayed mode provides **Send now** and **Cancel** while delivery remains
unclaimed. Opening a card or reaching zero on its countdown never submits a
send. A lost chat timer requires renewed manual review. If delivery has an
unknown outcome, check Outlook before preparing another message; the app will
not automatically repeat the potentially successful send.

Automatic send mode and **Mark message as read** keep their immediate behavior
and do not create an extra confirmation. A legacy pending action without enough
stored authorization context must be cancelled and prepared again.

## Related

- [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
- [Calendar action]({{ '/reference/actions/m365-calendar/' | relative_url }})
- [Profile preferences]({{ '/guides/update-profile-preferences/' | relative_url }})
