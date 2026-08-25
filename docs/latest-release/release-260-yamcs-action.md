---
layout: latest-release-feature
title: "Yamcs Mission Control Integration"
description: "A new Yamcs action type connects agents to Yamcs mission control servers with eleven read-only tools covering telemetry, parameters, events, packets, alarms, and archive queries."
section: "Latest Release"
---

Current release version for Yamcs Mission Control Integration: **0.261.001**

The Yamcs action is strictly read-only by design, so an agent can investigate mission data but cannot command a spacecraft. Archive SQL access is opt-in and enforced as SELECT-only. Several authentication methods are supported, and a dedicated configuration panel plus a Test Connection button make setup verifiable before you rely on it.

## User Side

A new Yamcs action type connects agents to Yamcs mission control servers with eleven read-only tools covering telemetry, parameters, events, packets, alarms, and archive queries.

## Admin Side

Admins decide whether Yamcs Mission Control Integration is available in your environment. If you cannot find Open Personal Workspace and Open Agents, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Why It Matters

This matters because mission operators can ask plain-language questions about telemetry and alarms instead of hand-writing queries against the archive.

## How to Try It

1. Open Personal Workspace and go to the Actions section.
2. Create a new action and choose the Yamcs action type.
3. Enter your Yamcs server address and pick the authentication method your instance uses.
4. Leave archive SQL disabled unless you specifically need archive queries, then enable it deliberately.
5. Click Test Connection to confirm SimpleChat can reach the server and read an instance.
6. Attach the saved action to an agent, then open Agents to confirm the eleven Yamcs tools are listed.
7. Open Chat, select that agent, and ask about recent telemetry, parameters, events, or active alarms.

## Notes

- The Yamcs Mission Control Integration guide belongs to the SimpleChat 0.261.001 latest-feature set.
- The gallery for this page uses `release_260_yamcs_action_1.png`, `release_260_yamcs_action_2.png`, `release_260_yamcs_action_3.png` from the app Latest Features catalog.
