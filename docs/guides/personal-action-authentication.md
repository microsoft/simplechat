---
layout: page
title: "Connect your own action account"
description: "Use a shared Yamcs action with your own private credentials in classic or v2 chat."
section: "Guides"
audience: user
version: "0.261.107"
---

## Why connect your own account

A global action can be shared while each person's requests use their own service
permissions. For example, a shared Yamcs agent can read the telemetry available to
your account without giving other participants your credentials.

Implemented in version: **0.261.107**, recorded in
`application/single_app/config.py`.

## Administrator setup

In **Admin Settings > Agents & Actions**, create or edit a global Yamcs action.
Classic uses the action wizard; v2 provides native Yamcs global-action setup.

Choose **Each user's personal identity**, select the authentication profile, and
set the identity name. The default is **Yamcs**; a deployment can use a more
specific label such as **Mission telemetry**.

Choose Yamcs login when the server exchanges a username/password for a Yamcs
token. Choose gateway HTTP Basic when the gateway expects a Basic header instead.
Bearer token and API key profiles are also available; the API-key profile uses
`x-api-key`.

Use an HTTPS destination with certificate validation. Save the action before
testing it with your own identity, then attach it to the intended agent. Existing
global/workspace merge settings and governance still determine who can use it.
The action's read-only restriction does not change.

## Connect from chat

Select the agent and submit your request. If it needs a personal identity, chat
keeps the draft unsent and displays a **Connect Yamcs** card marked **Private to
you**.

Review the destination, required identity name, and authentication profile.
Choose a compatible saved identity or enter the required credential fields.
Confirm the destination before saving. Once all required identities are ready,
chat sends your original request once.

Cancel stops the pending execution. Returning after navigation or reload does not
automatically send an old draft.

**Do not type a password or token into the normal chat message box.** Normal
messages are saved and may be shared. Only the separate credential form has this
private submission behavior.

## Set up the identity beforehand

1. Open **My Workspace > Identities** in v2, or the personal workspace's **Identities** tab in classic.
2. Add an action identity using the name supplied by the administrator, select **Actions** usage, and provide the indicated credential type.
3. Save, return to chat, and check the pending request again.

If your deployment hides the workspace, use the private in-chat setup rather than
looking for an unavailable page. Supplying credentials does not grant permission
to create personal actions or access another user's workspace.

## Understand identity reuse

Two actions can reuse your identity when the destination and authentication
profile are compatible and approved. A matching name alone is not enough to send
a credential to a new system.

If more than one identity matches, select the intended one. An administrator's
label change does not silently rename an existing personal identity. A changed
destination or authentication profile needs review before reuse.

Stored secrets are not returned to the form. To rotate a credential, enter its
replacement through personal identity management or the private repair flow.
Other actions using that identity may be affected by a replacement or deletion.

## Use a shared conversation

Your submitted turn uses your identity. Another participant's turn, or a retry
they are permitted to initiate, uses theirs. Delegated agent calls keep the
identity of whoever submitted the root turn, not the agent creator's account.

The credential card and saved credentials stay private. Your posted message and
the returned data are visible to everyone with conversation access, as the
sharing notice explains.

Earlier results remain shared history even when another participant has narrower
Yamcs permissions. Authentication controls new requests to Yamcs, not the visibility
of data someone already posted.

## Resolve connection problems

| What happens | What to do |
| --- | --- |
| A credential is missing or rejected | Provide or replace it in the private form, not in a normal message. |
| The service denies access to a resource | Ask the service administrator about the account's permissions; a different password is not necessarily the solution. |
| The destination or profile changed | Review the current action and approve the intended recipient again. |
| The network or credential store is unavailable | Retry after the service recovers; SimpleChat does not substitute an owner's or global credential. |
| A request expired or another save won | Check the current identity/request state rather than resubmitting the old form. |

If a tool already ran before a later authentication failure, credential repair
does not automatically repeat the whole turn. Review the outcome before making
an explicit retry.

## Related

- [Yamcs action reference]({{ '/reference/actions/yamcs/' | relative_url }})
- [Agents & Actions administration]({{ '/admin/agents-actions/' | relative_url }})
- [Chat controls]({{ '/reference/chat-controls/' | relative_url }})
