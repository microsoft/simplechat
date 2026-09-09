---
applyTo: '**/*.py'
---

# Python Language Guide

- All files MUST start with a comment of the file name. Ex: `# functions_personal_agents.py`

## Rule: Follow Standard Python Conventions

- Standard python conventions, such as the use of snake case, must be followed.

## Rule: Imports Must Be Organized and at the Top of the File !IMPORTANT

- Group imports after the module docstring by default. Before moving or adding any import, trace the dependency chain and initialization timing. Do not mechanically hoist a local import: that can turn a deferred dependency into a startup failure. Local imports require a concrete lifecycle or performance justification.

## Rule: Preserve Settings and Bootstrap Dependency Boundaries

- A local import delays execution; it does **not** remove a cycle in the dependency graph. Never claim a cycle is fixed merely because the import moved inside a function, or hide it with `try/except ImportError`, `getattr`, or a success-shaped fallback.
- `config.py` constructs Azure clients and imports logging. Treat `config`, `functions_settings`, logging, cache modules, and Redis/Key Vault helpers as a startup dependency chain, not interchangeable utility modules.
- Configure cache/client behavior from the **settings object already supplied by the caller**. Do not import `config`, `cosmos_settings_container`, or another settings owner back into a lower-level cache helper to rediscover that configuration.
- Pass storage handles, factories, and logging callbacks explicitly from the owning settings/bootstrap layer. Keep those runtime objects separate from the settings dictionary: never persist them, copy them into Redis settings payloads, or pass them to the browser.
- Keep `app_settings_cache.py` and `app_settings_store.py` below their owners in the dependency graph. Neither may directly or transitively import `config`, `functions_settings`, `functions_appinsights`, or the configuration-dependent Redis factory. The web app and scheduler supply the factory; the settings owner supplies initialized storage dependencies.
- Use `import app_settings_cache` and module-qualified access for dynamically configured accessors. Importing an accessor by value can retain the pre-initialization `None` or an obsolete implementation.
- On bootstrap changes, inspect both normal web startup and the scheduler, Redis-enabled/disabled/error paths, and calls that occur before initialization. An uninitialized accessor must not silently import its owner or initialize cloud resources.
- Validate with real-module cold imports in fresh processes and blocked network access, plus static dependency checks that include function-local imports. Stub external I/O, not the module boundary under test. Compilation and AST-extracted function tests alone do not prove import safety.

## Rule: Indentation, Logging, and Decorators
- Use 4 spaces per indentation level. No tabs.

- Code and definitions should occur after the imports block.

- All logging should use tag-based prefixes. Ex: `[GPT_CLIENT]` or `[SK_LOADER]` to identify the source of the log message and make it easier to trace. Tags should be enclosed in square brackets and MUST use `UPPERCASE_WITH_UNDERSCORES`. Tags should be generalized to the operation that is occurring. Prefer static tags; move dynamic values into the message body or `extra` metadata instead of embedding them inside the bracketed tag. Any existing logging that is missing tags should have tags added. When adding or renaming a logging tag, update `docs/reference/logging-tags.md` in the same change so the reference inventory stays current.

- Always import `log_event` from `functions_appinsights.py` for any logging activities.

- All files MUST use the `log_event` function from `functions_appinsights.py` for production-type logging activities. Ensure that all log events include relevant contextual information as properties to facilitate effective monitoring and troubleshooting. Messages returned to the client should not contain sensitive information, but should be informative enough to understand the context of the event.

- Prefer using `log_event` from functions_appinsights.py for production-type logging activites.

- Use `log_event` from functions_appinsights.py with debug_only=True for debug logging purposes. All method, calls, warnings and errors should be debug_logged. 

- Files with routes MUST import `from swagger_wrapper import swagger_route, get_auth_security` and use the `@swagger_route(security=get_auth_security())` decorator for all route functions.

- New Flask routes MUST be registered on a `Blueprint`, not directly on `app`. Use `Blueprint(...).route(...)` or pass a `Blueprint` into the route module registrar. Do not add new `@app.route(...)` routes except for a reviewed framework/bootstrap exception.

- Each route-owning Blueprint MUST have an explicit `before_request` security policy using the shared helpers in `functions_authentication.py`, such as `login_required_blueprint()`, `user_required_blueprint()`, `admin_required_blueprint()`, or `external_api_required_blueprint()`. Mixed-policy Blueprints may use a login-only Blueprint guard and keep stricter route-specific decorators such as `@user_required`, `@admin_required`, `@control_center_required(...)`, `@feedback_admin_required`, or `@safety_violation_admin_required` on individual routes.

- Every route change MUST update or verify the route coverage tests in `functional_tests/route_tests/`. At minimum, run `python functional_tests/route_tests/test_route_blueprint_policy_inventory.py`, `python functional_tests/route_tests/test_route_unauthenticated_policy_contract.py`, and `python functional_tests/route_tests/test_route_policy_test_coverage.py` after adding, moving, or changing routes.

- When editing group workspace content, always use the `assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin", "DocumentManager", "User"))` function to verify the user's current membership and role in the group before allowing access to group-scoped resources or operations. This ensures that users cannot access or modify group content based solely on a potentially stale or tampered `activeGroupOid` reference. Roles should vary based on the level of access required for the operation, but should always include "Owner" and "Admin" as allowed roles.

- Unless otherwise indicated, all protected routes MUST be covered by a Blueprint-level login policy and/or an explicit route-level `@login_required` decorator. Public and external bearer-token routes must be listed in the route policy tests with their expected unauthenticated behavior.

- Always use f-strings for string interpolation. Ex: `f"User ID: {user_id}"` instead of `"User ID: {}".format(user_id)"`

- Never use `except:` without specifying the exception type. Always catch specific exceptions or use `except Exception as ex:` to capture the exception details. This also avoids accidentally catching system-exiting exceptions like `KeyboardInterrupt` or `SystemExit`.

- Never return raw exception text to browser or API clients. Do not use `str(e)`, `str(exc)`, `repr(e)`, traceback text, SDK exception messages, connection strings, or provider errors in `jsonify()`, template rendering, streaming responses, or other client-visible payloads. Log exception type and safe contextual metadata server-side with `log_event` or `debug_print`, then return a stable user-safe message such as `"Invalid request."`, `"Unable to save action."`, or `"Unable to store secrets in Key Vault."`
