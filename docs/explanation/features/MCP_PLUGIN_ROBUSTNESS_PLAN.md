# MCP Current State And Remaining Roadmap

Current documentation version: **0.250.098**

Related configuration version: `application\single_app\config.py` currently sets `VERSION = "0.250.098"`.

Detailed inbound server reference: [Inbound SimpleChat MCP Server Architecture](./INBOUND_MCP_SERVER_ARCHITECTURE.md).

## Overview

SimpleChat now has two MCP capabilities:

1. **Outbound MCP actions**: SimpleChat acts as an MCP client and connects to governed external MCP servers.
2. **Inbound SimpleChat MCP server**: approved MCP clients can call a small, governed set of SimpleChat personal-workspace tools.

This document is the current-state roadmap for what was kept. It intentionally omits the historical phase-by-phase implementation log and superseded design alternatives.

## Current Scope

### Track A: Outbound MCP Actions

Outbound MCP actions support governed connections to external MCP servers.

Current kept capabilities:

- Compatibility presets served from `GET /api/plugins/mcp/presets`.
- Server-side preconfiguration catalog served from `GET /api/plugins/mcp/preconfigurations`.
- Destination governance for personal, group, and global/admin MCP actions.
- Server-side destination enforcement on action save/update, discovery, and runtime invocation.
- Endpoint normalization and optional unsafe literal-IP blocking.
- Supported auth methods: none, bearer token, API key, basic auth, and reusable workspace identity.
- Custom HTTP headers with strict header-name validation and secret-value redaction.
- Transport-aware endpoint validation for streamable HTTP, SSE, websocket, and admin-managed stdio.
- Bounded timeout, retry, and retry-backoff settings.
- Optional tool argument validation.
- Large-result handling through the configured MCP result policy.
- Redaction-safe discovery and runtime telemetry for Application Insights.
- Bundled public documentation templates plus hidden enterprise templates for organization-reviewed endpoints.

Current governance entity types:

| Scope | Entity type | Purpose |
| --- | --- | --- |
| Personal MCP actions | `mcp_personal_destination` | Controls destinations usable by personal actions. |
| Group MCP actions | `mcp_group_destination` | Controls destinations usable by group actions, including optional per-group target prefixes. |
| Global/admin MCP actions | `mcp_global_destination` | Controls destinations usable by admin-managed global actions. |

Destination policy item IDs can be exact URLs, hostnames, wildcard host/path patterns, `preset:<id>`, `preconfiguration:<id>`, `transport:<transport>`, or `*` for deployments that intentionally allow broad access.

### Track B: Inbound SimpleChat MCP Server

Inbound MCP is implemented as a first-class Flask route in SimpleChat.

Current kept capabilities:

- Streamable HTTP JSON-RPC endpoint at `POST /api/mcp`.
- Protected Resource Metadata (PRM) endpoints for OAuth-capable MCP client discovery.
- SimpleChat-hosted OAuth authorization server metadata bridge for Entra authorize/token discovery.
- Easy Auth excluded-path setup guidance and verification in Admin Settings.
- Stateless request handling with no durable MCP session ID and no server-initiated SSE stream.
- Dedicated inbound bearer-token auth guard.
- Dedicated delegated user role, future app-only role, and delegated scope defaults:
  - `InboundMCPUserAccess`
  - `InboundMCPAppAccess`
  - `DelegatedMcpServerAccess`
- Runtime trust controls for caller app IDs, tenant IDs, and source IDs.
- Source-first governance through `inbound_mcp_source` item policies only.
- Admin Settings controls for request size and per-category tool rate limits.
- Cosmos-backed per-tool rate limiting that works across multi-instance deployments.
- Safe request/tool/auth/governance/rate-limit telemetry with `mcp_request_id` and `X-Correlation-ID`.
- Copyable Application Insights starter queries in the Admin Settings MCP overview modal.

Current active inbound governance entity type:

| Entity type | Item ID | Meaning |
| --- | --- | --- |
| `inbound_mcp_source` | `*` | Allows the governed users/groups to use any runtime-accepted source ID. |
| `inbound_mcp_source` | `<source-id>` | Allows the governed users/groups to use one specific runtime-accepted source ID. |

The current active design uses source policies only; separate inbound access, tool, scope, target, or automatic wildcard policies are not active controls.

## Current Inbound Tool Surface

The inbound MCP server intentionally exposes a small delegated personal-workspace surface.

