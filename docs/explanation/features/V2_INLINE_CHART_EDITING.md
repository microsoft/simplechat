# V2 Inline Chart Editing

## Overview

A generated chart in a reply used to be final. If the model picked a pie where a bar was
wanted, put a scale on the axis that flattened the whole story, left the axes unnamed, or got a
single number wrong, the only remedy was to ask again in the thread — which produced a second
near-duplicate chart sitting below the first, with no indication of which one was current.

This feature makes a rendered `simplechart` block editable in place:

- **A data grid** for the numbers: edit any value or label, rename series, add and remove rows
  and series.
- **Design controls** for the chart type, its titles, the legend, bar width, line and point
  styling, the doughnut hole, and gridlines.
- **Axis controls** for the axis names, an explicit value range, a linear or logarithmic scale,
  and the angle and thinning of crowded category labels.
- **A source editor** for the payload itself, validated as it is typed.
- **A scoped AI conversation** that changes the chart in front of it without adding anything to
  the thread.
- **A revision history** with restore, recording who made each change and what it was.

It is the sibling of [V2 Inline Diagram Editing](V2_INLINE_DIAGRAM_EDITING.md) and shares its
storage, its routes and its guarantees. The message's stored content is never rewritten, and
only the version currently on screen is ever sent to the model.

**Implemented in version: 0.261.059**

### Dependencies

None added. Chart.js is already vendored under `application/v2_ui/public/vendor/` and loaded on
demand, and the AI edit uses the chat deployment already configured in Admin Settings. There is
no new settings toggle and no new admin surface.

## Architecture

### Every control is an edit to the chart's own source

The single design decision everything else follows from: a control does not set hidden state, it
rewrites the chart's payload. Choosing a bar width produces a new version of the JSON in the
fence, stored as a revision.

That is what makes a control change behave like every other edit. It appears in the history, it
can be restored, it survives a round trip through the source editor, it is honoured by the
server-side export, and a reader in the classic interface sees it. A parallel "chart settings"
store would have had none of those properties and would have had to be kept in step with the
source by hand.

The transforms live in `application/v2_ui/src/lib/chartEdits.ts` and are pure
source-to-source functions, in the same way `mermaidLayout.ts` is for diagrams.

Two rules protect a payload while it is being rewritten:

1. **A transform mutates the raw parsed payload, never the normalised `ChartSpec`.** The spec
   fills in defaults and drops fields this client does not read, so round-tripping through it
   would quietly delete whatever the chart action wrote that the renderer ignores.
2. **The serialised form follows the source it came from.** The chart action emits compact
   single-line JSON; pretty-printing it on the first control click would inflate a large payload
   towards the size limit a revision may be stored at. The **Lay it out** button in the Source
   tab spreads it over lines when someone actually wants to read it.

A hand-written payload — the indented `key: value` form a model sometimes produces instead of
JSON — is the one case where the form changes. It is read with the same tolerant parser the
renderer uses and written back as JSON, because there is no faithful writer for a format that
only has a reader.

### One save for the whole panel

The diagram editor saves the moment a layout button is pressed, which is right when there are
two buttons. A chart has a few dozen controls, so the same rule would file twenty documents and
produce a history nobody can read.

Instead the whole panel edits a draft, the preview follows it live, and one **Save version**
records the lot with an automatically written note naming what changed — "Bar width, Value axis"
rather than "Edited". **Discard changes** puts the draft back to the saved version.

### Storage is the block revision overlay

Charts reuse the storage, addressing and routes that diagrams already use, described in full in
[V2 Inline Diagram Editing](V2_INLINE_DIAGRAM_EDITING.md). Nothing about it needed to change:
`BLOCK_REVISION_KINDS` in `functions_message_block_revisions.py` gained `simplechart`, and the
rest already worked, because a revision is a length-capped string filed against a fence
language and the module has never known what a diagram is.

```
metadata.block_revisions.simplechart["0"] = {
  "source_hash": "65df990d",
  "current": 2,
  "revisions": [ ... ],
  "chat": [ ... ]
}
```

