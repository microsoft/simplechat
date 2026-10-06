# Orchestration Duplicate Thinking Indicator Fix (v0.261.253)

## Issue

Once an orchestration plan started running, the V2 chat showed two progress indicators for the
same work:

- **Streaming bubble:** "Thinking". When a run notice such as a saved-memory warning arrived, a
  "1 reasoning step" toggle appeared above it.
- **Plan card running row:** a spinner, the plan's intent, a step count such as `0/1`,
  **Review**, and a status line that said only "Reasoning".

Neither said what the run was actually doing. The planning phase before them also said
"Thinking", which didn't match the plan card that replaced it.

Fixed in version: **0.261.253**, tracked in `application/single_app/config.py`.

## Root cause

A run is driven by the orchestration controller, but it borrows the chat store's shared
`streaming` flag. That flag routes **Stop** to the run, keeps the composer from sending into a busy
turn, and collects the run's thoughts for the finished answer. `executeSavedPlan` took the flag
through `beginOrchestrationTurn`, and `MessageList` drew `StreamingBubble` whenever `streaming` was
true. The store recorded only that something was streaming, not that it was the run, so the bubble
could not step aside for the card.

The bubble had nothing to add while the run worked. The server never streams a run's answer.
`functions_orchestration_execution.py` sends `orchestration_step` frames and the occasional notice
thought while steps run, then the whole answer in one `content` frame immediately before `done`.
For the entire run the bubble therefore showed only "Thinking". The
[duplicate progress card fix](ORCHESTRATION_DUPLICATE_PROGRESS_CARD_FIX.md) in 0.261.204 removed
the orchestration lane's card for the same reason, but left this placeholder.

The owner can't be inferred from the orchestration store. The composer only blocks sending while
`streaming` is true, so a chat reply can be sent while a run waits for a durable result or is being
reconciled after a dropped connection. That run is still in flight on its card. Hiding the bubble
whenever a run was in flight would also have hidden the chat reply's **Thinking**.

## Technical details

### Files modified

- `application/v2_ui/src/stores/chatStore.ts`
  - Adds `OrchestrationSurfacePhase` (`planning` or `running`) and `orchestrationSurface`. This
    state records which phase holds the open conversation's `streaming` flag, or null for a chat
    stream.
  - `orchestrationSurfaces` is now a `Map` from conversation id to phase. Leaving and reopening a
    conversation, and a server re-key in `reassignOrchestrationTurn`, keep the phase.
  - `beginOrchestrationTurn` takes an optional trailing `phase` that defaults to `planning`, so
    existing callers are unchanged. Every visible branch of `settleOrchestrationTurn` releases it,
    `selectConversation` restores it with `streaming`, and `startNewConversation` clears it.
  - `sendMessage`, `resumeChatStream`, `retryMessage` and `editMessage` set
    `orchestrationSurface: null` when they take the flag.
- `application/v2_ui/src/lib/orchestrationController.ts`: `executeSavedPlan` takes the surface as
  `running`. Stop, the composer lock and thought collection are unchanged.
- `application/v2_ui/src/stores/orchestrationStore.ts`: adds `selectActiveTurnRunInFlight`. It is
  true exactly when `ActiveOrchestrationCard` draws the plan card's running row: the active turn has
  a plan, no pending question, and a run in flight.
- `application/v2_ui/src/components/chat/MessageList.tsx`: `StreamingBubble` changes in two ways.
  - **Running:** while the run holds the surface and the card is drawing it, the bubble draws
    nothing until the answer arrives, and then shows only the answer. If the card is not drawing
    the run, the bubble shows as usual, so a run always has an indicator.
  - **Planning:** the label is **Planning** instead of **Thinking**.
- `application/v2_ui/src/lib/orchestrationPlan.ts`: adds `describeRunProgress`, which writes the
  running card's status line.
- `application/v2_ui/src/components/chat/OrchestrationPlanCard.tsx`: the running row's status line
  comes from `describeRunProgress`. The row's layout, step count and **Review** are unchanged.
- `application/single_app/config.py`: version bumped to `0.261.253`.

### Status line

The first matching row wins.

| Run state | Status line |
|---|---|
| The plan is waiting | Waiting for results |
| A step is running | Its kind of work and title, for example "Gathering: Read quarterly reports" |
| A step is waiting | Waiting for results |
| Every enabled step is completed, partial, skipped, failed or cancelled | Preparing the answer |
| No enabled step has reported yet | Starting |
| Between two steps | No line |

Disabled steps are ignored. A running step without a role shows its title, and one without a title
shows its role.

