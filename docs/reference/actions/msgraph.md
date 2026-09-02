---
layout: page
title: "Microsoft Graph"
description: "Full guide for the Microsoft Graph SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: msgraph -->

{% include media.html src="reference/actions-msgraph-configuration.png" alt="The Microsoft Graph configuration pane noting the action uses the signed-in user's delegated permissions, above capability toggles for reading profile, mailbox timezone, calendar events, and mail, and for creating calendar invites and sending mail with their delivery mode selectors." title="Microsoft Graph action configuration" capture="Capture Default Microsoft Graph Capabilities and mail/calendar delivery settings. Redact user identifiers." %}

## What this action does

Microsoft Graph uses the signed-in user's delegated permissions and the standard Graph endpoint. Its capabilities include profile, timezone, calendar events, calendar invites, mail read/update/send, directory search, user lookup, OneDrive listing, and security alerts available to the user.

## Why and when to use it

Use Microsoft Graph when an agent should help with Microsoft 365 work in the user's own context: drafting mail, checking calendar context, finding people, or listing OneDrive items. Do not use it for app-wide mailbox automation unless delegated-user behavior is intended and consented. Keep mail/calendar sending modes conservative when users must review drafts before delivery.

## Before you start

- Microsoft Graph permissions and consent appropriate for enabled capabilities.
- Signed-in users who are allowed to use the action.
- A decision about risky capabilities, especially **Send mail** and **Create calendar invites**.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

## Configure the action

1. Choose **Microsoft Graph**.
2. Review **Default Microsoft Graph Capabilities** and enable only needed operations.
3. For mail, choose manual draft, delayed draft, or auto-send where allowed.
4. Set mail delay seconds when using delayed delivery.
5. For calendar invites, choose the invite delivery behavior and delay seconds when applicable.
6. Save and assign the action only to agents that need Microsoft 365 access.

## Example prompts

- "Draft a reply to the latest unread message from Contoso and leave it for my review."
- "Find free time tomorrow afternoon and create a Teams meeting invite for these attendees."
- "Search the directory for Alex Chen and show the likely match with email address."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Graph calls fail for one user | Delegated permission, consent, or mailbox access is missing for that user. | Confirm Graph scopes and have the user re-consent if required. |
| Mail sends when drafts were expected | The action is configured for auto-send. | Change mail delivery mode to manual draft or delayed draft. |
| Calendar invite lacks group members | The prompt or permissions did not include resolvable group context. | Enable invite capability and include group/workspace context. |

## Related

- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Agents administration]({{ '/admin/agents-actions/' | relative_url }})
- [Governance]({{ '/admin/governance/' | relative_url }})

