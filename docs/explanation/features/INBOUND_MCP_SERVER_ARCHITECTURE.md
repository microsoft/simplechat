# Inbound SimpleChat MCP Server Architecture

Architecture recorded in version: **0.250.062**

Disabled shell implemented in version: **0.250.063**

Planned base inbound action set updated in version: **0.250.069**

First governed tool slice implemented in version: **0.250.070**

App-settings and minimal admin UI slice implemented in version: **0.250.071**

Easy Auth enablement guard implemented in version: **0.250.072**

Cloud-aware Easy Auth script implemented in version: **0.250.073**

Script copy and authsettingsV2 read fix implemented in version: **0.250.074**

Delegated scope default and setup preflight implemented in version: **0.250.075**

OAuth protected-resource discovery header implemented in version: **0.250.076**

Inbound MCP governance UI implemented in version: **0.250.077**

Inbound MCP user/app role split implemented in version: **0.250.078**

MCP governance help modal implemented in version: **0.250.079**

Simplified inbound MCP access/source governance implemented in version: **0.250.080**

Single inbound MCP access governance implemented in version: **0.250.081**

Runtime implementation: **Inbound MCP shell supports minimal streamable HTTP JSON-RPC (`initialize`, `tools/list`, `tools/call`) and exposes personal delegated tools only when the single explicit inbound MCP access policy allows the delegated user. Mutable inbound MCP runtime settings are stored in the Cosmos-backed `app_settings` document. Admin enablement is blocked until the required App Service Authentication excluded paths are verified. The Easy Auth setup script is generated from SimpleChat deployment hints, supports public/government/custom Resource Manager endpoints, attempts to verify that the SimpleChat API app exposes the delegated scope plus required inbound MCP user/app roles, creates a backup before changing `authsettingsV2`, and can be copied from the modal. Inbound MCP 401 responses advertise the PRM endpoint through `WWW-Authenticate` so OAuth-capable MCP clients discover Entra instead of falling back to `/authorize` on the SimpleChat host. Admin Settings now exposes a quick-create governance control and reusable policy-help modal for the current inbound MCP access policy; source filtering stays in runtime configuration.**

## Overview

This document records Track B Phase B0 and B1 decisions for the inbound SimpleChat Model Context Protocol (MCP) server. The goal is to expose a small, governed set of SimpleChat capabilities to approved MCP clients without weakening SimpleChat's existing authentication, authorization, workspace, governance, observability, and data-protection boundaries.

This document began as the architecture and auth-foundation slice. As of version **0.250.081**, the first governed personal read tool is implemented, the mutable runtime settings are app-settings backed, a minimal Admin Settings panel exists behind an OS-only UI feature flag, enabling the server requires a verified Easy Auth exclusion check, the default delegated scope is `DelegatedMcpServerAccess`, delegated personal tools require the `InboundMCPUserAccess` user-assignable app role by default, `InboundMCPAppAccess` is reserved for future app-only tools, OAuth clients receive the PRM discovery challenge on bearer-token 401 responses, and admins can create a single inbound MCP access policy from the Governance tab with per-button help guidance. Source filtering stays in Inbound MCP runtime configuration. The rest of the initial tool set remains planned and disabled.

## Dependencies

- Existing Microsoft Entra application registration for SimpleChat.
- Existing SimpleChat bearer-token validation patterns in `functions_authentication.py`.
- Existing route blueprint registration pattern in `app.py`.
- Existing governance helpers in `functions_governance.py`.
- Existing group/public workspace authorization helpers.
- Existing `log_event` telemetry pattern.
- Streamable HTTP JSON-RPC route shell in `route_inbound_mcp.py`; broader MCP protocol surfaces beyond `initialize`, `tools/list`, and `tools/call` remain future work.

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
- Delegated tokens include the required delegated scope and at least one required delegated user role.
- App-only tokens include at least one required app-only role, but are not sufficient for personal tools.
- Token type is understood: delegated user token vs app-only token.
- User-data tools receive a delegated user identity.

