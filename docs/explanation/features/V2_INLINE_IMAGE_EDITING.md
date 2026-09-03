# V2 Inline Image Editing

## Overview

A generated image in a reply used to be final. The only way to change one was to ask again in
the thread, which cost another paid generation, produced another image message, and left the
previous image sitting in the conversation with no relationship to the new one. Ten refinements
meant ten images and no way to tell which was current or to go back to one that was better.

This makes a generated image changeable in place:

- **An AI change with a region** — describe what should be different, and optionally select
  *where* on the image it applies.
- **The prompt** that produced the image, shown, editable and re-runnable.
- **Rendering controls** for shape, quality and background.
- **A version history** with thumbnails, restore, and a before/after compare, recording who made
  each change and why.

The two properties that matter most are the same ones the diagram editor established: the
message's stored content is never rewritten, and the conversation never grows. A change replaces
what is on screen rather than appending to the thread.

**Implemented in version: 0.261.058**

### What this deliberately does not do

An image is pixels. There is no source to edit, so **there is no hand-editing and no drawing
tool** — every version comes from the model. That is why this feature has two routes where the
diagram editor has three: "save what I typed" has no meaning here, so creating a version and
asking for one are the same call.

**A mask guides the model; it does not clamp pixels.** Areas outside the selection can still
shift. The interface says so rather than implying a precision the API does not offer.

**Only generated images are editable.** A user's own uploaded image is not something the image
deployment can be asked to rework, and editing one is a separate decision. The Edit control is
not offered for an upload.

Editing is available in the V2 interface only. The classic interface shows whatever version is
current — because both interfaces load images through the same serve routes — but the editor is
not offered there.

### Dependencies

None added. Pillow and the OpenAI SDK are already pinned in `requirements.txt`, and the mask is
drawn with plain browser canvas APIs. No CDN asset is introduced and no npm dependency was
added.

## Architecture

### An image is its own message, which removes most of the machinery

This is the single most important difference from inline diagram editing, and it is a
simplification rather than a port.

A Mermaid diagram is a fenced block *inside* an assistant message and has no identity of its
own, so `functions_message_block_revisions.py` addresses it by position among blocks of the same
kind plus a fingerprint of its original source, with a markdown fence scanner, a hash that has
to agree across three languages, and careful ordering against `masked_ranges` character offsets.

**A generated image is its own `role: 'image'` message document.** It is addressed by its message
id.

| Diagram concern | Image equivalent |
|---|---|
| `(kind, index, source_hash)` addressing | the message id |
| fence scanning and position drift | none |
| FNV-1a fingerprint parity in three languages | none |
| ordering against `masked_ranges` | none — the content is a URL, not prose |
| a resolver feeding the model's history | none — image roles are excluded from history |

That last row is worth stating plainly. `build_conversation_history_segments` in
`route_backend_chats.py` skips `image` for older messages and restricts recent messages to
`user` and `assistant`, so an edited image is never re-sent to the model and there is no history
reader to keep in step.

`functions_message_image_revisions.py` mirrors the *interface* of the block revision module —
revisions with a `current` pointer, the original pinned at index zero, a scoped sub-conversation,
attribution, pruning, and `expected_revision_count` conflict detection — and shares none of its
addressing.

### Storage is an overlay, and never inline

```
metadata.image_revisions = {
  "current": 1,
  "revisions": [
    { "id": "...", "origin": "original", "prompt": "a cat on a wall", ... },
    { "id": "...", "origin": "ai", "instruction": "make the sky orange",
      "prompt": "<the composed edit prompt>",
      "blob_container": "...", "blob_path": "...", "mime_type": "image/png",
      "width": 1024, "height": 1024,
      "mask": { "coverage": 0.14, "regions": 2 },
      "model": "gpt-image-1", "method": "edit",
      "author_name": "Ada Lovelace", "timestamp": "..." }
  ],
  "chat": [ { "role": "user", "content": "make the sky orange", ... } ]
}
```

Two rules are load-bearing:

**Revision zero stores no bytes.** It *means* "the message's own stored content", whatever form
that takes — a chunked data URL, a blob-backed pointer, or an external URL. Copying a
multi-megabyte original into metadata would be wasteful, and for a chunked image it is not
possible at all.

