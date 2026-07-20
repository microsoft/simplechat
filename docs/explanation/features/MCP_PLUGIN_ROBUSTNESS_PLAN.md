# MCP Plugin Robustness Plan

Planning version: **0.250.080**

Implemented in version: **In progress across phases**

Related configuration version: `application/single_app/config.py` currently sets `VERSION = "0.250.080"`.

Detailed Track B Phase B0/B1 architecture outcome: [Inbound SimpleChat MCP Server Architecture](./INBOUND_MCP_SERVER_ARCHITECTURE.md).

## Overview

This plan describes how to make the SimpleChat Model Context Protocol (MCP) plugin more robust for Splunk MCP Server and other MCP-compatible servers. The current implementation should work for Splunk's GA encrypted-token flow when configured with `streamable_http` transport and bearer authentication. The main gaps are advanced OAuth 2.1 PKCE support, custom headers, richer diagnostics, enterprise TLS options, stronger result handling, and optional support for MCP features beyond tools.

The recommended implementation path is split into two related tracks:

- **Track A: Outbound MCP plugin robustness** - SimpleChat acts as an MCP client that connects to external MCP servers such as Splunk.
- **Track B: Inbound SimpleChat MCP server** - SimpleChat exposes a small, governed MCP server surface so approved MCP clients can call SimpleChat tools.

Track A should start by hardening the existing token-based tool flow, then add capability probing and richer metadata, then add OAuth 2.1 PKCE as a distinct advanced-auth feature. Track B should be planned as a separate enterprise-ready implementation. PR #722 provides useful intent and a candidate initial tool list, but the implementation in that PR should not be copied directly because it is not robust, scalable, or enterprise-ready enough for this feature.

## PR #722 Review Summary

PR #722, **MCP Server addition and modification of SimpleChat API to accommodate...**, introduces an external FastMCP app under `application/external_apps/mcp/` plus small SimpleChat API and authentication changes. The PR is useful as a prototype and requirements signal, especially for the smaller initial MCP tool set. It should not be treated as the target architecture.

### Useful Intent To Carry Forward

- Start with a small inbound SimpleChat MCP tool surface rather than full SimpleChat feature parity.
- Prefer personal-scope read tools before group, public, or all-scope tools.
- Include Protected Resource Metadata (PRM) and bearer-token interoperability in the design.
- Keep potentially broader group/public/all-scope tools disabled until policy, role, and workspace checks are fully designed.
- Add a way for MCP clients to inspect required auth status if needed, subject to redaction and claims minimization; do not expose a user profile tool in the initial set.

### Implementation Patterns To Avoid

- Do not relax the shared `accesstoken_required` decorator from `ExternalApi` to broad `User` or `Admin` access. That would widen the trust boundary for all existing external routes that use the decorator.
- Do not add a broad `/external/login` bearer-to-Flask-session bridge without feature flags, app ID allowlists, audience validation, governance, audit logging, and clear user/app-token separation.
- Do not rely on in-memory session/token caches as production state.
- Do not use environment variables such as `ENABLE_UNAPPROVED_TOOLS` as the enterprise authorization model for group, public, or all-scope tools.
- Do not expose all-scope search or all-scope chat as an initial capability.
- Do not modify interactive auth routes such as `/getATokenApi` to mix browser login, local redirects, and machine-to-machine session creation without a separate security design.

## Goals

- Keep existing MCP action manifests backward compatible.
- Improve Splunk MCP Server setup reliability for token-based bearer authorization.
- Support common enterprise MCP requirements such as custom headers, diagnostics, redaction, and optional TLS/certificate references.
- Add OAuth 2.1 PKCE support without mixing external MCP token storage into the app sign-in token cache.
- Improve tool discovery, tool metadata, argument validation, and large-result behavior.
- Keep tools as the primary supported MCP surface while leaving resources, prompts, streaming, and long-running jobs as later enhancements.
- Add an enterprise-ready plan for a SimpleChat inbound MCP server after outbound MCP plugin hardening is under way.
- Start inbound SimpleChat MCP with a small, personal-scope tool set and grow only after governance, authorization, observability, and scaling controls are in place.
- Use a combined access model where Entra roles/scopes and client allowlists provide coarse app access, SimpleChat governance provides user/source policy, and existing workspace roles protect data.
- Add fine-grained outbound MCP destination controls so admins can restrict which external MCP servers may be used by personal, group, or global actions.
- Add a server-side catalog of preconfigured outbound MCP servers so useful unauthenticated or low-friction MCP servers can be created from trusted templates without confusing them with compatibility presets.
- Classify preconfigured outbound MCP servers by risk and auth tier, including future authenticated enterprise templates for Microsoft Sentinel MCP and Azure MCP Server.
- Manage outbound MCP destination and preconfiguration policy through SimpleChat's governance/item-delegation model where possible, using roles only as coarse access gates.

## Non-Goals For The First Slice

- Do not implement OAuth 2.1 PKCE in the same slice as basic Splunk/token hardening.
- Do not add per-action TLS or client certificate settings until connector support is confirmed.
- Do not add long-running job persistence until a concrete MCP server workflow requires it.
- Do not expose prompts or resources as first-class action behavior until the user experience is designed.
- Do not break existing MCP actions or require existing manifests to be migrated.
- Do not deliver inbound MCP full feature parity with the SimpleChat web UI or internal SimpleChat plugin in the first inbound slice.
- Do not enable group, public, or all-scope inbound MCP tools until workspace role checks and governance policy are explicitly wired and tested.
- Do not use PR #722's external app as-is as the production MCP server.
- Do not ship broad outbound preconfigured MCP server creation without server-side destination governance and backend enforcement during action save, discovery, and runtime invocation.
- Do not ship Microsoft Sentinel MCP or Azure MCP Server as default unauthenticated preconfigurations; they require explicit admin governance, identity/token design, tool allowlists, source/destination controls, and audit readiness.

## Track A: Outbound MCP Plugin Robustness

### Phase 1: Baseline Hardening For Splunk And Token-Based MCP

1. Add a Splunk-friendly preset or profile.
   - Set `transport=streamable_http`.
   - Set `auth_method=bearer`.
   - Set `load_tools=true`.
   - Set `load_prompts=false`.
   - Recommend conservative tool allowlists for sensitive tools such as broad query, user info, or user list operations.

2. Add safe custom HTTP headers.
   - Add a `custom_headers` field to MCP `additionalFields`.
   - Validate header names with a strict allowlist such as `^[A-Za-z0-9_-]+$`.
   - Redact custom header values in logs, API responses, UI summaries, and test artifacts.
   - Merge custom headers with auth headers in `McpPluginFactory._build_headers`.
   - Let auth headers win by default unless an explicit, reviewed override path is added.

3. Improve endpoint and transport validation.
   - Keep `http` and `https` for `streamable_http` and `sse`.
   - Keep `ws` and `wss` for `websocket`.
   - Enforce non-empty host values.
   - Reject unsupported schemes.
   - Preserve the current restriction that `stdio` is only available for admin-managed global actions.

4. Improve timeout and retry controls.
   - Keep existing timeout bounds of 1-300 seconds.
   - Add optional retry count and backoff settings for discovery and tool calls.
   - Do not change existing defaults in a way that changes current behavior.
   - Classify timeout errors so Splunk query guardrails are easier to distinguish from network failures.

