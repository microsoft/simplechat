# Route Blueprint Security Policies

Implemented in version: **0.242.069**

## Overview

SimpleChat routes are now organized behind explicit Flask Blueprint security policies. The route migration centralizes runtime authentication at the Blueprint boundary while preserving existing route-level role checks and object-level authorization helpers.

## Purpose

The change reduces the risk of adding a route without a runtime authentication boundary. New route work must register routes on a Blueprint, apply an explicit `before_request` auth policy, and keep route policy tests updated.

## Dependencies

- `application/single_app/functions_authentication.py`
- `application/single_app/app.py`
- `functional_tests/route_tests/test_route_blueprint_policy_inventory.py`
- `functional_tests/route_tests/test_route_unauthenticated_policy_contract.py`
- `functional_tests/route_tests/test_route_policy_test_coverage.py`
- `.github/workflows/swagger-route-check.yml`
- `.github/instructions/python-lang.instructions.md`
- `.github/prompts/route-authentication-audit.prompt.md`

## Technical Specifications

### Blueprint Auth Helpers

`functions_authentication.py` provides shared Blueprint guard factories:

- `login_required_blueprint()`
- `user_required_blueprint()`
- `admin_required_blueprint()`
- `external_api_required_blueprint()`
- `apply_blueprint_auth(...)` for specialized composition

These helpers compose the existing route decorators as a `before_request` guard, so runtime behavior stays aligned with existing `@login_required`, `@user_required`, `@admin_required`, and `@accesstoken_required` semantics.

### Route Registration

Route modules now register routes on a Blueprint instead of directly on the Flask app. `app.py` uses `register_route_blueprint(...)` for registrar-based modules and directly registers a few local Blueprints for public app pages, session heartbeat, and debug-admin routes.

Existing mixed-policy route modules keep stricter route-level decorators where needed. Examples include Control Center, feedback admin, safety admin, approvals, file sync, workspace identities, and Custom Pages.

### Custom Pages

Custom Pages remain login-required at the host-route level. Page metadata roles continue to apply inside the Custom Pages dispatcher, allowing authenticated-only pages and future governance work without forcing every custom page through `user_required`.

### Route Policy Tests

The route policy tests enforce three contracts:

1. Every route is on a Blueprint or a reviewed explicit policy surface.
2. Every route has an expected unauthenticated behavior: public, login-only, user, admin/specialized admin, or external bearer-token.
3. The route policy tests cover the same route set and are referenced by repo instructions/prompts.

## Usage Instructions

When adding or changing routes:

1. Register the route on a Blueprint.
2. Apply a Blueprint `before_request` guard using the shared auth helpers.
3. Keep route-level decorators for stricter role or feature-specific checks.
4. Update `functional_tests/route_tests/` if the route set, route path, or policy category changes.
5. Run:

```powershell
python functional_tests/route_tests/test_route_blueprint_policy_inventory.py
python functional_tests/route_tests/test_route_unauthenticated_policy_contract.py
python functional_tests/route_tests/test_route_policy_test_coverage.py
python scripts/check_swagger_routes.py <changed-route-files>
```

## Testing and Validation

Validation for this implementation included:

- Route policy inventory tests
- Unauthenticated route policy contract tests
- Route policy coverage meta-test
- Broken access control guardrail self-test
- Swagger route validation
- Python syntax compilation
- `git diff --check`

Runtime app import requires valid local configuration and Cosmos credentials; static route validation does not depend on live service credentials.
