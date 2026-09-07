# V2 Orchestration Approval Persistence Fix (v0.261.101)

**Fixed in version: 0.261.101**

The application version is tracked in `application/single_app/config.py`.

## Issue

Selecting an orchestration approval mode in the React v2 chat interface did not
save it. Leaving chat and returning restored the administrator-defined default,
not the user's last selection.

## Root cause

`Composer.tsx` kept the mode in local React state. The dropdown only changed that
state; it never called the user-settings API. Remounting the composer initialized
the value from `default_approval_mode` again. A separate effect also replaced the
local selection whenever that administrator default changed.

Bootstrap and account preferences load independently, so simply reading a saved
value with an administrator fallback would still allow an unintended mode to run
before preferences arrived. The shared settings store also needed serialized writes
and selective rollback so an older request could not replace a newer selection.

## Changes

The optional account preference `orchestrationApprovalMode` accepts `manual`,
`timed`, or `auto`. The existing authenticated GET/POST `/api/user/settings` route
reads and writes it for the current user. Invalid values or types return HTTP 400
before any part of the update is saved.

The composer derives its displayed and submitted mode from the same policy:

- With overrides allowed, a saved user choice takes precedence.
- Without a saved choice, the current deployment default applies.
- With overrides disabled, the deployment default is enforced without deleting
  the user's preference.
- With preferences still loading or a read failure, orchestration waits. A retry
  reloads preferences without clearing the draft.
- Invalid stored data requires a valid replacement instead of silently selecting
  a potentially automatic mode.

An explicit selection immediately flushes the existing settings store. Requests
are serialized, updates queued during a write are retained, and an older failure
does not roll back a newer choice. A failed latest write restores the last confirmed
value and exposes an error. Other controls retain their existing save debounce.

No default is written merely by opening chat. No database migration, new endpoint,
browser-storage fallback, or new administrator setting is required. Existing plans,
the classic interface, countdown duration, and the Orchestrate toggle are unchanged.

## Files changed

| File | Responsibility |
| --- | --- |
| `application/v2_ui/src/components/chat/Composer.tsx` | Account preference selection, loading/retry, save feedback, and submission guards |
| `application/v2_ui/src/lib/orchestrationApproval.ts` | Typed mode validation and administrator/user precedence |
| `application/v2_ui/src/lib/userSettings.ts` | Optional preference type and writable-key declaration |
| `application/v2_ui/src/stores/userSettingsStore.ts` | Serialized writes, immediate flush, and pending-aware rollback |
| `application/single_app/route_backend_users.py` | Allowlist and approval enum validation |
| `application/single_app/config.py` | Application version increment to 0.261.101 |
| `ui_tests/fixtures/orchestration/harness_entry.tsx` | Real-store navigation coverage and removal of a duplicate import that prevented bundling |

## Validation

| Regression coverage | What it exercises |
| --- | --- |
| `functional_tests/test_v2_orchestration_approval_persistence.py` | Current-user route round-trips, partial updates, missing values, invalid input, storage failures, and the real Node runtime suite |
| `functional_tests/test_v2_orchestration_approval_logic.mjs` | Mode precedence, debounce, serialized flushes, both failed-write rollback cases, unrelated preference preservation, and read retry |
| `ui_tests/test_v2_orchestration_approval_persistence.py` | Real Composer interactions on desktop/mobile, navigation, fresh contexts, delayed saves, loading failure/retry, administrator enforcement, and existing-plan isolation |
| `functional_tests/test_v2_settings_and_workspace_tags.py` | Existing preference behavior with the corrected pending-aware rollback contract |

The API cases isolate storage and authentication dependencies around the real route
body. Browser cases use the real components and stores with a persistent HTTP fixture;
fresh browser contexts prove restoration comes from the settings API, not retained
browser memory. These tests do not provision Azure resources or invoke live models.
The shared Playwright connection supports either local Chromium or a configured
Azure Playwright workspace.

| User action | Before | After |
| --- | --- | --- |
| Choose Review, leave chat, return | Administrator default | Saved Review choice |
| Reload or use another device | Administrator default | Last successfully saved account choice |
| Administrator changes the default | Local choice replaced | Saved choice retained while overrides are allowed |
| Administrator temporarily disables overrides | Default enforced | Default enforced; saved choice available when overrides return |
| Preferences fail to load | Could run using the deployment default | Draft retained; orchestration waits for retry |
| An older save fails after a newer choice | Could restore an outdated value | Newer choice retained; latest failure restores the confirmed value |

Persistence is acknowledged only after the server accepts a write. Closing the
browser before acknowledgement is not a durability guarantee, and live cross-tab
preference synchronization is outside this fix.

## Related documentation

- [Chat Orchestration](../features/CHAT_ORCHESTRATION.md)
- [Orchestration settings](../../admin/orchestration.md)
- [Chat interface controls](../../reference/chat-controls.md)
