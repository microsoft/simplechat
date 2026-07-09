# Inbound SimpleChat MCP Server Architecture

Implemented in version: **0.250.062**

## Overview

This document records Track B Phase B0 and B1 decisions for the inbound SimpleChat Model Context Protocol (MCP) server. The goal is to expose a small, governed set of SimpleChat capabilities to approved MCP clients without weakening SimpleChat's existing authentication, authorization, workspace, governance, observability, and data-protection boundaries.

This phase is intentionally an architecture and auth-foundation slice. It does **not** expose inbound MCP tools yet.

## Dependencies

- Existing Microsoft Entra application registration for SimpleChat.
- Existing SimpleChat bearer-token validation patterns in `functions_authentication.py`.
- Existing route blueprint registration pattern in `app.py`.
- Existing governance helpers in `functions_governance.py`.
- Existing group/public workspace authorization helpers.
- Existing `log_event` telemetry pattern.
- Future MCP transport implementation using streamable HTTP.

## Phase B0 Architecture Decisions

### Decision 1: First Production Hosting Model

The first inbound MCP implementation should be a first-class SimpleChat component, not a standalone external app.

Recommended initial files:

```text
application\single_app\route_inbound_mcp.py
application\single_app\functions_mcp_server_auth.py
application\single_app\functions_mcp_server_governance.py
application\single_app\functions_mcp_server_registry.py
application\single_app\functions_mcp_server_tools.py
```

Rationale:

- The MCP surface needs the same settings, auth validation, governance, logging, rate limits, and operation helpers as the main app.
- A first-class component avoids copying business logic into a separate prototype service.
- A later sidecar/container remains possible if it reuses the same service layer and auth/governance contracts.

### Decision 2: Service Layer First

Inbound MCP tool business logic must sit behind reusable operation functions. MCP decorators, Flask routes, tests, and any future sidecar should call the same service layer.

Do this:

```text
MCP transport handler -> inbound MCP auth context -> governance decision -> tool registry -> service-layer function
```

Do not do this:

```text
FastMCP decorator -> direct Cosmos/search/settings access
```

Each service-layer function must receive an explicit authorized context rather than reading caller-controlled `user_id`, `group_id`, `conversation_id`, or scope arguments directly from MCP tool input.

### Decision 3: Transport For First Release

Start with streamable HTTP only.

Initial route shape should be similar to:

```text
GET  /.well-known/oauth-protected-resource/mcp
GET  /api/mcp/health
POST /api/mcp
```

SSE can be added later only if a required client cannot support streamable HTTP. Stdio is not supported for inbound SimpleChat production hosting.

### Decision 4: Stateless Scale Assumptions

Inbound MCP authorization must be stateless and multi-instance safe.

Rules:

- Do not use process-local token/session caches as the source of truth.
- Do not bridge app-only bearer tokens into long-lived Flask browser sessions.
- Do not depend on process-local MCP session state for authorization correctness.
- Validate bearer tokens per request or through a safe, bounded JWKS/key cache.
- Use durable SimpleChat stores for governance, client enablement, and audit records.
- Ensure restart or horizontal scale does not change whether a caller is authorized.

## Phase B1 Auth Foundation

### Dedicated Inbound MCP Auth Guard

Add a dedicated guard instead of broadening `accesstoken_required`.

Proposed helper:

```text
functions_mcp_server_auth.py
    validate_inbound_mcp_request(request) -> InboundMcpAuthContext
```

The guard must validate:

- `Authorization: Bearer ...` is present and well-formed.
- Token signature is valid.
- Token has not expired and is not before its valid time.
- Tenant is allowed.
- Issuer matches expected Entra issuer forms for the configured tenant.
- Audience is the SimpleChat API resource.
- Caller application ID is allowlisted.
- Required app role or delegated scope is present.
- Token type is understood: delegated user token vs app-only token.
- User-data tools receive a delegated user identity.

Do not reuse the current external `ExternalApi` role implicitly. Use a dedicated app role or scope unless an admin deliberately maps it.