Do not reuse the current external `ExternalApi` role implicitly. Use dedicated inbound MCP scope and role values unless an admin deliberately maps them.

Recommended defaults:

```text
Delegated user role: InboundMCPUserAccess
Future app-only role: InboundMCPAppAccess
Delegated scope: DelegatedMcpServerAccess
```

### App-Only vs Delegated Access

Initial personal tools require delegated user access. A delegated scope is the best default for VS Code and other interactive MCP clients because the request is bound to the represented user and can safely evaluate personal workspace authorization. Read operations remain list/retrieve/search only; `execute_workflow` requires separate execution governance because it can create workflow runs, messages, model calls, and audit records.

Policy:

| Token type | Initial personal tools | Future admin tools | Notes |
| --- | --- | --- | --- |
| Delegated user token | Allowed after all auth/governance checks | Not applicable | Tool execution is bound to represented user and requires the configured delegated scope plus at least one configured user-assignable app role. |
| App-only token | Rejected by personal tool governance | Possible future separate design | App role claims are consumed for future app-only MCP access, but must not be mapped to arbitrary user data. |
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

Mutable runtime configuration is stored in the Cosmos-backed `app_settings` document so Azure deployments can change inbound MCP enablement and auth/source allowlists without editing code or restarting solely to change environment variables.

Implemented `app_settings` keys:

```text
enable_inbound_mcp_server=false
inbound_mcp_required_user_roles=["InboundMCPUserAccess"]
inbound_mcp_required_app_roles=["InboundMCPAppAccess"]
inbound_mcp_required_scope=DelegatedMcpServerAccess
inbound_mcp_allowed_client_app_ids=[]
inbound_mcp_allowed_tenant_ids=[]
inbound_mcp_allowed_source_ids=["*"]
inbound_mcp_source_header=X-SimpleChat-MCP-Source
```

The inbound MCP endpoint paths remain fixed in application routing for this slice:

```text
/api/mcp
/.well-known/oauth-protected-resource/mcp
```

The minimal Admin Settings panel is gated by the OS/App Service environment feature flag `ENABLE_MCP_UI`. That flag is not stored in `app_settings`, not rendered as an editable UI control, and only controls whether the admin panel and left-nav jump link are visible.

When App Service Authentication is configured to redirect unauthenticated callers, admins must exclude the MCP discovery and endpoint paths at the App Service Authentication layer before enabling inbound MCP. The Admin Settings modal provides Azure Cloud Shell-compatible PowerShell/az CLI guidance and verifies that these public unauthenticated requests reach SimpleChat JSON handlers rather than Microsoft sign-in HTML:

```text
/.well-known/oauth-protected-resource/mcp
/api/mcp
/api/mcp/health
```

Excluding `/api/mcp` and `/api/mcp/health` from Easy Auth does not make MCP unauthenticated because SimpleChat still enforces its dedicated bearer-token guard on those routes.

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

Bearer-token 401 responses from `/api/mcp` should include a protected-resource discovery challenge:

```http
WWW-Authenticate: Bearer resource_metadata="https://<public-simplechat-host>/.well-known/oauth-protected-resource/mcp"
```

Without this challenge, some OAuth-capable MCP clients may infer the SimpleChat host itself is the authorization server and redirect users to a non-existent `/authorize` route. The intended authorization server is the configured Entra authority returned by PRM.

Proposed response shape:

