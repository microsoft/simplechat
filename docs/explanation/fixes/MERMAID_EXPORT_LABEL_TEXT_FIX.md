# Exported Mermaid Diagrams Lost Their Label Text

Fixed in version: **0.261.035**

## Issue

Exporting a chat message containing a Mermaid diagram to Word or PowerPoint produced a
diagram with the right shape — every node, every edge, every arrowhead — and **no text in
any of the boxes**. The same diagram rendered correctly on screen in the chat.

The export was also slow enough to look broken. A PowerPoint export ran long enough that it
was reported as having failed, when in fact it had completed; nothing in either interface
said an export was in progress, so the only visible response to the click was the menu
closing.

## Root cause

Two independent problems that presented as one.

### 1. The container has no scalable font

`application/single_app/Dockerfile` installed fonts for the Chromium runtime with:

```dockerfile
tdnf install -y xorg-x11-fonts-Type1 xorg-x11-fonts-misc || true;
```

Those are legacy X11 Type1 and bitmap packages. Neither provides a scalable TrueType Latin
face, and the trailing `|| true` meant that if the packages did not resolve at all the build
carried on silently. Azure Linux is deliberately minimal and ships no fonts by default, so
the deployed image had nothing Chromium could use.

`functions_mermaid_server_render.py` asked Mermaid to render with
`fontFamily: 'Arial, Helvetica, sans-serif'`. On Linux none of those exist, and the generic
`sans-serif` fallback resolved to nothing. Chromium therefore measured every label as
zero-width, so Mermaid fell back to its minimum node size and painted no glyphs.

The giveaway in the reported files is that **every box came out the same width**, while on
screen the same diagram had boxes of visibly different widths. That is the signature of
zero-width text measurement, not of a colour, theme or `<foreignObject>` problem.

This only ever affected server-side rendering. A browser has its own fonts, which is why the
on-screen diagram was correct.

### 2. V2 never sent the diagram it had already drawn

`downloadMessageExport()` in `application/v2_ui/src/lib/endpoints.ts` posted only
`message_id` and `conversation_id`. The classic chat sends `visual_assets`, but V2 did not,
so every V2 export went down the server rendering path and hit the font problem — even
though a correct picture of the diagram already existed in the page.

### Why the test suite did not catch it

`test_server_renders_diagrams_with_visible_labels` claimed to verify that "a rendered diagram
keeps its label text", but only asserted `painted_ratio > 0.01`. Boxes and arrows alone clear
that threshold easily, so a diagram with no text at all passed.

## Changes

| File | Change |
|---|---|
| `application/single_app/Dockerfile` | Install DejaVu, Liberation and Noto Sans font packages and rebuild the font cache, so everything rendering in this image has glyphs |
| `application/single_app/functions_mermaid_server_render.py` | Embed DejaVu Sans as an `@font-face` from matplotlib; capture the diagram with a Playwright element screenshot instead of an `<img>`/canvas repaint; block only real network schemes so the font's `data:` URI resolves; report `embedded_font_available` from the capability probe |
| `application/v2_ui/src/lib/exportVisuals.ts` | New: registry of on-screen diagrams and the rasterizer that turns them into `visual_assets` |
| `application/v2_ui/src/components/chat/MermaidDiagram.tsx` | Register each rendered diagram for export |
| `application/v2_ui/src/lib/endpoints.ts` | Carry `visual_assets` on the export request |
| `application/v2_ui/src/stores/toastStore.ts` | Add a `pending` tone that does not auto-dismiss, and `settle()` to replace it in place |
| `application/v2_ui/src/components/ui/Toaster.tsx` | Render the pending tone with a spinner and no dismiss button |
| `application/v2_ui/src/components/chat/MessageActions.tsx` | Raise a pending toast before each export, settle it on the outcome, and disable the menu entry with a spinner while it runs |
| `application/single_app/static/js/toast.js` | Support `{ autohide: false }` and return a `{ dismiss }` handle |
| `application/single_app/static/js/chat/chat-toast.js` | Forward the toast handle to callers |
| `application/single_app/static/js/chat/chat-message-export.js` | Progress toast around the Word, PowerPoint and email exports, always cleared in a `finally` |
| `application/single_app/static/js/chat/chat-messages.js` | Give the dropdown export entries the `data-pending-label` the inline buttons already had, so they spin and disable |

### Why an element screenshot

The server renderer previously serialized its SVG, reloaded it through an `<img>` and painted
it onto a canvas — a reconstruction of a browser render, performed inside a real browser that
was already open. That isolated context silently drops `<foreignObject>` content and will not
load a font that is not already present. Screenshotting the mounted element renders exactly
what a browser would show, and removes the whole class of failure.

## Validation

- `functional_tests/test_export_mermaid_server_render.py` — 13/13. The label assertion now
  renders the same graph with and without label text and requires the labelled one to have
  materially more dark pixels **and** to be wider, which is what uniform minimum-width boxes
  would fail. Measured on the fixture: 12,295 dark pixels labelled versus 0 unlabelled, and
  945px wide versus 372px.
- `functional_tests/test_message_export_progress_feedback.py` — 8/8. Includes a parity check
  that executes the browser's own `normalizeVisualSource` in Node against Python's
  `normalize_visual_source`, because a mismatch there silently discards every client asset
  rather than failing.
- `functional_tests/test_export_mermaid_browser_rasterizer.py` — 3/3.
- `functional_tests/test_conversation_export_mermaid_tex_images.py` — 18/18.
- `functional_tests/test_deep_research_chromium_build_opt_out.py` — 3/3.
- `npm run build` in `application/v2_ui` — clean.

### Before and after

| | Before | After |
|---|---|---|
| Server-rendered diagram | Uniform empty boxes | Labels drawn in the embedded font |
| V2 export with a diagram | Always launched headless Chromium | Sends the on-screen picture; no browser launch |
| Exported colours | Server defaults | The colours the reader chose |
| During an export | Nothing on screen | Pending toast plus a disabled, spinning menu entry |

## Notes

- Investigated and rejected: `htmlLabels` was never the problem. The rendered SVG contains 11
  `<text>` elements and zero `<foreignObject>` elements, and a diagram using `classDef` and
  `style` produces identical colour histograms through the canvas path and a live screenshot.
  The browser rasterizers were correct and were left unchanged.
- `gunicorn.conf.py` already allows 900s per request, so a slow export is not being cut off
  server-side. The practical ceiling is the Azure App Service front-end idle timeout of
  roughly 230 seconds, which cannot be configured from this repository. Skipping the browser
  launch and reporting progress were the available mitigations.
- No files under `deployers/` changed, so `deployers/version.txt` was not bumped. The
  Dockerfile lives under `application/` and introduces no new build argument or parameter.
- `test_deep_research_chromium_build_opt_out.py` asserted an exact deployer version of
  `1.0.4` and had been failing since the deployer moved past it. Because it is the test
  covering the Dockerfile changed here, it was switched to the shared
  `assert_version_at_least` helper the repository's own versioning rules require.