Recommended default app role/scope:

```text
McpServerAccess
```

### App-Only vs Delegated Access

Initial read-only personal tools require delegated user access.

Policy:

| Token type | Initial personal tools | Future admin tools | Notes |
| --- | --- | --- | --- |
| Delegated user token | Allowed after all auth/governance checks | Not applicable | Tool execution is bound to represented user. |
| App-only token | Rejected | Possible future separate design | Never map app-only identity to arbitrary user data. |
| Browser session cookie | Rejected for MCP API | Not applicable | MCP clients use bearer tokens, not browser session auth. |

The auth context should include:

```text
tenant_id
audience
issuer
caller_app_id
token_type
roles
scopes
delegated_user_id
delegated_username
correlation_id
```

Do not expose raw token claims to tools by default.

### Configuration Contract

Add configuration through settings/env first, then admin UI later.

Proposed settings:

```text
ENABLE_INBOUND_MCP_SERVER=false
INBOUND_MCP_REQUIRED_ROLE=McpServerAccess
INBOUND_MCP_REQUIRED_SCOPE=McpServerAccess
INBOUND_MCP_ALLOWED_CLIENT_APP_IDS=
INBOUND_MCP_ALLOWED_TENANT_IDS=
INBOUND_MCP_RESOURCE_PATH=/api/mcp
INBOUND_MCP_PRM_PATH=/.well-known/oauth-protected-resource/mcp
```

Default behavior must be deny-by-default:

- Inbound MCP disabled.
- No clients allowed unless configured.
- No tools enabled unless governance allows them.
- Group/public/all-scope tools disabled.

### Protected Resource Metadata Contract

Expose a Protected Resource Metadata (PRM) endpoint before tools are enabled:

```text
GET /.well-known/oauth-protected-resource/mcp
```

The response should be derived from safe configuration only.

Proposed response shape:

```json
{
    "resource": "api://<simplechat-client-id>",
    "authorization_servers": [
        "https://login.microsoftonline.com/<tenant-id>/v2.0"
    ],
    "scopes_supported": [
        "McpServerAccess"
    ],
    "bearer_methods_supported": [
        "header"
    ],
    "resource_documentation": "https://<public-simplechat-host>/docs/inbound-mcp"
}
```

Do not include:

- Client secrets.
- Raw internal settings.
- Cosmos/Search/OpenAI endpoints.
- Key Vault names.
- Internal-only hostnames.
- Per-user or per-client policy details.

### Error Contract

Authentication and authorization errors should be clear but non-leaky.

Recommended responses:

| Scenario | HTTP | Public error |
| --- | --- | --- |
| Missing bearer token | 401 | `bearer_token_required` |
| Invalid/expired token | 401 | `invalid_token` |
| Wrong audience/issuer/tenant | 401 | `invalid_token` |
| Missing role/scope | 403 | `insufficient_mcp_permissions` |
| Disallowed client app | 403 | `mcp_client_not_allowed` |
| Inbound MCP disabled | 404 or 403 | `inbound_mcp_disabled` |
| Tool disabled by governance | 403 | `mcp_tool_not_allowed` |
| Scope disabled by governance | 403 | `mcp_scope_not_allowed` |

Log internal detail with `log_event`, but never return raw token or policy internals to the caller.

## Governance Model

Use a combined model:

1. **Entra app role/scope**: coarse gate to reach inbound MCP.
2. **Client app allowlist**: caller application must be approved.
3. **SimpleChat governance**: tools and scopes are enabled explicitly.
4. **Workspace authorization**: the represented user must already have access to the target data.

Initial governance dimensions:

```text
global inbound MCP enabled
client app id enabled
tool id enabled
scope enabled: personal, group, public, all
identity type allowed: delegated, app-only
optional per-client/user rate limit
```

Recommended default:

```text
inbound MCP: disabled
personal scope: disabled until B3
group scope: disabled
public scope: disabled
all scope: disabled
all tools: disabled
```

