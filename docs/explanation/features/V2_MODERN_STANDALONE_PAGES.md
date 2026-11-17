# V2 Modern Standalone Pages

**Implemented in version: 0.261.445**

## Overview

A few pages have to stay server-rendered even once SimpleChat can be served in the modern
(V2) interface, because the people who see them cannot use V2. V2 needs a signed-in
application user, and these pages are for everyone else:

- the home page for a visitor who is **not signed in**,
- the home page for a user who is **signed in without an application role**,
- the **Acceptable Use Policy** page,
- the **rate limited (429)** page, and
- the **Microsoft 365 sign-in result** page.

Until now each of them wore the classic chrome: they extended `base.html`, so a user in an
otherwise modern product saw the classic navigation bar around them. This feature adds a
modern variant of each page, built on one small standalone layout that carries the V2 look
(glass surfaces, V2 colours and type, light and dark) with no navigation and no script
bundle, and a single helper that chooses between the classic and the modern template.

**The modern variants are inactive.** The helper asks `functions_ui_mode.get_ui_mode()`,
which answers classic for everyone until the interface selector exists. Nothing changes
for any user today, and the classic templates are unchanged.

## Dependencies

- `functions_ui_mode.get_ui_mode` and `is_modern_ui`, the one seam that decides which
  interface a request is served (see [The interface seam](#the-interface-seam)).
- `functions_ui_pages.is_modern_ui_available`, which the home page and the classic to V2 redirect
  share: the modern interface is selected and `route_frontend_v2.is_v2_bundle_available` says the
  compiled bundle exists, so neither sends a signed-in user to `/v2` when the bundle is missing.
- The `markdown` and `nl2br` Jinja filters registered in `app.py`, and
  `markdown_filter`'s bleach sanitising.
- `functions_authentication.get_signed_in_account_display`, for the signed-in account block.
- `static/js/profile/profile-m365-connection-result.js`, unchanged, for the Microsoft 365
  result page.

No new package, no new route and no new setting.

## Technical specifications

### The interface seam

`functions_ui_mode.get_ui_mode(settings=None, user_settings=None)` returns `classic` or
`modern`. Today the body is `return UI_MODE_CLASSIC`; the interface selector replaces it
without touching any caller, which is why code that has to choose between a classic and a
modern template asks there instead of deciding for itself.

`functions_ui_pages.py` is the choosing code for page templates:

| Function | Purpose |
|---|---|
| `render_page(classic_template, modern_template, *, settings=None, user_settings=None, **context)` | Renders the template for the interface the request is served, with the same context either way. `settings` and `user_settings` go to `get_ui_mode` only and are never passed to the template, so raw settings cannot reach a browser through this helper. A mode it does not recognise renders the classic page. |
| `choose_page_template(classic_template, modern_template, settings=None, user_settings=None)` | The template name, without rendering. |
| `has_app_user_role(user)` | True when the signed-in user holds `User` or `Admin`: the test `user_required` applies and the classic home page uses. |
| `is_modern_ui_available(settings=None, user_settings=None, *, bundle_available=None)` | True when the modern interface is selected and the V2 bundle exists: the one test for "send this request to V2", shared with the classic to V2 redirect. When the bundle is the reason a request stays classic it writes one throttled `[UI_MODE]` warning per process. |
| `is_v2_bundle_ready(bundle_available=None)` | The bundle half of that test, with the same throttled warning. |
| `V2_HOME_PATH` | `/v2`, where a signed-in application user lands in the modern interface. |

The module imports only the standard library, Flask and `functions_ui_mode` at load time; the V2
route module and the logger are imported when they are needed. The pages
that use it are public or error pages and the rate limited page in particular has to render
while the rest of the application is struggling, so it must not pull in the settings or Cosmos
stack.

### Pages and call sites

| Page | Classic template | Modern template | Chosen in |
|---|---|---|---|
| Home page (signed out, no role) | `index.html` | `modern/landing.html` | `index()` in `app.py` |
| Acceptable Use Policy | `acceptable_use_policy.html` | `modern/acceptable_use_policy.html` | `acceptable_use_policy()` in `app.py` |
| Rate limited | `errors/429.html` | `modern/errors/429.html` | `handle_rate_limited_request()` in `app.py` |
| Microsoft 365 sign-in result | `m365_connection_result.html` | `modern/m365_connection_result.html` | `_connection_result_page()` in `route_backend_m365.py` |

The Teams sign-in page (`login.html`) stays as it is. Custom pages, including the built-in
Request Access page, are served by the custom pages feature, not here.

### The home page, state by state

`index()` still begins with the `ENABLE_AUTO_LOGIN_ON_INDEX` redirect, so index auto-login
behaves the same in both interfaces.

| Who is asking | Classic interface (today) | Modern interface |
|---|---|---|
| Signed in with the `User` or `Admin` role | The classic home page with **Start Chatting** | A `302` to `/v2` **only when** `is_modern_ui_available()` is true and the address does not carry `ui=classic`; without the compiled bundle `/v2` answers `503`, so the classic home page is rendered instead (with one throttled `[UI_MODE]` warning), and `ui=classic` is how "Back to classic UI" reaches the classic home page |
| Signed in without an application role | The classic access-denied block | `modern/landing.html` with the access denied message, the signed-in account, **Request Access** and **Sign in with another account** |
| Not signed in | The classic landing text and sign-in link | `modern/landing.html` with the landing text and a **Sign in** link |

The redirect goes to `/v2`, not `/v2/`. `route_frontend_v2.py` registers `/v2` and
`/v2/<path:subpath>`, and `/v2/` matches neither, so a redirect there would answer `404`. The
classic to V2 redirect that covers every other classic page is described in
`V2_INTERFACE_SELECTION_PREREQUISITES.md`; `index()` makes its own decision because the landing
page is the one classic page whose signed-out and no-role states must stay server-rendered.

The modern landing page shows:

- **Branding**: the logo (scaled by **Main Page Logo Size**, applied as a pixel height exactly
  as the classic page and the V2 home page do) and the application title as the page's
  `h1`. With **Hide Application Title** on, the `h1` stays in the page for screen readers and
  the logo's `alt` text names the application.
- **Landing text**: the administrator's Markdown, aligned as **Markdown Alignment** says.
  Unlike the classic signed-out page, which centres the text whatever the setting, the modern
  page follows the setting in every state, as the V2 home page does.
- **Access denied message**: escaped, with its line breaks kept (`nl2br`).
- **Signed in as**: the account name, or `Microsoft account` when there is none, and the
  email-style claim when `get_signed_in_account_display` found one.
- **Request Access**, only when **access_request_button_enabled** is on and the configured URL
  is a path on this site, or an `http`, `https` or `mailto` link. Its label is
  **access_request_button_text**.
- **Sign in with another account**, which goes to `login?select_account=1`.

### The rate limited page

`handle_rate_limited_request` in `app.py` behaves as before and only the template it renders can
change:

- JSON callers (a path under `/api/` or `/external/`, `X-Requested-With: XMLHttpRequest`, or a client
  that accepts JSON but not HTML) never get a page. They get the shared payload and the status
  `429`.
- A `Retry-After` header is set whenever a retry window is known.
- If the page cannot be rendered, classic or modern, the message is returned as `text/plain` so it
  still reaches the user, and the failure is logged under `[RATE_LIMIT]`.
- The modern page needs nothing but its stylesheet: no API call and no V2 bundle, so it renders
  while the application is throttling or the bundle has not been built.

### The standalone layout

`templates/modern/standalone_base.html` is the layout every modern page extends. It has no
navigation, no Bootstrap and no script bundle, only `static/css/modern-standalone.css`:

| Block | Use |
|---|---|
| `title` | The `<title>`; defaults to the application title |
| `head` | Extra `<head>` content (the Microsoft 365 page adds `noindex`) |
| `page_class` | `ms-page-narrow` (32 rem) or `ms-page-wide` (48 rem); 40 rem by default |
| `brand` | The compact logo and title above the panel; the landing page empties it and keeps the brand in its panel |
| `content` | The page. It must contain an `h1`. |
| `scripts` | Scripts at the end of `<body>` |

Every page has, in order: a **Skip to main content** link, the classification banner (when
enabled), the compact brand header, and one `main` landmark.

`templates/modern/_branding.html` holds the logo rules once, copied from the classic home page:
a custom light logo, a custom dark logo and the shipped logos when nothing was uploaded; a
light-only upload also serves dark mode. Both images are written out and the stylesheet shows the
one that matches the theme; they load lazily, so the one that stays hidden is never downloaded. The
favicon and the classification banner (text, background and text colours, with the same defaults)
follow `base.html`. The stylesheet link carries the application version (`?v=`), so an upgrade is
not served a cached copy of the old stylesheet.

The templates read `app_settings`, the sanitised settings the context processor supplies. When
it is missing, as in a bare Flask test app, the application title falls back to `SimpleChat` and
the branding and banner are left out, so a modern page can always render.

### Theme

An inline script in `<head>` sets a `light` or `dark` class on `<html>` before first paint, as the
V2 shell does:

1. a value of `light` or `dark` in `localStorage` under `simplechat.v2.theme`, the key V2 writes,
   wins;
2. otherwise the operating system's `prefers-color-scheme` decides.

When storage is blocked or scripts are off, no class is set and the stylesheet's
`prefers-color-scheme: dark` block applies the same dark tokens, so the page still follows the
operating system. The two dark token blocks must stay identical, and the functional test checks
that. There is no theme toggle: these pages follow the V2 choice stored in the browser, or the
operating system when there is none.

### Design tokens and contrast

The tokens repeat the ones in `application/v2_ui/src/styles/theme.css`, with the same names and
values, for light and dark. Only the tokens these pages use are carried over. The page
backdrop, glass panel, radii and type scale are V2's, with system fonts only.

Contrast is a requirement on these public pages, so a few values differ from V2 on purpose:

| Where | V2 | Standalone | Why |
|---|---|---|---|
| Primary button fill, light | `#3b6ef0` (white text 4.49:1) | `#2f5ed8` (5.66:1) and `#2549b8` on hover | V2's resting accent is just under 4.5:1 |
| Link, light | `#3b6ef0` (4.26-4.42:1 on the panel) | `#2f5ed8` (5.37-5.57:1) | Links are text |
| Link, dark | `#7ea0ff` (4.07:1 over the strongest part of the mesh) | `#97b3ff` (4.98:1 or more) | Links are text |
| Secondary text | `--text-3` (3.39:1 in dark over the mesh) | `--text-2` only | `--text-3` is not carried over |
| Status icons | the status colours | `--ms-icon-*` shades | Each is at least 3:1 on its tinted square |

The panel uses the most opaque of V2's three glass levels (`--surface-3`), so text on it keeps its
contrast over every part of the background mesh. The functional test measures the tokens over the
strongest tint of the mesh as well as the plain backdrop.

### Accessibility and layout

- `lang="en"`, one `main` landmark with `tabindex="-1"`, the skip link, and a leading `h1`.
  Administrator Markdown can add headings of its own, including another `h1`; the page's own
  title always comes first.
- Every link and button gets a visible 2 px focus ring in the accent colour; the skip link is
  off screen until it is focused. Buttons are at least 44 px tall.
- Actions sit side by side on a wide screen and stack, each full width, below 40 em.
- The layout has no horizontal scroll at 390 px or 320 px. Long words and addresses wrap, and a wide
  table or code block in Markdown scrolls inside its own box.
- Under `forced-colors` every panel, note and button keeps a visible border, and a
  `prefers-reduced-motion` visitor gets no transitions.

### Security

- Administrator text is escaped by Jinja everywhere: the application title, the access denied
  message, the account name and email, the banner text, and the Request Access label. Nothing in
  the modern templates uses `|safe`.
- The landing text and the rate limit message are Markdown converted and sanitised by
  `markdown_filter` (`bleach`, with only `http`, `https` and `mailto` links). They are `Markup`
  values and are written out as they arrive. A plain string handed to the same template is
  escaped, so a caller cannot make the page render markup by mistake.
- The Request Access link is only rendered for a path on this site (one `/`, not `//` or `/\`) or an
  `http`, `https` or `mailto` URL, so a stored `javascript:` or `data:` URL never becomes a link.
  The classic page writes the URL as stored.
- The Microsoft 365 result page keeps its JSON data block through `tojson`, which escapes `<`, so a
  message containing `</script>` cannot break out of it.
- The pages load nothing from outside the application: no CDN, no remote font or image, no
  `@import`. The only inline script is the theme script. No route, decorator or Content Security
  Policy changed.

### The Microsoft 365 sign-in result

`modern/m365_connection_result.html` keeps every element id the completion script reads
(`m365-connection-result`, `…-title`, `…-message`, `…-closing`, `…-continue`, `…-close`, and the
`m365-connection-result-data` JSON block). The script is the same file and the page
defines `d-none`, the class it toggles. In a popup the page still reports to the window that
opened it and closes; on a full page it shows the outcome, with an icon, and a link back.
`_connection_result_page` changed only the template it renders; the continue URLs, status codes and
no-store headers are as before.

### Documentation inventory

`scripts/build_docs_inventory.py` maps each page template to its route by looking for
`render_template` calls. It now also counts `render_page`, whose first argument is the classic
template, so choosing templates through the helper does not drop a page's route from the
generated inventory.

### File structure

```text
application/single_app/
  functions_ui_mode.py                       the seam (answers classic)
  functions_ui_pages.py                      render_page and friends
  app.py                                     index, acceptable_use_policy, handle_rate_limited_request
  route_backend_m365.py                      _connection_result_page
  static/css/modern-standalone.css           tokens and components
  templates/modern/
    standalone_base.html                     the layout
    _branding.html                           logo macro
    landing.html
    acceptable_use_policy.html
    errors/429.html
    m365_connection_result.html
```

## Usage

### Before the interface selector exists

There is nothing to enable. Every page renders its classic template. A developer can preview the
modern pages in a local checkout by making `get_ui_mode` return `UI_MODE_MODERN`; that is a
development aid, not a supported setting. In that mode a signed-in application user is sent to
`/v2` when the bundle is built.

### Publishing your own Acceptable Use Policy

The shipped Acceptable Use Policy is an example, and the default landing text links to it
(`acceptable_use_policy.html`). To publish your own wording, change the text in **both**
`templates/acceptable_use_policy.html` and `templates/modern/acceptable_use_policy.html`, or point
the landing text at a policy you host. The classic template was not changed to share a partial, so
the two copies are edited together until the classic page can be refactored.

### Branding

Everything the pages show comes from existing settings: **Application Title**, **Hide Application
Title**, **Show Logo**, the light and dark logos, **Main Page Logo Size**, **Landing Page Text**,
**Markdown Alignment**, the classification banner, **Access Denied Message**, and the access request
button settings. No new setting was added.

## Testing and validation

- `functional_tests/test_modern_standalone_pages.py` runs the real `index`, Acceptable Use Policy and
  429 functions from `app.py` against the real templates, and the real
  `_connection_result_page`. It covers the classic default (the same templates with the same context),
  each modern state, the redirect to `/v2` only when the bundle exists (and not for `ui=classic`),
  the 429 JSON path,
  `Retry-After` and the plain-text fallback, escaping and sanitising, branding, the template and
  stylesheet contracts (no `base.html`, no remote asset, no unsafe sink, identical dark token blocks,
  token parity with V2), and the WCAG AA contrast of the tokens over the whole background mesh.
- `ui_tests/test_modern_standalone_pages.py` drives the rendered pages in Chromium: landmarks,
  headings and links; the stored V2 theme, the operating system preference and no script; measured
  text contrast in both themes; no sideways scrolling at 390 px and 320 px with hostile long content;
  tab order with a visible focus ring; the skip link; and the Microsoft 365 popup contract.
- Existing tests that read the classic templates, the 429 handler and the Microsoft 365 route keep
  passing unchanged (`test_index_auto_login.py`, `test_rate_limit_message_configuration.py`,
  `test_access_denied_message_feature.py`, `test_m365_routes.py`, `test_m365_runtime_imports.py`,
  `ui_tests/test_m365_connection_result_page.py`).

Results at version 0.261.445: the functional test passes 69 checks and the UI test passes 71 in Chromium
(light and dark, desktop, 390 px and 320 px). The lowest rendered text contrast measured on the
Acceptable Use Policy page is 6.76:1 in light mode and 9.47:1 in dark mode. Two sensitivity checks showed
the tests do their job: removing the long-word wrapping from the stylesheet fails the layout test with a
1,981 px overflow at 320 px, and weakening the link and secondary text tokens fails the contrast test.

Commands:

```powershell
python -m pytest functional_tests\test_modern_standalone_pages.py -q -p no:cacheprovider
python -m pytest ui_tests\test_modern_standalone_pages.py -q -p no:cacheprovider
python scripts\check_xss_sinks.py --full-file application\single_app\templates\modern\standalone_base.html application\single_app\templates\modern\landing.html application\single_app\templates\modern\acceptable_use_policy.html application\single_app\templates\modern\errors\429.html application\single_app\templates\modern\m365_connection_result.html
```

## Known limitations

- The variants are inactive until the interface selector lands; today no one sees them.
- The Acceptable Use Policy text exists twice, in the classic and the modern template. Change both.
- The Request Access custom page and any other custom page are not part of this feature, and the
  Teams sign-in page stays as it is.
- Landing text alignment follows **Markdown Alignment** in every state on the modern page, where the
  classic signed-out page always centres it.
- A Request Access URL that is neither a path starting with `/` nor an `http`, `https` or `mailto` URL
  does not show a button on the modern page.
- A visitor cannot change the theme on these pages; they follow the V2 choice stored in the browser or
  the operating system.
- Landing text that starts with its own `# heading` gives the page two `h1` elements; the
  application title comes first.
