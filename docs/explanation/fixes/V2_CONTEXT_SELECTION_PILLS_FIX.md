# V2 Context Selection Pills Fix (v0.261.094)

## Issue and root cause

Selecting documents through a workspace **Chat** action or the chat **Documents**
menu inserted their names into the message as `#[Name]` as well as showing context
chips above the composer. That duplicated context the user had selected without
intending to mention it in their question.

The V2 composer treated every context item as an inline mention. Its menu and
workspace handoff appended tokens, and text reconciliation removed any item
whose token disappeared. Simply removing the insertion would therefore make
selected chips disappear on the next keystroke.

## Fixed in version: **0.261.094**

The application patch version is recorded in `application/single_app/config.py`.
This changes V2 only; the classic interface and historical messages are unchanged.

## Behavior

| Workflow | Result |
| --- | --- |
| Workspace Chat action or Documents-menu selection | Context chips are added without changing the message text. |
| Explicit `#` autocomplete selection | An inline reference is inserted and its context chip is added or reused. |
| Delete an inline-only mention | Its chip is removed when no complete mention remains. |
| Delete an inline mention of an independently selected item | The independent context chip stays selected. |
| Remove or deselect a context chip | Its context and owned inline mentions are removed; unrelated literal text is preserved. |
| Send the message | Context travels with the request, and the draft and chips clear together. |

The same rules cover documents, tags, and whole-workspace references. A plain
hand-typed `#[Name]` does not resolve an identity or upgrade a selection into an
inline mention.

## Technical details

`ContextItem.attachment` distinguishes independent selection, inline mention,
and both. Source merging uses the existing stable key, preserving one chip and
one request identity per item. Reconciliation can downgrade a combined attachment
to an independent selection without removing the item; the composer applies that
change even when the number of chips stays the same.

Only active mention attachments participate in inline highlighting and token
removal. Asynchronous workspace handoffs are marked consumed and have their query
parameters cleared after resolution, so effect cleanup cannot discard them before
their chips arrive. They never append text, including when the user starts writing
while the selection loads.

Repeated explicit mentions reuse one chip. The token parser excludes nested
opening brackets so a partially deleted mention cannot swallow a later complete
mention of the same item.

Ordinary chat and orchestration continue to derive document IDs, tag filters, and
workspace scopes from context items rather than message text. Tag-only and
workspace-only selections also activate document search; they must not be ignored
because no individual document ID is present. No API schema, authorization policy,
or data migration changes are required.

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/chatContext.ts` | Typed attachment state, source merging, and selection token deduplication. |
| `application/v2_ui/src/lib/chatContextTokens.ts` | Mention-aware reconciliation, highlighting eligibility, and token parsing. |
| `application/v2_ui/src/lib/contextMentions.ts` | Explicit attachment mode for candidate conversion. |
| `application/v2_ui/src/components/chat/Composer.tsx` | Separate selection/mention entry points, removal, and asynchronous handoff adoption. |
| `application/v2_ui/src/stores/chatStore.ts` | Enable search for any selected context kind. |
| `application/single_app/config.py` | Patch version update. |

## Validation

At implementation, 35 token checks, 20 TypeScript request checks, the 10-check
picker functional suite, and 25 browser scenarios passed. The V2 production
build and the documentation coverage and quality checks also passed.

The regression coverage exercises both the state transitions and real browser
interactions, rather than relying only on source-code assertions:

- `functional_tests/test_v2_chat_context_tokens.mjs` covers token grammar,
  independent selections, mixed attachment lifetimes, and repeated mentions.
- `functional_tests/test_v2_chat_context_request.ts` covers identity merging,
  collision handling, and equivalent context fields for pill-only and inline items.
- `functional_tests/test_v2_chat_context_picker.py` covers composer wiring,
  handoff routing, existing replay metadata, and the TypeScript request checks.
- `ui_tests/test_v2_chat_context_selection.py` covers workspace and menu selection,
  explicit mentions, draft edits, removal, handoff resolution, and outgoing requests.

The expected before/after difference is visible before sending: selecting a
document no longer writes its name into the question, but its chip remains
selected while the user types and its ID still grounds the request.

See [Chat Context Picker](../features/CHAT_CONTEXT_PICKER.md) for usage and the
existing search and orchestration semantics.
