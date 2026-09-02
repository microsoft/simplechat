# V2 Chat Notices Fix

## Issue

The classic (V1) chat page renders two administrator-configured notices around the composer.
The V2 React interface rendered neither, so an organisation that had configured them lost
both the moment a user switched to V2 — including the data-handling warning that tells people
their message is about to leave the tenant.

Instead, V2 ended its composer with a hardcoded line of its own:

> AI responses can be inaccurate. Verify important information.

That is not the same thing. It is not the administrator's wording, it cannot be turned off,
it cannot be dismissed, and it appeared even for organisations that had deliberately
configured different text.

**Fixed in version: 0.261.028**

## Root cause

Both notices reach the classic page through Jinja template context, which a single-page
application cannot read.

- **Web search notice** — `templates/chats.html` renders it behind
  `enable_web_search and web_search_consent_accepted and enable_web_search_user_notice`, with
  the copy from `web_search_user_notice_text`. `static/js/chat/chat-input-actions.js` shows
  and hides it as the Web toggle changes and records a session dismissal.
- **AI notice** — `route_frontend_chats.chats` passes an `ai_notice` dict built by
  `functions_ai_notice.get_ai_notice_config()` and marked with
  `is_ai_notice_dismissed()`. `static/js/chat/chat-ai-notice.js` handles the four dismissal
  frequencies.

`/api/v2/bootstrap` mirrors that template context, but neither notice had been added to it.
Neither is derivable from what the payload already carried:

- The AI notice's `hash` is a SHA-256 of its message and frequency. It is what invalidates
  stored dismissals when an administrator edits the wording, and whether the current user's
  dismissal still applies depends on a stored, server-timestamped record and a date window.
- The web search notice's condition includes `web_search_consent_accepted`, which does not
  start with `enable_` and so was never forwarded by `_build_feature_flags`.

## Files modified

| File | Change |
|---|---|
| `application/single_app/functions_settings.py` | Added `WEB_SEARCH_USER_NOTICE_DEFAULT_TEXT` and used it for the settings default |
| `application/single_app/route_frontend_admin_settings.py` | Use the shared constant instead of a repeated literal |
| `application/single_app/route_backend_v2.py` | New `_build_notices()`; `notices` added to the bootstrap payload |
| `application/v2_ui/src/lib/types.ts` | `AiNoticeConfig`, `WebSearchNoticeConfig`, `notices` on `BootstrapPayload` |
| `application/v2_ui/src/lib/endpoints.ts` | `dismissAiNotice(hash, frequency)` |
| `application/v2_ui/src/lib/userSettings.ts` | `aiNoticeDismissal` declared as a key the client writes |
| `application/v2_ui/src/lib/notices.ts` | **New.** Session-storage keys and fault-tolerant read/write |
| `application/v2_ui/src/components/chat/WebSearchNotice.tsx` | **New.** Banner above the input |
| `application/v2_ui/src/components/chat/AiNotice.tsx` | **New.** Banner below the composer |
| `application/v2_ui/src/components/chat/Composer.tsx` | Renders both; hardcoded disclaimer removed |
| `application/single_app/config.py` | `VERSION` → `0.261.028` |

## Technical details

### Notices are resolved on the server

`_build_notices()` calls the same `get_ai_notice_config()` and `is_ai_notice_dismissed()`
helpers the classic page uses, so the hash and the dismissal window are computed in exactly
one place. `route_backend_v2.py` deliberately does not hash anything itself; the functional
test asserts that, because a second implementation of the hash would let the two interfaces
disagree about whether an edited notice should reappear for someone who had dismissed the
previous wording.

The web search condition is evaluated server-side for the same reason it could not be done in
`composerGating.ts`: `web_search_consent_accepted` is not a feature flag.

The block is built from `sanitize_settings_for_user()` output, not the raw settings document.

```json
"notices": {
  "ai": {
    "enabled": true,
    "message": "AI generated response may contain inaccuracies",
    "frequency": "every_session",
    "hash": "<sha256 of message + frequency>",
    "dismissed": false
  },
  "web_search": {
    "enabled": true,
    "text": "Your current message will be sent to Microsoft Bing for web search. ..."
  }
}
```

