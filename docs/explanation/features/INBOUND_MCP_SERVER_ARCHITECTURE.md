# Inbound SimpleChat MCP Server Architecture

Current documentation version: **0.250.098**

Related configuration version: `application\single_app\config.py` currently sets `VERSION = "0.250.098"`.

## Overview

The inbound SimpleChat Model Context Protocol (MCP) server exposes a small, governed, delegated personal-workspace tool surface to approved MCP clients. It is implemented inside the main Flask application so it can reuse SimpleChat authentication, app settings, governance, authorization, workflow, logging, and rate-limit infrastructure.

The current implementation is intentionally limited to:

- streamable HTTP JSON-RPC;
- tools only;
- delegated personal-workspace access;
- source-first governance;
- safe telemetry and bounded responses.

It does not expose full SimpleChat feature parity, group/public/all-scope tools, prompt/resource MCP surfaces, server-initiated SSE, or durable MCP sessions.

## Key Files

```text
application\single_app\route_inbound_mcp.py
application\single_app\functions_mcp_server_auth.py
application\single_app\functions_mcp_server_config.py
application\single_app\functions_mcp_server_enterprise.py
application\single_app\functions_mcp_server_governance.py
application\single_app\functions_mcp_server_registry.py
application\single_app\functions_mcp_server_tools.py
application\single_app\templates\admin_settings.html
application\single_app\static\js\admin\admin_settings.js
application\single_app\static\js\admin\admin_governance.js
```

## Route Contract

| Route | Purpose | Current behavior |
| --- | --- | --- |
| `GET /.well-known/oauth-protected-resource` | Protected Resource Metadata discovery | Public metadata for OAuth-capable MCP clients. |
| `GET /.well-known/oauth-protected-resource/api/mcp` | PRM alias for `/api/mcp` clients | Public metadata alias. |
| `GET /.well-known/oauth-protected-resource/mcp` | Legacy PRM alias | Public metadata alias. |
| `GET /.well-known/oauth-authorization-server` | SimpleChat-hosted OAuth metadata bridge | Returns Entra authorize/token metadata derived from safe tenant configuration. |
| `GET /api/mcp/health` | Easy Auth exclusion reachability check | Reaches SimpleChat and returns an unauthenticated JSON response when no bearer token is supplied. |
| `GET /api/mcp` | Streamable HTTP GET/SSE probe | Returns `405 Method Not Allowed`; server-initiated SSE is not implemented. |
| `POST /api/mcp` | MCP JSON-RPC endpoint | Handles `initialize`, `notifications/initialized`, `tools/list`, and `tools/call`. |

All Flask routes must keep the standard `@swagger_route(security=get_auth_security())` decorator.

## Protocol Behavior

Current JSON-RPC methods:

| Method | Response |
| --- | --- |
| `initialize` | `200 application/json`; negotiates supported protocol version and advertises tools capability only. |
| `notifications/initialized` | `202 Accepted`; notification-only response with no body. |
| `tools/list` | `200 application/json`; returns implemented tools allowed by source governance for the caller. |
| `tools/call` | `200 application/json` for tool results or JSON-RPC tool errors; error data includes support correlation metadata. |

Supported protocol versions:

```text
2025-11-25
2025-06-18
2025-03-26
```

The server is stateless. It does not return `MCP-Session-Id`, does not persist per-client MCP session state, and does not advertise prompts, resources, tasks, SSE resumability, or server-to-client notifications.

## Runtime Settings

Inbound MCP runtime configuration is stored in the Cosmos-backed `app_settings` document and normalized through `functions_mcp_server_config.py`.