**Every later revision is blob-backed.** Image messages already split across several documents at
1.5 MB because a data URL exceeds the Cosmos item limit, so a revision that embedded its bytes
in metadata would grow the message document past what can be written after a couple of edits.
This is a correctness constraint rather than an optimisation.

Blob containers and paths are storage detail and never reach the browser.
`serialize_image_revisions` is the only shape a route returns, and every reader of a message goes
through it: `hydrate_image_messages`, `serialize_collaboration_message`,
`build_collaboration_message_metadata_payload`, and the per-message metadata route, which returns
an image document more or less verbatim. A blob path spells out the owner's user id and the
source conversation id as well as the container, so this is not merely tidiness.

### Why an edited image gets a new URL

`/api/image/<message_id>` does not change when a revision lands, and it is served with
`Cache-Control: private, max-age=300` personally and `public, max-age=3600` collaboratively. So
without a changing URL a change would be invisible for up to an hour: the reader would keep
seeing the version they had just replaced.

Once an image has any history at all, its content therefore resolves to
`/api/image/<message_id>?rev=<revision_id>`, and both serve routes resolve the parameter.
Because the URL is then addressed by revision, those long cache lifetimes become correct rather
than merely tolerated, and a specific revision is served `immutable`.

**This applies to the original too, not only to edits.** Returning the message's stored content
when the original is current looks reasonable and is wrong in two cases: a collaboration mirror
stores a placeholder rather than a URL, so restoring the original would replace a working image
with that placeholder for every participant, permanently; and a legacy image split across
several documents stores only its first chunk, which is a truncated data URL. The endpoint
resolves the original correctly in both cases — `resolve_served_revision` reports no blob for it
and the serve routes fall through to the message's own bytes, reassembling chunks or redirecting
to an external URL exactly as they always did.

An unrecognised `rev` is answered with whatever is current rather than with an error. The
parameter exists to make the URL change, so a stale link is best answered with the live image.

The same id is what lets the history strip show several versions at once. Without it every
thumbnail would resolve to the same URL and therefore to the same cached image.

## Masking

### The polarity

In the images API a mask is a PNG with an alpha channel where **fully transparent pixels mark
the region to edit** and opaque pixels are preserved. It is not a white-on-black stencil.

Inverting this produces an edit that changes everything *except* what was selected, which looks
like a model failure rather than a bug and would survive review. So it is not written by hand:
`imageMask.ts` fills a canvas fully opaque and then *erases* the selection out of it with
`globalCompositeOperation = 'destination-out'`, which produces the required polarity by
construction. `functions_image_edit.py` verifies it independently, and
`test_message_image_revisions.py` asserts it end to end against real PNG bytes.

### What the server checks

The mask is validated with Pillow rather than trusted, on three points that each produce a
silently wrong edit rather than an error:

| Check | Why |
|---|---|
| It carries an alpha channel and is not fully opaque | A fully opaque mask selects nothing, and sending one asks the model to change nothing while still being charged. Reported as *absent* so the caller edits the whole image instead. |
| Its dimensions match the source exactly | Required by the API. A mismatch is resized with nearest neighbour, so a rounding difference between the browser's layout and the image's true size is absorbed without blurring hard edges into partial alpha. |
| It is within the size cap | The API caps an uploaded mask at 4 MB. |

**The browser never uploads the image.** It sends only the mask and the instruction, and the
server fetches the current image bytes itself from blob storage or from the message's chunks.
That avoids a second transfer of a multi-megabyte image and sidesteps cross-origin questions
entirely. The mask canvas never reads the source image's pixels either, only its dimensions, so
it is never tainted.

### Selecting without a mouse

Drawing is a pointer-only interaction, and a feature reachable only with a mouse is one some
readers cannot use at all. A three-by-three region grid offers the same selection from the
keyboard.

This is not a token gesture: the grid produces the same `MaskShape` values a drag produces, so
both paths go through identical rendering code rather than being two implementations with two
sets of bugs. The regions are computed from boundaries rather than by multiplying a third, so
they tile the image exactly and leave no unedited seam on a size that does not divide by three.

### The prompt

The API's own guidance is that describing the **complete desired image** preserves the unmasked
regions far better than describing only the change, because the model generates a whole image
either way and a change-only prompt leaves the rest unspecified.

