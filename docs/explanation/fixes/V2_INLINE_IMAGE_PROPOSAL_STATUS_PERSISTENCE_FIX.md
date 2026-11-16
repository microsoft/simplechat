# V2 Inline Image Proposal Status Persistence Fix

Fixed in version: **0.261.045**

## Issue

In the V2 React chat interface, an assistant reply containing several `simpleimage` proposals
renders one approval card per proposal plus an **Approve all N images** control. Pressing
**Approve all** behaved correctly at first: every Approve button greyed out and each card
showed its queue position and then **Generating image…**.

As soon as the *first* image came back, the remaining cards fell apart:

- their status text disappeared,
- their Approve buttons became enabled again, and
- the **Approve all** control reappeared.

Nothing had actually gone wrong. Those approvals were still draining through the serial
approval queue, and their images arrived a moment later. But the interface said otherwise, so a
user was told nothing was happening and invited to approve — and pay for — the same image a
second time.

A second, smaller problem: once a card's image had been generated, the card still showed the
proposal's badge row — the visual type ("illustration"), the slide reference, and the free-text
context. Those describe an image that does not exist yet. Once it does, they describe nothing
the reader cannot already see.

## Root cause

The cause was not in the image proposal code.

`application/v2_ui/src/components/chat/AssistantMarkdown.tsx` built its react-markdown
`components` map inline in the JSX:

```tsx
<ReactMarkdown components={{ p: ..., pre: ..., code: ... }}>
```

react-markdown uses those functions as the **element type** for the nodes they handle.
`hast-util-to-jsx-runtime` resolves the tag name against the supplied map and passes the result
straight to the JSX runtime:

```js
const type = findComponentFromName(state, node.tagName, false)
// -> own.call(state.components, name) ? state.components[name] : name
return state.create(node, type, props, key)
```

React unmounts and remounts a subtree whenever an element's type changes, and an object literal
in JSX produces new function identities on every render. So **every render of a message tore
down and rebuilt every rich block inside it** — image proposal cards, Mermaid diagrams and
inline charts alike.

`InlineImageProposal` kept its `status`, `queuePosition`, `failure` and edited `prompt` in
component-local `useState`, so a rebuild reset each card to `idle`.

The trigger was the approval itself. `chatStore.approveImageProposal` appends the generated
image to `messages`; `MessageList` regroups the proposal images and passes a fresh
`proposalImages` array to `MessageBubble`, which re-renders `AssistantMarkdown`. The very event
the user was waiting for was what discarded the progress of everything still queued behind it.

`useId()` returns the same value for a component rebuilt in the same tree position, so the
rebuilt cards re-registered as pending and brought the **Approve all** control back with them.

## Fix

Two independent changes, because the first removes the cause and the second removes the class
of bug.

### 1. The component map is memoised

`renderTokens` is now a `useCallback`, and the component map a `useMemo` keyed on it and on the
message id. react-markdown therefore sees stable element types across renders and reconciles
the rich blocks instead of rebuilding them.

The optional `citations`, `masks` and `math` inputs now default to shared module-level empty
arrays rather than an inline `?? []`, which would have minted a new array per render — and so
invalidated the memo — for every message that has none of them, which is most of them.

This also stops Mermaid re-initialising every diagram in a thread, and inline charts
re-mounting, whenever anything about their message changes.

### 2. A card's approval state is owned by its message

`ProposalCardState` (status, queue position, failure, edited prompt, editor open) moved out of
the card and into the message's `ImageProposalScope`, in a record keyed by
`proposalCardKey(spec, blockIndex)`.

The scope is rendered by `MessageBubble`, which the thread keys on the message id, so it
survives a rebuild of the markdown subtree beneath it and a `reloadMessages()` alike. A rebuilt
card reads its entry back and carries on showing **Generating image…** with Approve disabled,
whatever caused the rebuild — a conversation reload, a mask, a collaborator's message, or
something not yet written.

The key comes from the fence index `rehypeRichBlockIndex` already stamps on each rich fence, so
two proposals in one message can never share an entry. The prompt field's DOM `id` still comes
from `useId()`, because every message's first proposal shares the card key `block:0` and a DOM
id has to be unique across the document.

A consequence worth noting: cancelling a proposal now survives a re-render too. It previously
un-cancelled itself for the same reason the status was lost.

### 3. The approved card keeps only what still applies

The approved-result branch no longer renders the proposal's badges. It shows the title, the
image, and the model deployment that produced it. A card still awaiting a decision shows its
badges and description exactly as before.

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/components/chat/AssistantMarkdown.tsx` | Memoised `renderTokens` and the react-markdown `components` map; shared empty defaults; the block index is now read before the image-proposal branch and passed to the card |
| `application/v2_ui/src/lib/imageProposalCardState.ts` | New. `ApprovalStatus`, `ProposalCardState`, `IDLE_CARD_STATE` and the `applyCardStatePatch` reducer |
| `application/v2_ui/src/lib/imageProposalSpec.ts` | New `proposalCardKey`, which names a card within its message |
| `application/v2_ui/src/components/chat/ImageProposalContext.tsx` | The scope owns the card state map and exposes `cardStates` and `updateCardState` |
| `application/v2_ui/src/components/chat/InlineImageProposal.tsx` | Reads and writes its state through the scope; accepts `blockIndex`; the approved card drops the badge row |
| `application/single_app/config.py` | `VERSION` to `0.261.045` |

## Not changed

The classic V1 client keeps its card state in the DOM and rebuilds nothing when a new message
arrives, so it never had this bug; `static/js/chat/chat-inline-image-proposals.js` is untouched.
Its approved card still shows the proposal's badge row. That divergence is deliberate rather
than overlooked: the V1 markup is asserted by
`ui_tests/test_chat_inline_image_proposal_cards.py`, and changing it is a separate decision from
fixing a V2 defect.

No server, route, settings or storage behaviour changed. Nothing new is sent to the browser and
no npm dependency was added.

## Validation

| Check | Result |
|---|---|
| `functional_tests/test_v2_inline_image_proposal_status_persistence.py` | 7/7 |
| `functional_tests/test_v2_inline_image_proposals.py` | 13/13 |
| `node functional_tests/test_v2_inline_image_proposal_logic.mjs` | 32/32 |
| `functional_tests/test_v2_rich_rendering.py` | 13/13 |
| `functional_tests/test_v2_ui_local_assets.py` | 4/4 |
| `functional_tests/test_v2_citations.py`, `test_v2_message_masking.py`, `test_v2_chat_phase1_fixes.py`, `test_v2_diagram_viewer_controls.py`, `test_v2_visual_style_controls.py`, `test_v2_generated_image_lightbox.py`, `test_v2_message_inspector.py` | all pass |
| `npm run typecheck` and `npm run build` in `application/v2_ui` | clean |

The runtime checks added to the logic test cover the bug directly: that two cards in one message
get different keys, that re-parsing the same message names the same card, and that recording one
card's progress leaves another's alone.

## Before and after

| | Before | After |
|---|---|---|
| Second and third card, once the first image arrives | Status gone, Approve enabled, "Approve all" back | Still "Generating image…" or their queue position, Approve still disabled |
| Prompt edited, then the message re-renders | Edit discarded | Edit kept |
| Proposal cancelled, then the message re-renders | Card returns as pending | Stays dismissed for the view |
| Approved card | Title, badges, image, model | Title, image, model |
| Mermaid diagram in a re-rendering message | Re-initialised from scratch | Reconciled in place |
