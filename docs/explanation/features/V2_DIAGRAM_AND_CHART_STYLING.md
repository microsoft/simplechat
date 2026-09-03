# V2 Diagram And Chart Styling

## Overview

The V2 chat renders two kinds of block that are not text: Mermaid diagrams from ` ```mermaid `
fences, and charts from the ` ```simplechart ` fences the built-in chart action emits. Both
were previously fixed in appearance. A diagram followed the light/dark theme and could not be
saved, and a chart used a single built-in palette.

This feature adds:

- **PNG download for diagrams**, matching the download charts already had.
- **Colour palettes and a background colour** for both kinds of block, with per-series and
  per-slice colours for charts.
- **Two levels of persistence**: a default per user, and an override saved against one
  individual block of one message.

**Implemented in version: 0.261.033**

**Shared conversation support added in version: 0.261.039**

### Dependencies

None added. Mermaid, Chart.js and DOMPurify are already vendored under
`application/v2_ui/public/vendor/`, and the rasterizer uses the browser's own canvas. The
Content-Security-Policy in `config.py` is unchanged: it already permits `data:` image sources,
which is what rasterizing an SVG requires.

## How colours are resolved

Three sources are consulted, each overriding the one before it:

| Layer | Where it lives | Applies to |
|---|---|---|
| Built-in default | `PALETTE_PRESETS` in `visualPalettes.ts` | Everything |
| Your default | `v2MermaidStyle` / `v2ChartStyle` in your user settings | Every block you have not singled out |
| Block override | `metadata.visual_styles` on the message | One block of one message |

An override replaces the layer beneath it rather than merging into it. A block you recoloured
keeps the colours you gave it even after you later change your own default, because that is
what "I chose this one specifically" means.

Recolouring one chart does not affect any other. Three charts in a reply have three independent
entries, and a chart with no entry follows your default.

### Identifying a block

A block has no identifier of its own. An override is filed under the block's position among
blocks of the same kind in that message — `mermaid[0]`, `simplechart[1]` — together with a
short fingerprint of the block's source.

The fingerprint exists because a position alone is not a stable identity. If a message is later
edited, or a mask removes a whole block, the block at a given position may be different
content. A stored style whose fingerprint no longer matches is ignored, so the worst case is
that a block falls back to your default rather than being drawn in somebody else's colours.

Positions come from `rehypeRichBlockIndex`, which walks the parsed tree in document order and
stamps each fence with its number, rather than from scanning the markdown text or counting
while rendering. Both alternatives are wrong in ways that matter:

- **Counting during rendering** gives the same block a different number each time, because
  React can re-render one block without touching its neighbours.
- **Scanning the text** disagrees with the parser about what a fenced code block is. CommonMark
  admits fences indented four or more spaces inside a nested list item, and fences behind a
  blockquote's `>` prefix. A scanner that missed those would leave them unnumbered, and an
  unnumbered block would take block zero's slot and overwrite its saved colours.

A block the renderer cannot number is treated as unaddressable rather than defaulted to zero:
its colour control still works for the current view but says the choice will not be kept.

## Palettes

The five presets are the classic interface's `CHART_COLOR_PRESETS`, reused verbatim so a
palette called "Vivid" means the same colours in both interfaces:

| Palette | First colours |
|---|---|
| Default | `#1c6ea4` `#d75b35` `#277b54` `#995c20` `#7e4d8c` |
| Calm | `#2563eb` `#0f766e` `#65a30d` `#0891b2` `#7c3aed` |
| Vivid | `#dc2626` `#ea580c` `#ca8a04` `#16a34a` `#0891b2` |
| Warm | `#b91c1c` `#c2410c` `#ca8a04` `#a16207` `#92400e` |
| Contrast | `#111827` `#2563eb` `#dc2626` `#16a34a` `#ca8a04` |

### Charts

A preset sets every series or slice. Line and bar series get the palette colour as their border
with the same colour at 18% opacity as their fill, matching the classic interface. Pie, doughnut
and polar-area slices are filled solid once styled, because a pale wash is hard to tell one
slice from another.

Individual series and slices can then be changed one at a time. Choosing a preset clears those
individual choices, since a chart showing a mixture is not on any palette.

A chart left on the Default palette keeps whatever colours its own payload asked for. Only the
series you actually changed is overridden, so a chart the model deliberately coloured is not
flattened by adjusting one series.

### Diagrams

