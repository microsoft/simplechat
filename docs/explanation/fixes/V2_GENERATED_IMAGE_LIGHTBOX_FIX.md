# V2 Generated Image Lightbox Fix

## Issue

In the V2 chat view, clicking an image the assistant generated left the application. The
image opened as a raw file in a new browser tab, dropping the user out of their conversation
to look at something the page was already showing them. The classic chat view has never
behaved this way — it opens the image in a modal — so V2 was the outlier.

For one class of image it was worse than merely awkward: clicking did nothing at all. Small
images are delivered inline as `data:image/...` URIs, and browsers block top-level navigation
to a `data:` URL. Those images silently refused to respond to a click, with no error and no
explanation.

**Fixed in version:** 0.261.025

## Root cause

`ImageMessage` in `application/v2_ui/src/components/chat/MessageList.tsx` wrapped the
thumbnail in an anchor:

```tsx
<a href={source.src} target="_blank" rel="noopener noreferrer" title="Open the full-size image">
    <img src={source.src} ... />
</a>
```

`resolveImageSource` (`src/lib/images.ts`) can return three different kinds of source — a
`data:` URI, an `/api/image/<id>` path, or an external `https://` URL — and the anchor treated
all three as though they were an ordinary navigable URL. Only two of them are.

## The fix

The thumbnail is now a button that opens `ImageLightbox`, a dialog rendered in place. Because
the click no longer navigates anywhere, everything the new tab used to provide is offered
inside the dialog instead:

- **Fit / actual size.** The image is scaled to the panel by default and can be switched to
  natural size, where it scrolls so the edges of a large image stay reachable. The header
  control and the image itself both toggle it.
- **Save the image.**
- **Open in a new tab**, for anyone who genuinely wanted the raw file.

The dialog follows the conventions already set by `CitationChip` and
`EnhancedCitationViewer`: a click-to-close backdrop, Escape to dismiss, `role="dialog"` with
`aria-modal="true"`, and no focus-trap utility, since no other dialog in this UI uses one.
Focus moves to the dialog on open and returns to the thumbnail on close.

### Each source kind is handled deliberately

The three shapes `resolveImageSource` returns need different treatment, which is the part the
original anchor got wrong:

| Kind | Download | Open in new tab |
|---|---|---|
| `data-uri` | Decoded to a blob locally, no request | Republished as an object URL, because `data:` navigation is blocked |
| `endpoint` | Fetched with the client's credentials mode | The URL directly |
| `external` | Fetched; a CORS refusal is reported | The URL directly |

Download fetches the bytes and saves a blob rather than pointing an `<a download>` at the URL.
The `download` attribute is ignored for a cross-origin URL, which is exactly what
`/api/image/<id>` becomes in the split-origin (`VITE_API_BASE`) deployment, so the attribute
alone would have silently produced a navigation instead of a saved file.

The object URL created for a `data:` image is revoked on a timer. Revoking it immediately
would break the tab still loading it; never revoking it would hold the bytes for the life of
the page.

### A trap worth recording

`window.open()` returns `null` when `noopener` appears in its feature string — even when the
tab opens successfully. Passing `noopener` there would have made every successfully opened tab
look blocked, and the UI would have reported a failure on every use. The opener is severed by
assignment after the call instead, which keeps the return value meaningful so a genuinely
blocked popup can still be reported. The functional test asserts this so it cannot regress.

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/components/chat/ImageLightbox.tsx` | New dialog: zoom toggle, download, open in new tab, close |
| `application/v2_ui/src/components/chat/MessageList.tsx` | `ImageMessage` opens the lightbox instead of a new tab |
| `application/v2_ui/src/lib/images.ts` | `decodeImageDataUri`, `resolveImageBlob`, `downloadImageSource`, `openImageInNewTab`, `imageFileName` |
| `application/v2_ui/src/lib/endpoints.ts` | `saveBlob` exported so the image download reuses one save path |
| `application/v2_ui/src/lib/apiClient.ts` | `CREDENTIALS_MODE` exported for the authenticated image fetch |
| `application/single_app/config.py` | Version to 0.261.025 |
| `functional_tests/test_v2_generated_image_lightbox.py` | New test |

The classic chat view was not touched. It already opens a modal through `showImagePopup` in
`static/js/chat/chat-citations.js`.

User-uploaded images benefit alongside generated ones, because V2 routes every message with
`role === 'image'` through `ImageMessage` — matching the classic view, where uploaded and
generated images share the same `.generated-image` click handler.

## Validation

`functional_tests/test_v2_generated_image_lightbox.py` asserts that the thumbnail is a button
rather than an anchor and carries `aria-haspopup="dialog"`, that the broken-image fallback
survived the rewrite with every hook still declared before its early return, that the dialog
is dismissable by Escape and by the backdrop and manages focus in both directions, that all
three source kinds are handled by both download and open-in-new-tab, that the download reuses
the existing `saveBlob` rather than adding a second save path, that file names are derived
safely, and that `noopener` is not passed to `window.open`.

The test was confirmed to fail against the pre-change code: the extracted `ImageMessage` body
at `HEAD` contains `target="_blank"` and no lightbox.

The helpers were additionally exercised at runtime against the real compiled module. A
base64 PNG data URI decoded to bytes beginning with the PNG signature
`89 50 4E 47 0D 0A 1A 0A`; malformed URIs returned `null` rather than throwing; file names
resolved as expected from a server filename, a short prompt, an over-long prompt falling back
to the message id, and a prompt containing characters illegal in a filename; a `data:` source
opened through a `blob:` URL rather than being navigated to; and a refused `window.open`
returned `false` so a blocked popup is reported rather than assumed to have worked.

`npm run typecheck` and `npm run build` both pass, and
`functional_tests/test_v2_ui_local_assets.py` confirms no remote asset was introduced —
the icons come from `lucide-react`, which was already a dependency.

## Related

- Feature documentation: `docs/explanation/features/REACT_V2_UI.md`
