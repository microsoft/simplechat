# Orchestration Duplicate Progress Card Fix (v0.261.204)

## Issue

While Orchestrate planned a question in the V2 chat, the reply bubble described the same wait
three times. Above the "1 reasoning step" toggle and the **Thinking** indicator sat an
**Orchestration** progress card with "Current step: Building a plan", a 45% badge, "0/1 step |
1 running", a progress bar and the planner's latest sentence, "Deciding what this question
needs." Expanding the toggle showed that sentence again as an `orchestration_planning` step.

The card added nothing the toggle did not already say, and its numbers meant nothing. It stayed
at 45% for as long as the planner worked and disappeared as soon as the plan arrived. It never
showed progress, it only made a short wait look busier. Run-time notices, such as a saved-memory
warning or a reasoning adjustment, are also orchestration steps, so the card came back during a
run beside the plan card, which already shows the run's progress. It came back again in a
finished answer's expanded reasoning.

Fixed in version: **0.261.204**, tracked in `application/single_app/config.py`.

## Root cause

Progress cards are drawn from a lane table in `activityLanes.ts`. Orchestration was declared
there like tabular analysis and agent calls, so any turn whose steps carried
`activity.lane_key = "orchestration"` or an `orchestration_*` step type drew the same card.

That card suits tabular analysis, which reports one workbook tool call after another for
minutes. An orchestrated turn reports nothing like that. The planner sends one running
"Building a plan" step until the plan arrives, and the run's progress lives on the plan card,
which counts completed steps and names the running one, and in the drawer. The card had one
activity to count, so its percentage came from the generic bands, where one running activity
is 45%.

The lane itself is still needed. A turn keeps the first specific lane its steps match, and only
the general agent lane can be replaced. Without an orchestration entry, orchestration steps
would match no lane, and an agent hand-off later in the same turn would draw an "Agent progress"
card instead.

## Technical details

### Files modified

- `application/v2_ui/src/lib/activityLanes.ts`: `LaneDefinition` gains `showsCard`. Tabular and
  agent lanes set it to `true`. The orchestration lane sets it to `false`, with the reason next
  to its entry. `buildLaneProgress` passes the flag through on `lane`.
- `application/v2_ui/src/components/chat/ThoughtsList.tsx`: `ThoughtsProgressCard` draws nothing
  when the lane's `showsCard` is `false`. That covers both places the card appears: the live
  streaming bubble and a finished answer's expanded reasoning.
- `application/single_app/config.py`: version bumped to `0.261.204`.

### Tests

- `functional_tests/test_v2_orchestration_progress_lane.mjs`, run with `node`:
  - Planning, plan-ready, saved-memory and reasoning-adjustment steps land in the orchestration
    lane with `showsCard` false, whether live or finished.
  - Each `orchestration_*` step type is claimed without an activity payload.
  - An agent hand-off inside an orchestrated turn stays in the orchestration lane.
  - Tabular, agent-then-tabular and agent turns keep `showsCard` true.
  - Ordinary reasoning still forms no lane.
- `ui_tests/test_v2_orchestration_streaming_bubble.py` runs the production controller, stores,
  SSE reader, `MessageList` and plan card in Chromium with production CSS. It holds the plan and
  run streams open and feeds them server-shaped frames one at a time.
  - While planning, only the toggle and **Thinking** show. The toggle is the first element in
    its panel, above **Thinking**. There is no progress bar, percentage, step count,
    "Current step" line or card heading, and the planner's sentence stays hidden until the
    toggle is expanded.
  - When the plan arrives, **Thinking** gives way to **Approve and run the plan**.
  - No card is drawn during the run or in the finished answer's expanded reasoning.
  - A tabular turn still draws its **Tabular analysis** card.
  - Before the fix, both orchestration tests failed at the card assertions and the tabular test
    passed.

## Impact

- While an orchestrated turn plans, it shows the reasoning toggle and **Thinking**. While it
  runs, the plan card shows the step count, the running step and **Review**. The planner's
  steps are still one click away under the toggle.
- Tabular analysis and agent turns keep their progress cards unchanged.
- The server is unchanged. Thought payloads and what is saved with a message are the same, so
  reopened conversations also show no card.

## Validation

- Before: an **Orchestration** card with "Current step: Building a plan", 45%, "0/1 step | 1
  running", a progress bar and the planner's latest sentence sat above the toggle and
  **Thinking**.
- After: only "1 reasoning step" and **Thinking** show. Expanding the toggle shows the
  `orchestration_planning` step "Deciding what this question needs."
- `functional_tests/test_v2_tabular_parity.py`: its 70 TypeScript logic checks pass, including
  the lane table checks.
- `ui_tests/test_v2_orchestration_planning_retry.py` passes unchanged.

## Related

- [Chat Orchestration](../features/CHAT_ORCHESTRATION.md), under "Stream events"
- [V2 Tabular Analysis](../features/V2_TABULAR_ANALYSIS.md), under "Progress lanes"
