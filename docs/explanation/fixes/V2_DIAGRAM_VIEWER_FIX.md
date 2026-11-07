# V2 Diagram Viewer Fix

Diagrams in the V2 chat rendered too small to read, made long threads unusable, and sometimes
did not render at all with nothing to explain why.

Fixed in version: **0.261.037**

## The reports

1. Diagrams render "really tiny, kind of hard to see" — but clicking **Colors** makes the same
   diagram large enough to read.
2. A long diagram makes the chat "reload" when scrolling, and the bottom of the thread becomes
   unreachable.
3. Some diagrams show **Diagram could not be rendered** and produce no logs at all.
4. There is no way to make a diagram bigger.

## Root causes

Each was reproduced against the vendored mermaid 11.17.2 bundle in Chromium, configured exactly
as `MermaidDiagram.tsx` configures it, before anything was changed.

### 1 and the Colors jump: the diagram contributed no width

The assistant bubble is a shrink-to-fit flex item — `bubbleWidthClass()` supplies a `max-width`
and nothing else, so its width is `min(max-content of its contents, max-width)`.

Mermaid renders with `useMaxWidth: true`, which emits:

```html
<svg viewBox="0 0 1094 541" width="100%" style="max-width: 1094px;">
```

A percentage width contributes essentially nothing to intrinsic sizing, so a message containing
only a diagram collapsed the bubble to the width of the diagram's own toolbar, and the
`width: 100%` SVG then scaled itself down to match.

Opening the **Colors** menu revealed the same bug from the other side: `PalettePresets` is a
wrapping row of five labelled swatch buttons, which *does* have a natural width, so the bubble
grew and the diagram grew with it.

Measured in Chromium, using the natural size of the Azure governance diagram from the report:

| | Panel | Diagram drawn at |
|---|---|---|
| Before | 358px | 300px — 27% of natural size |
| Before, Colors open | 575px | 517px — 47% of natural size |
| After | 1024px | 966px — 88% of natural size |
| After, Colors open | 1024px | unchanged |

### 2: nothing bounded a diagram's height

The diagram stage had no height cap. A flowchart at mermaid's own default limit of 500 edges
measures **50,466 pixels tall**, and that went straight into the message list, where the browser
re-rasterizes it on every scroll frame.

Two further faults compounded it:

- `MessageBubble` was not memoised, and `readMaskState()` ran unmemoised on every render. The
  list re-rendered on every streaming token *and* every time the scroll crossed the
  pinned-to-bottom threshold, so the entire remark/rehype pipeline re-ran for every message in
  the thread each time.
- The auto-scroll effect ran on `[messages, streamingContent, pinnedToBottom]`. A diagram
  renders **asynchronously**: a 96px placeholder is replaced by a much taller panel long after
  the scroll that was meant to land at the bottom. Nothing re-ran, so the bottom stayed out of
  reach.

### 3: the error was thrown away

```ts
.catch(() => {
    if (!cancelled) {
        setState({ status: 'error' });   // the error object is never read
    }
});
```

No message, no `console.warn`, nothing in the panel beyond the words "Diagram could not be
rendered". The classic client at least logged the error
(`chat-inline-diagrams.js`). There was also no render timeout and no source-size guard, both of
which the classic client has.

Twelve distinct parse failures were reproduced, all of them things models actually write:

| Source | Mermaid's response |
|---|---|
| `end["End"]` as a node id | Parse error — `end` is reserved |
| `graph`, `class`, `style` as node ids | Parse error — all reserved |
| `End` closing a subgraph | Parse error — only lowercase `end` is accepted |
| A `subgraph` with no `end` | Parse error, reported at the last line of the diagram |
| `a[""]` | Parse error |
| `a[App (main)]` | Parse error |
| `a -->|metadata: {}| b` | Parse error |
| `a["He said "hello" loudly"]` | Parse error — the string token ends at the second quote |
| `a["A"] b["B"]` on one line | Parse error |
| A trailing `b -->` with no target | Parse error |
| A leading byte-order mark | "No diagram type detected" |
| 500 edges | "Edge limit exceeded" |

### An additional finding: label wrapping

Mermaid's `flowchart.wrappingWidth` defaults to 200px, which turns the long labels models write
into narrow columns of text — making a diagram *taller* and harder to read. The same
label-heavy diagram measures:

