# V2 Chat Phase 1 Parity Fixes

## Issue

Six problems were reported in the V2 chat page. They looked unrelated, but each turned out
to be the same kind of defect: the client had been written against an *assumed* API contract
rather than the one the Flask routes actually implement. In every case the request succeeded
or the render completed, so nothing failed loudly — the feature just quietly did the wrong
thing.

**Fixed in version:** 0.261.012

## Root causes

### 1. Word, PowerPoint and email export did nothing

`route_backend_conversation_export.py` reads its parameters with
`request.get_json(silent=True)` and returns `400 Request body is required` when there is no
JSON body.

V2 submitted a hidden HTML form, which sends `application/x-www-form-urlencoded`. The server
therefore saw no JSON and rejected all three exports. The form approach had been justified in
a code comment claiming a `fetch` could not hand a file to the browser's download machinery.
That is not true, and the classic client (`chat-message-export.js`) does exactly that:
`fetch` with a JSON body, then `response.blob()` into an object URL.

A second, separate mistake was treating all three exports alike. They are not:

| Endpoint | Returns | Client must |
|---|---|---|
| `/api/message/export-word` | `.docx` bytes | download the blob |
| `/api/message/export-powerpoint` | `.pptx` bytes | download the blob |
| `/api/message/export-email-draft` | **JSON** `{subject, subject_source, body, attachments[]}` | save each attachment, then navigate to a `mailto:` |

Email is not a file download at all. A `mailto:` URL cannot carry attachments, which is why
the server returns the images separately for the user to attach.

### 2. Generated images rendered as a line of text

`hydrate_image_messages` (`functions_image_messages.py`) writes the image into the message's
**`content`**, in one of three forms:

- `data:image/...;base64,...` for a small inline image,
- `/api/image/<message_id>` when the bytes are in blob storage or exceed the inline limit,
- a plain `http(s)` URL for an externally hosted image.

There is no `image_url` key on the payload. V2 gated on `message.image_url`, which is never
set, so image messages fell through to the text renderer and printed the raw path.

### 3. Every message showed "2 of 2"

`thread_attempt` is **one-based**. Every creation site in the application writes
`'thread_attempt': 1` for a first attempt. V2 computed `(thread_attempt ?? 0) + 1`, so a
first-and-only attempt reported 2.

The total was wrong for a deeper reason. `/api/get_messages` filters the list to the active
attempt, so the loaded messages contain exactly one attempt per thread and can never reveal
how many exist. V2 derived the count from that list anyway.

### 4. The conversation tag never changed

The header rendered `scope.active_group_name` — the user's *globally* active group. It was
correctly showing a global value, in a position that implies a per-conversation one, so every
conversation displayed the same badge.

### 5. Selecting an agent had no effect

`route_backend_chats.py` reads the selection as:

```python
request_agent_info = data.get('agent_info') if isinstance(data.get('agent_info'), dict) else {}
```

The key is `agent_info` and it must be a **dict**. V2 sent `agent_selection` as a string, so
the server discarded it. The request still succeeded, which is why the picker looked
functional.

The agent picker also keyed its options off `agent.selection_key`. Agent catalog records
(`functions_agent_catalog._serialize_catalog_agent`) have no such field — `selection_key` is
a *model* concept — so the picker was silently falling back to `name`.

### 6. Newlines rendered differently depending on the sender

User messages render with `whitespace-pre-wrap` and keep every newline. Assistant messages go
through markdown, which by default collapses a single newline into the surrounding paragraph.
The same text therefore looked different depending on who sent it.

## The fixes

- **Exports** use `fetch` with a JSON body. Word and PowerPoint read `response.blob()` and
  save it; email fetches the JSON draft, saves its attachments, and then opens `mailto:`.
  Failures are reported rather than silent.
- **Images** are resolved from `content`, handling all three forms, with a visible fallback
  when an image cannot be loaded.
- **Attempts** use `thread_attempt` as one-based. The total comes from `available_attempts`,
  which the switch-attempt endpoint returns and which is now remembered per thread. The
  control is hidden until more than one attempt is known to exist, and shows the attempt
  number alone rather than inventing a denominator when the exact set is not yet known.
- **The title badge** reproduces `addChatTypeBadges` from `chat-conversations.js`, driven by
  the conversation's own metadata.
- **Agent selection** sends `agent_info` as the seven-field object the server resolves
  against, on both new messages and retries.
- **Newlines** are line breaks for both roles, with runs of blank lines collapsed as the
  classic client does.

### The title badge rules

| `chat_type` | Badge |
|---|---|
| `personal` / `personal_single_user` | none |
| `personal_multi_user` | `shared` |
| starts with `group` | the group name |
| starts with `public` | `public - <name>` |

