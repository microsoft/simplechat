# Conversation Fork HTTP 500 Fix

## Issue

Forking an owned conversation with group or public workspace context returned
HTTP 500 instead of creating the fork or reporting an eligibility conflict.

**Fixed in version: 0.250.101**

## Root Cause

The fork operation allowed only personal context, even though SimpleChat stores
owned group- and public-grounded chats as single-user conversations. When that
eligibility check raised `ConversationForkConflictError`, the route attempted to
log it with the unsupported `custom_dimensions` argument. `log_event()` raised
`TypeError`, masking the intended HTTP 409 response as HTTP 500.

Additional fork cleanup and activity log calls used the similarly unsupported
`properties` argument and could mask persistence failures.

## Technical Details

### Files Modified

- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `functional_tests/test_conversation_fork.py`
- `functional_tests/test_conversations_read_ownership_authorization.py`
- `ui_tests/test_chat_conversation_fork.py`
- `docs/explanation/features/FORK_CONVERSATION.md`
- `application/single_app/config.py`

### Code Changes

- Replaced invalid fork logging keyword arguments with `extra`, the structured
  context parameter supported by `log_event()`.
- Added group and public workspace context revalidation before any destination
  message, blob, or conversation is written.
- Continued to require exact source ownership and reject collaborative,
  multi-user, workflow, mixed-scope, and unknown conversation types.
- Preserved the authorized group/public context and normalized destination chat
  type.
- Aligned the browser Fork action with the supported backend conversation types.

### Impact

Owned single-user conversations grounded in an active group or public workspace
can now be forked when the current user still has access. Stale or unauthorized
workspace context returns a controlled conflict without creating partial data.
Expected validation and conflict errors can no longer be converted into HTTP
500 by fork-specific logging.

## Validation

### Coverage

- Personal, group-single-user, and public fork success paths.
- Missing, inactive, and unauthorized workspace context.
- Unsupported multi-user conversation rejection.
- Route-level conflict logging and HTTP 409 response behavior.
- Browser action visibility for supported and unsupported conversation types.
- Existing message ordering, source immutability, artifact remapping, blob copy,
  concurrency, and failed-write cleanup behavior.

### Before and After

Before the fix, an expected workspace eligibility conflict triggered a logging
`TypeError` and returned HTTP 500. After the fix, authorized workspace-grounded
conversations fork successfully, while genuine conflicts return HTTP 409 with no
partial destination records.
