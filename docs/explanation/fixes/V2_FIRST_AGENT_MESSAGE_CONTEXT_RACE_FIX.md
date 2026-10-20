# V2 first-agent-message context race

Fixed/Implemented in version: **0.261.355**.

Related version update: `application/single_app/config.py`.

## Issue and root cause

The first message in a new V2 conversation could display
"The selected chat context changed. Recheck before sending." without reaching
the chat endpoint. This affected the shared selected-agent send path, not a
particular connector, model, or prompt.

The chat store creates the conversation before starting the message request.
Assigning the saved conversation ID changes the props of
`ActionRecoveryNotice`. Its React effect cleanup previously invalidated the
action-recovery revision for every conversation-ID change. That cleanup could
run after the same send had already started fetching its recovery context,
making the valid first request appear stale.

The reported acceptance run was consistent with this sequence: conversation
creation and recovery-context initialization returned HTTP 200, but neither
action-health nor chat-stream received a POST. The regression test reproduced
the exact visible error before the fix.

## Technical details

`application/v2_ui/src/lib/actionRecovery.ts` now owns an idempotent conversation
identity setter. A different identity still invalidates pending recovery state;
observing the same identity again does not.

`application/v2_ui/src/stores/chatStore.ts` synchronizes that identity in its
synchronous conversation-change subscription. This happens before the new
conversation's send captures its preflight revision. Starting another New chat
also explicitly invalidates recovery, even if the active ID is already empty.

`application/v2_ui/src/components/chat/ActionRecoveryNotice.tsx` observes the
conversation identity instead of invalidating it again during delayed effect
cleanup. Agent/account changes and unmounting retain their invalidation behavior.

This fixes the timing at the state-owning boundary rather than delaying the
request, exempting all first messages from validation, or retrying a failed send.
Existing action availability, CSRF, consent, and server authorization checks
remain in place. No backend route, storage schema, setting, or classic-client
behavior changed.

## User impact

A healthy selected agent's first message proceeds with one Send action. No
additional recheck, recovery dialog, or automatic replay is introduced.
Genuine context changes still prevent stale preflight responses from submitting
under a different selection.

Since **0.261.356**, leaving a selected-agent send during conversation creation
also rejects that unsent preflight and preserves the Composer draft. This is
distinct from an already-admitted background generation, whose navigation
behavior is unchanged. The conversation setter and full-context owner share
the same state; see
[Chat preflight context lifecycle](CHAT_PREFLIGHT_CONTEXT_LIFECYCLE_FIX.md).

The user-message placeholder is reconciled with the saved message ID through
the existing stream events; no new persistence behavior is introduced.

## Validation

`ui_tests/test_v2_first_agent_message.py` runs the production composer, message
list, chat store, and SSE reader with controlled synthetic HTTP responses.
It covers ordinary and held context responses, React StrictMode, different
agent identities, existing conversations, the upload-created-ID adoption
boundary, genuine context changes during context/health reads, and starting
another New chat during conversation creation. The upload case exercises the
ID-adoption boundary, not the entire upload workflow.

`functional_tests/test_v2_action_recovery_context.py` bundles and executes the
real recovery module to check idempotent identity observation, changed
identities, explicit invalidation, and aborted requests. It also runs under
optimized Python.

The focused first-message and existing classic/V2 action-recovery browser
suites pass **38 tests**. The real-module functional regression passes under
both normal and optimized Python. The production V2 build and TypeScript
checks pass.

These tests simulate the server persistence and response boundary; they do not
claim a live connector or model invocation. Deployment and a live acceptance
rerun are separate from this code change.
