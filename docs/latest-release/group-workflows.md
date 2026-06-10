---
layout: latest-release-feature
title: "Group Workflow Support"
description: "How group workspaces can create, schedule, run, and monitor shared workflows"
section: "Latest Release"
---

Current release version: **0.241.183**

Group Workflow Support extends the workflow system into group workspaces so shared teams can create, schedule, run, and monitor repeatable document work against group-owned content.

## User Side

Group members with the right role can open Group Workspaces, select an active group, and use group workflows for shared document analysis. Group workflows can use group agents, merged global agents, group model endpoints, group File Sync sources, manual runs, interval schedules, and changed-file Analyze targets.

## Admin Side

Admins enable group workflows from the workspace workflow settings. They can optionally require group assignment before a group can use workflows and can require group Owners to manage group agents, actions, and workflows when stricter governance is needed.

## Screenshot Placeholder

Add an admin screenshot showing **Enable Group Workflows**, group assignment controls, and owner-only management controls in Admin Settings.

Add a user screenshot showing a Group Workspaces view with the Group Workflows tab, a workflow list, and a New Group Workflow button.

## Why It Matters

Recurring document work often belongs to a team workspace, not one person's personal workspace.

## How to Try It

1. Open **Admin Settings > Workspaces** and enable group workflows.
2. Optionally require group assignment and select which groups can use the feature.
3. Open Group Workspaces and select an active group.
4. Create a workflow, choose a runner, configure the prompt and document action, then run it manually or on a schedule.

## Notes

- Group workflow definitions and run history are scoped by group.
- Group workflows accept only group-scoped File Sync sources for the active group.
- Changed synced files can become dynamic Analyze targets when workflow File Sync configuration allows it.