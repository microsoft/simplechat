# Chat preflight context lifecycle fix - v0.261.356

## Issue and root cause

**Fixed in version: 0.261.356**, recorded in
`application/single_app/config.py`.

The first message to an agent in V2 could fail with "The selected chat context
changed. Recheck before sending." even though the user had not changed anything.
The chat store creates a conversation before starting action preflight. React
could commit that new ID while the CSRF context request was pending. The recovery
notice's prop-change cleanup then invalidated the request that created the ID.

This was a client lifecycle defect, not evidence that the selected model or
action provider had failed. A mounted regression using the real chat store,
transport, and recovery notice reproduced the exact error before the fix.

## Technical details

`application/v2_ui/src/lib/actionRecovery.ts` now synchronizes an explicit
actor/conversation/agent context. Synchronizing the same context is idempotent.
The chat store binds that context before asynchronous work and adopts the ID
returned by its own still-current creation operation before starting preflight.
The mounted notice observes that adoption instead of clearing it.

This extends the first-message conversation synchronization introduced in
**0.261.355**. Its synchronous store subscription remains in place:
`setActionRecoveryConversation()` delegates to the same full-context owner
instead of keeping a second conversation identity or invalidating the send
again. Direct store changes and the send's own adoption therefore stay aligned.

Each mounted observer has its own ownership token. Prop changes synchronize
context; unmount releases only the current observer. Cleanup of an older
observer cannot cancel a newer one. An explicit revision and conversation epoch
still reject a late selected-agent creation after navigation, New chat, Stop,
actor changes, agent changes, or leaving the chat. This is not a blanket
exception for any empty-chat-to-conversation transition.

`Composer.tsx` restores an in-memory draft rejected during creation or preflight
only if the current draft is still empty and the account is unchanged. Typed
text and newly attached context are never overwritten. The transport marks
rejection only before the stream POST; uncertain or already-submitted model
requests do not qualify for automatic draft restoration.
Existing preflight failures and cancelled availability decisions retain their
preserved-request notice. Nothing automatically replays a message or retries an
external action. Already-started background generations retain their existing
navigation behavior.

Backend CSRF, authorization, expiry, request/configuration fingerprints, and
single-use continuation claims are unchanged. There are no provider-, model-,
agent-, or acceptance-case-specific exceptions.

## Validation and impact

`ui_tests/test_chat_action_recovery.py` exercises first-send adoption with both
immediate and held context responses, late creation and context responses after
real context changes, actual Composer draft restoration, existing late health
and stream responses, restored requests, explicit consent, and classic/V2
transport compatibility. All HTTP traffic is intercepted; no model or tool runs.

`functional_tests/test_v2_action_recovery_context.mjs` executes the production
context owner, including idempotent synchronization, stale-observer cleanup,
CSRF rejection after genuine changes, and unmount after an explicit reset.
Backend recovery contracts remain covered by
`functional_tests/test_action_runtime_recovery.py`.

Before base integration, at branch version **0.261.355**, the combined
chat-recovery/SQL-feedback browser selection
passed **43 cases**, and the focused backend selection passed **259 cases**.
The network-blocked Cosmos contract gate passed **1,198 cases and 244 subtests**
using the application's pinned Cosmos SDK. The context-ownership Node contract,
V2 typecheck/build, route policies, and documentation checks also passed.

After integrating the concurrent **0.261.355** base fix, version **0.261.356**
passed **58 combined browser cases**, including the incoming real-Composer
and StrictMode regressions. The existing conversation-setter contract passed
in normal and optimized Python, and the Node contract verifies that its
same-ID observation preserves the full context and observer ownership.
The merged Cosmos inventory still reports zero review gaps.

Before the fix, both mounted first-send variants failed with the reported
context-change error and never reached action health. After the fix, both admit
exactly one health check and one stream. Genuine context changes admit neither.
Offline regressions do not qualify the deployed application's live acceptance
run; this change has not been deployed by this investigation.

See [Agent action recovery](../features/AGENT_ACTION_RECOVERY.md).
