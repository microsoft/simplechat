---
layout: latest-release-feature
title: "Workflow Automation"
description: "How personal and group workflows can run after File Sync changes and resume failed analysis batches"
section: "Latest Release"
---

Current release version: **0.241.183**

Workflow Automation connects personal and group workflows to File Sync sources, access governance, dynamic document targeting, and batch resume behavior.

## User Side

Workflow users can create and monitor personal workflows from Personal Workspace and group workflows from Group Workspaces when the feature is enabled for their group. Workflows can trigger File Sync before a run starts and can target changed synced files for Analyze steps.

## Admin Side

Admins enable personal workflows, optionally require the `WorkflowUser` Enterprise App role, enable group workflows, assign group workflow access to selected groups, and control File Sync before-run automation. The screenshot gallery pairs those admin settings with the user workflow list and editor controls.

## Screenshot Placeholder

Add a screenshot showing the group workflow enablement controls beside personal workflow controls in Admin Settings.

Add a group-side screenshot showing a group workflow list with group File Sync sources available in the workflow editor.

## Why It Matters

Repeatable document analysis can run when source files change rather than waiting for someone to manually refresh and restart every item.

## How to Try It

1. Open Personal Workspace or Group Workspaces and review workflow availability in your environment.
2. Configure a workflow to run selected personal or group File Sync sources before the workflow prompt executes.
3. Use monitor-for-changes mode when the workflow should run only after synced files change.
4. Resume failed document items from workflow run history when a batch analysis partially fails.

## Notes

- Admins can require a dedicated WorkflowUser Enterprise App role.
- Admins can enable group workflows and optionally assign the feature to selected groups.
- Analyze workflows can target changed synced documents dynamically.
- Per-document run tracking makes batch failures easier to retry without rerunning everything.
