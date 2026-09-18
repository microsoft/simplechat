---
layout: page
title: "Microsoft 365 data and approvals"
description: "Choose how Microsoft 365 data is retrieved, analyzed, and shared in conversations and workflows."
section: "Guides"
audience: user
version: "0.261.032"
---

## Choose the right action

Calendar, Email, OneDrive, and SharePoint Online are separate actions so an agent
can receive the capabilities it needs without unrelated access. Personal,
group-context single-user, shared personal, and shared group conversations can
use them.

Direct chat uses the person asking. A workflow instead uses its explicitly
authorized Run as account for both manual and scheduled execution.

To narrow a request, name the file or supply its canonical folder URL, for
example: "Use SharePoint Online to find the current travel policy under
`https://tenant.sharepoint.com/sites/Team/Shared%20Documents/Policies`."
The restriction belongs to that request, not the action's configuration.
Search uses the provider's index rather than an SMB-style recursive folder
walk; continuation and coverage results describe the available search window.

## Understand the separate decisions

| Decision | What it authorizes |
| --- | --- |
| Microsoft Entra consent/sign-in | The application may call the selected Microsoft 365 APIs as the user. Source permissions still apply. |
| Sharing acknowledgement | Retrieved answers and retained source evidence may be published to conversation participants. |
| Extended analysis | The selected files may receive additional staged processing beyond the fast windows. |
| Workflow Run as approval | A specific workflow revision may use the selected person's connected account. |

One decision does not substitute for another. An administrator who owns an
action cannot approve another person's data disclosure.

## Manage sharing in Profile

The **Settings** tab on Profile keeps independent sharing preferences for
Calendar, Email, OneDrive, and SPO. They apply across personal, group, and global
actions rather than being tied to one agent you might not be able to edit.

In shared conversations, choose **Allow this request**, **Allow for today**,
**Always allow**, or **No**. Today expires at local midnight in the confirmed
time zone. An action owner can permit a shorter maximum duration. An Always
preference does not silently create a fresh daily approval when that action's
shorter approval has expired.

Declining a source lets the request continue without that source. Private
single-user chats do not require a sharing acknowledgement merely because
they use a group workspace.

## Connect from a conversation

When a selected Microsoft 365 action needs fresh source access, Chat checks the
current user's delegated permissions before asking the model to answer.
Missing access pauses the request and offers **Connect Microsoft 365** with
the relevant sources. Use that button to sign in and review Microsoft's
permission consent; there is no need to open Profile first.

After successful sign-in, SimpleChat returns to the original conversation and
queues its saved request. The authorization code and token cache stay in the
server-side login flow, not in browser storage or the conversation. Sign in as
the same tenant account that started the request.

The **workflow connection** status in Profile applies to unattended workflow
access. A disconnected workflow account does not mean interactive chat is
disabled. Reloading already-published file evidence also does not require a
fresh source sign-in.

## Share evidence deliberately

A sharing acknowledgement covers **retained source evidence, not only the final
answer**. Other participants can reuse the published snapshot without having
access to its original Microsoft 365 file. New remote calls still use the
requesting participant's delegated identity.

The same rules apply when a private conversation is shared later. Published
snapshots follow conversation retention and deletion. Disconnecting Microsoft
365 or removing source permissions does not recall copies already disclosed.

## Choose fast or deeper file analysis

OneDrive and SharePoint have separate analysis preferences. Fast windows allow
small relevant file reads without another prompt. Larger or more numerous
files offer a choice: deeper analysis, a faster answer, or a standing preference
for deeper work.

Deeper analysis processes content in batches and preserves extracted evidence,
intermediate results, and checkpoints in the chat storage account. It can
reload relevant ranges instead of putting everything into one prompt.
Summaries are navigation aids, not replacements for captured evidence.

Progress reports identify covered files and page, slide, sheet, or row ranges.
Unsupported content and hard service limits remain explicit limitations.
No workspace document or Azure AI Search index is created.

## Respond through chat or Approvals

The inline prompt and **Approvals** page refer to the same request. Notifications
link to the request when you are no longer looking at the conversation.
Conversation audit metadata records which decision was used.

Approval can queue a continuation or require Microsoft 365 sign-in; it does
not necessarily mean the operation has finished. A waiting workflow resumes
from its checkpoint rather than rerunning completed work.

## Connect an account for workflows

Use the Profile Microsoft 365 connection controls for explicit background
access. Saved workflow connections require configured Key Vault protection;
normal interactive actions do not.

Choose the sources once; there is no second set of permission checkboxes.
Calendar includes events, invitations, timezone, and recipient lookup. Email
includes reading, drafts/read state, sending, and recipient lookup. OneDrive
and SharePoint include file discovery and reading. Review these permissions
on Microsoft's consent page.

Granting a source bundle does not enable disabled agent capabilities or approve
an outgoing message. Existing action limits, delivery review, and workflow
Run as approval remain separate. Older read-only connections need an explicit
reconnect before workflows can use newly requested write permissions.

Select the **Microsoft 365 Run as** account on the workflow. That person must
approve the workflow's sources, instructions, and destinations. Material edits
require approval again. Disconnecting the account stops future credential use
and pauses affected work; it does not remove conversation evidence.

Outgoing mail and calendar review is separate from permission to access a source.
Manual outgoing actions notify the Run as user and appear in workflow activity;
only that user can send or cancel them. Delayed workflow delivery rechecks the
current account and approval when it sends, even after a server restart.
Cancelling a workflow delivery stops the send but leaves an existing Outlook draft
in the user's mailbox. If an interrupted send has an unknown outcome, check Microsoft
365 before starting another action.

## Retrieval availability

Copilot Retrieval is used only in a supported cloud for a verified
Copilot-licensed user. Government and unlicensed or unverified users use
delegated Microsoft Graph. Pay-as-you-go Retrieval is not enabled or used.
Provider errors are not a reason to bypass access or protection restrictions.
