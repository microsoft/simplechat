# V2 Admin Settings Live Shell Refresh Fix

## Issue

An administrator enabled the classification banner in the V2 interface
(**Admin Settings → Appearance → Notices**), gave it text and a colour, and saved. The
save succeeded and the toast confirmed it, but no banner appeared. It only became visible
after a full browser reload.

The banner was not the visible part of the problem. Everything the V2 shell draws itself
from behaves the same way: the application title, the sidebar logo and favicon,
`hide_app_title`, the feature flags the chat surface branches on, the administrator-configured
AI notice and the admin navigation all kept showing the values that were current when the
page was first opened.

**Fixed in version: 0.261.046**

## Root cause

The classification banner was already implemented end to end:

- `route_backend_v2.py::_build_branding()` emits `branding.classification_banner` in the
  `/api/v2/bootstrap` payload whenever `classification_banner_enabled` is set and
  `classification_banner_text` is non-empty.
- `AppShell.tsx::ClassificationBanner` renders it, reading it from `useBootstrapStore`.

The gap was upstream of both. `/api/v2/bootstrap` is fetched exactly once, from a mount
effect in `App.tsx`, and there was no second call anywhere in the V2 source.
`AdminSettingsPage.save()` PATCHed the settings and merged the response into the admin
page's own local `data.settings` state — which is what drives the form controls and the
in-page preview, and nothing else. The bootstrap store was never told that anything had
changed, so the shell went on rendering the payload it had held since page load.

The server side was not implicated: `update_settings()` calls
`_refresh_app_settings_cache_after_write()` immediately after the Cosmos upsert, so a
refetch issued straight after a successful save reads the new values.

## The fix

`bootstrapStore` gained a `refresh()` action that re-reads `/api/v2/bootstrap` and replaces
`data` in place. `AdminSettingsPage` calls it on both of its write paths.

### Why `refresh()` is not `load()`

`load()` sets `loading: true` while it runs and `error` when it fails. `App.tsx` renders
`<BootScreen />` instead of the entire interface while `loading` is set, and `<BootError />`
instead of the entire interface when `error` is set. Reusing `load()` for a background
refetch would therefore tear down the admin page the moment a save landed — discarding any
unsaved draft — and would replace a page whose save had just succeeded with a full-screen
error if the refetch happened to fail.

`refresh()` writes only `data`. A failure is swallowed deliberately: the write it follows
has already succeeded, so a briefly stale shell is cosmetic and the next full load corrects
it.

### Ordering

A module-level `refreshSequence` counter is claimed before the request and checked before
the payload is applied. Two saves in quick succession issue two refetches, and nothing
guarantees the responses return in the order the requests left; without the guard the
interface can settle on the payload from before the second save.

### Branding uploads

Logo and favicon uploads go through `POST /api/v2/admin/settings/branding-image`, which
writes to the settings document immediately rather than waiting for **Save**. The sidebar
logo went stale for the same reason, and its URL is version-stamped (`?v=N`), so only a
refetch produces the new URL and busts the browser cache. `onBrandingUploaded` refreshes
too.

## Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/stores/bootstrapStore.ts` | Added the `refresh()` action and the `refreshSequence` ordering guard |
| `application/v2_ui/src/pages/AdminSettingsPage.tsx` | Calls `refresh()` after a successful settings PATCH and after a branding image upload |
| `application/single_app/config.py` | `VERSION` `0.261.045` → `0.261.046` |
| `functional_tests/test_v2_admin_settings_live_shell_refresh.py` | New test pinning the wiring |
| `functional_tests/test_v2_bootstrap_refresh_logic.mjs` | New runtime test executing the real store |
| `docs/explanation/features/REACT_V2_UI.md` | Documents that a save reaches the shell |
| `docs/explanation/release_notes.md` | Release entry |

## Alternatives considered

- **Patching `branding.classification_banner` in the browser from the PATCH response.**
  The server decides whether the banner is emitted at all — it requires both the toggle and
  non-empty text — and applies the `#ffc107` / `#ffffff` colour defaults. Re-deriving those
  rules client-side creates a second copy that drifts from the first.
- **Injecting the banner into the SPA shell HTML server-side**, so it paints before the
  bundle boots. This puts administrator-controlled text into raw HTML for a sub-second gain
  and does not address the save case at all.
- **Refreshing only when banner-related keys were saved.** This needs a hand-maintained list
  of the settings that affect the shell, which goes out of date as soon as a setting is
  added. Practically every admin setting reaches the bootstrap payload, so refreshing
  unconditionally is both simpler and correct.

## Validation

```powershell
python .\functional_tests\test_v2_admin_settings_live_shell_refresh.py
node .\functional_tests\test_v2_bootstrap_refresh_logic.mjs
python .\functional_tests\test_v2_admin_appearance_parity.py
python .\functional_tests\test_v2_chat_notices.py
cd .\application\v2_ui; npm run build   # tsc -b passes, bundle builds
```

The `.mjs` test imports and executes the real store rather than asserting on its source. It
covers the two ways this can go quietly wrong in a way source assertions cannot: it records
**every** intermediate state during a refresh, because `loading` only has to be set
transiently to blank the interface, and it holds one refetch open while a second completes
to prove the stale payload is discarded. Both were confirmed to fail against a deliberately
broken store before being accepted.

### Before

1. **Admin Settings → Appearance → Notices**, enable the classification banner, set text,
   save.
2. Toast confirms the save. No banner.
3. Reload the browser. Banner appears.

### After

1. Same steps.
2. The banner appears at the top of the interface as the save completes. Turning it off, or
   blanking its text, removes it just as immediately.
3. Changing the application title, uploading a logo, or enabling a capability now reaches
   the shell on save in the same way, without a reload.
