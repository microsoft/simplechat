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

**Implemented in version: 0.261.028**

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

## API

### `POST /api/message/<message_id>/visual-style`

Saves or clears the colours for one block.

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
  }
}
```

A `style` of `null` removes the entry, which is not the same as saving a style that happens to
equal your current default: a removed entry follows the default when the default later changes.

The response returns the whole stored map for the message, not just the entry that changed:

```json
{
  "success": true,
  "message_id": "msg-456",
  "visual_styles": {
    "simplechart": { "1": { "palette": "vivid", "background": "#ffffff", "colors": {}, "source_hash": "a1b2c3d4" } }
  }
}
```

The endpoint authorizes the **conversation**, not the message. A diagram lives in an assistant
message, which carries no author of its own, and authorizing the conversation also admits a
participant acting inside a shared conversation.

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
  message. A message document cannot be grown without bound by repeated requests.

The rendering guarantees that were already in place are unchanged. Mermaid still runs at
`securityLevel: 'strict'` with `htmlLabels: false`, its output still passes through DOMPurify
as an independent second boundary, and `bindFunctions` is still never called.

## File structure

| File | Purpose |
|---|---|
| `application/v2_ui/src/lib/visualPalettes.ts` | Presets, colour maths, Mermaid theme mapping, fingerprint, resolver |
| `application/v2_ui/src/lib/svgRaster.ts` | SVG element to PNG data URI |
| `application/v2_ui/src/lib/blockVisualStyle.ts` | Hook resolving and saving one block's style |
| `application/v2_ui/src/components/chat/VisualStyleMenu.tsx` | The shared colour controls |
| `application/v2_ui/src/components/chat/MermaidDiagram.tsx` | Diagram rendering, toolbar and PNG download |
| `application/v2_ui/src/components/chat/InlineChart.tsx` | Chart rendering and toolbar |
| `application/v2_ui/src/lib/richBlocks.ts` | Fence languages and the streaming placeholder guard |
| `application/v2_ui/src/lib/rehypeRichBlockIndex.ts` | Numbers the blocks on the parsed tree |
| `application/single_app/functions_message_visual_styles.py` | Server-side validation and storage rules |
| `application/single_app/route_backend_chats.py` | The `visual-style` endpoint |
| `application/single_app/route_backend_users.py` | Allowlisting and validating the two defaults |

## Testing

- `functional_tests/test_v2_visual_style_controls.py` — validation rules, storage bounds,
  endpoint protections, sanitizer boundaries, and the PNG download wiring.
- `functional_tests/test_v2_visual_style_logic.ts` — behavioural checks of the colour and
  fence-numbering logic, bundled with esbuild and run by the test above when the front-end
  toolchain is installed.

The most important assertion is a negative one: a block nobody has recoloured produces
byte-identical Chart.js configuration to before this feature existed, and a diagram nobody has
recoloured keeps Mermaid's stock `default` or `dark` theme. Existing conversations are
unaffected.

## Known limitations

- Colours are stored on personal conversations, which is how the V2 chat loads messages. A
  message reached through the collaboration routes renders with your defaults and does not
  persist a per-block choice.
- Block positions shift if an edit or a mask removes an entire block from a message. The source
  fingerprint makes this fail safe — the override is ignored — rather than applying colours to
  the wrong content.
- A reply that is still streaming has no message to save against, so the control says the
  choice will be kept once the reply finishes. The PNG download works throughout.
