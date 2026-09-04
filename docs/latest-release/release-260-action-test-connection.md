---
layout: latest-release-feature
title: "Test Connection Before You Save an Action"
description: "Test Connection is now available across twelve action types, verifying credentials and reachability without making you re-enter stored secrets."
section: "Latest Release"
---

Current release version for Test Connection Before You Save an Action: **0.261.001**

OpenAPI, Azure Maps, Blob Storage, Databricks, Log Analytics, MCP, Snowflake, Tableau, RocksDB, Yamcs, SQL, and Cosmos DB actions all support Test Connection. The test resolves secrets stored in Key Vault on the server side, so you never retype a credential to check it. A successful test reports useful detail about what it reached, and a failure names the specific cause rather than a generic error.

## User Side

Test Connection is now available across twelve action types, verifying credentials and reachability without making you re-enter stored secrets.

## Admin Side

Admins decide whether Test Connection Before You Save an Action is available in your environment. If you cannot find Open Personal Workspace and Open Agents, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Why It Matters

This matters because a broken action used to surface as a confusing failure mid-conversation, and now you find out at setup time with a message that tells you what to fix.

## How to Try It

1. Open Personal Workspace and go to the Actions section.
2. Create a new action or open an existing one that is not behaving as expected.
3. Fill in the connection details for the action type you are configuring.
4. Click Test Connection and wait for the result rather than saving immediately.
5. On success, read the returned detail to confirm you reached the intended system and scope.
6. On failure, read the named cause and correct just that field, then test again.
7. Save the action once the test passes, then attach it to an agent.

## Notes

- The Test Connection Before You Save an Action guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_action_test_connection_1.png`, `release_260_action_test_connection_2.png`, `release_260_action_test_connection_3.png` from the app Latest Features catalog.
