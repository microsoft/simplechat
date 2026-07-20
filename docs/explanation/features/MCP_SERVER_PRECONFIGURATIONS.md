# MCP Server Preconfigurations

Implemented in version: **0.250.064**

Destination governance UI and delegated policy persistence implemented in version: **0.250.065**

Enterprise preconfiguration tiering implemented in version: **0.250.066**

Implementation-specific preconfiguration schema validation added in version: **0.250.067**

Capability-probe defaults for argument validation and result policy added in version: **0.250.068**

## Overview

MCP server preconfigurations are concrete, server-side action templates for known outbound MCP servers. They are different from MCP server presets:

* **Preset**: compatibility defaults for a class of MCP server behavior, with no concrete destination.
* **Preconfiguration**: a curated MCP action template with a specific endpoint, transport, auth requirement, default tool allowlist, documentation link, scope eligibility, and warnings.

The catalog lets organizations ship a drop-down of ready-to-create MCP actions such as Microsoft Learn, Azure documentation, GitHub, Microsoft Sentinel, Azure MCP Server, or a local development MCP fixture while keeping the definitions validated and controlled by the server.

Enterprise templates such as Microsoft Sentinel MCP and Azure MCP Server are stored in the same catalog, but they are hidden by default. They only appear when destination governance is enabled and an admin explicitly allows the matching `preconfiguration:<id>` item policy for the intended scope.

## Dependencies

* `jsonschema`
* Existing MCP action manifest normalization in `functions_mcp_operations.py`
* Existing MCP preset catalog in `functions_mcp_presets.py`
* Optional destination governance from `functions_mcp_destinations.py`

## Technical Specifications

### File Structure

```text
application/single_app/
  functions_mcp_destinations.py
  functions_mcp_catalog_implementations.py
  functions_mcp_preconfigurations.py
  mcp_preconfigurations/
    mcp_server_preconfiguration.schema.json
    implementation_schemas/
      azure_mcp_server.preconfiguration.schema.json
      github.preconfiguration.schema.json
      microsoft_learn.preconfiguration.schema.json
      microsoft_sentinel.preconfiguration.schema.json
      simplechat_local_dev.preconfiguration.schema.json
    definitions/
      azure_documentation.json
      azure_mcp_server.json
      github.json
      local_dev.json
      microsoft_learn.json
      microsoft_sentinel.json
```

### API

```http
GET /api/plugins/mcp/preconfigurations?scope=personal
```

The response is authenticated, scope-filtered, and destination-governance-filtered when MCP destination governance is enabled:

```json
{
  "defaultPreconfiguration": "",
  "scope": "personal",
  "preconfigurations": [
    {
      "id": "microsoft_learn",
      "displayName": "Microsoft Learn Documentation",
      "endpoint": "https://learn.microsoft.com/api/mcp",
      "transport": "streamable_http",
      "presetId": "generic",
      "authRequirement": "none",
      "defaults": {
        "auth_method": "none",
        "load_tools": true,
        "load_prompts": false,
        "request_timeout": 30,
        "connect_timeout": 10,
        "sse_read_timeout": 300,
        "retry_count": 0,
        "retry_backoff_seconds": 1,
        "validate_tool_arguments": false,
        "tool_result_policy": "truncate",
        "allowed_tool_names": []
      },
      "catalogTier": "public",
      "authTier": "public_unauthenticated",
      "deploymentModel": "hosted_remote",
      "implementation": {
        "id": "microsoft_learn",
        "schemaVersion": "1.0.0"
      },
      "additionalSettings": {
        "contentFocus": "all_microsoft",
        "publicDocumentationOnly": true,
        "preferredTools": ["microsoft_docs_search"]
      },
      "requiredGovernanceGates": []
    }
  ]
}
```

### Configuration

```text
SIMPLECHAT_MCP_PRECONFIGURATION_PATHS=
ENABLE_LOCAL_MCP_PRECONFIGURATION=false
ENABLE_MCP_DESTINATION_GOVERNANCE=false
MCP_ALLOWED_DESTINATIONS=
MCP_ALLOWED_PERSONAL_DESTINATIONS=
MCP_ALLOWED_GROUP_DESTINATIONS=
MCP_ALLOWED_GLOBAL_DESTINATIONS=
MCP_BLOCK_UNSAFE_DESTINATIONS=false
```

`SIMPLECHAT_MCP_PRECONFIGURATION_PATHS` uses the OS path separator and can point to one or more directories containing organization-authored JSON definitions.

`ENABLE_LOCAL_MCP_PRECONFIGURATION=true` exposes the bundled local development server entry. It is hidden by default.

Destination governance is compatibility-off by default. When enabled, configured allowlists are enforced server-side during MCP action save/update, tool discovery, and runtime connector creation.

Enterprise preconfigurations are additionally hidden unless the matched policy is an explicit `preconfiguration:<id>` rule. Endpoint-reviewed enterprise templates also require a separate specific destination rule for the governed endpoint. Broad rules such as `*`, host wildcards, presets, or transport allowlists are not sufficient to surface enterprise templates.

Admins can persist destination allowlists through **Admin Settings > Governance > MCP Action Destination Governance**. These controls reuse delegated item policies:

| Scope | Entity Type | Item ID / Pattern |
| --- | --- | --- |
| Personal MCP actions | `mcp_personal_destination` | `preconfiguration:microsoft_learn`, `*.contoso.com`, URL prefix, transport, or `*` |
| Group MCP actions | `mcp_group_destination` | Same pattern format for all groups, or `group:<group-id>::<pattern>` for one group |
| Global/admin MCP actions | `mcp_global_destination` | Same pattern format for global/admin-managed actions |

