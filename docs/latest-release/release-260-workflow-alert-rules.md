---
layout: latest-release-feature
title: Workflow Alerts That Only Fire When They Should
description: Instead of notifying you on every run, a workflow now defines rules that describe why it should interrupt you, and a run that matches nothing stays completely silent.
section: Latest Release
generated_from_catalog: true
---

Current release version for Workflow Alerts That Only Fire When They Should: **0.261.001**

Conditions cover run status, task status, output text that contains, does not contain, or matches a regular expression, File Sync results, empty output, a signal raised by an agent, and a plain-English condition judged by a model such as "any certificate expires within 14 days". Each rule can watch the final output, any task output, or one specific task. Severity runs info, low, medium, high, and critical: info and low land quietly in the notification bell while medium and above open the pop-up. When several rules match, the highest severity wins and the alert lists every matched rule under Triggered by.

## Why It Matters

This matters because a workflow that notifies you on every single run gets ignored, which defeats the point of running it unattended.

## How to Try It

1. Open Personal Workspace and go to the Workflows section.
2. Open a workflow and step through the builder to Review.
3. Switch the alert mode from the simple setting to rules.
4. Add a rule and choose a condition, such as output text matching a phrase you care about.
5. Set the severity, remembering that info and low stay in the notification bell.
6. Save, then run the workflow and confirm a non-matching run stays silent.
7. Trigger a matching run and check the Triggered by section on the alert.

## Where to Find It

- **Open Personal Workspace** &mdash; Add conditional alert rules in the workflow builder Review step.
