# Interface preference saves with no personal agents

Fixed in version: **0.261.449**, recorded in `application/single_app/config.py`.

## Issue and root cause

An account with `settings.agents = []` and no selected agent could not save a
preference through `/api/user/settings`. The shared settings writer indexed the
first agent before checking whether one existed. That raised `IndexError` and
returned a failed-save response, preventing the new interface switch from
persisting on otherwise valid accounts.

## Technical details

`application/single_app/functions_settings.py` now selects the first personal
agent only when the list is nonempty. An empty list follows the existing no-agent
selection branch. Agent creation, global-agent fallback, authorization, write
metadata and cache invalidation remain unchanged.

## Validation and impact

`functional_tests/test_ui_interface_selection.py` exercises the real settings
route and writer using installed-SDK Cosmos responses, with empty personal agent
lists. Normal and optimized Python probes confirm that a valid preference is
durable, survives a new session, remains account-specific, and is not changed
when persistence fails.

Before the fix, the valid save returned HTTP 500. After it, the same request
returns HTTP 200 and a subsequent read contains the saved interface preference.
See [Interface selection](../features/UI_INTERFACE_SELECTION.md) for user behavior.
