# React V2 User Interface

## Overview

The V2 interface is a React single-page application that runs alongside the existing
server-rendered SimpleChat UI. It exists to evaluate a different visual and interaction
direction — a glassmorphism design system, a single collapsible left rail with no top bar,
and a search-first admin surface — without disturbing the interface people use today.

It reuses the existing Flask JSON APIs unchanged. No existing route, template, or
JavaScript module was modified to support it.

**Implemented in version:** 0.261.003
**Deployer version:** 1.0.26

### Dependencies

| Dependency | Purpose |
|---|---|
| React 18 + TypeScript | Application framework |
| Vite 6 | Build tooling, compiles to a static bundle |
| Tailwind CSS 4 | Styling, with a custom token layer for the glass system |
| zustand | Client state (theme, bootstrap, conversations, chat) |
| react-router-dom | Client-side routing under `/v2` |
| react-markdown + remark-gfm | Assistant message rendering |
| remark-breaks | Single newlines render as line breaks |
| lowlight | Code block syntax highlighting |
| lucide-react | Icons |

All dependencies are bundled locally by Vite and served from `/static/v2/`. Nothing is
loaded from a CDN, so the `default-src 'self'` Content-Security-Policy is unchanged.

### Vendored browser libraries

The libraries behind maths, diagrams and charts are **not** npm dependencies. They are
downloaded once, committed to this repository under
`application/v2_ui/public/vendor/<library>-<version>/`, and loaded at runtime from that
local path.

| Library | Vendored file | Purpose |
|---|---|---|
| KaTeX 0.18.4 | `katex.min.js`, `katex.min.css`, `fonts/` | TeX rendering |
| Mermaid 11.17.2 | `mermaid.min.js` | Diagram rendering |
| Chart.js 4.5.1 | `chart.umd.min.js` | Inline chart rendering |
| DOMPurify 3.4.14 | `purify.min.js` | Sanitizer boundary in front of both HTML sinks |

Resolving these from a registry at build time would mean the code the browser executes is
not the code in this repository. Vendoring pins it: a change to any of these libraries is a
reviewable commit rather than a silent substitution. Vite copies `public/` into the build
output verbatim, so the committed bytes are exactly what is served.

They are loaded on demand rather than bundled. Mermaid alone is 3.4 MB, and a conversation
with no diagram, chart or equation downloads none of it.

To upgrade one, replace the directory and its `LICENSE`, then update `VENDOR_PATHS` in
`src/lib/vendorAssets.ts` and the expected version in
`functional_tests/test_v2_rich_rendering.py`:

```powershell
$v = "11.17.3"
$dir = "application/v2_ui/public/vendor/mermaid-$v"
New-Item -ItemType Directory -Force -Path $dir
curl.exe -s -o "$dir/mermaid.min.js" "https://cdn.jsdelivr.net/npm/mermaid@$v/dist/mermaid.min.js"
curl.exe -s -o "$dir/LICENSE" "https://cdn.jsdelivr.net/npm/mermaid@$v/LICENSE"
```

Verify the download against the registry's published SHA-256 before committing it.

## Architecture

```
application/v2_ui/                     source (React + TypeScript)
  src/lib/          apiClient, sse, endpoints, types, enhancedCitations, syntax highlighting
  src/stores/       uiStore (theme, rail), bootstrapStore, chatStore
  src/components/   layout/, ui/, chat/
  src/pages/        ChatPage, AdminSettingsPage, WorkspacePage, PlaceholderPage
        │
        │  vite build
        ▼
application/single_app/static/v2/      compiled bundle (gitignored)
        │
        │  served by
        ▼
GET /v2  and  GET /v2/<path>           route_frontend_v2.py
```

### Why the SPA is served from the same App Service

The SPA is served by Flask from `/v2` on the same origin as the API. This is a deliberate
choice driven by how SimpleChat authenticates:

- Authentication is Entra ID / MSAL with a **server-side Flask session cookie**
  (`SameSite=Lax`, `HttpOnly`). Same-origin means the cookie is sent with no extra
  configuration.
- The application enforces a **custom same-origin CSRF check** on state-changing requests.
  Same-origin requests pass it unchanged.
- The Content-Security-Policy is `default-src 'self'`. Same-origin assets need no CSP
  relaxation.
- No CORS layer is required.

