---
layout: page
title: "MCP"
description: "Full guide for the MCP SimpleChat action."
section: "Reference"
audience: user
---

<!-- action-slug: mcp -->

{% include media.html src="reference/actions-mcp-configuration.png" alt="MCP action configuration UI." title="MCP configuration" capture="Capture MCP Server, Authentication, Tool Exposure, Timeouts and Retries, Discover Tools, and Test Connection. Redact secrets." %}

## What this action does

MCP connects SimpleChat to a Model Context Protocol server and exposes selected server tools to agents. Supported transports include streamable HTTP, server-sent events, WebSocket, and stdio. The action can discover tool metadata and call configured tools by name.

## Why and when to use it

Use MCP when a provider already exposes an MCP server and agents should use those tools through a standard protocol. Do not use MCP for a single REST API with a stable OpenAPI spec; OpenAPI is simpler. Do not expose every discovered tool by default if the server has broad or sensitive capabilities.

## Before you start

- An MCP server endpoint or stdio command reachable from the SimpleChat environment.
- Transport choice: **Streamable HTTP**, **Server-Sent Events**, **WebSocket**, or **Stdio**.
- Auth details when required: bearer token, API key header, basic auth, reusable identity, or custom headers.
- Tool exposure policy: load tools, optional prompts, allowed tool names, and large-result handling.
- Agents/actions enabled with [`enable_semantic_kernel`]({{ '/admin/agents/' | relative_url }}).

## Configure the action

1. Choose **MCP**.
2. Optionally select **Preconfigured MCP Server** and **Server Preset**.
3. Choose **Transport** and fill **Endpoint**. For stdio, fill **Command**, **Arguments**, and **Environment (JSON)**.
4. Choose **Authentication Method** and fill the shown auth fields or **Custom Headers (JSON)**.
5. Set **Load tools**, **Load prompts**, **Validate tool arguments**, and **Large Result Policy**.
6. Fill **Allowed Tool Names** to expose only approved tools, or leave blank to expose all discovered tools.
7. Use **Discover Tools** to populate **Discovered Tool Metadata (JSON)**.
8. Set **Request Timeout**, **Connect Timeout**, **SSE Read Timeout**, **Retry Count**, and **Retry Backoff**, then use **Test Connection**.

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

## Related

- [OpenAPI](../openapi/)
- [Actions reference index]({{ '/reference/actions/' | relative_url }})
- [Workspace identities]({{ '/admin/workspace-identities/' | relative_url }})