5. Improve error surfaces and redaction.
   - Return enough detail to distinguish DNS/connect, TLS, authentication, MCP initialization, discovery, and tool execution failures.
   - Redact `auth.key`, bearer tokens, API keys, basic credentials, OAuth tokens, and sensitive custom header values.
   - Ensure secrets never appear in logs, rendered HTML, browser-visible JSON, or docs examples.

6. Add Phase 1 tests.
   - Cover `streamable_http` bearer header construction.
   - Cover custom header validation and redaction.
   - Cover secret hydration during discovery.
   - Cover invalid and expired token error shapes with mocked connector failures.
   - Cover tool allowlist behavior.
   - Cover backward-compatible manifest normalization.

### Phase 1B: Outbound Destination Governance And Preconfigured Server Catalog

Status: **implemented as the first server-side slice in v0.250.064**. Admin UI and persisted item-delegation policy management are split into Phase 1C.

This phase is separate from MCP server presets.

- **Preset**: compatibility defaults for a class of MCP server, such as Generic MCP Server or Splunk MCP Server. Presets set transport/auth/timeouts/help text but should not represent a concrete destination.
- **Preconfiguration**: a concrete action template for a known MCP server, such as Microsoft Learn, GitHub documentation, or Azure documentation. Preconfigurations may include endpoint, transport, auth method, default tool allowlist, documentation links, and scope eligibility.

1. Add fine-grained outbound MCP destination allowlisting.
   - Admins must be able to control which external MCP destinations can be used for personal, group, and admin/global actions.
   - Policies should support exact URL, origin, hostname, path-prefix, and wildcard matching.
   - Policies should support action scope: personal, group, global/admin, and future public workspace scopes if outbound actions are added there.
   - Policies should support target scope IDs such as a specific user, specific group, all groups, or all personal actions.
   - Policies should support transport restrictions such as `streamable_http`, `sse`, `websocket`, and admin-only `stdio`.
   - Policies should optionally bind to a preset ID or preconfiguration ID.
   - Policies should optionally restrict auth methods so a destination can be allowed only for no-auth, bearer, API key, basic, identity, or future OAuth.
   - Policies should allow wildcard `*` for organizations that do not want outbound destination filtering.
   - Default compatibility posture should preserve existing behavior until an admin enables enforcement; secure deployments can switch to deny-by-default.

2. Enforce destination policy server-side.
   - Enforce during action create and update.
   - Enforce during MCP discovery and compatibility probe.
   - Enforce during runtime tool invocation.
   - Do not rely on frontend filtering alone.
   - Store the normalized destination decision with enough audit context to explain why a call was allowed or denied.

3. Add outbound SSRF and endpoint-safety guardrails.
   - Normalize URLs before policy evaluation.
   - Reject credentials embedded in URLs.
   - Reject unsupported schemes.
   - Prevent redirects from bypassing destination policy.
   - Consider blocking private, loopback, link-local, and metadata-service IP ranges unless an admin explicitly allows them for a trusted internal deployment.
   - Treat DNS rebinding and CNAME-to-private-IP behavior as security risks when resolving destinations.
   - Preserve the existing restriction that `stdio` is only available for admin-managed global actions.

4. Add a server-side preconfigured MCP server catalog.
   - Store preconfiguration definitions outside browser-static files.
   - Validate definitions against a JSON schema before returning them to the browser.
   - Return sanitized definitions through an authenticated API route.
   - Allow bundled shippable definitions and optional organization-provided definitions.
   - Never include secrets, tokens, passwords, tenant-specific credentials, or customer data in definitions.

5. Initial shippable preconfiguration candidates.
   - Microsoft Learn MCP server.
   - Azure documentation MCP server.
   - GitHub documentation MCP server.
   - SimpleChat local MCP development server as a development-only catalog item when local/dev mode is enabled.

6. Future authenticated enterprise preconfiguration template candidates.
   - Microsoft Sentinel MCP server.
     - Treat as an Entra-authenticated, high-risk security-data connector, not an unauthenticated docs connector.
     - Track prerequisites such as Sentinel data lake onboarding, Microsoft Defender/Sentinel product access, and Security reader or product-specific permissions.
     - Default to disabled until admin approval, source allowlisting, destination governance, identity/token refresh, per-tool allowlists, and audit logging are complete.
     - Start with read-oriented/data exploration or triage tool collections only; never enable all Sentinel tools by default.
   - Azure MCP Server.
     - Treat as an Entra/Azure-authenticated, high-risk operational connector because it can inspect and potentially change Azure resources.
     - Do not have SimpleChat execute local `npx`, `dnx`, `uvx`, Docker, or other command-based MCP servers from user input.
     - Support only organization-hosted remote Azure MCP endpoints initially, or a later explicitly designed managed connector.
     - Prefer read-only mode, explicit enabled service namespaces, and conservative tool allowlists before any mutating Azure tools are exposed.

7. Define preconfiguration metadata.
   - Stable `id`.
   - Display name and description.
   - Provider/category.
   - Endpoint and transport.
   - Preset ID to apply first.
   - Auth requirement: none, optional, required, or identity-backed.
   - Auth tier: public unauthenticated, user-provided credential, delegated OAuth/Entra, app identity, or organization-hosted.
   - Deployment model: hosted remote endpoint, organization-hosted remote endpoint, or local/stdio reference only.
   - Default custom headers by name only, never secret values.
   - Default allowed tool names when the server has broad tools.
   - Scope eligibility: personal, group, global/admin.
   - Destination policy tags.
   - Risk label and admin-facing notes.
   - Required governance gates such as source allowlisting, destination allowlisting, per-tool policy, read-only mode, and audit requirements.
   - Documentation URL.
   - Enabled/disabled flag.

8. Add modal flow for "Create from preconfigured MCP server."
   - The client should call the server-side preconfiguration API.
   - The dropdown should show only definitions allowed for the current action scope and governance context.
   - Selecting a preconfiguration should populate the MCP action form.
   - The user should still be able to review, discover tools, adjust allowed tools, and save.
   - Save/discovery/runtime must still pass server-side destination policy.

9. Add outbound destination and preconfiguration tests.
   - Exact host allow.
   - Wildcard allow.
   - Personal action destination denied while group action destination allowed.
   - Specific group destination denied while other groups are unaffected.
   - Destination policy enforced on save, discovery, and runtime invocation.
   - Redirect/private-IP policy cannot bypass allowlisting.
   - Preconfigured catalog definitions validate against schema.
   - Disabled or scope-ineligible preconfigurations are not returned to the modal.
   - Preconfigurations never expose secrets.
   - Creating from catalog produces the expected MCP manifest fields.

Implemented Phase 1B artifacts:

- `functions_mcp_destinations.py` for config/env-backed destination allowlists, endpoint normalization, unsafe literal-IP blocking, and save/discovery/runtime enforcement.
- `functions_mcp_preconfigurations.py` plus `mcp_preconfigurations/` JSON schema and bundled Microsoft Learn, Azure documentation, GitHub, and local development definitions.
- `GET /api/plugins/mcp/preconfigurations` for authenticated, scope-filtered catalog retrieval.
- MCP modal preconfiguration dropdown that applies server-returned definitions without hard-coded provider logic.
- `preconfiguration_id` storage in MCP `additionalFields`.
- `MCP_SERVER_PRECONFIGURATIONS.md` documentation and functional/UI test coverage.

