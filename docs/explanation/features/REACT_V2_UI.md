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
| lowlight | Code block syntax highlighting |
| lucide-react | Icons |

All dependencies are bundled locally by Vite and served from `/static/v2/`. Nothing is
loaded from a CDN, so the `default-src 'self'` Content-Security-Policy is unchanged.

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
| `settings` | Settings passed through `sanitize_settings_for_user()` |

Settings returned here are always sanitized. The logo is reported as a URL rather than the
stored base64 payload, because sanitization strips any key containing `base64` and the
images are already served as static files.

### `GET` and `PATCH /api/v2/admin/settings`

Blueprint `backend_v2_admin` — `login_required`, `admin_required`.

Returns the **raw** settings document plus the admin navigation. Admin settings are
deliberately not sanitized: sanitization removes the keys, secrets and endpoint
configuration that an administrator is there to manage. Access is gated on the Admin role
at both the blueprint guard and the route decorator.

`PATCH` applies a partial update, so the V2 admin surface can toggle a single capability
without posting the entire settings form.

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
paint, which avoids a light flash for dark-mode users, and is persisted to `localStorage`.
The toggle lives at the bottom of the left rail.

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
- Citations rendered as inline chips that open either the cited source itself — the PDF
  page, image, media clip, spreadsheet or Visio page — or the passage that was extracted
  from it

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
- **Reasoning effort is per model family.** `gpt-4o` supports none, `gpt-5-pro` only
  `high`, the 5.1 series skips `low`, and the o-series offers low/medium/high. The control
  is hidden entirely when a model offers no choice.
- **Citation markers** follow the grammar in `chat-citations.js`; a functional test asserts
  the two patterns stay identical so markers never render as raw text.

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
pane of sections, and a search box that matches across every section, tab, group and
capability key at once. Pressing `/` focuses search from anywhere on the page. Typing
`retention` or `data lifecycle` both find the retention settings.

The structure still comes from `admin_settings_nav.py`, so it cannot drift from the classic
page. Capability keys are associated with sections by matching word stems between the key
and the section id; anything that cannot be matched is collected under "Other capabilities"
rather than hidden, because a silently missing toggle is worse than a misfiled one.

Toggles save individually via `PATCH`, with the switch rolling back if the request fails.
Settings that need more than a switch — endpoints, keys, prompts, connection tests — remain
on the classic admin page, which is linked from the bottom of the V2 page.

### Workspace

Personal documents: list, search, tag filter, upload, processing status and delete, against
`/api/documents` and `/api/documents/tags`.

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
| `functional_tests/test_v2_dropdown_placement.py` | Composer pickers flip above the trigger when the bottom-anchored composer leaves no room below, and clamp their height to the viewport |
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
- **Video playback has only been verified structurally.** Element wiring, the seek offset
  and the fallback path are covered, but no sample video was played end to end, so
  codec-dependent behaviour in a real deployment is unproven.
- **Voice and speech could not be verified end to end.** Voice input needs a real
  microphone and speech output needs Azure Speech configured in the tenant. Both were
  verified structurally — correct controls, correct gating, correct requests and payloads —
  but neither actual capture nor actual playback has been exercised.
- Collaboration, tabular runs, conversation export, workflow activity, scope lock and the
  chat tutorial are not wired.
- Stream reattachment (`/api/chat/stream/reattach/{id}`) is not used; a dropped connection
  surfaces an error rather than silently resuming.
- Admin settings edits boolean capabilities only.
- Group and public workspaces are not rebuilt.
- The bundle is ~530 KB raw / ~162 KB gzipped, dominated by React, the markdown pipeline
  and syntax highlighting grammars. It is not code-split, because the chat page needs
  nearly all of it on first paint.
