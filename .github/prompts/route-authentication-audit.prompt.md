---
description: "Use when: auditing SimpleChat Flask routes for missing or incorrect @login_required, @user_required, @admin_required, specialized admin decorators, Swagger auth metadata, or decorator order."
name: "Route Authentication Audit"
argument-hint: "Target route files, endpoint prefixes, changed files, or route names to audit"
agent: "agent"
---

Audit the requested SimpleChat Flask routes for runtime authentication and role authorization decorator coverage. Treat `@swagger_route(security=get_auth_security())` as OpenAPI metadata only; it does not enforce authentication at runtime.

Use the repository route and access-control guardrails in [.github/copilot-instructions.md](../copilot-instructions.md), [.github/instructions/python-lang.instructions.md](../instructions/python-lang.instructions.md), and [.github/instructions/broken-access-control-prevention.instructions.md](../instructions/broken-access-control-prevention.instructions.md). Use [scripts/check_swagger_routes.py](../../scripts/check_swagger_routes.py) and [scripts/check_broken_access_control.py](../../scripts/check_broken_access_control.py) where useful, but do not stop at deterministic checker output.

## Expected Route Patterns

- Every Flask route must include `@swagger_route(security=get_auth_security())` immediately after the route decorator unless the route has a reviewed exception.
- Most non-admin application API routes should use `@login_required` followed by `@user_required` before the view function runs.
- Admin-namespaced or admin-only routes should use `@login_required` followed by `@admin_required`, or a more specific admin decorator such as `@feedback_admin_required` or `@safety_violation_admin_required` when the codebase already uses that role boundary.
- Group, public workspace, conversation, document, user profile, and plugin/action routes still need object-level authorization at the sensitive read or mutation boundary. Role decorators are not enough for object access.
- Feature flags such as `@enabled_required(...)`, Swagger metadata, frontend-only visibility, and route names are not substitutes for runtime auth decorators.
- Public routes should be rare and explicit. Validate likely public exceptions against nearby files and app behavior, such as health probes, static assets, login/auth callbacks, external API bearer-token routes, and documentation endpoints.

## Audit Workflow

1. Identify all Flask route functions in the target files, including routes registered on blueprints and routes inside `register_route_backend_*` functions.
2. Record each route path, HTTP method, endpoint function, and decorator stack in source order.
3. Classify each route as public, authenticated user, admin, specialized admin, external API, or unclear.
4. Compare the decorator stack against nearby routes in the same file and similar feature areas. Prefer local conventions over generic assumptions.
5. Flag routes that are missing runtime authentication, have only `@login_required` where the surrounding user-facing API pattern expects `@user_required`, or expose admin functionality without an admin decorator.
6. For each protected route, check that `@login_required` appears before role decorators in the source so unauthenticated API callers receive the login boundary before role checks.
7. For routes using object IDs from path, query, body, session settings, or plugin arguments, call out any missing ownership, membership, or relationship validation separately from decorator coverage.
8. Recommend the smallest remediation and the minimum regression test that would fail before the fix and pass after.

## Output Format

Return findings first, ordered by severity. For each finding include:

- `Severity`: Critical, Important, Moderate, or Low.
- `Route`: HTTP method and path.
- `Function`: file path and function name.
- `Current Decorators`: runtime auth decorators currently present.
- `Expected Decorators`: the route pattern that should be used.
- `Impact`: what anonymous, non-user, or non-admin callers could do or learn.
- `Remediation`: exact decorator or object-level check to add.
- `Regression Test`: focused test coverage to prevent recurrence.

If no issues are found, say that clearly and list any routes intentionally left public or login-only with the reason they are acceptable.