---
description: "Use when: auditing SimpleChat Flask routes for missing or incorrect @login_required, @user_required, @admin_required, specialized admin decorators, Swagger auth metadata, or decorator order."
name: "Route Authentication Audit"
argument-hint: "Target route files, endpoint prefixes, changed files, or route names to audit"
agent: "agent"
---

Audit the requested SimpleChat Flask routes for Blueprint-level runtime authentication, route-specific role authorization, and Swagger metadata coverage. Treat `@swagger_route(security=get_auth_security())` as OpenAPI metadata only; it does not enforce authentication at runtime.

Use the repository route and access-control guardrails in [.github/copilot-instructions.md](../copilot-instructions.md), [.github/instructions/python-lang.instructions.md](../instructions/python-lang.instructions.md), and [.github/instructions/broken-access-control-prevention.instructions.md](../instructions/broken-access-control-prevention.instructions.md). Use [scripts/check_swagger_routes.py](../../scripts/check_swagger_routes.py) and [scripts/check_broken_access_control.py](../../scripts/check_broken_access_control.py) where useful, but do not stop at deterministic checker output.

## Expected Route Patterns

- Every Flask route must be registered on a `Blueprint`. New `@app.route(...)` routes are not allowed except for a reviewed framework/bootstrap exception.
- Every route-owning Blueprint must have an explicit `before_request` policy using helpers such as `login_required_blueprint()`, `user_required_blueprint()`, `admin_required_blueprint()`, or `external_api_required_blueprint()`.
- Every Flask route must include `@swagger_route(security=get_auth_security())` immediately after the route decorator unless the route has a reviewed exception.
- Most non-admin application API routes should be covered by `user_required_blueprint()` or by a login-only Blueprint guard plus route-level `@user_required` before the view function runs.
- Admin-namespaced or admin-only routes should be covered by `admin_required_blueprint()` or by a login-only Blueprint guard plus `@admin_required`, `@control_center_required(...)`, `@feedback_admin_required`, or `@safety_violation_admin_required` where the codebase already uses that role boundary.
- Group, public workspace, conversation, document, user profile, and plugin/action routes still need object-level authorization at the sensitive read or mutation boundary. Role decorators are not enough for object access.
- Feature flags such as `@enabled_required(...)`, Swagger metadata, frontend-only visibility, and route names are not substitutes for runtime auth decorators.
- Public routes should be rare and explicit. Validate likely public exceptions against nearby files and app behavior, such as health probes, static assets, login/auth callbacks, and external API bearer-token routes. Public, login-only, admin, and external bearer routes must be represented in `functional_tests/route_tests/`.

## Audit Workflow

1. Identify all Flask route functions in the target files, including routes registered on Blueprints and routes inside route registrar functions.
2. Record each route path, HTTP method, endpoint function, Blueprint name, Blueprint `before_request` policy, and route decorator stack in source order.
3. Classify each route as public, authenticated user, login-only, admin, specialized admin, external API, or unclear.
4. Compare the Blueprint policy and route decorator stack against nearby routes in the same file and similar feature areas. Prefer local conventions over generic assumptions.
5. Flag routes that are not on a Blueprint, Blueprints without a `before_request` auth policy, protected routes missing a login boundary, routes with only `login_required` where the surrounding user-facing API pattern expects `user_required`, or admin functionality without an admin/specialized admin boundary.
6. For routes using object IDs from path, query, body, session settings, or plugin arguments, call out any missing ownership, membership, or relationship validation separately from Blueprint/decorator coverage.
7. Update or verify `functional_tests/route_tests/test_route_blueprint_policy_inventory.py`, `functional_tests/route_tests/test_route_unauthenticated_policy_contract.py`, and `functional_tests/route_tests/test_route_policy_test_coverage.py` for any new, removed, moved, or policy-changed route.
8. Recommend the smallest remediation and the minimum regression test that would fail before the fix and pass after.

## Output Format

Return findings first, ordered by severity. For each finding include:

- `Severity`: Critical, Important, Moderate, or Low.
- `Route`: HTTP method and path.
- `Function`: file path and function name.
- `Blueprint Policy`: Blueprint name and `before_request` auth policy, or missing.
- `Current Decorators`: runtime auth decorators currently present.
- `Expected Policy`: the Blueprint/route pattern that should be used.
- `Impact`: what anonymous, non-user, or non-admin callers could do or learn.
- `Remediation`: exact decorator or object-level check to add.
- `Regression Test`: focused test coverage to prevent recurrence, including route policy tests under `functional_tests/route_tests/` when route coverage changes.

If no issues are found, say that clearly and list any routes intentionally left public or login-only with the reason they are acceptable.
