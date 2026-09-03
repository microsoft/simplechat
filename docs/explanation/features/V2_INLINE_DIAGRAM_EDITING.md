# V2 Inline Diagram Editing

## Overview

A Mermaid diagram in a reply used to be final. The only way to change one was to ask again in
the thread, which produced a new message containing a new diagram. Ten refinements meant ten
near-duplicate diagrams in the conversation, every one of them in the model's context, and no
way to see what had changed or go back to a version that was better.

This feature makes a rendered diagram editable in place:

- **A source editor** with live preview and the parser's own error text.
- **Layout controls** for flow direction and spacing, applied as real edits to the source.
- **A scoped AI conversation** that changes the diagram in front of it without adding anything
  to the thread.
- **A revision history** with restore, recording who made each change and why.

Two properties matter more than the features themselves. The message's stored content is never
rewritten, and **only the version currently on screen is ever sent to the model** — the
revisions behind it, and the sub-conversation that produced them, are not.

**Implemented in version: 0.261.049**

<!-- Developed as 0.261.043 (feature) and 0.261.044 (shared conversation support), renumbered
     to 0.261.049 when merged, since the base branch had reached 0.261.048 in the meantime. -->

### What this deliberately does not do

Mermaid is a declarative language. Node positions are computed by a layout engine, and the
language has no syntax for placing a node at a coordinate, so **boxes cannot be dragged**.
Faking it by post-processing the emitted SVG would produce a frozen picture that any later edit
discards, which is worse than not offering it.

What is offered instead covers most of the underlying intent: flow direction, spacing, subgraph
grouping, and reordering statements in the source. The Layout tab says this plainly, and the
prompt used for AI edits tells the model the same thing so it does not invent a syntax.

Per-line text alignment is likewise not a Mermaid concept. Bold and italic are available inside
labels through Mermaid's markdown strings; richer HTML labels are not, because the renderer runs
with `htmlLabels: false`.

### Dependencies

None added. Mermaid and DOMPurify are already vendored under
`application/v2_ui/public/vendor/`, and the AI edit uses the chat deployment already configured
in Admin Settings. There is no new settings toggle.

## Architecture

### Storage is an overlay, not a rewrite

Revisions live in message metadata under `block_revisions`, beside the `visual_styles` key that
already stores per-block colours. The message's `content` keeps the diagram the model produced,
and the current revision is substituted over it whenever the content is read.

```
metadata.block_revisions.mermaid["0"] = {
  "source_hash": "65df990d",
  "current": 2,
  "revisions": [
    { "id": "...", "source": "graph TD ...", "origin": "original", ... },
    { "id": "...", "source": "graph LR ...", "origin": "ai", "note": "make it left to right",
      "author_name": "Ada Lovelace", "timestamp": "..." }
  ],
  "chat": [ { "role": "user", "content": "make it left to right", "timestamp": "..." } ]
}
```

Splicing the new source directly into `content` was considered and rejected. `masked_ranges`
are character offsets into that string, so rewriting a fence body shifts every mask after it —
and silently unmasking something a user chose to mask is a confidentiality bug rather than a
rendering one. The overlay never touches those offsets, and it keeps the original recoverable
for nothing.

### How a diagram is addressed

A rendered block has no identity of its own, so an entry is filed under the block's position
among blocks of the same kind, plus a fingerprint of the block's **original** source. This is
the same addressing `functions_message_visual_styles.py` already uses, which is what lets the
two agree about what a block is.

The fingerprint is always taken over the original source, never the current one. That is what
lets a diagram keep its colours after being edited: if the key moved every time the source
changed, recolouring a diagram and then rewriting it would silently lose the colour.

Position alone is only ever a guess. The V2 client numbers fences by walking the parsed tree;
the server has no parser and scans text. Where the two disagree, substituting by position would
put one diagram's source into another diagram's fence, so the fence found at a position must
also match the stored fingerprint. When it does not, the fingerprint is searched for across the
message instead, and an ambiguous result substitutes nothing. **Every failure mode shows the
original.**

