# MCP Plugin Robustness Plan

Planning version: **0.250.062**

Implemented in version: **In progress across phases**

Related configuration version: `application/single_app/config.py` currently sets `VERSION = "0.250.062"`.

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
- Add a way for MCP clients to inspect login/auth status and user profile, subject to redaction and claims minimization.

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
- Use a combined access model where Entra roles/scopes provide coarse access, SimpleChat governance provides tool/scope policy, and existing workspace roles protect data.

## Non-Goals For The First Slice

- Do not implement OAuth 2.1 PKCE in the same slice as basic Splunk/token hardening.
- Do not add per-action TLS or client certificate settings until connector support is confirmed.
- Do not add long-running job persistence until a concrete MCP server workflow requires it.
- Do not expose prompts or resources as first-class action behavior until the user experience is designed.
- Do not break existing MCP actions or require existing manifests to be migrated.
- Do not deliver inbound MCP full feature parity with the SimpleChat web UI or internal SimpleChat plugin in the first inbound slice.
- Do not enable group, public, or all-scope inbound MCP tools until workspace role checks and governance policy are explicitly wired and tested.
- Do not use PR #722's external app as-is as the production MCP server.

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

### Phase 2: Capability Probe And Tool Metadata Robustness

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

Status: **Architecture decision recorded in version 0.250.062.** See [Inbound SimpleChat MCP Server Architecture](./INBOUND_MCP_SERVER_ARCHITECTURE.md).

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

Status: **Auth foundation and PRM contract recorded in version 0.250.062.** See [Inbound SimpleChat MCP Server Architecture](./INBOUND_MCP_SERVER_ARCHITECTURE.md).

1. Add a dedicated inbound MCP auth guard.
   - Do not weaken or broaden the shared `accesstoken_required` decorator used by existing external routes.
   - Require valid token issuer, tenant, expiration, and audience for SimpleChat.
   - Support the required Entra token version intentionally rather than by accident.
   - Require a dedicated inbound MCP app role or scope such as `McpServerAccess` or a deliberately reused `ExternalApi`.
   - Add an allowed client application ID list similar to the existing CI bearer-session allowlist pattern.

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

Use a combined model rather than choosing only governance or only roles:

- **Entra roles/scopes** provide the coarse gate: the caller can reach the inbound MCP surface.
- **Client app allowlists** provide client trust: the calling application is approved.
- **SimpleChat governance** provides fine-grained policy: which tools and workspace scopes are enabled.
- **Existing workspace roles** protect data: the delegated user must already be allowed to access the requested personal, group, or public resource.

1. Add inbound MCP governance settings.
   - Global enablement flag for inbound MCP.
   - Per-client enablement.
   - Per-tool allowlist.
   - Per-scope allowlist: personal, group, public.
   - Optional per-client or per-user rate limits.

2. Keep the initial tool registry explicit.
   - Each MCP tool should declare required identity type, workspace scope, feature flags, governance keys, rate-limit category, and audit event type.
   - Do not expose a tool simply because a Python function exists.

3. Reuse existing authorization helpers.
   - Personal tools must validate current-user ownership.
   - Group tools must use the same group role checks used by web/API routes.
   - Public workspace tools must use the same public workspace role and workspace-status checks used by existing external/public routes.
   - Governance must deny by default when a client/tool/scope is not configured.

### Phase B3: Initial Read-Only Personal Tool Set

Start with a small, personal-scope read set inspired by PR #722, not full feature parity:

1. `show_user_profile`
   - Return minimal profile fields needed by MCP clients.
   - Do not return raw token claims by default.

2. `list_conversations`
   - Return only conversations visible to the delegated user.
   - Include pagination and maximum result limits.

3. `get_conversation_messages`
   - Require conversation ownership or collaboration access.
   - Include pagination and maximum message limits.

4. `list_personal_documents`
   - Return only the delegated user's personal documents.
   - Include pagination, filtering, and result limits.

5. `list_personal_prompts`
   - Return only the delegated user's personal prompts.
   - Include pagination and result limits.

6. `search_personal_documents`
   - Restrict to personal document scope.
   - Require bounded `top_n`.
   - Preserve existing search and embedding error behavior.

7. `list_agent_template_tags`
   - Return only approved template tags.
   - Respect the agent template gallery feature flag.

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
  - Normalize and validate custom headers, OAuth config, retry settings, result policy, capability metadata, TLS references, and schema-validation flags.

- `application/single_app/semantic_kernel_plugins/mcp_plugin_factory.py`
  - Merge headers, resolve auth/OAuth tokens, create connectors, run discovery/probes, serialize results, classify errors, and optionally validate arguments.

- `application/single_app/semantic_kernel_plugins/mcp_plugin.py`
  - Expose discovered tool metadata, enforce allowlists, route tool calls through validation/result policy, and later expose resources/prompts if supported.

- `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`
  - Validate expanded MCP manifest fields, auth-method requirements, header safety, TLS references, OAuth requirements, and timeout/retry limits.

### Routes, UI, And Schemas

- `application/single_app/route_backend_plugins.py`
  - Extend discovery/test routes, hydrate secrets/identities, add compatibility probe route, and later add OAuth connect/callback/disconnect routes.

- `application/single_app/static/js/plugin_modal_stepper.js`
  - Update MCP modal behavior for custom headers, Splunk preset, diagnostics, OAuth status, TLS settings, result policy, and richer discovery warnings.

- `application/single_app/templates/_plugin_modal.html`
  - Add controls for new MCP settings without external browser assets.

- `application/single_app/static/json/schemas/mcp_plugin.additional_settings.schema.json`
  - Add expanded MCP settings and backward-compatible defaults.

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
  - Validate inbound MCP bearer tokens, issuer, audience, client app ID, role/scope, delegated user identity, and app-only restrictions.

