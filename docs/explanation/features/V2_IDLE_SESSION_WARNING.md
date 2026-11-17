# V2 Idle Session Warning

**Implemented in version: 0.261.445**, tracked in `application/single_app/config.py`.

## Overview

When an administrator turns on **Sign out inactive users** (Admin Settings > Security > Session),
the server ends a session that has had no activity for the configured number of minutes. The
classic interface warns people first, with a **Session Expiring Soon** dialog, and quietly keeps the
session alive while they work. The React V2 interface did neither: it showed only the after-the-fact
"your session needs to be renewed" notice, so people were signed out without warning, and an active
person was signed out too.

V2 now does what classic does. It warns before the sign-out with a countdown, lets the person
**Stay signed in** or **Logout now**, signs them out when the countdown ends, and reports activity to
the server so someone who is working is never signed out at all.

There are no new settings: the four idle settings an administrator already configures
(`enable_idle_timeout`, `idle_timeout_minutes`, `idle_warning_minutes`, `idle_warning_message`)
drive both interfaces.

**Dependencies:** the V2 bootstrap payload (`GET /api/v2/bootstrap`), the heartbeat route
(`POST /api/session/heartbeat`) and the local sign-out (`GET /logout/local`), the shared V2 API
client (`lib/apiClient.ts`), and the existing sign-in notice (`components/layout/SessionNotice.tsx`).

## Why V2 needed a heartbeat, not only a dialog

The server's idle check (`enforce_idle_session_timeout` in `app.py`) measures idleness from
`session['last_activity_epoch']`. Only two things move it: loading a page, and calling the heartbeat
route. API calls (`/api/...`) never do. V2 is one page load followed by nothing but API calls, so
without a heartbeat a person actively chatting is signed out `idle_timeout_minutes` after opening the
app. The dialog alone would have warned them about something they were not doing.

## Technical specifications

### Server

| File | Change |
| --- | --- |
| `application/single_app/functions_idle_timeout.py` | New. `get_idle_timeout_settings(settings)`, `is_idle_timeout_enabled(settings)`, `get_idle_warning_message(settings)` and `build_idle_timeout_bootstrap(settings)`. Reads only the settings dictionary it is given. |
| `application/single_app/app.py` | `get_idle_timeout_settings(settings=None)` and `is_idle_timeout_enabled(settings=None)` keep their names and signatures. They resolve the request's settings when none are passed and delegate to the shared module. The enforcement hook, the template context and the heartbeat route are unchanged. |
| `application/single_app/route_backend_v2.py` | `_build_session(public_settings)` and a `session` key in the bootstrap payload. |

**Why a new module.** `route_*` modules are imported by `app.py`, so a route cannot import anything from
it. The V2 bootstrap route needs the same normalization the server enforces with, so both import
`functions_idle_timeout`. That module imports only `logging` and `functions_appinsights`: it depends on
nothing that depends on a route, on `config` or on the settings owner, so it cannot take part in an import
cycle. `functional_tests/test_v2_idle_session_warning.py` checks the dependency set, checks that no
module-level or function-level import path leads back to it, and loads it cold and offline in three
orders (the module first, the V2 route first, the web app first) under normal and optimized Python.

**Normalization** is exactly what the server enforced before the move:

- `idle_timeout_minutes` is read as an integer, defaulting to 30 when absent or unreadable, and is raised
  to at least 10.
- `idle_warning_minutes` defaults to 28 and is raised to at least 0. A warning later than the timeout is
  lowered to the timeout.
- `enable_idle_timeout` accepts a boolean or the strings `1`, `true`, `yes` and `on`.
- `idle_warning_message` is trimmed and capped at 200 characters. A blank or missing message is replaced
  by `You've been inactive for a while.`

Invalid and adjusted values are logged under the new `[IDLE_TIMEOUT]` tag (listed in
`docs/reference/logging-tags.md`). The log lines are the ones `app.py` wrote before, with the tag added.

**Bootstrap block.** `GET /api/v2/bootstrap` now carries:

```json
"session": {
    "idle_timeout": {
        "enabled": true,
        "timeout_minutes": 30,
        "warning_minutes": 28,
        "warning_message": "You've been inactive for a while."
    }
}
```

The block is built from the **sanitized** settings (`sanitize_settings_for_user`), and only these four
normalized values leave the function. Nothing else about the settings document is exposed. A server that
predates the block sends no `session` key, which V2 reads as "no idle warning".

### Browser