### Tests

- `functional_tests/test_v2_orchestration_run_progress_status.mjs`, run with `node`, executes
  `describeRunProgress` for the status line cases above, including:
  - role labels for gather, reason and render steps, with fallbacks;
  - several steps running at once;
  - a run whose only step failed;
  - disabled steps;
  - waiting runs and waiting steps.
- `functional_tests/test_v2_orchestration_streaming_surface.mjs`, run with `node`, drives the real
  controller and stores against held SSE streams. It checks that:
  - the planner holds the surface as `planning` and an approved run holds it as `running`;
  - an auto-approved plan hands the surface straight to the run;
  - a chat reply sent while a run waits takes the flag as a chat stream, with the run still on its
    card;
  - the phase survives leaving, returning and a server re-key;
  - the run's notice reaches the finished answer's reasoning steps;
  - every write that takes `streaming` names its owner.
- `ui_tests/test_v2_orchestration_streaming_bubble.py` runs the production controller, stores, SSE
  reader, `MessageList` and plan card in Chromium. It checks that:
  - while planning, only the toggle and **Planning** show;
  - for a manually approved run, only the card shows, and its status line moves through
    "Starting", "Gathering: Read quarterly reports", "Gathering: Investigate context",
    "Reasoning: Write the comparison" and "Preparing the answer";
  - a mutation observer confirms **Thinking** was never drawn during the turn;
  - an auto-approved plan goes from **Planning** straight to the run card;
  - the finished answer's "1 reasoning step" toggle still reveals the run notice;
  - a stream that is not the run's shows **Thinking** beside the card;
  - a tabular turn keeps its progress card.

  Before the fix, the four orchestration tests failed and the tabular test passed.
- `ui_tests/test_v2_new_chat_reset.py` now looks for **Planning** while a turn plans and for the
  running card while a plan runs. A new chat must show neither, nor **Thinking**.
- `ui_tests/test_v2_reasoning_controls.py` scopes its run-correction status locator to the
  reasoning notice, because the running card's own status line ("Starting") is also a status.
- `functional_tests/test_v2_new_chat_reset.py` and `functional_tests/test_v2_stream_reconnect.py`
  check the new map bookkeeping and label expression. Their intent is unchanged.

## Impact

- **Planning:** the bubble shows the reasoning-step toggle and **Planning**.
- **Running:** the plan card alone shows progress, with a status line that names the work. **Stop**
  and the locked composer behave as before.
- **Finished:** the answer shows as before. Notices the run raised are under its reasoning steps.
- **Chat:** chat streams are unchanged, including a reply sent while a run waits in the same
  conversation.
- **Server:** unchanged. Stream frames and saved messages are the same.

## Validation

- **Before:** after **Approve**, the thread showed "Thinking" in a bubble above a card reading
  "Generate and evaluate potential app names… 0/1 Review" and "Reasoning".
- **After:** the thread shows only the card, with a status line such as "Reasoning: Draft candidate
  names", then the answer.
- `npm --prefix .\application\v2_ui run typecheck` and the production `vite build` pass.
- Both new Node tests pass, as do `functional_tests/test_v2_orchestration_progress_lane.mjs`,
  `test_v2_new_chat_reset.py`, `test_v2_stream_reconnect.py`, `test_v2_stream_leave_without_cancel.py`
  and `test_v2_prompt_composer_card.py`, which calls `beginOrchestrationTurn` with positional
  arguments.
- These UI suites pass:
  - `ui_tests/test_v2_orchestration_streaming_bubble.py`
  - `ui_tests/test_v2_new_chat_reset.py`
  - `ui_tests/test_v2_orchestration_planning_retry.py`
  - `ui_tests/test_v2_orchestration_plan_card.py`, run with `python`
- The wider regression sweep also passes. Run on their own, each of these suites passes:
  - approval persistence, auto open, conversation context, model picker, outputs, recovery,
    dependency plans, actions, and workflow run links and cards;
  - reasoning controls, the elicitation and prompt composers, and the admin orchestration
    settings.

  The composer, drawer views, elicitation, pending approval resume, plan editing and run
  hydration suites pass when run with `python <file>`, as they are written to be.

## Related

- [Chat Orchestration](../features/CHAT_ORCHESTRATION.md), under "Stream events"
- [Orchestration Duplicate Progress Card Fix](ORCHESTRATION_DUPLICATE_PROGRESS_CARD_FIX.md)
- [V2 New Chat Reset Fix](V2_NEW_CHAT_RESET_FIX.md), which introduced the per-conversation surface
  bookkeeping this fix extends
