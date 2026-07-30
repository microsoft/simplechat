---
applyTo: '**/*.py'
---

# Python Language Guide

- All files MUST start with a comment of the file name. Ex: `# functions_personal_agents.py`

## Rule: Follow Standard Python Conventions

- Standard python conventions, such as the use of snake case, must be followed.

## Rule: Imports Must Be Organized and at the Top of the File !IMPORTANT

- IMPORTANT: `from` and `import` statements MUST be grouped at the top of the document after the module docstring, unless otherwise indicated by the code writer or for performance reasons in which case the import should be as close as possible to the usage with a comment explaining why the import is not at the top of the file. CodeQL hammers us on this in the findings. If you find imports that are not at the top of the file, move them to the top and add a comment if there is a reason they cannot be moved. This also helps prevent multuple imports of the same module in different places which can lead to confusion and maintenance issues.

## Rule: Indentation, Logging, and Decorators
- Use 4 spaces per indentation level. No tabs.

- Code and definitions should occur after the imports block.

- All logging should used tag based prefixes. Ex: [GPTClient] or [SKLoader] to identify the source of the log message and make it easier to trace. Tags should be enclosed in square brackets. Tags should be generalized to the operation that is occurring. Any existins logging that is missing tags should have tags added.

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
