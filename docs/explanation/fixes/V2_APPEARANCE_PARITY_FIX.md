# V2 Appearance Parity Fix

**Fixed in version: 0.261.047**

## Issue

Six Appearance settings had no visible effect in the V2 React interface, and four
settings appeared under the wrong tab.

Reported symptoms:

1. Custom light and dark logos never appeared anywhere in the application.
2. The left rail showed a letter avatar instead of the uploaded logo.
3. A custom favicon never replaced the shipped one.
4. Enabling and applying the classification banner did not render it.
5. Custom Pages and External Links never appeared in the left rail.
6. Under **Appearance > Notices & Agreements > User Agreement** an unrelated
   "User workspace" toggle appeared, and under **Appearance > Pages & Links >
   External Links** three unrelated toggles appeared: external health check,
   no-auth external health check, and support latest feature documentation links.

## Root cause

Four distinct causes, not six.

### Bootstrap was never re-read (symptoms 1, 2 and 4)

`/api/v2/bootstrap` carries `branding`, which holds the logo URLs, the application
title and the classification banner. `useBootstrapStore` loads that payload once,
from `App.tsx`, and had no way to reload it. `AdminSettingsPage.save()` merged the
PATCH response into its own local `data.settings` and stopped there.

Applying a branding change therefore updated the settings document and left every
consumer of `branding` holding the payload fetched at sign-in. `Sidebar.BrandMark`
and `AppShell.ClassificationBanner` were both already written correctly; neither
ever received a fresh value. The only way to see a change was a full page reload.

**This cause was diagnosed and fixed independently, in parallel with this work, and
shipped first in `0.261.046`.** See
[V2_ADMIN_SETTINGS_LIVE_SHELL_REFRESH_FIX.md](V2_ADMIN_SETTINGS_LIVE_SHELL_REFRESH_FIX.md),
which adds `bootstrapStore.refresh()` and calls it from both write paths in
`AdminSettingsPage`. That implementation also orders concurrent refreshes so a
slower earlier refetch cannot land after a newer one, and is the one kept here. The
three symptoms are recorded in this document because they are what was reported
against Appearance, and because the remaining causes below are only visible once
this one is out of the way.

### The SPA shell hard-coded the shipped favicon (symptom 3)

`application/v2_ui/index.html` is a build input, compiled to
`static/v2/index.html`, and carried a literal
`<link rel="icon" href="/static/images/favicon.ico">` with no version and a literal
`<title>SimpleChat</title>`. `_serve_v2_shell` returned that file verbatim.

The classic interface does not do this. `base.html` appends
`?v={{ favicon_version }}` whenever `custom_favicon_base64` is set, precisely
because the static file keeps a stable name across uploads: without the version, a
browser keeps serving whichever icon it had already cached.

### Bootstrap carried no navigation data (symptom 5)

The classic rail reads `custom_pages_nav`, built by `get_custom_pages_nav` in
`app.py`'s context processor, and `app_settings.external_links` directly in
`_sidebar_nav.html`. Neither reaches a single-page application, and neither can be
derived from what bootstrap already sent: custom pages are filtered per page
against the caller's roles, and the external link list is not an `enable_*` key so
it never appears in `features`.

### The undeclared-settings fallback guessed wrong (symptom 6)

Settings that `admin_settings_fields.py` does not describe are still shown in the
V2 admin surface. `buildCapabilityIndex` in `AdminSettingsPage.tsx` scans the
settings document for `enable_*` booleans and files each one under the navigation
section sharing the most leading word stems, keeping the first section that scores
at all.

That guess placed five toggles in the Appearance group:

| Setting | Guessed into | Actually belongs in |
|---|---|---|
| `enable_user_workspace` | Appearance > Notices & Agreements > User Agreement | Workspaces > Workspace Types > Personal Workspaces |
| `enable_external_healthcheck` | Appearance > Pages & Links > External Links | Operations > Logging & Health > Health Check |
| `enable_no_auth_external_healthcheck` | Appearance > Pages & Links > External Links | Operations > Logging & Health > Health Check |
| `enable_support_latest_feature_documentation_links` | Appearance > Pages & Links > External Links | Help > User-Facing Latest Features |
| `enable_text_plugin` | Appearance > Branding > Home Page Text | Agents & Actions > Actions |

Each is explainable from the heuristic:

- `enable_user_workspace` matches "user" in `user-agreement-section`.
- `enable_external_healthcheck` matches "external" in `external-links-section`.
  `health-check-section` splits into "health" and "check", neither of which matches
  the single token "healthcheck", so the correct section could never win.
- `enable_support_latest_feature_documentation_links` matches "links" in
  `external-links-section`, which comes first in navigation order and so beat the
  equally-scoring Support and Latest Features sections.
- `enable_text_plugin` matches "text" in `home-page-text-section`.

The fifth was not in the original report and was found by simulating the heuristic
against the real settings keys.

## Files modified