### Dismissals go where they can survive long enough

| Frequency | Stored | Why |
|---|---|---|
| `non_dismissible` | — | No dismiss control is rendered |
| `every_session` | `sessionStorage` | A browser-session fact; the server has nothing to add |
| `daily`, `once` | `/api/user/settings` → `aiNoticeDismissal` | Must outlive the tab, and the window is evaluated against a server timestamp |

The `daily` and `once` write goes through a dedicated `dismissAiNotice()` helper rather than
the debounced `userSettingsStore`. That store rolls a failure back silently into a preference
cache, but the route replaces the posted value with its own timestamped record, so the cached
value would never match what was stored — and the button needs a definite success or failure
to decide whether the notice may disappear. The notice therefore stays visible until the
write lands, and a failure raises a toast rather than looking like a dead button.

`aiNoticeDismissal` was already in the route's `allowed_keys`; it is now also declared in
`WRITABLE_USER_SETTING_KEYS`, so the existing whitelist test covers it. A key outside that
set is dropped silently, with the POST still returning success.

### Session keys are shared with the classic interface

`webSearchNoticeDismissed` and `simplechat.aiNoticeDismissal.<hash>` are the keys the classic
client already writes, and V2 reuses them rather than namespacing them the way
`v2RailCollapsed` is namespaced. A dismissal is a statement about the person, not about which
interface they happened to be looking at; namespacing would make a notice the user had just
dismissed reappear when they switched interfaces in the same tab. The V2-prefixed preferences
are different — they describe V2's own chrome.

`sessionStorage` throws rather than returning `null` in some privacy modes, and a notice is
not worth taking the page down for. Reads fail closed, leaving the notice visible; writes
report failure so the caller can say the dismissal did not stick.

### Behaviour when nothing is configured

Nothing renders. This was an explicit decision rather than an oversight: V2 no longer
substitutes a generic disclaimer, because an organisation that turned the AI notice off did so
on purpose and the classic interface honours that. The removed hardcoded line was also
untranslatable, unconfigurable and undismissable, which is the opposite of what the notice
feature exists to provide.

## Validation

| Check | Result |
|---|---|
| `functional_tests/test_v2_chat_notices.py` | 8/8 passed |
| `functional_tests/test_v2_api_payload_shapes.py` | Passed |
| `functional_tests/test_v2_settings_and_workspace_tags.py` | Passed — `aiNoticeDismissal` is whitelisted |
| `functional_tests/test_v2_settings_tabs.py` | Passed |
| `functional_tests/test_v2_ui_local_assets.py` | Passed — no new browser assets, CSP unchanged |
| `functional_tests/test_docs_app_surface_coverage.py` | Passed — no new settings keys, inventory unchanged |
| `npm run typecheck` (`application/v2_ui`) | Clean |

### Before and after

| | Before | After |
|---|---|---|
| Web search notice in V2 | Never shown | Shown above the input while Web is armed, dismissible for the session |
| AI notice in V2 | Never shown | Shown below the composer, honouring all four frequencies |
| AI notice disabled | V2 showed its own hardcoded line | Nothing, matching V1 |
| Administrator edits the notice text | No effect on V2 | Hash changes, dismissals invalidated, new wording shown again |

## Notes

- No new settings keys were introduced. Both capabilities already exist in admin settings
  (**Web & Research** → Web Search, and **Notices & Agreements** → Chat AI Notice) and are
  already documented, so `docs/_data/app_surface.yml` is unchanged.
- No new browser assets. Both components use existing `lucide-react` icons and the existing
  `info` / `info-soft` theme tokens.
- Notice text is administrator-entered and is rendered as a plain React child, so React
  escapes it. There is no `dangerouslySetInnerHTML` on either component, matching the classic
  interface's use of `textContent` and Jinja escaping.

## Related

- `docs/explanation/features/REACT_V2_UI.md` — "Notices"
- `docs/explanation/features/v0.237.001/WEB_SEARCH_AZURE_AI_FOUNDRY.md`
- `application/single_app/functions_ai_notice.py`