| Setting | Default | Purpose |
| --- | --- | --- |
| `enable_inbound_mcp_server` | `false` | Enables or disables the inbound MCP endpoint. |
| `inbound_mcp_required_user_role` | `InboundMCPUserAccess` | Delegated user app role required for personal tools. |
| `inbound_mcp_required_app_role` | `InboundMCPAppAccess` | Reserved for future app-only tools. |
| `inbound_mcp_required_scope` | `DelegatedMcpServerAccess` | Delegated OAuth scope required for interactive MCP clients. |
| `inbound_mcp_allowed_client_app_entries` | `[]` | Approved caller application IDs with optional descriptions. |
| `inbound_mcp_allow_external_tenants` | `false` | Controls whether tenants beyond the SimpleChat tenant can be accepted. |
| `inbound_mcp_allowed_tenant_entries` | current tenant plus admin entries | Approved tenant IDs with optional descriptions. |
| `inbound_mcp_allow_all_source_ids` | `true` | Runtime source allowlist mode. |
| `inbound_mcp_allowed_source_entries` | `[{ "value": "*", "description": "Allow all inbound MCP source IDs" }]` | Accepted source IDs with optional descriptions. |
| `inbound_mcp_source_header` | `X-SimpleChat-MCP-Source` | Header used to resolve the caller-provided source signal. |
| `enable_inbound_mcp_rate_limits` | `true` | Enables Cosmos-backed tool throttles. |
| `inbound_mcp_rate_limit_window_seconds` | `60` | Rate-limit window in seconds. |
| `inbound_mcp_rate_limit_read_per_window` | `120` | Read-category tool calls per window. |
| `inbound_mcp_rate_limit_search_per_window` | `30` | Search-category tool calls per window. |
| `inbound_mcp_rate_limit_write_per_window` | `10` | Write-category tool calls per window. |
| `inbound_mcp_max_request_bytes` | `65536` | Maximum JSON-RPC request payload size. |

Numeric settings are clamped by server-side normalization:

- request bytes: `1024` to `1048576`;
- rate-limit window seconds: `10` to `3600`;
- per-category limits: `1` to `10000`.

## Authentication And Trust Gates

Inbound MCP uses a dedicated bearer-token guard. A request must pass all applicable gates before tools are listed or called:

1. Inbound MCP runtime is enabled.
2. A bearer credential is present, well-formed, valid, not expired, and issued by an allowed tenant.
3. Token audience matches the SimpleChat API resource.
4. Caller application ID is allowlisted when a client allowlist is configured.
5. Delegated tokens include the configured delegated scope and user role.
6. App-only tokens include the configured app role, but app-only tokens are not sufficient for the current personal tools.
7. Source ID is accepted by runtime source settings.
8. Source governance allows the delegated user or one of the user's governance groups.
9. Existing SimpleChat ownership/workspace authorization allows access to the requested resource.

The current personal tools require delegated user context. App-only support is reserved for future non-user-data tools.

## Source Governance

Current active governance uses only the `inbound_mcp_source` entity type.

| Entity type | Item ID | Meaning |
| --- | --- | --- |
| `inbound_mcp_source` | `*` | Governed users/groups can use any source accepted by runtime source settings. |
| `inbound_mcp_source` | `<source-id>` | Governed users/groups can use that specific accepted source. |

Important current-state rules:

- Missing matching source policy denies tools by default.
- Explicit deny wins over allow.
- Runtime source allowlisting runs before governance.
- The source header is a control-plane signal; it is not strong identity unless trusted infrastructure sets or validates it.
- Existing personal ownership checks remain the data-access authority.
- The active design uses source policies only; separate inbound access, tool, scope, target, or automatic wildcard policies are not active controls.

## Current Tool Registry

The tool registry is explicit. A Python function is not exposed as MCP just because it exists.

| Tool | Category | Scope | Input limits | Result shape |
| --- | --- | --- | --- | --- |
| `list_conversations` | read | personal | `limit` 1-50, `offset` >= 0, optional `include_hidden` | Conversation metadata visible to the delegated user. |
| `get_conversation_messages` | read | personal | `conversation_id`, `limit` 1-100, `offset` >= 0 | Messages from an owned/authorized personal conversation. |
| `list_personal_documents` | read | personal | `limit` 1-100, `offset` >= 0, optional tag <= 50 chars | Document metadata only. |
| `search_personal_documents` | search | personal | query 1-1000 chars, `top_n` 1-20 | Metadata and capped snippets, not full chunk dumps. |
| `list_personal_tags` | read | personal | `limit` 1-100 | Personal workspace tags. |
| `list_personal_prompts` | read | personal | `limit` 1-100, `offset` >= 0 | Personal prompt metadata. |
| `list_personal_workflows` | read | personal | `limit` 1-100, `offset` >= 0 | Safe workflow metadata and generated workflow IDs. |
| `execute_workflow` | write | personal | generated `workflow_id` 1-128 chars | Bounded workflow run metadata and status. |