| File | Change |
|---|---|
| `application/single_app/functions_branding_urls.py` | **New.** Dependency-free module holding the branding asset paths and the version rule, previously restated in three places. |
| `application/single_app/admin_settings_fields.py` | Declared the five misfiled toggles in their real sections, plus the Support Menu gate chain the documentation-links toggle depends on. |
| `application/single_app/route_backend_v2.py` | `_build_branding` now returns `favicon_url` and the landing page fields; new `_build_navigation` supplies the custom pages and external links groups; `BRANDING_IMAGE_TARGETS` reads its paths from the shared module. |
| `application/single_app/route_frontend_v2.py` | `_serve_v2_shell` rewrites the shell's icon link and title from settings. |
| `application/v2_ui/src/components/layout/Sidebar.tsx` | Logo sized by height rather than forced square; Home nav entry; mounts `NavExtras`. |
| `application/v2_ui/src/components/layout/NavExtras.tsx` | **New.** Renders the two configured navigation groups. |
| `application/v2_ui/src/lib/navigationGroups.ts` | **New.** The inline-versus-menu and visibility rules, kept testable. |
| `application/v2_ui/src/pages/HomePage.tsx` | **New.** See `docs/explanation/features/V2_HOME_PAGE.md`. |
| `application/v2_ui/src/components/admin/AdminMarkdown.tsx` | Added a `size` variant so home page copy is not rendered at settings-preview scale. |
| `application/v2_ui/src/components/layout/AppShell.tsx` | Gave the classification banner the `classification-banner` id the classic layout uses. |
| `application/v2_ui/src/App.tsx` | Home route; keeps the tab icon in step with the stored favicon. |
| `application/v2_ui/src/lib/types.ts` | Extended `branding`; added the `navigation` block. |
| `application/single_app/config.py` | Version bump to `0.261.047`. |

`bootstrapStore.ts` and `AdminSettingsPage.tsx` are not listed: the refresh they
needed arrived in `0.261.046` and is kept as it was written there.

## Behavior changes

- A custom favicon and the configured application title now reach the browser tab,
  and the tab icon follows an upload made in the same session.
- Custom Pages and External Links appear in the V2 rail, using the same rule as the
  classic navigation: one or two entries inline, three or more (or "Force Menu
  Display") behind the configured menu name.
- An external link whose URL is not a local path or an `http`/`https` address is now
  dropped from the bootstrap payload. Only the V2 settings PATCH applied that rule on
  write, so a `javascript:` URL stored through the classic admin form, or already
  present in a settings document, would have become an anchor in every V2 user's
  rail. `EXTERNAL_LINK_ALLOWED_SCHEMES` is now enforced on the read path too.
- The five relocated settings now appear under the tab that owns them.
- The rail logo keeps its own proportions instead of being drawn into a square.
- `/v2` opens a home page rather than redirecting to chat.
- Clearing the landing page copy leaves the home page without it. Restoring default
  wording would put an acceptable-use statement back on a page an administrator had
  deliberately emptied, and the classic home page does not do that either.

### Deliberate divergence from the classic interface

When **Show Logo** is on but no custom logo has been uploaded, the classic
navigation falls back to the bundled `logo-lightmode.png` / `logo-darkmode.png`.
V2 keeps its letter avatar instead. This was a deliberate choice: the avatar is
derived from the application title, so an unbranded deployment shows its own name
rather than the product's default artwork.

## Validation

New and updated tests:

- `functional_tests/test_v2_admin_capability_placement.py` — ports the fallback
  heuristic and asserts the Appearance group, which the schema fully describes,
  receives no guessed rows at all. Verified to fail with the exact original symptom
  when one of the relocated keys is undeclared.
- `functional_tests/test_v2_bootstrap_branding_and_navigation.py` — lifts
  `_build_branding` and `_build_navigation` out of the route with `ast` and executes
  them, covering favicon versioning, the logo and dark-variant rules, the banner's
  text requirement, landing field bounds, the external links role gate, and
  degradation when the custom page lookup fails.
- `functional_tests/test_v2_ui_spa_route.py` — extended with the shell branding
  rewrite, its escaping, and its fallback when settings are unavailable.
- `functional_tests/test_v2_navigation_groups_logic.mjs` — executes the real
  inline-versus-menu and visibility rules.
- `functional_tests/test_v2_admin_settings_schema.py` — extended with a check that
  every declared default matches the default the application seeds into the settings
  document. Added after this change declared `enable_text_plugin` as `False` when the
  application defaults it to `True`, which would have shown the toggle off while the
  action was on. All 30 declared defaults now agree.
- `ui_tests/test_v2_appearance_branding_and_nav.py` — browser coverage driven by
  what `/api/v2/bootstrap` reports for the deployment under test.

Regression suite re-run and passing: `test_v2_admin_appearance_parity`,
`test_v2_admin_settings_schema`, `test_v2_admin_settings_normalization`,
`test_v2_admin_field_renderer_coverage`, `test_v2_api_security`,
`test_v2_api_payload_shapes`, `test_v2_ui_local_assets`, `test_v2_chat_notices`,
`test_v2_workspace_sections`, `test_admin_settings_field_contract`,
`test_admin_settings_nav_map`, `test_docs_app_surface_coverage`.