The `source_hash` is a fingerprint of the block's **original** payload, which is also what
per-block colours are filed under. Keying both off the original is what lets a recoloured chart
keep its colours after it is edited.

### Colours are not edits

A chart can be changed in two independent ways, and the distinction is deliberate:

| | Series colours and background | Everything else |
|---|---|---|
| Stored as | A reader's preference | A revision of the block |
| Visible to | The person who chose them | Everyone |
| Where | `visual_styles` metadata | `block_revisions` metadata |
| Control | The palette menu on the chart | The **Edit** button |

## Payload additions

The chart payload gained the following `options` keys. All are optional, and every default is
what charts written before the editor already did — so an untouched chart renders identically,
which is verified against the previously committed renderer.

| Key | Range | Default | Meaning |
|---|---|---|---|
| `yMin`, `yMax` | any number | unset | Explicit value-axis bounds |
| `yScale` | `linear`, `logarithmic` | `linear` | How the value axis steps |
| `xTickRotation` | 0–90 | `0` | Angle of the category labels |
| `xTickLimit` | 2–200 | unset | Most category labels to draw before thinning |
| `barWidth` | 0.1–1 | `0.9` | Share of its slot a bar fills |
| `lineWidth` | 0–10 | `2` | Series stroke width |
| `pointRadius` | 0–20 | `3` | Point marker size |
| `showGridX`, `showGridY` | boolean | `true` | Gridline visibility per axis |

Three options the payload format already had were parsed by every renderer and applied by none.
The editor offers controls for them, so they are now wired up: `smooth` (line curvature), `fill`
(shading under a line) and `showDataTable` (whether the numbers are offered beneath the chart).

### The value axis is not always the y axis

`yMin`, `yMax`, `yScale`, `beginAtZero` and `yAxisLabel` describe the axis that carries the
**values**. On a horizontal bar chart that axis runs along the bottom, so all of them are
applied to x instead. The server-side export has always swapped the axis *titles* this way; the
V2 and classic renderers now swap the rest to match, so a range or a logarithmic scale lands on
the axis that actually has numbers on it.

A logarithmic axis cannot show zero, so "start at zero" is dropped while one is chosen, and a
lower bound of zero or less is ignored. The Axes tab says so rather than leaving the toggle
looking broken.

## Using it

Every chart in a reply has an **Edit** button in its toolbar. A chart showing something other
than what the model first produced carries a dot beside it.

### Data

A grid of the chart's numbers. For a normal chart the rows are the labels and the columns are
the series; for a scatter or bubble chart each series gets its own list of x/y pairs.

- An **empty cell is a gap**, not a zero, so a line is drawn straight past it rather than
  dropping to the axis.
- Editing the numbers **removes the payload's stored `table`**, because that table is a copy of
  them and a stale copy contradicts the chart above it. The disclosure under the chart keeps
  working: it is derived from the labels and series whenever there is no stored table.
- A chart with more than 200 rows is **not** shown as a grid. A grid that showed part of the
  data would delete the rest when saved, so oversized charts are sent to the Source tab, which
  shows all of it, and to Ask AI, which can change numbers in bulk.

### Design

Chart type, titles, legend, bar width, orientation, stacking, line and point styling, the
doughnut hole, gridlines, and whether the data table is offered.

Chart type switching is offered only between compatible shapes. A scatter chart's data is a
list of x/y pairs and a bar chart's is one value per category; neither can be read as the other,
so the switch is not offered and the panel says why. Pie, doughnut and polar area are offered
only for a chart with a single series, because a pie of five series is five concentric rings.

### Axes

Axis names, an explicit minimum and maximum, start-at-zero, a linear or logarithmic scale, and
the angle and thinning of the category labels. A part-to-whole chart has no axes and the tab
says so instead of showing controls that do nothing.

### Source

The payload itself, checked as it is typed — for length, for a line that would break out of the
fence, and for whether it is still a chart that can be drawn. **Lay it out** spreads the
single-line JSON the chart action writes over several lines.

