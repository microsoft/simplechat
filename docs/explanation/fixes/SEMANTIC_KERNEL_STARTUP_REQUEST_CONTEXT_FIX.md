# Semantic Kernel Startup Request Context Fix (v0.260.023)

Fixed/Implemented in version: **0.260.023**

Refs: [#1327](https://github.com/microsoft/simplechat/issues/1327)

## Issue Summary

Starting SimpleChat directly with `python application/single_app/app.py` (including via `uv run`)
aborted at startup with:

```
RuntimeError: Working outside of request context.
```

The failure only appeared once at least one action had been assigned to an agent and saved. Before any
action was assigned, the same configuration started normally, which made the problem look intermittent.

Container and App Service deployments were unaffected, because they use the gunicorn entrypoint
(`ENTRYPOINT ["python3", "-m", "gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]`). The
`if __name__ == '__main__':` block never runs there, so initialization happens through the
`@app.before_request` hook, where a request context exists.

## Root Cause

`initialize_application(force=True)` runs at module scope in the direct-run path, outside any Flask
request context. With Semantic Kernel enabled and `per_user_semantic_kernel` disabled, that reaches
global agent loading:

`initialize_semantic_kernel()` -> `load_semantic_kernel()` -> `load_single_agent_for_kernel()`

Inside `load_single_agent_for_kernel`, the `if agent_config.get("actions_to_load"):` branch called
`get_current_user_id()` without a guard. That function reads the Flask `session` proxy, which raises
`RuntimeError` when there is no request context, so startup aborted.

The `actions_to_load` branch is what introduced the failing call, which is why the crash only began
after an action was attached to an agent and persisted.

The equivalent lookup in `load_plugins_for_kernel` was already wrapped in `try/except` with a `None`
fallback. That inconsistency is why global plugin loading succeeded earlier in the same startup
sequence while agent-specific plugin loading failed.

Three further identity lookups in the same module had the same latent defect. They are not reached in a
global-agent-only configuration, but they would fail the same way in per-user and group scopes.

## Files Modified

- `application/single_app/functions_authentication.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/config.py`
- `functional_tests/test_semantic_kernel_startup_without_request_context.py` (new)

## Code Changes Summary

1. Added `get_current_user_id_or_none()` to `functions_authentication.py`. It returns `None` when
   `has_request_context()` is false and otherwise delegates to `get_current_user_id()`. `flask` is now
   imported explicitly for `has_request_context` rather than relying on the `config` star-import.

2. Left `get_current_user_id()` unchanged. Authorization callers must keep failing loudly when there is
   no request context, so the fallback is deliberately opt-in at each call site rather than applied
   globally. `has_request_context()` is the established pattern for this across the codebase.

3. Routed all five identity lookups in `semantic_kernel_loader.py` through the new helper:

   | Location | Change |
   |---|---|
   | `load_single_agent_for_kernel` agent plugin loading | The reported crash. Now resolves through the safe helper. |
   | `resolve_agent_config.get_group_scope_id` | Resolves the identity first and returns an empty scope with the existing warning when it is absent. |
   | `resolve_agent_config.get_agent_model_endpoint_candidates` | Skips personal endpoint collection when no identity is available. |
   | `resolve_agent_config.resolve_foundry_endpoint_config` | Skips personal endpoint collection when no identity is available. |
   | `load_plugins_for_kernel` | Replaced the ad-hoc `try/except` with the shared helper. |

4. Short-circuited the group and personal endpoint lookups instead of passing an unresolved identity
   downstream. `require_active_group()` and `get_user_settings()` perform Cosmos reads keyed on the user
   id, so forwarding `None` would only have traded the `RuntimeError` for a Cosmos lookup error.

## Behavior

Startup now completes in the direct-run path. The kernel and agent plugins load with no resolved user
identity, the same way global plugin loading already did.

Hosted deployments are unaffected. The fallback only applies when there is no request context at all;
inside a request the identity resolves exactly as before, including returning `None` for an
unauthenticated request.

## Validation

`functional_tests/test_semantic_kernel_startup_without_request_context.py` covers both halves of the fix:

- **Behavioral.** `get_current_user_id()` still raises `RuntimeError` outside a request context, so the
  fail-loud property authorization code depends on is preserved. `get_current_user_id_or_none()` returns
  `None` outside a request context, resolves the session `oid` inside an authenticated request, and
  returns `None` for an unauthenticated request.
- **Structural.** An AST pass over `semantic_kernel_loader.py` asserts the module imports the safe helper,
  makes no direct `get_current_user_id()` call, and never passes an identity call straight into
  `require_active_group()` or `get_user_settings()`.

Both structural rules were verified to fail when the original defect is reintroduced, so the test is a
genuine regression guard rather than a restatement of the current source:

- Restoring the unguarded call reports `must not call get_current_user_id() directly; found at line(s) [1941]`.
- Passing the identity straight into `require_active_group()` reports the leaked-argument violation.

Result with the fix applied: `3/3 tests passed`.

The behavioral half stubs `config`, `functions_settings`, `functions_appinsights`, and `functions_debug`
in `sys.modules`, because importing the real `config` builds live Azure Cosmos clients at import time.
The stub re-exports the same Flask names `config.py` re-exports, since `functions_authentication` reaches
`session` through `from config import *`.

## Impact

- Local development works for configurations that assign actions to agents. Previously the only
  workarounds were removing every agent action or running gunicorn locally.
- The three latent call sites are fixed alongside the reported one, so per-user and group scopes cannot
  fail the same way from a non-request caller.
- Plugin and endpoint loading no longer depends on a request-scoped identity being present when the
  identity is only optional context.
