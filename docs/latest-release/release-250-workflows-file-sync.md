---
layout: latest-release-feature
title: "Workflows and File Sync Automation"
description: "How personal and group workflows can refresh File Sync sources and track per-document work"
section: "Latest Release"
---

Current release version: **0.250.001**

Personal and group workflows gained File Sync triggers, monitor-for-changes mode, per-document Analyze runs, resume-failed batches, activity views, and generated Office exports.

## User Side

Users can run personal or group workflows, refresh selected File Sync sources before a run, monitor changed files, and resume failed document items from a previous Analyze batch.

## Admin Side

Admins control personal workflow enablement, WorkflowUser role enforcement, group workflow enablement, group assignment, File Sync source types, connector identities, and workspace scope gates.

## Screenshot Placeholder

Replace `/images/latest-release/release_250_workflows_file_sync.png` with a screenshot of workflow lists, File Sync before-run controls, monitor mode, and workflow activity tracking.

## Why It Matters

Repeatable document work can run from shared workspace sources instead of depending on one person to refresh files and restart analysis manually.

## How to Try It

1. Open **Personal Workspace > Workflows** or **Group Workspaces > Workflows**.
2. Create or edit a workflow and enable File Sync Before Run.
3. Review run history and activity after execution.

## Notes

- Group workflows use group-specific authorization and assignment gating.
