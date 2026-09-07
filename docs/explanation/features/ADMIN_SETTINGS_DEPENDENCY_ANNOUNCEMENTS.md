# Admin Settings Dependency Announcements

**Implemented in version:** 0.260.008
**Area:** Admin Settings information architecture, stage B
**Related:** `ADMIN_SETTINGS_CARD_TARGETED_LINKS_FIX.md`

## Overview

Several Admin Settings options only take effect when a different option is
enabled. Those relationships were previously communicated inconsistently, and
in the weakest cases not until after saving. This adds a declarative way for a
card to state what it needs, with an inline notice that lets an admin satisfy
the prerequisite without hunting for it.

This matters more after the information architecture rework, because settings
that are currently one tab apart end up in different top-level groups.

## Problem

Dependencies were expressed in four different ways, none of them actionable:

| Dependency | How it was communicated |
|---|---|
| File Sync needs Redis Cache | Server-rendered alert, plus a `flash()` after saving |
| FeedbackAdmin role needs User Feedback | One sentence of prose |
| Backup source blobs need Enhanced Citations | Tooltip text |
| Web Search needs consent | `flash()` after saving |

The File Sync alert was accurate but static: it reflected saved state, so
toggling Redis in another tab did not update it. The prose and tooltip cases
offered no way to act, and no indication of where the prerequisite lived.

## Design

A dependent card declares its prerequisite in markup:

```html
<div class="card" id="file-sync-section"
     data-requires="enable_redis_cache"
     data-requires-label="Redis Cache"
     data-requires-target="redis-cache-section"
     data-requires-mode="warn"
     data-requires-description="File Sync settings can be saved now, but sync runs stay inactive until Redis Cache is enabled and configured.">
```

| Attribute | Purpose |
|---|---|
| `data-requires` | Element id of the prerequisite control |
| `data-requires-label` | Human name used in the notice |
| `data-requires-target` | Card id to link to, resolved via `data-admin-link` |
| `data-requires-mode` | `block` disables the dependent controls, `warn` only announces |
| `data-requires-scope` | Optional selector limiting which controls are gated |
| `data-requires-description` | Optional custom explanation |

`static/js/admin/admin_settings_dependencies.js` evaluates each declaration on
load and whenever the prerequisite changes, then renders a notice containing:

1. **An inline mirror** of the prerequisite switch, so it can be satisfied
   without leaving the tab.
2. **A link to the prerequisite's card**, using the stage A resolver, so the
   full configuration is one click away.

### Why the mirror cannot corrupt a save

Admin Settings posts one form, and the backend reads values by field name. A
second control sharing a name would submit the value twice. The mirror is
therefore created with **no `name` attribute**; it carries
`data-dependency-proxy-for` instead and drives the canonical input directly.
Exactly one named control per setting is ever submitted. This mirrors the
convention the Latest Features tab already uses, where proxies are named with a
`_proxy` suffix that the backend never reads.

### Why some dependencies warn instead of block

File Sync is deliberately `warn`. The backend already accepts File Sync as
*requested* and reconciles it once Redis is ready, tracked as
`requested_enable_file_sync` versus `file_sync_effective_enabled`. Hard
disabling the toggle would remove a behaviour the backend supports on purpose:
configure now, satisfy the infrastructure dependency after. Everything else
blocks, because there is no equivalent deferred-intent path.

### Field-level scoping

`permissions-section` holds both the SafetyViolationAdmin and FeedbackAdmin
role toggles, and only the latter depends on User Feedback. Blanket-disabling
the card would switch off an unrelated control, so that dependency declares
`data-requires-scope="#require_member_of_feedback_admin"`. A test asserts this
specific scoping, because getting it wrong is silent and user-visible.

### The backend remains authoritative

Client-side gating is a usability layer. A disabled input is a courtesy, never
a control. `route_frontend_admin_settings.py` still validates the File Sync
Redis prerequisite and still flashes when it is unmet, and a test asserts that
validation is still present so the client-side notice cannot be mistaken for
enforcement.

## Dependencies wired

| Card | Requires | Mode | Notes |
|---|---|---|---|
| `file-sync-section` | `enable_redis_cache` | warn | Preserves save-then-reconcile |
| `permissions-section` | `enable_user_feedback` | block, scoped | Only the FeedbackAdmin toggle |

Deliberately **not** wired:

- **Backup source blobs → Enhanced Citations.** Already handled in
  `admin_data_management.js`, which drives the control from
  `settings.enhanced_citations_enabled` and shows a lock message. Adding a
  second mechanism would risk the two disagreeing.
- **Multi-modal vision → multi-endpoint management.** This is a fallback, not a
  requirement: vision uses Global Endpoints when multi-endpoint is on and the
  legacy GPT deployment otherwise. Gating it would misrepresent the behaviour.
- **Redis Key Vault auth → Key Vault storage.** Conditional on a select value
  rather than a boolean, and the existing inline hint already links correctly
  after the stage A conversion.

## Related change

The File Sync server-rendered alert previously fired whenever Redis was not
"ready", which now overlaps with the live notice. It is narrowed to the case it
uniquely covers — Redis enabled but not fully configured, which the client
cannot detect because readiness also depends on the URL and credentials being
present. The two messages no longer double up.

## Files modified

| File | Change |
|---|---|
| `application/single_app/static/js/admin/admin_settings_dependencies.js` | New module |
| `application/single_app/templates/admin_settings.html` | Loads the module |
| `application/single_app/templates/admin/_panes/file-sync.html` | Declares the Redis dependency; narrows the server alert |
| `application/single_app/templates/admin/_panes/safety.html` | Declares the scoped User Feedback dependency |
| `functional_tests/test_admin_settings_dependencies.py` | New contract test |
| `application/single_app/config.py` | Version to 0.260.008 |

## Validation

`test_admin_settings_dependencies.py` pins five properties:

1. Every declared prerequisite control exists in the composed template.
2. Every declared link target is a real card.
3. The mirror control is never given a `name`, so it cannot double-post.
4. The Permissions dependency is scoped to the FeedbackAdmin toggle.
5. The module is loaded, and the backend prerequisite validation still exists.

Regression evidence:

- Form field names and card ids unchanged: **462 names, 110 card ids identical**.
- 75 functional test files covering `admin_settings.html`: **33 pre-existing
  failures before and after, identical sets**.
- All 20 admin templates parse under Jinja.
- `scripts/check_xss_sinks.py` passes a full-file scan of every touched file.
  The notice is built with DOM APIs and `textContent`, never string HTML.

## Follow-up

Stage C adds the group navigation level. The 10 hand-written Latest Features
mirrors can then migrate onto this module's proxy handling, replacing roughly
120 lines of per-field `addEventListener` pairs with one declarative attribute.
