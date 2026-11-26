# Streamed Chat Action Recovery Continue Fix

**Issue:** When an agent's action became unavailable after the client's pre-send check, a streamed chat paused for action recovery after it had already saved the user's question. Choosing **Continue** then failed with "This submission was used for another request," and the conversation kept a question with no answer, even though the recovery notice tells the user the message has not been sent.

**Root cause:** The stream route saves and dispatches the question when it opens the response attempt (`ChatAttemptStore.begin`), and only then checks the agent's actions in the stream worker. A paused request had therefore already used its submission. On **Continue**, the client resends the same submission with a fresh `action_recovery_nonce` and the recovery decision, which no longer matches the saved attempt. `/api/chat` checks actions before it saves the turn and was not affected.

**Fixed in version: 0.261.486**

## Technical details

### Files modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_action_runtime_recovery.py`

### Code changes

- `_admit_chat_actions_before_saving` runs the action check (`validate_recovery_agent` and `check_chat_actions(..., admit=True)`) in the stream route before the question is saved, after a new conversation is created. A recovery pause returns the same one-event stream as before, without saving the question or opening a response attempt, and releases the conversation lease. An invalid or expired recovery decision returns the existing error event, also without saving.
- Other outcomes of the early check, such as Microsoft 365 sign-in, approvals, action credentials, policy, and storage errors, are left to the stream worker. It repeats the check after saving the question and reports them exactly as before.
- The stream worker runs with a fresh Flask `g`. The route copies the admission result, the claimed one-time decision, and the actions the user chose to continue without into the worker. The worker does not repeat the check, and later action loading reuses the claimed decision instead of rejecting it as already used.

### Testing

- `test_actual_chat_routes_pause_before_kernel_initialization_or_user_persistence[/api/chat/stream]` now passes: a send-time pause saves nothing and starts no model.
- `test_stream_continue_after_a_send_time_pause_sends_the_question_once` pauses at send time, rechecks with a fresh nonce as both clients do, and then continues. It checks that Continue is accepted, the question is saved once, Microsoft 365 preflight and kernel setup see the user's exclusions and the claimed decision, and the action check runs once per request. The test fails on the previous route, and it also fails if the worker state is not copied.

### Impact

- Only agent chats on the ordinary streamed path change. The action check moves from the start of the stream worker to just before the stream opens, so it adds no work, although the first stream event for agent chats can arrive slightly later.
- After **Continue** in the classic UI, the original question keeps its temporary message ID until the conversation reloads. V2 reloads the conversation when the resumed response finishes.

## Validation

- The recovery suite and the stream, retry, Microsoft 365, collaboration, and shared conversation suites that exercise the stream route were run in isolation against the unmodified branch, with no new failures.

**Before:** a send-time pause saved the question, and **Continue** failed with `submission_conflict`, leaving an unanswered question.

**After:** the question stays unsent until the user continues, and **Continue** sends it once.
