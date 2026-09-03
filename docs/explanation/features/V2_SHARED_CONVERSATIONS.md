# Shared Conversations In The V2 Interface

## Overview

A shared conversation is one several people read and write in together, with the assistant
available inside it. SimpleChat has supported them since the collaborative conversations
foundation, and the classic interface drives them from
`application/single_app/static/js/chat/chat-collaboration.js`.

The V2 interface listed them but could not open them. Clicking a shared conversation showed
an empty thread, and every other action on one was wired to the personal conversation API,
which does not know they exist. This change routes the V2 interface through the
`/api/collaboration/*` API so a shared conversation can be read, replied to, invited into
and managed there.

**Implemented in version:** 0.261.038

### Dependencies

| Dependency | Purpose |
|---|---|
| `enable_collaborative_conversations` | Administrator capability that switches the whole surface on |
| `/api/collaboration/*` | The existing collaboration API, unchanged by this work |
| `EventSource` | Live updates from the conversation's server-sent event stream |

No Flask route, Cosmos container or server behaviour was changed. Every endpoint this uses
already existed and was already driven by the classic interface.

## Why the thread was empty

The V2 interface loaded every conversation's messages with
`GET /api/get_messages?conversation_id=<id>`. That route reads only
`cosmos_messages_container` and authorizes with `_authorize_personal_conversation_read`,
which raises `LookupError` for a conversation that is not in it. The route catches that and
answers:

```python
except LookupError:
    return jsonify({'messages': []})
```

with a **200** (`route_backend_conversations.py`). So a shared conversation did not fail to
open — it opened successfully, with nothing in it, and stayed the target of the next message
sent. Shared conversations live in `cosmos_collaboration_conversations_container` and
`cosmos_collaboration_messages_container`, behind their own API.

The conversation **feed** already merged them, which is why the rows appeared in the rail at
all: `functions_conversation_feed.py` combines a legacy source and a collaboration source
into one page. Only the per-conversation operations were missing.

## Architecture

Routing is decided by `conversation_kind`, which the feed already returns on every row, and
never by trying one endpoint and falling back — because the personal endpoint does not fail
for a shared conversation.

| Concern | Module |
|---|---|
| Endpoint wrappers | `application/v2_ui/src/lib/collaboration.ts` |
| Event stream, replay guard, de-duplication | `application/v2_ui/src/lib/collaborationEvents.ts` |
| Mention grammar and the send rule | `application/v2_ui/src/lib/mentions.ts` |
| Author, reply and message-kind reading | `application/v2_ui/src/lib/sharedMessage.ts` |
| Which invite route a conversation uses | `application/v2_ui/src/lib/sharing.ts` |
| Membership, typing, panel and invite state | `application/v2_ui/src/stores/collaborationStore.ts` |
| Kind-aware conversation and message actions | `application/v2_ui/src/stores/chatStore.ts` |
| Participants panel | `application/v2_ui/src/components/chat/ParticipantsPanel.tsx` |
| Mention autocomplete | `application/v2_ui/src/components/chat/MentionMenu.tsx` |
| Invitation prompt | `application/v2_ui/src/components/chat/InviteBanner.tsx` |
| Generated file approvals | `application/v2_ui/src/components/chat/FileApprovals.tsx` |

### Endpoints used