## Initial Tool Registry Design

The registry should be explicit and data-driven in Python. Do not expose functions automatically.

Suggested registry record:

```python
{
    "id": "list_conversations",
    "display_name": "List conversations",
    "description": "List conversations visible to the delegated user.",
    "scope": "personal",
    "identity_type": "delegated",
    "feature_flag": "enable_user_workspace",
    "governance_key": "inbound_mcp.list_conversations",
    "rate_limit_category": "read",
    "audit_event": "InboundMcpListConversations",
    "enabled_by_default": False,
}
```

Initial candidate read-only personal tools remain planned, not exposed:

| Tool | Scope | Identity | Initial status |
| --- | --- | --- | --- |
| `show_user_profile` | personal | delegated | Planned |
| `list_conversations` | personal | delegated | Planned |
| `get_conversation_messages` | personal | delegated | Planned |
| `list_personal_documents` | personal | delegated | Planned |
| `list_personal_prompts` | personal | delegated | Planned |
| `search_personal_documents` | personal | delegated | Planned |
| `list_agent_template_tags` | personal | delegated | Planned |

Deferred tools:

- Personal chat write.
- Group tools.
- Public workspace tools.
- All-scope search or chat.
- Admin/app-only tools.

## Route And Blueprint Requirements

Inbound MCP routes must use a dedicated blueprint, such as:

```text
inbound_mcp_bp = Blueprint("inbound_mcp", __name__)
```

The blueprint should have a dedicated before-request guard once implemented. It should not use `login_required_blueprint()` because MCP clients use bearer tokens and are not browser sessions.

Every Flask route still needs:

```python
@swagger_route(security=get_auth_security())
```

Route policy tests must be updated when routes are added.

## Observability Requirements

Use `log_event` with a clear category such as `InboundMCP`.

Log:

- correlation ID
- caller app ID
- tenant ID
- delegated user ID, when present
- token type
- tool ID
- governance decision
- scope
- duration
- success/failure category

Do not log:

- bearer tokens
- raw token claims
- prompt/message content
- document content
- secrets
- raw settings

## Test Plan For B1 Implementation

Auth contract tests before tools:

- Missing bearer token.
- Malformed bearer token.
- Expired token.
- Invalid issuer.
- Invalid audience.
- Invalid tenant.
- Missing required role/scope.
- Disallowed caller app ID.
- App-only token rejected for user-data tools.
- Delegated token accepted only for represented user.

PRM tests:

- Metadata endpoint returns expected resource shape.
- Metadata derives authorization server from safe tenant configuration.
- Metadata does not expose secrets or internal endpoints.
- Metadata remains available when tools are disabled, if inbound MCP metadata is enabled.

Governance tests:

- Inbound MCP disabled.
- Client disabled.
- Tool disabled.
- Scope disabled.
- Personal scope allowed only for delegated users.
- Group/public/all scopes remain disabled by default.

Scale tests:

- Authorization remains stateless across process restart.
- No process-local cache is required for authorization correctness.
- Health/readiness responses do not expose secrets.

## Acceptance Criteria For Phase B0/B1

Phase B0/B1 is complete when:

1. Hosting decision is recorded.
2. Service-layer boundary is recorded.
3. Initial transport decision is recorded.
4. Stateless scale assumptions are recorded.
5. Dedicated auth guard contract is defined.
6. App-only vs delegated user policy is defined.
7. PRM metadata contract is defined.
8. Governance dimensions and deny-by-default posture are defined.
9. Initial tool registry shape is defined.
10. Test plan for the first executable inbound slice is defined.

## Next Executable Slice

The next implementation slice should add the disabled inbound MCP shell:

1. Configuration flags.
2. Dedicated inbound MCP blueprint.
3. PRM metadata route.
4. Health/readiness route.
5. Auth guard helper with mocked-token unit tests.
6. Governance helper skeleton.
7. Explicit tool registry returning no enabled tools by default.

Only after that should Phase B3 expose read-only personal tools.