```json
{
    "resource": "api://<simplechat-client-id>",
    "authorization_servers": [
        "https://login.microsoftonline.com/<tenant-id>/v2.0"
    ],
    "scopes_supported": [
        "DelegatedMcpServerAccess"
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
| Missing delegated scope, delegated user role, or app-only role | 403 | `insufficient_mcp_permissions` |
| Disallowed client app | 403 | `mcp_client_not_allowed` |
| Disallowed source | 403 | `mcp_source_not_allowed` |
| Inbound MCP disabled | 404 or 403 | `inbound_mcp_disabled` |
| Personal access disabled by governance | 403 | `mcp_access_not_allowed` |
| Future capability disabled by governance | 403 | capability-specific error |

Log internal detail with `log_event`, but never return raw token or policy internals to the caller.

## Governance Model

Use a combined model:

1. **Entra scope plus role**: coarse gate to reach inbound MCP; delegated tools require both the configured delegated scope and a configured user-assignable app role.
2. **Client app allowlist**: caller application must be approved in inbound MCP runtime configuration.
3. **Source runtime allowlist**: approved source signals are allowed through `inbound_mcp_allowed_source_ids` and the configured source header/origin extraction.
4. **SimpleChat governance**: users and groups are allowed through the single `inbound_mcp_access/inbound_mcp` policy.
5. **Workspace authorization**: the represented user must already have access to the target data.

Current required governance dimensions:

```text
global inbound MCP enabled
client app id enabled
source allowlist enabled in runtime configuration when source filtering is required
inbound MCP access policy enabled: inbound_mcp_access item "inbound_mcp"
identity type allowed: delegated, app-only
optional per-client/user rate limit
```

Recommended default:

```text
inbound MCP: disabled
inbound MCP access: disabled until an explicit inbound_mcp_access/inbound_mcp policy allows users or groups
group scope: disabled
public scope: disabled
all scope: disabled
source filtering: controlled by inbound_mcp_allowed_source_ids in runtime configuration
```

### Fine-Grained Resource Exposure

Fine-grained resource exposure is still a required future design constraint, but it should not make the first production governance UI harder to understand. The current implemented path uses one broad inbound MCP access policy plus runtime tenant/client/source allowlists. Future capability-level controls should use admin-facing capability names rather than raw tool ids or resource-operation strings.

Future policy surfaces may independently toggle exposed MCP resources and operations by:

- capability such as `personal_read`, `personal_search`, `workflow_execute`, or `group_read`,
- resource family,
- operation,
- caller user or caller group segment,
- target workspace scope,
- specific target group or public workspace,
- wildcard target such as all groups or all public workspaces.

Examples:

| Policy goal | Required policy shape |
| --- | --- |
| Disable document listing for every group | `scope=group`, `resource_family=documents`, `operation=list`, `target_scope_id=*`, `effect=deny` |
| Disable document retrieval for one group only | `scope=group`, `resource_family=documents`, `operation=retrieve`, `target_scope_id=<group_id>`, `effect=deny` |
| Allow personal search only for one approved user segment | `capability=personal_search`, `allowed_groups=[<group_id>]`, `effect=allow` |
| Disable prompt retrieval for a user segment | `caller_segment=<group_or_policy_id>`, `resource_family=prompts`, `operation=retrieve`, `effect=deny` |

Policy evaluation should follow these rules:

1. Explicit deny wins over allow.
2. More specific target policy wins over wildcard policy when effects do not conflict.
3. Missing policy means deny.
4. Workspace authorization is always evaluated after governance allows the operation.
5. Governance allow never grants access to data the delegated user cannot already access.

This should remain compatible with item-delegation governance: every future exposed MCP capability should have an explicit, understandable policy surface, not just a broad "MCP enabled" toggle.

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

Initial candidate personal tools are explicit and data-driven. Most are read-only; `execute_workflow` is a governed execution operation and must not share the same lightweight policy path as list/retrieve/search actions.

| Tool | Scope | Identity | Initial status |
| --- | --- | --- | --- |
| `list_conversations` | personal | delegated | Planned |
| `get_conversation_messages` | personal | delegated | Planned |
| `list_personal_documents` | personal | delegated | Planned |
| `list_personal_prompts` | personal | delegated | Planned |
| `list_personal_tags` | personal | delegated | Implemented in v0.250.070; exposed only when the explicit inbound MCP access policy allows the delegated user |
| `search_personal_documents` | personal | delegated | Planned |
| `execute_workflow` | personal | delegated | Planned with explicit execution governance |

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
- Missing required delegated scope.
- Missing required delegated user role.
- Missing required app-only role for app-only MCP access.
- Disallowed caller app ID.
- Disallowed source when source allowlist is not wildcard `*`.
- Wildcard source `*` permits source-agnostic access only after identity/client/governance checks pass.
- App-only token rejected for user-data tools.
- Delegated token accepted only for represented user.

PRM tests:

- Metadata endpoint returns expected resource shape.
- Bearer-token 401 responses include a `WWW-Authenticate` challenge with `resource_metadata`.
- Metadata derives authorization server from safe tenant configuration.
- Metadata does not expose secrets or internal endpoints.
- Metadata remains available when tools are disabled, if inbound MCP metadata is enabled.

Governance tests:

- Inbound MCP disabled.
- Disallowed client application ID is rejected by MCP runtime configuration before governance.
- Missing inbound MCP access policy denies personal tools.
- Runtime source allowlist denies disallowed source signals before governance.
- Inbound MCP access item `inbound_mcp` allows only users or groups on the policy, unless the policy's own allow-all toggle is enabled.
- Legacy `inbound_mcp_scope` and `inbound_mcp_target` policies are accepted only as a temporary compatibility fallback for personal access.
- Personal scope allowed only for delegated users.
- Group/public/all scopes remain disabled by default.
- Explicit deny wins over allow.

Source allowlist tests:

- `app_settings.inbound_mcp_allowed_source_ids=["*"]` does not block otherwise-authorized requests.
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
8. Inbound MCP access governance, runtime source allowlisting, and deny-by-default posture are defined.
9. Future fine-grained resource family, operation, and capability governance requirements are defined separately from the first personal-access slice.
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
application\single_app\functions_mcp_server_config.py
application\single_app\functions_mcp_server_auth.py
application\single_app\functions_mcp_server_governance.py
application\single_app\functions_mcp_server_registry.py
functional_tests\test_inbound_mcp_server_shell.py
functional_tests\test_inbound_mcp_admin_ui.py
```

