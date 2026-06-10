---
layout: latest-release-feature
title: "Workflow Automation"
description: "How workflows can run after File Sync changes and resume failed analysis batches"
section: "Latest Release"
---

Workflow Automation connects personal workflows to File Sync sources, access governance, dynamic document targeting, and batch resume behavior.

## User Side

Workflow users can create and monitor personal workflows, review runs, trigger File Sync before a workflow starts, and target changed synced files for Analyze steps.

## Admin Side

Admins enable personal workflows, optionally require the `WorkflowUser` Enterprise App role, and control File Sync before-run automation. The screenshot gallery pairs those admin settings with the user workflow list and editor controls.

## Why It Matters

Repeatable document analysis can run when source files change rather than waiting for someone to manually refresh and restart every item.

## How to Try It

1. Open Personal Workspace and review workflow availability in your environment.
2. Configure a workflow to run selected File Sync sources before the workflow prompt executes.
3. Use monitor-for-changes mode when the workflow should run only after synced files change.
4. Resume failed document items from workflow run history when a batch analysis partially fails.

## Notes

- Admins can require a dedicated WorkflowUser Enterprise App role.
- Analyze workflows can target changed synced documents dynamically.
- Per-document run tracking makes batch failures easier to retry without rerunning everything.