- New `application/single_app/functions_mcp_server_governance.py` or equivalent.
  - Resolve inbound MCP client/tool/scope policy and compose Entra roles/scopes, app allowlists, SimpleChat governance, and workspace-role checks.

- New `application/single_app/functions_mcp_server_tools.py` or equivalent.
  - Implement the explicit inbound SimpleChat MCP tool registry and call reusable SimpleChat service functions with authorization-aware context.

- New `application/single_app/route_mcp_server.py` or equivalent.
  - Host streamable HTTP MCP endpoints, PRM metadata, health/readiness behavior, and inbound MCP request handling.

- `application/single_app/app.py`
  - Register inbound MCP routes or blueprint only after the architecture and feature flag are defined.

- `application/single_app/functions_simplechat_operations.py`
  - Reuse or extract operation helpers for personal conversations, personal documents, prompts, search, and later personal chat writes.

- `application/single_app/functions_governance.py`
  - Add inbound MCP feature, client, tool, and scope governance helpers if existing action-governance primitives are not sufficient.

- `application/single_app/functions_settings.py`
  - Add sanitized settings support for inbound MCP governance and configuration if the admin UI needs to display these settings.

- Optional `application/external_apps/mcp/`.
  - Keep only if a separate deployment model is deliberately chosen. Do not copy PR #722's prototype directly.

### Tests And Documentation

- `functional_tests/test_mcp_action_manifest_workflow.py`
  - Extend baseline MCP coverage.

- New focused functional tests under `functional_tests/`.
  - Suggested names: `test_mcp_custom_headers.py`, `test_mcp_splunk_profile.py`, `test_mcp_discovery_diagnostics.py`, `test_mcp_result_policy.py`, `test_mcp_oauth_pkce.py`.

- New inbound MCP functional tests under `functional_tests/`.
  - Suggested names: `test_inbound_mcp_auth_contract.py`, `test_inbound_mcp_tool_governance.py`, `test_inbound_mcp_personal_tools.py`, `test_inbound_mcp_prm_metadata.py`, `test_inbound_mcp_personal_chat_guardrails.py`.

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
   - Missing required inbound MCP app role/scope.
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
   - Tool disabled.
   - Personal scope disabled.
   - Group/public/all-scope tools remain disabled by default.
   - Governance denial returns a clear authorization response without leaking policy internals.

4. Add initial personal-tool tests:
   - `show_user_profile` returns minimized profile data.
   - `list_conversations` returns only the delegated user's conversations.
   - `get_conversation_messages` rejects conversations the user cannot access.
   - `list_personal_documents` returns only personal documents for the delegated user.
   - `list_personal_prompts` returns only personal prompts for the delegated user.
   - `search_personal_documents` enforces personal scope and result limits.
   - `list_agent_template_tags` respects the agent template gallery feature flag.

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
2. Track B Phase B0 architecture decision and Track B Phase B1 auth foundation design. **Status: recorded; next executable slice is the disabled inbound MCP shell.**
3. Track A Phase 2 capability probe, richer metadata, result policies, and opt-in schema validation. **Status: deferred until after the inbound B0/B1 shell decision gate.**
4. Track B Phase B2 governance/tool registry and Track B Phase B3 initial read-only personal tools.
5. Track B Phase B4 personal chat write tool only after read-only tools, auth, and governance are stable.
6. Track A Phase 3 TLS diagnostics and optional certificate references after connector support is confirmed.
7. Track A Phase 4 OAuth 2.1 PKCE.
8. Track B Phase B5 group/public/all-scope tools only after explicit governance and workspace-role tests.
9. Track A Phase 5 prompts/resources/streaming/long-running jobs and Track B Phase B6 enterprise readiness hardening.

## Risk Notes

- OAuth token storage and refresh is the highest-risk area because it spans auth, Key Vault, workspace identity scope, callbacks, UI state, and redaction.
- Custom headers need strict validation to avoid header injection and credential leakage.
- Result storage can create cleanup and retention obligations if large outputs are persisted.
- Schema validation can break existing dynamic tools if enabled by default; keep it opt-in initially.
- TLS controls should not be exposed until the connector stack can honor them securely.
- Relaxing shared external auth decorators would broaden access for existing external APIs; inbound MCP should use a dedicated guard.
- App-only tokens are dangerous for user-data tools unless they are explicitly constrained to admin-only operations.
- Bearer-to-session bridges can become confused-deputy paths if caller app ID, audience, role/scope, delegated user, expiry, and audit controls are not enforced.
- Inbound group/public/all-scope tools can bypass workspace protections if they do not reuse existing role and workspace-status checks.
- Inbound MCP tool schemas and metadata can leak internal URLs, settings, or implementation details if not reviewed and redacted.

## Recommended First Slice

Implement Track A Phase 1 first:

- Splunk profile/preset.
- Safe custom headers.
- Better validation and error classification.
- Better redaction.
- Focused functional and UI tests.
- Documentation update.

This first slice improves Splunk GA token mode and most token-based MCP servers without touching the highest-conflict shared OAuth/storage surfaces.

Then implement the first inbound planning/architecture slice before any inbound tools are exposed:

- Track B Phase B0 architecture decision.
- Track B Phase B1 auth foundation design.
- Dedicated inbound MCP auth guard design.
- PRM metadata contract.
- Governance model for client, tool, and scope allowlists.
- Initial read-only personal tool registry.
- Auth and governance test plan.

The first inbound executable slice should expose only read-only personal tools after token validation, client allowlisting, governance checks, observability, redaction, and tests are in place.