The shell is disabled by default through `app_settings.enable_inbound_mcp_server=false`. The public PRM endpoint returns safe metadata only. The `/api/mcp` and `/api/mcp/health` routes use the dedicated inbound MCP bearer-token guard when enabled.

## First Governed Tool Slice

Version **0.250.070** adds the first executable inbound MCP tool slice:

1. `route_inbound_mcp.py` handles minimal streamable HTTP JSON-RPC methods:
   - `initialize`
   - `notifications/initialized`
   - `tools/list`
   - `tools/call`
2. `functions_mcp_server_governance.py` evaluates explicit item policies for:
   - `inbound_mcp_access` with item `inbound_mcp`
3. Missing explicit policy denies access.
4. Matching explicit deny policies win over matching allow policies.
5. `functions_mcp_server_registry.py` distinguishes planned tools from implemented tools.
6. `functions_mcp_server_tools.py` implements `list_personal_tags` using the delegated user identity from the inbound MCP auth context.

To expose personal inbound MCP tools, an admin must enable the global inbound MCP feature and configure the bearer-token delegated scope, delegated user role, tenant allowlist, client allowlist, and source allowlist as needed. Tenant, client, and source trust belong to the Inbound MCP runtime configuration. SimpleChat governance decides which users/groups may use inbound MCP. Version **0.250.081** simplifies the required item policy shape to:

| Entity type | Item id example |
| --- | --- |
| `inbound_mcp_access` | `inbound_mcp` |

The allow-all toggle, allowed users, and allowed groups on the access policy remain the only user/group authorization controls. Do not encode user authorization into item ids such as `personal:*`; use delegated item `inbound_mcp` and then choose allow-all or explicit users/groups. Legacy client, source, tool, scope, resource-operation, and target policy types remain readable for compatibility, but the Admin Settings quick-create experience no longer creates them for the current MCP slice.