So the instruction is not sent alone. It is combined with the prompt describing the version
currently on screen, plus a statement that the change applies within the transparent region and
everything outside it should be kept. That composition is deterministic and server-side: a
second completion to rewrite the prompt would add latency and cost to every edit and give the
wording another chance to drift from what was asked.

`input_fidelity: 'high'` is requested where the deployment supports it.

## Model capability

`/images/edits` exists for `gpt-image-*` and legacy `dall-e-2`. **DALL·E 3 has no edit endpoint
at all.** Editing also needs image generation API version `2025-04-01-preview` or newer, and an
older one fails in a way that reads like a broken deployment.

Capability is therefore resolved server-side from
`settings.image_gen_model.selected[0].modelName` and
`settings.azure_openai_image_gen_api_version`:

| Configuration | Mode |
|---|---|
| `gpt-image-*`, `dall-e-2`, on a recent API version | `masked` — a region can be selected |
| `dall-e-3` | `regenerate` — no edit endpoint exists |
| APIM, or a deployment saved before `modelName` was recorded | `regenerate` — capability unknown, so the safe answer wins |
| An API version older than `2025-04-01-preview` | `regenerate`, with the setting named in the reason |

In `regenerate` mode the mask tools are not shown at all and the panel states the limitation,
naming the model or the setting responsible. The reason is surfaced rather than swallowed,
because being told up front that only whole-image regeneration is available is a usable
experience, while painting a mask and then being refused is not.

This is reported through a new `capabilities` object on `/api/v2/bootstrap`, deliberately **not**
through `features`. That map is built by forwarding every `enable_*` boolean settings key, so
inventing an `enable_image_edit` would make a derived capability look like a settings key to
everything that reads the application's surface, including the documentation inventory.

`resolve_image_edit_capability` lives in `functions_image_edit.py` rather than beside the
generation helpers, because those import the Cosmos and Azure OpenAI clients at module scope and
capability has to stay resolvable from a test.

### SDK compatibility

`quality`, `background` and `input_fidelity` do not exist on `images.edit` in every version of
the OpenAI SDK, so passing them as keyword arguments raises `TypeError` depending on which
version is installed. They are sent through `extra_body`, which merges into the same request
body on every 1.x release, so the call works against the pinned SDK and an older one without
version sniffing.

A deployment that predates one of these parameters rejects the whole request rather than
ignoring the field it does not know, so a refusal naming an unsupported parameter is retried
once without them. A slightly less controlled image is a much better outcome than refusing to
edit at all.

## API

| Route | Purpose |
|---|---|
| `POST /api/message/<id>/image-revision` | Produce a new version and show it |
| `POST /api/message/<id>/image-revision/current` | Show one of the stored versions |

There is no `assist` counterpart to the diagram editor's third route. A browser cannot author an
image, so every version already comes from the model and one route covers it.

`origin` selects which operation is meant, and they are genuinely different rather than
variations of one:

| `origin` | Meaning |
|---|---|
| `ai` | Apply an instruction. The only one that uses a mask. |
| `prompt` | Replace the prompt outright and rebuild from it. |
| `control` | Keep the prompt, change how it is rendered. |

`expected_revision_count` and `expected_current_revision_id` are optional. Sending what the
editor was opened against turns a silent overwrite of someone else's change into a `409`.

Both exist because the count alone has a blind spot: once the stored versions reach their cap,
every new one drops an old one, so the total stops changing and a count-only check would quietly
stop protecting anybody. Which version is *current* has no such limit, and is the stronger
statement anyway — a change is built on a particular version.

The guard is evaluated twice: once before the model is called, so a conflict does not cost a
generation that was always going to be rejected, and again against a **freshly re-read document**
before the write. A generation takes seconds, and in a shared conversation another participant
can land their own version inside that window; writing to the copy loaded before the call would
pass the first check and then silently discard their change.

The revision is written only after the image comes back, so a failed generation leaves no version
behind describing a change that never happened. The reverse is possible: a change rejected by
the second conflict check has already had its bytes written, leaving a blob nothing points at.
That is the intended trade — a leaked blob rather than a lost change — and the pre-flight check
narrows the window without closing it.

### Shared conversations