Mermaid colours work through theme variables rather than per-shape, so a diagram takes a
palette rather than individual colours. A styled diagram switches to Mermaid's `base` theme
with variables derived from the palette:

- Node fills are the palette colour blended 18% into the background, so a diagram reads as
  tinted boxes with strong borders rather than blocks of solid colour, and the same palette
  works on a light or a dark background.
- Borders are the palette colour itself.
- Line and label colours come from the background's relative luminance, not from the palette.
  An arrow that cannot be seen is worse than one that is not on-palette.

### Background

Both kinds of block offer a background colour, and both default to **Match theme**. That is a
distinct choice rather than a colour that happens to match: a block saved while reading in light
mode follows you into dark mode unless you asked for a specific colour.

For a chart the background is painted by a per-chart Chart.js plugin, so it is part of the
canvas and therefore part of the downloaded PNG. Axis, tick and legend colours are recomputed
from it, so a dark background chosen while in light mode is not labelled in dark grey.

## In a shared conversation

Everything above works the same way in a shared conversation, with one difference that follows
from what a shared conversation is: the choice is stored on the shared message, so it is what
every participant sees, and it changes on their screen as you make it rather than on their next
load. This matches how masking already behaves, and it is the only option that keeps a
conversation looking the same to the people in it.

Because a change is seen by everyone, restyling a block needs the same write access as posting a
message. A read-only viewer sees the colours others chose and can still expand, zoom and
download a diagram.

Your own default palette still applies to every shared block nobody has singled out, so two
participants reading the same untouched chart each see it in their own colours.

## Downloading a diagram

The PNG is rasterized from the SVG already on screen rather than re-rendered, so the file
matches what you are looking at, colours included. The path — serialise, load through an
`<img>`, paint onto a canvas — is the one `static/js/chat/chat-visual-rasterizer.js` already
uses to embed diagrams in exported conversations.

Two details make the difference between a usable file and a broken one:

- The SVG is given explicit pixel dimensions. Mermaid emits `width="100%"` with a `viewBox`,
  and an `<img>` given that has no intrinsic size to rasterize at.
- The canvas is filled opaquely first. A transparent PNG of dark diagram text is invisible on
  any dark surface it is later pasted onto.

Output is 2× scale, capped at 4000 pixels on the longest edge, which is where browsers start
refusing to allocate the canvas.

`htmlLabels` stays off in the Mermaid configuration. It is a security property — labels are SVG
text rather than embedded HTML — and it is also what makes a diagram rasterizable at all, since
a `<foreignObject>` label disappears when an SVG is painted onto a canvas.

## Sizing a diagram

A diagram's panel takes its width from the diagram's own measured natural width, read back out of
the `max-width` Mermaid writes. This matters more than it sounds: the assistant bubble is
shrink-to-fit, and Mermaid emits `width="100%"`, which contributes nothing to intrinsic sizing.
Without a measured width the bubble collapsed to the width of the diagram's toolbar and the
diagram was drawn at roughly a quarter of its natural size.

The stage the diagram sits in is capped at 520 pixels tall by default and scrolls internally.
Without a cap a large flowchart goes straight into the message list — one at Mermaid's own limit
of 500 edges measures over 50,000 pixels tall — where the browser re-rasterizes it on every
scroll frame.

Three controls change what you see:

| Control | Effect |
|---|---|
| `−` / `+` | Scales the diagram between 0.4x and 4x of the scale that fits it to the panel |
| Fit | Returns to fitting the panel width |
| **Expand** | Opens the diagram full screen, with its own zoom and PNG download |

The bar along the bottom edge of the stage is a drag handle. It is exposed as a slider, so it can
be moved with the arrow keys and reset to the automatic height with **Home**. The height you
leave it at is saved on the message alongside the colours, and the two are independent: resetting
the colours does not resize the diagram, and resizing it does not stop it following your default
palette.

Mermaid's `flowchart.wrappingWidth` is set to 500 rather than its default of 200. The default
wraps the long labels models write into narrow columns of text, which makes a diagram taller and
harder to read: the same diagram measures 273 x 955 at 200 and 497 x 867 at 500.

## When a diagram will not render

A diagram that Mermaid rejects falls back to its source, because the source is still the answer
the model gave. The panel says why, behind **Show details**, and offers **Copy source**. The
reason also goes to the browser console.