Hosting the SPA on a separate origin is supported but optional — see
[Optional: separate App Service](#optional-separate-app-service).

### URL layout

| Path | Served by | Notes |
|---|---|---|
| `/v2` | `route_frontend_v2.py` | SPA shell, `Cache-Control: no-store` |
| `/v2/<anything>` | `route_frontend_v2.py` | Same shell; client-side routing handles the path |
| `/static/v2/assets/*` | Flask static handler | Content-hashed JS and CSS |

The asset prefix (`/static/v2/`) differs from the app prefix (`/v2`) on purpose: assets go
through Flask's built-in static handler and its caching, so no asset request ever falls
through the SPA catch-all. The shell itself is never cached, because it references
content-hashed asset filenames that change on every deploy.

### Linking to a conversation

`/v2/chat` names the conversation it has open, in the same query parameter the classic
interface uses:

```
/v2/chat?conversationId=<conversation-uuid>
```

The parameter is read when the chat page first renders, and written whenever the open
conversation changes — including when the server creates one on the first message sent, and
when a conversation is forked. Starting a new chat or deleting the open conversation
removes it. Copying the address bar therefore always shares what is on screen, and a
refresh returns to it rather than to an empty chat.

Both spellings are accepted on arrival. The server emits `conversationId` from notifications
and workflow runs, and `conversation_id` from chat responses and workspace document rows, so
a link built by any part of the application opens. Only `conversationId` is ever written: an
incoming `conversation_id` link is rewritten to it, so a URL never carries both.

The parameter is a description of what is open, not a navigation step. It is written with a
history *replace*, matching `history.replaceState` in the classic client, so opening ten
conversations does not put ten entries behind the back button.

A conversation reached this way need not be in the loaded conversation list — it can be
older than the first page of the feed, or hidden. Its list row is built from the metadata
the chat page already fetches, so the rail highlights it and the header shows its real
title. A link naming a conversation that has been deleted, or that belongs to somebody else,
reports that it cannot be opened and falls back to an empty chat; leaving the failure in
place would strand the parameter in the URL and reproduce the same error on every refresh.

**Back to classic UI** in the account menu carries the open conversation across as
`/chats?conversationId=<id>`, so crossing between the two interfaces keeps your place.

Server-generated links — notifications, workflow runs, document sources — still point at the
classic `/chats`. They are not interface-aware.

## API surface

### `GET /api/v2/bootstrap`

Blueprint `backend_v2` — `login_required`, `user_required`.

Returns everything the SPA needs for its first paint in one request, mirroring the template
context that `route_frontend_chats.chats` passes to `chats.html`. It calls the same catalog
builders (`_build_chat_model_catalog`, `_build_chat_prompt_catalog`,
`build_accessible_agent_catalog`, `_build_initial_chat_model_selection`), so the two
interfaces cannot disagree about which models, agents or prompts a user may use.

Response fields:

| Field | Contents |
|---|---|
| `version` | Application version |
| `user` | Id, display name, email, `is_admin`, roles |
| `branding` | App title, logo URLs, classification banner |
| `features` | Every boolean `enable_*` key, plus per-user computed overrides |
| `catalogs` | Models, agents, prompts, and the initial model selection |
| `scope` | Active group and public workspace, plus the lists the user can pick from |
| `admin_nav` | The `ADMIN_NAV` structure — **only** for users holding the Admin role |
| `notices` | The two administrator-configured chat notices, resolved server-side |
| `settings` | Settings passed through `sanitize_settings_for_user()` |

Settings returned here are always sanitized. The logo is reported as a URL rather than the
stored base64 payload, because sanitization strips any key containing `base64` and the
images are already served as static files.

### `GET` and `PATCH /api/v2/admin/settings`

Blueprint `backend_v2_admin` — `login_required`, `admin_required`.

Returns the **raw** settings document, the admin navigation, the field schema and a
description of the stored branding images. Admin settings are deliberately not sanitized:
sanitization removes the keys, secrets and endpoint configuration that an administrator is
there to manage. Access is gated on the Admin role at both the blueprint guard and the
route decorator.

| Key | What it carries |
| --- | --- |
| `settings` | The raw settings document. |
| `admin_nav` | Group → tab → section structure, from `admin_settings_nav.py`. |
| `field_schema` | Section id → declared fields, from `admin_settings_fields.py`. |
| `branding_assets` | Presence, version and URL of each logo and the favicon. The base64 blobs are never returned. |

`PATCH` applies a partial update. Supplied values are normalized against the field schema
before anything is written, and the update is applied only if every key validates, so a
save never lands half-applied. A rejected save returns `400` with a `field_errors` map so
the UI can put each message next to the control that caused it.

Values that are advisory rather than invalid — an agreement longer than the recommended
200 words, for example — are returned in a `warnings` map and still saved, matching what
the server-rendered form does.

### `POST /api/v2/admin/settings/branding-image`

Blueprint `backend_v2_admin` — `login_required`, `admin_required`. Multipart.

Accepts `target` (`logo`, `logo_dark` or `favicon`) and `file`. Branding images cannot ride
along with a JSON `PATCH`, and they have to be converted before they can be stored, so they
get their own endpoint.

The conversion is `functions_branding_images.py`, shared with the server-rendered form, so
an image uploaded through either interface is stored identically: PNG and JPEG only, logos
capped at 500px tall, favicons squared off to a 32×32 ICO. Each successful upload bumps the
matching version counter, because the static file keeps a stable name and browsers would
otherwise keep serving the previous image.

## Interface

### Design system

Glass surfaces are defined as CSS custom properties in `src/styles/theme.css` and mapped
into Tailwind utilities with `@theme inline`, which is what allows them to swap at runtime
between light and dark.

Three deliberate constraints shape the implementation:

- **`backdrop-filter` is expensive.** The blurred `.glass` class is applied only to a
  bounded set of persistent chrome — the rail, page headers, the composer, and popovers.
  Repeated content such as message bubbles and document rows uses `.glass-flat`, which has
  the same surface colour and border but no blur, so long threads stay smooth to scroll.
- **Glass on light backgrounds hurts readability.** Light-mode surface alpha is kept high
  (0.62–0.86) rather than the more dramatic low values, so long-form assistant responses
  stay comfortable to read.
- **Transparency is a preference, not a given.** `prefers-reduced-transparency` switches
  every glass surface to a solid colour and removes the background mesh entirely;
  `prefers-reduced-motion` disables transitions and animations.

### Dark and light mode

Theme is a `.dark` class on `<html>`, not a media query, so an explicit choice overrides
the OS preference. It is applied by a small inline script in the document head before first
paint, which avoids a light flash for dark-mode users. The toggle lives at the bottom of the
left rail.

It is stored twice, on purpose. `localStorage` is what the first render reads, because the
settings request has not resolved at that point and hydrating only from the server would
flash the wrong theme on every load. The durable copy goes to `/api/user/settings` under
`darkModeEnabled` — the key the classic interface already uses — so the choice follows the
user to another machine and the two interfaces agree. Rail collapse and chat width persist
the same way, but under `v2RailCollapsed` and `v2ChatWidth`: the classic `dockedSidebarHidden`
and `chatLayout` describe its own surfaces, and writing them from here would rearrange that
interface as a side effect of a choice made in this one.

### Layout

There is no top bar. Brand and logo sit in the upper left of the rail, primary navigation
and the conversation list sit beneath, and the theme toggle and user menu are pinned to the
bottom. The rail collapses to a 68px icon strip, and the collapse state is persisted. All
content lives in the right-hand pane.

The classification banner, when configured, is the only element that spans the full width —
matching the server-rendered interface.

### Chat

Wired to the live APIs:

- Conversation feed with cursor paging (`/api/conversations/feed`), search, rename, delete,
  pin and hide
- Streaming responses over `POST /api/chat/stream`, including `thought` frames rendered in
  a collapsible reasoning panel, `conversation_metadata` for server-generated titles,
  `user_message_persisted` acknowledgements, and cancellation
- Model, agent and prompt pickers populated from the bootstrap catalogs
- Document search, web search, image generation, deep research, URL access and per-model
  reasoning effort
- File upload to `/upload`, and voice input via `/api/speech/transcribe-chat`
- A right-hand drawer with Contents (jump to any of your turns) and Documents (what the
  conversation cited, and where)
- Conversation details with inline rename
- Per-message actions: copy, retry, edit and resend, delete, feedback, fork, exports, read
  aloud, and attempt paging once a message has been retried
- A per-message inspector with the sources a response cited, the reasoning behind it, and
  how it was produced
- Masking part or all of a message, so its content is withheld from the model
- Conversation details with a generated summary, categorised tags and paged source documents
- Composer controls that appear only when they are relevant, and a chat width preference
- Citations rendered as inline chips that open either the cited source itself — the PDF
  page, image, media clip, spreadsheet or Visio page — or the passage that was extracted
  from it
- Generated images rendered inline, opening in a viewer with fit and actual-size zoom, a
  download and a link to the raw file, and a conversation badge showing the group or public
  workspace the conversation is working in
- The administrator-configured web search and AI notices

The SSE reader in `src/lib/sse.ts` reproduces the framing rules of
`static/js/chat/chat-streaming.js` exactly, including the repair for frames whose blank-line
delimiter was emitted as a literal escaped `\n\n`. The native `EventSource` API cannot be
used because the endpoint is a `POST` with a JSON body.

Several contracts here are two-step or otherwise non-obvious, and were read from the route
source rather than inferred:

- **Retry and edit generate nothing on their own.** Each creates the next thread attempt
  and returns a ready-made `chat_request` body, which must then be POSTed to
  `/api/chat/stream`. Skipping that second call leaves the new attempt permanently empty.
- **Attempt switching is server-side state.** `switch-attempt` flips `active_thread` in
  storage and `/api/get_messages` filters on it, so the client re-reads the list rather
  than reordering locally.
- **Deep research is carried by two fields.** Both `source_review_enabled` and
  `deep_research_enabled` are sent; only one disables half the behaviour.
- **Reasoning effort is per model family, and remembered per model.** `gpt-4o` supports
  none, `gpt-5-pro` only `high`, the 5.1 series skips `low`, and the o-series offers
  low/medium/high. The control is hidden entirely when a model offers no choice. The chosen
  level is stored in `reasoningEffortSettings`, the same map the classic interface writes,
  keyed by model id — so it survives a reload, applies to that model alone, and means the
  same thing in both interfaces. Where there is no model catalog to key on, which is a
  single-endpoint deployment, no level is derived or sent unless one is chosen.
- **Citation markers** follow the grammar in `chat-citations.js`; a functional test asserts
  the two patterns stay identical so markers never render as raw text.
- **`thread_attempt` is one-based**, and `/api/get_messages` filters to the active attempt.
  The number of attempts therefore cannot be counted from the loaded messages; only
  `switch-attempt` reports the full set, in `available_attempts`.
- **Agent selection is `agent_info`, and must be a dict.** The chat route reads
  `data.get('agent_info')` and ignores anything that is not a dictionary, so a bare string
  is accepted by the request and then silently dropped. Agent catalog records carry no
  `selection_key`; that field belongs to models.
- **A model needs four fields, not one.** `model_endpoint_id`, `model_id`, `model_provider`
  and `model_deployment` are resolved together. With multiple endpoints configured a
  deployment name is not unique, so `resolve_streaming_multi_endpoint_gpt_config` returns
  `None` when the endpoint id is missing and the request falls back to the legacy
  single-endpoint client — a different model than the one selected, with no error. The
  picker therefore keys on `selection_key`, which is unique per endpoint.
- **The document scope travels with its workspace ids.** `_get_authorized_chat_scope_context`
  filters requested ids down to what the caller may see, so `doc_scope: 'all'` with no ids
  covers only personal documents. The scope is computed from the workspaces in play, as
  `chat-messages.js` does: personal alone gives `'personal'`, anything wider gives `'all'`
  together with the group and public workspace ids.
- **`chat_type` is part of that scope, not a constant.** The streaming route accepts only
  `'user'` or `'group'` and derives `scope_id` / `scope_type` from it, so a group
  conversation that reports `'user'` is searched and attributed as a personal one. It is
  set to `'group'` exactly when a group is active; a public workspace stays `'user'`,
  matching `chat-messages.js:7149`.
- **`chat_type` stays `'user'`, deliberately.** The streaming route turns it into
  `scope_id` / `scope_type`, and those feed the fact-memory read and autosave — so sending
  `'group'` because a group happens to be selected would publish a personal conversation's
  extracted facts into that group. The classic client appears to send `'group'` when a
  group is active, but its guard reads `window.activeChatTabType`, which is read in two
  places and assigned in none, so the branch is unreachable and V1 always sends `'user'`.
  Group documents are reached through the scope ids above, which widens the search without
  re-scoping the request.
- **A dropped stream is recoverable, because generation outlives the connection.** The
  answer is written into a server-side stream session, so a broken transport is not a lost
  answer. On a stream that ends without a terminal frame, `GET /api/chat/stream/status/<id>`
  is consulted and, if it reports `pending`, `GET /api/chat/stream/reattach/<id>` is
  consumed. That route calls `iter_events()` with no start index, so it **replays from the
  first event rather than resuming at an offset** — everything already rendered has to be
  cleared or the answer appears twice. Recovery is attempted once, as
  `chat-streaming.js` does with `allowRecovery: false`. Opening a conversation whose answer
  is still generating attaches the same way.
- **Recovering and recovered are separate states.** While the status check and the reattach
  request are in flight the answer genuinely has stopped arriving, and the interface says
  so — including when part of the answer is already on screen, which would otherwise just
  look frozen. Once frames are coming back the response is working normally, so the wording
  becomes a brief confirmation that clears itself and the activity label returns to
  "Thinking". Holding the "reconnecting" state for the whole reattached stream makes
  working output look stalled, which is the opposite of what is happening.
- **Attaching to a stream is not the same as owning it.** `stopStreaming` POSTs
  `/api/chat/stream/cancel`, a real server-side cancellation, and it addresses the
  conversation recorded as this tab's own stream. A resume therefore does not record one:
  the generation may belong to another tab or to this page before a reload, so navigating
  away detaches locally instead of truncating someone else's answer. The classic client
  behaves the same way — a thread switch only aborts its own reader, and cancellation is
  reached solely from the Stop button.
- **Citation replacement must restore the whitespace it consumed.** The marker grammar ends
  in `((?:\[#.*?\]\s*)+)`, and `\s` matches newlines, so the pattern absorbs the blank line
  that separates the citation from the next markdown block. Because the whole match is
  replaced, dropping that whitespace merges the following bullet list, heading or paragraph
  into the citation's own line. `chat-citations.js` captures and re-appends it; V2 does the
  same, at both exits from the replacer.
- **Text leaving the app is not `message.content`.** Two transformations sit between the
  stored content and what a reader sees, and both matter on the clipboard. Masked spans are
  redactions, so copying raw content would hand back text someone deliberately hid; and
  citation markers are shown as chips, so raw content still carries
  `(Source: file.pdf, Page: 3) [#guid_3]` mid-sentence, which is unreadable when pasted.
  `lib/messageText.ts` holds the single conversion used by copy, the Markdown download and
  reuse as a prompt: it applies masks, replaces them with `[masked]`, removes citation
  markers together with the space in front of them, and leaves markdown untouched. A
  wholly masked message is withheld rather than partially cut. Attribution is not lost —
  **Copy with sources** and the saved file append the citations as a numbered reference
  list instead of interleaving them.
- **Image messages carry the image in `content`**, as a data URI, an `/api/image/<id>` path,
  or an external URL. There is no `image_url` field. The three are not interchangeable once
  the image leaves the page: `data:` URIs cannot be navigated to at the top level, and
  `/api/image/<id>` is authenticated, so both saving and opening an image branch on the kind
  rather than treating `content` as a plain URL.
- **The three message exports are not alike.** Word and PowerPoint stream a document; the
  email draft returns JSON, whose images must be saved separately because a `mailto:` URL
  cannot carry attachments. All three require a JSON request body and reject a form post.
- **The conversation summary's body is `summary.content`**, not `summary.text`.

### Maths, diagrams and charts

Three kinds of block that the application already produces render as themselves rather than
as raw text. All of it is handled in `AssistantMarkdown.tsx`, which is split out of
`MessageList.tsx` because how a message renders is a separate concern from how the thread is
laid out.

**TeX** is recognised as `$$…$$`, `\[…\]` and `\(…\)`. A single `$…$` is deliberately *not*
recognised: it is ordinary in prose about money, and rendering "costs $5 to $10 per user" as
an equation is a worse failure than leaving a rare inline expression unrendered.

`remark-math` is not used, for two reasons. CommonMark treats a backslash before ASCII
punctuation as an escape, so by the time an mdast node exists `\(x\)` has already become the
literal text `(x)` — a post-parse plugin cannot see those delimiters at all. And the renderer
already has the right mechanism: citations and masks are lifted out of the text as inert
`⟦cite:N⟧` tokens and swapped back in as components, so that nothing injects HTML into model
output. Maths uses the same path, as `⟦math:N⟧`.

**Mermaid** has been reaching the chat since before it could be rendered: Content
Understanding writes ```` ```mermaid ```` fences into extracted document text
(`functions_content_understanding.py`), so a document containing a diagram was arriving as
diagram source.

**SimpleChart** renders the ```` ```simplechart ```` payload the built-in chart action emits,
matching what the classic client draws for the same message. The payload grammar and
sanitisation limits are ported from `chat-inline-charts.js`. Below the chart sit a
**Data** disclosure, a **PNG** download and a **Colors** control. The disclosure is closed by
default — the chart is the answer, and a 500-row table opened automatically would bury the rest
of the reply — but it is one click away, because a chart without its numbers cannot be checked.
A payload with no `table` of its own has one derived from its labels and series.

Diagrams carry the same **PNG** and **Colors** controls. The PNG is rasterized from the SVG
already on screen rather than re-rendered, so the file matches what is displayed; the path is
the one `chat-visual-rasterizer.js` already uses for exports. `htmlLabels: false` is what makes
this possible at all, since a `<foreignObject>` label vanishes when an SVG is painted onto a
canvas.

**Colours** are resolved from the built-in palette, then a per-user default in Settings →
Preferences, then an override saved against one block of one message. Recolouring one chart
never affects another. See
[V2 Diagram And Chart Styling](V2_DIAGRAM_AND_CHART_STYLING.md) for the palettes, the
storage format and the validation rules. Unlike the classic client's colour editor, nothing
rewrites the stored message: the payload the model produced stays as it was written, and the
colours live beside it in message metadata.

Some details worth recording:

- **Untrusted input is the whole design constraint.** KaTeX runs with `trust: false`, which
  disables `\href`, `\url` and `\includegraphics`. Mermaid runs with `securityLevel: 'strict'`
  and `htmlLabels: false`, never has `bindFunctions` called on it, and registers no icon packs
  because those are fetched from the public Internet. Both produce markup that has to be
  injected as HTML, so each passes through DOMPurify first — the only two places in the SPA
  that use `dangerouslySetInnerHTML`, and a test fails if a third appears. Chosen colours are
  reduced to `#rrggbb` before they reach a style attribute or Mermaid's configuration.
- **A streaming reply would otherwise be handed half a diagram.** The bubble re-renders on
  every token and markdown treats an unclosed fence as a code block running to the end of the
  input, so an unterminated trailing diagram or chart fence renders a placeholder until it is
  complete. The classic client solves the same problem the same way, with
  `INLINE_CHART_PENDING_REGEX`. Completed diagrams are cached by source text and colours, so the
  rest of the stream re-renders nothing.
- **Rich fences are rendered from `pre`, not `code`.** The `<pre>` is the element the renderer
  replaces outright, and `rehypeRichBlockIndex` stamps the `<code>` inside it with the block's
  number — which is how a block is matched to any colours saved against it. That number comes
  from walking the parsed tree, because a text scan disagrees with the parser about fences
  nested in list items or behind a blockquote prefix.
- **Copying a chart gives you its numbers.** On screen a `simplechart` block is a chart;
  pasted verbatim it is kilobytes of minified JSON in the middle of an answer. `messageText.ts`
  substitutes the chart's title and a markdown table. TeX and mermaid sources are left alone,
  because unlike a chart payload they are still meaningful to read.
- **Charts and diagrams follow the theme.** Mermaid re-renders on a light/dark switch and
  Chart.js takes its tick, grid and legend colours from the same CSS custom properties as the
  rest of the interface. A block left on "Match theme" keeps doing so; one given an explicit
  background has its label colours recomputed from that background's luminance instead. The
  downloaded PNG is composited onto an opaque colour first, because a transparent chart or
  diagram is unreadable wherever it is pasted.

### Message inspector

Three controls in the hover row open a panel beneath the message: **Sources**, **Reasoning**
and **Details**. One panel with three sections rather than three panels, because comparing
what a response cited against how it was produced should not mean closing one to open
another.

**Sources** are already on the message document — `hybrid_citations`,
`web_search_citations` and `agent_citations` — so no request is needed. A citation URL is
model-influenced input, so only `http(s)` becomes a live link; anything else is shown as
text.

**Reasoning** is not on the message. It is stored separately and fetched per message from
`/api/conversations/<id>/messages/<id>/thoughts`, whose records use `step_type`, `detail`,
`activity` and `duration_ms` where a live stream frame carries `title` and `content`. The
stored shape is mapped onto the streamed one so a single renderer draws both: historical
reasoning looks exactly like reasoning being generated, rather than becoming a different
presentation once the response finishes. The endpoint distinguishes "none recorded" from
"capture is disabled", and the panel says which.

**Details** reports the model or agent, reasoning effort, and capability usage. Enabled and
used are tracked separately, and the difference is the useful part: a response where web
search was available but never exercised explains itself. It also surfaces `history_context`,
which records how many earlier messages were kept, summarised, or skipped as an inactive
attempt or as masked — usually the answer to why a response lacked context the user expected.

The response shape of `/api/message/<id>/metadata` **depends on the message's role**: a user
message returns its nested `metadata` object alone, while assistant, image and file messages
return the whole document with `metadata` nested inside. Both are handled.

### Message masking

Selecting text inside a message offers a **Mask selection** control; the hover row offers
masking the whole message and clearing masks once any exist.

Masking is not a display setting. The server strips masked content from the history it sends
to the model, so the client's job is to show what is masked and to make the correct calls,
never to enforce anything. Consistent with that, masked text is **cut out of the content
before rendering** rather than hidden with styling — it is never present in the page, and the
component that stands in for it is given only the range's metadata.

Two details of the endpoint shape the implementation:

- **The server does not trust the offsets it is sent.** It resolves the selection against the
  stored content, first by the offsets, then by locating the selected text, then against a
  markdown-stripped projection of it (`_resolve_selection_offsets`). A selection it cannot
  place uniquely is rejected with a 400 — which happens when a selection spans citations or
  formatting and so is not a contiguous span of the original. The interface reports that
  rather than showing a mask that does not exist.
- **The response reports only `masked` and `masked_ranges`.** It does not return who applied
  a whole-message mask, so the attribution shown immediately afterwards comes from the acting
  user; a reload replaces it with the stored value.

Masks are applied **before** citation parsing, because their offsets are canonical positions
in the raw content and citation parsing rewrites the string.

There is no `can_*` field on any payload, so the client mirrors the server's rule — the
message's author, falling back to the conversation's owner for messages that record no author
— to decide what to offer, and still handles a 403.

### Conversation details

The metadata endpoint returns considerably more than a flat list. Its `tags` array is
heterogeneous — every entry carries a `category` of `document`, `model`, `agent`,
`participant`, `semantic` or `web`, and the useful fields differ per category. Rendering
them as one row of chips is what mixed documents in with model names, so each category is
presented on its own terms.

**Source documents** get their own paged section. Which list is authoritative depends on the
conversation: `used_documents` once `used_documents_tracking_version` is at least 1,
otherwise `legacy_used_documents`, otherwise the document tags — the same order the classic
client uses. Documents a response actually referenced are marked as cited; a conversation
that predates citation tracking says so rather than showing everything as uncited.

The **summary** is produced by a model, so it is generated on demand rather than
automatically, and the panel re-reads the conversation afterwards rather than trusting the
response.

A `web` tag's value comes from model output, so only `http(s)` values become links.

### Conversation export

A whole conversation, or several at once, can be exported as JSON, Markdown or PDF, either as
one file or as a ZIP holding one file per conversation. An optional intro summary puts a short
written abstract above each transcript.

It is reachable three ways: a single conversation's own menu in the rail, the rail's selection
mode for several at once, and the conversation details dialog. Starting from a single
conversation skips the review step, so that export opens on the format choice.

The wizard drives the endpoints the classic wizard already uses —
`POST /api/conversations/export` and `POST /api/conversations/export/visual-scan` — so nothing
was added server-side and the two interfaces produce identical files.

A model chosen for the intro summary is sent as all four identity fields
(`summary_model_deployment`, `summary_model_endpoint_id`, `summary_model_id`,
`summary_model_provider`). Sending only the deployment name makes the server's resolver return
nothing and fall back to the legacy single-endpoint client, which is a different endpoint from
the one the user picked, with no error anywhere.

**Diagrams are drawn in the browser.** Mermaid is a browser library, so the alternative is the
server launching headless Chromium once per export. The client asks the scan endpoint which
diagram sources the selected conversations contain, renders each one, and posts the PNGs back
as `visual_assets`. Rendering goes through the same hardened runtime the chat uses
(`lib/mermaidRuntime.ts`), which is why that runtime is shared rather than living inside
`MermaidDiagram.tsx`: an export covers conversations that were never on screen, so there is no
mounted component to take an SVG from.

Exports are drawn with a fixed light preset rather than the reader's theme, because the file is
read outside the application, where a dark diagram on white paper is unreadable. A diagram that
fails to render is left out and the server draws it instead, so a broken diagram costs fidelity
rather than the whole export. A JSON export skips this entirely — it keeps the original
markdown, fences included.

### Composer gating

Every control being visible whenever its capability was enabled is what made the composer
row crowded, and offering "Read URLs" with no URL present invites a confusing result. The
rules from `chat-input-actions.js` are reproduced:

- **Read URLs** requires `enable_url_access` **and** a URL in what is currently typed.
- **Deep research** requires `enable_source_review` **and** somewhere to research: web
  search active, or URLs present.
- **Image generation** is mutually exclusive. While it is on, the retrieval controls and
  file upload are disabled and the model picker is hidden, because the request goes to an
  image endpoint that takes neither.

A control that stops being relevant also clears its option, so a request never carries a
capability the user can no longer see they enabled.

### Notices

Two notices are configured by an administrator, and both are reproduced from the classic
interface rather than reinvented.

The **web search notice** (`enable_web_search_user_notice`, text in
`web_search_user_notice_text`) sits above the input and appears only while the Web toggle is
armed. A banner that is always present stops being read, and the thing it warns about — this
message leaving the tenant — only happens when web search is on. Turning web search off hides
it again without consuming the dismissal, which is held for the browser session.

The **AI notice** (`enable_ai_notice`, `ai_notice_message`, `ai_notice_frequency`) sits below
the composer. Where a dismissal is stored depends on how long it has to last:
`every_session` is a browser-session fact and stays in `sessionStorage`; `daily` and `once`
outlive the tab, so they are written to `/api/user/settings` as `aiNoticeDismissal` and the
server decides on each load whether the window still applies. `non_dismissible` renders no
dismiss control at all. The notice is hidden only after the write succeeds — hiding first
would tell a user the notice is gone for the day when it may be back on the next load.

Neither is derivable from `features`, which is why `/api/v2/bootstrap` carries a `notices`
block instead:

- The AI notice's version hash is a SHA-256 of its message and frequency, computed by
  `functions_ai_notice.py`. Editing the notice changes the hash and invalidates every stored
  dismissal, so the new wording is shown again. Recomputing that in the browser would let the
  two interfaces disagree about whether somebody had dismissed it.
- The web search notice additionally requires `web_search_consent_accepted`, which is not an
  `enable_*` key and therefore never reaches the feature flags.

When an administrator has not enabled the AI notice, V2 shows nothing there. It deliberately
does not substitute a generic disclaimer of its own: an organisation that turned the notice
off did so on purpose, and the classic interface honours that.

Both notices render administrator text as an ordinary React child, so it is escaped. Session
storage is read through `src/lib/notices.ts`, which tolerates the privacy modes where
`sessionStorage` throws instead of returning `null` — a notice is not worth taking the page
down for, so a read that fails leaves the notice visible and a write that fails says so.

### Chat width

A header control switches between a fixed reading measure and using the full pane, and the
choice persists alongside the theme. The thread and the composer widen together: widening
one without the other leaves the composer just as cramped, which is the problem it exists to
solve. Bubbles stay narrower than the container in both modes, since a line spanning a large
monitor is unreadable either way.

### Conversation badges

The badges beside the conversation title reproduce `addChatTypeBadges`
(`static/js/chat/chat-conversations.js`) so both interfaces describe a conversation the same
way: classification pills, then a single workspace badge — the group name, `public - <name>`,
`shared`, or nothing at all for a personal conversation — and the scope-lock indicator.

All of it comes from that conversation's own metadata. Reading the user's globally active
group here instead is what made every conversation show the same badge.

A null `scope_locked` means no workspace data has been used yet, which is not the same as
being unlocked, so nothing is shown rather than an open padlock.

### Workspace tags in the conversation list

The same derivation labels every row of the conversation list, so a user working across
several groups can tell their conversations apart without opening them.

This needs no extra request. `chat_type` and `context` are stored on the conversation
document itself (`functions_conversation_metadata.py`), and the feed returns that document
whole — `_strip_internal_feed_fields` removes only `_feed_source`. The badge helper therefore
accepts either the metadata payload or a feed conversation, and the list derives the tag
from what it already holds. Fetching metadata per row would be one request per conversation
on every page of the feed.

The tag renders as a muted second line under the title rather than an inline pill, because
the rail is narrow and group names are long: inline, either the title or the tag would always
be truncated. It is controlled by `showConversationWorkspaceTags`, which defaults to shown
when unset.

### Enhanced citations

A citation into a PDF is more useful when it opens the page than when it quotes the
sentence, and a citation into a recording is only meaningful if it plays from the moment
being cited. V2 reproduces that behaviour against the existing
`/api/enhanced_citations/*` endpoints.

Clicking a chip resolves in three steps:

1. `enable_enhanced_citations` must be on. It arrives with the bootstrap feature flags.
2. `GET /api/enhanced_citations/document_metadata?doc_id=` is consulted, and the result is
   cached per document so repeated citations into the same file do not refetch. The gate is
   deliberately permissive, matching `chat-citations.js`: only an explicit
   `enhanced_citations === false` opts a document out. Missing or unreadable metadata still
   attempts the viewer and relies on the fallback below.
3. The viewer is chosen from the file extension alone, exactly as `getFileType` does. There
   is no content-type negotiation.

| Extensions | Viewer | Behaviour |
|---|---|---|
| `pdf` | PDF | Opens at the cited page, with a toggle for the whole document |
| `jpg` `jpeg` `png` `bmp` `tiff` `tif` | Image | Fit-to-pane and actual-size zoom |
| `mp4` `mov` `avi` `mkv` `flv` `webm` `wmv` `m4v` `3gp` | Video | Seeks to the cited offset |
| `mp3` `wav` `ogg` `aac` `flac` `m4a` | Audio | Seeks to the cited offset |
| `csv` `xlsx` `xls` `xlsm` | Tabular | Sheet switcher, truncation notice, download |
| `vsdx` | Visio | Server-rendered PNG per page, with page stepping |

Anything else — a `.txt` or `.docx`, say — has no viewer and goes straight to the text
passage. So does any failure at any stage, and the text panel says so rather than opening
silently, because a fallback that looks identical to success hides a broken deployment.

Three details are worth recording:

- **No PDF engine is bundled.** The client fetches the bytes, creates an object URL and
  points an `<iframe>` at `blob:…#page=N`, which is what V1 does and what the existing
  `frame-src 'self' blob:` policy already permits. Vendoring a PDF renderer would have
  added a large third-party browser asset for no benefit. Object URLs are revoked when the
  viewer closes.
- **The server, not the client, narrows the PDF.** `serve_enhanced_citation_pdf_content`
  extracts a one-page window either side of the citation and returns `X-Sub-PDF-Page`
  naming the page *within that extract* to open at. The client reads that response header;
  it does not compute the page itself.
- **Media citations carry a time offset, not a page.** The location field may be a seconds
  count, `MM:SS` or `HH:MM:SS`, and is converted before `currentTime` is set. V2's
  conversion tests the clock forms before attempting a plain number, so `0:02` seeks to two
  seconds. Doing it the other way round makes `parseFloat` return `0` and every cited
  moment plays from the start.

### Admin settings

The server-rendered admin page nests 14 groups → 46 tabs → 96 sections, so finding a single
toggle can take several clicks through two levels of tabs.

V2 flattens the same structure: a slim category rail for the 14 groups, a single scrollable
pane of sections, and a search box that matches across every section, tab, group, setting
key, label and help string at once. Pressing `/` focuses search from anywhere on the page.
Typing `retention` or `data lifecycle` both find the retention settings.

The structure still comes from `admin_settings_nav.py`, so it cannot drift from the classic
page.

#### Where the controls come from

Two sources feed the page, and which one a section uses depends on whether it has been
described yet.

**Declared fields.** `admin_settings_fields.py` maps a section id to an ordered list of
fields, each carrying the type, label, help text, default, bounds, options and visibility
dependency a generic renderer needs. Everything in the Appearance group is described this
way, which is what allows V2 to show titles, colour pickers, selects, ranges, markdown
editors, image uploads and repeatable lists rather than switches alone.

**The `enable_*` fallback.** A section with no declaration is still discovered by scanning
the settings document for booleans and matching each key to a section by shared word stems.
Anything unmatched is collected under "Other capabilities" rather than hidden, because a
silently missing toggle is worse than a misfiled one. This is how the whole page originally
worked; it stays so undescribed groups keep functioning, and it retires one group at a time
as each is described.

A key that has a declared field is excluded from the fallback scan, so a setting is never
rendered twice.

#### Saving

Edits buffer into a draft and save together through a single `PATCH`, from a sticky bar
that reports how many changes are pending and offers **Save changes** or **Discard**.
`Ctrl`/`Cmd`+`S` saves, and closing the tab with pending edits prompts first.

Buffering is not only a UI preference. Terms of Use and the AI notice derive a content
version from their text and frequency, and every new version re-prompts every user. Saving
on each keystroke would mint a version per character.

Two things save immediately instead, because they are not part of the settings document:
branding image uploads, which need server-side conversion before anything can be previewed,
and custom page metadata, which lives in its own Cosmos container.

#### Appearance group

| Tab | What V2 now renders |
| --- | --- |
| Branding | Application title, show-logo and hide-title switches, a 50–500% home page logo size slider, light and dark logo uploads and a favicon upload, each with a live preview |
| Branding → Home Page Text | Markdown alignment, editor toggle, and the landing page text with a live preview that follows the chosen alignment |
| Branding → Appearance | Dark mode and left navigation defaults |
| Notices & Agreements | Classification banner with two colour pickers and a live preview; the AI notice text and display behaviour; the full Terms of Use configuration; the user agreement with its four apply-to targets, a word counter and a **Test preview** dialog |
| Pages & Links | Custom pages with a restart acknowledgement, menu options and the full static page designer; external links as an add, remove and reorder editor |

The static page designer writes to the same `/api/admin/custom-pages` CRUD as the classic
designer, so a page created in either interface is identical. Python-registered pages are
listed but not editable, because they are defined in code.

#### Keeping the two interfaces in step

The schema is a second description of settings the server-rendered panes also describe, so
it could drift. `functional_tests/test_v2_admin_appearance_parity.py` reads the three
Appearance panes, collects every form field name they submit, and fails unless each one is
claimed by the schema — directly, through the documented `LEGACY_FIELD_NAMES` aliases where
the two shapes differ, or through an explicit exemption. It also checks the reverse
direction, so the schema cannot invent a setting nothing reads, and compares select option
values and range bounds between the two.

`LEGACY_FIELD_NAMES` records the places the shapes genuinely differ:

| Server-rendered form field | Settings key |
| --- | --- |
| `user_agreement_apply_personal` / `_group` / `_public` / `_chat` | `user_agreement_apply_to` (array) |
| `external_links_json` | `external_links` (array of `{label, url}`) |
| `logo_file` / `logo_dark_file` / `favicon_file` | `custom_logo_base64` / `custom_logo_dark_base64` / `custom_favicon_base64` |
| `custom_pages_restart_acknowledged` | An acknowledgement on `enable_custom_pages`, never stored |

#### Adding a group

Describing another group is a Python-only change: add its sections to
`ADMIN_SETTINGS_FIELDS`, extend the parity test to cover the group's panes, and the V2 page
renders the new controls without a front-end change. A field type the renderer does not
implement is caught by `test_v2_admin_field_renderer_coverage.py` rather than silently
drawing nothing.

Groups that still rely on the fallback scan link to the classic admin page for the settings
that need more than a switch. That link is now shown only for those groups, since it is
misleading once a group is fully described.

### Workspace

Personal documents: list, search, tag filter, upload, processing status and delete, against
`/api/documents` and `/api/documents/tags`.

### Personal settings

`/settings`, reached from the account menu, is the V2 home for per-user preferences. It
keeps the classic profile page's six sections — Preferences, Stats, Groups, Public, Feedback
and Violations — but leads with Preferences, since that is why a V2 user opens the page, and
renders the sections as a vertical rail rather than Bootstrap tabs. The active section is in
the query string, so a section can be linked to and survives a reload.

Each tab is registered once in `components/settings/tabs.tsx` and owns its own component,
which is what lets the remaining tabs be built without touching the page shell, the router
or the sidebar.

Two things about `/api/user/settings` shape the client:

- **The route keeps a whitelist.** `allowed_keys` in `route_backend_users.py` silently drops
  anything outside it — the POST still succeeds and the value never arrives, so the
  preference appears to save and resets on the next load. `WRITABLE_USER_SETTING_KEYS` lists
  every key V2 writes and a functional test checks each one against that set.
- **`activeGroupOid` and `activePublicWorkspaceOid` are not settings.** They are popped from
  the payload and routed to `update_active_group_for_user()` /
  `update_active_public_workspace_for_user()`, returning 404 for an unknown workspace and 403
  for one the caller is not in, and they never come back from a later GET. Treating them as
  ordinary settings would make the store believe a save had been lost.

Saves are debounced and merged rather than sitting behind per-section Save buttons: dragging
a slider produces one request, and because the route merges partial updates server-side,
sending pending keys separately would race. A failed save reverts the affected keys to the
last value the server confirmed, since a control showing something that was never stored
gives the user no way to discover the failure.

Tabs whose capability is disabled are hidden rather than shown empty — their endpoints fail
in that state, so they could only ever render an error. The same applies within the
Preferences tab: a section is offered only when its capability is on, **and** only when this
interface actually acts on the setting. Several classic preferences drive V1-only surfaces
(its tutorial buttons, its sidebar hide-control style); offering them here would either do
nothing visible or silently change the other interface, so they stay on the classic page.

Text size is shared. `data-font-size` on `<html>` and its five percentages are taken verbatim
from `static/css/styles.css`, so a size chosen in either interface means the same in both,
and the whole design system scales because it is expressed in rem.

The **Diagrams** and **Charts** sections set the default palette and background for rendered
blocks. They are a starting point rather than a rule: a diagram or chart recoloured inside a
conversation stores its own colours on that message and stops following the default, so
changing it here restyles everything nobody has singled out. Both keys are validated
server-side and reduced to `#rrggbb` before storage — see
[V2 Diagram And Chart Styling](V2_DIAGRAM_AND_CHART_STYLING.md).

Two things are worth noting about the other tabs:

- **Switching the active workspace does not go through `/api/user/settings`.** The dedicated
  `PATCH /api/groups/setActive` and `PATCH /api/public_workspaces/setActive` routes take
  `{ groupId }` and `{ workspaceId }` respectively and say why they refused — 404 for an
  unknown workspace, 403 for one the caller is not a member of. Writing `activeGroupOid` to
  the settings route also works, but it is popped and never returned, so the client would
  have no way to confirm it took.
- **Stats draws its own charts.** The classic page uses Chart.js; here the data is a flat
  series of daily counts, which needs no axis machinery, interaction model or animation
  loop, so it is drawn as plain SVG `<rect>` bars. Adding a charting dependency would grow
  the bundle for every page to draw a shape the browser already has, and browser assets have
  to be locally served in any case. The window is an enum — the route accepts only 7, 30 or
  90 and silently falls back to its default for anything else — so only those are offered.

### Not rebuilt yet

Agents, group workspaces and public workspaces appear in the rail and link through to their
classic pages rather than dead-ending.

## Building

```powershell
cd application/v2_ui
npm install
npm run build
```

The bundle compiles to `application/single_app/static/v2/`, which is gitignored. Container
images build it automatically in a dedicated `v2uibuilder` Docker stage, so Node and
`node_modules` never reach the runtime image.

For local development against a running Flask app:

```powershell
cd application/v2_ui
npm run dev
```

Vite serves on port 5174 and proxies the API paths to `http://127.0.0.1:5000`, which keeps
the browser on one origin so the session cookie and CSRF check behave as they do in
production. Set `SIMPLECHAT_DEV_ORIGIN` to point at a different Flask instance.

## Deployment

### Default: same App Service

No configuration is required. The `v2uibuilder` Docker stage compiles the SPA and the
compiled bundle is copied into the runtime image after the application code. Visiting `/v2`
serves the interface using the session the user already has.

If the bundle is missing — which is the normal state of a fresh local checkout, since the
build output is gitignored — `/v2` returns a 503 page explaining how to build it rather than
a bare 404.

### Optional: separate App Service

Set `deployV2FrontendAppService=true` to provision a standalone Linux Node App Service that
serves the SPA with `pm2 serve --spa`. The module is
`deployers/bicep/modules/v2FrontendAppService.bicep`.

This topology requires cross-origin configuration:

1. Provision the app service:
   `azd env set DEPLOY_V2_FRONTEND_APP_SERVICE true`
2. Set `V2_UI_ALLOWED_ORIGIN` on the API app service to the V2 app's HTTPS origin, emitted
   as the `var_v2WebServiceOrigin` output. That one setting enables CORS for exactly that
   origin, adds it to `CSRF_TRUSTED_ORIGINS`, and switches the session cookie to
   `SameSite=None; Secure`.
3. Add the V2 app's URL as a redirect URI on the Entra app registration.
4. Build the bundle against the API origin, via the `V2_UI_API_BASE` Docker build argument
   or `VITE_API_BASE` when building directly.
5. Uncomment the `v2ui` service block in `deployers/azure.yaml` and run `azd deploy v2ui`.

`V2_UI_ALLOWED_ORIGIN` is unset by default and the CORS block is completely inert without
it, so the default same-origin deployment emits no CORS headers and keeps `SameSite=Lax`.

Setting it changes three things at once, all scoped to that one origin:

- CORS headers are emitted for the exact configured origin, never a wildcard, and `Vary:
  Origin` is set. A wildcard would be incompatible with `Allow-Credentials`, which the
  session cookie requires.
- CORS preflights are answered by an app-level `before_request` handler that runs ahead of
  the authentication guards. Preflights carry no cookies, so without this every
  state-changing call would fail its preflight with a 401.
- The same-origin CSRF guard consults the trusted-origin allowlist before refusing a
  cross-site request. Browsers label requests from a separate front-end origin
  `Sec-Fetch-Site: cross-site`, so without this every mutation would be refused with a 403.
  An untrusted cross-site origin is still refused.

**Caveat:** in this topology the session cookie becomes a third-party cookie. Browsers that
block third-party cookies will break the split deployment. The same-origin default avoids
this entirely and is the recommended layout.

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_ui_spa_route.py` | Shell serving for `/v2` and deep links, `no-store` caching, missing-bundle handling, bundle location |
| `functional_tests/test_v2_api_security.py` | Bootstrap sanitization, swagger decorators, admin role gating, admin nav withheld from non-admins |
| `functional_tests/test_v2_ui_local_assets.py` | No CDN references in source or compiled bundle, shell loads only `/static/` assets, build output gitignored |
| `functional_tests/test_v2_api_payload_shapes.py` | Client field names match what the routes actually return, and bodyless toggle endpoints are called as toggles |
| `functional_tests/test_v2_conversation_drawer.py` | Contents and Documents drawer, conversation details, inline rename |
| `functional_tests/test_v2_message_actions.py` | Per-message actions, the two-step retry and edit contracts, attempt switching by refetch |
| `functional_tests/test_v2_citations.py` | Citation marker grammar parity with `chat-citations.js`, the four link kinds |
| `functional_tests/test_v2_enhanced_citations.py` | Extension-to-viewer map parity with `getFileType`, the permissive metadata gate, `X-Sub-PDF-Page` handling, timestamp conversion, fallback on every failure |
| `functional_tests/test_v2_research_voice.py` | Deep research's two fields, URL access, per-model reasoning effort, voice in and out |
| `functional_tests/test_v2_reasoning_effort_persistence.py` | The reasoning level and the model selection are stored in keys the settings route accepts, keyed the way the classic interface keys them, derived per model rather than remembered, and `none` never sent |
| `functional_tests/test_v2_dropdown_placement.py` | Composer pickers flip above the trigger when the bottom-anchored composer leaves no room below, and clamp their height to the viewport |
| `functional_tests/test_v2_chat_phase1_fixes.py` | Exports send JSON rather than a form, email has its own path, images resolve from `content`, attempts are one-based, the title badge comes from conversation metadata, `agent_info` is an object, newlines match across roles, and failures are announced |
| `functional_tests/test_v2_message_inspector.py` | Role-dependent metadata shape, reasoning fetched per message, shared renderer for live and historical reasoning, citation URL scheme checking, enabled-versus-used capability reporting |
| `functional_tests/test_v2_message_masking.py` | All mask actions, selection carries text not just offsets, rejection is explained, masked text never reaches the DOM, masks applied before citation parsing, attribution, permission rule, popup stays on screen |
| `functional_tests/test_v2_conversation_details_and_gating.py` | Tags split by category, source documents paged with the citation-tracking note, summary generated on demand, URL access and deep research gated on what is typed, image generation exclusivity, chat width persisted, unsafe tag values not linked |
| `functional_tests/test_v2_model_identity_and_scope.py` | The whole model identity is sent and the picker keys on `selection_key`, the document scope is computed rather than hardcoded, and workspace ids travel with it |
| `functional_tests/test_v2_rich_rendering.py` | Browser libraries vendored into the repository with their licences and pinned versions, no equivalent npm dependency, KaTeX fonts complete and locally resolvable, a sanitizer boundary at every HTML sink and nowhere else, KaTeX `trust: false`, mermaid strict with no autostart or icon packs, single `$` not treated as maths, fence wiring and chart language parity with the backend, charts copied as data, CSP unchanged |
| `functional_tests/test_v2_generated_image_lightbox.py` | The image thumbnail opens a dialog rather than a new tab, the dialog is dismissable and manages focus, every source kind is handled by download and open-in-new-tab, and `window.open` is not given `noopener` |
| `functional_tests/test_v2_chat_notices.py` | Both notices resolved server-side from the shared helpers, the web search notice's three-key condition including consent, all four AI notice frequencies, dismissal only after a successful write, session keys shared with the classic interface, no hardcoded disclaimer, notice text escaped |
| `functional_tests/test_v2_conversation_deep_link.py` | Both parameter spellings read and only the canonical one written, the incoming link captured before any effect can strip it, the URL replaced rather than pushed, a dead link reported instead of stranded, a list row backfilled behind the stale-response guard, and the classic handover carrying the conversation |
| `functional_tests/test_v2_conversation_export.py` | The wizard reuses the existing export endpoints and sends only fields the route reads, the summary model carries all four identity fields, JSON exports skip rasterizing, diagrams render through the shared hardened runtime, a percentage width is not mistaken for a size, the rail's selection survives rows being removed, and all three entry points open the wizard |
| `functional_tests/test_csrf_state_changing_route_guard.py` | Cross-site mutations require an explicitly trusted origin; CORS preflights answered before authentication and never wildcarded |
| `functional_tests/route_tests/` | Blueprint policy classification for `frontend_v2`, `backend_v2`, `backend_v2_admin` |

The SPA route tests stub the Azure-dependent imports so the real route functions run against
a real Flask test client; `config.py` builds live Azure clients at import time and cannot be
imported in a test environment.

## Known limitations

- **Seeking in long media waits for the whole file.**
  `serve_enhanced_citation_content` advertises `Accept-Ranges: bytes` but returns a
  complete body through a plain Flask `Response`; nothing calls `make_conditional`, so a
  `206 Partial Content` is never produced. A video citation therefore downloads the file
  before it can seek. This is pre-existing server behaviour that the V2 client cannot fix,
  and it affects the classic UI identically.
- **Headless browsers cannot render the PDF viewer.** Headless Chromium ships no PDF
  plugin, so a `blob:` PDF frame is blank there regardless of correctness. PDF rendering
  was verified in a headed browser instead; automated coverage asserts the request, the
  `X-Sub-PDF-Page` handling and the frame wiring rather than the pixels.
- **Video codec support is the browser's, not the application's.** A real H.264/AAC clip
  was played end to end against the viewer, confirming decode, the seek to the cited
  offset, and streaming from the endpoint rather than a blob. What a given browser will
  decode is still its own affair, so an exotic codec in an uploaded file may fail; that
  path falls back to the cited passage with a visible notice.
- **Voice and speech could not be verified end to end.** Voice input needs a real
  microphone and speech output needs Azure Speech configured in the tenant. Both were
  verified structurally — correct controls, correct gating, correct requests and payloads —
  but neither actual capture nor actual playback has been exercised.
- Collaboration, tabular runs, workflow activity, scope lock and the chat tutorial are not
  wired.
- Stream reattachment (`/api/chat/stream/reattach/{id}`) is not used; a dropped connection
  surfaces an error rather than silently resuming.
- Admin settings edits boolean capabilities only.
- Group and public workspaces are not rebuilt.
- The bundle is ~711 KB raw / ~213 KB gzipped, dominated by React, the markdown pipeline
  and syntax highlighting grammars. It is not code-split, because the chat page needs
  nearly all of it on first paint.
