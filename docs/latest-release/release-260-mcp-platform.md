---
layout: latest-release-feature
title: "Model Context Protocol Connections"
description: "SimpleChat can now act as a governed MCP server for approved external clients, and outbound MCP actions gained presets, preconfigured catalogs, and a Test Connection button."
section: "Latest Release"
---

Current release version for Model Context Protocol Connections: **0.260.001**

Model Context Protocol connections work in both directions. Outbound, your agents reach MCP servers using presets and admin-curated catalogs rather than hand-typed configuration, and you can verify a connection before saving it. Inbound, approved MCP clients can reach SimpleChat conversations, documents, prompts, tags, and workflow tools under admin governance.

## User Side

SimpleChat can now act as a governed MCP server for approved external clients, and outbound MCP actions gained presets, preconfigured catalogs, and a Test Connection button.

## Admin Side

Admins decide whether Model Context Protocol Connections is available in your environment. If you cannot find Open Personal Workspace and Open Agents, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Screenshot Placeholder

The v0.260.001 app catalog currently provides branded placeholder captures for Model Context Protocol Connections. Replace these copied documentation images when final screenshots are ready:

- `/images/latest-release/release_260_mcp_platform_1.png`
- `/images/latest-release/release_260_mcp_platform_2.png`
- `/images/latest-release/release_260_mcp_platform_3.png`

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

- The Model Context Protocol Connections guide belongs to the SimpleChat 0.260.001 latest-feature set.
- The gallery for this page uses `release_260_mcp_platform_1.png`, `release_260_mcp_platform_2.png`, `release_260_mcp_platform_3.png` from the app Latest Features catalog.
