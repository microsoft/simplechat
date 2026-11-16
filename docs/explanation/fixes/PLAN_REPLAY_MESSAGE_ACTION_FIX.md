# Plan replay calendar message action fix

Fixed in version: **0.261.338**.

Application version tracking: `application\single_app\config.py`.

## Issue and root cause

Every eligible completed orchestration answer displayed a persistent
**Repeat on a schedule** text button inside its message bubble.
`MessageList.tsx` mounted `PlanReplaySaveCard.tsx` in the answer body, and the
card's collapsed state rendered that button instead of using the existing
message action bar. Scheduling remained useful, but its entry point distracted
from answers even when the reader did not want to create a workflow.

## Changes

`MessageActions.tsx` now renders a calendar icon beside the other message
actions, using the shared `IconButton`, the existing local Lucide icon, and the
incumbent theme. It retains the **Repeat on a schedule** accessible name and
tooltip, and announces whether its associated panel is expanded. Action groups
wrap on narrow screens rather than overflowing as the extra icon appears.

`MessageList.tsx` shares one availability condition between the icon and panel.
The existing feature switches, private active conversation restriction,
completed-run requirement, masking restrictions, and workflow proposal/start/
hand-off exclusions still apply. The open state belongs to the message's run;
a changed run or newly ineligible answer closes the panel without reusing the
previous run's preview.

`PlanReplaySaveCard.tsx` is now a controlled inline panel without a second
collapsed trigger. Choosing the calendar loads the preview and opens the
existing form below the answer, outside the hover-fading action bar.
**Collapse** returns focus to the calendar. Reopening the same eligible plan
preserves its name and description while reloading the preview, as before.

No routes, administrative settings, replay execution rules, schedule defaults,
or save payloads changed. Merely displaying or hovering over an answer does
not fetch a preview or create a workflow.

## Regression coverage

`functional_tests/test_v2_message_actions.py` checks the icon wiring and
controlled, lazy-loaded panel contract. The real-component browser suite in
`ui_tests/test_v2_workflow_plan_replay_card.py` covers placement beside Copy,
hover and keyboard reveal, expansion and collapse, preserved form state,
desktop/light and mobile/dark layouts, prerequisite flags, answer eligibility,
masking and run changes, visible preview failures, paused saving, refusals,
and inert hostile content.

Related client contracts remain covered by
`functional_tests/test_v2_workflow_plan_replay_client.mjs`.

## Validation

The V2 production build passed, including TypeScript compilation. Browser
coverage passed all **27 tests**, including desktop/light and mobile/dark
interaction. The plan-replay client suite passed all **9 tests**. Documentation
inventory/coverage passed all **7 checks**, and site quality passed all
**6 checks**. Regenerating the inventory produced no content change.

The message-action functional suite passed **7 tests** when excluding
`test_retry_and_edit_are_two_step_flows`. The full selected run exposed that
existing test's stale source assertion: it expects `'chat_request':
chat_request`, while the current route returns `'chat_request': body`.
Executing the unchanged test from `HEAD` reproduced the same failure. The
unrelated assertion and production retry behavior were left unchanged.

Commands used from the worktree root:

```powershell
npm --prefix .\application\v2_ui run build -- --outDir ..\..\ui_tests\artifacts\orchestration-plan-editor
.\.venv\Scripts\python.exe -m pytest .\ui_tests\test_v2_workflow_plan_replay_card.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest .\functional_tests\test_v2_message_actions.py -q -k 'not retry_and_edit_are_two_step_flows' --tb=short
node --test .\functional_tests\test_v2_workflow_plan_replay_client.mjs
python .\scripts\build_docs_inventory.py
python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_site_quality.py
git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check
```

Desktop and mobile screenshots confirmed the icon sits beside Retry and that
the expanded form remains outside the answer bubble. The design detector
reported only existing typing-indicator bounce classes and an image-source
false positive on an unchanged, dynamically resolved image. No scheduling UI
finding required a design change, and no detector suppression was added.

## Before and after

Before, eligible answers always contained a text scheduling button.
After, the answer stays uncluttered: the calendar appears with its other
message actions, and the scheduling form appears only when requested.

See [Workflow plan replay](../features/WORKFLOW_PLAN_REPLAY.md),
[Chat controls](../../reference/chat-controls.md#saved-chat-plans-v2-interface),
and [Create a workflow](../../guides/create-a-workflow.md#repeat-a-chat-plan-on-a-schedule).
