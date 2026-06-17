---
description: "Use when: auditing SimpleChat agents, Semantic Kernel plugins, tool calls, actions, workflows, external APIs, prompt/tool injection boundaries, or plugin-scoped authorization."
name: "Plugin Tool And Agent Security Audit"
argument-hint: "Target plugin/action/agent/workflow files, tool names, feature area, scan only, or fix findings"
agent: "agent"
---

# Plugin Tool And Agent Security Audit

Audit SimpleChat agent, plugin, action, tool-call, workflow, and external API integration code for authorization, injection, data leakage, unsafe tool execution, and cross-scope access issues.

Use the repository guardrails in [.github/instructions/broken-access-control-prevention.instructions.md](../instructions/broken-access-control-prevention.instructions.md), [.github/instructions/xss-prevention.instructions.md](../instructions/xss-prevention.instructions.md), [.github/instructions/python-lang.instructions.md](../instructions/python-lang.instructions.md), and [.github/copilot-instructions.md](../copilot-instructions.md).

## Operating Rules

- Work in the SimpleChat repository root.
- Treat model output, tool arguments, plugin responses, action configuration, OpenAPI specs, user prompts, active scope settings, and stored agent/action records as untrusted.
- Do not revert unrelated user changes.
- If the user asks for `scan only` or `stop after plan`, do not edit files.
- If fixing findings, preserve existing agent/action behavior and keep scope changes explicit.

## Baseline Discovery

1. Confirm the repo root, current branch, and concise `git status --short`.
2. Inventory plugin, tool, action, workflow, and agent surfaces:

```powershell
rg -n "@kernel_function|KernelFunction|semantic_kernel|plugin|tool_call|tool choice|function_call|OpenAPI|operationId|action|agent|workflow|run_workflow|invoke|execute|external" application/single_app
```

3. Search for caller-controlled scope and identity arguments:

```powershell
rg -n "user_id|conversation_id|message_id|group_id|public_workspace_id|scope_id|scope_type|activeGroupOid|activePublicWorkspaceOid|owner|participant|membership" application/single_app/semantic_kernel_plugins application/single_app/functions_* application/single_app/route_backend_*.py
```

4. Search for external calls, dynamic execution, and sensitive plugin sinks:

```powershell
rg -n "requests\.|aiohttp|httpx|subprocess|shell=True|eval\(|exec\(|open\(|read_item|query_items|upsert_item|delete_item|download_blob|upload_blob|Graph|graph|Authorization|headers" application/single_app
```

5. Run the broken access control checker where useful:

```powershell
python scripts/check_broken_access_control.py --full-file <target-python-files>
```

## Manual Audit Checklist

Review these areas:

- Semantic Kernel `@kernel_function` parameters that expose `user_id`, `conversation_id`, `group_id`, `public_workspace_id`, `scope_id`, `scope_type`, file/document IDs, or owner IDs.
- Whether tool-call scope arguments are rebound to the authorized request context with helpers such as `_resolve_authorized_scope_arguments(...)`, `_resolve_blob_location_with_fallback(...)`, `_resolve_authorized_fact_memory_call(...)`, `require_active_group(...)`, or `require_active_public_workspace(...)` before storage, search, blob, or Graph access.
- OpenAPI/plugin actions that allow arbitrary URLs, headers, auth schemes, operation IDs, or request bodies from user-controlled configuration.
- External API calls that may leak secrets, authorization headers, prompts, document content, user data, or internal endpoints.
- Prompt/tool injection risks where model output can select tools, override scope, exfiltrate context, or trigger unintended mutations.
- Workflow runners that persist, replay, or mirror tool results across personal, group, public, or collaboration conversations.
- Plugin/action enablement, admin management routes, disabled global records, selected agents/actions, and user visibility boundaries.
- Plugin logs, citations, thought records, activity records, and telemetry that may expose sensitive inputs or tool responses.
- Tool results rendered in the browser as markdown, HTML, citations, maps, tables, charts, images, videos, or generated artifacts.
- Long-running or retrying tool calls that could amplify side effects, duplicate writes, or bypass approval gates.

## Triage And Plan

Group findings before editing:

- `Critical`: A tool or agent can access, mutate, or exfiltrate another user’s data, execute arbitrary external calls with secrets, or bypass admin/user authorization.
- `Important`: Tool arguments, action configuration, workflow scope, or model output can influence sensitive reads, writes, or network calls without explicit validation.
- `Moderate`: Logs, citations, telemetry, retries, or rendering paths expose sensitive tool data or create confusing authorization boundaries.
- `Low`: False positives, static-only tool metadata, reviewed exceptions, or unreachable legacy paths.

For each finding, record:

- Agent/plugin/action/workflow surface and file path.
- Untrusted input source.
- Sensitive sink or side effect.
- Missing authorization, validation, prompt boundary, or sanitizer.
- Realistic impact.
- Remediation approach.
- Minimum regression test.

## Remediation Patterns

Use these fixes by default:

- Rebind identity and scope parameters to authenticated request context before sensitive operations.
- Validate group/public workspace membership and object ownership at the storage/blob/search/Graph boundary.
- Deny or normalize arbitrary URL, header, and auth configuration for external actions.
- Keep secrets server-side; never expose action credentials or auth headers to model-visible content or browser responses.
- Separate model-visible summaries from raw tool responses when sensitive data exists.
- Make mutations idempotent or guarded against retry side effects.
- Render tool output with the same XSS-safe patterns used elsewhere.
- Add focused functional tests for scope isolation, disabled action/agent behavior, external call validation, or rendered tool output.

## Verification

After fixing, run the narrowest reliable checks:

- `python -m py_compile <changed-python-files>`.
- Relevant functional tests under `functional_tests/`.
- `python scripts/check_broken_access_control.py --full-file <changed-python-files>` for authorization-sensitive changes.
- `python scripts/check_xss_sinks.py --full-file <changed browser files/routes>` when plugin output rendering changed.
- Relevant UI tests when agent/action/workflow browser behavior changed.
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`.

If a check cannot run locally, explain why and include the remaining risk.

## Output Expectations

Return findings first, ordered by severity. Include scope scanned, tools and plugins reviewed, files changed, validation commands run, skipped checks, false positives, and remaining risks.