Future authenticated enterprise catalog entries are now tracked separately from the initial unauthenticated/low-friction catalog. Microsoft Sentinel MCP and Azure MCP Server should be added as disabled-by-default, admin-governed templates only after the identity, source allowlisting, destination governance, per-tool policy, and audit gates above are ready.

### Phase 1C: Destination Governance UI And Policy Persistence

Status: **implemented as the first admin-governed persistence slice in v0.250.065**. Future catalog administration can add per-definition enable/disable switches, but destination and preconfiguration use is now governable through delegated item policies.

Phase 1B added the server-side enforcement hooks and configuration-backed policy evaluation. Phase 1C makes that governable by administrators through the existing SimpleChat governance model instead of relying on environment variables or one-off MCP-specific controls.

Recommended approach:

- Use existing governance/item-delegation policy primitives as the durable control plane whenever possible.
- Use roles as a coarse prerequisite for whether a user, group, or admin can create/use MCP actions at all.
- Use governance policy for fine-grained decisions about destinations, preconfiguration IDs, transport, auth method, action scope, target user/group, and future tool exposure.
- Avoid creating a parallel "MCP-only governance island" unless the existing policy model cannot represent the required decisions safely.

1. Add persisted outbound MCP destination policy fields.
   - Represent personal, group, and global/admin policies independently. **Implemented with `mcp_personal_destination`, `mcp_group_destination`, and `mcp_global_destination` delegated item policy entity types.**
   - Support target identifiers such as a specific user, all personal actions, a specific group, all groups, and global/admin actions. **Implemented through existing item-policy allow-all/user/group principal allowlists plus `group:<group-id>::<pattern>` item IDs for group-specific overrides.**
   - Support allowed destination patterns: `*`, exact origin, hostname, wildcard hostname, URL prefix, `preset:<id>`, `preconfiguration:<id>`, and `transport:<transport>`. **Implemented in the shared destination evaluator.**
   - Support optional auth-method restrictions: none, bearer, API key, basic, identity, and future OAuth.
   - Preserve compatibility when destination governance is disabled.
   - Keep deny-by-default available for secure deployments.

2. Add admin UI controls for MCP destination governance.
   - Surface controls under the existing admin governance/settings area rather than creating an unrelated MCP-only page.
   - Let admins enable/disable destination enforcement.
   - Let admins edit global/admin, personal, and group policy scopes.
   - Let admins add per-group overrides without affecting personal actions or other groups.
   - Let admins explicitly allow `*` when identity/governance is sufficient and destination filtering is not desired.
   - Display clear warnings for wildcard rules, local/private endpoints, bearer-token destinations, and broad preconfiguration enablement.
   - **Implemented admin controls for destination enforcement, unsafe literal-IP blocking, and creating delegated destination policies for personal, group, and global scopes.**

3. Add preconfiguration enablement and eligibility controls.
   - Allow admins to enable/disable bundled and organization-provided preconfigurations. **Still planned as a future catalog-administration refinement.**
   - Allow policy to restrict which preconfiguration IDs can be used in personal, group, or global/admin contexts. **Implemented through `preconfiguration:<id>` destination policies.**
   - Ensure the preconfiguration API returns only definitions that are enabled and eligible for the caller's scope/governance context. **Implemented for scope and destination-governance eligibility.**
   - Keep definitions secret-free; credentials still come from the user's/admin's action configuration or future workspace identity/OAuth flows.

4. Wire persisted policy into enforcement.
   - Update `functions_mcp_destinations.py` to read governance-backed policy before falling back to config/env policy. **Implemented by merging delegated item policies into the existing policy config.**
   - Enforce the same policy during action create/update, discovery/probe, and runtime invocation. **Implemented with caller identity on save/discovery and request/stored identity where available at runtime.**
   - Keep audit-safe allow/deny reasons consistent across save, discovery, and runtime.
   - Do not rely on frontend filtering for enforcement.

5. Add governance UI and backend tests.
   - Enabled/disabled governance preserves current compatibility behavior.
   - Personal policy does not affect group action behavior.
   - Group policy does not affect personal action behavior.
   - A specific group policy does not affect other groups.
   - Wildcard `*` allows destinations only in the intended scope.
   - `preconfiguration:<id>` rules allow only the intended preconfiguration.
   - Disallowed destinations are rejected on save, discovery, and runtime invocation.
   - UI/API responses never expose credentials, tokens, raw settings, or internal policy implementation details.

### Phase 1D: Authenticated Enterprise Preconfiguration Templates For Sentinel And Azure MCP

Status: **implemented in v0.250.066 as a guarded catalog/template foundation**. This phase adds catalog support for high-value Microsoft enterprise MCP servers without treating them as public unauthenticated defaults or complete token-lifecycle integrations.

1. Add catalog tiering for authenticated enterprise templates.
   - Separate public unauthenticated starter entries from authenticated enterprise entries and organization-hosted templates.
   - Keep enterprise templates disabled by default until an admin explicitly enables them for a scope.
   - Require destination governance and `preconfiguration:<id>` policy support before enterprise templates are returned to non-admin users.
   - Show admin-facing warnings for security-data access, cloud-resource access, mutating tools, wildcard destinations, and broad tool allowlists.

2. Add Microsoft Sentinel MCP as a future enterprise template.
   - Classify as high risk because it can expose security operations data such as alerts, incidents, entities, evidence, and hunting/query results.
   - Require Microsoft Entra identity and product prerequisites rather than static unauthenticated access.
   - Gate use by admin approval, user/group policy, source allowlisting, destination allowlisting, and per-tool allowlists.
   - Prefer the smallest read-oriented Sentinel tool collections first; defer custom tool creation, agent creation, and broader triage/action tools until governance and audit controls are mature.
   - Document prerequisites and expected roles/permissions instead of embedding tenant-specific endpoints, secrets, or credentials.

3. Add Azure MCP Server as a future enterprise template.
   - Classify as high risk because it can inspect and potentially modify Azure resources across many services.
   - Treat local package-run configurations as documentation references only; SimpleChat should not execute user-supplied local MCP commands.
   - Support an organization-hosted remote Azure MCP endpoint first, with admin-provided endpoint details and no bundled secrets.
   - Require read-only mode and explicitly enabled Azure service namespaces by default.
   - Defer mutating Azure tools until OAuth/identity, RBAC, per-tool policy, audit logging, and operator warnings are complete.

4. Add validation gates before either template is broadly usable.
   - Identity/token handling supports expiry and refresh without mixing MCP tokens into SimpleChat sign-in token caches.
   - Admins can restrict by user, group, action scope, destination, source/client, preconfiguration ID, and tool name.
   - Audit logs identify the user, workspace/group, MCP destination, preconfiguration ID, tool invoked, allow/deny reason, and redacted result summary.
   - Tests prove disabled templates are hidden from ordinary users, policy-enabled templates appear only in the intended scope, and high-risk tools are not enabled by default.

Implemented Phase 1D artifacts:

- Extended MCP preconfiguration schema metadata for catalog tier, auth tier, deployment model, disabled-by-default status, endpoint review, required governance gates, and operator notes.
- Added bundled enterprise templates:
  - `microsoft_sentinel`
  - `azure_mcp_server`
- Kept enterprise templates hidden unless MCP destination governance is enabled and a matching explicit `preconfiguration:<id>` policy allows the requested scope.
- Kept enterprise template defaults tool-safe by setting `load_tools=false` and no default tool allowlist.
- Added modal warning/help text for high-risk or warning-bearing preconfigurations.
- Added functional/UI coverage for enterprise template metadata, hidden-by-default behavior, explicit policy requirements, and warnings.

