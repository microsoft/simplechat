---
layout: latest-release-feature
title: "Analyze and Compare"
description: "How chat and workspace document actions support full-document review and side-by-side comparison"
section: "Latest Release"
---

Current release version: **0.241.183**

Analyze and Compare give users deliberate document-action modes beyond regular workspace search.

## User Side

Users can open the Workspaces tool in Chat and choose **Analyze** when a prompt should review selected documents end to end. They can choose **Compare** when one source document should be compared against one or more target documents. Workspace document actions and workflow configuration reuse the same document-action concepts when a repeated review is needed.

## Admin Side

Admins enable the underlying workspace, enhanced citation, and workflow capabilities that determine where document actions appear. Analyze and Compare respect the user's current workspace access and document selection rather than exposing documents outside the active scope.

## Screenshot Placeholder

Add a user screenshot showing the Chat Workspaces tool with Search, Analyze, and Compare available as document action modes.

Add a second screenshot showing a Compare setup with one source document and one or more target documents selected.

## Why It Matters

Some questions need exhaustive review or side-by-side comparison instead of top-search snippets.

## How to Try It

1. Open Chat and expand the Workspaces tool.
2. Select a workspace scope and choose one or more documents.
3. Choose **Analyze** for full-document review or **Compare** for source-versus-target comparison.
4. Send a prompt and review the progress, coverage, citations, and final answer.

## Notes

- Interactive chat analysis targets a deliberately bounded set of selected documents.
- Workflow Analyze runs can cover larger repeated batches and changed synced documents.
- Compare treats one selected document as the source baseline and compares selected target documents against it.