| Purpose | Endpoint |
|---|---|
| Messages | `GET /api/collaboration/conversations/<id>/messages` |
| Post to participants | `POST /api/collaboration/conversations/<id>/messages` |
| Ask the assistant | `POST /api/collaboration/conversations/<id>/stream` |
| Cancel generation | `POST /api/collaboration/conversations/<id>/stream/cancel` |
| Live updates | `GET /api/collaboration/conversations/<id>/events` |
| Typing | `POST /api/collaboration/conversations/<id>/typing` |
| Membership and capabilities | `GET /api/collaboration/conversations/<id>` |
| Rename | `PUT /api/collaboration/conversations/<id>` |
| Pin, hide, mark read | `POST /api/collaboration/conversations/<id>/{pin,hide,mark-read}` |
| Leave or delete | `POST /api/collaboration/conversations/<id>/delete-action` |
| Invite into a shared conversation | `POST /api/collaboration/conversations/<id>/members` |
| Share a personal conversation | `POST /api/collaboration/conversations/from-personal/<id>/members` |
| Share a group conversation | `POST /api/collaboration/conversations/from-group/<id>/members` |
| Remove a member | `DELETE /api/collaboration/conversations/<id>/members/<user_id>` |
| Change a role | `PUT /api/collaboration/conversations/<id>/members/<user_id>/role` |
| Accept or decline | `POST /api/collaboration/conversations/<id>/invite-response` |
| Delete a message | `DELETE /api/collaboration/conversations/<id>/messages/<message_id>` |
| Mask a message | `POST /api/collaboration/conversations/<id>/messages/<message_id>/mask` |
| Pending file approvals | `GET /api/collaboration/file-approvals` |
| Resolve a file approval | `POST /api/collaboration/file-approvals/<src>/<msg>/<decision>` |
| People who can be invited | `GET /api/user/collaboration-suggestions` |
| Group members | `GET /api/groups/<group_id>/members` |

### Capability flags

What a reader may do is decided by the server and reported on the conversation by
`serialize_collaboration_conversation`. The V2 interface reads those flags and never
reimplements the rules behind them, because they fold together membership status, role,
visibility mode and whether membership is explicit at all — and a group-visibility
conversation grants posting with no membership record to inspect.

| Flag | Controls |
|---|---|
| `can_post_messages` | Whether the composer is usable |
| `can_manage_members` | Whether people can be invited or removed |
| `can_manage_roles` | Whether a member can be promoted to admin |
| `can_accept_invite` | Whether the invitation prompt is shown |
| `can_delete_conversation` | Whether removal destroys the conversation for everybody |
| `can_leave_conversation` | Whether removal only removes the reader from it |

## What a shared conversation does differently

### Messages are attributed

A personal conversation has one human, so its messages need no author. A shared one shows
who wrote each message, and puts another participant's message on the left rather than on
the reader's own side. The reader's own messages read as "You". A message that asked the
assistant is labelled as such, because a plain message and a request to the model are both
stored with `role: 'user'` and only `message_kind` separates them.

Shared conversations can also contain a `file` message — an upload, which
`serialize_collaboration_message` gives a display role the personal endpoints never emit. It
is rendered as a named attachment rather than as message text, because its `content` is the
extracted document text.

### The assistant is not addressed by default

Most messages in a shared conversation are people talking to each other, so sending one does
not invoke the model. The assistant answers only when:

- the message `@`-mentions a model or an agent, or
- an assistant-implying composer option is set: an agent, document search, web search, image
  generation, deep research, URL access, or a saved prompt.

Otherwise the message is posted to the participants and the model never sees it. This is the
classic interface's rule, reproduced from `buildCollaborativeInvocationTarget` in
`chat-messages.js` so the two interfaces cannot disagree about what a given message does.

An explicit `@` tag overrides the pickers for that message alone: tagging `@o3` sends that
one message to `o3` whatever the model picker holds.

### Mentions

Typing `@` opens a menu of, in order, the people already in the conversation, the models and
agents that can be addressed, and — for somebody who may manage members — people who could
be added. Choosing one of the last group invites them.

A mention matches at a word boundary on both sides, so `@Sam` does not match `@Samantha` and
an email address does not become a mention. Where one person's name is a prefix of
another's, the longer match is struck out of the text before shorter names are tried, so
writing `@Ada Lovelace` does not also notify somebody called `Ada`.

### Live updates

The conversation's event stream delivers other people's messages, deletions, masks, typing,
membership changes and deletion of the conversation itself.

Two properties of that endpoint shape the client. It **replays**: `iter_events` starts at
index 0, so attaching delivers the conversation's whole event history first. And
`EventSource` **reconnects by itself**, reattaching from the beginning, so that replay
happens again after every network blip. Events that predate the subscription are therefore
discarded, and every event is de-duplicated by identity so a repeat cannot append a second
copy of a message.