### Phase 1E: Implementation-Specific Catalog Schemas

Status: **implemented in v0.250.067 as a base-schema plus provider-schema framework**. This phase keeps outbound MCP presets and preconfigurations extensible without pushing Sentinel-, Azure-, GitHub-, or Splunk-specific fields into the generic catalog schemas.

1. Split catalog validation into provider-neutral and implementation-specific layers.
   - Keep `mcp_server_preset.schema.json` and `mcp_server_preconfiguration.schema.json` focused on common catalog fields.
   - Add `implementation` metadata and non-secret `additionalSettings` to catalog definitions.
   - Validate `additionalSettings` through `implementation_schemas\{implementation-id}.preset.schema.json` or `implementation_schemas\{implementation-id}.preconfiguration.schema.json`.

2. Migrate bundled definitions into the framework.
   - Add implementation schemas for generic, Splunk, Microsoft Learn, GitHub, local development, Microsoft Sentinel, and Azure MCP Server.
   - Move provider-specific traits such as Sentinel tool collections, Azure service namespace allowlists, GitHub permission model hints, and Splunk compatibility metadata into implementation-specific `additionalSettings`.
   - Reject secret-like fields in `defaults` and implementation-specific `additionalSettings`.

3. Harden enterprise preconfiguration use beyond dropdown filtering.
   - Enforce explicit enterprise preconfiguration policy during direct action save/update, discovery, and runtime connector creation.
   - Require endpoint-reviewed enterprise templates to also match a specific destination policy for the governed endpoint, not just `preconfiguration:<id>`.
   - Default Sentinel and Azure MCP enterprise templates to reusable identity auth rather than bearer-token entry.

Implemented Phase 1E artifacts:

- Added `functions_mcp_catalog_implementations.py` for implementation ID normalization, secret-like field detection, and schema-backed `additionalSettings` validation.
- Added implementation schema directories under `mcp_presets` and `mcp_preconfigurations`.
- Updated bundled presets/preconfigurations to include `implementation` and validated `additionalSettings`.
- Updated MCP action normalization and modal payload generation so selected preconfiguration implementation metadata is copied into saved actions.
- Added functional/UI coverage for custom implementation schemas, direct enterprise policy denial, endpoint-specific enterprise approval, and identity-backed enterprise defaults.

### Phase 2: Capability Probe And Tool Metadata Robustness

Status: **implemented in v0.250.068 as outbound discovery probing, richer cached tool metadata, opt-in argument validation, large-result policies, and modal warnings.**

1. Add an MCP compatibility probe endpoint or discovery mode.
   - Reuse `McpPluginFactory.create_connector`.
   - Connect to the MCP server and list tools.
   - Capture server/session capability data where the Semantic Kernel connector exposes it.
   - Return transport, auth method, tool count, capability hints, and warnings.

2. Expand cached tool metadata.
   - Preserve `original_name`, Semantic Kernel-safe `function_name`, description, and input schema.
   - Preserve annotations if available.
   - Add optional output schema and structured-content hints if available.
   - Keep compatibility with existing `mcp_tools` entries.

3. Add opt-in input schema validation.
   - Add a `validate_tool_arguments` MCP setting.
   - Validate against discovered JSON Schema before invocation when enabled.
   - Default to disabled or warning-only initially to avoid breaking dynamic calls.

4. Improve result handling.
   - Replace the single hard-coded truncation behavior with explicit policies.
   - Default policy: `truncate`.
   - Optional policy: `error_on_limit`.
   - Later policy: `store_reference` for Blob/Cosmos-backed large outputs.

5. Add UI warnings.
   - Warn when a server exposes no tools.
   - Warn when discovery fails but cached tools remain.
   - Warn when duplicate names require function-name normalization.
   - Warn when prompts/resources are requested but unsupported.
   - Warn when schemas are too broad for safe auto-exposure.

Implemented Phase 2 artifacts:

- Discovery now uses an MCP compatibility probe that returns the existing `tools` payload plus transport, auth method, capability hints, and non-blocking warnings.
- Cached MCP tool metadata now preserves output schemas, annotations, and structured-content hints when the connector exposes them.
- Added optional `validate_tool_arguments` schema checks against cached input schemas before configured tool invocation.
- Added `tool_result_policy` with backward-compatible `truncate` behavior and an `error_on_limit` option for oversized MCP tool results.
- Updated the MCP action modal to display discovery warnings and summarize validation/result policy settings.
- Added functional/UI coverage for metadata preservation, broad-schema warnings, argument validation, large-result policy behavior, and saved modal payloads.

### Phase 3: TLS And Enterprise Network Options

1. Confirm connector support before adding per-action TLS settings.
   - Prefer OS/container trust store guidance first.
   - Only expose per-action options if the connector stack can safely use them.

2. Add optional TLS settings if support exists.
   - Consider `tls_verify`.
   - Consider `ca_certificate_secret_id`.
   - Consider `client_certificate_identity_id`.
   - Store certificate material through Key Vault or workspace identities, not directly in `additionalFields`.

3. Add diagnostics for enterprise network failures.
   - DNS/connect timeout.
   - TLS validation failure.
   - HTTP authentication failure.
   - MCP initialization/list-tools failure.
   - Tool call failure.

### Phase 4: OAuth 2.1 PKCE

1. Add a new MCP auth method such as `oauth_pkce`.

2. Add explicit OAuth fields.
   - Authorization URL.
   - Token URL.
   - Client ID.
   - Optional client secret reference.
   - Redirect/callback mode.
   - Scopes.
   - Optional audience/resource value.
   - Token refresh behavior.

3. Add Splunk-specific OAuth defaults where a Splunk profile is selected.
   - Pin scopes to `openid offline_access` for Splunk MCP OAuth preview.
   - Surface clear errors for callback mismatch and scope negotiation failures.

4. Implement state and PKCE verifier handling.
   - Store transient state and code verifier in server-side session or a short-lived Cosmos record.
   - Key state to user, action, and scope.
   - Validate callback state before exchanging the code.

5. Add callback routes.
   - Use the standard route decorators required by the repository.
   - Keep external MCP OAuth token cache separate from the application sign-in MSAL cache.
   - Reuse patterns from existing authentication helpers where appropriate.

6. Store tokens securely.
   - Reuse workspace identities and Key Vault secret-reference patterns.
   - Never store refresh tokens directly in the action manifest.
   - Track token expiry.
   - Refresh before discovery/tool calls when expired or after 401 responses.

7. Add OAuth UI behavior.
   - Connect.
   - Reconnect.
   - Disconnect.
   - Scope display.
   - Token expiry status.
   - Clear failure states for revoked clients, refresh failures, callback mismatch, and missing provider support.

8. Add OAuth tests.
   - PKCE verifier/challenge generation.
   - State validation.
   - Callback validation.
   - Mocked token exchange.
   - Refresh flow.
   - Scope pinning.
   - Redaction.
   - Header generation from refreshed tokens.

### Phase 5: Prompts, Resources, Streaming, And Long-Running Calls

1. Keep tools as the primary SimpleChat MCP action path.

