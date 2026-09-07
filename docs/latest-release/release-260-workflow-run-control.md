---
layout: latest-release-feature
title: Stop a Running Workflow, and Give Each Task Its Own Model
description: You can cancel a workflow while it is still running, and every task in a workflow can use its own model or agent and its own documents.
section: Latest Release
generated_from_catalog: true
---

Current release version for Stop a Running Workflow, and Give Each Task Its Own Model: **0.261.001**

An active run can be cancelled from the workspace row, from run history, or from the workflow activity view. Cancellation stops further File Sync, document, model, agent, artifact, and notification work once any in-flight request returns, and a cancelled scheduled workflow goes back to idle and waits for its next scheduled run instead of restarting immediately. Separately, each task can either inherit the workflow Default Runner or pick its own model or agent, and each task now owns its own document action, document targets, and selected documents.

## Why It Matters

This matters because a long workflow that is clearly going wrong no longer has to run to the end, and a multi-step workflow can use a fast model for early steps and a stronger one only where it counts.

## How to Try It

1. Open Personal Workspace and go to the Workflows section.
2. Open a workflow and step through to Tasks in the builder.
3. On a task, change Runner from Workflow default to a specific Direct Model or Agent.
4. Set that task its own document action and pick the documents it should use.
5. Add a second task and confirm its document fields start clean rather than inheriting the first one.
6. Save the workflow and start a run.
7. While the run is active, select Cancel from the workflow row or from run history and confirm it stops.

## Where to Find It

- **Open Personal Workspace** &mdash; Configure per-task runners and documents, then cancel an active run.
