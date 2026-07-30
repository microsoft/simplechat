# MCP Server Preconfigurations

Last updated for SimpleChat version: **0.250.067**

## Purpose

MCP server preconfigurations define curated, concrete MCP server templates that users can choose from when creating an MCP action. A preconfiguration may include a real or placeholder endpoint, provider name, risk metadata, scope eligibility, default tool exposure, documentation links, and governance requirements.

Use a preconfiguration when SimpleChat should offer a known MCP server as a ready-to-review starting point instead of asking users to build the action from a blank custom configuration.

## Presets vs. Preconfigurations

| Catalog type | Question it answers | Contains endpoint? | Contains concrete provider/server? | Stored on action as |
| --- | --- | --- | --- | --- |
| Preset | "How should SimpleChat talk to this kind of MCP server?" | No | No | `additionalFields.server_profile` |
| Preconfiguration | "Which known MCP server should this action start from?" | Yes | Yes | `additionalFields.preconfiguration_id` plus copied action fields |

Examples:

* `microsoft_learn`: public Microsoft Learn MCP endpoint.
* `github`: hosted GitHub MCP server template.
* `microsoft_sentinel`: hidden enterprise template for an organization-hosted Microsoft Sentinel MCP endpoint.
* `azure_mcp_server`: hidden enterprise template for an organization-hosted Azure MCP Server endpoint.

## What Belongs Here

Preconfiguration definitions may include:

* Concrete or reviewed placeholder MCP endpoint.
* Transport.
* Referenced `presetId`.
* Provider/category/display metadata.
* Auth requirement and auth tier.
* Deployment model.
* Default MCP action field values.
* Scope eligibility: personal, group, global.
* Destination tags.
* Risk label.
* Documentation URL.
* UI help text, operator notes, and warnings.
* Enterprise governance gates such as explicit destination allowlisting, source allowlisting, per-tool allowlisting, read-only mode, audit logging, and identity review.
* Provider-specific, non-secret `additionalSettings` validated by implementation-specific schemas.

## What Does Not Belong Here

Do not put these values in preconfigurations:

* Secrets, tokens, passwords, keys, or connection strings.
* Tenant-specific credentials.
* User-specific authorization choices.
* Runtime token refresh state.
* Browser-only behavior that bypasses server-side validation.
* Generic compatibility defaults that should be reusable across unrelated MCP servers. Those belong in presets.

## Enterprise Template Rules

Enterprise templates are allowed in this catalog, but they must stay safe by default:

1. Set `catalogTier` to `enterprise`.
2. Set `disabledByDefault` and `requiresAdminEnablement` to `true`.
3. Use `authRequirement` of `identity` or `required`; never `none`.
4. Use a non-public `authTier`.
5. Set `defaults.load_tools` to `false` unless the default tool allowlist is already narrow and reviewed.
6. Include required governance gates for destination allowlisting, explicit preconfiguration policy, per-tool allowlisting, audit logging, and identity review.
7. Use operator warnings for high-risk data, broad cloud access, or mutating tools.

Enterprise templates are hidden from the action modal unless MCP destination governance is enabled, an explicit `preconfiguration:<id>` policy allows the requested scope, and endpoint-reviewed templates also have a specific destination policy for their governed endpoint. Broad rules such as `*`, host wildcards, transport allowlists, or preset rules are not enough to surface enterprise templates.

## Authoring Rules

1. Copy an existing JSON file from `definitions\`.
2. Save the file as `{id}.json`; the file name must match the `id`.
3. Validate against `mcp_server_preconfiguration.schema.json`.
4. Reference an existing preset with `presetId`.
5. Keep default tool exposure narrow.
6. Never include credentials or secret-bearing fields.
7. Add `implementation` and `additionalSettings` when a provider needs custom non-secret metadata.
8. Prefer organization-hosted remote endpoints for high-risk enterprise servers.

## Provider-Specific Settings

The base preconfiguration schema remains provider-neutral. If a provider needs custom settings, add those settings through an implementation-specific preconfiguration schema rather than expanding the base schema with provider-only fields.

Implemented pattern:

```text
mcp_preconfigurations\
  mcp_server_preconfiguration.schema.json
  implementation_schemas\
    microsoft_sentinel.preconfiguration.schema.json
    azure_mcp_server.preconfiguration.schema.json
  definitions\
    microsoft_sentinel.json
    azure_mcp_server.json
```

The base schema should validate common catalog, endpoint, auth, risk, and governance metadata. The implementation schema should validate provider-specific `additionalSettings`, such as Sentinel tool collections or Azure MCP service namespace allowlists.
