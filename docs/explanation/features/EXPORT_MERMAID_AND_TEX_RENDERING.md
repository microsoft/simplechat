# Mermaid And TeX Rendering In Exports

Assistant replies frequently contain Mermaid diagrams and LaTeX formulas. Before this
feature they reached an exported document as raw fenced code, which made a Word file or
PDF unreadable for the person it was sent to. SimpleChat already converted its own
`simplechart` blocks into pictures for every export surface; this extends the same
treatment to Mermaid and TeX.

Implemented in version: **0.261.027**

Dependencies: `matplotlib` (already required, used for the existing chart renderer) and a
vendored copy of Mermaid served from SimpleChat's own static files.

## What it covers

| Export | Charts | TeX formulas | Mermaid diagrams |
|---|---|---|---|
| Conversation Markdown | Image | Image | Image |
| Conversation PDF | Image | Image | Image |
| Message to Word | Image | Image | Image |
| Message to PowerPoint | Image | Image | Image |
| Open in Email | PNG download + reference | PNG download + reference | PNG download + reference |
| Conversation JSON | Untouched | Untouched | Untouched |

JSON is a data format rather than a document, so it keeps the original markdown.

This feature is limited to exports. The classic chat interface does not render Mermaid or
TeX on screen, so a diagram that appears there as a code block appears as a picture in the
exported file. The V2 interface renders both in chat as of 0.261.024, and this makes its
Word and PowerPoint exports carry the formulas it already displays.

## Recognised syntax

Mermaid is read from ` ```mermaid ` fenced blocks.

TeX is read from:

- ` ```math `, ` ```latex ` and ` ```tex ` fenced blocks
- `$$…$$` display math
- `\[…\]` display math

A fence language must match exactly and be followed by a newline, so a ` ```text ` or
` ```mathematica ` block is never mistaken for math.

Single-dollar inline math is deliberately **not** recognised. Detecting it would turn
ordinary prose such as "the unit costs $100 to $200" into a rendered formula. Display math
inside another fenced code block is also left alone, so a Python snippet containing a
`$$` string is never rewritten.

## How each kind is rendered

### TeX

Formulas are rendered on the server by matplotlib's `mathtext` engine, which parses a
large subset of LaTeX math in pure Python. No TeX distribution is installed and no
subprocess is spawned.

`mathtext` covers fractions, roots, sums, integrals, Greek letters, sub- and superscripts
and the common symbol set, but not multi-line environments such as `align`, `matrix` or
`cases`. A formula it cannot parse is left in the document exactly as the model wrote it
rather than failing the export.

The expression is laid out and measured before it is rasterized, and rejected if the
resulting image would be oversized. Spacing commands such as `\hspace` let a very short
expression lay out to an arbitrarily wide box, so an input length limit alone would not
bound the rendered image. A rejected formula keeps its original markup.

Because rendering happens on the server, TeX works on every export path regardless of
which interface started it.

### Mermaid

Mermaid is a browser rendering library, so a faithful diagram needs a real browser
somewhere. SimpleChat uses two, in this order:

1. **The user's browser**, when one is attached to the export. It reads the Mermaid blocks
   out of the message, or calls `POST /api/conversations/export/visual-scan` for a
   conversation export, renders each diagram to SVG, paints it onto a canvas and reads it
   back as a PNG. The PNGs travel with the export request as `visual_assets`.
2. **Headless Chromium on the server**, for anything the browser did not cover — an export
   started from an interface that does not rasterize, or a server-initiated export. The
   container already installs Playwright's Chromium for Source Review and Deep Research
   (`INSTALL_PLAYWRIGHT_CHROMIUM`, on by default), so this costs no new dependency.

Both load the same vendored bundle and use the same configuration, so a diagram renders
identically whichever path produced it.

The server matches each asset to its fence by **normalized source text**, and only renders
diagrams that have no asset already. A client-supplied picture is never re-rendered.

A fence still keeps its code block when neither path can produce an image — for example
when a deployment sets `INSTALL_PLAYWRIGHT_CHROMIUM=false` and the export came from an
interface that does not rasterize.

## Architecture

### Server modules

| Module | Responsibility |
|---|---|
| `functions_export_visuals.py` | Shared wrapper markup, `visual_assets` validation, and the `replace_inline_visual_blocks_with_export_html()` entry point |
| `functions_tex_export.py` | TeX detection and matplotlib `mathtext` rendering |
| `functions_mermaid_export.py` | Mermaid fence detection, source extraction and asset substitution |
| `functions_mermaid_server_render.py` | Headless Chromium rasterization for diagrams no browser covered |
| `functions_chart_export.py` | Existing chart rendering, now using the shared wrapper markup |

Every export surface consumes the same HTML shape, so a new visual kind only has to be
registered once:

```html
<div class="export-inline-diagram">
  <p><img src="data:image/png;base64,..." alt="Flowchart diagram" /></p>
  <p class="export-inline-diagram-caption"><em>Order flow</em></p>
</div>
```

