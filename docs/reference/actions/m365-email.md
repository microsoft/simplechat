---
layout: page
title: "Microsoft 365 Email"
description: "Read and search mail and prepare or send messages without enabling unrelated Microsoft 365 tools."
section: "Reference"
audience: user
version: "0.261.321"
---

<!-- action-slug: m365-email -->

## What this action does

Microsoft 365 Email provides mail reading and search, read-state updates, and
message composition/delivery using delegated access. It does not expose
calendar or file-retrieval tools.

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

Since **0.261.321**, Orchestrate can choose an authorized email action directly or use
an agent with this action. Explicit operation intent allows configured sending or
read-state changes; gathering intent remains read-only. Research and prepared content
arrive as complete named inputs. A request to send still follows the configured manual,
delayed, or automatic delivery mode, and a draft awaiting review is not reported as sent.

In shared conversations, email results can disclose personal information.
Users acknowledge that disclosure in chat or Approvals. Their source preference
is managed in Profile and is constrained by the action's permitted duration.
This acknowledgement does not authorize a mail send or grant OAuth scopes.

## Find older mail

Implemented in version: **0.261.129** (`application/single_app/config.py`).

**Read my mail** reaches any message still in the user's mailbox, not only the
newest ones. The agent narrows a request with these parameters:

| Parameter | What it does |
|---|---|
| `search` | Plain words that must all appear in the sender, subject, or body. Operators such as `OR` and field prefixes such as `from:` are ignored, so the agent can't widen or reshape the query. Up to 10 words. |
| `received_from` | Returns only messages received at or after this date or time. |
| `received_to` | Returns only messages received before this date or time. A date without a time includes that whole day. |
| `folder` | `inbox` by default. Use `all` for every folder, or a folder such as `sentitems` or `archive`. |
| `unread_only` | Returns only unread messages. |
| `top` | Up to 25 messages per call, newest first. |
| `select_fields` | Extra Graph fields to request. Baseline source-card metadata and `webLink` are still requested, so a custom selection does not remove the subject, sender, received time or Outlook link. |

Dates and times without a time zone are read as UTC.

Example: "Find every email about the Fabrikam contract from March 2024, in all
folders."

### Read a long history

Each result includes a `coverage` summary: the folder, words, and date range
that were read, the newest and oldest message returned, and whether that range
was read completely. When more messages match, `coverage.continue_with` holds
the exact arguments for the next, older set. The agent calls again with those
arguments to keep reading back, and a continuation doesn't return a message it
already returned.

When a result is incomplete without a continuation, its note says why. For
example, more messages can share one received second than `top` allows; the note
then names that time and suggests a larger `top`.

### Permissions and limits

Older mail uses the same delegated `Mail.Read` permission as new mail.
Microsoft Graph has no separate permission for mailbox history, so no new
consent or app registration change is needed.

- Only the user's primary mailbox is read. Online archive and shared mailboxes
  aren't included.
- Messages that were permanently deleted, by the user or a retention policy,
  can't be returned.
- Microsoft 365 returns at most 1,000 results for one keyword search. When a
  search is combined with a date range or `unread_only`, one call examines up
  to 500 search results and then offers a continuation from where it stopped.
- Keyword results are ordered by when each message was sent. A message that
  arrived long after it was sent can be skipped when a search continues across
  calls.

## Cited emails and a consistent list

Implemented in version: **0.261.303** (`application/single_app/config.py`).

Every email that **Read my mail** returns carries a citation value, and the answer
cites each email it mentions with a chip that shows the subject. Clicking the chip
opens a card with the sender, received time, read state, importance and a short
preview when recorded, and **Open in Outlook** opens the specific message in
Outlook on the web in a new tab.
Cited emails are also listed under **Email** in the conversation's **Documents**
pane, with **Open in Outlook**. The reply's **Sources** panel offers the same action.

Refined in version: **0.261.305** (`application/single_app/config.py`). Custom
Graph selections preserve the fields needed to build source cards, and the cards
remain readable in light and dark themes. Existing history is unchanged: if a saved
record has no online URL, the card explains that the link is unavailable and suggests
recalling the email again.

Lists of emails always use the same layout, so the answer reads the same from one
request to the next:

```text
10 most recent emails, all unread, newest first:
1. **PIM: Role activated** — Microsoft Security, Oct 7, 2026, 12:52 PM EDT [citation]
2. ...
```

Each line has the subject in bold, the sender, and the received time in the
reader's browser time zone. " · Unread" and " · High importance" are added only
when they apply, and a one-line summary appears under an email only when the
question was about its content. The header says "matching" instead of "most
recent" for a search.

Only an `https` link from Microsoft Graph becomes a link, and stored citations
hold no message body. Answer guidance avoids routine source-provenance introductions,
but still requires citations and disclosures about uncertainty or incomplete coverage. See
[Microsoft 365 Source Citations]({{ '/explanation/features/M365_SOURCE_CITATIONS/' | relative_url }}).

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


## V2 action configuration

The V2 editor registers this as a native Microsoft 365 action instead of relying on the legacy Microsoft Graph action. Capability switches come from the action catalogue and are stored under `additionalFields.m365_capabilities`, so owners can expose only the calendar, email, file, or site operations this action needs.

The Microsoft Graph endpoint is read-only and derived from the deployment cloud: commercial deployments use `graph.microsoft.com`, and US Government deployments use `graph.microsoft.us`. Custom cloud endpoint behavior follows the deployment's configured Microsoft 365 runtime instead of being edited per action.

Connection testing appears in **Authentication**, after the delegated or workflow identity choice. The V2 editor no longer offers ad hoc custom fields; preserved legacy values remain available in **Advanced → JSON**.

## Related

- [Microsoft 365 data and approvals]({{ '/guides/microsoft-365-conversation-data/' | relative_url }})
- [Calendar action]({{ '/reference/actions/m365-calendar/' | relative_url }})
- [Profile preferences]({{ '/guides/update-profile-preferences/' | relative_url }})
