---
layout: page
title: "MCP"
description: "Full guide for the MCP SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: mcp -->

{% include media.html src="reference/actions-mcp-configuration.png" alt="The MCP Server configuration pane showing the preconfigured server template selector, server preset, transport and endpoint fields, the authentication method, and a custom headers JSON box noting header values are treated as secrets." title="MCP action configuration" capture="Capture MCP Server, Authentication, Tool Exposure, Timeouts and Retries, Discover Tools, and Test Connection. Redact secrets." %}

## What this action does

MCP connects SimpleChat to a remote Model Context Protocol server and exposes selected server tools to agents. Supported transports are streamable HTTP, server-sent events (SSE), and WebSocket. The action can discover tool metadata and call configured tools by name.

As of **0.261.029**, stdio and local process command, argument, and environment configuration are removed for every role and scope, including Admin and global actions.

## Why and when to use it

Use MCP when a provider already exposes an MCP server and agents should use those tools through a standard protocol. Do not use MCP for a single REST API with a stable OpenAPI spec; OpenAPI is simpler. Do not expose every discovered tool by default if the server has broad or sensitive capabilities.

## Before you start

- A remote MCP server endpoint reachable from the SimpleChat environment and permitted by destination policy.
- Transport choice: **Streamable HTTP**, **Server-Sent Events**, or **WebSocket**.
- Auth details when required: bearer token, API key header, basic auth, reusable identity, or custom headers.
- Tool exposure policy: load tools, optional prompts, allowed tool names, and large-result handling.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents-actions/' | relative_url }}).

## Configure the action

1. Choose **MCP**.
2. Optionally select **Preconfigured MCP Server** and **Server Preset**.
3. Choose **Transport** and fill **Endpoint** with the remote server URL.
4. Choose **Authentication Method** and fill the shown auth fields or **Custom Headers (JSON)**.
5. Set **Load tools**, **Load prompts**, **Validate tool arguments**, and **Large Result Policy**.
6. Fill **Allowed Tool Names** to expose only approved tools, or leave blank to expose all discovered tools.
7. Use **Discover Tools** to populate **Discovered Tool Metadata (JSON)**.
8. Set **Request Timeout**, **Connect Timeout**, **SSE Read Timeout**, **Retry Count**, and **Retry Backoff**, then use **Test Connection**.

## Retired stdio actions

Existing stdio actions remain visible with an unsupported status, but they cannot discover tools, test a connection, or execute. Opening or cancelling an edit does not change them. SimpleChat neither selects HTTP for them automatically nor deletes them during migration.

To keep an action, explicitly select a supported remote transport and supply a valid endpoint for an approved, separately operated MCP server. Review authentication, headers, timeouts, and tool exposure, then test and save the remote configuration under current governance. SimpleChat does not start a local server command as a replacement. The HTTP-based local development server is unchanged.

If an action is no longer needed, explicitly delete it. Omitting a retired action from a bulk save does not delete it, and migration retains unsupported or failed records. Owners can inspect and delete their retired actions even when MCP-usage governance prevents execution; personal ownership, group-management permissions, and Admin requirements still apply. Reconfiguration must pass normal governance.

## Authorization and destination policy

Save, discovery, connection testing, and runtime use share the same MCP authorization rules. The server determines an action's scope from its authorized storage location and evaluates the current user or established workflow identity against current settings, including when a tool was previously cached.

Environment-enforced destination restrictions are a minimum that Admin Settings cannot relax. Settings may tighten those restrictions. A previously successful connection test does not grant ongoing access after policy or caller permissions change.

## Example prompts

- "Use the GitHub MCP tool to summarize open issues labeled customer-impact."
- "Call the approved search tool from this MCP server and compare the top results."
- "List the tools exposed by this MCP action before deciding which one to call."

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Discovery finds too many tools | **Allowed Tool Names** is blank. | Add one approved tool name per line. |
| Tool calls fail on arguments | Arguments do not match the discovered schema. | Enable **Validate tool arguments** and rediscover tools. |
| SSE connections time out | Read timeout is too low or a proxy interrupts the stream. | Increase **SSE Read Timeout** and verify the network path. |
| An existing action is marked unsupported | It uses the retired stdio transport. | Explicitly configure a supported remote transport and endpoint, or delete the action. Admin/global scope does not restore stdio support. |
| A remote action is denied after previously working | Current caller permissions or destination policy no longer allow it. | Review both deployment environment restrictions and current Admin Settings; settings cannot override an environment restriction. |

## Related

- [OpenAPI](../openapi/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspaces/' | relative_url }})
- [MCP destination governance]({{ '/admin/governance/' | relative_url }}#mcp-governance)
