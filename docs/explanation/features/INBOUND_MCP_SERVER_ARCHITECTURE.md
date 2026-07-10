# Inbound SimpleChat MCP Server Architecture

Architecture recorded in version: **0.250.062**

Disabled shell implemented in version: **0.250.063**

Runtime implementation: **Disabled inbound MCP shell implemented; no inbound MCP tools are exposed.**

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
- Disabled streamable HTTP route shell in `route_inbound_mcp.py`; full MCP protocol/tool execution remains future work.

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
source_id
source_signal_type
source_trust_level
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
INBOUND_MCP_ALLOWED_SOURCE_IDS=*
INBOUND_MCP_SOURCE_HEADER=X-SimpleChat-MCP-Source
INBOUND_MCP_RESOURCE_PATH=/api/mcp
INBOUND_MCP_PRM_PATH=/.well-known/oauth-protected-resource/mcp
```

Default behavior must be deny-by-default:

- Inbound MCP disabled.
- No clients allowed unless configured.
- Source allowlist defaults to `*`, which means identity, client, and governance checks are enforced without source-location filtering.
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
| Disallowed source | 403 | `mcp_source_not_allowed` |
| Inbound MCP disabled | 404 or 403 | `inbound_mcp_disabled` |
| Tool disabled by governance | 403 | `mcp_tool_not_allowed` |
| Scope disabled by governance | 403 | `mcp_scope_not_allowed` |
| Resource operation disabled | 403 | `mcp_resource_operation_not_allowed` |

Log internal detail with `log_event`, but never return raw token or policy internals to the caller.

## Governance Model

Use a combined model:

1. **Entra app role/scope**: coarse gate to reach inbound MCP.
2. **Client app allowlist**: caller application must be approved.
3. **Source allowlist**: optional approved connection/source policy for where approved clients may connect from.
4. **SimpleChat governance**: tools, resources, operations, users, groups, and scopes are enabled explicitly.
5. **Workspace authorization**: the represented user must already have access to the target data.

Initial governance dimensions:

```text
global inbound MCP enabled
client app id enabled
source id enabled or wildcard "*"
tool id enabled
resource family enabled: profile, conversations, documents, prompts, agent_templates, chat
resource operation enabled: list, retrieve, search, write
scope enabled: personal, group, public, all
target scope id enabled: user id, group id, public workspace id, or wildcard "*"
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
all resource operations: disabled
source allowlist: "*" until admins opt into source filtering
```

### Fine-Grained Resource Exposure

Fine-grained resource exposure is a required design constraint for the first implementation, even if the first executable slice only ships a disabled shell.

Admins must be able to independently toggle exposed MCP resources and operations by:

- tool id,
- resource family,
- operation,
- caller user or caller group segment,
- client application id,
- target workspace scope,
- specific target group or public workspace,
- wildcard target such as all groups or all public workspaces.

Examples:

| Policy goal | Required policy shape |
| --- | --- |
| Disable document listing for every group | `scope=group`, `resource_family=documents`, `operation=list`, `target_scope_id=*`, `effect=deny` |
| Disable document retrieval for one group only | `scope=group`, `resource_family=documents`, `operation=retrieve`, `target_scope_id=<group_id>`, `effect=deny` |
| Allow one client to search personal documents only | `client_app_id=<app_id>`, `scope=personal`, `resource_family=documents`, `operation=search`, `effect=allow` |
| Disable prompt retrieval for a user segment | `caller_segment=<group_or_policy_id>`, `resource_family=prompts`, `operation=retrieve`, `effect=deny` |

Policy evaluation should follow these rules:

1. Explicit deny wins over allow.
2. More specific target policy wins over wildcard policy when effects do not conflict.
3. Missing policy means deny.
4. Workspace authorization is always evaluated after governance allows the operation.
5. Governance allow never grants access to data the delegated user cannot already access.

This is intentionally similar to item-delegation governance: every exposed MCP resource operation should have an explicit policy surface, not just a broad "MCP enabled" toggle.

### Source Allowlisting

Admins must also be able to whitelist approved sources so an approved user/client cannot use SimpleChat's inbound MCP surface from an unapproved source location when source filtering is enabled.

Important security posture:

- Token identity and client app id remain the primary trusted controls.
- `Origin`, `Referer`, `User-Agent`, and custom headers are not strong identity proofs for non-browser MCP clients.
- Custom headers may be useful for routing or admin policy, but they are spoofable unless injected by trusted infrastructure or paired with a signed/secret source attestation.
- Some MCP clients, including hosted agent platforms, may not provide stable or controllable browser-style origin headers.
- The allowlist must support `*` for organizations that only want identity/client/governance checks.

Recommended source signal order:

1. **Token caller app id (`azp`/`appid`)**: strongest available application identity signal and mandatory for allowlisting.
2. **Trusted infrastructure injection**: source id header injected by APIM, Front Door, App Gateway, or another trusted reverse proxy after it validates network/client properties.
3. **Signed source attestation header**: future option for clients that can sign a source id using a shared secret or certificate-bound mechanism.
4. **Origin/Referer headers**: advisory only; useful for browser-like clients but not reliable for server-to-server clients.
5. **User-Agent or raw custom source header**: logging/advisory only unless paired with another trusted signal.

Initial source allowlist contract:

```text
allowed_source_ids=["*"] means source filtering is disabled.
allowed_source_ids=["m365-agents", "contoso-copilot"] means the resolved source id must match.
source_id is resolved from trusted infrastructure first, then optional configured header, then origin, then "unknown".
source_trust_level records trusted_proxy, signed_header, token_client, origin, advisory_header, or unknown.
```

The disabled-shell implementation should include this model in the auth/governance context, even if enforcement initially defaults to wildcard `*`.

## Initial Tool Registry Design

The registry should be explicit and data-driven in Python. Do not expose functions automatically.

Suggested registry record:

```python
{
    "id": "list_conversations",
    "display_name": "List conversations",
    "description": "List conversations visible to the delegated user.",
    "scope": "personal",
    "resource_family": "conversations",
    "operation": "list",
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
- source ID and source trust level
- token type
- tool ID
- resource family and operation
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
- Disallowed source when source allowlist is not wildcard `*`.
- Wildcard source `*` permits source-agnostic access only after identity/client/governance checks pass.
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
- Resource family disabled.
- Resource operation disabled.
- Specific group target disabled while other groups remain governed independently.
- Wildcard all-groups policy applies to group resources unless a more specific policy overrides it.
- Personal scope allowed only for delegated users.
- Group/public/all scopes remain disabled by default.
- Explicit deny wins over allow.

Source allowlist tests:

- `INBOUND_MCP_ALLOWED_SOURCE_IDS=*` does not block otherwise-authorized requests.
- Non-wildcard source allowlist rejects unknown source.
- Trusted proxy-injected source id is preferred over caller-supplied advisory headers.
- Raw custom source header is treated as advisory unless configured as trusted through infrastructure or signed attestation.
- Missing source signal is logged as `unknown` and rejected when wildcard is not configured.

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
9. Fine-grained resource family and operation governance requirements are defined.
10. Source allowlisting requirements and trust limitations are defined.
11. Initial tool registry shape is defined.
12. Test plan for the first executable inbound slice is defined.

## Disabled Shell Implementation

The disabled shell was implemented in version **0.250.063** with:

1. Configuration flags.
2. Dedicated inbound MCP blueprint.
3. PRM metadata route.
4. Health/readiness route.
5. Dedicated inbound MCP auth guard helper.
6. Governance helper skeleton.
7. Source signal extraction skeleton with wildcard `*` default.
8. Resource-operation policy model skeleton with deny-by-default behavior.
9. Explicit tool registry returning no enabled tools by default.
10. Route policy and functional regression tests.

Implemented files:

```text
application\single_app\route_inbound_mcp.py
application\single_app\functions_mcp_server_auth.py
application\single_app\functions_mcp_server_governance.py
application\single_app\functions_mcp_server_registry.py
functional_tests\test_inbound_mcp_server_shell.py
```

The shell is disabled by default through `ENABLE_INBOUND_MCP_SERVER=false`. The public PRM endpoint returns safe metadata only. The `/api/mcp` and `/api/mcp/health` routes use the dedicated inbound MCP bearer-token guard when enabled, and return no tools.

## Next Executable Slice

Only after the disabled shell is reviewed should Phase B2/B3 expose read-only personal tools. The next implementation slice should add durable governance policy storage/evaluation and one read-only personal tool behind:

1. delegated-user token validation,
2. client app allowlisting,
3. source allowlisting,
4. explicit SimpleChat MCP governance allow,
5. existing workspace/object authorization,
6. audit logging,
7. negative tests proving disabled group/public/all scopes stay unavailable.