Each delegated item policy can allow all users or restrict the destination to specific users and workspace groups using the existing item-delegation allowlist editor.

### Destination Allowlist Pattern Examples

```text
*
learn.microsoft.com
*.githubcopilot.com
https://learn.microsoft.com/api/*
preset:generic
preconfiguration:microsoft_learn
preconfiguration:microsoft_sentinel
preconfiguration:azure_mcp_server
transport:streamable_http
```

When `MCP_BLOCK_UNSAFE_DESTINATIONS=true`, literal loopback, link-local, metadata-service, private, multicast, reserved, and unspecified IP destinations are rejected before allowlist matching.

## Creating a Preconfiguration Definition

1. Copy an existing JSON definition from `application/single_app/mcp_preconfigurations/definitions/`.
2. Save the new file as `{id}.json`; the filename must match the `id`.
3. Validate the definition against `mcp_server_preconfiguration.schema.json`.
4. Do not include secrets, tokens, passwords, connection strings, or concrete credentials.
5. Set `scopeEligibility` to the supported action scopes: `personal`, `group`, and/or `global`.
6. If provider-specific metadata is needed, add:
   * `implementation` with normalized `id` and `schemaVersion`.
   * `additionalSettings` validated by `implementation_schemas\{id}.preconfiguration.schema.json`.
7. For enterprise templates, set:
   * `catalogTier` to `enterprise`.
   * `authTier` to the expected identity/credential model.
   * `deploymentModel` to `organization_hosted_remote` when SimpleChat should connect only to an organization-owned remote endpoint.
   * `disabledByDefault` and `requiresAdminEnablement` to `true`.
   * `requiredGovernanceGates` to include at least destination allowlisting, explicit preconfiguration policy, per-tool allowlisting, audit logging, and identity review.
   * `requiresEndpointReview` to `true` when the example endpoint must be replaced by an approved organization endpoint.
   * `defaults.load_tools` to `false` unless the tool allowlist is already narrow and reviewed.
8. Restart the app or clear catalog caches when adding definitions to a running process.

## User Workflow

1. Open the action modal.
2. Select **Model Context Protocol server**.
3. Choose a value in **Preconfigured MCP Server**.
4. Review the populated endpoint, transport, auth method, timeout, tool allowlist, argument-validation preference, and result policy values.
5. Provide credentials only when the selected server requires authentication.
6. Optionally discover tools, then save the action.

## Enterprise Template Behavior

Bundled enterprise templates are intentionally safe by default:

| Template | ID | Default Visibility | Default Auth | Default Tool Loading | Required Admin Action |
| --- | --- | --- | --- | --- | --- |
| Microsoft Sentinel MCP Server | `microsoft_sentinel` | Hidden | Reusable identity | Disabled | Enable destination governance, add `preconfiguration:microsoft_sentinel`, and add a specific approved Sentinel MCP endpoint rule for the approved scope. |
| Azure MCP Server | `azure_mcp_server` | Hidden | Reusable identity | Disabled | Enable destination governance, add `preconfiguration:azure_mcp_server`, and add a specific approved Azure MCP endpoint rule for the approved scope. |

Both templates use example organization-hosted endpoints and require endpoint review before use. SimpleChat should not run local package commands such as `npx`, `dnx`, `uvx`, or Docker from user-provided Azure MCP configuration. Operators should replace the example endpoint with a governed remote endpoint that they own, then enable only narrow read-oriented tools until identity, source allowlisting, destination allowlisting, per-tool policy, and audit controls are validated.

## Testing and Validation

Coverage added in version **0.250.064**:

* `functional_tests/test_mcp_destination_governance_and_preconfigurations.py`
* `ui_tests/test_workspace_mcp_action_modal.py`

The tests validate catalog loading, custom definition loading, scope filtering, secret-free defaults, destination allowlist decisions, unsafe literal-IP blocking, and modal payload generation.

Expanded coverage in version **0.250.065** validates governance-backed destination patterns, per-group destination overrides, preconfiguration filtering through destination governance, and the admin MCP destination governance UI.

Expanded coverage in version **0.250.066** validates enterprise template metadata, hidden-by-default behavior, explicit `preconfiguration:<id>` policy requirements, and warning text displayed in the MCP action modal.

Expanded coverage in version **0.250.067** validates implementation-specific preconfiguration schemas, provider-specific `additionalSettings`, identity-backed enterprise defaults, direct-submit enterprise policy enforcement, and the endpoint-specific policy required for endpoint-reviewed enterprise templates.

Expanded coverage in version **0.250.068** validates preconfiguration-compatible defaults for opt-in MCP argument validation and large-result policy behavior.

## Known Limitations

* Per-definition enable/disable controls for bundled and organization-provided preconfigurations remain a future catalog-administration refinement. Current admins can allow or block preconfiguration use with `preconfiguration:<id>` destination policies.
* Hostname DNS resolution is not used as a trust boundary; strict environments should combine allowlists with network egress controls.
* Preconfigurations never include credential values. Credentials must come from user input or reusable workspace identities.
* OAuth/token refresh for identity-backed enterprise MCP servers is not implemented yet. Enterprise templates are metadata and governance-gated starting points, not a complete token lifecycle solution.