2. Add prompts/resources only after UX design.
   - Add separate cached metadata fields for `mcp_resources`, `mcp_resource_templates`, and `mcp_prompts`.
   - Add explicit UI toggles.
   - Add warnings when a server does not support the requested capability.

3. Add streaming or large-result support after result policies are stable.
   - Prefer bounded paging or stored references over dumping large outputs into chat history.
   - For Splunk, keep query defaults within the documented 1-minute and 1000-event guardrails.

4. Add long-running call support only if required.
   - Use a persisted job model rather than in-memory polling.
   - Include cleanup and retention settings.
   - Ensure app restarts do not lose tool state.

## Track B: Inbound SimpleChat MCP Server

The inbound MCP server is a separate feature track from outbound MCP plugin robustness. It should let approved MCP clients call a small, governed set of SimpleChat tools while preserving SimpleChat's existing user, workspace, governance, audit, and security boundaries.

### Phase B0: Architecture Decision

Status: **Architecture decision recorded in version 0.250.062; disabled shell implemented in version 0.250.063.** See [Inbound SimpleChat MCP Server Architecture](./INBOUND_MCP_SERVER_ARCHITECTURE.md).

1. Choose the first production hosting model.
   - **Recommended first design target:** a first-class SimpleChat component or tightly integrated service layer that can share existing settings, auth validation, governance, logging, and operation helpers.
   - **Possible later deployment target:** a separate sidecar/container MCP server for independent scale, as long as it uses the same hardened auth and tool-service layer.

2. Keep the MCP tool implementation behind a reusable service layer.
   - Avoid binding business logic directly to FastMCP decorators or Flask routes.
   - Let MCP transport handlers, HTTP routes, tests, and future deployment shapes reuse the same authorization-aware operation functions.

3. Define supported MCP transport for the first release.
   - Start with streamable HTTP.
   - Add SSE only if required by target clients.
   - Do not support stdio for inbound SimpleChat production hosting.

4. Define scale assumptions before implementation.
   - No process-local token/session state as the source of truth.
   - Use stateless bearer validation and existing durable SimpleChat data stores.
   - Ensure app restarts, multi-instance hosting, and horizontal scale do not lose authorization state.

### Phase B1: Auth Foundation And Protected Resource Metadata

Status: **Auth foundation and PRM contract recorded in version 0.250.062; dedicated disabled-shell guard and PRM route implemented in version 0.250.063; mutable runtime settings moved to app_settings with minimal OS-gated admin UI in version 0.250.071; Easy Auth exclusion modal and server-side enablement guard implemented in version 0.250.072; cloud-aware generated setup script with backup implemented in version 0.250.073; script copy button and authsettingsV2 GET read fix implemented in version 0.250.074; default delegated scope and setup-script delegated-scope preflight implemented in version 0.250.075; PRM discovery challenge implemented in version 0.250.076; inbound MCP governance UI implemented in version 0.250.077; delegated user role and future app-only role split implemented in version 0.250.078; MCP governance help modals implemented in version 0.250.079; inbound MCP governance simplified to personal access plus source policies in version 0.250.080.** See [Inbound SimpleChat MCP Server Architecture](./INBOUND_MCP_SERVER_ARCHITECTURE.md).

1. Add a dedicated inbound MCP auth guard.
   - Do not weaken or broaden the shared `accesstoken_required` decorator used by existing external routes.
   - Require valid token issuer, tenant, expiration, and audience for SimpleChat.
   - Support the required Entra token version intentionally rather than by accident.
   - Require a dedicated delegated user app role such as `InboundMCPUserAccess` plus a separate delegated scope such as `DelegatedMcpServerAccess` for interactive user clients.
   - Reserve an app-only app role such as `InboundMCPAppAccess` for future non-personal service/admin tools.
   - Add an allowed client application ID list similar to the existing CI bearer-session allowlist pattern.
   - Include source allowlist context in the auth/governance decision, while treating custom headers, Origin, Referer, and User-Agent as supplemental signals rather than primary identity proof.

2. Separate app-only and delegated user access.
   - User-data tools must run with a delegated user identity or validated on-behalf-of flow.
   - App-only tokens must not be bridged into per-user sessions that can read personal conversations or documents.
   - Admin/app-only tools can be considered later, but they need separate governance and audit design.

3. Add PRM support.
   - Serve `.well-known/oauth-protected-resource` metadata for the MCP server endpoint.
   - Derive resource and authorization server metadata from validated configuration.
   - Avoid exposing secrets or internal endpoints in metadata.

4. Avoid broad bearer-to-session bridging.
   - If a session bridge is needed, model it after the existing CI bearer-session pattern: feature flag, required role, client app allowlist, audit logging, and clear expiry behavior.
   - Prefer direct service-layer execution under validated claims over creating long-lived Flask sessions for MCP clients.

### Phase B2: Governance, Roles, And Tool Policy

Status: **Initial explicit item-policy evaluator implemented in version 0.250.070 for the first personal read tool. Minimal Admin Settings controls for runtime enablement, Entra scope/user role/app-only role, client allowlist, tenant allowlist, source allowlist, and source header were added across versions 0.250.071 and 0.250.078. Easy Auth exclusion verification is required before enabling the server as of version 0.250.072. Version 0.250.080 simplifies current inbound MCP governance to two required policy concepts: personal access and source. Broader capability/tool policy authoring UX and additional tools remain future work.**

Use a combined model rather than choosing only governance or only roles:

- **Entra roles/scopes** provide the coarse gate: the caller can reach the inbound MCP surface.
- **Client app allowlists** provide client trust: the calling application is approved.
- **SimpleChat governance** provides delegated user/source policy: which users or groups can use personal inbound MCP and which sources are allowed.
- **Existing workspace roles** protect data: the delegated user must already be allowed to access the requested personal, group, or public resource.

1. Add inbound MCP governance settings.
   - Global enablement flag for inbound MCP remains in runtime configuration.
   - Tenant and client application allowlists remain in inbound MCP runtime configuration because they are app trust controls, not user governance controls.
   - Current user governance uses `inbound_mcp_access` with item `personal`; the allow-all toggle, allowed users, and allowed groups decide who can use personal inbound MCP.
   - Current source governance uses `inbound_mcp_source` with item `*` or a resolved source id; the policy's allow-all/users/groups decide who may satisfy that source rule.
   - Future capability governance should use admin-friendly capability names such as `personal_read`, `personal_search`, `workflow_execute`, or `group_read` instead of raw tool names.
   - Future per-resource-family, per-operation, per-scope, and per-target policy should be added only when it maps to clear admin workflows and does not duplicate existing workspace authorization.
   - Optional per-client or per-user rate limits remain future work.

2. Keep the initial tool registry explicit.
   - Each MCP tool should declare required identity type, workspace scope, resource family, operation, feature flags, governance keys, rate-limit category, and audit event type.
   - Do not expose a tool simply because a Python function exists.

3. Reuse existing authorization helpers.
   - Personal tools must validate current-user ownership.
   - Group tools must use the same group role checks used by web/API routes.
   - Public workspace tools must use the same public workspace role and workspace-status checks used by existing external/public routes.
   - Governance must deny by default when personal access or source policy is not configured.
   - Fine-grained governance allow must never grant data access that existing workspace authorization would deny.

4. Evaluate policy with deny-by-default and explicit-deny precedence.
   - Missing policy denies the operation.
   - Explicit deny wins over allow.
   - Personal access should use delegated item `personal`; do not encode user authorization into item ids such as `personal:*`.
   - Source policy item `*` disables source filtering only for principals allowed by that source policy; identity, client app configuration, personal access governance, and workspace authorization still apply.

