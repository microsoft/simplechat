# Orchestrate Model Picker Placement and Persistence Fix

**Version: 0.261.137** (tracked in `application/single_app/config.py`)

**Fixed in version: 0.261.137**

## Issue

In the V2 composer, switching on **Orchestrate** made the model picker jump out of the
toolbar and appear above the message box as a separate **Auto - choose per step**
control. Every other manual choice (documents, web, agent, prompt, reasoning) folds
behind **Manual controls** while orchestrating, so the one picker that did not changed
the toolbar's shape and sat next to the unrelated **Auto** approval choice.

Choosing **Auto - choose per step** also did not stick. Leaving the chat and coming back,
or opening a new chat from another page, reset the picker to a specific model, so Auto
had to be chosen again for every visit.

A related problem affected the normal chat model: after choosing a model, leaving the
chat and returning could restore the model that was selected when the page first loaded.

## Root cause

- **Placement:** the orchestration picker was rendered outside the Manual controls row,
  above the composer, whenever Orchestrate was on.
- **Auto reset:** the Auto choice and any pinned orchestration model were held only in
  the composer's component state (`useState`). Any remount of the composer discarded them
  and fell back to a specific model.
- **Normal model snap-back:** on mount, the composer restored the model from the
  bootstrap payload's `initial_model_selection`. The bootstrap resolves that once, when
  it is fetched, so a model chosen later in the same session was newer in the settings
  store than in the payload.

## Resolution

| Area | Change |
| --- | --- |
| Placement | The orchestration picker renders in the normal model picker's slot inside Manual controls. The above-input picker is removed. |
| Default | **Auto - choose per step** is the default wherever a catalog model is eligible for Auto: an unarchived catalog profile rated suitable or strong for general answering, text generation, and a supported API, matching the server's candidate filter. Every plan ends with a general answering step, so a catalog without a general-rated model could not be planned under Auto. Where no model qualifies, Auto is not offered and a specific model is used. |
| Persistence | The choice is saved to the account as `orchestrationModelRouting` (`auto` or `manual`) and `orchestrationPreferredModelId` (a catalog selection key), and read back on every render. It survives remounts, reloads, and other devices. |
| Separation | A model pinned for Orchestrate does not change `preferredModelId`, the normal chat model. |
| Hidden controls | When an administrator turns off **Keep The Manual Composer Controls Available**, the picker is unreachable, so saved pins are ignored and the default applies. |
| Loading | While preferences are loading and the picker is reachable, orchestrated sends wait, so a saved pin is never replaced by the default on a fast first send. A failed load does not block sending. |
| Normal model | On mount, the composer prefers the settings store's `preferredModelId` when it names a catalog model, and otherwise uses the bootstrap selection. |

The settings route whitelists the two new keys. It accepts only `auto` or `manual` for
the routing value, and a stripped, printable selection key of at most 512 characters for
the pinned model. Anything else rejects the whole update with 400. The stored key only
selects an option in the user's own picker; every orchestrated request still authorizes
the model it names on the server.

## Files

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/orchestrationModelRouting.ts` | New resolver for Auto availability, defaults, pins, and picker values. |
| `application/v2_ui/src/components/chat/Composer.tsx` | Picker moved under Manual controls, preference-backed choice, send gating, and normal-model restore. |
| `application/v2_ui/src/lib/userSettings.ts` | Typed and writable preference keys. |
| `application/single_app/route_backend_users.py` | Whitelist and validation for the two keys. |

## Validation

- `functional_tests/test_v2_orchestration_model_routing_preference.py` exercises the real
  settings route: round trips, rejected values, per-user scoping, and absent defaults. It
  also runs `functional_tests/test_v2_orchestration_model_routing_logic.mjs` against the
  real resolver.
- `ui_tests/test_v2_orchestration_model_picker.py` drives the real Composer, router, and
  settings store at desktop and mobile widths. It covers:
  - the picker's placement under Manual controls;
  - Auto as the default;
  - Auto and pinned choices surviving leaving the chat, a reload, and a fresh browser
    context;
  - Auto not being offered when no model has a catalog profile, or when no profile is
    rated for general answering;
  - hidden Manual controls ignoring a saved pin;
  - an Orchestrate pin leaving the normal chat model alone;
  - the normal chat model surviving a remount with a stale bootstrap;
  - sends waiting for a saved pin to load.
- `ui_tests/test_model_catalog_management.py` and `ui_tests/test_v2_orchestration_composer.py`
  check the new placement and default. The existing reasoning, approval-persistence,
  context-selection, prompt-composer, and saved-analysis UI suites pass unchanged.

## Related

- [Chat controls](../../reference/chat-controls.md)
- [Choose models for orchestration](../../guides/model-catalog-routing.md)
- [Chat orchestration](../features/CHAT_ORCHESTRATION.md)
- [Gather / Reason / Render harness](../features/ORCHESTRATION_RENDERING_HARNESS.md)
