# V2 Interface Selection Prerequisites

**Implemented in version: 0.261.445**, recorded in `application/single_app/config.py`.

## Overview

SimpleChat serves two interfaces from one backend: the classic server-rendered pages and the
React V2 interface under `/v2`. An administrator will eventually choose which of the two people
use. Choosing is only safe when three things are already true: every link the product has ever
written (a notification, an approval email, a bookmark, a Microsoft 365 sign-in return) still
arrives at a page, a person can always get back to the classic page they were on, and a
deployment that has no V2 build keeps working instead of sending everyone into an error.

This change builds those prerequisites and nothing else. **It changes nothing for anyone today**:
`functions_ui_mode.get_ui_mode()` still answers classic for every request, and every rule below
starts from the modern interface being selected. The interface selector (a later plan) replaces the
body of that one function.

| Prerequisite | What it does | Where |
| --- | --- | --- |
| Classic to V2 redirect | A `GET` of a classic page is answered with a `302` to its V2 counterpart, with the query string and mapped parameters carried across. | `functions_ui_redirect.py`, one hook in `app.py` |
| V2 fragment translation | A browser keeps `#fragment` across a redirect, so V2 turns `/v2/workspace#documents-tab` into `/v2/workspace/documents`. | `lib/classicLinks.ts`, `lib/useClassicFragmentTranslation.ts` |
| Back to classic UI | The account menu opens the classic version of the page on screen, not only the classic chat page, and carries `ui=classic`. | `lib/classicLinks.ts`, `components/layout/Sidebar.tsx` |
| Return URLs | Every address the server builds to send a person back into the application was checked; the redirect covers all of them, so no URL helper was added. | [Return URLs](#return-urls) |
| Bundle fallback | One shared test, "the modern interface is selected and the V2 bundle exists", used by the redirect and the landing page. A missing bundle means classic and one throttled `[UI_MODE]` warning, never a 503 loop. | `functions_ui_pages.py` |
| Registry finalisation | The page registry has no `gap` rows left and a guard that keeps it so. | `ui_route_map.json`, `test_ui_route_parity_registry.py` |

## Dependencies

- `application/single_app/functions_ui_mode.py`: the seam that decides classic or modern.
- `application/single_app/ui_route_map.json` and `ui_routing.py`: the page registry and its
  resolvers (`V2_CLASSIC_PAGE_PARITY.md`). The redirect and the V2 links are built on them.
- `application/single_app/functions_ui_pages.py`: `has_app_user_role` and the shared bundle test.
- `application/single_app/route_frontend_v2.py`: `is_v2_bundle_available`, and the V2 shell routes.
- `application/single_app/functions_custom_pages.py`: which custom pages V2 can host
  (`V2_CUSTOM_PAGES.md`).
- No new package, no new route, no new setting and no browser asset.

## Technical specifications

### The modes and the seam

`functions_ui_mode.get_ui_mode(settings=None, user_settings=None)` returns `classic` or `modern`.
Today the body is `return UI_MODE_CLASSIC`. Everything in this change asks it, and nothing decides
for itself:

- the redirect hook asks it for a classic page `GET`;
- `index()` asks `is_modern_ui_available()`, which asks it and then checks the bundle;
- `render_page` asks it which template to render.

`settings` and `user_settings` are already threaded through every caller, so the selector can read
an administrator default and a per-user choice without touching a caller. The tests replace the
mode with `modern` to prove the rules.

### The redirect

`functions_ui_redirect.decide_ui_redirect(...)` is a pure function: it takes what the request and
the session say and answers with a same-site `Location` or `None`. `evaluate_ui_redirect(...)`
answers the same with the reason, which is what the tests read. `redirect_classic_page_to_modern_ui`
is the thin Flask wrapper the hook calls. It answers `302` (the mode is per user and can change, so
no client or cache may remember it) with `Cache-Control: no-store`, and any error inside it is logged
(`[UI_MODE]`) and leaves the request to be served as it was.

A request is redirected only when all of these hold, checked cheapest first so an API call or a static
file costs nothing:

| Rule | Why |
| --- | --- |
| The method is `GET` or `HEAD`. | Anything else is a form post or an API call. |
| The path is not `/v2`, `/v2/*`, `/api/*`, `/external/*`, `/static/*`, `/custom/assets/*` or `/.well-known/*`. | Those hold no classic page, and a redirect target is therefore never redirected again: a loop is impossible. |
| The request is a person opening a page in the window: not a frame (`Sec-Fetch-Dest` of `iframe`, `frame`, `embed` or `object`), not a fetch or prefetch (`Sec-Fetch-Dest` other than `document`, `Sec-Fetch-Mode` other than `navigate`), not `X-Requested-With: XMLHttpRequest`, and the `Accept` header allows HTML. | A classic page linked from inside a V2 custom page frame must not load V2 inside V2. A client that sends none of these headers (curl) is treated as opening a page. |
| The query does not carry `ui=classic`. | The escape pair ([below](#the-escape-pair-uiclassic)). |
| The registry has a V2 page for the path (`native`, `alias` or `partial`). | Sign-in, sign-out, OAuth callbacks, form handlers, developer tools and anything unknown stay where they are. A custom page's own frame (`?embed=1`) is never redirected, because V2 loads it. |
| The modern interface is selected. | Nothing is redirected in the classic interface. |
| The visitor is signed in with the `User` or `Admin` role. | `/v2` answers 403 without the role. A signed-out visitor has no V2 page to be sent to, and `home` and `terms-of-use` are `partial` rows because their signed-out and pre-sign-in states stay server-rendered. |
| The V2 bundle exists ([Bundle fallback](#bundle-fallback)). | Without it `/v2` answers 503. |
| For `/custom/<slug>` and `/custom/<slug>.html`: the page is in the visitor's navigation, embeddable, does not ask to open in its own tab, and is not open to any signed-in user. | A page open to any signed-in user exists for people without the application role, so it stays classic and chrome-less. |

The answer is always a path under `/v2` built from registry data and validated path segments, never
anything the caller supplied. A path or query that tries to smuggle a host (`//host`, `/\host`,
`/%2e%2e//host`, `https://host`), a header break or an oversized value gets no redirect. Only the
query keys a registry row maps cross over; the rest are dropped.

| Classic URL | In the modern interface |
| --- | --- |
| `/chats?conversationId=abc&utm_source=mail` | `302` to `/v2/chat?conversationId=abc` |
| `/profile?tab=feedback` | `302` to `/v2/settings?tab=feedback` |
| `/group_workspaces` | `302` to `/v2/groups` |
| `/workspace?feature_action=file_sync` | `302` to `/v2/workspace/sync` |
| `/approvals?m365_approval=a1` | `302` to `/v2/approvals?m365_approval=a1` |
| `/custom/handbook` | `302` to `/v2/custom/handbook` when V2 can host the page |
| `/` | `302` to `/v2` for a signed-in application user (`index()` does this itself) |
| `/terms-of-use?next=%2Fchats` | `302` to `/v2/terms-of-use?next=%2Fchats` |
| `/login`, `/logout`, `/getAToken`, a form post, `/api/...`, `/static/...`, `/v2/...` | untouched |
| `/chats?ui=classic`, a request from a frame, a fetch, or a signed-out visitor | untouched |

#### Where the hook sits

Flask runs app-level `before_request` hooks in registration order, and the first one that returns a
response ends the request. `app.py` registers them in this order:

1. `ensure_application_initialized`
2. `reload_kernel_if_needed`
3. `answer_cors_preflight_for_allowed_origins` (answers `OPTIONS` only)
4. `enforce_same_origin_for_state_changing_requests` (answers `POST`, `PUT`, `PATCH` and `DELETE` only)
5. **`redirect_classic_pages_to_modern_ui`** (new)
6. `enforce_terms_of_use`
7. `enforce_idle_session_timeout`

The route's own guards (`login_required`, `user_required`, the blueprint `before_request` guards and
the access restriction check they make) run after all of them.

The hook sits ahead of the Terms of Use gate on purpose. The gate sends a classic path to the classic
`/terms-of-use?next=...` interstitial and a `/v2` path to `/v2/terms-of-use`. Were the redirect to run
after it, a modern-interface user who still has to accept the terms and opens `/chats?conversationId=abc`
would meet the classic interstitial first. Running the redirect first turns the classic URL into a V2 URL,
so the gate then sends the person to the V2 terms page; the same holds for the access restriction check
(`/v2/access-restricted`). An expired idle session is handled by the idle-timeout hook on the V2 request
that follows. It sits after the CORS and same-origin hooks, which only ever answer other methods, and it
never touches a method other than `GET` or `HEAD`. The decision costs a request nothing until it is a
candidate, and settings are read lazily, only for a classic page `GET` the registry maps.

### The escape pair `ui=classic`

"Back to classic UI" in V2 appends `ui=classic` to the classic address. In the modern interface the
redirect and the landing page both skip a request whose query's first `ui` value is `classic` (case
insensitive, whitespace trimmed, the key matched exactly). Its semantics:

- **Per request only.** It sets no cookie and no session flag, and it is not copied into any V2 address
  or redirect. The classic page it opens shows classic navigation whose links do not carry it, so the
  first click on one of them in the modern interface is redirected to V2. It is a way to look at one
  classic page, not a way to stay in classic.
- **Harmless in the classic interface**, where nothing reads it.
- **Available to anyone who types it.** It needs no role and no setting, so it also lets a visitor opt out
  of the modern interface for a single page. Whether that is acceptable, and who may use it, is a decision
  for the interface selector plan ([What the selector plan must still do](#what-the-selector-plan-must-still-do)).
- `index()` honours it as well, so the classic landing page can be reached with `/?ui=classic`.

### What V2 does with the address

**Fragment translation.** A server never sees the part of a URL after `#`, but a browser keeps it across
a redirect whose `Location` has none (the Fetch standard; Chromium does, and `ui_tests/test_v2_classic_links.py`
proves it against a real local server). So `/workspace#documents-tab` arrives as `/v2/workspace#documents-tab`.
`useClassicFragmentTranslation` is mounted once in `App.tsx`. When the address carries a fragment that the
registry lists in a row's `hash_map` and the page is that row's own route, it replaces the address (a
`replace`, not a new history entry, and the fragment is dropped so it runs once) with the route the registry
names:

| Arrives as | Becomes |
| --- | --- |
| `/v2/workspace#documents-tab` | `/v2/workspace/documents` |
| `/v2/workspace#plugins-tab` | `/v2/workspace/actions` |
| `/v2/settings?tab=preferences#m365-chat-connection` | `/v2/settings?tab=preferences&section=m365-chat-connection` |
| `/v2/approvals#agent-template-approvals` | `/v2/approvals/agent-templates` |
| `/v2/chat#chatbox`, any fragment the registry does not list | left exactly as it is |

When the query string and the fragment both name a section, the query string wins, as in the server resolver.

**Back to classic UI.** The account menu's link is `classicBackHref(pathname, search, hash, activeConversationId)`:

- On the chat page it is the classic chat page carrying the open conversation, as it always was.
- On any other page with a classic counterpart it is that counterpart: a settings tab opens `/profile?tab=...`
  (`/v2/settings?tab=feedback` opens `/profile?tab=feedback`), `/v2/groups/<id>/members` opens `/groups/<id>`,
  `/v2/notifications` opens `/notifications`, a workspace section opens `/workspace#<tab>`. The V2 group
  page `/v2/groups/<id>` itself opens `/group_workspaces`, because V2 merges the classic group workspace and
  manage pages and the registry says the workspace page answers for it.
- A page with none (the group directory) falls back to the classic chat page, as before.
- Every address carries `ui=classic`. `target` and the accessible name are unchanged. `withClassicEscape` only
  extends a same-site absolute path (anything else becomes the classic chat page), which is why it and
  `classicBackHref` are on the XSS checker's reviewed same-origin URL builder list.

`classicHrefFor` is the TypeScript twin of `ui_routing.resolve_classic_target`, and
`functional_tests/test_v2_classic_links.py` holds the two to the same answers for every row of the registry,
its subroutes, query values, fragments and hostile addresses. The two other links back to classic that V2
owns, the boot error page and the missing-bundle page (`route_frontend_v2.py`), carry `ui=classic` too.

**V2 hand-offs that do not carry the pair yet.** A few V2 places send a reader to a classic address with a
plain link. In the modern interface the redirect sends that reader straight back to V2, so each needs
`withClassicEscape(...)` from `lib/classicLinks.ts` where it really means "the classic page", or its target
retired when the V2 page replaces it:

- `lib/workspaces.ts` (`classicHref` of the groups and public workspaces cards, `/profile?tab=groups` and
  `/profile?tab=public-workspaces`), which the redirect already maps to the V2 Settings tabs;
- the classic fallbacks of `lib/notificationNavigation.ts`, `lib/notificationLinks.ts` and
  `lib/latestFeatureShortcuts.ts`, and the "opens in the classic interface" anchors in
  `components/support/SupportAnnouncements.tsx`, for pages that are not in the registry.

The Admin Settings hand-offs have since been fixed: `safeClassicAdminTabHref` in `lib/adminOperations.ts` now
wraps its `/admin/settings#<tab>` address with `withClassicEscape`, so every link from V2 Admin Settings to the
classic page carries the pair (see [V2 Admin Section Links](V2_ADMIN_SECTION_LINKS.md#the-classic-escape-pair)).

### Return URLs

The server writes classic addresses in several places. Each was evaluated for whether the redirect already
covers it or a helper that builds the V2 address is needed. **None needed a helper**, so no `page_url()` was
added: a helper is warranted only where a redirect cannot carry the context, and every case below carries all
the context V2 reads.

| URL | Built in | Decision and evidence |
| --- | --- | --- |
| `CLASSIC_CHAT_CONNECTION_URL`, `CLASSIC_CHAT_CONNECTED_URL` (`/profile?tab=settings[&m365_chat_connection=connected]#m365-chat-connection`) | `route_backend_m365.py` | Covered. The redirect sends `/profile?tab=settings` to `/v2/settings?tab=preferences`, and V2 rewrites the fragment to `&section=m365-chat-connection`, which `SettingsPage.tsx` reads. The connected flag is dropped on purpose: V2 reads the saved connection from its API, so the connected state does not need the address. |
| `CLASSIC_WORKFLOW_CONNECTION_URL`, `CLASSIC_WORKFLOW_CONNECTED_URL` (`...#m365-connection-status`) | `route_backend_m365.py` | Covered the same way, ending on `section=m365-workflow-connection`. |
| `CLASSIC_CHATS_URL` (`/chats`) | `route_backend_m365.py` | Covered: `/v2/chat`. |
| The chat sign-in return `/chats?conversationId=...&m365_request_id=...&m365_auth=connected` | `_complete_chat_connection` | Covered for what V2 reads: `/v2/chat?conversationId=...`. V2 reads neither `m365_request_id` nor `m365_auth` from the address (`test_ui_return_urls.py` keeps it so): it signs in from a popup and resumes the paused request in the page through `/api/m365/requests/<id>/resume`, so there is nothing to carry. The registry's `chat` notes record it. |
| `continue_url` of the Microsoft 365 popup result page | `_connection_result_page` | The same `CLASSIC_*` constants, covered the same way. |
| `TEAMS_SUCCESS_REDIRECT_PATH` (default `/chats`) | `config.py`, Teams sign-in | A Teams sign-in builds its session user from claims with no `roles`, so it is not an application user as far as the redirect is concerned and is never redirected (`/v2` would answer 403 for it, as the classic pages do). Nothing to change; the test fails if Teams sessions ever gain roles, so the question is asked again. Not verified inside a Teams tab. |
| The login flows' `redirect(url_for('public_app.index'))` | `route_frontend_authentication.py` | Covered by `index()`: a signed-in application user goes to `/v2` in the modern interface; everyone else gets the modern landing page. |
| `HOME_REDIRECT_URL` and the Front Door URLs | `route_frontend_authentication.py` | External to the application. Left alone: the Front Door home resolves to `/` of the application. |
| The Terms of Use return path (`next`) | `app.py`, `route_frontend_terms_of_use.py`, `route_backend_v2.py` | Covered. `next` crosses to `/v2/terms-of-use` as a same-site path only (`local_path`); the server validates it again (`normalize_terms_of_use_return_path`); after acceptance V2 follows that classic path and the redirect lands it on V2. |

One known limitation: a full-page chat sign-in that was started from a classic chat page (reached with
`ui=classic` in the modern interface) returns to V2 chat without resuming the request on its own. The
paused request stays under Approvals, Waiting requests, where V2 resumes it.

### Bundle fallback

`/v2` answers 503 when `static/v2/index.html` is not built. A deployment that selected the modern interface
but shipped no bundle must therefore keep serving classic pages. `functions_ui_pages.is_modern_ui_available()`
is the one test (modern mode **and** bundle present) and `is_v2_bundle_ready()` its bundle half. The redirect
hook and `index()` both use it, so they cannot disagree. A missing bundle means classic, never a 503 loop, and
it writes one `[UI_MODE]` warning per process, then at most once an hour, only when the missing bundle is the
reason a request that the modern interface would have taken stays classic (see `docs/reference/logging-tags.md`).
The bundle is built by `npm run build` in `application/v2_ui`; container images do this automatically.

### Registry finalisation

The rows whose V2 work landed were flipped after each was verified in code: `notifications`, `workflow-activity`,
`custom-page` and `custom-page-html` (native, keeping `classic_only_query` so V2's own frame is never redirected),
`chat` (scope lock editing and the generated artifact actions), `profile` (Refresh photo), `control-center` (the
refresh controls) and `acceptable-use-policy` (now `standalone`: it has a modern variant but no V2 page).
The registry has no `gap` rows. `test_ui_route_parity_registry.py` fails on any `gap` row and requires every `partial`
row to be listed in `EXPECTED_PARTIAL_KEYS`. `home` and `terms-of-use` are partial by design (the signed-out and
pre-sign-in states stay server-rendered, and the redirect only moves signed-in application users); the workspace and
admin rows are listed as unfinished until their work lands and the list shrinks.

### Files

| File | Role |
| --- | --- |
| `application/single_app/functions_ui_redirect.py` | The decision, the escape test and the Flask wrapper. |
| `application/single_app/app.py` | The thin `redirect_classic_pages_to_modern_ui` hook with the placement comment, and `index()` using the shared test and the escape pair. |
| `application/single_app/functions_ui_pages.py` | `is_modern_ui_available`, `is_v2_bundle_ready` and the throttled `[UI_MODE]` warning. |
| `application/single_app/ui_routing.py` | `resolve_v2_target` now also returns the classic path parameters (`params`). |
| `application/single_app/route_frontend_v2.py` | The missing-bundle page links to `/chats?ui=classic`. |
| `application/v2_ui/src/lib/classicLinks.ts` | `classicHrefFor`, `withClassicEscape`, `classicBackHref`, `translateClassicFragment`. |
| `application/v2_ui/src/lib/useClassicFragmentTranslation.ts` | The effect that applies it, mounted once in `App.tsx`. |
| `application/v2_ui/src/components/layout/Sidebar.tsx` | "Back to classic UI" uses `classicBackHref`. |
| `scripts/check_xss_sinks.py` | `classicBackHref` and `withClassicEscape` join the reviewed same-origin URL builders. |

## What the selector plan must still do

Nothing selects the modern interface yet. These decisions were deliberately left to that plan:

- **Where the administrator default lives.** A setting in the application settings and an Admin Settings tab
  for it (with its `docs/admin` page), read by `get_ui_mode(settings)`. The settings the redirect hook receives are
  the request-cached ones, so reading the default costs nothing extra; keep it that way.
- **The per-user preference.** Where it is stored (the user settings that `get_ui_mode(settings, user_settings)`
  already receives), how a person changes it in both interfaces, and whether an administrator can lock it.
  The hook runs for every classic page `GET` the registry maps, so `get_ui_mode` must stay cheap for them.
- **Precedence.** Per-request escape pair, administrator lock, user preference, administrator default: in what
  order, and whether the escape pair is still honoured when an administrator has locked the modern interface (today
  it always is, because the hook knows nothing about a lock). If it is not, the account menu link must be hidden
  too, through the bootstrap payload.
- **Who may use the escape hatch, and whether it sticks.** Today anyone, for one page. Staying in classic needs a
  stored preference or a session flag. Decide which, who may set it, and what happens when it conflicts with a lock.
- **Caching and CDNs.** The redirect is `302` with `Cache-Control: no-store`. A CDN or Front Door rule must not cache
  the classic pages or the redirects across users, because the interface now varies per user; `ui=classic` URLs are
  distinct cache keys from the plain ones.
- **Teams.** Whether Teams tabs follow the redirect: that needs roles in the Teams session and `/v2` allowed by the
  Teams frame and content security policy settings.
- **A warning when the bundle is missing.** The selector setting should say so when `is_v2_bundle_ready()` is false,
  as the log does.
- **`index()` and the hook.** `index()` honours the escape pair but does not apply the frame, fetch and `Accept`
  rules the hook does. Fold the two into one decision when the selector lands.
- **The V2 hand-offs** listed above, so a "classic" link never lands back in V2.
- **Warning administrators** that classic cannot show the V2-only capabilities below.

### V2-only capabilities

Classic cannot show or edit these. An administrator who keeps the classic interface as the default, or lets people
choose it, should be told. Each is verified in code:

| Capability | What classic does | Evidence |
| --- | --- | --- |
| Chat orchestration: the orchestration mode in the composer, plan review and editing, runs and approval gates | Nothing. The setting says "Available in the V2 interface only." | `templates/admin/_panes/chat-orchestration.html`; `components/chat/Orchestration*.tsx` (`OrchestrationPlanEditor.tsx`, `OrchestrationRunView.tsx`) |
| V2 Auto model routing | Classic chat chooses the model manually; favourites and priorities guide V2 Auto only. | `templates/admin/_panes/model-catalog.html` |
| Merge files (combine CSV or Excel files) | Lists a workflow's Merge task but refuses to edit it. | `templates/admin/_panes/actions.html`; `static/js/workspace/workspace_workflows.js` (`workflowNativeEditorReason`) |
| Workflow editing beyond the simple form: advanced data flow (a definition version other than 1, or a `flow`), calendar schedules, chat capability and results delivery settings, saved chat plans | Refuses to edit and says "Open V2 to edit it"; Run and Cancel remain. Durable progress and approval gates are reviewed in V2. | `static/js/workspace/workspace_workflows.js` |
| AI assist for agents, actions and workflows: plain-language drafts reviewed before saving | Nothing. | `templates/admin/_panes/agents.html`, `workflow.html` |
| AI analysis and triage in the Review center | Nothing. | `templates/admin/_panes/access-roles.html` |
| Editing a chart or diagram in a reply | Reads the edited version but cannot edit. | `static/js/chat/chat-block-revisions.js`, `chat-inline-diagrams.js`, `chat-inline-charts.js` |
| The `control_center` action type | Cannot be created in classic. | `static/js/plugin_modal_stepper.js` |

## Usage

There is nothing to enable. While `get_ui_mode()` answers classic, the redirect, the escape pair and the bundle
warning are never reached, and V2's "Back to classic UI" simply opens the classic page with `?ui=classic` appended,
which classic ignores.

To see the redirect in a development checkout, make `get_ui_mode` return `UI_MODE_MODERN`, build the bundle, and sign
in as a user with the `User` role. That is a development aid, not a supported setting. Open `/chats?conversationId=abc`
to arrive at `/v2/chat?conversationId=abc`, then use the account menu's **Back to classic UI** to return.

## Testing and validation

- `functional_tests/test_ui_redirect_edge.py` covers the decision for every row of the registry (modern redirects to a
  path V2 declares, classic does nothing), loop impossibility, the escape pair, methods, API, static and V2 paths,
  fetches, frames and `Accept`, signed-out and role-less visitors, the missing bundle and its single throttled warning,
  custom page rules, hostile paths and queries, and, in a fresh process, the real web application: the hook order, the
  documented examples, classic mode untouched, the terms gate placement and a spoofed `Host`.
- `functional_tests/test_ui_return_urls.py` pins the return URL evidence above.
- `functional_tests/test_v2_classic_links.py` runs `classicLinks.ts` under node against cases produced by the server's
  resolvers from the real registry, and checks the wiring.
- `ui_tests/test_v2_classic_links.py` drives the real rail, account menu and fragment translation in Chromium on desktop
  and a 390 px phone: fragments become routes in place with no extra history entry, a real `302` keeps the fragment,
  and the menu link follows the page on screen.
- `functional_tests/test_ui_route_parity_registry.py` guards the registry (no `gap` rows, an explicit `partial` list).
- `functional_tests/test_modern_standalone_pages.py` covers `index()` with the shared test and the escape pair.

Results at version 0.261.445: `test_ui_redirect_edge.py` passes 157 checks (the fresh-process probe of the real
web application takes about 25 seconds), `test_ui_return_urls.py` 8, `test_v2_classic_links.py` 9 (which run 18
TypeScript checks under node, including every row of the registry against the server's resolvers),
`test_ui_route_parity_registry.py` 45, `test_modern_standalone_pages.py` 69, and `ui_tests/test_v2_classic_links.py`
30 in Chromium (desktop and 390 px). `npm --prefix application\v2_ui run typecheck` is clean, and the XSS sink check
passes on every file this change touches.

Commands:

```powershell
python -m pytest functional_tests\test_ui_redirect_edge.py functional_tests\test_ui_return_urls.py functional_tests\test_v2_classic_links.py functional_tests\test_ui_route_parity_registry.py functional_tests\test_modern_standalone_pages.py -q -p no:cacheprovider
python -m pytest ui_tests\test_v2_classic_links.py -q -p no:cacheprovider
python scripts\build_ui_route_map.py --check
```

## Known limitations

- Nothing selects the modern interface, so none of this has run against a real selected deployment.
- The escape pair is per request and open to anyone; see above.
- A Teams tab is never redirected, and this was not exercised inside Teams.
- A full-page chat sign-in started from classic in the modern interface does not resume on its own.
- `index()` does not apply the frame, fetch and `Accept` rules.
- Some V2 hand-offs to classic pages do not carry `ui=classic` yet; the redirect sends a reader back to V2 from them.
- Reverse resolution is best effort (`V2_CLASSIC_PAGE_PARITY.md`): `/v2/groups/<id>` opens the classic group workspace
  page, which uses the active group rather than the group in the address.