### Phase B3: Initial Personal Read And Workflow Tool Set

Status: **First governed personal read tool implemented in version 0.250.070: `list_personal_tags`. Other planned personal tools remain disabled until their service-layer authorization, bounds, and tests are complete.**

Start with a small, personal-scope set inspired by PR #722, not full feature parity. Most actions are read-only. `execute_workflow` is intentionally treated as an execution/write operation and must stay behind explicit governance, workflow ownership, rate limiting, and audit controls.

1. `list_conversations`
   - Return only conversations visible to the delegated user.
   - Include pagination and maximum result limits.

2. `get_conversation_messages`
   - Require conversation ownership or collaboration access.
   - Include pagination and maximum message limits.

3. `list_personal_documents`
   - Return only the delegated user's personal documents.
   - Include pagination, filtering, and result limits.

4. `list_personal_prompts`
   - Return only the delegated user's personal prompts.
   - Include pagination and result limits.

5. `list_personal_tags`
   - Return only personal workspace tags available to the delegated user.
   - Include pagination or bounded result limits if the tag set grows.
   - Implemented in version **0.250.070**. As of version **0.250.080**, exposure requires personal access governance for item `personal` plus source governance for `*` or a resolved source id; client allowlisting lives in inbound MCP runtime configuration.

6. `search_personal_documents`
   - Restrict to personal document scope.
   - Require bounded `top_n`.
   - Preserve existing search and embedding error behavior.

7. `execute_workflow`
   - Trigger only explicitly governed personal workflows owned by the delegated user.
   - Require workflow execution governance separate from read-only list/retrieve/search operations.
   - Preserve workflow runner guardrails: distributed run lock, status updates, token/cost logging, audit logging, and bounded response metadata.

### Phase B4: Personal Chat Write Tool

Add `send_personal_chat_message` only after Phase B3 is stable.

Required guardrails:

- Personal scope only.
- Valid delegated user identity.
- Conversation ownership validation when `conversation_id` is supplied.
- Explicit behavior for new-conversation creation.
- Content safety behavior preserved.
- Model invocation and token/cost logging preserved.
- Rate limiting and abuse protections.
- Bounded response size.
- Audit events that identify caller app, user, tool, conversation, and success/failure without logging message secrets.

### Phase B5: Deferred Group, Public, And All-Scope Tools

Keep these tools disabled until explicit design and testing are complete:

- `list_group_workspaces`
- `list_group_documents`
- `list_group_prompts`
- `list_public_workspaces`
- `list_public_documents`
- `list_public_prompts`
- All-scope `search_documents`
- All-scope `send_chat_message`

Prerequisites before enabling:

- Reuse existing group/public role and workspace-status checks.
- Add governance controls per tool and scope.
- Add tenant/client/user audit logging.
- Add pagination and result limits.
- Add negative tests for users without workspace access.
- Add admin UX for enabling specific tools/scopes rather than relying on environment variables.

### Phase B6: Enterprise Readiness

1. Observability.
   - Use `log_event`, not `print()`.
   - Add correlation IDs across MCP requests, tool execution, and downstream SimpleChat operations.
   - Track caller app ID, delegated user ID, tool name, duration, result status, and error type.
   - Redact tokens, secrets, prompts, and sensitive document content.

2. Reliability and scale.
   - Avoid in-memory token/session caches as production state.
   - Set bounded request timeouts.
   - Add retry only where safe and idempotent.
   - Add health/readiness endpoints for the MCP hosting surface.
   - Ensure multi-instance deployments behave consistently.

3. Security hardening.
   - Validate token audience and issuer before shipping user-data tools.
   - Keep auth failures distinct from governance denials.
   - Add rate limits and tool-level throttles.
   - Keep raw settings out of frontend/API responses.
   - Confirm MCP metadata and tool schemas do not expose internal secrets or URLs.

4. Documentation and operations.
   - Document app registration setup.
   - Document PRM metadata.
   - Document inbound MCP governance setup.
   - Document the initial supported tool set and explicit non-goals.
   - Document how admins can disable a client, user, tool, or scope.

## Files Expected To Change

### MCP Plugin And Validation

- `application/single_app/functions_mcp_operations.py`
  - Normalize and validate custom headers, outbound destination metadata, OAuth config, retry settings, result policy, capability metadata, TLS references, and schema-validation flags.

- New `application/single_app/functions_mcp_destinations.py` or equivalent.
  - Normalize outbound MCP destinations, evaluate per-scope destination policies, block unsafe endpoints, and produce audit-safe allow/deny decisions.

- New `application/single_app/functions_mcp_preconfigurations.py` or equivalent.
  - Load, validate, sanitize, filter, and return shippable, authenticated enterprise, and organization-provided outbound MCP server preconfiguration definitions.

- `application/single_app/semantic_kernel_plugins/mcp_plugin_factory.py`
  - Merge headers, resolve auth/OAuth tokens, evaluate outbound destination policy before connector creation, create connectors, run discovery/probes, serialize results, classify errors, and optionally validate arguments.

- `application/single_app/semantic_kernel_plugins/mcp_plugin.py`
  - Expose discovered tool metadata, enforce tool allowlists, enforce outbound destination decisions before tool calls, route tool calls through validation/result policy, and later expose resources/prompts if supported.

