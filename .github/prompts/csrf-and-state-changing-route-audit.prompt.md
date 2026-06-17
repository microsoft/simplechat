---
description: "Use when: auditing SimpleChat state-changing Flask routes for CSRF, unsafe HTTP methods, content-type assumptions, same-site/session risks, or mutation endpoints reachable through browser requests."
name: "CSRF And State Changing Route Audit"
argument-hint: "Target route files, endpoint prefixes, changed files, scan only, or fix findings"
agent: "agent"
---

# CSRF And State Changing Route Audit

Audit SimpleChat state-changing Flask routes for CSRF exposure, unsafe HTTP methods, content-type assumptions, browser-triggerable mutations, and session boundary risks.

Use the repository guardrails in [.github/copilot-instructions.md](../copilot-instructions.md), [.github/instructions/python-lang.instructions.md](../instructions/python-lang.instructions.md), [.github/instructions/broken-access-control-prevention.instructions.md](../instructions/broken-access-control-prevention.instructions.md), and [.github/instructions/santize_settings_for_frontend_routes.instructions.md](../instructions/santize_settings_for_frontend_routes.instructions.md). This prompt complements route authentication and broken access control audits; it does not replace object-level authorization review.

## Operating Rules

- Work in the SimpleChat repository root.
- Treat POST, PUT, PATCH, DELETE, and any GET route with side effects as state-changing.
- Treat browser cookies and Easy Auth sessions as ambient authority that may be sent automatically by the browser.
- Do not revert unrelated user changes.
- If the user asks for `scan only` or `stop after plan`, do not edit files.
- If fixing findings, keep route behavior compatible with existing clients where possible and add focused tests.

## Baseline Discovery

1. Confirm the repo root, current branch, and concise `git status --short`.
2. Inventory Flask routes and methods:

```powershell
rg -n "@app\.route|Blueprint\(|\.route\(|methods=|request\.(json|get_json|form|args|files)|session\[|session\." application/single_app/route_*.py application/single_app/*.py
```

3. Search for mutation verbs and side-effect helpers:

```powershell
rg -n "methods=\[.*(POST|PUT|PATCH|DELETE)|create_|update_|delete_|save_|set_|enable_|disable_|archive_|approve_|reject_|upload|download|run_|execute_|send_|start_|stop_|clear_|reset_" application/single_app
```

4. Search for GET routes that may mutate state:

```powershell
rg -n "@app\.route\([^\n]+methods=\[.*GET|@app\.route\([^\n]+\)" application/single_app/route_*.py application/single_app/*.py
```

Then inspect matched GET handlers for calls to create/update/delete/save/set/write/send/run/execute helpers.

5. Search for CSRF-related helpers and tokens:

```powershell
rg -n "CSRF|csrf|WTF_CSRF|csrf_token|X-CSRF|SameSite|SESSION_COOKIE|CORS|Access-Control-Allow|Origin|Referer" application deployers docs .github
```

6. Run existing route and access-control checkers where useful:

```powershell
python scripts/check_swagger_routes.py <target-route-files>
python scripts/check_broken_access_control.py --full-file <target-python-files>
```

## Manual Audit Checklist

Review these areas:

- Routes using GET for writes, state transitions, active workspace changes, downloads with side effects, task starts, deletes, approvals, admin toggles, workflow starts, or plugin/action execution.
- State-changing routes that accept form posts, JSON, multipart uploads, query-string mutation parameters, or hidden fields.
- Whether browser-callable mutations rely only on cookies/session without CSRF token, Origin/Referer validation, SameSite assumptions, or another explicit anti-CSRF boundary.
- Routes intended for external APIs or webhooks that use bearer tokens, API keys, Easy Auth headers, or public callbacks instead of browser session cookies.
- Content-Type assumptions: routes that call `request.get_json()` without checking JSON, accept `text/plain` or form-encoded bodies unexpectedly, or mutate based on query args.
- Admin-only mutations exposed through browser forms or fetch calls.
- CORS headers and preflight behavior that could allow cross-origin credentialed requests.
- Idempotency and retry behavior for workflow starts, file operations, plugin calls, notifications, and external sends.
- Settings updates, active scope writes, and session writes triggered by user-controlled IDs.

## Triage And Plan

Group findings before editing:

- `Critical`: Cross-site browser requests can trigger sensitive admin or user mutations using ambient session credentials.
- `Important`: State-changing routes lack a clear anti-CSRF boundary, use unsafe methods, or accept query/form data in risky ways.
- `Moderate`: Content-type validation, SameSite/CORS assumptions, retry/idempotency, or external callback boundaries are unclear.
- `Low`: False positives, non-browser external API routes with strong bearer auth, read-only routes, or reviewed exceptions.

For each finding, record:

- HTTP method and route path.
- Function and file path.
- Mutation or side effect.
- Existing auth, object authorization, and CSRF-related boundary.
- Missing guard or unsafe assumption.
- Realistic impact.
- Remediation approach.
- Minimum regression test.

## Remediation Patterns

Use these fixes by default:

- Move mutations off GET routes where compatible.
- Require JSON or multipart content types explicitly for API mutations as appropriate.
- Add or reuse CSRF token validation for browser-session form/fetch mutations where the app pattern supports it.
- For non-browser external routes, require explicit bearer/API authentication and avoid session-cookie authorization.
- Validate `Origin` or `Referer` only as a defense-in-depth measure, not as the sole boundary unless that is the established local pattern.
- Keep object-level authorization checks at the mutation boundary.
- Make retries idempotent or require operation IDs for side-effect-heavy workflows.
- Add functional tests for unsafe method rejection, missing token rejection, or external-auth-only behavior.

## Verification

After fixing, run the narrowest reliable checks:

- `python -m py_compile <changed-python-files>`.
- Relevant functional tests under `functional_tests/`.
- `python scripts/check_swagger_routes.py <changed-route-files>` for changed route files.
- `python scripts/check_broken_access_control.py --full-file <changed-python-files>` when object authorization is involved.
- Relevant UI tests when browser forms or fetch behavior changed.
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

If a check cannot run locally, explain why and include the remaining risk.

## Output Expectations

Return findings first, ordered by severity. Include routes intentionally left public or external, any CSRF assumptions, files changed, validation commands run, skipped checks, and remaining risks.