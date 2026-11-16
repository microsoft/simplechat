# Shared chat action credentials fix

Fixed/Implemented in version: **0.261.348**.

Related version update: `application/single_app/config.py`.

## Issue and root cause

A working shared conversation displayed an action-credential load error even
when no action was waiting for a sign-in. Its pending-request lookup treated
the visible shared ID as a personal conversation ID. Shared messages loaded
successfully from collaboration storage while that lookup returned 404.
Reloading repeated the same incorrect lookup.

Action credentials are private service/proxy authentication for an action,
currently Yamcs. They are not SimpleChat login or access to another participant's
personal agent. The check runs when a conversation opens; it must succeed with
an empty list when the user has no unfinished action.

## Changes

`functions_action_credential_conversations.py` resolves personal and verified
shared execution contexts using injected storage and existing authorization
policies. It checks current participation, source ownership/linkage, and the
original AI question's sender. The general personal-conversation authorizer
continues to reject shared Orchestrate backings.

The credential runtime and API keep requests/checkpoints in the invoking
actor's partition under the execution ID. Only safe browser DTOs use the
visible shared ID. Pending reads are read-only, including legacy accepted
group participants whose user-state record has not been materialized.
Unavailable storage remains an explicit error, not a successful empty list.

The shared stream translates both credential SSE formats privately for its
requesting actor. It never broadcasts credential forms, identity choices or
private request IDs. Chat continuation reconstructs the actor's own agent,
reauthorizes retained sources and tool execution, and screens the resulting
answer before mirroring it into the original shared thread.

Stable answer IDs and the completed execution journal allow an explicit
delivery retry after publication failure without repeating completed tool
operations or posting another question. Uncertain execution failures do not
acquire this delivery-only retry. Existing ETags, CSRF, expiry, action
fingerprints, journal guards, and creator-only shared Orchestrate remain.

V2 credential cards wait for the conversation kind to resolve, clear on
conversation/account changes, and continue through the correct history family.
Load failures distinguish session/access problems from transient request-check
errors. Reload is single-flight and visibly busy.

## Behavior and limitations

Before the fix, a valid shared ID could produce a persistent, misleading
credential banner. After the fix, no unfinished work means no banner; an actual
blocked action shows only its invoking user's sign-in card. Continuing returns
the normal answer to everyone in the shared thread, not the credentials.

Each participant may use their own authorized personal agents. Sharing a
conversation does not share personal agents or identities. Shared Orchestrate
is still creator-only. Requests expire after 24 hours, and old shared requests
without a verified original question are not guessed or replayed.

## Validation

`functional_tests/test_action_credentials_shared_conversations.py` covers
private per-actor lists, guessed-ID denial, revoked access, forged/deleted
origins, expiration, storage errors and private live-stream projection.

`functional_tests/test_action_credentials_chat_reconstruction.py` exercises
real loaders, identity storage, journals and routes for personal/group actions
in shared personal/group chats, including noncreator personal agents,
read-only legacy membership and delivery retry without a second provider call.

`ui_tests/test_v2_action_credentials.py` covers empty/error states, single-flight
retry, stale responses, secret clearing and personal/shared routing.
`ui_tests/test_v2_action_credentials_backend.py` drives the real React card
through Flask and a freshly reconstructed agent into shared history. Classic
cards and existing credential/orchestration regressions retain their coverage.

All external service/model/Cosmos transport in these integration tests is
offline. They do not submit production credentials, invoke real external
actions, or deploy the change.