The wrapper classes are `export-inline-chart`, `export-inline-image`,
`export-inline-diagram` and `export-inline-math`.

Rendering order matters: TeX runs first, while code fences are still intact, so display
math detection can skip fenced blocks and never rewrite a chart payload or a Mermaid
source.

### Browser module

`static/js/chat/chat-visual-rasterizer.js` owns diagram rasterization. It is wired into
`chat-message-export.js` for Word, PowerPoint and email, and into `chat-export.js` for
conversation exports.

The Mermaid bundle is roughly 3.5 MB, so it is **not** loaded with the chat page. The
rasterizer injects the script tag only when an export actually contains a diagram.

Mermaid is initialized with `htmlLabels: false`. This is required rather than cosmetic:
Mermaid draws labels inside `<foreignObject>` by default, and `<foreignObject>` content is
dropped when an SVG is painted onto a canvas, which would produce diagrams with shapes and
arrows but no text.

### Vendored asset

Mermaid is pinned and served locally at
`static/js/mermaid/mermaid-11.17.2.min.js`, with its `LICENSE` alongside it, per the
repository's local browser asset rule. The bundle is self-contained: no CDN references, no
web fonts, no worker scripts and no dynamic imports. No Content Security Policy change was
needed, since `script-src 'self'` and `img-src 'self' data:` already permit it.

## API

### Existing endpoints

`POST /api/conversations/export`, `POST /api/message/export-word`,
`POST /api/message/export-powerpoint` and `POST /api/message/export-email-draft` all accept
an optional `visual_assets` array:

```json
{
  "visual_assets": [
    {
      "kind": "diagram",
      "source": "graph TD\n    A[Start] --> B[End]",
      "data_uri": "data:image/png;base64,...",
      "alt": "Flowchart diagram",
      "caption": ""
    }
  ]
}
```

The field is optional everywhere. Omitting it produces the previous behaviour.

### New endpoint

`POST /api/conversations/export/visual-scan`

Request:

```json
{ "conversation_ids": ["conversation-id"] }
```

Response:

```json
{
  "visual_sources": [
    { "kind": "diagram", "source": "graph TD\n    A --> B", "alt": "Flowchart diagram", "caption": "" }
  ]
}
```

The endpoint applies the same ownership and collaboration access checks as the export
route, so it cannot be used to read a conversation the caller could not already export.

## Security

`visual_assets` is user-supplied binary that ends up embedded in a generated document, so
each entry is validated before use:

- the data URI must carry the exact `data:image/png;base64,` prefix
- the decoded bytes must begin with the PNG signature and open as a PNG in Pillow
- decoded size, pixel dimensions, source length and asset count are all capped
- the stored data URI is re-encoded from the validated bytes, so no caller-supplied text is
  echoed back into a document

An individual entry that fails validation is dropped rather than raised, so one malformed
asset cannot fail an entire export.

Server-rendered formulas are held to an equivalent budget: the parsed layout is measured
before rasterization and rejected if it exceeds the pixel or edge limit, and the encoded
PNG is rejected if it exceeds the same byte cap that browser-supplied assets use.

## Known limitations

- `mathtext` does not support `align`, `matrix`, `cases` or other multi-line environments.
  Those formulas keep their original code block.
- A deployment that builds with `INSTALL_PLAYWRIGHT_CHROMIUM=false` has no server-side
  renderer, so a diagram is only rendered when the export came from an interface that
  rasterizes. Otherwise it keeps its code block.
- Server-side rendering launches a browser, which takes roughly a second before the first
  diagram in a request. Exports whose diagrams the client already rasterized never pay it,
  and neither do exports with no diagrams at all.
- V2 vendors its own copy of the same Mermaid version under
  `application/v2_ui/public/vendor/mermaid-11.17.2/` for in-chat rendering. The two
  frontends have separate vendor trees, so the bundle is currently committed twice.
- Conversation exports render at most 60 diagrams per request; a single message export
  renders at most 20.

## Testing

| Test | Covers |
|---|---|
| `functional_tests/test_conversation_export_mermaid_tex_images.py` | TeX rendering across Markdown, PDF, Word, PowerPoint and email; false-positive guards; Mermaid substitution and degradation; asset validation and caps |
| `functional_tests/test_export_mermaid_browser_rasterizer.py` | The vendored bundle has no external assets, and a diagram rasterizes in Chromium to a PNG that still contains its label text |
| `functional_tests/test_export_mermaid_server_render.py` | The capability probe, server rendering with visible labels, error isolation, configuration parity with the browser renderer, and that the route only renders what the client did not |
| `functional_tests/test_conversation_export_inline_chart_images.py` | Existing chart output is unchanged by the shared wrapper builder |

The browser and server rendering tests skip themselves when Playwright or its Chromium
build is unavailable.
