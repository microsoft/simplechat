# V2 Reasoning Effort Persistence Fix

## Issue

In the V2 chat interface the reasoning level did not stick. Choosing **Medium** for a model,
navigating to another page and coming back showed the picker empty again, and the request
went out with whatever the model's absence of a setting implied rather than the level that
had been chosen. Switching between models lost it in the same way: there was no per-model
memory, so a level chosen for one model was either carried to the next or gone.

The model picker appeared to behave, which made the reasoning picker look like the odd one
out. It was not: the model was not being saved either.

**Fixed in version:** 0.261.034

## Root cause

Two separate omissions with the same shape.

**The reasoning level was never persisted.** It lived in `Composer.tsx` local component
state:

```tsx
const [options, setOptions] = useState<ComposerOptions>({ ... });
```

Nothing read it from `/api/user/settings` and nothing wrote it back, so remounting the
composer — which is what navigating away and returning does — reset it.

**The model was never persisted either.** `/api/v2/bootstrap` returns
`initial_model_selection`, which `_build_initial_chat_model_selection` resolves from the
`preferredModelId` and `preferredModelDeployment` user settings. V2 read that value but never
wrote those keys, so it was restoring whatever the classic interface had last saved, or
falling back to the first entry in the catalog. It looked persistent only for as long as the
chosen model happened to match one of those.

A third defect followed from the first. Because the level was never cleared when the model
changed, choosing `high` on `gpt-5` and then switching to `gpt-4o` — a model with no
reasoning at all — still sent `reasoning_effort: "high"`. The control disappeared from the
toolbar while its value stayed in the request for the endpoint to strip.

The classic interface had already solved all of this. `chat-reasoning.js` keeps a per-model
map in the `reasoningEffortSettings` user setting, and `chat-messages.js` saves
`preferredModelId` when the picker changes. Both keys were already in `allowed_keys` in
`route_backend_users.py`, so **no backend change was needed**.

## The fix

The level in effect is now derived rather than remembered, and the inputs it is derived from
are stored:

- `resolveReasoningEffort(modelName, saved)` reproduces
  `getCurrentModelReasoningEffort()`: `high` for `gpt-5-pro`, the stored level when the
  current model still accepts it, otherwise `low` when supported, otherwise the model's first
  supported level.
- `reasoningModelKey(model)` decides how a model is keyed in the shared map, preferring the
  model id over the deployment name exactly as `getCurrentModelName()` does. The order is not
  cosmetic: it is what makes a level chosen in one interface visible in the other, and it is
  what stops a deployment an administrator named `chat-prod` from being read as a model with
  unknown reasoning support when its model id is `gpt-5-mini`.
- A model that offers no choice now resolves to no level at all, so nothing stale is sent to
  a model that rejects it.
- `requestReasoningEffort()` suppresses `none` on both the send and retry paths, matching
  `getCurrentReasoningEffort()`, which returns null for it.
- Choosing a level writes it into `reasoningEffortSettings` through the existing debounced
  settings store, which reverts the control if the write fails.
- Choosing a model writes `preferredModelId` (the catalog selection key, which is what the
  server matches on) and `preferredModelDeployment` (its fallback when the selection key no
  longer resolves).

The reasoning picker is no longer clearable. Every model now has an effective level, and
`None` is already an explicit option for the families that support it, so a separate "no
value" state would only mean "fall back to the default" — which the picker cannot show.

On a single-endpoint deployment there is no model catalog and therefore no model identity.
Nothing is derived there — the offered levels would be a guess, and a default would attach a
`reasoning_effort` to every request that the user never asked for. The control stays opt-in
and clearable for the session, exactly as it was, and the picker is only made non-clearable
once a model is known and a level is genuinely always in effect.

A level chosen before the settings have arrived is held and written once they do. This
setting is a map rather than a scalar and the route stores it whole, while the app renders as
soon as the bootstrap resolves — not necessarily after the settings have loaded. Merging into
a map that had not been read would replace every other model's level, including levels set in
the classic interface. Dropping the choice instead would reproduce the very defect being
fixed, so it is queued rather than discarded, and the write reads the map as it stands at that
moment rather than as it was when the choice was made. If the settings load failed outright
there is no map to merge into at all, and the user is told the level applies to this session
only rather than left to discover it later.

## Behaviour change

A reasoning-capable model with nothing stored now shows and sends its default level — `low`
for most families, `none` for the 5.1 series, `high` for `gpt-5-pro` — where V2 previously
sent nothing. This is what the classic interface has always done; the two now agree.

This applies only where V2 has a model catalog, which means
`enable_multi_model_endpoints` is on. A single-endpoint deployment is unchanged: no level is
sent unless one is chosen, and a choice lasts for the session. V2 does not yet build a model
picker for that configuration, so it has no model name to key a stored level on.

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/lib/reasoning.ts` | `reasoningModelKey`, `resolveReasoningEffort`, `requestReasoningEffort`, `ReasoningEffortSettings` |
| `application/v2_ui/src/lib/userSettings.ts` | Declared the three shared keys and added them to `WRITABLE_USER_SETTING_KEYS` |
| `application/v2_ui/src/components/chat/Composer.tsx` | Reads the stored map, resolves the level per model, clears it for models with no choice, writes the level and the model selection |
| `application/v2_ui/src/stores/chatStore.ts` | `none` suppressed on the send and retry paths |
| `application/single_app/config.py` | Version to 0.261.034 |
| `functional_tests/test_v2_reasoning_effort_persistence.py` | New test |
| `functional_tests/test_v2_reasoning_effort_logic.mjs` | New runtime test |

No route or storage change was required.

## Validation

`functional_tests/test_v2_reasoning_effort_persistence.py` asserts that all three settings
keys are declared by the client and present in the route's whitelist, that the storage key
still matches `getCurrentModelName()`, that the composer reads the map and writes back into
it, that the effort is cleared for a model with no reasoning, that the model selection is
saved as the selection key the bootstrap matches on, and that both request paths go through
`requestReasoningEffort`.

`functional_tests/test_v2_reasoning_effort_logic.mjs` executes the resolution itself against
the real module, covering the cases whose failures are silent: a level restored for its own
model, a level not following the user to another model, a stored level the new model does not
accept being discarded, the per-family defaults, `gpt-5-pro` overriding whatever was stored,
and `none` never being sent.

| Check | Before | After |
|---|---|---|
| Choose Medium, leave the page, return | Picker empty | Medium |
| Choose High on `gpt-5`, switch to `o3` | High carried over | `o3`'s own level, or its default |
| Choose High on `gpt-5`, switch to `gpt-4o` | `reasoning_effort: "high"` still sent | Nothing sent |
| Choose `None` where supported | `"none"` sent | Parameter omitted |
| Choose a model, reload | Server default, often a different model | The chosen model |
| Choose a level before preferences finish loading | Lost | Held and written when they arrive |
| Single-endpoint deployment | Nothing sent unless chosen | Unchanged |

Results: 7/7 Python tests and 14/14 runtime checks pass, alongside `npm run typecheck` and
the existing V2, reasoning and settings suites.

## Related

- Feature documentation: `docs/explanation/features/REACT_V2_UI.md`
- Classic implementation: `application/single_app/static/js/chat/chat-reasoning.js`
