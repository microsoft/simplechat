---
description: "Use when: auditing SimpleChat for settings, secrets, credentials, connection strings, tokens, API keys, or raw configuration exposure in routes, templates, JSON APIs, logs, docs, and tests."
name: "Settings And Secrets Exposure Audit"
argument-hint: "Target paths, changed files, setting names, suspected leak, scan only, or fix findings"
agent: "agent"
---

# Settings And Secrets Exposure Audit

Audit SimpleChat for accidental disclosure of secrets, credentials, raw settings, environment values, connection strings, tokens, API keys, or internal configuration details.

Use the repository guardrails in [.github/instructions/santize_settings_for_frontend_routes.instructions.md](../instructions/santize_settings_for_frontend_routes.instructions.md), [.github/instructions/python-lang.instructions.md](../instructions/python-lang.instructions.md), and [.github/copilot-instructions.md](../copilot-instructions.md). Admin routes are allowed to use raw settings for admin functionality, but still review whether secrets are unnecessarily rendered, logged, serialized to JavaScript, included in downloads, or exposed through browser-inspectable markup.

## Operating Rules

- Work in the SimpleChat repository root.
- Treat settings, environment values, credentials, tokens, and service endpoints as sensitive unless the code proves they are public-safe display values.
- Do not revert unrelated user changes.
- If the user asks for `scan only` or `stop after plan`, do not edit files.
- If the user asks to fix findings, make focused changes and preserve admin behavior.
- Prefer existing helpers such as `sanitize_settings_for_user(...)`, `get_settings()`, `log_event(...)`, and local masking patterns over new abstractions.

## Baseline Discovery

1. Confirm the repo root, current branch, and concise `git status --short`.
2. Identify settings and configuration flow:

```powershell
rg -n "get_settings\(|sanitize_settings_for_user\(|update_settings\(|app_settings|settings\s*=|render_template\(|jsonify\(" application/single_app
```

3. Search for likely secret terms in application code, templates, docs, tests, deployers, and scripts:

```powershell
rg -n -i "api[_-]?key|secret|password|passwd|pwd|token|bearer|credential|connection[_ -]?string|client[_-]?secret|private[_-]?key|account[_-]?key|sas[_-]?token|instrumentation[_-]?key" application docs functional_tests ui_tests deployers scripts .github
```

4. Search for logging, print, telemetry, error, and export surfaces that might serialize sensitive values:

```powershell
rg -n "log_event\(|logging\.|logger\.|print\(|traceback|json\.dumps\(|Response\(|send_file\(|make_response\(|download|export" application/single_app functional_tests scripts
```

5. Search frontend templates and JavaScript for settings embedded into browser-visible variables or attributes:

```powershell
rg -n "tojson|app_settings|settings|window\.|data-[A-Za-z0-9_-]+=|localStorage|sessionStorage" application/single_app/templates application/single_app/static
```

## Manual Audit Checklist

Review these areas:

- Non-admin routes that call `get_settings()` and pass settings into `render_template(...)` or `jsonify(...)` without `sanitize_settings_for_user(...)`.
- Admin routes that render raw settings into unnecessary hidden fields, JavaScript globals, data attributes, logs, exports, or downloadable artifacts.
- API responses that return full configuration objects when only a few public display values are needed.
- Error responses, exception handlers, tracebacks, debug endpoints, health endpoints, and diagnostics that include settings, environment variables, request headers, tokens, or service responses.
- `log_event(...)`, plugin logs, activity logs, App Insights properties, workflow activity, and audit logs that include prompts, headers, authorization tokens, keys, connection strings, or full request/response payloads.
- Documentation, examples, tests, fixtures, session files, generated artifacts, and deployer outputs that may contain real secrets.
- Client storage such as `localStorage` or `sessionStorage` that may persist secrets or raw settings.

Treat these as high-risk values:

- Azure OpenAI, Azure AI Search, Cosmos DB, Blob Storage, Key Vault, Speech, Document Intelligence, Redis, SQL, PostgreSQL, MySQL, Tableau, Microsoft Graph, App Insights, and Entra credentials.
- `Authorization`, `Cookie`, `x-ms-*`, OAuth tokens, MSAL cache values, session IDs, Flask secrets, SAS URLs, private keys, and connection strings.

## Triage And Plan

Group findings before editing:

- `Critical`: A secret, token, connection string, or credential can reach an unauthenticated user, normal user, browser markup, JavaScript, public docs, logs available to broad roles, or repository history.
- `Important`: Raw settings or internal endpoints are exposed to authenticated users or admin browser surfaces without a clear need.
- `Moderate`: Overbroad logging, verbose diagnostics, test fixtures, or exports could expose sensitive data in common development or support workflows.
- `Low`: False positives, placeholders, documented dummy values, or admin-only display with masking and clear need.

For each finding, record:

- File and function/template/component.
- Sensitive source.
- Exposure sink.
- Existing guard or why it is insufficient.
- Remediation approach.
- Minimum regression test or deterministic check.

## Remediation Patterns

Use these fixes by default:

- Sanitize settings with `sanitize_settings_for_user(...)` before non-admin `render_template(...)` or `jsonify(...)` responses.
- Pass only the exact public fields a route needs instead of whole settings objects.
- Mask secrets before admin display, telemetry, logs, exports, or diagnostics when raw values are not required.
- Redact `Authorization`, cookies, tokens, passwords, keys, connection strings, and SAS query values from logs and errors.
- Avoid persisting secrets in browser storage, hidden fields, or data attributes.
- Replace real secrets in docs/tests with obvious placeholders.
- Add focused tests for any fixed route, log sanitizer, or redaction helper.

## Verification

After fixing, run the narrowest reliable checks:

- `python -m py_compile <changed-python-files>` for changed Python files.
- Relevant functional tests for modified routes or helpers.
- `python scripts/check_xss_sinks.py --full-file <changed application browser files>` when browser rendering changes are involved.
- Targeted `rg` searches from the discovery section for changed areas.
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

If a check cannot run locally, explain why and include the remaining risk.

## Output Expectations

Return findings first, ordered by severity. Include false positives and reviewed exceptions. When complete, report scope scanned, files changed, redaction or sanitization patterns used, validation commands run, skipped checks, and remaining risks.