The name comes from the primary context. When `chat_type` is absent the classic client infers
it from that context's scope, and conversations predating the field rely on that, so the
fallback is reproduced rather than defaulting everything to personal.

Classification pills and the scope-lock indicator complete the row. A null `scope_locked`
means no workspace data has been used yet, which is different from being unlocked, so it
shows nothing rather than an open padlock.

## Deliberate divergences

- **A single newline is a line break.** The classic UI uses marked's defaults
  (`breaks: false`), so strict parity would keep collapsing them. The reported complaint was
  the split behaviour between roles, and the classic UI's own Word export uses markdown2's
  `break-on-newline`, so honouring line breaks is the more faithful reading of intent.
- **Attempt navigation is actually reachable.** The classic UI renders its carousel buttons
  with `style="display: none"` and never reveals them, so attempt switching is effectively
  unavailable there. V2 surfaces it, which is why it needed a correct rule rather than a
  copied one.

## Additional bug found while fixing

Correcting the local preview fixture to the verified summary shape exposed that
`ConversationDetails.tsx` read `summary.text`. The stored summary's body is under
**`content`** (`route_backend_conversation_export.py` builds
`{'content', 'model_deployment', 'generated_at', 'message_time_start', 'message_time_end'}`),
so a generated summary would never have displayed. Fixed in the same change.

This is the same failure mode as the six above, and it was found the same way: by making the
fixture match the API instead of the assumption.

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/lib/endpoints.ts` | Real export implementations; blob download, email draft, mailto |
| `application/v2_ui/src/lib/images.ts` | New: resolve an image message's content |
| `application/v2_ui/src/lib/agents.ts` | New: `agent_info` construction |
| `application/v2_ui/src/lib/threads.ts` | New: one-based attempt rules |
| `application/v2_ui/src/lib/conversationBadges.ts` | New: badge rules mirrored from the classic client |
| `application/v2_ui/src/lib/citations.ts` | Collapse runs of blank lines |
| `application/v2_ui/src/lib/types.ts` | `summary.content`; image field comment |
| `application/v2_ui/src/stores/toastStore.ts` | New: user-facing notifications |
| `application/v2_ui/src/stores/chatStore.ts` | `agent_info`, attempt tracking, metadata on open |
| `application/v2_ui/src/components/ui/Toaster.tsx` | New |
| `application/v2_ui/src/components/chat/ConversationBadges.tsx` | New |
| `application/v2_ui/src/components/chat/MessageActions.tsx` | Exports, attempt display |
| `application/v2_ui/src/components/chat/MessageList.tsx` | Image rendering, `remark-breaks` |
| `application/v2_ui/src/components/chat/Composer.tsx` | Agent option keys |
| `application/v2_ui/src/components/chat/ConversationDetails.tsx` | `summary.content` |
| `application/v2_ui/src/components/layout/AppShell.tsx` | Mount the toaster |
| `application/v2_ui/src/pages/ChatPage.tsx` | Conversation badges |
| `application/v2_ui/src/styles/theme.css` | `--info` token for the group badge |
| `application/v2_ui/package.json` | `remark-breaks` |
| `application/single_app/config.py` | Version to 0.261.012 |

No Flask route was changed.

## Validation

`functional_tests/test_v2_chat_phase1_fixes.py` asserts each fix against the server source it
depends on, so a future change that re-guesses a contract fails the test. It checks that the
export routes require JSON and that no form submission remains, that email has its own path,
that images are read from `content` and `image_url` is gone, that nothing adds one to
`thread_attempt`, that the header no longer reads the active group, that `agent_info` is sent
as an object with all seven fields, that `remark-breaks` is registered, that the summary reads
`content`, and that failures are announced.

Behaviour was also verified in a browser against the local preview server, 26 checks:

| Area | Result |
|---|---|
| Header badges | Shows the conversation's own group (`FAA`), classification and scope lock; does **not** show the globally active group |
| Newlines | Three lines render as three lines (two `<br>` elements) |
| Images | A real `<img>` loads at 240×160; the raw path no longer appears as text |
| Attempts | No "2/2" anywhere on single-attempt messages |
| Word export | Downloads a `.docx` and reports success |
| Email export | Saves the attachment and opens the draft, via its own endpoint |
| Agent selection | `agent_info` arrives as a dict with the real id, name and scope flags; no `agent_selection` key |

The preview fixture was corrected first — agents no longer carry an invented `selection_key`,
`chat_type` uses a real value, attempts are one-based, and the export routes reject a form
post exactly as the real ones do. Building against a fixture that mirrors the assumption
rather than the API is what produced these defects originally.

## Related

- Feature documentation: `docs/explanation/features/REACT_V2_UI.md`