The first tool intentionally returns only tag metadata: tag name, count, color, scope, count, and limit. It does not accept a caller-supplied `user_id`.

## App Settings And Minimal Admin UI Slice

Version **0.250.071** moves mutable inbound MCP runtime settings from static OS environment variables into the Cosmos-backed `app_settings` document and adds a minimal Admin Settings panel under **Agents and Actions**.

Implemented behavior:

1. `functions_mcp_server_config.py` centralizes defaults, list normalization, boolean normalization, and OS-only UI gate evaluation.
2. `functions_settings.py` persists default inbound MCP runtime settings into `app_settings` and normalizes updates.
3. `functions_mcp_server_auth.py` and `route_inbound_mcp.py` resolve runtime config per request instead of importing static env constants for enablement, delegated scope, delegated user roles, app-only roles, client allowlist, tenant allowlist, source allowlist, or source-header behavior.
4. `app.py` injects `mcp_ui_enabled` into templates without adding `enable_mcp_ui` to sanitized or persisted app settings.
5. `templates\admin_settings.html` renders the minimal inbound MCP panel only when `mcp_ui_enabled` is true.
6. `templates\_sidebar_nav.html` renders the left-nav **Inbound MCP** jump link only when `mcp_ui_enabled` is true.

The UI intentionally exposes only mutable runtime settings. Endpoint route paths stay fixed for this slice, and `ENABLE_MCP_UI` remains an OS/App Service environment setting rather than an editable SimpleChat setting.

## Easy Auth Enablement Guard

Version **0.250.072** adds an admin enablement guard for Azure App Service Authentication deployments that redirect unauthenticated requests. Version **0.250.073** upgrades the setup script to be generated from SimpleChat deployment hints instead of assuming public Azure. Version **0.250.074** adds a copy-to-clipboard button and fixes the script to read `authsettingsV2` with the resource GET endpoint before creating a backup. Version **0.250.075** changes the default delegated scope to `DelegatedMcpServerAccess` and adds a best-effort setup-script check that the SimpleChat API app registration exposes that enabled delegated scope. Version **0.250.078** adds preflight checks for the `InboundMCPUserAccess` user role and `InboundMCPAppAccess` app-only role.

Implemented behavior:

1. The inbound MCP admin panel opens a Bootstrap modal when an admin attempts to enable the server from a disabled state.
2. The modal provides PowerShell/az CLI instructions for adding the three required `authsettingsV2.properties.globalValidation.excludedPaths` values.
3. The admin must confirm that the App Service Authentication exclusions were applied.
4. SimpleChat then probes the public PRM, MCP JSON-RPC, and MCP health endpoints without following redirects or adding browser credentials.
5. The UI keeps inbound MCP disabled when the probe sees a sign-in redirect, sign-in HTML, non-JSON response, or unexpected status.
6. The Admin Settings POST path repeats the server-side probe before saving a false-to-true enablement transition, so browser bypasses cannot enable inbound MCP while Easy Auth is still intercepting the endpoints.
7. The generated script derives tenant, Azure environment, Resource Manager endpoint, App Service name, resource group, and subscription hints from SimpleChat/App Service environment values.
8. The generated script selects the Azure CLI cloud before login, logs into the configured tenant, validates the active Resource Manager endpoint, and matches custom clouds by registered Azure CLI cloud endpoint.
9. The generated script writes a timestamped `simplechat-authsettingsV2-backup-*.json` file before applying the PUT update.
10. The generated script reads the current resource with `GET .../config/authsettingsV2` and only creates the backup after that read succeeds.
11. The modal exposes a small copy button for the generated PowerShell script.

## Next Executable Slice

After the first governed tool slice, the next implementation slice should add another low-risk personal read tool behind the same controls:

1. delegated-user token validation,
2. client app allowlisting,
3. source allowlisting,
4. explicit SimpleChat MCP governance allow,
5. existing workspace/object authorization,
6. audit logging,
7. negative tests proving disabled group/public/all scopes stay unavailable.
