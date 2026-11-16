# V2 Stats Tab Parity

## Overview

The **Stats** tab on the V2 Settings page (`/v2/settings?tab=stats`) reports the signed-in
user's own activity: lifetime totals, day-by-day trends over a chosen window, storage
consumption, a CSV export, and the account the figures belong to.

It replaces a placeholder that showed four SVG sparklines and no totals. The classic profile
page's stats tab (`/profile?tab=stats`) had been the only place these figures existed, and
the V2 account menu offered a **Profile** link to reach it. That link is gone: with the
figures rebuilt here, a second entry in the menu offered a choice nobody had the information
to make. Settings is now the single destination for personal settings in V2.

Implemented in version: **0.261.041**

### Dependencies

- No new server routes. Everything is served by `GET /api/user/activity-trends` and
  `GET /api/user/settings`, both of which already existed for the classic page.
- Chart.js 4.5.1, from the copy vendored at
  `application/v2_ui/public/vendor/chartjs-4.5.1/`. It is not an npm dependency and does not
  enter the main bundle.

## Two kinds of number

The tab shows figures that are computed in different ways and at different times, and reading
one as the other would be wrong.

**The four cards at the top are lifetime totals** — total conversations, messages, documents
and sign-ins. They come from the `metrics` block stored on the user's settings document,
which the control-center metrics pass recalculates periodically and stamps with
`calculated_at`. They are not filtered by the selected window and they are not live, which is
why the tab states when they were last worked out rather than presenting them as current.

`last_login` is the one exception on that block. `GET /api/user/settings` overwrites it from
the activity log when that lookup succeeds, so the last sign-in shown beside the sign-in total
is current even when the total behind it is not.

**Everything below the cards describes the selected window** and is computed per request from
the activity log. Sums shown on each chart card are sums over that window only.

## The window

| Control | Sends |
|---|---|
| 7 days / 30 days / 90 days | `days=<n>` |
| Custom | `start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` |

The two forms are mutually exclusive. `resolve_stats_time_window()` in
`functions_stats_windows.py` branches on the *presence* of either date and ignores `days`
entirely in that branch, so sending both would let them disagree with nothing to say which
won.

The presets are constrained where the custom range is not. `ALLOWED_STATS_WINDOW_DAYS` is
`(7, 30, 90)`, and a `days` value outside it is not rejected — it silently becomes 30. Only
those three are therefore offered, so the highlighted button always matches the data on
screen. A custom range has no such enum and may be any span.

A reversed or incomplete range is refused by the server with a 400. The client checks the same
two conditions first, so the user is told what is wrong with the dates they just typed rather
than shown a failed request.

The label above the charts prefers `window.label` from the response — the server's own
statement of what it resolved — falling back to a locally derived one only before the first
response arrives.

## What is drawn

| Card | Shape | Source |
|---|---|---|
| Sign-in activity | Filled line | `logins[].count` |
| Conversation activity | Grouped bar, created versus deleted | `conversations.creates[]`, `conversations.deletes[]` |
| Document activity | Grouped bar, uploaded versus deleted | `documents.uploads[]`, `documents.deletes[]` |
| Token usage | Filled line, scaled to millions | `tokens[].tokens` |
| Storage used | Doughnut | `storage.ai_search_size`, `storage.storage_account_size` |

Two details in that table are easy to get wrong. The token series carries its value under
`tokens`, not `count` like every other series, so reading it by the common key yields a chart
of zeroes rather than an error. And conversations nest under `creates`/`deletes` while
documents nest under `uploads`/`deletes` — the same idea under different words.

Raw token counts run into the millions over a 90-day window, so the token chart is scaled and
labelled in millions; its axis is the one place the shared integer tick formatting is
overridden, because fractions of a million are the normal case there.

Series are placed on the chart by looking each day up in `dateRange` rather than by zipping
the two arrays. The server normally returns every day in the window, including empty ones, but
relying on that would mean a value drawn against whatever label happened to sit at the same
index if it ever stopped.

Storage is shown only when there is some. An empty ring is not a reading.

## Charts

Charts are drawn with Chart.js loaded from the vendored copy on first use, through
`src/lib/chartRuntime.ts`. That module is the single loader: the inline chat charts
(`InlineChart.tsx`) and the stats charts (`StatsChart.tsx`) both call it, so whichever draws
first fetches and evaluates the script and the other reuses it.