`execute_workflow` accepts the generated workflow document ID returned by `list_personal_workflows`; workflow display names are not executable IDs.

## Tool Error Behavior

Tool failures use JSON-RPC error payloads on the JSON-RPC transport instead of turning every tool problem into an HTTP transport failure.

Errors distinguish:

- invalid parameters;
- missing or unknown tool;
- governance denied;
- object authorization denied;
- not found;
- conflict;
- rate limited;
- rate-limit store unavailable;
- workflow business-rule failure;
- unexpected server failure.

Workflow-run business failures are returned with MCP `isError: true` so clients can display the workflow failure instead of a generic cancellation message.

## Rate Limiting

Inbound MCP uses Cosmos-backed counters so throttles work across multi-instance deployments.

Current categories:

| Category | Default limit per 60 seconds |
| --- | --- |
| read | 120 |
| search | 30 |
| write | 10 |

Rate-limit subjects are built from safe caller dimensions such as token type, delegated user, caller application, tenant, and category. User-controllable source ID is intentionally not part of the rate-limit subject so callers cannot bypass limits by rotating source headers.

## Observability

Inbound MCP logs safe structured events through `log_event`.

Logged event classes include:

- request start/completion/rejection;
- auth guard failures;
- runtime client/tenant/source denials;
- governance denials;
- tool start/completion/failure;
- rate-limit denials and rate-limit store failures.

Common safe dimensions:

- `mcp_request_id`;
- caller application ID;
- tenant ID;
- delegated user presence;
- source ID;
- token type;
- JSON-RPC method;
- tool ID;
- rate-limit category;
- result status;
- error type;
- duration;
- payload size.

Do not log:

- bearer tokens;
- raw token claims;
- prompt or message content;
- document content;
- secrets;
- raw settings.

The Admin Settings **About MCP & Tools** modal includes copyable starter KQL for these scenarios:

- request and failure trends;
- error categories by caller/source;
- tool latency and result status;
- rate-limit denials.

Example:

```kusto
traces
| where timestamp > ago(24h)
| where message has "[InboundMCP]"
| summarize requests=count(), failures=countif(tostring(customDimensions.result_status) !in ("", "success", "accepted")) by bin(timestamp, 1h)
| order by timestamp desc
```

## Admin Operations

Admins configure inbound MCP from Admin Settings when the OS-level MCP UI feature flag is enabled.

Admin Settings exposes:

- inbound MCP enablement;
- delegated scope and role defaults;
- caller app allowlist entries;
- tenant allowlist entries;
- source allowlist entries;
- source-governance callouts and create-policy buttons;
- Easy Auth excluded-path verification and setup script copy;
- request-size and read/search/write throttle controls;
- observability/KQL starter queries.

The Easy Auth setup script:

- derives deployment hints from App Service environment values;
- supports Azure public, government, and custom Resource Manager endpoints;
- verifies the SimpleChat API app exposes the expected delegated scope and app roles when possible;
- backs up `authsettingsV2` before changing excluded paths;
- reminds admins to restart the web app so App Service Authentication reloads excluded-path changes.

## Deferred Scope

The following are not part of the current inbound MCP server:

- personal chat write;
- group workspace tools;
- public workspace tools;
- all-scope document search or chat tools;
- MCP prompts/resources;
- server-initiated SSE streams;
- durable MCP session state;
- app-only access to personal user data.

These items require separate design and validation before implementation.

## Validation References

Primary validation coverage:

- `functional_tests\test_inbound_mcp_server_shell.py`
- `functional_tests\test_inbound_mcp_governance_and_tools.py`
- `functional_tests\test_inbound_mcp_admin_ui.py`
- Route policy tests under `functional_tests\route_tests\`
- `ui_tests\test_admin_inbound_mcp_easy_auth_modal.py`
- `ui_tests\test_admin_inbound_mcp_governance_ui.py`
