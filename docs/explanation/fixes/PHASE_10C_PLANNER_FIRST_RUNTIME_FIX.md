# Phase 10C Planner-First Runtime Fix

Fixed in version: **0.250.077**

Associated issue: **[#1021](https://github.com/microsoft/simplechat/issues/1021)**

## Issue

Assist could invoke the model planner, receive an opaque `client_error`, and
then continue through deterministic capability classification. The user saw a
direct or heuristic result instead of the intended short first model call and
governed capability choice. Incomplete administrator endpoint/model IDs also
disabled the planner rather than using the model selected for the chat turn.
The Admin panel exposed the global endpoint and model IDs as free-form text.

## Root Cause

The Azure/OpenAI request profile still included provider-sensitive optional
parameters without a bounded compatibility sequence or safe diagnostic class.
Assist cleared some deterministic output only after the classifiers and
automatic matching had already run. Model-source normalization treated an
incomplete configured pair as a reason to turn planning off, and the Admin UI
did not bind model choices to the selected enabled global endpoint.

## Technical Changes

- `application/single_app/functions_chat_capability_planner.py`
  - Uses `max_completion_tokens` and minimal reasoning for the first fast call.
  - Tries strict JSON schema first, then bounded optional-field and JSON-object
    compatibility variants only for classified HTTP 400 rejections.
  - Emits only bounded transport error classes and variant indexes; prompts,
    provider messages, endpoints, credentials, and raw responses remain absent.
- `application/single_app/route_backend_chats.py`
  - Uses the exact turn-selected client and deployment unless both configured
    global IDs are complete.
  - Builds the authorized inventory in Assist without invoking built-in or
    governed-agent heuristic classifiers, creating automatic capability IDs,
    or restoring a deterministic recommendation after planner failure.
- `application/single_app/functions_chat_capabilities.py` and
  `application/single_app/functions_settings.py`
  - Keep Assist activation planner-owned and normalize incomplete configured
    model selection to `same_as_chat` while preserving the selected mode.
- `application/single_app/templates/admin_settings.html`,
  `application/single_app/static/js/admin/admin_settings.js`, and
  `application/single_app/static/js/admin/admin_model_endpoints.js`
  - Replace raw ID inputs with dependent enabled global endpoint/model selects.
  - Rebuild options with inert DOM APIs and preserve current unsaved selections
    when the endpoint catalog emits an update.
- Planner, activation, route, and Admin UI tests cover exact model fallback,
  global-only resolution, transport fallback, safe diagnostics, planner-only
  Assist, and dependent selector behavior.

## Impact

Assist now performs one bounded non-executing planner call before deciding
whether to answer directly, ask one structured clarification, or show a
server-authored capability choice. Planner failure grants and suggests nothing;
explicitly selected capabilities remain the only baseline. Shadow remains
observational and can still compare the planner with the deterministic control.
The model never receives authorization or execution authority.

## Validation

- Canonical Phase 9/10 compile, functional, route-policy, and UI-contract gate:
  **352 passed, 11 skipped**.
- Full-file broken-access-control checker: **17 files passed**.
- Full-file XSS checker: **19 files passed**.
- Focused route/Admin selector slice: **11 passed, 2 skipped**.
- Changed Python and JavaScript files compile or parse successfully, with no VS
  Code diagnostics.
- A live non-executing probe through the exact server-resolved chat model
  returned `propose` in **4.017 seconds**, recommending Deep Research and
  offering Web Search as the alternative through the bounded JSON-object
  fallback. No capability executed.

The application version in `application/single_app/config.py` was updated to
`0.250.077` for this correction.