Loading on demand rather than bundling means a user who never opens this tab and never
receives a chart in a reply downloads none of it. Because the file is committed to this
repository and served from the app's own origin, the `default-src 'self'` Content-Security-
Policy is unchanged. See the vendored libraries section of
[React V2 User Interface](REACT_V2_UI.md).

`StatsChart` rebuilds its chart rather than mutating it when the data, kind or theme changes.
The charts here change shape entirely when the window is switched — a 90-day range replacing a
7-day one is a different chart, not the same chart with more points.

A chart that cannot be drawn says so. A blank rectangle where a chart belongs reads as "you
have no activity", which is a different and much worse claim than "this failed to load".

Series colours are fixed rather than derived from the theme, and are the classic page's hues.
Created-versus-deleted has to stay blue-versus-red in both light and dark, and someone
comparing the two interfaces should be looking at the same chart rather than working out
which line is which again. Axis, grid and legend colours *are* read from the theme's custom
properties, so the charts follow the light/dark switch.

## Export

The **Export** button opens a dialog offering five sections — summary totals, sign-ins,
conversations, documents and token usage — and its own 7/30/90/custom window. The export
window is deliberately independent of the one on screen: looking at the last 7 days and
exporting the last 90 is an ordinary thing to want, and tying them together would force a
detour through the chart controls.

The file is assembled in the browser from the same two responses, the way the classic page
does it. There is no export endpoint, and adding one would mean maintaining a second
implementation of totals that are on screen at the time. Section titles, column headers and
ordering match the classic export, so a saved spreadsheet keeps working across both
interfaces.

Deleted counts are joined to their own date rather than to the row position, because the
deletes series can be shorter than the creates series; zipping by index would file one day's
deletions under another day.

Fields containing a comma, quote or newline are quoted and internal quotes doubled, and the
file is written with a UTF-8 BOM so a name with non-ASCII characters opens correctly in Excel.

## Account

The card at the foot of the tab shows the signed-in user's name, email address and user id,
read from the `/api/v2/bootstrap` payload.

The classic card also carries a read-only "Dark Mode: Enabled/Disabled" badge. That is
deliberately not reproduced: the V2 rail has a live theme toggle a few inches away, and a
second, non-interactive echo of it adds nothing.

## File structure

| File | Purpose |
|---|---|
| `application/v2_ui/src/lib/userStats.ts` | Response types, window model and query building, range validation, series alignment, formatting, CSV builder. No API import, so the logic is executable by a Node test |
| `application/v2_ui/src/lib/chartRuntime.ts` | The shared vendored Chart.js loader and the theme colour reader |
| `application/v2_ui/src/components/settings/StatsChart.tsx` | Canvas wrapper: lazy load, rebuild, cleanup, failure notice, and the shared axis/legend options and series colours |
| `application/v2_ui/src/components/settings/StatsExportDialog.tsx` | The export dialog and CSV download |
| `application/v2_ui/src/components/settings/StatsTab.tsx` | The tab itself |
| `application/v2_ui/src/components/layout/Sidebar.tsx` | Account menu, with the Profile entry removed |

## Testing and validation

```powershell
python .\functional_tests\test_v2_stats_parity.py
node .\functional_tests\test_v2_stats_logic.mjs
python .\functional_tests\test_v2_settings_tabs.py
python .\functional_tests\test_v2_ui_local_assets.py
cd application\v2_ui; npm run typecheck; npm run build
```

`test_v2_stats_parity.py` pins names: every trend field, query parameter and metrics key the
tab reads is checked to exist on the server side, each classic stats surface is checked to
have a counterpart, the account menu is checked not to link to `/profile`, and both chart
consumers are checked to share the vendored runtime. Those are source assertions — they prove
the pieces are wired together.

`test_v2_stats_logic.mjs` proves the pieces behave. It executes `userStats.ts` directly under
Node against the parts where a quiet mistake renders perfectly and states something false: a
window sent as the wrong pair of parameters, a sparse series drawn against the wrong dates,
the token series read by the wrong key, or an export whose columns have slipped by one.

## Known limitations

- **Custom ranges are not remembered.** The selected window resets to 30 days on reload. The
  preset and the range live in component state rather than the query string, unlike the tab
  selection itself.
- **Storage figures come from the cached metrics block**, not from a live measurement, so
  they move only when that pass runs. This matches the classic page.
- **Nothing here is exported server-side.** A very long custom range produces a large
  response that is turned into CSV in the browser; the practical limit is the response the
  activity-trends route is willing to build, which is the same limit the classic page has.