Before the reader sees any of that, the source is repaired and rendered once more.
`repairMermaidSource()` fixes the mistakes models actually make — reserved words used as node
ids, a capitalised `End`, an unclosed `subgraph`, an empty label, unquoted parentheses or braces,
a bare quote inside a label, two statements run onto one line, a dangling edge, and stray
byte-order marks, non-breaking spaces and smart quotes.

Two properties of the repair matter:

- **It only runs after a failure.** A diagram Mermaid accepts is handed over untouched and can
  never be rewritten, so nothing that renders today can change.
- **It is scoped to flowcharts.** `subgraph`, `end`, square labels and piped edge labels all mean
  something else in the other diagram types — `||--o{` in an `erDiagram`, for one — so anything
  that is not a flowchart is left alone.

Rendering is bounded either way: a diagram is given 10 seconds, and a source longer than 30,000
characters is refused with its own message rather than being attempted.

## API

### `POST /api/message/<message_id>/visual-style`

Saves or clears the colours, and the chosen height, for one block.

```json
{
  "conversation_id": "conv-123",
  "block_kind": "simplechart",
  "block_index": 1,
  "source_hash": "a1b2c3d4",
  "style": {
    "palette": "vivid",
    "background": "#ffffff",
    "colors": { "0": "#123456" }
  },
  "height": 640
}
```

A `style` of `null` removes the colours, which is not the same as saving a style that happens to
equal your current default: a removed entry follows the default when the default later changes.

`height` is optional and independent of `style`. **Omitting the key** leaves whatever height is
stored alone, so changing colours never resets a diagram you resized; **sending `null`** clears
it so the block is sized automatically again. It is validated as a number and clamped to
140–2000 pixels rather than refused, because it arrives from a drag and a value a few pixels past
the limit is someone holding the mouse down, not a client misbehaving.

An entry is removed entirely only once it holds neither colours nor a height.

The response returns the whole stored map for the message, not just the entry that changed:

```json
{
  "success": true,
  "message_id": "msg-456",
  "visual_styles": {
    "simplechart": { "1": { "palette": "vivid", "background": "#ffffff", "colors": {}, "source_hash": "a1b2c3d4", "height": 640 } }
  }
}
```

An entry carrying only a `height` is **not** a colour override. The client tells the two apart by
the presence of `palette`, so a diagram you only resized still follows your default palette
rather than being pinned to the built-in one.

The endpoint authorizes the **conversation**, not the message. A diagram lives in an assistant
message, which carries no author of its own, and authorizing the conversation also admits a
participant acting inside a shared conversation.

### `POST /api/collaboration/conversations/<conversation_id>/messages/<message_id>/visual-style`

The same operation for a shared conversation. Body and response are identical except that the
conversation travels in the path rather than in the body, which is how every other collaboration
message route addresses its conversation.

A shared conversation and its messages live in different Cosmos containers, so the personal
endpoint cannot resolve one and answers 404 for it. Both routes hand the payload to the same
`apply_visual_style` validator, so a value refused in a personal conversation is refused in a
shared one.

Two things differ in behaviour rather than in shape:

- **It requires write access**, not just visibility. The stored choice is on the shared message,
  so it is what every participant sees; a read-only viewer recolouring a chart would be changing
  the conversation for everybody else.
- **It broadcasts.** A `collaboration.message.visual_style_updated` event goes out on the
  conversation's event stream, so other participants' charts change where they are sitting
  instead of on their next load. The event carries the serialized message; the client takes only
  the styles from it and shows no notification, because a colour change is cosmetic.

Unlike message masking, the styles are **not** copied back to the hidden source conversation.
A mask changes what is exported and what the model is later shown; colours change neither.

### `GET /api/conversations/<conversation_id>/kind`

Reports whether a conversation is `personal` or `collaborative`, and confirms it exists. For a
shared conversation the serialized conversation document travels with the answer, so opening one
from a link costs a single request.

This exists because a conversation reached from a link is not in the loaded conversation list and
so has no row to read a kind from. The client used to work it out by calling the personal
metadata endpoint and reading its 404 as "then it must be a shared one" — correct, but it made
the browser log a failed request every time somebody followed a link to a shared conversation.

A conversation the caller may not see is reported as absent rather than forbidden, and a shared
conversation is never named as such while collaborative conversations are disabled by
configuration, since its endpoints would refuse everything.

### User settings

Two keys are accepted by `POST /api/user/settings`:

| Key | Value |
|---|---|
| `v2MermaidStyle` | `{ "palette": "...", "background": "#rrggbb" \| "theme", "colors": {} }` |
| `v2ChartStyle` | Same shape |

