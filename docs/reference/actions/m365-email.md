---
layout: page
title: "Microsoft 365 Email"
description: "Read mail and prepare or send messages without enabling unrelated Microsoft 365 tools."
section: "Reference"
audience: user
version: "0.261.032"
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

## Related

- [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
- [Calendar action]({{ '/reference/actions/m365-calendar/' | relative_url }})
- [Profile preferences]({{ '/guides/update-profile-preferences/' | relative_url }})
