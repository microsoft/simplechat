---
layout: latest-release-feature
title: "Agent Knowledge and Actions"
description: "How assigned knowledge, reusable identities, Databricks actions, and MCP actions expand agent governance"
section: "Latest Release"
---

Agent Knowledge and Actions combines governed agent retrieval with expanded enterprise action types and reusable identity workflows.

## User Side

Workspace users can review Agents and Actions from Personal Workspace, chat with configured agents, inspect enabled tools, and use reusable identities where actions need credentials.

## Admin Side

Admins and workspace owners govern which agents, actions, identities, and Microsoft Graph mail behaviors are available before assigning them to users. The visual tour includes Assigned Knowledge setup plus user-facing Agents and Actions views.

## Microsoft Graph Mail Actions

Microsoft Graph actions now include a **Send mail** capability. Action owners can configure whether the action creates a manual draft, prepares a delayed-delivery draft, or sends mail automatically from the signed-in user's mailbox.

<img src="{{ '/images/feature-msgraph-mail-delivery.png' | relative_url }}" alt="Annotated Microsoft Graph action configuration showing Send mail and Mail Delivery controls." style="width: 70%;" />

## Why It Matters

Agent creators can make assistants more predictable while admins keep cleaner credential and action governance.

## How to Try It

1. Open an agent create or edit modal and review the **Knowledge** step.
2. Assign workspaces, documents, tags, and optional web sources that should anchor the agent.
3. Review workspace or global identities before configuring actions that need credentials.
4. Use Databricks, MCP, or Microsoft Graph action types when approved external tools should be available to agents.
5. For Microsoft Graph mail actions, enable **Send mail** and choose the default **Mail Delivery** behavior before assigning the action to an agent.

## Notes

- Assigned Knowledge is stored with the agent configuration and applied when the agent is selected.
- User-added workspace context can be allowed or restricted based on agent policy.
- Databricks, MCP, and Microsoft Graph actions should be reviewed with the same care as other tool integrations.