| File | Role |
| --- | --- |
| `application/v2_ui/src/lib/idleSession.ts` | Thresholds, throttles and the controller. No DOM, React or network: the page lends it a clock, timers, the heartbeat, the sign-out and shared storage, which is what lets the thresholds run against a fake clock. |
| `application/v2_ui/src/lib/idleSessionRuntime.ts` | `useIdleSessionRuntime(policy)`: the real clock, the DOM events that count as activity, the heartbeat through `apiClient`, the sign-out navigation, shared storage and the link to the sign-in notice. |
| `application/v2_ui/src/components/layout/IdleSessionDialog.tsx` | `IdleSessionDialog` (the alert dialog) and `IdleSessionDialogHost`, which reads the block from bootstrap and runs the runtime. |
| `application/v2_ui/src/lib/types.ts` | `IdleTimeoutBootstrap` and the optional `session` block on `BootstrapPayload`. |
| `application/v2_ui/src/App.tsx` | Mounts `<IdleSessionDialogHost />` once, inside the shell. Only a loaded session reaches the shell, so only a loaded session is timed. The Terms of Use and Access restricted pages, which render without the shell, are not. |

**Thresholds (the same as classic's `static/js/idle-logout-warning.js`).**

- The warning opens `idle_warning_minutes` after the last activity and the person is signed out
  `idle_timeout_minutes` after it. A warning time equal to the timeout means no dialog: the person is signed
  out at the timeout.
- A policy the classic page also refuses to act on (no positive timeout, or a warning outside 0 to the
  timeout) runs nothing. The server still enforces the timeout.
- Activity is counted at most once a second.
- The heartbeat is sent at most every minute, or every half timeout if that is shorter.
- The countdown shows whole seconds remaining, rounded up.

**Activity** is `mousedown`, `mousemove`, `keydown`, `scroll`, `touchstart`, `click` and `wheel`, listened
for in the capture phase so a scroll inside any pane counts (a scroll event does not bubble out of a pane,
and V2 scrolls inside panes). Input inside same-origin frames the page embeds, such as an embedded custom
page, never reaches the page's document, so each such frame is listened to from the outside, on its `load`
event and on a five-second scan. A frame from another origin cannot be read and is not counted. Returning to
the tab counts as activity while there is time to spare.

**The heartbeat** is `api.post('/api/session/heartbeat', {})`, so the same-origin rules, the empty JSON body
and the `X-SimpleChat-UI: v2` header apply as to every V2 call. The first activity is reported at once. If
a heartbeat was sent less than the interval ago, the report goes out as soon as one is due, so the server's
clock never trails the page's by more than the interval: a person who stops moving right after a throttled
input is still reported before the warning they are owed, and the server cannot sign them out before the
page warns them. Two heartbeats are never in flight at once, and a failed one is retried by the next input,
not by a loop.

**The dialog.**

- `role="alertdialog"`, `aria-modal="true"`, labelled by the title **Session expiring soon** and described by
  the administrator's sentence and the countdown. It is drawn above every other dialog.
- Focus moves to **Stay signed in** when it opens and returns to where it was when it closes. Tab and
  Shift+Tab stay inside it. Escape is swallowed before it can reach a dialog underneath, and a click outside
  is ignored and does not pull focus out.
- The countdown reads, for example, `1 minute 40 seconds`. It is not a live region: that would be read out
  every second. A separate status region announces it as it crosses a minute, half a minute and ten seconds.
- **Stay signed in** posts the heartbeat. While it is waiting the button is marked busy (`aria-busy`,
  `aria-disabled`, a spinner) but stays focusable, so focus is not dropped. On success the dialog closes and the
  clock restarts.
- **Logout now** and the end of the countdown navigate to `/logout/local`, the same local sign-out classic
  uses for both. It clears the SimpleChat session; it does not take the person through the Microsoft Entra
  sign-out page.
- The administrator's sentence is plain text, rendered as text.
- At 390 px wide the buttons stack and fill the width, and the dialog stays inside the viewport.

**When the heartbeat fails.**

| Answer | Result |
| --- | --- |
| The server ended the session (a 401 saying so, or any bare 401) | The existing sign-in notice (`SessionNotice`) appears. The warning closes, the clock stops, and nothing signs the person out behind the notice or sends another heartbeat. When sign-in is confirmed the clock restarts from that moment. |
| Any other failure, from **Stay signed in** | The dialog stays open, says "We couldn't confirm your session. Check your connection and try again before the countdown ends.", and lets the person try again. The countdown keeps running and the sign-out still happens at zero. |
| Any other failure, from an activity heartbeat | Nothing is shown. The next input tries again. |

### Differences from classic

| | Classic | V2 |
| --- | --- | --- |
| Input while the warning is open | Any mouse move, key press or scroll dismisses it and restarts the clock | Nothing but **Stay signed in** continues the session. Otherwise pressing Tab to reach **Logout now** would cancel the warning, and the dialog could not be used from the keyboard. |
| A failed **Stay signed in** | Signs out immediately, for any failure | Keeps the dialog, shows the failure and lets the person retry. An ended session goes to the sign-in notice instead of a sign-out. |
| Several tabs | Each tab has its own clock, so an idle background tab can sign out a session in use in another | V2 tabs share their last activity through `localStorage` (`simplechat.v2.idleActivity`), so an idle V2 tab neither warns nor signs out while another V2 tab is in use. Without storage each tab keeps its own clock, as in classic. |
| Embedded pages | Not applicable (full pages) | Input in same-origin embedded frames counts. |
| Heartbeat timing | On input, at most every minute | The same, plus a report as soon as one is due after a throttled input, so the server never trails the page. |
| Late input | A timer decides | Wall-clock time decides. Input that arrives after the warning was due, for example after a laptop wakes, opens the warning (or signs out past the timeout) instead of extending the session, and a throttled background tab cannot believe less time has passed than the server does. |
| Coming back to the tab | Counts as activity, and dismisses an open warning | Counts as activity while there is time to spare. An open warning stays until answered. |
| Countdown | `NNN seconds`, in a live region that updates every second | Minutes and seconds in words, announced at a few marks. |
| Where the values come from | Template context | The bootstrap `session` block, normalized by the helper the server enforces with. |

### Known limitations

- The clock is per interface. A classic tab and a V2 tab open at once do not share activity, so an idle
  classic tab can sign out a session in use in a V2 tab, exactly as two classic tabs can today.
- Work that produces no input does not count. A long reply streaming while nobody touches the page is not
  activity, here or in classic.
- A warning time of 0 minutes (the schema allows it) shows the dialog continuously, as classic does.
- The Terms of Use and Access restricted pages do not show the warning. The server's timeout still applies
  to them.
- The V2 admin schema describes **Idle Warning Message** as the dialog's "heading". Both interfaces show it
  as the first line of the dialog, under the fixed title.

## Usage

Administrators configure the timeout in Admin Settings > Security > Session. Nothing changes for a deployment
that leaves **Sign out inactive users** off: V2 attaches no listeners and sends no heartbeats.

With it on, someone using V2 sees nothing until they have been idle for the warning time. The dialog then
counts down. **Stay signed in** keeps the session; **Logout now** or doing nothing ends it. Anyone who keeps
working is never warned.

## Testing and validation

- `functional_tests/test_v2_idle_session_warning.py`: the helper's normalization, switch reading and
  sentence handling; its logging under `[IDLE_TIMEOUT]`; the four settings against the admin schema, the stored
  defaults and the real sanitizer; no import cycle through the module and no route importing `app`; cold,
  offline imports in three orders under normal and optimized Python; the real bootstrap route building the block
  from the sanitized settings; the heartbeat and sign-out routes the page calls, their gates and the page's
  use of the API client; and the TypeScript run below.
- `functional_tests/test_v2_idle_session_warning_logic.ts`, run under node by the test above: the thresholds
  to the millisecond, the throttles, the trailing heartbeat, overlapping heartbeats, sleep, tab visibility,
  shared activity from another tab (including implausible values), Stay signed in succeeding, failing and
  refused as an ended session, pause and resume, no timer left running, timers within a browser's limit, and
  every block the real helper builds for a spread of settings.
- `ui_tests/test_v2_idle_session_warning.py`: against the built SPA with the page's clock controlled. The warning
  appears at the warning time with the administrator's sentence as text; the countdown and its announcements;
  Stay signed in posts an empty JSON body with the V2 header and restarts the clock; Logout now and the end of
  the countdown leave through `/logout/local`; active users are reported at most once a minute and never
  warned over 160 minutes; scrolling in a pane and input inside an embedded frame count; a disabled timeout, a
  warning equal to the timeout and a missing session block behave as described; focus is trapped and returns,
  Escape does not reach a dialog underneath and passing input does not dismiss the warning; the dialog fits a
  390 px phone; text contrast in light and dark; an ended session shows the sign-in notice, and a failed Stay
  signed in offers a retry; an idle tab does not sign out a session in use in another tab.
- `functional_tests/test_idle_logout_timeout.py` and `functional_tests/test_v2_scope_and_bootstrap_timings.py`
  were updated for the move of the helpers and the new bootstrap section.

Run:

```powershell
python -m pytest functional_tests\test_v2_idle_session_warning.py -q -p no:cacheprovider
python -m pytest functional_tests\test_idle_logout_timeout.py functional_tests\test_v2_scope_and_bootstrap_timings.py -q -p no:cacheprovider
cd application\v2_ui; npx vite build; cd ..\..
python -m pytest ui_tests\test_v2_idle_session_warning.py -q -p no:cacheprovider
```