### Ask AI

Describe a change in words. The model is given only this chart's current payload, this chart's
own sub-conversation, and the request that produced it — not the thread. The reply becomes a new
revision, and nothing is added to the conversation.

The chart prompt differs from the diagram one in two ways worth knowing. It names the payload's
own fields, so the model rewrites a document whose shape the renderer already enforces. And it
**forbids inventing data**: if an instruction asks for numbers that are not present and cannot
be derived from the ones that are, the model is told to leave the data alone and change only
what it can. A chart is evidence, and a model that quietly fills in missing values makes it a
lie.

The reply is checked for actually being a chart before it is stored, so a model that returns
prose produces an error rather than a stored revision that draws as a broken block.

### History

Every version, oldest first, with who made it and what changed. Restoring moves a pointer rather
than discarding newer versions, and the version the model originally produced is never removed.

## The other places a chart is drawn

A chart is rendered in three separate implementations, and an edit has to reach all of them or
the same conversation disagrees with itself.

| Where | What it does with an edit |
|---|---|
| **V2** (`inlineChartSpec.ts`, `ChartCanvas.tsx`) | Draws the current revision |
| **Classic** (`chat-inline-charts.js`) | Resolves and draws the current revision, read-only |
| **Export** (`functions_chart_export.py`, matplotlib) | Renders the current revision with every option applied |

Editing itself happens only in V2. The classic client resolves revisions through
`chat-block-revisions.js`, shared with the diagram renderer, so the rule — find by position,
confirm by fingerprint, fall back to an unambiguous fingerprint match, and otherwise leave the
original alone — has one implementation rather than two that could drift.

## File structure

```
application/v2_ui/src/
  lib/chartEdits.ts               Source-to-source transforms, validation, change summaries
  lib/inlineChartSpec.ts          Payload parsing and Chart.js configuration
  lib/blockRevisions.ts           The revision hook, shared with diagrams
  components/chat/ChartEditor.tsx         The editor panel
  components/chat/ChartDataGrid.tsx       The numbers
  components/chat/ChartEditorControls.tsx Form controls
  components/chat/ChartCanvas.tsx         The only place a Chart.js instance is created
  components/chat/InlineChart.tsx         The chart in a reply

application/single_app/
  functions_message_block_revisions.py    Storage, addressing and substitution
  functions_block_revision_assist.py      The scoped model call, per kind
  functions_chart_export.py               The matplotlib renderer
  static/js/chat/chat-block-revisions.js  Shared revision resolution for the classic client
  static/js/chat/chat-inline-charts.js    The classic chart renderer
```

## Testing and validation

- `functional_tests/test_v2_chart_editor.py` — 23 checks covering the storage guarantees, the
  assist prompt, the classic and export renderers, route protection, and the editor's own
  structure. It renders real PNGs through matplotlib to prove the new options reach the export,
  that a value range actually moves the axis on a horizontal bar chart, and that a hostile
  payload cannot take the export down.
- `functional_tests/test_v2_chart_editor_logic.ts` — 76 behavioural checks on the transforms,
  bundled with esbuild and run under node by the test above.
- `functional_tests/test_message_block_revisions.py` — the shared storage layer.
- `functional_tests/test_v2_diagram_editor.py` — the sibling feature, including the
  three-implementation fingerprint parity check.

### Known limitations

- **A chart payload is capped at 20,000 characters**, like any other revision. A chart carrying
  a very large embedded `table` may exceed it, and the editor reports that plainly rather than
  truncating.
- **Colour overrides are keyed by position.** Adding or removing a series after choosing
  per-series colours shifts which series a saved colour lands on.
- **The classic client's colour editor rewrites the stored message.** That changes the fence
  body, so the fingerprint an edit was filed under stops matching and the revision stops
  resolving. The failure is graceful — the original chart is shown — but the two features do not
  compose. This predates the chart editor.
- **The export renderer does not group non-stacked bars side by side.** This also predates the
  chart editor and is unrelated to bar width, which scales whatever bars are drawn.
