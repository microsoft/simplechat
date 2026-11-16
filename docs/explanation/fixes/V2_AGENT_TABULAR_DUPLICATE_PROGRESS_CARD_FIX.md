# V2 Agent and Tabular Duplicate Progress Card Fix (v0.261.318)

## Issue

When a selected agent responded in V2, an **Agent progress** card appeared above the
collapsed reasoning dropdown. It repeated activity that was already available by expanding
the dropdown: the current tool, latest status sentence, counts, and a progress percentage.
Workbook analysis displayed a similar **Tabular analysis** card. These summaries distracted
from the response and made activity details visible even when the user had not opened them.

Fixed in version: **0.261.318**, tracked by the `VERSION` update in
`application/single_app/config.py`.

## Root cause

`activityLanes.ts` classifies thought events as agent, tabular, or orchestration work.
Its agent and tabular entries set `showsCard: true`. The shared `ThoughtsProgressCard`
renderer therefore drew their summaries above live reasoning and inside a finished answer's
expanded reasoning.

Orchestration already used `showsCard: false` to avoid a duplicate summary beside its plan
and reasoning details. Agent and tabular activity needed the same presentation policy,
without removing the events or changing how tools execute.

## Technical details

### Files modified

- `application/v2_ui/src/lib/activityLanes.ts`: agent and tabular entries now set
  `showsCard: false`. Lane matching, precedence, status counting, and completion handling
  remain unchanged.
- `application/single_app/config.py`: application version incremented to `0.261.318`.
- `functional_tests/test_v2_agent_tabular_progress_cards.mjs`: exercises real lane
  classification for hand-off text, step types, activity kinds, lane keys, and plugins.
- `functional_tests/test_v2_orchestration_progress_lane.mjs`: updates agent/tabular
  expectations while retaining orchestration classification coverage.
- `ui_tests/test_v2_orchestration_streaming_bubble.py`: verifies hidden agent/tabular
  summaries and usable reasoning details with production components and CSS.
- `docs/explanation/features/V2_TABULAR_ANALYSIS.md`: describes the current distinction
  between reasoning activity and background-export status.

The renderer already returns nothing when `showsCard` is false. No component rewrite,
CSS visibility workaround, new setting, route change, or dependency is required.

### User-facing behavior

Both thought-summary cards are removed completely, including their headings, badges,
percentages, progress bars, counters, current-tool summaries, and repeated status sentences.
Their underlying thought records remain available.

The **N reasoning steps** dropdown keeps its existing label and starts collapsed. It still
opens with mouse or keyboard during generation and on finished responses. Tool failures
remain readable there; suppressing the summary does not discard their details.

V1 is unchanged. V2's lightweight **Thinking**/**Planning** indicator, streamed answer,
connection notices, error handling, and orchestration plan/run status are also unchanged.

The separate background-export card is intentionally preserved. `TabularRunStatus.tsx`
still reports durable file generation, polls the server, offers **Continue**/**Cancel** when
allowed, and yields to the finished downloads. That operational status is not the
thought-summary card above the reasoning dropdown.

## Validation

Before the fix, the new lane checks failed because `showsCard` was true, and the desktop-agent
browser case found one progress bar where none was expected. After the fix:

| Check | Result |
|---|---|
| `node --test .\functional_tests\test_v2_orchestration_progress_lane.mjs .\functional_tests\test_v2_agent_tabular_progress_cards.mjs` | 20 passed |
| `npm --prefix .\application\v2_ui run build -- --outDir ..\..\ui_tests\artifacts\orchestration-plan-editor --logLevel error` | Passed, including TypeScript checking |
| `python -m pytest .\ui_tests\test_v2_orchestration_streaming_bubble.py -q` | 8 passed in local Chromium |
| `python .\functional_tests\test_v2_tabular_parity.py` | 13 of 14 checks passed, including all 70 TypeScript logic checks; existing confirmation-handler lookup failure |

Browser coverage includes desktop and mobile agent/tabular turns, collapsed and expanded
reasoning, Enter/Space activation, failed activity, finished answers, and remounted saved
responses. It checks that the whole summary card is absent rather than hiding only its bar.
The existing orchestration planning/running cases also pass.

The wider tabular parity script has an unrelated assertion, **Could not locate the composer
submit handler**. Re-running that check against the unchanged `HEAD` version of `Composer.tsx`
reproduces the same failure. Neither the composer nor that assertion is modified by this fix.

## Related

- [V2 Tabular Analysis](../features/V2_TABULAR_ANALYSIS.md)
- [Orchestration Duplicate Progress Card Fix](ORCHESTRATION_DUPLICATE_PROGRESS_CARD_FIX.md)
