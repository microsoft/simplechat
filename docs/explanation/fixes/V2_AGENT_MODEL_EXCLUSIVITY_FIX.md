# V2 Agent / Model Exclusivity Fix

**Fixed in version: 0.261.034**

## Issue

In the V2 chat composer the **Model**, **Agent** and **Reasoning** pickers were all
independently live. Selecting an agent left a model showing as selected and left a reasoning
level selectable, even though an agent can act on neither. The interface offered two choices
that had no effect, with nothing to indicate which one was actually in force.

## Root cause

Two halves, one visible and one not.

### The controls were never told about each other

`Composer.tsx` rendered the model picker on `gating.showModelPicker` (false only during image
generation) and the reasoning picker on model support alone. Neither consulted the agent
selection, so all three stayed live together.

They are not independent. An agent answers with its own deployment:

```python
# semantic_kernel_loader.py
deployment = agent.get("azure_openai_gpt_deployment")
```

and `reasoning_effort` only ever reaches the direct-model call parameters, through
`_resolve_reasoning_effort_for_model` into `api_params` / `stream_params` in
`route_backend_chats.py`. Under an agent, both controls are inert.

### The request sent both halves, which the server reads as an override

`chatStore.sendMessage` assigned the model identity unconditionally and then appended
`agent_info` and `reasoning_effort` after it, so V2 posted all three at once. The route only
lets an agent request choose its own model when no model identity was sent:

```python
# route_backend_chats.py
should_use_default_model = (
    _has_chat_agent_selection(request_agent_info)
    and settings.get('enable_multi_model_endpoints', False)
    and not data.get('model_id')
    and not data.get('model_endpoint_id')
)
```

Because V2 always sent `model_id` and `model_endpoint_id`, that branch never fired. The route
has agent-without-a-model handling for every configuration — the multi-endpoint default, the
first APIM deployment, and the configured default model — and V2 reached none of it.

### Note on the classic client

V1 has the same asymmetry and posts a model alongside an agent too: `getCurrentAgentSelection`
checks that agent mode is active, but `getCurrentModelSelection` reads the model select
without checking that agent mode has hidden it. Suppressing the fields is therefore a
deliberate divergence from V1, not a parity break, and `test_v2_agent_model_exclusivity.py`
pins that asymmetry so the decision is revisited if V1 changes.

## Behaviour after the fix

- Selecting an agent renders the model picker as its plain `Model` placeholder in muted
  styling, with a tooltip naming the agent that supplies the model. The picker stays
  **clickable**, and the menu still marks the retained model so it is visible what returns.
- Choosing a model clears the agent, because the two cannot both apply.
- Choosing an agent **retains** the model selection rather than clearing it; it is simply not
  in force, and it comes back the moment the agent is cleared.
- The reasoning picker is hidden while an agent is selected. It is also hidden during image
  generation, matching `updateReasoningButtonVisibility` in `static/js/chat/chat-reasoning.js`.
- With an agent selected, the request carries `agent_info` and nothing else — no
  `model_deployment`, `model_id`, `model_endpoint_id`, `model_provider` or `reasoning_effort`.

## Files modified

| File | Change |
|------|--------|
| `application/v2_ui/src/lib/chatRequestSelection.ts` | **New.** `buildSelectionFields()` and `hasResolvableAgent()` — the single source of the agent-wins rule. |
| `application/v2_ui/src/lib/composerGating.ts` | Added `agentActive` input; added `modelPickerInactive` and `showReasoning` outputs. |
| `application/v2_ui/src/components/ui/Dropdown.tsx` | Added `inactive` (retained-but-overridden trigger state) and an explicit `title` tooltip. |
| `application/v2_ui/src/components/chat/Composer.tsx` | Wires the rule into the toolbar; choosing a model clears the agent; reasoning picker gated on `showReasoning`. |
| `application/v2_ui/src/stores/chatStore.ts` | `sendMessage` and `retryMessage` both build routing fields through `buildSelectionFields`. |
| `application/single_app/config.py` | `VERSION` `0.261.033` → `0.261.034`. |

### Why `inactive` is not `disabled`

The overridden model picker has to stay usable, because clicking it is how the user leaves
agent mode. It keeps its real `aria-haspopup` / `aria-expanded` semantics and stays keyboard
reachable; only its label and opacity change. A `disabled` control would have been a dead end.

### Why the rule is a module rather than JSX

The original bug arose precisely because "an agent wins" was written nowhere: the toolbar and
the request builder each made their own decision and drifted apart. `buildSelectionFields` is
what both now read, so the payload cannot disagree with what the user is being shown.

## Testing

| Test | Covers |
|------|--------|
| `functional_tests/test_v2_agent_model_exclusivity.py` | Establishes the server's contract first (the `should_use_default_model` condition, the APIM agent fallback, where `reasoning_effort` lands), then asserts the client honours it. Also runs the logic checks below. |
| `functional_tests/test_v2_agent_model_exclusivity_logic.ts` | 27 behavioural checks of `buildSelectionFields` and `resolveGating`, bundled with esbuild and run under node. |

Validation performed:

```powershell
cd application\v2_ui; npm run typecheck          # clean
cd functional_tests
python test_v2_agent_model_exclusivity.py        # 9/9, 27 logic checks
python test_v2_model_identity_and_scope.py       # 9/9
python test_v2_chat_phase1_fixes.py              # 10/10
python test_v2_conversation_details_and_gating.py # 9/9
python test_v2_api_payload_shapes.py             # 6/6
python test_v2_dropdown_placement.py             # 6/6
```

The exclusivity test was verified against a deliberately reintroduced defect: making
`buildSelectionFields` emit `agent_info` alongside the model identity fails three checks
(`an agent selection sends no model identity at all`, `an agent selection sends no reasoning
level`, `nothing but agent_info is sent for an agent`).

### Existing tests updated

Three assertions in existing tests checked for a literal call site that has moved into the
shared rule. They were updated to follow the indirection rather than relaxed — each still
asserts the same guarantee, now in the module that owns it:

- `test_v2_model_identity_and_scope.py` — `test_client_sends_the_whole_model_identity` and
  `test_retry_resolves_the_model_the_same_way`.
- `test_v2_chat_phase1_fixes.py` — `test_agent_selection_is_sent_as_agent_info`.

## Before / after

| Situation | Before | After |
|-----------|--------|-------|
| Agent selected, model picker | Shows a model as selected and in force | Shows `Model`, muted, tooltip names the agent; selection retained |
| Agent selected, reasoning picker | Shown and selectable | Hidden |
| Agent selected, request body | `agent_info` + four model fields + `reasoning_effort` | `agent_info` only |
| Agent selected, server model resolution | Agent default-model handling skipped | Agent default-model handling runs |
| Picking a model while an agent is selected | Both remain selected | Agent is cleared |
| Clearing the agent | — | Previous model and reasoning level return |

## Known limitations

Image generation hides the model picker but leaves the agent picker visible, and the classic
client forces `image_generation = false` when an agent is explicitly tagged
(`chat-messages.js`). That is the same family of inconsistency but a separate decision, and it
is deliberately left unchanged here.

`retryMessage` is still invoked with no options from `MessageActions.tsx`, so a retry uses
server defaults rather than the composer's current selection. That gap predates this change;
routing retry through `buildSelectionFields` means it cannot reintroduce the conflict when it
is eventually wired up.