A third property matters just as much and is easy to miss. Every route that publishes an
event calls `serialize_collaboration_conversation` with the user who **caused** the event,
then broadcasts that single document to every subscriber. So the conversation inside an
event carries the *actor's* permissions, role, membership status and pin state — not the
reader's. Applying it wholesale is wrong in both directions: a participant leaving publishes
a conversation in which `can_post_messages` is false, which would disable everyone else's
composer, and an owner acting publishes one in which `can_delete_conversation` is true,
which would offer every member a "Delete for everyone" button the server then refuses.

`conversationFactsOnly` (`lib/collaborationEvents.ts`) therefore strips the viewer-scoped
fields from any broadcast, leaving only what means the same to everybody — title,
participants, counts, timestamps, scope. A membership change is treated as a reason to
**re-read** the conversation for this reader rather than as a payload to trust.

Capability flags are also **deny-by-default** while unknown: `can_post_messages` must be
explicitly true for the composer to be usable, so a membership that has not loaded leaves
the composer disabled rather than offering Send to somebody who has not joined.

### Operations a shared conversation does not have

Retry, edit, attempt navigation and fork are hidden. Those endpoints read and rewrite the
personal messages container and have no collaboration counterpart; the classic interface
leaves them out for the same reason.

Stream recovery is also switched off. `/api/chat/stream/reattach` is keyed on the
conversation the generation actually runs in, which for a shared conversation is a hidden
source conversation the browser is never told the id of, so a dropped transport is reported
rather than retried against a conversation that endpoint has never heard of.

## Usage

### Enabling the capability

Shared conversations require **Collaborative conversations** to be enabled in admin
settings (`enable_collaborative_conversations`). With it off, the API refuses every request
and the V2 interface shows no sharing controls at all.

### Sharing a conversation

Open a conversation and choose the **people** button in the chat header, or **Share** from
the conversation's menu in the left rail. Search for somebody and add them.

Sharing does not convert the conversation in place. It creates a new shared conversation
seeded from it and leaves the original as the hidden source the assistant runs in, so the
interface moves you to the new one. That is why the conversation appears in the rail under a
new entry after sharing.

A group conversation may only be shared with members of that group, so the search there
offers group members rather than the directory.

### Being invited

An invited conversation is readable before it is accepted, so the invitation can be judged
on its contents. A prompt above the thread offers **Join** or **Decline**, and the composer
stays disabled until you join.

### Managing people

The people panel lists everyone, shows who is an owner or admin and who has been invited but
has not joined, and offers removal and promotion to whoever the server says may do them.
Ownership is not assignable: it moves by being handed on when an owner leaves.

### Leaving versus deleting

Removing a shared conversation from the rail does different things depending on who you are.
An owner deletes it for everybody. Anybody else leaves it, and the conversation carries on
without them. The rail's menu says which of the two it will do.

### Generated files

A file the assistant generates in a shared conversation is staged rather than released,
because it would become available to every participant. A banner above the thread lists
files waiting on your decision, with **Approve** and **Deny**.

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_shared_conversations.py` | Endpoint wiring, capability gating, hidden operations, share routing, replay handling |
| `functional_tests/test_v2_shared_conversation_logic.mjs` | The send rule, the mention grammar, event dispatch and attribution, executed against the real modules |

Run them with:

```powershell
python .\functional_tests\test_v2_shared_conversations.py
node .\functional_tests\test_v2_shared_conversation_logic.mjs
```

### Known limitations

- **Deep research, URL access and source review are not applied.** They make a message a
  request to the assistant, but `_build_collaboration_stream_request_payload` does not
  forward `deep_research_enabled`, `source_review_enabled` or `url_access_enabled` to the
  chat stream it bridges to. This is existing server behaviour and affects the classic
  interface identically.
- **A dropped stream cannot be resumed** in a shared conversation, as described above.
- **Retry, edit, attempt navigation and fork** are unavailable, matching the classic
  interface.
