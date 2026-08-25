---
layout: latest-release-feature
title: MCP Server Governance & Outbound Action Controls
description: Admins can govern inbound MCP server exposure and outbound MCP action destinations before users connect external tools.
section: Latest Release
generated_from_catalog: true
---

Current release version for MCP Server Governance & Outbound Action Controls: **0.261.001**

SimpleChat can operate as a governed inbound MCP server exposing conversations, documents, prompts, tags, and workflow tools to MCP clients. Outbound MCP actions add presets, server-side preconfiguration catalogs, destination governance, Test Connection support, observability controls, Application Insights KQL starters, and standards-compliant tool argument normalization for end users invoking MCP actions.

## Why It Matters

This matters because admins can unlock MCP interoperability while controlling destinations, observability, and supported tool surfaces.

## How to Try It

1. Open Admin Settings > Agents and review outbound MCP action configuration and available presets.
2. Open Admin Settings > Inbound MCP to enable the inbound server and scope it with required roles, scope, and client or tenant allow-lists.
3. Open Admin Settings > MCP Governance and apply destination or capability policies before making MCP actions broadly available.
4. Use Test Connection on configured MCP actions so users see reliable action availability.
5. Tell users which MCP clients or outbound destinations are approved before enabling the capability tenant-wide.

## Where to Find It

- **Open Agents** &mdash; Configure outbound MCP action presets and server-side catalogs.
- **Open Inbound MCP** &mdash; Enable and scope the inbound MCP server exposed to MCP clients.
- **Open MCP Governance** &mdash; Control MCP destination and capability access.
- **Open Logging** &mdash; Review observability and KQL starter guidance for MCP operations.