A shared conversation is stored in different Cosmos containers and served by
`/api/collaboration/*`, so it has its own pair of routes with deliberately identical request and
response shapes:

| Route |
|---|
| `POST /api/collaboration/conversations/<cid>/messages/<mid>/image-revision` |
| `POST /api/collaboration/conversations/<cid>/messages/<mid>/image-revision/current` |

The client picks an endpoint from the conversation's kind — `activeConversationKind` in
`chatStore` — rather than trying one and falling back.

**A shared image is a mirror, so the edit is written to the source.** The bytes live on the
source message in the personal container, which the owner's own view, the export and the
collaboration image route all read. The revision is applied there and the revision map mirrored
onto the collaboration document, following `_sync_collaboration_block_revisions_to_source`, which
exists for the same reason. One blob, two documents pointing at it.

These routes authorize with `assert_user_can_participate_in_collaboration_conversation`: a
pending invitee may view a shared image but not change one, matching who may already recolour a
diagram.

Each shared edit is published as a `collaboration.message.image_revised` event carrying the
revision map **and the new image URL**. Unlike a diagram revision, this changes what the message
points at, and without taking the URL the other participants would keep showing the copy already
in their cache.

### Limits

| Limit | Value | Why |
|---|---|---|
| Versions per image | 20 | Bounds the message document and the stored blobs. The original is pinned at index 0 and never pruned. |
| Instruction length | 2,000 characters | Longer than this is a new image request, not a change. |
| Prompt length | 4,000 characters | Matches the image proposal prompt cap. |
| Mask size | 4 MB | The API's own cap. |
| Source image | 20 MB, 12 megapixels | Guards against a decompression bomb as much as a large picture. |
| Sub-conversation turns | 20 | Oldest dropped first. |

## Usage

An **Edit** button appears under a generated image in the thread, in the full-size viewer, and on
an approved image proposal card. An image that has been changed shows a small dot on the button.

The editor opens with the image on one side and four tabs on the other:

- **Ask AI** — describe the change. With a mask-capable deployment the image is shown with
  selection tools: a box, a freehand brush with three sizes, and a nine-region grid for keyboard
  use, plus undo and clear. The selected proportion of the image is reported, together with the
  reminder that areas outside it can still shift. Enter submits; Shift+Enter adds a line.
- **Prompt** — the prompt behind the version showing, editable. Rebuilding from it produces a
  new version and is labelled as rebuilding rather than adjusting.
- **Controls** — shape, quality and transparent background. Each writes a version, so any of them
  can be undone.
- **History** — every version newest first, with a thumbnail, who made it, why, and how much of
  the image was selected. Restore moves the pointer; nothing is deleted, so restoring an older
  version and then editing appends rather than truncating. Holding **compare** shows the previous
  version in place.

An edit is composed against the version currently on screen rather than the first image ever
generated, so successive changes accumulate.

Because a version can be produced at a different shape from the one it replaced — the GPT image
models emit only `1024x1024`, `1024x1536` and `1536x1024` — the history records the dimensions
that actually came back rather than the ones requested.

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_message_image_revisions.py` | Storage, pruning, restore, conflict detection, revision-addressed serving, mask polarity end to end, mask resizing, empty and full selections, transparent source images, prompt composition, capability resolution |
| `functional_tests/test_v2_image_editor.py` | Route decorators, the absent assist route, shared write-through and the realtime event, capability plumbing, the markup sink boundary, keyboard masking, endpoint placement |
| `functional_tests/test_v2_image_mask_logic.ts` | Region grid tiling, drag normalisation and clamping, what counts as a selection |

The mask polarity check is the important one. It renders a real mask, reads its alpha back, and
asserts that the selected region is transparent and the rest opaque — because an inversion would
look like a model failure rather than a bug.

### Known limitations

- No pixel-level editing, as described above. Every version comes from the model.
- A mask guides the model rather than constraining it, so unmasked areas can still change.
- Uploaded images are not editable.
- Editing is not offered in the classic interface, though it shows the current version.
- Deployments without an edit endpoint can only regenerate the whole image.
- A change rejected as a conflict leaves its generated bytes in blob storage with nothing
  referencing them. Harmless, but unreferenced blobs accumulate slowly and there is no sweeper.
