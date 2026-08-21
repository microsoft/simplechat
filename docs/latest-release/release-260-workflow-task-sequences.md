---
layout: latest-release-feature
title: "Multi-Step Workflows With Alert Rules"
description: "Workflows can now run an ordered sequence of tasks, each with its own model, agent, and documents, and can notify you through configurable alert rules instead of a single priority setting."
section: "Latest Release"
---

Current release version for Multi-Step Workflows With Alert Rules: **0.260.001**

The workflow builder is now a stepped experience covering General, Trigger, Tasks, Reliability, and Review. Each task chooses its own model or agent, sets its own document action and targets, and passes context forward to the next task. Alerts moved to a rules engine supporting run status, text matches, regular expressions, File Sync results, and AI-judged conditions across five severity levels. Runs can also be cancelled while in flight.

## User Side

Workflows can now run an ordered sequence of tasks, each with its own model, agent, and documents, and can notify you through configurable alert rules instead of a single priority setting.

## Admin Side

Admins decide whether Multi-Step Workflows With Alert Rules is available in your environment. If you cannot find Open Personal Workspace, Open Group Workspaces, and Open Workflow Activity, ask whether the related settings, governance policy, or workspace access has been enabled for your account.

## Screenshot Placeholder

The v0.260.001 app catalog currently provides branded placeholder captures for Multi-Step Workflows With Alert Rules. Replace these copied documentation images when final screenshots are ready:

- `/images/latest-release/release_260_workflow_task_sequences_1.png`
- `/images/latest-release/release_260_workflow_task_sequences_2.png`
- `/images/latest-release/release_260_workflow_task_sequences_3.png`

## Why It Matters

This matters because real work is rarely one prompt, and chaining steps with targeted notifications turns a workflow into something you can trust to run unattended.

## How to Try It

1. Open Personal Workspace and go to the Workflows section, or open Group Workspaces for a shared workflow.
2. Create a workflow and step through General and Trigger to name it and choose when it runs.
3. In the Tasks step, add your first instruction task and pick the model or agent that should run it.
4. Set that task document action and choose the specific documents it should operate on.
5. Add a second task and reference what the first task produced so the steps build on each other.
6. In the Reliability step, set retry and failure handling for tasks that call external systems.
7. In the Review step, add alert rules such as notify on failure or notify when the output matches a phrase, then save and run it.

## Notes

- The Multi-Step Workflows With Alert Rules guide belongs to the SimpleChat 0.260.001 latest-feature set.
- The gallery for this page uses `release_260_workflow_task_sequences_1.png`, `release_260_workflow_task_sequences_2.png`, `release_260_workflow_task_sequences_3.png` from the app Latest Features catalog.
