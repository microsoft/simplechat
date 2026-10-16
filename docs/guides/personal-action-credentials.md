---
layout: page
title: "Use your own credentials with a shared action"
description: "Provide a private personal identity when a shared Yamcs action needs your sign-in."
section: "Guides"
audience: user
version: "0.261.343"
---

## What this does

A shared action can describe the server and operations everyone uses while each
person signs in separately. Your administrator does not need to publish a copy
of the action or agent for you. This first integration supports Yamcs service
credentials and the username/password required by a reverse proxy in front of
Yamcs.

Fixed/Implemented in version: **0.261.333**, recorded in
`application/single_app/config.py`.
Continuation failure feedback and status recovery were fixed in **0.261.343**.

## When a credential card appears

Use an authorized shared agent, or ask orchestration to perform work using an
authorized action directly. A custom agent is not required. If the action
requires your personal identity and none is bound to it, chat pauses that work
and shows a **Personal action credentials** card.

The card names the action and destination. A proxy sign-in is not necessarily
your Yamcs sign-in: a deployment can have proxy authentication while Yamcs
itself has none. Follow the labels rather than supplying the same credential
for every field.

## Save and continue

1. Review the action and destination before entering a credential.
2. Select a compatible existing personal identity, or give a new identity a name
   and enter the requested username/password, API key, or bearer token.
3. Choose **Save and continue**. SimpleChat saves the identity privately and
   resumes the blocked work. It does not send a new question or replay completed
   operations.

Credential inputs are separate from the chat composer. Do not paste passwords,
tokens, or API keys into a message. Credentials are not saved as conversation
content, sent to the model, or shared with conversation participants.

Saving credentials does not grant access to an action or approve an unrelated
write operation. The action's governance and current group membership still
apply.

## Returning later or cancelling

Saved personal identities are reused on subsequent authorized invocations.
Pending requests can be recovered when you reopen their conversation. Unsaved
credential inputs do not survive navigation, sign-out, or reload; enter them
again only in the recovered card.

**Cancel blocked work** stops the credential request rather than supplying an
empty identity. If continuation cannot be confirmed, reload requests and review
the saved work before trying again. Do not resend the original question merely
to complete the blocked action.

## If saving or continuing cannot be confirmed

A successful save and a successful action are different outcomes. If the card
says **Your credentials are saved**, do not enter them again because continuation
failed. Select **Refresh saved request** to read its current status from the
server. SimpleChat also checks the saved run for orchestration work.

Continue becomes available only if the request is still ready and its run is
still waiting. It uses the refreshed request revision, not a second credential
submission. If the work is running, finished, failed, or superseded, the card
does not offer another continuation. Review run details for saved progress and
the recovery actions the server permits. For ordinary agent chat, review the
conversation instead.

If saving itself cannot be confirmed, refresh before entering credentials again:
the server may already have saved them even if the response was lost. If refresh
fails too, reload the conversation. Neither refresh nor reload automatically
replays the action or sends the original question again.

## When credentials stop working

A confirmed authentication rejection can ask for a replacement identity.
Choose another compatible personal identity, save a new one, or select
**Replace credentials in this personal identity** to update the selected
identity in the card. An identity
removed after it was bound can also require setup again.

Updating an existing identity checks its current revision independently of the
credential request. If another editor changed it, reload the request instead of
overwriting those changes. Other actions using that personal identity use its
updated credentials.

Not every service error means a password has expired. Permission denials,
connection failures, and secret-storage outages need their own resolution.
Contact the action administrator for those errors, or when the action or its
destination changed while a request was waiting.

When personal identity management is enabled, **My Workspace > Identities**
lets you maintain identities you own. The chat credential flow also works for
authorized shared actions when personal workspace authoring is disabled; it
does not enable personal action or agent creation.

## Storage and limitations

Identities use the deployment's existing storage choice: Key Vault when
configured and enabled, otherwise the existing Cosmos identity storage.
SimpleChat does not require Key Vault solely for this workflow.

Only Yamcs exposes personal action credential sources in this release. Other
connectors retain their existing authentication behavior. Application managed
identity and SimpleChat's session cookie are not personal credentials to paste
into a card. Scheduled/background prompting is outside this release.

## Related

- [Yamcs action]({{ '/reference/actions/yamcs/' | relative_url }})
- [Create an agent with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }})
- [Personal action credential framework]({{ '/explanation/features/PERSONAL_ACTION_CREDENTIALS/' | relative_url }})