### One resolver, three readers

`resolve_block_sources_in_content` in `functions_message_block_revisions.py` is the single seam
every reader of a message's content goes through:

| Reader | Where |
|---|---|
| The model's conversation history | `route_backend_chats.py` |
| Conversation and single-message export | `route_backend_conversation_export.py` |
| The classic chat client | `static/js/chat/chat-inline-diagrams.js` |

In the history builder the resolve happens **after** masking, because masks are character
offsets into the stored content. A mask that alters a fence's body changes its fingerprint, so
the revision stops resolving rather than being applied over content a reader deliberately
removed.

### The fingerprint exists in three languages

`fingerprintSource` is FNV-1a 32-bit over CRLF-normalised, trimmed source, hashing UTF-16 code
units. The V2 client writes the hashes, the server verifies them, and the classic client reads
them, so all three have to agree exactly:

| Implementation | File |
|---|---|
| Reference | `application/v2_ui/src/lib/visualPalettes.ts` |
| Server | `application/single_app/functions_message_block_revisions.py` |
| Classic client | `application/single_app/static/js/chat/chat-inline-diagrams.js` |

Two details are easy to get wrong and are covered by tests. Hashing Python characters instead
of UTF-16 code units agrees for the whole Basic Multilingual Plane and then diverges for
anything above it, so a diagram containing an emoji would stop resolving. And JavaScript's
`trim()` removes U+FEFF where Python's `str.strip()` does not, so a diagram with a byte order
mark would hash differently on the two sides.

## API

All three routes take `conversation_id`, `block_kind`, `block_index` and `source_hash`, and
authorize the conversation rather than the message — which is also what admits a participant of
a shared conversation.

| Route | Purpose |
|---|---|
| `POST /api/message/<id>/block-revision` | Store an edited source as a new revision and show it |
| `POST /api/message/<id>/block-revision/current` | Show one of the stored revisions |
| `POST /api/message/<id>/block-revision/assist` | Ask the model to change the diagram |

`original_source` seeds the history the first time a block is edited and is verified against
`source_hash` rather than trusted, so "restore the original" cannot be pointed at the wrong
content.

`expected_revision_count` is optional. Sending the count the editor was opened against turns a
silent overwrite of someone else's edit into a `409`.

### Shared conversations

A shared conversation is stored in different Cosmos containers and served by
`/api/collaboration/*`, so it has its own three routes:

| Route |
|---|
| `POST /api/collaboration/conversations/<cid>/messages/<mid>/block-revision` |
| `POST /api/collaboration/conversations/<cid>/messages/<mid>/block-revision/current` |
| `POST /api/collaboration/conversations/<cid>/messages/<mid>/block-revision/assist` |

The request and response shapes are deliberately identical, so the client picks an endpoint from
the conversation's kind — `activeConversationKind` in `chatStore` — and sends the same body
either way. It does not try one and fall back: a shared conversation id sent to a personal route
reads the personal container, finds nothing, and reports the conversation as missing.

These routes authorize with `assert_user_can_participate_in_collaboration_conversation` rather
than by ownership. A participant is not the owner of the underlying source conversation and
would fail a plain ownership comparison even though they are a legitimate member.

**A shared message is a mirror, so an edit is written through to its source.** The shared AI
request is delegated to the personal chat path using the *source* conversation id, and the
history builder, the export and the owner's own view all read the personal container. An edit
stored only on the mirror would be visible to whoever was reading the shared thread while the
model and everyone else continued to see the original. `_sync_collaboration_block_revisions_to_source`
is what closes that, mirroring `_sync_collaboration_mask_metadata_to_source`, which exists for
exactly the same reason.

Each shared edit is published as a `collaboration.message.block_revised` event, so other
participants see the change without reloading. The event carries only the revision map, not the
whole message, since nothing else about the message changed.

### Limits

