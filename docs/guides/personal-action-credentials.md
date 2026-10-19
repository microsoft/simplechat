---
layout: page
title: "Use your own credentials with a shared action"
description: "Provide a private personal identity when a shared Yamcs action needs your sign-in."
section: "Guides"
audience: user
version: "0.261.348"
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
Fresh agent reconstruction for new same-conversation requests was fixed in
**0.261.345**.
Private prompts and continuation in shared conversations were fixed in
**0.261.348**.

## When a credential card appears

Use an authorized shared agent, or ask orchestration to perform work using an
authorized action directly. A custom agent is not required. If the action
requires your personal identity and none is bound to it, chat pauses that work
and shows a **Personal action credentials** card.

This is the action's connection to its configured service, not your SimpleChat
login. Checking for unfinished requests does not mean that an action needs
credentials; a conversation with no unfinished requests shows no card.

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

The action's result and the assistant's response return in this same
conversation; you do not need to resend the question or start a new chat.
This also applies to a new credential request in a conversation with existing
messages. SimpleChat rebuilds the paused agent with its original tool setup,
while still rejecting changes to its configuration or your access.

Credential inputs are separate from the chat composer. Do not paste passwords,
tokens, or API keys into a message. Credentials are not saved as conversation
content, sent to the model, or shared with conversation participants.

Saving credentials does not grant access to an action or approve an unrelated
write operation. The action's governance and current group membership still
apply.

## Using an agent in a shared conversation

You can invoke your own personal agent in a shared personal or group conversation
when that agent is available to you. Another participant can use their own
personal agent, but sharing the conversation does not let either of you select
the other's personal agents or identities.

An action sign-in card belongs only to the person who invoked the action. Other
participants cannot see its identity choices, enter credentials on your behalf,
or continue your paused work. After you continue, the normal assistant answer
is posted to the shared thread as a reply to your original question. Consider
what your agent may return before asking it to share information with the group.

Shared **Orchestrate** remains available only to the person who started the
conversation, while they are still a participant.

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

If a completed shared answer could not be delivered, refreshing its saved
request can make **Continue** available to retry delivery. This uses the retained
answer, not a second call to the external action.

If the unfinished-request check fails, **Reload requests** checks again and
shows **Checking requests...** while it runs. A session-expired notice requires
signing in again; an access notice requires reopening the conversation or
contacting its owner. Neither notice means you should supply a service password.

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

Requests expire after 24 hours. Removed conversation/group access, a deleted
original shared question, or a changed agent/action can prevent continuation.
Older shared requests without a verified original question are not automatically
reconstructed or replayed.

## Related

- [Yamcs action]({{ '/reference/actions/yamcs/' | relative_url }})
- [Create an agent with actions]({{ '/guides/create-an-agent-with-actions/' | relative_url }})
- [Personal action credential framework]({{ '/explanation/features/PERSONAL_ACTION_CREDENTIALS/' | relative_url }})
