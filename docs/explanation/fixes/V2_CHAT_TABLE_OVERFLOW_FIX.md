# V2 Chat Table Overflow Fix

Fixed in version: **0.261.425**

## Issue and root cause

Wide tables in V2 assistant replies could extend past their message bubble. Long
identifiers, compact JSON, and URLs contributed an intrinsic table width larger
than the bubble's reading-width limit. Setting the table to `width: 100%` did not
override that minimum content width, and there was no table-local scroll
container.

The normal bubble limits remain useful for prose: wide mode caps bubbles at
`min(64rem, 90%)`, and comfortable mode at `min(46rem, 85%)`. The defect was
applying those limits to evidence tables without handling their layout and
overflow separately.

## Changes

`application/v2_ui/src/components/chat/MessageList.tsx` gives saved assistant
bubbles and the streaming bubble a shared layout class and permits them to
shrink within their flex container. User bubbles retain their existing classes.

`application/v2_ui/src/components/chat/AssistantMarkdown.tsx` wraps each Markdown
table in a bounded horizontal scroll region. The region is keyboard focusable,
has the accessible name **Table**, and shows a focus outline. The semantic
`table`, header cells, data cells, citation substitutions, and safe React
rendering remain intact.

`application/v2_ui/src/styles/theme.css` expands only assistant bubbles that
contain a rendered Markdown table. They can fill the existing conversation
container rather than stopping at the normal bubble reading limit. Comfortable
mode still limits the conversation container; wide mode still allows it to fill
the pane. No preference is changed or persisted by this fix.

Table cells wrap text, including long unbroken records, with
`overflow-wrap: anywhere`. A responsive minimum cell width of
`clamp(3.5rem, 8vw, 8rem)` prevents a short column from collapsing into a narrow
strip beside a long record. Column allocation otherwise remains automatic; the
fix does not impose equal-width columns or reduce the font size.

`application/single_app/config.py` increments `VERSION` from `0.261.424` to
`0.261.425`. The new functional and UI test headers record that implementation
version.

## User-visible behavior and boundaries

Tables use available horizontal space, then wrap their content. If the columns
or non-wrapping content still cannot fit, the reader can scroll the table
horizontally without scrolling the conversation sideways. For example, the
four-column regression fixture fits at 393 pixels but needs local scrolling at
320 pixels when it includes a non-wrapping citation chip. The same text-only
table wraps without horizontal scrolling at 320 pixels.

The shared rules apply as a streamed reply becomes a table, after finalization,
and when the saved message is loaded again. Plain prose messages keep their
existing reading widths. Classic chat, backend APIs, settings, browser assets,
and deployers are unchanged.

Very narrow tables can become tall because content is retained rather than
truncated. Tables with many columns intentionally use the scroll fallback.
Validation used desktop Chromium, including emulated narrow viewports; it does
not constitute real-device or cross-browser qualification.

## Regression coverage

`functional_tests/test_v2_chat_table_layout.py` checks the saved/streaming layout
wiring, unchanged width preferences, rendered-table scoping, wrapping, keyboard
focus, and safe semantic Markdown rendering.

`ui_tests/test_v2_chat_table_layout.py` runs production components, stores, and
production CSS through the existing V2 browser harness. It covers:

- Evidence tables at 320, 393, 768, 1280, and 1920 pixels, in light/dark themes
  and both reading-width preferences.
- Long identifiers, JSON in inline code, long links, and document citations.
- Table and bubble geometry, cell overflow, page/pane containment, minimum cell
  width, unchanged table font size, and narrower ordinary messages.
- Resizing the same conversation, partial streaming, finalization, and remounting
  the saved reply.
- A 30-column table whose final column is reached with keyboard scrolling.

The shared browser fixtures support local Chromium or an existing Azure
Playwright workspace using `DefaultAzureCredential`. No cloud resources or
credentials are created by these tests. Screenshots are written to the ignored
`ui_tests/artifacts/v2-chat-tables/` directory.

## Validation results

The new desktop evidence-table regression failed against the original
implementation: at a 1920-pixel viewport, the table's right edge reached
approximately 4533 pixels while its bubble ended at 1040 pixels. After the fix,
the bubble expands within the conversation and the content stays within its
table scroll region.

| Command | Result |
| --- | --- |
| `npm --prefix .\application\v2_ui run build -- --outDir ..\..\ui_tests\artifacts\orchestration-plan-editor` | Passed TypeScript compilation and production build; Vite reported its existing large-chunk warning. |
| `python .\functional_tests\test_v2_chat_table_layout.py` | 3 passed. |
| `python .\functional_tests\test_v2_mobile_layout.py` | 5 passed. |
| `python -m pytest .\ui_tests\test_v2_chat_table_layout.py .\ui_tests\test_v2_mobile_chat_layout.py -q --tb=short` | 18 passed: 9 table regressions and 9 existing mobile-layout regressions. |
| `python .\functional_tests\test_docs_site_quality.py` | 6 of 6 checks passed. |
| `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` | Passed. |

The adjacent `test_v2_orchestration_streaming_bubble.py` suite was also attempted.
It reported three assertion failures and eight teardown errors: its API stub
does not handle the current pending-question, credential-request, and user-input
reads, and three tests expect a **Review the running plan** button that is not
found. A representative failing test was rerun with all three production UI
files restored to their original source and reproduced both the missing-button
failure and API-stub errors. These unrelated tests were left unchanged.

The required UI detector reported the existing activity-indicator
`animate-bounce` rule and a false positive matching the literal `<img>` in an
accessibility comment. The actual adjacent image has a resolved `src` and an
error handler. Neither finding concerns the table changes; no detector
suppression or unrelated design change was added.