| `wrappingWidth` | Natural size |
|---|---|
| 200 (mermaid's default) | 273 x 955 |
| 500 | 497 x 867 |

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/components/chat/MermaidDiagram.tsx` | Error reporting, render timeout, source guard, repair-and-retry, zoom, expanded viewer, panel width from measured natural size |
| `application/v2_ui/src/components/chat/DiagramStage.tsx` | New. Natural-size measurement, bounded scrolling stage, resize handle |
| `application/v2_ui/src/lib/mermaidSource.ts` | New. `repairMermaidSource()`, `isRepairWorthTrying()`, `describeMermaidError()` |
| `application/v2_ui/src/components/chat/MessageList.tsx` | Memoised bubbles, pinned flag moved to a ref, `ResizeObserver` re-pin |
| `application/v2_ui/src/lib/blockVisualStyle.ts` | Reads and writes a stored height alongside the colours |
| `application/v2_ui/src/lib/endpoints.ts`, `src/stores/chatStore.ts` | Optional `height` on the visual-style request |
| `application/single_app/functions_message_visual_styles.py` | Validates, clamps and stores `height` independently of the colours |
| `application/single_app/route_backend_chats.py` | Accepts `height`, distinguishing "absent" from "null" |
| `application/single_app/functions_diagram_operations.py` | Guidance covering reserved words, terminators, placeholders and label length |

## What changed in behaviour

**Sizing.** The panel takes its width from the diagram's measured natural width, floored so the
toolbar never wraps and capped at the bubble. Because the width is now definite, the Colors menu
can no longer resize anything.

**Height.** The stage is capped at 520px by default and scrolls internally, so a tall diagram is
a panel rather than a wall. A drag handle on its bottom edge sets a different height; it is a
slider, so it works from the keyboard, with **Home** returning to the automatic height. The
chosen height is stored on the message beside the colours.

**Zoom and expand.** `−`, `+` and a fit control scale the diagram between 0.4x and 4x of the
fit-to-width scale. **Expand** opens a full-screen viewer with its own zoom and PNG download,
following the same conventions as the existing image lightbox.

**Failure reporting.** The reason is kept, logged with `console.warn`, and shown in the fallback
panel behind **Show details**. The panel also offers **Copy source**. Mermaid's limit errors are
reworded — "Edge limit exceeded. 500 edges found, but the limit is 500." becomes "The diagram has
too many connections to draw."

**Repair and retry.** When mermaid rejects a diagram, `repairMermaidSource()` rewrites it and it
is tried once more. The repair runs **only after a failure**, so a diagram that renders today is
handed to mermaid untouched and can never be changed by it. It is also scoped to flowcharts:
`subgraph`, `end`, square labels and piped edge labels all mean something else in the other
diagram types, and `||--o{` in an `erDiagram` must survive intact.

## Validation

`functional_tests/test_v2_diagram_viewer_controls.py` — 18 checks, including 58 bundled
TypeScript behaviour checks in `test_v2_diagram_viewer_logic.ts`.

Verified in Chromium against the real mermaid bundle:

- All 14 reproduced parse failures render after repair.
- All 6 working diagrams — flowchart, sequence, state, class, ER, and the two from the report —
  are byte-identical after repair, so `isRepairWorthTrying()` returns false and no second render
  is attempted.
- The layout measurements in the table above.
- `DiagramStage` mounted directly: fit scale, zoom, resize, clamping and reset all measured.

Existing suites re-run and passing: `test_v2_visual_style_controls.py` (16),
`test_v2_rich_rendering.py` (13), `test_chat_inline_diagram_rendering.py` (5),
`test_mermaid_diagram_prompt_guidance.py` (7), `test_export_mermaid_server_render.py` (10),
`test_conversation_export_mermaid_tex_images.py` (18),
`test_export_mermaid_browser_rasterizer.py` (3), and the three route policy suites.

### Issues caught during review

Four defects were found by review and fixed before this shipped. They are recorded because each
was a silent failure rather than a visible one:

1. **A stored height survived a source change.** `apply_visual_style` carried the previous
   entry's height forward without comparing its `source_hash` to the incoming one, then stamped
   the entry with the *new* fingerprint. A height chosen for a block that an edit had shifted out
   of that position was resurrected and made authoritative for different content — defeating the
   fingerprint guard the client already honours.
2. **Renaming a reserved id ate the subgraph terminators.** `end` is both the most common
   reserved node id models use and the keyword that closes a `subgraph`. Renaming every
   occurrence rewrote the terminators too, so `balanceSubgraphs` then appended one at the bottom
   and everything after the original terminator was swallowed into the group. The result still
   parsed, so it showed the wrong structure rather than an error.
3. **A pipe inside a node label was paired with the edge-label pipe.** `a["A|B"] --> |"yes"| b`
   had the arrow itself escaped into the middle of a label, which could destroy a line that was
   not the reason the diagram failed. Square node labels are now stashed before the edge pass
   runs, and a line with an odd number of pipes is left alone rather than paired by guesswork.
4. **`Infinity` as a height returned a 500.** `json.loads` accepts the bare `Infinity` token and
   `round(float('inf'))` raises `OverflowError`, which is not a `VisualStyleError` and so escaped
   the route's handler. Now rejected with a 400.

Each has a regression test.

## Notes

No new npm package and no remote asset. Mermaid and DOMPurify were already vendored locally, so
the `default-src 'self'` Content-Security-Policy is unchanged.

The full-screen viewer is defined inside `MermaidDiagram.tsx` rather than in its own file. It
writes diagram markup to the DOM, and
`test_v2_rich_rendering.py::test_sanitizer_boundary_at_every_html_sink` fixes the set of
components allowed to do that; keeping it in the reviewed file preserves that invariant instead
of widening it.
