---
layout: latest-release-feature
title: "Model Context Protocol Connections"
description: "SimpleChat can now act as a governed MCP server for approved external clients, and outbound MCP actions gained presets, preconfigured catalogs, and a Test Connection button."
section: "Latest Release"
---

Current release version for Model Context Protocol Connections: **0.261.001**

Model Context Protocol connections work in both directions. Outbound, your agents reach MCP servers using presets and admin-curated catalogs rather than hand-typed configuration, and you can verify a connection before saving it. Inbound, approved MCP clients can reach SimpleChat conversations, documents, prompts, tags, and workflow tools under admin governance.

## User Side

SimpleChat can now act as a governed MCP server for approved external clients, and outbound MCP actions gained presets, preconfigured catalogs, and a Test Connection button.

## Admin Side

MCP runs in two directions and they are configured in different places.

**Outbound** — SimpleChat calling someone else's MCP server — is an action type configured under Agents. Presets and a server-side preconfiguration catalog let an admin publish a known-good destination instead of asking every user to type a URL, and Test Connection verifies a destination before users depend on it. Governance policy decides who can reach which destination.

**Inbound** — SimpleChat acting as an MCP server so a Copilot-style client can reach your conversations, documents, prompts, tags, and workflow tools — has its own **Inbound MCP** tab, which only appears when MCP is enabled for the tenant. It is off until an admin turns on the inbound server, and it is not an open door: access is gated on an Entra scope (`DelegatedMcpServerAccess` by default), on app and user roles (`InboundMCPUserAccess` and `InboundMCPAppAccess` by default), and optionally on explicit allow-lists of client application IDs and tenant IDs. External tenants are refused unless deliberately allowed. The server publishes OAuth protected-resource metadata under `/.well-known/oauth-protected-resource` so compliant clients can discover how to authenticate against the `/api/mcp` endpoint.

Governance carries a dedicated Inbound MCP Source Governance section, so a request arriving over MCP can be held to different rules than the same user working in the browser.

## Why It Matters

This matters because it lets SimpleChat participate in the wider tool ecosystem your organization already uses, without every team hand-rolling its own integration.

## How to Try It

1. Open Personal Workspace and go to the Actions section, or open Agents if you are wiring an agent directly.
2. Create a new action and choose the MCP action type.
3. Pick a preset or an admin-preconfigured server entry instead of typing the connection by hand.
4. Fill in any remaining destination and authentication details the preset does not cover.
5. Click Test Connection and confirm the server responds before saving.
6. Attach the saved action to an agent so it can call those MCP tools during a conversation.
7. Open Chat, select that agent, and ask something that requires the connected MCP tool.

## Notes

- The Model Context Protocol Connections guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_mcp_platform_1.png`, `release_260_mcp_platform_2.png`, `release_260_mcp_platform_3.png` from the app Latest Features catalog.
