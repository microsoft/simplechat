# MCP Server Presets

Last updated for SimpleChat version: **0.250.067**

## Purpose

MCP server presets define reusable compatibility settings for a class of MCP servers. A preset does **not** identify a concrete MCP server, endpoint, tenant, workspace, or source of data.

Use a preset when multiple MCP servers share the same transport/auth/default behavior and the action creator still needs to provide the actual destination.

## Presets vs. Preconfigurations

| Catalog type | Question it answers | Contains endpoint? | Contains concrete provider/server? | Stored on action as |
| --- | --- | --- | --- | --- |
| Preset | "How should SimpleChat talk to this kind of MCP server?" | No | No | `additionalFields.server_profile` |
| Preconfiguration | "Which known MCP server should this action start from?" | Yes | Yes | `additionalFields.preconfiguration_id` plus copied action fields |

Examples:

* `generic` preset: default streamable HTTP MCP behavior.
* `splunk` preset: compatibility defaults for Splunk-style MCP behavior.

The user or preconfiguration still supplies the actual endpoint.

## What Belongs Here

Preset definitions may include:

* Default transport: `streamable_http`, `sse`, `websocket`, or `stdio`.
* Default auth method: `none`, `bearer`, `api_key`, `basic`, or `identity`.
* Timeout and retry defaults.
* Prompt/tool loading defaults.
* Default allowed tool names when a server class needs a narrow starter set.
* UI placeholder/help text.
* Allowed transports/auth methods.
* Suggested header names and descriptions.
* Compatibility warnings.

## What Does Not Belong Here

Do not put these values in presets:

* Real MCP server endpoints.
* Concrete provider template names such as "Microsoft Sentinel MCP Server".
* Tenant IDs, workspace IDs, subscription IDs, organization URLs, or source locations.
* Secrets, tokens, passwords, keys, or connection strings.
* Provider-specific operational settings such as Sentinel tool collections or Azure service namespace allowlists.
* Governance policy decisions for specific destinations.

Those belong in MCP preconfigurations or in implementation-specific preconfiguration settings.

## Authoring Rules

1. Copy an existing JSON file from `definitions\`.
2. Save the file as `{id}.json`; the file name must match the `id`.
3. Validate against `mcp_server_preset.schema.json`.
4. Keep defaults generic and reusable.
5. Never include credentials or secret-bearing fields.
6. Use warnings for compatibility caveats, not security policy decisions.

## Implementation-Specific Settings

The base preset schema stays provider-neutral. If a preset needs compatibility metadata that is specific to a server family, add:

* `implementation`: `{ "id": "<implementation-id>", "schemaVersion": "1.0.0" }`
* `additionalSettings`: provider-specific, non-secret settings validated by `implementation_schemas\<implementation-id>.preset.schema.json`

Use this for compatibility traits such as Splunk transport expectations. Do not use it for concrete endpoints, tenant IDs, workspace IDs, subscription IDs, or secrets.

## Relationship To Preconfigurations

Every MCP preconfiguration references a preset with `presetId`. The preconfiguration applies the preset first, then overlays its concrete server details such as endpoint, transport, auth requirement, default tool allowlist, risk label, implementation metadata, and governance metadata.

If a future MCP server needs concrete provider-specific settings, add those settings to the preconfiguration side through implementation-specific schema validation. Do not expand presets to carry concrete provider data.
