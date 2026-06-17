---
description: "Use when: auditing SimpleChat logs, App Insights telemetry, activity logs, plugin logs, exports, traces, errors, or diagnostics for privacy, PII, prompt/content, token, or secret exposure."
name: "Privacy Logging And Telemetry Audit"
argument-hint: "Target paths, log surface, activity type, export flow, scan only, or fix findings"
agent: "agent"
---

# Privacy Logging And Telemetry Audit

Audit SimpleChat logging, telemetry, activity records, plugin logs, traces, diagnostics, exports, and error handling for privacy and sensitive-data exposure.

Use the repository guardrails in [.github/instructions/santize_settings_for_frontend_routes.instructions.md](../instructions/santize_settings_for_frontend_routes.instructions.md), [.github/instructions/broken-access-control-prevention.instructions.md](../instructions/broken-access-control-prevention.instructions.md), [.github/instructions/python-lang.instructions.md](../instructions/python-lang.instructions.md), and [.github/copilot-instructions.md](../copilot-instructions.md).

## Operating Rules

- Work in the SimpleChat repository root.
- Treat user prompts, chat messages, document text, uploaded content, generated outputs, profile fields, emails, IDs, headers, tokens, settings, and tool responses as sensitive unless explicitly intended for that log audience.
- Do not revert unrelated user changes.
- If the user asks for `scan only` or `stop after plan`, do not edit files.
- If fixing findings, preserve useful diagnostics while minimizing sensitive payloads.
- Prefer `log_event(...)` from `functions_appinsights.py` and existing activity/plugin logging helpers over ad hoc logging.

## Baseline Discovery

1. Confirm the repo root, current branch, and concise `git status --short`.
2. Inventory logging and telemetry calls:

```powershell
rg -n "log_event\(|logging\.|logger\.|print\(|traceback|AppInsights|Application Insights|activity_log|activity_logs|plugin_log|plugin_logging|thought|telemetry|diagnostic|debug|error|exception" application functional_tests scripts deployers
```

3. Search for likely sensitive fields near logs, exports, and diagnostics:

```powershell
rg -n -i "prompt|message|content|document|chunk|summary|citation|email|user_id|object_id|authorization|cookie|token|secret|password|api[_-]?key|connection[_ -]?string|headers|settings|request\.|response\." application/single_app
```

4. Search export and admin-view surfaces:

```powershell
rg -n "export|download|csv|json|xlsx|docx|pdf|report|activity|control_center|admin|audit|history|trace" application/single_app docs functional_tests
```

5. Search for broad serialization of request, response, settings, or exception objects:

```powershell
rg -n "vars\(|__dict__|json\.dumps\(|asdict\(|model_dump\(|dict\(|request\.headers|request\.cookies|request\.environ|os\.environ|str\(.*exception|repr\(" application/single_app
```

## Manual Audit Checklist

Review these areas:

- `log_event(...)` custom properties and messages for secrets, tokens, headers, cookies, settings, connection strings, prompts, document text, or full tool responses.
- Activity logs and admin views for user-visible privacy boundaries, searchability, retention expectations, and unnecessary PII.
- Plugin invocation logs, thought records, workflow activity, agent citations, and generated artifacts that may store raw external responses or sensitive context.
- Exception handlers and error responses that expose stack traces, request payloads, service errors, internal endpoints, IDs, or secrets.
- Export flows that package chat history, logs, citations, metadata, activity, or diagnostics with more data than the user/admin should receive.
- Debug flags, environment-controlled diagnostics, and support endpoints that can be enabled in production.
- PII fields such as display names, emails, Entra IDs, group memberships, profile images, IP addresses, document names, and workspace names.
- Whether logs include enough correlation IDs and coarse event names after redaction to remain useful.

## Triage And Plan

Group findings before editing:

- `Critical`: Secrets, tokens, connection strings, authorization headers, or raw private content are logged or exported to a broad audience.
- `Important`: Sensitive user, document, prompt, or tool data is logged by default without clear need or masking.
- `Moderate`: Debug diagnostics, admin views, error responses, or exports are overbroad but role-restricted or environment-limited.
- `Low`: False positives, placeholders, reviewed diagnostic fields, or coarse metadata that is necessary and proportionate.

For each finding, record:

- File and logging/export surface.
- Sensitive source.
- Audience and storage sink.
- Existing redaction or role boundary.
- Missing minimization, masking, or authorization.
- Realistic impact.
- Remediation approach.
- Minimum regression test.

## Remediation Patterns

Use these fixes by default:

- Log event names, IDs, counts, durations, statuses, and coarse categories instead of raw payloads.
- Redact secrets, headers, cookies, tokens, connection strings, and SAS URLs before logging.
- Truncate long prompt, document, tool, or service-response previews and avoid logging full content by default.
- Use stable correlation IDs rather than full user/profile payloads when possible.
- Keep admin exports role-protected and scoped to explicit filters.
- Sanitize settings before frontend diagnostics unless it is an admin route that deliberately requires raw settings.
- Add tests for redaction helpers, log payload construction, export field filtering, or error response shape.

## Verification

After fixing, run the narrowest reliable checks:

- `python -m py_compile <changed-python-files>`.
- Relevant functional tests under `functional_tests/`.
- Targeted `rg` searches from the discovery section for changed areas.
- `python scripts/check_broken_access_control.py --full-file <changed-python-files>` when log/export access control changed.
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

If a check cannot run locally, explain why and include the remaining risk.

## Output Expectations

Return findings first, ordered by severity. Include log and export surfaces reviewed, files changed, redaction/minimization patterns used, validation commands run, skipped checks, false positives, and remaining risks.