Both are validated by `sanitize_visual_style` before storage rather than being stored as sent.

## Security

Colours end up in inline `style` attributes and in Mermaid's theme configuration in a browser,
so the accepted form is deliberately narrow:

- A colour is reduced to lowercase `#rrggbb`, or it is not stored. `red`, `rgb(1,2,3)`,
  `url(...)` and everything else is refused, even though a browser would apply them.
- A palette must be one of the five known identifiers. The server refuses an unknown one; the
  client falls back to the default when *reading* one it does not recognise, because it still
  has to draw something.
- Unknown keys in a submitted style are dropped rather than stored, so a client ahead of the
  server cannot put arbitrary fields into a message document.
- Sizes are capped: block index 0–199, 24 colour overrides per block, 100 styled blocks per
  message, and a block height of 140–2000 pixels. A message document cannot be grown without
  bound by repeated requests.

The rendering guarantees that were already in place are unchanged. Mermaid still runs at
`securityLevel: 'strict'` with `htmlLabels: false`, its output still passes through DOMPurify
as an independent second boundary, and `bindFunctions` is still never called.

## File structure

| File | Purpose |
|---|---|
| `application/v2_ui/src/lib/visualPalettes.ts` | Presets, colour maths, Mermaid theme mapping, fingerprint, resolver |
| `application/v2_ui/src/lib/svgRaster.ts` | SVG element to PNG data URI |
| `application/v2_ui/src/lib/blockVisualStyle.ts` | Hook resolving and saving one block's colours and height |
| `application/v2_ui/src/lib/mermaidSource.ts` | Repairs and describes diagram source Mermaid has rejected |
| `application/v2_ui/src/components/chat/VisualStyleMenu.tsx` | The shared colour controls |
| `application/v2_ui/src/components/chat/MermaidDiagram.tsx` | Diagram rendering, toolbar, PNG download and the full-screen viewer |
| `application/v2_ui/src/components/chat/DiagramStage.tsx` | Natural-size measurement, the bounded stage and the resize handle |
| `application/v2_ui/src/components/chat/InlineChart.tsx` | Chart rendering and toolbar |
| `application/v2_ui/src/lib/richBlocks.ts` | Fence languages and the streaming placeholder guard |
| `application/v2_ui/src/lib/rehypeRichBlockIndex.ts` | Numbers the blocks on the parsed tree |
| `application/single_app/functions_message_visual_styles.py` | Server-side validation and storage rules |
| `application/single_app/route_backend_chats.py` | The personal `visual-style` endpoint |
| `application/single_app/route_backend_collaboration.py` | The shared-conversation `visual-style` endpoint |
| `application/single_app/route_backend_conversations.py` | The conversation-kind endpoint used to open a linked conversation |
| `application/single_app/route_backend_users.py` | Allowlisting and validating the two defaults |

## Testing

- `functional_tests/test_v2_visual_style_controls.py` — validation rules, storage bounds,
  endpoint protections, sanitizer boundaries, and the PNG download wiring.
- `functional_tests/test_v2_collaboration_visual_style_fix.py` — the shared-conversation
  endpoint exercised end to end: what it stores, what it refuses, who may call it, what it
  broadcasts, and the conversation-kind endpoint's answers.
- `functional_tests/test_v2_visual_style_logic.ts` — behavioural checks of the colour and
  fence-numbering logic, bundled with esbuild and run by the test above when the front-end
  toolchain is installed.
- `functional_tests/test_v2_diagram_viewer_controls.py` and
  `functional_tests/test_v2_diagram_viewer_logic.ts` — sizing, the stage cap, the resize handle,
  the expanded viewer, height storage, and the source repair.

The most important assertion is a negative one: a block nobody has recoloured produces
byte-identical Chart.js configuration to before this feature existed, and a diagram nobody has
recoloured keeps Mermaid's stock `default` or `dark` theme. Existing conversations are
unaffected. The repair pass is held to the same standard — it must be a no-op for every diagram
Mermaid already accepts.

## Known limitations

- In a shared conversation the choice is stored on the shared message, so it applies for every
  participant rather than only for you. There is no per-reader override of a shared block.
- Block positions shift if an edit or a mask removes an entire block from a message. The source
  fingerprint makes this fail safe — the override is ignored — rather than applying colours to
  the wrong content.
- A reply that is still streaming has no message to save against, so the control says the
  choice will be kept once the reply finishes. The PNG download works throughout.
