# Mermaid Diagram Rendering

Assistants are good at describing a system, and a diagram is often the clearest way to
show one. SimpleChat can render Mermaid diagrams in chat, but until this change the model
was never told that. Asked to "turn this into a diagram", it fell back on what works in a
plain text box: ASCII box art in a ` ```text ` fence, which arrives as an unreadable code
block and is meaningless to a screen reader.

This feature closes both halves of that gap. The model is now told which fence actually
renders, and the classic chat interface renders that fence instead of printing it.

Implemented in version: **0.261.029**

Dependencies: the vendored Mermaid bundle already shipped for export rendering, served
from SimpleChat's own static files. No new setting and no new browser dependency.

## Why answers used to come back as ASCII art

Two independent causes produced the same symptom.

The first was prompt guidance. SimpleChat already tells the model about capabilities it
cannot infer, such as inline charts and opt-in image proposals, by attaching a system
message when the request calls for one. Diagrams had no such message. Worse, the chart
guidance ended by telling the model not to output Mermaid at all, which is correct advice
when the answer should be a plotted data chart and actively harmful when the answer should
be an architecture diagram.

The second was the classic interface. Mermaid had been wired only into the export
rasterizer, so a diagram became a picture in an exported Word file or PDF while the same
diagram stayed a code block in the conversation it came from.

## Prompt guidance

`functions_diagram_operations.py` detects a structural diagram request and builds the
guidance that is attached to it. Detection is deliberately narrow so it does not compete
with chart detection: "draw the request flow" and "give me an ERD for the orders table"
are diagram requests, while "visualize revenue by month" and "plot the sales trend" remain
chart requests and keep the chart guidance.

The guidance tells the model that fenced `mermaid` blocks render as diagrams and are
carried into exports as images, rules out ASCII art and box-drawing characters, maps
intent onto the diagram types the renderer supports, and gives the syntax constraints that
decide whether a generated diagram parses on the first attempt — quoted node labels above
all, since an unquoted parenthesis or colon in a label is the most common way a generated
diagram fails.

It also draws two boundaries. A diagram is preferred over a generated image for structural
content, because Mermaid output stays selectable, accessible and editable. Numeric plots
stay with inline chart blocks.

Guidance is attached on every generation path: the agent path, the model fallback path,
and the streaming path. It is inserted after any existing system messages and is never
added twice.

## Rendering in the classic interface

`chat-inline-diagrams.js` follows the pipeline the inline chart renderer already uses.
Mermaid fences are lifted out of the markdown and replaced with tokens before `marked`
parses it, which also protects diagram source from the table-conversion passes. The
surrounding markdown is sanitized as usual, the tokens are swapped for placeholders, and
the placeholders are rendered after they are in the DOM.

Rendered SVG is sanitized by DOMPurify before it is written to the page. That is a second
pass: Mermaid itself runs under `securityLevel: 'strict'`, which sanitizes its own output
and disables the `click` directive. The `bindFunctions` callback Mermaid returns is never
called, so no handler is ever attached to a model-authored diagram.

Behaviour that matters in practice:

- A fence that is still streaming becomes a "Preparing diagram" placeholder rather than
  being handed half of its own source and failing to parse on every token.
- A diagram that cannot be parsed falls back to showing its source. The source is still
  the answer the model gave, so hiding it would lose information.
- Rendered SVG is cached by theme and source, so re-rendering a streaming message does not
  redraw diagrams that have not changed.
- Diagrams re-render when the user switches between light and dark mode.
- Copying a message and exporting it both still produce the original ` ```mermaid ` fence,
  because the tokens are restored for the copy text.

The Mermaid bundle is 3.4 MB and is fetched on first use, so a conversation that never
shows a diagram never downloads it.

## The shared Mermaid runtime

`mermaid.initialize()` sets global configuration and `mermaid.render()` reads it back, so
two callers cannot each configure the library once and assume it stays that way. Inline
chat rendering wants a theme-aware, width-constrained diagram; export rasterization wants a
neutral theme at a fixed size, because a `useMaxWidth` diagram and a dark background do not
survive being painted onto a canvas. Whichever configured last would have decided for both.

`chat-mermaid-runtime.js` owns the library for the classic client. It loads the bundle
once, applies the caller's preset immediately before each render, and serialises renders so
a configuration always stays paired with the diagram that asked for it. The export
rasterizer requests the `export` preset and the chat renderer requests `inline`.

The V2 interface solves the same problem the same way inside `MermaidDiagram.tsx`.

## Interface coverage

| Surface | Before | After |
|---|---|---|
| V2 chat | Rendered | Rendered |
| Classic chat | Code block | Rendered |
| Exports (PDF, Word, PowerPoint, Markdown) | Image | Image |
| Model asked for a diagram | ASCII art in a `text` fence | `mermaid` fence |

The V2 interface needed no rendering change. It picks up the prompt guidance and starts
receiving diagrams it could already draw.

## Testing and validation

`functional_tests/test_mermaid_diagram_prompt_guidance.py` covers diagram intent detection
including the chart requests that must not trigger it, the guidance content, idempotent
insertion into the system prefix, wiring on every generation path, and that the chart
guidance no longer contradicts the diagram guidance.

`functional_tests/test_chat_inline_diagram_rendering.py` drives the classic renderer in
headless Chromium: it renders a real diagram and asserts its labels survive, checks the
pending-fence placeholder, the source fallback for an unparseable diagram, the render
cache, teardown, and that no request leaves the origin.

`functional_tests/test_export_mermaid_browser_rasterizer.py` and
`functional_tests/test_export_mermaid_server_render.py` continue to assert that the browser
and server renderers agree on configuration, now reading the browser side from the shared
runtime.

## Known limitations

Diagram quality depends on the model. The guidance improves the odds that a diagram parses
and is well chosen, but a model can still emit invalid Mermaid; that case shows the source
rather than failing silently.

A ` ```mermaid ` fence nested inside a larger fenced block is still treated as a diagram.
This matches the existing behaviour of inline chart blocks.

## Related documentation

- [Mermaid And TeX Rendering In Exports](EXPORT_MERMAID_AND_TEX_RENDERING.md)
- [React V2 UI](REACT_V2_UI.md)