- `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
  - Validate expanded MCP manifest fields, destination policy compatibility, auth-method requirements, header safety, TLS references, OAuth requirements, and timeout/retry limits.

### Routes, UI, And Schemas

- `application/single_app/route_backend_plugins.py`
  - Extend discovery/test routes, hydrate secrets/identities, add destination policy checks, add preconfiguration catalog routes, add compatibility probe route, and later add OAuth connect/callback/disconnect routes.

- `application/single_app/static/js/plugin_modal_stepper.js`
  - Update MCP modal behavior for custom headers, server presets, preconfigured server creation, destination policy feedback, diagnostics, OAuth status, TLS settings, result policy, and richer discovery warnings.

- `application/single_app/templates/_plugin_modal.html`
  - Add controls for new MCP settings and preconfiguration selection without external browser assets.

- `application/single_app/static/json/schemas/mcp_plugin.additional_settings.schema.json`
  - Add expanded MCP settings, destination metadata, preconfiguration IDs, and backward-compatible defaults.

- New `application/single_app/mcp_preconfigurations/` or equivalent.
  - Store server-side outbound MCP preconfiguration JSON schema and bundled catalog definitions, including future disabled-by-default templates for Microsoft Sentinel MCP and Azure MCP Server.

- Existing `application/single_app/mcp_presets/`.
  - Continue storing compatibility presets only; do not mix concrete server preconfigurations into the preset catalog.

### Admin Governance And Settings

- `application/single_app/functions_governance.py`
  - Add outbound MCP destination, scope, and preconfiguration governance helpers if existing item-delegation policy primitives are not sufficient.
  - Prefer extending the existing item-delegation policy model over creating a separate MCP-only authorization store.

- Existing admin settings/governance routes and templates.
  - Phase 1C should surface controls for enabling outbound MCP destination filtering, creating per-personal/group/global policies, configuring per-group overrides, and enabling/disabling shippable preconfigurations.
  - Phase 1D should add enterprise-template policy warnings and eligibility controls for high-risk authenticated entries such as Microsoft Sentinel MCP and Azure MCP Server.

### Shared Auth And Secret Infrastructure

- `application/single_app/functions_authentication.py`
  - Reference existing OAuth patterns. Do not mix external MCP OAuth tokens into the app sign-in cache without deliberate design.
  - Add or reuse hardened token validation for inbound MCP without broadening the existing `accesstoken_required` external-route decorator.

- `application/single_app/functions_workspace_identities.py`
  - Reuse identity and Key Vault-backed secret storage for reusable MCP credentials, certificates, and OAuth tokens.

- `application/single_app/functions_keyvault.py`
  - Reuse secret-reference and redaction patterns for MCP secrets.

### Inbound SimpleChat MCP Server

- New `application/single_app/functions_mcp_server_auth.py` or equivalent.
  - Validate inbound MCP bearer tokens, issuer, audience, client app ID, source context, delegated scope, delegated user role, delegated user identity, and app-only restrictions.

- New `application/single_app/functions_mcp_server_config.py` or equivalent.
  - Normalize app-settings-backed inbound MCP runtime configuration, keep the admin UI feature gate OS/App-Service-environment only, and verify required App Service Authentication excluded paths before enabling inbound MCP.

- New `application/single_app/functions_mcp_server_governance.py` or equivalent.
  - Resolve inbound MCP client/source/tool/resource/operation/scope policy and compose Entra roles/scopes, app allowlists, SimpleChat governance, source allowlists, resource-operation policy, and workspace-role checks.

- New `application/single_app/functions_mcp_server_tools.py` or equivalent.
  - Implement the explicit inbound SimpleChat MCP tool registry and call reusable SimpleChat service functions with authorization-aware context, declared resource family, declared operation, and target-scope policy checks.

- New `application/single_app/route_mcp_server.py` or equivalent.
  - Host streamable HTTP MCP endpoints, PRM metadata, health/readiness behavior, and inbound MCP request handling.

- `application/single_app/app.py`
  - Register inbound MCP routes or blueprint only after the architecture and feature flag are defined.

- `application/single_app/functions_simplechat_operations.py`
  - Reuse or extract operation helpers for personal conversations, personal documents, prompts, search, and later personal chat writes.

- `application/single_app/functions_governance.py`
  - Add inbound MCP feature, client, tool, and scope governance helpers if existing action-governance primitives are not sufficient.

- `application/single_app/functions_settings.py`
  - Persist mutable inbound MCP runtime settings in `app_settings`, while keeping the UI gate out of persisted settings.

- `application/single_app/templates/admin_settings.html` and `application/single_app/templates/_sidebar_nav.html`
  - Surface the minimal inbound MCP runtime settings panel and left-nav jump link only when the OS-only MCP UI feature flag is enabled.

- Optional `application/external_apps/mcp/`.
  - Keep only if a separate deployment model is deliberately chosen. Do not copy PR #722's prototype directly.

### Tests And Documentation

- `functional_tests/test_mcp_action_manifest_workflow.py`
  - Extend baseline MCP coverage.

- New focused functional tests under `functional_tests/`.
  - Suggested names: `test_mcp_custom_headers.py`, `test_mcp_splunk_profile.py`, `test_mcp_discovery_diagnostics.py`, `test_mcp_result_policy.py`, `test_mcp_oauth_pkce.py`.

- New inbound MCP functional tests under `functional_tests/`.
  - Suggested names: `test_inbound_mcp_auth_contract.py`, `test_inbound_mcp_access_governance.py`, `test_inbound_mcp_personal_tools.py`, `test_inbound_mcp_prm_metadata.py`, `test_inbound_mcp_personal_chat_guardrails.py`.

- `ui_tests/test_workspace_mcp_action_modal.py`
  - Extend UI coverage for new controls and discovery behavior.

- New admin/governance UI tests if inbound MCP settings are surfaced in the browser.
  - Cover enablement, client allowlists, tool allowlists, scope toggles, redaction, and disabled-by-default behavior.

- `docs/explanation/features/`
  - Add/update feature documentation when implementation begins.

- `docs/explanation/fixes/`
  - Add robustness/fix documentation if this is delivered as a compatibility improvement.

- `docs/explanation/release_notes.md`
  - Update after implementation if approved.

- `application/single_app/config.py`
  - Increment the third version segment after code changes.

## Verification Plan

### Outbound MCP Plugin Verification

1. Run the existing baseline MCP functional test:

   ```bash
   pytest functional_tests/test_mcp_action_manifest_workflow.py -v
   ```

2. Add and run focused functional tests for:
   - Custom headers.
   - Bearer/Splunk profile.
   - Destination allowlist exact/wildcard matches.
   - Destination policy by personal, group, and global/admin action scope.
   - Specific group destination denied while other groups remain unaffected.
   - Destination policy enforced on action save, discovery/probe, and runtime invocation.
   - Redirect/private-IP policy cannot bypass allowlisting.
   - Preconfigured catalog loading, validation, scope filtering, and manifest population.
   - Discovery hydration.
   - Header redaction.
   - Invalid header rejection.
   - Timeout classification.
   - Result policy.
   - Schema validation.

3. Add mocked OAuth tests before any live OAuth testing:
   - PKCE generation.
   - State validation.
   - Callback validation.
   - Token exchange.
   - Refresh flow.
   - Scope pinning.
   - Key Vault/reference storage.
   - Redaction.

4. Extend UI tests for:
   - MCP preset selection.
   - MCP preconfiguration catalog selection.
   - Admin MCP destination governance policy editing.
   - Per-scope personal/group/global policy isolation.
   - Destination policy warning and denial states.
   - Custom header entry.
   - OAuth connect state.
   - TLS warnings.
   - Discovery diagnostics.
   - Preserving backward-compatible manifests.

5. Run a live/manual Splunk smoke test when endpoint and token are available:
   - Discover tools.
   - Invoke `splunk_get_info` or `splunk_get_indexes`.
   - Test auth failure with an invalid token.
   - Test a bounded `splunk_run_query` within Splunk guardrails.

6. If route files change, run route policy tests under `functional_tests/route_tests/`.

7. Verify secrets never appear in logs, JSON responses, rendered HTML, browser-visible config, test artifacts, or documentation examples.

### Inbound SimpleChat MCP Server Verification

1. Add inbound auth contract tests before exposing tools:
   - Missing bearer token.
   - Malformed bearer token.
   - Expired token.
   - Invalid issuer.
   - Invalid audience.
   - Missing required inbound MCP delegated scope, delegated user role, or app-only role.
   - Disallowed caller app ID.
   - App-only token rejected for user-data tools.
   - Delegated token accepted only for the represented user.

2. Add PRM metadata tests:
   - Metadata endpoint returns expected resource shape.
   - Authorization server and supported scopes are derived from safe configuration.
   - Metadata does not expose secrets, internal endpoints, or raw settings.

3. Add governance tests:
   - Inbound MCP disabled globally.
   - Client disabled.
   - Source denied when no matching `inbound_mcp_source` policy allows the delegated user.
   - Personal access denied when no matching `inbound_mcp_access/personal` policy allows the delegated user.
   - Legacy scope/target policies remain temporary compatibility fallback only.
   - Specific group document listing/retrieval disabled while other group operations remain governed independently.
   - Wildcard all-groups policy applies consistently.
   - Group/public/all-scope tools remain disabled by default.
   - Governance denial returns a clear authorization response without leaking policy internals.

4. Add initial personal-tool tests:
   - `list_conversations` returns only the delegated user's conversations.
   - `get_conversation_messages` rejects conversations the user cannot access.
   - `list_personal_documents` returns only personal documents for the delegated user.
   - `list_personal_prompts` returns only personal prompts for the delegated user.
   - `list_personal_tags` returns only personal tags for the delegated user.
   - `search_personal_documents` enforces personal scope and result limits.
   - `execute_workflow` rejects workflows the delegated user does not own, rejects missing governance, uses a distributed run lock, and records the caller/source in audit-safe run metadata.

5. Add personal-chat write tests before enabling `send_personal_chat_message`:
   - New conversation creation.
   - Existing conversation ownership validation.
   - Rejection for inaccessible conversations.
   - Rate-limit behavior.
   - Bounded response behavior.
   - Audit logging without message-secret leakage.

6. Add deferred group/public negative tests:
   - Group and public tools are unavailable until explicitly enabled.
   - Users without workspace roles cannot access group/public data after those tools are enabled.
   - Inactive or disabled workspaces remain blocked.

7. Add scale and reliability tests:
   - Stateless behavior across process restart.
   - Multi-instance-safe auth behavior.
   - Timeout handling.
   - Health/readiness endpoint behavior.
   - No in-memory cache dependency for authorization correctness.

## Implementation Order

1. Track A Phase 1 custom headers, Splunk preset, validation, redaction, diagnostics, and tests. **Status: implemented with the declarative MCP preset catalog extension.**
2. Track B Phase B0 architecture decision and Track B Phase B1 auth foundation design. **Status: recorded; disabled inbound MCP shell implemented.**
3. Track A Phase 1B outbound destination governance and preconfigured MCP server catalog. **Status: implemented as config/env-backed server enforcement in v0.250.064.**
4. Track A Phase 1C destination governance UI and policy persistence. **Status: implemented in v0.250.065 using delegated item policies; remaining catalog-admin refinements can follow later.**
5. Track A Phase 1D authenticated enterprise preconfiguration templates for Microsoft Sentinel MCP and Azure MCP Server. **Status: implemented in v0.250.066 as disabled-by-default, explicit-policy-gated templates; OAuth/token refresh remains future work.**
6. Track A Phase 2 capability probe, richer metadata, result policies, and opt-in schema validation. **Status: implemented in v0.250.068.**
7. Track B Phase B2 governance/tool registry and Track B Phase B3 initial personal read plus workflow-execution tools. **Status: first governed read tool implemented in v0.250.070; app-settings-backed runtime config and minimal OS-gated Admin Settings UI implemented in v0.250.071; Easy Auth exclusion verification before enablement implemented in v0.250.072; generated setup script now derives cloud/deployment hints and backs up authsettings in v0.250.073; copy button and GET-based authsettings read fix implemented in v0.250.074; delegated scope default and setup-script preflight implemented in v0.250.075; OAuth PRM challenge implemented in v0.250.076; inbound MCP governance policy UI implemented in v0.250.077; delegated user role and future app-only role split implemented in v0.250.078; per-policy help modals implemented in v0.250.079; current inbound MCP governance simplified to personal access plus source in v0.250.080.**
8. Track B Phase B4 personal chat write tool only after read-only tools, auth, and governance are stable.
9. Track A Phase 3 TLS diagnostics and optional certificate references after connector support is confirmed.
10. Track A Phase 4 OAuth 2.1 PKCE.
11. Track B Phase B5 group/public/all-scope tools only after explicit governance and workspace-role tests.
12. Track A Phase 5 prompts/resources/streaming/long-running jobs and Track B Phase B6 enterprise readiness hardening.

## Risk Notes

- OAuth token storage and refresh is the highest-risk area because it spans auth, Key Vault, workspace identity scope, callbacks, UI state, and redaction.
- Custom headers need strict validation to avoid header injection and credential leakage.
- Outbound MCP destination filtering is a data-exfiltration and SSRF control. It must be enforced on the server during save, discovery/probe, and runtime invocation rather than only in the browser.
- Preconfigured outbound MCP servers improve usability but can encourage broad external data flow if destination policy, scope eligibility, tool allowlists, and admin enablement are not enforced.
- Microsoft Sentinel MCP can expose sensitive security operations data; it must be treated as an authenticated, high-risk enterprise connector with admin approval, least-privilege roles, source/destination allowlists, and audited tool invocation.
- Azure MCP Server can inspect or change Azure resources; SimpleChat should not execute local package-run MCP commands from user input, and any Azure MCP template should default to organization-hosted remote endpoints, read-only mode, explicit service namespaces, and conservative tool allowlists.
- Result storage can create cleanup and retention obligations if large outputs are persisted.
- Schema validation can break existing dynamic tools if enabled by default; keep it opt-in initially.
- TLS controls should not be exposed until the connector stack can honor them securely.
- Relaxing shared external auth decorators would broaden access for existing external APIs; inbound MCP should use a dedicated guard.
- App-only tokens are dangerous for user-data tools unless they are explicitly constrained to admin-only operations.
- Bearer-to-session bridges can become confused-deputy paths if caller app ID, audience, delegated scope, delegated user role, delegated user, expiry, and audit controls are not enforced.
- Inbound group/public/all-scope tools can bypass workspace protections if they do not reuse existing role and workspace-status checks.
- Inbound MCP tool schemas and metadata can leak internal URLs, settings, or implementation details if not reviewed and redacted.

## Recommended First Slice

Track A Phase 1 has been implemented:

- Splunk profile/preset.
- Safe custom headers.
- Better validation and error classification.
- Better redaction.
- Focused functional and UI tests.
- Documentation update.

This first slice improves Splunk GA token mode and most token-based MCP servers without touching the highest-conflict shared OAuth/storage surfaces.

The first inbound planning/architecture slice and disabled shell are also complete:

- Track B Phase B0 architecture decision.
- Track B Phase B1 auth foundation design.
- Dedicated inbound MCP auth guard design.
- PRM metadata contract.
- Governance model for personal access and source allowlists, with client trust kept in inbound MCP runtime configuration.
- Initial personal read and workflow-execution tool registry.
- Auth and governance test plan.
- Disabled `/api/mcp` route shell.
- Dedicated inbound MCP auth guard.
- PRM metadata route.
- Health/readiness route.
- Deny-by-default governance and no-enabled-tools registry skeleton.
- Easy Auth exclusion modal and server-side verification guard before inbound MCP can be enabled from Admin Settings.

Current forward options:

1. Continue Track B with the next low-risk personal read tool after `list_personal_tags`, reusing the app-settings-backed runtime config, simplified personal-access/source governance, minimal admin UI, and verified Easy Auth exclusion guard.
2. Add outbound MCP catalog-administration refinements: per-definition enable/disable controls, policy summaries, and optional environment/config import review.
3. Start outbound OAuth/token lifecycle planning for authenticated MCP servers such as GitHub, Microsoft Sentinel MCP, and Azure MCP Server.
4. Continue Track A Phase 3: TLS diagnostics and enterprise network guidance once connector support is confirmed.

The first inbound executable slice should start with governed personal tools after token validation, client allowlisting, governance checks, observability, redaction, and tests are in place. Read tools should come first; `execute_workflow` should be enabled only after workflow ownership, execution governance, run locking, and audit tests are ready.