| Tool | Category | Scope | Notes |
| --- | --- | --- | --- |
| `list_conversations` | read | personal | Bounded conversation list for the delegated user. |
| `get_conversation_messages` | read | personal | Bounded messages from an owned/authorized personal conversation. |
| `list_personal_documents` | read | personal | Metadata-only document list with optional tag filter. |
| `search_personal_documents` | search | personal | Bounded personal document search with capped snippets. |
| `list_personal_tags` | read | personal | Personal workspace tag list. |
| `list_personal_prompts` | read | personal | Personal prompt metadata list. |
| `list_personal_workflows` | read | personal | Safe workflow metadata and generated workflow IDs. |
| `execute_workflow` | write | personal | Executes an owned personal workflow by generated workflow ID. |

`execute_workflow` is the only current execution/write-style inbound tool. It reuses the existing personal workflow runner, ownership checks, feature/app-role eligibility, distributed run lock, status updates, and audit-safe run metadata.

## Current Security Boundaries

### Outbound MCP Actions

- Destination governance is enforced server-side; frontend filtering is not trusted.
- Preconfiguration and preset definitions are validated before being returned to the browser.
- Catalog definitions must not include secrets, tenant credentials, customer data, or production credential values.
- Enterprise preconfigurations are hidden by default and require explicit destination governance.
- Local command execution for Azure MCP Server-style templates is not supported from user input.
- Secret values are redacted in logs, API responses, rendered HTML, browser-visible JSON, and test artifacts.

### Inbound SimpleChat MCP Server

- Inbound MCP is disabled by default.
- Tools require a valid bearer token, approved tenant/client/source runtime configuration, and matching SimpleChat source governance.
- Personal tools require delegated user context; app-only tokens are not sufficient for current personal tools.
- Existing personal ownership and workspace authorization checks remain authoritative for data access.
- Source headers are treated as control-plane signals, not strong identity by themselves.
- Prompt content, message content, document content, bearer tokens, token claims, raw settings, and secrets are not logged.

## Current Observability

Inbound MCP emits safe structured telemetry for:

- request start/completion/rejection;
- auth guard failures;
- source/runtime trust decisions;
- governance denials;
- tool start/completion/failure;
- rate-limit denials and rate-limit store failures.

Common dimensions include:

- `mcp_request_id`
- `caller_app_id`
- `tenant_id`
- delegated user presence
- `source_id`
- token type
- JSON-RPC method
- tool ID
- rate-limit category
- result status
- error type
- duration
- payload size

The Admin Settings inbound MCP overview modal includes copyable KQL starter queries for request trends, error categories, tool latency, and rate-limit denials.

## Deferred Or Explicitly Out Of Scope

These items are not part of the current kept MCP implementation:

| Item | Issue | Status |
| --- | --- | --- |
| Enterprise TLS diagnostics and outbound OAuth 2.1 PKCE | #1016 | Deferred until a concrete provider/test target requires it. |
| Personal chat write tool | #1019 | Deferred pending a separate design for prompt, conversation, retention, safety, and abuse controls. |
| Group/public/all-scope inbound tools | #1020 | Deferred until workspace-role checks, governance, negative tests, pagination, and admin enablement are explicitly designed. |
| Inbound SSE streams and stateful MCP sessions | Future | Deferred until a concrete client or tool needs progress streaming, resumability, or durable session state. |
| Inbound MCP prompts/resources | Future | Deferred; current server advertises tools only. |
| Long-running outbound MCP jobs | Future | Deferred until a concrete workflow requires durable job state. |
| Per-definition catalog administration UI | Future | Optional refinement; current admins can allow/block catalog items with destination governance. |

## Issue Closure Guidance For The Upcoming PR

The current working branch should close the completed MCP issues when the PR lands on `main`:

```text
Closes #1013
Closes #1014
Closes #1015
Closes #1017
Closes #1018
```

Do not include close keywords for #1016, #1019, or #1020 unless their remaining deferred scope is split or explicitly reclassified.

## Validation References

Relevant validation coverage includes:

- `functional_tests\test_mcp_destination_governance_and_preconfigurations.py`
- `functional_tests\test_mcp_server_presets.py`
- `functional_tests\test_mcp_outbound_logging.py`
- `functional_tests\test_inbound_mcp_server_shell.py`
- `functional_tests\test_inbound_mcp_governance_and_tools.py`
- `functional_tests\test_inbound_mcp_admin_ui.py`
- Route policy tests under `functional_tests\route_tests\`
- Targeted UI tests under `ui_tests\`
