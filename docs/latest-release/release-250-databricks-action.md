---
layout: latest-release-feature
title: "Databricks Action"
description: "Users with access can use approved Databricks actions to run governed read-only SQL against Azure Commercial Databricks workspaces."
section: "Latest Release"
---

Current release version: **0.250.001**

The Databricks action connects to Databricks SQL Statement Execution APIs with configured warehouses, catalogs, schemas, identities, and limits. Admins may gate access by user, group, or workspace.

## User Side

Users with access can use approved Databricks actions to run governed read-only SQL against Azure Commercial Databricks workspaces.

## Admin Side

Availability may depend on tenant settings, governance policies, workspace scope, action configuration, or admin-managed identities. If you do not see this capability, contact your SimpleChat admin.

## Screenshot Placeholder

Replace `/images/latest-release/release_250_databricks_action.png` with a screenshot showing databricks action in the app.

## Why It Matters

This matters because analytics data can be queried from SimpleChat without giving every user direct database tooling.

## How to Try It

1. Use a Databricks-enabled action or agent when your admin has made it available.
2. Ask your admin for access if the action is not available in your workspace.
3. Expect Databricks actions to be read-only and governed by configured limits.

## Notes

- This guide is part of the SimpleChat 0.250.001 latest-feature set.
- Screenshot filenames are placeholders until final captures are added.
