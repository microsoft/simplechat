# Admin Settings Card-Targeted Navigation Links

**Implemented in version:** 0.260.008
**Area:** Admin Settings information architecture, stage A
**Related:** `ADMIN_SETTINGS_NAVIGATION_AND_TEMPLATE_STRUCTURE_FIX.md`

## Issue

Admin Settings contains cross-references between related settings, for example
Citations pointing at the video and audio file-support toggles, or the Redis
Key Vault hint pointing at the Key Vault card. Each of those links named a tab
button directly:

```html
<a href="#workspaces" onclick="switchTab(event, 'workspaces-tab')">
```

`switchTab` looked up `document.getElementById('workspaces-tab')`. That couples
every link to a tab id, with two consequences.

### 1. Links break silently on any tab change

If the tab id changes, the lookup returns `null`, `switchTab` falls through to
`showAdminTab('workspaces')`, no pane matches, and the only symptom is a console
warning plus a URL hash pointing at nothing. Nothing fails loudly, so the
breakage survives review.

This was about to happen at scale: the information architecture rework renames
and regroups most tabs.

### 2. Two links were already wrong

The Citations tab referenced **Enable Video File Support** and **Enable Audio
File Support** with `#workspaces`, and the surrounding prose said "see the
Workspaces tab". Both settings actually live in **Search and Extract**:

| Setting | Card | Pane |
|---|---|---|
| `enable_video_file_support` | `video-intelligence-section` | `search-extract` |
| `enable_audio_file_support` | `ai-voice-chat-section` | `search-extract` |

So an admin following either link landed on the wrong tab with no indication
why.

## Root cause

The link contract pointed at *navigation structure* (a tab button id) rather
than at *content* (the setting being referenced). Navigation structure changes;
the identity of a settings card does not.

## Fix

Links now declare the card they want:

```html
<a href="#video-intelligence-section" data-admin-link="video-intelligence-section">
    Enable Video File Support
</a>
```

`static/js/admin/admin_card_links.js` resolves the owning tab from the DOM at
click time:

```js
const card = document.getElementById(cardId);
const pane = card.closest('.tab-pane');
window.showAdminTab(pane.id);
```

Because the tab is derived rather than declared, cards can move between tabs and
tabs can be renamed or regrouped without touching a single link. Card ids are
the only contract, and they are already stable — the template split preserved
all 110 of them byte-identically.

Behaviour on click:

1. Resolve the card and activate its tab, in either the top-tab or sidebar layout.
2. Mirror the active state in the sidebar when that layout is in use.
3. Scroll the card into view.
4. Highlight it for 1.6 seconds so the destination is obvious after the jump.

Clicks are handled by delegation, so links rendered later still work.

`switchTab` had no remaining callers and was removed, which makes the old
coupling impossible to reintroduce by copy-paste.

## Files modified

| File | Change |
|---|---|
| `application/single_app/static/js/admin/admin_card_links.js` | New resolver module |
| `application/single_app/static/js/admin/admin_settings.js` | Removed the dead `switchTab` helper |
| `application/single_app/templates/admin_settings.html` | Loads the resolver; adds the highlight style; sanitizes the User Agreement preview at the sink |
| `application/single_app/templates/admin/_panes/citation.html` | Two corrected links plus corrected prose |
| `application/single_app/templates/admin/_panes/latest-features.html` | Eight links converted |
| `application/single_app/templates/admin/_panes/scale.html` | Key Vault link converted |
| `application/single_app/templates/admin/_panes/search-extract.html` | Enhanced Citations link converted |
| `functional_tests/test_admin_card_links.py` | New contract test |
| `application/single_app/config.py` | Version to 0.260.008 |

## Link inventory

| Source | Target card |
|---|---|
| Citations → video support | `video-intelligence-section` *(was wrong)* |
| Citations → audio support | `ai-voice-chat-section` *(was wrong)* |
| Latest Features → model endpoints | `multi-endpoint-configuration` |
| Latest Features → citations ×2 | `enhanced-citations-section` |
| Latest Features → processing thoughts | `processing-thoughts-section` |
| Latest Features → support menu ×2 | `support-menu-section` |
| Latest Features → Redis | `redis-cache-section` |
| Latest Features → send feedback | `send-feedback-overview-card` |
| Scale → Key Vault | `keyvault-section` |
| Search and Extract → enhanced citations | `enhanced-citations-section` |

## Validation

`functional_tests/test_admin_card_links.py` pins four properties:

1. Every `data-admin-link` target is a real element id in the composed template.
2. Every such link carries a matching `href="#<target>"`, so it degrades
   sensibly without JavaScript and stays copy-pasteable.
3. No link reintroduces the tab-coupled `switchTab` pattern.
4. The resolver module exists, is loaded by the page, and derives the tab from
   the DOM rather than from a hardcoded map.

Property 1 is the one that matters: it fails the build if a card is renamed or
removed without updating the links that point at it, which is precisely the
failure mode that went unnoticed before.

Regression evidence:

- Form field names and card ids unchanged: **462 names, 110 card ids identical**.
- 75 functional test files covering `admin_settings.html`: **33 pre-existing
  failures before and after, identical sets**.
- All 20 admin templates parse under Jinja.
- `scripts/check_xss_sinks.py` passes a full-file scan of every touched file,
  which it did not before the User Agreement preview change.

## Follow-up

Stage B introduces declarative dependency gating, where a setting that requires
another one announces it inline with a mirror control and a link to the
prerequisite. That link uses the resolver added here.