| Limit | Value | Why |
|---|---|---|
| Revisions per block | 20 | Bounds the message document. The original is pinned at index 0 and never pruned. |
| Source length | 20,000 characters | Matches the classic renderer's own guard. |
| Sub-conversation turns | 20 | Oldest dropped first. |
| Edited blocks per message | 50 | |
| Instruction length | 2,000 characters | Longer than this is a new diagram request, not an edit. |

## The scoped AI conversation

The model is given exactly three things: the diagram's current source, the turns of that
diagram's own sub-conversation, and the request that originally produced the diagram. It is not
given the conversation.

The originating request is included because "make it match what we discussed" nearly always
refers to the request the diagram came from, and one message is enough for that to mean
something without sending an entire thread to redraw a flowchart. It is passed as background
with an explicit instruction not to follow it.

The reply is auto-applied as a new revision with undo, and stored as a turn in the
sub-conversation. Neither is ever sent back as conversation history.

### Security

Everything handed to the model is content the model wrote earlier or that a user typed, so the
system prompt states that the material is a diagram to edit rather than instructions to follow.
The source that comes back is validated and then sanitised at render like any other diagram —
nothing gets a shortcut for having been generated here.

A source containing a line that would close its enclosing fence is refused outright on both the
client and the server. Accepting one would let an edit break out of its own code block and
inject arbitrary markdown into someone else's message.

## Usage

An **Edit** button appears in the toolbar under every rendered diagram, alongside Expand and
PNG. A diagram that has been edited shows a small dot on the button.

The editor opens with a live preview on one side and four tabs on the other:

- **Source** — the Mermaid source, with a preview that follows what is typed. An invalid draft
  keeps showing the last good version rather than flashing an error on every keystroke. Save
  version stores it; Discard changes returns to what is stored.
- **Layout** — flow direction and spacing. Each writes a revision, so a layout change can be
  undone like any other edit.
- **Ask AI** — describe a change in words. Enter submits; Shift+Enter adds a line.
- **History** — every version, newest first, with who made it and why. Restore moves the
  pointer; nothing is deleted, so restoring an old version and then editing appends rather than
  truncating.

Editing is available in the V2 interface only. The classic interface renders whatever the
current version is, so a conversation read in either place shows the same diagram, but the
editor is not offered there.

Any participant of a shared conversation may edit a diagram, matching who may already recolour
one. Every revision records its author, which is what makes that accountable.

## Rendering and safety

Diagram markup reaches the DOM in exactly one reviewed file, `MermaidDiagram.tsx`, and
`test_v2_rich_rendering.py` fails when any other component sets inner HTML. The editor's live
preview is therefore passed in as a render prop, already rendered, rather than drawn in
`DiagramEditor.tsx` — so adding an editor did not add a second place where untrusted markup can
reach the page.

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_message_block_revisions.py` | Storage, pruning, restore, stale entries, position drift, duplicate blocks, fence breakout, concurrency, mask ordering, Python/JavaScript fingerprint parity |
| `functional_tests/test_block_revision_assist.py` | Context isolation, reply parsing, model failure handling, prompt guidance |
| `functional_tests/test_v2_diagram_editor.py` | Sink boundary, resolver wiring across all three readers, route decorators, shared conversation routes and source mirroring, three-way fingerprint parity |
| `functional_tests/test_v2_diagram_editor_logic.ts` | Layout transforms and edit validation |

The fingerprint parity checks read the JavaScript implementations out of their source files and
execute them, rather than retyping them in the test, so they compare against what actually
ships.

### Known limitations

- Node positioning is not supported, as described above.
- Editing is not offered in the classic interface.
- Charts are not editable yet. The storage and the resolver are kind-agnostic, so adding them is
  wiring rather than a rewrite; only `mermaid` is admitted today. Generated **images** are now
  editable, through a parallel mechanism rather than this one — an image is its own message, so
  it needs none of the fence addressing here. See `V2_INLINE_IMAGE_EDITING.md`.
- A fence nested inside a blockquote or indented into a list item is not recognised by the
  server's scanner. Such a block fails the fingerprint check and simply keeps showing its
  original source rather than resolving incorrectly.
